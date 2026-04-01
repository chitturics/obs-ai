"""Tests for Toolformer-style tool use decisions."""

import pytest


@pytest.fixture
def engine():
    from chat_app.toolformer import ToolDecisionEngine
    return ToolDecisionEngine()


class TestToolDecisions:

    def test_search_query_uses_tools(self, engine):
        decision = engine.should_use_tools(
            query="search for errors in index=main",
            intent="splunk_search",
        )
        assert decision.use_tools is True

    def test_simple_question_skips_tools(self, engine):
        decision = engine.should_use_tools(
            query="What is the eval command?",
            intent="spl_help",
            retrieval_score=0.9,
        )
        assert decision.use_tools is False

    def test_greeting_never_uses_tools(self, engine):
        decision = engine.should_use_tools(
            query="Hello!",
            intent="greeting",
        )
        assert decision.use_tools is False

    def test_explicit_request_always_uses_tools(self, engine):
        decision = engine.should_use_tools(
            query="please search for me",
            intent="general",
            user_explicitly_requested=True,
        )
        assert decision.use_tools is True
        assert decision.confidence == 1.0

    def test_health_check_uses_tools(self, engine):
        decision = engine.should_use_tools(
            query="check splunk health",
            intent="config_health_check",
        )
        assert decision.use_tools is True

    def test_high_retrieval_score_reduces_tool_need(self, engine):
        decision_low = engine.should_use_tools(
            query="explain stats command",
            intent="spl_help",
            retrieval_score=0.2,
        )
        decision_high = engine.should_use_tools(
            query="explain stats command",
            intent="spl_help",
            retrieval_score=0.95,
        )
        # High retrieval should be less likely to use tools
        assert decision_high.confidence >= decision_low.confidence or not decision_high.use_tools


class TestComplexityScoring:

    def test_spl_query_is_complex(self, engine):
        score = engine._score_complexity("index=main sourcetype=syslog | stats count by host")
        assert score > 0.4

    def test_simple_question_is_not_complex(self, engine):
        score = engine._score_complexity("What is a lookup?")
        assert score < 0.4

    def test_destructive_action_is_complex(self, engine):
        score = engine._score_complexity("delete the index named test_data")
        assert score > 0.4

    def test_deployment_is_complex(self, engine):
        score = engine._score_complexity("deploy the new pipeline to production")
        assert score > 0.4


class TestDecisionResult:

    def test_to_dict(self, engine):
        decision = engine.should_use_tools("test query", "general")
        d = decision.to_dict()
        assert "use_tools" in d
        assert "confidence" in d
        assert "reason" in d

    def test_skip_reason_populated(self, engine):
        decision = engine.should_use_tools("hello", "greeting")
        if not decision.use_tools:
            assert decision.skip_reason is not None


class TestOutcomeTracking:

    def test_record_outcome(self, engine):
        engine.record_outcome("splunk_search", used_tools=True, tool_helped=True)
        engine.record_outcome("splunk_search", used_tools=True, tool_helped=False)
        engine.record_outcome("spl_help", used_tools=False, tool_helped=False)

        stats = engine.get_stats()
        assert stats["intent_stats"]["splunk_search"]["tool_used"] == 2
        assert stats["intent_stats"]["splunk_search"]["tool_helped"] == 1
        assert stats["intent_stats"]["splunk_search"]["effectiveness"] == 0.5

    def test_historical_score_affects_decision(self, engine):
        # Train the engine: spl_help tools always waste time
        for _ in range(10):
            engine.record_outcome("spl_help", used_tools=True, tool_helped=False)

        # Should now be less likely to use tools for spl_help
        decision = engine.should_use_tools("explain eval command", intent="spl_help")
        # The historical score should be low
        assert engine._get_historical_score("spl_help") < 0.2


class TestIntentToolNeeds:

    def test_get_intent_tool_needs(self, engine):
        needs = engine.get_intent_tool_needs()
        assert needs["splunk_search"] == 1.0
        assert needs["greeting"] == 0.0
        assert 0 < needs["spl_help"] < 0.5


class TestStats:

    def test_stats_structure(self, engine):
        engine.should_use_tools("test", "general")
        stats = engine.get_stats()
        assert stats["total_decisions"] >= 1
        assert "threshold" in stats
