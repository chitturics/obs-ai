"""Tests for extended cost tracker (retrieval + tool tracking + dashboard)."""

import pytest


@pytest.fixture
def tracker():
    from chat_app.cost_tracker import CostTracker
    return CostTracker()


class TestRetrievalTracking:

    def test_record_retrieval(self, tracker):
        result = tracker.record_retrieval("user1", "spl_docs", latency_ms=120.5, chunks_returned=5)
        assert result["collection"] == "spl_docs"
        assert result["chunks_returned"] == 5

    def test_retrieval_in_dashboard(self, tracker):
        tracker.record_retrieval("user1", "spl_docs", 100, 3)
        tracker.record_retrieval("user1", "configs", 200, 7)
        dashboard = tracker.get_dashboard(hours=1)
        assert dashboard["retrieval"]["total_calls"] == 2
        assert dashboard["retrieval"]["total_chunks"] == 10


class TestToolTracking:

    def test_record_tool_execution(self, tracker):
        result = tracker.record_tool_execution("user1", "splunk_search", latency_ms=2500, success=True)
        assert result["tool"] == "splunk_search"
        assert result["success"] is True

    def test_tool_in_dashboard(self, tracker):
        tracker.record_tool_execution("user1", "search", 1000, True)
        tracker.record_tool_execution("user1", "search", 2000, False)
        dashboard = tracker.get_dashboard(hours=1)
        assert dashboard["tools"]["total_calls"] == 2
        assert dashboard["tools"]["success_rate"] == 0.5


class TestDashboard:

    def test_empty_dashboard(self, tracker):
        dashboard = tracker.get_dashboard()
        assert dashboard["llm"]["total_calls"] == 0
        assert dashboard["retrieval"]["total_calls"] == 0
        assert dashboard["tools"]["total_calls"] == 0

    def test_full_dashboard(self, tracker):
        tracker.record("llama3", "chat", 500, 200)
        tracker.record_retrieval("user1", "docs", 100, 3)
        tracker.record_tool_execution("user1", "search", 1500, True)

        dashboard = tracker.get_dashboard(hours=1)
        assert dashboard["llm"]["total_calls"] == 1
        assert dashboard["retrieval"]["total_calls"] == 1
        assert dashboard["tools"]["total_calls"] == 1
        assert "model_pricing" in dashboard
        assert "timestamp" in dashboard

    def test_top_users_in_dashboard(self, tracker):
        tracker.record("llama3", "chat", 500, 200, user_id="user1")
        tracker.record("llama3", "chat", 500, 200, user_id="user2")
        dashboard = tracker.get_dashboard(hours=1)
        assert "top_users" in dashboard
