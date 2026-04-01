"""Architecture tests — verify ADR compliance.

Tests that enforce the architectural decisions documented in
docs/ARCHITECTURE_DECISIONS.md. These are NOT unit tests —
they verify structural properties of the codebase.
"""

import pytest


class TestADR001_ExceptionHandling:
    """ADR-001: No blind exceptions without logging."""

    def test_zero_bare_except(self):
        """No bare 'except:' (without type) in any module."""
        import glob, re
        bare = []
        for f in glob.glob("chat_app/*.py") + glob.glob("chat_app/handlers/*.py"):
            for i, line in enumerate(open(f), 1):
                if re.match(r'^\s+except:\s*$', line):
                    bare.append(f"{f}:{i}")
        assert not bare, f"Bare except found: {bare}"


class TestADR003_ClarificationProtocol:
    """ADR-003: Agent clarification flows through the pipeline."""

    def test_orchestration_result_has_clarification_fields(self):
        from chat_app.orchestration_strategies import OrchestrationResult
        from dataclasses import fields
        field_names = [f.name for f in fields(OrchestrationResult)]
        assert "clarification_needed" in field_names
        assert "clarification_questions" in field_names
        assert "clarification_agent" in field_names

    def test_dispatcher_result_has_clarification_fields(self):
        from chat_app.agent_dispatcher import AgentDispatchResult
        from dataclasses import fields
        field_names = [f.name for f in fields(AgentDispatchResult)]
        assert "clarification_needed" in field_names
        assert "clarification_questions" in field_names

    def test_message_handler_checks_clarification(self):
        content = open("chat_app/message_handler.py").read()
        assert "clarification_needed" in content
        assert "clarification_questions" in content


class TestADR005_OIDCTrustModel:
    """ADR-005: OIDC JWT validation includes algorithm safety."""

    def test_rejects_none_algorithm(self):
        from chat_app.auth_providers import OIDCProvider
        import base64, json
        provider = OIDCProvider({"issuer_url": "https://idp.example.com"})
        header = base64.urlsafe_b64encode(json.dumps({"alg": "none"}).encode()).decode().rstrip("=")
        payload = base64.urlsafe_b64encode(json.dumps({"sub": "user", "iss": "https://idp.example.com"}).encode()).decode().rstrip("=")
        sig = base64.urlsafe_b64encode(b"").decode().rstrip("=")
        token = f"{header}.{payload}.{sig}"
        assert provider._decode_jwt_unverified(token) == {}

    def test_rejects_hs256_algorithm(self):
        from chat_app.auth_providers import OIDCProvider
        import base64, json
        provider = OIDCProvider({"issuer_url": "https://idp.example.com"})
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).decode().rstrip("=")
        payload = base64.urlsafe_b64encode(json.dumps({"sub": "user", "iss": "https://idp.example.com"}).encode()).decode().rstrip("=")
        sig = base64.urlsafe_b64encode(b"fakesig").decode().rstrip("=")
        token = f"{header}.{payload}.{sig}"
        assert provider._decode_jwt_unverified(token) == {}

    def test_nonce_uses_timing_safe_comparison(self):
        content = open("chat_app/auth_providers.py").read()
        assert "compare_digest" in content


class TestADR007_WorkflowStateMachine:
    """ADR-007: Formal state machine with validated transitions."""

    def test_valid_transitions(self):
        from chat_app.workflow_state_machine import StateMachine, WorkflowState
        sm = StateMachine()
        sm.transition("wf1", WorkflowState.CREATED, WorkflowState.RUNNING)
        sm.transition("wf1", WorkflowState.RUNNING, WorkflowState.WAITING_INPUT)
        sm.transition("wf1", WorkflowState.WAITING_INPUT, WorkflowState.RUNNING)
        sm.transition("wf1", WorkflowState.RUNNING, WorkflowState.COMPLETED)

    def test_invalid_transition_raises(self):
        from chat_app.workflow_state_machine import StateMachine, WorkflowState, InvalidTransitionError
        sm = StateMachine()
        with pytest.raises(InvalidTransitionError):
            sm.transition("wf1", WorkflowState.COMPLETED, WorkflowState.RUNNING)

    def test_terminal_states(self):
        from chat_app.workflow_state_machine import StateMachine, WorkflowState
        sm = StateMachine()
        assert sm.is_terminal(WorkflowState.COMPLETED)
        assert sm.is_terminal(WorkflowState.FAILED)
        assert sm.is_terminal(WorkflowState.CANCELLED)
        assert not sm.is_terminal(WorkflowState.RUNNING)

    def test_transition_history(self):
        from chat_app.workflow_state_machine import StateMachine, WorkflowState
        sm = StateMachine()
        sm.transition("wf1", WorkflowState.CREATED, WorkflowState.RUNNING, reason="start")
        sm.transition("wf1", WorkflowState.RUNNING, WorkflowState.COMPLETED, reason="done")
        history = sm.get_history("wf1")
        assert len(history) == 2
        assert history[0]["to"] == "completed"
        assert history[1]["to"] == "running"


class TestADR004_ConfigPersistence:
    """ADR-004: Config writes to persistent volume."""

    def test_config_manager_uses_persistent_path(self):
        content = open("chat_app/config_manager.py").read()
        assert "/app/data/config.yaml" in content
        assert "persistent_path" in content

    def test_compose_has_app_data_volume(self):
        content = open("docker-compose.yml").read()
        assert "app_data:/app/data" in content
        assert "app_data:" in content


class TestADR006_LearningGovernance:
    """ADR-006: Learning goes through governance with rollback."""

    def test_auto_rollback_on_quality_drop(self):
        from chat_app.learning_governance import LearningGovernor
        g = LearningGovernor(min_quality_delta=-0.05)
        with g.learning_session("test") as s:
            s.record_quality(before=0.9, after=0.7)  # -0.2 drop
        history = g.get_history()
        assert history[0]["rolled_back"] is True

    def test_model_customization_requires_approval(self):
        from chat_app.learning_governance import LearningGovernor
        g = LearningGovernor()
        with g.learning_session("model_customization") as s:
            s.record_quality(before=0.8, after=0.9)
        history = g.get_history()
        assert history[0]["approved"] is False  # Needs explicit approval
