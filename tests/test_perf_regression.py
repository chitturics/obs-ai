"""Sprint 4: Performance regression gates.

Verifies critical operations complete within latency budgets.
Run in CI to prevent performance regressions.
"""

import pytest
import time


@pytest.mark.unit
class TestLatencyBudgets:
    """Verify operations complete within their latency budgets."""

    def test_skill_executor_import_under_2s(self):
        start = time.monotonic()
        from chat_app.skill_executor import SkillExecutor
        from chat_app.handlers import get_all_handlers
        handlers = get_all_handlers()
        elapsed = (time.monotonic() - start) * 1000
        assert elapsed < 2000, f"Handler import: {elapsed:.0f}ms (budget: 2000ms)"
        assert len(handlers) >= 30

    def test_settings_load_under_2s(self):
        start = time.monotonic()
        from chat_app.settings import get_settings
        s = get_settings()
        elapsed = (time.monotonic() - start) * 1000
        assert elapsed < 2000, f"Settings load: {elapsed:.0f}ms (budget: 2000ms)"

    def test_intent_classifier_under_5ms(self):
        try:
            from chat_app.intent_classifier import IntentClassifier
        except ImportError:
            pytest.skip("IntentClassifier not available")
        c = IntentClassifier()
        start = time.monotonic()
        for _ in range(100):
            c.classify("index=main sourcetype=syslog ERROR", 6)
        per_ms = (time.monotonic() - start) * 1000 / 100
        assert per_ms < 5, f"Intent classify: {per_ms:.1f}ms/q (budget: 5ms)"

    def test_utility_handlers_under_1ms(self):
        from chat_app.handlers.utility_handlers import HANDLERS
        for name in ["base64_encode", "md5", "sha256", "uuid_generate"]:
            h = HANDLERS.get(name)
            if not h:
                continue
            start = time.monotonic()
            for _ in range(100):
                h(user_input="test data")
            per_ms = (time.monotonic() - start) * 1000 / 100
            assert per_ms < 1, f"{name}: {per_ms:.2f}ms (budget: 1ms)"

    def test_workflow_simulation_under_1ms(self):
        from chat_app.workflow_engine import get_workflow_engine
        engine = get_workflow_engine()
        start = time.monotonic()
        for _ in range(100):
            engine.simulate("splunk_search")
        per_ms = (time.monotonic() - start) * 1000 / 100
        assert per_ms < 1, f"Simulation: {per_ms:.2f}ms (budget: 1ms)"


@pytest.mark.unit
class TestCIGates:

    def test_coverage_config(self):
        import tomllib
        with open("pyproject.toml", "rb") as f:
            c = tomllib.load(f)
        assert "coverage" in c.get("tool", {})

    def test_markers_configured(self):
        import tomllib
        with open("pyproject.toml", "rb") as f:
            c = tomllib.load(f)
        markers = c.get("tool", {}).get("pytest", {}).get("ini_options", {}).get("markers", [])
        names = [m.split(":")[0].strip() for m in markers]
        assert "unit" in names and "integration" in names and "e2e" in names
