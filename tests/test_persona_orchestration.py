"""Tests for persona-aware orchestration."""

import pytest


@pytest.fixture
def orchestrator():
    from chat_app.persona_orchestration import PersonaOrchestrator
    return PersonaOrchestrator()


class TestAgentScoring:

    def test_technical_prefers_engineering(self, orchestrator):
        score = orchestrator.score_agent("technical_expert", "engineering", "expert")
        assert score > 0

    def test_executive_prefers_management(self, orchestrator):
        score = orchestrator.score_agent("executive_summary", "management", "lead")
        assert score > 0

    def test_no_affinity_returns_zero(self, orchestrator):
        score = orchestrator.score_agent("technical_expert", "creative", "generalist")
        assert score == 0

    def test_unknown_persona_returns_zero(self, orchestrator):
        score = orchestrator.score_agent("nonexistent", "engineering", "expert")
        assert score == 0

    def test_department_match_higher_than_no_match(self, orchestrator):
        match_score = orchestrator.score_agent("debug_mode", "engineering", "expert")
        no_match_score = orchestrator.score_agent("debug_mode", "creative", "generalist")
        assert match_score > no_match_score


class TestStrategyRecommendation:

    def test_technical_recommends_review_critique(self, orchestrator):
        strategy = orchestrator.recommend_strategy("technical_expert", "splunk_search")
        assert strategy == "review_critique"

    def test_executive_recommends_single_agent(self, orchestrator):
        strategy = orchestrator.recommend_strategy("executive_summary", "config_health_check")
        assert strategy == "single_agent"

    def test_debug_recommends_react(self, orchestrator):
        strategy = orchestrator.recommend_strategy("debug_mode", "splunk_search")
        assert strategy == "react"

    def test_unknown_persona_recommends_adaptive(self, orchestrator):
        strategy = orchestrator.recommend_strategy("unknown", "any_intent")
        assert strategy == "adaptive"


class TestFullMatch:

    def test_match_with_agents(self, orchestrator):
        agents = [
            {"name": "spl_expert", "department": "engineering", "expertise": "expert"},
            {"name": "config_helper", "department": "operations", "expertise": "specialist"},
            {"name": "general_assistant", "department": "support", "expertise": "generalist"},
        ]
        result = orchestrator.match("technical_expert", "splunk_search", agents)
        assert result.user_persona == "technical_expert"
        assert result.recommended_agent == "spl_expert"  # Engineering expert
        assert result.agent_score_boost > 0

    def test_match_without_agents(self, orchestrator):
        result = orchestrator.match("executive_summary", "config_health_check")
        assert result.recommended_strategy == "single_agent"
        assert result.recommended_agent is None

    def test_match_result_to_dict(self, orchestrator):
        result = orchestrator.match("debug_mode", "splunk_search")
        d = result.to_dict()
        assert "user_persona" in d
        assert "recommended_strategy" in d
        assert "reasoning" in d


class TestVersionTracking:

    def test_record_persona_change(self, orchestrator):
        version = orchestrator.record_persona_change("user1", "debug_mode", "technical_expert")
        assert version.persona_id == "debug_mode"
        assert version.previous_persona == "technical_expert"

    def test_get_persona_history(self, orchestrator):
        orchestrator.record_persona_change("user1", "technical_expert")
        orchestrator.record_persona_change("user1", "debug_mode", "technical_expert")
        orchestrator.record_persona_change("user2", "executive_summary")

        history = orchestrator.get_persona_history()
        assert len(history) == 3

        user1_history = orchestrator.get_persona_history(username="user1")
        assert len(user1_history) == 2


class TestAffinityMatrix:

    def test_get_affinity_matrix(self, orchestrator):
        matrix = orchestrator.get_affinity_matrix()
        assert "technical_expert" in matrix
        assert "executive_summary" in matrix
        assert "preferred_departments" in matrix["technical_expert"]
        assert "strategy_preference" in matrix["technical_expert"]

    def test_all_personas_have_strategy(self, orchestrator):
        matrix = orchestrator.get_affinity_matrix()
        for persona_id, affinity in matrix.items():
            assert "strategy_preference" in affinity, f"{persona_id} missing strategy_preference"


class TestStats:

    def test_stats_structure(self, orchestrator):
        orchestrator.match("technical_expert", "splunk_search")
        stats = orchestrator.get_stats()
        assert stats["total_matches"] == 1
        assert stats["personas_configured"] >= 5
