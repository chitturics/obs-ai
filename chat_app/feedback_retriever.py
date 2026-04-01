"""
Feedback-based answer retrieval.

When a user query matches a previously thumbs-up'd answer, retrieve and present it
with high confidence as it's been validated by users.

Uses embedding cosine similarity (via Ollama) with Jaccard pre-filter for speed.
"""
import logging
from typing import Optional, Dict, List
import re

from chat_app.settings import get_settings

logger = logging.getLogger(__name__)

_MAX_EMBED_FAILURES = 5

_embedder = None
_embedder_init_attempted = False
_embed_fail_count = 0


def _embed_text(text: str) -> Optional[List[float]]:
    """Get embedding vector via LangChain OllamaEmbeddings. Returns None on failure."""
    global _embedder, _embedder_init_attempted, _embed_fail_count

    if _embed_fail_count >= _MAX_EMBED_FAILURES:
        return None

    if _embedder is None and not _embedder_init_attempted:
        _embedder_init_attempted = True
        try:
            from langchain_ollama import OllamaEmbeddings
            cfg = get_settings().ollama
            _embedder = OllamaEmbeddings(model=cfg.embed_model, base_url=cfg.base_url)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("OllamaEmbeddings init failed: %s", exc)
            return None

    if _embedder is None:
        return None

    try:
        result = _embedder.embed_query(text)
        _embed_fail_count = 0
        return result
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        _embed_fail_count += 1
        logger.warning("Embedding failed (%d/%d): %s", _embed_fail_count, _MAX_EMBED_FAILURES, exc)
    return None


def _cosine_similarity(a: List[float], b: List[float]) -> float:
    """Compute cosine similarity between two vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def extract_qa_from_feedback_chunk(chunk_text: str) -> tuple[Optional[str], Optional[str]]:
    """
    Extract question and answer from a feedback chunk.

    Feedback chunks are formatted as:
    Q: {question}
    A: {answer}

    Returns:
        (question, answer) or (None, None) if not parseable
    """
    # Try "Question: ... Answer: ..." format (from add_feedback_qa_to_memory)
    match = re.match(r'Question:\s*(.*?)\s*\n\s*\n?\s*Answer:\s*(.*)', chunk_text, re.DOTALL)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    # Fallback: "Q: ... A: ..." format
    match2 = re.match(r'Q:\s*(.*?)\s*A:\s*(.*)', chunk_text, re.DOTALL)
    if match2:
        return match2.group(1).strip(), match2.group(2).strip()
    return None, None


def find_feedback_match(
    chunks: list[dict],
    query: str,
    similarity_threshold: float = 0.70
) -> Optional[Dict]:
    """
    Check if any retrieved chunks are from the feedback collection
    and match the query using fast Jaccard similarity (NO embedding calls).

    Chunks were already retrieved by embedding similarity from ChromaDB,
    so we only need token overlap as a second filter.

    Args:
        chunks: List of retrieved chunks from ChromaDB
        query: User's current query
        similarity_threshold: Minimum Jaccard similarity (default: 0.70)

    Returns:
        Dictionary with {question, answer, source, username, similarity} if found, None otherwise
    """
    query_lower = query.lower()
    query_tokens = {t for t in re.split(r'[^a-z0-9]+', query_lower) if len(t) >= 3}

    if not query_tokens:
        return None

    best_match = None
    best_similarity = 0.0

    for chunk in chunks:
        source = chunk.get("source", "")

        if not source.startswith("feedback://"):
            continue

        text = chunk.get("text", "")
        question, answer = extract_qa_from_feedback_chunk(text)

        if not question or not answer:
            continue

        question_lower = question.lower()
        question_tokens = {t for t in re.split(r'[^a-z0-9]+', question_lower) if len(t) >= 3}

        if not question_tokens:
            continue

        # Jaccard similarity (fast, no Ollama call)
        intersection = len(query_tokens & question_tokens)
        union = len(query_tokens | question_tokens)
        jaccard = intersection / union if union > 0 else 0

        if jaccard < 0.30:
            continue

        if jaccard > best_similarity and jaccard >= similarity_threshold:
            best_similarity = jaccard
            username = source.replace("feedback://", "").split("/")[0] if "/" in source else "unknown"
            best_match = {
                "question": question,
                "answer": answer,
                "source": source,
                "username": username,
                "similarity": jaccard,
            }

    if best_match:
        logger.info(f"Feedback match FOUND: {best_match['similarity']:.2f} for: {best_match['question'][:50]}...")

    return best_match


def query_feedback_collection(query: str, similarity_threshold: float = 0.75, top_k: int = 5) -> Optional[Dict]:
    """Directly query the feedback_qa ChromaDB collection for corrections.

    Unlike find_feedback_match() which only checks already-retrieved chunks,
    this function independently queries the feedback_qa collection to find
    user-validated answers (including corrections from negative feedback).

    Returns:
        Dictionary with {question, answer, source, username, similarity} if found,
        None otherwise.
    """
    try:
        import chromadb

        settings = get_settings()
        cfg = settings.chroma
        url = cfg.http_url
        host = url.replace("http://", "").replace("https://", "").split(":")[0]
        port = int(url.split(":")[-1])
        client = chromadb.HttpClient(host=host, port=port)

        # Try to get the feedback_qa collection
        feedback_name = cfg.feedback_collection or "feedback_qa_mxbai_embed_large"
        try:
            collection = client.get_collection(feedback_name)
        except Exception as _exc:  # broad catch — resilience at boundary  # narrowed
            return None

        if collection.count() == 0:
            return None

        # Query using ONE embedding call (via ChromaDB's built-in embedding)
        from vectorstore import get_embeddings_model
        embeddings = get_embeddings_model()
        query_embedding = embeddings.embed_query(query)

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=min(top_k, collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        if not results or not results["documents"] or not results["documents"][0]:
            return None

        best_match = None
        best_similarity = 0.0

        for doc, metadata, distance in zip(
            results["documents"][0],
            results["metadatas"][0],
            results["distances"][0],
        ):
            question, answer = extract_qa_from_feedback_chunk(doc)
            if not question or not answer:
                continue

            # Use ChromaDB distance directly (no extra embedding calls)
            similarity = max(0, 1.0 - distance)

            if similarity > best_similarity and similarity >= similarity_threshold:
                best_similarity = similarity
                source = metadata.get("source", "feedback://unknown")
                username = source.replace("feedback://", "").split("/")[0] if "/" in source else metadata.get("username", "unknown")
                best_match = {
                    "question": question,
                    "answer": answer,
                    "source": source,
                    "username": username,
                    "similarity": similarity,
                }

        if best_match:
            logger.info(f"[FEEDBACK DIRECT] Match found: {best_match['similarity']:.2f} for: {best_match['question'][:50]}...")

        return best_match

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[FEEDBACK DIRECT] Query failed: {exc}")
        return None


def format_feedback_response(feedback_match: Dict) -> str:
    """
    Format a feedback match for presentation to the user.

    Args:
        feedback_match: Dictionary from find_feedback_match()

    Returns:
        Formatted markdown string
    """
    question = feedback_match["question"]
    answer = feedback_match["answer"]
    username = feedback_match["username"]
    similarity = feedback_match["similarity"]

    response = f"""✨ **Found Previously Validated Answer** (👍 by {username})

**Your Question:**
{question}

**Answer:**
{answer}

---
*This answer was previously marked as helpful with {int(similarity * 100)}% query match.*
"""

    return response


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Test feedback chunk parsing
    test_chunk = {
        "text": "Q: What is TERM in Splunk?\nA: TERM() is a search optimization directive...",
        "source": "feedback://john/abc123def456"
    }

    q, a = extract_qa_from_feedback_chunk(test_chunk["text"])
    print(f"Q: {q}")
    print(f"A: {a}")

    # Test similarity matching
    chunks = [test_chunk]
    query = "what is TERM directive in splunk"
    match = find_feedback_match(chunks, query, similarity_threshold=0.5)

    if match:
        print("\n" + format_feedback_response(match))
    else:
        print("No feedback match found")
