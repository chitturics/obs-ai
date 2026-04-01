"""
Comprehensive tests for chat_app.user_model — pure/sync functions only.

Covers:
- UserModel dataclass construction, defaults, and satisfaction_rate property
- personalize_settings: beginner, expert, intermediate, low-satisfaction overrides
- get_user_context_note: expert, beginner, insufficient data, pain points, low satisfaction
- _infer_expertise: expert signals, beginner signals, mixed, empty
- _extract_common_topics: single topic, multiple topics, no match, ranking
- _avg_complexity: simple text, SPL with pipes, empty list, boundary values
"""
import pytest

from chat_app.user_model import (
    UserModel,
    personalize_settings,
    get_user_context_note,
    _infer_expertise,
    _extract_common_topics,
    _avg_complexity,
)


# ---------------------------------------------------------------------------
# 1. UserModel dataclass construction and defaults
# ---------------------------------------------------------------------------

class TestUserModelDefaults:
    def test_default_construction(self):
        """UserModel() should produce sensible defaults for every field."""
        m = UserModel()
        assert m.username == "anonymous"
        assert m.expertise_level == "intermediate"
        assert m.preferred_profile is None
        assert m.preferred_style == "detailed"
        assert m.common_topics == []
        assert m.strengths == []
        assert m.pain_points == []
        assert m.total_queries == 0
        assert m.positive_feedback == 0
        assert m.negative_feedback == 0
        assert m.avg_query_complexity == 0.5

    def test_custom_construction(self):
        """UserModel should accept all keyword arguments."""
        m = UserModel(
            username="alice",
            expertise_level="expert",
            preferred_profile="security",
            preferred_style="concise",
            common_topics=["spl_queries", "security"],
            strengths=["spl_queries"],
            pain_points=["deployment"],
            total_queries=100,
            positive_feedback=80,
            negative_feedback=5,
            avg_query_complexity=0.8,
        )
        assert m.username == "alice"
        assert m.expertise_level == "expert"
        assert m.preferred_profile == "security"
        assert m.preferred_style == "concise"
        assert m.common_topics == ["spl_queries", "security"]
        assert m.total_queries == 100
        assert m.positive_feedback == 80
        assert m.negative_feedback == 5
        assert m.avg_query_complexity == 0.8

    def test_satisfaction_rate_no_feedback(self):
        """With zero feedback the satisfaction rate should default to 0.5."""
        m = UserModel()
        assert m.satisfaction_rate == 0.5

    def test_satisfaction_rate_all_positive(self):
        """100 % positive feedback should yield 1.0."""
        m = UserModel(positive_feedback=10, negative_feedback=0)
        assert m.satisfaction_rate == 1.0

    def test_satisfaction_rate_mixed(self):
        """Mixed feedback should compute the correct ratio."""
        m = UserModel(positive_feedback=3, negative_feedback=7)
        assert m.satisfaction_rate == pytest.approx(0.3)


# ---------------------------------------------------------------------------
# 2. personalize_settings
# ---------------------------------------------------------------------------

class TestPersonalizeSettings:
    def test_expert_gets_deeper_search(self):
        """Expert users should get search_depth=7 by default."""
        m = UserModel(expertise_level="expert")
        result = personalize_settings(m, {})
        assert result["search_depth"] == 7

    def test_expert_does_not_override_existing_depth(self):
        """setdefault must not overwrite a depth the caller already set."""
        m = UserModel(expertise_level="expert")
        result = personalize_settings(m, {"search_depth": 10})
        assert result["search_depth"] == 10

    def test_beginner_gets_shallow_search_and_tutorial(self):
        """Beginners should get search_depth=4 and tutorial response style."""
        m = UserModel(expertise_level="beginner")
        result = personalize_settings(m, {})
        assert result["search_depth"] == 4
        assert result["response_style"] == "tutorial"

    def test_beginner_does_not_override_existing_style(self):
        """If response_style is already provided, beginner logic should not touch it."""
        m = UserModel(expertise_level="beginner")
        result = personalize_settings(m, {"response_style": "concise"})
        assert result["response_style"] == "concise"

    def test_intermediate_leaves_settings_unchanged(self):
        """Intermediate expertise should not inject search_depth or response_style."""
        m = UserModel(expertise_level="intermediate")
        base = {"foo": "bar"}
        result = personalize_settings(m, base)
        assert "search_depth" not in result
        assert "response_style" not in result
        assert result["foo"] == "bar"

    def test_low_satisfaction_forces_detailed_and_examples(self):
        """A dissatisfied user with enough history should get detailed + examples."""
        m = UserModel(
            expertise_level="intermediate",
            total_queries=10,
            positive_feedback=2,
            negative_feedback=8,
        )
        # satisfaction_rate = 2/10 = 0.2 < 0.4
        result = personalize_settings(m, {})
        assert result["response_style"] == "detailed"
        assert result["include_examples"] is True

    def test_low_satisfaction_requires_enough_queries(self):
        """Low satisfaction should not trigger overrides when total_queries <= 5."""
        m = UserModel(
            total_queries=3,
            positive_feedback=0,
            negative_feedback=3,
        )
        result = personalize_settings(m, {})
        assert "include_examples" not in result

    def test_base_settings_not_mutated(self):
        """personalize_settings must not mutate the input dict."""
        base = {"key": "value"}
        m = UserModel(expertise_level="expert")
        personalize_settings(m, base)
        assert "search_depth" not in base


# ---------------------------------------------------------------------------
# 3. get_user_context_note
# ---------------------------------------------------------------------------

class TestGetUserContextNote:
    def test_returns_none_when_few_queries(self):
        """With fewer than 3 queries, there is not enough data."""
        m = UserModel(total_queries=2)
        assert get_user_context_note(m) is None

    def test_expert_note_includes_expertise(self):
        """The note should mention the user's expertise level."""
        m = UserModel(expertise_level="expert", total_queries=10)
        note = get_user_context_note(m)
        assert note is not None
        assert "expert" in note

    def test_beginner_note_includes_expertise(self):
        m = UserModel(expertise_level="beginner", total_queries=5)
        note = get_user_context_note(m)
        assert note is not None
        assert "beginner" in note

    def test_common_topics_included(self):
        """Frequent topics (up to 3) should appear in the note."""
        m = UserModel(
            total_queries=10,
            common_topics=["spl_queries", "security", "dashboards", "performance"],
        )
        note = get_user_context_note(m)
        assert "spl_queries" in note
        assert "security" in note
        assert "dashboards" in note
        # 4th topic should be excluded (limit is 3)
        assert "performance" not in note

    def test_pain_points_included(self):
        """Pain points (up to 2) should appear in the note."""
        m = UserModel(
            total_queries=5,
            pain_points=["deployment", "indexing", "security"],
        )
        note = get_user_context_note(m)
        assert "deployment" in note
        assert "indexing" in note
        # 3rd pain point should be excluded (limit is 2)
        assert "security" not in note

    def test_low_satisfaction_warning(self):
        """A dissatisfied user with enough queries should trigger the warning."""
        m = UserModel(
            total_queries=10,
            positive_feedback=1,
            negative_feedback=9,
        )
        note = get_user_context_note(m)
        assert note is not None
        assert "low satisfaction" in note

    def test_low_satisfaction_not_triggered_under_threshold(self):
        """Low satisfaction warning should not appear when total_queries <= 5."""
        m = UserModel(
            total_queries=4,
            positive_feedback=0,
            negative_feedback=4,
        )
        note = get_user_context_note(m)
        # total_queries=4 >= 3 so we get a note, but no low-satisfaction clause
        assert note is not None
        assert "low satisfaction" not in note


# ---------------------------------------------------------------------------
# 4. _infer_expertise
# ---------------------------------------------------------------------------

class TestInferExpertise:
    def test_expert_queries(self):
        """Queries rich in expert SPL signals should yield 'expert'."""
        questions = [
            "| tstats count from datamodel=Authentication",
            "| tstats summariesonly=t values(prefix(src_ip)) from datamodel",
            "Use TERM() for performance optimization",
            "How to accelerate a CIM datamodel?",
            "Show risk based alerting for TERM(malware)",
        ]
        assert _infer_expertise(questions) == "expert"

    def test_beginner_queries(self):
        """Simple, definitional queries should yield 'beginner'."""
        questions = [
            "What is Splunk?",
            "How do I search?",
            "Explain the basic search",
            "What is SPL?",
            "How to start?",
            "How can I filter?",
        ]
        assert _infer_expertise(questions) == "beginner"

    def test_mixed_queries_intermediate(self):
        """A mix of expert and beginner signals should fall to 'intermediate'."""
        questions = [
            "| stats count by src_ip grouped over time window",
            "Show me a timechart of login events by sourcetype last week",
            "I need to build a lookup table from CSV data",
            "Can you show me how to use subsearch with the append command",
            "What is an index?",
        ]
        # expert_ratio and beginner_ratio both stay below their thresholds
        assert _infer_expertise(questions) == "intermediate"

    def test_empty_list(self):
        """An empty question list should return 'intermediate'."""
        assert _infer_expertise([]) == "intermediate"


# ---------------------------------------------------------------------------
# 5. _extract_common_topics
# ---------------------------------------------------------------------------

class TestExtractCommonTopics:
    def test_single_matching_topic(self):
        """A query that matches one topic pattern."""
        questions = ["show me a dashboard panel"]
        topics = _extract_common_topics(questions)
        assert "dashboards" in topics

    def test_multiple_topics(self):
        """Multiple topics should be detected across different questions."""
        questions = [
            "my search query is slow",
            "optimize the stats search for performance",
            "error when parsing events not working",
        ]
        topics = _extract_common_topics(questions)
        assert "performance" in topics
        assert "spl_queries" in topics
        assert "troubleshooting" in topics

    def test_no_match(self):
        """Questions that match no pattern should yield an empty list."""
        questions = ["hello world", "just a random sentence"]
        assert _extract_common_topics(questions) == []

    def test_ranking_by_frequency(self):
        """The most frequently mentioned topic should appear first."""
        questions = [
            "search query stats",
            "eval query where",
            "search index query",
            "metric trace otel",
        ]
        topics = _extract_common_topics(questions)
        # spl_queries matches all 3 of the first questions; observability matches 1
        assert topics[0] == "spl_queries"

    def test_max_five_topics(self):
        """At most 5 topics should be returned."""
        # Build questions that hit many topic categories
        questions = [
            "search query stats eval where",       # spl_queries
            "conf config stanza inputs",            # configuration
            "error fail issue debug not working",   # troubleshooting
            "index ingest sourcetype parsing",      # indexing
            "security alert notable threat cim",    # security
            "dashboard panel visualization chart",  # dashboards
            "deploy cluster forwarder heavy",       # deployment
            "slow performance optimize tstats",     # performance
        ]
        topics = _extract_common_topics(questions)
        assert len(topics) <= 5


# ---------------------------------------------------------------------------
# 6. _avg_complexity
# ---------------------------------------------------------------------------

class TestAvgComplexity:
    def test_empty_list(self):
        """Empty input should return the default 0.5."""
        assert _avg_complexity([]) == 0.5

    def test_simple_short_text(self):
        """A very short, non-SPL question should have low complexity."""
        result = _avg_complexity(["hello"])
        # words=1 -> 1/30 ~ 0.033, pipes=0, no spl -> 0.033
        assert result < 0.2

    def test_spl_with_pipes(self):
        """SPL with pipes and index= should score higher complexity."""
        result = _avg_complexity(["index=main sourcetype=syslog | stats count by host | sort -count"])
        assert result > 0.3

    def test_multiple_questions_averaged(self):
        """Complexity should be averaged across all questions."""
        questions = ["hi", "index=main | stats count by src | eval x=1 | where x>0"]
        result = _avg_complexity(questions)
        # First is low (~0.033), second is high; average should be moderate
        simple_score = _avg_complexity(["hi"])
        complex_score = _avg_complexity([questions[1]])
        assert result == pytest.approx((simple_score + complex_score) / 2)

    def test_score_capped_at_one(self):
        """No individual score should exceed 1.0, so the average is at most 1.0."""
        giant = " ".join(["word"] * 100) + " | " * 20 + " index=main"
        result = _avg_complexity([giant])
        assert result <= 1.0
