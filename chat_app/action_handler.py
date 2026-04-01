"""
Action handlers for the Splunk Assistant.
"""
import logging
import time
from typing import List
import chainlit as cl
from feedback_logger import log_followup_sequence
from helper import current_username, current_thread_id
from chat_app.message_context import MessageHandlerContext

logger = logging.getLogger(__name__)

async def on_followup(action: cl.Action, on_message, context: MessageHandlerContext):
    question = action.label
    if action.payload:
        question = action.payload.get("question", question)

    # Log the followup sequence
    try:
        last_question = cl.user_session.get("last_question")
        if last_question and last_question != question:
            await log_followup_sequence(
                engine=context.engine,
                username=current_username(),
                thread_id=current_thread_id(),
                parent_question=last_question,
                followup_question=question,
            )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.warning(f"Failed to log followup sequence: {e}")

    await cl.Message(author="user", content=question).send()
    from chat_app import on_message
    await on_message(
        cl.Message(content=question),
        context
    )


def _build_improvement_notes(analysis: dict) -> List[str]:
    """Build improvement notes from analysis result."""
    notes = []
    for issue in (analysis.get("issues") or [])[:3]:
        msg = issue.get("message")
        suggestion = issue.get("suggestion")
        if suggestion:
            notes.append(f"{msg} — {suggestion}")
        elif msg:
            notes.append(msg)
    for rec in (analysis.get("recommendations") or [])[:3]:
        if rec and rec not in notes:
            notes.append(rec)
    return notes


def _build_optimized_query_response(optimized: str, analysis: dict, notes: List[str]) -> str:
    """Build the optimized query response."""
    summary_parts = []
    if analysis.get("optimization_potential") is not None:
        summary_parts.append(f"Optimization potential: {analysis.get('optimization_potential')}/100")
    if analysis.get("cost_score") is not None:
        summary_parts.append(f"Estimated cost: {analysis.get('cost_score')}/100")
    summary_line = " | ".join(summary_parts) if summary_parts else "Optimization summary:"

    response = f"""**Optimized SPL Query:**
```spl
{optimized}
```

{summary_line}"""
    if notes:
        response += "\n\nImprovements:\n" + "\n".join(f"- {n}" for n in notes)

    return response


async def on_optimize_query(action: cl.Action, call_robust_analyzer):
    """
    Handles the user's request to optimize a query.
    """
    original_spl = getattr(action, "value", None)
    if not original_spl:
        payload = getattr(action, "payload", None)
        if isinstance(payload, dict):
            original_spl = payload.get("query") or payload.get("spl") or payload.get("value")
        elif isinstance(payload, str):
            original_spl = payload
    if not original_spl:
        return

    # De-duplicate repeated clicks for the same query
    last_req = cl.user_session.get("last_optimize_request")
    now_ts = time.time()
    if isinstance(last_req, dict):
        if last_req.get("query") == original_spl and (now_ts - float(last_req.get("ts", 0))) < 10:
            return
    cl.user_session.set("last_optimize_request", {"query": original_spl, "ts": now_ts})

    await cl.Message(content="Optimizing the query...", author="Splunk Assistant").send()

    try:
        analysis = await call_robust_analyzer(original_spl, auto_fix=True)
        if not analysis:
            await cl.Message(
                content="The optimizer service did not return a result. Please try again.",
                author="Splunk Assistant",
            ).send()
            return

        # Prefer optimized_query, then fixed_query, then normalized_query
        optimized = (
            analysis.get("optimized_query")
            or analysis.get("fixed_query")
            or analysis.get("normalized_query")
        )

        notes = _build_improvement_notes(analysis)

        if optimized and optimized.strip() != original_spl.strip():
            response = _build_optimized_query_response(optimized, analysis, notes)
            await cl.Message(content=response, author="Splunk Assistant").send()
            return

        # No automatic rewrite, but provide guidance if we have it
        if notes:
            response = "**No automatic rewrite was applied**, but here are suggested improvements:\n"
            response += "\n".join(f"- {n}" for n in notes)
            await cl.Message(content=response, author="Splunk Assistant").send()
        else:
            await cl.Message(
                content="I couldn't find any automatic optimizations for this query.",
                author="Splunk Assistant",
            ).send()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.error(f"Error during query optimization: {e}")
        await cl.Message(content="Sorry, I encountered an error while trying to optimize the query.", author="Splunk Assistant").send()


async def on_ignore_optimization(action: cl.Action):
    """
    Handles the user's choice to ignore the optimization suggestion.
    """
    # Do nothing, just acknowledge the user's choice.
    pass
