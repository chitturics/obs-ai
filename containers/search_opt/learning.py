"""
Feedback learning system: extract and apply optimization patterns from user feedback.
"""
import json
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .utils import _resolve_data_root, _load_analyzed_searches

logger = logging.getLogger(__name__)

_LEARNED_PATTERNS: List[Dict[str, Any]] = []


def _get_learned_patterns_path() -> Path:
    return _resolve_data_root() / "learned_patterns.json"


def _get_learned_patterns() -> List[Dict[str, Any]]:
    """Load learned patterns from disk."""
    global _LEARNED_PATTERNS
    if _LEARNED_PATTERNS:
        return _LEARNED_PATTERNS

    path = _get_learned_patterns_path()
    if path.exists():
        try:
            _LEARNED_PATTERNS = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            _LEARNED_PATTERNS = []
    return _LEARNED_PATTERNS


def _save_learned_patterns(patterns: List[Dict[str, Any]]) -> None:
    """Persist learned patterns."""
    global _LEARNED_PATTERNS
    _LEARNED_PATTERNS = patterns
    path = _get_learned_patterns_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(patterns, indent=2), encoding="utf-8")


def _extract_pattern_from_feedback(original: str, improved: str, notes: str) -> Optional[Dict[str, Any]]:
    """Extract a reusable pattern from original -> improved transformation."""
    original_lower = original.lower()
    improved_lower = improved.lower()

    pattern = None

    if "stats " in original_lower and "tstats" in improved_lower and "tstats" not in original_lower:
        pattern = {
            "type": "stats_to_tstats",
            "description": "Convert stats to tstats for indexed field aggregations",
            "condition": "query contains 'stats count' without eval-based fields",
        }
    elif "term(" in improved_lower and "term(" not in original_lower:
        term_match = re.search(r"term\s*\(\s*([^)]+)\s*\)", improved, re.IGNORECASE)
        if term_match:
            pattern = {
                "type": "add_term",
                "description": "Wrap literal string in TERM() for exact matching",
                "example_term": term_match.group(1),
                "condition": "query contains literal strings with special characters",
            }
    elif "prefix(" in improved_lower and "prefix(" not in original_lower:
        pattern = {
            "type": "add_prefix",
            "description": "Use PREFIX() for wildcard prefix matching",
            "condition": "query has prefix wildcard patterns",
        }
    elif "index=" in improved_lower and "index=" not in original_lower:
        idx_match = re.search(r"index\s*=\s*(\S+)", improved, re.IGNORECASE)
        if idx_match:
            pattern = {
                "type": "add_index",
                "description": "Specify explicit index instead of searching all",
                "example_index": idx_match.group(1),
                "condition": "query missing explicit index specification",
            }
    elif "index=*" in original_lower and "index=" in improved_lower and "index=*" not in improved_lower:
        pattern = {
            "type": "remove_wildcard_index",
            "description": "Replace index=* with specific index",
            "condition": "query uses index=* (very slow)",
        }
    elif "| join " in original_lower and "| join " not in improved_lower:
        pattern = {
            "type": "remove_join",
            "description": "Replace join with lookup or stats-based alternative",
            "condition": "query uses expensive join command",
        }
    elif "| transaction " in original_lower and "| transaction " not in improved_lower:
        pattern = {
            "type": "remove_transaction",
            "description": "Replace transaction with stats earliest/latest",
            "condition": "query uses expensive transaction command",
        }
    elif ("earliest=" in improved_lower or "latest=" in improved_lower) and \
         "earliest=" not in original_lower and "latest=" not in original_lower:
        pattern = {
            "type": "add_time_bounds",
            "description": "Add explicit time range to limit search scope",
            "condition": "query missing time constraints",
        }

    if pattern:
        pattern["learned_from_notes"] = notes
        pattern["learned_at"] = datetime.utcnow().isoformat() + "Z"

    return pattern


def learn_from_feedback() -> Dict[str, Any]:
    """Analyze all high-ranked feedback and extract reusable patterns."""
    analyzed = _load_analyzed_searches()
    patterns = _get_learned_patterns()
    existing_types = {p["type"] for p in patterns}

    new_patterns = []

    for name, data in analyzed.items():
        original = data.get("original_query", "")
        if not original:
            continue

        for feedback in data.get("feedback", []):
            if feedback.get("rank", 0) < 5:
                continue

            improved = feedback.get("improved_query", "")
            notes = feedback.get("notes", "")

            if not improved or improved == original:
                continue

            pattern = _extract_pattern_from_feedback(original, improved, notes)
            if pattern and pattern["type"] not in existing_types:
                pattern["source_search"] = name
                new_patterns.append(pattern)
                existing_types.add(pattern["type"])

    if new_patterns:
        patterns.extend(new_patterns)
        _save_learned_patterns(patterns)

    return {
        "existing_patterns": len(patterns) - len(new_patterns),
        "new_patterns_learned": len(new_patterns),
        "total_patterns": len(patterns),
        "pattern_types": list(existing_types),
    }


def apply_learned_patterns(query: str) -> List[Dict[str, Any]]:
    """Check if any learned patterns can be applied to a query."""
    patterns = _get_learned_patterns()
    query_lower = query.lower()
    suggestions = []

    for pattern in patterns:
        ptype = pattern.get("type", "")
        applicable = False

        if ptype == "stats_to_tstats":
            if "stats " in query_lower and "tstats" not in query_lower:
                applicable = True
        elif ptype == "add_term":
            if re.search(r'"[^"]+\.[^"]+"', query) and "term(" not in query_lower:
                applicable = True
        elif ptype == "add_prefix":
            if re.search(r'\w+\*', query) and "prefix(" not in query_lower:
                applicable = True
        elif ptype == "add_index":
            if "index=" not in query_lower:
                applicable = True
        elif ptype == "remove_wildcard_index":
            if "index=*" in query_lower:
                applicable = True
        elif ptype == "remove_join":
            if "| join " in query_lower:
                applicable = True
        elif ptype == "remove_transaction":
            if "| transaction " in query_lower:
                applicable = True
        elif ptype == "add_time_bounds":
            if "earliest=" not in query_lower and "latest=" not in query_lower:
                applicable = True

        if applicable:
            suggestions.append({
                "pattern_type": ptype,
                "description": pattern.get("description", ""),
                "learned_from": pattern.get("source_search", "user feedback"),
                "priority": 8,
            })

    return suggestions
