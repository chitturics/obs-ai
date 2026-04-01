"""
Organization-specific context awareness for intelligent result interpretation.

This module provides domain knowledge about the organization's Splunk deployment
structure, app types, and organizational patterns.
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Data constants and type definitions extracted to keep file under 600 lines
from chat_app.obsai_context_data import (  # noqa: F401
    AppContext,
    UI_APPS, TA_APPS, BA_APPS, IA_APPS, GENERAL_APPS, ALL_APP_CONTEXTS,
    APP_TYPE_PATTERNS, CONFIG_FILE_TYPES, STANZA_TYPE_PATTERNS,
    TSTATS_PATTERNS, INDEXED_TOKEN_KNOWLEDGE,
)

# CONTEXT EXTRACTION
# =====================================================================

def extract_app_context(file_path: str) -> Optional[AppContext]:
    """
    Extract app context from file path.

    Args:
        file_path: Full file path (e.g., "/repo/UIs/org-es/local/savedsearches.conf")

    Returns:
        AppContext if recognized, None otherwise
    """
    if not file_path:
        return None

    # Try each app type pattern
    for app_type, pattern in APP_TYPE_PATTERNS.items():
        match = pattern.search(file_path)
        if match:
            if app_type == "_general":
                return GENERAL_APPS["_general"]

            # Extract app name
            app_name = match.group(1) if match.groups() else None
            if not app_name:
                continue

            # Look up specific app context
            app_name_lower = app_name.lower()

            # Try exact match first
            if app_name_lower in ALL_APP_CONTEXTS:
                return ALL_APP_CONTEXTS[app_name_lower]

            # Try wildcard match (e.g., TA-* for unknown TAs)
            wildcard_key = f"{app_type}-*"
            if wildcard_key in ALL_APP_CONTEXTS:
                # Create dynamic context for unknown app
                template = ALL_APP_CONTEXTS[wildcard_key]
                return AppContext(
                    app_name=app_name,
                    app_type=template.app_type,
                    category=template.category,
                    description=f"{template.description} ({app_name})",
                    deployment_target=template.deployment_target,
                    typical_contents=template.typical_contents,
                )

    return None


def interpret_config_file(file_path: str, stanza_name: Optional[str] = None) -> str:
    """
    Generate human-readable interpretation of a config file based on its context.

    Args:
        file_path: Full file path
        stanza_name: Optional stanza name from the file

    Returns:
        Natural language interpretation
    """
    app_context = extract_app_context(file_path)

    # Extract config file type
    config_type = None
    for conf_file, description in CONFIG_FILE_TYPES.items():
        if conf_file in file_path.lower():
            config_type = conf_file
            break

    # Build interpretation
    parts = []

    # App context
    if app_context:
        if app_context.app_type == "_general":
            parts.append(
                f"This is in **{app_context.app_name}** - configs that deploy to "
                f"**{app_context.deployment_target}** (entire environment)."
            )
        else:
            parts.append(
                f"This is in **{app_context.app_name}** ({app_context.app_type}), "
                f"a **{app_context.category}** app."
            )
            parts.append(f"Deploys to: **{app_context.deployment_target}**.")

    # Config file type
    if config_type:
        parts.append(f"The file **{config_type}** contains {CONFIG_FILE_TYPES[config_type]}.")

    # Stanza interpretation
    if stanza_name:
        stanza_type = interpret_stanza_type(stanza_name)
        if stanza_type:
            parts.append(f"The stanza `{stanza_name}` is a **{stanza_type}**.")

    # App-specific context
    if app_context:
        if app_context.app_type == "TA":
            parts.append(
                "Technology Add-ons (TAs) focus on **data ingestion** - "
                "getting data INTO Splunk and parsing it correctly."
            )
            if config_type == "savedsearches.conf":
                parts.append(
                    "Saved searches in a TA are typically used to **generate lookups** "
                    "or **normalize data** for CIM compliance."
                )
        elif app_context.app_type == "UI":
            if config_type == "savedsearches.conf":
                parts.append(
                    "Saved searches in a UI app are typically **user-facing reports**, "
                    "**dashboards**, or **alerts** for monitoring."
                )
        elif app_context.app_type == "_general":
            parts.append(
                "Since this is in _general, changes here affect the **entire Splunk deployment** - "
                "use with caution!"
            )

    return " ".join(parts) if parts else "Configuration file in organization Splunk environment."


def interpret_stanza_type(stanza_name: str) -> Optional[str]:
    """
    Interpret what type of stanza this is based on its name.

    Args:
        stanza_name: Stanza name (e.g., "[WinEventLog://Application]")

    Returns:
        Human-readable stanza type
    """
    if not stanza_name:
        return None

    for pattern, description in STANZA_TYPE_PATTERNS.items():
        if re.match(pattern, stanza_name, re.IGNORECASE):
            return description

    # Generic saved search detection
    if not stanza_name.startswith("[") and "://" not in stanza_name:
        return "saved search definition"

    return None


# =====================================================================
# UNIT_ID AND REGION AWARENESS
# =====================================================================

# Unit ID: 3-4 char identifier for specific department (e.g., dept01, dept02, unit_a)
# Region: Regional grouping (1st-11th, hq, central)

REGION_PATTERNS = re.compile(
    r'\b(1st|2nd|3rd|4th|5th|6th|7th|8th|9th|10th|11th|hq|central)\s+region\b',
    re.IGNORECASE
)

UNIT_ID_PATTERN = re.compile(
    r'\b(unit_id[=\s:]+([a-z]{3,4})|U\d{3,4})\b',
    re.IGNORECASE
)


def extract_unit_id_from_query(query: str) -> Optional[str]:
    """Extract unit_id from query (e.g., 'dept01', 'dept02', 'unit_a')."""
    query_lower = query.lower()

    # Pattern: unit_id=dept01 or unit_id: dept01
    match = re.search(r'unit_id[=:\s]+([a-z0-9_]{3,8})', query_lower)
    if match:
        return match.group(1)

    # Pattern: U123 or U1234
    match = re.search(r'\bU(\d{3,4})\b', query)
    if match:
        return f"U{match.group(1)}"

    # Pattern: standalone department codes
    # Common department/unit abbreviations
    dept_codes = ["dept01", "dept02", "dept03", "unit_a", "unit_b", "unit_c", "unit_d"]
    for code in dept_codes:
        if code in query_lower:
            return code

    return None


def extract_region_from_query(query: str) -> Optional[str]:
    """Extract region from query (e.g., '2nd', '9th', 'hq')."""
    match = REGION_PATTERNS.search(query)
    if match:
        return match.group(1).lower()

    # Also check for just numbers (e.g., "2nd region" or "region 2")
    region_num = re.search(r'\b(region\s+)?(\d+)(st|nd|rd|th)?\b', query.lower())
    if region_num:
        num = region_num.group(2)
        try:
            num_int = int(num)
            if 1 <= num_int <= 11:
                # Return correct ordinal suffix
                if num_int == 1:
                    return "1st"
                elif num_int == 2:
                    return "2nd"
                elif num_int == 3:
                    return "3rd"
                else:
                    return f"{num_int}th"
        except ValueError:
            pass  # Invalid number, continue

    return None


# =====================================================================
# SCORING BOOST BASED ON CONTEXT
# =====================================================================

def calculate_context_boost(
    query: str,
    file_path: str,
    stanza_name: Optional[str] = None,
    config_type: Optional[str] = None,
    metadata: Optional[dict] = None
) -> tuple[int, str]:
    """
    Calculate relevance boost based on organization context awareness.

    This function understands:
    - App types (UIs, TAs, BAs, _general)
    - Deployment targets (search heads, indexers, forwarders)
    - Config file types (savedsearches, inputs, etc.)
    - Unit IDs and regions for multi-tenant scoping

    Args:
        query: User's query
        file_path: File path of the chunk
        stanza_name: Stanza name if available
        config_type: Config file type if known
        metadata: Additional metadata (unit_id, region, etc.)

    Returns:
        (boost_score, reason) tuple
    """
    # Cache lowercase versions for performance
    query_lower = query.lower()
    file_path_lower = file_path.lower() if file_path else ""
    stanza_lower = stanza_name.lower() if stanza_name else ""

    boost = 0
    reasons = []

    # Extract app context
    app_context = extract_app_context(file_path)
    if not app_context:
        return 0, ""

    # Query mentions specific app name
    if app_context.app_name.lower() in query_lower:
        boost += 25
        reasons.append(f"query mentions app '{app_context.app_name}'")

    # Query asks about saved searches + file is savedsearches.conf
    if "saved search" in query_lower or "savedsearches" in query_lower:
        if "savedsearches.conf" in file_path.lower():
            boost += 15
            reasons.append("saved search query + savedsearches.conf file")

            # Extra boost for TA saved searches if query mentions "lookup" or "normalize"
            if app_context.app_type == "TA":
                if "lookup" in query_lower or "normalize" in query_lower or "cim" in query_lower:
                    boost += 10
                    reasons.append("TA saved search for lookup/normalization")

    # Query asks about inputs + file is inputs.conf
    if any(kw in query_lower for kw in ["input", "ingestion", "data source", "monitor"]):
        if "inputs.conf" in file_path.lower():
            boost += 15
            reasons.append("input query + inputs.conf file")

            # TAs are the authoritative source for inputs
            if app_context.app_type == "TA":
                boost += 10
                reasons.append("TA is primary source for data inputs")

    # Query mentions "enterprise security" or "ES"
    if "enterprise security" in query_lower or " es " in query_lower or query_lower.startswith("es "):
        if app_context.app_name == "org-es":
            boost += 20
            reasons.append("ES query + org-es app")

    # Query mentions "itsi" or "service intelligence"
    if "itsi" in query_lower or "service intelligence" in query_lower or "kpi" in query_lower:
        if app_context.app_name == "org-itsi":
            boost += 20
            reasons.append("ITSI query + org-itsi app")

    # Query mentions "machine learning" or "mltk"
    if "machine learning" in query_lower or "mltk" in query_lower or " ml " in query_lower:
        if app_context.app_name == "org-mltk":
            boost += 20
            reasons.append("ML query + org-mltk app")

    # Query asks about "dashboard" or "user search"
    if "dashboard" in query_lower or "user search" in query_lower or "user facing" in query_lower:
        if app_context.app_name == "org-search":
            boost += 15
            reasons.append("user search query + org-search app")

    # Query asks about global/deployment-wide settings
    if any(kw in query_lower for kw in ["global", "all", "everywhere", "deployment"]):
        if app_context.app_type == "_general":
            boost += 20
            reasons.append("global query + _general deployment")

    # Stanza-specific boosts (using cached stanza_lower)
    if stanza_name:
        # Query mentions specific input type
        if "wineventlog" in query_lower and "wineventlog://" in stanza_lower:
            boost += 15
            reasons.append("WinEventLog query + WinEventLog stanza")

        if "monitor" in query_lower and "monitor://" in stanza_lower:
            boost += 15
            reasons.append("monitor query + monitor stanza")

        if "script" in query_lower and "script://" in stanza_lower:
            boost += 15
            reasons.append("script query + scripted input stanza")

    # Category-based boosts
    if app_context.category:
        category_lower = app_context.category.lower()

        # Query mentions the category
        if category_lower in query_lower:
            boost += 10
            reasons.append(f"query mentions category '{app_context.category}'")

    # UNIT_ID AND REGION SCOPING (multi-tenant awareness)
    query_unit_id = extract_unit_id_from_query(query)
    query_region = extract_region_from_query(query)

    if metadata:
        chunk_unit_id = metadata.get("unit_id")
        chunk_region = metadata.get("region")

        # Check unit_id matching (most specific) - INDEPENDENT CHECK
        if query_unit_id:
            if chunk_unit_id:
                if query_unit_id.lower() == chunk_unit_id.lower():
                    boost += 30
                    reasons.append(f"exact unit_id match: {query_unit_id}")
                else:
                    # Different unit_id - significant penalty
                    boost -= 20
                    reasons.append(f"unit_id mismatch: query={query_unit_id}, chunk={chunk_unit_id}")
            else:
                # Query has unit_id but chunk is generic
                boost -= 5
                reasons.append("query has unit_id but chunk is generic")

        # Check region matching (regional scope) - INDEPENDENT CHECK
        if query_region:
            if chunk_region:
                if query_region.lower() == chunk_region.lower():
                    boost += 15
                    reasons.append(f"region match: {query_region}")
                else:
                    # Different region - moderate penalty
                    boost -= 10
                    reasons.append(f"region mismatch: query={query_region}, chunk={chunk_region}")
            else:
                # Query has region but chunk is generic
                boost -= 3
                reasons.append("query has region but chunk is generic")

    # Query mentions "all departments" or "all regions" - boost generic content
    if any(kw in query_lower for kw in ["all departments", "all regions", "every department", "global"]):
        if metadata and not metadata.get("unit_id") and not metadata.get("region"):
            boost += 10
            reasons.append("global query + generic content (applies to all)")

    # TSTATS AND INDEXED TOKEN AWARENESS (using cached file_path_lower)
    if "tstats" in query_lower or "term(" in query_lower:
        # Detect tstats usage patterns
        tstats_info = detect_tstats_usage(query)

        # Boost content about tstats if query asks about it
        if "tstats" in file_path_lower or "indexed" in file_path_lower:
            boost += 15
            reasons.append("tstats query + tstats/indexed content")

        # Boost if chunk discusses TERM() and query uses it
        if tstats_info["uses_term"]:
            if "term(" in stanza_lower or "term" in file_path_lower:
                boost += 10
                reasons.append("TERM() usage + TERM()-related content")

        # Boost spl_commands collection for tstats questions
        if "spl_commands" in file_path_lower:
            boost += 12
            reasons.append("tstats query + SPL command docs")

    # Query asks about indexed fields or tokens
    if any(kw in query_lower for kw in ["indexed field", "indexed token", "major breaker", "minor breaker"]):
        if "field" in file_path_lower or "index" in file_path_lower or "token" in file_path_lower:
            boost += 15
            reasons.append("indexed field/token query + relevant content")

    # Query asks about performance optimization
    if any(kw in query_lower for kw in ["performance", "optimize", "faster", "acceleration"]):
        if "tstats" in file_path_lower or "acceleration" in file_path_lower:
            boost += 10
            reasons.append("performance query + tstats/acceleration content")

        # Data model acceleration app
        if app_context and app_context.app_name == "org-dma":
            boost += 15
            reasons.append("performance query + data model acceleration app")

    reason_str = "; ".join(reasons) if reasons else ""
    return boost, reason_str


# =====================================================================
# TSTATS AND INDEXED TOKEN AWARENESS
# =====================================================================

# Knowledge from "Fields, Indexed Tokens, and You" (Splunk Conf 2016/2017)


def detect_tstats_usage(query: str) -> dict:
    """
    Detect and analyze tstats usage in query.

    Returns dict with:
        - has_tstats: bool
        - uses_term: bool
        - has_indexed_fields: bool
        - issues: list of potential issues
        - suggestions: list of improvements
    """
    query_lower = query.lower()

    result = {
        "has_tstats": bool(TSTATS_PATTERNS["tstats_basic"].search(query)),
        "uses_term": bool(TSTATS_PATTERNS["tstats_with_term"].search(query)),
        "has_indexed_fields": bool(TSTATS_PATTERNS["indexed_field"].search(query)),
        "issues": [],
        "suggestions": [],
    }

    if result["has_tstats"]:
        # Check if TERM() is used with indexed fields
        if result["has_indexed_fields"] and not result["uses_term"]:
            result["suggestions"].append(
                "Consider using TERM() with indexed fields (sourcetype, source, host) for better performance"
            )

        # Check for wildcards inside TERM() - more robust detection
        term_with_wildcard = re.search(r'TERM\([^)]*\*[^)]*\)', query, re.IGNORECASE)
        if term_with_wildcard:
            result["issues"].append(
                "TERM() doesn't support wildcards - use prefix matching instead (e.g., TERM(win) matches win*)"
            )

        # Check if piping into tstats
        if not query.strip().startswith("|"):
            if "| tstats" in query_lower:
                # Check if there's content before | tstats
                before_tstats = query_lower.split("| tstats")[0].strip()
                if before_tstats and not before_tstats.startswith("|"):
                    result["issues"].append(
                        "Cannot pipe regular search into tstats - tstats must be the first command"
                    )

    return result


# =====================================================================
# QUERY INTERPRETATION
# =====================================================================

def interpret_query_intent(query: str) -> dict:
    """
    Interpret what the user is asking about in organization context.

    Args:
        query: User's query

    Returns:
        Dictionary with interpretation details including tstats analysis
    """
    query_lower = query.lower()

    result = {
        "app_focus": None,
        "config_type": None,
        "intent": None,
        "deployment_scope": None,
        "tstats_usage": None,
    }

    # Analyze tstats usage if present
    if "tstats" in query_lower or "term(" in query_lower:
        result["tstats_usage"] = detect_tstats_usage(query)

    # Detect app focus
    for app_name, context in ALL_APP_CONTEXTS.items():
        if app_name.lower() in query_lower:
            result["app_focus"] = context
            break

    # Detect config type focus
    for conf_file, description in CONFIG_FILE_TYPES.items():
        if conf_file.replace(".conf", "") in query_lower:
            result["config_type"] = conf_file
            break

    # Detect intent
    if any(kw in query_lower for kw in ["tstats", "term(", "indexed field", "indexed token"]):
        result["intent"] = "tstats_performance_query"
    elif any(kw in query_lower for kw in ["saved search", "savedsearches", "alert", "report", "dashboard"]):
        result["intent"] = "saved_search_query"
    elif any(kw in query_lower for kw in ["input", "ingest", "data source", "monitor"]):
        result["intent"] = "data_input_query"
    elif any(kw in query_lower for kw in ["field extraction", "props", "parsing"]):
        result["intent"] = "field_extraction_query"
    elif any(kw in query_lower for kw in ["lookup", "transform"]):
        result["intent"] = "lookup_transformation_query"
    elif any(kw in query_lower for kw in ["index", "retention", "storage"]):
        result["intent"] = "index_config_query"
    elif any(kw in query_lower for kw in ["role", "permission", "capability", "access"]):
        result["intent"] = "rbac_query"
    elif any(kw in query_lower for kw in ["performance", "optimize", "acceleration", "faster"]):
        result["intent"] = "performance_optimization_query"

    # Detect deployment scope
    if any(kw in query_lower for kw in ["global", "everywhere", "all", "deployment"]):
        result["deployment_scope"] = "_general"
    elif any(kw in query_lower for kw in ["search head", "sh "]):
        result["deployment_scope"] = "search_heads"
    elif any(kw in query_lower for kw in ["indexer", "idx"]):
        result["deployment_scope"] = "indexers"
    elif any(kw in query_lower for kw in ["forwarder", "uf", "hf"]):
        result["deployment_scope"] = "forwarders"

    return result


# =====================================================================
# EXPORTS
# =====================================================================

__all__ = [
    "AppContext",
    "extract_app_context",
    "interpret_config_file",
    "interpret_stanza_type",
    "calculate_context_boost",
    "interpret_query_intent",
    "extract_unit_id_from_query",
    "extract_region_from_query",
    "detect_tstats_usage",
    "INDEXED_TOKEN_KNOWLEDGE",
    "ALL_APP_CONTEXTS",
    "UI_APPS",
    "TA_APPS",
    "GENERAL_APPS",
]
