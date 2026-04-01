"""
Tests for AgentDispatcher — routes queries to agent personas and orchestrates skill execution.

Covers:
1.  AgentDispatchResult dataclass (get_combined_output, to_dict)
2.  AgentDispatcher.select_agent() — by intent, preferred_department, fallback, scoring
3.  AgentDispatcher.dispatch() — full dispatch flow, enriched context, approval gates
4.  AgentDispatcher._plan_agent_skills() — intent-matching, secondary fill, max_skills cap
5.  AgentDispatcher._extract_spl() — code block, inline SPL, no SPL
6.  AgentDispatcher.get_dispatch_log() — records dispatches
7.  AgentDispatcher.get_agent_metrics() — success rate, latency
8.  AgentDispatcher.get_summary() — totals, unique agents
9.  format_agent_context_for_llm() — personality + skill results
10. Singleton get_agent_dispatcher()
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import asyncio
import time
from dataclasses import field
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chat_app.agent_catalog import (
    AgentCatalog,
    AgentPersona,
    Department,
    ExpertiseLevel,
)
from chat_app.skill_catalog import (
    ApprovalGate,
    Skill,
    SkillCatalog,
    SkillFamily,
)
from chat_app.skill_executor import SkillExecResult, SkillExecutor
from chat_app.agent_dispatcher import (
    AgentDispatchResult,
    AgentDispatcher,
    format_agent_context_for_llm,
    get_agent_dispatcher,
)


# ---------------------------------------------------------------------------
# Helpers for building test fixtures
# ---------------------------------------------------------------------------

def _make_agent(**overrides) -> AgentPersona:
    """Build an AgentPersona with sensible defaults, overridable."""
    defaults = dict(
        role="test agent",
        name="test_agent",
        description="A test agent",
        department=Department.ENGINEERING,
        skills=["skill_a", "skill_b"],
        personality="Helpful and precise.",
        expertise=ExpertiseLevel.SPECIALIST,
        emoji="",
        intents=["test_intent"],
        tags=["test"],
        active=True,
    )
    defaults.update(overrides)
    return AgentPersona(**defaults)


def _make_skill(**overrides) -> Skill:
    """Build a Skill with sensible defaults, overridable."""
    defaults = dict(
        action="test",
        name="skill_a",
        description="A test skill",
        family=SkillFamily.COGNITIVE,
        handler_key="handler_a",
        intents=["test_intent"],
        tags=["test"],
        enabled=True,
        approval=ApprovalGate.AUTO,
    )
    defaults.update(overrides)
    return Skill(**defaults)


def _make_exec_result(success=True, output="result text", **kw) -> SkillExecResult:
    """Build a SkillExecResult with sensible defaults."""
    defaults = dict(
        success=success,
        output=output,
        skill_name="skill_a",
        handler_key="handler_a",
        approval_required=False,
    )
    defaults.update(kw)
    return SkillExecResult(**defaults)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_catalog():
    """An AgentCatalog mock with controllable returns."""
    cat = MagicMock(spec=AgentCatalog)
    cat.count = 5
    cat.get_for_intent.return_value = []
    cat.search.return_value = []
    cat.get.return_value = None
    return cat


@pytest.fixture
def mock_executor():
    """A SkillExecutor mock whose execute() is async."""
    ex = MagicMock(spec=SkillExecutor)
    ex.execute = AsyncMock(return_value=_make_exec_result())
    ex.resolve_handler = MagicMock(return_value=("internal", "handler_a"))
    return ex


@pytest.fixture
def dispatcher(mock_catalog, mock_executor):
    """Dispatcher wired to mock catalog + executor."""
    return AgentDispatcher(agent_catalog=mock_catalog, skill_executor=mock_executor)


@pytest.fixture
def sample_agent():
    return _make_agent()


# ===================================================================
# 1. AgentDispatchResult dataclass
# ===================================================================

class TestAgentDispatchResult:
    # -- get_combined_output --

    def test_combined_output_multiple_successful(self):
        r = AgentDispatchResult(
            agent_name="a", agent_role="r", department="d",
            skill_results=[
                _make_exec_result(output="part1"),
                _make_exec_result(output="part2"),
            ],
        )
        assert r.get_combined_output() == "part1\n\npart2"

    def test_combined_output_skips_failures(self):
        r = AgentDispatchResult(
            agent_name="a", agent_role="r", department="d",
            skill_results=[
                _make_exec_result(output="good"),
                _make_exec_result(success=False, output="bad"),
            ],
        )
        assert r.get_combined_output() == "good"

    def test_combined_output_skips_empty_output(self):
        r = AgentDispatchResult(
            agent_name="a", agent_role="r", department="d",
            skill_results=[
                _make_exec_result(output=""),
                _make_exec_result(output="data"),
            ],
        )
        assert r.get_combined_output() == "data"

    def test_combined_output_empty_list(self):
        r = AgentDispatchResult(
            agent_name="a", agent_role="r", department="d",
            skill_results=[],
        )
        assert r.get_combined_output() == ""

    def test_combined_output_all_failures(self):
        r = AgentDispatchResult(
            agent_name="a", agent_role="r", department="d",
            skill_results=[
                _make_exec_result(success=False, output="err1"),
                _make_exec_result(success=False, output="err2"),
            ],
        )
        assert r.get_combined_output() == ""

    # -- to_dict --

    def test_to_dict_keys(self):
        r = AgentDispatchResult(
            agent_name="spl_coder", agent_role="coder",
            department="engineering",
            skills_executed=["generate_spl"],
            success=True, error=None, duration_ms=42.567,
        )
        d = r.to_dict()
        assert d["agent_name"] == "spl_coder"
        assert d["agent_role"] == "coder"
        assert d["department"] == "engineering"
        assert d["skills_executed"] == ["generate_spl"]
        assert d["success"] is True
        assert d["error"] is None
        assert d["duration_ms"] == 42.57  # rounded to 2

    def test_to_dict_duration_rounded(self):
        r = AgentDispatchResult(
            agent_name="a", agent_role="r", department="d",
            duration_ms=1.23456,
        )
        assert r.to_dict()["duration_ms"] == 1.23

    def test_to_dict_with_error(self):
        r = AgentDispatchResult(
            agent_name="a", agent_role="r", department="d",
            success=False, error="something broke",
        )
        d = r.to_dict()
        assert d["success"] is False
        assert d["error"] == "something broke"

    def test_default_fields(self):
        r = AgentDispatchResult(agent_name="a", agent_role="r", department="d")
        assert r.skills_executed == []
        assert r.skill_results == []
        assert r.enriched_context == ""
        assert r.system_prompt_fragment == ""
        assert r.success is True
        assert r.error is None
        assert r.duration_ms == 0.0


# ===================================================================
# 2. select_agent()
# ===================================================================

class TestSelectAgent:
    def test_returns_agent_for_known_intent(self, dispatcher, mock_catalog):
        agent = _make_agent(name="spl_coder", intents=["spl_generation"])
        mock_catalog.get_for_intent.return_value = [agent]
        result = dispatcher.select_agent("spl_generation")
        assert result is agent

    def test_fallback_to_search_when_no_intent_match(self, dispatcher, mock_catalog):
        agent = _make_agent(name="found_agent")
        mock_catalog.get_for_intent.return_value = []
        mock_catalog.search.return_value = [agent]
        result = dispatcher.select_agent("unknown_intent", user_input="show me data")
        # Multi-word fallback: searches each word >= 3 chars
        assert mock_catalog.search.call_count >= 1
        mock_catalog.search.assert_any_call("show")
        assert result is agent

    def test_fallback_to_general_assistant(self, dispatcher, mock_catalog):
        fallback = _make_agent(name="general_assistant", role="helper")
        mock_catalog.get_for_intent.return_value = []
        mock_catalog.search.return_value = []
        mock_catalog.get.return_value = fallback
        result = dispatcher.select_agent("random_intent", user_input="hello")
        mock_catalog.get.assert_called_with("general_assistant")
        assert result is fallback

    def test_returns_none_when_no_agent_found(self, dispatcher, mock_catalog):
        mock_catalog.get_for_intent.return_value = []
        mock_catalog.search.return_value = []
        mock_catalog.get.return_value = None
        result = dispatcher.select_agent("nonexistent", user_input="hello")
        assert result is None

    def test_returns_none_no_input_no_agents(self, dispatcher, mock_catalog):
        mock_catalog.get_for_intent.return_value = []
        mock_catalog.get.return_value = None
        result = dispatcher.select_agent("nonexistent", user_input="")
        assert result is None

    def test_preferred_department_filters(self, dispatcher, mock_catalog):
        eng_agent = _make_agent(name="eng", department=Department.ENGINEERING, intents=["i"])
        ops_agent = _make_agent(name="ops", department=Department.OPERATIONS, intents=["i"])
        mock_catalog.get_for_intent.return_value = [eng_agent, ops_agent]
        result = dispatcher.select_agent(
            "i", preferred_department=Department.OPERATIONS,
        )
        assert result is ops_agent

    def test_preferred_department_ignored_if_no_match(self, dispatcher, mock_catalog):
        eng_agent = _make_agent(name="eng", department=Department.ENGINEERING, intents=["i"])
        mock_catalog.get_for_intent.return_value = [eng_agent]
        result = dispatcher.select_agent(
            "i", preferred_department=Department.SECURITY,
        )
        # Falls back to the only candidate
        assert result is eng_agent

    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    def test_scoring_prefers_higher_expertise(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        # Make resolve_handler always return something so skills count
        mock_executor.resolve_handler.return_value = ("internal", "h")

        specialist = _make_agent(
            name="spec", expertise=ExpertiseLevel.SPECIALIST,
            intents=["i"], skills=["s1"],
        )
        expert = _make_agent(
            name="exp", expertise=ExpertiseLevel.EXPERT,
            intents=["i"], skills=["s1"],
        )

        mock_skill_catalog = MagicMock()
        mock_skill_catalog.get.return_value = _make_skill()
        mock_get_cat.return_value = mock_skill_catalog
        mock_get_cat_helpers.return_value = mock_skill_catalog

        mock_catalog.get_for_intent.return_value = [specialist, expert]
        result = dispatcher.select_agent("i")
        assert result.name == "exp"

    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    def test_scoring_intent_match_bonus(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        mock_executor.resolve_handler.return_value = (None, None)
        mock_get_cat.return_value = MagicMock(**{"get.return_value": None})
        mock_get_cat_helpers.return_value = MagicMock(**{"get.return_value": None})

        with_intent = _make_agent(
            name="with_intent", expertise=ExpertiseLevel.SPECIALIST,
            intents=["target_intent"], skills=[],
        )
        without_intent = _make_agent(
            name="without_intent", expertise=ExpertiseLevel.SPECIALIST,
            intents=["other"], skills=[],
        )
        mock_catalog.get_for_intent.return_value = [with_intent, without_intent]
        result = dispatcher.select_agent("target_intent")
        assert result.name == "with_intent"

    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    def test_scoring_role_keyword_bonus(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        mock_executor.resolve_handler.return_value = (None, None)
        mock_get_cat.return_value = MagicMock(**{"get.return_value": None})
        mock_get_cat_helpers.return_value = MagicMock(**{"get.return_value": None})

        agent_a = _make_agent(
            name="a", role="coder", expertise=ExpertiseLevel.SPECIALIST,
            intents=["i"], skills=[], tags=[],
        )
        agent_b = _make_agent(
            name="b", role="helper", expertise=ExpertiseLevel.SPECIALIST,
            intents=["i"], skills=[], tags=[],
        )
        mock_catalog.get_for_intent.return_value = [agent_a, agent_b]
        # user_input contains "coder" -> agent_a gets role bonus
        result = dispatcher.select_agent("i", user_input="I need a coder please")
        assert result.name == "a"

    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    def test_scoring_tag_keyword_bonus(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        mock_executor.resolve_handler.return_value = (None, None)
        mock_get_cat.return_value = MagicMock(**{"get.return_value": None})
        mock_get_cat_helpers.return_value = MagicMock(**{"get.return_value": None})

        agent_a = _make_agent(
            name="a", expertise=ExpertiseLevel.SPECIALIST,
            intents=["i"], skills=[], tags=["security"],
        )
        agent_b = _make_agent(
            name="b", expertise=ExpertiseLevel.SPECIALIST,
            intents=["i"], skills=[], tags=["coding"],
        )
        mock_catalog.get_for_intent.return_value = [agent_a, agent_b]
        result = dispatcher.select_agent("i", user_input="security concern")
        assert result.name == "a"

    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    def test_scoring_executable_skills_bonus(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        """Agent with more executable skills gets a higher score."""
        skill_mock = _make_skill()
        mock_get_cat.return_value = MagicMock(**{"get.return_value": skill_mock})
        mock_get_cat_helpers.return_value = MagicMock(**{"get.return_value": skill_mock})

        # agent with 3 executable skills
        many = _make_agent(
            name="many", expertise=ExpertiseLevel.SPECIALIST,
            intents=["i"], skills=["s1", "s2", "s3"], tags=[],
        )
        # agent with 1 executable skill
        few = _make_agent(
            name="few", expertise=ExpertiseLevel.SPECIALIST,
            intents=["i"], skills=["s1"], tags=[],
        )
        mock_executor.resolve_handler.return_value = ("internal", "h")
        mock_catalog.get_for_intent.return_value = [few, many]
        result = dispatcher.select_agent("i")
        assert result.name == "many"


# ===================================================================
# 3. dispatch()
# ===================================================================

class TestDispatch:
    @pytest.mark.asyncio
    async def test_dispatch_no_agent_found(self, dispatcher, mock_catalog):
        mock_catalog.get_for_intent.return_value = []
        mock_catalog.search.return_value = []
        mock_catalog.get.return_value = None

        result = await dispatcher.dispatch("hello", "unknown_intent")
        assert result.success is False
        assert result.agent_name == "none"
        assert "No suitable agent" in result.error
        assert result.duration_ms > 0

    @pytest.mark.asyncio
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    async def test_dispatch_executes_skills(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        agent = _make_agent(name="coder", skills=["skill_a", "skill_b"], intents=["gen"])
        mock_catalog.get_for_intent.return_value = [agent]

        skill_a = _make_skill(name="skill_a", handler_key="ha", intents=["gen"])
        skill_b = _make_skill(name="skill_b", handler_key="hb", intents=["gen"])
        cat = MagicMock(spec=SkillCatalog)
        cat.get.side_effect = lambda n: {"skill_a": skill_a, "skill_b": skill_b}.get(n)
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat

        mock_executor.resolve_handler.return_value = ("internal", "h")
        mock_executor.execute = AsyncMock(return_value=_make_exec_result(output="done"))

        result = await dispatcher.dispatch("generate spl", "gen")
        assert result.success is True
        assert result.agent_name == "coder"
        assert len(result.skills_executed) == 2
        assert result.duration_ms > 0

    @pytest.mark.asyncio
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    async def test_dispatch_enriched_context_built(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        agent = _make_agent(name="ag", skills=["s1"], intents=["i"])
        mock_catalog.get_for_intent.return_value = [agent]

        skill = _make_skill(name="s1", handler_key="h1", intents=["i"])
        cat = MagicMock(spec=SkillCatalog)
        cat.get.return_value = skill
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat

        mock_executor.resolve_handler.return_value = ("internal", "h1")
        mock_executor.execute = AsyncMock(
            return_value=_make_exec_result(output="Analysis output here")
        )

        result = await dispatcher.dispatch("query", "i")
        assert "Analysis output here" in result.enriched_context
        assert "Agent:" in result.enriched_context

    @pytest.mark.asyncio
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    async def test_dispatch_stops_on_approval_required(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        agent = _make_agent(name="ag", skills=["s1", "s2"], intents=["i"])
        mock_catalog.get_for_intent.return_value = [agent]

        s1 = _make_skill(name="s1", handler_key="h1", intents=["i"])
        s2 = _make_skill(name="s2", handler_key="h2", intents=["i"])
        cat = MagicMock(spec=SkillCatalog)
        cat.get.side_effect = lambda n: {"s1": s1, "s2": s2}.get(n)
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat

        mock_executor.resolve_handler.return_value = ("internal", "h")
        approval_result = _make_exec_result(
            success=False, output="", approval_required=True,
        )
        mock_executor.execute = AsyncMock(return_value=approval_result)

        result = await dispatcher.dispatch("query", "i")
        # Should stop after first skill since approval_required
        assert len(result.skills_executed) == 1

    @pytest.mark.asyncio
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    async def test_dispatch_records_dispatch(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        agent = _make_agent(name="ag", skills=["s1"], intents=["i"])
        mock_catalog.get_for_intent.return_value = [agent]

        cat = MagicMock(spec=SkillCatalog)
        cat.get.return_value = _make_skill(name="s1", handler_key="h1", intents=["i"])
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat

        mock_executor.resolve_handler.return_value = ("internal", "h1")
        mock_executor.execute = AsyncMock(return_value=_make_exec_result())

        assert len(dispatcher.get_dispatch_log()) == 0
        await dispatcher.dispatch("query", "i")
        assert len(dispatcher.get_dispatch_log()) == 1

    @pytest.mark.asyncio
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    async def test_dispatch_success_true_when_any_skill_succeeds(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        agent = _make_agent(name="ag", skills=["s1", "s2"], intents=["i"])
        mock_catalog.get_for_intent.return_value = [agent]

        s1 = _make_skill(name="s1", handler_key="h1", intents=["i"])
        s2 = _make_skill(name="s2", handler_key="h2", intents=["i"])
        cat = MagicMock(spec=SkillCatalog)
        cat.get.side_effect = lambda n: {"s1": s1, "s2": s2}.get(n)
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat

        mock_executor.resolve_handler.return_value = ("internal", "h")

        call_count = 0

        async def alternating_execute(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_exec_result(success=False, output="")
            return _make_exec_result(success=True, output="ok")

        mock_executor.execute = AsyncMock(side_effect=alternating_execute)

        result = await dispatcher.dispatch("query", "i")
        assert result.success is True

    @pytest.mark.asyncio
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    async def test_dispatch_success_true_when_no_skills(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        """If agent has no executable skills, success defaults to True."""
        agent = _make_agent(name="ag", skills=[], intents=["i"])
        mock_catalog.get_for_intent.return_value = [agent]
        mock_get_cat.return_value = MagicMock(**{"get.return_value": None})
        mock_get_cat_helpers.return_value = MagicMock(**{"get.return_value": None})

        result = await dispatcher.dispatch("query", "i")
        assert result.success is True
        assert result.skills_executed == []

    @pytest.mark.asyncio
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    async def test_dispatch_spl_extraction_for_analyze_spl(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        """When skill handler_key is analyze_spl, SPL is extracted from input."""
        agent = _make_agent(name="ag", skills=["s1"], intents=["i"])
        mock_catalog.get_for_intent.return_value = [agent]

        skill = _make_skill(name="s1", handler_key="analyze_spl", intents=["i"])
        cat = MagicMock(spec=SkillCatalog)
        cat.get.return_value = skill
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat

        mock_executor.resolve_handler.return_value = ("internal", "analyze_spl")
        mock_executor.execute = AsyncMock(return_value=_make_exec_result())

        spl_input = "Please analyze:\n```spl\nindex=main | stats count by host\n```"
        await dispatcher.dispatch(spl_input, "i")

        # Verify the params passed to execute include 'query'
        call_kwargs = mock_executor.execute.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert "query" in params
        assert "index=main" in params["query"]

    @pytest.mark.asyncio
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    async def test_dispatch_description_for_generate_spl(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        agent = _make_agent(name="ag", skills=["s1"], intents=["i"])
        mock_catalog.get_for_intent.return_value = [agent]

        skill = _make_skill(name="s1", handler_key="generate_spl", intents=["i"])
        cat = MagicMock(spec=SkillCatalog)
        cat.get.return_value = skill
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat

        mock_executor.resolve_handler.return_value = ("internal", "generate_spl")
        mock_executor.execute = AsyncMock(return_value=_make_exec_result())

        await dispatcher.dispatch("count errors by host", "i")
        call_kwargs = mock_executor.execute.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert params["description"] == "count errors by host"

    @pytest.mark.asyncio
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    async def test_dispatch_search_knowledge_base(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        agent = _make_agent(name="ag", skills=["s1"], intents=["i"])
        mock_catalog.get_for_intent.return_value = [agent]

        skill = _make_skill(name="s1", handler_key="search_knowledge_base", intents=["i"])
        cat = MagicMock(spec=SkillCatalog)
        cat.get.return_value = skill
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat

        mock_executor.resolve_handler.return_value = ("internal", "search_knowledge_base")
        mock_executor.execute = AsyncMock(return_value=_make_exec_result())

        await dispatcher.dispatch("what is tstats", "i")
        call_kwargs = mock_executor.execute.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert params["query"] == "what is tstats"

    @pytest.mark.asyncio
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    async def test_dispatch_with_preferred_department(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        eng = _make_agent(name="eng", department=Department.ENGINEERING, intents=["i"], skills=["s1"])
        ops = _make_agent(name="ops", department=Department.OPERATIONS, intents=["i"], skills=["s1"])
        mock_catalog.get_for_intent.return_value = [eng, ops]

        mock_get_cat.return_value = MagicMock(**{"get.return_value": _make_skill(intents=["i"])})
        mock_get_cat_helpers.return_value = MagicMock(**{"get.return_value": _make_skill(intents=["i"])})
        mock_executor.resolve_handler.return_value = ("internal", "h")
        mock_executor.execute = AsyncMock(return_value=_make_exec_result())

        result = await dispatcher.dispatch(
            "query", "i", preferred_department=Department.OPERATIONS,
        )
        assert result.agent_name == "ops"

    @pytest.mark.asyncio
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    async def test_dispatch_system_prompt_fragment_set(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        agent = _make_agent(name="ag", role="coder", skills=[], intents=["i"],
                           personality="Precise builder.")
        mock_catalog.get_for_intent.return_value = [agent]
        mock_get_cat.return_value = MagicMock(**{"get.return_value": None})
        mock_get_cat_helpers.return_value = MagicMock(**{"get.return_value": None})

        result = await dispatcher.dispatch("query", "i")
        assert "Coder" in result.system_prompt_fragment
        assert "Precise builder" in result.system_prompt_fragment


# ===================================================================
# 4. _plan_agent_skills()
# ===================================================================

class TestPlanAgentSkills:
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    def test_intent_matching_skills_prioritized(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_executor):
        primary = _make_skill(name="primary", handler_key="h1", intents=["target"])
        secondary = _make_skill(name="secondary", handler_key="h2", intents=["other"])
        cat = MagicMock(spec=SkillCatalog)
        cat.get.side_effect = lambda n: {"primary": primary, "secondary": secondary}.get(n)
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat
        mock_executor.resolve_handler.return_value = ("internal", "h")

        agent = _make_agent(skills=["secondary", "primary"], intents=["target"])
        planned = dispatcher._plan_agent_skills(agent, "target", "", max_skills=3)
        assert planned[0] == "primary"

    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    def test_secondary_fills_remaining(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_executor):
        primary = _make_skill(name="primary", handler_key="h1", intents=["target"])
        secondary = _make_skill(name="secondary", handler_key="h2", intents=["other"])
        cat = MagicMock(spec=SkillCatalog)
        cat.get.side_effect = lambda n: {"primary": primary, "secondary": secondary}.get(n)
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat
        mock_executor.resolve_handler.return_value = ("internal", "h")

        agent = _make_agent(skills=["primary", "secondary"], intents=["target"])
        planned = dispatcher._plan_agent_skills(agent, "target", "", max_skills=3)
        assert "primary" in planned
        assert "secondary" in planned

    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    def test_max_skills_caps_output(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_executor):
        skills = [_make_skill(name=f"s{i}", handler_key=f"h{i}", intents=["t"]) for i in range(5)]
        cat = MagicMock(spec=SkillCatalog)
        cat.get.side_effect = lambda n: next((s for s in skills if s.name == n), None)
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat
        mock_executor.resolve_handler.return_value = ("internal", "h")

        agent = _make_agent(skills=[f"s{i}" for i in range(5)], intents=["t"])
        planned = dispatcher._plan_agent_skills(agent, "t", "", max_skills=2)
        assert len(planned) == 2

    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    def test_unresolvable_skills_skipped(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_executor):
        skill = _make_skill(name="s1", handler_key="h1", intents=["t"])
        cat = MagicMock(spec=SkillCatalog)
        cat.get.return_value = skill
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat
        mock_executor.resolve_handler.return_value = (None, None)

        agent = _make_agent(skills=["s1"], intents=["t"])
        planned = dispatcher._plan_agent_skills(agent, "t", "", max_skills=3)
        assert planned == []

    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    def test_unknown_skills_skipped(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_executor):
        cat = MagicMock(spec=SkillCatalog)
        cat.get.return_value = None
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat

        agent = _make_agent(skills=["nonexistent"], intents=["t"])
        planned = dispatcher._plan_agent_skills(agent, "t", "", max_skills=3)
        assert planned == []

    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    def test_empty_skills_list(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_executor):
        mock_get_cat.return_value = MagicMock(spec=SkillCatalog)
        mock_get_cat_helpers.return_value = MagicMock(spec=SkillCatalog)
        agent = _make_agent(skills=[], intents=["t"])
        planned = dispatcher._plan_agent_skills(agent, "t", "", max_skills=3)
        assert planned == []

    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    def test_secondary_limited_to_remaining(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_executor):
        """If 2 primary skills fill max_skills=2, no secondary skills added."""
        p1 = _make_skill(name="p1", handler_key="h1", intents=["t"])
        p2 = _make_skill(name="p2", handler_key="h2", intents=["t"])
        sec = _make_skill(name="sec", handler_key="h3", intents=["other"])
        cat = MagicMock(spec=SkillCatalog)
        cat.get.side_effect = lambda n: {"p1": p1, "p2": p2, "sec": sec}.get(n)
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat
        mock_executor.resolve_handler.return_value = ("internal", "h")

        agent = _make_agent(skills=["p1", "p2", "sec"], intents=["t"])
        planned = dispatcher._plan_agent_skills(agent, "t", "", max_skills=2)
        assert len(planned) == 2
        assert "sec" not in planned


# ===================================================================
# 5. _extract_spl()
# ===================================================================

class TestExtractSpl:
    def test_code_block_with_spl_tag(self, dispatcher):
        text = "Check this:\n```spl\nindex=main | stats count\n```"
        assert dispatcher._extract_spl(text) == "index=main | stats count"

    def test_code_block_without_tag(self, dispatcher):
        text = "Check this:\n```\nindex=main | head 10\n```"
        assert dispatcher._extract_spl(text) == "index=main | head 10"

    def test_code_block_multiline(self, dispatcher):
        text = "```spl\nindex=main\n| stats count by host\n| sort -count\n```"
        result = dispatcher._extract_spl(text)
        assert result is not None
        assert "index=main" in result
        assert "stats count" in result

    def test_inline_spl_with_index(self, dispatcher):
        text = "Please optimize index=main sourcetype=syslog | stats count by host"
        result = dispatcher._extract_spl(text)
        assert result is not None
        assert "index=" in result

    def test_inline_spl_with_pipe(self, dispatcher):
        text = "Please help with | stats count by src_ip"
        result = dispatcher._extract_spl(text)
        assert result is not None
        assert "stats count" in result

    def test_no_spl_returns_none(self, dispatcher):
        text = "How do I create a dashboard?"
        result = dispatcher._extract_spl(text)
        assert result is None

    def test_no_spl_simple_text(self, dispatcher):
        text = "Hello, how are you?"
        assert dispatcher._extract_spl(text) is None

    def test_empty_input(self, dispatcher):
        assert dispatcher._extract_spl("") is None

    def test_code_block_strips_whitespace(self, dispatcher):
        text = "```spl\n   index=main | head 5   \n```"
        result = dispatcher._extract_spl(text)
        assert result == "index=main | head 5"


# ===================================================================
# 6. get_dispatch_log()
# ===================================================================

class TestGetDispatchLog:
    def test_empty_log(self, dispatcher):
        assert dispatcher.get_dispatch_log() == []

    def test_records_dispatches(self, dispatcher):
        result = AgentDispatchResult(
            agent_name="a", agent_role="r", department="d",
            skills_executed=["s1"], success=True, duration_ms=10.0,
        )
        dispatcher._record_dispatch(result)
        log = dispatcher.get_dispatch_log()
        assert len(log) == 1
        assert log[0]["agent_name"] == "a"
        assert log[0]["success"] is True
        assert "timestamp" in log[0]

    def test_limit_respected(self, dispatcher):
        for i in range(10):
            r = AgentDispatchResult(
                agent_name=f"a{i}", agent_role="r", department="d",
                success=True, duration_ms=1.0,
            )
            dispatcher._record_dispatch(r)
        log = dispatcher.get_dispatch_log(limit=3)
        assert len(log) == 3
        # Should be the last 3
        assert log[-1]["agent_name"] == "a9"

    def test_log_capped_at_200(self, dispatcher):
        for i in range(210):
            r = AgentDispatchResult(
                agent_name=f"a{i}", agent_role="r", department="d",
                success=True, duration_ms=1.0,
            )
            dispatcher._record_dispatch(r)
        # Internal log capped at 200
        assert len(dispatcher._dispatch_log) == 200

    def test_log_entry_has_expected_keys(self, dispatcher):
        r = AgentDispatchResult(
            agent_name="n", agent_role="r", department="d",
            skills_executed=["s"], success=True, duration_ms=5.5,
        )
        dispatcher._record_dispatch(r)
        entry = dispatcher.get_dispatch_log()[0]
        for key in ("agent_name", "agent_role", "department", "skills_executed",
                     "success", "duration_ms", "timestamp"):
            assert key in entry


# ===================================================================
# 7. get_agent_metrics()
# ===================================================================

class TestGetAgentMetrics:
    def test_empty_metrics(self, dispatcher):
        assert dispatcher.get_agent_metrics() == {}

    def test_success_rate_computed(self, dispatcher):
        for success in [True, True, False]:
            r = AgentDispatchResult(
                agent_name="ag", agent_role="r", department="d",
                success=success, duration_ms=10.0,
            )
            dispatcher._record_dispatch(r)
        metrics = dispatcher.get_agent_metrics()
        assert "ag" in metrics
        # 2 successes / 3 dispatches
        assert metrics["ag"]["success_rate"] == round(2 / 3, 4)

    def test_avg_latency_computed(self, dispatcher):
        for ms in [10.0, 20.0, 30.0]:
            r = AgentDispatchResult(
                agent_name="ag", agent_role="r", department="d",
                success=True, duration_ms=ms,
            )
            dispatcher._record_dispatch(r)
        metrics = dispatcher.get_agent_metrics()
        assert metrics["ag"]["avg_latency_ms"] == 20.0

    def test_multiple_agents_tracked(self, dispatcher):
        for name in ["a", "b", "c"]:
            r = AgentDispatchResult(
                agent_name=name, agent_role="r", department="d",
                success=True, duration_ms=5.0,
            )
            dispatcher._record_dispatch(r)
        metrics = dispatcher.get_agent_metrics()
        assert len(metrics) == 3
        assert all(m["dispatches"] == 1 for m in metrics.values())

    def test_zero_dispatches_no_division_error(self, dispatcher):
        # Force a weird state by directly setting metrics with 0 dispatches
        dispatcher._agent_metrics["ghost"] = {
            "dispatches": 0, "successes": 0, "total_ms": 0.0,
        }
        metrics = dispatcher.get_agent_metrics()
        assert metrics["ghost"]["success_rate"] == 0.0
        assert metrics["ghost"]["avg_latency_ms"] == 0.0

    def test_all_failures_rate_zero(self, dispatcher):
        for _ in range(3):
            r = AgentDispatchResult(
                agent_name="ag", agent_role="r", department="d",
                success=False, duration_ms=5.0,
            )
            dispatcher._record_dispatch(r)
        assert dispatcher.get_agent_metrics()["ag"]["success_rate"] == 0.0

    def test_all_successes_rate_one(self, dispatcher):
        for _ in range(4):
            r = AgentDispatchResult(
                agent_name="ag", agent_role="r", department="d",
                success=True, duration_ms=5.0,
            )
            dispatcher._record_dispatch(r)
        assert dispatcher.get_agent_metrics()["ag"]["success_rate"] == 1.0


# ===================================================================
# 8. get_summary()
# ===================================================================

class TestGetSummary:
    def test_empty_summary(self, dispatcher):
        s = dispatcher.get_summary()
        assert s["total_dispatches"] == 0
        assert s["total_successes"] == 0
        assert s["success_rate"] == 0.0
        assert s["unique_agents_used"] == 0
        assert s["total_agents_available"] == dispatcher._catalog.count

    def test_summary_after_dispatches(self, dispatcher):
        for name in ["a", "b"]:
            r = AgentDispatchResult(
                agent_name=name, agent_role="r", department="d",
                success=True, duration_ms=5.0,
            )
            dispatcher._record_dispatch(r)
        r_fail = AgentDispatchResult(
            agent_name="a", agent_role="r", department="d",
            success=False, duration_ms=3.0,
        )
        dispatcher._record_dispatch(r_fail)

        s = dispatcher.get_summary()
        assert s["total_dispatches"] == 3
        assert s["total_successes"] == 2
        assert s["unique_agents_used"] == 2
        assert s["success_rate"] == round(2 / 3, 4)

    def test_total_agents_available(self, dispatcher, mock_catalog):
        mock_catalog.count = 42
        s = dispatcher.get_summary()
        assert s["total_agents_available"] == 42


# ===================================================================
# 9. format_agent_context_for_llm()
# ===================================================================

class TestFormatAgentContextForLlm:
    def test_returns_none_on_failed_no_context(self):
        r = AgentDispatchResult(
            agent_name="a", agent_role="r", department="d",
            success=False, enriched_context="",
        )
        assert format_agent_context_for_llm(r) is None

    def test_returns_personality_section(self):
        r = AgentDispatchResult(
            agent_name="a", agent_role="r", department="d",
            success=True,
            system_prompt_fragment="You are a coder.",
        )
        result = format_agent_context_for_llm(r)
        assert "### Active Agent" in result
        assert "You are a coder." in result

    def test_returns_skill_results_section(self):
        r = AgentDispatchResult(
            agent_name="a", agent_role="r", department="d",
            success=True,
            enriched_context="SPL analysis results here",
        )
        result = format_agent_context_for_llm(r)
        assert "### Agent Analysis" in result
        assert "SPL analysis results here" in result

    def test_returns_both_sections(self):
        r = AgentDispatchResult(
            agent_name="a", agent_role="r", department="d",
            success=True,
            system_prompt_fragment="personality text",
            enriched_context="skill output text",
        )
        result = format_agent_context_for_llm(r)
        assert "### Active Agent" in result
        assert "personality text" in result
        assert "### Agent Analysis" in result
        assert "skill output text" in result

    def test_returns_none_when_no_fragment_and_no_context(self):
        r = AgentDispatchResult(
            agent_name="a", agent_role="r", department="d",
            success=True,
            system_prompt_fragment="",
            enriched_context="",
        )
        assert format_agent_context_for_llm(r) is None

    def test_failed_with_enriched_context_returns_context(self):
        """Even on failure, if enriched_context is present, return it."""
        r = AgentDispatchResult(
            agent_name="a", agent_role="r", department="d",
            success=False,
            enriched_context="partial results",
        )
        result = format_agent_context_for_llm(r)
        assert result is not None
        assert "partial results" in result

    def test_success_with_only_system_prompt(self):
        r = AgentDispatchResult(
            agent_name="a", agent_role="r", department="d",
            success=True,
            system_prompt_fragment="I am the helper.",
            enriched_context="",
        )
        result = format_agent_context_for_llm(r)
        assert "### Active Agent" in result
        assert "### Agent Analysis" not in result


# ===================================================================
# 10. Singleton get_agent_dispatcher()
# ===================================================================

class TestSingleton:
    def test_returns_same_instance(self):
        import chat_app.agent_dispatcher as mod
        mod._dispatcher = None  # Reset
        a = get_agent_dispatcher()
        b = get_agent_dispatcher()
        assert a is b
        mod._dispatcher = None  # Cleanup

    def test_creates_dispatcher(self):
        import chat_app.agent_dispatcher as mod
        mod._dispatcher = None
        d = get_agent_dispatcher()
        assert isinstance(d, AgentDispatcher)
        mod._dispatcher = None

    def test_reset_creates_new_instance(self):
        import chat_app.agent_dispatcher as mod
        mod._dispatcher = None
        first = get_agent_dispatcher()
        mod._dispatcher = None
        second = get_agent_dispatcher()
        assert first is not second
        mod._dispatcher = None


# ===================================================================
# Additional edge-case / integration-level tests
# ===================================================================

class TestDispatchEdgeCases:
    @pytest.mark.asyncio
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    async def test_dispatch_with_params_passed_through(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        agent = _make_agent(name="ag", skills=["s1"], intents=["i"])
        mock_catalog.get_for_intent.return_value = [agent]

        skill = _make_skill(name="s1", handler_key="custom_handler", intents=["i"])
        cat = MagicMock(spec=SkillCatalog)
        cat.get.return_value = skill
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat

        mock_executor.resolve_handler.return_value = ("internal", "h")
        mock_executor.execute = AsyncMock(return_value=_make_exec_result())

        await dispatcher.dispatch("query", "i", params={"extra_key": "extra_val"})
        call_kwargs = mock_executor.execute.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert params["extra_key"] == "extra_val"
        assert params["user_input"] == "query"
        assert params["intent"] == "i"

    @pytest.mark.asyncio
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    async def test_dispatch_max_skills_limits_execution(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        agent = _make_agent(name="ag", skills=["s1", "s2", "s3"], intents=["i"])
        mock_catalog.get_for_intent.return_value = [agent]

        skills = {
            f"s{i}": _make_skill(name=f"s{i}", handler_key=f"h{i}", intents=["i"])
            for i in range(1, 4)
        }
        cat = MagicMock(spec=SkillCatalog)
        cat.get.side_effect = lambda n: skills.get(n)
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat

        mock_executor.resolve_handler.return_value = ("internal", "h")
        mock_executor.execute = AsyncMock(return_value=_make_exec_result())

        result = await dispatcher.dispatch("query", "i", max_skills=1)
        assert len(result.skills_executed) == 1

    @pytest.mark.asyncio
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    async def test_dispatch_enriched_context_separator(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        """Multiple skill outputs are separated by ---."""
        agent = _make_agent(name="ag", skills=["s1", "s2"], intents=["i"])
        mock_catalog.get_for_intent.return_value = [agent]

        s1 = _make_skill(name="s1", handler_key="h1", intents=["i"])
        s2 = _make_skill(name="s2", handler_key="h2", intents=["i"])
        cat = MagicMock(spec=SkillCatalog)
        cat.get.side_effect = lambda n: {"s1": s1, "s2": s2}.get(n)
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat

        mock_executor.resolve_handler.return_value = ("internal", "h")

        call_count = 0

        async def side_effect(**kwargs):
            nonlocal call_count
            call_count += 1
            return _make_exec_result(output=f"output{call_count}")

        mock_executor.execute = AsyncMock(side_effect=side_effect)

        result = await dispatcher.dispatch("query", "i")
        assert "---" in result.enriched_context
        assert "output1" in result.enriched_context
        assert "output2" in result.enriched_context

    def test_record_dispatch_duration_rounded(self, dispatcher):
        r = AgentDispatchResult(
            agent_name="a", agent_role="r", department="d",
            success=True, duration_ms=12.3456789,
        )
        dispatcher._record_dispatch(r)
        entry = dispatcher.get_dispatch_log()[0]
        assert entry["duration_ms"] == 12.35

    @pytest.mark.asyncio
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    async def test_dispatch_all_skills_fail_sets_success_false(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        agent = _make_agent(name="ag", skills=["s1"], intents=["i"])
        mock_catalog.get_for_intent.return_value = [agent]

        skill = _make_skill(name="s1", handler_key="h1", intents=["i"])
        cat = MagicMock(spec=SkillCatalog)
        cat.get.return_value = skill
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat

        mock_executor.resolve_handler.return_value = ("internal", "h")
        mock_executor.execute = AsyncMock(
            return_value=_make_exec_result(success=False, output="")
        )

        result = await dispatcher.dispatch("query", "i")
        assert result.success is False

    @pytest.mark.asyncio
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    async def test_dispatch_optimize_spl_extracts_query(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        agent = _make_agent(name="ag", skills=["s1"], intents=["i"])
        mock_catalog.get_for_intent.return_value = [agent]

        skill = _make_skill(name="s1", handler_key="optimize_spl", intents=["i"])
        cat = MagicMock(spec=SkillCatalog)
        cat.get.return_value = skill
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat

        mock_executor.resolve_handler.return_value = ("internal", "h")
        mock_executor.execute = AsyncMock(return_value=_make_exec_result())

        spl_input = "optimize: index=firewall | stats count"
        await dispatcher.dispatch(spl_input, "i")

        call_kwargs = mock_executor.execute.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert "query" in params

    @pytest.mark.asyncio
    @patch("chat_app.agent_dispatcher.get_skill_catalog")
    @patch("chat_app.agent_dispatcher_helpers.get_skill_catalog")
    async def test_dispatch_validate_spl_extracts_query(self, mock_get_cat_helpers, mock_get_cat, dispatcher, mock_catalog, mock_executor):
        agent = _make_agent(name="ag", skills=["s1"], intents=["i"])
        mock_catalog.get_for_intent.return_value = [agent]

        skill = _make_skill(name="s1", handler_key="validate_spl", intents=["i"])
        cat = MagicMock(spec=SkillCatalog)
        cat.get.return_value = skill
        mock_get_cat.return_value = cat
        mock_get_cat_helpers.return_value = cat

        mock_executor.resolve_handler.return_value = ("internal", "h")
        mock_executor.execute = AsyncMock(return_value=_make_exec_result())

        spl_input = "```spl\nindex=main | head 10\n```"
        await dispatcher.dispatch(spl_input, "i")

        call_kwargs = mock_executor.execute.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert params["query"] == "index=main | head 10"


class TestExtractSplEdgeCases:
    def test_code_block_preferred_over_inline(self, dispatcher):
        text = "index=main | head 5\n```spl\nindex=firewall | stats count\n```"
        result = dispatcher._extract_spl(text)
        assert result == "index=firewall | stats count"

    def test_inline_without_pipe_but_with_index(self, dispatcher):
        text = "Check index=main sourcetype=access_combined"
        result = dispatcher._extract_spl(text)
        # Should match because 'index=' is present
        assert result is not None
        assert "index=main" in result

    def test_no_match_regular_sentence(self, dispatcher):
        text = "Tell me about Splunk best practices"
        assert dispatcher._extract_spl(text) is None


class TestDispatchResultDefaults:
    def test_dispatch_result_default_success(self):
        r = AgentDispatchResult(agent_name="a", agent_role="r", department="d")
        assert r.success is True

    def test_dispatch_result_default_error_none(self):
        r = AgentDispatchResult(agent_name="a", agent_role="r", department="d")
        assert r.error is None

    def test_dispatch_result_default_duration_zero(self):
        r = AgentDispatchResult(agent_name="a", agent_role="r", department="d")
        assert r.duration_ms == 0.0

    def test_dispatch_result_mutable_lists_independent(self):
        r1 = AgentDispatchResult(agent_name="a", agent_role="r", department="d")
        r2 = AgentDispatchResult(agent_name="b", agent_role="r", department="d")
        r1.skills_executed.append("x")
        assert "x" not in r2.skills_executed
