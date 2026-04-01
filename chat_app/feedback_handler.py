"""
Feedback handler for the Splunk Assistant.
"""
import asyncio
import logging
import hashlib
import chainlit as cl

from chainlit.types import Feedback
from helper import current_username, current_thread_id
from feedback_logger import log_feedback, log_query_preference
from vectorstore_ingest import add_feedback_qa_to_memory
import json
import re

logger = logging.getLogger(__name__)


async def _llm_polish_feedback(
    question: str,
    answer: str,
    llm,
    is_liked: bool,
    reason: str = "",
    username: str = "unknown",
) -> bool:
    """
    Run ALL feedback through LLM to produce polished prompt-ready examples.

    For liked feedback: Polishes the Q&A into a clean, canonical example.
    For disliked feedback: Creates a clear 'what NOT to do' example with the correction.

    Stores the polished result in the CORRECT collection:
    - Liked → feedback_qa collection (positive guardrails)
    - Disliked → negative_feedback collection (warning guardrails)
    """
    if not question or not answer:
        return False

    try:
        if is_liked:
            prompt = (
                "You are a Q&A dataset curator for a Splunk assistant.\n"
                "A user approved this answer as correct. Polish it into a clean, canonical Q&A pair.\n"
                "- The question should be well-phrased and standalone.\n"
                "- The answer should be clear, complete, and well-formatted.\n"
                "- Preserve technical accuracy. Do NOT change SPL queries or config values.\n\n"
                f"**Original Question:** {question}\n\n"
                f"**Approved Answer:** {answer}\n\n"
                'Respond with ONLY a JSON object: {"question": "...", "answer": "..."}'
            )
        else:
            prompt = (
                "You are a Q&A dataset curator for a Splunk assistant.\n"
                "A user marked this answer as BAD. Create a clear warning example.\n"
                "- The question should be well-phrased and standalone.\n"
                "- The bad_answer should clearly show what was wrong.\n"
                "- The correction should explain the right approach.\n"
                "- If the user provided a reason, incorporate it.\n\n"
                f"**Original Question:** {question}\n\n"
                f"**Bad Answer:** {answer}\n\n"
                f"**User's Reason:** {reason or 'Not specified'}\n\n"
                'Respond with ONLY a JSON object: {"question": "...", "bad_answer": "...", "correction": "..."}'
            )

        try:
            response = await asyncio.wait_for(llm.ainvoke(prompt), timeout=60)
        except asyncio.TimeoutError:
            logger.warning("[FEEDBACK POLISH] LLM timed out after 60s, storing raw feedback")
            return False
        if hasattr(response, 'content'):
            response = response.content

        json_match = re.search(r'\{[^{}]*\}', response, re.DOTALL)
        if not json_match:
            logger.warning("LLM did not return valid JSON for feedback polishing")
            return False

        data = json.loads(json_match.group(0))

        if is_liked and "question" in data and "answer" in data:
            # Store polished positive example in feedback_qa collection
            f"Q: {data['question'].strip()}\n\nA: {data['answer'].strip()}"
            try:
                from vectorstore_ingest import add_feedback_qa_to_memory
                success, _ = add_feedback_qa_to_memory(
                    data["question"], data["answer"], username,
                )
                if success:
                    logger.info(f"[FEEDBACK POLISH] Stored polished liked Q&A: {data['question'][:50]}...")
                    return True
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                logger.warning(f"[FEEDBACK POLISH] Failed to store polished liked Q&A: {e}")

        elif not is_liked and "question" in data:
            # Store polished negative example in negative_feedback collection
            bad_answer = data.get("bad_answer", answer)
            correction = data.get("correction", reason or "")
            try:
                from negative_feedback import add_negative_feedback
                add_negative_feedback(
                    data["question"],
                    f"{bad_answer}\n\nCorrection: {correction}" if correction else bad_answer,
                    username,
                    reason=reason or "thumbs_down",
                )
                logger.info(f"[FEEDBACK POLISH] Stored polished negative example: {data['question'][:50]}...")
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                logger.warning(f"[FEEDBACK POLISH] Failed to store polished negative: {e}")

            # Also store the CORRECTION as a positive Q&A so it's returned next time
            if correction:
                try:
                    from vectorstore_ingest import add_feedback_qa_to_memory
                    success, _ = add_feedback_qa_to_memory(
                        data["question"], correction, username,
                    )
                    if success:
                        logger.info(f"[FEEDBACK POLISH] Stored correction as positive Q&A: {data['question'][:50]}...")
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                    logger.warning(f"[FEEDBACK POLISH] Failed to store correction as positive Q&A: {e}")

            return True

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.error(f"[FEEDBACK POLISH] LLM polishing failed: {e}")

    return False


async def on_feedback(feedback: "Feedback", engine, vector_store, llm, docs_base_url):
    """
    Handles user feedback on a message.
    """
    username = current_username()
    thread_id = current_thread_id()
    message_id = getattr(feedback, "for_id", None) or getattr(feedback, "id", None) or "unknown"

    last_q = cl.user_session.get("last_question", "")
    last_a = cl.user_session.get("last_answer", "")
    last_ctx = cl.user_session.get("last_context", "")
    last_agent = cl.user_session.get("last_agent_name", "")
    last_intent = cl.user_session.get("last_intent", "unknown")

    is_liked = bool(feedback.value and feedback.value > 0)
    reason = feedback.comment

    if not is_liked and not reason:
        reason_res = await cl.AskUserMessage(
            content="Thanks for the feedback! Could you tell us why this answer was not helpful?",
            timeout=60,
        ).send()
        if reason_res:
            reason = reason_res["output"]

    feedback_file = None
    try:
        feedback_file = await log_feedback(
            engine=engine, message_id=message_id, value=feedback.value,
            comment=reason, username=username, thread_id=thread_id,
            title=last_q or "User feedback", question=last_q,
            answer=last_a, context=last_ctx,
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("Failed to log feedback: %s", exc)

    # --- Analytics Engine: record feedback ---
    try:
        from chat_app.analytics import get_analytics_engine
        get_analytics_engine().record_feedback(
            query=last_q,
            feedback="positive" if is_liked else "negative",
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("Analytics feedback recording failed: %s", exc)

    try:
        if last_q and last_a:
            await log_query_preference(
                engine=engine, username=username, thread_id=thread_id,
                question=last_q, answer=last_a, context=last_ctx,
                liked=is_liked, source_message_id=message_id,
            )

            # Run ALL feedback through LLM polishing before storage
            # This ensures clean, prompt-ready examples in both collections
            polished = await _llm_polish_feedback(
                question=last_q,
                answer=last_a,
                llm=llm,
                is_liked=is_liked,
                reason=reason or "",
                username=username,
            )

            if not polished:
                # Fallback: store raw if LLM polishing fails or times out
                logger.info("[FEEDBACK] LLM polish failed/timed out, storing raw feedback")
                if is_liked:
                    try:
                        add_feedback_qa_to_memory(
                            last_q, last_a, username,
                            feedback_file=feedback_file, docs_base_url=docs_base_url,
                        )
                    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                        logger.debug("%s", _exc)  # was: pass
                else:
                    try:
                        from negative_feedback import add_negative_feedback
                        add_negative_feedback(last_q, last_a, username, reason=reason or "thumbs_down")
                    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                        logger.debug("%s", _exc)  # was: pass
                    # Store user's correction as positive Q&A so it's returned next time
                    if reason and reason.strip():
                        try:
                            add_feedback_qa_to_memory(last_q, reason.strip(), username)
                            logger.info(f"[FEEDBACK] Stored user correction as positive Q&A: {last_q[:50]}...")
                        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                            logger.debug("%s", _exc)  # was: pass

            # Invalidate cache on negative feedback
            if not is_liked and last_ctx:
                try:
                    from cache import invalidate_specific_query
                    ctx_hash = hashlib.sha256(last_ctx.encode()).hexdigest()
                    await invalidate_specific_query(last_q, ctx_hash)
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                    logger.debug("%s", _exc)  # was: pass

            # Apply self-adaptive RAG learning from all feedback (thumbs up & down)
            try:
                from self_adaptive_rag import apply_adaptive_learning
                collections_used = cl.user_session.get("last_collections_used", [])
                apply_adaptive_learning(
                    feedback_value=1 if is_liked else 0,
                    query=last_q,
                    response=last_a,
                    chunks_used=[{"collection": c} for c in collections_used],
                    username=username,
                )
            except Exception as _exc:  # broad catch — resilience against all failures
                pass  # Self-adaptive RAG is optional
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("Failed to log query preference: %s", exc)

    # --- Agent quality feedback loop ---
    # Feed user thumbs-up/down directly into agent quality scores
    try:
        if last_agent:
            from agent_dispatcher import get_agent_dispatcher
            feedback_quality = 1.0 if is_liked else 0.0
            get_agent_dispatcher().record_quality(last_agent, last_intent, feedback_quality)
            logger.info(
                "[FEEDBACK→AGENT] Recorded quality=%.1f for agent=%s intent=%s (user %s)",
                feedback_quality, last_agent, last_intent,
                "liked" if is_liked else "disliked",
            )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[FEEDBACK→AGENT] Agent quality update skipped: %s", exc)

    # --- SLO quality recording from feedback ---
    try:
        from observability import get_observability_manager
        _obs = get_observability_manager()
        _obs.record_slo_data("response_quality", 1.0 if is_liked else 0.0)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    try:
        import subprocess
        subprocess.Popen(
            ["python", "/app/chat_app/generate_feedback_index.py"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # Trigger learning on the search optimizer side so patterns are updated
    try:
        from search_opt_client import trigger_learning
        learn_result = await trigger_learning()
        if learn_result:
            logger.info(f"Search optimizer learning triggered: {learn_result}")
    except Exception as _exc:  # broad catch — resilience against all failures
        pass  # Search optimizer is optional
