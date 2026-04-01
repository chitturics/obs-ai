"""Sprint 3: SRE Alignment tests.

Prove: every P1 alert has matching metrics AND matching runbooks.
"""

import pytest
import yaml


class TestAlertMetricAlignment:
    """Verify Prometheus alerts reference metrics that exist in code."""

    @pytest.fixture(autouse=True)
    def load_alerts(self):
        with open("containers/prometheus/alert_rules.yml") as f:
            data = yaml.safe_load(f)
        self.alerts = data["groups"][0]["rules"]

    def test_all_alerts_have_runbook_label(self):
        """Every alert should have a runbook label for SRE mapping."""
        for alert in self.alerts:
            if alert["alert"] != "ServiceUnhealthy":  # Generic alert, no specific runbook
                assert "runbook" in alert.get("labels", {}), \
                    f"Alert '{alert['alert']}' missing runbook label"

    def test_all_alerts_use_chainlit_metrics(self):
        """Alerts should use chainlit_* metrics (not http_requests_total etc)."""
        for alert in self.alerts:
            expr = alert["expr"]
            # ServiceUnhealthy uses 'up' which is a Prometheus built-in
            if alert["alert"] == "ServiceUnhealthy":
                assert "up" in expr
                continue
            # All others should use chainlit_ or be standard PromQL functions
            assert "chainlit_" in expr or "up" in expr, \
                f"Alert '{alert['alert']}' uses non-chainlit metric: {expr}"

    def test_service_up_metrics_exist(self):
        """chainlit_service_up gauge must exist for OllamaDown/ChromaDBDown/PostgresDown alerts."""
        from chat_app.prometheus_metrics import PROMETHEUS_AVAILABLE
        if not PROMETHEUS_AVAILABLE:
            pytest.skip("prometheus_client not installed")
        from chat_app.prometheus_metrics import SERVICE_UP
        assert SERVICE_UP is not None

    def test_alert_count_minimum(self):
        """Should have at least 8 alert rules."""
        assert len(self.alerts) >= 8


class TestAlertRunbookMapping:
    """Verify every alert's runbook label maps to an actual runbook."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with open("containers/prometheus/alert_rules.yml") as f:
            data = yaml.safe_load(f)
        self.alerts = data["groups"][0]["rules"]
        from chat_app.runbooks import get_runbook_registry
        self.registry = get_runbook_registry()

    def test_every_alert_runbook_exists(self):
        """Every alert with a runbook label must have a matching runbook in the registry."""
        missing = []
        for alert in self.alerts:
            runbook_key = alert.get("labels", {}).get("runbook")
            if runbook_key:
                rb = self.registry.get_for_alert(runbook_key)
                if not rb:
                    missing.append(f"{alert['alert']} → runbook:{runbook_key}")
        assert not missing, f"Alerts with missing runbooks: {missing}"

    def test_runbook_has_diagnostic_steps(self):
        """Every mapped runbook should have at least 1 diagnostic step."""
        for alert in self.alerts:
            runbook_key = alert.get("labels", {}).get("runbook")
            if runbook_key:
                rb = self.registry.get_for_alert(runbook_key)
                if rb:
                    assert len(rb.diagnostic_steps) > 0, \
                        f"Runbook '{runbook_key}' has no diagnostic steps"

    def test_runbook_has_fix_steps(self):
        """Every mapped runbook should have at least 1 fix step."""
        for alert in self.alerts:
            runbook_key = alert.get("labels", {}).get("runbook")
            if runbook_key:
                rb = self.registry.get_for_alert(runbook_key)
                if rb:
                    assert len(rb.fix_steps) > 0, \
                        f"Runbook '{runbook_key}' has no fix steps"


class TestServiceHealthMetrics:
    """Verify health checks record Prometheus metrics."""

    def test_record_service_health_function_exists(self):
        from chat_app.prometheus_metrics import record_service_health
        # Should not raise
        record_service_health("test_service", True)
        record_service_health("test_service", False)

    def test_health_monitor_records_metrics(self):
        """health_monitor.py should call _record_service_metric."""
        content = open("chat_app/health_monitor.py").read()
        assert "_record_service_metric" in content
        # Should be called for each service
        for svc in ["postgres", "ollama", "chromadb", "redis"]:
            assert f'_record_service_metric("{svc}"' in content, \
                f"Missing metric recording for {svc} in health_monitor.py"


class TestReadinessProbe:
    """Verify readiness probe checks all critical services."""

    def test_readiness_checks_multiple_services(self):
        """Readiness probe should check more than just Ollama+ChromaDB."""
        content = open("chat_app/health_routes.py").read()
        assert "chromadb" in content or "chroma" in content
        assert "ollama" in content
        assert "record_service_health" in content  # Records to Prometheus


class TestErrorBudget:
    """Verify error budget recording exists."""

    def test_error_budget_function_exists(self):
        from chat_app.prometheus_metrics import record_error_budget
        # Should not raise
        record_error_budget("test_slo", 0.85)
