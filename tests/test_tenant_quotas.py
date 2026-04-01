"""Tests for tenant quotas and budgets."""

import pytest


@pytest.fixture
def mgr():
    from chat_app.tenant_quotas import QuotaManager
    return QuotaManager()


class TestQuotaRecording:

    def test_record_usage(self, mgr):
        status = mgr.record_usage("tenant_a", "llm_tokens", 500)
        assert status.current_usage == 500
        assert status.within_quota is True

    def test_cumulative_usage(self, mgr):
        mgr.record_usage("tenant_a", "llm_tokens", 500)
        mgr.record_usage("tenant_a", "llm_tokens", 300)
        status = mgr.check_quota("tenant_a", "llm_tokens")
        assert status.current_usage == 800

    def test_exceed_quota(self, mgr):
        mgr.set_quota("test_resource", 100)
        for _ in range(11):
            mgr.record_usage("tenant_a", "test_resource", 10)
        status = mgr.check_quota("tenant_a", "test_resource")
        assert status.within_quota is False
        assert "EXCEEDED" in status.warning


class TestQuotaChecks:

    def test_check_within_quota(self, mgr):
        mgr.record_usage("tenant_a", "api_calls", 50)
        status = mgr.check_quota("tenant_a", "api_calls")
        assert status.within_quota is True
        assert status.remaining > 0

    def test_warning_at_80_pct(self, mgr):
        mgr.set_quota("test_resource", 100)
        mgr.record_usage("tenant_a", "test_resource", 85)
        status = mgr.check_quota("tenant_a", "test_resource")
        assert status.warning is not None
        assert "WARNING" in status.warning

    def test_critical_at_95_pct(self, mgr):
        mgr.set_quota("test_resource", 100)
        mgr.record_usage("tenant_a", "test_resource", 96)
        status = mgr.check_quota("tenant_a", "test_resource")
        assert "CRITICAL" in status.warning

    def test_unknown_resource_passes(self, mgr):
        status = mgr.check_quota("tenant_a", "unknown_resource")
        assert status.within_quota is True


class TestQuotaManagement:

    def test_set_quota(self, mgr):
        quota = mgr.set_quota("custom_resource", 500, enforcement="hard_limit")
        assert quota.limit == 500
        assert quota.enforcement == "hard_limit"

    def test_update_existing_quota(self, mgr):
        mgr.set_quota("llm_tokens", 2_000_000)
        status = mgr.check_quota("tenant_a", "llm_tokens")
        assert status.limit == 2_000_000

    def test_reset_usage(self, mgr):
        mgr.record_usage("tenant_a", "api_calls", 500)
        mgr.reset_usage("tenant_a", "api_calls")
        status = mgr.check_quota("tenant_a", "api_calls")
        assert status.current_usage == 0

    def test_reset_all_usage(self, mgr):
        mgr.record_usage("tenant_a", "api_calls", 500)
        mgr.record_usage("tenant_a", "llm_tokens", 1000)
        mgr.reset_usage("tenant_a")
        assert mgr.check_quota("tenant_a", "api_calls").current_usage == 0
        assert mgr.check_quota("tenant_a", "llm_tokens").current_usage == 0


class TestTenantUsage:

    def test_get_tenant_usage(self, mgr):
        mgr.record_usage("tenant_a", "llm_tokens", 500)
        mgr.record_usage("tenant_a", "api_calls", 100)
        usage = mgr.get_tenant_usage("tenant_a")
        assert usage["tenant"] == "tenant_a"
        assert len(usage["quotas"]) >= 6
        assert usage["any_exceeded"] is False

    def test_independent_tenants(self, mgr):
        mgr.record_usage("tenant_a", "llm_tokens", 500)
        mgr.record_usage("tenant_b", "llm_tokens", 1000)
        assert mgr.check_quota("tenant_a", "llm_tokens").current_usage == 500
        assert mgr.check_quota("tenant_b", "llm_tokens").current_usage == 1000


class TestQuotaDefinitions:

    def test_default_quotas(self, mgr):
        defs = mgr.get_quota_definitions()
        assert len(defs) >= 6
        names = [d["resource"] for d in defs]
        assert "llm_tokens" in names
        assert "api_calls" in names
        assert "storage_mb" in names

    def test_get_all_tenants(self, mgr):
        mgr.record_usage("tenant_a", "api_calls", 1)
        mgr.record_usage("tenant_b", "api_calls", 1)
        tenants = mgr.get_all_tenants()
        assert "tenant_a" in tenants
        assert "tenant_b" in tenants


class TestStats:

    def test_stats_structure(self, mgr):
        stats = mgr.get_stats()
        assert stats["total_quotas"] >= 6
        assert stats["total_tenants"] == 0
        assert "timestamp" in stats

    def test_stats_with_exceeded(self, mgr):
        mgr.set_quota("tiny_quota", 5)
        mgr.record_usage("tenant_a", "tiny_quota", 10)
        stats = mgr.get_stats()
        assert stats["exceeded_count"] >= 1


class TestSerialization:

    def test_quota_status_to_dict(self, mgr):
        status = mgr.record_usage("tenant_a", "llm_tokens", 100)
        d = status.to_dict()
        assert "resource" in d
        assert "tenant" in d
        assert "within_quota" in d
        assert "usage_pct" in d
