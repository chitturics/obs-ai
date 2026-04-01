"""
MCP Tool Executor for the Splunk Assistant.

Binds MCP tools to the LLM and handles tool-calling flows.
When the user requests actions (run search, create alert, etc.),
the tool-bound LLM decides which tool to call, this module
executes it, and feeds the result back for a final response.

Supports two modes:
1. **Native tool calling** — LangChain ``bind_tools()`` when the LLM and
   tools both support it (requires langchain-core).
2. **Prompt-based tool calling** — Falls back to embedding tool descriptions
   in the system prompt and parsing the LLM's JSON response.  Works with
   any LLM and any tool that exposes ``ainvoke(args)``.
"""
import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Availability flag
_TOOL_CALLING_AVAILABLE = False
_tool_bound_llm = None

try:
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage  # noqa: F401
    _TOOL_CALLING_AVAILABLE = True
except ImportError:
    logger.info("langchain-core messages not available — native tool calling disabled")


def bind_tools_to_llm(llm, tools: List[Any]):
    """
    Bind MCP tools to the LLM for tool-calling capabilities.

    Returns a tool-bound LLM instance, or None if binding fails.
    """
    global _tool_bound_llm

    if not tools:
        logger.info("[TOOLS] No tools to bind")
        return None

    if not _TOOL_CALLING_AVAILABLE:
        logger.info("[TOOLS] Tool calling not available (missing langchain-core)")
        return None

    try:
        bound = llm.bind_tools(tools)
        _tool_bound_llm = bound
        tool_names = [getattr(t, "name", str(t)) for t in tools]
        logger.info(f"[TOOLS] Bound {len(tools)} tools to LLM: {tool_names}")
        return bound
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[TOOLS] Failed to bind tools to LLM: {exc}")
        return None


def get_tool_bound_llm():
    """Return the tool-bound LLM, or None if not available."""
    return _tool_bound_llm


async def execute_tool_call(
    tool_call: Dict[str, Any],
    available_tools: List[Any],
) -> str:
    """
    Execute a single tool call and return the result as a string.

    Args:
        tool_call: Dict with 'name', 'args', and 'id' from the LLM response.
        available_tools: List of tool objects (LangChain or MCPTool).

    Returns:
        String result from the tool execution.
    """
    tool_name = tool_call.get("name", "")
    tool_args = tool_call.get("args", {})

    # Find the matching tool
    tool = None
    for t in available_tools:
        if getattr(t, "name", "") == tool_name:
            tool = t
            break

    if tool is None:
        return f"Tool '{tool_name}' not found in available tools."

    try:
        logger.info(f"[TOOLS] Executing tool: {tool_name} with args: {tool_args}")
        # Tools may be sync or async
        if hasattr(tool, "ainvoke"):
            result = await tool.ainvoke(tool_args)
        elif hasattr(tool, "invoke"):
            result = await asyncio.get_running_loop().run_in_executor(
                None, lambda: tool.invoke(tool_args)
            )
        elif callable(tool):
            result = await asyncio.get_running_loop().run_in_executor(
                None, lambda: tool(tool_args)
            )
        else:
            return f"Tool '{tool_name}' is not callable."

        logger.info(f"[TOOLS] Tool {tool_name} returned result (length={len(str(result))})")
        try:
            from chat_app.health_monitor import get_internal_metrics
            get_internal_metrics().increment("tool_executions")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass
        return str(result) if result is not None else "Tool executed successfully (no output)."

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error(f"[TOOLS] Tool {tool_name} failed: {exc}")
        try:
            from chat_app.health_monitor import get_internal_metrics
            im = get_internal_metrics()
            im.increment("tool_executions")
            im.increment("tool_failures")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass
        return f"Tool execution failed: {exc}"


# ---------------------------------------------------------------------------
# Native tool-calling flow (requires langchain-core + bind_tools support)
# ---------------------------------------------------------------------------

async def _run_native_tool_loop(
    user_input: str,
    llm,
    tools: List[Any],
    system_prompt: str = "",
    context: str = "",
    max_tool_rounds: int = 3,
) -> Optional[str]:
    """LangChain ``bind_tools`` flow."""
    bound_llm = bind_tools_to_llm(llm, tools) if _tool_bound_llm is None else _tool_bound_llm
    if bound_llm is None:
        return None

    from langchain_core.messages import SystemMessage  # noqa: F401

    messages = []
    if system_prompt:
        messages.append(SystemMessage(content=system_prompt))
    if context:
        messages.append(HumanMessage(content=f"Context:\n{context}\n\nQuestion: {user_input}"))
    else:
        messages.append(HumanMessage(content=user_input))

    for round_num in range(max_tool_rounds):
        try:
            response = await bound_llm.ainvoke(messages)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning(f"[TOOLS] LLM invocation failed (round {round_num}): {exc}")
            return None

        tool_calls = getattr(response, "tool_calls", None)
        if not tool_calls:
            content = getattr(response, "content", "")
            return content if content else None

        messages.append(response)
        for tc in tool_calls:
            result = await execute_tool_call(tc, tools)
            messages.append(ToolMessage(
                content=result,
                tool_call_id=tc.get("id", f"call_{round_num}"),
            ))
            logger.info(f"[TOOLS] Round {round_num + 1}: executed {tc.get('name', 'unknown')}")

    try:
        final = await bound_llm.ainvoke(messages)
        content = getattr(final, "content", "")
        return content if content else None
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[TOOLS] Final response failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Prompt-based tool-calling fallback (works with any LLM + MCPTool)
# ---------------------------------------------------------------------------

def _build_tool_descriptions(tools: List[Any]) -> str:
    """Build a system-prompt section describing available tools."""
    lines = ["You have access to the following tools:\n"]
    for t in tools:
        name = getattr(t, "name", "unknown")
        desc = getattr(t, "description", "")
        schema = getattr(t, "input_schema", {})
        params = ""
        if schema and schema.get("properties"):
            param_parts = []
            for pname, pinfo in schema["properties"].items():
                ptype = pinfo.get("type", "string")
                pdesc = pinfo.get("description", "")
                param_parts.append(f"    - {pname} ({ptype}): {pdesc}")
            params = "\n" + "\n".join(param_parts)
        lines.append(f"- **{name}**: {desc}{params}")

    lines.append(
        "\nTo use a tool, respond with EXACTLY this JSON block (and nothing else before it):\n"
        '```json\n{"tool": "<tool_name>", "args": {<arguments>}}\n```\n'
        "If you don't need a tool, just respond normally."
    )
    return "\n".join(lines)


def _parse_tool_call(text: str) -> Optional[Dict[str, Any]]:
    """Try to extract a tool call from LLM text output."""
    # Try JSON code block first
    json_block = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if json_block:
        try:
            data = json.loads(json_block.group(1))
            if "tool" in data:
                return {"name": data["tool"], "args": data.get("args", {})}
        except json.JSONDecodeError as _exc:
            logger.debug("Could not parse JSON tool call from code block: %s", _exc)

    # Try bare JSON at start of text
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            data = json.loads(stripped.split("\n\n")[0])
            if "tool" in data:
                return {"name": data["tool"], "args": data.get("args", {})}
        except json.JSONDecodeError as _exc:
            logger.debug("Could not parse bare JSON tool call from text start: %s", _exc)

    return None


async def _run_prompt_tool_loop(
    user_input: str,
    llm,
    tools: List[Any],
    system_prompt: str = "",
    context: str = "",
    max_tool_rounds: int = 3,
) -> Optional[str]:
    """Prompt-based tool calling for non-LangChain tools."""
    tool_section = _build_tool_descriptions(tools)
    full_prompt = f"{system_prompt}\n\n{tool_section}" if system_prompt else tool_section

    if context:
        query = f"Context:\n{context}\n\nQuestion: {user_input}"
    else:
        query = user_input

    for round_num in range(max_tool_rounds):
        try:
            if hasattr(llm, "ainvoke"):
                response = await llm.ainvoke(f"{full_prompt}\n\nUser: {query}")
            elif hasattr(llm, "invoke"):
                import asyncio
                response = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: llm.invoke(f"{full_prompt}\n\nUser: {query}")
                )
            else:
                return None
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[TOOLS] Prompt-based LLM call failed (round %d): %s", round_num, exc)
            return None

        text = getattr(response, "content", str(response)) if hasattr(response, "content") else str(response)

        tc = _parse_tool_call(text)
        if not tc:
            return text if text.strip() else None

        result = await execute_tool_call(tc, tools)
        logger.info("[TOOLS] Prompt-based round %d: executed %s", round_num + 1, tc["name"])
        query = (
            f"Previous question: {user_input}\n\n"
            f"Tool '{tc['name']}' returned:\n{result}\n\n"
            "Using the tool result above, provide a complete answer to the user's question."
        )

    return None


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

async def run_tool_augmented_query(
    user_input: str,
    llm,
    tools: List[Any],
    system_prompt: str = "",
    context: str = "",
    max_tool_rounds: int = 3,
) -> Optional[str]:
    """
    Run a tool-augmented LLM query.

    Tries native LangChain tool calling first; if that's unavailable or
    the tools don't support ``bind_tools``, falls back to prompt-based
    tool selection.

    Returns None if no tools were triggered or tool calling failed.
    """
    if not tools:
        return None

    # Try native tool calling first
    if _TOOL_CALLING_AVAILABLE:
        try:
            result = await _run_native_tool_loop(
                user_input, llm, tools, system_prompt, context, max_tool_rounds,
            )
            if result is not None:
                return result
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.info("[TOOLS] Native tool calling failed, trying prompt-based: %s", exc)

    # Fallback: prompt-based tool calling
    return await _run_prompt_tool_loop(
        user_input, llm, tools, system_prompt, context, max_tool_rounds,
    )


def should_use_tools(intent: str) -> bool:
    """
    Determine if the query intent warrants tool calling.

    Tool calling is used for actionable intents that need live Splunk interaction.
    """
    tool_intents = {
        "run_search",
        "create_alert",
        "saved_search_analysis",
        "config_health_check",
    }
    return intent in tool_intents
