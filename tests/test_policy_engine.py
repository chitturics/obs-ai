"""Tests for the policy-as-code engine."""

import pytest


@pytest.fixture
def engine():
    from chat_app.policy_engine import PolicyEngine
    return PolicyEngine()


def _ctx(**kwargs):
    from chat_app.policy_engine import PolicyContext
    defaults = {"tool": "test_tool", "actor": "user@test.com", "role": "USER", "environment": "development"}
    defaults.update(kwargs)
    return PolicyContext(**defaults)


class TestPolicyEvaluation:

    def test_default_allows_read_in_dev(self, engine):
        result = engine.evaluate(_ctx(tool="splunk_search"))
        assert result.allowed is True

    def test_dry_run_always_passes(self, engine):
        result = engine.evaluate(_ctx(tool="delete_index", environment="production", is_dry_run=True))
        assert result.allowed is True
        assert "dry_run_bypass" in result.applied_policies

    def test_viewer_denied_write_tools(self, engine):
        result = engine.evaluate(_ctx(tool="update_config", role="VIEWER"))
        assert result.allowed is False
        assert any("viewer_no_writes" in r for r in result.denial_reasons)

    def test_viewer_allowed_read_tools(self, engine):
        result = engine.evaluate(_ctx(tool="splunk_search", role="VIEWER"))
        assert result.allowed is True

    def test_destructive_in_prod_requires_approval(self, engine):
        result = engine.evaluate(_ctx(tool="delete_index", environment="production"))
        assert result.requires_approval is True
        assert result.approval_level == "ADMIN"

    def test_approved_action_passes(self, engine):
        result = engine.evaluate(_ctx(tool="delete_index", environment="production", is_approved=True))
        # Approval policies are skipped for pre-approved actions
        assert result.allowed is True

    def test_staging_destructive_warns(self, engine):
        result = engine.evaluate(_ctx(tool="delete_index", environment="staging"))
        assert any("staging_destructive_warn" in w for w in result.warnings)


class TestCustomPolicies:

    def test_add_custom_rule(self, engine):
        from chat_app.policy_engine import PolicyRule, PolicyType
        rule = PolicyRule(
            name="test_block_search",
            description="Block search tool for testing",
            policy_type=PolicyType.CUSTOM,
            condition=lambda ctx: ctx.tool == "blocked_tool",
            effect="deny",
            priority=1,
        )
        engine.add_rule(rule)
        result = engine.evaluate(_ctx(tool="blocked_tool"))
        assert result.allowed is False

    def test_remove_rule(self, engine):
        engine.remove_rule("weekend_freeze")
        rules = engine.get_all_rules()
        assert not any(r["name"] == "weekend_freeze" for r in rules)

    def test_disable_rule(self, engine):
        engine.disable_rule("viewer_no_writes")
        result = engine.evaluate(_ctx(tool="update_config", role="VIEWER"))
        assert result.allowed is True  # Rule disabled, no denial

    def test_enable_rule(self, engine):
        engine.disable_rule("viewer_no_writes")
        engine.enable_rule("viewer_no_writes")
        result = engine.evaluate(_ctx(tool="update_config", role="VIEWER"))
        assert result.allowed is False


class TestPolicyRules:

    def test_get_all_rules(self, engine):
        rules = engine.get_all_rules()
        assert len(rules) >= 5
        assert all("name" in r for r in rules)

    def test_rules_sorted_by_priority(self, engine):
        rules = engine.get_all_rules()
        priorities = [r["priority"] for r in rules]
        assert priorities == sorted(priorities)


class TestPolicyStats:

    def test_stats_structure(self, engine):
        engine.evaluate(_ctx(tool="splunk_search"))
        engine.evaluate(_ctx(tool="update_config", role="VIEWER"))
        stats = engine.get_stats()
        assert stats["total_rules"] >= 5
        assert stats["total_evaluations"] == 2
        assert stats["total_denials"] >= 1
        assert "by_type" in stats


class TestPolicyResult:

    def test_result_to_dict(self, engine):
        result = engine.evaluate(_ctx(tool="delete_index", environment="production"))
        d = result.to_dict()
        assert "allowed" in d
        assert "denial_reasons" in d
        assert "warnings" in d
        assert "applied_policies" in d
