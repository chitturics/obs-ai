"""
Saved search analysis, feedback, and service statistics.
"""
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from shared.spl_knowledge_base import get_knowledge_base
from shared.spl_query_optimizer import SPLQueryOptimizer
from shared.spl_validator import SPLValidator

from .utils import (
    _SAVED_CACHE,
    _append_history,
    _get_analyzed_searches_path,
    _get_feedback_path,
    _load_analyzed_searches,
    _load_log_hints,
    _load_saved_searches,
    _resolve_data_root,
    _review_query,
    _save_analyzed_searches,
    get_custom_command_names,
    _load_all_macros,
)
from .config_manager import get_splunk_config_manager
from .optimizer import _optimize_query
from .analyzer import explain_query, score_query
from .learning import _get_learned_patterns, learn_from_feedback

logger = logging.getLogger(__name__)

# Safe lazy init — get_knowledge_base() now does I/O (doc enrichment)
# that can fail inside containers. Retry lazily on first use.
try:
    _knowledge_base = get_knowledge_base()
except Exception as _kb_err:
    logger.warning(f"Knowledge base init failed (will retry lazily): {_kb_err}")
    _knowledge_base = None


def _get_kb():
    """Safe accessor that retries if module-level init failed."""
    global _knowledge_base
    if _knowledge_base is None:
        try:
            _knowledge_base = get_knowledge_base()
        except Exception:
            pass
    return _knowledge_base


def analyze_all_saved_searches(force_reanalyze: bool = False) -> Dict[str, Any]:
    """Analyze all saved searches from savedsearches.conf files."""
    saved_searches = _load_saved_searches()
    analyzed = _load_analyzed_searches() if not force_reanalyze else {}

    updated_count = 0
    skipped_count = 0

    for search in saved_searches:
        name = search.get("name")
        if not name:
            continue

        if name in analyzed and not force_reanalyze:
            skipped_count += 1
            continue

        search_text = search.get("search_expanded") or search.get("search_raw")
        if not search_text:
            continue

        try:
            review, validation = _review_query(search_text)
            optimization = _optimize_query(search_text)
            explanation = explain_query(search_text)
            score_result = score_query(search_text)

            kb = _get_kb()
            kb_pipeline = kb.explain_pipeline(search_text) if kb else []
            kb_complexity = kb.calculate_query_complexity(search_text) if kb else {}
            human_summary = explanation.get("human_summary", "")

            analyzed[name] = {
                "name": name,
                "file": search.get("file"),
                "original_query": search_text,
                "macros_used": search.get("macros_used", []),
                "human_summary": human_summary,
                "complexity": kb_complexity.get("level", "unknown"),
                "analysis": {
                    "review": review,
                    "optimization": optimization,
                    "explanation": explanation.get("explanation") if explanation else None,
                    "detailed_stages": explanation.get("detailed_stages"),
                    "score": score_result.get("score") if score_result else None,
                    "anti_patterns": score_result.get("anti_patterns", []),
                    "optimization_opportunities": score_result.get("optimization_opportunities", []),
                },
                "optimized_query": optimization.get("optimized_query") if optimization.get("optimized") else None,
                "analyzed_at": datetime.utcnow().isoformat() + "Z",
                "feedback": [],
            }
            updated_count += 1
        except Exception as e:
            analyzed[name] = {
                "name": name,
                "original_query": search_text,
                "error": str(e),
                "analyzed_at": datetime.utcnow().isoformat() + "Z",
            }

    _save_analyzed_searches(analyzed)

    return {
        "total_searches": len(saved_searches),
        "analyzed": updated_count,
        "skipped": skipped_count,
        "stored_at": str(_get_analyzed_searches_path()),
    }


def get_analyzed_search(name: str) -> Dict[str, Any]:
    """Retrieve analysis for a specific saved search by name."""
    analyzed = _load_analyzed_searches()

    if name in analyzed:
        result = analyzed[name].copy()
        if result.get("feedback"):
            result["feedback"] = sorted(
                result["feedback"],
                key=lambda x: x.get("rank", 0),
                reverse=True
            )
        return result

    name_lower = name.lower()
    matches = []
    for key in analyzed:
        if name_lower in key.lower():
            matches.append(analyzed[key])

    if matches:
        return {"exact_match": False, "suggestions": matches[:5]}

    return {"error": f"Saved search '{name}' not found in analyzed data"}


def submit_search_feedback(
    name: str,
    improved_query: str,
    notes: str = "",
    user: str = "anonymous",
    rank: int = 0,
) -> Dict[str, Any]:
    """Submit user feedback with an improved version of a search."""
    analyzed = _load_analyzed_searches()

    if name not in analyzed:
        return {"error": f"Saved search '{name}' not found"}

    review, _ = _review_query(improved_query)
    score_result = score_query(improved_query)

    feedback_entry = {
        "improved_query": improved_query,
        "notes": notes,
        "user": user,
        "rank": rank,
        "validation": review,
        "score": score_result.get("score") if score_result else None,
        "submitted_at": datetime.utcnow().isoformat() + "Z",
    }

    if "feedback" not in analyzed[name]:
        analyzed[name]["feedback"] = []

    analyzed[name]["feedback"].append(feedback_entry)

    analyzed[name]["feedback"] = sorted(
        analyzed[name]["feedback"],
        key=lambda x: x.get("rank", 0),
        reverse=True
    )

    _save_analyzed_searches(analyzed)

    feedback_path = _get_feedback_path()
    _append_history(feedback_path, {"search_name": name, **feedback_entry})

    # Auto-trigger learning after high-ranked feedback
    learning_result = None
    if rank >= 5:
        try:
            learning_result = learn_from_feedback()
            logger.info(f"Auto-learning after feedback: {learning_result}")
        except Exception as e:
            logger.warning(f"Auto-learning after feedback failed: {e}")

    return {
        "success": True,
        "search_name": name,
        "feedback_count": len(analyzed[name]["feedback"]),
        "top_ranked_query": analyzed[name]["feedback"][0]["improved_query"] if analyzed[name]["feedback"] else None,
        "learning": learning_result,
    }


def list_analyzed_searches(limit: int = 100, sort_by: str = "name") -> Dict[str, Any]:
    """List all analyzed saved searches."""
    analyzed = _load_analyzed_searches()

    items = []
    for name, data in analyzed.items():
        score = 0
        if data.get("analysis", {}).get("score", {}).get("overall"):
            score = data["analysis"]["score"]["overall"]

        items.append({
            "name": name,
            "file": data.get("file"),
            "has_optimization": bool(data.get("optimized_query")),
            "score": score,
            "feedback_count": len(data.get("feedback", [])),
            "analyzed_at": data.get("analyzed_at"),
        })

    if sort_by == "score":
        items.sort(key=lambda x: x.get("score", 0), reverse=True)
    elif sort_by == "analyzed_at":
        items.sort(key=lambda x: x.get("analyzed_at", ""), reverse=True)
    else:
        items.sort(key=lambda x: x.get("name", "").lower())

    return {
        "total": len(items),
        "returned": min(limit, len(items)),
        "searches": items[:limit],
    }


def preload_caches() -> None:
    """Preload caches from disk on startup."""
    global _SAVED_CACHE

    saved_path = _resolve_data_root() / "savedsearch_index.json"
    if saved_path.exists():
        try:
            _SAVED_CACHE["savedsearches"] = json.loads(saved_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    analyzed_path = _get_analyzed_searches_path()
    if analyzed_path.exists():
        try:
            from .utils import _ANALYZED_CACHE
            _ANALYZED_CACHE.update(json.loads(analyzed_path.read_text(encoding="utf-8")))
        except Exception:
            pass

    try:
        _load_log_hints(_resolve_data_root() / "log_type_hints.csv")
    except Exception:
        pass

    try:
        config_mgr = get_splunk_config_manager()
        counts = config_mgr.load_all()
        logger.info(
            f"SplunkConfigManager loaded: "
            f"{counts['commands']} commands, "
            f"{counts['macros']} macros, "
            f"{counts['searches']} saved searches"
        )

        if not _SAVED_CACHE.get("savedsearches"):
            searches = list(config_mgr.get_searches().values())
            _SAVED_CACHE["savedsearches"] = searches

    except Exception as e:
        logger.warning(f"SplunkConfigManager failed, falling back to legacy loading: {e}")

        try:
            custom_cmds = get_custom_command_names()
            if custom_cmds:
                SPLValidator.register_custom_commands(custom_cmds)
                logger.info(f"Registered {len(custom_cmds)} custom commands (legacy)")
        except Exception as e2:
            logger.warning(f"Failed to load custom commands: {e2}")

        try:
            macros = _load_all_macros()
            if macros:
                SPLQueryOptimizer.register_macros(macros)
                logger.info(f"Registered {len(macros)} macros (legacy)")
        except Exception as e2:
            logger.warning(f"Failed to load macros: {e2}")

        try:
            if not _SAVED_CACHE.get("savedsearches"):
                _load_saved_searches()
        except Exception:
            pass


def get_best_query_version(name: str) -> Dict[str, Any]:
    """Get the best version of a saved search query."""
    analyzed = _load_analyzed_searches()

    if name not in analyzed:
        name_lower = name.lower()
        for key in analyzed:
            if name_lower in key.lower():
                name = key
                break
        else:
            return {"error": f"Saved search '{name}' not found"}

    data = analyzed[name]

    feedback = data.get("feedback", [])
    if feedback:
        best_feedback = feedback[0]
        if best_feedback.get("rank", 0) >= 5:
            return {
                "query": best_feedback["improved_query"],
                "source": "user_feedback",
                "rank": best_feedback.get("rank", 0),
                "user": best_feedback.get("user", "anonymous"),
                "notes": best_feedback.get("notes", ""),
                "explanation": f"User-improved query (rank {best_feedback.get('rank', 0)})",
                "original_query": data.get("original_query"),
            }

    optimized = data.get("optimized_query")
    if optimized:
        return {
            "query": optimized,
            "source": "optimization",
            "explanation": "System-optimized query using tstats/TERM patterns",
            "original_query": data.get("original_query"),
        }

    return {
        "query": data.get("original_query"),
        "source": "original",
        "explanation": "Original query (no optimization available)",
    }


def get_service_stats() -> Dict[str, Any]:
    """Get service statistics for monitoring."""
    analyzed = _load_analyzed_searches()
    saved = _SAVED_CACHE.get("savedsearches", [])

    total_feedback = sum(len(data.get("feedback", [])) for data in analyzed.values())
    high_ranked_feedback = sum(
        1 for data in analyzed.values()
        for fb in data.get("feedback", [])
        if fb.get("rank", 0) >= 5
    )

    optimized_count = sum(1 for data in analyzed.values() if data.get("optimized_query"))

    learned_patterns = _get_learned_patterns()

    return {
        "saved_searches_found": len(saved),
        "saved_searches_analyzed": len(analyzed),
        "optimizable_searches": optimized_count,
        "total_feedback_entries": total_feedback,
        "high_ranked_feedback": high_ranked_feedback,
        "learned_patterns": len(learned_patterns),
    }
