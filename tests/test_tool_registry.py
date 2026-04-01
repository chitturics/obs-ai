"""
Comprehensive tests for chat_app/tool_registry.py -- ToolCategory enum,
ToolParameter/ToolResult/Tool dataclasses, ToolRegistry class (register,
capabilities, lookup, execute), the singleton factory, built-in tool
registration, and individual tool implementation functions.

Covers:
1. ToolCategory enum                  (3 tests)
2. ToolParameter dataclass            (3 tests)
3. ToolResult dataclass               (5 tests)
4. Tool dataclass                     (4 tests)
5. ToolRegistry core                  (20 tests)
6. ToolRegistry.execute()             (15 tests)
7. Built-in tool registration         (8 tests)
8. Tool implementation functions      (15 tests)
"""

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "chat_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

from chat_app.tool_registry import (
    Tool,
    ToolCategory,
    ToolParameter,
    ToolRegistry,
    ToolResult,
    _register_builtin_tools,
    _tool_analyze_cribl_pipeline,
    _tool_analyze_spl,
    _tool_generate_cribl_route,
    _tool_optimize_spl,
    _tool_suggest_metrics_query,
    _tool_validate_spl,
    get_tool_registry,
)


# ===========================================================================
# 1. ToolCategory enum
# ===========================================================================

class TestToolCategory:
    """Tests for the ToolCategory enum."""

    def test_all_seven_values_exist(self):
        expected = {"splunk", "cribl", "observability", "knowledge",
                    "analysis", "generation", "admin"}
        actual = {tc.value for tc in ToolCategory}
        assert actual == expected

    def test_is_string_enum(self):
        """ToolCategory inherits from str, so members are also strings."""
        for tc in ToolCategory:
            assert isinstance(tc, str)

    def test_member_access_by_name(self):
        assert ToolCategory.SPLUNK == "splunk"
        assert ToolCategory.CRIBL == "cribl"
        assert ToolCategory.OBSERVABILITY == "observability"
        assert ToolCategory.KNOWLEDGE == "knowledge"
        assert ToolCategory.ANALYSIS == "analysis"
        assert ToolCategory.GENERATION == "generation"
        assert ToolCategory.ADMIN == "admin"


# ===========================================================================
# 2. ToolParameter dataclass
# ===========================================================================

class TestToolParameter:
    """Tests for the ToolParameter dataclass."""

    def test_defaults(self):
        p = ToolParameter(name="foo", description="bar")
        assert p.param_type == "string"
        assert p.required is False
        assert p.default is None

    def test_required_parameter(self):
        p = ToolParameter(name="query", description="SPL", required=True)
        assert p.required is True

    def test_custom_param_type(self):
        p = ToolParameter(name="count", description="N", param_type="int", default=10)
        assert p.param_type == "int"
        assert p.default == 10


# ===========================================================================
# 3. ToolResult dataclass
# ===========================================================================

class TestToolResult:
    """Tests for the ToolResult dataclass."""

    def test_success_result(self):
        r = ToolResult(success=True, output="done")
        assert r.success is True
        assert r.output == "done"
        assert r.error is None
        assert r.data is None
        assert r.suggestions == []

    def test_failure_result(self):
        r = ToolResult(success=False, output="", error="boom")
        assert r.success is False
        assert r.error == "boom"

    def test_format_for_context_success(self):
        r = ToolResult(success=True, output="results here")
        assert r.format_for_context() == "results here"

    def test_format_for_context_error(self):
        r = ToolResult(success=False, output="", error="something broke")
        assert r.format_for_context() == "[Tool Error] something broke"

    def test_format_for_context_error_none(self):
        """When error is None on a failure result, show 'Unknown error'."""
        r = ToolResult(success=False, output="")
        assert r.format_for_context() == "[Tool Error] Unknown error"

    def test_suggestions_field(self):
        r = ToolResult(success=True, output="ok", suggestions=["try this"])
        assert r.suggestions == ["try this"]


# ===========================================================================
# 4. Tool dataclass
# ===========================================================================

class TestTool:
    """Tests for the Tool dataclass."""

    def test_param_names_property(self):
        t = Tool(
            name="t1", description="d", category=ToolCategory.ANALYSIS,
            parameters=[
                ToolParameter("a", "desc_a"),
                ToolParameter("b", "desc_b"),
            ],
        )
        assert t.param_names == ["a", "b"]

    def test_param_names_empty(self):
        t = Tool(name="t2", description="d", category=ToolCategory.ADMIN)
        assert t.param_names == []

    def test_defaults(self):
        t = Tool(name="t3", description="d", category=ToolCategory.SPLUNK)
        assert t.requires == set()
        assert t.intents == []
        assert t.execute_fn is None
        assert t.max_retries == 1
        assert t.timeout_seconds == 30

    def test_requires_set(self):
        t = Tool(name="t4", description="d", category=ToolCategory.SPLUNK,
                 requires={"splunk_connected", "mcp_available"})
        assert "splunk_connected" in t.requires
        assert "mcp_available" in t.requires


# ===========================================================================
# 5. ToolRegistry core
# ===========================================================================

class TestToolRegistryCore:
    """Tests for ToolRegistry register / get / capabilities."""

    def _fresh(self) -> ToolRegistry:
        return ToolRegistry()

    def _make_tool(self, name="test_tool", intents=None, requires=None,
                   params=None, execute_fn=None, category=ToolCategory.ANALYSIS):
        return Tool(
            name=name,
            description=f"Description for {name}",
            category=category,
            parameters=params or [],
            requires=requires or set(),
            intents=intents or [],
            execute_fn=execute_fn,
        )

    # --- register() ---

    def test_register_adds_tool(self):
        reg = self._fresh()
        t = self._make_tool("my_tool")
        reg.register(t)
        assert reg.get_tool("my_tool") is t

    def test_register_updates_intent_map(self):
        reg = self._fresh()
        t = self._make_tool("my_tool", intents=["intent_a", "intent_b"])
        reg.register(t)
        assert "my_tool" in reg._intent_map.get("intent_a", [])
        assert "my_tool" in reg._intent_map.get("intent_b", [])

    def test_register_multiple_tools_same_intent(self):
        reg = self._fresh()
        reg.register(self._make_tool("t1", intents=["shared_intent"]))
        reg.register(self._make_tool("t2", intents=["shared_intent"]))
        names = reg._intent_map["shared_intent"]
        assert "t1" in names and "t2" in names

    # --- get_tool() ---

    def test_get_tool_returns_none_for_unknown(self):
        reg = self._fresh()
        assert reg.get_tool("nonexistent") is None

    def test_get_tool_by_name(self):
        reg = self._fresh()
        t = self._make_tool("existing")
        reg.register(t)
        assert reg.get_tool("existing") is t

    # --- get_tools_for_intent() ---

    def test_get_tools_for_intent_returns_matching(self):
        reg = self._fresh()
        reg.register(self._make_tool("a", intents=["x"]))
        reg.register(self._make_tool("b", intents=["y"]))
        tools = reg.get_tools_for_intent("x")
        assert len(tools) == 1
        assert tools[0].name == "a"

    def test_get_tools_for_intent_filters_by_capabilities(self):
        reg = self._fresh()
        reg.register(self._make_tool("restricted", intents=["x"],
                                     requires={"splunk_connected"}))
        # Without capability -> empty
        assert reg.get_tools_for_intent("x") == []
        # With capability -> available
        reg.add_capability("splunk_connected")
        tools = reg.get_tools_for_intent("x")
        assert len(tools) == 1

    def test_get_tools_for_intent_unknown_intent(self):
        reg = self._fresh()
        assert reg.get_tools_for_intent("no_such_intent") == []

    # --- get_available_tools() ---

    def test_get_available_tools_returns_all_when_no_requires(self):
        reg = self._fresh()
        reg.register(self._make_tool("a"))
        reg.register(self._make_tool("b"))
        available = reg.get_available_tools()
        assert len(available) == 2

    def test_get_available_tools_filters_when_capabilities_missing(self):
        reg = self._fresh()
        reg.register(self._make_tool("free"))
        reg.register(self._make_tool("locked", requires={"need_this"}))
        available = reg.get_available_tools()
        assert len(available) == 1
        assert available[0].name == "free"

    def test_get_available_tools_includes_when_capability_present(self):
        reg = self._fresh()
        reg.register(self._make_tool("locked", requires={"key"}))
        reg.add_capability("key")
        assert len(reg.get_available_tools()) == 1

    # --- capabilities management ---

    def test_set_capabilities_replaces(self):
        reg = self._fresh()
        reg.add_capability("a")
        reg.set_capabilities({"b", "c"})
        assert reg._capabilities == {"b", "c"}

    def test_add_capability(self):
        reg = self._fresh()
        reg.add_capability("alpha")
        assert "alpha" in reg._capabilities

    def test_remove_capability(self):
        reg = self._fresh()
        reg.add_capability("alpha")
        reg.remove_capability("alpha")
        assert "alpha" not in reg._capabilities

    def test_remove_capability_missing_is_noop(self):
        """discard on a missing capability should not raise."""
        reg = self._fresh()
        reg.remove_capability("not_here")  # no error

    # --- list_tools_summary() ---

    def test_list_tools_summary_includes_names_and_descriptions(self):
        reg = self._fresh()
        reg.register(self._make_tool("cool_tool"))
        summary = reg.list_tools_summary()
        assert "cool_tool" in summary
        assert "Description for cool_tool" in summary

    def test_list_tools_summary_shows_params(self):
        reg = self._fresh()
        params = [ToolParameter("query", "The query", required=True)]
        reg.register(self._make_tool("ptool", params=params))
        summary = reg.list_tools_summary()
        assert "query: string (required)" in summary

    def test_list_tools_summary_returns_no_tools_when_all_blocked(self):
        reg = self._fresh()
        reg.register(self._make_tool("locked", requires={"missing_cap"}))
        summary = reg.list_tools_summary()
        assert summary == "No tools currently available."

    def test_list_tools_summary_empty_registry(self):
        reg = self._fresh()
        summary = reg.list_tools_summary()
        assert summary == "No tools currently available."


# ===========================================================================
# 6. ToolRegistry.execute()
# ===========================================================================

class TestToolRegistryExecute:
    """Tests for ToolRegistry.execute() async method."""

    def _fresh(self) -> ToolRegistry:
        return ToolRegistry()

    def _make_tool(self, name="t", execute_fn=None, requires=None,
                   max_retries=1, timeout_seconds=30):
        return Tool(
            name=name,
            description="d",
            category=ToolCategory.ANALYSIS,
            requires=requires or set(),
            execute_fn=execute_fn,
            max_retries=max_retries,
            timeout_seconds=timeout_seconds,
        )

    # --- error paths ---

    @pytest.mark.asyncio
    async def test_execute_unknown_tool(self):
        reg = self._fresh()
        result = await reg.execute("ghost")
        assert result.success is False
        assert "Unknown tool" in result.error

    @pytest.mark.asyncio
    async def test_execute_missing_capabilities(self):
        reg = self._fresh()
        reg.register(self._make_tool("locked", requires={"splunk_connected"}))
        result = await reg.execute("locked")
        assert result.success is False
        assert "requires" in result.error
        assert "splunk_connected" in result.error

    @pytest.mark.asyncio
    async def test_execute_no_execute_fn(self):
        reg = self._fresh()
        reg.register(self._make_tool("no_fn", execute_fn=None))
        result = await reg.execute("no_fn")
        assert result.success is False
        assert "no execute function" in result.error

    # --- sync function ---

    @pytest.mark.asyncio
    async def test_execute_sync_returning_string(self):
        def my_fn(**kwargs):
            return f"hello {kwargs.get('name', 'world')}"

        reg = self._fresh()
        reg.register(self._make_tool("sync_str", execute_fn=my_fn))
        result = await reg.execute("sync_str", name="pytest")
        assert result.success is True
        assert "hello pytest" in result.output

    @pytest.mark.asyncio
    async def test_execute_sync_returning_tool_result(self):
        def my_fn(**kwargs):
            return ToolResult(success=True, output="direct result")

        reg = self._fresh()
        reg.register(self._make_tool("sync_tr", execute_fn=my_fn))
        result = await reg.execute("sync_tr")
        assert result.success is True
        assert result.output == "direct result"

    # --- async function ---

    @pytest.mark.asyncio
    async def test_execute_async_returning_string(self):
        async def my_fn(**kwargs):
            return "async hello"

        reg = self._fresh()
        reg.register(self._make_tool("async_str", execute_fn=my_fn))
        result = await reg.execute("async_str")
        assert result.success is True
        assert "async hello" in result.output

    @pytest.mark.asyncio
    async def test_execute_async_returning_tool_result(self):
        async def my_fn(**kwargs):
            return ToolResult(success=True, output="async direct")

        reg = self._fresh()
        reg.register(self._make_tool("async_tr", execute_fn=my_fn))
        result = await reg.execute("async_tr")
        assert result.success is True
        assert result.output == "async direct"

    # --- exception handling ---

    @pytest.mark.asyncio
    async def test_execute_exception_returns_error(self):
        def boom(**kwargs):
            raise ValueError("kaboom")

        reg = self._fresh()
        reg.register(self._make_tool("boom", execute_fn=boom))
        result = await reg.execute("boom")
        assert result.success is False
        assert "kaboom" in result.error

    @pytest.mark.asyncio
    async def test_execute_async_exception_returns_error(self):
        async def boom(**kwargs):
            raise RuntimeError("async kaboom")

        reg = self._fresh()
        reg.register(self._make_tool("aboom", execute_fn=boom))
        result = await reg.execute("aboom")
        assert result.success is False
        assert "async kaboom" in result.error

    # --- timeout ---

    @pytest.mark.asyncio
    async def test_execute_timeout(self):
        async def slow(**kwargs):
            await asyncio.sleep(10)

        reg = self._fresh()
        reg.register(self._make_tool("slow", execute_fn=slow, timeout_seconds=1))
        result = await reg.execute("slow")
        assert result.success is False
        assert "timed out" in result.error

    # --- retries ---

    @pytest.mark.asyncio
    async def test_execute_retries_on_failure(self):
        call_count = 0

        def flaky(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise ValueError("transient error")
            return "ok now"

        reg = self._fresh()
        reg.register(self._make_tool("flaky", execute_fn=flaky, max_retries=2))
        result = await reg.execute("flaky")
        assert result.success is True
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_execute_exhausts_retries(self):
        def always_fail(**kwargs):
            raise ValueError("persistent error")

        reg = self._fresh()
        reg.register(self._make_tool("fail", execute_fn=always_fail, max_retries=3))
        result = await reg.execute("fail")
        assert result.success is False
        assert "persistent error" in result.error

    @pytest.mark.asyncio
    async def test_execute_retries_timeout(self):
        """Timeout retries should also be retried up to max_retries."""
        call_count = 0

        async def sometimes_slow(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                await asyncio.sleep(10)
            return "fast now"

        reg = self._fresh()
        reg.register(self._make_tool("tslow", execute_fn=sometimes_slow,
                                     max_retries=2, timeout_seconds=1))
        result = await reg.execute("tslow")
        assert result.success is True
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_execute_with_capabilities_satisfied(self):
        def ok(**kwargs):
            return "all good"

        reg = self._fresh()
        reg.register(self._make_tool("gated", execute_fn=ok, requires={"cap_a"}))
        reg.add_capability("cap_a")
        result = await reg.execute("gated")
        assert result.success is True


# ===========================================================================
# 7. Built-in tool registration
# ===========================================================================

class TestBuiltinToolRegistration:
    """Tests that _register_builtin_tools() correctly populates the singleton."""

    def _registry(self) -> ToolRegistry:
        return get_tool_registry()

    def test_all_13_tools_registered(self):
        reg = self._registry()
        expected_names = {
            "analyze_spl", "optimize_spl", "validate_spl", "generate_spl",
            "run_splunk_search", "list_saved_searches", "check_splunk_health",
            "analyze_configs", "lookup_config",
            "analyze_cribl_pipeline", "generate_cribl_route",
            "suggest_metrics_query", "search_knowledge_base",
        }
        actual_names = set(reg._tools.keys())
        assert expected_names.issubset(actual_names), (
            f"Missing: {expected_names - actual_names}"
        )

    def test_analyze_spl_correct_category(self):
        t = self._registry().get_tool("analyze_spl")
        assert t is not None
        assert t.category == ToolCategory.ANALYSIS

    def test_validate_spl_has_query_param(self):
        t = self._registry().get_tool("validate_spl")
        assert t is not None
        assert "query" in t.param_names

    def test_run_splunk_search_requires_splunk_connected(self):
        t = self._registry().get_tool("run_splunk_search")
        assert t is not None
        assert "splunk_connected" in t.requires

    def test_generate_spl_has_required_description_param(self):
        t = self._registry().get_tool("generate_spl")
        assert t is not None
        desc_param = [p for p in t.parameters if p.name == "description"]
        assert len(desc_param) == 1
        assert desc_param[0].required is True

    def test_suggest_metrics_query_intents(self):
        t = self._registry().get_tool("suggest_metrics_query")
        assert t is not None
        assert "observability_metrics" in t.intents

    def test_all_tools_have_execute_fn(self):
        reg = self._registry()
        for name, tool in reg._tools.items():
            assert tool.execute_fn is not None, f"Tool '{name}' has no execute_fn"

    def test_search_knowledge_base_category(self):
        t = self._registry().get_tool("search_knowledge_base")
        assert t is not None
        assert t.category == ToolCategory.KNOWLEDGE


# ===========================================================================
# 8. Tool implementation tests
# ===========================================================================

class TestToolAnalyzeSPL:
    """Tests for _tool_analyze_spl."""

    def test_valid_spl_returns_success(self):
        result = _tool_analyze_spl(query="index=main | stats count by host")
        assert isinstance(result, ToolResult)
        assert result.success is True

    def test_invalid_spl_unbalanced_parens(self):
        result = _tool_analyze_spl(query="index=main | where (a==b")
        assert result.success is True  # analysis itself succeeds
        output_lower = result.output.lower()
        # Should report issues about unbalanced parens
        assert "unbalanced" in output_lower or "issue" in output_lower or "paren" in output_lower

    def test_result_contains_data(self):
        result = _tool_analyze_spl(query="index=main | stats count by host")
        assert result.data is not None
        assert "issues_count" in result.data


class TestToolOptimizeSPL:
    """Tests for _tool_optimize_spl."""

    def test_simple_query_returns_success(self):
        result = _tool_optimize_spl(query="index=main | stats count by host")
        assert isinstance(result, ToolResult)
        assert result.success is True

    def test_already_optimized_query(self):
        """A tstats query should come back as already optimized."""
        result = _tool_optimize_spl(query="| tstats count WHERE index=main by sourcetype")
        assert result.success is True


class TestToolValidateSPL:
    """Tests for _tool_validate_spl."""

    def test_valid_query(self):
        result = _tool_validate_spl(query="index=main | stats count by host")
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert "Validation Status" in result.output

    def test_query_with_known_errors(self):
        """A query with unbalanced quotes should report errors or warnings."""
        result = _tool_validate_spl(query='index=main sourcetype="syslog')
        assert result.success is True
        output_lower = result.output.lower()
        # Should contain errors or warning about the malformed query
        assert "error" in output_lower or "warning" in output_lower or "unbalanced" in output_lower


class TestToolGenerateCriblRoute:
    """Tests for _tool_generate_cribl_route."""

    def test_returns_valid_config(self):
        result = _tool_generate_cribl_route(description="Route syslog to S3")
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert "Route" in result.output or "route" in result.output

    def test_with_source_type_filter(self):
        result = _tool_generate_cribl_route(
            description="Route syslog",
            source_type="syslog",
            destination="s3_bucket",
        )
        assert result.success is True
        assert "syslog" in result.output
        assert "s3_bucket" in result.output

    def test_without_source_type_uses_true_filter(self):
        result = _tool_generate_cribl_route(description="Route everything")
        assert result.success is True
        assert "true" in result.output


class TestToolSuggestMetricsQuery:
    """Tests for _tool_suggest_metrics_query."""

    def test_returns_mstats_queries(self):
        result = _tool_suggest_metrics_query(metric_name="cpu.idle")
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert "mstats" in result.output
        assert "cpu.idle" in result.output

    def test_includes_mcatalog(self):
        result = _tool_suggest_metrics_query(metric_name="mem.used")
        assert "mcatalog" in result.output

    def test_custom_time_range(self):
        result = _tool_suggest_metrics_query(metric_name="disk.io",
                                             time_range="-4h")
        assert result.success is True
        assert "-4h" in result.output

    def test_default_time_range(self):
        result = _tool_suggest_metrics_query(metric_name="net.bytes")
        assert "-1h" in result.output


class TestToolAnalyzeCriblPipeline:
    """Tests for _tool_analyze_cribl_pipeline."""

    def test_valid_yaml_config(self):
        config = """
functions:
  - id: func1
    filter: "true"
    conf:
      type: mask
        """
        result = _tool_analyze_cribl_pipeline(pipeline_config=config)
        assert isinstance(result, ToolResult)
        assert result.success is True

    def test_valid_json_config(self):
        config = json.dumps({
            "functions": [
                {"id": "func1", "filter": "true", "conf": {"type": "eval"}}
            ]
        })
        result = _tool_analyze_cribl_pipeline(pipeline_config=config)
        assert result.success is True

    def test_invalid_config_returns_error(self):
        result = _tool_analyze_cribl_pipeline(pipeline_config="{{not valid yaml or json!!")
        assert result.success is False
        assert "parse" in result.error.lower()

    def test_empty_functions_no_issues(self):
        config = json.dumps({"functions": []})
        result = _tool_analyze_cribl_pipeline(pipeline_config=config)
        assert result.success is True
        assert "looks good" in result.output.lower() or "no issues" in result.output.lower()

    def test_function_without_filter_gets_suggestion(self):
        config = json.dumps({
            "functions": [
                {"id": "my_func", "conf": {"type": "eval", "add": [{"name": "x", "value": "1"}]}}
            ]
        })
        result = _tool_analyze_cribl_pipeline(pipeline_config=config)
        assert result.success is True
        assert "filter" in result.output.lower()


class TestSingleton:
    """Test that get_tool_registry returns the module-level singleton."""

    def test_returns_same_instance(self):
        a = get_tool_registry()
        b = get_tool_registry()
        assert a is b
