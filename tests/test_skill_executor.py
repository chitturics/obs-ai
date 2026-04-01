"""
Comprehensive tests for chat_app/skill_executor.py

Covers:
1.  SkillExecResult dataclass -- format_for_context() for success/failure
2.  Internal handler registration -- register_internal_handler(), get_internal_handler()
3.  Built-in internal handlers -- each of the 9 handlers
4.  SkillExecutor.resolve_handler() -- resolution order
5.  SkillExecutor.execute() -- by skill_name, by handler_key, approval gates, capability checks, error handling
6.  SkillExecutor._dispatch() -- tool_registry route, skills_manager route, internal route, react_loop route
7.  SkillExecutor.get_available_skills() -- returns only skills with resolved handlers
8.  SkillExecutor.get_skills_for_intent() -- filters by intent
9.  SkillExecutor.get_metrics() -- execution count, error rate, latency
10. SkillExecutor.get_execution_log() -- recent log entries
11. Singleton get_skill_executor()

Target: 50+ tests
"""

import asyncio
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "chat_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

from chat_app.skill_catalog import (
    ApprovalGate,
    Skill,
    SkillCatalog,
    SkillFamily,
)
from chat_app.tool_registry import (
    Tool,
    ToolCategory,
    ToolParameter,
    ToolRegistry,
    ToolResult,
)
from chat_app.skill_executor import (
    SkillExecResult,
    SkillExecutor,
    _register_builtin_internal_handlers,
    get_internal_handler,
    get_skill_executor,
    register_internal_handler,
    _INTERNAL_HANDLERS,
)
from chat_app.handlers.cognitive_handlers import (
    _handler_context_builder,
    _handler_confidence_scorer,
    _handler_context_compressor,
    _handler_episodic_memory,
    _handler_failure_analyzer,
    _handler_intent_classifier,
    _handler_knowledge_gap,
    _handler_self_evaluator,
    _handler_spl_template_engine,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run a coroutine synchronously."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _make_tool(name: str, has_execute_fn: bool = True) -> Tool:
    """Create a minimal Tool for testing."""
    return Tool(
        name=name,
        description=f"Test tool {name}",
        category=ToolCategory.ANALYSIS,
        execute_fn=(lambda **kw: ToolResult(success=True, output=f"Ran {name}")) if has_execute_fn else None,
    )


def _make_skill(
    name: str = "test_skill",
    action: str = "test",
    handler_key: str = "test_handler",
    approval: ApprovalGate = ApprovalGate.AUTO,
    requires: Set[str] = None,
    intents: List[str] = None,
    enabled: bool = True,
) -> Skill:
    """Create a minimal Skill for testing."""
    return Skill(
        action=action,
        name=name,
        description=f"Test skill {name}",
        family=SkillFamily.COGNITIVE,
        handler_key=handler_key,
        approval=approval,
        requires=requires or set(),
        intents=intents or [],
        enabled=enabled,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean_internal_handlers():
    """Save and restore internal handlers between tests."""
    saved = dict(_INTERNAL_HANDLERS)
    yield
    _INTERNAL_HANDLERS.clear()
    _INTERNAL_HANDLERS.update(saved)


@pytest.fixture
def mock_tool_registry():
    """A fresh ToolRegistry with no built-in tools."""
    return ToolRegistry()


@pytest.fixture
def mock_skills_manager():
    """A mock SkillsManager with an action registry."""
    sm = MagicMock()
    sm._action_registry = {}
    sm.execute_action = AsyncMock()
    return sm


@pytest.fixture
def mock_skill_catalog():
    """A SkillCatalog backed by a controlled set of skills."""
    cat = MagicMock(spec=SkillCatalog)
    cat.get.return_value = None
    cat.get_enabled.return_value = []
    cat.get_for_intent.return_value = []
    cat.count = 0
    return cat


@pytest.fixture
def executor(mock_tool_registry, mock_skills_manager, mock_skill_catalog):
    """A SkillExecutor with fully mocked backends."""
    return SkillExecutor(
        tool_registry=mock_tool_registry,
        skills_manager=mock_skills_manager,
        skill_catalog=mock_skill_catalog,
    )


# ===========================================================================
# 1. SkillExecResult dataclass
# ===========================================================================

class TestSkillExecResult:
    def test_format_for_context_success(self):
        r = SkillExecResult(success=True, output="Here is the answer")
        assert r.format_for_context() == "Here is the answer"

    def test_format_for_context_failure_with_error(self):
        r = SkillExecResult(
            success=False, output="", skill_name="analyze_spl", error="bad query"
        )
        assert "Skill Error" in r.format_for_context()
        assert "analyze_spl" in r.format_for_context()
        assert "bad query" in r.format_for_context()

    def test_format_for_context_failure_unknown_error(self):
        r = SkillExecResult(success=False, output="", skill_name="x")
        formatted = r.format_for_context()
        assert "Unknown error" in formatted

    def test_defaults(self):
        r = SkillExecResult(success=True, output="ok")
        assert r.skill_name == ""
        assert r.handler_key == ""
        assert r.data is None
        assert r.error is None
        assert r.duration_ms == 0.0
        assert r.approval_required is False
        assert r.approval_message == ""
        assert r.source == ""

    def test_all_fields(self):
        r = SkillExecResult(
            success=True, output="done", skill_name="s", handler_key="h",
            data={"x": 1}, error=None, duration_ms=42.5,
            approval_required=False, approval_message="",
            source="internal",
        )
        assert r.duration_ms == 42.5
        assert r.data == {"x": 1}
        assert r.source == "internal"


# ===========================================================================
# 2. Internal handler registration
# ===========================================================================

class TestInternalHandlerRegistration:
    def test_register_and_get(self):
        fn = lambda **kw: "hello"
        register_internal_handler("my_test_handler", fn)
        assert get_internal_handler("my_test_handler") is fn

    def test_get_missing_returns_none(self):
        assert get_internal_handler("nonexistent_handler_xyz") is None

    def test_overwrite_handler(self):
        fn1 = lambda **kw: "v1"
        fn2 = lambda **kw: "v2"
        register_internal_handler("overwrite_test", fn1)
        register_internal_handler("overwrite_test", fn2)
        assert get_internal_handler("overwrite_test") is fn2

    def test_register_builtin_internal_handlers(self):
        _INTERNAL_HANDLERS.clear()
        _register_builtin_internal_handlers()
        expected_keys = [
            "intent_classifier", "context_builder", "self_evaluator",
            "confidence_scorer", "failure_analyzer", "knowledge_gap",
            "context_compressor", "spl_template_engine", "episodic_memory",
        ]
        for key in expected_keys:
            assert get_internal_handler(key) is not None, f"Missing handler: {key}"

    def test_register_builtin_count(self):
        _INTERNAL_HANDLERS.clear()
        _register_builtin_internal_handlers()
        assert len([k for k in _INTERNAL_HANDLERS if k in [
            "intent_classifier", "context_builder", "self_evaluator",
            "confidence_scorer", "failure_analyzer", "knowledge_gap",
            "context_compressor", "spl_template_engine", "episodic_memory",
        ]]) == 9


# ===========================================================================
# 3. Built-in internal handlers
# ===========================================================================

class TestBuiltinHandlers:
    def test_handler_intent_classifier(self):
        """Test _handler_intent_classifier with mocked IntentClassifier."""
        mock_result = MagicMock()
        mock_result.intent = "spl_generation"
        mock_result.confidence = 0.95
        mock_classifier_instance = MagicMock()
        mock_classifier_instance.classify.return_value = mock_result
        mock_module = MagicMock()
        mock_module.IntentClassifier.return_value = mock_classifier_instance
        with patch.dict("sys.modules", {"chat_app.intent_classifier": mock_module}):
            out = _handler_intent_classifier(user_input="show errors")
        assert "spl_generation" in out
        assert "0.95" in out

    @patch("context_builder.detect_config_context")
    def test_handler_context_builder_with_context(self, mock_detect):
        mock_detect.return_value = (["inputs.conf", "outputs.conf"], "tcp")
        out = _handler_context_builder(user_input="tcp input")
        assert "inputs.conf" in out
        assert "tcp" in out

    @patch("context_builder.detect_config_context")
    def test_handler_context_builder_no_context(self, mock_detect):
        mock_detect.return_value = ([], None)
        out = _handler_context_builder(user_input="hello")
        assert "No specific config context" in out

    @patch("chat_app.self_evaluator.evaluate_response_quality")
    def test_handler_self_evaluator(self, mock_eval):
        mock_eval.return_value = {"overall_score": 0.88, "summary": "Good"}
        out = _handler_self_evaluator(response="test response")
        assert "0.88" in out
        assert "Good" in out

    @patch("chat_app.confidence_scorer.score_confidence")
    def test_handler_confidence_scorer(self, mock_score):
        mock_score.return_value = {"overall": 0.72, "summary": "Moderate"}
        out = _handler_confidence_scorer(chunks=[], user_input="test")
        assert "0.72" in out
        assert "Moderate" in out

    @patch("chat_app.confidence_scorer.score_confidence")
    def test_handler_confidence_scorer_defaults(self, mock_score):
        mock_score.return_value = {"overall": 0.5, "summary": "ok"}
        out = _handler_confidence_scorer()
        mock_score.assert_called_once_with([], "")

    @patch("chat_app.failure_analyzer.categorize_failure")
    def test_handler_failure_analyzer(self, mock_cat):
        mock_cat.return_value = {"category": "syntax_error", "recovery_action": "fix query"}
        out = _handler_failure_analyzer(error="bad syntax", error_type="spl")
        assert "syntax_error" in out
        assert "fix query" in out

    @patch("chat_app.knowledge_gap_detector.detect_knowledge_gaps")
    def test_handler_knowledge_gap_with_gaps(self, mock_gaps):
        mock_gaps.return_value = [{"gap": "missing_index"}, {"gap": "unknown_field"}]
        out = _handler_knowledge_gap(user_input="some query")
        assert "missing_index" in out

    @patch("chat_app.knowledge_gap_detector.detect_knowledge_gaps")
    def test_handler_knowledge_gap_no_gaps(self, mock_gaps):
        mock_gaps.return_value = []
        out = _handler_knowledge_gap(user_input="valid query")
        assert "No knowledge gaps" in out

    @patch("chat_app.context_compressor.compress_interaction_history")
    def test_handler_context_compressor(self, mock_compress):
        mock_compress.return_value = [{"text": "compressed"}]
        out = _handler_context_compressor(history=[{"text": "a"}, {"text": "b"}])
        assert "Compressed 2 entries to 1 entries" in out

    @patch("chat_app.context_compressor.compress_interaction_history")
    def test_handler_context_compressor_empty(self, mock_compress):
        mock_compress.return_value = []
        out = _handler_context_compressor()
        assert "Compressed 0 entries to 0 entries" in out

    def test_handler_spl_template_engine_success(self):
        """Test _handler_spl_template_engine with mocked SPLTemplateEngine class."""
        mock_intent = MagicMock()
        mock_intent.intent_type = "search"
        mock_engine = MagicMock()
        mock_engine.detect_intent.return_value = mock_intent
        mock_engine.generate_query.return_value = ("index=main | stats count", mock_intent, "note")
        mock_module = MagicMock()
        mock_module.SPLTemplateEngine = mock_engine
        with patch.dict("sys.modules", {"shared.spl_template_engine": mock_module}):
            out = _handler_spl_template_engine(user_input="count events")
        assert "index=main | stats count" in out
        assert "Generated SPL" in out

    def test_handler_spl_template_engine_no_intent(self):
        mock_engine = MagicMock()
        mock_engine.detect_intent.return_value = None
        mock_module = MagicMock()
        mock_module.SPLTemplateEngine = mock_engine
        with patch.dict("sys.modules", {"shared.spl_template_engine": mock_module}):
            out = _handler_spl_template_engine(user_input="something")
        assert "Could not generate" in out

    def test_handler_spl_template_engine_unknown_intent(self):
        """When intent_type is 'unknown', should return 'Could not generate'."""
        mock_intent = MagicMock()
        mock_intent.intent_type = "unknown"
        mock_engine = MagicMock()
        mock_engine.detect_intent.return_value = mock_intent
        mock_module = MagicMock()
        mock_module.SPLTemplateEngine = mock_engine
        with patch.dict("sys.modules", {"shared.spl_template_engine": mock_module}):
            out = _handler_spl_template_engine(user_input="something")
        assert "Could not generate" in out

    def test_handler_spl_template_engine_no_query(self):
        mock_intent = MagicMock()
        mock_intent.intent_type = "search"
        mock_engine = MagicMock()
        mock_engine.detect_intent.return_value = mock_intent
        mock_engine.generate_query.return_value = (None, mock_intent, "")
        mock_module = MagicMock()
        mock_module.SPLTemplateEngine = mock_engine
        with patch.dict("sys.modules", {"shared.spl_template_engine": mock_module}):
            out = _handler_spl_template_engine(user_input="x")
        assert "Could not generate" in out

    def test_handler_episodic_memory(self):
        out = _handler_episodic_memory(user_input="test", response="resp")
        assert "Episodic memory updated" in out


# ===========================================================================
# 4. SkillExecutor.resolve_handler()
# ===========================================================================

class TestResolveHandler:
    def test_empty_handler_key(self, executor):
        source, handler = executor.resolve_handler("")
        assert source is None
        assert handler is None

    def test_tool_registry_match(self, executor, mock_tool_registry):
        tool = _make_tool("analyze_spl")
        mock_tool_registry.register(tool)
        source, handler = executor.resolve_handler("analyze_spl")
        assert source == "tool_registry"
        assert handler == "analyze_spl"

    def test_tool_registry_no_execute_fn(self, executor, mock_tool_registry):
        tool = _make_tool("no_exec", has_execute_fn=False)
        mock_tool_registry.register(tool)
        # Tool exists but has no execute_fn, so falls through
        source, _ = executor.resolve_handler("no_exec")
        assert source is None or source != "tool_registry"

    def test_skills_manager_match(self, executor, mock_skills_manager):
        mock_skills_manager._action_registry = {"custom_action": MagicMock()}
        source, handler = executor.resolve_handler("custom_action")
        assert source == "skills_manager"
        assert handler == "custom_action"

    def test_internal_handler_match(self, executor):
        register_internal_handler("my_internal", lambda **kw: "ok")
        source, handler = executor.resolve_handler("my_internal")
        assert source == "internal"
        assert handler == "my_internal"

    def test_react_loop_match(self, executor):
        source, handler = executor.resolve_handler("react_loop")
        assert source == "react_loop"
        assert handler == "react_loop"

    def test_deep_analysis_match(self, executor):
        source, handler = executor.resolve_handler("deep_analysis")
        assert source == "react_loop"
        assert handler == "deep_analysis"

    def test_no_match(self, executor):
        source, handler = executor.resolve_handler("totally_unknown_handler")
        assert source is None
        assert handler is None

    def test_resolution_order_tool_registry_first(self, executor, mock_tool_registry):
        """tool_registry wins over skills_manager and internal."""
        tool = _make_tool("conflict_key")
        mock_tool_registry.register(tool)
        register_internal_handler("conflict_key", lambda **kw: "internal")
        executor._skills_manager._action_registry = {"conflict_key": MagicMock()}

        source, _ = executor.resolve_handler("conflict_key")
        assert source == "tool_registry"

    def test_resolution_order_skills_manager_before_internal(self, executor, mock_skills_manager):
        """skills_manager wins over internal when tool_registry has no match."""
        register_internal_handler("sm_priority_key", lambda **kw: "internal")
        mock_skills_manager._action_registry = {"sm_priority_key": MagicMock()}

        source, _ = executor.resolve_handler("sm_priority_key")
        assert source == "skills_manager"

    def test_no_skills_manager(self, mock_tool_registry, mock_skill_catalog):
        """When skills_manager is None, skip that layer."""
        ex = SkillExecutor(
            tool_registry=mock_tool_registry,
            skills_manager=None,
            skill_catalog=mock_skill_catalog,
        )
        register_internal_handler("only_internal", lambda **kw: "yes")
        source, _ = ex.resolve_handler("only_internal")
        assert source == "internal"


# ===========================================================================
# 5. SkillExecutor.execute()
# ===========================================================================

class TestExecute:
    def test_execute_by_handler_key_internal(self, executor):
        register_internal_handler("echo_handler", lambda msg="": msg)
        result = _run(executor.execute(handler_key="echo_handler", params={"msg": "hi"}))
        assert result.success is True
        assert result.output == "hi"
        assert result.source == "internal"

    def test_execute_by_skill_name(self, executor, mock_skill_catalog):
        skill = _make_skill(name="test_s", handler_key="echo2")
        mock_skill_catalog.get.return_value = skill
        register_internal_handler("echo2", lambda **kw: "from skill")
        result = _run(executor.execute(skill_name="test_s"))
        assert result.success is True
        assert result.skill_name == "test_s"

    def test_execute_no_handler_key(self, executor, mock_skill_catalog):
        mock_skill_catalog.get.return_value = None
        result = _run(executor.execute(skill_name="missing"))
        assert result.success is False
        # When catalog lookup fails, skill_name is tried as handler_key fallback
        assert "Handler not found" in result.error or "No handler_key" in result.error

    def test_execute_no_handler_key_and_no_skill_name(self, executor):
        result = _run(executor.execute())
        assert result.success is False
        assert "No handler_key" in result.error

    def test_execute_handler_not_found(self, executor):
        result = _run(executor.execute(handler_key="nonexistent_xyz"))
        assert result.success is False
        assert "Handler not found" in result.error

    def test_execute_handler_not_found_is_recorded(self, executor):
        """Handler-not-found is recorded in metrics as an error."""
        _run(executor.execute(handler_key="nonexistent_xyz"))
        assert executor._execution_count == 1
        assert executor._error_count == 1

    def test_execute_approval_confirm_not_approved(self, executor, mock_skill_catalog):
        skill = _make_skill(name="gated", handler_key="gated_h", approval=ApprovalGate.CONFIRM)
        mock_skill_catalog.get.return_value = skill
        register_internal_handler("gated_h", lambda **kw: "ok")

        result = _run(executor.execute(skill_name="gated", user_approved=False))
        assert result.success is False
        assert result.approval_required is True
        assert "confirmation" in result.approval_message

    def test_execute_approval_review_not_approved(self, executor, mock_skill_catalog):
        skill = _make_skill(name="review_gated", handler_key="rh", approval=ApprovalGate.REVIEW)
        mock_skill_catalog.get.return_value = skill
        register_internal_handler("rh", lambda **kw: "ok")

        result = _run(executor.execute(skill_name="review_gated", user_approved=False))
        assert result.success is False
        assert result.approval_required is True
        assert "admin review" in result.approval_message

    def test_execute_approval_confirm_approved(self, executor, mock_skill_catalog):
        skill = _make_skill(name="gated_ok", handler_key="gh", approval=ApprovalGate.CONFIRM)
        mock_skill_catalog.get.return_value = skill
        register_internal_handler("gh", lambda **kw: "passed")

        result = _run(executor.execute(skill_name="gated_ok", user_approved=True))
        assert result.success is True

    def test_execute_approval_auto_does_not_block(self, executor, mock_skill_catalog):
        skill = _make_skill(name="auto_s", handler_key="auto_h", approval=ApprovalGate.AUTO)
        mock_skill_catalog.get.return_value = skill
        register_internal_handler("auto_h", lambda **kw: "auto_ok")

        result = _run(executor.execute(skill_name="auto_s", user_approved=False))
        assert result.success is True

    def test_execute_approval_inform_does_not_block(self, executor, mock_skill_catalog):
        skill = _make_skill(name="inform_s", handler_key="inform_h", approval=ApprovalGate.INFORM)
        mock_skill_catalog.get.return_value = skill
        register_internal_handler("inform_h", lambda **kw: "informed")

        result = _run(executor.execute(skill_name="inform_s", user_approved=False))
        assert result.success is True

    def test_execute_missing_capabilities(self, executor, mock_skill_catalog):
        skill = _make_skill(
            name="cap_s", handler_key="cap_h",
            requires={"splunk_connected", "mcp_available"},
        )
        mock_skill_catalog.get.return_value = skill
        executor.set_capabilities({"splunk_connected"})
        register_internal_handler("cap_h", lambda **kw: "ok")

        result = _run(executor.execute(skill_name="cap_s"))
        assert result.success is False
        assert "Missing capabilities" in result.error
        assert "mcp_available" in result.error

    def test_execute_missing_capabilities_is_recorded(self, executor, mock_skill_catalog):
        """Missing capabilities is recorded in metrics as an error."""
        skill = _make_skill(name="cap_s2", handler_key="cap_h2", requires={"need_this"})
        mock_skill_catalog.get.return_value = skill
        register_internal_handler("cap_h2", lambda **kw: "ok")

        _run(executor.execute(skill_name="cap_s2"))
        assert executor._execution_count == 1
        assert executor._error_count == 1

    def test_execute_capabilities_satisfied(self, executor, mock_skill_catalog):
        skill = _make_skill(
            name="cap_ok", handler_key="cap_h2",
            requires={"splunk_connected"},
        )
        mock_skill_catalog.get.return_value = skill
        executor.set_capabilities({"splunk_connected", "extra"})
        register_internal_handler("cap_h2", lambda **kw: "cap_passed")

        result = _run(executor.execute(skill_name="cap_ok"))
        assert result.success is True

    def test_execute_exception_in_dispatch(self, executor):
        def boom(**kw):
            raise RuntimeError("kaboom")
        register_internal_handler("boom_handler", boom)

        result = _run(executor.execute(handler_key="boom_handler"))
        assert result.success is False
        assert "kaboom" in result.error

    def test_execute_exception_still_records(self, executor):
        """Even when dispatch raises, the execution is still recorded."""
        def boom(**kw):
            raise RuntimeError("kaboom")
        register_internal_handler("boom2", boom)

        _run(executor.execute(handler_key="boom2"))
        assert executor._execution_count == 1
        assert executor._error_count == 1

    def test_execute_records_duration(self, executor):
        register_internal_handler("slow", lambda **kw: "ok")
        result = _run(executor.execute(handler_key="slow"))
        assert result.duration_ms >= 0

    def test_execute_skill_name_overrides_handler_key(self, executor, mock_skill_catalog):
        """When both skill_name and handler_key are given, skill's handler_key is used
        only if handler_key param is empty."""
        skill = _make_skill(name="s1", handler_key="from_skill")
        mock_skill_catalog.get.return_value = skill
        register_internal_handler("from_skill", lambda **kw: "from_skill")
        register_internal_handler("from_param", lambda **kw: "from_param")

        # handler_key param takes precedence since it's provided
        result = _run(executor.execute(skill_name="s1", handler_key="from_param"))
        assert result.output == "from_param"

    def test_execute_skill_handler_key_used_when_param_empty(self, executor, mock_skill_catalog):
        skill = _make_skill(name="s2", handler_key="skill_hk")
        mock_skill_catalog.get.return_value = skill
        register_internal_handler("skill_hk", lambda **kw: "skill_hk_out")

        result = _run(executor.execute(skill_name="s2"))
        assert result.output == "skill_hk_out"


# ===========================================================================
# 6. SkillExecutor._dispatch()
# ===========================================================================

class TestDispatch:
    def test_dispatch_tool_registry(self, executor, mock_tool_registry):
        async def _async_exec(**kw):
            return ToolResult(success=True, output="tool_ok", data={"k": 1})

        tool = Tool(
            name="dispatch_tool",
            description="test",
            category=ToolCategory.ANALYSIS,
            execute_fn=_async_exec,
        )
        mock_tool_registry.register(tool)

        result = _run(executor._dispatch("tool_registry", "dispatch_tool", {"query": "x"}))
        assert result.success is True
        assert result.output == "tool_ok"

    def test_dispatch_skills_manager(self, executor, mock_skills_manager):
        sm_result = MagicMock()
        sm_result.success = True
        sm_result.output = "sm_output"
        sm_result.data = None
        sm_result.error = None
        mock_skills_manager.execute_action.return_value = sm_result

        result = _run(executor._dispatch("skills_manager", "sm_action", {"p": 1}))
        assert result.success is True
        assert result.output == "sm_output"
        mock_skills_manager.execute_action.assert_awaited_once()

    def test_dispatch_skills_manager_not_available(self, mock_tool_registry, mock_skill_catalog):
        ex = SkillExecutor(
            tool_registry=mock_tool_registry,
            skills_manager=None,
            skill_catalog=mock_skill_catalog,
        )
        result = _run(ex._dispatch("skills_manager", "action", {}))
        assert result.success is False
        assert "SkillsManager not available" in result.error

    def test_dispatch_internal_sync(self, executor):
        register_internal_handler("sync_fn", lambda val="": f"got:{val}")

        result = _run(executor._dispatch("internal", "sync_fn", {"val": "42"}))
        assert result.success is True
        assert result.output == "got:42"

    def test_dispatch_internal_async(self, executor):
        async def async_handler(val=""):
            return f"async:{val}"

        register_internal_handler("async_fn", async_handler)

        result = _run(executor._dispatch("internal", "async_fn", {"val": "99"}))
        assert result.success is True
        assert result.output == "async:99"

    def test_dispatch_internal_not_found(self, executor):
        result = _run(executor._dispatch("internal", "no_such_handler_xyz", {}))
        assert result.success is False
        assert "Internal handler not found" in result.error

    def test_dispatch_internal_returns_none(self, executor):
        register_internal_handler("null_fn", lambda **kw: None)
        result = _run(executor._dispatch("internal", "null_fn", {}))
        assert result.success is True
        assert result.output == ""

    @patch("chat_app.skill_executor.SkillExecutor._execute_react", new_callable=AsyncMock)
    def test_dispatch_react_loop(self, mock_react, executor):
        mock_react.return_value = SkillExecResult(success=True, output="react output")
        result = _run(executor._dispatch("react_loop", "react_loop", {"query": "test"}))
        assert result.success is True
        assert result.output == "react output"
        mock_react.assert_awaited_once_with({"query": "test"})

    def test_dispatch_unknown_source(self, executor):
        result = _run(executor._dispatch("alien_source", "key", {}))
        assert result.success is False
        assert "Unknown source" in result.error


# ===========================================================================
# 7. SkillExecutor.get_available_skills()
# ===========================================================================

class TestGetAvailableSkills:
    def test_empty_catalog(self, executor, mock_skill_catalog):
        mock_skill_catalog.get_enabled.return_value = []
        available = executor.get_available_skills()
        assert available == []

    def test_returns_only_resolvable(self, executor, mock_skill_catalog):
        s1 = _make_skill(name="has_handler", handler_key="hh")
        s2 = _make_skill(name="no_handler", handler_key="missing_xyz")
        mock_skill_catalog.get_enabled.return_value = [s1, s2]
        register_internal_handler("hh", lambda **kw: "ok")

        available = executor.get_available_skills()
        assert len(available) == 1
        assert available[0]["name"] == "has_handler"
        assert available[0]["source"] == "internal"

    def test_includes_all_fields(self, executor, mock_skill_catalog):
        s = _make_skill(name="full_s", action="analyze", handler_key="fh")
        s.family = SkillFamily.OPERATIONAL
        s.approval = ApprovalGate.CONFIRM
        mock_skill_catalog.get_enabled.return_value = [s]
        register_internal_handler("fh", lambda **kw: "ok")

        available = executor.get_available_skills()
        assert len(available) == 1
        entry = available[0]
        assert entry["name"] == "full_s"
        assert entry["action"] == "analyze"
        assert entry["handler_key"] == "fh"
        assert entry["source"] == "internal"
        assert entry["family"] == "operational"
        assert entry["approval"] == "confirm"


# ===========================================================================
# 8. SkillExecutor.get_skills_for_intent()
# ===========================================================================

class TestGetSkillsForIntent:
    def test_empty(self, executor, mock_skill_catalog):
        mock_skill_catalog.get_for_intent.return_value = []
        result = executor.get_skills_for_intent("spl_generation")
        assert result == []

    def test_filters_unresolvable(self, executor, mock_skill_catalog):
        s1 = _make_skill(name="resolvable", handler_key="rk")
        s2 = _make_skill(name="not_resolvable", handler_key="nope_xyz")
        mock_skill_catalog.get_for_intent.return_value = [s1, s2]
        register_internal_handler("rk", lambda **kw: "ok")

        result = executor.get_skills_for_intent("spl_generation")
        assert len(result) == 1
        assert result[0]["name"] == "resolvable"

    def test_returns_correct_fields(self, executor, mock_skill_catalog):
        s = _make_skill(name="sk", action="think", handler_key="sk_h")
        mock_skill_catalog.get_for_intent.return_value = [s]
        register_internal_handler("sk_h", lambda **kw: "ok")

        result = executor.get_skills_for_intent("analysis")
        assert len(result) == 1
        assert result[0]["name"] == "sk"
        assert result[0]["action"] == "think"
        assert result[0]["handler_key"] == "sk_h"
        assert result[0]["source"] == "internal"


# ===========================================================================
# 9. SkillExecutor.get_metrics()
# ===========================================================================

class TestGetMetrics:
    def test_initial_metrics(self, executor, mock_skill_catalog):
        mock_skill_catalog.get_enabled.return_value = []
        mock_skill_catalog.count = 10
        metrics = executor.get_metrics()
        assert metrics["total_executions"] == 0
        assert metrics["total_errors"] == 0
        assert metrics["error_rate"] == 0.0
        assert metrics["avg_latency_ms"] == 0.0
        assert metrics["total_catalog_skills"] == 10

    def test_metrics_after_success(self, executor, mock_skill_catalog):
        mock_skill_catalog.get_enabled.return_value = []
        mock_skill_catalog.count = 5
        register_internal_handler("m_ok", lambda **kw: "ok")

        _run(executor.execute(handler_key="m_ok"))
        metrics = executor.get_metrics()
        assert metrics["total_executions"] == 1
        assert metrics["total_errors"] == 0
        assert metrics["error_rate"] == 0.0

    def test_metrics_after_dispatch_error(self, executor, mock_skill_catalog):
        """A handler that resolves but throws is recorded as an error."""
        mock_skill_catalog.get_enabled.return_value = []
        mock_skill_catalog.count = 5
        register_internal_handler("m_ok", lambda **kw: "ok")

        def boom(**kw):
            raise RuntimeError("fail")
        register_internal_handler("m_err", boom)

        _run(executor.execute(handler_key="m_ok"))
        _run(executor.execute(handler_key="m_err"))

        metrics = executor.get_metrics()
        assert metrics["total_executions"] == 2
        assert metrics["total_errors"] == 1
        assert metrics["error_rate"] == 0.5

    def test_metrics_approval_recorded_but_not_as_error(self, executor, mock_skill_catalog):
        """Approval-required results are recorded but NOT counted as errors."""
        mock_skill_catalog.get_enabled.return_value = []
        mock_skill_catalog.count = 0
        skill = _make_skill(name="appr", handler_key="appr_h", approval=ApprovalGate.CONFIRM)
        mock_skill_catalog.get.return_value = skill
        register_internal_handler("appr_h", lambda **kw: "ok")

        _run(executor.execute(skill_name="appr", user_approved=False))
        metrics = executor.get_metrics()
        # Approval is recorded as an execution but NOT as an error
        assert metrics["total_executions"] == 1
        assert metrics["total_errors"] == 0

    def test_avg_latency(self, executor, mock_skill_catalog):
        mock_skill_catalog.get_enabled.return_value = []
        mock_skill_catalog.count = 0
        register_internal_handler("lat_h", lambda **kw: "ok")

        _run(executor.execute(handler_key="lat_h"))
        _run(executor.execute(handler_key="lat_h"))

        metrics = executor.get_metrics()
        assert metrics["total_executions"] == 2
        assert metrics["avg_latency_ms"] >= 0


# ===========================================================================
# 10. SkillExecutor.get_execution_log()
# ===========================================================================

class TestGetExecutionLog:
    def test_empty_log(self, executor):
        assert executor.get_execution_log() == []

    def test_log_after_execution(self, executor):
        register_internal_handler("log_h", lambda **kw: "logged")
        _run(executor.execute(handler_key="log_h"))

        log = executor.get_execution_log()
        assert len(log) == 1
        entry = log[0]
        assert entry["handler_key"] == "log_h"
        assert entry["source"] == "internal"
        assert entry["success"] is True
        assert "timestamp" in entry
        assert "duration_ms" in entry

    def test_log_limit(self, executor):
        register_internal_handler("lim_h", lambda **kw: "ok")
        for _ in range(5):
            _run(executor.execute(handler_key="lim_h"))

        assert len(executor.get_execution_log(limit=3)) == 3
        assert len(executor.get_execution_log(limit=10)) == 5

    def test_log_records_dispatch_errors(self, executor):
        """Handlers that resolve but throw still get logged."""
        def boom(**kw):
            raise RuntimeError("fail")
        register_internal_handler("log_err_handler", boom)

        _run(executor.execute(handler_key="log_err_handler"))
        log = executor.get_execution_log()
        assert len(log) == 1
        assert log[0]["success"] is False
        assert log[0]["error"] is not None

    def test_log_handler_not_found_is_recorded(self, executor):
        """When handler is not found, the error is still logged."""
        _run(executor.execute(handler_key="no_exist_xyz"))
        log = executor.get_execution_log()
        assert len(log) == 1
        assert log[0]["success"] is False
        assert "Handler not found" in log[0]["error"]

    def test_log_truncation_at_200(self, executor):
        register_internal_handler("trunc_h", lambda **kw: "ok")
        for _ in range(210):
            _run(executor.execute(handler_key="trunc_h"))

        # Internal log should be capped at 200
        assert len(executor._execution_log) == 200

    def test_log_entry_fields(self, executor):
        register_internal_handler("fields_h", lambda **kw: "ok")
        _run(executor.execute(handler_key="fields_h"))

        entry = executor.get_execution_log()[0]
        expected_keys = {"skill", "handler_key", "source", "success", "duration_ms", "timestamp", "error", "intent"}
        assert expected_keys == set(entry.keys())


# ===========================================================================
# 11. Singleton get_skill_executor()
# ===========================================================================

class TestSingleton:
    @patch("chat_app.skill_executor._executor", None)
    @patch("chat_app.skill_executor._INTERNAL_HANDLERS", {})
    @patch("chat_app.skill_executor.get_tool_registry")
    @patch("chat_app.skill_executor.get_skill_catalog")
    @patch("chat_app.skill_executor._register_builtin_internal_handlers")
    def test_creates_on_first_call(self, mock_reg_handlers, mock_cat, mock_tr):
        mock_tr.return_value = ToolRegistry()
        mock_cat.return_value = MagicMock(spec=SkillCatalog)
        ex = get_skill_executor()
        assert ex is not None
        mock_reg_handlers.assert_called_once()

    @patch("chat_app.skill_executor._executor", None)
    @patch("chat_app.skill_executor._INTERNAL_HANDLERS", {})
    @patch("chat_app.skill_executor.get_tool_registry")
    @patch("chat_app.skill_executor.get_skill_catalog")
    @patch("chat_app.skill_executor._register_builtin_internal_handlers")
    def test_returns_same_instance(self, mock_reg_handlers, mock_cat, mock_tr):
        mock_tr.return_value = ToolRegistry()
        mock_cat.return_value = MagicMock(spec=SkillCatalog)
        ex1 = get_skill_executor()
        ex2 = get_skill_executor()
        assert ex1 is ex2
        # Only called once on first creation
        mock_reg_handlers.assert_called_once()


# ===========================================================================
# 12. set_capabilities
# ===========================================================================

class TestSetCapabilities:
    def test_set_capabilities(self, executor):
        executor.set_capabilities({"splunk_connected", "mcp_available"})
        assert executor._capabilities == {"splunk_connected", "mcp_available"}

    def test_empty_capabilities(self, executor):
        executor.set_capabilities(set())
        assert executor._capabilities == set()


# ===========================================================================
# 13. _execute_react
# ===========================================================================

class TestExecuteReact:
    @patch("chat_app.react_loop.format_tool_context_for_llm")
    @patch("chat_app.react_loop.execute_react_loop", new_callable=AsyncMock)
    def test_react_success(self, mock_react, mock_format):
        mock_trace = MagicMock()
        mock_trace.tools_used = ["analyze_spl"]
        mock_react.return_value = mock_trace
        mock_format.return_value = "React analysis result"

        ex = SkillExecutor(
            tool_registry=ToolRegistry(),
            skills_manager=None,
            skill_catalog=MagicMock(spec=SkillCatalog),
        )
        result = _run(ex._execute_react({"user_input": "test query", "intent": "spl_generation"}))
        assert result.success is True
        assert result.output == "React analysis result"

    @patch("chat_app.react_loop.format_tool_context_for_llm")
    @patch("chat_app.react_loop.execute_react_loop", new_callable=AsyncMock)
    def test_react_empty_context(self, mock_react, mock_format):
        """When format_tool_context_for_llm returns empty, success is False."""
        mock_trace = MagicMock()
        mock_trace.tools_used = []
        mock_react.return_value = mock_trace
        mock_format.return_value = ""

        ex = SkillExecutor(
            tool_registry=ToolRegistry(),
            skills_manager=None,
            skill_catalog=MagicMock(spec=SkillCatalog),
        )
        result = _run(ex._execute_react({"user_input": "test", "intent": "spl_generation"}))
        assert result.success is False
        assert result.output == ""

    def test_react_import_failure(self):
        """When react_loop import fails, error is captured."""
        ex = SkillExecutor(
            tool_registry=ToolRegistry(),
            skills_manager=None,
            skill_catalog=MagicMock(spec=SkillCatalog),
        )
        # Temporarily remove the module to force ImportError
        saved = sys.modules.get("chat_app.react_loop")
        sys.modules["chat_app.react_loop"] = None  # Will cause ImportError
        try:
            result = _run(ex._execute_react({"query": "test"}))
            assert result.success is False
            assert "ReAct loop failed" in result.error
        finally:
            if saved is not None:
                sys.modules["chat_app.react_loop"] = saved
            else:
                sys.modules.pop("chat_app.react_loop", None)


# ===========================================================================
# 14. Edge cases / additional coverage
# ===========================================================================

class TestEdgeCases:
    def test_execute_with_none_params(self, executor):
        register_internal_handler("none_p", lambda **kw: "none_ok")
        result = _run(executor.execute(handler_key="none_p", params=None))
        assert result.success is True

    def test_execute_result_has_handler_key_and_source(self, executor):
        register_internal_handler("hk_test", lambda **kw: "test")
        result = _run(executor.execute(handler_key="hk_test"))
        assert result.handler_key == "hk_test"
        assert result.source == "internal"

    def test_dispatch_tool_error(self, executor, mock_tool_registry):
        async def _fail(**kw):
            return ToolResult(success=False, output="", error="tool failed", data=None)

        tool = Tool(
            name="fail_tool",
            description="fails",
            category=ToolCategory.ANALYSIS,
            execute_fn=_fail,
        )
        mock_tool_registry.register(tool)

        result = _run(executor._dispatch("tool_registry", "fail_tool", {}))
        assert result.success is False
        assert result.error == "tool failed"

    def test_execute_skill_not_in_catalog(self, executor, mock_skill_catalog):
        """When skill_name doesn't exist in catalog but handler_key is provided."""
        mock_skill_catalog.get.return_value = None
        register_internal_handler("direct_h", lambda **kw: "direct")

        result = _run(executor.execute(skill_name="no_skill", handler_key="direct_h"))
        assert result.success is True
        assert result.skill_name == "no_skill"

    def test_multiple_executions_accumulate_metrics(self, executor, mock_skill_catalog):
        mock_skill_catalog.get_enabled.return_value = []
        mock_skill_catalog.count = 0
        register_internal_handler("multi", lambda **kw: "ok")

        for _ in range(10):
            _run(executor.execute(handler_key="multi"))

        metrics = executor.get_metrics()
        assert metrics["total_executions"] == 10
        assert metrics["total_errors"] == 0

    def test_get_skills_for_intent_multiple_resolvable(self, executor, mock_skill_catalog):
        s1 = _make_skill(name="s1", handler_key="h1")
        s2 = _make_skill(name="s2", handler_key="h2")
        mock_skill_catalog.get_for_intent.return_value = [s1, s2]
        register_internal_handler("h1", lambda **kw: "ok")
        register_internal_handler("h2", lambda **kw: "ok")

        result = executor.get_skills_for_intent("spl_generation")
        assert len(result) == 2
        names = {r["name"] for r in result}
        assert names == {"s1", "s2"}

    def test_dispatch_tool_registry_data_propagation(self, executor, mock_tool_registry):
        """Verify data field propagates from ToolResult to SkillExecResult."""
        async def _data_tool(**kw):
            return ToolResult(success=True, output="out", data={"key": "val"})

        tool = Tool(
            name="data_tool", description="test",
            category=ToolCategory.ANALYSIS, execute_fn=_data_tool,
        )
        mock_tool_registry.register(tool)

        result = _run(executor._dispatch("tool_registry", "data_tool", {}))
        assert result.data == {"key": "val"}

    def test_dispatch_skills_manager_error_propagation(self, executor, mock_skills_manager):
        """Verify error field propagates from SkillsManager result."""
        sm_result = MagicMock()
        sm_result.success = False
        sm_result.output = ""
        sm_result.data = None
        sm_result.error = "sm failure"
        mock_skills_manager.execute_action.return_value = sm_result

        result = _run(executor._dispatch("skills_manager", "sm_action", {}))
        assert result.success is False
        assert result.error == "sm failure"

    def test_dispatch_internal_data_stored(self, executor):
        """Internal handler return value stored in data field."""
        register_internal_handler("data_fn", lambda **kw: {"analysis": True})

        result = _run(executor._dispatch("internal", "data_fn", {}))
        assert result.success is True
        assert result.data == {"analysis": True}

    def test_execution_log_preserves_order(self, executor):
        """Log entries appear in execution order."""
        register_internal_handler("a", lambda **kw: "a")
        register_internal_handler("b", lambda **kw: "b")
        register_internal_handler("c", lambda **kw: "c")

        _run(executor.execute(handler_key="a"))
        _run(executor.execute(handler_key="b"))
        _run(executor.execute(handler_key="c"))

        log = executor.get_execution_log()
        assert [e["handler_key"] for e in log] == ["a", "b", "c"]

    def test_get_available_skills_with_tool_registry(self, executor, mock_skill_catalog, mock_tool_registry):
        """Skills resolved via tool_registry show source=tool_registry."""
        tool = _make_tool("tr_handler")
        mock_tool_registry.register(tool)
        s = _make_skill(name="tr_skill", handler_key="tr_handler")
        mock_skill_catalog.get_enabled.return_value = [s]

        available = executor.get_available_skills()
        assert len(available) == 1
        assert available[0]["source"] == "tool_registry"

    def test_record_execution_no_error_on_approval_required(self, executor):
        """Directly test _record_execution: approval_required=True should not be an error."""
        result = SkillExecResult(
            success=False, output="", skill_name="x",
            approval_required=True, duration_ms=10.0,
        )
        executor._record_execution(result)
        assert executor._execution_count == 1
        assert executor._error_count == 0

    def test_record_execution_counts_real_error(self, executor):
        """Directly test _record_execution: actual failure increments error_count."""
        result = SkillExecResult(
            success=False, output="", skill_name="x",
            approval_required=False, error="real error", duration_ms=5.0,
        )
        executor._record_execution(result)
        assert executor._execution_count == 1
        assert executor._error_count == 1
