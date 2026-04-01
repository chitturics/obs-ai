"""Comprehensive unit tests for chat_app.react_loop."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

from chat_app.react_loop import (
    AGENTIC_INTENTS,
    MAX_REASONING_STEPS,
    ReasoningStep,
    ReasoningTrace,
    execute_react_loop,
    format_tool_context_for_llm,
    plan_actions,
    should_use_react,
)
from chat_app.tool_registry import Tool, ToolCategory, ToolRegistry, ToolResult


# ---------------------------------------------------------------------------
# Helper: create a minimal Tool with only a name (for plan_actions tests)
# ---------------------------------------------------------------------------

def _make_tool(name: str, execute_fn=None) -> Tool:
    """Create a minimal Tool object for testing."""
    return Tool(
        name=name,
        description=f"Mock tool: {name}",
        category=ToolCategory.KNOWLEDGE,
        execute_fn=execute_fn,
    )


# ---------------------------------------------------------------------------
# ReasoningStep dataclass
# ---------------------------------------------------------------------------

class TestReasoningStep:
    def test_defaults(self):
        step = ReasoningStep(step_num=1, thought="thinking")
        assert step.step_num == 1
        assert step.thought == "thinking"
        assert step.action is None
        assert step.action_args == {}
        assert step.observation is None
        assert step.duration_ms == 0

    def test_all_fields_populated(self):
        step = ReasoningStep(
            step_num=3,
            thought="Analyzing query",
            action="analyze_spl",
            action_args={"query": "index=main", "auto_fix": True},
            observation="Found 2 issues",
            duration_ms=150,
        )
        assert step.step_num == 3
        assert step.thought == "Analyzing query"
        assert step.action == "analyze_spl"
        assert step.action_args == {"query": "index=main", "auto_fix": True}
        assert step.observation == "Found 2 issues"
        assert step.duration_ms == 150

    def test_action_args_default_factory_independence(self):
        """Each instance gets its own dict for action_args."""
        step_a = ReasoningStep(step_num=1, thought="a")
        step_b = ReasoningStep(step_num=2, thought="b")
        step_a.action_args["key"] = "value"
        assert "key" not in step_b.action_args


# ---------------------------------------------------------------------------
# ReasoningTrace dataclass
# ---------------------------------------------------------------------------

class TestReasoningTrace:
    def test_defaults(self):
        trace = ReasoningTrace(query="test query", intent="spl_generation")
        assert trace.query == "test query"
        assert trace.intent == "spl_generation"
        assert trace.steps == []
        assert trace.final_answer is None
        assert trace.tools_used == []
        assert trace.total_duration_ms == 0
        assert trace.success is True

    def test_format_trace_with_steps(self):
        trace = ReasoningTrace(query="find errors in index=main", intent="spl_generation")
        step = ReasoningStep(
            step_num=1,
            thought="Analyzing the SPL query",
            action="analyze_spl",
            action_args={"query": "index=main"},
            observation="No issues found",
        )
        trace.steps.append(step)
        trace.tools_used.append("analyze_spl")
        trace.total_duration_ms = 200

        output = trace.format_trace()
        assert "Query: find errors in index=main" in output
        assert "Intent: spl_generation" in output
        assert "Step 1:" in output
        assert "Analyzing the SPL query" in output
        assert "Action: analyze_spl" in output
        assert "Observation: No issues found" in output
        assert "Tools used: analyze_spl" in output
        assert "Duration: 200ms" in output

    def test_format_trace_empty_steps(self):
        trace = ReasoningTrace(query="hello", intent="general_qa")
        output = trace.format_trace()
        assert "Query: hello" in output
        assert "Intent: general_qa" in output
        assert "Tools used: " in output
        assert "Duration: 0ms" in output

    def test_tools_used_tracking(self):
        trace = ReasoningTrace(query="q", intent="i")
        trace.tools_used.extend(["tool_a", "tool_b", "tool_c"])
        output = trace.format_trace()
        assert "Tools used: tool_a, tool_b, tool_c" in output

    def test_format_trace_truncates_long_query(self):
        long_query = "x" * 200
        trace = ReasoningTrace(query=long_query, intent="i")
        output = trace.format_trace()
        # format_trace truncates query to 80 chars
        first_line = output.split("\n")[0]
        assert len(first_line) <= len("Query: ") + 80


# ---------------------------------------------------------------------------
# AGENTIC_INTENTS set
# ---------------------------------------------------------------------------

class TestAgenticIntents:
    def test_contains_key_intents(self):
        expected = {
            "spl_generation",
            "spl_optimization",
            "troubleshooting",
            "saved_search_analysis",
            "config_health_check",
            "cribl_pipeline",
            "cribl_config",
            "observability_metrics",
        }
        assert expected == AGENTIC_INTENTS

    def test_does_not_contain_non_agentic_intents(self):
        non_agentic = ["meta_question", "general_qa", "config_lookup", "greeting", "run_search"]
        for intent in non_agentic:
            assert intent not in AGENTIC_INTENTS

    def test_is_a_set(self):
        assert isinstance(AGENTIC_INTENTS, set)
        assert len(AGENTIC_INTENTS) == 8


# ---------------------------------------------------------------------------
# should_use_react()
# ---------------------------------------------------------------------------

class TestShouldUseReact:
    # --- Returns True for each AGENTIC_INTENTS member ---
    @pytest.mark.parametrize("intent", sorted(AGENTIC_INTENTS))
    def test_true_for_agentic_intents(self, intent):
        assert should_use_react(intent, "any input") is True

    # --- Returns False for non-agentic intents ---
    @pytest.mark.parametrize("intent", ["meta_question", "general_qa", "config_lookup"])
    def test_false_for_non_agentic_intents(self, intent):
        assert should_use_react(intent, "short") is False

    # --- Multi-action signals with long input ---
    @pytest.mark.parametrize("signal", ["and then", "also", "as well as", "additionally", "then also", "plus"])
    def test_true_for_multi_action_signals_long_input(self, signal):
        long_input = f"please do something with the search {signal} run the optimization step afterward"
        assert len(long_input) > 50
        assert should_use_react("general_qa", long_input) is True

    # --- Multi-action signals with short input ---
    @pytest.mark.parametrize("signal", ["and then", "also", "as well as"])
    def test_false_for_multi_action_signals_short_input(self, signal):
        short_input = f"do {signal} x"
        assert len(short_input) <= 50
        assert should_use_react("general_qa", short_input) is False

    # --- SPL with analysis request ---
    def test_true_for_spl_with_optimize(self):
        assert should_use_react("general_qa", "index=main | stats count optimize this query") is True

    def test_true_for_spl_with_review(self):
        assert should_use_react("general_qa", "review this index=main | stats count by host") is True

    def test_true_for_spl_with_validate(self):
        assert should_use_react("general_qa", "validate index=main | stats count by host") is True

    def test_true_for_spl_with_improve(self):
        assert should_use_react("general_qa", "improve index=main | stats count by host") is True

    def test_true_for_spl_with_check(self):
        assert should_use_react("general_qa", "check index=main | stats count by host") is True

    def test_true_for_spl_with_analyze(self):
        assert should_use_react("general_qa", "analyze | stats count by source") is True

    def test_true_for_tstats_with_analysis(self):
        assert should_use_react("general_qa", "| tstats count where index=main optimize please") is True

    # --- Returns False for plain question without SPL or agentic intent ---
    def test_false_for_plain_question(self):
        assert should_use_react("general_qa", "What is Splunk?") is False

    def test_false_for_short_general_query(self):
        assert should_use_react("meta_question", "help") is False


# ---------------------------------------------------------------------------
# plan_actions()
# ---------------------------------------------------------------------------

class TestPlanActions:
    # --- spl_generation with raw SPL plans analyze_spl + validate_spl ---
    def test_spl_generation_with_raw_spl_plans_analyze_and_validate(self):
        tools = [_make_tool("analyze_spl"), _make_tool("validate_spl"), _make_tool("optimize_spl")]
        plan = plan_actions("index=main | stats count by host", "spl_generation", tools)
        tool_names = [name for name, _ in plan]
        assert "analyze_spl" in tool_names
        assert "validate_spl" in tool_names

    # --- spl_generation with optimize keywords adds optimize_spl ---
    def test_spl_generation_with_optimize_keyword(self):
        tools = [_make_tool("analyze_spl"), _make_tool("validate_spl"), _make_tool("optimize_spl")]
        plan = plan_actions("optimize index=main | stats count by host", "spl_generation", tools)
        tool_names = [name for name, _ in plan]
        assert "optimize_spl" in tool_names

    def test_spl_generation_with_improve_keyword(self):
        tools = [_make_tool("analyze_spl"), _make_tool("validate_spl"), _make_tool("optimize_spl")]
        plan = plan_actions("improve index=main | stats count by host", "spl_generation", tools)
        tool_names = [name for name, _ in plan]
        assert "optimize_spl" in tool_names

    def test_spl_generation_with_faster_keyword(self):
        tools = [_make_tool("analyze_spl"), _make_tool("validate_spl"), _make_tool("optimize_spl")]
        plan = plan_actions("make index=main | stats count faster", "spl_generation", tools)
        tool_names = [name for name, _ in plan]
        assert "optimize_spl" in tool_names

    # --- spl_generation without SPL plans generate_spl ---
    def test_spl_generation_without_spl_plans_generate(self):
        tools = [_make_tool("generate_spl"), _make_tool("analyze_spl")]
        plan = plan_actions("show me failed logins in the last hour", "spl_generation", tools)
        tool_names = [name for name, _ in plan]
        assert "generate_spl" in tool_names
        assert "analyze_spl" not in tool_names

    # --- spl_generation with code-fenced SPL ---
    def test_spl_generation_with_code_fenced_spl(self):
        user_input = "analyze this:\n```spl\nindex=main | stats count by source\n```"
        tools = [_make_tool("analyze_spl"), _make_tool("validate_spl")]
        plan = plan_actions(user_input, "spl_generation", tools)
        tool_names = [name for name, _ in plan]
        assert "analyze_spl" in tool_names
        # Check that extracted SPL is in args
        analyze_args = [args for name, args in plan if name == "analyze_spl"][0]
        assert "index=main | stats count by source" in analyze_args["query"]

    # --- spl_generation with inline SPL ---
    def test_spl_generation_with_inline_spl(self):
        tools = [_make_tool("analyze_spl"), _make_tool("validate_spl")]
        plan = plan_actions("index=main | stats count", "spl_generation", tools)
        tool_names = [name for name, _ in plan]
        assert "analyze_spl" in tool_names

    # --- spl_optimization with raw SPL plans optimize_spl + validate_spl ---
    def test_spl_optimization_with_raw_spl(self):
        tools = [_make_tool("optimize_spl"), _make_tool("validate_spl")]
        plan = plan_actions("index=main | stats count by host", "spl_optimization", tools)
        tool_names = [name for name, _ in plan]
        assert "optimize_spl" in tool_names
        assert "validate_spl" in tool_names

    def test_spl_optimization_without_spl_returns_empty(self):
        tools = [_make_tool("optimize_spl"), _make_tool("validate_spl"), _make_tool("search_knowledge_base")]
        plan = plan_actions("how to optimize my searches", "spl_optimization", tools)
        # No raw SPL -> no optimize/validate planned -> fallback to search_knowledge_base
        tool_names = [name for name, _ in plan]
        assert "optimize_spl" not in tool_names
        assert "search_knowledge_base" in tool_names

    # --- saved_search_analysis plans list_saved_searches ---
    def test_saved_search_analysis(self):
        tools = [_make_tool("list_saved_searches")]
        plan = plan_actions("show me saved searches", "saved_search_analysis", tools)
        assert plan == [("list_saved_searches", {})]

    # --- config_health_check plans analyze_configs ---
    def test_config_health_check(self):
        tools = [_make_tool("analyze_configs")]
        plan = plan_actions("check config health", "config_health_check", tools)
        assert plan == [("analyze_configs", {})]

    # --- config_lookup with .conf reference ---
    def test_config_lookup_with_conf_ref(self):
        tools = [_make_tool("lookup_config")]
        plan = plan_actions("what is in inputs.conf", "config_lookup", tools)
        assert len(plan) == 1
        assert plan[0][0] == "lookup_config"
        assert plan[0][1]["conf_file"] == "inputs.conf"

    # --- config_lookup with multiple .conf refs plans multiple lookups (max 2) ---
    def test_config_lookup_with_multiple_conf_refs(self):
        tools = [_make_tool("lookup_config")]
        plan = plan_actions(
            "compare inputs.conf, outputs.conf, and transforms.conf",
            "config_lookup",
            tools,
        )
        assert len(plan) == 2  # max 2
        conf_files = [args["conf_file"] for _, args in plan]
        assert "inputs.conf" in conf_files
        assert "outputs.conf" in conf_files

    # --- cribl_pipeline with 'pipeline' keyword ---
    def test_cribl_pipeline_with_pipeline_keyword(self):
        tools = [_make_tool("analyze_cribl_pipeline"), _make_tool("generate_cribl_route")]
        plan = plan_actions("analyze my cribl pipeline config", "cribl_pipeline", tools)
        tool_names = [name for name, _ in plan]
        assert "analyze_cribl_pipeline" in tool_names

    # --- cribl_pipeline without 'pipeline' or 'config' falls back to generate_cribl_route ---
    def test_cribl_pipeline_falls_back_to_generate_route(self):
        tools = [_make_tool("analyze_cribl_pipeline"), _make_tool("generate_cribl_route")]
        plan = plan_actions("set up routing for syslog", "cribl_pipeline", tools)
        tool_names = [name for name, _ in plan]
        assert "generate_cribl_route" in tool_names

    # --- observability_metrics with metric name ---
    def test_observability_metrics_with_cpu(self):
        tools = [_make_tool("suggest_metrics_query")]
        plan = plan_actions("show me cpu usage", "observability_metrics", tools)
        assert len(plan) == 1
        assert plan[0][0] == "suggest_metrics_query"
        assert plan[0][1]["metric_name"] == "cpu"

    def test_observability_metrics_with_memory(self):
        tools = [_make_tool("suggest_metrics_query")]
        plan = plan_actions("check memory utilization", "observability_metrics", tools)
        assert plan[0][1]["metric_name"] == "memory"

    # --- troubleshooting plans search_knowledge_base ---
    def test_troubleshooting_plans_search_kb(self):
        tools = [_make_tool("search_knowledge_base")]
        plan = plan_actions("my forwarder is not sending data", "troubleshooting", tools)
        assert plan[0][0] == "search_knowledge_base"

    def test_troubleshooting_with_spl_also_validates(self):
        tools = [_make_tool("search_knowledge_base"), _make_tool("validate_spl")]
        plan = plan_actions(
            "why does index=main | stats count return nothing",
            "troubleshooting",
            tools,
        )
        tool_names = [name for name, _ in plan]
        assert "search_knowledge_base" in tool_names
        assert "validate_spl" in tool_names

    # --- run_search with raw SPL ---
    def test_run_search_with_raw_spl(self):
        tools = [_make_tool("run_splunk_search")]
        plan = plan_actions("index=main | stats count by host", "run_search", tools)
        assert plan[0][0] == "run_splunk_search"

    # --- Fallback to search_knowledge_base ---
    def test_fallback_to_search_knowledge_base(self):
        tools = [_make_tool("search_knowledge_base")]
        plan = plan_actions("random question", "unknown_intent", tools)
        assert plan[0][0] == "search_knowledge_base"

    # --- Empty tool list returns empty plan ---
    def test_empty_tools_returns_empty_plan(self):
        plan = plan_actions("index=main | stats count", "spl_generation", [])
        assert plan == []

    # --- Tools not in available_tools are not planned ---
    def test_tools_not_available_are_not_planned(self):
        # Only provide validate_spl but not analyze_spl
        tools = [_make_tool("validate_spl")]
        plan = plan_actions("index=main | stats count", "spl_generation", tools)
        tool_names = [name for name, _ in plan]
        assert "analyze_spl" not in tool_names
        assert "validate_spl" in tool_names


# ---------------------------------------------------------------------------
# execute_react_loop() — async
# ---------------------------------------------------------------------------

class TestExecuteReactLoop:
    @pytest.mark.asyncio
    async def test_returns_reasoning_trace(self):
        registry = ToolRegistry()
        registry.register(Tool(
            name="search_knowledge_base",
            description="search kb",
            category=ToolCategory.KNOWLEDGE,
            execute_fn=lambda query="": ToolResult(success=True, output="found stuff"),
        ))
        trace = await execute_react_loop("test query", "troubleshooting", registry=registry)
        assert isinstance(trace, ReasoningTrace)
        assert trace.query == "test query"
        assert trace.intent == "troubleshooting"

    @pytest.mark.asyncio
    async def test_empty_registry_returns_trace_with_no_final_answer(self):
        registry = ToolRegistry()
        trace = await execute_react_loop("test", "spl_generation", registry=registry)
        assert trace.final_answer is None
        assert trace.steps == []

    @pytest.mark.asyncio
    async def test_successful_tool_execution_populates_trace(self):
        registry = ToolRegistry()
        registry.register(Tool(
            name="search_knowledge_base",
            description="search kb",
            category=ToolCategory.KNOWLEDGE,
            execute_fn=lambda query="": ToolResult(success=True, output="KB result here"),
        ))
        trace = await execute_react_loop("my forwarder is broken", "troubleshooting", registry=registry)
        assert len(trace.steps) >= 1
        assert trace.steps[0].action == "search_knowledge_base"
        assert trace.steps[0].observation is not None
        assert "KB result here" in trace.steps[0].observation
        assert trace.final_answer is not None
        assert "KB result here" in trace.final_answer

    @pytest.mark.asyncio
    async def test_failed_tool_execution_includes_error(self):
        registry = ToolRegistry()
        registry.register(Tool(
            name="search_knowledge_base",
            description="search kb",
            category=ToolCategory.KNOWLEDGE,
            execute_fn=lambda query="": ToolResult(success=False, output="", error="connection refused"),
        ))
        trace = await execute_react_loop("test", "troubleshooting", registry=registry)
        assert len(trace.steps) >= 1
        # The observation should contain the error
        assert "connection refused" in (trace.steps[0].observation or "")
        # final_answer should include the error text
        assert trace.final_answer is not None
        assert "Error" in trace.final_answer

    @pytest.mark.asyncio
    async def test_respects_max_steps_limit(self):
        registry = ToolRegistry()
        # Register many tools that would all be planned
        registry.register(Tool(
            name="analyze_spl",
            description="analyze",
            category=ToolCategory.ANALYSIS,
            execute_fn=lambda query="", auto_fix=True: ToolResult(success=True, output="analyzed"),
        ))
        registry.register(Tool(
            name="optimize_spl",
            description="optimize",
            category=ToolCategory.GENERATION,
            execute_fn=lambda query="": ToolResult(success=True, output="optimized"),
        ))
        registry.register(Tool(
            name="validate_spl",
            description="validate",
            category=ToolCategory.ANALYSIS,
            execute_fn=lambda query="": ToolResult(success=True, output="valid"),
        ))
        trace = await execute_react_loop(
            "optimize index=main | stats count",
            "spl_generation",
            registry=registry,
            max_steps=1,
        )
        assert len(trace.steps) <= 1

    @pytest.mark.asyncio
    async def test_multiple_tools_in_sequence(self):
        registry = ToolRegistry()
        registry.register(Tool(
            name="analyze_spl",
            description="analyze",
            category=ToolCategory.ANALYSIS,
            execute_fn=lambda query="", auto_fix=True: ToolResult(success=True, output="analysis done"),
        ))
        registry.register(Tool(
            name="validate_spl",
            description="validate",
            category=ToolCategory.ANALYSIS,
            execute_fn=lambda query="": ToolResult(success=True, output="validation done"),
        ))
        trace = await execute_react_loop(
            "index=main | stats count by host",
            "spl_generation",
            registry=registry,
        )
        assert len(trace.steps) >= 2
        actions = [s.action for s in trace.steps]
        assert "analyze_spl" in actions
        assert "validate_spl" in actions

    @pytest.mark.asyncio
    async def test_tools_used_tracks_all_tool_names(self):
        registry = ToolRegistry()
        registry.register(Tool(
            name="analyze_spl",
            description="analyze",
            category=ToolCategory.ANALYSIS,
            execute_fn=lambda query="", auto_fix=True: ToolResult(success=True, output="ok"),
        ))
        registry.register(Tool(
            name="validate_spl",
            description="validate",
            category=ToolCategory.ANALYSIS,
            execute_fn=lambda query="": ToolResult(success=True, output="ok"),
        ))
        trace = await execute_react_loop(
            "index=main | stats count",
            "spl_generation",
            registry=registry,
        )
        assert "analyze_spl" in trace.tools_used
        assert "validate_spl" in trace.tools_used

    @pytest.mark.asyncio
    async def test_total_duration_ms_is_positive(self):
        registry = ToolRegistry()
        registry.register(Tool(
            name="search_knowledge_base",
            description="kb",
            category=ToolCategory.KNOWLEDGE,
            execute_fn=lambda query="": ToolResult(success=True, output="result"),
        ))
        trace = await execute_react_loop("query", "troubleshooting", registry=registry)
        assert trace.total_duration_ms >= 0

    @pytest.mark.asyncio
    async def test_no_planned_actions_returns_none_final_answer(self):
        """When intent does not match any planned tools, final_answer is None."""
        registry = ToolRegistry()
        # Register a tool that won't match the intent/plan
        registry.register(Tool(
            name="some_unrelated_tool",
            description="unrelated",
            category=ToolCategory.KNOWLEDGE,
            execute_fn=lambda: ToolResult(success=True, output="hi"),
        ))
        trace = await execute_react_loop(
            "something with no matching plan",
            "unknown_intent",
            registry=registry,
        )
        # "some_unrelated_tool" is not "search_knowledge_base", so no fallback
        assert trace.final_answer is None

    @pytest.mark.asyncio
    async def test_async_execute_fn(self):
        """Tools with async execute_fn work correctly."""
        async def async_fn(query=""):
            return ToolResult(success=True, output="async result")

        registry = ToolRegistry()
        registry.register(Tool(
            name="search_knowledge_base",
            description="kb",
            category=ToolCategory.KNOWLEDGE,
            execute_fn=async_fn,
        ))
        trace = await execute_react_loop("test", "troubleshooting", registry=registry)
        assert trace.final_answer is not None
        assert "async result" in trace.final_answer

    @pytest.mark.asyncio
    async def test_tool_raising_exception_produces_error_step(self):
        """A tool that raises an exception produces an error in the trace."""
        def bad_fn(query=""):
            raise RuntimeError("boom")

        registry = ToolRegistry()
        registry.register(Tool(
            name="search_knowledge_base",
            description="kb",
            category=ToolCategory.KNOWLEDGE,
            execute_fn=bad_fn,
        ))
        trace = await execute_react_loop("test", "troubleshooting", registry=registry)
        assert len(trace.steps) >= 1
        # The observation should reflect the error
        obs = trace.steps[0].observation or ""
        assert "boom" in obs or "failed" in obs.lower()

    @pytest.mark.asyncio
    async def test_step_duration_is_populated(self):
        registry = ToolRegistry()
        registry.register(Tool(
            name="search_knowledge_base",
            description="kb",
            category=ToolCategory.KNOWLEDGE,
            execute_fn=lambda query="": ToolResult(success=True, output="ok"),
        ))
        trace = await execute_react_loop("test", "troubleshooting", registry=registry)
        for step in trace.steps:
            assert step.duration_ms >= 0


# ---------------------------------------------------------------------------
# format_tool_context_for_llm()
# ---------------------------------------------------------------------------

class TestFormatToolContextForLLM:
    def test_returns_none_for_empty_trace(self):
        trace = ReasoningTrace(query="q", intent="i")
        assert format_tool_context_for_llm(trace) is None

    def test_returns_none_when_final_answer_is_none(self):
        trace = ReasoningTrace(query="q", intent="i")
        trace.steps.append(ReasoningStep(step_num=1, thought="t", action="a", observation="obs"))
        trace.final_answer = None
        assert format_tool_context_for_llm(trace) is None

    def test_includes_agentic_tool_results_header(self):
        trace = ReasoningTrace(query="q", intent="i")
        trace.steps.append(ReasoningStep(
            step_num=1, thought="t", action="analyze_spl", observation="Found issues",
        ))
        trace.final_answer = "some answer"
        result = format_tool_context_for_llm(trace)
        assert result is not None
        assert "### Agentic Tool Results" in result

    def test_includes_tool_name_and_observation(self):
        trace = ReasoningTrace(query="q", intent="i")
        trace.steps.append(ReasoningStep(
            step_num=1, thought="thinking", action="validate_spl", observation="Query is valid",
        ))
        trace.final_answer = "answer"
        result = format_tool_context_for_llm(trace)
        assert "**Tool: validate_spl**" in result
        assert "Query is valid" in result

    def test_multiple_steps_format_correctly(self):
        trace = ReasoningTrace(query="q", intent="i")
        trace.steps.append(ReasoningStep(
            step_num=1, thought="t1", action="analyze_spl", observation="Analysis output",
        ))
        trace.steps.append(ReasoningStep(
            step_num=2, thought="t2", action="optimize_spl", observation="Optimization output",
        ))
        trace.final_answer = "combined answer"
        result = format_tool_context_for_llm(trace)
        assert "**Tool: analyze_spl**" in result
        assert "Analysis output" in result
        assert "**Tool: optimize_spl**" in result
        assert "Optimization output" in result


# ---------------------------------------------------------------------------
# MAX_REASONING_STEPS constant
# ---------------------------------------------------------------------------

class TestConstants:
    def test_max_reasoning_steps(self):
        assert MAX_REASONING_STEPS == 5
