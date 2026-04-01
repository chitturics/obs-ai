"""
Sprint 3+4 tests for the Splunk Upgrade Readiness Testing System.

Coverage:
  TestSplunkbaseFetcher    — catalog lookup, version path, cache (15 tests)
  TestContainerTester      — deploy/cleanup lifecycle with mocked podman (10 tests)
  TestUFTestEnvironment    — two-container setup mocked (10 tests)
  TestReportBuilder        — JSON/Markdown generation, save/load (15 tests)
  TestAdminUpgradeAPI      — all API endpoints via TestClient (15 tests)
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_report(
    app_id: str = "Splunk_TA_test",
    from_version: str = "1.0.0",
    to_version: str = "2.0.0",
    cluster: str = "cluster-es",
    findings: List[Any] = None,
) -> "UpgradeImpactReport":
    """Build a minimal UpgradeImpactReport for testing."""
    from chat_app.upgrade_readiness.models import UpgradeImpactReport, UpgradeRisk

    return UpgradeImpactReport(
        app_id=app_id,
        from_version=from_version,
        to_version=to_version,
        cluster=cluster,
        findings=findings or [],
        overall_risk=UpgradeRisk.MEDIUM,
        recommendation="Review before upgrading.",
    )


def _make_finding(
    risk: str = "HIGH",
    category: str = "KEY_CHANGED",
    conf_type: str = "props",
    stanza: str = "source::access.log",
    key: str = "LINE_BREAKER",
    description: str = "LINE_BREAKER changed",
    recommendation: str = "Validate parsing.",
) -> "UpgradeFinding":
    """Build a minimal UpgradeFinding for testing."""
    from chat_app.upgrade_readiness.models import (
        FindingCategory,
        UpgradeFinding,
        UpgradeRisk,
    )

    return UpgradeFinding.create(
        risk=UpgradeRisk(risk),
        category=FindingCategory(category),
        conf_type=conf_type,
        stanza=stanza,
        key=key,
        description=description,
        recommendation=recommendation,
        old_value="\\n",
        new_value="\\r\\n",
    )


def _make_catalog_entry(
    app_id: str = "Splunk_TA_test",
    uid: str = "1234",
    title: str = "Splunk TA Test",
    latest_version: str = "2.0.0",
    releases: List[Dict] = None,
) -> Dict[str, Any]:
    """Build a minimal Splunkbase catalog entry dict."""
    if releases is None:
        releases = [
            {"version": "1.0.0", "release_date": "2024-01-01"},
            {"version": "1.5.0", "release_date": "2024-06-01"},
            {"version": "2.0.0", "release_date": "2025-01-01"},
        ]
    return {
        "uid": uid,
        "title": title,
        "app_id": app_id,
        "latest_version": latest_version,
        "latest_release_date": "2025-01-01",
        "releases": releases,
    }


# ===========================================================================
# TestSplunkbaseFetcher — 15 tests
# ===========================================================================


class TestSplunkbaseFetcher:
    """Tests for SplunkbaseFetcher catalog lookup, version path, and cache."""

    def _make_fetcher(self, tmp_path: Path, catalog_apps: Dict = None) -> "SplunkbaseFetcher":
        """Create a SplunkbaseFetcher with a mocked catalog."""
        from chat_app.upgrade_readiness.splunkbase_fetcher import SplunkbaseFetcher

        fetcher = SplunkbaseFetcher(cache_dir=str(tmp_path))

        # Mock the catalog property
        mock_catalog = MagicMock()
        mock_catalog.catalog = {
            "apps": {
                "1234": _make_catalog_entry(),
                "5678": _make_catalog_entry(
                    app_id="Splunk_TA_windows",
                    uid="5678",
                    title="Splunk Add-on for Windows",
                    latest_version="9.0.0",
                    releases=[
                        {"version": "8.0.0", "release_date": "2023-01-01"},
                        {"version": "9.0.0", "release_date": "2024-01-01"},
                    ],
                ),
            }
        }
        if catalog_apps:
            mock_catalog.catalog["apps"].update(catalog_apps)

        fetcher._catalog_instance = mock_catalog
        return fetcher

    def test_find_app_by_app_id(self, tmp_path):
        """find_app returns entry when app_id matches."""
        fetcher = self._make_fetcher(tmp_path)
        result = fetcher.find_app("Splunk_TA_test")
        assert result is not None
        assert result["app_id"] == "Splunk_TA_test"

    def test_find_app_by_app_id_case_insensitive(self, tmp_path):
        """find_app is case-insensitive."""
        fetcher = self._make_fetcher(tmp_path)
        result = fetcher.find_app("splunk_ta_test")
        assert result is not None

    def test_find_app_by_title(self, tmp_path):
        """find_app falls back to title matching."""
        fetcher = self._make_fetcher(tmp_path)
        result = fetcher.find_app("Splunk Add-on for Windows")
        assert result is not None
        assert result["uid"] == "5678"

    def test_find_app_not_in_catalog(self, tmp_path):
        """find_app returns None for unknown apps."""
        fetcher = self._make_fetcher(tmp_path)
        result = fetcher.find_app("Unknown_App_XYZ")
        assert result is None

    def test_find_app_catalog_not_loaded(self, tmp_path):
        """find_app returns None gracefully when catalog fails to load."""
        from chat_app.upgrade_readiness.splunkbase_fetcher import SplunkbaseFetcher

        fetcher = SplunkbaseFetcher(cache_dir=str(tmp_path))

        # Mock catalog with empty apps dict so find_app returns None cleanly
        mock_catalog = MagicMock()
        mock_catalog.catalog = {"apps": {}}
        fetcher._catalog_instance = mock_catalog

        result = fetcher.find_app("any_app_not_in_catalog")
        assert result is None

    def test_get_upgrade_path_returns_newer_versions(self, tmp_path):
        """get_upgrade_path returns only versions newer than from_version."""
        fetcher = self._make_fetcher(tmp_path)
        path = fetcher.get_upgrade_path("Splunk_TA_test", "1.0.0")
        assert len(path) == 2
        versions = [r["version"] for r in path]
        assert "1.5.0" in versions
        assert "2.0.0" in versions
        assert "1.0.0" not in versions

    def test_get_upgrade_path_sorted_oldest_first(self, tmp_path):
        """get_upgrade_path is sorted oldest version first."""
        fetcher = self._make_fetcher(tmp_path)
        path = fetcher.get_upgrade_path("Splunk_TA_test", "1.0.0")
        assert len(path) >= 2
        versions = [r["version"] for r in path]
        assert versions == sorted(versions, key=lambda v: tuple(int(x) for x in v.split(".")))

    def test_get_upgrade_path_empty_when_at_latest(self, tmp_path):
        """get_upgrade_path returns empty list when already at latest."""
        fetcher = self._make_fetcher(tmp_path)
        path = fetcher.get_upgrade_path("Splunk_TA_test", "2.0.0")
        assert path == []

    def test_get_upgrade_path_unknown_app(self, tmp_path):
        """get_upgrade_path returns empty list for unknown apps."""
        fetcher = self._make_fetcher(tmp_path)
        path = fetcher.get_upgrade_path("unknown_app", "1.0.0")
        assert path == []

    def test_get_cached_versions_empty_dir(self, tmp_path):
        """get_cached_versions returns empty list when nothing cached."""
        fetcher = self._make_fetcher(tmp_path)
        result = fetcher.get_cached_versions("Splunk_TA_test")
        assert result == []

    def test_get_cached_versions_with_cache(self, tmp_path):
        """get_cached_versions returns version strings for cached dirs."""
        fetcher = self._make_fetcher(tmp_path)
        app_cache = tmp_path / "Splunk_TA_test"
        (app_cache / "Splunk_TA_test-1.0.0").mkdir(parents=True)
        (app_cache / "Splunk_TA_test-2.0.0").mkdir(parents=True)

        result = fetcher.get_cached_versions("Splunk_TA_test")
        assert "1.0.0" in result
        assert "2.0.0" in result

    def test_extract_tgz_creates_directory(self, tmp_path):
        """extract_tgz correctly extracts a .tgz and returns inner app dir."""
        from chat_app.upgrade_readiness.splunkbase_fetcher import SplunkbaseFetcher

        fetcher = SplunkbaseFetcher(cache_dir=str(tmp_path))

        # Create a minimal .tgz with an app directory structure
        app_dir = tmp_path / "Splunk_TA_test"
        default_dir = app_dir / "default"
        default_dir.mkdir(parents=True)
        (default_dir / "props.conf").write_text("[source::test]\nTIME_FORMAT=%Y\n")

        tgz_path = tmp_path / "test.tgz"
        with tarfile.open(str(tgz_path), "w:gz") as tf:
            tf.add(str(app_dir), arcname="Splunk_TA_test")

        extract_dest = tmp_path / "extracted"
        result = fetcher.extract_tgz(str(tgz_path), str(extract_dest))

        assert Path(result).is_dir()
        assert (Path(result) / "default" / "props.conf").exists()

    def test_extract_tgz_empty_archive_raises(self, tmp_path):
        """extract_tgz raises ValueError on empty archive."""
        from chat_app.upgrade_readiness.splunkbase_fetcher import SplunkbaseFetcher

        fetcher = SplunkbaseFetcher(cache_dir=str(tmp_path))
        tgz_path = tmp_path / "empty.tgz"
        with tarfile.open(str(tgz_path), "w:gz"):
            pass  # empty archive

        with pytest.raises(ValueError, match="empty"):
            fetcher.extract_tgz(str(tgz_path), str(tmp_path / "dest"))

    def test_download_version_returns_cached_path(self, tmp_path):
        """download_version returns cached path without downloading."""
        fetcher = self._make_fetcher(tmp_path)

        # Pre-create a cached extraction
        cached = tmp_path / "Splunk_TA_test" / "Splunk_TA_test-2.0.0"
        (cached / "default").mkdir(parents=True)

        result = asyncio.run(
            fetcher.download_version("Splunk_TA_test", "2.0.0")
        )
        assert result == str(cached)

    def test_download_version_returns_none_when_api_fails(self, tmp_path):
        """download_version returns None gracefully when network fails."""
        fetcher = self._make_fetcher(tmp_path)

        # Add a download URL to the catalog entry
        entry = fetcher.find_app("Splunk_TA_test")
        entry["releases"][0]["download_url"] = "http://invalid.localhost/test.tgz"

        # Mock _sync_download to always fail
        with patch.object(fetcher, "_sync_download", return_value=False):
            result = asyncio.run(
                fetcher.download_version("Splunk_TA_test", "1.0.0")
            )
        assert result is None


# ===========================================================================
# TestContainerTester — 10 tests
# ===========================================================================


class TestContainerTester:
    """Tests for SplunkTestContainer lifecycle with mocked podman."""

    def _mock_podman_success(self, stdout: str = "container123"):
        """Patch _run_podman to return success with given stdout."""
        return patch(
            "chat_app.upgrade_readiness.container_tester._run_podman",
            return_value=(0, stdout, ""),
        )

    def _mock_podman_failure(self, stderr: str = "error"):
        """Patch _run_podman to return failure."""
        return patch(
            "chat_app.upgrade_readiness.container_tester._run_podman",
            return_value=(1, "", stderr),
        )

    def test_deploy_returns_container_id(self, tmp_path):
        """deploy() returns the container ID from podman run output."""
        from chat_app.upgrade_readiness.container_tester import SplunkTestContainer

        tester = SplunkTestContainer()
        with self._mock_podman_success("abc123def456"):
            cid = asyncio.run(
                tester.deploy("cluster-es", {}, "9.3.2")
            )
        assert cid == "abc123def456"

    def test_deploy_raises_on_failure(self, tmp_path):
        """deploy() raises RuntimeError when podman fails."""
        from chat_app.upgrade_readiness.container_tester import SplunkTestContainer

        tester = SplunkTestContainer()
        with self._mock_podman_failure("no such image"):
            with pytest.raises(RuntimeError, match="Failed to create"):
                asyncio.run(
                    tester.deploy("cluster-es", {}, "9.3.2")
                )

    def test_wait_ready_returns_true_on_success(self):
        """wait_ready returns True when 'splunkd is running' in output."""
        from chat_app.upgrade_readiness.container_tester import SplunkTestContainer

        tester = SplunkTestContainer()
        with patch(
            "chat_app.upgrade_readiness.container_tester._run_podman",
            return_value=(0, "splunkd is running", ""),
        ):
            result = asyncio.run(
                tester.wait_ready("container123", timeout=10)
            )
        assert result is True

    def test_wait_ready_returns_false_on_timeout(self):
        """wait_ready returns False after timeout when Splunk never starts."""
        from chat_app.upgrade_readiness.container_tester import SplunkTestContainer

        tester = SplunkTestContainer()
        with patch(
            "chat_app.upgrade_readiness.container_tester._run_podman",
            return_value=(1, "", "splunk not running"),
        ):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                result = asyncio.run(
                    tester.wait_ready("container123", timeout=1)
                )
        assert result is False

    def test_capture_state_returns_dict(self):
        """capture_state returns a dict with expected keys."""
        from chat_app.upgrade_readiness.container_tester import SplunkTestContainer

        tester = SplunkTestContainer()
        # Return valid JSON paging response
        paging_json = json.dumps({"paging": {"total": 5}, "entry": []})
        with patch(
            "chat_app.upgrade_readiness.container_tester._run_podman",
            return_value=(0, paging_json, ""),
        ):
            state = asyncio.run(
                tester.capture_state("container123")
            )
        assert isinstance(state, dict)
        assert "captured_at" in state
        assert "container_id" in state

    def test_run_validation_tests_returns_15_results(self):
        """run_validation_tests returns exactly 15 ContainerTestResult objects."""
        from chat_app.upgrade_readiness.container_tester import SplunkTestContainer

        tester = SplunkTestContainer()
        with self._mock_podman_success("some output"):
            results = asyncio.run(
                tester.run_validation_tests("container123")
            )
        assert len(results) == 15

    def test_run_validation_tests_marks_passed_on_exit_0(self):
        """run_validation_tests marks tests as PASSED when exit code is 0."""
        from chat_app.upgrade_readiness.container_tester import SplunkTestContainer
        from chat_app.upgrade_readiness.models import TestStatus

        tester = SplunkTestContainer()
        with self._mock_podman_success("ok"):
            results = asyncio.run(
                tester.run_validation_tests("container123")
            )
        assert all(r.status == TestStatus.PASSED for r in results)

    def test_run_validation_tests_marks_failed_on_nonzero(self):
        """run_validation_tests marks tests as FAILED when exit code is non-zero."""
        from chat_app.upgrade_readiness.container_tester import SplunkTestContainer
        from chat_app.upgrade_readiness.models import TestStatus

        tester = SplunkTestContainer()
        with self._mock_podman_failure("command failed"):
            results = asyncio.run(
                tester.run_validation_tests("container123")
            )
        assert all(r.status == TestStatus.FAILED for r in results)

    def test_cleanup_calls_stop_and_rm(self):
        """cleanup() calls podman stop and podman rm."""
        from chat_app.upgrade_readiness.container_tester import SplunkTestContainer

        tester = SplunkTestContainer()
        calls = []

        def _capture(*args, timeout=60):
            calls.append(args)
            return 0, "", ""

        with patch("chat_app.upgrade_readiness.container_tester._run_podman", side_effect=_capture):
            asyncio.run(tester.cleanup("container123"))

        command_words = [" ".join(str(a) for a in call) for call in calls]
        assert any("stop" in c for c in command_words)
        assert any("rm" in c for c in command_words)

    def test_apply_upgrade_raises_on_stop_failure(self):
        """apply_upgrade raises RuntimeError when podman stop fails."""
        from chat_app.upgrade_readiness.container_tester import SplunkTestContainer

        tester = SplunkTestContainer()
        with patch(
            "chat_app.upgrade_readiness.container_tester._run_podman",
            return_value=(1, "", "cannot stop container"),
        ):
            with pytest.raises(RuntimeError, match="Could not stop Splunk"):
                asyncio.run(
                    tester.apply_upgrade("container123", "Splunk_TA_test", "/tmp/new_app")
                )


# ===========================================================================
# TestUFTestEnvironment — 10 tests
# ===========================================================================


class TestUFTestEnvironment:
    """Tests for the two-container UF → Indexer test environment."""

    def _mock_podman(self, stdout: str = "container456"):
        return patch(
            "chat_app.upgrade_readiness.container_tester._run_podman",
            return_value=(0, stdout, ""),
        )

    def test_deploy_returns_uf_and_indexer_ids(self):
        """deploy() returns a (uf_id, indexer_id) tuple."""
        from chat_app.upgrade_readiness.container_tester import UFTestEnvironment

        env = UFTestEnvironment()
        call_count = [0]

        def _sequential(*args, timeout=60):
            # network create → indexer → inspect → uf
            call_count[0] += 1
            if call_count[0] == 1:
                return 0, "", ""  # network create
            elif call_count[0] == 2:
                return 0, "indexer_container_id", ""
            elif call_count[0] == 3:
                return 0, "obsai-indexer-name", ""  # inspect
            else:
                return 0, "uf_container_id", ""

        with patch("chat_app.upgrade_readiness.container_tester._run_podman", side_effect=_sequential):
            uf_id, indexer_id = asyncio.run(
                env.deploy("9.3.2", "9.3.2", {}, {})
            )

        assert uf_id == "uf_container_id"
        assert indexer_id == "indexer_container_id"

    def test_deploy_creates_isolated_network(self):
        """deploy() calls podman network create."""
        from chat_app.upgrade_readiness.container_tester import UFTestEnvironment

        env = UFTestEnvironment()
        calls = []

        def _capture(*args, timeout=60):
            calls.append(args)
            return 0, "some_id", ""

        with patch("chat_app.upgrade_readiness.container_tester._run_podman", side_effect=_capture):
            asyncio.run(
                env.deploy("9.3.2", "9.3.2", {}, {})
            )

        all_args = " ".join(str(a) for call in calls for a in call)
        assert "network" in all_args
        assert "create" in all_args

    def test_send_test_events_calls_exec(self):
        """send_test_events writes events via podman exec."""
        from chat_app.upgrade_readiness.container_tester import UFTestEnvironment

        env = UFTestEnvironment()
        calls = []

        def _capture(*args, timeout=60):
            calls.append(args)
            return 0, "", ""

        with patch("chat_app.upgrade_readiness.container_tester._run_podman", side_effect=_capture):
            asyncio.run(
                env.send_test_events("uf123", ["event1", "event2"])
            )

        assert len(calls) == 2
        all_args = " ".join(str(a) for call in calls for a in call)
        assert "exec" in all_args

    def test_verify_received_returns_true_on_sufficient_count(self):
        """verify_received returns True when search finds enough events."""
        from chat_app.upgrade_readiness.container_tester import UFTestEnvironment

        env = UFTestEnvironment()
        with patch(
            "chat_app.upgrade_readiness.container_tester._run_podman",
            return_value=(0, "count\n----\n10\n", ""),
        ):
            result = asyncio.run(
                env.verify_received("indexer123", 5)
            )
        assert result is True

    def test_verify_received_returns_false_on_too_few(self):
        """verify_received returns False when count is below expected."""
        from chat_app.upgrade_readiness.container_tester import UFTestEnvironment

        env = UFTestEnvironment()
        with patch(
            "chat_app.upgrade_readiness.container_tester._run_podman",
            return_value=(0, "count\n----\n2\n", ""),
        ):
            result = asyncio.run(
                env.verify_received("indexer123", 10)
            )
        assert result is False

    def test_verify_received_returns_false_on_search_failure(self):
        """verify_received returns False when podman exec returns non-zero."""
        from chat_app.upgrade_readiness.container_tester import UFTestEnvironment

        env = UFTestEnvironment()
        with patch(
            "chat_app.upgrade_readiness.container_tester._run_podman",
            return_value=(1, "", "search failed"),
        ):
            result = asyncio.run(
                env.verify_received("indexer123", 1)
            )
        assert result is False

    def test_cleanup_removes_both_containers(self):
        """cleanup removes both UF and indexer containers."""
        from chat_app.upgrade_readiness.container_tester import UFTestEnvironment

        env = UFTestEnvironment()
        env._network_name = "test-network"
        calls = []

        def _capture(*args, timeout=60):
            calls.append(args)
            return 0, "", ""

        with patch("chat_app.upgrade_readiness.container_tester._run_podman", side_effect=_capture):
            asyncio.run(
                env.cleanup("uf123", "indexer456")
            )

        all_args = " ".join(str(a) for call in calls for a in call)
        assert "uf123" in all_args
        assert "indexer456" in all_args

    def test_cleanup_removes_network(self):
        """cleanup calls podman network rm."""
        from chat_app.upgrade_readiness.container_tester import UFTestEnvironment

        env = UFTestEnvironment()
        env._network_name = "obsai-uf-test-net"
        calls = []

        def _capture(*args, timeout=60):
            calls.append(args)
            return 0, "", ""

        with patch("chat_app.upgrade_readiness.container_tester._run_podman", side_effect=_capture):
            asyncio.run(
                env.cleanup("uf123", "indexer456")
            )

        all_args = " ".join(str(a) for call in calls for a in call)
        assert "network" in all_args
        assert "rm" in all_args

    def test_cleanup_clears_network_name(self):
        """cleanup sets _network_name to None after removal."""
        from chat_app.upgrade_readiness.container_tester import UFTestEnvironment

        env = UFTestEnvironment()
        env._network_name = "test-net"

        with patch(
            "chat_app.upgrade_readiness.container_tester._run_podman",
            return_value=(0, "", ""),
        ):
            asyncio.run(
                env.cleanup("uf1", "idx1")
            )

        assert env._network_name is None

    def test_deploy_raises_on_indexer_failure(self):
        """deploy raises RuntimeError when indexer container fails to start."""
        from chat_app.upgrade_readiness.container_tester import UFTestEnvironment

        env = UFTestEnvironment()
        call_count = [0]

        def _sequential(*args, timeout=60):
            call_count[0] += 1
            if call_count[0] == 1:
                return 0, "", ""  # network create
            return 1, "", "image not found"  # indexer deploy fails

        with patch("chat_app.upgrade_readiness.container_tester._run_podman", side_effect=_sequential):
            with pytest.raises(RuntimeError, match="Indexer deploy failed"):
                asyncio.run(
                    env.deploy("9.3.2", "9.3.2", {}, {})
                )


# ===========================================================================
# TestReportBuilder — 15 tests
# ===========================================================================


class TestReportBuilder:
    """Tests for JSON/Markdown generation, save/load."""

    def _builder(self, tmp_path) -> "ReportBuilder":
        from chat_app.upgrade_readiness.report_builder import ReportBuilder
        return ReportBuilder(reports_dir=str(tmp_path))

    def test_to_json_contains_report_id(self, tmp_path):
        """to_json output contains the report_id."""
        builder = self._builder(tmp_path)
        report = _make_report()
        result = json.loads(builder.to_json(report))
        assert result["report_id"] == report.report_id

    def test_to_json_contains_all_required_fields(self, tmp_path):
        """to_json output has all required top-level fields."""
        builder = self._builder(tmp_path)
        report = _make_report()
        result = json.loads(builder.to_json(report))
        for field in ["app_id", "from_version", "to_version", "cluster",
                      "overall_risk", "recommendation", "findings", "generated_at"]:
            assert field in result, f"Missing field: {field}"

    def test_to_json_serialises_findings(self, tmp_path):
        """to_json includes all findings with their fields."""
        builder = self._builder(tmp_path)
        finding = _make_finding()
        report = _make_report(findings=[finding])
        result = json.loads(builder.to_json(report))
        assert len(result["findings"]) == 1
        assert result["findings"][0]["risk"] == "HIGH"
        assert result["findings"][0]["conf_type"] == "props"

    def test_to_json_risk_counts(self, tmp_path):
        """to_json includes risk_counts dict."""
        builder = self._builder(tmp_path)
        finding = _make_finding(risk="CRITICAL")
        report = _make_report(findings=[finding])
        result = json.loads(builder.to_json(report))
        assert "risk_counts" in result
        assert result["risk_counts"]["CRITICAL"] == 1

    def test_to_markdown_contains_title(self, tmp_path):
        """to_markdown output starts with the app name as title."""
        builder = self._builder(tmp_path)
        report = _make_report()
        md = builder.to_markdown(report)
        assert "Splunk_TA_test" in md
        assert "# Upgrade Readiness Report" in md

    def test_to_markdown_contains_summary_section(self, tmp_path):
        """to_markdown output contains a Summary section."""
        builder = self._builder(tmp_path)
        report = _make_report()
        md = builder.to_markdown(report)
        assert "## Summary" in md
        assert "MEDIUM" in md

    def test_to_markdown_contains_findings_section(self, tmp_path):
        """to_markdown lists findings when present."""
        builder = self._builder(tmp_path)
        finding = _make_finding(risk="HIGH")
        report = _make_report(findings=[finding])
        md = builder.to_markdown(report)
        assert "## Findings by Severity" in md
        assert "HIGH" in md
        assert "LINE_BREAKER" in md

    def test_to_markdown_remediation_plan_present(self, tmp_path):
        """to_markdown always contains a Remediation Plan section."""
        builder = self._builder(tmp_path)
        report = _make_report()
        md = builder.to_markdown(report)
        assert "## Remediation Plan" in md

    def test_to_markdown_critical_findings_in_remediation(self, tmp_path):
        """to_markdown includes CRITICAL findings in the remediation plan steps."""
        builder = self._builder(tmp_path)
        finding = _make_finding(risk="CRITICAL")
        report = _make_report(findings=[finding])
        md = builder.to_markdown(report)
        assert "CRITICAL" in md
        assert "1." in md  # numbered steps

    def test_save_report_creates_file(self, tmp_path):
        """save_report writes a JSON file to the reports directory."""
        builder = self._builder(tmp_path)
        report = _make_report()
        path = builder.save_report(report)
        assert Path(path).exists()
        content = json.loads(Path(path).read_text())
        assert content["report_id"] == report.report_id

    def test_load_report_roundtrip(self, tmp_path):
        """A saved report can be loaded back and matches the original."""
        builder = self._builder(tmp_path)
        report = _make_report()
        builder.save_report(report)

        loaded = builder.load_report(report.report_id)
        assert loaded is not None
        assert loaded.report_id == report.report_id
        assert loaded.app_id == report.app_id
        assert loaded.from_version == report.from_version

    def test_load_report_returns_none_for_missing(self, tmp_path):
        """load_report returns None for non-existent report IDs."""
        builder = self._builder(tmp_path)
        result = builder.load_report("nonexistent-uuid-0000")
        assert result is None

    def test_list_reports_empty(self, tmp_path):
        """list_reports returns empty list when no reports saved."""
        builder = self._builder(tmp_path)
        result = builder.list_reports()
        assert result == []

    def test_list_reports_returns_summaries(self, tmp_path):
        """list_reports returns one entry per saved report."""
        builder = self._builder(tmp_path)
        r1 = _make_report(app_id="App1")
        r2 = _make_report(app_id="App2")
        builder.save_report(r1)
        builder.save_report(r2)

        summaries = builder.list_reports()
        assert len(summaries) == 2
        app_ids = {s["app_id"] for s in summaries}
        assert "App1" in app_ids
        assert "App2" in app_ids

    def test_build_report_escalates_risk_on_container_failures(self, tmp_path):
        """build_report escalates overall_risk when container tests fail."""
        from chat_app.upgrade_readiness.models import ContainerTestResult, TestStatus, UpgradeRisk
        from chat_app.upgrade_readiness.report_builder import ReportBuilder

        builder = ReportBuilder(reports_dir=str(tmp_path))
        report = _make_report()
        report.overall_risk = UpgradeRisk.LOW

        container_results = [
            ContainerTestResult(
                test_id="conf_merge",
                name="Conf Merge",
                status=TestStatus.FAILED,
                output="",
            )
        ]

        enriched = builder.build_report(report, container_results=container_results)
        assert enriched.overall_risk >= UpgradeRisk.HIGH


# ===========================================================================
# TestAdminUpgradeAPI — 15 tests
# ===========================================================================


class TestAdminUpgradeAPI:
    """Tests for all /api/admin/upgrade/* endpoints via TestClient."""

    @pytest.fixture()
    def client(self):
        """Create a FastAPI TestClient with auth bypassed."""
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from chat_app.admin_upgrade_routes import upgrade_router
        from chat_app.auth_dependencies import get_authenticated_user, require_admin
        from chat_app.admin_shared import (
            _csrf_check, _rate_limit, _track_audit_user,
        )

        def _fake_admin_user():
            return {"username": "test_admin", "role": "ADMIN"}

        test_app = FastAPI()

        # Bypass all auth/rate-limit/CSRF dependencies
        test_app.dependency_overrides[get_authenticated_user] = _fake_admin_user
        test_app.dependency_overrides[require_admin] = lambda: None
        test_app.dependency_overrides[_csrf_check] = lambda: None
        test_app.dependency_overrides[_rate_limit] = lambda: None
        test_app.dependency_overrides[_track_audit_user] = lambda: None

        test_app.include_router(upgrade_router)
        return TestClient(test_app)

    def test_get_inventory_empty(self, client):
        """GET /upgrade/inventory returns empty status when no scan done."""
        import chat_app.admin_upgrade_routes as routes
        routes._inventory_cache.clear()

        resp = client.get("/api/admin/upgrade/inventory")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "empty"

    def test_get_inventory_with_data(self, client):
        """GET /upgrade/inventory returns cluster info after scan."""
        import chat_app.admin_upgrade_routes as routes
        from chat_app.upgrade_readiness.models import ClusterInventory

        routes._inventory_cache["cluster-es"] = ClusterInventory(cluster_name="cluster-es")

        resp = client.get("/api/admin/upgrade/inventory")
        assert resp.status_code == 200
        data = resp.json()
        assert "cluster-es" in data["clusters"]

        routes._inventory_cache.clear()

    def test_scan_inventory_no_cluster_dirs(self, client, tmp_path):
        """POST /upgrade/inventory/scan with empty repo returns no scanned clusters."""
        resp = client.post(
            "/api/admin/upgrade/inventory/scan",
            json={"repo_path": str(tmp_path)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_scan_inventory_with_cluster_dir(self, client, tmp_path):
        """POST /upgrade/inventory/scan detects cluster directories."""
        cluster_dir = tmp_path / "cluster-es" / "apps" / "Splunk_TA_test"
        (cluster_dir / "default").mkdir(parents=True)
        (cluster_dir / "default" / "app.conf").write_text("[launcher]\nversion=1.0.0\nauthor=test\n")

        resp = client.post(
            "/api/admin/upgrade/inventory/scan",
            json={"repo_path": str(tmp_path)},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_get_cluster_inventory_not_found(self, client):
        """GET /upgrade/inventory/{cluster} returns 404 for unknown cluster."""
        import chat_app.admin_upgrade_routes as routes
        routes._inventory_cache.clear()

        resp = client.get("/api/admin/upgrade/inventory/unknown_cluster")
        assert resp.status_code == 404

    def test_get_cluster_inventory_found(self, client):
        """GET /upgrade/inventory/{cluster} returns apps list when cached."""
        import chat_app.admin_upgrade_routes as routes
        from chat_app.upgrade_readiness.models import AppBaseline, AppVersion, ClusterInventory

        inventory = ClusterInventory(cluster_name="cluster-test")
        inventory.apps["Splunk_TA_example"] = AppBaseline(
            app_id="Splunk_TA_example",
            version=AppVersion(app_id="Splunk_TA_example", version="1.2.3"),
        )
        routes._inventory_cache["cluster-test"] = inventory

        resp = client.get("/api/admin/upgrade/inventory/cluster-test")
        assert resp.status_code == 200
        data = resp.json()
        assert "Splunk_TA_example" in data["apps"]
        assert data["apps"]["Splunk_TA_example"]["version"] == "1.2.3"

        routes._inventory_cache.clear()

    def test_get_candidates_empty_inventory(self, client):
        """GET /upgrade/candidates returns empty when no inventory."""
        import chat_app.admin_upgrade_routes as routes
        routes._inventory_cache.clear()

        resp = client.get("/api/admin/upgrade/candidates")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "empty"

    def test_list_reports_empty(self, client, tmp_path):
        """GET /upgrade/reports returns empty list when no reports."""
        with patch("chat_app.admin_upgrade_routes._get_report_builder") as mock_builder:
            mock_builder.return_value.list_reports.return_value = []
            resp = client.get("/api/admin/upgrade/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0

    def test_list_reports_returns_summaries(self, client):
        """GET /upgrade/reports returns report summaries."""
        summaries = [
            {"report_id": "abc", "app_id": "Splunk_TA_test",
             "from_version": "1.0", "to_version": "2.0",
             "cluster": "cluster-es", "overall_risk": "HIGH", "generated_at": "2025-01-01"},
        ]
        with patch("chat_app.admin_upgrade_routes._get_report_builder") as mock_builder:
            mock_builder.return_value.list_reports.return_value = summaries
            resp = client.get("/api/admin/upgrade/reports")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1

    def test_get_report_not_found(self, client):
        """GET /upgrade/reports/{id} returns 404 for unknown ID."""
        import chat_app.admin_upgrade_routes as routes
        routes._report_cache.clear()

        with patch("chat_app.admin_upgrade_routes._get_report_builder") as mock_builder:
            mock_builder.return_value.load_report.return_value = None
            resp = client.get("/api/admin/upgrade/reports/nonexistent-id")
        assert resp.status_code == 404

    def test_get_report_found(self, client):
        """GET /upgrade/reports/{id} returns the report when cached."""
        import chat_app.admin_upgrade_routes as routes

        report = _make_report()
        routes._report_cache[report.report_id] = report

        json_str = json.dumps({"report_id": report.report_id, "app_id": "Splunk_TA_test"})
        with patch("chat_app.admin_upgrade_routes._get_report_builder") as mock_builder:
            mock_builder.return_value.to_json.return_value = json_str
            resp = client.get(f"/api/admin/upgrade/reports/{report.report_id}")

        assert resp.status_code == 200
        routes._report_cache.clear()

    def test_get_cim_cluster_not_found(self, client):
        """GET /upgrade/cim/{cluster}/{app} returns 404 for unknown cluster."""
        import chat_app.admin_upgrade_routes as routes
        routes._inventory_cache.clear()

        resp = client.get("/api/admin/upgrade/cim/no_such_cluster/some_app")
        assert resp.status_code == 404

    def test_get_dependencies_cluster_not_found(self, client):
        """GET /upgrade/dependencies/{cluster} returns 404 for unknown cluster."""
        import chat_app.admin_upgrade_routes as routes
        routes._inventory_cache.clear()

        resp = client.get("/api/admin/upgrade/dependencies/no_such_cluster")
        assert resp.status_code == 404

    def test_get_test_results_not_found(self, client):
        """GET /upgrade/test/{suite_id} returns 404 for unknown suite ID."""
        import chat_app.admin_upgrade_routes as routes
        routes._test_suites.clear()

        resp = client.get("/api/admin/upgrade/test/nonexistent-suite-id")
        assert resp.status_code == 404

    def test_get_test_results_found(self, client):
        """GET /upgrade/test/{suite_id} returns suite data when present."""
        import chat_app.admin_upgrade_routes as routes
        from chat_app.upgrade_readiness.models import ContainerTestSuite, TestStatus

        suite = ContainerTestSuite(
            app_id="Splunk_TA_test",
            from_version="1.0.0",
            to_version="2.0.0",
        )
        suite.status = TestStatus.PASSED
        routes._test_suites[suite.suite_id] = suite

        resp = client.get(f"/api/admin/upgrade/test/{suite.suite_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["app_id"] == "Splunk_TA_test"
        assert data["status"] == "PASSED"

        routes._test_suites.clear()
