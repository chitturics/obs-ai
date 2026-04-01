"""Tests for chat_app/context_compressor.py — context window management."""
import pytest
from chat_app.context_compressor import (
    compress_interaction_history,
    estimate_context_tokens,
    should_compress,
    compress_context_if_needed,
    CompressedTurn,
)


class TestCompressedTurnDataclass:
    """Test CompressedTurn data structure."""

    def test_default_construction(self):
        ct = CompressedTurn(turn_number=1, summary="talked about stats")
        assert ct.turn_number == 1
        assert ct.summary == "talked about stats"
        assert ct.key_facts == []
        assert ct.query_topic == ""

    def test_full_construction(self):
        ct = CompressedTurn(
            turn_number=3,
            summary="discussed SPL optimization",
            key_facts=["tstats is faster", "filter early"],
            query_topic="performance",
        )
        assert len(ct.key_facts) == 2
        assert ct.query_topic == "performance"


class TestEstimateContextTokens:
    """Test token estimation."""

    def test_empty_string(self):
        assert estimate_context_tokens("") == 0

    def test_short_string(self):
        # 12 chars → ~3 tokens
        tokens = estimate_context_tokens("hello world!")
        assert tokens == 3

    def test_longer_string(self):
        text = "a" * 400
        assert estimate_context_tokens(text) == 100

    def test_proportional(self):
        t1 = estimate_context_tokens("short")
        t2 = estimate_context_tokens("short" * 100)
        assert t2 > t1


class TestShouldCompress:
    """Test compression threshold checking."""

    def test_short_context_no_compress(self):
        assert should_compress("hello", max_tokens=4000) is False

    def test_long_context_needs_compress(self):
        long_text = "x" * 20000  # ~5000 tokens
        assert should_compress(long_text, max_tokens=4000) is True

    def test_exact_threshold(self):
        # 16000 chars = 4000 tokens
        text = "x" * 16000
        assert should_compress(text, max_tokens=4000) is False

    def test_just_over_threshold(self):
        text = "x" * 16004  # 4001 tokens
        assert should_compress(text, max_tokens=4000) is True

    def test_custom_threshold(self):
        text = "x" * 4000  # ~1000 tokens
        assert should_compress(text, max_tokens=500) is True
        assert should_compress(text, max_tokens=2000) is False


class TestCompressInteractionHistory:
    """Test interaction history compression."""

    def test_empty_interactions(self):
        result = compress_interaction_history([])
        assert result == ""

    def test_few_interactions_kept_full(self):
        interactions = [
            "User: what is stats?\nAssistant: stats aggregates data",
            "User: how about eval?\nAssistant: eval computes fields",
        ]
        result = compress_interaction_history(interactions, max_full_turns=4)
        # With only 2 turns and max 4, all should be kept in full
        assert "what is stats?" in result
        assert "how about eval?" in result

    def test_old_turns_compressed(self):
        interactions = [
            "User: what is stats?\nAssistant: stats aggregates data",
            "User: how about eval?\nAssistant: eval computes fields",
            "User: explain tstats\nAssistant: tstats is faster",
            "User: what is rex?\nAssistant: rex extracts fields",
            "User: show me join\nAssistant: join combines results",
            "User: latest question\nAssistant: latest answer",
        ]
        result = compress_interaction_history(interactions, max_full_turns=2)
        # Last 2 turns should be in full
        assert "latest question" in result
        assert "show me join" in result
        # Older turns should be compressed
        assert "[Previous conversation summary:" in result

    def test_exact_threshold_no_compression(self):
        interactions = ["turn1", "turn2", "turn3", "turn4"]
        result = compress_interaction_history(interactions, max_full_turns=4)
        assert "[Previous conversation summary:" not in result

    def test_one_over_threshold_compresses(self):
        interactions = [
            "User: old question\nAssistant: old answer",
            "User: recent 1\nAssistant: answer 1",
            "User: recent 2\nAssistant: answer 2",
        ]
        result = compress_interaction_history(interactions, max_full_turns=2)
        assert "recent 1" in result
        assert "recent 2" in result


class TestCompressContextIfNeeded:
    """Test full context compression."""

    def test_short_context_unchanged(self):
        text = "short context"
        result = compress_context_if_needed(text, max_tokens=4000)
        assert result == text

    def test_long_context_compressed(self):
        # Create context with multiple sections
        sections = [f"Section {i}: " + "x" * 2000 for i in range(10)]
        text = "\n\n".join(sections)
        result = compress_context_if_needed(text, max_tokens=2000)
        assert len(result) < len(text)

    def test_truncation_marker_added(self):
        sections = [f"Section {i}: " + "x" * 2000 for i in range(10)]
        text = "\n\n".join(sections)
        result = compress_context_if_needed(text, max_tokens=2000)
        assert "[...truncated]" in result

    def test_empty_context(self):
        result = compress_context_if_needed("", max_tokens=4000)
        assert result == ""
