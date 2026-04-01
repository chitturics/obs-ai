"""
Proactive handlers for the Splunk Assistant.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from chat_app.query_router_handler import QueryPlan

import chainlit as cl
from search_opt_client import call_robust_analyzer

logger = logging.getLogger(__name__)


def _get_spl_from_response(response: str) -> Optional[str]:
    """Extracts the first SPL query from a markdown response."""
    match = re.search(r"```spl\n(.*?)\n```", response, re.DOTALL)
    if match:
        return match.group(1).strip()
    return None


async def proactive_optimization_check(plan: "QueryPlan", response: str):
    """
    After a response is sent, check if an SPL query was generated and if it
    can be optimized. If so, proactively ask the user if they want to improve it.
    """
    from chat_app.registry import Intent
    if plan.intent != Intent.SPL_GENERATION and not plan.optimizer_action:
        return

    generated_spl = _get_spl_from_response(response)
    if not generated_spl:
        return

    try:
        analysis = await call_robust_analyzer(generated_spl)
        if not analysis:
            return

        is_optimizable = analysis.get("optimization_potential", 0) > 30
        has_issues = bool(analysis.get("issues"))

        if is_optimizable or has_issues:
            cl.user_session.set("last_generated_spl", generated_spl)
            actions = [
                cl.Action(name="optimize_query", label="Yes, improve it", payload={"query": generated_spl}),
                cl.Action(name="ignore_optimization", label="No, thanks", payload={"ignore": True}),
            ]
            await cl.Message(
                content="I noticed the generated SPL query could be improved. Would you like me to optimize it for better performance?",
                actions=actions,
                author="Splunk Assistant"
            ).send()

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.warning(f"Proactive optimization check failed: {e}")
