"""Tests for the configurable multi-agent orchestration framework."""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

@dataclass
class FakeDispatchResult:
    """Mimics AgentDispatchResult for tests."""
    agent_name: str = "test_agent"
    agent_role: str = "Test Role"
    department: str = "engineering"
    enriched_context: str = "Test enriched context output"
    system_prompt_fragment: str = "You are a test agent."
    skills_executed: list = None
    skill_results: list = None
    success: bool = True
    duration_ms: float = 100.0

    def __post_init__(self):
        if self.skills_executed is None:
            self.skills_executed = ["skill_a"]
        if self.skill_results is None:
            self.skill_results = [{"skill": "skill_a", "output": "ok"}]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_name": self.agent_name,
            "agent_role": self.agent_role,
            "enriched_context": self.enriched_context,
            "system_prompt_fragment": self.system_prompt_fragment,
            "success": self.success,
            "duration_ms": self.duration_ms,
        }


@dataclass
class FakeWorkflowResult:
    """Mimics WorkflowResult for tests."""
    combined_output: str = "Workflow output"
    tasks_completed: int = 3
    tasks_total: int = 3
    success: bool = True
    agent_trace: list = None

    def __post_init__(self):
        if self.agent_trace is None:
            self.agent_trace = []


@dataclass
class FakeQualityScore:
    overall: float = 0.8
    relevance: float = 0.8
    accuracy: float = 0.8
    completeness: float = 0.8
    grounding: float = 0.8
    hallucination_risk: float = 0.1
    gaps: list = None
    recommended_action: str = "send"

    def __post_init__(self):
        if self.gaps is None:
            self.gaps = []


@dataclass
class FakeReasoningTrace:
    tools_used: list = None
    total_duration_ms: float = 200.0
    reasoning_steps: list = None
    steps: list = None

    def __post_init__(self):
        if self.tools_used is None:
            self.tools_used = ["tool_a"]
        if self.reasoning_steps is None:
            self.reasoning_steps = []
        if self.steps is None:
            self.steps = [{"action": "test", "result": "ok"}]


class FakeAgent:
    """Mock agent persona for fast-path testing."""
    name = "test_agent"
    role = "Test Role"

    class _Dept:
        value = "engineering"
    department = _Dept()

    def get_system_prompt_fragment(self):
        return "You are a test agent."


class FakeDispatcher:
    """Mock agent dispatcher."""
    async def dispatch(self, user_input, intent, params=None,
                       max_skills=3, preferred_department=None,
                       user_approved=False):
        return FakeDispatchResult()

    def select_agent(self, intent, user_input=None, preferred_department=None, skip_top_n=0):
        return FakeAgent()


class FakeOrchestrator:
    """Mock workflow orchestrator."""
    async def run(self, user_input, intent, template_name=None,
                  user_approved=False):
        return FakeWorkflowResult()


class FakeSettings:
    """Minimal settings for orchestration."""
    default_strategy = "adaptive"
    max_iterations = 3
    max_parallel_agents = 3
    quality_threshold = 0.7
    max_duration_seconds = 30.0
    resource_fallback = True
    critic_enabled = True
    human_approval_intents = []
    strategy_overrides = {}


@pytest.fixture
def fake_settings():
    return FakeSettings()


# ---------------------------------------------------------------------------
# Test OrchestrationResult
# ---------------------------------------------------------------------------

class TestOrchestrationResult:
    def test_default_values(self):
        from chat_app.orchestration_strategies import OrchestrationResult
        r = OrchestrationResult(strategy_used="test")
        assert r.strategy_used == "test"
        assert r.context == ""
        assert r.iterations == 1
        assert r.quality_score == 0.0
        assert r.success is True
        assert r.fallback_used is False
        assert r.fallback_from == ""
        assert r.error is None

    def test_to_dict(self):
        from chat_app.orchestration_strategies import OrchestrationResult
        r = OrchestrationResult(
            strategy_used="parallel",
            context="test context",
            iterations=3,
            quality_score=0.85,
            duration_ms=1200.0,
            success=True,
            fallback_used=True,
            fallback_from="adaptive",
        )
        d = r.to_dict()
        assert d["strategy_used"] == "parallel"
        assert d["iterations"] == 3
        assert d["quality_score"] == 0.85
        assert d["fallback_used"] is True
        assert d["fallback_from"] == "adaptive"
        assert isinstance(d, dict)

    def test_error_result(self):
        from chat_app.orchestration_strategies import OrchestrationResult
        r = OrchestrationResult(
            strategy_used="voting",
            success=False,
            error="Something went wrong",
        )
        assert r.success is False
        assert r.error == "Something went wrong"
        d = r.to_dict()
        assert d["success"] is False


# ---------------------------------------------------------------------------
# Test Strategy Registry
# ---------------------------------------------------------------------------

class TestStrategyRegistry:
    def test_all_strategies_registered(self):
        from chat_app.orchestration_strategies import list_strategies
        strategies = list_strategies()
        names = {s["name"] for s in strategies}
        expected = {
            "single_agent", "parallel", "hierarchical", "iterative",
            "coordinator", "voting", "react", "review_critique",
            "workflow", "swarm", "human_in_loop", "adaptive",
            "democratic", "capitalist", "authoritarian", "parliament",
            "meritocratic", "supervisor",
            # OpenMAIC-inspired strategies
            "two_stage_pipeline", "action_engine", "director_graph", "feedback_loop",
        }
        assert names == expected

    def test_get_strategy_exists(self):
        from chat_app.orchestration_strategies import get_strategy
        s = get_strategy("single_agent")
        assert s is not None
        assert s.name == "single_agent"

    def test_get_strategy_missing(self):
        from chat_app.orchestration_strategies import get_strategy
        assert get_strategy("nonexistent") is None

    def test_register_custom_strategy(self):
        from chat_app.orchestration_strategies import (
            OrchestrationStrategy, OrchestrationResult,
            register_strategy, get_strategy,
        )

        class CustomStrategy(OrchestrationStrategy):
            name = "custom_test"
            resource_weight = "light"
            async def execute(self, *args, **kwargs):
                return OrchestrationResult(strategy_used=self.name)

        register_strategy(CustomStrategy())
        assert get_strategy("custom_test") is not None
        assert get_strategy("custom_test").name == "custom_test"

        # Clean up
        from chat_app.orchestration_strategies import _STRATEGY_REGISTRY
        _STRATEGY_REGISTRY.pop("custom_test", None)

    def test_strategy_resource_weights(self):
        from chat_app.orchestration_strategies import list_strategies
        weights = {s["name"]: s["resource_weight"] for s in list_strategies()}
        assert weights["single_agent"] == "light"
        assert weights["human_in_loop"] == "light"
        assert weights["parallel"] == "medium"
        assert weights["iterative"] == "medium"
        assert weights["react"] == "medium"
        assert weights["adaptive"] == "heavy"
        assert weights["coordinator"] == "heavy"
        assert weights["voting"] == "heavy"


# ---------------------------------------------------------------------------
# Test Fallback Chain
# ---------------------------------------------------------------------------

class TestFallbackChain:
    def test_fallback_chain_defined(self):
        from chat_app.orchestration_strategies import FALLBACK_CHAIN
        assert "adaptive" in FALLBACK_CHAIN
        assert "coordinator" in FALLBACK_CHAIN
        assert "voting" in FALLBACK_CHAIN
        assert "swarm" in FALLBACK_CHAIN

    def test_no_circular_fallbacks(self):
        from chat_app.orchestration_strategies import FALLBACK_CHAIN
        for start, chain in FALLBACK_CHAIN.items():
            visited = {start}
            for fb_name in chain:
                assert fb_name not in visited, f"Circular fallback: {start} -> {fb_name}"
                visited.add(fb_name)

    def test_fallback_targets_exist(self):
        from chat_app.orchestration_strategies import FALLBACK_CHAIN, get_strategy
        for start, chain in FALLBACK_CHAIN.items():
            for fb_name in chain:
                assert get_strategy(fb_name) is not None, f"Missing strategy: {fb_name}"

    def test_heavy_strategies_have_fallback(self):
        from chat_app.orchestration_strategies import FALLBACK_CHAIN, get_strategy
        from chat_app.orchestration_strategies import _STRATEGY_REGISTRY
        for name, s in _STRATEGY_REGISTRY.items():
            if s.resource_weight == "heavy":
                assert name in FALLBACK_CHAIN, f"Heavy strategy '{name}' needs fallback"


# ---------------------------------------------------------------------------
# Test SingleAgentStrategy
# ---------------------------------------------------------------------------

class TestSingleAgent:
    @pytest.mark.asyncio
    async def test_success(self, fake_settings):
        from chat_app.orchestration_strategies import SingleAgentStrategy
        strategy = SingleAgentStrategy()

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.agent_dispatcher.format_agent_context_for_llm",
                    return_value="formatted context"):
            mock_gad.return_value = FakeDispatcher()
            result = await strategy.execute(
                "test query", "general_qa", None, None, fake_settings,
            )
        assert result.strategy_used == "single_agent"
        assert result.success is True
        assert result.context != ""

    @pytest.mark.asyncio
    async def test_failure_returns_error(self, fake_settings):
        from chat_app.orchestration_strategies import SingleAgentStrategy
        strategy = SingleAgentStrategy()

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher",
                    side_effect=RuntimeError("dispatch broken")):
            result = await strategy.execute(
                "test", "general_qa", None, None, fake_settings,
            )
        assert result.success is False
        assert "dispatch broken" in result.error


# ---------------------------------------------------------------------------
# Test ParallelStrategy
# ---------------------------------------------------------------------------

class TestParallel:
    @pytest.mark.asyncio
    async def test_parallel_dispatch(self, fake_settings):
        from chat_app.orchestration_strategies import ParallelStrategy
        strategy = ParallelStrategy()

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.agent_catalog.get_agent_catalog") as mock_cat:
            mock_gad.return_value = FakeDispatcher()
            mock_catalog = MagicMock()
            mock_catalog.match_agents.return_value = [
                MagicMock(agent_id="a1", name="Agent1"),
                MagicMock(agent_id="a2", name="Agent2"),
            ]
            mock_cat.return_value = mock_catalog
            result = await strategy.execute(
                "test", "general_qa", None, None, fake_settings,
            )
        assert result.strategy_used == "parallel"
        assert result.success is True


# ---------------------------------------------------------------------------
# Test IterativeStrategy
# ---------------------------------------------------------------------------

class TestIterative:
    @pytest.mark.asyncio
    async def test_quality_loop(self, fake_settings):
        from chat_app.orchestration_strategies import IterativeStrategy
        strategy = IterativeStrategy()
        fake_settings.quality_threshold = 0.5

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.self_evaluator.evaluate_response_quality") as mock_eval:
            mock_gad.return_value = FakeDispatcher()
            mock_eval.return_value = FakeQualityScore(overall=0.9)
            result = await strategy.execute(
                "test", "general_qa", None, None, fake_settings,
            )
        assert result.strategy_used == "iterative"
        assert result.success is True
        assert result.quality_score >= 0.5

    @pytest.mark.asyncio
    async def test_max_iterations_respected(self, fake_settings):
        from chat_app.orchestration_strategies import IterativeStrategy
        strategy = IterativeStrategy()
        fake_settings.max_iterations = 2
        fake_settings.quality_threshold = 0.99

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.self_evaluator.evaluate_response_quality") as mock_eval:
            mock_gad.return_value = FakeDispatcher()
            mock_eval.return_value = FakeQualityScore(overall=0.3)
            result = await strategy.execute(
                "test", "general_qa", None, None, fake_settings,
            )
        assert result.iterations <= 2


# ---------------------------------------------------------------------------
# Test VotingStrategy
# ---------------------------------------------------------------------------

class TestVoting:
    @pytest.mark.asyncio
    async def test_voting_picks_best(self, fake_settings):
        from chat_app.orchestration_strategies import VotingStrategy
        strategy = VotingStrategy()

        call_count = 0

        async def varying_dispatch(user_input, intent, **kwargs):
            nonlocal call_count
            call_count += 1
            return FakeDispatchResult(
                enriched_context=f"Output {call_count}",
                agent_name=f"agent_{call_count}",
            )

        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = varying_dispatch

        quality_scores = [0.5, 0.9, 0.6]
        eval_calls = iter(quality_scores)

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher",
                    return_value=mock_dispatcher), \
             patch("chat_app.self_evaluator.evaluate_response_quality") as mock_eval:
            mock_eval.side_effect = lambda **kwargs: FakeQualityScore(
                overall=next(eval_calls, 0.5)
            )
            result = await strategy.execute(
                "test", "general_qa", None, None, fake_settings,
            )
        assert result.strategy_used == "voting"
        assert result.success is True


# ---------------------------------------------------------------------------
# Test ReviewCritiqueStrategy
# ---------------------------------------------------------------------------

class TestReviewCritique:
    @pytest.mark.asyncio
    async def test_worker_and_critic(self, fake_settings):
        from chat_app.orchestration_strategies import ReviewCritiqueStrategy
        strategy = ReviewCritiqueStrategy()

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.agent_catalog.Department") as mock_dept:
            mock_gad.return_value = FakeDispatcher()
            mock_dept.KNOWLEDGE = "knowledge"
            result = await strategy.execute(
                "test", "general_qa", None, None, fake_settings,
            )
        assert result.strategy_used == "review_critique"
        assert result.success is True
        assert result.iterations == 2


# ---------------------------------------------------------------------------
# Test WorkflowStrategy
# ---------------------------------------------------------------------------

class TestWorkflow:
    def test_is_applicable_with_workflow(self):
        from chat_app.orchestration_strategies import WorkflowStrategy
        strategy = WorkflowStrategy()
        with patch("chat_app.workflow_orchestrator.detect_workflow",
                    return_value="compare_template"):
            assert strategy.is_applicable("compare", "compare X vs Y") is True

    def test_is_applicable_without_workflow(self):
        from chat_app.orchestration_strategies import WorkflowStrategy
        strategy = WorkflowStrategy()
        with patch("chat_app.workflow_orchestrator.detect_workflow",
                    return_value=None):
            assert strategy.is_applicable("general_qa", "what is Splunk?") is False

    @pytest.mark.asyncio
    async def test_execute(self, fake_settings):
        from chat_app.orchestration_strategies import WorkflowStrategy
        strategy = WorkflowStrategy()

        with patch("chat_app.workflow_orchestrator.get_workflow_orchestrator") as mock_wfo:
            mock_wfo.return_value = FakeOrchestrator()
            result = await strategy.execute(
                "compare A vs B", "compare", None, None, fake_settings,
            )
        assert result.strategy_used == "workflow"
        assert result.success is True
        assert "Workflow" in result.context


# ---------------------------------------------------------------------------
# Test ReactStrategy
# ---------------------------------------------------------------------------

class TestReact:
    @pytest.mark.asyncio
    async def test_react_wraps_loop(self, fake_settings):
        from chat_app.orchestration_strategies import ReactStrategy
        strategy = ReactStrategy()

        with patch("chat_app.react_loop.execute_react_loop",
                    new_callable=AsyncMock) as mock_react, \
             patch("chat_app.react_loop.format_tool_context_for_llm",
                    return_value="Tool context output"):
            mock_react.return_value = FakeReasoningTrace()
            result = await strategy.execute(
                "test", "troubleshooting", None, None, fake_settings,
            )
        assert result.strategy_used == "react"
        assert result.success is True


# ---------------------------------------------------------------------------
# Test AdaptiveStrategy
# ---------------------------------------------------------------------------

class TestAdaptive:
    @pytest.mark.asyncio
    async def test_adaptive_full_pipeline(self, fake_settings):
        from chat_app.orchestration_strategies import AdaptiveStrategy
        strategy = AdaptiveStrategy()

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.agent_catalog.Department") as mock_dept, \
             patch("chat_app.self_evaluator.evaluate_response_quality") as mock_eval, \
             patch("chat_app.resource_manager.can_run_heavy_task",
                    return_value=(True, "ok")):
            mock_gad.return_value = FakeDispatcher()
            mock_dept.KNOWLEDGE = "knowledge"
            mock_eval.return_value = FakeQualityScore(overall=0.9)
            result = await strategy.execute(
                "test", "general_qa", None, None, fake_settings,
            )
        assert result.strategy_used == "adaptive"
        assert result.success is True

    @pytest.mark.asyncio
    async def test_adaptive_resource_gating(self, fake_settings):
        from chat_app.orchestration_strategies import AdaptiveStrategy
        strategy = AdaptiveStrategy()
        fake_settings.resource_fallback = True

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.agent_catalog.Department") as mock_dept, \
             patch("chat_app.self_evaluator.evaluate_response_quality") as mock_eval, \
             patch("chat_app.resource_manager.can_run_heavy_task") as mock_res:
            mock_gad.return_value = FakeDispatcher()
            mock_dept.KNOWLEDGE = "knowledge"
            mock_eval.return_value = FakeQualityScore(overall=0.3)
            mock_res.return_value = (False, "CPU too high")
            result = await strategy.execute(
                "test", "general_qa", None, None, fake_settings,
            )
        assert result.success is True
        assert result.iterations <= 2


# ---------------------------------------------------------------------------
# Test execute_orchestration
# ---------------------------------------------------------------------------

class TestExecuteOrchestration:
    @pytest.mark.asyncio
    async def test_default_strategy_used(self):
        from chat_app.orchestration_strategies import execute_orchestration

        fake_orch = FakeSettings()
        fake_orch.default_strategy = "single_agent"

        mock_settings = MagicMock()
        mock_settings.orchestration = fake_orch

        with patch("chat_app.settings.get_settings",
                    return_value=mock_settings), \
             patch("chat_app.resource_manager.can_run_heavy_task",
                    return_value=(True, "ok")), \
             patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.agent_dispatcher.format_agent_context_for_llm",
                    return_value="context"):
            mock_gad.return_value = FakeDispatcher()
            result = await execute_orchestration(
                "test", "general_qa", None, None,
            )
        assert result.strategy_used == "single_agent"

    @pytest.mark.asyncio
    async def test_strategy_override_by_intent(self):
        from chat_app.orchestration_strategies import execute_orchestration

        fake_orch = FakeSettings()
        fake_orch.default_strategy = "adaptive"
        fake_orch.strategy_overrides = {"spl_generation": "single_agent"}

        mock_settings = MagicMock()
        mock_settings.orchestration = fake_orch

        with patch("chat_app.settings.get_settings",
                    return_value=mock_settings), \
             patch("chat_app.resource_manager.can_run_heavy_task",
                    return_value=(True, "ok")), \
             patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.agent_dispatcher.format_agent_context_for_llm",
                    return_value="ctx"):
            mock_gad.return_value = FakeDispatcher()
            result = await execute_orchestration(
                "generate spl", "spl_generation", None, None,
            )
        assert result.strategy_used == "single_agent"

    @pytest.mark.asyncio
    async def test_human_approval_intent_forces_human_in_loop(self):
        from chat_app.orchestration_strategies import execute_orchestration

        fake_orch = FakeSettings()
        fake_orch.default_strategy = "adaptive"
        fake_orch.human_approval_intents = ["dangerous_action"]

        mock_settings = MagicMock()
        mock_settings.orchestration = fake_orch

        with patch("chat_app.settings.get_settings",
                    return_value=mock_settings), \
             patch("chat_app.resource_manager.can_run_heavy_task",
                    return_value=(True, "ok")), \
             patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.agent_dispatcher.format_agent_context_for_llm",
                    return_value="ctx"):
            mock_gad.return_value = FakeDispatcher()
            result = await execute_orchestration(
                "do dangerous thing", "dangerous_action", None, None,
            )
        assert result.strategy_used == "human_in_loop"

    @pytest.mark.asyncio
    async def test_resource_fallback_for_heavy(self):
        from chat_app.orchestration_strategies import execute_orchestration

        fake_orch = FakeSettings()
        fake_orch.default_strategy = "adaptive"
        fake_orch.resource_fallback = True

        mock_settings = MagicMock()
        mock_settings.orchestration = fake_orch

        with patch("chat_app.settings.get_settings",
                    return_value=mock_settings), \
             patch("chat_app.resource_manager.can_run_heavy_task",
                    return_value=(False, "CPU high")), \
             patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.agent_dispatcher.format_agent_context_for_llm",
                    return_value="ctx"):
            mock_gad.return_value = FakeDispatcher()
            result = await execute_orchestration(
                "test", "general_qa", None, None,
            )
        assert result.fallback_used is True
        assert result.fallback_from == "adaptive"

    @pytest.mark.asyncio
    async def test_unknown_strategy_falls_back(self):
        from chat_app.orchestration_strategies import execute_orchestration

        fake_orch = FakeSettings()
        fake_orch.default_strategy = "nonexistent_strategy"
        fake_orch.resource_fallback = False

        mock_settings = MagicMock()
        mock_settings.orchestration = fake_orch

        with patch("chat_app.settings.get_settings",
                    return_value=mock_settings), \
             patch("chat_app.resource_manager.can_run_heavy_task",
                    return_value=(True, "ok")), \
             patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.agent_dispatcher.format_agent_context_for_llm",
                    return_value="ctx"):
            mock_gad.return_value = FakeDispatcher()
            result = await execute_orchestration(
                "test", "general_qa", None, None,
            )
        assert result.strategy_used == "single_agent"

    @pytest.mark.asyncio
    async def test_timeout_handled(self):
        from chat_app.orchestration_strategies import execute_orchestration

        fake_orch = FakeSettings()
        fake_orch.default_strategy = "single_agent"
        fake_orch.max_duration_seconds = 0.01
        fake_orch.resource_fallback = False

        mock_settings = MagicMock()
        mock_settings.orchestration = fake_orch
        mock_settings.fast_mode = False  # disable fast_mode so dispatch() is called

        async def slow_dispatch(*args, **kwargs):
            await asyncio.sleep(5)
            return FakeDispatchResult()

        slow_dispatcher = MagicMock()
        slow_dispatcher.dispatch = slow_dispatch

        with patch("chat_app.settings.get_settings",
                    return_value=mock_settings), \
             patch("chat_app.resource_manager.can_run_heavy_task",
                    return_value=(True, "ok")), \
             patch("chat_app.agent_dispatcher.get_agent_dispatcher",
                    return_value=slow_dispatcher), \
             patch("chat_app.agent_dispatcher.format_agent_context_for_llm",
                    return_value="ctx"):
            result = await execute_orchestration(
                "test", "general_qa", None, None,
            )
        assert result.success is False
        assert "Timed out" in result.error


# ---------------------------------------------------------------------------
# Test Execution Log & Summary
# ---------------------------------------------------------------------------

class TestExecutionLog:
    def test_get_execution_log_empty(self):
        from chat_app.orchestration_strategies import get_execution_log
        log = get_execution_log(10)
        assert isinstance(log, list)

    def test_get_orchestration_summary_empty(self):
        from chat_app.orchestration_strategies import (
            get_orchestration_summary, _execution_log,
        )
        saved = _execution_log.copy()
        _execution_log.clear()
        summary = get_orchestration_summary()
        assert summary["total"] == 0
        _execution_log.extend(saved)

    def test_summary_with_data(self):
        from chat_app.orchestration_strategies import (
            get_orchestration_summary, _execution_log,
        )
        saved = _execution_log.copy()
        _execution_log.clear()
        _execution_log.extend([
            {"strategy_used": "single_agent", "success": True,
             "fallback_used": False, "quality_score": 0.8, "duration_ms": 100},
            {"strategy_used": "adaptive", "success": True,
             "fallback_used": True, "quality_score": 0.6, "duration_ms": 200},
            {"strategy_used": "single_agent", "success": False,
             "fallback_used": False, "quality_score": 0.0, "duration_ms": 50},
        ])
        summary = get_orchestration_summary()
        assert summary["total"] == 3
        assert summary["by_strategy"]["single_agent"] == 2
        assert summary["by_strategy"]["adaptive"] == 1
        assert 0.0 < summary["success_rate"] < 1.0
        assert summary["fallback_rate"] > 0
        _execution_log.clear()
        _execution_log.extend(saved)


# ---------------------------------------------------------------------------
# Test OrchestrationSettings validation
# ---------------------------------------------------------------------------

class TestOrchestrationSettings:
    def test_default_values(self):
        from chat_app.settings import OrchestrationSettings
        s = OrchestrationSettings()
        assert s.default_strategy == "adaptive"
        assert s.max_iterations == 3
        assert s.quality_threshold == 0.7
        assert s.resource_fallback is True

    def test_valid_strategy(self):
        from chat_app.settings import OrchestrationSettings
        s = OrchestrationSettings(default_strategy="single_agent")
        assert s.default_strategy == "single_agent"

    def test_invalid_strategy_rejected(self):
        from chat_app.settings import OrchestrationSettings
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            OrchestrationSettings(default_strategy="not_a_strategy")

    def test_quality_threshold_bounds(self):
        from chat_app.settings import OrchestrationSettings
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            OrchestrationSettings(quality_threshold=1.5)
        with pytest.raises(ValidationError):
            OrchestrationSettings(quality_threshold=-0.1)

    def test_all_strategies_valid(self):
        from chat_app.settings import OrchestrationSettings
        for name in [
            "single_agent", "parallel", "hierarchical", "iterative",
            "coordinator", "voting", "react", "review_critique",
            "workflow", "swarm", "human_in_loop", "adaptive",
        ]:
            s = OrchestrationSettings(default_strategy=name)
            assert s.default_strategy == name


# ---------------------------------------------------------------------------
# Test SwarmStrategy handoff detection
# ---------------------------------------------------------------------------

class TestSwarm:
    def test_handoff_detection(self):
        from chat_app.orchestration_strategies import SwarmStrategy
        strategy = SwarmStrategy()
        assert strategy._detect_handoff(
            "We need to optimize the search query", "general_qa"
        ) == "spl_optimization"
        assert strategy._detect_handoff("", "general_qa") is None
        assert strategy._detect_handoff("no signals here", "general_qa") is None

    @pytest.mark.asyncio
    async def test_swarm_execute(self, fake_settings):
        from chat_app.orchestration_strategies import SwarmStrategy
        strategy = SwarmStrategy()
        fake_settings.max_iterations = 2

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad:
            mock_gad.return_value = FakeDispatcher()
            result = await strategy.execute(
                "test", "general_qa", None, None, fake_settings,
            )
        assert result.strategy_used == "swarm"
        assert result.success is True


# ---------------------------------------------------------------------------
# Test HumanInLoopStrategy (Chainlit unavailable fallback)
# ---------------------------------------------------------------------------

class TestHumanInLoop:
    @pytest.mark.asyncio
    async def test_falls_back_on_import_error(self, fake_settings):
        """When chainlit is unavailable (ImportError), falls back to single agent."""
        from chat_app.orchestration_strategies import HumanInLoopStrategy
        strategy = HumanInLoopStrategy()

        import sys
        saved = sys.modules.pop("chainlit", None)
        try:
            with patch.dict("sys.modules", {"chainlit": None}), \
                 patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
                 patch("chat_app.agent_dispatcher.format_agent_context_for_llm",
                        return_value="ctx"):
                mock_gad.return_value = FakeDispatcher()
                result = await strategy.execute(
                    "test", "general_qa", None, None, fake_settings,
                )
            assert result.strategy_used == "human_in_loop"
            assert result.success is True
        finally:
            if saved is not None:
                sys.modules["chainlit"] = saved

    @pytest.mark.asyncio
    async def test_denies_on_runtime_error(self, fake_settings):
        """Non-ImportError should deny for safety."""
        from chat_app.orchestration_strategies import HumanInLoopStrategy
        strategy = HumanInLoopStrategy()

        import sys
        mock_cl = MagicMock()
        mock_cl.AskActionMessage.return_value.send = AsyncMock(
            side_effect=RuntimeError("connection lost")
        )
        saved = sys.modules.get("chainlit")
        sys.modules["chainlit"] = mock_cl
        try:
            result = await strategy.execute(
                "test", "general_qa", None, None, fake_settings,
            )
            assert result.success is False
            assert "Approval error" in result.error
        finally:
            if saved is not None:
                sys.modules["chainlit"] = saved


# ---------------------------------------------------------------------------
# Edge case tests from review
# ---------------------------------------------------------------------------

class TestOrchResultToDict:
    def test_error_included_in_to_dict(self):
        from chat_app.orchestration_strategies import OrchestrationResult
        r = OrchestrationResult(
            strategy_used="test", success=False, error="Something broke"
        )
        d = r.to_dict()
        assert d["error"] == "Something broke"
        assert d["success"] is False

    def test_error_omitted_when_none(self):
        from chat_app.orchestration_strategies import OrchestrationResult
        r = OrchestrationResult(strategy_used="test", success=True)
        d = r.to_dict()
        assert "error" not in d

    def test_to_dict_all_fields(self):
        from chat_app.orchestration_strategies import OrchestrationResult
        r = OrchestrationResult(
            strategy_used="adaptive", quality_score=0.85,
            duration_ms=123.456, iterations=3, success=True,
            fallback_used=True, fallback_from="coordinator",
            agent_trace=[{"a": 1}, {"b": 2}],
        )
        d = r.to_dict()
        assert d["trace_steps"] == 2
        assert d["quality_score"] == 0.85
        assert d["fallback_from"] == "coordinator"


class TestDequeLog:
    def test_execution_log_bounded(self):
        from chat_app.orchestration_strategies import (
            _execution_log, _MAX_EXEC_LOG,
        )
        saved = list(_execution_log)
        _execution_log.clear()
        # Fill beyond max
        for i in range(_MAX_EXEC_LOG + 50):
            _execution_log.append({"i": i})
        assert len(_execution_log) == _MAX_EXEC_LOG
        # Oldest entries should be gone
        first = list(_execution_log)[0]
        assert first["i"] == 50
        _execution_log.clear()
        _execution_log.extend(saved)

    def test_get_execution_log_limit(self):
        from chat_app.orchestration_strategies import (
            get_execution_log, _execution_log,
        )
        saved = list(_execution_log)
        _execution_log.clear()
        for i in range(20):
            _execution_log.append({"i": i})
        log = get_execution_log(5)
        assert len(log) == 5
        assert log[-1]["i"] == 19
        _execution_log.clear()
        _execution_log.extend(saved)


class TestParallelDiversity:
    @pytest.mark.asyncio
    async def test_parallel_uses_different_departments(self, fake_settings):
        from chat_app.orchestration_strategies import ParallelStrategy

        strategy = ParallelStrategy()
        dispatched_depts = []

        async def tracking_dispatch(*args, **kwargs):
            dept = kwargs.get("preferred_department")
            dispatched_depts.append(dept)
            return FakeDispatchResult(agent_role=f"Agent-{dept}")

        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = tracking_dispatch

        # Create fake agents with different departments
        agent1 = MagicMock()
        agent1.department = "engineering"
        agent2 = MagicMock()
        agent2.department = "operations"
        agent3 = MagicMock()
        agent3.department = "knowledge"

        mock_catalog = MagicMock()
        mock_catalog.get_for_intent.return_value = [agent1, agent2, agent3]

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher",
                    return_value=mock_dispatcher), \
             patch("chat_app.agent_catalog.get_agent_catalog",
                    return_value=mock_catalog):
            result = await strategy.execute(
                "test", "general_qa", None, None, fake_settings,
            )
        assert result.success is True
        # Should have dispatched to 3 different departments
        assert len(dispatched_depts) == 3
        assert len(set(dispatched_depts)) == 3


class TestLazyRegistration:
    def test_ensure_registered_idempotent(self):
        from chat_app.orchestration_strategies import (
            _ensure_registered, _STRATEGY_REGISTRY,
        )
        _ensure_registered()
        count1 = len(_STRATEGY_REGISTRY)
        _ensure_registered()  # Second call should be no-op
        count2 = len(_STRATEGY_REGISTRY)
        assert count1 == count2 >= 17  # 17 base + supervisor

    def test_all_strategies_accessible_after_lazy_init(self):
        from chat_app.orchestration_strategies import get_strategy
        names = [
            "single_agent", "parallel", "hierarchical", "iterative",
            "coordinator", "voting", "react", "review_critique",
            "workflow", "swarm", "human_in_loop", "adaptive",
        ]
        for name in names:
            s = get_strategy(name)
            assert s is not None, f"Strategy '{name}' not found"
            assert s.name == name


class TestSingleAgentFallbackSafety:
    @pytest.mark.asyncio
    async def test_unknown_strategy_with_missing_registry(self):
        """Even with corrupted registry, execute_orchestration should not crash."""
        from chat_app.orchestration_strategies import execute_orchestration

        fake_orch = FakeSettings()
        fake_orch.default_strategy = "totally_bogus_123"
        fake_orch.resource_fallback = False

        mock_settings = MagicMock()
        mock_settings.orchestration = fake_orch

        with patch("chat_app.settings.get_settings",
                    return_value=mock_settings), \
             patch("chat_app.resource_manager.can_run_heavy_task",
                    return_value=(True, "ok")), \
             patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.agent_dispatcher.format_agent_context_for_llm",
                    return_value="ctx"):
            mock_gad.return_value = FakeDispatcher()
            result = await execute_orchestration(
                "test", "general_qa", None, None,
            )
        # Should fall back to single_agent, not crash
        assert result.strategy_used == "single_agent"
        assert result.success is True


# ---------------------------------------------------------------------------
# Test HierarchicalStrategy
# ---------------------------------------------------------------------------

class TestHierarchical:
    @pytest.mark.asyncio
    async def test_hierarchical_decompose_and_execute(self, fake_settings):
        from chat_app.orchestration_strategies import HierarchicalStrategy
        strategy = HierarchicalStrategy()

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.agent_dispatcher.format_agent_context_for_llm",
                    return_value="formatted"):
            mock_gad.return_value = FakeDispatcher()
            result = await strategy.execute(
                "test query", "general_qa", None, None, fake_settings,
            )
        assert result.strategy_used == "hierarchical"
        assert result.success is True
        assert result.context != ""
        assert len(result.agent_trace) >= 1

    @pytest.mark.asyncio
    async def test_hierarchical_llm_decompose(self, fake_settings):
        """When context has a chain, use LLM for decomposition."""
        from chat_app.orchestration_strategies import HierarchicalStrategy
        strategy = HierarchicalStrategy()

        fake_chain = AsyncMock()
        fake_chain.ainvoke.return_value = "- Check logs\n- Analyze errors\n- Fix issues"

        fake_context = MagicMock()
        fake_context.chain = fake_chain

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.agent_dispatcher.format_agent_context_for_llm",
                    return_value="formatted"):
            mock_gad.return_value = FakeDispatcher()
            result = await strategy.execute(
                "troubleshoot slow search", "troubleshooting",
                None, fake_context, fake_settings,
            )
        assert result.success is True
        # LLM decomposed into 3 subtasks
        assert len(result.agent_trace) == 3

    @pytest.mark.asyncio
    async def test_hierarchical_dispatcher_failure(self, fake_settings):
        from chat_app.orchestration_strategies import HierarchicalStrategy
        strategy = HierarchicalStrategy()

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher",
                    side_effect=RuntimeError("dispatcher down")):
            result = await strategy.execute(
                "test", "general_qa", None, None, fake_settings,
            )
        assert result.success is False
        assert "dispatcher down" in result.error


# ---------------------------------------------------------------------------
# Test CoordinatorStrategy
# ---------------------------------------------------------------------------

class TestCoordinator:
    @pytest.mark.asyncio
    async def test_coordinator_synthesizes(self, fake_settings):
        from chat_app.orchestration_strategies import CoordinatorStrategy
        strategy = CoordinatorStrategy()

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.agent_dispatcher.format_agent_context_for_llm",
                    return_value="formatted"):
            mock_gad.return_value = FakeDispatcher()
            result = await strategy.execute(
                "test query", "general_qa", None, None, fake_settings,
            )
        assert result.strategy_used == "coordinator"
        assert result.success is True
        assert result.context != ""

    @pytest.mark.asyncio
    async def test_coordinator_failure(self, fake_settings):
        from chat_app.orchestration_strategies import CoordinatorStrategy
        strategy = CoordinatorStrategy()

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher",
                    side_effect=RuntimeError("coord failed")):
            result = await strategy.execute(
                "test", "general_qa", None, None, fake_settings,
            )
        assert result.success is False


# ---------------------------------------------------------------------------
# Test medium-weight resource fallback in execute_orchestration
# ---------------------------------------------------------------------------

class TestMediumWeightFallback:
    @pytest.mark.asyncio
    async def test_medium_strategy_fallback_on_high_resources(self):
        from chat_app.orchestration_strategies import execute_orchestration

        fake_orch = FakeSettings()
        fake_orch.default_strategy = "iterative"  # medium weight
        fake_orch.resource_fallback = True

        mock_settings = MagicMock()
        mock_settings.orchestration = fake_orch

        # First call (heavy check) returns True, second call (medium check) returns False
        call_count = 0

        def selective_resource_check(max_cpu=80.0, max_memory=85.0):
            nonlocal call_count
            call_count += 1
            if max_cpu == 90.0:  # medium-weight check
                return (False, "Memory high")
            return (True, "ok")

        with patch("chat_app.settings.get_settings",
                    return_value=mock_settings), \
             patch("chat_app.resource_manager.can_run_heavy_task",
                    side_effect=selective_resource_check), \
             patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.agent_dispatcher.format_agent_context_for_llm",
                    return_value="ctx"):
            mock_gad.return_value = FakeDispatcher()
            result = await execute_orchestration(
                "test", "general_qa", None, None,
            )
        assert result.fallback_used is True
        assert result.strategy_used == "single_agent"


# (HumanInLoop deny-on-error tests are in TestHumanInLoop above)


# ---------------------------------------------------------------------------
# Test execute_orchestration with non-timeout exception
# ---------------------------------------------------------------------------

class TestStrategyRuntimeError:
    @pytest.mark.asyncio
    async def test_strategy_execute_raises_runtime_error(self):
        from chat_app.orchestration_strategies import execute_orchestration

        fake_orch = FakeSettings()
        fake_orch.default_strategy = "single_agent"
        fake_orch.resource_fallback = False

        mock_settings = MagicMock()
        mock_settings.orchestration = fake_orch
        mock_settings.fast_mode = False  # disable fast_mode so dispatch() is called

        async def crashing_dispatch(*args, **kwargs):
            raise ValueError("unexpected internal error")

        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = crashing_dispatch

        with patch("chat_app.settings.get_settings",
                    return_value=mock_settings), \
             patch("chat_app.resource_manager.can_run_heavy_task",
                    return_value=(True, "ok")), \
             patch("chat_app.agent_dispatcher.get_agent_dispatcher",
                    return_value=mock_dispatcher):
            result = await execute_orchestration(
                "test", "general_qa", None, None,
            )
        assert result.success is False
        assert "unexpected internal error" in result.error


# ---------------------------------------------------------------------------
# Test IterativeStrategy uses user_input as context (not self-referential)
# ---------------------------------------------------------------------------

class TestIterativeContextNotSelfReferential:
    @pytest.mark.asyncio
    async def test_eval_context_is_not_response(self, fake_settings):
        """The context arg to evaluate_response_quality should NOT be the response."""
        from chat_app.orchestration_strategies import IterativeStrategy
        strategy = IterativeStrategy()
        fake_settings.quality_threshold = 0.5

        eval_calls = []

        def capture_eval(**kwargs):
            eval_calls.append(kwargs)
            return FakeQualityScore(overall=0.9)

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.self_evaluator.evaluate_response_quality",
                    side_effect=capture_eval):
            mock_gad.return_value = FakeDispatcher()
            await strategy.execute(
                "my test query", "general_qa", None, None, fake_settings,
            )

        assert len(eval_calls) >= 1
        call = eval_calls[0]
        # context should be user_input, NOT the response
        assert call["context"] == "my test query"
        assert call["context"] != call["response"]


# ---------------------------------------------------------------------------
# Test thread safety of lazy registration
# ---------------------------------------------------------------------------

class TestRegistryThreadSafety:
    def test_concurrent_ensure_registered(self):
        """Multiple threads calling _ensure_registered should not corrupt registry."""
        import threading
        from chat_app.orchestration_strategies import (
            _ensure_registered, _STRATEGY_REGISTRY,
        )
        errors = []

        def worker():
            try:
                _ensure_registered()
                assert len(_STRATEGY_REGISTRY) >= 17
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors, f"Thread safety errors: {errors}"
        assert len(_STRATEGY_REGISTRY) >= 17  # 17 base + supervisor


# ---------------------------------------------------------------------------
# Test SwarmStrategy cycle detection
# ---------------------------------------------------------------------------

class TestSwarmCycleDetection:
    @pytest.mark.asyncio
    async def test_swarm_stops_on_revisited_intent(self, fake_settings):
        from chat_app.orchestration_strategies import SwarmStrategy
        strategy = SwarmStrategy()
        fake_settings.max_iterations = 10

        call_count = 0

        async def looping_dispatch(user_input, intent, **kwargs):
            nonlocal call_count
            call_count += 1
            # Always suggest going to spl_optimization
            return FakeDispatchResult(
                enriched_context="We need to optimize the search query"
            )

        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = looping_dispatch

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher",
                    return_value=mock_dispatcher):
            result = await strategy.execute(
                "test", "general_qa", None, None, fake_settings,
            )
        assert result.success is True
        # Should stop early due to cycle, not exhaust all 10 iterations
        assert call_count <= 5


# ---------------------------------------------------------------------------
# Test VotingStrategy all-fail scenario
# ---------------------------------------------------------------------------

class TestVotingAllFail:
    @pytest.mark.asyncio
    async def test_all_voters_fail(self, fake_settings):
        from chat_app.orchestration_strategies import VotingStrategy
        strategy = VotingStrategy()

        async def failing_dispatch(*args, **kwargs):
            return FakeDispatchResult(
                enriched_context="", success=False,
            )

        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = failing_dispatch

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher",
                    return_value=mock_dispatcher), \
             patch("chat_app.self_evaluator.evaluate_response_quality") as mock_eval:
            mock_eval.return_value = FakeQualityScore(overall=0.0)
            result = await strategy.execute(
                "test", "general_qa", None, None, fake_settings,
            )
        assert result.success is False
        assert "All voters failed" in (result.error or "")
