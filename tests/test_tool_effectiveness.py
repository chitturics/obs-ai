"""Comprehensive unit tests for chat_app.tool_effectiveness."""
import time

import pytest

from chat_app.tool_effectiveness import (
    ToolChainStats,
    ToolEffectivenessTracker,
    ToolExecution,
    ToolStats,
)


# ---------------------------------------------------------------------------
# ToolExecution dataclass
# ---------------------------------------------------------------------------

class TestToolExecution:
    def test_create_minimal(self):
        te = ToolExecution(tool_name="t1", intent="search", success=True, latency_ms=42.0)
        assert te.tool_name == "t1"
        assert te.intent == "search"
        assert te.success is True
        assert te.latency_ms == 42.0
        assert te.error is None
        assert te.preceded_by is None
        assert te.followed_by is None
        assert te.timestamp > 0

    def test_create_full(self):
        te = ToolExecution(
            tool_name="t2",
            intent="optimize",
            success=False,
            latency_ms=100.0,
            error="timeout",
            query_pattern="index=main",
            preceded_by="t1",
            followed_by="t3",
        )
        assert te.error == "timeout"
        assert te.preceded_by == "t1"
        assert te.followed_by == "t3"
        assert te.query_pattern == "index=main"


# ---------------------------------------------------------------------------
# ToolStats
# ---------------------------------------------------------------------------

class TestToolStats:
    def test_empty_stats(self):
        ts = ToolStats(tool_name="empty")
        assert ts.success_rate == 0.0
        assert ts.avg_latency_ms == 0.0
        assert ts.p95_latency_ms == 0.0

    def test_record_success(self):
        ts = ToolStats(tool_name="s")
        ts.record(True, 100.0)
        assert ts.total_executions == 1
        assert ts.successes == 1
        assert ts.failures == 0
        assert ts.success_rate == 1.0
        assert ts.avg_latency_ms == 100.0

    def test_record_failure(self):
        ts = ToolStats(tool_name="f")
        ts.record(False, 50.0)
        assert ts.total_executions == 1
        assert ts.successes == 0
        assert ts.failures == 1
        assert ts.success_rate == 0.0

    def test_mixed_records(self):
        ts = ToolStats(tool_name="m")
        ts.record(True, 100.0)
        ts.record(True, 200.0)
        ts.record(False, 300.0)
        assert ts.total_executions == 3
        assert ts.success_rate == pytest.approx(2 / 3)
        assert ts.avg_latency_ms == pytest.approx(200.0)

    def test_p95_latency(self):
        ts = ToolStats(tool_name="p95")
        # Record 100 values: 1..100
        for i in range(1, 101):
            ts.record(True, float(i))
        # p95 index = int(100 * 0.95) = 95 -> value at sorted[95] = 96
        assert ts.p95_latency_ms == 96.0

    def test_p95_single_value(self):
        ts = ToolStats(tool_name="single")
        ts.record(True, 42.0)
        assert ts.p95_latency_ms == 42.0

    def test_latency_truncation(self):
        ts = ToolStats(tool_name="trunc")
        for i in range(1100):
            ts.record(True, float(i))
        # After exceeding 1000, latencies truncated to last 500
        assert len(ts.latencies) <= 1000


# ---------------------------------------------------------------------------
# ToolChainStats
# ---------------------------------------------------------------------------

class TestToolChainStats:
    def test_empty_chain(self):
        cs = ToolChainStats(chain=("a", "b"))
        assert cs.success_rate == 0.0
        assert cs.avg_latency_ms == 0.0
        assert cs.total_runs == 0

    def test_chain_with_data(self):
        cs = ToolChainStats(chain=("a", "b"), total_runs=4, successes=3, total_latency_ms=400.0)
        assert cs.success_rate == 0.75
        assert cs.avg_latency_ms == 100.0


# ---------------------------------------------------------------------------
# ToolEffectivenessTracker — record_execution
# ---------------------------------------------------------------------------

class TestRecordExecution:
    def test_basic_recording(self):
        tracker = ToolEffectivenessTracker()
        tracker.record_execution("tool_a", "search", True, 50.0)
        stats = tracker.get_tool_stats("tool_a")
        assert stats["total_executions"] == 1
        assert stats["success_rate"] == 1.0

    def test_multiple_recordings(self):
        tracker = ToolEffectivenessTracker()
        tracker.record_execution("t1", "intent_a", True, 100.0)
        tracker.record_execution("t1", "intent_a", False, 200.0)
        stats = tracker.get_tool_stats("t1")
        assert stats["total_executions"] == 2
        assert stats["success_rate"] == 0.5

    def test_per_intent_stats(self):
        tracker = ToolEffectivenessTracker()
        tracker.record_execution("t1", "search", True, 10.0)
        tracker.record_execution("t1", "optimize", False, 20.0)
        matrix = tracker.get_intent_tool_matrix()
        assert "search" in matrix
        assert "optimize" in matrix
        assert matrix["search"][0]["success_rate"] == 1.0
        assert matrix["optimize"][0]["success_rate"] == 0.0

    def test_history_truncation(self):
        tracker = ToolEffectivenessTracker(max_history=10)
        for i in range(20):
            tracker.record_execution("t", "i", True, 1.0)
        assert len(tracker._history) == 10


# ---------------------------------------------------------------------------
# rank_tools_for_intent
# ---------------------------------------------------------------------------

class TestRankTools:
    def test_no_data_returns_neutral(self):
        tracker = ToolEffectivenessTracker()
        ranked = tracker.rank_tools_for_intent("unknown", ["a", "b"])
        assert len(ranked) == 2
        for name, score in ranked:
            assert score == 0.5

    def test_ranking_with_data(self):
        tracker = ToolEffectivenessTracker()
        # Tool A: 100% success, low latency
        for _ in range(5):
            tracker.record_execution("tool_a", "search", True, 10.0)
        # Tool B: 60% success, higher latency
        for _ in range(3):
            tracker.record_execution("tool_b", "search", True, 100.0)
        for _ in range(2):
            tracker.record_execution("tool_b", "search", False, 100.0)
        ranked = tracker.rank_tools_for_intent("search")
        assert ranked[0][0] == "tool_a"
        assert ranked[0][1] > ranked[1][1]

    def test_ranking_fewer_than_3_executions_gets_neutral(self):
        tracker = ToolEffectivenessTracker()
        tracker.record_execution("t1", "intent_x", True, 10.0)
        tracker.record_execution("t1", "intent_x", True, 10.0)
        ranked = tracker.rank_tools_for_intent("intent_x")
        assert ranked[0][1] == 0.5  # Not enough data

    def test_ranking_includes_unseen_tools(self):
        tracker = ToolEffectivenessTracker()
        for _ in range(5):
            tracker.record_execution("known", "i1", True, 10.0)
        ranked = tracker.rank_tools_for_intent("i1", ["known", "new_tool"])
        names = [r[0] for r in ranked]
        assert "new_tool" in names

    def test_ranking_filters_available_tools(self):
        tracker = ToolEffectivenessTracker()
        for _ in range(5):
            tracker.record_execution("t1", "i", True, 10.0)
            tracker.record_execution("t2", "i", True, 20.0)
        ranked = tracker.rank_tools_for_intent("i", available_tools=["t1"])
        names = [r[0] for r in ranked]
        assert "t2" not in names

    def test_ranking_tied_scores(self):
        tracker = ToolEffectivenessTracker()
        for _ in range(5):
            tracker.record_execution("a", "i", True, 10.0)
        for _ in range(5):
            tracker.record_execution("b", "i", True, 10.0)
        ranked = tracker.rank_tools_for_intent("i")
        assert len(ranked) == 2
        assert ranked[0][1] == ranked[1][1]


# ---------------------------------------------------------------------------
# get_fallback_tool
# ---------------------------------------------------------------------------

class TestFallbackTool:
    def test_no_data(self):
        tracker = ToolEffectivenessTracker()
        assert tracker.get_fallback_tool("t1", "unknown") is None

    def test_fallback_found(self):
        tracker = ToolEffectivenessTracker()
        for _ in range(5):
            tracker.record_execution("primary", "search", False, 10.0)
        for _ in range(5):
            tracker.record_execution("backup", "search", True, 10.0)
        fallback = tracker.get_fallback_tool("primary", "search")
        assert fallback == "backup"

    def test_fallback_excludes_failed_tool(self):
        tracker = ToolEffectivenessTracker()
        for _ in range(5):
            tracker.record_execution("only", "i", True, 10.0)
        fallback = tracker.get_fallback_tool("only", "i")
        assert fallback is None

    def test_fallback_requires_min_executions(self):
        tracker = ToolEffectivenessTracker()
        tracker.record_execution("candidate", "i", True, 10.0)
        # Only 1 execution, needs >= 2
        fallback = tracker.get_fallback_tool("other", "i")
        assert fallback is None

    def test_fallback_requires_over_50_success(self):
        tracker = ToolEffectivenessTracker()
        for _ in range(3):
            tracker.record_execution("weak", "i", False, 10.0)
        tracker.record_execution("weak", "i", True, 10.0)
        # 25% success rate < 50%
        fallback = tracker.get_fallback_tool("other", "i")
        assert fallback is None


# ---------------------------------------------------------------------------
# get_best_chain_for_intent
# ---------------------------------------------------------------------------

class TestBestChain:
    def test_no_chains(self):
        tracker = ToolEffectivenessTracker()
        assert tracker.get_best_chain_for_intent("any") is None

    def test_best_chain_selected(self):
        tracker = ToolEffectivenessTracker()
        tracker.record_chain(["a", "b"], True, 100.0)
        tracker.record_chain(["a", "b"], True, 100.0)
        tracker.record_chain(["c", "d"], False, 50.0)
        tracker.record_chain(["c", "d"], False, 50.0)
        best = tracker.get_best_chain_for_intent("any")
        assert best == ("a", "b")

    def test_chain_needs_minimum_runs(self):
        tracker = ToolEffectivenessTracker()
        tracker.record_chain(["x"], True, 10.0)
        # Only 1 run, needs >= 2
        assert tracker.get_best_chain_for_intent("any") is None


# ---------------------------------------------------------------------------
# get_tool_stats / get_chain_stats / get_intent_tool_matrix
# ---------------------------------------------------------------------------

class TestStatsRetrieval:
    def test_get_tool_stats_specific(self):
        tracker = ToolEffectivenessTracker()
        tracker.record_execution("alpha", "i", True, 50.0)
        stats = tracker.get_tool_stats("alpha")
        assert stats["tool_name"] == "alpha"
        assert stats["total_executions"] == 1

    def test_get_tool_stats_not_found(self):
        tracker = ToolEffectivenessTracker()
        assert tracker.get_tool_stats("missing") == {}

    def test_get_tool_stats_all(self):
        tracker = ToolEffectivenessTracker()
        tracker.record_execution("a", "i", True, 10.0)
        tracker.record_execution("b", "i", False, 20.0)
        all_stats = tracker.get_tool_stats()
        assert "a" in all_stats
        assert "b" in all_stats

    def test_get_chain_stats(self):
        tracker = ToolEffectivenessTracker()
        tracker.record_chain(["a", "b"], True, 100.0)
        tracker.record_chain(["a", "b"], False, 200.0)
        chains = tracker.get_chain_stats()
        assert len(chains) == 1
        assert chains[0]["chain"] == ["a", "b"]
        assert chains[0]["total_runs"] == 2
        assert chains[0]["success_rate"] == 0.5

    def test_get_intent_tool_matrix_empty(self):
        tracker = ToolEffectivenessTracker()
        assert tracker.get_intent_tool_matrix() == {}

    def test_get_intent_tool_matrix_sorted(self):
        tracker = ToolEffectivenessTracker()
        for _ in range(5):
            tracker.record_execution("good", "i", True, 10.0)
        for _ in range(5):
            tracker.record_execution("bad", "i", False, 10.0)
        matrix = tracker.get_intent_tool_matrix()
        # "good" should come first (sorted by success_rate desc)
        assert matrix["i"][0]["tool"] == "good"
        assert matrix["i"][1]["tool"] == "bad"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_history(self):
        tracker = ToolEffectivenessTracker()
        assert tracker.get_tool_stats() == {}
        assert tracker.get_chain_stats() == []
        assert tracker.get_intent_tool_matrix() == {}

    def test_single_execution(self):
        tracker = ToolEffectivenessTracker()
        tracker.record_execution("solo", "only_intent", True, 7.5)
        stats = tracker.get_tool_stats("solo")
        assert stats["total_executions"] == 1
        assert stats["p95_latency_ms"] == 7.5

    def test_max_history_boundary(self):
        tracker = ToolEffectivenessTracker(max_history=5)
        for i in range(7):
            tracker.record_execution(f"t{i}", "x", True, 1.0)
        assert len(tracker._history) == 5
        # The oldest 2 should have been dropped
        assert tracker._history[0].tool_name == "t2"
