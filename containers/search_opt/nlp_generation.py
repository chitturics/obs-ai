"""
NLP to SPL generation with validation and optimization.
"""
import logging
import re
from typing import Any, Dict, Optional

from shared.spl_query_optimizer import SPLQueryOptimizer

from .config_manager import get_splunk_config_manager
from .splunk_integration import validate_spl_with_splunk

# Optional modules
try:
    from shared.nlp_to_spl import get_nlp_generator, NLPtoSPL, SPLGenerationResult
    _NLP_AVAILABLE = True
except ImportError:
    _NLP_AVAILABLE = False
    get_nlp_generator = None
    NLPtoSPL = None
    SPLGenerationResult = None

try:
    from shared.spl_robust_analyzer import (
        analyze_spl as robust_analyze_spl,
    )
    _ROBUST_ANALYZER_AVAILABLE = True
except ImportError:
    _ROBUST_ANALYZER_AVAILABLE = False
    robust_analyze_spl = None

logger = logging.getLogger(__name__)


def generate_spl_from_nlp(
    nl_query: str,
    validate: bool = True,
    optimize: bool = True,
    context: Optional[Dict] = None
) -> Dict[str, Any]:
    """Generate SPL from natural language with optional validation and optimization."""
    if not _NLP_AVAILABLE:
        return {
            "nl_query": nl_query,
            "error": "NLP-to-SPL module not available. Rebuild container with nlp_to_spl.py",
            "success": False,
        }

    result = {
        "nl_query": nl_query,
        "generated_query": None,
        "final_query": None,
        "confidence": 0.0,
        "intent": None,
        "examples_used": [],
        "validation": None,
        "optimization": None,
        "robust_analysis": None,
        "suggestions": [],
        "success": False,
    }

    try:
        mgr = get_splunk_config_manager()
        mgr.load_all()

        nlp_gen = get_nlp_generator()
        gen_result = nlp_gen.generate(nl_query, context)

        result["generated_query"] = gen_result.query
        result["confidence"] = gen_result.confidence
        result["intent"] = gen_result.intent
        result["examples_used"] = gen_result.examples_used
        result["suggestions"].extend(gen_result.suggestions)

        current_query = gen_result.query

        if _ROBUST_ANALYZER_AVAILABLE and current_query:
            try:
                robust_result = robust_analyze_spl(current_query)
                result["robust_analysis"] = robust_result

                if robust_result.get("optimized_query"):
                    current_query = robust_result["optimized_query"]
                    result["suggestions"].append("Query improved by robust analyzer.")
                elif robust_result.get("normalized_query"):
                    current_query = robust_result["normalized_query"]
            except Exception as e:
                logger.warning(f"Robust analyzer failed during NLP generation: {e}")

        if validate and current_query:
            val_result = validate_spl_with_splunk(current_query)
            result["validation"] = val_result

        if optimize and current_query and (not validate or result["validation"].get("valid", True)):
            opt_result = SPLQueryOptimizer.optimize(current_query)
            result["optimization"] = {
                "status": opt_result.status.value,
                "optimized": opt_result.optimized,
                "explanation": opt_result.explanation,
            }
            if opt_result.status.value in ("full", "partial"):
                current_query = opt_result.optimized
                result["suggestions"].append(f"Query optimized: {opt_result.explanation}")

        result["final_query"] = current_query
        result["success"] = True

        for ex_name in gen_result.examples_used:
            if ex_name.startswith("feedback_"):
                mgr.record_usage("feedback", ex_name)
            elif "macro" in ex_name or any(n == ex_name for n in mgr.get_macros()):
                mgr.record_usage("macro", ex_name)
            else:
                mgr.record_usage("search", ex_name)

    except Exception as e:
        logger.error(f"NLP to SPL generation failed: {e}")
        result["error"] = str(e)

    return result


def _try_fix_syntax(query: str, validation: Dict) -> str:
    """Try to fix common syntax errors in generated query."""
    fixed = query

    if "tstats" in fixed and not fixed.strip().startswith("|"):
        if "index=" in fixed and "tstats" in fixed:
            pass
        elif fixed.strip().startswith("tstats"):
            fixed = "| " + fixed.strip()

    if fixed.count('"') % 2 != 0:
        fixed = fixed.replace('"', '')

    open_parens = fixed.count('(')
    close_parens = fixed.count(')')
    if open_parens > close_parens:
        fixed += ')' * (open_parens - close_parens)
    elif close_parens > open_parens:
        fixed = '(' * (close_parens - open_parens) + fixed

    return fixed


def get_nlp_stats() -> Dict[str, Any]:
    """Get NLP generator statistics."""
    if not _NLP_AVAILABLE:
        return {"error": "NLP module not available", "available": False}
    try:
        nlp_gen = get_nlp_generator()
        return nlp_gen.get_stats()
    except Exception as e:
        return {"error": str(e)}
