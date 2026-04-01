"""Tests for chat_app.splunkbase_catalog — Splunkbase add-on version validator."""

import json
import pytest
import asyncio
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from chat_app.splunkbase_catalog import (
    SplunkbaseCatalog,
    _parse_version_tuple,
    _is_outdated,
    _now_iso,
    get_splunkbase_catalog,
    rebuild_splunkbase_catalog,
    run_catalog_update,
    run_comparison_report,
    SPLUNKBASE_API_BASE,
)


# ---------------------------------------------------------------------------
# Version parsing tests
# ---------------------------------------------------------------------------

class TestVersionParsing:
    """Test version string parsing and comparison."""

    def test_parse_simple_version(self):
        assert _parse_version_tuple("1.2.3") == (1, 2, 3)

    def test_parse_two_part_version(self):
        assert _parse_version_tuple("3.5") == (3, 5)

    def test_parse_single_part(self):
        assert _parse_version_tuple("7") == (7,)

    def test_parse_four_part_version(self):
        assert _parse_version_tuple("1.2.3.4") == (1, 2, 3, 4)

    def test_parse_non_numeric_segment(self):
        assert _parse_version_tuple("1.2.beta") == (1, 2, 0)

    def test_parse_empty_string(self):
        assert _parse_version_tuple("") == (0,)

    def test_is_outdated_true(self):
        assert _is_outdated("1.0.0", "2.0.0") is True
        assert _is_outdated("4.1.0", "4.2.0") is True
        assert _is_outdated("4.2.0", "4.2.1") is True

    def test_is_outdated_false(self):
        assert _is_outdated("2.0.0", "2.0.0") is False
        assert _is_outdated("3.0.0", "2.0.0") is False

    def test_is_outdated_mixed_length(self):
        assert _is_outdated("1.0", "1.0.1") is True
        assert _is_outdated("1.0.1", "1.0") is False


# ---------------------------------------------------------------------------
# Catalog I/O tests
# ---------------------------------------------------------------------------

class TestCatalogIO:
    """Test catalog load/save from local JSON."""

    def test_load_empty_catalog(self, tmp_path):
        catalog = SplunkbaseCatalog(catalog_path=str(tmp_path / "catalog.json"))
        result = catalog.load_catalog()
        assert result == {"metadata": {}, "apps": {}}
        assert catalog.app_count == 0

    def test_save_and_load_catalog(self, tmp_path):
        path = str(tmp_path / "catalog.json")
        catalog = SplunkbaseCatalog(catalog_path=path)
        catalog._catalog = {
            "metadata": {"last_updated": "2026-01-01T00:00:00+00:00", "total_apps": 1},
            "apps": {
                "1234": {
                    "uid": "1234",
                    "title": "Splunk Add-on for Windows",
                    "app_id": "Splunk_TA_windows",
                    "latest_version": "8.1.0",
                    "releases": [],
                    "last_fetched": "2026-01-01T00:00:00+00:00",
                }
            },
        }
        catalog.save_catalog()

        # Load it back in a new instance
        catalog2 = SplunkbaseCatalog(catalog_path=path)
        result = catalog2.load_catalog()
        assert result["metadata"]["total_apps"] == 1
        assert "1234" in result["apps"]
        assert result["apps"]["1234"]["title"] == "Splunk Add-on for Windows"
        assert catalog2.app_count == 1

    def test_load_corrupt_file(self, tmp_path):
        path = tmp_path / "corrupt.json"
        path.write_text("not valid json{{{", encoding="utf-8")
        catalog = SplunkbaseCatalog(catalog_path=str(path))
        result = catalog.load_catalog()
        assert result == {"metadata": {}, "apps": {}}

    def test_save_creates_directories(self, tmp_path):
        path = str(tmp_path / "nested" / "dir" / "catalog.json")
        catalog = SplunkbaseCatalog(catalog_path=path)
        catalog._catalog = {"metadata": {}, "apps": {"1": {"uid": "1"}}}
        catalog.save_catalog()
        assert Path(path).is_file()

    def test_catalog_property_lazy_loads(self, tmp_path):
        path = tmp_path / "catalog.json"
        data = {"metadata": {"total_apps": 2}, "apps": {"a": {}, "b": {}}}
        path.write_text(json.dumps(data), encoding="utf-8")
        catalog = SplunkbaseCatalog(catalog_path=str(path))
        assert not catalog._loaded
        # Accessing the property triggers lazy load
        result = catalog.catalog
        assert catalog._loaded
        assert len(result["apps"]) == 2


# ---------------------------------------------------------------------------
# HTTP fetch tests (mocked)
# ---------------------------------------------------------------------------

class TestSplunkbaseAPIFetch:
    """Test fetching from the Splunkbase REST API with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_fetch_app_list_success(self, tmp_path):
        catalog = SplunkbaseCatalog(catalog_path=str(tmp_path / "catalog.json"), max_apps=5)

        mock_response = {
            "results": [
                {"uid": "1001", "title": "App One"},
                {"uid": "1002", "title": "App Two"},
                {"uid": "1003", "title": "App Three"},
            ]
        }

        with patch.object(catalog, "_http_get", new_callable=AsyncMock, return_value=mock_response):
            apps = await catalog.fetch_app_list(limit=5)
            assert len(apps) == 3
            assert apps[0]["uid"] == "1001"

    @pytest.mark.asyncio
    async def test_fetch_app_list_pagination(self, tmp_path):
        catalog = SplunkbaseCatalog(catalog_path=str(tmp_path / "catalog.json"), max_apps=250)

        page1 = {"results": [{"uid": str(i)} for i in range(100)], "total": 150}
        page2 = {"results": [{"uid": str(i)} for i in range(100, 150)]}

        call_count = 0

        async def mock_get(url, params=None):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return page1
            return page2

        with patch.object(catalog, "_http_get", side_effect=mock_get):
            apps = await catalog.fetch_app_list(limit=250)
            assert len(apps) == 150
            assert call_count == 2

    @pytest.mark.asyncio
    async def test_fetch_app_list_api_failure(self, tmp_path):
        catalog = SplunkbaseCatalog(catalog_path=str(tmp_path / "catalog.json"))

        with patch.object(catalog, "_http_get", new_callable=AsyncMock, return_value=None):
            apps = await catalog.fetch_app_list()
            assert apps == []

    @pytest.mark.asyncio
    async def test_fetch_app_details_success(self, tmp_path):
        catalog = SplunkbaseCatalog(catalog_path=str(tmp_path / "catalog.json"))

        app_data = {
            "uid": "1234",
            "title": "Splunk Add-on for Windows",
            "appid": "Splunk_TA_windows",
            "sourcetypes": ["WinEventLog", "PerfmonMk"],
        }
        releases_data = {
            "results": [
                {
                    "name": "8.1.0",
                    "published_datetime": "2025-11-15T12:00:00+00:00",
                    "product_versions": [{"name": "9.4"}, {"name": "9.3"}],
                },
                {
                    "name": "8.0.0",
                    "published_datetime": "2025-06-01T12:00:00+00:00",
                    "product_versions": [{"name": "9.3"}, {"name": "9.2"}],
                },
            ]
        }

        call_count = 0

        async def mock_get(url, params=None, timeout=30.0):
            nonlocal call_count
            call_count += 1
            if "release" in url:
                return releases_data
            return app_data

        with patch.object(catalog, "_http_get", side_effect=mock_get):
            details = await catalog.fetch_app_details("1234")
            assert details is not None
            assert details["title"] == "Splunk Add-on for Windows"
            assert details["app_id"] == "Splunk_TA_windows"
            assert details["latest_version"] == "8.1.0"
            assert len(details["releases"]) == 2
            assert details["supported_splunk_versions"] == ["9.4", "9.3"]

    @pytest.mark.asyncio
    async def test_fetch_app_details_failure(self, tmp_path):
        catalog = SplunkbaseCatalog(catalog_path=str(tmp_path / "catalog.json"))

        with patch.object(catalog, "_http_get", new_callable=AsyncMock, return_value=None):
            details = await catalog.fetch_app_details("9999")
            assert details is None


# ---------------------------------------------------------------------------
# Catalog update tests
# ---------------------------------------------------------------------------

class TestCatalogUpdate:
    """Test catalog update workflow."""

    @pytest.mark.asyncio
    async def test_full_update(self, tmp_path):
        catalog = SplunkbaseCatalog(catalog_path=str(tmp_path / "catalog.json"), max_apps=3)

        app_list = [{"uid": "100"}, {"uid": "200"}]
        detail_100 = {
            "uid": "100", "title": "App A", "app_id": "app_a",
            "latest_version": "1.0.0", "releases": [],
            "latest_release_date": "", "supported_splunk_versions": [],
            "sourcetypes": [], "last_fetched": _now_iso(),
        }
        detail_200 = {
            "uid": "200", "title": "App B", "app_id": "app_b",
            "latest_version": "2.0.0", "releases": [],
            "latest_release_date": "", "supported_splunk_versions": [],
            "sourcetypes": [], "last_fetched": _now_iso(),
        }

        with patch.object(catalog, "fetch_app_list", new_callable=AsyncMock, return_value=app_list):
            async def mock_details(uid):
                if uid == "100":
                    return detail_100
                return detail_200

            with patch.object(catalog, "fetch_app_details", side_effect=mock_details):
                summary = await catalog.update_catalog(incremental=False)
                assert summary["added"] == 2
                assert summary["total"] == 2
                assert catalog.app_count == 2

    @pytest.mark.asyncio
    async def test_incremental_update(self, tmp_path):
        path = str(tmp_path / "catalog.json")
        catalog = SplunkbaseCatalog(catalog_path=path)
        catalog._catalog = {
            "metadata": {},
            "apps": {
                "100": {
                    "uid": "100", "title": "App A", "app_id": "app_a",
                    "latest_version": "1.0.0", "releases": [],
                },
            },
        }
        catalog._loaded = True

        updated_detail = {
            "uid": "100", "title": "App A", "app_id": "app_a",
            "latest_version": "1.1.0", "releases": [],
            "latest_release_date": "", "supported_splunk_versions": [],
            "sourcetypes": [], "last_fetched": _now_iso(),
        }

        with patch.object(catalog, "fetch_app_details", new_callable=AsyncMock, return_value=updated_detail):
            summary = await catalog.update_catalog(incremental=True)
            assert summary["updated"] == 1
            assert summary["added"] == 0
            assert catalog._catalog["apps"]["100"]["latest_version"] == "1.1.0"

    @pytest.mark.asyncio
    async def test_update_with_failures(self, tmp_path):
        path = str(tmp_path / "catalog.json")
        catalog = SplunkbaseCatalog(catalog_path=path)
        catalog._catalog = {
            "metadata": {},
            "apps": {
                "100": {"uid": "100"},
                "200": {"uid": "200"},
            },
        }
        catalog._loaded = True

        async def mock_details(uid):
            if uid == "100":
                return {"uid": "100", "title": "A", "app_id": "a",
                        "latest_version": "1.0", "releases": [],
                        "latest_release_date": "", "supported_splunk_versions": [],
                        "sourcetypes": [], "last_fetched": _now_iso()}
            return None  # Simulate failure

        with patch.object(catalog, "fetch_app_details", side_effect=mock_details):
            summary = await catalog.update_catalog(incremental=True)
            assert summary["updated"] == 1
            assert summary["failed"] == 1


# ---------------------------------------------------------------------------
# Installed apps from Splunk REST API (mocked)
# ---------------------------------------------------------------------------

class TestInstalledAppsFetch:
    """Test fetching installed apps from Splunk REST API."""

    @pytest.mark.asyncio
    async def test_get_installed_apps_success(self, tmp_path):
        catalog = SplunkbaseCatalog(catalog_path=str(tmp_path / "catalog.json"))

        splunk_response = {
            "entry": [
                {
                    "name": "Splunk_TA_windows",
                    "updated": "2025-10-01T00:00:00+00:00",
                    "content": {
                        "version": "8.0.0",
                        "label": "Splunk Add-on for Windows",
                        "visible": True,
                        "disabled": False,
                        "author": "Splunk",
                    },
                },
                {
                    "name": "search",
                    "updated": "2025-10-01T00:00:00+00:00",
                    "content": {
                        "version": "9.4.0",
                        "label": "Search & Reporting",
                        "visible": True,
                        "disabled": False,
                    },
                },
            ]
        }

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = splunk_response
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        with patch("chat_app.splunkbase_catalog.httpx", create=True) as mock_httpx:
            # We need to mock the import inside the method
            import httpx as real_httpx
            with patch.object(real_httpx, "AsyncClient", return_value=mock_client):
                installed = await catalog.get_installed_apps_from_splunk(
                    "https://splunk:8089", "test_token",
                )
                assert len(installed) == 2
                assert installed[0]["name"] == "Splunk_TA_windows"
                assert installed[0]["version"] == "8.0.0"

    @pytest.mark.asyncio
    async def test_get_installed_apps_connection_error(self, tmp_path):
        catalog = SplunkbaseCatalog(catalog_path=str(tmp_path / "catalog.json"))

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock()

        import httpx as real_httpx
        with patch.object(real_httpx, "AsyncClient", return_value=mock_client):
            installed = await catalog.get_installed_apps_from_splunk(
                "https://splunk:8089", "test_token",
            )
            assert installed == []


# ---------------------------------------------------------------------------
# Version comparison tests
# ---------------------------------------------------------------------------

class TestVersionComparison:
    """Test comparing installed apps against the catalog."""

    def _make_catalog_with_apps(self, tmp_path):
        """Helper to create a catalog with a few apps."""
        catalog = SplunkbaseCatalog(catalog_path=str(tmp_path / "catalog.json"))
        catalog._catalog = {
            "metadata": {"last_updated": _now_iso()},
            "apps": {
                "100": {
                    "uid": "100",
                    "title": "Splunk Add-on for Windows",
                    "app_id": "splunk_ta_windows",
                    "latest_version": "8.1.0",
                    "latest_release_date": "2025-11-15",
                    "supported_splunk_versions": ["9.4", "9.3"],
                    "sourcetypes": ["WinEventLog"],
                    "releases": [
                        {"version": "8.1.0", "release_date": "2025-11-15", "product_versions": []},
                        {"version": "8.0.0", "release_date": "2025-06-01", "product_versions": []},
                        {"version": "7.0.0", "release_date": "2024-01-01", "product_versions": []},
                    ],
                },
                "200": {
                    "uid": "200",
                    "title": "Splunk Add-on for Linux",
                    "app_id": "splunk_ta_nix",
                    "latest_version": "9.0.0",
                    "latest_release_date": "2025-12-01",
                    "supported_splunk_versions": ["9.4"],
                    "sourcetypes": ["syslog"],
                    "releases": [
                        {"version": "9.0.0", "release_date": "2025-12-01", "product_versions": []},
                    ],
                },
            },
        }
        catalog._loaded = True
        return catalog

    def test_outdated_app(self, tmp_path):
        catalog = self._make_catalog_with_apps(tmp_path)
        installed = [
            {"name": "splunk_ta_windows", "label": "Splunk Add-on for Windows", "version": "7.0.0"},
        ]
        result = catalog.compare_installed(installed)
        assert len(result["outdated"]) == 1
        assert result["outdated"][0]["installed_version"] == "7.0.0"
        assert result["outdated"][0]["latest_version"] == "8.1.0"
        assert result["outdated"][0]["versions_behind"] == 2

    def test_current_app(self, tmp_path):
        catalog = self._make_catalog_with_apps(tmp_path)
        installed = [
            {"name": "splunk_ta_nix", "label": "Splunk Add-on for Linux", "version": "9.0.0"},
        ]
        result = catalog.compare_installed(installed)
        assert len(result["current"]) == 1
        assert result["current"][0]["status"] == "current"

    def test_unknown_app(self, tmp_path):
        catalog = self._make_catalog_with_apps(tmp_path)
        installed = [
            {"name": "my_custom_app", "label": "My Custom App", "version": "1.0.0"},
        ]
        result = catalog.compare_installed(installed)
        assert len(result["unknown"]) == 1
        assert result["unknown"][0]["status"] == "not_in_catalog"

    def test_mixed_results(self, tmp_path):
        catalog = self._make_catalog_with_apps(tmp_path)
        installed = [
            {"name": "splunk_ta_windows", "label": "Splunk Add-on for Windows", "version": "7.0.0"},
            {"name": "splunk_ta_nix", "label": "Splunk Add-on for Linux", "version": "9.0.0"},
            {"name": "custom_app", "label": "Custom", "version": "1.0"},
        ]
        result = catalog.compare_installed(installed)
        assert result["summary"]["total_installed"] == 3
        assert result["summary"]["outdated_count"] == 1
        assert result["summary"]["current_count"] == 1
        assert result["summary"]["unknown_count"] == 1

    def test_unknown_version_string(self, tmp_path):
        catalog = self._make_catalog_with_apps(tmp_path)
        installed = [
            {"name": "splunk_ta_windows", "label": "Splunk Add-on for Windows", "version": "unknown"},
        ]
        result = catalog.compare_installed(installed)
        assert len(result["unknown"]) == 1
        assert result["unknown"][0]["status"] == "version_unknown"

    def test_match_by_title(self, tmp_path):
        """Apps can be matched by title when app_id doesn't match."""
        catalog = self._make_catalog_with_apps(tmp_path)
        installed = [
            {"name": "some_different_folder_name", "label": "Splunk Add-on for Windows", "version": "8.0.0"},
        ]
        result = catalog.compare_installed(installed)
        assert len(result["outdated"]) == 1
        assert result["outdated"][0]["latest_version"] == "8.1.0"

    def test_empty_installed_list(self, tmp_path):
        catalog = self._make_catalog_with_apps(tmp_path)
        result = catalog.compare_installed([])
        assert result["summary"]["total_installed"] == 0
        assert result["summary"]["outdated_count"] == 0

    def test_versions_behind_count(self, tmp_path):
        catalog = self._make_catalog_with_apps(tmp_path)
        count = catalog._count_versions_behind("7.0.0", [
            {"version": "8.1.0"},
            {"version": "8.0.0"},
            {"version": "7.0.0"},
            {"version": "6.0.0"},
        ])
        assert count == 2  # 8.1.0 and 8.0.0 are newer


# ---------------------------------------------------------------------------
# Report generation tests
# ---------------------------------------------------------------------------

class TestReportGeneration:
    """Test markdown report generation."""

    def _make_catalog(self, tmp_path):
        catalog = SplunkbaseCatalog(catalog_path=str(tmp_path / "catalog.json"))
        catalog._catalog = {
            "metadata": {"last_updated": "2026-03-04", "total_apps": 1},
            "apps": {
                "100": {
                    "uid": "100",
                    "title": "Test App",
                    "app_id": "test_app",
                    "latest_version": "2.0.0",
                    "latest_release_date": "2026-01-01T00:00:00",
                    "supported_splunk_versions": ["9.4"],
                    "releases": [
                        {"version": "2.0.0", "release_date": "2026-01-01", "product_versions": []},
                    ],
                },
            },
        }
        catalog._loaded = True
        return catalog

    def test_catalog_only_report(self, tmp_path):
        catalog = self._make_catalog(tmp_path)
        report = catalog._catalog_only_report()
        assert "## Splunkbase Catalog Summary" in report
        assert "Test App" in report
        assert "2.0.0" in report

    def test_catalog_only_report_empty(self, tmp_path):
        catalog = SplunkbaseCatalog(catalog_path=str(tmp_path / "catalog.json"))
        catalog._loaded = True
        report = catalog._catalog_only_report()
        assert "empty" in report.lower()

    def test_comparison_report(self, tmp_path):
        catalog = self._make_catalog(tmp_path)
        comparison = {
            "outdated": [
                {
                    "name": "test_app",
                    "label": "Test App",
                    "installed_version": "1.0.0",
                    "latest_version": "2.0.0",
                    "versions_behind": 1,
                    "latest_release_date": "2026-01-01T00:00:00",
                },
            ],
            "current": [
                {"name": "current_app", "label": "Current App"},
            ],
            "unknown": [
                {
                    "name": "unknown_app",
                    "label": "Unknown App",
                    "installed_version": "1.0.0",
                    "status": "not_in_catalog",
                },
            ],
            "summary": {
                "total_installed": 3,
                "outdated_count": 1,
                "current_count": 1,
                "unknown_count": 1,
                "timestamp": "2026-03-04T00:00:00",
            },
        }
        report = catalog._format_comparison_report(comparison)
        assert "## Splunkbase Add-on Version Report" in report
        assert "Outdated Apps" in report
        assert "Test App" in report
        assert "Current Apps" in report
        assert "Not Found in Catalog" in report
        assert "Unknown App" in report

    @pytest.mark.asyncio
    async def test_generate_report_no_connection(self, tmp_path):
        catalog = self._make_catalog(tmp_path)
        report = await catalog.generate_report()
        assert "Catalog Summary" in report

    @pytest.mark.asyncio
    async def test_generate_report_no_installed(self, tmp_path):
        catalog = self._make_catalog(tmp_path)
        report = await catalog.generate_report(installed_apps=[])
        assert "No installed apps found" in report


# ---------------------------------------------------------------------------
# Catalog summary (admin API) tests
# ---------------------------------------------------------------------------

class TestCatalogSummary:
    """Test get_catalog_summary for admin dashboard."""

    def test_summary_empty(self, tmp_path):
        catalog = SplunkbaseCatalog(catalog_path=str(tmp_path / "catalog.json"))
        summary = catalog.get_catalog_summary()
        assert summary["total_apps"] == 0
        # No catalog file on disk, so _loaded stays False
        assert summary["loaded"] is False

    def test_summary_with_apps(self, tmp_path):
        catalog = SplunkbaseCatalog(catalog_path=str(tmp_path / "catalog.json"))
        catalog._catalog = {
            "metadata": {"last_updated": "2026-01-01", "total_apps": 2},
            "apps": {
                "1": {"title": "App A", "latest_version": "1.0"},
                "2": {"title": "App B", "latest_version": "2.0"},
            },
        }
        catalog._loaded = True
        summary = catalog.get_catalog_summary()
        assert summary["total_apps"] == 2
        assert len(summary["top_apps"]) == 2


# ---------------------------------------------------------------------------
# Singleton and integration tests
# ---------------------------------------------------------------------------

class TestSingleton:
    """Test singleton accessor and rebuild."""

    def test_get_splunkbase_catalog_returns_instance(self):
        # Reset singleton
        import chat_app.splunkbase_catalog as mod
        mod._instance = None
        with patch("chat_app.settings.get_settings") as mock_settings:
            mock_sb = MagicMock()
            mock_sb.enabled = False
            mock_sb.catalog_path = "/tmp/test_catalog.json"
            mock_sb.max_apps_per_fetch = 50
            mock_settings.return_value = MagicMock(splunkbase_catalog=mock_sb)

            catalog = get_splunkbase_catalog()
            assert isinstance(catalog, SplunkbaseCatalog)

            # Second call should return the same instance
            catalog2 = get_splunkbase_catalog()
            assert catalog is catalog2

        # Clean up
        mod._instance = None

    def test_rebuild_creates_new_instance(self):
        import chat_app.splunkbase_catalog as mod
        mod._instance = None
        with patch("chat_app.settings.get_settings") as mock_settings:
            mock_sb = MagicMock()
            mock_sb.enabled = True
            mock_sb.catalog_path = "/tmp/test_catalog.json"
            mock_sb.max_apps_per_fetch = 100
            mock_settings.return_value = MagicMock(splunkbase_catalog=mock_sb)

            cat1 = get_splunkbase_catalog()
            cat2 = rebuild_splunkbase_catalog()
            assert cat1 is not cat2

        mod._instance = None


# ---------------------------------------------------------------------------
# Scheduler integration tests
# ---------------------------------------------------------------------------

class TestSchedulerIntegration:
    """Test run_catalog_update and run_comparison_report for scheduler use."""

    @pytest.mark.asyncio
    async def test_run_catalog_update_disabled(self):
        import chat_app.splunkbase_catalog as mod
        mod._instance = None
        with patch("chat_app.settings.get_settings") as mock_settings:
            mock_sb = MagicMock()
            mock_sb.enabled = False
            mock_settings.return_value = MagicMock(splunkbase_catalog=mock_sb)

            result = await run_catalog_update()
            assert result["skipped"] is True
            assert result["reason"] == "feature_disabled"

        mod._instance = None

    @pytest.mark.asyncio
    async def test_run_comparison_report_disabled(self):
        with patch("chat_app.settings.get_settings") as mock_settings:
            mock_sb = MagicMock()
            mock_sb.enabled = False
            mock_settings.return_value = MagicMock(splunkbase_catalog=mock_sb)

            result = await run_comparison_report()
            assert "error" in result
            assert "disabled" in result["error"]

    @pytest.mark.asyncio
    async def test_run_comparison_report_no_splunk_url(self):
        with patch("chat_app.settings.get_settings") as mock_settings:
            mock_sb = MagicMock()
            mock_sb.enabled = True
            mock_sb.splunk_url = ""
            mock_sb.splunk_token = ""
            mock_settings.return_value = MagicMock(splunkbase_catalog=mock_sb)

            result = await run_comparison_report()
            assert "error" in result
            assert "not configured" in result["error"]


# ---------------------------------------------------------------------------
# Settings integration tests
# ---------------------------------------------------------------------------

class TestSettingsIntegration:
    """Test that SplunkbaseCatalogSettings integrates correctly."""

    def test_settings_defaults(self):
        from chat_app.settings import SplunkbaseCatalogSettings
        s = SplunkbaseCatalogSettings()
        assert s.enabled is True
        assert s.catalog_path == "/app/data/splunkbase_catalog.json"
        assert s.update_schedule == "daily"
        assert s.splunk_url == ""
        assert s.splunk_token == ""
        assert s.max_apps_per_fetch == 0  # 0 = fetch all available apps
        assert s.include_private is False
        assert s.auto_compare is True

    def test_settings_custom_values(self):
        from chat_app.settings import SplunkbaseCatalogSettings
        s = SplunkbaseCatalogSettings(
            enabled=True,
            catalog_path="/custom/path.json",
            update_schedule="daily",
            splunk_url="https://splunk:8089",
            splunk_token="mytoken123",
            max_apps_per_fetch=50,
        )
        assert s.enabled is True
        assert s.catalog_path == "/custom/path.json"
        assert s.update_schedule == "daily"

    def test_settings_invalid_schedule(self):
        from chat_app.settings import SplunkbaseCatalogSettings
        with pytest.raises(Exception):
            SplunkbaseCatalogSettings(update_schedule="hourly")

    def test_settings_in_main_settings(self):
        from chat_app.settings import Settings, SplunkbaseCatalogSettings
        s = Settings()
        assert hasattr(s, "splunkbase_catalog")
        assert isinstance(s.splunkbase_catalog, SplunkbaseCatalogSettings)
        assert s.splunkbase_catalog.enabled is True
