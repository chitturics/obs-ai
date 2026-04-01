"""
SPL query analysis: robust analysis, explanation, scoring, annotation, and deep analysis.
"""
import logging
import re
from typing import Any, Dict, List, Optional

from shared.spl_analyzer import SPLAnalyzer, UserIntent
from shared.spl_knowledge_base import get_knowledge_base
from shared.spl_query_optimizer import SPLQueryOptimizer

from .learning import apply_learned_patterns
from .splunk_integration import validate_spl_with_splunk

# Optional robust analyzer
try:
    from shared.spl_robust_analyzer import (
        get_robust_analyzer,
        analyze_spl as robust_analyze_spl,
        validate_and_optimize,
        RobustSPLAnalyzer,
    )
    _ROBUST_ANALYZER_AVAILABLE = True
except ImportError:
    _ROBUST_ANALYZER_AVAILABLE = False
    get_robust_analyzer = None
    robust_analyze_spl = None
    validate_and_optimize = None
    RobustSPLAnalyzer = None

# Deep analysis (next-level optimization intelligence)
try:
    from shared.spl_deep_analysis import get_deep_analyzer, deep_analyze as _deep_analyze
    _DEEP_ANALYSIS_AVAILABLE = True
except ImportError:
    _DEEP_ANALYSIS_AVAILABLE = False
    get_deep_analyzer = None
    _deep_analyze = None

logger = logging.getLogger(__name__)

# Singletons
_analyzer = SPLAnalyzer()
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


# ---------------------------------------------------------------------------
# Robust analyzer wrappers
# ---------------------------------------------------------------------------
def robust_analyze_query(
    query: str,
    auto_fix: bool = True,
    validate_with_splunk: bool = True,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Comprehensive robust analysis of an SPL query."""
    if not _ROBUST_ANALYZER_AVAILABLE:
        return {
            "query": query,
            "is_valid": False,
            "error": "Robust analyzer module not available. Rebuild container with spl_robust_analyzer.py",
        }

    try:
        analyzer = get_robust_analyzer()
        result = analyzer.analyze(query)

        anti_patterns = [
            issue.message for issue in result.issues
            if issue.category.value == "performance"
        ]

        response = {
            "query": query,
            "is_valid": result.is_valid,
            "cost_score": result.estimated_cost,
            "optimization_potential": result.optimization_potential,
            "issues": [
                {
                    "severity": issue.severity.value if hasattr(issue.severity, 'value') else str(issue.severity),
                    "category": issue.category.value if hasattr(issue.category, 'value') else str(issue.category),
                    "message": issue.message,
                    "suggestion": issue.suggestion,
                    "auto_fixable": issue.auto_fixable,
                }
                for issue in result.issues
            ],
            "commands": [
                {
                    "name": cmd.name,
                    "cost": cmd.estimated_cost,
                    "is_generating": cmd.is_generating,
                    "is_streaming": cmd.is_streaming,
                    "is_transforming": cmd.is_transforming,
                }
                for cmd in result.commands
            ],
            "anti_patterns": anti_patterns,
            "normalized_query": result.normalized_query,
            "optimized_query": result.optimized_query,
            "recommendations": result.recommendations,
        }

        if validate_with_splunk and result.optimized_query:
            splunk_result = validate_spl_with_splunk(result.optimized_query)
            response["splunk_validation"] = splunk_result

        return response
    except Exception as e:
        logger.error(f"Robust analysis failed: {e}")
        return {"query": query, "is_valid": False, "error": str(e)}


def get_query_cost(query: str) -> Dict[str, Any]:
    """Get cost estimation for an SPL query."""
    if not _ROBUST_ANALYZER_AVAILABLE:
        return {"query": query, "error": "Robust analyzer not available"}

    try:
        analyzer = get_robust_analyzer()
        result = analyzer.analyze(query)

        return {
            "query": query,
            "cost_score": result.estimated_cost,
            "optimization_potential": result.optimization_potential,
            "command_costs": [
                {"name": cmd.name, "cost": cmd.estimated_cost}
                for cmd in result.commands
            ],
            "expensive_operations": [
                issue.message for issue in result.issues
                if issue.category.value == "performance"
            ],
            "suggestions": [
                issue.suggestion for issue in result.issues
                if issue.suggestion
            ],
            "recommendations": result.recommendations,
        }
    except Exception as e:
        logger.error(f"Cost estimation failed: {e}")
        return {"query": query, "error": str(e)}


def apply_auto_fixes(query: str) -> Dict[str, Any]:
    """Apply auto-fixes to an SPL query without full analysis."""
    if not _ROBUST_ANALYZER_AVAILABLE:
        return {"original_query": query, "fixed_query": query, "error": "Robust analyzer not available"}

    try:
        analyzer = get_robust_analyzer()
        result = analyzer.analyze(query)

        fixed = result.optimized_query or result.normalized_query or query

        return {
            "original_query": query,
            "fixed_query": fixed,
            "normalized_query": result.normalized_query,
            "recommendations": result.recommendations,
            "remaining_issues": [
                {
                    "severity": issue.severity.value if hasattr(issue.severity, 'value') else str(issue.severity),
                    "message": issue.message,
                    "suggestion": issue.suggestion,
                }
                for issue in result.issues
                if not issue.auto_fixable
            ],
        }
    except Exception as e:
        logger.error(f"Auto-fix failed: {e}")
        return {"original_query": query, "fixed_query": query, "error": str(e)}


def validate_and_optimize_query(
    query: str,
    context: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Full pipeline: validate, analyze, fix, and optimize an SPL query."""
    if not _ROBUST_ANALYZER_AVAILABLE:
        return {"query": query, "error": "Robust analyzer not available"}

    try:
        result = validate_and_optimize(query)
        return result
    except Exception as e:
        logger.error(f"Validate and optimize failed: {e}")
        return {"query": query, "error": str(e)}


# ---------------------------------------------------------------------------
# Explain / Score / Annotate
# ---------------------------------------------------------------------------
def explain_query(query: str) -> Dict[str, Any]:
    """Explain an SPL query step by step."""
    result = _analyzer.explain(query)

    kb = _get_kb()
    kb_pipeline = kb.explain_pipeline(query) if kb else []
    kb_complexity = kb.calculate_query_complexity(query) if kb else {}
    kb_anti_patterns = kb.detect_anti_patterns(query) if kb else []
    kb_suggestions = kb.get_optimization_suggestions(query) if kb else []

    response = {
        "query": query,
        "intent": result.intent.value,
        "processing_time_ms": result.processing_time_ms,
    }

    if result.explanation:
        response["explanation"] = {
            "summary": result.explanation.summary,
            "stages": result.explanation.stages,
            "fields_used": result.explanation.fields_used,
            "data_flow": result.explanation.data_flow,
            "purpose": result.explanation.purpose,
            "complexity": result.explanation.complexity,
        }

    response["detailed_stages"] = kb_pipeline
    response["complexity_analysis"] = kb_complexity

    if kb_anti_patterns:
        response["issues_found"] = kb_anti_patterns
    if kb_suggestions:
        response["improvement_suggestions"] = kb_suggestions[:5]

    response["human_summary"] = _generate_human_summary(query, kb_pipeline, kb_complexity)

    # Include official doc references if available
    docs = kb.docs if kb else None
    if docs:
        doc_refs = {}
        for stage in kb_pipeline:
            cmd = stage.get("command", "")
            if cmd:
                url = docs.get_command_url(cmd)
                if url:
                    doc_refs[cmd] = url
        if doc_refs:
            response["doc_references"] = doc_refs

    if result.error:
        response["error"] = result.error

    return response


def _generate_human_summary(query: str, pipeline: List[Dict], complexity: Dict) -> str:
    """Generate a human-readable summary like an expert would explain it."""
    if not pipeline:
        return "Unable to analyze query."

    parts = []

    level = complexity.get("level", "moderate")
    if level == "simple":
        parts.append("This is a straightforward search that")
    elif level == "moderate":
        parts.append("This search")
    elif level == "complex":
        parts.append("This is a complex search that")
    else:
        parts.append("This is a very complex search that")

    # Hardcoded summaries for common commands (fast path)
    _CMD_SUMMARIES = {
        "stats": "aggregates the data",
        "timechart": "creates a time-based chart",
        "eval": "calculates new field values",
        "where": "filters the results",
        "table": "formats the output as a table",
        "tstats": "uses fast indexed statistics (optimized)",
        "join": "joins with another dataset (expensive)",
        "transaction": "groups events into transactions (very expensive)",
        "lookup": "enriches data from a lookup table",
        "rex": "extracts fields using regex",
        "dedup": "removes duplicate entries",
        "sort": "sorts the results",
        "fields": "selects or removes fields",
        "rename": "renames fields",
        "head": "returns the first N results",
        "tail": "returns the last N results",
        "eventstats": "adds statistics to each event",
        "streamstats": "adds running statistics to events",
        "chart": "creates a chart visualization",
        "top": "finds the most common values",
        "rare": "finds the least common values",
        "fillnull": "replaces null values",
        "append": "appends subsearch results",
        "bin": "groups values into buckets",
        "convert": "converts field values",
        "mvexpand": "expands multivalue fields",
    }

    # Get docs for fallback descriptions
    kb = _get_kb()
    docs = kb.docs if kb else None

    stage_descriptions = []
    for stage in pipeline:
        cmd = stage.get("command", "")

        if cmd in ("search", "index") or stage.get("stage") == 1:
            if "index=" in query:
                idx_match = re.search(r"index\s*=\s*(\S+)", query)
                if idx_match:
                    idx = idx_match.group(1)
                    if idx == "*":
                        stage_descriptions.append("searches all indexes (which is slow)")
                    else:
                        stage_descriptions.append(f"searches the '{idx}' index")
        elif cmd in _CMD_SUMMARIES:
            stage_descriptions.append(_CMD_SUMMARIES[cmd])
        elif docs:
            # Fall back to official docs description
            desc = docs.get_command_description(cmd)
            if desc:
                # Take just the first sentence, lowercased
                first_sent = desc.split(".")[0].strip().lower()
                if len(first_sent) < 80:
                    stage_descriptions.append(first_sent)
                else:
                    stage_descriptions.append(f"runs {cmd}")

    if stage_descriptions:
        parts.append(", ".join(stage_descriptions[:4]))
        if len(stage_descriptions) > 4:
            parts.append(f", and {len(stage_descriptions) - 4} more operations")
        parts.append(".")

    high_cost = complexity.get("high_cost_commands", [])
    if high_cost:
        parts.append(f" Note: Uses expensive command(s): {', '.join(high_cost)}.")

    return " ".join(parts)


def score_query(query: str) -> Dict[str, Any]:
    """Score an SPL query for quality and efficiency."""
    result = _analyzer.validate(query)

    kb = _get_kb()
    kb_anti_patterns = kb.detect_anti_patterns(query) if kb else []
    kb_complexity = kb.calculate_query_complexity(query) if kb else {}
    kb_suggestions = kb.get_optimization_suggestions(query) if kb else []

    learned_suggestions = apply_learned_patterns(query)

    response = {
        "query": query,
        "processing_time_ms": result.processing_time_ms,
    }

    if result.score:
        penalty = len([ap for ap in kb_anti_patterns if ap["severity"] == "high"]) * 15
        penalty += len([ap for ap in kb_anti_patterns if ap["severity"] == "medium"]) * 8
        penalty += len([ap for ap in kb_anti_patterns if ap["severity"] == "low"]) * 3

        adjusted_overall = max(0, result.score.overall - penalty)
        adjusted_efficiency = max(0, result.score.efficiency - penalty)

        all_recommendations = (
            result.score.recommendations +
            [s["description"] for s in kb_suggestions[:3]] +
            [s["description"] for s in learned_suggestions[:2]]
        )

        response["score"] = {
            "overall": adjusted_overall,
            "readability": result.score.readability,
            "efficiency": adjusted_efficiency,
            "best_practices": result.score.best_practices,
            "issues": result.score.issues + [ap["name"] for ap in kb_anti_patterns],
            "recommendations": all_recommendations[:6],
        }

    if result.validation:
        response["validation"] = {
            "status": result.validation.status.value,
            "risk_score": result.validation.risk_score,
            "risk_level": result.validation.risk_level.value,
        }

    response["complexity"] = kb_complexity
    response["anti_patterns"] = kb_anti_patterns
    response["optimization_opportunities"] = kb_suggestions

    if learned_suggestions:
        response["learned_suggestions"] = learned_suggestions

    if result.error:
        response["error"] = result.error

    return response


def annotate_query(query: str) -> Dict[str, Any]:
    """Add inline comments to an SPL query."""
    result = _analyzer.annotate(query)
    response = {
        "query": query,
        "processing_time_ms": result.processing_time_ms,
    }
    if result.annotated_query:
        response["annotated_query"] = result.annotated_query
    if result.error:
        response["error"] = result.error
    return response


def auto_analyze(input_text: str, force_intent: str = None) -> Dict[str, Any]:
    """Auto-detect intent and analyze input."""
    intent = None
    if force_intent:
        try:
            intent = UserIntent(force_intent)
        except ValueError:
            pass

    result = _analyzer.analyze(input_text, force_intent=intent)
    return result.to_dict()


# ---------------------------------------------------------------------------
# Deep Analysis (next-level optimization intelligence)
# ---------------------------------------------------------------------------
def deep_analyze_query(query: str) -> Dict[str, Any]:
    """
    Run deep analysis on an SPL query.

    Returns comprehensive analysis including:
    - Cardinality warnings for BY/dedup fields
    - Memory estimation per command
    - Regex complexity scoring
    - Bucket/span optimization suggestions
    - Lookup placement analysis
    - Subsearch nesting depth
    - Metric index / mstats opportunities
    - Distributed vs non-distributed command warnings
    - Resource risk matrix (memory, CPU, disk I/O, network)
    - Stage-by-stage search profiling with bottleneck identification
    - Pipeline reorder suggestions
    - Query fingerprint for dedup
    """
    if not _DEEP_ANALYSIS_AVAILABLE:
        return {
            "query": query,
            "error": "Deep analysis module not available. Ensure shared/spl_deep_analysis.py is present.",
        }

    try:
        result = _deep_analyze(query)
        return result.to_dict()
    except Exception as e:
        logger.error(f"Deep analysis failed: {e}")
        return {"query": query, "error": str(e)}
