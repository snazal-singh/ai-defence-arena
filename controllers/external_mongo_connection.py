"""
External MongoDB Server Management (multi-server).

Lets a user attach one or more of their own externally-hosted MongoDB
servers (e.g. Atlas) to a specific knowledge container, as an additional
structured data source alongside (or instead of) data ingested from
uploaded JSON files. Each attached server is introspected once at
connect-time into a cached schema_catalog spanning every database/
collection on that server, so routing and query generation don't need to
re-sample the live server on every question.

Once attached, controllers/mongodb_db.py's schema/query-routing pipeline
treats these servers as additional entries in the combined schema shown to
the intent classifier, which picks a server_id + database_name alongside
its data_source decision (see query_intent_service.py).

By default, only publicly reachable Mongo servers (e.g. MongoDB Atlas) are
allowed -- "localhost" as the user's browser understands it is generally not
reachable from wherever this backend runs. Set ALLOW_LOCAL_MONGO=true (see
app/core/config.py) to additionally allow localhost/private/loopback hosts,
for dev or self-hosted setups where this backend genuinely can reach them.
"""

import ipaddress
import logging
import re
import socket
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import pymongo
from cryptography.fernet import Fernet, InvalidToken

import time

from app.core.config import settings
from controllers import database

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_MS = 5000
_SOCKET_TIMEOUT_MS = 10000
_ALLOWED_SCHEMES = {"mongodb", "mongodb+srv"}
_SCHEMA_SAMPLE_SIZE = 3      # documents sampled per collection to infer field types
_MAX_DATABASES = 20          # max databases introspected in a full-server scan
_MAX_COLLECTIONS_PER_DB = 30 # max collections introspected per database
_MAX_FIELDS_PER_COLLECTION = 50  # max fields kept per collection in the schema catalog
# Databases every Mongo deployment has that are never user data.
_SYSTEM_DATABASES = {"admin", "local", "config"}

_MAX_CONSECUTIVE_FAILURES = 3
_COOLDOWN_SECONDS = 60


def _mask_uri_credentials(uri: str) -> str:
    """Mask credentials in MongoDB connection URI for safe logging and error reporting."""
    if not uri:
        return ""
    # Matches scheme://username:password@host and replaces password with ***
    return re.sub(r"(mongodb(?:\+srv)?://)([^:]+):(.*)@([a-zA-Z0-9._-]+)", r"\1\2:***@\4", uri)


class MongoConnectionRateLimiter:
    """Thread-safe rate limiter and circuit breaker for MongoDB connection attempts.

    Tracks consecutive failed connection attempts per session/host. If consecutive
    failures reach _MAX_CONSECUTIVE_FAILURES, connection attempts are locked out
    for _COOLDOWN_SECONDS to prevent thread starvation and resource exhaustion.
    """

    def __init__(self, max_failures: int = _MAX_CONSECUTIVE_FAILURES, cooldown_seconds: int = _COOLDOWN_SECONDS):
        self.max_failures = max_failures
        self.cooldown_seconds = cooldown_seconds
        self._failures: Dict[str, Tuple[int, float]] = {}  # key -> (failure_count, cooldown_until_timestamp)
        self._lock = threading.Lock()

    def _make_key(self, user_session: str, connection_uri: str) -> str:
        try:
            parsed = urlparse(connection_uri)
            host = parsed.hostname or "unknown_host"
        except Exception:
            host = "unknown_host"
        return f"{user_session}:{host}"

    def check_rate_limit(self, user_session: str, connection_uri: str) -> Tuple[bool, str]:
        """Check if connection attempt is allowed or locked out due to active cooldown."""
        key = self._make_key(user_session, connection_uri)
        with self._lock:
            now = time.time()
            if key in self._failures:
                count, cooldown_until = self._failures[key]
                if now < cooldown_until:
                    remaining = int(cooldown_until - now) + 1
                    masked_uri = _mask_uri_credentials(connection_uri)
                    logger.warning(
                        f"MongoDB connection request throttled for session '{user_session}' "
                        f"({masked_uri}). Cooldown active ({remaining}s remaining)."
                    )
                    return False, (
                        f"Too many consecutive connection failures for this MongoDB server. "
                        f"Connection attempt locked out to protect resources. Please wait {remaining} seconds before retrying."
                    )
                elif now >= cooldown_until and count >= self.max_failures:
                    # Cooldown expired, reset state to allow a fresh retry
                    self._failures.pop(key, None)
        return True, ""

    def record_failure(self, user_session: str, connection_uri: str, error_msg: str) -> None:
        """Record a connection failure and activate cooldown if max failures reached."""
        key = self._make_key(user_session, connection_uri)
        masked_uri = _mask_uri_credentials(connection_uri)
        safe_error = _mask_uri_credentials(error_msg)
        with self._lock:
            now = time.time()
            count, _ = self._failures.get(key, (0, 0.0))
            count += 1
            cooldown_until = 0.0
            if count >= self.max_failures:
                cooldown_until = now + self.cooldown_seconds
                logger.warning(
                    f"MongoDB connection rate limit triggered for session '{user_session}' ({masked_uri}). "
                    f"{count} consecutive failures recorded. Locked out for {self.cooldown_seconds} seconds."
                )
            else:
                logger.info(
                    f"Recorded Mongo connection failure ({count}/{self.max_failures}) for session '{user_session}' ({masked_uri}): {safe_error}"
                )
            self._failures[key] = (count, cooldown_until)

    def record_success(self, user_session: str, connection_uri: str) -> None:
        """Reset failure tracking on successful connection."""
        key = self._make_key(user_session, connection_uri)
        with self._lock:
            if key in self._failures:
                self._failures.pop(key, None)
                logger.info(f"MongoDB connection succeeded for session '{user_session}'; reset failure state.")

    def reset_all(self) -> None:
        """Reset all rate limiter state (useful for testing)."""
        with self._lock:
            self._failures.clear()


_mongo_rate_limiter = MongoConnectionRateLimiter()



# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------

def _get_fernet() -> Fernet:
    key = getattr(settings, "EXTERNAL_MONGO_ENCRYPTION_KEY", "")
    if not key:
        # Fall back to a deterministic key derived from SECRET_KEY to prevent unhandled RuntimeError in dev/test
        import base64
        import hashlib
        secret = getattr(settings, "SECRET_KEY", "sachet-default-mongo-encryption-key")
        key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest()).decode()
    return Fernet(key.encode() if isinstance(key, str) else key)


def _encrypt(value: str) -> str:
    try:
        return _get_fernet().encrypt(value.encode()).decode()
    except Exception as e:
        logger.error(f"Failed to encrypt connection URI: {e}")
        raise RuntimeError(f"Encryption failed: {e}") from e


def _decrypt(token: str) -> str:
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        logger.error(f"Stored external Mongo connection string could not be decrypted: {e}")
        raise RuntimeError("Stored external Mongo connection string could not be decrypted") from e
    except Exception as e:
        logger.error(f"Unexpected error decrypting external Mongo connection URI: {e}")
        raise RuntimeError(f"Decryption failed: {e}") from e


# ---------------------------------------------------------------------------
# SSRF guard: a user-supplied host is, by construction, attacker-controlled
# input to an outbound connection this backend makes. Block loopback/private/
# link-local/reserved ranges so this feature can't be used to reach internal
# infrastructure the backend can see but the user shouldn't be able to probe.
# ---------------------------------------------------------------------------

def _validate_host_is_public(hostname: str) -> Tuple[bool, str]:
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        return False, f"Could not resolve host '{hostname}': {e}"

    for _family, _type, _proto, _canon, sockaddr in addrinfo:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            if settings.ALLOW_LOCAL_MONGO:
                continue
            return False, (
                f"Host '{hostname}' resolves to a non-public address ({ip_str}); "
                "external connections must point at a publicly reachable Mongo "
                "server (e.g. MongoDB Atlas). Locally-hosted Mongo servers on "
                "your own machine/network are not reachable from this backend. "
                "Set ALLOW_LOCAL_MONGO=true if this backend can actually reach "
                "that address (e.g. local dev/self-hosted setups)."
            )
    return True, ""


def _points_to_own_backend_mongo(hostname: str, port: Optional[int]) -> bool:
    """True if hostname:port is the same server this app itself uses
    internally (settings.MONGO_URL) -- every knowledge container's own
    private data (db_<session> databases) lives there, so treating the
    whole server as one "external" source would leak one container's data
    into another's. Compares string hostnames, standard aliases, and
    resolved IP sets to prevent bypasses."""
    if not hostname:
        return False
    try:
        own = urlparse(settings.MONGO_URL)
    except Exception:
        return False
    own_port = own.port or 27017
    target_port = port or 27017
    if own_port != target_port:
        return False

    own_host = (own.hostname or "").lower()
    target_host = hostname.lower()
    if own_host in ("localhost", "127.0.0.1", "::1") and target_host in ("localhost", "127.0.0.1", "::1"):
        return True
    if own_host == target_host:
        return True

    # Compare resolved IP addresses as an additional check against DNS aliases
    try:
        own_ips = {sa[0] for _, _, _, _, sa in socket.getaddrinfo(own_host, None)}
        target_ips = {sa[0] for _, _, _, _, sa in socket.getaddrinfo(target_host, None)}
        if own_ips and target_ips and bool(own_ips & target_ips):
            return True
    except Exception:
        pass

    return False


def validate_connection_uri(connection_uri: str) -> Tuple[bool, str]:
    """Structural, format, and SSRF validation before attempting connection."""
    if not connection_uri or not isinstance(connection_uri, str):
        return False, "Connection URI is required"

    if len(connection_uri) > 2048:
        return False, "Connection URI exceeds maximum length of 2048 characters"

    try:
        parsed = urlparse(connection_uri)
    except Exception as e:
        return False, f"Malformed connection URI: {e}"

    if parsed.scheme not in _ALLOWED_SCHEMES:
        return False, f"Unsupported scheme '{parsed.scheme}'; expected mongodb:// or mongodb+srv://"

    if not parsed.hostname:
        return False, "Connection URI must include a host"

    # Validate database name in path if provided
    uri_db = (parsed.path or "").lstrip("/")
    if uri_db:
        if uri_db in _SYSTEM_DATABASES:
            return False, f"Database '{uri_db}' is a system database and cannot be used as an external source"
        if not re.match(r"^[a-zA-Z0-9_\-\.]+$", uri_db):
            return False, "Database name contains invalid characters. Only alphanumeric, _, -, and . are permitted"

    if settings.ALLOW_LOCAL_MONGO:
        return True, ""

    # Always block common loopback names explicitly
    if parsed.hostname.lower() in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
        return False, f"Host '{parsed.hostname}' is not reachable from this backend (local/loopback addresses disallowed)"

    # SSRF IP address validation
    ok, msg = _validate_host_is_public(parsed.hostname)
    if not ok and parsed.scheme == "mongodb":
        return False, msg
    elif not ok and parsed.scheme == "mongodb+srv":
        # For mongodb+srv, if host resolved to private IP, reject it
        if "non-public address" in msg:
            return False, msg

    return True, ""


# ---------------------------------------------------------------------------
# Schema catalog: introspect every user database/collection on the server,
# sampling _SCHEMA_SAMPLE_SIZE documents per collection to infer field types.
# Cached at attach-time rather than re-sampled on every query.
# ---------------------------------------------------------------------------

def infer_type_name(value: Any) -> str:
    """Infer string type name for a python value (used for schema introspection)."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


_infer_type_name = infer_type_name


def _describe_collections(
    db: pymongo.database.Database,
    collection_names: List[str],
    max_collections: int = _MAX_COLLECTIONS_PER_DB,
) -> Dict[str, Dict[str, str]]:
    """Introspect up to `max_collections` collections in `db`, sampling
    _SCHEMA_SAMPLE_SIZE documents each to infer field types. Caps fields
    per collection at _MAX_FIELDS_PER_COLLECTION so the resulting schema
    text stays a reasonable size regardless of document width."""
    db_catalog: Dict[str, Dict[str, str]] = {}
    for coll_name in collection_names[:max_collections]:
        fields: Dict[str, str] = {}
        for doc in db[coll_name].find({}, limit=_SCHEMA_SAMPLE_SIZE):
            for key, value in doc.items():
                if key == "_id":
                    continue
                if key not in fields:
                    fields[key] = _infer_type_name(value)
                if len(fields) >= _MAX_FIELDS_PER_COLLECTION:
                    break
        db_catalog[coll_name] = fields
    skipped = len(collection_names) - max_collections
    if skipped > 0:
        logger.warning(
            f"_describe_collections: capped at {max_collections} collections "
            f"({skipped} skipped) for db '{db.name}'"
        )
    return db_catalog


def build_schema_catalog(client: pymongo.MongoClient) -> Dict[str, Dict[str, Dict[str, str]]]:
    """{database_name: {collection_name: {field_name: type}}} across every
    non-system database/collection this connection can see.

    Used as a fallback for connection URIs with no database segment in the
    path (nothing for get_default_database() to resolve) -- when the URI
    does name a database, build_scoped_schema_catalog is used instead so a
    server isn't fully scanned when the user already told us which database
    they want.

    Capped at _MAX_DATABASES databases to prevent hangs on large Atlas
    clusters with hundreds of databases."""
    catalog: Dict[str, Dict[str, Dict[str, str]]] = {}
    all_db_names = [
        name for name in client.list_database_names()
        if name not in _SYSTEM_DATABASES
    ]
    if len(all_db_names) > _MAX_DATABASES:
        logger.warning(
            f"build_schema_catalog: server has {len(all_db_names)} user databases; "
            f"introspecting only the first {_MAX_DATABASES}."
        )
    for db_name in all_db_names[:_MAX_DATABASES]:
        db = client[db_name]
        db_catalog = _describe_collections(db, db.list_collection_names())
        if db_catalog:
            catalog[db_name] = db_catalog
    return catalog


def get_default_database_name(client: pymongo.MongoClient) -> Optional[str]:
    """The database named in the connection URI's path segment
    (e.g. '...mongodb.net/mydb'), if any. None for a URI with no database
    segment, in which case every database on the server is in play."""
    try:
        return client.get_default_database().name
    except pymongo.errors.ConfigurationError:
        return None


def build_scoped_schema_catalog(
    client: pymongo.MongoClient, database_name: str
) -> Dict[str, Dict[str, Dict[str, str]]]:
    """Same shape as build_schema_catalog, but introspects only the one
    database named in the connection URI instead of scanning the whole
    server. Still caps at _MAX_COLLECTIONS_PER_DB collections so a
    database with thousands of collections doesn't stall introspection."""
    db = client[database_name]
    db_catalog = _describe_collections(db, db.list_collection_names())
    return {database_name: db_catalog} if db_catalog else {}


def format_schema_catalog(server_id: str, catalog: Dict[str, Dict[str, Dict[str, str]]]) -> str:
    """Render a schema_catalog as 'Server: [ID] | DB: [Name] | Collection:
    [Name] | Fields: [Types]' lines for the intent-classification prompt."""
    lines = []
    for db_name, collections in catalog.items():
        for coll_name, fields in collections.items():
            field_desc = ", ".join(f"{k} ({v})" for k, v in fields.items()) if fields else "(empty)"
            lines.append(
                f"Server: {server_id} | DB: {db_name} | Collection: {coll_name} | Fields: {field_desc}"
            )
    return "\n".join(lines)


def format_server_schema(server: Dict[str, Any]) -> str:
    """Schema lines for one attached server, honoring a locked
    selected_collections list if the user picked one or more from the
    collection dropdown -- in that case only those collections' lines are
    shown, so query routing has no other collection on this server to
    (mis)pick."""
    catalog = server.get("schema_catalog", {})
    selected = server.get("selected_collections") or []
    database_name = server.get("database_name")

    if selected and database_name:
        db_catalog = catalog.get(database_name, {})
        lines = []
        missing = []
        for coll_name in selected:
            fields = db_catalog.get(coll_name)
            if fields is None:
                missing.append(coll_name)
                continue
            field_desc = ", ".join(f"{k} ({v})" for k, v in fields.items()) if fields else "(empty)"
            lines.append(
                f"Server: {server['server_id']} | DB: {database_name} | "
                f"Collection: {coll_name} | Fields: {field_desc}"
            )
        if missing:
            # One or more selected collections no longer in the cached
            # catalog (e.g. the server changed since attach) -- fall back to
            # the full catalog rather than silently dropping them.
            logger.warning(
                f"Selected collections {missing} not found in cached catalog "
                f"for server '{server.get('server_id')}'; showing full catalog"
            )
            return format_schema_catalog(server["server_id"], catalog)
        return "\n".join(lines)

    return format_schema_catalog(server["server_id"], catalog)


# ---------------------------------------------------------------------------
# Connect / verify / introspect
# ---------------------------------------------------------------------------

def test_connection(connection_uri: str) -> Tuple[bool, str, Optional[pymongo.MongoClient]]:
    """Validate + attempt to actually ping the server. Returns a live client
    on success (caller is responsible for closing it, or handing it off to
    build_schema_catalog and then closing it) so callers don't need to
    reconnect immediately after a successful test."""
    ok, msg = validate_connection_uri(connection_uri)
    if not ok:
        return False, msg, None

    try:
        client = pymongo.MongoClient(
            connection_uri,
            serverSelectionTimeoutMS=_CONNECT_TIMEOUT_MS,
            connectTimeoutMS=_CONNECT_TIMEOUT_MS,
            socketTimeoutMS=_SOCKET_TIMEOUT_MS,
        )
        client.admin.command("ping")
        return True, "Connection successful", client
    except Exception as e:
        safe_msg = _mask_uri_credentials(str(e))
        logger.warning(f"External Mongo connection test failed: {safe_msg}")
        return False, f"Could not connect: {safe_msg}", None


def attach_server(
    user_session: str, connection_uri: str, server_name: str,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Full attach flow: validate, connect, introspect the requested scope,
    encrypt the URI, and persist the server config for this session.

    The database is taken from the connection URI's own path (e.g.
    mongodb://host/mydb -> "mydb"); if the URI has no database segment, the
    whole server is introspected instead. The collection to actually query
    is chosen afterwards via select_collection(), once the caller has seen
    what's available (see list_collections_for_server).

    Returns (ok, message, server_config_without_encrypted_uri)."""
    # 1. Validate user_session
    if not user_session or not isinstance(user_session, str) or not user_session.strip():
        return False, "Invalid user session identifier", None

    # 2. Validate server_name
    if not server_name or not isinstance(server_name, str) or not server_name.strip():
        return False, "Server name cannot be empty", None
    clean_server_name = server_name.strip()
    if len(clean_server_name) > 100:
        return False, "Server name must be 100 characters or fewer", None
    if re.search(r"[\x00-\x1f\x7f<>]", clean_server_name):
        return False, "Server name contains invalid or unsafe characters", None

    # 3. Validate connection URI upfront before any connection attempt
    ok, msg = validate_connection_uri(connection_uri)
    if not ok:
        return False, msg, None

    # 3b. Check rate limit & failure cooldown lockouts
    allowed, limit_msg = _mongo_rate_limiter.check_rate_limit(user_session, connection_uri)
    if not allowed:
        return False, limit_msg, None

    parsed_host = urlparse(connection_uri)
    uri_database = (parsed_host.path or "").lstrip("/") or None

    # 4. Check backend Mongo isolation
    if _points_to_own_backend_mongo(parsed_host.hostname, parsed_host.port):
        if not uri_database:
            return False, (
                "This connection points at the same MongoDB server this app uses "
                "internally, which also hosts every other knowledge container's "
                "own private data. Introspecting the whole server would expose "
                "other containers' data here. Include a database name in the "
                "connection string (e.g. '...mongodb.net/mydb') to scope this to "
                "just your own external data."
            ), None
        if uri_database.startswith("db_"):
            return False, (
                f"'{uri_database}' is this app's own internal per-container "
                "database namespace (reserved for a knowledge container's own "
                "uploaded data), not an external data source — attaching it here "
                "would expose another container's private data. Point this at a "
                "different database instead."
            ), None

    # 5. Connect and ping
    ok, msg, client = test_connection(connection_uri)
    if not ok:
        _mongo_rate_limiter.record_failure(user_session, connection_uri, msg)
        return False, msg, None

    try:
        database_name = get_default_database_name(client)
        # If the connection URI names a specific database (the normal case
        # -- e.g. '...mongodb.net/mydb'), scope introspection to just that
        # database instead of scanning every database on the server. Falls
        # back to a full-server scan only for a URI with no database segment.
        catalog = (
            build_scoped_schema_catalog(client, database_name)
            if database_name
            else build_schema_catalog(client)
        )
    except Exception as e:
        safe_err = _mask_uri_credentials(str(e))
        _mongo_rate_limiter.record_failure(user_session, connection_uri, safe_err)
        logger.error(f"Schema introspection failed for new external Mongo server: {safe_err}")
        return False, f"Connected, but failed to introspect databases/collections: {safe_err}", None
    finally:
        client.close()

    if not catalog:
        scope = f" for database '{database_name}'" if database_name else ""
        no_cat_msg = f"Connected, but no databases/collections were found{scope} on this server"
        _mongo_rate_limiter.record_failure(user_session, connection_uri, no_cat_msg)
        return False, no_cat_msg, None

    _mongo_rate_limiter.record_success(user_session, connection_uri)

    try:
        encrypted_uri = _encrypt(connection_uri)
    except Exception as e:
        logger.error(f"Failed to encrypt connection URI during attach_server: {e}")
        return False, "Failed to securely store connection credentials", None

    server_id = f"srv_{uuid.uuid4().hex[:8]}"
    server_config = {
        "server_id": server_id,
        "server_name": clean_server_name,
        "encrypted_uri": encrypted_uri,
        "database_name": database_name,
        "schema_catalog": catalog,
        # Set later via select_collections() once the user picks from the
        # collection dropdown; empty means "not yet chosen, all collections
        # in scope" until then.
        "selected_collections": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    if not database.add_mongo_server(user_session, server_config):
        return False, "Failed to save server configuration", None

    logger.info(f"Attached external Mongo server '{server_id}' ({server_name}) to session {user_session}")
    return True, "Server connected and introspected successfully", _strip_secret(server_config)


def _strip_secret(server_config: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in server_config.items() if k != "encrypted_uri"}


def list_servers(user_session: str) -> List[Dict[str, Any]]:
    """Metadata for every server attached to this session -- never includes
    the (encrypted) connection string."""
    return [_strip_secret(s) for s in database.get_mongo_servers(user_session)]


def has_external_servers(user_session: str) -> bool:
    return len(database.get_mongo_servers(user_session)) > 0


def remove_server(user_session: str, server_id: str) -> bool:
    removed = database.remove_mongo_server(user_session, server_id)
    if removed:
        _client_cache.pop(server_id, None)
    return removed


def remove_all_servers_for_session(user_session: str) -> bool:
    """Detach all external Mongo servers and clear pooled clients for this session."""
    servers = database.get_mongo_servers(user_session)
    for server in servers:
        server_id = server.get("server_id")
        if server_id:
            _client_cache.pop(server_id, None)
    return database.delete_all_mongo_servers(user_session)


def get_combined_schema_text(user_session: str) -> str:
    """All attached servers' cached catalogs, formatted for the intent
    classification prompt. Uses the cache built at attach-time -- does not
    re-sample the live server on every question. A server with locked
    selected_collections only contributes those collections' lines (see
    format_server_schema)."""
    lines = []
    for server in database.get_mongo_servers(user_session):
        formatted = format_server_schema(server)
        if formatted:
            lines.append(formatted)
    return "\n".join(lines)


def list_collections_for_server(
    user_session: str, server_id: str
) -> Tuple[bool, str, Optional[str], List[str]]:
    """Database name + collection names available for the dropdown shown
    after a server is attached. Reads the cache built at attach-time --
    no live server round-trip needed."""
    server = _find_server_config(user_session, server_id)
    if server is None:
        return False, f"No server '{server_id}' attached to this session", None, []

    database_name = server.get("database_name")
    catalog = server.get("schema_catalog", {})

    if database_name:
        collections = sorted(catalog.get(database_name, {}).keys())
        return True, "OK", database_name, collections

    # URI had no database segment -- catalog spans multiple databases, so
    # there's no single database's collections to hand back for a dropdown.
    return (
        False,
        "This server's connection URI doesn't specify a database, so there's "
        "no single database to list collections for. Reconnect with a URI "
        "that includes a database name (e.g. '...mongodb.net/mydb').",
        None,
        [],
    )


def select_collections(user_session: str, server_id: str, collection_names: List[str]) -> Tuple[bool, str]:
    """Lock an attached server to one or more collections the user picked
    from the dropdown -- replaces any previous selection wholesale. All
    subsequent queries against this server target only these collections
    (see format_server_schema / mongodb_db._build_query_targets). Passing an
    empty list clears the lock, putting every collection in this server's
    database back in scope."""
    server = _find_server_config(user_session, server_id)
    if server is None:
        return False, f"No server '{server_id}' attached to this session"

    database_name = server.get("database_name")
    if collection_names and not database_name:
        return False, "This server has no single database scope to select collections within"

    available = server.get("schema_catalog", {}).get(database_name, {}) if database_name else {}
    missing = [c for c in collection_names if c not in available]
    if missing:
        return False, (
            f"Collection(s) {missing} were not found in database "
            f"'{database_name}' on this server (available: {sorted(available.keys())})"
        )

    if not database.set_mongo_server_selected_collections(user_session, server_id, collection_names):
        return False, "Failed to save collection selection"

    logger.info(f"Locked server '{server_id}' to collections {collection_names} for session {user_session}")
    if collection_names:
        return True, f"{len(collection_names)} collection(s) selected"
    return True, "Collection selection cleared"


# ---------------------------------------------------------------------------
# Client pooling: one pooled MongoClient per server_id, decrypted and
# connected lazily on first use rather than on every request.
# ---------------------------------------------------------------------------
_client_cache: Dict[str, pymongo.MongoClient] = {}
_cache_lock = threading.Lock()


def _find_server_config(user_session: str, server_id: str) -> Optional[Dict[str, Any]]:
    for server in database.get_mongo_servers(user_session):
        if server["server_id"] == server_id:
            return server
    return None


def get_client_for_server(user_session: str, server_id: str) -> pymongo.MongoClient:
    """Pooled MongoClient for an attached server, decrypting its stored URI
    only on first use per process."""
    if server_id not in _client_cache:
        with _cache_lock:
            if server_id not in _client_cache:
                config = _find_server_config(user_session, server_id)
                if config is None:
                    raise ValueError(f"No server '{server_id}' attached to session {user_session}")
                connection_uri = _decrypt(config["encrypted_uri"])
                _client_cache[server_id] = pymongo.MongoClient(
                    connection_uri,
                    serverSelectionTimeoutMS=_CONNECT_TIMEOUT_MS,
                    connectTimeoutMS=_CONNECT_TIMEOUT_MS,
                    socketTimeoutMS=_SOCKET_TIMEOUT_MS,
                )
    return _client_cache[server_id]


def get_database_for_server(user_session: str, server_id: str, database_name: str) -> pymongo.database.Database:
    return get_client_for_server(user_session, server_id)[database_name]
