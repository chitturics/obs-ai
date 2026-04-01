"""Cribl Migration Generators Ext — Pipeline YAML and Checklist generators.

Extracted from conf_cribl_migration_generators.py to keep file sizes manageable.
Contains: generate_cribl_pipeline_yaml, _yaml_escape, generate_migration_checklist.
All public names are re-exported from conf_cribl_migration_generators for backward compat.
"""

from __future__ import annotations

import re
from typing import Dict, List

from chat_app.conf_index_time_analyzer import (
    Priority,
    SourcetypeReport,
    TransformType,
)

logger = __import__("logging").getLogger(__name__)


# ---------------------------------------------------------------------------
# Pipeline YAML & Migration Checklist generators
# ---------------------------------------------------------------------------


def generate_cribl_pipeline_yaml(
    by_app: Dict[str, Dict[str, SourcetypeReport]],
) -> str:
    """Generate Cribl-importable YAML pipeline definitions for each sourcetype.

    Iterates over all apps and sourcetypes, producing one YAML pipeline per
    sourcetype with Cribl functions derived from the Splunk index-time settings.

    Args:
        by_app: Dict[app_name] -> Dict[sourcetype] -> SourcetypeReport.

    Returns:
        A multi-document YAML string (separated by ``---``) with one pipeline
        per sourcetype, importable into Cribl Stream.
    """
    documents: List[str] = []

    for app_name, sourcetypes in sorted(by_app.items()):
        for st_name, st_report in sorted(sourcetypes.items()):
            if st_name == "default":
                continue

            # Sanitize sourcetype name for use as pipeline ID
            pipeline_id = re.sub(r"[^a-zA-Z0-9_]", "_", st_name)

            lines: List[str] = []
            lines.append(f"# Pipeline for sourcetype: {st_name}")
            lines.append(f"# Source: {app_name}")
            lines.append(f"id: {pipeline_id}")
            lines.append("functions:")

            has_functions = False

            # --- Event Breaker ---
            eb = st_report.event_breaking
            if eb:
                has_functions = True
                lb = eb.get("LINE_BREAKER", "")
                slm = eb.get("SHOULD_LINEMERGE", "")
                lines.append("  - id: event_breaker")
                lines.append('    filter: "true"')
                lines.append("    conf:")
                if lb:
                    lines.append("      type: regex")
                    lines.append(f"      regex: \"{_yaml_escape(lb)}\"")
                    comment_parts = [f"LINE_BREAKER = {lb}"]
                    if slm:
                        comment_parts.append(f"SHOULD_LINEMERGE = {slm}")
                    lines.append(f"      # From Splunk: {', '.join(comment_parts)}")
                else:
                    lines.append("      type: auto")
                    if slm:
                        lines.append(f"      # From Splunk: SHOULD_LINEMERGE = {slm}")

                # Additional event breaking settings as comments
                for k, v in eb.items():
                    if k not in ("LINE_BREAKER", "SHOULD_LINEMERGE"):
                        lines.append(f"      # {k} = {v}")

            # --- Auto Timestamp ---
            ts = st_report.timestamp
            if ts:
                has_functions = True
                tf = ts.get("TIME_FORMAT", "")
                tp = ts.get("TIME_PREFIX", "")
                tz = ts.get("TZ", "")
                lines.append("  - id: auto_timestamp")
                lines.append('    filter: "true"')
                lines.append("    conf:")

                dc = ts.get("DATETIME_CONFIG", "")
                if dc.upper() == "NONE":
                    lines.append("      type: none")
                    lines.append("      # From Splunk: DATETIME_CONFIG = NONE")
                elif dc.upper() == "CURRENT":
                    lines.append("      type: current")
                    lines.append("      # From Splunk: DATETIME_CONFIG = CURRENT")
                else:
                    lines.append("      type: auto")
                    if tp:
                        lines.append(f"      prefix: \"{_yaml_escape(tp)}\"")
                    else:
                        lines.append('      prefix: ""')
                    if tf:
                        lines.append(f"      format: \"{_yaml_escape(tf)}\"")
                        comment = f"TIME_FORMAT = {tf}"
                        if tp:
                            comment = f"TIME_PREFIX = {tp}, " + comment
                        lines.append(f"      # From Splunk: {comment}")
                    if tz:
                        lines.append(f"      timezone: \"{tz}\"")
                        lines.append(f"      # From Splunk: TZ = {tz}")

                # Additional timestamp settings as comments
                for k, v in ts.items():
                    if k not in ("TIME_FORMAT", "TIME_PREFIX", "TZ", "DATETIME_CONFIG"):
                        lines.append(f"      # {k} = {v}")

            # --- SEDCMD → Mask ---
            for sed_key, sed_val in st_report.sedcmds.items():
                has_functions = True
                lines.append(f"  - id: mask_{re.sub(r'[^a-zA-Z0-9_]', '_', sed_key)}")
                lines.append('    filter: "true"')
                lines.append("    conf:")
                lines.append("      type: regex_replace")
                lines.append(f"      expression: \"{_yaml_escape(sed_val)}\"")
                lines.append(f"      # From Splunk: {sed_key} = {sed_val}")

            # --- INGEST_EVAL → Eval ---
            for idx, eval_expr in enumerate(st_report.ingest_eval):
                has_functions = True
                lines.append(f"  - id: eval_{idx}")
                lines.append('    filter: "true"')
                lines.append("    conf:")
                lines.append(f"      expression: \"{_yaml_escape(eval_expr)}\"")
                lines.append(f"      # From Splunk: INGEST_EVAL = {eval_expr}")

            # --- TRANSFORMS (resolved) ---
            for td in st_report.transforms:
                has_functions = True
                func_id = re.sub(r"[^a-zA-Z0-9_]", "_", td.transform_name)

                if td.transform_type == TransformType.EVENT_DROPPING:
                    lines.append(f"  - id: drop_{func_id}")
                    lines.append(f'    filter: "/{_yaml_escape(td.regex or ".*")}/.test(_raw)"')
                    lines.append("    conf:")
                    lines.append("      action: drop")
                    lines.append(f"      # From Splunk: TRANSFORMS ({td.transform_name}) → nullQueue")
                elif td.transform_type == TransformType.INDEX_ROUTING:
                    lines.append(f"  - id: route_{func_id}")
                    lines.append('    filter: "true"')
                    lines.append("    conf:")
                    lines.append("      type: route")
                    if td.regex:
                        lines.append(f"      regex: \"{_yaml_escape(td.regex)}\"")
                    if td.format_str:
                        lines.append(f"      index: \"{_yaml_escape(td.format_str)}\"")
                    lines.append(f"      # From Splunk: TRANSFORMS ({td.transform_name}) → _MetaData:Index")
                elif td.transform_type in (
                    TransformType.HOST_OVERRIDE,
                    TransformType.SOURCE_OVERRIDE,
                    TransformType.SOURCETYPE_OVERRIDE,
                ):
                    field_map = {
                        TransformType.HOST_OVERRIDE: "host",
                        TransformType.SOURCE_OVERRIDE: "source",
                        TransformType.SOURCETYPE_OVERRIDE: "sourcetype",
                    }
                    field = field_map[td.transform_type]
                    lines.append(f"  - id: eval_{func_id}")
                    lines.append('    filter: "true"')
                    lines.append("    conf:")
                    if td.regex:
                        lines.append(f"      regex: \"{_yaml_escape(td.regex)}\"")
                    if td.format_str:
                        lines.append(f"      value: \"{_yaml_escape(td.format_str)}\"")
                    lines.append(f"      field: {field}")
                    lines.append(f"      # From Splunk: TRANSFORMS ({td.transform_name}) → {td.dest_key}")
                elif td.transform_type == TransformType.RAW_MODIFICATION:
                    lines.append(f"  - id: mask_{func_id}")
                    lines.append('    filter: "true"')
                    lines.append("    conf:")
                    lines.append("      type: regex_replace")
                    if td.regex:
                        lines.append(f"      regex: \"{_yaml_escape(td.regex)}\"")
                    if td.format_str:
                        lines.append(f"      replacement: \"{_yaml_escape(td.format_str)}\"")
                    lines.append(f"      # From Splunk: TRANSFORMS ({td.transform_name}) → _raw")
                elif td.transform_type == TransformType.CLONE:
                    lines.append(f"  - id: clone_{func_id}")
                    lines.append('    filter: "true"')
                    lines.append("    conf:")
                    clone_st = td.raw_settings.get("CLONE_SOURCETYPE", "")
                    lines.append(f"      clone_sourcetype: \"{clone_st}\"")
                    lines.append(f"      # From Splunk: TRANSFORMS ({td.transform_name}) → CLONE_SOURCETYPE")
                elif td.transform_type == TransformType.FIELD_EXTRACTION and td.write_meta and td.write_meta.lower() == "true":
                    lines.append(f"  - id: eval_{func_id}")
                    lines.append('    filter: "true"')
                    lines.append("    conf:")
                    if td.regex:
                        lines.append(f"      regex: \"{_yaml_escape(td.regex)}\"")
                    if td.format_str:
                        lines.append(f"      format: \"{_yaml_escape(td.format_str)}\"")
                    lines.append(f"      # From Splunk: TRANSFORMS ({td.transform_name}) WRITE_META=true")
                else:
                    # Generic / unknown transform
                    lines.append(f"  - id: eval_{func_id}")
                    lines.append('    filter: "true"')
                    lines.append("    conf:")
                    if td.regex:
                        lines.append(f"      regex: \"{_yaml_escape(td.regex)}\"")
                    if td.format_str:
                        lines.append(f"      format: \"{_yaml_escape(td.format_str)}\"")
                    lines.append(f"      # From Splunk: TRANSFORMS ({td.transform_name})")

            # --- Structured data → Parser ---
            if st_report.structured_data:
                has_functions = True
                ie = st_report.structured_data.get("INDEXED_EXTRACTIONS", "")
                lines.append("  - id: parser")
                lines.append('    filter: "true"')
                lines.append("    conf:")
                if ie:
                    lines.append(f"      format: {ie.lower()}")
                fd = st_report.structured_data.get("FIELD_DELIMITER", "")
                if fd:
                    lines.append(f"      delimiter: \"{_yaml_escape(fd)}\"")
                fn = st_report.structured_data.get("FIELD_NAMES", "")
                if fn:
                    lines.append(f"      fields: \"{_yaml_escape(fn)}\"")
                lines.append(f"      # From Splunk: INDEXED_EXTRACTIONS={ie or 'N/A'}")

            if not has_functions:
                lines.append("  []  # No index-time functions detected")

            documents.append("\n".join(lines))

    return "\n---\n".join(documents)


def _yaml_escape(value: str) -> str:
    """Escape special characters for embedding in double-quoted YAML strings."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


def generate_migration_checklist(
    by_app: Dict[str, Dict[str, SourcetypeReport]],
) -> str:
    """Generate a comprehensive Markdown migration checklist.

    Groups items by priority and category with actionable checkboxes.

    Args:
        by_app: Dict[app_name] -> Dict[sourcetype] -> SourcetypeReport.

    Returns:
        Markdown string with categorized checklists.
    """
    # Collect all items grouped by priority → category
    items: Dict[str, Dict[str, List[str]]] = {
        Priority.CRITICAL.value: {},
        Priority.HIGH.value: {},
        Priority.MEDIUM.value: {},
        Priority.LOW.value: {},
    }

    priority_labels = {
        Priority.CRITICAL.value: "Critical (Action Required)",
        Priority.HIGH.value: "High Priority",
        Priority.MEDIUM.value: "Medium Priority",
        Priority.LOW.value: "Low Priority",
    }

    # Category grouping
    category_labels = {
        "event_breaking": "Event Breakers",
        "timestamp": "Timestamp Extraction",
        "sedcmd": "SED Commands (Data Masking)",
        "ingest_eval": "Ingest Eval Expressions",
        "transforms_event_dropping": "Event Dropping (nullQueue)",
        "transforms_index_routing": "Index Routing",
        "transforms_field_extraction": "Field Extraction (WRITE_META)",
        "transforms_host_override": "Host Override",
        "transforms_source_override": "Source Override",
        "transforms_sourcetype_override": "Sourcetype Override",
        "transforms_raw_modification": "Raw Data Modification",
        "transforms_clone": "Event Cloning",
        "transforms_routing": "TCP/Syslog Routing",
        "transforms_timestamp_override": "Timestamp Override",
        "transforms_other": "Other Transforms",
        "structured_data": "Structured Data Parsing",
        "sourcetype": "Sourcetype Settings",
        "encoding": "Encoding Settings",
        "metrics": "Metrics Configuration",
    }

    total_items = 0
    completed = 0  # always 0 for fresh checklist

    for app_name, sourcetypes in sorted(by_app.items()):
        for st_name, st_report in sorted(sourcetypes.items()):
            if st_name == "default":
                continue

            # Event breaking
            if st_report.event_breaking:
                cat = "event_breaking"
                priority = Priority.CRITICAL.value
                eb = st_report.event_breaking
                detail_parts = []
                if "LINE_BREAKER" in eb:
                    detail_parts.append(f"Custom LINE_BREAKER: `{eb['LINE_BREAKER']}`")
                if "SHOULD_LINEMERGE" in eb:
                    detail_parts.append(f"SHOULD_LINEMERGE={eb['SHOULD_LINEMERGE']}")
                if "BREAK_ONLY_BEFORE_DATE" in eb:
                    detail_parts.append(f"BREAK_ONLY_BEFORE_DATE={eb['BREAK_ONLY_BEFORE_DATE']}")
                for k, v in eb.items():
                    if k not in ("LINE_BREAKER", "SHOULD_LINEMERGE", "BREAK_ONLY_BEFORE_DATE"):
                        detail_parts.append(f"{k}={v}")
                detail = ", ".join(detail_parts) if detail_parts else "Event breaking configured"
                line = f"- [ ] {st_name} ({app_name}) — {detail}"
                items[priority].setdefault(cat, []).append(line)
                total_items += 1

            # Timestamp
            if st_report.timestamp:
                cat = "timestamp"
                priority = Priority.CRITICAL.value
                ts = st_report.timestamp
                detail_parts = []
                if "TIME_FORMAT" in ts:
                    detail_parts.append(f"TIME_FORMAT=`{ts['TIME_FORMAT']}`")
                if "TIME_PREFIX" in ts:
                    detail_parts.append(f"TIME_PREFIX=`{ts['TIME_PREFIX']}`")
                if "DATETIME_CONFIG" in ts:
                    detail_parts.append(f"DATETIME_CONFIG={ts['DATETIME_CONFIG']}")
                for k, v in ts.items():
                    if k not in ("TIME_FORMAT", "TIME_PREFIX", "DATETIME_CONFIG"):
                        detail_parts.append(f"{k}={v}")
                detail = ", ".join(detail_parts) if detail_parts else "Timestamp configured"
                line = f"- [ ] {st_name} ({app_name}) — {detail}"
                items[priority].setdefault(cat, []).append(line)
                total_items += 1

            # SEDCMDs
            for sed_key, sed_val in st_report.sedcmds.items():
                cat = "sedcmd"
                priority = Priority.HIGH.value
                line = f"- [ ] {st_name} ({app_name}) — `{sed_key}` = `{sed_val}`"
                items[priority].setdefault(cat, []).append(line)
                total_items += 1

            # INGEST_EVAL
            for eval_expr in st_report.ingest_eval:
                cat = "ingest_eval"
                priority = Priority.HIGH.value
                line = f"- [ ] {st_name} ({app_name}) — `{eval_expr}`"
                items[priority].setdefault(cat, []).append(line)
                total_items += 1

            # Transforms
            for td in st_report.transforms:
                tt = td.transform_type
                if tt == TransformType.EVENT_DROPPING:
                    cat = "transforms_event_dropping"
                    priority = Priority.CRITICAL.value
                elif tt == TransformType.INDEX_ROUTING:
                    cat = "transforms_index_routing"
                    priority = Priority.CRITICAL.value
                elif tt == TransformType.RAW_MODIFICATION:
                    cat = "transforms_raw_modification"
                    priority = Priority.CRITICAL.value
                elif tt == TransformType.TIMESTAMP_OVERRIDE:
                    cat = "transforms_timestamp_override"
                    priority = Priority.CRITICAL.value
                elif tt == TransformType.HOST_OVERRIDE:
                    cat = "transforms_host_override"
                    priority = Priority.HIGH.value
                elif tt == TransformType.SOURCE_OVERRIDE:
                    cat = "transforms_source_override"
                    priority = Priority.HIGH.value
                elif tt == TransformType.SOURCETYPE_OVERRIDE:
                    cat = "transforms_sourcetype_override"
                    priority = Priority.HIGH.value
                elif tt == TransformType.CLONE:
                    cat = "transforms_clone"
                    priority = Priority.HIGH.value
                elif tt == TransformType.ROUTING:
                    cat = "transforms_routing"
                    priority = Priority.HIGH.value
                elif tt == TransformType.FIELD_EXTRACTION:
                    if td.write_meta and td.write_meta.lower() == "true":
                        cat = "transforms_field_extraction"
                        priority = Priority.HIGH.value
                    else:
                        cat = "transforms_other"
                        priority = Priority.LOW.value
                else:
                    cat = "transforms_other"
                    priority = Priority.MEDIUM.value

                detail = f"TRANSFORMS ({td.transform_name})"
                if td.regex:
                    detail += f" REGEX=`{td.regex}`"
                if td.dest_key:
                    detail += f" DEST_KEY={td.dest_key}"
                line = f"- [ ] {st_name} ({app_name}) — {detail}"
                items[priority].setdefault(cat, []).append(line)
                total_items += 1

            # Structured data
            if st_report.structured_data:
                cat = "structured_data"
                priority = Priority.MEDIUM.value
                ie = st_report.structured_data.get("INDEXED_EXTRACTIONS", "")
                detail = f"INDEXED_EXTRACTIONS={ie}" if ie else "Structured data settings"
                line = f"- [ ] {st_name} ({app_name}) — {detail}"
                items[priority].setdefault(cat, []).append(line)
                total_items += 1

            # Sourcetype settings
            if st_report.sourcetype_settings:
                cat = "sourcetype"
                priority = Priority.MEDIUM.value
                detail = ", ".join(f"{k}={v}" for k, v in st_report.sourcetype_settings.items())
                line = f"- [ ] {st_name} ({app_name}) — {detail}"
                items[priority].setdefault(cat, []).append(line)
                total_items += 1

            # Encoding
            if st_report.encoding:
                cat = "encoding"
                priority = Priority.LOW.value
                detail = ", ".join(f"{k}={v}" for k, v in st_report.encoding.items())
                line = f"- [ ] {st_name} ({app_name}) — {detail}"
                items[priority].setdefault(cat, []).append(line)
                total_items += 1

            # Metrics
            if st_report.metrics:
                cat = "metrics"
                priority = Priority.MEDIUM.value
                detail = ", ".join(f"{k}={v}" for k, v in st_report.metrics.items())
                line = f"- [ ] {st_name} ({app_name}) — {detail}"
                items[priority].setdefault(cat, []).append(line)
                total_items += 1

    # Build the markdown
    md: List[str] = []
    md.append("# Cribl Migration Checklist")
    md.append("")
    md.append(f"> Total items: {total_items} | Completed: {completed}/{total_items}")
    md.append("")

    for priority_value in [Priority.CRITICAL.value, Priority.HIGH.value, Priority.MEDIUM.value, Priority.LOW.value]:
        categories = items.get(priority_value, {})
        if not categories:
            continue

        label = priority_labels.get(priority_value, priority_value)
        md.append(f"## {label}")
        md.append("")

        for cat_key, cat_items in sorted(categories.items()):
            cat_label = category_labels.get(cat_key, cat_key)
            md.append(f"### {cat_label} ({len(cat_items)} sourcetypes)")
            md.append("")
            for item in cat_items:
                md.append(item)
            md.append("")

    return "\n".join(md)
