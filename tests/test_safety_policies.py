"""Tests for safety policies — per-tool execution policies."""

import pytest


class TestToolClassification:

    def test_read_only_tools(self):
        from chat_app.safety_policies import get_tool_safety_level, ToolSafetyLevel
        assert get_tool_safety_level("splunk_search") == ToolSafetyLevel.READ_ONLY
        assert get_tool_safety_level("validate_spl") == ToolSafetyLevel.READ_ONLY
        assert get_tool_safety_level("base64_encode") == ToolSafetyLevel.READ_ONLY

    def test_write_tools(self):
        from chat_app.safety_policies import get_tool_safety_level, ToolSafetyLevel
        assert get_tool_safety_level("update_config") == ToolSafetyLevel.WRITE
        assert get_tool_safety_level("toggle_feature") == ToolSafetyLevel.WRITE

    def test_external_write_tools(self):
        from chat_app.safety_policies import get_tool_safety_level, ToolSafetyLevel
        assert get_tool_safety_level("update_saved_search") == ToolSafetyLevel.EXTERNAL_WRITE
        assert get_tool_safety_level("deploy_pipeline") == ToolSafetyLevel.EXTERNAL_WRITE

    def test_destructive_tools(self):
        from chat_app.safety_policies import get_tool_safety_level, ToolSafetyLevel
        assert get_tool_safety_level("delete_collection") == ToolSafetyLevel.DESTRUCTIVE
        assert get_tool_safety_level("delete_index") == ToolSafetyLevel.DESTRUCTIVE
        assert get_tool_safety_level("restart_container") == ToolSafetyLevel.DESTRUCTIVE

    def test_unknown_defaults_to_write(self):
        from chat_app.safety_policies import get_tool_safety_level, ToolSafetyLevel
        assert get_tool_safety_level("unknown_tool") == ToolSafetyLevel.WRITE

    def test_custom_classification(self):
        from chat_app.safety_policies import classify_tool, get_tool_safety_level, ToolSafetyLevel
        classify_tool("my_custom_tool", ToolSafetyLevel.DESTRUCTIVE)
        assert get_tool_safety_level("my_custom_tool") == ToolSafetyLevel.DESTRUCTIVE


class TestPolicyEvaluation:

    def test_read_only_always_allowed(self):
        from chat_app.safety_policies import evaluate_policy, PolicyAction
        for env in ("development", "staging", "production"):
            decision = evaluate_policy("splunk_search", user_role="VIEWER", environment=env)
            assert decision.action == PolicyAction.ALLOW

    def test_dry_run_always_allowed(self):
        from chat_app.safety_policies import evaluate_policy, PolicyAction
        decision = evaluate_policy("delete_index", user_role="VIEWER",
                                   environment="production", is_dry_run=True)
        assert decision.action == PolicyAction.ALLOW
        assert decision.requires_dry_run is True

    def test_pre_approved_allowed(self):
        from chat_app.safety_policies import evaluate_policy, PolicyAction
        decision = evaluate_policy("delete_index", user_role="USER",
                                   environment="production", is_approved=True)
        assert decision.action == PolicyAction.ALLOW

    def test_write_in_dev_allowed(self):
        from chat_app.safety_policies import evaluate_policy, PolicyAction
        decision = evaluate_policy("update_config", user_role="USER", environment="development")
        assert decision.action == PolicyAction.ALLOW

    def test_write_in_production_needs_confirmation(self):
        from chat_app.safety_policies import evaluate_policy, PolicyAction
        decision = evaluate_policy("update_config", user_role="USER", environment="production")
        assert decision.action == PolicyAction.REQUIRE_CONFIRMATION

    def test_write_in_production_analyst_bypasses(self):
        """ANALYST role bypasses confirmation for WRITE tools."""
        from chat_app.safety_policies import evaluate_policy, PolicyAction
        decision = evaluate_policy("update_config", user_role="ANALYST", environment="production")
        assert decision.action == PolicyAction.ALLOW

    def test_external_write_in_staging_needs_confirmation(self):
        from chat_app.safety_policies import evaluate_policy, PolicyAction
        decision = evaluate_policy("update_saved_search", user_role="USER", environment="staging")
        assert decision.action == PolicyAction.REQUIRE_CONFIRMATION

    def test_external_write_in_production_needs_approval(self):
        from chat_app.safety_policies import evaluate_policy, PolicyAction
        decision = evaluate_policy("deploy_pipeline", user_role="ANALYST", environment="production")
        assert decision.action == PolicyAction.REQUIRE_APPROVAL
        assert decision.approval_role == "ADMIN"

    def test_destructive_in_production_always_needs_approval(self):
        """Even ADMIN needs approval for destructive actions in production."""
        from chat_app.safety_policies import evaluate_policy, PolicyAction
        decision = evaluate_policy("delete_index", user_role="ADMIN", environment="production")
        assert decision.action == PolicyAction.REQUIRE_APPROVAL

    def test_destructive_in_dev_needs_confirmation(self):
        from chat_app.safety_policies import evaluate_policy, PolicyAction
        decision = evaluate_policy("delete_collection", user_role="USER", environment="development")
        assert decision.action == PolicyAction.REQUIRE_CONFIRMATION

    def test_destructive_in_staging_needs_approval(self):
        from chat_app.safety_policies import evaluate_policy, PolicyAction
        decision = evaluate_policy("restart_container", user_role="USER", environment="staging")
        assert decision.action == PolicyAction.REQUIRE_APPROVAL

    def test_production_dry_run_required_for_destructive(self):
        from chat_app.safety_policies import evaluate_policy
        decision = evaluate_policy("delete_index", user_role="ADMIN", environment="production")
        assert decision.requires_dry_run is True


class TestPolicyDecisionStructure:

    def test_decision_has_all_fields(self):
        from chat_app.safety_policies import evaluate_policy
        decision = evaluate_policy("splunk_search", user_role="USER", environment="development")
        assert hasattr(decision, "action")
        assert hasattr(decision, "tool_name")
        assert hasattr(decision, "safety_level")
        assert hasattr(decision, "reason")
        assert hasattr(decision, "requires_dry_run")
        assert hasattr(decision, "environment")

    def test_reason_is_descriptive(self):
        from chat_app.safety_policies import evaluate_policy
        decision = evaluate_policy("delete_index", user_role="USER", environment="production")
        assert "destructive" in decision.reason
        assert "production" in decision.reason


class TestEnvironmentPolicies:

    def test_get_environment_policies(self):
        from chat_app.safety_policies import get_environment_policies
        policies = get_environment_policies()
        assert "development" in policies
        assert "staging" in policies
        assert "production" in policies
        assert "read_only" in policies["production"]

    def test_get_all_classifications(self):
        from chat_app.safety_policies import get_all_classifications
        classifications = get_all_classifications()
        assert "splunk_search" in classifications
        assert classifications["splunk_search"] == "read_only"
        assert "delete_index" in classifications
        assert classifications["delete_index"] == "destructive"
