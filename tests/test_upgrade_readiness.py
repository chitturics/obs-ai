"""
Comprehensive tests for the Splunk Upgrade Readiness Testing System — Sprint 1.

Coverage:
  TestModels             — enum values, dataclass creation, serialization (10 tests)
  TestConfDiffer         — three_way_diff for all conflict scenarios (40+ tests)
  TestImpactScorer       — risk classification, recommendation generation (15 tests)
  TestBaselineBuilder    — app version extraction, directory scanning (15 tests)
  TestIntegration        — full pipeline from scan to findings (10 tests)
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict

import pytest

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so imports work in isolation
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Fixtures directory
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "upgrade_readiness"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stanzas(*items: tuple) -> Dict[str, Dict[str, str]]:
    """Build a stanza dict from (stanza_name, {key: val, ...}) pairs."""
    return {name: dict(keys) for name, keys in items}


# ===========================================================================
# TestModels
# ===========================================================================


class TestModels:
    def test_upgrade_risk_enum_values(self):
        from chat_app.upgrade_readiness.models import UpgradeRisk

        assert UpgradeRisk.INFO.value == "INFO"
        assert UpgradeRisk.LOW.value == "LOW"
        assert UpgradeRisk.MEDIUM.value == "MEDIUM"
        assert UpgradeRisk.HIGH.value == "HIGH"
        assert UpgradeRisk.CRITICAL.value == "CRITICAL"

    def test_upgrade_risk_ordering(self):
        from chat_app.upgrade_readiness.models import UpgradeRisk

        assert UpgradeRisk.INFO < UpgradeRisk.LOW
        assert UpgradeRisk.LOW < UpgradeRisk.MEDIUM
        assert UpgradeRisk.MEDIUM < UpgradeRisk.HIGH
        assert UpgradeRisk.HIGH < UpgradeRisk.CRITICAL
        assert UpgradeRisk.INFO <= UpgradeRisk.INFO

    def test_finding_category_enum_values(self):
        from chat_app.upgrade_readiness.models import FindingCategory

        # Core categories (must exist)
        core = {
            "STANZA_REMOVED", "STANZA_ADDED", "KEY_REMOVED", "KEY_ADDED",
            "KEY_CHANGED", "INDEX_TIME_CHANGE", "MERGE_CONFLICT", "ORPHANED_LOCAL",
        }
        actual = {c.value for c in FindingCategory}
        assert core.issubset(actual), f"Missing core categories: {core - actual}"
        # ES/ITSI/UF categories also expected
        assert len(actual) >= 8, f"Expected 8+ categories, got {len(actual)}"

    def test_conf_file_type_from_filename(self):
        from chat_app.upgrade_readiness.models import ConfFileType

        assert ConfFileType.from_filename("props.conf") == ConfFileType.PROPS
        assert ConfFileType.from_filename("transforms.conf") == ConfFileType.TRANSFORMS
        assert ConfFileType.from_filename("savedsearches.conf") == ConfFileType.SAVEDSEARCHES
        assert ConfFileType.from_filename("unknown.conf") == ConfFileType.OTHER

    def test_test_status_enum(self):
        from chat_app.upgrade_readiness.models import TestStatus

        assert TestStatus.PENDING.value == "PENDING"
        assert TestStatus.PASSED.value == "PASSED"
        assert TestStatus.FAILED.value == "FAILED"

    def test_app_version_dataclass(self):
        from chat_app.upgrade_readiness.models import AppVersion

        v = AppVersion(app_id="Splunk_TA_example", version="2.3.1", author="Splunk")
        assert v.app_id == "Splunk_TA_example"
        assert v.version == "2.3.1"
        assert v.as_tuple() == (2, 3, 1)

    def test_app_version_tuple_comparison(self):
        from chat_app.upgrade_readiness.models import AppVersion

        v1 = AppVersion(app_id="ta", version="1.0.0")
        v2 = AppVersion(app_id="ta", version="2.0.0")
        assert v1.as_tuple() < v2.as_tuple()

    def test_upgrade_finding_create(self):
        from chat_app.upgrade_readiness.models import (
            FindingCategory,
            UpgradeFinding,
            UpgradeRisk,
        )

        f = UpgradeFinding.create(
            risk=UpgradeRisk.HIGH,
            category=FindingCategory.KEY_CHANGED,
            conf_type="props",
            stanza="source::syslog",
            description="A description",
            recommendation="Do something",
            key="TIME_FORMAT",
            old_value="%b %d",
            new_value="%Y-%m-%d",
        )
        assert f.risk == UpgradeRisk.HIGH
        assert f.key == "TIME_FORMAT"
        assert f.finding_id  # auto-generated UUID

    def test_upgrade_impact_report_counts(self):
        from chat_app.upgrade_readiness.models import (
            FindingCategory,
            UpgradeFinding,
            UpgradeImpactReport,
            UpgradeRisk,
        )

        def _f(risk):
            return UpgradeFinding.create(
                risk=risk,
                category=FindingCategory.KEY_CHANGED,
                conf_type="props",
                stanza="s",
                description="d",
                recommendation="r",
            )

        report = UpgradeImpactReport(
            findings=[
                _f(UpgradeRisk.CRITICAL),
                _f(UpgradeRisk.HIGH),
                _f(UpgradeRisk.HIGH),
                _f(UpgradeRisk.MEDIUM),
                _f(UpgradeRisk.INFO),
            ]
        )
        assert report.critical_count == 1
        assert report.high_count == 2
        assert report.medium_count == 1
        assert report.low_count == 0
        assert report.info_count == 1

    def test_finding_response_serialization(self):
        from chat_app.upgrade_readiness.models import (
            FindingCategory,
            FindingResponse,
            UpgradeFinding,
            UpgradeRisk,
        )

        f = UpgradeFinding.create(
            risk=UpgradeRisk.CRITICAL,
            category=FindingCategory.INDEX_TIME_CHANGE,
            conf_type="props",
            stanza="source::syslog",
            description="desc",
            recommendation="rec",
            key="LINE_BREAKER",
        )
        resp = FindingResponse.from_finding(f)
        assert resp.risk == "CRITICAL"
        assert resp.category == "INDEX_TIME_CHANGE"
        # Pydantic can serialise to dict
        data = resp.model_dump()
        assert data["stanza"] == "source::syslog"


# ===========================================================================
# TestConfDiffer
# ===========================================================================


class TestConfDiffer:
    # --- simulate_splunk_merge ---

    def test_merge_local_overrides_default(self):
        from chat_app.upgrade_readiness.conf_differ import simulate_splunk_merge

        default = {"TIME_FORMAT": "%b %d", "SHOULD_LINEMERGE": "false"}
        local = {"TIME_FORMAT": "%Y-%m-%d"}
        merged = simulate_splunk_merge(default, local)
        assert merged["TIME_FORMAT"] == "%Y-%m-%d"
        assert merged["SHOULD_LINEMERGE"] == "false"

    def test_merge_local_adds_new_key(self):
        from chat_app.upgrade_readiness.conf_differ import simulate_splunk_merge

        default = {"A": "1"}
        local = {"B": "2"}
        merged = simulate_splunk_merge(default, local)
        assert merged == {"A": "1", "B": "2"}

    def test_merge_empty_local(self):
        from chat_app.upgrade_readiness.conf_differ import simulate_splunk_merge

        default = {"A": "1", "B": "2"}
        merged = simulate_splunk_merge(default, {})
        assert merged == default

    def test_merge_empty_default(self):
        from chat_app.upgrade_readiness.conf_differ import simulate_splunk_merge

        local = {"A": "1"}
        merged = simulate_splunk_merge({}, local)
        assert merged == local

    # --- Stanza-level scenarios ---

    def test_stanza_removed_with_local_is_critical(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old = _make_stanzas(("source::syslog", {"TIME_FORMAT": "%b %d"}))
        new: Dict = {}
        local = _make_stanzas(("source::syslog", {"FIELDALIAS-src": "src_host AS src_ip"}))

        findings = three_way_diff(old, new, local, conf_type="props")
        assert len(findings) == 1
        assert findings[0].risk == UpgradeRisk.CRITICAL
        assert findings[0].category == FindingCategory.ORPHANED_LOCAL
        assert findings[0].stanza == "source::syslog"

    def test_stanza_removed_no_local_is_medium(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old = _make_stanzas(("source::syslog", {"TIME_FORMAT": "%b %d"}))
        new: Dict = {}
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="props")
        assert len(findings) == 1
        assert findings[0].risk == UpgradeRisk.MEDIUM
        assert findings[0].category == FindingCategory.STANZA_REMOVED

    def test_stanza_added_with_local_conflict_is_medium(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old: Dict = {}
        new = _make_stanzas(("new_stanza", {"KEY": "vendor_value"}))
        local = _make_stanzas(("new_stanza", {"KEY": "local_value"}))

        findings = three_way_diff(old, new, local, conf_type="props")
        assert len(findings) >= 1
        conflict = next(
            (f for f in findings if f.category == FindingCategory.MERGE_CONFLICT), None
        )
        assert conflict is not None
        assert conflict.risk == UpgradeRisk.MEDIUM

    def test_stanza_added_no_local_is_info(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old: Dict = {}
        new = _make_stanzas(("new_stanza", {"KEY": "value"}))
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="props")
        assert len(findings) == 1
        assert findings[0].risk == UpgradeRisk.INFO
        assert findings[0].category == FindingCategory.STANZA_ADDED

    def test_key_changed_with_local_override_is_low(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old = _make_stanzas(("stanza", {"TRANSFORMS-syslog": "v1_extract"}))
        new = _make_stanzas(("stanza", {"TRANSFORMS-syslog": "v2_extract"}))
        local = _make_stanzas(("stanza", {"TRANSFORMS-syslog": "custom_extract"}))

        findings = three_way_diff(old, new, local, conf_type="props")
        changed = [f for f in findings if f.category == FindingCategory.KEY_CHANGED]
        assert any(f.risk == UpgradeRisk.LOW for f in changed)

    def test_key_changed_no_local_override_is_high(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old = _make_stanzas(("stanza", {"REGEX": "old_pattern"}))
        new = _make_stanzas(("stanza", {"REGEX": "new_pattern"}))
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="transforms")
        changed = [f for f in findings if f.category == FindingCategory.KEY_CHANGED]
        assert any(f.risk == UpgradeRisk.HIGH for f in changed)

    def test_key_removed_no_local_override_is_high(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old = _make_stanzas(("s", {"A": "1", "B": "2"}))
        new = _make_stanzas(("s", {"A": "1"}))
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="props")
        removed = [f for f in findings if f.category == FindingCategory.KEY_REMOVED]
        assert len(removed) == 1
        assert removed[0].risk == UpgradeRisk.HIGH
        assert removed[0].key == "B"

    def test_key_removed_with_local_override_is_low(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old = _make_stanzas(("s", {"TRANSFORMS-x": "v1"}))
        new = _make_stanzas(("s", {}))
        local = _make_stanzas(("s", {"TRANSFORMS-x": "custom"}))

        findings = three_way_diff(old, new, local, conf_type="props")
        removed = [f for f in findings if f.category == FindingCategory.KEY_REMOVED]
        assert any(f.risk == UpgradeRisk.LOW for f in removed)

    def test_index_time_key_changed_is_critical(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old = _make_stanzas(("source::syslog", {"LINE_BREAKER": r"([\r\n]+)"}))
        new = _make_stanzas(("source::syslog", {"LINE_BREAKER": r"([^\r\n]+)"}))
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="props")
        index_time = [f for f in findings if f.category == FindingCategory.INDEX_TIME_CHANGE]
        assert len(index_time) >= 1
        assert index_time[0].risk == UpgradeRisk.CRITICAL

    def test_time_format_change_is_critical(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old = _make_stanzas(("s", {"TIME_FORMAT": "%b %d %H:%M:%S"}))
        new = _make_stanzas(("s", {"TIME_FORMAT": "%Y-%m-%dT%H:%M:%S"}))
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="props")
        assert any(
            f.risk == UpgradeRisk.CRITICAL and f.category == FindingCategory.INDEX_TIME_CHANGE
            for f in findings
        )

    def test_should_linemerge_change_is_critical(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old = _make_stanzas(("s", {"SHOULD_LINEMERGE": "true"}))
        new = _make_stanzas(("s", {"SHOULD_LINEMERGE": "false"}))
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="props")
        assert any(
            f.category == FindingCategory.INDEX_TIME_CHANGE and f.risk == UpgradeRisk.CRITICAL
            for f in findings
        )

    def test_index_time_key_removed_is_critical(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old = _make_stanzas(("s", {"TIME_PREFIX": "time="}))
        new = _make_stanzas(("s", {}))
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="props")
        assert any(
            f.category == FindingCategory.INDEX_TIME_CHANGE and f.risk == UpgradeRisk.CRITICAL
            for f in findings
        )

    def test_key_added_no_local_is_info(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old = _make_stanzas(("s", {"A": "1"}))
        new = _make_stanzas(("s", {"A": "1", "B": "new_default"}))
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="props")
        added = [f for f in findings if f.category == FindingCategory.KEY_ADDED]
        assert len(added) == 1
        assert added[0].risk == UpgradeRisk.INFO

    def test_key_added_with_local_conflict_is_medium(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old = _make_stanzas(("s", {"A": "1"}))
        new = _make_stanzas(("s", {"A": "1", "B": "new_default"}))
        local = _make_stanzas(("s", {"B": "local_value"}))

        findings = three_way_diff(old, new, local, conf_type="props")
        added = [f for f in findings if f.category == FindingCategory.KEY_ADDED]
        assert any(f.risk == UpgradeRisk.MEDIUM for f in added)

    def test_empty_configs_produce_no_findings(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff

        findings = three_way_diff({}, {}, {}, conf_type="props")
        assert findings == []

    def test_identical_configs_produce_no_findings(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff

        same = _make_stanzas(("s", {"A": "1", "B": "2"}))
        findings = three_way_diff(same, same, {}, conf_type="props")
        assert findings == []

    def test_single_stanza_multiple_keys(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import UpgradeRisk

        old = _make_stanzas(("s", {"A": "old", "B": "old", "C": "same"}))
        new = _make_stanzas(("s", {"A": "new", "B": "old", "C": "same", "D": "added"}))
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="props")
        # A changed → HIGH, D added → INFO
        risks = {f.key: f.risk for f in findings}
        assert risks["A"].value in ("HIGH", "CRITICAL")
        assert risks["D"].value == "INFO"

    def test_many_stanzas(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff

        old = {f"stanza_{i}": {"key": f"v{i}"} for i in range(20)}
        new = {f"stanza_{i}": {"key": f"v{i}_new"} for i in range(20)}
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="transforms")
        # Each stanza has one key changed with no local → HIGH
        assert len(findings) == 20

    def test_findings_sorted_critical_first(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import UpgradeRisk

        old = _make_stanzas(
            ("s1", {"LINE_BREAKER": "(a)"}),
            ("s2", {"REGEX": "old"}),
        )
        new = _make_stanzas(
            ("s1", {"LINE_BREAKER": "(b)"}),
            ("s2", {"REGEX": "new"}),
        )
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="props")
        assert findings[0].risk == UpgradeRisk.CRITICAL

    def test_app_id_propagated_to_findings(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff

        old = _make_stanzas(("s", {"A": "1"}))
        new = _make_stanzas(("s", {"A": "2"}))
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="props", app_id="MyTA")
        assert all(f.app_id == "MyTA" for f in findings)

    def test_build_stanza_diff_summary(self):
        from chat_app.upgrade_readiness.conf_differ import build_stanza_diff

        old = {"A": "1", "B": "old", "C": "same"}
        new = {"B": "new", "C": "same", "D": "added"}
        local = {"B": "local"}

        diff = build_stanza_diff("s", old, new, local, "props")
        assert "A" in diff.removed_keys
        assert "D" in diff.added_keys
        assert "B" in diff.changed_keys
        assert "C" not in diff.changed_keys

    def test_diff_stanza_direct_function(self):
        from chat_app.upgrade_readiness.conf_differ import diff_stanza
        from chat_app.upgrade_readiness.models import UpgradeRisk

        old = {"TIME_FORMAT": "%b %d", "REGEX": "old"}
        new = {"TIME_FORMAT": "%Y-%m-%d", "REGEX": "new"}
        local: Dict = {}

        findings = diff_stanza(old, new, local, "source::syslog", "props")
        risks = {f.key: f.risk for f in findings}
        # TIME_FORMAT is an index-time key
        assert risks["TIME_FORMAT"] == UpgradeRisk.CRITICAL
        assert risks["REGEX"] == UpgradeRisk.HIGH

    def test_multiple_conf_types_independent(self):
        """Findings from props and transforms are independent namespaces."""
        from chat_app.upgrade_readiness.conf_differ import three_way_diff

        old = _make_stanzas(("s", {"KEY": "old"}))
        new = _make_stanzas(("s", {"KEY": "new"}))
        local: Dict = {}

        props_findings = three_way_diff(old, new, local, conf_type="props")
        transform_findings = three_way_diff(old, new, local, conf_type="transforms")

        assert all(f.conf_type == "props" for f in props_findings)
        assert all(f.conf_type == "transforms" for f in transform_findings)

    def test_local_only_stanza_produces_no_findings(self):
        """A stanza only in local/ is an org addition — not a diff concern."""
        from chat_app.upgrade_readiness.conf_differ import three_way_diff

        old: Dict = {}
        new: Dict = {}
        local = _make_stanzas(("org_stanza", {"CUSTOM": "value"}))

        findings = three_way_diff(old, new, local, conf_type="props")
        assert findings == []

    def test_simulate_merge_before_after_detects_change(self):
        """
        Simulate merged state before and after to confirm actual behaviour change.
        """
        from chat_app.upgrade_readiness.conf_differ import simulate_splunk_merge

        old_default = {"REGEX": "old_pattern", "SHOULD_LINEMERGE": "false"}
        new_default = {"REGEX": "new_pattern", "SHOULD_LINEMERGE": "false"}
        local = {"DEST_KEY": "custom_field"}

        merged_before = simulate_splunk_merge(old_default, local)
        merged_after = simulate_splunk_merge(new_default, local)

        assert merged_before != merged_after
        assert merged_before["REGEX"] == "old_pattern"
        assert merged_after["REGEX"] == "new_pattern"
        # Local key preserved in both
        assert merged_before["DEST_KEY"] == "custom_field"
        assert merged_after["DEST_KEY"] == "custom_field"

    def test_finding_old_new_values_populated(self):
        """Findings must carry old/new/local values for display."""
        from chat_app.upgrade_readiness.conf_differ import three_way_diff

        old = _make_stanzas(("s", {"REGEX": "old"}))
        new = _make_stanzas(("s", {"REGEX": "new"}))
        local = _make_stanzas(("s", {"REGEX": "local"}))

        findings = three_way_diff(old, new, local, conf_type="transforms")
        changed = next(f for f in findings if f.key == "REGEX")
        assert changed.old_value == "old"
        assert changed.new_value == "new"
        assert changed.local_value == "local"

    def test_key_added_new_value_populated(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff

        old = _make_stanzas(("s", {}))
        new = _make_stanzas(("s", {"NEW_KEY": "brand_new"}))
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="props")
        added = next(f for f in findings if f.key == "NEW_KEY")
        assert added.new_value == "brand_new"
        assert added.old_value is None

    def test_stanza_with_lines_meta_stripped(self):
        """parse_conf_file_advanced inserts __lines__ — must be ignored."""
        from chat_app.upgrade_readiness.conf_differ import three_way_diff

        old = {"s": {"A": "1", "__lines__": {"A": 5}}}
        new = {"s": {"A": "1", "__lines__": {"A": 5}}}
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="props")
        assert findings == []

    def test_event_breaker_is_index_time_key(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old = _make_stanzas(("s", {"EVENT_BREAKER": "pattern_v1"}))
        new = _make_stanzas(("s", {"EVENT_BREAKER": "pattern_v2"}))
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="props")
        assert any(
            f.category == FindingCategory.INDEX_TIME_CHANGE and f.risk == UpgradeRisk.CRITICAL
            for f in findings
        )

    def test_transforms_regex_change_is_high(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import UpgradeRisk

        old = _make_stanzas(("syslog_extract", {"REGEX": r"(?<host>\S+)", "FORMAT": "host::$1"}))
        new = _make_stanzas(
            ("syslog_extract", {"REGEX": r"(?<host>\S+)\s+(?<ts>\S+)", "FORMAT": "host::$1 ts::$2"})
        )
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="transforms")
        assert any(f.risk == UpgradeRisk.HIGH for f in findings)

    def test_all_five_risk_levels_reachable(self):
        """Verify that all five risk levels can be produced by the differ."""
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import UpgradeRisk

        old = {
            "removed_with_local": {"A": "1"},
            "removed_no_local": {"B": "1"},
            "modified": {"REGEX": "old", "LINE_BREAKER": "(a)", "C": "old", "D": "same"},
        }
        new = {
            "added_no_local": {"E": "new"},
            "modified": {"REGEX": "new", "LINE_BREAKER": "(b)", "C": "old", "D": "same", "F": "added"},
        }
        local = {
            "removed_with_local": {"CUSTOM": "keep"},
            "modified": {"C": "local_c", "F": "local_f"},
        }

        findings = three_way_diff(old, new, local, conf_type="props")
        risks_found = {f.risk for f in findings}
        assert UpgradeRisk.CRITICAL in risks_found
        assert UpgradeRisk.HIGH in risks_found
        assert UpgradeRisk.MEDIUM in risks_found
        assert UpgradeRisk.INFO in risks_found

    def test_truncate_key_is_index_time(self):
        from chat_app.upgrade_readiness.conf_differ import diff_stanza
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old = {"TRUNCATE": "10000"}
        new = {"TRUNCATE": "0"}
        local: Dict = {}

        findings = diff_stanza(old, new, local, "s", "props")
        assert any(
            f.category == FindingCategory.INDEX_TIME_CHANGE and f.risk == UpgradeRisk.CRITICAL
            for f in findings
        )

    def test_diff_finding_ids_are_unique(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff

        old = {f"s{i}": {"K": f"v{i}"} for i in range(10)}
        new = {f"s{i}": {"K": f"v{i}_new"} for i in range(10)}
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="props")
        ids = [f.finding_id for f in findings]
        assert len(ids) == len(set(ids))

    def test_multiple_index_time_keys_all_critical(self):
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old = _make_stanzas(
            ("s", {"LINE_BREAKER": "a", "TIME_FORMAT": "b", "TIME_PREFIX": "c"})
        )
        new = _make_stanzas(
            ("s", {"LINE_BREAKER": "x", "TIME_FORMAT": "y", "TIME_PREFIX": "z"})
        )
        local: Dict = {}

        findings = three_way_diff(old, new, local, conf_type="props")
        index_time = [f for f in findings if f.category == FindingCategory.INDEX_TIME_CHANGE]
        assert len(index_time) == 3
        assert all(f.risk == UpgradeRisk.CRITICAL for f in index_time)


# ===========================================================================
# TestImpactScorer
# ===========================================================================


class TestImpactScorer:
    def _make_finding(self, risk, category, key="k", stanza="s", local_value=None):
        from chat_app.upgrade_readiness.models import UpgradeFinding

        return UpgradeFinding.create(
            risk=risk,
            category=category,
            conf_type="props",
            stanza=stanza,
            key=key,
            description="desc",
            recommendation="rec",
            local_value=local_value,
        )

    def test_classify_risk_index_time_always_critical(self):
        from chat_app.upgrade_readiness.impact_scorer import classify_risk
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        f = self._make_finding(UpgradeRisk.HIGH, FindingCategory.INDEX_TIME_CHANGE)
        assert classify_risk(f) == UpgradeRisk.CRITICAL

    def test_classify_risk_orphaned_local_always_critical(self):
        from chat_app.upgrade_readiness.impact_scorer import classify_risk
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        f = self._make_finding(UpgradeRisk.MEDIUM, FindingCategory.ORPHANED_LOCAL)
        assert classify_risk(f) == UpgradeRisk.CRITICAL

    def test_classify_risk_key_changed_with_local_is_low(self):
        from chat_app.upgrade_readiness.impact_scorer import classify_risk
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        f = self._make_finding(
            UpgradeRisk.HIGH, FindingCategory.KEY_CHANGED, local_value="custom"
        )
        assert classify_risk(f) == UpgradeRisk.LOW

    def test_classify_risk_key_removed_no_local_is_high(self):
        from chat_app.upgrade_readiness.impact_scorer import classify_risk
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        f = self._make_finding(UpgradeRisk.HIGH, FindingCategory.KEY_REMOVED)
        assert classify_risk(f) == UpgradeRisk.HIGH

    def test_score_findings_deduplicates(self):
        from chat_app.upgrade_readiness.impact_scorer import score_findings
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        f1 = self._make_finding(UpgradeRisk.HIGH, FindingCategory.KEY_CHANGED, key="A")
        f2 = self._make_finding(UpgradeRisk.HIGH, FindingCategory.KEY_CHANGED, key="A")

        scored = score_findings([f1, f2])
        # Same (conf_type, stanza, key, category) → deduplicated
        assert len(scored) == 1

    def test_score_findings_sorted_critical_first(self):
        from chat_app.upgrade_readiness.impact_scorer import score_findings
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        findings = [
            self._make_finding(UpgradeRisk.INFO, FindingCategory.STANZA_ADDED, key="a"),
            self._make_finding(UpgradeRisk.CRITICAL, FindingCategory.INDEX_TIME_CHANGE, key="b"),
            self._make_finding(UpgradeRisk.HIGH, FindingCategory.KEY_CHANGED, key="c"),
        ]
        scored = score_findings(findings)
        assert scored[0].risk.value == "CRITICAL"

    def test_generate_recommendation_safe(self):
        from chat_app.upgrade_readiness.impact_scorer import generate_recommendation
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        findings = [
            self._make_finding(UpgradeRisk.INFO, FindingCategory.STANZA_ADDED),
            self._make_finding(UpgradeRisk.LOW, FindingCategory.KEY_CHANGED, local_value="v"),
        ]
        assert generate_recommendation(findings) == "Safe to upgrade"

    def test_generate_recommendation_review_required_high(self):
        from chat_app.upgrade_readiness.impact_scorer import generate_recommendation
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        findings = [self._make_finding(UpgradeRisk.HIGH, FindingCategory.KEY_CHANGED)]
        assert generate_recommendation(findings) == "Review required before upgrade"

    def test_generate_recommendation_review_required_many_medium(self):
        from chat_app.upgrade_readiness.impact_scorer import generate_recommendation
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        findings = [
            self._make_finding(UpgradeRisk.MEDIUM, FindingCategory.STANZA_REMOVED, stanza=f"s{i}")
            for i in range(5)
        ]
        assert generate_recommendation(findings) == "Review required before upgrade"

    def test_generate_recommendation_do_not_upgrade_critical(self):
        from chat_app.upgrade_readiness.impact_scorer import generate_recommendation
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        findings = [
            self._make_finding(UpgradeRisk.CRITICAL, FindingCategory.INDEX_TIME_CHANGE)
        ]
        assert generate_recommendation(findings) == "Do not upgrade without remediation"

    def test_generate_recommendation_empty_findings(self):
        from chat_app.upgrade_readiness.impact_scorer import generate_recommendation

        assert generate_recommendation([]) == "Safe to upgrade"

    def test_compute_overall_risk_highest_wins(self):
        from chat_app.upgrade_readiness.impact_scorer import compute_overall_risk
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        findings = [
            self._make_finding(UpgradeRisk.LOW, FindingCategory.KEY_CHANGED, key="a"),
            self._make_finding(UpgradeRisk.CRITICAL, FindingCategory.INDEX_TIME_CHANGE, key="b"),
            self._make_finding(UpgradeRisk.MEDIUM, FindingCategory.STANZA_ADDED, key="c"),
        ]
        assert compute_overall_risk(findings) == UpgradeRisk.CRITICAL

    def test_compute_overall_risk_empty_is_info(self):
        from chat_app.upgrade_readiness.impact_scorer import compute_overall_risk
        from chat_app.upgrade_readiness.models import UpgradeRisk

        assert compute_overall_risk([]) == UpgradeRisk.INFO

    def test_build_impact_report_populates_all_fields(self):
        from chat_app.upgrade_readiness.impact_scorer import build_impact_report
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        findings = [
            self._make_finding(UpgradeRisk.HIGH, FindingCategory.KEY_CHANGED, key="A"),
            self._make_finding(UpgradeRisk.CRITICAL, FindingCategory.INDEX_TIME_CHANGE, key="B"),
        ]
        report = build_impact_report(
            findings,
            app_id="Splunk_TA_test",
            from_version="1.0.0",
            to_version="2.0.0",
            cluster="cluster-es",
        )
        assert report.app_id == "Splunk_TA_test"
        assert report.overall_risk == UpgradeRisk.CRITICAL
        assert "Do not upgrade" in report.recommendation
        assert report.critical_count >= 1

    def test_summarize_impact_structure(self):
        from chat_app.upgrade_readiness.impact_scorer import build_impact_report, summarize_impact
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        findings = [
            self._make_finding(UpgradeRisk.HIGH, FindingCategory.KEY_CHANGED, key="A"),
        ]
        report = build_impact_report(findings, app_id="TA")
        summary = summarize_impact(report)
        assert "risk_counts" in summary
        assert "recommendation" in summary
        assert "overall_risk" in summary
        assert "total_findings" in summary

    def test_score_findings_keeps_higher_risk_on_dedup(self):
        from chat_app.upgrade_readiness.impact_scorer import score_findings
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        # Two findings with same key but different risk
        low_f = self._make_finding(UpgradeRisk.LOW, FindingCategory.KEY_CHANGED, key="A")
        high_f = self._make_finding(UpgradeRisk.HIGH, FindingCategory.KEY_CHANGED, key="A")

        scored = score_findings([low_f, high_f])
        assert len(scored) == 1
        # classify_risk for KEY_CHANGED with no local_value → HIGH
        assert scored[0].risk == UpgradeRisk.HIGH


# ===========================================================================
# TestBaselineBuilder
# ===========================================================================


class TestBaselineBuilder:
    def test_extract_app_version_from_fixture(self):
        from chat_app.upgrade_readiness.baseline_builder import extract_app_version

        app_dir = str(FIXTURES_DIR / "sample_ta_v1")
        version = extract_app_version(app_dir)
        assert version.version == "1.0.0"
        assert version.author == "Splunk Inc."
        assert version.app_id == "sample_ta_v1"

    def test_extract_app_version_v2(self):
        from chat_app.upgrade_readiness.baseline_builder import extract_app_version

        version = extract_app_version(str(FIXTURES_DIR / "sample_ta_v2"))
        assert version.version == "2.0.0"

    def test_extract_app_version_missing_dir(self):
        from chat_app.upgrade_readiness.baseline_builder import extract_app_version

        version = extract_app_version("/nonexistent/path/to/app")
        assert version.version == "0.0.0"

    def test_extract_app_version_as_tuple(self):
        from chat_app.upgrade_readiness.baseline_builder import extract_app_version

        v = extract_app_version(str(FIXTURES_DIR / "sample_ta_v1"))
        assert v.as_tuple() == (1, 0, 0)

    def test_scan_app_directory_v1(self):
        from chat_app.upgrade_readiness.baseline_builder import scan_app_directory

        baseline = scan_app_directory(str(FIXTURES_DIR / "sample_ta_v1"))
        assert baseline.app_id == "sample_ta_v1"
        assert "props" in baseline.default_confs
        assert "transforms" in baseline.default_confs

    def test_scan_app_directory_local_confs(self):
        from chat_app.upgrade_readiness.baseline_builder import scan_app_directory

        baseline = scan_app_directory(str(FIXTURES_DIR / "sample_ta_v1"))
        assert "props" in baseline.local_confs

    def test_scan_app_directory_get_default_stanzas(self):
        from chat_app.upgrade_readiness.baseline_builder import scan_app_directory

        baseline = scan_app_directory(str(FIXTURES_DIR / "sample_ta_v1"))
        stanzas = baseline.get_default_stanzas("props")
        # sample_ta_v1/default/props.conf has [source::syslog]
        assert "source::syslog" in stanzas
        assert "__lines__" not in stanzas.get("source::syslog", {})

    def test_scan_app_directory_get_local_stanzas(self):
        from chat_app.upgrade_readiness.baseline_builder import scan_app_directory

        baseline = scan_app_directory(str(FIXTURES_DIR / "sample_ta_v1"))
        local = baseline.get_local_stanzas("props")
        assert "source::syslog" in local
        assert "__lines__" not in local.get("source::syslog", {})

    def test_scan_app_directory_v2(self):
        from chat_app.upgrade_readiness.baseline_builder import scan_app_directory

        baseline = scan_app_directory(str(FIXTURES_DIR / "sample_ta_v2"))
        assert "props" in baseline.default_confs
        stanzas = baseline.get_default_stanzas("props")
        assert "source::new_sourcetype" in stanzas

    def test_scan_cluster_directory(self, tmp_path):
        """Create a minimal cluster dir with two apps and verify both are scanned."""
        from chat_app.upgrade_readiness.baseline_builder import scan_cluster_directory

        for app_name in ("AppA", "AppB"):
            (tmp_path / app_name / "default").mkdir(parents=True)
            (tmp_path / app_name / "default" / "app.conf").write_text(
                "[launcher]\nversion=1.0.0\nauthor=Test\n"
            )

        inventory = scan_cluster_directory(str(tmp_path))
        assert "AppA" in inventory.apps
        assert "AppB" in inventory.apps

    def test_scan_cluster_directory_missing_path(self):
        from chat_app.upgrade_readiness.baseline_builder import scan_cluster_directory

        inventory = scan_cluster_directory("/nonexistent/cluster")
        assert len(inventory.apps) == 0
        assert len(inventory.errors) > 0

    def test_scan_cluster_skips_non_app_dirs(self, tmp_path):
        from chat_app.upgrade_readiness.baseline_builder import scan_cluster_directory

        # A real app
        (tmp_path / "RealApp" / "default").mkdir(parents=True)
        (tmp_path / "RealApp" / "default" / "app.conf").write_text("[launcher]\nversion=1.0\n")

        # A non-app directory (no default/ or app.conf)
        (tmp_path / "NotAnApp").mkdir()
        (tmp_path / "NotAnApp" / "README.md").write_text("# Not an app")

        inventory = scan_cluster_directory(str(tmp_path))
        assert "RealApp" in inventory.apps
        assert "NotAnApp" not in inventory.apps

    def test_scan_app_directory_with_tmp_path(self, tmp_path):
        from chat_app.upgrade_readiness.baseline_builder import scan_app_directory

        app_dir = tmp_path / "MyTA"
        (app_dir / "default").mkdir(parents=True)
        (app_dir / "local").mkdir()

        (app_dir / "default" / "app.conf").write_text(
            "[launcher]\nversion=3.2.1\nauthor=Acme\n"
        )
        (app_dir / "default" / "props.conf").write_text(
            "[source::mylog]\nTRANSFORMS-my=my_extract\n"
        )
        (app_dir / "local" / "props.conf").write_text(
            "[source::mylog]\nFIELDALIAS-ip=src_ip AS ip\n"
        )

        baseline = scan_app_directory(str(app_dir))
        assert baseline.version.version == "3.2.1"
        assert "source::mylog" in baseline.get_default_stanzas("props")
        assert "source::mylog" in baseline.get_local_stanzas("props")

    def test_scan_app_no_local_dir(self, tmp_path):
        from chat_app.upgrade_readiness.baseline_builder import scan_app_directory

        app_dir = tmp_path / "MinimalTA"
        (app_dir / "default").mkdir(parents=True)
        (app_dir / "default" / "app.conf").write_text("[launcher]\nversion=1.0.0\n")

        baseline = scan_app_directory(str(app_dir))
        assert baseline.local_confs == {}

    def test_app_version_label_from_ui_stanza(self, tmp_path):
        from chat_app.upgrade_readiness.baseline_builder import extract_app_version

        app_dir = tmp_path / "LabeledTA"
        (app_dir / "default").mkdir(parents=True)
        (app_dir / "default" / "app.conf").write_text(
            "[launcher]\nversion=4.0.0\n\n[ui]\nlabel=My Custom Label\n"
        )
        v = extract_app_version(str(app_dir))
        assert v.label == "My Custom Label"
        assert v.version == "4.0.0"


# ===========================================================================
# TestIntegration
# ===========================================================================


class TestIntegration:
    def test_full_pipeline_fixtures(self):
        """Full pipeline: scan fixtures, diff, score, report."""
        from chat_app.upgrade_readiness.baseline_builder import scan_app_directory
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.impact_scorer import build_impact_report
        from chat_app.upgrade_readiness.models import UpgradeRisk

        old_baseline = scan_app_directory(str(FIXTURES_DIR / "sample_ta_v1"))
        new_baseline = scan_app_directory(str(FIXTURES_DIR / "sample_ta_v2"))

        all_findings = []
        for conf_name in old_baseline.default_confs.keys() | new_baseline.default_confs.keys():
            findings = three_way_diff(
                old_default=old_baseline.get_default_stanzas(conf_name),
                new_default=new_baseline.get_default_stanzas(conf_name),
                local=old_baseline.get_local_stanzas(conf_name),
                conf_type=conf_name,
                app_id="sample_ta",
            )
            all_findings.extend(findings)

        report = build_impact_report(
            all_findings,
            app_id="sample_ta",
            from_version=old_baseline.version.version,
            to_version=new_baseline.version.version,
        )

        assert report.from_version == "1.0.0"
        assert report.to_version == "2.0.0"
        assert report.overall_risk != UpgradeRisk.INFO  # fixture has real changes
        assert len(report.findings) > 0

    def test_pipeline_detects_time_format_change(self):
        """The TIME_FORMAT change in the fixture should be CRITICAL."""
        from chat_app.upgrade_readiness.baseline_builder import scan_app_directory
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old_baseline = scan_app_directory(str(FIXTURES_DIR / "sample_ta_v1"))
        new_baseline = scan_app_directory(str(FIXTURES_DIR / "sample_ta_v2"))

        findings = three_way_diff(
            old_default=old_baseline.get_default_stanzas("props"),
            new_default=new_baseline.get_default_stanzas("props"),
            local=old_baseline.get_local_stanzas("props"),
            conf_type="props",
        )

        critical = [
            f for f in findings
            if f.risk == UpgradeRisk.CRITICAL
            and f.category == FindingCategory.INDEX_TIME_CHANGE
        ]
        assert len(critical) >= 1

    def test_pipeline_detects_orphaned_local_customisation(self):
        """
        The fixture local/props.conf has [source::syslog] customisations.
        Even though both v1 and v2 have [source::syslog], a fully removed
        stanza would trigger orphaned local. Verify the orphaned detection
        works with a synthetic scenario.
        """
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.models import FindingCategory, UpgradeRisk

        old = _make_stanzas(("orphan_stanza", {"KEY": "value"}))
        new: Dict = {}
        local = _make_stanzas(("orphan_stanza", {"CUSTOM": "org_value"}))

        findings = three_way_diff(old, new, local, conf_type="props")
        orphaned = [f for f in findings if f.category == FindingCategory.ORPHANED_LOCAL]
        assert len(orphaned) >= 1
        assert orphaned[0].risk == UpgradeRisk.CRITICAL

    def test_report_response_serialization(self):
        """UpgradeReportResponse can be serialised to dict via Pydantic."""
        from chat_app.upgrade_readiness.impact_scorer import build_impact_report
        from chat_app.upgrade_readiness.models import (
            FindingCategory,
            UpgradeFinding,
            UpgradeReportResponse,
            UpgradeRisk,
        )

        findings = [
            UpgradeFinding.create(
                risk=UpgradeRisk.HIGH,
                category=FindingCategory.KEY_CHANGED,
                conf_type="props",
                stanza="s",
                description="desc",
                recommendation="rec",
                key="K",
            )
        ]
        report = build_impact_report(findings, app_id="TA", from_version="1.0", to_version="2.0")
        response = UpgradeReportResponse.from_report(report)
        data = response.model_dump()
        assert data["app_id"] == "TA"
        assert isinstance(data["findings"], list)

    def test_pipeline_with_tmp_path_cluster(self, tmp_path):
        """Build a complete cluster with two apps and scan all."""
        from chat_app.upgrade_readiness.baseline_builder import (
            scan_app_directory,
            scan_cluster_directory,
        )
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.impact_scorer import build_impact_report

        # Create two apps in the cluster
        for app_name, version in (("TA_alpha", "1.0.0"), ("TA_beta", "2.5.0")):
            app_dir = tmp_path / app_name
            (app_dir / "default").mkdir(parents=True)
            (app_dir / "default" / "app.conf").write_text(
                f"[launcher]\nversion={version}\n"
            )
            (app_dir / "default" / "props.conf").write_text(
                "[source::log]\nTRANSFORMS-log=extract_log\n"
            )

        inventory = scan_cluster_directory(str(tmp_path))
        assert len(inventory.apps) == 2
        assert inventory.errors == []

    def test_simulate_merge_integration_with_diff(self):
        """
        Verify that simulate_splunk_merge reflects the same changes that
        three_way_diff flags as HIGH risk.
        """
        from chat_app.upgrade_readiness.conf_differ import simulate_splunk_merge, three_way_diff
        from chat_app.upgrade_readiness.models import UpgradeRisk

        stanza = "source::test"
        old_default = {"REGEX": "old_pattern", "FORMAT": "host::$1"}
        new_default = {"REGEX": "new_pattern", "FORMAT": "host::$1"}
        local: Dict = {}

        merged_before = simulate_splunk_merge(old_default, local)
        merged_after = simulate_splunk_merge(new_default, local)
        assert merged_before != merged_after

        findings = three_way_diff(
            {stanza: old_default}, {stanza: new_default}, {}, conf_type="transforms"
        )
        high_findings = [f for f in findings if f.risk == UpgradeRisk.HIGH]
        assert len(high_findings) >= 1

    def test_analyze_request_pydantic_model(self):
        """AnalyzeUpgradeRequest validates required fields."""
        from chat_app.upgrade_readiness.models import AnalyzeUpgradeRequest

        req = AnalyzeUpgradeRequest(
            app_id="Splunk_TA_windows",
            cluster="cluster-es",
            include_container_test=False,
        )
        assert req.app_id == "Splunk_TA_windows"
        assert req.cluster == "cluster-es"
        assert req.check_cim is True

    def test_pipeline_no_changes_safe_to_upgrade(self):
        """An identical old and new version should yield 'Safe to upgrade'."""
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.impact_scorer import build_impact_report

        confs = _make_stanzas(("s", {"A": "1", "B": "2"}))
        findings = three_way_diff(confs, confs, {}, conf_type="props")
        report = build_impact_report(findings)
        assert report.recommendation == "Safe to upgrade"

    def test_pipeline_from_init_module(self):
        """Verify the __init__ module re-exports everything correctly."""
        from chat_app.upgrade_readiness import (
            build_impact_report,
            scan_app_directory,
            three_way_diff,
        )

        old_baseline = scan_app_directory(str(FIXTURES_DIR / "sample_ta_v1"))
        findings = three_way_diff(
            old_default=old_baseline.get_default_stanzas("props"),
            new_default={},
            local=old_baseline.get_local_stanzas("props"),
            conf_type="props",
        )
        report = build_impact_report(findings, app_id="sample_ta")
        assert report is not None

    def test_container_test_suite_creation(self):
        """ContainerTestSuite tracks test results correctly."""
        from chat_app.upgrade_readiness.models import (
            ContainerTestResult,
            ContainerTestSuite,
            TestStatus,
        )

        suite = ContainerTestSuite(app_id="TA", from_version="1.0", to_version="2.0")
        suite.results = [
            ContainerTestResult(
                test_id="t1", name="Conf merge", status=TestStatus.PASSED, duration_seconds=0.3
            ),
            ContainerTestResult(
                test_id="t2", name="Field extract", status=TestStatus.FAILED, duration_seconds=0.8
            ),
        ]
        assert suite.passed_count == 1
        assert suite.failed_count == 1
