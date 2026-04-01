"""
Feedback Guardrails - Use feedback to guide LLM responses
"""
import logging
try:
    from vectorstore import ensure_feedback_store
except ImportError:
    ensure_feedback_store = None

logger = logging.getLogger(__name__)


def extract_feedback_guardrails(query: str, max_examples: int = 4, similarity_threshold: float = 0.60) -> str:
    """
    Extract relevant feedback examples to use as guardrails in the prompt.

    ONLY returns guardrails if the query is sufficiently similar to past feedback.
    This prevents injecting irrelevant feedback into every query.

    Args:
        query: User's question
        max_examples: Maximum number of feedback examples to include
        similarity_threshold: Minimum similarity (0-1) required to include feedback
                              Default 0.60 = include if query is reasonably similar

    Returns:
        Formatted guardrail text to prepend to the prompt (empty if no relevant matches)
    """
    try:
        if ensure_feedback_store is None:
            return ""
        feedback_store = ensure_feedback_store()
        if not feedback_store:
            return ""

        # Search feedback collection for similar queries WITH SCORES
        try:
            results = feedback_store.similarity_search_with_score(query, k=max_examples)
        except (AttributeError, NotImplementedError):
            # Fallback: no score available, skip feedback entirely (be conservative)
            logger.debug("similarity_search_with_score not available, skipping feedback guardrails")
            return ""

        if not results:
            return ""

        # Filter by similarity threshold (lower distance = more similar)
        # ChromaDB returns distance, not similarity. For cosine: similarity = 1 - distance
        relevant_results = []
        for doc, distance in results:
            # Handle edge cases where distance might be unexpected
            if distance is None or distance < 0:
                continue
            similarity = max(0, 1 - distance)  # Clamp to [0, 1]
            if similarity >= similarity_threshold:
                relevant_results.append((doc, similarity))

        if not relevant_results:
            logger.debug(f"No feedback above threshold {similarity_threshold} for query: {query[:50]}...")
            return ""

        guardrails = []
        guardrails.append("\n## User Feedback Guardrails")
        guardrails.append("Based on similar past queries, users have validated these responses:\n")

        for i, (doc, similarity) in enumerate(relevant_results, 1):
            content = doc.page_content
            metadata = doc.metadata

            # Extract Q&A from content
            lines = content.split('\n')
            question_line = next((l for l in lines if l.startswith('Q:') or l.startswith('Question:')), None)
            answer_line = next((l for l in lines if l.startswith('A:') or l.startswith('Answer:')), None)

            if question_line and answer_line:
                question = question_line.split(':', 1)[1].strip()
                answer = answer_line.split(':', 1)[1].strip()

                guardrails.append(f"\n**Example {i} (User Approved, {int(similarity*100)}% match):**")
                guardrails.append(f"Q: {question}")
                guardrails.append(f"A: {answer}")

                # Add metadata if available
                if 'username' in metadata:
                    guardrails.append(f"(Validated by: {metadata['username']})")

        guardrails.append("\n**Important**: When answering the current question, prefer patterns and approaches similar to these validated examples.\n")

        logger.info(f"Including {len(relevant_results)} feedback guardrails for query: {query[:50]}...")
        return '\n'.join(guardrails)

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.error(f"Error extracting feedback guardrails: {e}")
        return ""


def extract_negative_feedback_warnings(query: str, max_warnings: int = 3, similarity_threshold: float = 0.55) -> str:
    """
    Extract negative feedback to warn about common mistakes.

    ONLY returns warnings if the query is sufficiently similar to past negative feedback.
    This prevents injecting irrelevant warnings into every query.

    Args:
        query: User's question
        max_warnings: Maximum number of warnings to include
        similarity_threshold: Minimum similarity (0-1) required to include warning
                              Default 0.55 = warn if query is somewhat similar

    Returns:
        Formatted warning text (empty if no relevant matches)
    """
    try:
        from negative_feedback import get_collection
    except ImportError:
        # Module not available - silently return empty
        return ""

    try:
        collection = get_collection()
        if not collection:
            return ""

        # Query negative feedback collection WITH DISTANCES
        results = collection.query(
            query_texts=[query],
            n_results=max_warnings,
            include=['documents', 'metadatas', 'distances']
        )

        if not results or not results['documents'] or not results['documents'][0]:
            return ""

        # Filter by similarity threshold
        # ChromaDB returns distances (lower = more similar). For cosine: similarity = 1 - distance
        distances = results.get('distances', [[]])[0]
        documents = results['documents'][0]
        metadatas = results['metadatas'][0]

        relevant_items = []
        for doc, meta, dist in zip(documents, metadatas, distances):
            similarity = 1 - dist if dist is not None else 0
            if similarity >= similarity_threshold:
                relevant_items.append((doc, meta, similarity))

        if not relevant_items:
            logger.debug(f"No negative feedback above threshold {similarity_threshold} for query: {query[:50]}...")
            return ""

        warnings = []
        warnings.append("\n## ⚠️ Common Mistakes to Avoid")
        warnings.append("Users have reported these answers as incorrect or unhelpful:\n")

        for i, (doc, metadata_list, similarity) in enumerate(relevant_items, 1):
            # Extract issue from metadata
            reason = metadata_list.get('reason', 'No reason provided')

            # Parse Q&A from document (format: "Question: ...\n\nBad Answer: ...")
            lines = doc.split('\n')
            question_line = next((l for l in lines if l.startswith('Question:') or l.startswith('Q:')), None)
            bad_answer_line = next((l for l in lines if l.startswith('Bad Answer:') or l.startswith('A:')), None)

            if question_line and bad_answer_line:
                question = question_line.split(':', 1)[1].strip()
                bad_answer = bad_answer_line.split(':', 1)[1].strip()

                warnings.append(f"\n**Avoid Pattern {i} ({int(similarity*100)}% similar):**")
                warnings.append(f"Similar Q: {question[:200]}...")
                warnings.append(f"❌ Wrong approach: {bad_answer[:200]}...")
                warnings.append(f"Issue: {reason}")

        warnings.append("\n**Important**: Ensure your answer doesn't repeat these mistakes.\n")

        logger.info(f"Including {len(relevant_items)} negative feedback warnings for query: {query[:50]}...")
        return '\n'.join(warnings)

    except ImportError:
        logger.warning("negative_feedback module not available")
        return ""
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.error(f"Error extracting negative feedback warnings: {e}")
        return ""


def build_enhanced_prompt(base_prompt: str, query: str, context: str) -> str:
    """
    Build an enhanced prompt with feedback guardrails.

    Args:
        base_prompt: Original system prompt
        query: User's question
        context: Retrieved context chunks

    Returns:
        Enhanced prompt with guardrails
    """
    # Extract positive examples (guardrails)
    positive_guardrails = extract_feedback_guardrails(query, max_examples=4)

    # Extract negative examples (warnings)
    negative_warnings = extract_negative_feedback_warnings(query, max_warnings=3)

    # Build enhanced prompt
    parts = [base_prompt]

    if positive_guardrails:
        parts.append(positive_guardrails)

    if negative_warnings:
        parts.append(negative_warnings)

    parts.append("\n## Context Chunks")
    parts.append(context)

    parts.append(f"\n## User Question\n{query}")

    return '\n'.join(parts)


# Example usage
if __name__ == "__main__":
    # Test extraction
    query = "How do I configure inputs.conf for monitoring files?"
    guardrails = extract_feedback_guardrails(query)
    print(guardrails)

    warnings = extract_negative_feedback_warnings(query)
    print(warnings)
