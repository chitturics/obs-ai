"""Tests for chat_app/response_generator.py — optimizer bypass formatting."""
import pytest
from chat_app.response_generator import _format_optimizer_bypass_response


class TestFormatOptimizerBypassResponse:
    """Test _format_optimizer_bypass_response for all input formats."""

    def test_none_input_returns_none(self):
        assert _format_optimizer_bypass_response(None, "index=main", "optimize") is None

    def test_empty_dict_returns_none(self):
        assert _format_optimizer_bypass_response({}, "index=main", "optimize") is None

    def test_unchanged_query_returns_none(self):
        result = _format_optimizer_bypass_response(
            {"optimization": {"optimized_query": "index=main | stats count"}},
            "index=main | stats count",
            "optimize",
        )
        assert result is None

    def test_remote_optimizer_dict_optimization(self):
        opt_result = {
            "optimization": {
                "optimized_query": "| tstats count WHERE index=main by host",
                "strategy": "tstats_conversion",
                "performance_notes": ["Converted stats to tstats for 10x speedup"],
                "suggestions": ["Add time range for better performance"],
            }
        }
        result = _format_optimizer_bypass_response(
            opt_result, "index=main | stats count by host", "optimize"
        )
        assert result is not None
        assert "tstats" in result

    def test_remote_optimizer_dict_improvement(self):
        opt_result = {
            "improvement": {
                "improved_query": "index=main | stats count by host | sort -count",
                "notes": ["Added sorting for better readability"],
            }
        }
        result = _format_optimizer_bypass_response(
            opt_result, "index=main | stats count by host", "optimize"
        )
        assert result is not None
        assert "sort" in result

    def test_remote_optimizer_generated_query(self):
        opt_result = {
            "generated_query": "index=security sourcetype=syslog | stats count by src_ip",
        }
        result = _format_optimizer_bypass_response(
            opt_result, "show me security events by IP", "optimize"
        )
        assert result is not None
        assert "index=security" in result

    def test_top_level_optimized_query(self):
        opt_result = {
            "optimized_query": "| tstats count WHERE index=main by sourcetype",
        }
        result = _format_optimizer_bypass_response(
            opt_result, "index=main | stats count by sourcetype", "optimize"
        )
        assert result is not None
        assert "tstats" in result

    def test_review_action_format(self):
        opt_result = {
            "optimization": {
                "optimized_query": "index=main | stats count by host",
            },
            "review": {
                "status": "valid",
                "risk_score": 2,
                "errors": [],
                "warnings": ["Consider adding time range"],
            },
        }
        result = _format_optimizer_bypass_response(
            opt_result, "index=main | stats count", "review"
        )
        assert result is not None

    def test_dataclass_input(self):
        """Test with an object that has .optimized attribute (like OptimizedQuery)."""
        class MockOptimized:
            optimized = "| tstats count WHERE index=main by host"
            strategy = "tstats_conversion"
            performance_notes = ["Much faster"]

        result = _format_optimizer_bypass_response(
            MockOptimized(), "index=main | stats count by host", "optimize"
        )
        assert result is not None
        assert "tstats" in result

    def test_dataclass_with_enum_strategy(self):
        """Test with strategy that has a .value attribute (enum-like)."""
        class MockEnum:
            value = "tstats_rewrite"

        class MockOptimized:
            optimized = "| tstats count WHERE index=main by host"
            strategy = MockEnum()
            performance_notes = []

        result = _format_optimizer_bypass_response(
            MockOptimized(), "index=main | stats count by host", "optimize"
        )
        assert result is not None

    def test_dataclass_none_optimized_returns_none(self):
        class MockOptimized:
            optimized = None
            strategy = None
            performance_notes = []

        result = _format_optimizer_bypass_response(
            MockOptimized(), "index=main", "optimize"
        )
        assert result is None
