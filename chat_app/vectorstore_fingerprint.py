"""Vectorstore fingerprinting — deduplication and change detection for ingested documents.

Extracted from vectorstore.py. Contains: has_fingerprint, get_existing_fingerprints,
_should_replace, _delete_source, fingerprint_file, fingerprint_bytes.
"""
import hashlib
import logging
from typing import Optional

from langchain_chroma import Chroma

logger = logging.getLogger(__name__)


def _fingerprint_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def has_fingerprint(store: Chroma, fingerprint: str) -> bool:
    if not store or not fingerprint:
        return False
    try:
        coll = getattr(store, "_collection", None)
        if coll is None:
            return False
        res = coll.get(where={"fingerprint": fingerprint}, limit=1)
        ids = res.get("ids") if isinstance(res, dict) else None
        return bool(ids)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"has_fingerprint failed: {exc}")
        return False


def get_existing_fingerprints(store: Chroma, fingerprints: list[str]) -> set[str]:
    """Batch check which fingerprints already exist in ChromaDB.

    Much faster than calling has_fingerprint() one by one for large ingestion jobs.

    Args:
        store: ChromaDB vector store
        fingerprints: List of fingerprint hashes to check

    Returns:
        Set of fingerprints that already exist in the collection
    """
    if not store or not fingerprints:
        return set()

    try:
        coll = getattr(store, "_collection", None)
        if coll is None:
            return set()

        existing = set()
        # ChromaDB $in operator supports up to ~1000 items per query
        batch_size = 500

        for i in range(0, len(fingerprints), batch_size):
            batch = fingerprints[i:i + batch_size]
            try:
                res = coll.get(
                    where={"fingerprint": {"$in": batch}},
                    include=["metadatas"],
                )
                if res and res.get("metadatas"):
                    for meta in res["metadatas"]:
                        if isinstance(meta, dict) and meta.get("fingerprint"):
                            existing.add(meta["fingerprint"])
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                # Fallback: check one by one if $in fails
                logger.warning(f"Batch fingerprint check failed, using fallback: {e}")
                for fp in batch:
                    if has_fingerprint(store, fp):
                        existing.add(fp)

        return existing
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        print(f"[vectorstore] get_existing_fingerprints failed: {exc}")
        return set()


def _should_replace(store: Chroma, source: str, fingerprint: str) -> bool:
    """Check if an existing source has a different fingerprint.

    Returns True if:
    - source doesn't exist (new document) -> replace (add fresh)
    - source exists with different fingerprint -> replace (content changed)
    Returns False if source exists with same fingerprint (skip re-ingestion).
    """
    coll = getattr(store, "_collection", None)
    if coll is None:
        return True
    try:
        res = coll.get(where={"source": source}, limit=1, include=["metadatas"])
        if not res or not res.get("metadatas"):
            return True  # Source doesn't exist yet
        existing_fp = res["metadatas"][0].get("fingerprint", "")
        if existing_fp == fingerprint:
            logger.info(f"[INGEST] Skipping '{source}' - content unchanged (fingerprint match)")
            return False
        logger.info(f"[INGEST] Replacing '{source}' - content changed (fingerprint mismatch)")
        return True
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"_should_replace check failed for {source}: {exc}")
        return True  # Fallback: re-ingest on error


def _delete_source(store: Chroma, source: str) -> None:
    coll = getattr(store, "_collection", None)
    if coll is None:
        return
    try:
        coll.delete(where={"source": source})
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"Delete by source failed for {source}: {exc}")


def fingerprint_file(path: str) -> Optional[str]:
    try:
        with open(path, "rb") as f:
            return _fingerprint_bytes(f.read())
    except Exception as _exc:  # broad catch — resilience against all failures
        return None


def fingerprint_bytes(data: bytes | bytearray) -> str:
    return _fingerprint_bytes(bytes(data))
