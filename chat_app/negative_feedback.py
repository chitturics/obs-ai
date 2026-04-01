"""
Negative Feedback Storage and Filtering System.

Stores thumbs-down feedback in a dedicated ChromaDB collection and uses it to
filter out previously-bad answers from future search results.

Key functions:
    add_negative_feedback()      — Store a bad Q&A pair
    filter_negative_results()    — Remove results matching prior bad answers
    get_negative_feedback_context() — Inject "avoid these" examples into prompts
    get_negative_feedback_stats()   — Collection statistics
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from chat_app.settings import get_settings

logger = logging.getLogger(__name__)

# Collection name for negative feedback
NEGATIVE_FEEDBACK_COLLECTION = "negative_feedback_mxbai_embed_large"


# ---------------------------------------------------------------------------
# Shared ChromaDB helper (DRY — used by every function below)
# ---------------------------------------------------------------------------

def _get_chroma_client():
    """Return an HttpClient connected to the configured ChromaDB instance."""
    import chromadb

    cfg = get_settings().chroma
    url = cfg.http_url
    # Parse host:port from URL like "http://host:port"
    host = url.replace("http://", "").replace("https://", "").split(":")[0]
    port = int(url.split(":")[-1])
    return chromadb.HttpClient(host=host, port=port)


def _get_or_create_collection(client=None):
    """Get existing collection or create it. Returns (collection, client)."""
    if client is None:
        client = _get_chroma_client()

    try:
        return client.get_collection(NEGATIVE_FEEDBACK_COLLECTION), client
    except Exception as _exc:  # broad catch — resilience at boundary  # ChromaDB raises ValueError when collection does not exist
        collection = client.create_collection(
            name=NEGATIVE_FEEDBACK_COLLECTION,
            metadata={"description": "Negative feedback for filtering bad answers"},
        )
        logger.info("Created collection: %s", NEGATIVE_FEEDBACK_COLLECTION)
        return collection, client


def _fingerprint_text(text: str) -> str:
    """Generate SHA256 fingerprint for text."""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def add_negative_feedback(
    question: str,
    bad_answer: str,
    username: str = "unknown",
    reason: Optional[str] = None,
) -> Tuple[bool, Optional[str]]:
    """Store a thumbs-down Q&A pair in the negative feedback collection.

    This allows the system to:
    1. Track answers to avoid suggesting again.
    2. Filter similar bad answers from future search results.
    3. Inject "avoid these" context into prompts.
    4. Export for fine-tuning (teach the model what's wrong).

    Args:
        question: User's original question.
        bad_answer: The answer that received thumbs down.
        username: User who gave negative feedback.
        reason: Optional reason why the answer was bad.

    Returns:
        (success, error_message) tuple.
    """
    try:
        from vectorstore import get_embeddings_model

        collection, _ = _get_or_create_collection()
        embeddings = get_embeddings_model()

        qa_text = f"Question: {question.strip()}\n\nBad Answer: {bad_answer.strip()}"
        fingerprint = _fingerprint_text(qa_text)

        # Skip if already stored
        existing = collection.get(ids=[fingerprint])
        if existing and existing["ids"]:
            logger.info("[NEGATIVE_FEEDBACK] Already stored: %s", fingerprint[:16])
            return True, "Already stored"

        metadata = {
            "kind": "negative_feedback",
            "question": question[:500],
            "bad_answer_preview": bad_answer[:200],
            "username": username,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "fingerprint": fingerprint,
            "reason": reason or "thumbs_down",
        }

        embedding = embeddings.embed_query(qa_text)
        collection.add(
            ids=[fingerprint],
            embeddings=[embedding],
            documents=[qa_text],
            metadatas=[metadata],
        )

        logger.info("[NEGATIVE_FEEDBACK] Stored: %s...", question[:50])
        return True, None

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[NEGATIVE_FEEDBACK] Failed to store: %s", exc)
        return False, str(exc)


def filter_negative_results(
    search_results: List[tuple],
    question: str,
    similarity_threshold: float = 0.85,
) -> List[tuple]:
    """Remove search results that match previously-bad answers.

    Args:
        search_results: List of (doc, score) tuples from vector search.
        question: Current user question.
        similarity_threshold: Minimum similarity to consider a match (unused
            currently — uses fingerprint matching for exactness).

    Returns:
        Filtered list of (doc, score) tuples.
    """
    try:
        from vectorstore import get_embeddings_model

        client = _get_chroma_client()
        try:
            collection = client.get_collection(NEGATIVE_FEEDBACK_COLLECTION)
        except Exception as _exc:  # broad catch — resilience at boundary  # ChromaDB raises ValueError when collection does not exist
            return search_results  # No collection yet

        count = collection.count()
        if count == 0:
            return search_results

        embeddings = get_embeddings_model()
        query_embedding = embeddings.embed_query(question)

        negative_results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(10, count),
        )

        # Build set of bad answer fingerprints
        bad_fingerprints: set[str] = set()
        if negative_results and negative_results["metadatas"]:
            for metadata in negative_results["metadatas"][0]:
                bad_fingerprints.add(metadata.get("fingerprint", ""))

        # Filter out exact matches
        filtered = []
        for item in search_results:
            # Support both dict chunks and (doc, score) tuples
            if isinstance(item, dict):
                doc_text = item.get("text", item.get("page_content", ""))
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                doc = item[0]
                doc_text = doc.page_content if hasattr(doc, "page_content") else str(doc)
            else:
                doc_text = str(item)

            if _fingerprint_text(doc_text) in bad_fingerprints:
                logger.info("[NEGATIVE_FEEDBACK] Filtered: %s...", doc_text[:50])
                continue
            filtered.append(item)

        removed = len(search_results) - len(filtered)
        if removed:
            logger.info("[NEGATIVE_FEEDBACK] Filtered %d bad results", removed)

        return filtered

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[NEGATIVE_FEEDBACK] Filtering failed: %s", exc)
        return search_results  # Return originals on error


def get_negative_feedback_context(question: str, top_k: int = 3) -> str:
    """Get negative feedback examples to inject into prompts.

    Tells the LLM "here are examples of BAD answers to avoid for similar questions".

    Args:
        question: Current user question.
        top_k: Number of negative examples to retrieve.

    Returns:
        Formatted markdown string (empty if no relevant examples found).
    """
    try:
        from vectorstore import get_embeddings_model

        client = _get_chroma_client()
        try:
            collection = client.get_collection(NEGATIVE_FEEDBACK_COLLECTION)
        except Exception as _exc:  # broad catch — resilience at boundary  # ChromaDB raises ValueError when collection does not exist
            return ""

        count = collection.count()
        if count == 0:
            return ""

        embeddings = get_embeddings_model()
        query_embedding = embeddings.embed_query(question)

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, count),
        )

        if not results or not results["documents"]:
            return ""

        parts = ["\nAVOID THESE BAD ANSWER PATTERNS:"]
        for i, (doc, metadata) in enumerate(
            zip(results["documents"][0], results["metadatas"][0]), 1
        ):
            reason = metadata.get("reason", "thumbs_down")
            timestamp = metadata.get("timestamp", "unknown")
            parts.append(f"\nBad Example {i} (reason: {reason}, when: {timestamp}):")
            parts.append(doc[:300])
            # Extract and highlight the correction if present
            if "\n\nCorrection:" in doc:
                correction = doc.split("\n\nCorrection:", 1)[1].strip()[:200]
                parts.append(f"\n**USE THIS INSTEAD:** {correction}")
            parts.append("---")

        return "\n".join(parts)

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[NEGATIVE_FEEDBACK] Failed to get context: %s", exc)
        return ""


def get_negative_feedback_stats() -> Dict[str, Any]:
    """Get statistics about the negative feedback collection.

    Returns:
        Dict with count, exists flag, and recent examples.
    """
    try:
        client = _get_chroma_client()
        try:
            collection = client.get_collection(NEGATIVE_FEEDBACK_COLLECTION)
        except Exception as _exc:  # broad catch — resilience at boundary  # ChromaDB raises ValueError when collection does not exist
            return {"count": 0, "exists": False}

        count = collection.count()
        recent = collection.get(limit=5)
        recent_examples = []
        if recent and recent["metadatas"]:
            for metadata in recent["metadatas"]:
                recent_examples.append({
                    "question": metadata.get("question", "")[:100],
                    "timestamp": metadata.get("timestamp", ""),
                    "username": metadata.get("username", ""),
                    "reason": metadata.get("reason", ""),
                })

        return {"count": count, "exists": True, "recent_examples": recent_examples}

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[NEGATIVE_FEEDBACK] Failed to get stats: %s", exc)
        return {"count": 0, "exists": False, "error": str(exc)}


def get_collection():
    """Get the negative feedback ChromaDB collection.

    Handles dimension mismatch by recreating the collection automatically.

    Returns:
        ChromaDB collection object, or None if unavailable.
    """
    try:
        client = _get_chroma_client()
        try:
            collection = client.get_collection(NEGATIVE_FEEDBACK_COLLECTION)

            # Validate dimensions by doing a test query
            if collection.count() > 0:
                try:
                    collection.query(query_texts=["test"], n_results=1)
                except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as dim_err:
                    if "dimension" in str(dim_err).lower():
                        logger.warning(
                            "[NEGATIVE_FEEDBACK] Dimension mismatch, recreating: %s",
                            dim_err,
                        )
                        client.delete_collection(NEGATIVE_FEEDBACK_COLLECTION)
                        collection = client.create_collection(
                            name=NEGATIVE_FEEDBACK_COLLECTION,
                            metadata={"description": "Negative feedback for filtering bad answers"},
                        )
                        logger.info("[NEGATIVE_FEEDBACK] Recreated collection")
                    else:
                        raise

            return collection

        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            if "does not exist" in str(e).lower() or "not found" in str(e).lower():
                collection = client.create_collection(
                    name=NEGATIVE_FEEDBACK_COLLECTION,
                    metadata={"description": "Negative feedback for filtering bad answers"},
                )
                logger.info("[NEGATIVE_FEEDBACK] Created collection: %s", NEGATIVE_FEEDBACK_COLLECTION)
                return collection
            raise

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[NEGATIVE_FEEDBACK] Failed to get collection: %s", exc)
        return None
