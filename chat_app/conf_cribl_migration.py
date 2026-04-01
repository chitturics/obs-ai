"""
Cribl Migration Tools — Scanner, Comparator, Pipeline Generator.

Extracted from conf_index_time_analyzer.py. Contains:
- CriblMigrationMapper: maps Splunk settings to Cribl equivalents
- CriblScanner: scans Cribl repos for pipeline configurations
- SplunkCriblComparator: compares Splunk settings with Cribl pipelines
- BtoolImporter: imports from btool CSV output
- generate_cribl_pipeline_yaml: generates Cribl pipeline YAML
- generate_migration_checklist: produces migration checklist
- main: CLI entry point
- validate_regex_pattern: tests regex patterns for event breaking
"""

from __future__ import annotations

import logging
from typing import Any, Dict

# CriblScanner, SplunkCriblComparator, and BtoolImporter extracted to keep file under 600 lines
from chat_app.conf_cribl_migration_comparator import (  # noqa: F401
    BtoolImporter,
    CriblScanner,
    SplunkCriblComparator,
)

from chat_app.conf_index_time_analyzer import (
    CriblMapping,
    IndexTimeSetting,
    Priority,
    TransformDetail,
    TransformType,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 3. CriblMigrationMapper — maps settings to Cribl equivalents
# ---------------------------------------------------------------------------

class CriblMigrationMapper:
    """Map each Splunk index-time setting to its Cribl Stream equivalent."""

    def map_setting(self, setting: IndexTimeSetting) -> CriblMapping:
        """Produce a CriblMapping for a single IndexTimeSetting."""
        handler = self._CATEGORY_HANDLERS.get(setting.category, self._map_generic)
        return handler(self, setting)

    def map_transform(self, detail: TransformDetail) -> CriblMapping:
        """Produce a CriblMapping for a resolved transform."""
        handler = self._TRANSFORM_TYPE_HANDLERS.get(detail.transform_type, self._map_transform_generic)
        mapping = handler(self, detail)
        # Annotate when STOP_PROCESSING_IF is present
        if detail.stop_processing_if:
            mapping.cribl_config["stop_processing_if"] = detail.stop_processing_if
            mapping.notes += (
                f" STOP_PROCESSING_IF={detail.stop_processing_if} — in Cribl, use a "
                "Drop or Route function with the filter condition to stop processing matching events."
            )
        return mapping

    # -- event breaking --

    def _map_event_breaking(self, s: IndexTimeSetting) -> CriblMapping:
        key_upper = s.key.upper()
        config: Dict[str, Any] = {}
        notes = ""

        if key_upper == "LINE_BREAKER":
            config = {"type": "regex", "regex": s.value}
            notes = "Map LINE_BREAKER regex to Cribl Event Breaker regex rule. Test thoroughly — Splunk uses the capturing group boundary."
        elif key_upper == "SHOULD_LINEMERGE":
            config = {"enabled": s.value.lower() not in ("false", "0", "no")}
            notes = "When false, disables line merging. In Cribl, configure the Event Breaker to not merge."
        elif key_upper == "TRUNCATE":
            config = {"maxEventBytes": int(s.value) if s.value.isdigit() else s.value}
            notes = "Set max event size in Cribl Event Breaker or pipeline Eval."
        elif key_upper == "LINE_BREAKER_LOOKBEHIND":
            config = {"lookbehind": int(s.value) if s.value.isdigit() else s.value}
            notes = "Lookbehind bytes for LINE_BREAKER regex. Note in Cribl Event Breaker config — no direct equivalent but affects regex matching window."
        elif key_upper == "EVENT_BREAKER_ENABLE":
            config = {"enabled": s.value.lower() not in ("false", "0", "no")}
            notes = "Enables UF event breaking. In Cribl, Event Breaker is configured per source."
        elif key_upper == "EVENT_BREAKER":
            config = {"type": "regex", "regex": s.value}
            notes = "UF-only event breaker regex. In Cribl, map to Event Breaker regex rule (note: this is UF-specific, not HWF/indexer)."
        else:
            config = {"setting": s.key, "value": s.value}
            notes = f"Translate {s.key} into Event Breaker configuration."

        return CriblMapping(
            splunk_setting=s.key,
            splunk_value=s.value,
            cribl_function="Event Breaker",
            cribl_config=config,
            priority=Priority.CRITICAL,
            notes=notes,
        )

    # -- timestamp --

    def _map_timestamp(self, s: IndexTimeSetting) -> CriblMapping:
        key_upper = s.key.upper()
        config: Dict[str, Any] = {}
        notes = ""

        if key_upper == "TIME_FORMAT":
            config = {"type": "strptime", "format": s.value}
            notes = "Map TIME_FORMAT to Cribl Auto Timestamp strptime format. Verify %Z/%z timezone tokens."
        elif key_upper == "TIME_PREFIX":
            config = {"prefix": s.value}
            notes = "Regex prefix before the timestamp. Use in Auto Timestamp's prefix field."
        elif key_upper == "MAX_TIMESTAMP_LOOKAHEAD":
            config = {"maxLength": int(s.value) if s.value.isdigit() else s.value}
            notes = "Limits how far into the event Cribl looks for a timestamp."
        elif key_upper == "DATETIME_CONFIG":
            if s.value.upper() == "CURRENT":
                config = {"type": "current"}
                notes = "Use current time as event time. In Cribl, use an Eval to set _time = Date.now()/1000."
            elif s.value.upper() == "NONE":
                config = {"type": "none"}
                notes = "No timestamp extraction. Skip Auto Timestamp in Cribl pipeline."
            else:
                config = {"type": "custom", "config": s.value}
                notes = "Custom datetime.xml reference. Review and translate manually."
        elif key_upper == "TZ":
            config = {"timezone": s.value}
            notes = "Set timezone in Cribl Auto Timestamp function."
        elif key_upper == "TZ_ALIAS":
            config = {"tz_alias": s.value}
            notes = "Timezone alias mapping. In Cribl, use an Eval function to map timezone abbreviations before timestamp parsing."
        elif key_upper == "TIMESTAMP_FIELDS":
            config = {"fields": s.value}
            notes = "Specifies fields containing timestamps. In Cribl, configure Auto Timestamp field setting to extract from named fields."
        else:
            config = {"setting": s.key, "value": s.value}
            notes = f"Translate {s.key} into Auto Timestamp configuration."

        return CriblMapping(
            splunk_setting=s.key,
            splunk_value=s.value,
            cribl_function="Auto Timestamp",
            cribl_config=config,
            priority=Priority.CRITICAL,
            notes=notes,
        )

    # -- sedcmd --

    def _map_sedcmd(self, s: IndexTimeSetting) -> CriblMapping:
        return CriblMapping(
            splunk_setting=s.key,
            splunk_value=s.value,
            cribl_function="Mask",
            cribl_config={
                "type": "sed",
                "expression": s.value,
            },
            priority=Priority.HIGH,
            notes=(
                "SEDCMD modifies raw data at index time. Use Cribl Mask (Regex Replace) or "
                "Eval with C.Text.replace(). Test the sed expression — Splunk's sed syntax has quirks."
            ),
        )

    # -- transforms reference --

    def _map_transforms_ref(self, s: IndexTimeSetting) -> CriblMapping:
        return CriblMapping(
            splunk_setting=s.key,
            splunk_value=s.value,
            cribl_function="Pipeline Reference",
            cribl_config={
                "transforms_stanza": s.value,
                "note": "Resolve via transforms.conf — see transforms detail.",
            },
            priority=Priority.HIGH,
            notes="Look up the referenced transforms.conf stanza for the actual Cribl function needed.",
        )

    # -- ingest_eval --

    def _map_ingest_eval(self, s: IndexTimeSetting) -> CriblMapping:
        return CriblMapping(
            splunk_setting=s.key,
            splunk_value=s.value,
            cribl_function="Eval",
            cribl_config={
                "expression": s.value,
            },
            priority=Priority.HIGH,
            notes=(
                "INGEST_EVAL runs SPL eval expressions at index time. Translate each "
                "expression to a Cribl Eval function. Watch for SPL-specific functions "
                "(e.g., if/case/replace/substr) — use JavaScript equivalents in Cribl."
            ),
        )

    # -- structured data --

    def _map_structured_data(self, s: IndexTimeSetting) -> CriblMapping:
        key_upper = s.key.upper()
        config: Dict[str, Any] = {}

        if key_upper == "INDEXED_EXTRACTIONS":
            config = {"format": s.value}
        elif key_upper == "FIELD_DELIMITER":
            config = {"delimiter": s.value}
        elif key_upper == "FIELD_NAMES":
            config = {"fields": s.value}
        else:
            config = {"setting": s.key, "value": s.value}

        return CriblMapping(
            splunk_setting=s.key,
            splunk_value=s.value,
            cribl_function="Parser",
            cribl_config=config,
            priority=Priority.MEDIUM,
            notes=(
                "Structured data extraction (CSV/JSON/TSV). In Cribl, use a Parser function "
                "matching the format. For JSON, Cribl auto-parses; for CSV/TSV, configure "
                "delimiter and field names."
            ),
        )

    # -- sourcetype --

    def _map_sourcetype(self, s: IndexTimeSetting) -> CriblMapping:
        return CriblMapping(
            splunk_setting=s.key,
            splunk_value=s.value,
            cribl_function="Eval",
            cribl_config={
                "field": "sourcetype",
                "expression": f"'{s.value}'",
            },
            priority=Priority.MEDIUM,
            notes="Sourcetype rename/override. Use a Cribl Eval to set the sourcetype field.",
        )

    # -- encoding --

    def _map_encoding(self, s: IndexTimeSetting) -> CriblMapping:
        key_upper = s.key.upper()
        config: Dict[str, Any] = {}
        notes = ""

        if key_upper == "CHARSET":
            config = {"encoding": s.value}
            notes = "Character encoding. In Cribl, configure encoding in the Parser function or Source settings."
        elif key_upper == "NO_BINARY_CHECK":
            config = {"noBinaryCheck": s.value.lower() not in ("false", "0", "no")}
            notes = "Disables binary file detection. In Cribl, no direct equivalent — binary data handling is automatic."
        else:
            config = {"setting": s.key, "value": s.value}
            notes = f"Encoding-related setting '{s.key}'. Review for Cribl Source or Parser config."

        return CriblMapping(
            splunk_setting=s.key,
            splunk_value=s.value,
            cribl_function="Parser",
            cribl_config=config,
            priority=Priority.MEDIUM,
            notes=notes,
        )

    # -- metrics --

    def _map_metrics(self, s: IndexTimeSetting) -> CriblMapping:
        key_upper = s.key.upper()
        config: Dict[str, Any] = {}
        notes = ""

        if key_upper == "METRICS_PROTOCOL":
            config = {"protocol": s.value}
            notes = "Metrics protocol (statsd/collectd). In Cribl, use a StatsD or Collectd parser as appropriate."
        elif key_upper == "STATSD-DIM-TRANSFORMS":
            config = {"transforms": s.value}
            notes = "StatsD dimension transforms. In Cribl, configure dimension extraction in the StatsD parser."
        else:
            config = {"setting": s.key, "value": s.value}
            notes = f"Metrics setting '{s.key}'. Map to Cribl metrics parser config."

        return CriblMapping(
            splunk_setting=s.key,
            splunk_value=s.value,
            cribl_function="Parser",
            cribl_config=config,
            priority=Priority.MEDIUM,
            notes=notes,
        )

    # -- generic fallback --

    def _map_generic(self, s: IndexTimeSetting) -> CriblMapping:
        return CriblMapping(
            splunk_setting=s.key,
            splunk_value=s.value,
            cribl_function="Eval",
            cribl_config={"setting": s.key, "value": s.value},
            priority=Priority.LOW,
            notes=f"Unrecognized index-time setting '{s.key}'. Review manually.",
        )

    # -- transform type handlers --

    def _map_transform_field_extraction(self, t: TransformDetail) -> CriblMapping:
        return CriblMapping(
            splunk_setting=f"TRANSFORMS ({t.transform_name})",
            splunk_value=t.regex or "",
            cribl_function="Eval",
            cribl_config={
                "regex": t.regex,
                "format": t.format_str,
                "write_meta": t.write_meta,
            },
            priority=Priority.HIGH if t.write_meta and t.write_meta.lower() == "true" else Priority.LOW,
            notes=(
                "Field extraction transform. If WRITE_META=true, this writes indexed fields — "
                "use Cribl Eval with regex capture groups. If WRITE_META is absent/false, this "
                "is search-time only and can be skipped for Cribl migration."
            ),
        )

    def _map_transform_index_routing(self, t: TransformDetail) -> CriblMapping:
        return CriblMapping(
            splunk_setting=f"TRANSFORMS ({t.transform_name})",
            splunk_value=t.regex or "",
            cribl_function="Route",
            cribl_config={
                "regex": t.regex,
                "format": t.format_str,
                "dest_key": t.dest_key,
                "description": "Route events to different indexes based on regex match.",
            },
            priority=Priority.CRITICAL,
            notes=(
                "Index routing transform. In Cribl, use a Route or Pipeline with conditional "
                "logic to send events to different destinations (indexes)."
            ),
        )

    def _map_transform_event_dropping(self, t: TransformDetail) -> CriblMapping:
        return CriblMapping(
            splunk_setting=f"TRANSFORMS ({t.transform_name})",
            splunk_value=t.regex or "",
            cribl_function="Drop",
            cribl_config={
                "regex": t.regex,
                "description": "Drop events matching this regex.",
            },
            priority=Priority.CRITICAL,
            notes=(
                "Event dropping (nullQueue). In Cribl, use a Drop function or Route filter "
                "to discard matching events. Verify the regex — dropped events are unrecoverable."
            ),
        )

    def _map_transform_host_override(self, t: TransformDetail) -> CriblMapping:
        return CriblMapping(
            splunk_setting=f"TRANSFORMS ({t.transform_name})",
            splunk_value=t.regex or "",
            cribl_function="Eval",
            cribl_config={
                "field": "host",
                "regex": t.regex,
                "format": t.format_str,
            },
            priority=Priority.HIGH,
            notes="Host override. Use Cribl Eval: host = <extracted value from regex>.",
        )

    def _map_transform_source_override(self, t: TransformDetail) -> CriblMapping:
        return CriblMapping(
            splunk_setting=f"TRANSFORMS ({t.transform_name})",
            splunk_value=t.regex or "",
            cribl_function="Eval",
            cribl_config={
                "field": "source",
                "regex": t.regex,
                "format": t.format_str,
            },
            priority=Priority.HIGH,
            notes="Source override. Use Cribl Eval: source = <extracted value from regex>.",
        )

    def _map_transform_sourcetype_override(self, t: TransformDetail) -> CriblMapping:
        return CriblMapping(
            splunk_setting=f"TRANSFORMS ({t.transform_name})",
            splunk_value=t.regex or "",
            cribl_function="Eval",
            cribl_config={
                "field": "sourcetype",
                "regex": t.regex,
                "format": t.format_str,
            },
            priority=Priority.HIGH,
            notes="Sourcetype override. Use Cribl Eval: sourcetype = <extracted value from regex>.",
        )

    def _map_transform_raw_modification(self, t: TransformDetail) -> CriblMapping:
        return CriblMapping(
            splunk_setting=f"TRANSFORMS ({t.transform_name})",
            splunk_value=t.regex or "",
            cribl_function="Mask",
            cribl_config={
                "regex": t.regex,
                "format": t.format_str,
                "description": "Modifies _raw event data.",
            },
            priority=Priority.CRITICAL,
            notes=(
                "Raw data modification. In Cribl, use Mask (Regex Replace) to rewrite _raw. "
                "Test carefully — modifying raw data affects all downstream parsing."
            ),
        )

    def _map_transform_clone(self, t: TransformDetail) -> CriblMapping:
        return CriblMapping(
            splunk_setting=f"TRANSFORMS ({t.transform_name})",
            splunk_value=t.raw_settings.get("CLONE_SOURCETYPE", ""),
            cribl_function="Clone",
            cribl_config={
                "clone_sourcetype": t.raw_settings.get("CLONE_SOURCETYPE"),
                "dest_key": t.dest_key,
                "regex": t.regex,
            },
            priority=Priority.HIGH,
            notes=(
                "Event cloning. In Cribl, use a Clone function to duplicate events. "
                "Route clones to a separate pipeline for the target sourcetype."
            ),
        )

    def _map_transform_routing(self, t: TransformDetail) -> CriblMapping:
        return CriblMapping(
            splunk_setting=f"TRANSFORMS ({t.transform_name})",
            splunk_value=t.regex or "",
            cribl_function="Route",
            cribl_config={
                "regex": t.regex,
                "format": t.format_str,
                "dest_key": t.dest_key,
                "description": "TCP/Syslog routing based on regex match.",
            },
            priority=Priority.HIGH,
            notes=(
                "TCP or Syslog routing transform. In Cribl, use a Route function to direct "
                "events to the appropriate output destination based on the routing rule."
            ),
        )

    def _map_transform_timestamp_override(self, t: TransformDetail) -> CriblMapping:
        return CriblMapping(
            splunk_setting=f"TRANSFORMS ({t.transform_name})",
            splunk_value=t.regex or "",
            cribl_function="Eval",
            cribl_config={
                "field": "_time",
                "regex": t.regex,
                "format": t.format_str,
                "description": "Override event timestamp via transform.",
            },
            priority=Priority.CRITICAL,
            notes=(
                "Timestamp override transform (DEST_KEY=_time). In Cribl, use an Eval function "
                "to set _time from regex capture groups. Verify timestamp format carefully."
            ),
        )

    def _map_transform_generic(self, t: TransformDetail) -> CriblMapping:
        return CriblMapping(
            splunk_setting=f"TRANSFORMS ({t.transform_name})",
            splunk_value=t.regex or str(t.raw_settings),
            cribl_function="Eval",
            cribl_config={"raw_settings": t.raw_settings},
            priority=Priority.MEDIUM,
            notes="Unclassified transform. Review manually and map to appropriate Cribl function.",
        )

    # Dispatch tables
    _CATEGORY_HANDLERS = {
        "event_breaking": _map_event_breaking,
        "timestamp": _map_timestamp,
        "sedcmd": _map_sedcmd,
        "transforms": _map_transforms_ref,
        "ingest_eval": _map_ingest_eval,
        "structured_data": _map_structured_data,
        "sourcetype": _map_sourcetype,
        "encoding": _map_encoding,
        "metrics": _map_metrics,
    }

    _TRANSFORM_TYPE_HANDLERS = {
        TransformType.FIELD_EXTRACTION: _map_transform_field_extraction,
        TransformType.INDEX_ROUTING: _map_transform_index_routing,
        TransformType.EVENT_DROPPING: _map_transform_event_dropping,
        TransformType.HOST_OVERRIDE: _map_transform_host_override,
        TransformType.SOURCE_OVERRIDE: _map_transform_source_override,
        TransformType.SOURCETYPE_OVERRIDE: _map_transform_sourcetype_override,
        TransformType.RAW_MODIFICATION: _map_transform_raw_modification,
        TransformType.CLONE: _map_transform_clone,
        TransformType.ROUTING: _map_transform_routing,
        TransformType.TIMESTAMP_OVERRIDE: _map_transform_timestamp_override,
    }


# ---------------------------------------------------------------------------
# 7. BtoolImporter — import from btoolinfo CSV output
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Extracted to conf_cribl_migration_generators.py — re-exported for compat
# ---------------------------------------------------------------------------
from chat_app.conf_cribl_migration_generators import (  # noqa: F401, E402
    run_analysis,
    _process_props_settings,
    _merge_conf_layers,
    generate_cribl_pipeline_yaml,
    _yaml_escape,
    generate_migration_checklist,
    main,
    validate_regex_pattern,
)
