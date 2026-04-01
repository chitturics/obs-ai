"""
Query router handler for the Splunk Assistant.
"""
import re
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from context_builder import detect_compound_query
from chat_app.intent_classifier import IntentClassifier, RAW_SPL_PATTERNS

logger = logging.getLogger(__name__)

# Patterns for extracting SPL from user messages with instruction prefixes
# These match "optimize this spl:", "explain this query:", etc. and extract what follows
SPL_EXTRACTION_PATTERNS = [
    # "optimize this spl: <query>" or "optimize: <query>"
    r'(?:optimize|improve|speed up|make faster)\s*(?:this\s+)?(?:spl|query|search)?[:\s]+(.+)',
    # "explain this query: <query>"
    r'(?:explain|understand|break down)\s*(?:this\s+)?(?:spl|query|search)?[:\s]+(.+)',
    # "review this spl: <query>"
    r'(?:review|analyze|validate|check)\s*(?:this\s+)?(?:spl|query|search)?[:\s]+(.+)',
    # "score this query: <query>"
    r'(?:score|rate)\s*(?:this\s+)?(?:spl|query|search)?[:\s]+(.+)',
    # "annotate this spl: <query>"
    r'(?:annotate|comment)\s*(?:this\s+)?(?:spl|query|search)?[:\s]+(.+)',
    # "can you optimize: <query>" or "please optimize: <query>"
    r'(?:can you|could you|please)\s+(?:optimize|review|explain|check|analyze)\s*(?:this)?[:\s]+(.+)',
    # "here is my spl: <query>" or "my query is: <query>"
    r'(?:here is|here\'s|my)\s+(?:the\s+)?(?:spl|query|search)\s*(?:is)?[:\s]+(.+)',
    # Generic "spl:" or "query:" prefix
    r'^(?:spl|query|search)\s*:\s*(.+)',
]

@dataclass
class QueryPlan:
    """Execution plan for a user query."""
    intent: str = "general_qa"              # spl_generation, config_lookup, troubleshooting, repo_query, general_qa, meta_question, ingestion, clarification, saved_search_analysis, config_health_check, run_search, create_alert, cribl_pipeline, cribl_config, observability_metrics, observability_infra
    profile: str = "general"                # spl_expert, config_helper, troubleshooter, org_expert, cribl_expert, observability_expert, general
    skip_retrieval: bool = False            # True for meta-questions ("who are you")
    use_template_engine: bool = False       # True for tstats/TERM queries
    is_compound: bool = False               # True for multi-concept queries
    sub_queries: List[str] = field(default_factory=list)
    retrieval_collections: List[str] = field(default_factory=list)  # Ordered priority
    retrieval_k: int = 30                   # How many chunks to fetch
    # Search optimizer action: optimize, review, explain, score, annotate, auto, learn
    optimizer_action: Optional[str] = None  # None means skip optimizer
    optimizer_type: str = "auto"            # spl, nlp, sql - auto-detected if "auto"
    extracted_query: Optional[str] = None   # The actual SPL/query extracted from user input
    clarification_question: Optional[str] = None # The question to ask the user for clarification
    confidence: float = 0.5                 # 0.0-1.0 — how confident is the intent classification
    auto_explain: bool = False              # True when raw SPL is pasted without context
    episode_context: Optional[str] = None   # Enrichment from episodic memory (similar past queries)


intent_classifier = IntentClassifier()


def _trim_to_spl_start(text: str) -> str:
    """Trim leading non-SPL words from extracted text.

    If the text starts with natural-language words before the actual SPL
    (e.g., "optimize search: index=main ..."), strip everything up to the
    first SPL keyword (index=, sourcetype=, |, earliest=, search ...).
    """
    # Find the earliest position of an SPL keyword
    spl_start_re = re.compile(
        r'(?:index\s*=|sourcetype\s*=|\|\s*\w|earliest\s*=|latest\s*=)',
        re.IGNORECASE,
    )
    m = spl_start_re.search(text)
    if m and m.start() > 0:
        trimmed = text[m.start():].strip()
        if trimmed:
            return trimmed
    return text


def extract_spl_from_input(user_input: str) -> Optional[str]:
    """
    Extract the actual SPL query from a user message that may have instruction prefixes.

    Examples:
        "optimize this spl: index=main | stats count" -> "index=main | stats count"
        "explain: | tstats count" -> "| tstats count"
        "index=main | stats count" -> "index=main | stats count" (no prefix, return as-is if SPL)

    Returns:
        Extracted SPL query, or None if no SPL detected
    """
    text = user_input.strip()

    # Try extraction patterns first (for messages with instruction prefixes)
    for pattern in SPL_EXTRACTION_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
        if match:
            extracted = match.group(1).strip()
            # Verify the extracted part looks like SPL
            if any(re.search(p, extracted, re.IGNORECASE) for p in RAW_SPL_PATTERNS):
                # The extraction may still contain leading natural language
                # (e.g., "optimize search: index=main ..." captures "optimize search: index=main")
                # Try to find where the actual SPL starts
                extracted = _trim_to_spl_start(extracted)
                logger.debug(f"Extracted SPL from prefix pattern: {extracted[:100]}...")
                return extracted

    # If no extraction pattern matched, check if the entire input is raw SPL
    if any(re.search(p, text, re.IGNORECASE) for p in RAW_SPL_PATTERNS):
        # It's already raw SPL, but might have some prefix text before it
        # Try to find where the SPL starts (at index= or | or earliest=)
        spl_start_patterns = [
            r'((?:\||index\s*=|sourcetype\s*=|earliest\s*=|search\s+).+)',
        ]
        for pattern in spl_start_patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                extracted = match.group(1).strip()
                logger.debug(f"Extracted SPL from raw pattern: {extracted[:100]}...")
                return extracted
        # Fallback: return the whole thing
        return text

    return None


def route_query(user_input: str, user_settings: dict = None) -> QueryPlan:
    """
    Classify user intent and build an execution plan.

    Args:
        user_input: The user's message text.
        user_settings: User's chat settings dict.

    Returns:
        QueryPlan with routing decisions.
    """
    if user_settings is None:
        user_settings = {}

    word_count = len(user_input.split())
    search_depth = int(user_settings.get("search_depth", 5))

    plan = intent_classifier.classify(user_input, word_count)
    plan.retrieval_k = max(6, search_depth * 6)

    # Detect compound queries
    plan.is_compound, plan.sub_queries = detect_compound_query(user_input)

    # Extract the actual SPL query if optimizer is being used
    if plan.optimizer_action:
        plan.extracted_query = extract_spl_from_input(user_input)
        if plan.extracted_query:
            logger.debug(f"Extracted query for optimizer: {plan.extracted_query[:100]}...")

    return plan
