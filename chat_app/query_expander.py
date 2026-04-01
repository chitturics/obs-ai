"""
Query expansion for compound questions.

Handles queries asking about multiple concepts (e.g., "TERM & PREFIX")
by splitting into sub-queries and merging results.
"""
import re
from typing import List, Tuple
import logging

logger = logging.getLogger(__name__)


def detect_compound_query(query: str) -> Tuple[bool, List[str]]:
    """
    Detect if query asks about multiple concepts and split them.

    Args:
        query: User query

    Returns:
        (is_compound, sub_queries)

    Examples:
        "TERM & PREFIX" → (True, ["TERM", "PREFIX"])
        "TERM and PREFIX" → (True, ["TERM", "PREFIX"])
        "TERM vs PREFIX" → (True, ["TERM", "PREFIX"])
        "just TERM" → (False, ["just TERM"])
    """
    # Patterns that indicate compound queries
    compound_patterns = [
        r'\b(and|&|\+|with)\b',  # "TERM and PREFIX", "TERM & PREFIX"
        r'\b(vs|versus|or)\b',    # "TERM vs PREFIX"
        r',',                      # "TERM, PREFIX, DEST"
    ]

    query_lower = query.lower()

    # Check if any compound pattern matches
    is_compound = any(re.search(pattern, query_lower) for pattern in compound_patterns)

    if not is_compound:
        return False, [query]

    # Split the query into concepts
    # Common SPL commands/functions to preserve

    # Extract the main concepts being asked about
    concepts = []

    # Method 1: Split on common separators
    separators = r'(?:\s+(?:and|&|\+|with|vs|versus|or)\s+|,\s*)'
    parts = re.split(separators, query, flags=re.IGNORECASE)

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Skip common connecting words
        if part.lower() in ['and', '&', '+', 'with', 'vs', 'versus', 'or']:
            continue

        # Any meaningful fragment (2+ chars, not just stopwords) is a concept
        if len(part) >= 2 and part.lower() not in ('the', 'is', 'a', 'an', 'of', 'in', 'to'):
            concepts.append(part)

    if len(concepts) > 1:
        # Build sub-queries preserving the context
        base_context = query_lower

        # Remove the concepts from base context to get the question structure
        for concept in concepts:
            base_context = re.sub(re.escape(concept), '', base_context, flags=re.IGNORECASE)

        # Clean up base context
        base_context = re.sub(r'\s+', ' ', base_context).strip()
        base_context = re.sub(r'(?:and|&|\+|with|vs|versus|or)\s*$', '', base_context, flags=re.IGNORECASE).strip()

        # Generate sub-queries
        sub_queries = []
        for concept in concepts:
            if base_context:
                sub_query = f"{base_context} {concept}".strip()
            else:
                sub_query = concept
            sub_queries.append(sub_query)

        logger.info(f"Expanded compound query into {len(sub_queries)} sub-queries: {sub_queries}")
        return True, sub_queries

    return False, [query]


def merge_chunks_from_subqueries(
    chunks_per_query: List[List[dict]],
    k: int = 10
) -> List[dict]:
    """
    Merge chunks from multiple sub-queries, ensuring coverage of all concepts.

    Args:
        chunks_per_query: List of chunk lists, one per sub-query
        k: Total number of chunks to return

    Returns:
        Merged and deduplicated chunk list

    Strategy:
        - Round-robin selection from each sub-query
        - Deduplicate by content fingerprint
        - Ensure at least 1-2 chunks from each concept
    """
    if not chunks_per_query:
        return []

    if len(chunks_per_query) == 1:
        return chunks_per_query[0][:k]

    merged = []
    seen_fingerprints = set()

    # Calculate minimum chunks per query to ensure coverage
    min_per_query = max(1, k // len(chunks_per_query))

    # First pass: Get minimum from each query
    for chunk_list in chunks_per_query:
        for chunk in chunk_list[:min_per_query]:
            fingerprint = chunk.get('metadata', {}).get('fingerprint') or chunk.get('page_content', '')[:100]
            if fingerprint not in seen_fingerprints:
                merged.append(chunk)
                seen_fingerprints.add(fingerprint)
                if len(merged) >= k:
                    return merged

    # Second pass: Round-robin to fill remaining slots
    max_len = max(len(chunks) for chunks in chunks_per_query)

    for i in range(min_per_query, max_len):
        for chunk_list in chunks_per_query:
            if i < len(chunk_list):
                chunk = chunk_list[i]
                fingerprint = chunk.get('metadata', {}).get('fingerprint') or chunk.get('page_content', '')[:100]
                if fingerprint not in seen_fingerprints:
                    merged.append(chunk)
                    seen_fingerprints.add(fingerprint)
                    if len(merged) >= k:
                        return merged

    return merged


def enhance_prompt_for_compound_query(concepts: List[str], base_prompt: str) -> str:
    """
    Enhance LLM prompt to ensure all concepts are addressed.

    Args:
        concepts: List of concepts from sub-queries
        base_prompt: Original prompt template

    Returns:
        Enhanced prompt
    """
    if len(concepts) <= 1:
        return base_prompt

    concepts_str = ", ".join(f"**{c}**" for c in concepts)

    addition = f"\n\n**CRITICAL**: The user asked about multiple concepts: {concepts_str}. " \
               f"You MUST address EACH concept separately. If context is missing for any concept, " \
               f"say so explicitly rather than ignoring it."

    return base_prompt + addition


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    test_queries = [
        "tstats with TERM & PREFIX",
        "TERM and PREFIX in SPL",
        "difference between TERM vs PREFIX",
        "what is props.conf and transforms.conf",
        "just TERM",
        "TERM, PREFIX, and DEST commands",
    ]

    for query in test_queries:
        is_compound, sub_queries = detect_compound_query(query)
        print(f"\nQuery: {query}")
        print(f"  Compound: {is_compound}")
        print(f"  Sub-queries: {sub_queries}")
