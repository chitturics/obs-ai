"""Tests for unified SLO tracker."""

import pytest


@pytest.fixture
def tracker():
    from chat_app.slo_tracker import SLOTracker
    return SLOTracker()


@pytest.fixture
def simple_tracker():
    """Tracker with one simple SLO for controlled testing."""
    from chat_app.slo_tracker import SLOTracker, SLODefinition
    return SLOTracker(slo_definitions=[
        SLODefinition(
            name="test_slo",
            description="Test SLO",
            target=0.90,
            window_seconds=3600,
            min_samples=5,
            category="test",
        )
    ])


class TestSLORecording:

    def test_record_success(self, simple_tracker):
        for _ in range(10):
            simple_tracker.record("test_slo", success=True)
        result = simple_tracker.evaluate("test_slo")
        assert result["compliance"] == 1.0
        assert result["status"] == "met"

    def test_record_failures(self, simple_tracker):
        for _ in range(5):
            simple_tracker.record("test_slo", success=True)
        for _ in range(5):
            simple_tracker.record("test_slo", success=False)
        result = simple_tracker.evaluate("test_slo")
        assert result["compliance"] == 0.5
        assert result["status"] == "breached"  # 50% < 90%

    def test_no_data_status(self, simple_tracker):
        """Insufficient samples returns no_data."""
        simple_tracker.record("test_slo", success=True)
        result = simple_tracker.evaluate("test_slo")
        assert result["status"] == "no_data"
        assert result["total"] == 1

    def test_unknown_slo_ignored(self, simple_tracker):
        simple_tracker.record("nonexistent_slo", success=True)  # Should not raise
        assert simple_tracker.evaluate("nonexistent_slo") is None


class TestSLOStatusLevels:

    def test_met_status(self, simple_tracker):
        """95% success with 90% target = met."""
        for _ in range(95):
            simple_tracker.record("test_slo", success=True)
        for _ in range(5):
            simple_tracker.record("test_slo", success=False)
        result = simple_tracker.evaluate("test_slo")
        assert result["status"] == "met"

    def test_at_risk_status(self, simple_tracker):
        """87% success with 90% target = at_risk (within 5%)."""
        for _ in range(87):
            simple_tracker.record("test_slo", success=True)
        for _ in range(13):
            simple_tracker.record("test_slo", success=False)
        result = simple_tracker.evaluate("test_slo")
        assert result["status"] == "at_risk"

    def test_breached_status(self, simple_tracker):
        """80% success with 90% target = breached."""
        for _ in range(80):
            simple_tracker.record("test_slo", success=True)
        for _ in range(20):
            simple_tracker.record("test_slo", success=False)
        result = simple_tracker.evaluate("test_slo")
        assert result["status"] == "breached"

    def test_error_budget_remaining(self, simple_tracker):
        """When compliance is above target, error budget shows remaining margin."""
        for _ in range(98):
            simple_tracker.record("test_slo", success=True)
        for _ in range(2):
            simple_tracker.record("test_slo", success=False)
        result = simple_tracker.evaluate("test_slo")
        assert result["error_budget_remaining"] > 0  # 98% - 90% = 8%


class TestDashboard:

    def test_dashboard_no_data(self, tracker):
        dashboard = tracker.get_dashboard()
        assert dashboard["overall_status"] == "no_data"
        assert dashboard["overall_color"] == "gray"

    def test_dashboard_all_green(self, tracker):
        for slo_name in tracker.get_slo_names():
            for _ in range(20):
                tracker.record(slo_name, success=True)
        dashboard = tracker.get_dashboard()
        assert dashboard["overall_status"] == "met"
        assert dashboard["overall_color"] == "green"

    def test_dashboard_one_breached_makes_red(self, tracker):
        for slo_name in tracker.get_slo_names():
            for _ in range(20):
                tracker.record(slo_name, success=True)
        # Breach one SLO
        for _ in range(50):
            tracker.record("tool_success_rate", success=False)
        dashboard = tracker.get_dashboard()
        assert dashboard["overall_status"] == "breached"
        assert dashboard["overall_color"] == "red"
        assert len(dashboard["breached"]) >= 1

    def test_dashboard_categories(self, tracker):
        for slo_name in tracker.get_slo_names():
            for _ in range(10):
                tracker.record(slo_name, success=True)
        dashboard = tracker.get_dashboard()
        assert "system" in dashboard["categories"]
        assert "tool" in dashboard["categories"]
        assert "retrieval" in dashboard["categories"]
        assert "response" in dashboard["categories"]

    def test_dashboard_has_slo_count(self, tracker):
        dashboard = tracker.get_dashboard()
        assert dashboard["total_slos"] == len(tracker.get_slo_names())


class TestDefaultSLOs:

    def test_default_slos_registered(self, tracker):
        names = tracker.get_slo_names()
        assert "system_availability" in names
        assert "tool_success_rate" in names
        assert "retrieval_quality" in names
        assert "response_correctness" in names

    def test_evaluate_all(self, tracker):
        results = tracker.evaluate_all()
        assert len(results) == len(tracker.get_slo_names())
        for r in results:
            assert "name" in r
            assert "status" in r
            assert "target" in r


class TestCustomSLO:

    def test_add_custom_slo(self, tracker):
        from chat_app.slo_tracker import SLODefinition
        tracker.add_slo(SLODefinition(
            name="custom_metric",
            description="My custom metric",
            target=0.99,
            category="custom",
        ))
        assert "custom_metric" in tracker.get_slo_names()
        tracker.record("custom_metric", success=True)
        result = tracker.evaluate("custom_metric")
        assert result is not None
        assert result["name"] == "custom_metric"
