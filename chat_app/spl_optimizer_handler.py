"""
SPL optimizer handler for the Splunk Assistant.
"""
import logging

from shared.spl_query_optimizer import SPLQueryOptimizer, ConversionStatus
from shared.spl_validator import SPLValidator

logger = logging.getLogger(__name__)


def append_optimization_section(
    result_text: str,
    original_query: str,
    original_validation,
) -> str:
    """
    Run the local SPL optimizer and append a concise summary
    comparing the original vs optimized query.
    """
    try:
        optimization = SPLQueryOptimizer.optimize(original_query)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"SPL optimizer failed: {exc}")
        return result_text

    if optimization.status == ConversionStatus.IMPOSSIBLE:
        return result_text

    # Skip if optimizer didn't change the query materially
    if optimization.optimized.strip() == original_query.strip():
        return result_text

    optimized_validation = SPLValidator.validate(optimization.optimized, block_dangerous=False)

    notes = optimization.performance_notes[:4] if optimization.performance_notes else []
    notes_text = "\n".join(f"- {n}" for n in notes) if notes else "- No specific performance notes recorded"

    result_text += (
        "\n\n**Local Optimization (tstats/PREFIX/TERM):**"
        f"\n- Conversion: {optimization.status.value} via {optimization.strategy.value}"
        f"\n- Risk score: {original_validation.risk_score}/100 → {optimized_validation.risk_score}/100"
        f"\n- Validation: {optimized_validation.status.value.upper()} (original: {original_validation.status.value.upper()})"
        "\n- Why faster:"
        f"\n{notes_text}"
        "\n\n**Optimized SPL:**\n```spl\n"
        f"{optimization.optimized}\n```"
    )

    return result_text
