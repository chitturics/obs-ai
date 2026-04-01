"""Comprehensive tests for the Cribl Migration Analyzer.

Tests cover all major components:
- ConfsScanner (directory scanning, app categorization)
- IndexTimeExtractor (setting extraction, transform resolution)
- CriblMigrationMapper (Splunk → Cribl function mapping)
- BtoolImporter (CSV parsing, 4-col and 6-col formats)
- Layer merge logic (default/local precedence)
- Regex tester (line_breaker, time_prefix, extraction modes)
- Integration (full pipeline: scan → extract → map → report)
- Pipeline YAML and migration checklist generators
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Any

import pytest

from chat_app.conf_index_time_analyzer import (
    BtoolImporter,
    ConfFile,
    ConfsScanner,
    CriblMapping,
    CriblMigrationMapper,
    IndexTimeExtractor,
    IndexTimeSetting,
    Priority,
    ReportGenerator,
    SourcetypeReport,
    TransformDetail,
    TransformType,
    _merge_conf_layers,
    _process_props_settings,
    generate_cribl_pipeline_yaml,
    generate_migration_checklist,
    run_analysis,
    validate_regex_pattern,
)

# Path to the checked-in fixture data
FIXTURES_DIR = Path(__file__).parent / "fixtures" / "sample_splunk_repo"


# ---------------------------------------------------------------------------
# Helpers — create temporary Splunk app trees
# ---------------------------------------------------------------------------

def _write_conf(root: Path, app: str, layer: str, conf_name: str, content: str) -> Path:
    """Write a conf file into a temp Splunk-style directory tree."""
    target = root / app / layer / conf_name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


# ======================================================================
# 1. ConfsScanner tests
# ======================================================================


class TestConfsScanner:
    """Tests for discovering and classifying Splunk conf files."""

    def test_scan_empty_directory(self, tmp_path: Path):
        scanner = ConfsScanner()
        results = scanner.scan(str(tmp_path))
        assert results == []

    def test_scan_nonexistent_directory(self, tmp_path: Path):
        scanner = ConfsScanner()
        results = scanner.scan(str(tmp_path / "does_not_exist"))
        assert results == []

    def test_scan_single_app_default_only(self, tmp_path: Path):
        _write_conf(tmp_path, "TA-myapp", "default", "props.conf", "[syslog]\nTIME_FORMAT=%b %d\n")
        scanner = ConfsScanner()
        results = scanner.scan(str(tmp_path))

        assert len(results) == 1
        assert results[0].app_name == "TA-myapp"
        assert results[0].conf_type == "props"
        assert results[0].layer == "default"

    def test_scan_single_app_default_and_local(self, tmp_path: Path):
        _write_conf(tmp_path, "TA-myapp", "default", "props.conf", "[syslog]\nTIME_FORMAT=%b %d\n")
        _write_conf(tmp_path, "TA-myapp", "local", "props.conf", "[syslog]\nTIME_FORMAT=%Y-%m-%d\n")
        scanner = ConfsScanner()
        results = scanner.scan(str(tmp_path))

        assert len(results) == 2
        layers = {r.layer for r in results}
        assert layers == {"default", "local"}

    def test_scan_multiple_apps(self, tmp_path: Path):
        _write_conf(tmp_path, "TA-windows", "default", "props.conf", "[WinEventLog]\nTIME_FORMAT=%Y\n")
        _write_conf(tmp_path, "SA-Utils", "default", "transforms.conf", "[my_lookup]\nfilename=test.csv\n")
        scanner = ConfsScanner()
        results = scanner.scan(str(tmp_path))

        apps = {r.app_name for r in results}
        assert apps == {"TA-windows", "SA-Utils"}

    def test_scan_finds_both_props_and_transforms(self, tmp_path: Path):
        _write_conf(tmp_path, "TA-test", "default", "props.conf", "[src]\nTIME_FORMAT=%Y\n")
        _write_conf(tmp_path, "TA-test", "default", "transforms.conf", "[my_xform]\nREGEX=.*\n")
        scanner = ConfsScanner()
        results = scanner.scan(str(tmp_path))

        conf_types = {r.conf_type for r in results}
        assert conf_types == {"props", "transforms"}

    def test_scan_fixture_directory(self):
        """Scan the checked-in fixtures directory."""
        if not FIXTURES_DIR.is_dir():
            pytest.skip("fixtures not present")
        scanner = ConfsScanner()
        results = scanner.scan(str(FIXTURES_DIR))

        apps = {r.app_name for r in results}
        assert "TA-windows" in apps
        assert "Splunk_TA_nix" in apps
        assert "SA-NetworkProtection" in apps

    def test_app_category_detection(self):
        assert ConfsScanner.get_app_type("TA-windows") == "addon"
        assert ConfsScanner.get_app_type("SA-Utils") == "framework"
        assert ConfsScanner.get_app_type("DA-ESS-ThreatIntelligence") == "domain"
        assert ConfsScanner.get_app_type("system") == "system"
        assert ConfsScanner.get_app_type("org-custom-app") == "custom"
        assert ConfsScanner.get_app_type("my_regular_app") == "app"

    def test_app_priority_ordering(self):
        p_system = ConfsScanner.get_app_priority("system")
        p_framework = ConfsScanner.get_app_priority("SA-Utils")
        p_addon = ConfsScanner.get_app_priority("TA-windows")
        p_domain = ConfsScanner.get_app_priority("DA-ESS-Whatever")
        p_app = ConfsScanner.get_app_priority("my_app")
        p_custom = ConfsScanner.get_app_priority("org-custom")

        assert p_system < p_framework < p_addon < p_domain < p_app < p_custom

    def test_scan_nested_repo_structure(self, tmp_path: Path):
        """Test scanning a repo with TAs/BAs directories."""
        _write_conf(tmp_path / "TAs", "TA-windows", "default", "props.conf", "[win]\nTIME_FORMAT=%Y\n")
        _write_conf(tmp_path / "BAs", "BA-reporting", "default", "props.conf", "[report]\nTIME_FORMAT=%Y\n")

        scanner = ConfsScanner()
        # Deep scan should find both
        results = scanner.scan(str(tmp_path))
        apps = {r.app_name for r in results}
        assert "TA-windows" in apps
        assert "BA-reporting" in apps

    def test_scan_app_is_root(self, tmp_path: Path):
        """When root_dir itself is an app directory."""
        (tmp_path / "default").mkdir()
        (tmp_path / "default" / "props.conf").write_text("[test]\nTIME_FORMAT=%Y\n")
        scanner = ConfsScanner()
        results = scanner.scan(str(tmp_path))
        assert len(results) == 1
        assert results[0].layer == "default"


# ======================================================================
# 2. IndexTimeExtractor tests
# ======================================================================


class TestIndexTimeExtractor:
    """Tests for extracting and classifying index-time settings."""

    def test_extract_line_breaker(self):
        extractor = IndexTimeExtractor()
        props = {"syslog": {"LINE_BREAKER": r"([\r\n]+)", "SHOULD_LINEMERGE": "false"}}
        result = extractor.extract_from_props(props, "test/props.conf")
        assert "syslog" in result
        categories = {s.category for s in result["syslog"]}
        assert "event_breaking" in categories

    def test_extract_transforms_reference(self):
        extractor = IndexTimeExtractor()
        props = {"test": {"TRANSFORMS-lookup": "my_transform,another_transform"}}
        result = extractor.extract_from_props(props, "test/props.conf")
        assert "test" in result
        assert result["test"][0].category == "transforms"
        assert result["test"][0].value == "my_transform,another_transform"

    def test_extract_sedcmd(self):
        extractor = IndexTimeExtractor()
        props = {"test": {"SEDCMD-strip": "s/password=\\S+/password=REDACTED/g"}}
        result = extractor.extract_from_props(props, "test/props.conf")
        assert result["test"][0].category == "sedcmd"

    def test_extract_ingest_eval(self):
        extractor = IndexTimeExtractor()
        props = {"test": {"INGEST_EVAL": 'index=if(sourcetype=="error","errors",index)'}}
        result = extractor.extract_from_props(props, "test/props.conf")
        assert result["test"][0].category == "ingest_eval"

    def test_skip_non_index_time_settings(self):
        extractor = IndexTimeExtractor()
        props = {"test": {
            "EXTRACT-ip": "(?<src_ip>\\d+\\.\\d+\\.\\d+\\.\\d+)",
            "REPORT-fields": "my_extraction",
            "LOOKUP-geo": "geo_lookup src_ip",
            "KV_MODE": "auto",
        }}
        result = extractor.extract_from_props(props, "test/props.conf")
        # None of these are index-time
        assert "test" not in result

    def test_skip_dunder_keys(self):
        extractor = IndexTimeExtractor()
        props = {"test": {"__lines__": 42, "__provenance__": {}, "TIME_FORMAT": "%Y"}}
        result = extractor.extract_from_props(props, "test/props.conf")
        assert len(result["test"]) == 1
        assert result["test"][0].key == "TIME_FORMAT"

    def test_classify_transform_event_dropping(self):
        raw = {"REGEX": "EventCode=4634", "DEST_KEY": "queue", "FORMAT": "nullQueue"}
        assert IndexTimeExtractor._classify_transform(raw) == TransformType.EVENT_DROPPING

    def test_classify_transform_field_extraction_write_meta(self):
        raw = {"REGEX": "src=(?<src>\\S+)", "FORMAT": "src::$1", "WRITE_META": "true"}
        assert IndexTimeExtractor._classify_transform(raw) == TransformType.FIELD_EXTRACTION

    def test_classify_transform_index_routing(self):
        raw = {"REGEX": "action=blocked", "DEST_KEY": "_MetaData:Index", "FORMAT": "security_blocked"}
        assert IndexTimeExtractor._classify_transform(raw) == TransformType.INDEX_ROUTING

    def test_classify_transform_host_override(self):
        raw = {"REGEX": "host=(?<h>\\S+)", "DEST_KEY": "MetaData:Host", "FORMAT": "host::$1"}
        assert IndexTimeExtractor._classify_transform(raw) == TransformType.HOST_OVERRIDE

    def test_classify_transform_clone(self):
        raw = {"REGEX": ".*", "CLONE_SOURCETYPE": "my_clone"}
        assert IndexTimeExtractor._classify_transform(raw) == TransformType.CLONE

    def test_classify_transform_routing(self):
        raw = {"REGEX": "protocol=tcp", "DEST_KEY": "_TCP_ROUTING", "FORMAT": "my_group"}
        assert IndexTimeExtractor._classify_transform(raw) == TransformType.ROUTING

    def test_classify_transform_raw_modification(self):
        raw = {"REGEX": "password=\\S+", "DEST_KEY": "_raw", "FORMAT": "password=REDACTED"}
        assert IndexTimeExtractor._classify_transform(raw) == TransformType.RAW_MODIFICATION

    def test_classify_transform_timestamp_override(self):
        raw = {"REGEX": "epoch=(?<time>\\d+)", "DEST_KEY": "_time", "FORMAT": "$1"}
        assert IndexTimeExtractor._classify_transform(raw) == TransformType.TIMESTAMP_OVERRIDE

    def test_resolve_transforms_unknown_stanza(self):
        extractor = IndexTimeExtractor()
        result = extractor.resolve_transforms(["nonexistent"], {})
        assert len(result) == 1
        assert result[0].transform_type == TransformType.UNKNOWN

    def test_resolve_transforms_with_data(self):
        extractor = IndexTimeExtractor()
        transforms_data = {
            "my_drop": {
                "REGEX": "noisy_event",
                "DEST_KEY": "queue",
                "FORMAT": "nullQueue",
            }
        }
        result = extractor.resolve_transforms(["my_drop"], transforms_data)
        assert len(result) == 1
        assert result[0].transform_type == TransformType.EVENT_DROPPING
        assert result[0].regex == "noisy_event"


# ======================================================================
# 3. CriblMigrationMapper tests
# ======================================================================


class TestCriblMigrationMapper:
    """Tests for mapping Splunk settings to Cribl equivalents."""

    def _make_setting(self, key: str, value: str, category: str) -> IndexTimeSetting:
        return IndexTimeSetting(key=key, value=value, category=category, source_file="test", stanza="test")

    def test_map_line_breaker_to_event_breaker(self):
        mapper = CriblMigrationMapper()
        s = self._make_setting("LINE_BREAKER", r"([\r\n]+)", "event_breaking")
        m = mapper.map_setting(s)
        assert m.cribl_function == "Event Breaker"
        assert m.cribl_config["type"] == "regex"
        assert m.priority == Priority.CRITICAL

    def test_map_time_format_to_auto_timestamp(self):
        mapper = CriblMigrationMapper()
        s = self._make_setting("TIME_FORMAT", "%Y-%m-%dT%H:%M:%S", "timestamp")
        m = mapper.map_setting(s)
        assert m.cribl_function == "Auto Timestamp"
        assert m.cribl_config["format"] == "%Y-%m-%dT%H:%M:%S"
        assert m.priority == Priority.CRITICAL

    def test_map_sedcmd_to_mask(self):
        mapper = CriblMigrationMapper()
        s = self._make_setting("SEDCMD-strip", "s/foo/bar/g", "sedcmd")
        m = mapper.map_setting(s)
        assert m.cribl_function == "Mask"
        assert m.cribl_config["expression"] == "s/foo/bar/g"

    def test_map_ingest_eval_to_eval(self):
        mapper = CriblMigrationMapper()
        s = self._make_setting("INGEST_EVAL", "index=if(x,y,z)", "ingest_eval")
        m = mapper.map_setting(s)
        assert m.cribl_function == "Eval"
        assert m.priority == Priority.HIGH

    def test_map_transform_event_dropping_to_drop(self):
        mapper = CriblMigrationMapper()
        td = TransformDetail(
            transform_name="my_null", stanza_name="my_null",
            regex="noisy", dest_key="queue", format_str="nullQueue",
            transform_type=TransformType.EVENT_DROPPING, raw_settings={},
        )
        m = mapper.map_transform(td)
        assert m.cribl_function == "Drop"
        assert m.priority == Priority.CRITICAL

    def test_map_transform_index_routing_to_route(self):
        mapper = CriblMigrationMapper()
        td = TransformDetail(
            transform_name="route_idx", stanza_name="route_idx",
            regex="action=blocked", dest_key="_MetaData:Index", format_str="security",
            transform_type=TransformType.INDEX_ROUTING, raw_settings={},
        )
        m = mapper.map_transform(td)
        assert m.cribl_function == "Route"
        assert m.priority == Priority.CRITICAL

    def test_map_transform_host_override_to_eval(self):
        mapper = CriblMigrationMapper()
        td = TransformDetail(
            transform_name="set_host", stanza_name="set_host",
            regex="host=(?P<h>\\S+)", dest_key="MetaData:Host",
            transform_type=TransformType.HOST_OVERRIDE, raw_settings={},
        )
        m = mapper.map_transform(td)
        assert m.cribl_function == "Eval"
        assert m.cribl_config["field"] == "host"

    def test_map_datetime_config_current(self):
        mapper = CriblMigrationMapper()
        s = self._make_setting("DATETIME_CONFIG", "CURRENT", "timestamp")
        m = mapper.map_setting(s)
        assert m.cribl_config["type"] == "current"

    def test_map_datetime_config_none(self):
        mapper = CriblMigrationMapper()
        s = self._make_setting("DATETIME_CONFIG", "NONE", "timestamp")
        m = mapper.map_setting(s)
        assert m.cribl_config["type"] == "none"

    def test_map_indexed_extractions_to_parser(self):
        mapper = CriblMigrationMapper()
        s = self._make_setting("INDEXED_EXTRACTIONS", "csv", "structured_data")
        m = mapper.map_setting(s)
        assert m.cribl_function == "Parser"
        assert m.cribl_config["format"] == "csv"

    def test_map_metrics_protocol(self):
        mapper = CriblMigrationMapper()
        s = self._make_setting("METRICS_PROTOCOL", "statsd", "metrics")
        m = mapper.map_setting(s)
        assert m.cribl_function == "Parser"
        assert m.cribl_config["protocol"] == "statsd"

    def test_map_sourcetype_rename(self):
        mapper = CriblMigrationMapper()
        s = self._make_setting("sourcetype", "pan:firewall", "sourcetype")
        m = mapper.map_setting(s)
        assert m.cribl_function == "Eval"
        assert m.cribl_config["field"] == "sourcetype"

    def test_map_stop_processing_if(self):
        mapper = CriblMigrationMapper()
        td = TransformDetail(
            transform_name="test", stanza_name="test",
            regex=".*", dest_key="queue", format_str="nullQueue",
            transform_type=TransformType.EVENT_DROPPING,
            stop_processing_if="true()",
            raw_settings={},
        )
        m = mapper.map_transform(td)
        assert "stop_processing_if" in m.cribl_config
        assert "STOP_PROCESSING_IF" in m.notes


# ======================================================================
# 4. BtoolImporter tests
# ======================================================================


class TestBtoolImporter:
    """Tests for importing btool CSV data."""

    def test_parse_four_column_csv(self):
        csv_data = (
            "/opt/splunk/etc/apps/TA-test/default/props.conf,syslog,TIME_FORMAT,%b %d %H:%M:%S\n"
            "/opt/splunk/etc/apps/TA-test/default/props.conf,syslog,LINE_BREAKER,(\\r\\n)\n"
        )
        importer = BtoolImporter()
        result = importer.import_from_csv(csv_data)
        assert "props" in result
        assert "syslog" in result["props"]
        assert result["props"]["syslog"]["TIME_FORMAT"] == "%b %d %H:%M:%S"
        assert result["props"]["syslog"]["LINE_BREAKER"] == "(\\r\\n)"

    def test_parse_six_column_csv_with_header(self):
        csv_data = (
            "confpath,stanza,property,value,app_name,layer\n"
            "/opt/splunk/etc/apps/TA-windows/default/props.conf,WinEventLog:Security,TIME_FORMAT,%Y-%m-%d,TA-windows,default\n"
            "/opt/splunk/etc/apps/Splunk_TA_nix/default/props.conf,syslog,TIME_FORMAT,%b %d,Splunk_TA_nix,default\n"
        )
        importer = BtoolImporter()
        result = importer.import_from_csv(csv_data)
        assert result["props"]["WinEventLog:Security"]["TIME_FORMAT"] == "%Y-%m-%d"
        assert result["props"]["syslog"]["TIME_FORMAT"] == "%b %d"

        # Check that app names were captured
        conf_files = importer.to_conf_files(result)
        app_names = {cf.app_name for cf in conf_files}
        assert "TA-windows" in app_names
        assert "Splunk_TA_nix" in app_names
        assert "btool_merged" not in app_names

    def test_parse_six_column_csv_no_header(self):
        csv_data = (
            "/opt/splunk/etc/apps/TA-test/default/props.conf,src,TIME_FORMAT,%Y,TA-test,default\n"
            "/opt/splunk/etc/apps/TA-test/default/props.conf,src,LINE_BREAKER,(\\n),TA-test,default\n"
        )
        importer = BtoolImporter()
        result = importer.import_from_csv(csv_data)
        assert result["props"]["src"]["TIME_FORMAT"] == "%Y"
        conf_files = importer.to_conf_files(result)
        assert any(cf.app_name == "TA-test" for cf in conf_files)

    def test_handle_empty_csv(self):
        importer = BtoolImporter()
        result = importer.import_from_csv("")
        assert result == {}

    def test_handle_malformed_rows(self):
        csv_data = (
            "only,two\n"
            "also,just,three\n"
            "/opt/splunk/etc/apps/TA-ok/default/props.conf,syslog,TZ,UTC\n"
        )
        importer = BtoolImporter()
        result = importer.import_from_csv(csv_data)
        assert result["props"]["syslog"]["TZ"] == "UTC"

    def test_handle_csv_with_header_row(self):
        csv_data = (
            "confpath,stanza,property,value\n"
            "/opt/splunk/etc/apps/TA-x/default/props.conf,test,TIME_FORMAT,%Y\n"
        )
        importer = BtoolImporter()
        result = importer.import_from_csv(csv_data)
        assert "props" in result
        assert result["props"]["test"]["TIME_FORMAT"] == "%Y"

    def test_to_conf_files_default_app_name(self):
        """Without app_name column, uses btool_merged."""
        csv_data = "/opt/splunk/etc/apps/TA-x/default/props.conf,test,TIME_FORMAT,%Y\n"
        importer = BtoolImporter()
        result = importer.import_from_csv(csv_data)
        conf_files = importer.to_conf_files(result)
        assert all(cf.app_name == "btool_merged" for cf in conf_files)

    def test_skips_non_props_transforms(self):
        csv_data = (
            "/opt/splunk/etc/apps/TA-x/default/inputs.conf,monitor,disabled,0\n"
            "/opt/splunk/etc/apps/TA-x/default/props.conf,test,TZ,UTC\n"
        )
        importer = BtoolImporter()
        result = importer.import_from_csv(csv_data)
        assert "inputs" not in result
        assert "props" in result


# ======================================================================
# 5. Layer merge tests
# ======================================================================


class TestLayerMerge:
    """Tests for Splunk conf layer merging (default/local precedence)."""

    def test_default_only(self, tmp_path: Path):
        _write_conf(tmp_path, "TA-test", "default", "props.conf", "[syslog]\nTIME_FORMAT = %b %d\nTZ = UTC\n")
        cf = ConfFile(
            app_name="TA-test", app_path=str(tmp_path / "TA-test"),
            conf_type="props", layer="default",
            file_path=str(tmp_path / "TA-test" / "default" / "props.conf"),
        )
        merged = _merge_conf_layers([cf])
        assert merged["syslog"]["TIME_FORMAT"] == "%b %d"
        assert merged["syslog"]["TZ"] == "UTC"

    def test_local_only(self, tmp_path: Path):
        _write_conf(tmp_path, "TA-test", "local", "props.conf", "[syslog]\nTIME_FORMAT = %Y-%m-%d\n")
        cf = ConfFile(
            app_name="TA-test", app_path=str(tmp_path / "TA-test"),
            conf_type="props", layer="local",
            file_path=str(tmp_path / "TA-test" / "local" / "props.conf"),
        )
        merged = _merge_conf_layers([cf])
        assert merged["syslog"]["TIME_FORMAT"] == "%Y-%m-%d"

    def test_local_overrides_default_at_key_level(self, tmp_path: Path):
        _write_conf(tmp_path, "TA-test", "default", "props.conf",
                     "[syslog]\nTIME_FORMAT = %b %d\nTZ = UTC\nSHOULD_LINEMERGE = true\n")
        _write_conf(tmp_path, "TA-test", "local", "props.conf",
                     "[syslog]\nTIME_FORMAT = %Y-%m-%d\n")

        default_cf = ConfFile(
            app_name="TA-test", app_path=str(tmp_path / "TA-test"),
            conf_type="props", layer="default",
            file_path=str(tmp_path / "TA-test" / "default" / "props.conf"),
        )
        local_cf = ConfFile(
            app_name="TA-test", app_path=str(tmp_path / "TA-test"),
            conf_type="props", layer="local",
            file_path=str(tmp_path / "TA-test" / "local" / "props.conf"),
        )

        merged = _merge_conf_layers([default_cf, local_cf])
        # Local overrides TIME_FORMAT
        assert merged["syslog"]["TIME_FORMAT"] == "%Y-%m-%d"
        # Default TZ preserved
        assert merged["syslog"]["TZ"] == "UTC"
        # Default SHOULD_LINEMERGE preserved
        assert merged["syslog"]["SHOULD_LINEMERGE"] == "true"

    def test_multiple_apps_correct_precedence(self, tmp_path: Path):
        # SA-framework has lower priority than TA-addon
        _write_conf(tmp_path, "SA-base", "default", "props.conf",
                     "[syslog]\nTIME_FORMAT = %b %d\nTZ = UTC\n")
        _write_conf(tmp_path, "TA-override", "default", "props.conf",
                     "[syslog]\nTIME_FORMAT = %Y-%m-%d\n")

        sa_cf = ConfFile(
            app_name="SA-base", app_path=str(tmp_path / "SA-base"),
            conf_type="props", layer="default",
            file_path=str(tmp_path / "SA-base" / "default" / "props.conf"),
        )
        ta_cf = ConfFile(
            app_name="TA-override", app_path=str(tmp_path / "TA-override"),
            conf_type="props", layer="default",
            file_path=str(tmp_path / "TA-override" / "default" / "props.conf"),
        )

        merged = _merge_conf_layers([sa_cf, ta_cf])
        # TA has higher priority
        assert merged["syslog"]["TIME_FORMAT"] == "%Y-%m-%d"
        # SA-base TZ preserved (not overridden)
        assert merged["syslog"]["TZ"] == "UTC"


# ======================================================================
# 6. Regex tester tests
# ======================================================================


class TestRegexTester:
    """Tests for the migration regex validation tool."""

    def test_line_breaker_split_by_newlines(self):
        sample = "event1\nevent2\nevent3"
        result = validate_regex_pattern(r"([\r\n]+)", sample, mode="line_breaker")
        assert result["ok"] is True
        assert result["event_count"] >= 2

    def test_line_breaker_custom_pattern(self):
        sample = "event1---BREAK---event2---BREAK---event3"
        result = validate_regex_pattern(r"(---BREAK---)", sample, mode="line_breaker")
        assert result["ok"] is True
        assert result["event_count"] >= 2

    def test_time_prefix_finds_timestamp(self):
        sample = "some prefix 2024-01-15T10:30:00 rest of event"
        result = validate_regex_pattern(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", sample, mode="time_prefix")
        assert result["ok"] is True
        assert result["matches"] >= 1
        assert result["match"] == "2024-01-15T10:30:00"
        assert ">>" in result["highlighted"]

    def test_time_prefix_no_match(self):
        sample = "no timestamp here"
        result = validate_regex_pattern(r"\d{4}-\d{2}-\d{2}", sample, mode="time_prefix")
        assert result["ok"] is True
        assert result["matches"] == 0

    def test_time_prefix_multiple_lines(self):
        sample = "2024-01-15 event1\n2024-01-16 event2\n2024-01-17 event3"
        result = validate_regex_pattern(r"\d{4}-\d{2}-\d{2}", sample, mode="time_prefix")
        assert result["ok"] is True
        assert result["matches"] == 3
        assert len(result["line_matches"]) == 3

    def test_extraction_named_groups(self):
        sample = "src=10.0.0.1 dst=10.0.0.2 port=443"
        result = validate_regex_pattern(
            r"src=(?P<src>\S+)\s+dst=(?P<dst>\S+)\s+port=(?P<port>\d+)",
            sample,
            mode="extraction",
        )
        assert result["ok"] is True
        assert result["matches"] == 1
        assert result["extractions"][0]["named_groups"]["src"] == "10.0.0.1"
        assert result["extractions"][0]["named_groups"]["dst"] == "10.0.0.2"
        assert result["extractions"][0]["named_groups"]["port"] == "443"

    def test_extraction_multiple_matches(self):
        sample = "ip=10.0.0.1 ip=10.0.0.2 ip=10.0.0.3"
        result = validate_regex_pattern(r"ip=(\d+\.\d+\.\d+\.\d+)", sample, mode="extraction")
        assert result["matches"] == 3

    def test_invalid_regex(self):
        result = validate_regex_pattern("[invalid(", "test", mode="line_breaker")
        assert result["ok"] is False
        assert "error" in result

    def test_unknown_mode(self):
        result = validate_regex_pattern(".*", "test", mode="bogus_mode")
        assert result["ok"] is False


# ======================================================================
# 7. Integration tests
# ======================================================================


class TestIntegration:
    """End-to-end tests combining multiple components."""

    def test_full_pipeline_scan_extract_map_report(self, tmp_path: Path):
        """Full pipeline: scan → extract → map → report."""
        _write_conf(tmp_path, "TA-test", "default", "props.conf",
                     "[mysource]\nLINE_BREAKER = ([\\r\\n]+)\nSHOULD_LINEMERGE = false\n"
                     "TIME_FORMAT = %Y-%m-%d\n")

        report_str = run_analysis(str(tmp_path), "json")
        report = json.loads(report_str)

        assert "scan_summary" in report
        assert "by_app" in report
        assert "by_sourcetype" in report
        assert "cribl_summary" in report
        assert report["scan_summary"]["total_apps"] >= 1
        assert report["scan_summary"]["total_sourcetypes"] >= 1

    def test_btool_csv_full_analysis(self):
        """btool CSV → full analysis."""
        csv_data = (
            "/opt/splunk/etc/apps/TA-x/default/props.conf,web_access,LINE_BREAKER,(\\n)\n"
            "/opt/splunk/etc/apps/TA-x/default/props.conf,web_access,TIME_FORMAT,%d/%b/%Y:%H:%M:%S\n"
            "/opt/splunk/etc/apps/TA-x/default/props.conf,web_access,SHOULD_LINEMERGE,false\n"
        )
        report_str = run_analysis(btool_csv=csv_data, output_format="json")
        report = json.loads(report_str)

        assert report["scan_summary"]["total_sourcetypes"] >= 1
        assert "web_access" in report["by_sourcetype"]
        assert report["cribl_summary"]["total_functions"] >= 2

    def test_report_has_required_sections(self, tmp_path: Path):
        _write_conf(tmp_path, "TA-test", "default", "props.conf",
                     "[src1]\nLINE_BREAKER=(\\n)\nTIME_FORMAT=%Y\n")
        report_str = run_analysis(str(tmp_path), "json")
        report = json.loads(report_str)

        assert "scan_summary" in report
        assert "by_app" in report
        assert "by_sourcetype" in report
        assert "cribl_summary" in report

    def test_csv_output_format(self, tmp_path: Path):
        _write_conf(tmp_path, "TA-test", "default", "props.conf",
                     "[src1]\nLINE_BREAKER=(\\n)\n")
        report_str = run_analysis(str(tmp_path), "csv")
        assert "app" in report_str.split("\n")[0].lower()
        assert "TA-test" in report_str

    def test_empty_scan_returns_valid_json(self, tmp_path: Path):
        report_str = run_analysis(str(tmp_path), "json")
        report = json.loads(report_str)
        assert report["scan_summary"]["total_apps"] == 0

    def test_fixture_scan(self):
        """Scan the checked-in fixture directory end-to-end."""
        if not FIXTURES_DIR.is_dir():
            pytest.skip("fixtures not present")
        report_str = run_analysis(str(FIXTURES_DIR), "json")
        report = json.loads(report_str)

        assert report["scan_summary"]["total_apps"] >= 3
        assert report["scan_summary"]["total_sourcetypes"] >= 5
        assert report["cribl_summary"]["total_functions"] > 0

        # Verify specific sourcetypes appear
        all_st = set(report["by_sourcetype"].keys())
        assert "WinEventLog:Security" in all_st
        assert "syslog" in all_st
        assert "firewall" in all_st


# ======================================================================
# 8. Pipeline YAML & Checklist tests
# ======================================================================


class TestPipelineYAML:
    """Tests for Cribl pipeline YAML generation."""

    def _make_report(self) -> Dict[str, Dict[str, SourcetypeReport]]:
        st = SourcetypeReport(sourcetype="test_src", app_name="TA-test")
        st.event_breaking = {"LINE_BREAKER": r"([\r\n]+)", "SHOULD_LINEMERGE": "false"}
        st.timestamp = {"TIME_FORMAT": "%Y-%m-%d", "TIME_PREFIX": "ts="}
        st.sedcmds = {"SEDCMD-mask": "s/password=\\S+/password=XXX/g"}
        st.ingest_eval = ["index=if(x,y,z)"]
        return {"TA-test": {"test_src": st}}

    def test_generate_pipeline_yaml_basic(self):
        by_app = self._make_report()
        yaml_str = generate_cribl_pipeline_yaml(by_app)
        assert "id: test_src" in yaml_str
        assert "event_breaker" in yaml_str
        assert "auto_timestamp" in yaml_str
        assert "LINE_BREAKER" in yaml_str
        assert "TIME_FORMAT" in yaml_str

    def test_pipeline_yaml_contains_sed(self):
        by_app = self._make_report()
        yaml_str = generate_cribl_pipeline_yaml(by_app)
        assert "regex_replace" in yaml_str
        assert "SEDCMD-mask" in yaml_str

    def test_pipeline_yaml_contains_eval(self):
        by_app = self._make_report()
        yaml_str = generate_cribl_pipeline_yaml(by_app)
        assert "INGEST_EVAL" in yaml_str

    def test_pipeline_yaml_with_transforms(self):
        st = SourcetypeReport(sourcetype="fw", app_name="SA-test")
        st.transforms = [
            TransformDetail(
                transform_name="drop_noise", stanza_name="drop_noise",
                regex="heartbeat", dest_key="queue", format_str="nullQueue",
                transform_type=TransformType.EVENT_DROPPING, raw_settings={},
            ),
            TransformDetail(
                transform_name="route_idx", stanza_name="route_idx",
                regex="action=blocked", dest_key="_MetaData:Index", format_str="security",
                transform_type=TransformType.INDEX_ROUTING, raw_settings={},
            ),
        ]
        by_app = {"SA-test": {"fw": st}}
        yaml_str = generate_cribl_pipeline_yaml(by_app)
        assert "drop_" in yaml_str
        assert "route_" in yaml_str
        assert "nullQueue" in yaml_str

    def test_pipeline_yaml_skips_default_stanza(self):
        st = SourcetypeReport(sourcetype="default", app_name="TA-test")
        st.event_breaking = {"LINE_BREAKER": r"([\r\n]+)"}
        by_app = {"TA-test": {"default": st}}
        yaml_str = generate_cribl_pipeline_yaml(by_app)
        assert yaml_str == ""


class TestMigrationChecklist:
    """Tests for migration checklist generation."""

    def _make_report(self) -> Dict[str, Dict[str, SourcetypeReport]]:
        st1 = SourcetypeReport(sourcetype="WinEventLog:Security", app_name="TA-windows")
        st1.event_breaking = {"LINE_BREAKER": r"([\r\n]+)(?=<Event)", "SHOULD_LINEMERGE": "false"}
        st1.timestamp = {"TIME_FORMAT": "%Y-%m-%d"}
        st1.sedcmds = {"SEDCMD-clean": "s/foo/bar/g"}
        st1.ingest_eval = ["index=if(x,y,z)"]
        st1.transforms = [
            TransformDetail(
                transform_name="drop_noise", stanza_name="drop_noise",
                regex="noisy", dest_key="queue", format_str="nullQueue",
                transform_type=TransformType.EVENT_DROPPING, raw_settings={},
            ),
        ]

        st2 = SourcetypeReport(sourcetype="syslog", app_name="Splunk_TA_nix")
        st2.event_breaking = {"SHOULD_LINEMERGE": "true", "BREAK_ONLY_BEFORE_DATE": "true"}
        st2.encoding = {"NO_BINARY_CHECK": "true"}

        return {
            "TA-windows": {"WinEventLog:Security": st1},
            "Splunk_TA_nix": {"syslog": st2},
        }

    def test_checklist_has_markdown_structure(self):
        by_app = self._make_report()
        md = generate_migration_checklist(by_app)
        assert "# Cribl Migration Checklist" in md
        assert "## Critical" in md
        assert "- [ ]" in md

    def test_checklist_contains_sourcetypes(self):
        by_app = self._make_report()
        md = generate_migration_checklist(by_app)
        assert "WinEventLog:Security" in md
        assert "syslog" in md

    def test_checklist_groups_by_priority(self):
        by_app = self._make_report()
        md = generate_migration_checklist(by_app)
        # Critical should appear before High Priority
        crit_pos = md.index("Critical")
        high_pos = md.index("High Priority")
        assert crit_pos < high_pos

    def test_checklist_includes_event_breaking_category(self):
        by_app = self._make_report()
        md = generate_migration_checklist(by_app)
        assert "Event Breakers" in md

    def test_checklist_includes_transforms(self):
        by_app = self._make_report()
        md = generate_migration_checklist(by_app)
        assert "Event Dropping" in md
        assert "nullQueue" in md

    def test_checklist_shows_item_count(self):
        by_app = self._make_report()
        md = generate_migration_checklist(by_app)
        assert "Total items:" in md

    def test_checklist_empty_report(self):
        md = generate_migration_checklist({})
        assert "# Cribl Migration Checklist" in md
        assert "Total items: 0" in md
