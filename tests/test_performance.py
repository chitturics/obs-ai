"""
Performance and latency benchmarks for the Admin API.

These tests measure response times of key admin endpoints and assert
that they complete within acceptable thresholds.  They use FastAPI's
synchronous TestClient so no live containers are needed.

Run with:
    pytest tests/test_performance.py -v -s
"""

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from chat_app.settings import get_settings

get_settings.cache_clear()

from chat_app.admin_api import (
    router, public_router, _rate_limit, _track_audit_user, _csrf_check,
    dashboard_router, pages_router, pages_public_router,
    interactive_tools_public_router, interactive_tools_router,
    observability_router, skills_router, collections_router,
    learning_router, operations_router, config_router,
    settings_router, tools_router, users_router, security_router,
)
from chat_app.admin_config_helpers import config_ext_router
from chat_app.auth_dependencies import get_authenticated_user, require_admin

_ADMIN_USER = {
    "identifier": "perf_tester",
    "metadata": {"role": "ADMIN", "provider": "test"},
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_admin_state():
    """Reset mutable admin state between tests."""
    import chat_app.admin_api as mod
    mod._config_audit_trail.clear()
    mod._feature_flags = None
    mod._recent_queries.clear()
    mod._intent_counts.clear()
    mod._query_volume.clear()
    mod._SECTION_MODEL_MAP.clear()
    yield


@pytest.fixture
def perf_client():
    """FastAPI TestClient with all auth/rate-limit dependencies bypassed."""
    app = FastAPI()
    app.include_router(router)
    app.include_router(public_router)
    for sub in [dashboard_router, pages_router, pages_public_router,
                interactive_tools_public_router, interactive_tools_router,
                observability_router, skills_router, collections_router,
                learning_router, operations_router, config_router,
                config_ext_router, settings_router, tools_router,
                users_router, security_router]:
        app.include_router(sub)
    # Override every router-level dependency so requests are not rejected
    app.dependency_overrides[get_authenticated_user] = lambda: _ADMIN_USER
    app.dependency_overrides[require_admin] = lambda: _ADMIN_USER
    app.dependency_overrides[_rate_limit] = lambda: None
    app.dependency_overrides[_track_audit_user] = lambda: None
    app.dependency_overrides[_csrf_check] = lambda: None
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _timed_get(client, path: str):
    """Issue a GET and return (response, elapsed_seconds)."""
    start = time.monotonic()
    resp = client.get(f"/api/admin{path}")
    elapsed = time.monotonic() - start
    return resp, elapsed


def _timed_post(client, path: str, **kwargs):
    """Issue a POST and return (response, elapsed_seconds)."""
    start = time.monotonic()
    resp = client.post(f"/api/admin{path}", **kwargs)
    elapsed = time.monotonic() - start
    return resp, elapsed


# ---------------------------------------------------------------------------
# 1. Admin API Latency
# ---------------------------------------------------------------------------

class TestAdminAPILatency:
    """Verify core read endpoints respond within 500 ms."""

    @pytest.mark.parametrize("path,label", [
        ("/settings", "Settings"),
        ("/config/restart-policy", "RestartPolicy"),
        ("/features", "Features"),
        ("/collections", "Collections"),
    ])
    def test_endpoint_latency(self, perf_client, path, label):
        resp, elapsed = _timed_get(perf_client, path)
        print(f"  {label} ({path}): {elapsed*1000:.1f} ms  [status={resp.status_code}]")
        assert resp.status_code == 200, f"{label} returned {resp.status_code}: {resp.text[:300]}"
        assert elapsed < 0.5, f"{label} took {elapsed:.3f}s, expected < 0.5s"


# ---------------------------------------------------------------------------
# 2. Config Operations
# ---------------------------------------------------------------------------

class TestConfigOperations:
    """Benchmark config reload and section read."""

    def test_config_reload_latency(self, perf_client):
        resp, elapsed = _timed_post(perf_client, "/config/reload")
        print(f"  Config reload: {elapsed*1000:.1f} ms  [status={resp.status_code}]")
        assert resp.status_code == 200, f"Config reload returned {resp.status_code}"
        assert elapsed < 1.0, f"Config reload took {elapsed:.3f}s, expected < 1s"

    def test_settings_section_read_latency(self, perf_client):
        """Reading a single settings section should be fast."""
        start = time.monotonic()
        resp = perf_client.get("/api/admin/settings")
        elapsed = time.monotonic() - start
        print(f"  Settings full read: {elapsed*1000:.1f} ms")
        assert resp.status_code == 200
        data = resp.json()
        assert "sections" in data
        assert elapsed < 0.5, f"Settings read took {elapsed:.3f}s, expected < 0.5s"


# ---------------------------------------------------------------------------
# 3. Container List
# ---------------------------------------------------------------------------

class TestContainerListPerformance:
    """The containers endpoint probes live services; mock them for CI."""

    def test_containers_endpoint_latency(self, perf_client):
        resp, elapsed = _timed_get(perf_client, "/containers")
        print(f"  Containers: {elapsed*1000:.1f} ms  [status={resp.status_code}]")
        assert resp.status_code == 200, f"Containers returned {resp.status_code}"
        assert elapsed < 2.0, f"Containers took {elapsed:.3f}s, expected < 2s"


# ---------------------------------------------------------------------------
# 4. Knowledge Graph Query
# ---------------------------------------------------------------------------

class TestKnowledgeGraphPerformance:
    """Benchmark Knowledge Graph endpoints (in-memory graph, no services needed)."""

    def test_kg_stats_latency(self, perf_client):
        resp, elapsed = _timed_get(perf_client, "/knowledge-graph/stats")
        print(f"  KG stats: {elapsed*1000:.1f} ms  [status={resp.status_code}]")
        assert resp.status_code == 200
        assert elapsed < 1.0, f"KG stats took {elapsed:.3f}s, expected < 1s"

    def test_kg_entities_latency(self, perf_client):
        resp, elapsed = _timed_get(perf_client, "/knowledge-graph/entities?entity_type=Command")
        print(f"  KG entities: {elapsed*1000:.1f} ms  [status={resp.status_code}]")
        assert resp.status_code == 200
        assert elapsed < 1.0, f"KG entities took {elapsed:.3f}s, expected < 1s"

    def test_kg_graph_latency(self, perf_client):
        resp, elapsed = _timed_get(perf_client, "/knowledge-graph/graph")
        print(f"  KG graph: {elapsed*1000:.1f} ms  [status={resp.status_code}]")
        assert resp.status_code == 200
        assert elapsed < 1.0, f"KG graph took {elapsed:.3f}s, expected < 1s"

    def test_kg_query_latency(self, perf_client):
        resp, elapsed = _timed_get(perf_client, "/knowledge-graph/query?q=stats")
        print(f"  KG query: {elapsed*1000:.1f} ms  [status={resp.status_code}]")
        assert resp.status_code == 200
        assert elapsed < 1.0, f"KG query took {elapsed:.3f}s, expected < 1s"


# ---------------------------------------------------------------------------
# 5. Concurrent Requests
# ---------------------------------------------------------------------------

class TestConcurrentRequests:
    """Simulate concurrent load against the /settings endpoint."""

    def test_concurrent_settings_requests(self, perf_client):
        """Send 10 simultaneous GET /settings and assert all succeed within 5s."""
        num_requests = 10
        results: list[tuple[int, float]] = []

        def _fetch():
            start = time.monotonic()
            resp = perf_client.get("/api/admin/settings")
            elapsed = time.monotonic() - start
            results.append((resp.status_code, elapsed))

        import concurrent.futures

        wall_start = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=num_requests) as pool:
            futures = [pool.submit(_fetch) for _ in range(num_requests)]
            concurrent.futures.wait(futures, timeout=10)
        wall_elapsed = time.monotonic() - wall_start

        # Check for exceptions
        for f in futures:
            exc = f.exception()
            assert exc is None, f"Request raised: {exc}"

        statuses = [r[0] for r in results]
        latencies = [r[1] for r in results]
        errors = [s for s in statuses if s != 200]

        print(f"  Concurrent ({num_requests} reqs): wall={wall_elapsed*1000:.1f} ms, "
              f"avg={sum(latencies)/len(latencies)*1000:.1f} ms, "
              f"max={max(latencies)*1000:.1f} ms, errors={len(errors)}")

        assert len(results) == num_requests, f"Only {len(results)}/{num_requests} completed"
        assert len(errors) == 0, f"Got {len(errors)} non-200 responses: {errors}"
        assert wall_elapsed < 5.0, f"Wall time {wall_elapsed:.3f}s exceeds 5s limit"


# ---------------------------------------------------------------------------
# 6. Repeated-call stability (micro-benchmark)
# ---------------------------------------------------------------------------

class TestRepeatedCallStability:
    """Ensure latency does not degrade across repeated calls."""

    def test_settings_100_calls_stable(self, perf_client):
        """100 sequential GETs to /settings — p99 should stay under 500 ms."""
        latencies = []
        for _ in range(100):
            _, elapsed = _timed_get(perf_client, "/settings")
            latencies.append(elapsed)

        latencies.sort()
        p50 = latencies[49]
        p99 = latencies[98]
        avg = sum(latencies) / len(latencies)
        print(f"  100x /settings — avg={avg*1000:.1f} ms, p50={p50*1000:.1f} ms, p99={p99*1000:.1f} ms")
        assert p99 < 0.5, f"p99 latency {p99:.3f}s exceeds 0.5s"
