"""
Response generation for the Splunk Assistant.

Handles LLM invocation (streaming/non-streaming), SPL template engine,
SPL validation, and caching.
"""
import asyncio
import logging
from typing import Optional

from chat_app.settings import get_settings

import chainlit as cl
from cache import get_cached_query_response, cache_query_response
from ollama_priority import with_priority, RequestPriority
from chat_app.langfuse_integration import observe_llm
from resilience import call_with_resilience
from prometheus_metrics import record_llm_call
from chat_app.spl_template_handler import try_spl_template
from chat_app.spl_validator_handler import validate_spl_in_response

logger = logging.getLogger(__name__)

# Cache stats for telemetry report
_cache_stats: dict = {"hits": 0, "misses": 0}

# Guidance rules for LLM responses — compact for fast inference
RESPONSE_GUIDANCE = (
    "You are a Splunk/Cribl/Observability expert. "
    "You MUST answer using the retrieved context below. "
    "Extract and synthesize relevant information from the context to form your answer. "
    "If the context contains ANY relevant information, use it — do NOT say you lack information.\n\n"
    "RULES:\n"
    "- ALWAYS attempt an answer when context is provided, even if partial\n"
    "- NEVER invent configs, paths, SPL syntax, or parameter values\n"
    "- Cite sources (file names, stanzas, specs)\n"
    "- Be concise. For configs, include ALL parameters verbatim\n"
    "- Only say you cannot answer if the context is COMPLETELY unrelated to the question\n"
    "- SPL: prefer tstats, use TERM(), specify index, filter early\n"
    "- Present SPL in ```spl blocks\n"
)

def _format_optimizer_bypass_response(opt_result, original_query, action):
    """
    Formats the response when the LLM is bypassed.

    Handles multiple response formats:
    - Remote optimizer dict: optimized query nested under
      opt_result["optimization"]["optimized_query"] or
      opt_result["improvement"]["improved_query"] or
      opt_result["generated_query"]
    - Local OptimizedQuery dataclass: .optimized attribute
    """
    if not opt_result:
        return None

    # Extract the optimized query from whichever location it lives in
    optimized_query = None
    strategy = None
    performance_notes = []
    suggestions = []

    if isinstance(opt_result, dict):
        # Remote optimizer response - check nested structures
        opt_block = opt_result.get("optimization") or {}
        imp_block = opt_result.get("improvement") or {}

        if opt_block.get("optimized_query"):
            optimized_query = opt_block["optimized_query"]
            strategy = opt_block.get("strategy")
            performance_notes = opt_block.get("performance_notes") or []
            suggestions = opt_block.get("suggestions") or []
        elif imp_block.get("improved_query"):
            optimized_query = imp_block["improved_query"]
            performance_notes = imp_block.get("notes") or []
        elif opt_result.get("generated_query"):
            optimized_query = opt_result["generated_query"]
        # Fallback: top-level key (for local optimizer dict wrapper)
        elif opt_result.get("optimized_query"):
            optimized_query = opt_result["optimized_query"]
    else:
        # Local OptimizedQuery dataclass
        optimized_query = getattr(opt_result, "optimized", None)
        strategy = getattr(opt_result, "strategy", None)
        if strategy:
            strategy = strategy.value if hasattr(strategy, "value") else str(strategy)
        performance_notes = getattr(opt_result, "performance_notes", []) or []

    if not optimized_query:
        return None

    # Don't bypass if the query is unchanged
    if optimized_query.strip() == original_query.strip():
        return None

    if action == "review":
        # For review, show validation results
        review_block = opt_result.get("review", {}) if isinstance(opt_result, dict) else {}
        status = review_block.get("status", "valid")
        risk = review_block.get("risk_score", 0)
        errors = review_block.get("errors", [])
        warnings = review_block.get("warnings", [])

        parts = [f"**Query Review** (Status: {status}, Risk: {risk}/100)\n"]
        if errors:
            parts.append("**Errors:**")
            for e in errors:
                parts.append(f"- {e}")
        if warnings:
            parts.append("**Warnings:**")
            for w in warnings:
                parts.append(f"- {w}")
        if optimized_query != original_query.strip():
            parts.append(f"\n**Suggested Improvement:**\n```spl\n{optimized_query}\n```")
        else:
            parts.append(f"\n**Query:**\n```spl\n{original_query}\n```")
        return "\n".join(parts)

    # For optimize/improve actions - format bypass response
    parts = ["**Optimized Query:**\n```spl", optimized_query, "```"]

    if strategy:
        parts.append(f"\n**Strategy:** {strategy}")

    if performance_notes:
        parts.append("\n**Performance Notes:**")
        for note in performance_notes[:5]:
            parts.append(f"- {note}")

    if suggestions:
        parts.append("\n**Additional Suggestions:**")
        for s in suggestions[:3]:
            parts.append(f"- {s}")

    return "\n".join(parts)

@observe_llm(name="generate_response")
async def generate_response(
    user_input: str,
    formatted_context: str,
    chain,
    user_settings: dict,
    context_hash: str,
    feedback_match: Optional[dict] = None,
    profile: Optional[str] = None,
) -> str:
    """
    Generate a response using the appropriate strategy.

    Returns the response text.
    """
    # Check cache first
    cached_response = await get_cached_query_response(user_input, context_hash)
    if cached_response:
        _cache_stats["hits"] = _cache_stats.get("hits", 0) + 1
        logger.info(f"Cache hit for query: {user_input[:50]}...")
        return f"*[Cached Response]*\n\n{cached_response}"
    _cache_stats["misses"] = _cache_stats.get("misses", 0) + 1

    # Use previously validated answer if available
    if feedback_match:
        logger.info(f"[FEEDBACK] Using validated answer (similarity={feedback_match.get('similarity', 0):.2f})")
        try:
            from feedback_retriever import format_feedback_response
            return format_feedback_response(feedback_match)
        except Exception as _exc:  # broad catch — resilience against all failures
            return feedback_match.get("answer", "")

    # Check if this is a SPL template request (only for specific SPL keywords, not generic words)
    lower = user_input.lower()
    _EDUCATIONAL_SIGNALS = [
        'how to use', 'how do i use', 'how can i use', 'when to use',
        'when should i use', 'what is', 'what are', 'explain',
        'what does', 'how does', 'difference between', 'vs ',
        'versus', 'tell me about', 'teach me', 'help me understand',
        'documentation', 'syntax', 'examples of',
    ]
    _is_educational = any(sig in lower for sig in _EDUCATIONAL_SIGNALS)
    is_spl_template_candidate = (
        any(kw in lower for kw in ['tstats', 'term(', 'prefix('])
        and not _is_educational
    )

    if is_spl_template_candidate:
        result = try_spl_template(user_input)
        if result is not None:
            return result

    # General LLM response
    return await _generate_llm_response(user_input, formatted_context, chain, user_settings, context_hash, profile=profile)



@observe_llm(name="llm_inference", as_type="generation")
async def _generate_llm_response(
    user_input: str,
    formatted_context: str,
    chain,
    user_settings: dict,
    context_hash: str,
    profile: Optional[str] = None,
) -> str:
    """Generate response via LLM with streaming/non-streaming support."""
    from ollama import ResponseError
    import time as _time
    _llm_start = _time.monotonic()

    try:
        # Truncate context for speed — smaller context = faster LLM inference
        _fast = get_settings().fast_mode
        lower = user_input.lower()
        is_conf_query = any(kw in lower for kw in ['.conf', 'savedsearch', 'saved search', 'saved_search', 'stanza', 'inputs.conf', 'props.conf', 'transforms.conf', 'spec'])
        is_org_profile = profile in ("org_expert", "config_helper")
        if _fast:
            # CPU-only: aggressively limit context to keep inference under 15s
            max_tokens = 400
            max_chars_fallback = 1500
        elif is_org_profile or is_conf_query:
            max_tokens = 1500
            max_chars_fallback = 6000
        else:
            max_tokens = 1000
            max_chars_fallback = 4000
        try:
            from utils import truncate_context
            formatted_context = truncate_context(formatted_context, max_tokens=max_tokens)
        except ImportError:
            if len(formatted_context) > max_chars_fallback:
                logger.warning(f"Context truncated from {len(formatted_context)} to {max_chars_fallback} chars")
                formatted_context = formatted_context[:max_chars_fallback] + "\n\n[...context truncated]"

        # Apply response_style, include_examples, splunk_version settings
        style = user_settings.get("response_style", "detailed")
        include_examples = user_settings.get("include_examples", True)
        splunk_version = user_settings.get("splunk_version", "9.5.4")
        max_response_length = int(user_settings.get("max_response_length", 2000))
        style_guidance = ""
        if style == "concise":
            style_guidance = "\n\nBe concise. Answer in 2-3 sentences max. No lengthy explanations."
        elif style == "tutorial":
            style_guidance = "\n\nRespond in tutorial style: step-by-step with detailed explanations for beginners."
        if not include_examples:
            style_guidance += "\n\nDo NOT include SPL code examples in your response."
        style_guidance += f"\n\nAssume Splunk version {splunk_version} unless the user specifies otherwise."

        # For org_expert profile, emphasize using org repo context over generic knowledge
        if is_org_profile:
            org_guidance = (
                "**IMPORTANT: You are the Organization Expert.**\n"
                "Your PRIMARY source is the Knowledge Base context below (the organization's actual configs).\n"
                "Answer FROM the repo/org data — quote stanza names, parameter values, and file paths verbatim.\n"
                "Only fall back to generic Splunk knowledge if no relevant org data appears in the context.\n\n"
            )
            prompt_input = f"{org_guidance}{RESPONSE_GUIDANCE}{style_guidance}\n\n{formatted_context}\n\n**Question:** {user_input}"
        else:
            prompt_input = f"{RESPONSE_GUIDANCE}{style_guidance}\n\n{formatted_context}\n\n**Question:** {user_input}"

        logger.info(f"[LLM] Calling LLM with context size: {len(formatted_context)} chars")

        enable_streaming = user_settings.get("enable_streaming", True)
        used_streaming = False

        _settings = get_settings()
        llm_timeout = _settings.ollama.timeout if hasattr(_settings.ollama, 'timeout') else 120

        if enable_streaming:
            logger.info("[LLM] Using streaming mode (timeout=%ds)", llm_timeout)
            used_streaming = True

            try:
                streaming_msg = cl.Message(content="")
                await streaming_msg.send()

                result_text = ""

                async def _stream():
                    nonlocal result_text
                    async for token in chain.astream({"input": prompt_input}):
                        if token:
                            result_text += token
                            await streaming_msg.stream_token(token)

                await asyncio.wait_for(_stream(), timeout=llm_timeout)
                cl.user_session.set("streaming_msg", streaming_msg)
            except asyncio.TimeoutError:
                logger.warning("[LLM] Streaming timed out after %ds", llm_timeout)
                if not result_text:
                    result_text = "The LLM took too long to respond. Please try a more specific question or try again later."
                # Use whatever partial response we got
                cl.user_session.set("streaming_msg", streaming_msg)
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as stream_exc:
                logger.warning(f"[LLM] Streaming failed, falling back to non-streaming: {stream_exc}")
                used_streaming = False
                enable_streaming = False  # fall through to non-streaming below

        if not enable_streaming:
            logger.info("[LLM] Using non-streaming mode (timeout=%ds)", llm_timeout)

            async def call_llm():
                return await with_priority(
                    cl.make_async(chain.invoke),
                    RequestPriority.USER_QUERY,
                    {"input": prompt_input}
                )

            try:
                result_text = await asyncio.wait_for(
                    call_with_resilience(
                        call_llm,
                        service_name="ollama",
                        max_retries=3,
                        fallback_value=None,
                    ),
                    timeout=llm_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning("[LLM] Non-streaming timed out after %ds", llm_timeout)
                result_text = "The LLM took too long to respond. Please try a more specific question or try again later."

        _llm_elapsed = _time.monotonic() - _llm_start
        _model = get_settings().ollama.model
        logger.info(f"[LLM] Response received, length: {len(result_text) if result_text else 0} chars, latency={_llm_elapsed:.2f}s")
        record_llm_call(model=_model, status="success", latency=_llm_elapsed)

        # Cost tracking — estimate tokens from character counts (~4 chars per token)
        try:
            from chat_app.cost_tracker import record_llm_cost
            _input_chars = len(formatted_context) + len(user_input)
            _output_chars = len(result_text) if result_text else 0
            _est_input_tokens = _input_chars // 4
            _est_output_tokens = _output_chars // 4
            record_llm_cost(
                model=_model,
                purpose="generation",
                input_tokens=_est_input_tokens,
                output_tokens=_est_output_tokens,
                latency_ms=int(_llm_elapsed * 1000),
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

        # Langfuse generation tracking
        try:
            from chat_app.langfuse_integration import is_enabled as _lf_ok
            if _lf_ok():
                from langfuse import Langfuse
                _lf = Langfuse()
                _lf.generation(
                    name="llm_response",
                    model=_model,
                    input=user_input[:500],
                    output=(result_text or "")[:1000],
                    metadata={
                        "context_chars": len(formatted_context),
                        "streaming": used_streaming,
                        "profile": profile,
                        "latency_s": round(_llm_elapsed, 2),
                    },
                )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

        if not result_text:
            result_text = "I'm sorry, the LLM service is currently unavailable. Please try again in a moment."
            logger.error("[LLM] result_text is None/empty after LLM call")

        # Strip any "Confidence:" line the LLM added
        if result_text.startswith("**Confidence:**"):
            lines = result_text.split('\n', 1)
            if len(lines) > 1:
                result_text = lines[1].lstrip()

        # Enforce max response length (~5 chars per token estimate)
        if max_response_length and len(result_text) > max_response_length * 5:
            result_text = result_text[:max_response_length * 5]
            # Find last complete sentence
            last_period = result_text.rfind('.')
            last_newline = result_text.rfind('\n')
            cut_point = max(last_period, last_newline)
            if cut_point > len(result_text) * 0.7:
                result_text = result_text[:cut_point + 1]

        # Validate SPL if query generation request
        result_text = await validate_spl_in_response(user_input, result_text, chain)

        # Cache the response
        await cache_query_response(user_input, context_hash, result_text)

        return result_text

    except ResponseError as e:
        _llm_elapsed = _time.monotonic() - _llm_start
        _model = get_settings().ollama.model
        record_llm_call(model=_model, status="error", latency=_llm_elapsed)
        if "not found" in str(e).lower():
            raise RuntimeError(
                f"LLM model `{_model}` not available. Please pull: `ollama pull {_model}`"
            )
        raise
    except Exception as _exc:  # broad catch — resilience against all failures
        _llm_elapsed = _time.monotonic() - _llm_start
        record_llm_call(model=get_settings().ollama.model, status="error", latency=_llm_elapsed)
        raise



