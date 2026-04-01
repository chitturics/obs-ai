"""
Core routines for SPL/NLP query review, optimization, and learning.
Shared by the REST service and CLI.

This module is the public API facade — it re-exports functions from
focused submodules so that existing imports continue to work.
"""
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from shared.spl_template_engine import SPLTemplateEngine

# ---------------------------------------------------------------------------
# Re-export public API from submodules
# ---------------------------------------------------------------------------
from .utils import (
    _append_history,
    _apply_hint_to_query,
    _extract_best_practices,
    _find_hint,
    _find_matching_savedsearches,
    _load_best_practices,
    _load_log_hints,
    _load_saved_searches,
    _resolve_data_root,
    _review_query,
    _save_best_practices,
    _sql_lint,
    get_custom_command_names,
    get_custom_commands,
    get_registered_macros,
)

from .config_manager import (
    SplunkConfigManager,
    get_splunk_config_manager,
)

from .optimizer import (
    _apply_simple_optimizations,
    _apply_time_bounds,
    _generate_optimization_suggestions,
    _optimize_query,
    _simple_improvement,
)

from .analyzer import (
    annotate_query,
    apply_auto_fixes,
    auto_analyze,
    deep_analyze_query,
    explain_query,
    get_query_cost,
    robust_analyze_query,
    score_query,
    validate_and_optimize_query,
)

from .saved_searches import (
    analyze_all_saved_searches,
    get_analyzed_search,
    get_best_query_version,
    get_service_stats,
    list_analyzed_searches,
    preload_caches,
    submit_search_feedback,
)

from .learning import (
    apply_learned_patterns,
    learn_from_feedback,
)

from .nlp_generation import (
    generate_spl_from_nlp,
    get_nlp_stats,
)

from .splunk_integration import (
    _btool_all,
    _remote_parse,
    _run_btool_check,
    get_splunk_validator_status,
    run_btool_via_container,
    run_search_preview,
    validate_spl_with_splunk,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main entry point — routes to the correct action
# ---------------------------------------------------------------------------
def handle_query(sql_query: str, qtype: str, action: str, store_path: Path | None = None) -> Dict[str, Any]:
    """Execute the requested action and return a response dict."""
    raw_query = sql_query.strip()
    generated_info = {}

    working_query = raw_query
    hints = _load_log_hints(_resolve_data_root() / "log_type_hints.csv")
    hint = _find_hint(raw_query, hints)

    if qtype == "nlp":
        generated_query, intent, explanation = SPLTemplateEngine.generate_query(raw_query)
        if hint:
            generated_query = _apply_hint_to_query(generated_query, hint)
        working_query = generated_query
        generated_info = {
            "generated_query": generated_query,
            "intent": intent.query_type,
            "explanation": explanation,
        }

    response: Dict[str, Any] = {"action": action, "input_type": qtype, **generated_info}

    validation = None
    if action in ("review", "improve", "optimize", "learn"):
        review, validation = _review_query(working_query)
        response["review"] = review

        response["remote_parse"] = _remote_parse(working_query)

        splunk_validation = validate_spl_with_splunk(working_query)
        response["splunk_validation"] = splunk_validation

        if splunk_validation.get("available") and splunk_validation.get("errors"):
            response["review"]["splunk_errors"] = splunk_validation["errors"]
            if not splunk_validation.get("valid"):
                response["review"]["status"] = "error"
                response["review"]["errors"].extend([f"[Splunk] {e}" for e in splunk_validation["errors"]])

        response["btool"] = _run_btool_check()
        response["btool_repo_check"] = _btool_all(Path("/app/public/documents/repo"))

        if qtype == "sql":
            response["sql_lint"] = _sql_lint(working_query)

        if getattr(validation, "parsed_components", None):
            response["parsed_components"] = validation.parsed_components

        saved = _load_saved_searches()
        matches = _find_matching_savedsearches(working_query, saved)
        if matches:
            response["savedsearch_matches"] = [
                {
                    "name": m["name"],
                    "file": m["file"],
                    "search_expanded": m["search_expanded"],
                    "macros_used": m["macros_used"],
                }
                for m in matches
            ]

    if action in ("improve", "optimize"):
        response["optimization"] = _optimize_query(working_query)
        simple = _simple_improvement(working_query, validation)
        if simple:
            response["improvement"] = simple

    if action == "explain":
        response["explanation"] = explain_query(working_query)

    if action == "score":
        response["score"] = score_query(working_query)

    if action == "annotate":
        response["annotation"] = annotate_query(working_query)

    if action == "auto":
        response["analysis"] = auto_analyze(working_query)

    if action == "deep":
        response["deep_analysis"] = deep_analyze_query(working_query)

    # Persist learning / history
    history_path = _resolve_data_root() / "spl_search_history.json"
    record = {
        "query": working_query,
        "action": action,
        "input_type": qtype,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "optimization": response.get("optimization"),
        "review": response.get("review"),
        "parsed_components": response.get("parsed_components"),
    }
    _append_history(history_path, record)

    if action == "learn":
        target = store_path or (_resolve_data_root() / "spl_best_practices.json")
        practices = _load_best_practices(target)
        practices.append(
            {
                "query": working_query,
                "captured_at": datetime.utcnow().isoformat() + "Z",
                "best_practices": _extract_best_practices(working_query, validation),
            }
        )
        _save_best_practices(target, practices)
        response["learned_count"] = len(practices)
        response["store_path"] = str(target)

    return response
