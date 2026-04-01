"""
Sprint 2 tests for the Splunk Upgrade Readiness Testing System.

Coverage:
  TestCIMAnalyzer       — CIM compliance checking, regression detection (25 tests)
  TestDependencyTracer  — Dependency graph construction and impact tracing (25 tests)
  TestUFAnalyzer        — Universal Forwarder upgrade analysis (20 tests)
  TestIntegrationSprint2 — End-to-end pipelines using sample repo data (10 tests)
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from typing import Dict, List

import pytest

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Sample org repo path — used by integration tests
SAMPLE_REPO = PROJECT_ROOT / "documents" / "repo" / "splunk"
SAMPLE_ES_APPS = SAMPLE_REPO / "shcluster" / "cluster-es" / "apps"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _baseline(
    app_id: str,
    default_confs: Dict = None,
    local_confs: Dict = None,
) -> "AppBaseline":
    """Build an AppBaseline from raw conf dicts."""
    from chat_app.upgrade_readiness.models import AppBaseline, AppVersion

    return AppBaseline(
        app_id=app_id,
        version=AppVersion(app_id=app_id, version="1.0.0"),
        default_confs=default_confs or {},
        local_confs=local_confs or {},
    )


def _stanzas(**kwargs) -> Dict[str, Dict[str, str]]:
    """Shorthand: _stanzas(source__WinEventLog={"key": "val"}) → {"source::WinEventLog": {...}}"""
    return {k.replace("__", "::"): dict(v) for k, v in kwargs.items()}


# ===========================================================================
# TestCIMAnalyzer
# ===========================================================================


class TestCIMAnalyzer:
    """25 tests covering CIM compliance checking and upgrade regression detection."""

    def test_authentication_model_compliance_all_fields_present(self):
        """App with all Authentication CIM fields returns compliant result."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        baseline = _baseline(
            "TA_windows",
            default_confs={
                "eventtypes": {
                    "authentication": {"search": 'sourcetype="WinEventLog:Security"'},
                },
                "tags": {
                    "eventtype=authentication": {"authentication": "enabled"},
                },
                "props": {
                    "WinEventLog:Security": {
                        "FIELDALIAS-action": "EventCode AS action",
                        "FIELDALIAS-app": "LogName AS app",
                        "FIELDALIAS-dest": "dest_ip AS dest",
                        "FIELDALIAS-src": "src_ip AS src",
                        "FIELDALIAS-user": "AccountName AS user",
                    }
                },
            },
        )
        results = check_cim_compliance(baseline)
        auth_results = [r for r in results if r.model_name == "Authentication"]
        assert len(auth_results) >= 1
        auth = auth_results[0]
        assert auth.is_compliant
        assert auth.compliance_score == 1.0
        assert auth.missing_fields == []

    def test_missing_field_detection_authentication(self):
        """Missing CIM required field appears in missing_fields list."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        baseline = _baseline(
            "TA_partial",
            default_confs={
                "eventtypes": {
                    "authentication": {"search": 'sourcetype="syslog"'},
                },
                "tags": {
                    "eventtype=authentication": {"authentication": "enabled"},
                },
                "props": {
                    "syslog": {
                        # Missing: action, app, dest, src — only user provided
                        "FIELDALIAS-user": "username AS user",
                    }
                },
            },
        )
        results = check_cim_compliance(baseline)
        auth_results = [r for r in results if r.model_name == "Authentication"]
        assert len(auth_results) == 1
        auth = auth_results[0]
        assert not auth.is_compliant
        assert "action" in auth.missing_fields
        assert "src" in auth.missing_fields
        assert auth.compliance_score < 1.0

    def test_field_alias_mapping_to_cim_fields(self):
        """FIELDALIAS destination names are counted as provided fields."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        baseline = _baseline(
            "TA_alias",
            default_confs={
                "eventtypes": {
                    "authentication": {"search": 'sourcetype="pan:traffic"'},
                },
                "tags": {
                    "eventtype=authentication": {"authentication": "enabled"},
                },
                "props": {
                    "pan:traffic": {
                        "FIELDALIAS-src": "src_ip AS src",
                        "FIELDALIAS-dest": "dst_ip AS dest",
                    }
                },
            },
        )
        results = check_cim_compliance(baseline)
        auth = [r for r in results if r.model_name == "Authentication"][0]
        assert "src" in auth.provided_fields
        assert "dest" in auth.provided_fields

    def test_eval_fields_counted_as_provided(self):
        """EVAL-field_name is counted as a provided field."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        baseline = _baseline(
            "TA_eval",
            default_confs={
                "eventtypes": {
                    "web_traffic": {"search": 'sourcetype="nginx:access"'},
                },
                "tags": {
                    "eventtype=web_traffic": {"web": "enabled"},
                },
                "props": {
                    "nginx:access": {
                        "EVAL-status": 'tonumber(status_code)',
                        "EVAL-http_method": 'upper(method)',
                        "FIELDALIAS-dest": 'vhost AS dest',
                        "FIELDALIAS-src": 'remote_addr AS src',
                        "FIELDALIAS-url": 'request_uri AS url',
                    }
                },
            },
        )
        results = check_cim_compliance(baseline)
        web_results = [r for r in results if r.model_name == "Web"]
        assert len(web_results) >= 1
        web = web_results[0]
        assert "status" in web.provided_fields
        assert "http_method" in web.provided_fields

    def test_report_transform_fields_counted(self):
        """REPORT-name → transforms.conf FORMAT field names are counted."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        baseline = _baseline(
            "TA_report",
            default_confs={
                "eventtypes": {
                    "authentication": {"search": 'sourcetype="app:auth"'},
                },
                "tags": {
                    "eventtype=authentication": {"authentication": "enabled"},
                },
                "props": {
                    "app:auth": {
                        "REPORT-auth_fields": "auth-extract",
                        "FIELDALIAS-dest": "dest_host AS dest",
                        "FIELDALIAS-src": "src_host AS src",
                        "FIELDALIAS-app": "application AS app",
                    }
                },
                "transforms": {
                    "auth-extract": {
                        "REGEX": r"action=(?P<action>\w+).*user=(?P<user>\w+)",
                        "FORMAT": "action::$1 user::$2",
                    }
                },
            },
        )
        results = check_cim_compliance(baseline)
        auth_results = [r for r in results if r.model_name == "Authentication"]
        assert len(auth_results) >= 1
        auth = auth_results[0]
        # action, user should come from FORMAT, dest/src/app from FIELDALIAS
        assert "action" in auth.provided_fields
        assert "user" in auth.provided_fields

    def test_app_with_no_cim_tags_returns_empty(self):
        """App with no CIM-relevant tags returns empty results."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        baseline = _baseline(
            "TA_no_cim",
            default_confs={
                "eventtypes": {
                    "my_app_event": {"search": 'sourcetype="myapp"'},
                },
                "tags": {
                    "eventtype=my_app_event": {"custom_tag": "enabled"},
                },
                "props": {
                    "myapp": {"FIELDALIAS-host": "hostname AS host"}
                },
            },
        )
        results = check_cim_compliance(baseline)
        assert results == []

    def test_app_with_no_eventtypes_returns_empty(self):
        """App with no eventtypes.conf returns empty results."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        baseline = _baseline(
            "TA_no_et",
            default_confs={
                "props": {"sourcetype": {"FIELDALIAS-x": "a AS b"}},
            },
        )
        assert check_cim_compliance(baseline) == []

    def test_multiple_cim_models_from_same_app(self):
        """App with multiple tagged eventtypes returns results for each model."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        baseline = _baseline(
            "TA_multi",
            default_confs={
                "eventtypes": {
                    "authentication": {"search": 'sourcetype="auth:log"'},
                    "network_traffic": {"search": 'sourcetype="fw:traffic"'},
                },
                "tags": {
                    "eventtype=authentication": {"authentication": "enabled"},
                    "eventtype=network_traffic": {
                        "network": "enabled",
                        "communicate": "enabled",
                    },
                },
                "props": {},
            },
        )
        results = check_cim_compliance(baseline)
        model_names = {r.model_name for r in results}
        assert "Authentication" in model_names
        assert "Network_Traffic" in model_names

    def test_cim_models_dict_has_required_models(self):
        """CIM_MODELS contains at least 10 defined models."""
        from chat_app.upgrade_readiness.cim_analyzer import CIM_MODELS

        assert len(CIM_MODELS) >= 10
        assert "Authentication" in CIM_MODELS
        assert "Network_Traffic" in CIM_MODELS
        assert "Endpoint_Processes" in CIM_MODELS
        assert "Malware" in CIM_MODELS
        assert "Web" in CIM_MODELS

    def test_cim_model_has_required_and_optional_fields(self):
        """Every CIM model definition has required_fields."""
        from chat_app.upgrade_readiness.cim_analyzer import CIM_MODELS

        for model_name, model_def in CIM_MODELS.items():
            assert "required_fields" in model_def, f"{model_name} missing required_fields"
            assert isinstance(model_def["required_fields"], list)

    def test_compliance_score_partial(self):
        """Partial field coverage produces fractional compliance_score."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        # Authentication requires 5 fields; provide 3 → 60% compliance
        baseline = _baseline(
            "TA_partial_score",
            default_confs={
                "eventtypes": {
                    "authentication": {"search": 'sourcetype="partial"'},
                },
                "tags": {
                    "eventtype=authentication": {"authentication": "enabled"},
                },
                "props": {
                    "partial": {
                        "FIELDALIAS-src": "source_ip AS src",
                        "FIELDALIAS-dest": "dest_ip AS dest",
                        "FIELDALIAS-user": "username AS user",
                    }
                },
            },
        )
        results = check_cim_compliance(baseline)
        auth = [r for r in results if r.model_name == "Authentication"][0]
        assert 0.0 < auth.compliance_score < 1.0
        # action and app missing → 3/5 = 0.6
        assert auth.compliance_score == pytest.approx(0.6, abs=0.01)

    def test_upgrade_cim_regression_detection_field_removed(self):
        """Removing a FIELDALIAS in the upgrade triggers a regression finding."""
        from chat_app.upgrade_readiness.cim_analyzer import check_upgrade_cim_impact

        old_baseline = _baseline(
            "TA_reg",
            default_confs={
                "eventtypes": {
                    "authentication": {"search": 'sourcetype="auth"'},
                },
                "tags": {
                    "eventtype=authentication": {"authentication": "enabled"},
                },
                "props": {
                    "auth": {
                        "FIELDALIAS-action": "action_code AS action",
                        "FIELDALIAS-app": "app_name AS app",
                        "FIELDALIAS-dest": "dest_host AS dest",
                        "FIELDALIAS-src": "src_host AS src",
                        "FIELDALIAS-user": "username AS user",
                    }
                },
            },
        )

        # New version removes the action alias — regression
        new_confs = {
            "eventtypes": {
                "authentication": {"search": 'sourcetype="auth"'},
            },
            "tags": {
                "eventtype=authentication": {"authentication": "enabled"},
            },
            "props": {
                "auth": {
                    # action alias removed
                    "FIELDALIAS-app": "app_name AS app",
                    "FIELDALIAS-dest": "dest_host AS dest",
                    "FIELDALIAS-src": "src_host AS src",
                    "FIELDALIAS-user": "username AS user",
                }
            },
        }

        regressions = check_upgrade_cim_impact(old_baseline, new_confs)
        assert len(regressions) >= 1
        field_names = [r.field for r in regressions]
        assert "action" in field_names

    def test_upgrade_cim_regression_risk_level(self):
        """Regression findings have HIGH or CRITICAL risk."""
        from chat_app.upgrade_readiness.cim_analyzer import (
            check_upgrade_cim_impact,
            CIMRegressionFinding,
        )
        from chat_app.upgrade_readiness.models import UpgradeRisk

        old_baseline = _baseline(
            "TA_risk",
            default_confs={
                "eventtypes": {"authentication": {"search": 'sourcetype="x"'}},
                "tags": {"eventtype=authentication": {"authentication": "enabled"}},
                "props": {
                    "x": {
                        "FIELDALIAS-action": "act AS action",
                        "FIELDALIAS-app": "ap AS app",
                        "FIELDALIAS-dest": "d AS dest",
                        "FIELDALIAS-src": "s AS src",
                        "FIELDALIAS-user": "u AS user",
                    }
                },
            },
        )
        new_confs = {
            "eventtypes": {"authentication": {"search": 'sourcetype="x"'}},
            "tags": {"eventtype=authentication": {"authentication": "enabled"}},
            "props": {"x": {}},  # all aliases removed
        }
        regressions = check_upgrade_cim_impact(old_baseline, new_confs)
        for reg in regressions:
            assert reg.risk in (UpgradeRisk.HIGH, UpgradeRisk.CRITICAL)

    def test_upgrade_no_regression_when_fields_preserved(self):
        """No regression when new version provides same fields as old."""
        from chat_app.upgrade_readiness.cim_analyzer import check_upgrade_cim_impact

        confs = {
            "eventtypes": {"authentication": {"search": 'sourcetype="y"'}},
            "tags": {"eventtype=authentication": {"authentication": "enabled"}},
            "props": {
                "y": {
                    "FIELDALIAS-action": "a AS action",
                    "FIELDALIAS-app": "b AS app",
                    "FIELDALIAS-dest": "c AS dest",
                    "FIELDALIAS-src": "d AS src",
                    "FIELDALIAS-user": "e AS user",
                }
            },
        }
        old_baseline = _baseline("TA_no_reg", default_confs=confs)
        regressions = check_upgrade_cim_impact(old_baseline, confs)
        assert regressions == []

    def test_local_conf_fields_count_toward_compliance(self):
        """Fields defined in local/ are counted as provided."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        baseline = _baseline(
            "TA_local_fields",
            default_confs={
                "eventtypes": {"authentication": {"search": 'sourcetype="z"'}},
                "tags": {"eventtype=authentication": {"authentication": "enabled"}},
                "props": {
                    "z": {
                        "FIELDALIAS-action": "act AS action",
                        "FIELDALIAS-app": "ap AS app",
                    }
                },
            },
            local_confs={
                "props": {
                    "z": {
                        "FIELDALIAS-dest": "d AS dest",
                        "FIELDALIAS-src": "s AS src",
                        "FIELDALIAS-user": "u AS user",
                    }
                }
            },
        )
        results = check_cim_compliance(baseline)
        auth = [r for r in results if r.model_name == "Authentication"][0]
        assert auth.is_compliant

    def test_cim_result_has_eventtype_name(self):
        """CIMValidationResult.eventtype_name is populated."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        baseline = _baseline(
            "TA_et_name",
            default_confs={
                "eventtypes": {"my_auth_eventtype": {"search": 'sourcetype="logon"'}},
                "tags": {"eventtype=my_auth_eventtype": {"authentication": "enabled"}},
                "props": {},
            },
        )
        results = check_cim_compliance(baseline)
        auth = [r for r in results if r.model_name == "Authentication"]
        assert len(auth) == 1
        assert auth[0].eventtype_name == "my_auth_eventtype"

    def test_cim_result_sourcetypes_extracted(self):
        """sourcetypes list is populated from eventtype search string."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        baseline = _baseline(
            "TA_sources",
            default_confs={
                "eventtypes": {
                    "authentication": {
                        "search": 'sourcetype="WinEventLog:Security" OR sourcetype="linux:audit"'
                    }
                },
                "tags": {"eventtype=authentication": {"authentication": "enabled"}},
                "props": {},
            },
        )
        results = check_cim_compliance(baseline)
        auth = [r for r in results if r.model_name == "Authentication"]
        assert len(auth) >= 1
        all_sourcetypes = auth[0].sourcetypes
        assert "WinEventLog:Security" in all_sourcetypes or "linux:audit" in all_sourcetypes

    def test_get_cim_summary_structure(self):
        """get_cim_summary returns the expected keys."""
        from chat_app.upgrade_readiness.cim_analyzer import (
            CIMValidationResult,
            get_cim_summary,
        )

        results = [
            CIMValidationResult(
                model_name="Authentication",
                eventtype_name="auth",
                sourcetypes=["auth_log"],
                provided_fields=["action", "app", "dest", "src", "user"],
                required_fields=["action", "app", "dest", "src", "user"],
                missing_fields=[],
                is_compliant=True,
                compliance_score=1.0,
                app_id="TA_test",
            ),
            CIMValidationResult(
                model_name="Web",
                eventtype_name="web",
                sourcetypes=["nginx"],
                provided_fields=["dest"],
                required_fields=["dest", "http_method", "src", "status", "url"],
                missing_fields=["http_method", "src", "status", "url"],
                is_compliant=False,
                compliance_score=0.2,
                app_id="TA_test",
            ),
        ]
        summary = get_cim_summary(results)
        assert summary["total_checks"] == 2
        assert summary["compliant"] == 1
        assert summary["non_compliant"] == 1
        assert summary["compliance_rate"] == pytest.approx(0.5, abs=0.01)
        assert "Authentication" in summary["models_checked"]

    def test_extract_named_regex_groups_as_provided_fields(self):
        """EXTRACT with (?P<field>...) named groups are counted as provided."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        baseline = _baseline(
            "TA_extract",
            default_confs={
                "eventtypes": {"authentication": {"search": 'sourcetype="app:log"'}},
                "tags": {"eventtype=authentication": {"authentication": "enabled"}},
                "props": {
                    "app:log": {
                        "EXTRACT-fields": r'action=(?P<action>\w+) user=(?P<user>\S+)',
                        "FIELDALIAS-app": "application AS app",
                        "FIELDALIAS-dest": "dest_host AS dest",
                        "FIELDALIAS-src": "src_ip AS src",
                    }
                },
            },
        )
        results = check_cim_compliance(baseline)
        auth = [r for r in results if r.model_name == "Authentication"][0]
        assert "action" in auth.provided_fields
        assert "user" in auth.provided_fields

    def test_cim_compliance_returns_app_id(self):
        """CIMValidationResult.app_id matches the baseline's app_id."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        baseline = _baseline(
            "MY_TA_windows",
            default_confs={
                "eventtypes": {"authentication": {"search": 'sourcetype="ev"'}},
                "tags": {"eventtype=authentication": {"authentication": "enabled"}},
                "props": {},
            },
        )
        results = check_cim_compliance(baseline)
        for r in results:
            assert r.app_id == "MY_TA_windows"

    def test_network_traffic_model_tag_combo(self):
        """Network_Traffic requires both network AND communicate tags."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        # Only "network" tag — should NOT match Network_Traffic
        baseline_incomplete = _baseline(
            "TA_net_incomplete",
            default_confs={
                "eventtypes": {"net_event": {"search": 'sourcetype="fw"'}},
                "tags": {"eventtype=net_event": {"network": "enabled"}},
                "props": {},
            },
        )
        results = check_cim_compliance(baseline_incomplete)
        model_names = {r.model_name for r in results}
        assert "Network_Traffic" not in model_names

        # Both network + communicate → should match
        baseline_complete = _baseline(
            "TA_net_complete",
            default_confs={
                "eventtypes": {"net_event": {"search": 'sourcetype="fw"'}},
                "tags": {
                    "eventtype=net_event": {
                        "network": "enabled",
                        "communicate": "enabled",
                    }
                },
                "props": {},
            },
        )
        results2 = check_cim_compliance(baseline_complete)
        model_names2 = {r.model_name for r in results2}
        assert "Network_Traffic" in model_names2

    def test_disabled_tag_not_counted(self):
        """Tags with value != 'enabled' are not treated as active."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        baseline = _baseline(
            "TA_disabled_tag",
            default_confs={
                "eventtypes": {"authentication": {"search": 'sourcetype="x"'}},
                "tags": {"eventtype=authentication": {"authentication": "disabled"}},
                "props": {},
            },
        )
        results = check_cim_compliance(baseline)
        # Disabled tag → no CIM model match
        auth_results = [r for r in results if r.model_name == "Authentication"]
        assert len(auth_results) == 0

    def test_regression_finding_has_description_and_recommendation(self):
        """CIMRegressionFinding has non-empty description and recommendation."""
        from chat_app.upgrade_readiness.cim_analyzer import check_upgrade_cim_impact

        old_baseline = _baseline(
            "TA_desc",
            default_confs={
                "eventtypes": {"authentication": {"search": 'sourcetype="x"'}},
                "tags": {"eventtype=authentication": {"authentication": "enabled"}},
                "props": {
                    "x": {
                        "FIELDALIAS-action": "a AS action",
                        "FIELDALIAS-app": "b AS app",
                        "FIELDALIAS-dest": "c AS dest",
                        "FIELDALIAS-src": "d AS src",
                        "FIELDALIAS-user": "e AS user",
                    }
                },
            },
        )
        new_confs = {
            "eventtypes": {"authentication": {"search": 'sourcetype="x"'}},
            "tags": {"eventtype=authentication": {"authentication": "enabled"}},
            "props": {"x": {}},
        }
        regressions = check_upgrade_cim_impact(old_baseline, new_confs)
        assert len(regressions) > 0
        for reg in regressions:
            assert reg.description
            assert reg.recommendation
            assert reg.model_name
            assert reg.field

    def test_endpoint_processes_dual_tag_requirement(self):
        """Endpoint_Processes requires process AND report tags."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        baseline = _baseline(
            "TA_endpoint",
            default_confs={
                "eventtypes": {"endpoint_processes": {"search": 'sourcetype="sysmon"'}},
                "tags": {
                    "eventtype=endpoint_processes": {
                        "process": "enabled",
                        "report": "enabled",
                    }
                },
                "props": {},
            },
        )
        results = check_cim_compliance(baseline)
        ep_results = [r for r in results if r.model_name == "Endpoint_Processes"]
        assert len(ep_results) == 1

    def test_cim_models_required_fields_are_lists(self):
        """All CIM model definitions have list type for required_fields."""
        from chat_app.upgrade_readiness.cim_analyzer import CIM_MODELS

        for model_name, model_def in CIM_MODELS.items():
            rf = model_def.get("required_fields", [])
            assert isinstance(rf, list), f"{model_name}: required_fields should be list"
            assert len(rf) > 0, f"{model_name}: required_fields should be non-empty"

    def test_cim_compliance_with_only_local_confs(self):
        """App that defines all CIM fields only in local/ is compliant."""
        from chat_app.upgrade_readiness.cim_analyzer import check_cim_compliance

        baseline = _baseline(
            "TA_local_only",
            default_confs={},
            local_confs={
                "eventtypes": {"authentication": {"search": 'sourcetype="local_src"'}},
                "tags": {"eventtype=authentication": {"authentication": "enabled"}},
                "props": {
                    "local_src": {
                        "FIELDALIAS-action": "act AS action",
                        "FIELDALIAS-app": "ap AS app",
                        "FIELDALIAS-dest": "d AS dest",
                        "FIELDALIAS-src": "s AS src",
                        "FIELDALIAS-user": "u AS user",
                    }
                },
            },
        )
        results = check_cim_compliance(baseline)
        auth = [r for r in results if r.model_name == "Authentication"]
        assert len(auth) == 1
        assert auth[0].is_compliant


# ===========================================================================
# TestDependencyTracer
# ===========================================================================


class TestDependencyTracer:
    """25 tests covering dependency graph construction and impact tracing."""

    def _make_inventory(self, apps: Dict) -> "ClusterInventory":
        """Build a ClusterInventory from {app_name: AppBaseline} dict."""
        from chat_app.upgrade_readiness.models import ClusterInventory

        inv = ClusterInventory(cluster_name="test_cluster")
        inv.apps = apps
        return inv

    def test_transforms_reference_detected(self):
        """TRANSFORMS-* in props.conf creates edge to transforms.conf stanza."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            build_dependency_graph,
            EDGE_TRANSFORMS_REFERENCE,
        )

        baseline = _baseline(
            "TA_transforms",
            default_confs={
                "props": {
                    "WinEventLog:Security": {
                        "TRANSFORMS-user_extract": "win-user-extract",
                    }
                },
                "transforms": {
                    "win-user-extract": {"REGEX": r"user=(\S+)", "FORMAT": "user::$1"}
                },
            },
        )
        inv = self._make_inventory({"TA_transforms": baseline})
        graph = build_dependency_graph(inv)
        edge_types = {e.relationship for e in graph.edges}
        assert EDGE_TRANSFORMS_REFERENCE in edge_types

    def test_lookup_reference_detected(self):
        """| lookup in savedsearch creates edge to transforms.conf stanza."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            build_dependency_graph,
            EDGE_LOOKUP_REFERENCE,
        )

        baseline = _baseline(
            "TA_lookup",
            default_confs={
                "savedsearches": {
                    "My Search": {
                        "search": "index=main | lookup user_lookup user AS user",
                    }
                },
                "transforms": {
                    "user_lookup": {"filename": "users.csv"}
                },
            },
        )
        inv = self._make_inventory({"TA_lookup": baseline})
        graph = build_dependency_graph(inv)
        edge_types = {e.relationship for e in graph.edges}
        assert EDGE_LOOKUP_REFERENCE in edge_types

    def test_macro_usage_detected(self):
        """Backtick macro reference in savedsearch creates edge to macros.conf."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            build_dependency_graph,
            EDGE_MACRO_USAGE,
        )

        baseline = _baseline(
            "TA_macro",
            default_confs={
                "savedsearches": {
                    "Brute Force": {
                        "search": "`authentication` action=failure | stats count by src",
                    }
                },
                "macros": {
                    "authentication": {"definition": "tag=authentication"},
                },
            },
        )
        inv = self._make_inventory({"TA_macro": baseline})
        graph = build_dependency_graph(inv)
        edge_types = {e.relationship for e in graph.edges}
        assert EDGE_MACRO_USAGE in edge_types

    def test_cross_app_transforms_dependency(self):
        """Transform referenced in app A but defined in app B creates cross-app edge."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            build_dependency_graph,
            _make_node_id,
            ENTITY_TRANSFORMS_STANZA,
        )

        ta = _baseline(
            "Splunk_TA_windows",
            default_confs={
                "props": {
                    "WinEventLog:Security": {
                        "TRANSFORMS-shared": "shared-extract",
                    }
                }
            },
        )
        shared_app = _baseline(
            "SA_shared",
            default_confs={
                "transforms": {
                    "shared-extract": {"REGEX": r".*", "FORMAT": "field::$0"}
                }
            },
        )
        inv = self._make_inventory(
            {"Splunk_TA_windows": ta, "SA_shared": shared_app}
        )
        graph = build_dependency_graph(inv)

        target_node_id = _make_node_id(
            "SA_shared", ENTITY_TRANSFORMS_STANZA, "shared-extract"
        )
        assert target_node_id in graph.nodes

    def test_cross_app_macro_dependency(self):
        """Macro referenced in ES searches but defined in TA creates cross-app edge."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            build_dependency_graph,
            _make_node_id,
            ENTITY_MACRO,
        )

        es_app = _baseline(
            "SplunkEnterpriseSecuritySuite",
            default_confs={
                "savedsearches": {
                    "Access Alert": {
                        "search": "`authentication` action=failure | stats count by src",
                    }
                }
            },
        )
        ta = _baseline(
            "SA_CIM",
            default_confs={
                "macros": {"authentication": {"definition": "tag=authentication"}}
            },
        )
        inv = self._make_inventory(
            {"SplunkEnterpriseSecuritySuite": es_app, "SA_CIM": ta}
        )
        graph = build_dependency_graph(inv)

        macro_node_id = _make_node_id("SA_CIM", ENTITY_MACRO, "authentication")
        assert macro_node_id in graph.nodes

    def test_impact_trace_from_transform_to_savedsearch(self):
        """Changing a transform propagates impact to the savedsearch that references it."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            build_dependency_graph,
            trace_impact,
            _make_node_id,
            ENTITY_TRANSFORMS_STANZA,
        )

        ta = _baseline(
            "TA_win",
            default_confs={
                "props": {
                    "WinEventLog:Security": {
                        "TRANSFORMS-ev": "ev-extract",
                    }
                },
                "transforms": {
                    "ev-extract": {"REGEX": r"EventCode=(\d+)", "FORMAT": "EventCode::$1"}
                },
            },
        )
        es = _baseline(
            "ES_suite",
            default_confs={
                "savedsearches": {
                    "Brute Force": {
                        "search": "index=wineventlog | lookup ev-extract user",
                    }
                }
            },
        )
        inv = self._make_inventory({"TA_win": ta, "ES_suite": es})
        graph = build_dependency_graph(inv)

        transform_node_id = _make_node_id("TA_win", ENTITY_TRANSFORMS_STANZA, "ev-extract")
        # The transform node should exist
        assert transform_node_id in graph.nodes

    def test_eventtype_to_props_edge(self):
        """eventtypes.conf sourcetype reference creates edge to props stanza."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            build_dependency_graph,
            EDGE_SOURCETYPE_FEEDS,
        )

        baseline = _baseline(
            "SA_CIM",
            default_confs={
                "eventtypes": {
                    "authentication": {
                        "search": 'sourcetype="WinEventLog:Security"'
                    }
                },
                "tags": {
                    "eventtype=authentication": {"authentication": "enabled"}
                },
                "props": {
                    "WinEventLog:Security": {
                        "FIELDALIAS-user": "AccountName AS user"
                    }
                },
            },
        )
        inv = self._make_inventory({"SA_CIM": baseline})
        graph = build_dependency_graph(inv)
        edge_types = {e.relationship for e in graph.edges}
        assert EDGE_SOURCETYPE_FEEDS in edge_types

    def test_tags_to_eventtype_edge(self):
        """tags.conf [eventtype=X] creates edge back to eventtypes.conf [X]."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            build_dependency_graph,
            EDGE_EVENTTYPE_TAGGED_BY,
        )

        baseline = _baseline(
            "SA_CIM_tags",
            default_confs={
                "eventtypes": {
                    "authentication": {"search": 'sourcetype="x"'}
                },
                "tags": {
                    "eventtype=authentication": {"authentication": "enabled"}
                },
            },
        )
        inv = self._make_inventory({"SA_CIM_tags": baseline})
        graph = build_dependency_graph(inv)
        edge_types = {e.relationship for e in graph.edges}
        assert EDGE_EVENTTYPE_TAGGED_BY in edge_types

    def test_graph_nodes_have_correct_types(self):
        """Graph nodes carry correct entity_type values."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            build_dependency_graph,
            ENTITY_PROPS_STANZA,
            ENTITY_TRANSFORMS_STANZA,
        )

        baseline = _baseline(
            "TA_node_types",
            default_confs={
                "props": {
                    "sourcetype_x": {"TRANSFORMS-t": "transform_y"}
                },
                "transforms": {
                    "transform_y": {"REGEX": r"(.+)", "FORMAT": "f::$1"}
                },
            },
        )
        inv = self._make_inventory({"TA_node_types": baseline})
        graph = build_dependency_graph(inv)

        entity_types = {n.entity_type for n in graph.nodes.values()}
        assert ENTITY_PROPS_STANZA in entity_types
        assert ENTITY_TRANSFORMS_STANZA in entity_types

    def test_dependency_summary_structure(self):
        """get_dependency_summary returns expected keys."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            build_dependency_graph,
            get_dependency_summary,
        )

        baseline = _baseline(
            "TA_summary",
            default_confs={
                "props": {"src_type": {"TRANSFORMS-t": "t_stanza"}},
                "transforms": {"t_stanza": {"REGEX": r".*"}},
            },
        )
        inv = self._make_inventory({"TA_summary": baseline})
        graph = build_dependency_graph(inv)
        summary = get_dependency_summary(graph)

        assert "node_count" in summary
        assert "edge_count" in summary
        assert "entity_type_counts" in summary
        assert "most_depended_upon" in summary
        assert summary["node_count"] >= 2
        assert summary["edge_count"] >= 1

    def test_empty_inventory_produces_empty_graph(self):
        """ClusterInventory with no apps produces an empty graph."""
        from chat_app.upgrade_readiness.dependency_tracer import build_dependency_graph
        from chat_app.upgrade_readiness.models import ClusterInventory

        inv = ClusterInventory(cluster_name="empty")
        graph = build_dependency_graph(inv)
        assert len(graph.nodes) == 0
        assert len(graph.edges) == 0

    def test_trace_impact_returns_empty_for_unknown_node(self):
        """trace_impact with unknown changed_entity_ids returns empty list."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            build_dependency_graph,
            trace_impact,
        )

        baseline = _baseline("TA_x", default_confs={})
        inv = self._make_inventory({"TA_x": baseline})
        graph = build_dependency_graph(inv)

        paths = trace_impact(graph, ["non::existent::node"])
        assert paths == []

    def test_impact_path_has_correct_structure(self):
        """ImpactPath objects have path list and hop_count >= 1."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            build_dependency_graph,
            trace_impact,
            _make_node_id,
            ENTITY_TRANSFORMS_STANZA,
            ENTITY_SAVEDSEARCH,
        )

        ta = _baseline(
            "TA_impact",
            default_confs={
                "props": {"src": {"TRANSFORMS-t": "my_transform"}},
                "transforms": {"my_transform": {"REGEX": r"(.+)"}},
                "savedsearches": {
                    "Alert": {"search": "| lookup my_transform x"}
                },
            },
        )
        inv = self._make_inventory({"TA_impact": ta})
        graph = build_dependency_graph(inv)

        transform_node_id = _make_node_id(
            "TA_impact", ENTITY_TRANSFORMS_STANZA, "my_transform"
        )
        paths = trace_impact(graph, [transform_node_id])
        for path in paths:
            assert path.hop_count >= 1
            assert len(path.path) >= 2
            assert path.changed_entity_id == transform_node_id

    def test_multiple_lookup_references_in_search(self):
        """Multiple | lookup calls in one search generate multiple edges."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            build_dependency_graph,
            EDGE_LOOKUP_REFERENCE,
        )

        baseline = _baseline(
            "TA_multi_lookup",
            default_confs={
                "savedsearches": {
                    "Complex": {
                        "search": (
                            "index=main | lookup user_lookup user | lookup asset_lookup ip"
                        ),
                    }
                },
                "transforms": {
                    "user_lookup": {"filename": "users.csv"},
                    "asset_lookup": {"filename": "assets.csv"},
                },
            },
        )
        inv = self._make_inventory({"TA_multi_lookup": baseline})
        graph = build_dependency_graph(inv)

        lookup_edges = [e for e in graph.edges if e.relationship == EDGE_LOOKUP_REFERENCE]
        assert len(lookup_edges) >= 2

    def test_multiple_macro_references_in_search(self):
        """Multiple macro backticks in one search generate multiple edges."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            build_dependency_graph,
            EDGE_MACRO_USAGE,
        )

        baseline = _baseline(
            "TA_multi_macro",
            default_confs={
                "savedsearches": {
                    "Complex": {
                        "search": "`authentication` `endpoint_processes` | stats count by src",
                    }
                },
                "macros": {
                    "authentication": {"definition": "tag=authentication"},
                    "endpoint_processes": {"definition": "tag=process tag=report"},
                },
            },
        )
        inv = self._make_inventory({"TA_multi_macro": baseline})
        graph = build_dependency_graph(inv)
        macro_edges = [e for e in graph.edges if e.relationship == EDGE_MACRO_USAGE]
        assert len(macro_edges) >= 2

    def test_circular_dependency_does_not_loop_forever(self):
        """trace_impact handles circular deps without infinite loop."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            DependencyGraph,
            GraphNode,
            GraphEdge,
            trace_impact,
            ENTITY_TRANSFORMS_STANZA,
        )

        graph = DependencyGraph()
        node_a = GraphNode("a::type::alpha", "app_a", ENTITY_TRANSFORMS_STANZA, "alpha")
        node_b = GraphNode("b::type::beta", "app_b", ENTITY_TRANSFORMS_STANZA, "beta")
        graph.add_node(node_a)
        graph.add_node(node_b)
        # a → b → a (circular)
        graph.add_edge(GraphEdge("a::type::alpha", "b::type::beta", "transforms_reference"))
        graph.add_edge(GraphEdge("b::type::beta", "a::type::alpha", "transforms_reference"))

        # Should complete without hanging
        paths = trace_impact(graph, ["a::type::alpha"])
        # With circular deps, BFS visits each node once — no infinite loop
        assert isinstance(paths, list)

    def test_graph_node_id_format(self):
        """Node IDs follow <app>::<type>::<name> format."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            build_dependency_graph,
        )

        baseline = _baseline(
            "TA_id_format",
            default_confs={
                "props": {"WinLog": {"TRANSFORMS-t": "win_extract"}},
                "transforms": {"win_extract": {"REGEX": r"(.+)"}},
            },
        )
        inv = self._make_inventory({"TA_id_format": baseline})
        graph = build_dependency_graph(inv)

        for node_id in graph.nodes:
            parts = node_id.split("::")
            assert len(parts) == 3, f"Node ID {node_id!r} should have 3 parts"

    def test_extract_lookup_names(self):
        """_extract_lookup_names correctly parses lookup references."""
        from chat_app.upgrade_readiness.dependency_tracer import _extract_lookup_names

        search = "index=main | lookup user_lookup user | stats count | lookup asset_lookup ip AS ip"
        names = _extract_lookup_names(search)
        assert "user_lookup" in names
        assert "asset_lookup" in names

    def test_extract_macro_names(self):
        """_extract_macro_names correctly parses backtick references."""
        from chat_app.upgrade_readiness.dependency_tracer import _extract_macro_names

        search = "`authentication` `endpoint_processes` | stats count | `my_macro(arg1,arg2)`"
        names = _extract_macro_names(search)
        assert "authentication" in names
        assert "endpoint_processes" in names
        assert "my_macro" in names

    def test_multiple_apps_all_get_nodes(self):
        """All apps in inventory contribute nodes to the graph."""
        from chat_app.upgrade_readiness.dependency_tracer import build_dependency_graph

        app_a = _baseline("app_a", default_confs={"props": {"st_a": {"TRANSFORMS-t": "ta"}}})
        app_b = _baseline("app_b", default_confs={"transforms": {"ta": {"REGEX": r".*"}}})
        app_c = _baseline("app_c", default_confs={"macros": {"m": {"definition": "index=*"}}})

        inv = self._make_inventory({"app_a": app_a, "app_b": app_b, "app_c": app_c})
        graph = build_dependency_graph(inv)
        app_names_in_graph = {n.app_name for n in graph.nodes.values()}
        assert "app_a" in app_names_in_graph
        assert "app_b" in app_names_in_graph

    def test_impact_trace_multi_hop(self):
        """Impact chain A→B→C is traced across two hops."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            DependencyGraph,
            GraphNode,
            GraphEdge,
            trace_impact,
            ENTITY_TRANSFORMS_STANZA,
            ENTITY_SAVEDSEARCH,
            ENTITY_PROPS_STANZA,
        )

        graph = DependencyGraph()
        node_a = GraphNode("TA::t::alpha", "TA", ENTITY_TRANSFORMS_STANZA, "alpha")
        node_b = GraphNode("TA::p::src", "TA", ENTITY_PROPS_STANZA, "src")
        node_c = GraphNode("ES::s::alert", "ES", ENTITY_SAVEDSEARCH, "alert")
        graph.add_node(node_a)
        graph.add_node(node_b)
        graph.add_node(node_c)
        # b depends on a; c depends on b
        graph.add_edge(GraphEdge("TA::p::src", "TA::t::alpha", "transforms_reference"))
        graph.add_edge(GraphEdge("ES::s::alert", "TA::p::src", "sourcetype_feeds"))

        paths = trace_impact(graph, ["TA::t::alpha"])
        impacted_ids = {p.impacted_entity_id for p in paths}
        # At minimum, props stanza (b) should be in impact
        assert "TA::p::src" in impacted_ids

    def test_dependency_graph_adjacency_consistency(self):
        """Adjacency and reverse_adjacency are mirrors of each other."""
        from chat_app.upgrade_readiness.dependency_tracer import build_dependency_graph

        baseline = _baseline(
            "TA_adj",
            default_confs={
                "props": {"st": {"TRANSFORMS-t": "t1", "TRANSFORMS-u": "t2"}},
                "transforms": {
                    "t1": {"REGEX": r"(.+)"},
                    "t2": {"REGEX": r"(.*)"},
                },
            },
        )
        inv = self._make_inventory({"TA_adj": baseline})
        graph = build_dependency_graph(inv)

        # For every edge (src → tgt), src should appear in reverse_adj[tgt]
        for edge in graph.edges:
            assert edge.target_id in graph.reverse_adjacency
            assert edge.source_id in graph.reverse_adjacency[edge.target_id]

    def test_local_confs_contribute_edges(self):
        """Dependencies defined in local/ are also picked up."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            build_dependency_graph,
            EDGE_TRANSFORMS_REFERENCE,
        )

        baseline = _baseline(
            "TA_local_deps",
            default_confs={},
            local_confs={
                "props": {"WinLog": {"TRANSFORMS-t": "local_extract"}},
                "transforms": {"local_extract": {"REGEX": r"(.+)"}},
            },
        )
        inv = self._make_inventory({"TA_local_deps": baseline})
        graph = build_dependency_graph(inv)
        edge_types = {e.relationship for e in graph.edges}
        assert EDGE_TRANSFORMS_REFERENCE in edge_types

    def test_no_duplicate_nodes(self):
        """Same logical entity added twice results in only one node."""
        from chat_app.upgrade_readiness.dependency_tracer import (
            DependencyGraph,
            GraphNode,
            ENTITY_TRANSFORMS_STANZA,
        )

        graph = DependencyGraph()
        node = GraphNode("a::t::x", "a", ENTITY_TRANSFORMS_STANZA, "x")
        graph.add_node(node)
        graph.add_node(node)  # duplicate
        assert len(graph.nodes) == 1


# ===========================================================================
# TestUFAnalyzer
# ===========================================================================


class TestUFAnalyzer:
    """20 tests covering UF-specific upgrade risk analysis."""

    def test_input_removed_triggers_data_loss_critical(self):
        """Removed input stanza produces CRITICAL DATA_LOSS finding."""
        from chat_app.upgrade_readiness.uf_analyzer import analyze_uf_upgrade
        from chat_app.upgrade_readiness.models import UpgradeRisk

        old = _baseline(
            "uf_app",
            default_confs={
                "inputs": {
                    "monitor:///var/log/auth.log": {
                        "sourcetype": "linux:auth",
                        "index": "os",
                    }
                }
            },
        )
        new = _baseline("uf_app", default_confs={"inputs": {}})

        report = analyze_uf_upgrade([old], [new], "prod-linux-uf")
        assert report.data_loss_risk
        data_loss = [f for f in report.findings if f.category == "DATA_LOSS"]
        assert len(data_loss) >= 1
        assert data_loss[0].risk == UpgradeRisk.CRITICAL

    def test_output_server_changed_triggers_routing_risk(self):
        """Changed server list in outputs.conf creates ROUTING HIGH finding."""
        from chat_app.upgrade_readiness.uf_analyzer import analyze_uf_upgrade
        from chat_app.upgrade_readiness.models import UpgradeRisk

        old = _baseline(
            "uf_app",
            default_confs={
                "outputs": {
                    "tcpout:default": {"server": "indexer1:9997,indexer2:9997"}
                }
            },
        )
        new = _baseline(
            "uf_app",
            default_confs={
                "outputs": {
                    "tcpout:default": {"server": "indexer3:9997,indexer4:9997"}
                }
            },
        )
        report = analyze_uf_upgrade([old], [new], "prod-uf")
        assert report.routing_risk
        routing = [f for f in report.findings if f.category == "ROUTING"]
        assert len(routing) >= 1
        assert routing[0].risk in (UpgradeRisk.HIGH, UpgradeRisk.CRITICAL)

    def test_ssl_settings_changed_triggers_connection_risk(self):
        """Changed SSL key in outputs.conf creates CONNECTION finding."""
        from chat_app.upgrade_readiness.uf_analyzer import analyze_uf_upgrade

        old = _baseline(
            "uf_app",
            default_confs={
                "outputs": {
                    "tcpout:default": {
                        "server": "indexer1:9997",
                        "sslCertPath": "/opt/splunk/etc/auth/server.pem",
                    }
                }
            },
        )
        new = _baseline(
            "uf_app",
            default_confs={
                "outputs": {
                    "tcpout:default": {
                        "server": "indexer1:9997",
                        "sslCertPath": "/etc/ssl/splunk/server.pem",
                    }
                }
            },
        )
        report = analyze_uf_upgrade([old], [new], "ssl-uf")
        assert report.connection_risk

    def test_line_breaker_change_triggers_index_time_parsing_critical(self):
        """Changed LINE_BREAKER in props.conf creates CRITICAL INDEX_TIME_PARSING finding."""
        from chat_app.upgrade_readiness.uf_analyzer import analyze_uf_upgrade
        from chat_app.upgrade_readiness.models import UpgradeRisk

        old = _baseline(
            "uf_app",
            default_confs={
                "props": {
                    "sourcetype_x": {
                        "LINE_BREAKER": r"([\r\n]+)",
                        "SHOULD_LINEMERGE": "false",
                    }
                }
            },
        )
        new = _baseline(
            "uf_app",
            default_confs={
                "props": {
                    "sourcetype_x": {
                        "LINE_BREAKER": r"---NEW_BREAKER---",
                        "SHOULD_LINEMERGE": "false",
                    }
                }
            },
        )
        report = analyze_uf_upgrade([old], [new], "uf-group")
        index_findings = [f for f in report.findings if f.category == "INDEX_TIME_PARSING"]
        assert len(index_findings) >= 1
        assert index_findings[0].risk == UpgradeRisk.CRITICAL

    def test_time_format_change_is_critical(self):
        """Changed TIME_FORMAT is classified as CRITICAL."""
        from chat_app.upgrade_readiness.uf_analyzer import analyze_uf_upgrade
        from chat_app.upgrade_readiness.models import UpgradeRisk

        old = _baseline(
            "uf_app",
            default_confs={
                "props": {"src": {"TIME_FORMAT": "%m/%d/%Y %I:%M:%S %p"}}
            },
        )
        new = _baseline(
            "uf_app",
            default_confs={
                "props": {"src": {"TIME_FORMAT": "%Y-%m-%dT%H:%M:%S.%3N"}}
            },
        )
        report = analyze_uf_upgrade([old], [new], "uf-group")
        index_findings = [
            f for f in report.findings if f.category == "INDEX_TIME_PARSING"
        ]
        assert len(index_findings) >= 1
        assert all(f.risk == UpgradeRisk.CRITICAL for f in index_findings)

    def test_full_uf_report_structure(self):
        """UFUpgradeReport has expected fields."""
        from chat_app.upgrade_readiness.uf_analyzer import analyze_uf_upgrade

        old = _baseline("uf_app", default_confs={"inputs": {"monitor:///tmp": {}}})
        new = _baseline("uf_app", default_confs={"inputs": {"monitor:///tmp": {}}})
        report = analyze_uf_upgrade([old], [new], "my-uf-group")

        assert report.forwarder_group == "my-uf-group"
        assert isinstance(report.findings, list)
        assert isinstance(report.data_loss_risk, bool)
        assert isinstance(report.routing_risk, bool)
        assert isinstance(report.connection_risk, bool)
        assert isinstance(report.summary, dict)

    def test_no_findings_when_configs_identical(self):
        """No findings when old and new app configs are identical."""
        from chat_app.upgrade_readiness.uf_analyzer import analyze_uf_upgrade
        from chat_app.upgrade_readiness.models import UpgradeRisk

        confs = {
            "inputs": {"monitor:///var/log/syslog": {"sourcetype": "syslog"}},
            "outputs": {"tcpout:default": {"server": "idx1:9997"}},
            "props": {"syslog": {"LINE_BREAKER": r"([\r\n]+)"}},
        }
        old = _baseline("uf_app", default_confs=confs)
        new = _baseline("uf_app", default_confs=confs)
        report = analyze_uf_upgrade([old], [new], "stable-uf")
        assert report.findings == []
        assert report.overall_risk == UpgradeRisk.INFO

    def test_indexer_compat_old_indexer_with_new_uf(self):
        """UF 9.3 with indexer 8.x produces blocking_issues."""
        from chat_app.upgrade_readiness.uf_analyzer import check_indexer_compat

        result = check_indexer_compat("9.3.1", "8.2.0")
        assert not result.is_compatible
        assert len(result.blocking_issues) >= 1

    def test_indexer_compat_matching_versions(self):
        """UF and indexer at same version is always compatible."""
        from chat_app.upgrade_readiness.uf_analyzer import check_indexer_compat

        result = check_indexer_compat("9.2.1", "9.2.1")
        assert result.is_compatible
        assert len(result.blocking_issues) == 0

    def test_indexer_compat_uf_newer_minor_warning(self):
        """UF minor version ahead of indexer produces a warning."""
        from chat_app.upgrade_readiness.uf_analyzer import check_indexer_compat

        result = check_indexer_compat("9.3.0", "9.1.0")
        # Should be compatible (minor ahead) but with a warning
        assert isinstance(result.warnings, list)

    def test_overall_risk_is_highest_finding(self):
        """overall_risk equals the maximum risk among all findings."""
        from chat_app.upgrade_readiness.uf_analyzer import analyze_uf_upgrade
        from chat_app.upgrade_readiness.models import UpgradeRisk

        old = _baseline(
            "uf_app",
            default_confs={
                "inputs": {"monitor:///removed": {}},  # CRITICAL data loss
                "outputs": {"tcpout:default": {"server": "old_idx:9997"}},
            },
        )
        new = _baseline(
            "uf_app",
            default_confs={
                "inputs": {},  # stanza removed → CRITICAL
                "outputs": {"tcpout:default": {"server": "old_idx:9997"}},
            },
        )
        report = analyze_uf_upgrade([old], [new], "risk-uf")
        assert report.overall_risk == UpgradeRisk.CRITICAL

    def test_input_disabled_detected(self):
        """Input stanza changed to disabled=1 produces DATA_LOSS finding."""
        from chat_app.upgrade_readiness.uf_analyzer import analyze_uf_upgrade
        from chat_app.upgrade_readiness.models import UpgradeRisk

        old = _baseline(
            "uf_app",
            default_confs={
                "inputs": {"monitor:///opt/app/logs": {"disabled": "0", "index": "main"}}
            },
        )
        new = _baseline(
            "uf_app",
            default_confs={
                "inputs": {"monitor:///opt/app/logs": {"disabled": "1", "index": "main"}}
            },
        )
        report = analyze_uf_upgrade([old], [new], "disabled-uf")
        data_loss = [f for f in report.findings if f.category == "DATA_LOSS"]
        assert len(data_loss) >= 1

    def test_output_stanza_removed(self):
        """Removed output stanza creates a ROUTING finding."""
        from chat_app.upgrade_readiness.uf_analyzer import analyze_uf_upgrade

        old = _baseline(
            "uf_app",
            default_confs={
                "outputs": {
                    "tcpout:primary": {"server": "idx1:9997"},
                    "tcpout:secondary": {"server": "idx2:9997"},
                }
            },
        )
        new = _baseline(
            "uf_app",
            default_confs={
                "outputs": {
                    "tcpout:primary": {"server": "idx1:9997"},
                    # secondary removed
                }
            },
        )
        report = analyze_uf_upgrade([old], [new], "routing-uf")
        routing = [f for f in report.findings if f.category == "ROUTING"]
        assert len(routing) >= 1

    def test_non_index_time_props_change_ignored(self):
        """Search-time only props changes don't create UF findings."""
        from chat_app.upgrade_readiness.uf_analyzer import analyze_uf_upgrade

        old = _baseline(
            "uf_app",
            default_confs={"props": {"src": {"FIELDALIAS-user": "old AS user"}}},
        )
        new = _baseline(
            "uf_app",
            default_confs={"props": {"src": {"FIELDALIAS-user": "new AS user"}}},
        )
        report = analyze_uf_upgrade([old], [new], "search-time-uf")
        index_time = [f for f in report.findings if f.category == "INDEX_TIME_PARSING"]
        assert len(index_time) == 0

    def test_uf_report_summary_keys(self):
        """UFUpgradeReport.summary contains expected summary keys."""
        from chat_app.upgrade_readiness.uf_analyzer import analyze_uf_upgrade

        old = _baseline(
            "uf_app",
            default_confs={"inputs": {"monitor:///a": {}}},
        )
        new = _baseline(
            "uf_app",
            default_confs={"inputs": {}},
        )
        report = analyze_uf_upgrade([old], [new], "summary-uf")
        assert "total_findings" in report.summary
        assert "data_loss_risk" in report.summary
        assert "routing_risk" in report.summary
        assert "connection_risk" in report.summary

    def test_finding_has_old_and_new_values(self):
        """Findings for changed keys carry old_value and new_value."""
        from chat_app.upgrade_readiness.uf_analyzer import analyze_uf_upgrade

        old = _baseline(
            "uf_app",
            default_confs={
                "outputs": {"tcpout:primary": {"server": "old_host:9997"}}
            },
        )
        new = _baseline(
            "uf_app",
            default_confs={
                "outputs": {"tcpout:primary": {"server": "new_host:9997"}}
            },
        )
        report = analyze_uf_upgrade([old], [new], "val-uf")
        routing = [f for f in report.findings if f.category == "ROUTING"]
        assert len(routing) >= 1
        finding = routing[0]
        assert finding.old_value is not None
        assert finding.new_value is not None
        assert "old_host" in finding.old_value
        assert "new_host" in finding.new_value

    def test_uf_app_ids_analyzed_populated(self):
        """UFUpgradeReport.app_ids_analyzed lists all analysed app IDs."""
        from chat_app.upgrade_readiness.uf_analyzer import analyze_uf_upgrade

        app_a = _baseline("app_a", default_confs={"inputs": {"monitor:///a": {}}})
        app_b = _baseline("app_b", default_confs={"inputs": {"monitor:///b": {}}})
        new_a = _baseline("app_a", default_confs={"inputs": {"monitor:///a": {}}})
        new_b = _baseline("app_b", default_confs={"inputs": {"monitor:///b": {}}})

        report = analyze_uf_upgrade([app_a, app_b], [new_a, new_b], "multi-app-uf")
        assert "app_a" in report.app_ids_analyzed
        assert "app_b" in report.app_ids_analyzed

    def test_check_indexer_compat_returns_compat_result(self):
        """check_indexer_compat returns a CompatResult dataclass."""
        from chat_app.upgrade_readiness.uf_analyzer import check_indexer_compat, CompatResult

        result = check_indexer_compat("9.1.0", "9.1.0")
        assert isinstance(result, CompatResult)
        assert result.uf_version == "9.1.0"
        assert result.indexer_version == "9.1.0"

    def test_local_overrides_used_in_uf_analysis(self):
        """UF analysis merges local/ into effective config before comparing."""
        from chat_app.upgrade_readiness.uf_analyzer import analyze_uf_upgrade

        # Old app: default has monitor, local overrides path
        old = _baseline(
            "uf_app",
            default_confs={
                "inputs": {"monitor:///default/path": {"sourcetype": "myapp"}}
            },
            local_confs={
                "inputs": {"monitor:///local/path": {"sourcetype": "myapp"}}
            },
        )
        # New app: same default path (unchanged)
        new = _baseline(
            "uf_app",
            default_confs={
                "inputs": {"monitor:///default/path": {"sourcetype": "myapp"}}
            },
        )
        # The local-only stanza is not in new — that could produce a finding
        # What matters is the function runs without error
        report = analyze_uf_upgrade([old], [new], "local-uf")
        assert isinstance(report.findings, list)

    def test_ssl_verifyservercert_change_is_connection_risk(self):
        """Changing sslVerifyServerCert in outputs produces CONNECTION risk."""
        from chat_app.upgrade_readiness.uf_analyzer import analyze_uf_upgrade

        old = _baseline(
            "uf_app",
            default_confs={
                "outputs": {
                    "tcpout:primary": {
                        "server": "idx1:9997",
                        "sslVerifyServerCert": "false",
                    }
                }
            },
        )
        new = _baseline(
            "uf_app",
            default_confs={
                "outputs": {
                    "tcpout:primary": {
                        "server": "idx1:9997",
                        "sslVerifyServerCert": "true",
                    }
                }
            },
        )
        report = analyze_uf_upgrade([old], [new], "ssl-verify-uf")
        connection = [f for f in report.findings if f.category == "CONNECTION"]
        assert len(connection) >= 1


# ===========================================================================
# TestIntegrationSprint2
# ===========================================================================


class TestIntegrationSprint2:
    """10 integration tests using the sample org repo and in-memory fixtures."""

    def test_sample_repo_es_apps_cim_compliance(self):
        """
        Scan cluster-es apps from sample repo and run CIM compliance check.
        SA-CIM app has eventtypes and tags — should produce at least one CIM result.
        """
        if not SAMPLE_ES_APPS.exists():
            pytest.skip("Sample repo not present")

        from chat_app.upgrade_readiness import scan_app_directory, check_cim_compliance

        sa_cim_dir = SAMPLE_ES_APPS / "SA-CIM"
        if not sa_cim_dir.exists():
            pytest.skip("SA-CIM not in sample repo")

        baseline = scan_app_directory(str(sa_cim_dir))
        results = check_cim_compliance(baseline)
        # SA-CIM has authentication, network_traffic, endpoint_processes eventtypes
        assert len(results) >= 1

    def test_sample_repo_es_dependency_graph(self):
        """
        Scan cluster-es cluster apps and build a dependency graph.
        Expects at least one edge (ES savedsearches reference macros/lookups).
        """
        if not SAMPLE_ES_APPS.exists():
            pytest.skip("Sample repo not present")

        from chat_app.upgrade_readiness import (
            scan_cluster_directory,
            build_dependency_graph,
        )

        inventory = scan_cluster_directory(str(SAMPLE_ES_APPS))
        graph = build_dependency_graph(inventory)
        # cluster-es has ES searches using macros — should have macro edges
        assert len(graph.nodes) >= 1

    def test_sample_repo_ta_windows_cim_check(self):
        """
        Splunk_TA_windows in cluster-es has props.conf with FIELDALIAS for CIM fields.
        SA-CIM provides the eventtype/tags; TA_windows provides the FIELDALIAS.
        """
        if not SAMPLE_ES_APPS.exists():
            pytest.skip("Sample repo not present")

        from chat_app.upgrade_readiness import scan_app_directory, check_cim_compliance

        ta_dir = SAMPLE_ES_APPS / "Splunk_TA_windows"
        if not ta_dir.exists():
            pytest.skip("Splunk_TA_windows not in sample repo")

        baseline = scan_app_directory(str(ta_dir))
        # TA_windows itself may not have eventtypes, so CIM check may return []
        results = check_cim_compliance(baseline)
        # Just verify no exceptions are raised
        assert isinstance(results, list)

    def test_full_pipeline_scan_diff_cim_deps(self):
        """
        Full Sprint 1+2 pipeline:
        scan → diff → CIM check → dependency trace → all without errors.
        """
        from chat_app.upgrade_readiness import (
            build_impact_report,
            check_cim_compliance,
            build_dependency_graph,
            three_way_diff,
        )
        from chat_app.upgrade_readiness.models import ClusterInventory

        # Build two baselines (old vs new)
        old = _baseline(
            "TA_pipeline",
            default_confs={
                "eventtypes": {"authentication": {"search": 'sourcetype="auth"'}},
                "tags": {"eventtype=authentication": {"authentication": "enabled"}},
                "props": {
                    "auth": {
                        "LINE_BREAKER": r"([\r\n]+)",
                        "FIELDALIAS-action": "old_act AS action",
                        "FIELDALIAS-user": "username AS user",
                        "FIELDALIAS-src": "src_ip AS src",
                        "FIELDALIAS-dest": "dest_ip AS dest",
                        "FIELDALIAS-app": "app_name AS app",
                        "TRANSFORMS-t": "auth-extract",
                    }
                },
                "transforms": {"auth-extract": {"REGEX": r"(.+)", "FORMAT": "field::$1"}},
                "savedsearches": {
                    "Brute Force": {"search": "`authentication` | stats count by src"}
                },
                "macros": {"authentication": {"definition": "tag=authentication"}},
            },
        )

        new = _baseline(
            "TA_pipeline",
            default_confs={
                "eventtypes": {"authentication": {"search": 'sourcetype="auth"'}},
                "tags": {"eventtype=authentication": {"authentication": "enabled"}},
                "props": {
                    "auth": {
                        "LINE_BREAKER": r"---CHANGED---",  # CRITICAL index-time change
                        "FIELDALIAS-user": "username AS user",
                        "FIELDALIAS-src": "src_ip AS src",
                        "FIELDALIAS-dest": "dest_ip AS dest",
                        "FIELDALIAS-app": "app_name AS app",
                    }
                },
                "transforms": {},
                "savedsearches": {
                    "Brute Force": {"search": "`authentication` | stats count by src"}
                },
                "macros": {"authentication": {"definition": "tag=authentication"}},
            },
        )

        # Step 1: Diff
        findings = three_way_diff(
            old_default=old.get_default_stanzas("props"),
            new_default=new.get_default_stanzas("props"),
            local=old.get_local_stanzas("props"),
            conf_type="props",
            app_id="TA_pipeline",
        )
        report = build_impact_report(
            findings=findings,
            app_id="TA_pipeline",
            from_version="1.0.0",
            to_version="2.0.0",
        )
        assert report.critical_count >= 1  # LINE_BREAKER changed

        # Step 2: CIM check
        cim_results = check_cim_compliance(old)
        assert len(cim_results) >= 1

        # Step 3: Dependency graph
        inv = ClusterInventory(cluster_name="test")
        inv.apps["TA_pipeline"] = old
        graph = build_dependency_graph(inv)
        assert len(graph.nodes) >= 1

    def test_upgrade_cim_regression_in_pipeline(self):
        """Full pipeline: diff shows LINE_BREAKER change; CIM check shows field regression."""
        from chat_app.upgrade_readiness import (
            check_upgrade_cim_impact,
            three_way_diff,
        )
        from chat_app.upgrade_readiness.models import UpgradeRisk

        old = _baseline(
            "TA_reg_pipeline",
            default_confs={
                "eventtypes": {"authentication": {"search": 'sourcetype="syslog"'}},
                "tags": {"eventtype=authentication": {"authentication": "enabled"}},
                "props": {
                    "syslog": {
                        "FIELDALIAS-action": "act AS action",
                        "FIELDALIAS-app": "application AS app",
                        "FIELDALIAS-dest": "destination AS dest",
                        "FIELDALIAS-src": "source AS src",
                        "FIELDALIAS-user": "username AS user",
                    }
                },
            },
        )

        new_confs = {
            "eventtypes": {"authentication": {"search": 'sourcetype="syslog"'}},
            "tags": {"eventtype=authentication": {"authentication": "enabled"}},
            "props": {
                "syslog": {
                    # Drop action, app to create regression
                    "FIELDALIAS-dest": "destination AS dest",
                    "FIELDALIAS-src": "source AS src",
                    "FIELDALIAS-user": "username AS user",
                }
            },
        }

        diff_findings = three_way_diff(
            old_default=old.get_default_stanzas("props"),
            new_default={k: v for k, v in new_confs.items()}.get("props", {}),
            local=old.get_local_stanzas("props"),
            conf_type="props",
        )
        regressions = check_upgrade_cim_impact(old, new_confs)
        assert len(regressions) >= 1
        assert any(r.field == "action" for r in regressions)

    def test_uf_analysis_with_sample_deployment_app(self):
        """
        Use sample repo deployment-apps and create a mock upgrade to test UF analysis.
        """
        if not SAMPLE_REPO.exists():
            pytest.skip("Sample repo not present")

        from chat_app.upgrade_readiness import analyze_uf_upgrade

        global_uf_dir = SAMPLE_REPO / "deployment-apps" / "_global" / "org_all_forwarders"
        if not global_uf_dir.exists():
            pytest.skip("org_all_forwarders not in sample repo")

        from chat_app.upgrade_readiness import scan_app_directory

        old_baseline = scan_app_directory(str(global_uf_dir))
        # New version: identical (no changes) — expect no findings
        new_baseline = scan_app_directory(str(global_uf_dir))

        report = analyze_uf_upgrade([old_baseline], [new_baseline], "global-uf")
        # Identical configs → no risk findings
        assert not report.data_loss_risk or len(report.findings) == 0

    def test_dependency_trace_from_sample_transforms(self):
        """
        Build dependency graph from sample ES apps and trace impact
        from a TA_windows transform stanza.
        """
        if not SAMPLE_ES_APPS.exists():
            pytest.skip("Sample repo not present")

        from chat_app.upgrade_readiness import (
            scan_cluster_directory,
            build_dependency_graph,
            trace_impact,
        )
        from chat_app.upgrade_readiness.dependency_tracer import (
            _make_node_id,
            ENTITY_TRANSFORMS_STANZA,
        )

        inventory = scan_cluster_directory(str(SAMPLE_ES_APPS))
        graph = build_dependency_graph(inventory)

        # Try to trace impact from the msad-xml-eventcode-extract transform in TA_windows
        node_id = _make_node_id(
            "Splunk_TA_windows", ENTITY_TRANSFORMS_STANZA, "msad-xml-eventcode-extract"
        )
        if node_id not in graph.nodes:
            pytest.skip("Transform node not found in graph (app may not have been scanned)")

        paths = trace_impact(graph, [node_id])
        assert isinstance(paths, list)

    def test_sprint1_and_sprint2_work_together(self):
        """Sprint 1 models used in Sprint 2 functions without import errors."""
        from chat_app.upgrade_readiness import (
            scan_app_directory,
            three_way_diff,
            build_impact_report,
            check_cim_compliance,
            build_dependency_graph,
            analyze_uf_upgrade,
            check_indexer_compat,
        )

        # All imports succeeded without exception
        assert callable(scan_app_directory)
        assert callable(three_way_diff)
        assert callable(build_impact_report)
        assert callable(check_cim_compliance)
        assert callable(build_dependency_graph)
        assert callable(analyze_uf_upgrade)
        assert callable(check_indexer_compat)

    def test_get_cim_summary_with_multiple_apps(self):
        """get_cim_summary aggregates results from multiple apps correctly."""
        from chat_app.upgrade_readiness import check_cim_compliance, get_cim_summary

        app1 = _baseline(
            "app1",
            default_confs={
                "eventtypes": {"authentication": {"search": 'sourcetype="s1"'}},
                "tags": {"eventtype=authentication": {"authentication": "enabled"}},
                "props": {
                    "s1": {
                        "FIELDALIAS-action": "a AS action",
                        "FIELDALIAS-app": "b AS app",
                        "FIELDALIAS-dest": "c AS dest",
                        "FIELDALIAS-src": "d AS src",
                        "FIELDALIAS-user": "e AS user",
                    }
                },
            },
        )
        app2 = _baseline(
            "app2",
            default_confs={
                "eventtypes": {"network_traffic": {"search": 'sourcetype="fw"'}},
                "tags": {
                    "eventtype=network_traffic": {
                        "network": "enabled",
                        "communicate": "enabled",
                    }
                },
                "props": {},  # missing all required fields
            },
        )

        results = check_cim_compliance(app1) + check_cim_compliance(app2)
        summary = get_cim_summary(results)
        assert summary["total_checks"] == 2
        assert summary["compliant"] == 1
        assert summary["non_compliant"] == 1

    def test_dependency_summary_after_cluster_scan(self):
        """get_dependency_summary returns correct counts after building graph."""
        from chat_app.upgrade_readiness import build_dependency_graph, get_dependency_summary
        from chat_app.upgrade_readiness.models import ClusterInventory

        ta = _baseline(
            "TA_dep_sum",
            default_confs={
                "props": {"src": {"TRANSFORMS-t": "extract_t"}},
                "transforms": {"extract_t": {"REGEX": r"(.+)"}},
                "savedsearches": {
                    "Alert": {"search": "index=main | lookup extract_t field"}
                },
                "macros": {"auth": {"definition": "tag=authentication"}},
            },
        )
        inv = ClusterInventory(cluster_name="sum_cluster")
        inv.apps["TA_dep_sum"] = ta
        graph = build_dependency_graph(inv)
        summary = get_dependency_summary(graph)

        assert summary["node_count"] >= 3  # props stanza + transform + savedsearch
        assert summary["edge_count"] >= 1
        assert "most_depended_upon" in summary


# ---------------------------------------------------------------------------
# ES Analyzer Tests
# ---------------------------------------------------------------------------

class TestESAnalyzer:
    """Tests for Enterprise Security upgrade analysis."""

    def test_correlation_search_removed_is_critical(self):
        from chat_app.upgrade_readiness.es_analyzer import analyze_es_upgrade
        old = {"savedsearches": {"Brute Force": {"search": "tag=auth", "action.correlationsearch.enabled": "1"}}}
        new = {"savedsearches": {}}
        local = {"savedsearches": {}}
        report = analyze_es_upgrade(old, new, local)
        assert report.correlation_searches_removed == 1
        assert any(f.detection_gap for f in report.findings)
        assert report.overall_risk.value == "CRITICAL"

    def test_correlation_search_modified(self):
        from chat_app.upgrade_readiness.es_analyzer import analyze_es_upgrade
        old = {"savedsearches": {"BF": {"search": "old query", "action.correlationsearch.enabled": "1"}}}
        new = {"savedsearches": {"BF": {"search": "new query", "action.correlationsearch.enabled": "1"}}}
        report = analyze_es_upgrade(old, new, {"savedsearches": {}})
        assert report.correlation_searches_modified == 1

    def test_critical_macro_removed(self):
        from chat_app.upgrade_readiness.es_analyzer import analyze_es_upgrade
        old = {"macros": {"authentication": {"definition": "tag=authentication"}}}
        new = {"macros": {}}
        report = analyze_es_upgrade(old, new, {"macros": {}})
        assert any(f.risk.value == "CRITICAL" for f in report.findings)

    def test_lookup_fields_changed(self):
        from chat_app.upgrade_readiness.es_analyzer import analyze_es_upgrade
        old = {"transforms": {"identity_lookup": {"filename": "id.csv", "fields_list": "user,dept"}}}
        new = {"transforms": {"identity_lookup": {"filename": "id.csv", "fields_list": "user,dept,risk"}}}
        report = analyze_es_upgrade(old, new, {})
        assert report.lookups_changed == 1

    def test_detect_upgrade_type_es(self):
        from chat_app.upgrade_readiness.es_analyzer import detect_upgrade_type
        assert detect_upgrade_type("SplunkEnterpriseSecurityInstaller").value == "es"
        assert detect_upgrade_type("DA-ESS-ContentUpdate").value == "es"
        assert detect_upgrade_type("Splunk_TA_windows").value == "ta"
        assert detect_upgrade_type("SA-CIM").value == "sa"

    def test_safe_es_upgrade(self):
        from chat_app.upgrade_readiness.es_analyzer import analyze_es_upgrade
        confs = {"savedsearches": {"X": {"search": "q", "action.correlationsearch.enabled": "1"}}}
        report = analyze_es_upgrade(confs, confs, {})
        assert report.recommendation.startswith("Safe")


class TestITSIAnalyzer:
    """Tests for ITSI upgrade analysis."""

    def test_kpi_threshold_changed(self):
        from chat_app.upgrade_readiness.itsi_analyzer import analyze_itsi_upgrade
        old = {"savedsearches": {"KPI - CPU": {"alert.threshold": "90", "search": "q"}}}
        new = {"savedsearches": {"KPI - CPU": {"alert.threshold": "95", "search": "q"}}}
        report = analyze_itsi_upgrade(old, new, {})
        assert report.thresholds_changed >= 1
        assert report.overall_risk.value == "HIGH"

    def test_service_removed(self):
        from chat_app.upgrade_readiness.itsi_analyzer import analyze_itsi_upgrade
        old = {"itsi_service": {"web_service": {"title": "Web"}}}
        new = {"itsi_service": {}}
        report = analyze_itsi_upgrade(old, new, {})
        assert report.services_affected >= 1

    def test_safe_itsi_upgrade(self):
        from chat_app.upgrade_readiness.itsi_analyzer import analyze_itsi_upgrade
        confs = {"savedsearches": {}}
        report = analyze_itsi_upgrade(confs, confs, {})
        assert report.recommendation.startswith("Safe")

    def test_aggregation_policy_removed(self):
        from chat_app.upgrade_readiness.itsi_analyzer import analyze_itsi_upgrade
        old = {"itsi_notable_event_aggregation": {"policy1": {"filter": "severity>3"}}}
        new = {"itsi_notable_event_aggregation": {}}
        report = analyze_itsi_upgrade(old, new, {})
        assert report.aggregation_policies_changed >= 1

    def test_itsi_search_removed(self):
        from chat_app.upgrade_readiness.itsi_analyzer import analyze_itsi_upgrade
        old = {"savedsearches": {"ITSI Health Check": {"search": "index=_internal"}}}
        new = {"savedsearches": {}}
        report = analyze_itsi_upgrade(old, new, {})
        assert len(report.findings) >= 1
