"""
ReAct (Reason-Act-Observe) Loop — Agentic reasoning for complex queries.

Implements a structured reasoning loop:
1. THINK: Analyze the query and decide what tool/action to take
2. ACT: Execute the chosen tool
3. OBSERVE: Process the result
4. REPEAT or RESPOND: Either take another action or formulate the final answer

This module is called by the main message handler for queries that
benefit from multi-step reasoning (complex analysis, multi-tool tasks, etc.).
"""
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from chat_app.registry import Intent
from chat_app.tool_registry import (
    ToolRegistry, get_tool_registry,
)

logger = logging.getLogger(__name__)

# Maximum reasoning steps before forcing a response
MAX_REASONING_STEPS = 5

# Intents that benefit from agentic reasoning — derived from registry
AGENTIC_INTENTS = {
    Intent.SPL_GENERATION,
    Intent.SPL_OPTIMIZATION,
    Intent.SAVED_SEARCH_ANALYSIS,
    Intent.CONFIG_HEALTH_CHECK,
    Intent.TROUBLESHOOTING,
    Intent.CRIBL_PIPELINE,
    Intent.CRIBL_CONFIG,
    Intent.OBSERVABILITY_METRICS,
}


@dataclass
class ReasoningStep:
    """A single step in the reasoning chain."""
    step_num: int
    thought: str
    action: Optional[str] = None
    action_args: Dict[str, Any] = field(default_factory=dict)
    observation: Optional[str] = None
    duration_ms: int = 0


@dataclass
class ReasoningTrace:
    """Full trace of the reasoning process."""
    query: str
    intent: str
    steps: List[ReasoningStep] = field(default_factory=list)
    final_answer: Optional[str] = None
    tools_used: List[str] = field(default_factory=list)
    total_duration_ms: int = 0
    success: bool = True

    def format_trace(self) -> str:
        """Format the trace for debugging/logging."""
        lines = [f"Query: {self.query[:80]}", f"Intent: {self.intent}"]
        for step in self.steps:
            lines.append(f"  Step {step.step_num}: {step.thought[:100]}")
            if step.action:
                lines.append(f"    Action: {step.action}({step.action_args})")
            if step.observation:
                lines.append(f"    Observation: {step.observation[:100]}")
        lines.append(f"Tools used: {', '.join(self.tools_used)}")
        lines.append(f"Duration: {self.total_duration_ms}ms")
        return "\n".join(lines)


def should_use_react(intent: str, user_input: str, plan: Any = None) -> bool:
    """
    Decide whether to use the ReAct loop vs. simple single-pass.

    Uses ReAct for:
    - Complex multi-step intents
    - Queries mentioning multiple operations (analyze AND optimize, etc.)
    - Queries with raw SPL that needs validation + optimization
    """
    if intent in AGENTIC_INTENTS:
        return True

    lower = user_input.lower()

    # Multi-action signals
    multi_action = bool(re.search(
        r'\b(and then|then also|also|as well as|plus|additionally)\b', lower
    ))
    if multi_action and len(lower) > 50:
        return True

    # Complex SPL analysis (raw SPL with optimization request)
    has_spl = bool(re.search(r'\bindex\s*=|\|\s*stats\b|\|\s*tstats\b', lower))
    wants_analysis = bool(re.search(r'\b(analyze|optimize|review|check|validate|improve)\b', lower))
    if has_spl and wants_analysis:
        return True

    return False


def plan_actions(
    user_input: str,
    intent: str,
    available_tools: List[Any],
    context_chunks: List[dict] = None,
) -> List[Tuple[str, Dict[str, Any]]]:
    """
    Plan which tools to use and in what order.

    Returns a list of (tool_name, args) tuples.
    """
    lower = user_input.lower()
    planned = []

    # Extract SPL from input
    spl_match = re.search(r'```(?:spl)?\n(.+?)\n```', user_input, re.DOTALL)
    raw_spl = spl_match.group(1).strip() if spl_match else None

    # Also check for inline SPL (index=... | stats ...)
    if not raw_spl:
        inline_match = re.search(
            r'((?:index\s*=\s*\S+|(?:\|\s*\w+\s+))\S.*?)(?:\n|$)',
            user_input, re.DOTALL
        )
        if inline_match:
            candidate = inline_match.group(1).strip()
            # Only accept if it looks like real SPL (has pipe or index=)
            if '|' in candidate or 'index=' in candidate.lower():
                raw_spl = candidate

    tool_names = {t.name for t in available_tools}

    if intent == Intent.SPL_GENERATION:
        if raw_spl:
            # User provided SPL — analyze and optimize
            if "analyze_spl" in tool_names:
                planned.append(("analyze_spl", {"query": raw_spl, "auto_fix": True}))
            wants_optimize = bool(re.search(r'\b(optimize|improve|faster|speed|tstats)\b', lower))
            if wants_optimize and "optimize_spl" in tool_names:
                planned.append(("optimize_spl", {"query": raw_spl}))
            if "validate_spl" in tool_names:
                planned.append(("validate_spl", {"query": raw_spl}))
        else:
            # Natural language — generate SPL
            if "generate_spl" in tool_names:
                planned.append(("generate_spl", {"description": user_input}))

    elif intent == Intent.SPL_OPTIMIZATION:
        if raw_spl:
            if "optimize_spl" in tool_names:
                planned.append(("optimize_spl", {"query": raw_spl}))
            if "validate_spl" in tool_names:
                planned.append(("validate_spl", {"query": raw_spl}))

    elif intent == Intent.SAVED_SEARCH_ANALYSIS:
        if "list_saved_searches" in tool_names:
            planned.append(("list_saved_searches", {}))

    elif intent == Intent.CONFIG_HEALTH_CHECK:
        if "analyze_configs" in tool_names:
            planned.append(("analyze_configs", {}))

    elif intent == Intent.CONFIG_LOOKUP:
        conf_refs = re.findall(r'([a-z_]+\.conf)', lower)
        for conf in conf_refs[:2]:
            if "lookup_config" in tool_names:
                planned.append(("lookup_config", {"conf_file": conf}))

    elif intent in (Intent.CRIBL_PIPELINE, Intent.CRIBL_CONFIG):
        if "analyze_cribl_pipeline" in tool_names and ('pipeline' in lower or 'config' in lower):
            planned.append(("analyze_cribl_pipeline", {"pipeline_config": user_input}))
        elif "generate_cribl_route" in tool_names:
            planned.append(("generate_cribl_route", {"description": user_input}))

    elif intent == Intent.OBSERVABILITY_METRICS:
        metric_match = re.search(r'\b(cpu|memory|disk|network|latency|throughput|error.rate)\b', lower)
        if metric_match and "suggest_metrics_query" in tool_names:
            planned.append(("suggest_metrics_query", {"metric_name": metric_match.group(1)}))

    elif intent == Intent.TROUBLESHOOTING:
        if "search_knowledge_base" in tool_names:
            planned.append(("search_knowledge_base", {"query": user_input}))
        if raw_spl and "validate_spl" in tool_names:
            planned.append(("validate_spl", {"query": raw_spl}))

    elif intent == Intent.RUN_SEARCH:
        if raw_spl and "run_splunk_search" in tool_names:
            planned.append(("run_splunk_search", {"query": raw_spl}))

    # Fallback: search knowledge base for general queries
    if not planned and "search_knowledge_base" in tool_names:
        planned.append(("search_knowledge_base", {"query": user_input}))

    return planned


async def execute_react_loop(
    user_input: str,
    intent: str,
    registry: ToolRegistry = None,
    context_chunks: List[dict] = None,
    max_steps: int = MAX_REASONING_STEPS,
) -> ReasoningTrace:
    """
    Execute the full ReAct reasoning loop.

    Returns a ReasoningTrace with all steps and the final answer.
    """
    if registry is None:
        registry = get_tool_registry()

    start_time = time.monotonic()
    trace = ReasoningTrace(query=user_input, intent=intent)

    # Get available tools
    available_tools = registry.get_available_tools()
    if not available_tools:
        trace.final_answer = None  # No tools available, fall back to standard pipeline
        return trace

    # Plan initial actions
    planned_actions = plan_actions(user_input, intent, available_tools, context_chunks)

    if not planned_actions:
        trace.final_answer = None  # Nothing to do, fall back
        return trace

    # Execute planned actions
    tool_outputs = []
    for step_num, (tool_name, tool_args) in enumerate(planned_actions[:max_steps], 1):
        step_start = time.monotonic()

        step = ReasoningStep(
            step_num=step_num,
            thought=f"Using '{tool_name}' to process the query",
        )

        step.action = tool_name
        step.action_args = tool_args

        # Execute the tool
        result = await registry.execute(tool_name, **tool_args)

        step.observation = result.output[:500] if result.output else (result.error or "No output")
        step.duration_ms = int((time.monotonic() - step_start) * 1000)

        trace.steps.append(step)
        trace.tools_used.append(tool_name)

        if result.success and result.output:
            tool_outputs.append(f"**[{tool_name}]**\n{result.output}")
        elif result.error:
            tool_outputs.append(f"**[{tool_name}]** Error: {result.error}")
            logger.warning(f"[REACT] Tool {tool_name} failed: {result.error}")

        # If the tool produced suggestions for follow-up tools, add them
        if result.suggestions:
            for suggestion in result.suggestions:
                logger.info(f"[REACT] Tool suggestion: {suggestion}")

    # Combine tool outputs as the enrichment context
    if tool_outputs:
        trace.final_answer = "\n\n---\n\n".join(tool_outputs)
    else:
        trace.final_answer = None

    trace.total_duration_ms = int((time.monotonic() - start_time) * 1000)
    logger.info(f"[REACT] Completed: {len(trace.steps)} steps, {len(trace.tools_used)} tools, {trace.total_duration_ms}ms")

    return trace


def format_tool_context_for_llm(trace: ReasoningTrace) -> Optional[str]:
    """
    Format tool execution results as additional context for the LLM.

    This is injected into the prompt so the LLM can synthesize tool
    results with RAG context into a coherent response.
    """
    if not trace.steps or not trace.final_answer:
        return None

    parts = ["### Agentic Tool Results"]
    parts.append("The following analysis was performed automatically:\n")

    for step in trace.steps:
        if step.observation and step.action:
            parts.append(f"**Tool: {step.action}**")
            parts.append(step.observation)
            parts.append("")

    return "\n".join(parts)
