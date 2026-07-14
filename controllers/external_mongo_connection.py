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

Explicitly out of scope: connecting to a Mongo server on the user's own
local machine/LAN. This backend has no network path to "localhost" as the
user's browser understands it -- only to servers actually reachable from
wherever this backend runs (i.e. cloud-hosted/publicly-reachable Mongo).
"""

import ipaddress
import logging
import socket
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import pymongo
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings
from controllers import database

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_MS = 5000
_ALLOWED_SCHEMES = {"mongodb", "mongodb+srv"}
_SCHEMA_SAMPLE_SIZE = 3
# Databases every Mongo deployment has that are never user data.
_SYSTEM_DATABASES = {"admin", "local", "config"}


# ---------------------------------------------------------------------------
# Encryption
# ---------------------------------------------------------------------------

def _get_fernet() -> Fernet:
    key = settings.EXTERNAL_MONGO_ENCRYPTION_KEY
    if not key:
        raise RuntimeError(
            "EXTERNAL_MONGO_ENCRYPTION_KEY is not configured; refusing to store "
            "an external Mongo connection string unencrypted. Generate one with "
            "`python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\"` and set it in .env."
        )
    return Fernet(key.encode())


def _encrypt(value: str) -> str:
    return _get_fernet().encrypt(value.encode()).decode()


def _decrypt(token: str) -> str:
    try:
        return _get_fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise RuntimeError("Stored external Mongo connection string could not be decrypted") from e


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
            return False, (
                f"Host '{hostname}' resolves to a non-public address ({ip_str}); "
                "external connections must point at a publicly reachable Mongo "
                "server (e.g. MongoDB Atlas). Locally-hosted Mongo servers on "
                "your own machine/network are not reachable from this backend."
            )
    return True, ""


def validate_connection_uri(connection_uri: str) -> Tuple[bool, str]:
    """Structural + SSRF validation, before we ever attempt to connect."""
    try:
        parsed = urlparse(connection_uri)
    except Exception as e:
        return False, f"Malformed connection URI: {e}"

    if parsed.scheme not in _ALLOWED_SCHEMES:
        return False, f"Unsupported scheme '{parsed.scheme}'; expected mongodb:// or mongodb+srv://"

    if not parsed.hostname:
        return False, "Connection URI must include a host"

    # mongodb+srv:// resolves via DNS SRV records rather than a plain A/AAAA
    # lookup; skip the direct IP check for it (the driver resolves it at
    # connect time) but still block the obvious loopback/hostname cases.
    if parsed.scheme == "mongodb":
        ok, msg = _validate_host_is_public(parsed.hostname)
        if not ok:
            return False, msg
    elif parsed.hostname in ("localhost", "127.0.0.1", "::1"):
        return False, f"Host '{parsed.hostname}' is not reachable from this backend"

    return True, ""


# ---------------------------------------------------------------------------
# Schema catalog: introspect every user database/collection on the server,
# sampling _SCHEMA_SAMPLE_SIZE documents per collection to infer field types.
# Cached at attach-time rather than re-sampled on every query.
# ---------------------------------------------------------------------------

def _infer_type_name(value: Any) -> str:
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


def build_schema_catalog(client: pymongo.MongoClient) -> Dict[str, Dict[str, Dict[str, str]]]:
    """{database_name: {collection_name: {field_name: type}}} across every
    non-system database/collection this connection can see."""
    catalog: Dict[str, Dict[str, Dict[str, str]]] = {}
    for db_name in client.list_database_names():
        if db_name in _SYSTEM_DATABASES:
            continue
        db = client[db_name]
        db_catalog: Dict[str, Dict[str, str]] = {}
        for coll_name in db.list_collection_names():
            fields: Dict[str, str] = {}
            for doc in db[coll_name].find({}, limit=_SCHEMA_SAMPLE_SIZE):
                for key, value in doc.items():
                    if key == "_id":
                        continue
                    if key not in fields:
                        fields[key] = _infer_type_name(value)
            db_catalog[coll_name] = fields
        if db_catalog:
            catalog[db_name] = db_catalog
    return catalog


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
        )
        client.admin.command("ping")
        return True, "Connection successful", client
    except Exception as e:
        logger.warning(f"External Mongo connection test failed: {e}")
        return False, f"Could not connect: {e}", None


def attach_server(
    user_session: str, connection_uri: str, server_name: str
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Full attach flow: validate, connect, introspect every DB/collection,
    encrypt the URI, and persist the server config for this session.
    Returns (ok, message, server_config_without_encrypted_uri)."""
    ok, msg, client = test_connection(connection_uri)
    if not ok:
        return False, msg, None

    try:
        catalog = build_schema_catalog(client)
    except Exception as e:
        logger.error(f"Schema introspection failed for new external Mongo server: {e}")
        return False, f"Connected, but failed to introspect databases/collections: {e}", None
    finally:
        client.close()

    if not catalog:
        return False, "Connected, but no user databases/collections were found on this server", None

    server_id = f"srv_{uuid.uuid4().hex[:8]}"
    server_config = {
        "server_id": server_id,
        "server_name": server_name,
        "encrypted_uri": _encrypt(connection_uri),
        "schema_catalog": catalog,
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


def get_combined_schema_text(user_session: str) -> str:
    """All attached servers' cached catalogs, formatted for the intent
    classification prompt. Uses the cache built at attach-time -- does not
    re-sample the live server on every question."""
    lines = []
    for server in database.get_mongo_servers(user_session):
        formatted = format_schema_catalog(server["server_id"], server.get("schema_catalog", {}))
        if formatted:
            lines.append(formatted)
    return "\n".join(lines)


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
                )
    return _client_cache[server_id]


def get_database_for_server(user_session: str, server_id: str, database_name: str) -> pymongo.database.Database:
    return get_client_for_server(user_session, server_id)[database_name]
