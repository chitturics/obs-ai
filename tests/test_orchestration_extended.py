"""Extended tests for orchestration strategies — fallback, quality, suggestion, timeout."""
import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixtures and helpers (mirroring test_orchestration_strategies.py)
# ---------------------------------------------------------------------------

@dataclass
class FakeDispatchResult:
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
            "enriched_context": self.enriched_context,
            "success": self.success,
            "duration_ms": self.duration_ms,
        }


class FakeAgent:
    name = "test_agent"
    role = "Test Role"

    class _Dept:
        value = "engineering"
    department = _Dept()

    def get_system_prompt_fragment(self):
        return "You are a test agent."


class FakeDispatcher:
    async def dispatch(self, user_input, intent, params=None,
                       max_skills=3, preferred_department=None,
                       user_approved=False):
        return FakeDispatchResult()

    def select_agent(self, intent, user_input=None, preferred_department=None, skip_top_n=0):
        return FakeAgent()


class FakeSettings:
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
# Test fallback chain activation when resource constrained
# ---------------------------------------------------------------------------

class TestFallbackChainActivation:
    """Verify fallback chain fires when resources are insufficient."""

    @pytest.mark.asyncio
    async def test_heavy_strategy_falls_back_when_cpu_high(self, fake_settings):
        """Heavy strategies should fall back to lighter ones under resource pressure."""
        from chat_app.orchestration_strategies import execute_orchestration, OrchestrationResult

        fake_settings.default_strategy = "adaptive"
        fake_settings.resource_fallback = True

        with patch("chat_app.settings.get_settings") as mock_gs, \
             patch("chat_app.resource_manager.can_run_heavy_task",
                   return_value=(False, "CPU 95%")), \
             patch("chat_app.orchestration_strategies._suggest_strategy",
                   return_value="adaptive"), \
             patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.agent_dispatcher.format_agent_context_for_llm",
                    return_value="context"):
            mock_gs.return_value = MagicMock(orchestration=fake_settings)
            mock_gad.return_value = FakeDispatcher()

            result = await execute_orchestration(
                "test query", "general_qa", None, None, False
            )
        # Should have used a fallback, not the heavy adaptive strategy
        assert result.strategy_used != "adaptive" or result.fallback_used is True

    @pytest.mark.asyncio
    async def test_medium_strategy_falls_back_at_extreme_load(self, fake_settings):
        """Medium strategies fall back to single_agent at extreme CPU/MEM (>90%)."""
        from chat_app.orchestration_strategies import execute_orchestration

        fake_settings.default_strategy = "parallel"
        fake_settings.resource_fallback = True

        # can_run_heavy_task is called twice:
        # 1) Heavy check (parallel is medium, so skipped)
        # 2) Medium extreme check with max_cpu=90.0 — we fail this one
        def can_run_side_effect(max_cpu=80.0, max_memory=80.0):
            if max_cpu >= 90.0:
                return (False, "CPU 95%")
            return (True, "ok")

        with patch("chat_app.settings.get_settings") as mock_gs, \
             patch("chat_app.resource_manager.can_run_heavy_task",
                   side_effect=can_run_side_effect), \
             patch("chat_app.orchestration_strategies._suggest_strategy",
                   return_value="parallel"), \
             patch("chat_app.agent_dispatcher.get_agent_dispatcher") as mock_gad, \
             patch("chat_app.agent_dispatcher.format_agent_context_for_llm",
                    return_value="context"):
            mock_gs.return_value = MagicMock(orchestration=fake_settings)
            mock_gad.return_value = FakeDispatcher()

            result = await execute_orchestration(
                "test query", "general_qa", None, None, False
            )
        assert result.strategy_used == "single_agent" or result.fallback_used is True

    def test_fallback_chain_targets_exist(self):
        """Every fallback chain target must be a registered strategy."""
        from chat_app.orchestration_strategies import FALLBACK_CHAIN, get_strategy
        for source_name, targets in FALLBACK_CHAIN.items():
            for target_name in targets:
                assert get_strategy(target_name) is not None, (
                    f"Fallback target '{target_name}' (from '{source_name}') not registered"
                )

    def test_no_self_references_in_fallback_chain(self):
        """No strategy should fall back to itself."""
        from chat_app.orchestration_strategies import FALLBACK_CHAIN
        for source_name, targets in FALLBACK_CHAIN.items():
            assert source_name not in targets, (
                f"Strategy '{source_name}' falls back to itself"
            )

    def test_heavy_strategies_all_have_fallback(self):
        """All heavy strategies should have fallback chains defined."""
        from chat_app.orchestration_strategies import FALLBACK_CHAIN, _STRATEGY_REGISTRY, _ensure_registered
        _ensure_registered()
        for name, s in _STRATEGY_REGISTRY.items():
            if s.resource_weight == "heavy":
                assert name in FALLBACK_CHAIN, f"Heavy strategy '{name}' needs fallback"


# ---------------------------------------------------------------------------
# Test quality tracking across executions
# ---------------------------------------------------------------------------

class TestQualityTracking:
    """Verify quality scores are tracked per strategy."""

    def test_quality_scores_stored_via_record(self):
        """Recording quality via the public API should populate the tracking dict."""
        from chat_app.orchestration_strategies import (
            record_strategy_quality, _strategy_quality, _strategy_quality_lock,
        )
        record_strategy_quality("_test_quality_ext", 0.85)
        with _strategy_quality_lock:
            assert 0.85 in _strategy_quality["_test_quality_ext"]
            # Cleanup
            _strategy_quality.pop("_test_quality_ext", None)

    def test_quality_scores_clamped(self):
        """Scores should be clamped to [0.0, 1.0]."""
        from chat_app.orchestration_strategies import (
            record_strategy_quality, _strategy_quality, _strategy_quality_lock,
        )
        record_strategy_quality("_test_clamp", 1.5)
        record_strategy_quality("_test_clamp", -0.5)
        with _strategy_quality_lock:
            scores = _strategy_quality["_test_clamp"]
            assert scores[-2] == 1.0  # clamped from 1.5
            assert scores[-1] == 0.0  # clamped from -0.5
            _strategy_quality.pop("_test_clamp", None)

    def test_suggest_strategy_considers_quality(self):
        """When a default strategy has poor quality AND an alternative is better, switch."""
        from chat_app.orchestration_strategies import (
            _suggest_strategy, _strategy_quality, _strategy_quality_lock,
        )
        # Set up: poor default, good alternative
        with _strategy_quality_lock:
            _strategy_quality["_poor_default"] = [0.1, 0.15, 0.2, 0.1, 0.15, 0.2]
            _strategy_quality["single_agent"] = [0.8, 0.85, 0.9, 0.8, 0.85]

        result = _suggest_strategy("general_qa", "tell me about indexes", "_poor_default")
        # Should suggest single_agent since it has much better scores
        assert result != "_poor_default"

        # Cleanup
        with _strategy_quality_lock:
            _strategy_quality.pop("_poor_default", None)
            # Leave single_agent as-is (real strategies may use it)


# ---------------------------------------------------------------------------
# Test strategy suggestion based on query characteristics
# ---------------------------------------------------------------------------

class TestStrategySuggestion:
    """Verify _suggest_strategy picks appropriate strategies based on input."""

    def test_comparison_query_suggests_parallel(self):
        from chat_app.orchestration_strategies import _suggest_strategy
        result = _suggest_strategy("general_qa", "compare stats and eventstats", "adaptive")
        assert result == "parallel"

    def test_multipart_long_query_suggests_hierarchical(self):
        from chat_app.orchestration_strategies import _suggest_strategy
        long_query = (
            "I need to first create a saved search that monitors login failures "
            "and also set up an alert for disk space thresholds "
            "and additionally configure a dashboard panel to show trends"
        )
        result = _suggest_strategy("general_qa", long_query, "adaptive")
        assert result == "hierarchical"

    def test_complex_explanation_suggests_review_critique(self):
        from chat_app.orchestration_strategies import _suggest_strategy
        # "why does" pattern without any compare keywords (differ/difference/vs)
        # and word_count > 12
        query = (
            "Why does the stats command produce unexpected results when streaming mode "
            "is enabled in a distributed search environment with multiple indexers?"
        )
        result = _suggest_strategy("general_qa", query, "adaptive")
        assert result == "review_critique"

    def test_simple_query_keeps_default(self):
        from chat_app.orchestration_strategies import _suggest_strategy
        result = _suggest_strategy("general_qa", "what is SPL?", "adaptive")
        # No special keywords, no quality issue -- should keep default
        assert result == "adaptive"

    def test_versus_keyword_suggests_parallel(self):
        from chat_app.orchestration_strategies import _suggest_strategy
        result = _suggest_strategy("general_qa", "stats vs eventstats which is better", "adaptive")
        assert result == "parallel"

    def test_how_does_query_suggests_review_critique(self):
        from chat_app.orchestration_strategies import _suggest_strategy
        # Needs > 12 words and "how does" pattern, no compare keywords
        query = (
            "How does the tstats command optimize search performance when "
            "querying accelerated data models across large data volumes?"
        )
        result = _suggest_strategy("general_qa", query, "adaptive")
        assert result == "review_critique"


# ---------------------------------------------------------------------------
# Test timeout handling
# ---------------------------------------------------------------------------

class TestTimeoutHandling:
    @pytest.mark.asyncio
    async def test_strategy_timeout_returns_error(self, fake_settings):
        """When a strategy exceeds max_duration_seconds, result should indicate timeout."""
        from chat_app.orchestration_strategies import (
            OrchestrationStrategy, OrchestrationResult,
            register_strategy, _STRATEGY_REGISTRY,
        )

        class SlowStrategy(OrchestrationStrategy):
            name = "_slow_test_strategy"
            resource_weight = "light"

            async def execute(self, *args, **kwargs):
                await asyncio.sleep(10)  # Intentionally slow
                return OrchestrationResult(strategy_used=self.name)

        register_strategy(SlowStrategy())

        fake_settings.default_strategy = "_slow_test_strategy"
        fake_settings.max_duration_seconds = 0.1  # Very short timeout
        fake_settings.resource_fallback = False

        from chat_app.orchestration_strategies import execute_orchestration

        with patch("chat_app.settings.get_settings") as mock_gs, \
             patch("chat_app.orchestration_strategies._suggest_strategy",
                   return_value="_slow_test_strategy"), \
             patch("chat_app.resource_manager.can_run_heavy_task",
                   return_value=(True, "ok")):
            mock_gs.return_value = MagicMock(orchestration=fake_settings)

            result = await execute_orchestration(
                "test query", "general_qa", None, None, False
            )

        assert result.success is False
        assert "timed out" in (result.error or "").lower() or "Timed out" in (result.error or "")

        # Cleanup
        _STRATEGY_REGISTRY.pop("_slow_test_strategy", None)

    @pytest.mark.asyncio
    async def test_execute_orchestration_handles_exception(self, fake_settings):
        """When a strategy raises an exception, result should capture it."""
        from chat_app.orchestration_strategies import (
            OrchestrationStrategy, OrchestrationResult,
            register_strategy, _STRATEGY_REGISTRY,
        )

        class BrokenStrategy(OrchestrationStrategy):
            name = "_broken_test_strategy"
            resource_weight = "light"

            async def execute(self, *args, **kwargs):
                raise ValueError("Intentional test error")

        register_strategy(BrokenStrategy())

        fake_settings.default_strategy = "_broken_test_strategy"
        fake_settings.resource_fallback = False

        from chat_app.orchestration_strategies import execute_orchestration

        with patch("chat_app.settings.get_settings") as mock_gs, \
             patch("chat_app.orchestration_strategies._suggest_strategy",
                   return_value="_broken_test_strategy"), \
             patch("chat_app.resource_manager.can_run_heavy_task",
                   return_value=(True, "ok")):
            mock_gs.return_value = MagicMock(orchestration=fake_settings)

            result = await execute_orchestration(
                "test query", "general_qa", None, None, False
            )

        assert result.success is False
        assert result.error is not None

        # Cleanup
        _STRATEGY_REGISTRY.pop("_broken_test_strategy", None)


# ---------------------------------------------------------------------------
# Test OrchestrationResult edge cases
# ---------------------------------------------------------------------------

class TestOrchestrationResultExtended:
    def test_result_with_all_fields(self):
        from chat_app.orchestration_strategies import OrchestrationResult
        r = OrchestrationResult(
            strategy_used="adaptive",
            context="rich context",
            iterations=5,
            quality_score=0.95,
            duration_ms=2500.0,
            success=True,
            fallback_used=True,
            fallback_from="coordinator",
            error=None,
        )
        d = r.to_dict()
        assert d["strategy_used"] == "adaptive"
        assert d["iterations"] == 5
        assert d["quality_score"] == 0.95
        assert d["fallback_used"] is True
        assert d["fallback_from"] == "coordinator"
        assert d["duration_ms"] == 2500.0

    def test_result_defaults(self):
        from chat_app.orchestration_strategies import OrchestrationResult
        r = OrchestrationResult(strategy_used="single_agent")
        assert r.iterations == 1
        assert r.quality_score == 0.0
        assert r.fallback_used is False
        assert r.error is None
        assert r.success is True
