"""
Database initialization and helpers for the Notes service.

This module:
- Connects to MongoDB using MONGO_URL environment variable (falls back to a safe default
  if explicitly provided in code below — replace it or set MONGO_URL in production).
- Exposes `db`, common collections (users, notes, subscriptions), and GridFS (`fs`).
- Provides helper functions: ensure_indexes(), health_check(), get_collection(), close().
- Configures client with sensible timeouts and pool settings for use with Atlas.

Usage:
    from app.db import users, notes, subscriptions, fs, ensure_indexes

    ensure_indexes()  # call once at startup

Environment variables (recommended):
- MONGO_URL : MongoDB connection string (e.g. mongodb+srv://user:pass@cluster.example.net/LMBD?... )
- MONGO_DB  : optional database name to override the one in the URI
"""

from __future__ import annotations
import os
import logging
import time
import threading
from urllib.parse import urlparse
from typing import Optional

from pymongo import MongoClient, errors
from gridfs import GridFS

logger = logging.getLogger(__name__)

# Default connection string (development only).
# Replace or prefer setting MONGO_URL in environment for production.
_DEFAULT_MONGO_URL = (
    "mongodb://atlas-sql-687f19d2678c807903e45f78-zalniw.g.query.mongodb.net/LMBD?"
    "ssl=true&authSource=admin"
)

MONGO_URL = os.environ.get("MONGO_URL", os.environ.get("MONGO_URI", _DEFAULT_MONGO_URL))
# Optional override of database name (if you want to force a different DB than the URI path)
MONGO_DB_OVERRIDE = os.environ.get("MONGO_DB")

# Connection options for robustness (tune to your deployment)
_CONNECT_TIMEOUT_MS = int(os.environ.get("MONGO_CONNECT_TIMEOUT_MS", "10000"))  # 10s
_SERVER_SELECTION_TIMEOUT_MS = int(os.environ.get("MONGO_SERVER_SELECTION_TIMEOUT_MS", "10000"))
_MAX_POOL_SIZE = int(os.environ.get("MONGO_MAX_POOL_SIZE", "50"))
_MIN_POOL_SIZE = int(os.environ.get("MONGO_MIN_POOL_SIZE", "0"))
_RETRY_WRITES = os.environ.get("MONGO_RETRY_WRITES", "true").lower() in ("1", "true", "yes")

# Retry behavior for initial connection attempts
_INITIAL_CONNECT_RETRIES = int(os.environ.get("MONGO_INITIAL_CONNECT_RETRIES", "3"))
_INITIAL_CONNECT_INTERVAL = float(os.environ.get("MONGO_INITIAL_CONNECT_INTERVAL", "2.0"))

# Determine database name from URI if present
def _db_name_from_uri(uri: str) -> Optional[str]:
    try:
        parsed = urlparse(uri)
        if parsed.path and parsed.path not in ("/", ""):
            # path is like "/dbname"
            return parsed.path.lstrip("/")
    except Exception:
        return None
    return None


def _mask_uri(uri: str) -> str:
    """
    Mask credentials in a Mongo URI for logging.
    """
    try:
        parsed = urlparse(uri)
        if parsed.username or parsed.password:
            netloc = parsed.netloc
            # replace credentials portion if present
            if "@" in netloc:
                cred, host = netloc.split("@", 1)
                return uri.replace(cred + "@", "****:****@")
        return uri
    except Exception:
        return "mongodb://<hidden>"

# Build client options
_client_kwargs = dict(
    connect=True,
    serverSelectionTimeoutMS=_SERVER_SELECTION_TIMEOUT_MS,
    connectTimeoutMS=_CONNECT_TIMEOUT_MS,
    maxPoolSize=_MAX_POOL_SIZE,
    minPoolSize=_MIN_POOL_SIZE,
    retryWrites=_RETRY_WRITES,
)

# Create MongoClient with retries for initial connection (useful during container start)
_client: Optional[MongoClient] = None
_db = None
fs: Optional[GridFS] = None

def _create_client_with_retries(uri: str) -> MongoClient:
    last_exc = None
    # Ensure at least 1 attempt even if MONGO_INITIAL_CONNECT_RETRIES is set to 0
    retries = max(1, _INITIAL_CONNECT_RETRIES)
    for attempt in range(1, retries + 1):
        try:
            client = MongoClient(uri, **_client_kwargs)
            # Trigger server selection to validate connection
            client.admin.command("ping")
            logger.info("Connected to MongoDB (attempt %d)", attempt)
            return client
        except Exception as exc:
            last_exc = exc
            logger.warning("MongoDB connection attempt %d/%d failed: %s", attempt, retries, exc)
            if attempt < retries:
                time.sleep(_INITIAL_CONNECT_INTERVAL)
    # All attempts failed
    logger.error("All MongoDB initial connection attempts failed")
    if last_exc:
        raise last_exc
    raise RuntimeError("MongoDB connection failed with no exception details")

def init_db():
    """
    Initialize the global Mongo client, database and GridFS instance.
    Safe to call multiple times (idempotent).
    """
    global _client, _db, fs

    if _client is not None and _db is not None and fs is not None:
        return

    logger.info("Initializing MongoDB client using URL: %s", _mask_uri(MONGO_URL))
    _client = _create_client_with_retries(MONGO_URL)

    # Determine DB name
    db_name = MONGO_DB_OVERRIDE or _db_name_from_uri(MONGO_URL) or "LMBD"
    logger.info("Using MongoDB database: %s", db_name)
    _db = _client[db_name]

    # GridFS for storing binary assets
    fs = GridFS(_db)

    # Ensure indexes for collections (safe to call repeatedly)
    ensure_indexes()

def get_db():
    if _db is None:
        init_db()
    return _db

def get_client() -> MongoClient:
    if _client is None:
        init_db()
    return _client

def get_gridfs() -> GridFS:
    if fs is None:
        init_db()
    return fs

# Convenience collection references
def _get_collection(name: str):
    db = get_db()
    return db[name]

def get_users_collection():
    return _get_collection("users")

def get_notes_collection():
    return _get_collection("notes")

def get_subscriptions_collection():
    return _get_collection("subscriptions")

# Publicly exported collection references (lazy proxies)
# These are wrapped functions that will work even if DB is not immediately available

class LazyCollection:
    """Thread-safe proxy that lazily gets the actual collection when first accessed."""
    def __init__(self, getter):
        self._getter = getter
        self._collection = None
        self._lock = threading.Lock()
    
    def _get_collection(self):
        if self._collection is None:
            with self._lock:
                # Double-check after acquiring lock
                if self._collection is None:
                    self._collection = self._getter()
        return self._collection
    
    def __getattr__(self, name):
        return getattr(self._get_collection(), name)


# Create lazy collection proxies
users = LazyCollection(get_users_collection)
notes = LazyCollection(get_notes_collection)
subscriptions = LazyCollection(get_subscriptions_collection)


def get_gridfs_lazy() -> GridFS:
    """Lazily get GridFS instance."""
    global fs
    if fs is None:
        init_db()
    return fs


# For backward compatibility, also expose db and client lazily
def get_db_lazy():
    return get_db()


def get_client_lazy():
    return get_client()


# For modules that expect db and client as module-level variables
class LazyDB:
    """Proxy that lazily gets the database when first accessed."""
    def __getattr__(self, name):
        return getattr(get_db(), name)


class LazyClient:
    """Proxy that lazily gets the client when first accessed."""
    def __getattr__(self, name):
        return getattr(get_client(), name)


db = LazyDB()
client = LazyClient()

def ensure_indexes():
    """
    Create the common indexes used by the application.
    Call once at startup (idempotent).
    """
    try:
        uidx = users.create_index("username", unique=True, background=True)
        email_idx = users.create_index("email", unique=True, background=True)
        logger.debug("Users indexes created: %s, %s", uidx, email_idx)
    except Exception as exc:
        logger.exception("Error creating users indexes: %s", exc)

    try:
        notes.create_index("slug", unique=True, background=True)
        notes.create_index([("tags", 1)], background=True)
        notes.create_index([("updated_at", -1)], background=True)
        logger.debug("Notes indexes created")
    except Exception as exc:
        logger.exception("Error creating notes indexes: %s", exc)

    try:
        subscriptions.create_index("stripe_session_id", unique=True, sparse=True, background=True)
        subscriptions.create_index([("email", 1)], background=True)
        # TTL index example: expire one-time tokens after 30 days (if you store token docs with `created_at`)
        # subscriptions.create_index("created_at", expireAfterSeconds=60*60*24*30)
        logger.debug("Subscriptions indexes created")
    except Exception as exc:
        logger.exception("Error creating subscriptions indexes: %s", exc)

def health_check(timeout_seconds: float = 2.0) -> bool:
    """
    Check MongoDB connectivity. Returns True if ping succeeds.
    """
    try:
        client = get_client()
        client.admin.command("ping")
        return True
    except Exception as exc:
        logger.warning("MongoDB health check failed: %s", exc)
        return False

def close():
    """
    Close the Mongo client connection (useful for graceful shutdown/tests).
    """
    global _client
    if _client:
        try:
            _client.close()
            logger.info("Mongo client closed")
        except Exception:
            logger.exception("Error closing Mongo client")
        finally:
            _client = None

# Example helper: read a note by slug (wraps DB access)
def find_note_by_slug(slug: str):
    return notes.find_one({"slug": slug})

# Example helper: insert subscription record (useful for payments webhook)
def add_subscription_record(email: str, note_slug: str, stripe_session_id: str, status: str = "paid", extra: dict = None):
    doc = {
        "email": email,
        "note_slug": note_slug,
        "stripe_session_id": stripe_session_id,
        "status": status,
        "created_at": int(time.time()),
    }
    if extra:
        doc.update(extra)
    return subscriptions.insert_one(doc)

# When imported as module, the DB is initialized (so other modules can import users/notes/...)
# If you want to avoid eager init, remove the init_db() call above and call init_db() explicitly from app startup.
