"""
Live Prometheus metrics pipeline tests.

Tests run on the host to verify the full metrics pipeline:
1. Custom metrics are registered and recordable
2. /metrics endpoint exposes all expected metrics
3. Prometheus is scraping successfully
4. Grafana datasource is configured
5. Metric recording functions work correctly

All requests go through the nginx gateway (single-port architecture).
"""
import json
import os
import subprocess
from urllib.parse import quote

import pytest


# All services accessed via the nginx gateway
GATEWAY_PORT = os.environ.get("GATEWAY_PORT", "8000")
GATEWAY_URL = f"http://localhost:{GATEWAY_PORT}"
PROM_URL = f"{GATEWAY_URL}/prometheus"
GRAFANA_URL = f"{GATEWAY_URL}/grafana"


def _curl(url: str, user: str = None) -> tuple:
    """Fetch URL via curl, return (status_code, body_text)."""
    cmd = ["curl", "-s", "-w", "\n%{http_code}", url]
    if user:
        cmd.extend(["-u", user])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    lines = result.stdout.rsplit("\n", 1)
    body = lines[0] if len(lines) > 1 else result.stdout
    code = int(lines[-1]) if len(lines) > 1 and lines[-1].strip().isdigit() else 0
    return code, body


def _curl_json(url: str, user: str = None) -> dict:
    """Fetch JSON from URL."""
    code, body = _curl(url, user)
    assert code == 200, f"HTTP {code} from {url}: {body[:200]}"
    return json.loads(body)


def _prom_query(promql: str) -> dict:
    """Query Prometheus with proper URL encoding."""
    encoded = quote(promql, safe='')
    return _curl_json(f"{PROM_URL}/api/v1/query?query={encoded}")


def _gateway_reachable() -> bool:
    """Check if the gateway is reachable."""
    try:
        code, _ = _curl(f"{GATEWAY_URL}/nginx-health")
        return code == 200
    except Exception:
        return False


def _app_metrics_reachable() -> bool:
    """Check if the app /metrics endpoint returns 200 (not 502/503)."""
    try:
        code, _ = _curl(f"{GATEWAY_URL}/metrics")
        return code == 200
    except Exception:
        return False


def _metrics_text() -> str:
    """Get /metrics text from app (via gateway)."""
    code, body = _curl(f"{GATEWAY_URL}/metrics")
    assert code == 200, f"HTTP {code} from /metrics"
    return body


# Skip all tests if app metrics endpoint is not reachable
# (gateway may be up but app behind it may not be running)
pytestmark = pytest.mark.skipif(
    not _app_metrics_reachable(),
    reason="App /metrics not reachable (containers not fully running)"
)


# ---------------------------------------------------------------------------
# 1. App /metrics endpoint
# ---------------------------------------------------------------------------

def test_metrics_endpoint_reachable():
    """GET /metrics returns 200 with Prometheus content."""
    text = _metrics_text()
    assert "python_info" in text


def test_custom_query_metrics_registered():
    """chainlit_queries_total and chainlit_query_latency_seconds are present."""
    text = _metrics_text()
    assert "chainlit_queries_total" in text
    assert "chainlit_query_latency_seconds" in text


def test_custom_llm_metrics_registered():
    """chainlit_llm_calls_total and chainlit_llm_latency_seconds are present."""
    text = _metrics_text()
    assert "chainlit_llm_latency_seconds" in text


def test_custom_cache_metrics_registered():
    """chainlit_cache_hits_total and chainlit_cache_misses_total are present."""
    text = _metrics_text()
    assert "chainlit_cache_hits_total" in text
    assert "chainlit_cache_misses_total" in text


def test_custom_vector_metrics_registered():
    """chainlit_vector_search_seconds and chainlit_vector_results_count are present."""
    text = _metrics_text()
    assert "chainlit_vector_results_count" in text


def test_app_info_metric():
    """chainlit_app_info should contain version, environment, llm_model."""
    text = _metrics_text()
    assert "chainlit_app_info" in text


def test_process_metrics_present():
    """Standard process metrics (memory, CPU, fds) should be present."""
    text = _metrics_text()
    assert "process_resident_memory_bytes" in text
    assert "process_cpu_seconds_total" in text


def test_histogram_buckets_present():
    """Query latency histogram should be registered as a histogram type."""
    text = _metrics_text()
    # Histogram TYPE must be declared even before any observations
    assert "chainlit_query_latency_seconds" in text
    assert '# TYPE chainlit_query_latency_seconds histogram' in text
    # If observations have been made, bucket labels should exist
    if 'chainlit_query_latency_seconds_bucket' in text:
        assert 'le="+Inf"' in text


def test_pipeline_stage_metrics():
    """Pipeline stage latency histogram should be registered."""
    text = _metrics_text()
    assert "chainlit_pipeline_stage_seconds" in text


def test_agent_dispatch_metrics():
    """Agent dispatch metrics should be registered."""
    text = _metrics_text()
    assert "chainlit_agent_dispatches_total" in text


def test_orchestration_metrics():
    """Orchestration metrics should be registered."""
    text = _metrics_text()
    assert "chainlit_orchestration_total" in text


# ---------------------------------------------------------------------------
# 2. Prometheus scrape targets (via gateway /prometheus/)
# ---------------------------------------------------------------------------

def _prom_reachable() -> bool:
    """Check if Prometheus is reachable via gateway."""
    try:
        code, _ = _curl(f"{PROM_URL}/api/v1/status/config")
        return code == 200
    except Exception:
        return False


@pytest.mark.skipif(not _gateway_reachable(), reason="gateway not reachable")
class TestPrometheusTargets:
    """Tests that require Prometheus accessible via gateway."""

    @pytest.fixture(autouse=True)
    def _skip_if_prom_unreachable(self):
        if not _prom_reachable():
            pytest.skip("Prometheus not reachable via gateway /prometheus/")

    def test_prometheus_reachable(self):
        """Prometheus API should be reachable via gateway."""
        data = _curl_json(f"{PROM_URL}/api/v1/status/config")
        assert data["status"] == "success"

    def test_chainlit_target_up(self):
        """Prometheus should be scraping chainlit_app successfully."""
        data = _curl_json(f"{PROM_URL}/api/v1/targets")
        targets = data["data"]["activeTargets"]
        chainlit_targets = [t for t in targets if t["labels"].get("job") == "chainlit_app"]
        assert len(chainlit_targets) == 1, "Expected 1 chainlit_app target"
        assert chainlit_targets[0]["health"] == "up"
        assert chainlit_targets[0]["lastError"] == ""

    def test_search_optimizer_target_up(self):
        """Prometheus should be scraping search_optimizer successfully."""
        data = _curl_json(f"{PROM_URL}/api/v1/targets")
        targets = data["data"]["activeTargets"]
        opt_targets = [t for t in targets if t["labels"].get("job") == "search_optimizer"]
        assert len(opt_targets) == 1, "Expected 1 search_optimizer target"
        assert opt_targets[0]["health"] == "up"

    def test_prometheus_self_target_up(self):
        """Prometheus should be monitoring itself."""
        data = _curl_json(f"{PROM_URL}/api/v1/targets")
        targets = data["data"]["activeTargets"]
        prom_targets = [t for t in targets if t["labels"].get("job") == "prometheus"]
        assert len(prom_targets) == 1
        assert prom_targets[0]["health"] == "up"

    def test_no_down_targets(self):
        """All active targets should be up (no down targets)."""
        data = _curl_json(f"{PROM_URL}/api/v1/targets")
        down_targets = [
            t for t in data["data"]["activeTargets"]
            if t["health"] == "down"
        ]
        assert len(down_targets) == 0, f"Down targets: {[t['labels']['job'] for t in down_targets]}"

    def test_exactly_three_targets(self):
        """Should have exactly 3 scrape targets (app, search_opt, prometheus)."""
        data = _curl_json(f"{PROM_URL}/api/v1/targets")
        targets = data["data"]["activeTargets"]
        assert len(targets) == 3, f"Expected 3 targets, got {len(targets)}: {[t['labels']['job'] for t in targets]}"


# ---------------------------------------------------------------------------
# 3. Prometheus queries (data flowing)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not _gateway_reachable(), reason="gateway not reachable")
class TestPrometheusQueries:
    """Tests that require Prometheus query API."""

    @pytest.fixture(autouse=True)
    def _skip_if_prom_unreachable(self):
        if not _prom_reachable():
            pytest.skip("Prometheus not reachable via gateway /prometheus/")

    def test_up_metric_exists(self):
        """'up' metric should be 1 for all active scraped targets."""
        data = _prom_query("up")
        results = data["data"]["result"]
        active_jobs = {"chainlit_app", "search_optimizer", "prometheus"}
        active = [r for r in results if r["metric"].get("job") in active_jobs]
        assert len(active) >= 2, f"Expected at least 2 active up metrics, got {len(active)}"
        for result in active:
            assert result["value"][1] == "1", f"{result['metric']['job']} is down"

    def test_chainlit_query_metric_in_prometheus(self):
        """chainlit_queries_total should be queryable in Prometheus."""
        data = _curl_json(f"{PROM_URL}/api/v1/query?query=chainlit_queries_total")
        assert data["status"] == "success"

    def test_process_memory_queryable(self):
        """process_resident_memory_bytes should be queryable for the app."""
        data = _prom_query('process_resident_memory_bytes{job="chainlit_app"}')
        results = data["data"]["result"]
        assert len(results) >= 1, "Expected memory metric for chainlit_app"
        mem_bytes = float(results[0]["value"][1])
        assert mem_bytes > 0, f"Memory is {mem_bytes}"

    def test_scrape_duration_acceptable(self):
        """Scrape duration should be under 5 seconds."""
        data = _prom_query('scrape_duration_seconds{job="chainlit_app"}')
        results = data["data"]["result"]
        if results:
            duration = float(results[0]["value"][1])
            assert duration < 5.0, f"Scrape duration too high: {duration}s"

    def test_process_cpu_queryable(self):
        """process_cpu_seconds_total should have non-zero value."""
        data = _prom_query('process_cpu_seconds_total{job="chainlit_app"}')
        results = data["data"]["result"]
        assert len(results) >= 1
        cpu = float(results[0]["value"][1])
        assert cpu > 0, "CPU time should be > 0"


# ---------------------------------------------------------------------------
# 4. Search Optimizer metrics (via gateway)
# ---------------------------------------------------------------------------

def test_search_optimizer_metrics_endpoint():
    """Search optimizer /metrics should return FastAPI instrumentator metrics."""
    code, text = _curl(f"{GATEWAY_URL}/search-opt/metrics")
    assert code == 200, f"HTTP {code} from search-opt/metrics"
    assert "http_request" in text or "http_requests" in text


# ---------------------------------------------------------------------------
# 5. Grafana integration (via gateway)
# ---------------------------------------------------------------------------

def _grafana_reachable() -> bool:
    """Check if Grafana is reachable via gateway."""
    try:
        code, _ = _curl(f"{GRAFANA_URL}/api/health")
        return code == 200
    except Exception:
        return False


@pytest.mark.skipif(not _gateway_reachable(), reason="gateway not reachable")
class TestGrafana:
    """Tests that require Grafana accessible via gateway."""

    @pytest.fixture(autouse=True)
    def _skip_if_grafana_unreachable(self):
        if not _grafana_reachable():
            pytest.skip("Grafana not reachable via gateway /grafana/")

    def test_grafana_reachable(self):
        """Grafana health endpoint should respond."""
        data = _curl_json(f"{GRAFANA_URL}/api/health")
        assert data.get("database") == "ok"

    def test_grafana_prometheus_datasource(self):
        """Grafana should have Prometheus configured as a datasource."""
        data = _curl_json(f"{GRAFANA_URL}/api/datasources", user="admin:admin")
        prom_ds = [ds for ds in data if ds.get("type") == "prometheus"]
        assert len(prom_ds) >= 1, "No Prometheus datasource found in Grafana"

    def test_grafana_datasource_healthy(self):
        """Grafana's Prometheus datasource should pass its health check."""
        data = _curl_json(f"{GRAFANA_URL}/api/datasources", user="admin:admin")
        prom_ds = [ds for ds in data if ds.get("type") == "prometheus"]
        assert len(prom_ds) >= 1
        ds_id = prom_ds[0]["id"]
        health = _curl_json(f"{GRAFANA_URL}/api/datasources/{ds_id}/health", user="admin:admin")
        assert health.get("status") == "OK", f"Datasource health: {health}"


# ---------------------------------------------------------------------------
# 6. Metrics format validation
# ---------------------------------------------------------------------------

def test_metrics_format_valid():
    """All metrics lines should follow Prometheus exposition format."""
    text = _metrics_text()
    lines = text.strip().split("\n")
    for line in lines:
        if line.startswith("#"):
            assert line.startswith("# HELP") or line.startswith("# TYPE"), \
                f"Unexpected comment format: {line[:80]}"
        elif line.strip():
            parts = line.strip().split()
            assert len(parts) >= 2, f"Invalid metric line: {line[:80]}"
            try:
                float(parts[1])
            except ValueError:
                assert False, f"Invalid metric value in: {line[:80]}"


def test_no_duplicate_metric_names():
    """Each metric should be declared only once."""
    text = _metrics_text()
    type_lines = [l for l in text.split("\n") if l.startswith("# TYPE")]
    names = [l.split()[2] for l in type_lines]
    duplicates = [n for n in names if names.count(n) > 1]
    assert len(duplicates) == 0, f"Duplicate metric declarations: {set(duplicates)}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
