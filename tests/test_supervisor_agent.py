"""Tests for chat_app.supervisor_agent — SupervisorAgent pattern."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chat_app.schemas import ResearchFinding
from chat_app.supervisor_agent import SupervisorAgent, SupervisorResult


class TestSupervisorDecompose:
    def test_single_query(self):
        sa = SupervisorAgent()
        tasks = sa._decompose("how do I configure props.conf", "config_help")
        assert len(tasks) >= 1
        assert "props.conf" in tasks[0]

    def test_multi_part_query_and(self):
        sa = SupervisorAgent()
        tasks = sa._decompose(
            "configure props.conf and then restart splunk services",
            "config_help",
        )
        assert len(tasks) >= 2

    def test_multi_part_query_comma(self):
        sa = SupervisorAgent()
        tasks = sa._decompose(
            "check index health, then optimize search performance",
            "troubleshoot",
        )
        assert len(tasks) >= 2

    def test_long_query_gets_analysis_subtask(self):
        sa = SupervisorAgent()
        long_query = " ".join(["word"] * 20)
        tasks = sa._decompose(long_query, "general")
        assert len(tasks) >= 2

    def test_max_subtasks_capped(self):
        sa = SupervisorAgent()
        tasks = sa._decompose(
            "a and b and c and d and e and f and g",
            "general",
        )
        assert len(tasks) <= 5


class TestSupervisorDepartmentInference:
    def test_config_routes_to_engineering(self):
        sa = SupervisorAgent()
        assert sa._infer_department("configure props.conf") == "engineering"

    def test_search_routes_to_data(self):
        sa = SupervisorAgent()
        assert sa._infer_department("search for stats command") == "data"

    def test_security_routes_to_security(self):
        sa = SupervisorAgent()
        assert sa._infer_department("check auth settings") == "security"

    def test_deploy_routes_to_operations(self):
        sa = SupervisorAgent()
        assert sa._infer_department("restart the service") == "operations"

    def test_unknown_returns_none(self):
        sa = SupervisorAgent()
        assert sa._infer_department("hello world") is None


class TestSupervisorSynthesize:
    def test_empty_findings(self):
        sa = SupervisorAgent()
        result = sa._synthesize([])
        assert result == ""

    def test_single_finding(self):
        sa = SupervisorAgent()
        findings = [
            ResearchFinding(
                topic="Props.conf config",
                summary="Set INDEXED_EXTRACTIONS=json",
                agent_name="config_builder",
            )
        ]
        result = sa._synthesize(findings)
        assert "Props.conf config" in result
        assert "config_builder" in result

    def test_multiple_findings(self):
        sa = SupervisorAgent()
        findings = [
            ResearchFinding(topic="Topic A", summary="Summary A"),
            ResearchFinding(topic="Topic B", summary="Summary B"),
        ]
        result = sa._synthesize(findings)
        assert "Topic A" in result
        assert "Topic B" in result

    def test_findings_with_recommendations(self):
        sa = SupervisorAgent()
        findings = [
            ResearchFinding(
                topic="Optimization",
                summary="Use tstats",
                recommendations=["Use tstats instead of stats", "Add acceleration"],
            )
        ]
        result = sa._synthesize(findings)
        assert "Recommendations:" in result


class TestSupervisorResult:
    def test_to_dict(self):
        result = SupervisorResult(
            findings=[ResearchFinding(topic="t", summary="s")],
            quality_score=0.85,
            duration_ms=100.123,
            escalation_rounds=1,
        )
        d = result.to_dict()
        assert d["findings_count"] == 1
        assert d["quality_score"] == 0.85
        assert d["escalation_rounds"] == 1

    def test_defaults(self):
        result = SupervisorResult(findings=[])
        assert result.success is True
        assert result.error is None
        assert result.agent_trace == []


class TestSupervisorExecution:
    @pytest.mark.asyncio
    async def test_supervise_with_mock_dispatcher(self):
        """Test full supervise flow with mocked dispatcher."""
        from chat_app.agent_dispatcher import AgentDispatchResult

        mock_result = AgentDispatchResult(
            agent_name="spl_expert",
            agent_role="Expert",
            department="data",
            skills_executed=["analyze_spl"],
            enriched_context="Use stats command for aggregation",
            success=True,
            duration_ms=50.0,
        )

        mock_dispatcher = MagicMock()
        mock_dispatcher.dispatch = AsyncMock(return_value=mock_result)

        with patch("chat_app.agent_dispatcher.get_agent_dispatcher", return_value=mock_dispatcher):
            sa = SupervisorAgent(quality_threshold=0.3)
            result = await sa.supervise(
                user_input="explain the stats command",
                intent="spl_help",
            )

        assert result.success is True
        assert len(result.findings) >= 1
        assert result.quality_score > 0
        assert result.synthesized_context != ""

    @pytest.mark.asyncio
    async def test_supervise_failure(self):
        """Test supervise when dispatcher unavailable."""
        with patch("chat_app.agent_dispatcher.get_agent_dispatcher", side_effect=ImportError("no module")):
            sa = SupervisorAgent()
            result = await sa.supervise("test", "test")
            assert result.success is False
            assert result.error is not None


class TestStrategyRegistration:
    def test_supervisor_strategy_registered(self):
        """SupervisorStrategy should be in the registry."""
        # Import triggers registration
        import chat_app.supervisor_agent  # noqa: F401
        from chat_app.orchestration_strategies import get_strategy
        strategy = get_strategy("supervisor")
        assert strategy is not None
        assert strategy.name == "supervisor"
        assert strategy.resource_weight == "heavy"

    def test_supervisor_strategy_count(self):
        """Should now be 18 strategies."""
        import chat_app.supervisor_agent  # noqa: F401
        from chat_app.orchestration_strategies import list_strategies
        strategies = list_strategies()
        assert len(strategies) >= 18
