"""
Sequential Query Decomposition Planner.

Detects multi-step queries that require sequential reasoning
(as opposed to parallel sub-queries) and produces an ordered
execution plan.

Examples of sequential queries:
- "find all failed logins and then check if those users also had successful logins"
- "first get the top 10 sourcetypes by volume, then show me their event counts over time"
- "show me the errors, then correlate them with the deployment events"
"""
import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Patterns that indicate sequential/dependent steps
_SEQUENTIAL_PATTERNS = [
    r'\bthen\b',
    r'\bafter that\b',
    r'\bnext\b',
    r'\bfollowed by\b',
    r'\bonce (?:you|we|that)\b',
    r'\bfirst\b.*\bthen\b',
    r'\bstep\s*\d',
    r'\bcorrelate\b.*\bwith\b',
    r'\bcompare\b.*\bwith\b',
    r'\bcheck if\b.*\balso\b',
    r'\bbased on\b.*\bresults?\b',
    r'\bfrom (?:the|those) results?\b',
    r'\busing (?:the|those) results?\b',
]

# Splitters for sequential steps
_STEP_SPLITTERS = [
    r'\.\s*(?:then|next|after that|also)\s+',
    r'(?:,?\s*)?(?:and\s+)?then\s+',
    r'(?:,?\s*)?(?:and\s+)?after that\s+',
    r'(?:,?\s*)?(?:and\s+)?next\s+',
    r'\bfirst\b(.*?)\bthen\b',
    r';\s*',
]


@dataclass
class QueryStep:
    """A single step in a sequential query plan."""
    description: str
    depends_on_previous: bool = False
    retrieval_query: str = ""


@dataclass
class QueryPlanResult:
    """Result of query decomposition planning."""
    is_sequential: bool = False
    steps: List[QueryStep] = field(default_factory=list)
    original_query: str = ""


def detect_sequential_query(query: str) -> QueryPlanResult:
    """
    Detect if a query requires sequential execution steps.

    Returns a QueryPlanResult with ordered steps if sequential,
    or a single-step plan if not.
    """
    query_lower = query.lower().strip()

    # Check if any sequential pattern matches
    is_sequential = any(
        re.search(p, query_lower, re.IGNORECASE)
        for p in _SEQUENTIAL_PATTERNS
    )

    if not is_sequential:
        return QueryPlanResult(
            is_sequential=False,
            steps=[QueryStep(description=query, retrieval_query=query)],
            original_query=query,
        )

    # Try to split into steps
    steps = _split_into_steps(query)

    if len(steps) < 2:
        return QueryPlanResult(
            is_sequential=False,
            steps=[QueryStep(description=query, retrieval_query=query)],
            original_query=query,
        )

    return QueryPlanResult(
        is_sequential=True,
        steps=steps,
        original_query=query,
    )


def _split_into_steps(query: str) -> List[QueryStep]:
    """Split a sequential query into ordered steps."""
    # Try "first X then Y" pattern
    first_then = re.match(
        r'(?:first\s+)(.+?)(?:\s*,?\s*then\s+)(.+)',
        query,
        re.IGNORECASE | re.DOTALL,
    )
    if first_then:
        step1 = first_then.group(1).strip().rstrip('.,;')
        step2 = first_then.group(2).strip().rstrip('.,;')
        return [
            QueryStep(description=step1, depends_on_previous=False, retrieval_query=step1),
            QueryStep(description=step2, depends_on_previous=True, retrieval_query=step2),
        ]

    # Try splitting on "then", "next", "after that"
    parts = re.split(
        r'(?:,?\s*)?(?:and\s+)?(?:then|next|after that|followed by)\s+',
        query,
        flags=re.IGNORECASE,
    )
    parts = [p.strip().rstrip('.,;') for p in parts if p.strip()]

    if len(parts) >= 2:
        steps = []
        for i, part in enumerate(parts):
            steps.append(QueryStep(
                description=part,
                depends_on_previous=(i > 0),
                retrieval_query=part,
            ))
        return steps

    # Try splitting on semicolons
    parts = [p.strip() for p in query.split(';') if p.strip()]
    if len(parts) >= 2:
        steps = []
        for i, part in enumerate(parts):
            steps.append(QueryStep(
                description=part,
                depends_on_previous=(i > 0),
                retrieval_query=part,
            ))
        return steps

    return [QueryStep(description=query, retrieval_query=query)]


async def execute_sequential_retrieval(
    steps: List[QueryStep],
    search_func,
    store,
    k: int = 30,
    profile: Optional[str] = None,
    weight_map=None,
    user_settings=None,
) -> Tuple[List[dict], List[str]]:
    """
    Execute sequential retrieval steps, where each step can build
    on context from previous steps.

    Args:
        steps: Ordered list of query steps.
        search_func: The async-compatible search function.
        store: Vector store instance.
        k: Results per step.
        profile: Optional profile.
        weight_map: Optional weight map.
        user_settings: Optional user settings.

    Returns:
        Tuple of (merged_chunks, step_summaries).
    """
    import chainlit as cl

    all_chunks = []
    step_summaries = []

    for i, step in enumerate(steps):
        query = step.retrieval_query

        # If this step depends on previous results, enrich the query
        if step.depends_on_previous and all_chunks:
            # Extract key terms from previous results to enrich the query
            prev_context = _extract_key_terms(all_chunks[-min(5, len(all_chunks)):])
            if prev_context:
                query = f"{query} {prev_context}"

        try:
            chunks = await cl.make_async(search_func)(
                store, query, k=k // len(steps),
                profile=profile, weight_map_override=weight_map,
                user_settings=user_settings,
            )
            all_chunks.extend(chunks)
            step_summaries.append(f"Step {i+1}: '{step.description[:60]}' -> {len(chunks)} chunks")
            logger.info(f"[PLANNER] {step_summaries[-1]}")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning(f"[PLANNER] Step {i+1} failed: {exc}")
            step_summaries.append(f"Step {i+1}: '{step.description[:60]}' -> failed ({exc})")

    # Deduplicate by text hash
    seen = set()
    unique_chunks = []
    for chunk in all_chunks:
        text = chunk.get("text", "")
        h = hash(text[:200])
        if h not in seen:
            seen.add(h)
            unique_chunks.append(chunk)

    return unique_chunks[:k], step_summaries


def _extract_key_terms(chunks: List[dict], max_terms: int = 10) -> str:
    """Extract key terms from chunks for enriching subsequent queries."""
    terms = set()
    for chunk in chunks:
        text = chunk.get("text", "")
        # Extract field=value patterns
        for match in re.finditer(r'(\w+)\s*=\s*(\w+)', text):
            terms.add(match.group(0))
        # Extract Splunk commands
        for match in re.finditer(r'\|\s*(\w+)', text):
            terms.add(match.group(1))
        if len(terms) >= max_terms:
            break
    return " ".join(list(terms)[:max_terms])
