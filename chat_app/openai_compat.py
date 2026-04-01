"""
OpenAI-compatible API endpoints for ObsAI - Observability AI Assistant.

Exposes /v1/models and /v1/chat/completions so that Open WebUI (or any
OpenAI-compatible client) can consume the assistant as if it were an
OpenAI model.

This module does NOT import chainlit — it talks directly to the existing
pipeline functions (retrieve_context, build_llm_context, generate_response).
"""
import json
import logging
import time
import uuid
from typing import AsyncGenerator, List, Optional

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel, Field

from chat_app.session_store import session_store

logger = logging.getLogger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Request / response models (OpenAI-compatible subset)
# ---------------------------------------------------------------------------

class ChatMessage(BaseModel):
    role: str = "user"
    content: str = ""


class ChatCompletionRequest(BaseModel):
    model: str = "obsai"
    messages: List[ChatMessage] = Field(default_factory=list)
    stream: bool = False
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None


# ---------------------------------------------------------------------------
# Module-level reference to the pipeline context builder.
# Set by app_api.py after initialisation is complete.
# ---------------------------------------------------------------------------
_context_factory = None      # async callable -> MessageHandlerContext
_chain = None                # LangChain chain (prompt | LLM | parser)
_llm = None                  # Raw LLM instance
_system_prompt: str = ""
_model_name: str = "obsai"


def configure(*, context_factory, chain, llm, system_prompt: str, model_name: str):
    """Called once at startup by app_api.py to inject dependencies."""
    global _context_factory, _chain, _llm, _system_prompt, _model_name
    _context_factory = context_factory
    _chain = chain
    _llm = llm
    _system_prompt = system_prompt
    _model_name = model_name


# ---------------------------------------------------------------------------
# /v1/models
# ---------------------------------------------------------------------------

@router.get("/v1/models")
async def list_models():
    return {
        "object": "list",
        "data": [
            {
                "id": _model_name,
                "object": "model",
                "created": int(time.time()),
                "owned_by": "obsai-local",
            }
        ],
    }


# ---------------------------------------------------------------------------
# /v1/chat/completions
# ---------------------------------------------------------------------------

@router.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    req = ChatCompletionRequest(**body)

    # Extract the last user message
    user_input = ""
    for msg in reversed(req.messages):
        if msg.role == "user":
            user_input = msg.content.strip()
            break

    if not user_input:
        return JSONResponse(
            {"error": {"message": "No user message provided", "type": "invalid_request_error"}},
            status_code=400,
        )

    # Thread management — use header or generate
    thread_id = request.headers.get("x-thread-id", str(uuid.uuid4()))
    session_store.create_session(thread_id)

    if req.stream:
        return StreamingResponse(
            _stream_response(user_input, thread_id, req),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
    else:
        text = await _generate_full_response(user_input, thread_id, req)
        return _format_completion(text, req.model)


# ---------------------------------------------------------------------------
# Internal pipeline wrappers
# ---------------------------------------------------------------------------

async def _generate_full_response(user_input: str, thread_id: str, req: ChatCompletionRequest) -> str:
    """Run the full RAG pipeline and return the complete response text."""
    try:
        return await _run_pipeline(user_input, thread_id)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("Pipeline error: %s", exc, exc_info=True)
        return f"I encountered an error processing your request. Please try again.\n\n*Error: {type(exc).__name__}*"


async def _stream_response(user_input: str, thread_id: str, req: ChatCompletionRequest) -> AsyncGenerator[str, None]:
    """Stream response tokens as SSE in OpenAI chat.completion.chunk format."""
    chat_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    model = req.model or _model_name

    try:
        prompt_input = await _build_prompt_input(user_input, thread_id)

        # Stream tokens from the LangChain chain
        async for token in _chain.astream({"input": prompt_input}):
            if token:
                chunk = {
                    "id": chat_id,
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {"content": token},
                            "finish_reason": None,
                        }
                    ],
                }
                yield f"data: {json.dumps(chunk)}\n\n"

        # Final chunk
        done_chunk = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(done_chunk)}\n\n"
        yield "data: [DONE]\n\n"

    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        logger.error("Streaming error: %s", exc, exc_info=True)
        error_chunk = {
            "id": chat_id,
            "object": "chat.completion.chunk",
            "created": int(time.time()),
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "delta": {"content": f"\n\n[Error: {type(exc).__name__}]"},
                    "finish_reason": "stop",
                }
            ],
        }
        yield f"data: {json.dumps(error_chunk)}\n\n"
        yield "data: [DONE]\n\n"


async def _build_prompt_input(user_input: str, thread_id: str) -> str:
    """Build the full prompt input by running the RAG pipeline (minus Chainlit UI bits)."""
    if _context_factory is None:
        return user_input

    context = await _context_factory()
    user_settings = session_store.get(thread_id, "settings", {})

    # Import pipeline functions (they use cl.make_async but we can call the
    # sync functions directly via asyncio.to_thread)
    from query_router import route_query

    plan = route_query(user_input, user_settings)

    # Skip retrieval for meta questions
    from chat_app.registry import Intent
    if plan.intent == Intent.META_QUESTION and plan.skip_retrieval:
        return (
            "Answer the following question concisely and directly. "
            "Do NOT include any SPL queries, code blocks, or optimization notes "
            "unless the user specifically asks for them. Keep it to 2-4 sentences.\n\n"
            f"Question: {user_input}"
        )

    # Full RAG retrieval
    from chat_app.pipeline_retrieval import retrieve_context
    from chat_app.pipeline_response import build_llm_context
    from response_generator import RESPONSE_GUIDANCE

    current_profile = session_store.get(thread_id, "chat_profile", "general")

    memory_chunks, local_spec_content, local_spec_refs, detected_profile, chroma_source, has_conf_context, conf_files = await retrieve_context(
        user_input, context, user_settings,
        context.profiles_available, current_profile,
        context.map_source_to_url,
        context.SPEC_STATIC_ROOT, context.LOCAL_DOCS_ROOT, context.SPEC_SRC_ROOT,
    )

    formatted_context, base_system_prompt, feedback_match, all_refs, opt_result, plan, scored_chunks, doc_snippets = await build_llm_context(
        user_input, memory_chunks, local_spec_content, local_spec_refs,
        user_settings, context.engine, "api_user", context.system_prompt,
        context.profiles_available, detected_profile,
        context.feedback_guardrails_available,
        context.map_source_to_url, context.load_static_context,
        plan=plan, conf_files=conf_files,
    )

    # Confidence scoring (optional)
    try:
        from chat_app.confidence_scorer import score_confidence, format_confidence_for_context
        confidence = score_confidence(
            local_spec_content, memory_chunks, user_input, all_refs, feedback_match,
        )
        conf_note = format_confidence_for_context(confidence)
        formatted_context = f"{conf_note}\n\n{formatted_context}"
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # Context compression (optional)
    try:
        from chat_app.context_compressor import compress_context_if_needed
        formatted_context = compress_context_if_needed(formatted_context, max_tokens=4000)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # Build final prompt
    style = user_settings.get("response_style", "detailed")
    style_guidance = ""
    if style == "concise":
        style_guidance = "\n\nBe concise. Answer in 2-3 sentences max. No lengthy explanations."
    elif style == "tutorial":
        style_guidance = "\n\nRespond in tutorial style: step-by-step with detailed explanations for beginners."

    prompt_input = f"{RESPONSE_GUIDANCE}{style_guidance}\n\n{formatted_context}\n\n**Question:** {user_input}"
    return prompt_input


async def _run_pipeline(user_input: str, thread_id: str) -> str:
    """Run full pipeline (non-streaming) and return response text."""
    prompt_input = await _build_prompt_input(user_input, thread_id)

    result_text = ""
    async for token in _chain.astream({"input": prompt_input}):
        if token:
            result_text += token

    if not result_text:
        result_text = "I'm sorry, the LLM service is currently unavailable. Please try again in a moment."

    # Store in session for follow-up context
    session_store.set(thread_id, "last_question", user_input)
    session_store.set(thread_id, "last_answer", result_text)

    return result_text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _format_completion(text: str, model: str) -> dict:
    return {
        "id": f"chatcmpl-{uuid.uuid4().hex[:12]}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model or _model_name,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": text},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        },
    }
