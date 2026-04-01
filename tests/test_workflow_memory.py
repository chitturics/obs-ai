"""Tests for chat_app.workflow_memory — Cross-session workflow arc tracking."""

import time
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

from chat_app.workflow_memory import (
    WorkflowStep,
    WorkflowArc,
    WorkflowMemory,
    get_workflow_memory,
)


# ---------------------------------------------------------------------------
# WorkflowStep tests
# ---------------------------------------------------------------------------

class TestWorkflowStep:
    def test_creation(self):
        step = WorkflowStep(
            query="show me failed logins",
            answer_summary="Found 42 failed logins",
            intent="spl_generation",
            timestamp="2025-01-01T00:00:00Z",
            session_id="sess_1",
        )
        assert step.query == "show me failed logins"
        assert step.intent == "spl_generation"
        assert step.confidence == 0.0
        assert step.resources_used == []

    def test_creation_with_optional_fields(self):
        step = WorkflowStep(
            query="optimize my search",
            answer_summary="Added tstats",
            intent="spl_optimization",
            timestamp="2025-01-01T00:00:00Z",
            session_id="sess_2",
            confidence=0.85,
            resources_used=["spl_docs", "org_repo"],
        )
        assert step.confidence == 0.85
        assert len(step.resources_used) == 2


# ---------------------------------------------------------------------------
# WorkflowArc tests
# ---------------------------------------------------------------------------

class TestWorkflowArc:
    def test_creation(self):
        arc = WorkflowArc(id="arc_001", user_id="user1", title="failed login investigation")
        assert arc.id == "arc_001"
        assert arc.status == "active"
        assert arc.steps == []

    def test_add_step(self):
        arc = WorkflowArc(id="arc_002", user_id="user1", title="test arc")
        step = WorkflowStep(
            query="test", answer_summary="answer", intent="general_qa",
            timestamp="2025-01-01T00:00:00Z", session_id="s1"
        )
        arc.add_step(step)
        assert len(arc.steps) == 1
        assert arc.last_activity != ""

    def test_summary_empty(self):
        arc = WorkflowArc(id="arc_003", user_id="user1", title="empty arc")
        assert arc.summary() == ""

    def test_summary_with_steps(self):
        arc = WorkflowArc(id="arc_004", user_id="user1", title="test arc")
        for i in range(5):
            arc.add_step(WorkflowStep(
                query=f"query {i}", answer_summary=f"answer {i}",
                intent="general_qa", timestamp="2025-01-01T00:00:00Z",
                session_id="s1"
            ))
        summary = arc.summary()
        assert "test arc" in summary
        assert "5 steps" in summary
        # Should show only last 3 steps
        assert "query 2" in summary
        assert "query 4" in summary


# ---------------------------------------------------------------------------
# WorkflowMemory tests
# ---------------------------------------------------------------------------

class TestWorkflowMemory:
    def test_record_step_creates_arc(self):
        wm = WorkflowMemory()
        arc = wm.record_step("user1", "show failed logins", "found 42",
                             "spl_generation", "sess_1")
        assert arc is not None
        assert len(arc.steps) == 1
        assert arc.user_id == "user1"

    def test_record_step_appends_to_existing_arc(self):
        wm = WorkflowMemory()
        arc = wm.record_step("user1", "show failed logins", "found 42",
                             "spl_generation", "sess_1")
        arc2 = wm.record_step("user1", "optimize the search", "added tstats",
                              "spl_optimization", "sess_2", workflow_arc=arc)
        assert arc2 is arc
        assert len(arc.steps) == 2

    def test_detect_continuation_no_arcs(self):
        wm = WorkflowMemory()
        result = wm.detect_continuation("test query", "user1", "general_qa")
        assert result is None

    def test_detect_continuation_with_overlap(self):
        wm = WorkflowMemory()
        wm.record_step("user1", "show me failed login attempts by src_ip",
                        "found logins", "spl_generation", "sess_1")
        # Query with significant token overlap should match
        match = wm.detect_continuation(
            "failed login attempts from specific src_ip", "user1", "spl_generation"
        )
        assert match is not None

    def test_detect_continuation_no_match(self):
        wm = WorkflowMemory()
        wm.record_step("user1", "show me failed login attempts",
                        "found logins", "spl_generation", "sess_1")
        # Completely different query
        match = wm.detect_continuation(
            "configure props.conf for syslog", "user1", "config_lookup"
        )
        assert match is None

    def test_stale_arc_detection(self):
        wm = WorkflowMemory(stale_hours=1)
        arc = wm.record_step("user1", "test query", "answer",
                             "general_qa", "sess_1")
        # Manually set last_activity to 2 hours ago
        arc.last_activity = (
            datetime.now(timezone.utc) - timedelta(hours=2)
        ).isoformat()
        # Should not match because arc is stale
        match = wm.detect_continuation("test query again", "user1", "general_qa")
        assert match is None
        assert arc.status == "stalled"

    def test_max_arcs_per_user_cap(self):
        wm = WorkflowMemory(max_arcs_per_user=3)
        for i in range(5):
            wm.record_step("user1", f"unique query number {i}",
                           f"answer {i}", "general_qa", f"sess_{i}")
        assert len(wm._arcs["user1"]) == 3

    def test_get_active_arcs(self):
        wm = WorkflowMemory()
        wm.record_step("user1", "query 1", "answer 1", "general_qa", "s1")
        wm.record_step("user1", "query 2", "answer 2", "general_qa", "s2")
        arcs = wm.get_active_arcs("user1")
        assert len(arcs) == 2

    def test_get_active_arcs_empty(self):
        wm = WorkflowMemory()
        arcs = wm.get_active_arcs("nonexistent_user")
        assert arcs == []

    def test_get_suggestions(self):
        wm = WorkflowMemory()
        wm.record_step("user1", "show failed logins", "found 42",
                        "spl_generation", "sess_1")
        wm.record_step("user1", "optimize dashboard", "added panels",
                        "general_qa", "sess_2")
        suggestions = wm.get_suggestions("user1")
        assert len(suggestions) == 2
        assert suggestions[0]["title"] == "show failed logins"
        assert "steps" in suggestions[0]
        assert "last_activity" in suggestions[0]

    def test_get_suggestions_limit(self):
        wm = WorkflowMemory()
        for i in range(10):
            wm.record_step("user1", f"query {i}", f"answer {i}",
                           "general_qa", f"s_{i}")
        suggestions = wm.get_suggestions("user1")
        # Should return at most 3
        assert len(suggestions) <= 3


# ---------------------------------------------------------------------------
# Singleton tests
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_get_workflow_memory_returns_same_instance(self):
        import chat_app.workflow_memory as mod
        mod._workflow_memory = None  # Reset
        wm1 = get_workflow_memory()
        wm2 = get_workflow_memory()
        assert wm1 is wm2
        mod._workflow_memory = None  # Cleanup

    def test_workflow_memory_default_config(self):
        import chat_app.workflow_memory as mod
        mod._workflow_memory = None
        wm = get_workflow_memory()
        assert wm._max_arcs == 20
        assert wm._stale_hours == 72
        mod._workflow_memory = None
