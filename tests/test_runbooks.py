"""Tests for runbook registry."""

import pytest


@pytest.fixture
def registry():
    from chat_app.runbooks import RunbookRegistry
    return RunbookRegistry()


class TestBuiltinRunbooks:

    def test_has_postgres_runbook(self, registry):
        rb = registry.get_for_alert("postgres_unhealthy")
        assert rb is not None
        assert rb.severity == "critical"
        assert len(rb.diagnostic_steps) > 0
        assert len(rb.fix_steps) > 0

    def test_has_ollama_runbook(self, registry):
        rb = registry.get_for_alert("ollama_unhealthy")
        assert rb is not None

    def test_has_chromadb_runbook(self, registry):
        rb = registry.get_for_alert("chromadb_unhealthy")
        assert rb is not None

    def test_has_redis_runbook(self, registry):
        rb = registry.get_for_alert("redis_unhealthy")
        assert rb is not None
        assert rb.severity == "warning"  # Non-critical

    def test_has_slo_runbook(self, registry):
        rb = registry.get_for_alert("slo_breached")
        assert rb is not None
        assert rb.severity == "critical"

    def test_all_runbooks_have_required_fields(self, registry):
        for rb in registry.get_all():
            assert rb.alert_key
            assert rb.title
            assert rb.description
            assert rb.severity in ("info", "warning", "critical")
            assert rb.category

    def test_runbook_count(self, registry):
        assert len(registry.get_all()) >= 8


class TestRunbookSearch:

    def test_search_by_keyword(self, registry):
        results = registry.search("postgres")
        assert len(results) >= 1
        assert any("postgres" in r.title.lower() for r in results)

    def test_search_by_tag(self, registry):
        results = registry.search("critical")
        assert len(results) >= 3

    def test_search_no_match(self, registry):
        results = registry.search("xyznonexistent")
        assert len(results) == 0


class TestRunbookRegistration:

    def test_register_custom_runbook(self, registry):
        from chat_app.runbooks import Runbook, RunbookStep
        custom = Runbook(
            alert_key="custom_alert",
            title="Custom Alert",
            description="A custom runbook",
            severity="info",
            category="custom",
            diagnostic_steps=[RunbookStep(1, "Check logs")],
            fix_steps=[RunbookStep(1, "Restart service")],
        )
        registry.register(custom)
        rb = registry.get_for_alert("custom_alert")
        assert rb is not None
        assert rb.title == "Custom Alert"

    def test_nonexistent_alert(self, registry):
        assert registry.get_for_alert("nonexistent") is None


class TestRunbookSerialization:

    def test_to_dict(self, registry):
        rb = registry.get_for_alert("postgres_unhealthy")
        d = rb.to_dict()
        assert d["alert_key"] == "postgres_unhealthy"
        assert isinstance(d["diagnostic_steps"], list)
        assert isinstance(d["fix_steps"], list)
        assert "escalation" in d

    def test_to_list(self, registry):
        items = registry.to_list()
        assert isinstance(items, list)
        assert len(items) >= 8


class TestRunbookCategories:

    def test_get_categories(self, registry):
        cats = registry.get_categories()
        assert "database" in cats
        assert "llm" in cats
        assert "reliability" in cats
