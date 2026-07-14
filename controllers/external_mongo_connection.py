"""
External MongoDB Connection Management.

Lets a user attach their own externally-hosted MongoDB server (e.g. Atlas or
any network-reachable Mongo deployment) to a specific knowledge container,
instead of only querying data ingested from uploaded JSON files. Once
attached, controllers/mongodb_db.py's get_mongo_db_for_session resolves to
this external database instead of the app-managed per-session one, so
schema introspection, query generation, and intent routing all work
unchanged against it.

Explicitly out of scope: connecting to a Mongo server on the user's own
local machine/LAN. This backend has no network path to "localhost" as the
user's browser understands it — only to servers actually reachable from
wherever this backend runs (i.e. cloud-hosted/publicly-reachable Mongo).
"""

import ipaddress
import json
import logging
import os
import socket
import threading
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import pymongo
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import settings

logger = logging.getLogger(__name__)

_CONNECT_TIMEOUT_MS = 5000
_ALLOWED_SCHEMES = {"mongodb", "mongodb+srv"}


def _config_path(user_session: str) -> str:
    return os.path.join("users", user_session, "files", "external_mongo_config.json")


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

    for family, _, _, _, sockaddr in addrinfo:
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


def test_connection(connection_uri: str, database_name: str) -> Tuple[bool, str, List[str]]:
    """Validate + attempt to actually connect and list collections. Never
    persists anything -- callers decide whether to save after this succeeds."""
    ok, msg = validate_connection_uri(connection_uri)
    if not ok:
        return False, msg, []

    try:
        client = pymongo.MongoClient(
            connection_uri,
            serverSelectionTimeoutMS=_CONNECT_TIMEOUT_MS,
            connectTimeoutMS=_CONNECT_TIMEOUT_MS,
        )
        client.admin.command("ping")
        collections = client[database_name].list_collection_names()
        client.close()
        return True, "Connection successful", collections
    except Exception as e:
        logger.warning(f"External Mongo connection test failed: {e}")
        return False, f"Could not connect: {e}", []


def save_external_connection(
    user_session: str,
    connection_uri: str,
    database_name: str,
    collections: Optional[List[str]] = None,
) -> None:
    """Persist an (encrypted) external Mongo connection for this session.
    Caller is expected to have already called test_connection successfully."""
    path = _config_path(user_session)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    config = {
        "connection_uri": _encrypt(connection_uri),
        "database_name": database_name,
        "collections": collections or [],
    }
    with open(path, "w") as f:
        json.dump(config, f, indent=4)
    logger.info(f"Saved external Mongo connection for session {user_session} (db={database_name})")


def has_external_connection(user_session: str) -> bool:
    return os.path.exists(_config_path(user_session))


def load_external_connection(user_session: str) -> Optional[Dict[str, Any]]:
    """Returns {'connection_uri': <decrypted>, 'database_name': ..., 'collections': [...]}
    or None if this session has no external connection configured."""
    path = _config_path(user_session)
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        config = json.load(f)
    config["connection_uri"] = _decrypt(config["connection_uri"])
    return config


def remove_external_connection(user_session: str) -> None:
    path = _config_path(user_session)
    if os.path.exists(path):
        os.remove(path)
        logger.info(f"Removed external Mongo connection for session {user_session}")


# ---------------------------------------------------------------------------
# Client cache: one pooled MongoClient per distinct external URI, shared
# across sessions that happen to point at the same server, instead of
# opening a fresh connection (and pool) on every request.
# ---------------------------------------------------------------------------
_client_cache: Dict[str, pymongo.MongoClient] = {}
_cache_lock = threading.Lock()


def get_external_client(connection_uri: str) -> pymongo.MongoClient:
    if connection_uri not in _client_cache:
        with _cache_lock:
            if connection_uri not in _client_cache:
                _client_cache[connection_uri] = pymongo.MongoClient(
                    connection_uri,
                    serverSelectionTimeoutMS=_CONNECT_TIMEOUT_MS,
                    connectTimeoutMS=_CONNECT_TIMEOUT_MS,
                )
    return _client_cache[connection_uri]


def get_external_db_for_session(user_session: str) -> Optional[pymongo.database.Database]:
    """Resolve this session's external Mongo database, if one is configured."""
    config = load_external_connection(user_session)
    if config is None:
        return None
    client = get_external_client(config["connection_uri"])
    return client[config["database_name"]]


def get_allowed_collections(user_session: str) -> Optional[List[str]]:
    """The collection allowlist for this session's external connection, if any
    was configured. None means 'not externally connected' (caller should not
    restrict); an empty list means 'externally connected, no allowlist set'
    (all collections in the configured database are visible)."""
    config = load_external_connection(user_session)
    if config is None:
        return None
    return config.get("collections") or None
