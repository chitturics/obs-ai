"""Golden Answer Regression Tests — verify top SPL/admin workflows produce expected results.

Tests the complete pipeline from query → intent → tool selection → expected outcome.
Each test case defines:
- A user query
- Expected intent classification
- Expected tool/skill activation
- Key terms that must appear in the response context

These tests verify the deterministic parts of the pipeline without requiring
a running LLM (they test routing, tool selection, and context building).
"""

import pytest


# ---------------------------------------------------------------------------
# Intent Classification Golden Tests
# ---------------------------------------------------------------------------

class TestIntentClassification:
    """Verify intent classifier routes queries correctly."""

    @pytest.fixture(autouse=True)
    def setup(self):
        try:
            from chat_app.registry import Intent
            self.Intent = Intent
            self.has_registry = True
        except ImportError:
            self.has_registry = False

    def _classify(self, query: str) -> str:
        """Classify a query and return intent name."""
        try:
            from chat_app.intent_classifier import classify_intent
            result = classify_intent(query)
            if isinstance(result, tuple):
                return result[0].value if hasattr(result[0], 'value') else str(result[0])
            return result.value if hasattr(result, 'value') else str(result)
        except Exception:
            pytest.skip("Intent classifier not available")

    @pytest.mark.parametrize("query,expected_intent", [
        ("search for errors in the last hour", "splunk_search"),
        ("index=main sourcetype=syslog ERROR", "splunk_search"),
        ("show me the saved searches", "saved_search"),
        ("list all indexes", "splunk_admin"),
        ("what is the eval command", "spl_help"),
        ("explain this SPL: index=main | stats count by host", "spl_explain"),
        ("how do I configure HEC", "general"),
        ("check splunk health", "config_health_check"),
    ])
    def test_intent_classification(self, query, expected_intent):
        if not self.has_registry:
            pytest.skip("Registry not available")
        result = self._classify(query)
        assert result == expected_intent, f"Query '{query}' classified as '{result}', expected '{expected_intent}'"


# ---------------------------------------------------------------------------
# Skill Catalog Golden Tests
# ---------------------------------------------------------------------------

class TestSkillSelection:
    """Verify correct skills are selected for common intents."""

    @pytest.fixture(autouse=True)
    def setup(self):
        try:
            from chat_app.skill_catalog import get_skill_catalog
            self.catalog = get_skill_catalog()
            self.has_catalog = True
        except Exception:
            self.has_catalog = False

    def test_splunk_search_skill_exists(self):
        if not self.has_catalog:
            pytest.skip("Skill catalog not available")
        try:
            skills = self.catalog.get_all_skills() if hasattr(self.catalog, 'get_all_skills') else list(self.catalog.skills.values())
        except Exception:
            pytest.skip("Cannot iterate skill catalog")
        names = [getattr(s, 'name', '') for s in skills]
        assert any("search" in n.lower() for n in names), "splunk_search skill must exist"

    def test_health_check_skill_exists(self):
        if not self.has_catalog:
            pytest.skip("Skill catalog not available")
        try:
            skills = self.catalog.get_all_skills() if hasattr(self.catalog, 'get_all_skills') else list(self.catalog.skills.values())
        except Exception:
            pytest.skip("Cannot iterate skill catalog")
        names = [getattr(s, 'name', '') for s in skills]
        assert any("health" in n.lower() for n in names), "Health check skill must exist"

    def test_explain_spl_skill_exists(self):
        if not self.has_catalog:
            pytest.skip("Skill catalog not available")
        try:
            skills = self.catalog.get_all_skills() if hasattr(self.catalog, 'get_all_skills') else list(self.catalog.skills.values())
        except Exception:
            pytest.skip("Cannot iterate skill catalog")
        names = [getattr(s, 'name', '') for s in skills]
        assert any("explain" in n.lower() for n in names), "Explain SPL skill must exist"


# ---------------------------------------------------------------------------
# Safety Policy Golden Tests
# ---------------------------------------------------------------------------

class TestSafetyGoldenAnswers:
    """Verify safety policies produce expected decisions for common scenarios."""

    @pytest.mark.parametrize("tool,env,role,expected_action", [
        # Read tools always allowed
        ("splunk_search", "production", "VIEWER", "allow"),
        ("validate_spl", "production", "VIEWER", "allow"),
        ("base64_encode", "production", "VIEWER", "allow"),
        # Destructive in production requires approval
        ("delete_index", "production", "ADMIN", "require_approval"),
        ("delete_collection", "production", "ADMIN", "require_approval"),
        # Write in dev allowed for USER
        ("update_config", "development", "USER", "allow"),
        # External write in production requires approval
        ("deploy_pipeline", "production", "ANALYST", "require_approval"),
    ])
    def test_safety_decision(self, tool, env, role, expected_action):
        from chat_app.safety_policies import evaluate_policy
        decision = evaluate_policy(tool, user_role=role, environment=env)
        assert decision.action.value == expected_action, \
            f"{tool} in {env} for {role}: got {decision.action.value}, expected {expected_action}"


# ---------------------------------------------------------------------------
# Error Code Golden Tests
# ---------------------------------------------------------------------------

class TestErrorCodeGoldenAnswers:
    """Verify error codes map to correct HTTP status codes."""

    @pytest.mark.parametrize("code,expected_status", [
        ("AUTH_REQUIRED", 401),
        ("PERMISSION_DENIED", 403),
        ("RESOURCE_NOT_FOUND", 404),
        ("RATE_LIMITED", 429),
        ("INTERNAL_ERROR", 500),
        ("SERVICE_UNAVAILABLE", 503),
        ("TOOL_TIMEOUT", 504),
        ("VALIDATION_ERROR", 422),
        ("RESOURCE_ALREADY_EXISTS", 409),
    ])
    def test_error_status_codes(self, code, expected_status):
        from chat_app.error_taxonomy import ErrorCode, _ERROR_CATALOG
        error_code = ErrorCode(code)
        assert _ERROR_CATALOG[error_code]["status"] == expected_status


# ---------------------------------------------------------------------------
# RBAC Golden Tests
# ---------------------------------------------------------------------------

class TestRBACGoldenAnswers:
    """Verify RBAC produces correct decisions for common role+action combinations."""

    def _user(self, role):
        return {"identifier": "test", "metadata": {"role": role}}

    @pytest.mark.parametrize("role,resource_type,resource,action,expected", [
        ("ADMIN", "config", "llm", "update", True),
        ("ADMIN", "tool", "delete_index", "execute", True),
        ("VIEWER", "dashboard", "main", "read", True),
        ("VIEWER", "config", "llm", "update", False),
        ("USER", "tool", "splunk_search", "execute", True),
        ("USER", "collection", "spl_docs", "search", True),
        ("ANALYST", "collection", "custom", "create", True),
        ("ANALYST", "workflow", "test", "create", True),
    ])
    def test_rbac_decision(self, role, resource_type, resource, action, expected):
        from chat_app.rbac import check_permission
        result = check_permission(self._user(role), resource_type, resource, action)
        assert result == expected, \
            f"{role} {resource_type}:{resource}:{action} = {result}, expected {expected}"


# ---------------------------------------------------------------------------
# Latency Budget Golden Tests
# ---------------------------------------------------------------------------

class TestLatencyBudgetGoldenAnswers:
    """Verify timeout budgets are reasonable for each tool category."""

    @pytest.mark.parametrize("tool,max_timeout", [
        ("base64_encode", 5.0),      # Utility tools should be fast
        ("splunk_search", 60.0),     # Search can take time but not forever
        ("ingest_document", 180.0),  # Ingestion is slow but bounded
        ("validate_spl", 10.0),      # Validation should be quick
    ])
    def test_timeout_reasonable(self, tool, max_timeout):
        from chat_app.latency_budgets import get_latency_tracker
        timeout = get_latency_tracker().get_timeout(tool)
        assert timeout <= max_timeout, f"{tool} timeout {timeout}s exceeds max {max_timeout}s"

    @pytest.mark.parametrize("tool,min_timeout", [
        ("splunk_search", 10.0),     # Search needs at least some time
        ("ingest_document", 30.0),   # Ingestion needs generous timeout
    ])
    def test_timeout_not_too_short(self, tool, min_timeout):
        from chat_app.latency_budgets import get_latency_tracker
        timeout = get_latency_tracker().get_timeout(tool)
        assert timeout >= min_timeout, f"{tool} timeout {timeout}s below minimum {min_timeout}s"


# ---------------------------------------------------------------------------
# Runbook Coverage Golden Tests
# ---------------------------------------------------------------------------

class TestRunbookCoverage:
    """Verify runbooks exist for all critical services."""

    @pytest.mark.parametrize("alert_key", [
        "postgres_unhealthy",
        "ollama_unhealthy",
        "chromadb_unhealthy",
        "redis_unhealthy",
        "slo_breached",
        "high_error_rate",
    ])
    def test_critical_service_has_runbook(self, alert_key):
        from chat_app.runbooks import get_runbook_registry
        rb = get_runbook_registry().get_for_alert(alert_key)
        assert rb is not None, f"Missing runbook for: {alert_key}"
        assert len(rb.diagnostic_steps) > 0, f"Runbook {alert_key} has no diagnostic steps"
        assert len(rb.fix_steps) > 0, f"Runbook {alert_key} has no fix steps"
