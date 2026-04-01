"""
Splunk Config Analyzer Helpers — IndexTimeExtractor and ReportGenerator.

Extracted from conf_index_time_analyzer.py to keep file sizes manageable.

All public names are re-exported from conf_index_time_analyzer for backward compat.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
import re
from dataclasses import asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _import_types():
    """Lazy import to avoid circular dependencies."""
    from chat_app.conf_index_time_analyzer import (
        CriblMapping,
        EVENT_BREAKING_KEYS,
        ENCODING_KEYS,
        INLINE_EVAL_KEY,
        METRICS_KEYS,
        SOURCETYPE_KEYS,
        STRUCTURED_DATA_KEYS,
        TIMESTAMP_KEYS,
        IndexTimeSetting,
        Priority,
        SourcetypeReport,
        TransformDetail,
        TransformType,
    )
    return (
        CriblMapping, EVENT_BREAKING_KEYS, ENCODING_KEYS, INLINE_EVAL_KEY,
        METRICS_KEYS, SOURCETYPE_KEYS, STRUCTURED_DATA_KEYS, TIMESTAMP_KEYS,
        IndexTimeSetting, Priority, SourcetypeReport, TransformDetail, TransformType,
    )


# ---------------------------------------------------------------------------
# 2. IndexTimeExtractor — extracts index-time settings per stanza
# ---------------------------------------------------------------------------

class IndexTimeExtractor:
    """Extract index-time settings from parsed props.conf and resolve transforms references."""

    # Pattern for SEDCMD-<name>, TRANSFORMS-<name>, and RULESET-<name>
    _SEDCMD_PATTERN = re.compile(r"^SEDCMD-(.+)$", re.IGNORECASE)
    _TRANSFORMS_PATTERN = re.compile(r"^TRANSFORMS-(.+)$", re.IGNORECASE)
    _RULESET_PATTERN = re.compile(r"^RULESET-(.+)$", re.IGNORECASE)

    def extract_from_props(
        self,
        props_data: Dict[str, Dict[str, Any]],
        source_file: str,
    ) -> Dict[str, List[Any]]:
        """Extract all index-time settings from parsed props.conf data.

        Args:
            props_data: Output of parse_conf_file_advanced for a props.conf.
            source_file: Path to the props.conf for provenance.

        Returns:
            Dict mapping stanza name to list of IndexTimeSetting.
        """
        (CriblMapping, EVENT_BREAKING_KEYS, ENCODING_KEYS, INLINE_EVAL_KEY,
         METRICS_KEYS, SOURCETYPE_KEYS, STRUCTURED_DATA_KEYS, TIMESTAMP_KEYS,
         IndexTimeSetting, Priority, SourcetypeReport, TransformDetail, TransformType) = _import_types()

        results: Dict[str, List[Any]] = {}

        for stanza_name, stanza_kv in props_data.items():
            settings: List[Any] = []

            for key, value in stanza_kv.items():
                if key.startswith("__"):  # Skip __lines__, __provenance__, etc.
                    continue

                category = self._classify_props_key(key)
                if category is not None:
                    settings.append(IndexTimeSetting(
                        key=key,
                        value=str(value),
                        category=category,
                        source_file=source_file,
                        stanza=stanza_name,
                    ))

            if settings:
                results[stanza_name] = settings

        return results

    def resolve_transforms(
        self,
        transform_names: List[str],
        transforms_data: Dict[str, Dict[str, Any]],
    ) -> List[Any]:
        """Look up transform stanzas and classify each one.

        Args:
            transform_names: List of stanza names referenced via TRANSFORMS-*.
            transforms_data: Parsed transforms.conf data.

        Returns:
            List of TransformDetail with classification.
        """
        (CriblMapping, EVENT_BREAKING_KEYS, ENCODING_KEYS, INLINE_EVAL_KEY,
         METRICS_KEYS, SOURCETYPE_KEYS, STRUCTURED_DATA_KEYS, TIMESTAMP_KEYS,
         IndexTimeSetting, Priority, SourcetypeReport, TransformDetail, TransformType) = _import_types()

        details: List[Any] = []

        for name in transform_names:
            stanza = transforms_data.get(name, {})
            if not stanza:
                details.append(TransformDetail(
                    transform_name=name,
                    stanza_name=name,
                    transform_type=TransformType.UNKNOWN,
                ))
                continue

            raw = {k: str(v) for k, v in stanza.items() if not k.startswith("__")}
            detail = TransformDetail(
                transform_name=name,
                stanza_name=name,
                regex=raw.get("REGEX"),
                format_str=raw.get("FORMAT"),
                dest_key=raw.get("DEST_KEY"),
                source_key=raw.get("SOURCE_KEY"),
                write_meta=raw.get("WRITE_META"),
                lookahead=raw.get("LOOKAHEAD"),
                transform_type=self._classify_transform(raw),
                stop_processing_if=raw.get("STOP_PROCESSING_IF"),
                raw_settings=raw,
            )
            details.append(detail)

        return details

    # -- private helpers --

    def _classify_props_key(self, key: str) -> Optional[str]:
        """Return the category string for an index-time key, or None if not index-time."""
        (CriblMapping, EVENT_BREAKING_KEYS, ENCODING_KEYS, INLINE_EVAL_KEY,
         METRICS_KEYS, SOURCETYPE_KEYS, STRUCTURED_DATA_KEYS, TIMESTAMP_KEYS,
         IndexTimeSetting, Priority, SourcetypeReport, TransformDetail, TransformType) = _import_types()

        upper = key.upper()

        if upper in EVENT_BREAKING_KEYS or key in EVENT_BREAKING_KEYS:
            return "event_breaking"
        if upper in TIMESTAMP_KEYS or key in TIMESTAMP_KEYS:
            return "timestamp"
        if upper in STRUCTURED_DATA_KEYS or key in STRUCTURED_DATA_KEYS:
            return "structured_data"
        if key in SOURCETYPE_KEYS:
            return "sourcetype"
        if upper in ENCODING_KEYS or key in ENCODING_KEYS:
            return "encoding"
        if upper in METRICS_KEYS or key in METRICS_KEYS:
            return "metrics"
        if key == "force_local_processing" or upper == "FORCE_LOCAL_PROCESSING":
            return "encoding"
        if upper == INLINE_EVAL_KEY or key == INLINE_EVAL_KEY:
            return "ingest_eval"
        if self._SEDCMD_PATTERN.match(key):
            return "sedcmd"
        if self._TRANSFORMS_PATTERN.match(key):
            return "transforms"
        if self._RULESET_PATTERN.match(key):
            return "transforms"

        return None

    @staticmethod
    def _classify_transform(raw: Dict[str, str]) -> Any:
        """Classify a transforms.conf stanza by its DEST_KEY and other settings."""
        from chat_app.conf_index_time_analyzer import TransformType

        dest_key = raw.get("DEST_KEY", "").strip()
        regex = raw.get("REGEX", "")
        format_str = raw.get("FORMAT", "")
        write_meta = raw.get("WRITE_META", "").lower()

        # Clone events
        if raw.get("CLONE_SOURCETYPE"):
            return TransformType.CLONE

        # Routing by index
        if dest_key == "_MetaData:Index" or (
            dest_key == "queue" and "indexQueue" in format_str
        ):
            return TransformType.INDEX_ROUTING

        # Event dropping
        if dest_key == "queue" and "nullQueue" in format_str:
            return TransformType.EVENT_DROPPING

        # Host override
        if dest_key in ("MetaData:Host", "_MetaData:Host"):
            return TransformType.HOST_OVERRIDE

        # Source override
        if dest_key in ("MetaData:Source", "_MetaData:Source"):
            return TransformType.SOURCE_OVERRIDE

        # Sourcetype override
        if dest_key in ("MetaData:Sourcetype", "_MetaData:Sourcetype"):
            return TransformType.SOURCETYPE_OVERRIDE

        # Timestamp override (DEST_KEY = _time)
        if dest_key == "_time":
            return TransformType.TIMESTAMP_OVERRIDE

        # TCP/Syslog routing via transforms (rare — usually configured in outputs.conf/inputs.conf)
        # Only appears in transforms.conf when using DEST_KEY to dynamically route events
        if dest_key in ("_TCP_ROUTING", "_SYSLOG_ROUTING"):
            return TransformType.ROUTING

        # Raw data modification (e.g., DEST_KEY = _raw)
        if dest_key == "_raw":
            return TransformType.RAW_MODIFICATION

        # Field extraction (has REGEX and FORMAT, writes to named fields or _meta)
        if regex and (format_str or write_meta == "true"):
            return TransformType.FIELD_EXTRACTION

        # Default: if it has a REGEX it is probably an extraction
        if regex:
            return TransformType.FIELD_EXTRACTION

        return TransformType.UNKNOWN


# ---------------------------------------------------------------------------
# 4. ReportGenerator — outputs structured report
# ---------------------------------------------------------------------------

class ReportGenerator:
    """Generate structured migration reports in JSON, CSV, or YAML format."""

    def generate(
        self,
        by_app: Dict[str, Any],
        apps_dir: str,
        output_format: str = "json",
    ) -> str:
        """Build the final report string.

        Args:
            by_app: Dict[app_name] -> Dict[sourcetype] -> SourcetypeReport.
            apps_dir: Original scan path (for metadata).
            output_format: "json", "csv", or "yaml".

        Returns:
            Formatted report string.
        """
        report = self._build_report_dict(by_app, apps_dir)

        if output_format == "json":
            return json.dumps(report, indent=2, default=str)
        elif output_format == "csv":
            return self._to_csv(report)
        elif output_format == "yaml":
            return self._to_yaml(report)
        else:
            return json.dumps(report, indent=2, default=str)

    def _build_report_dict(
        self,
        by_app: Dict[str, Any],
        apps_dir: str,
    ) -> Dict[str, Any]:
        """Assemble the full report dictionary."""
        from chat_app.conf_index_time_analyzer import IndexTimeSetting, Priority

        total_settings = 0
        critical_count = 0
        all_sourcetypes: set = set()
        function_counts: Dict[str, int] = {}

        by_app_section: Dict[str, Any] = {}
        by_sourcetype_section: Dict[str, Any] = {}

        for app_name, sourcetypes in sorted(by_app.items()):
            app_entry: Dict[str, Any] = {
                "app_path": os.path.join(apps_dir, app_name),
                "sourcetypes": {},
            }

            for st_name, st_report in sorted(sourcetypes.items()):
                all_sourcetypes.add(st_name)

                st_entry = self._sourcetype_to_dict(st_report)
                app_entry["sourcetypes"][st_name] = st_entry

                # Accumulate stats
                for mapping in st_report.cribl_pipeline:
                    total_settings += 1
                    if mapping.priority == Priority.CRITICAL:
                        critical_count += 1
                    fn = mapping.cribl_function
                    function_counts[fn] = function_counts.get(fn, 0) + 1

                # Build by_sourcetype cross-reference
                if st_name not in by_sourcetype_section:
                    by_sourcetype_section[st_name] = {
                        "apps": [],
                        "all_settings": [],
                        "cribl_pipeline": [],
                    }
                by_sourcetype_section[st_name]["apps"].append(app_name)
                by_sourcetype_section[st_name]["all_settings"].extend(
                    [{"key": s.key, "value": s.value, "category": s.category}
                     for settings_list in [
                         list(st_report.event_breaking.items()),
                         list(st_report.timestamp.items()),
                         list(st_report.sedcmds.items()),
                         list(st_report.structured_data.items()),
                         list(st_report.sourcetype_settings.items()),
                         list(st_report.encoding.items()),
                         list(st_report.metrics.items()),
                     ]
                     for s_key, s_val in settings_list
                     for s in [IndexTimeSetting(key=s_key, value=s_val, category="", source_file="", stanza=st_name)]
                     ]
                    + [{"key": "INGEST_EVAL", "value": v, "category": "ingest_eval"} for v in st_report.ingest_eval]
                )
                by_sourcetype_section[st_name]["cribl_pipeline"].extend(
                    [self._mapping_to_dict(m) for m in st_report.cribl_pipeline]
                )

            by_app_section[app_name] = app_entry

        # Count unique pipelines needed (one per sourcetype that has settings)
        pipelines_needed = len(all_sourcetypes)
        event_breakers_needed = function_counts.get("Event Breaker", 0)

        report = {
            "scan_summary": {
                "total_apps": len(by_app),
                "total_sourcetypes": len(all_sourcetypes),
                "total_index_time_settings": total_settings,
                "critical_settings": critical_count,
                "apps_scanned": sorted(by_app.keys()),
            },
            "by_app": by_app_section,
            "by_sourcetype": by_sourcetype_section,
            "cribl_summary": {
                "pipelines_needed": pipelines_needed,
                "event_breakers_needed": event_breakers_needed,
                "total_functions": total_settings,
                "by_function_type": dict(sorted(function_counts.items())),
            },
        }
        return report

    def _sourcetype_to_dict(self, st: Any) -> Dict[str, Any]:
        """Convert a SourcetypeReport to a serialisable dict."""
        result: Dict[str, Any] = {
            "event_breaking": st.event_breaking,
            "timestamp": st.timestamp,
            "transforms": [asdict(t) for t in st.transforms],
            "sedcmds": st.sedcmds,
            "ingest_eval": st.ingest_eval,
            "structured_data": st.structured_data,
            "sourcetype_settings": st.sourcetype_settings,
            "encoding": st.encoding,
            "metrics": st.metrics,
            "cribl_pipeline": [self._mapping_to_dict(m) for m in st.cribl_pipeline],
        }
        if st.stanza_type:
            result["stanza_type"] = st.stanza_type
        return result

    @staticmethod
    def _mapping_to_dict(m: Any) -> Dict[str, Any]:
        return {
            "splunk_setting": m.splunk_setting,
            "splunk_value": m.splunk_value,
            "cribl_function": m.cribl_function,
            "cribl_config": m.cribl_config,
            "priority": m.priority.value,
            "notes": m.notes,
        }

    def _to_csv(self, report: Dict[str, Any]) -> str:
        """Flatten the report into a CSV string (one row per setting)."""
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "app", "sourcetype", "splunk_setting", "splunk_value",
            "cribl_function", "priority", "notes",
        ])

        for app_name, app_data in report.get("by_app", {}).items():
            for st_name, st_data in app_data.get("sourcetypes", {}).items():
                for mapping in st_data.get("cribl_pipeline", []):
                    writer.writerow([
                        app_name,
                        st_name,
                        mapping["splunk_setting"],
                        mapping["splunk_value"],
                        mapping["cribl_function"],
                        mapping["priority"],
                        mapping["notes"],
                    ])

        return buf.getvalue()

    @staticmethod
    def _to_yaml(report: Dict[str, Any]) -> str:
        """Convert report to YAML. Falls back to JSON if PyYAML is not installed."""
        try:
            import yaml
            return yaml.dump(report, default_flow_style=False, sort_keys=False, allow_unicode=True)
        except ImportError:
            logger.warning("PyYAML not installed; falling back to JSON output.")
            return json.dumps(report, indent=2, default=str)
