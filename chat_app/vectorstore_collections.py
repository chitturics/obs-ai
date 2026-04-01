"""Vectorstore collection management — listing, auto-discovery, and additional stores.

Extracted from vectorstore.py. Contains: _list_all_collections, _resolve_auto_collections,
ensure_additional_stores.
"""
import logging
from typing import Optional, List

from chromadb import HttpClient, PersistentClient
from chromadb.config import Settings
from langchain_chroma import Chroma

from chat_app.settings import get_settings
from chat_app.vectorstore_init import (
    get_vector_store,
    CHROMA_DIR,
    CHROMA_HTTP_URL,
    COLLECTION_NAME,
    SECONDARY_COLLECTION,
    FEEDBACK_COLLECTION,
)

logger = logging.getLogger(__name__)

_cfg = get_settings()

# Optional additional collections, comma-separated
ADDITIONAL_COLLECTIONS = [
    c.strip()
    for c in (_cfg.chroma.additional_collections or "").split(",")
    if c.strip()
]
EXCLUDE_COLLECTIONS = {
    c.strip()
    for c in (_cfg.chroma.exclude_collections or "").split(",")
    if c.strip()
}

# Singleton for auto-discovered additional stores
_ADDITIONAL_STORES: Optional[List[Chroma]] = None
_AUTO_COLLECTIONS: List[str] = []


def _list_all_collections() -> List[str]:
    """List all available Chroma collections via HTTP or local client.
    Falls back to empty list on error.
    """
    try:
        http_url = (CHROMA_HTTP_URL or "").strip()
        if http_url:
            from urllib.parse import urlparse
            parsed = urlparse(http_url if "://" in http_url else f"http://{http_url}")
            host = parsed.hostname or "127.0.0.1"
            port_int = parsed.port or 8001
            client = HttpClient(
                host=host,
                port=port_int,
                settings=Settings(anonymized_telemetry=False, allow_reset=True),
            )
        else:
            client = PersistentClient(
                path=CHROMA_DIR,
                settings=Settings(anonymized_telemetry=False, allow_reset=True),
            )
        cols = client.list_collections()
        names = []
        for col in cols:
            # col may be Collection or dict depending on client
            if hasattr(col, "name"):
                names.append(col.name)
            elif isinstance(col, dict) and "name" in col:
                names.append(col["name"])
        return names
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as exc:
        logger.error(f"List collections failed: {exc}")
        return []


def _resolve_auto_collections() -> List[str]:
    """Determine which collections to search in addition to primary/secondary/feedback.
    If CHROMA_ADDITIONAL_COLLECTIONS is set, use that; otherwise, discover all
    collections and include everything except primary/secondary/feedback/exclusions.
    """
    global _AUTO_COLLECTIONS
    if _AUTO_COLLECTIONS:
        return _AUTO_COLLECTIONS

    # If explicit env provided, honor it
    if ADDITIONAL_COLLECTIONS:
        _AUTO_COLLECTIONS = [c for c in ADDITIONAL_COLLECTIONS if c not in EXCLUDE_COLLECTIONS]
        return _AUTO_COLLECTIONS

    # Discover all and filter
    discovered = set(_list_all_collections())
    exclude = {
        COLLECTION_NAME,
        SECONDARY_COLLECTION or "",
        FEEDBACK_COLLECTION,
        *EXCLUDE_COLLECTIONS,
    }
    _AUTO_COLLECTIONS = [c for c in discovered if c and c not in exclude]
    logger.info(f"[vectorstore] auto additional collections: {_AUTO_COLLECTIONS}")
    return _AUTO_COLLECTIONS


def ensure_additional_stores() -> List[Chroma]:
    """Optional list of extra collections to widen retrieval.
    Controlled via CHROMA_ADDITIONAL_COLLECTIONS (comma-separated).
    """
    global _ADDITIONAL_STORES
    if _ADDITIONAL_STORES is not None:
        return _ADDITIONAL_STORES
    _ADDITIONAL_STORES = []
    extra_collections = _resolve_auto_collections()
    if not extra_collections:
        return _ADDITIONAL_STORES
    for coll_name in extra_collections:
        try:
            store = get_vector_store(collection_name=coll_name, persist_directory=CHROMA_DIR)
            _ADDITIONAL_STORES.append(store)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.error(f"[vectorstore] additional store init failed for {coll_name}: {exc}")
    return _ADDITIONAL_STORES
