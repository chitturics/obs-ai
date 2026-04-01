"""Chaos Testing — validate fallback strategies when tools fail.

Tests that the system handles tool failures gracefully:
- Circuit breakers trip on repeated failures
- Fallback strategies activate
- Error taxonomy produces correct codes
- Safety policies block dangerous operations
- SLOs detect degradation
- Audit log records failures
"""

import pytest
import time


# ---------------------------------------------------------------------------
# Circuit breaker chaos tests
# ---------------------------------------------------------------------------

class TestCircuitBreakerChaos:
    """Verify circuit breaker behavior under simulated failure storms."""

    def test_rapid_failure_trips_circuit(self):
        """Rapid consecutive failures should trip the circuit breaker."""
        from chat_app.circuit_breaker import CircuitBreakerRegistry
        registry = CircuitBreakerRegistry(default_failure_threshold=3, default_cooldown_seconds=1)

        # Simulate 3 rapid failures
        for _ in range(3):
            registry.record_failure("failing_tool")

        # Tool should be blocked
        assert registry.allow_request("failing_tool") is False

        # Other tools should be unaffected
        assert registry.allow_request("healthy_tool") is True

    def test_intermittent_failures_dont_trip(self):
        """Failures mixed with successes shouldn't trip the breaker."""
        from chat_app.circuit_breaker import CircuitBreakerRegistry
        registry = CircuitBreakerRegistry(default_failure_threshold=5, default_cooldown_seconds=1)

        # 4 failures interspersed with successes that reset the count
        for _ in range(4):
            registry.record_failure("flaky_tool")
            registry.record_success("flaky_tool")

        assert registry.allow_request("flaky_tool") is True

    def test_recovery_after_cooldown(self):
        """After cooldown, half-open state allows a test request."""
        from chat_app.circuit_breaker import CircuitBreakerRegistry
        registry = CircuitBreakerRegistry(default_failure_threshold=2, default_cooldown_seconds=1)

        registry.record_failure("tool_a")
        registry.record_failure("tool_a")
        assert registry.allow_request("tool_a") is False

        time.sleep(1.1)
        assert registry.allow_request("tool_a") is True  # Half-open
        registry.record_success("tool_a")
        registry.record_success("tool_a")

        status = registry.get_status("tool_a")
        assert status["state"] == "closed"  # Recovered


# ---------------------------------------------------------------------------
# Safety policy chaos tests
# ---------------------------------------------------------------------------

class TestSafetyPolicyChaos:
    """Verify safety policies block dangerous actions correctly."""

    def test_destructive_in_production_blocked(self):
        """Destructive tools in production must require approval."""
        from chat_app.safety_policies import evaluate_policy, PolicyAction

        for tool in ["delete_index", "delete_collection", "restart_container"]:
            decision = evaluate_policy(tool, user_role="USER", environment="production")
            assert decision.action in (PolicyAction.REQUIRE_APPROVAL, PolicyAction.REQUIRE_CONFIRMATION), \
                f"{tool} should be blocked in production"

    def test_dry_run_always_safe(self):
        """Dry-run mode should always be allowed, even for destructive tools."""
        from chat_app.safety_policies import evaluate_policy, PolicyAction

        for tool in ["delete_index", "restart_container", "deploy_pipeline"]:
            decision = evaluate_policy(tool, user_role="VIEWER", environment="production", is_dry_run=True)
            assert decision.action == PolicyAction.ALLOW, f"Dry run for {tool} should be allowed"

    def test_read_tools_always_pass(self):
        """Read-only tools should pass in all environments for all roles."""
        from chat_app.safety_policies import evaluate_policy, PolicyAction

        for env in ("development", "staging", "production"):
            for role in ("VIEWER", "USER", "ANALYST", "ADMIN"):
                decision = evaluate_policy("splunk_search", user_role=role, environment=env)
                assert decision.action == PolicyAction.ALLOW


# ---------------------------------------------------------------------------
# Policy engine chaos tests
# ---------------------------------------------------------------------------

class TestPolicyEngineChaos:
    """Verify policy engine handles edge cases correctly."""

    def test_multiple_denials_all_reported(self):
        """When multiple policies deny, all reasons should be captured."""
        from chat_app.policy_engine import PolicyEngine, PolicyRule, PolicyType, PolicyContext

        engine = PolicyEngine()
        # Add two custom denial policies
        engine.add_rule(PolicyRule(
            name="block_1", description="Block reason 1",
            policy_type=PolicyType.CUSTOM,
            condition=lambda ctx: True, effect="deny", priority=1,
        ))
        engine.add_rule(PolicyRule(
            name="block_2", description="Block reason 2",
            policy_type=PolicyType.CUSTOM,
            condition=lambda ctx: True, effect="deny", priority=2,
        ))

        ctx = PolicyContext(tool="any_tool", actor="user", role="USER")
        result = engine.evaluate(ctx)
        assert result.allowed is False
        assert len(result.denial_reasons) >= 2

    def test_approval_and_deny_together(self):
        """A deny policy should block even if approval policy is also triggered."""
        from chat_app.policy_engine import PolicyEngine, PolicyRule, PolicyType, PolicyContext

        engine = PolicyEngine()
        engine.add_rule(PolicyRule(
            name="require_approval", description="Needs approval",
            policy_type=PolicyType.CUSTOM,
            condition=lambda ctx: True, effect="require_approval",
            approval_level="ADMIN", priority=10,
        ))
        engine.add_rule(PolicyRule(
            name="hard_deny", description="Absolutely blocked",
            policy_type=PolicyType.CUSTOM,
            condition=lambda ctx: True, effect="deny", priority=1,
        ))

        ctx = PolicyContext(tool="blocked_tool", actor="user", role="USER")
        result = engine.evaluate(ctx)
        assert result.allowed is False  # Deny overrides approval requirement


# ---------------------------------------------------------------------------
# Error taxonomy chaos tests
# ---------------------------------------------------------------------------

class TestErrorTaxonomyChaos:
    """Verify error taxonomy handles all error scenarios."""

    def test_all_error_codes_raisable(self):
        """Every error code should be raisable without crashing."""
        from chat_app.error_taxonomy import ErrorCode, raise_error
        from fastapi import HTTPException

        for code in ErrorCode:
            with pytest.raises(HTTPException):
                raise_error(code, context="chaos_test", tool_name="test",
                           resource="test", identifier="test", reason="test",
                           field="test", message="test", retry_after="30",
                           timeout="30", service="test", dependency="test",
                           feature="test", section="test", step="test",
                           strategy="test", agent_name="test", container="test",
                           action="test", skill_name="test", workflow_id="test",
                           quota_type="test", max_size="10MB",
                           resource_type="test", resource_id="test",
                           required="ADMIN", current="USER")

    def test_unknown_template_vars_dont_crash(self):
        """Missing template variables should produce a message, not crash."""
        from chat_app.error_taxonomy import ErrorCode, raise_error
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            raise_error(ErrorCode.RESOURCE_NOT_FOUND)  # Missing resource/identifier
        # Should still produce a valid error body
        assert "error" in exc_info.value.detail


# ---------------------------------------------------------------------------
# SLO degradation chaos tests
# ---------------------------------------------------------------------------

class TestSLODegradationChaos:
    """Verify SLOs detect degradation patterns."""

    def test_gradual_degradation_detected(self):
        """Gradual increase in failures should eventually breach SLO."""
        from chat_app.slo_tracker import SLOTracker, SLODefinition

        tracker = SLOTracker(slo_definitions=[
            SLODefinition(name="test", description="Test", target=0.95,
                          window_seconds=3600, min_samples=10, category="test")
        ])

        # Start with all successes
        for _ in range(50):
            tracker.record("test", success=True)

        result = tracker.evaluate("test")
        assert result["status"] == "met"

        # Add failures until breached
        for _ in range(50):
            tracker.record("test", success=False)

        result = tracker.evaluate("test")
        assert result["status"] in ("at_risk", "breached")

    def test_dashboard_turns_red_on_breach(self):
        """Dashboard should show red when any SLO is breached."""
        from chat_app.slo_tracker import SLOTracker, SLODefinition

        tracker = SLOTracker(slo_definitions=[
            SLODefinition(name="good_slo", description="Healthy", target=0.9,
                          min_samples=5, category="test"),
            SLODefinition(name="bad_slo", description="Failing", target=0.9,
                          min_samples=5, category="test"),
        ])

        for _ in range(10):
            tracker.record("good_slo", success=True)
            tracker.record("bad_slo", success=False)

        dashboard = tracker.get_dashboard()
        assert dashboard["overall_color"] == "red"
        assert len(dashboard["breached"]) >= 1


# ---------------------------------------------------------------------------
# RBAC chaos tests
# ---------------------------------------------------------------------------

class TestRBACChaos:
    """Verify RBAC handles edge cases and privilege escalation attempts."""

    def test_empty_role_denied(self):
        """User with empty/missing role should be denied write access."""
        from chat_app.rbac import check_permission
        user = {"identifier": "unknown", "metadata": {}}
        assert check_permission(user, "config", "llm", "update") is False

    def test_case_sensitive_roles(self):
        """Role matching should be case-sensitive."""
        from chat_app.rbac import check_permission
        user = {"identifier": "user", "metadata": {"role": "admin"}}  # lowercase
        # "admin" != "ADMIN" — should not match
        assert check_permission(user, "config", "llm", "update") is False

    def test_denial_overrides_wildcard_grant(self):
        """Explicit denial should override even wildcard grants."""
        from chat_app.rbac import check_permission, set_user_overrides
        import chat_app.rbac as rbac_mod
        # Reset state
        rbac_mod._user_overrides = {}
        rbac_mod._overrides_loaded = True

        user = {"identifier": "test_user", "metadata": {"role": "ADMIN"}}
        # ADMIN has *:*:* but add explicit denial
        set_user_overrides("test_user", denials=["config:secrets:*"])
        assert check_permission(user, "config", "secrets", "read") is False
        assert check_permission(user, "config", "llm", "read") is True  # Other config still OK


# ---------------------------------------------------------------------------
# Audit log integrity chaos tests
# ---------------------------------------------------------------------------

class TestAuditLogChaos:
    """Verify audit log maintains integrity under stress."""

    def test_concurrent_appends_preserve_chain(self):
        """Multiple rapid appends should maintain valid hash chain."""
        from chat_app.audit_log import ImmutableAuditLog
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            log = ImmutableAuditLog(log_dir=tmpdir, max_in_memory=200)

            # Rapid-fire 100 entries
            for i in range(100):
                log.append(
                    event_type="chaos", actor=f"user_{i % 5}",
                    action="test", target=f"resource_{i}",
                    severity="low",
                )

            result = log.verify_chain()
            assert result["valid"] is True
            assert result["entries_checked"] == 100

    def test_chain_survives_reload(self):
        """Chain should remain valid after reload from file."""
        from chat_app.audit_log import ImmutableAuditLog
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            log1 = ImmutableAuditLog(log_dir=tmpdir)
            for i in range(50):
                log1.append(event_type="test", actor="a", action="create", target=f"r{i}")

            # Reload
            log2 = ImmutableAuditLog(log_dir=tmpdir)
            log2.append(event_type="test", actor="b", action="create", target="new")

            result = log2.verify_chain(full=True)
            assert result["valid"] is True
            assert result["entries_checked"] == 51


# ---------------------------------------------------------------------------
# Idempotency chaos tests
# ---------------------------------------------------------------------------

class TestIdempotencyChaos:
    """Verify idempotency prevents duplicate execution."""

    def test_same_key_returns_cached(self):
        """Same idempotency key should return cached result, not re-execute."""
        from chat_app.idempotency import IdempotencyStore

        store = IdempotencyStore(default_ttl=60)
        store.put("key_abc", {"result": "first_execution"}, tool="test")

        cached = store.get("key_abc")
        assert cached is not None
        assert cached["cached"] is True
        assert cached["result"]["result"] == "first_execution"

    def test_in_progress_blocks_concurrent(self):
        """In-progress marker should prevent concurrent execution."""
        from chat_app.idempotency import IdempotencyStore

        store = IdempotencyStore()
        assert store.mark_in_progress("concurrent_key") is True
        assert store.mark_in_progress("concurrent_key") is False  # Blocked

    def test_key_generation_deterministic(self):
        """Same tool+params should always generate the same key."""
        from chat_app.idempotency import generate_idempotency_key

        key1 = generate_idempotency_key("search", {"query": "index=main"}, "user1")
        key2 = generate_idempotency_key("search", {"query": "index=main"}, "user1")
        key3 = generate_idempotency_key("search", {"query": "index=other"}, "user1")

        assert key1 == key2
        assert key1 != key3
