"""
Cribl Migration Comparator — CriblScanner and SplunkCriblComparator.

Extracted from conf_cribl_migration.py to keep file sizes manageable.

All public names are re-exported from conf_cribl_migration for backward compat.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _get_conf_file_class():
    """Lazy import to avoid circular dependency."""
    from chat_app.conf_index_time_analyzer import ConfFile
    return ConfFile


# ---------------------------------------------------------------------------
# 5. CriblScanner — scan Cribl repos for pipeline configs
# ---------------------------------------------------------------------------


class CriblScanner:
    """Scan a Cribl repo for event breakers and pipeline configurations.

    Expected structure::

        cribl_root/groups/<group_name>/pipelines/<pipeline_name>/conf.yml
        cribl_root/groups/<group_name>/pipelines/<pipeline_name>/functions.yml

    Also handles flat pipeline directories (no groups) and JSON config files.
    """

    # Cribl function types relevant to Splunk migration comparison
    EVENT_BREAKER_TYPES = {"event_breaker_rule", "event_breaker"}
    TIMESTAMP_TYPES = {"auto_timestamp", "timestamp"}
    EVAL_TYPES = {"eval", "code"}
    MASK_TYPES = {"mask", "regex_extract"}
    PARSER_TYPES = {"parser", "json_unroll", "csv_parser"}
    ROUTE_TYPES = {"route", "router"}
    DROP_TYPES = {"drop", "suppress", "sampling"}

    def scan(self, cribl_root: str) -> Dict[str, Any]:
        """Walk cribl_root/groups/*/pipelines/* for event breaker configs.

        Returns dict mapping pipeline_name -> {
            "group": group_name,
            "event_breaker": {...} or None,
            "functions": [list of function dicts],
            "timestamp": {...} or None,
            "evals": [list of eval configs],
            "path": str,
        }
        """
        root_path = Path(cribl_root)
        if not root_path.is_dir():
            logger.warning("Cribl repo root does not exist: %s", cribl_root)
            return {}

        pipelines: Dict[str, Any] = {}

        # Strategy 1: groups/<group>/pipelines/<pipeline>/
        groups_dir = root_path / "groups"
        if groups_dir.is_dir():
            for group_dir in sorted(groups_dir.iterdir()):
                if not group_dir.is_dir():
                    continue
                pipelines_dir = group_dir / "pipelines"
                if not pipelines_dir.is_dir():
                    continue
                for pipe_dir in sorted(pipelines_dir.iterdir()):
                    if not pipe_dir.is_dir():
                        continue
                    pipeline = self._parse_pipeline(pipe_dir, group_dir.name)
                    if pipeline:
                        key = f"{group_dir.name}/{pipe_dir.name}"
                        pipelines[key] = pipeline

        # Strategy 2: pipelines/ directly under root (no groups)
        pipelines_dir = root_path / "pipelines"
        if pipelines_dir.is_dir():
            for pipe_dir in sorted(pipelines_dir.iterdir()):
                if not pipe_dir.is_dir():
                    continue
                pipeline = self._parse_pipeline(pipe_dir, "")
                if pipeline:
                    pipelines[pipe_dir.name] = pipeline

        logger.info(
            "Scanned Cribl repo %s: found %d pipelines across %d groups",
            cribl_root,
            len(pipelines),
            len({p.get("group", "") for p in pipelines.values() if p.get("group")}),
        )
        return pipelines

    def _parse_pipeline(self, pipe_dir: Path, group_name: str) -> Optional[Dict[str, Any]]:
        """Parse a single pipeline directory for its configuration.

        Looks for conf.yml/conf.json and functions.yml/functions.json.
        """
        pipeline: Dict[str, Any] = {
            "group": group_name,
            "name": pipe_dir.name,
            "event_breaker": None,
            "timestamp": None,
            "functions": [],
            "evals": [],
            "path": str(pipe_dir),
        }

        # Load pipeline configuration
        conf_data = self._load_yaml_or_json(pipe_dir / "conf.yml") or \
                    self._load_yaml_or_json(pipe_dir / "conf.json") or {}

        # Load functions
        functions_data = self._load_yaml_or_json(pipe_dir / "functions.yml") or \
                         self._load_yaml_or_json(pipe_dir / "functions.json") or {}

        # Functions can be a list or nested under "functions" key
        func_list = []
        if isinstance(functions_data, list):
            func_list = functions_data
        elif isinstance(functions_data, dict):
            func_list = functions_data.get("functions", [])
            # Also check conf for inline functions
            if not func_list and isinstance(conf_data, dict):
                func_list = conf_data.get("functions", [])

        if not func_list and not conf_data:
            return None

        for func in func_list:
            if not isinstance(func, dict):
                continue

            func_id = str(func.get("id", "")).lower()
            func_type = str(func.get("type", func.get("conf", {}).get("type", ""))).lower()
            func_conf = func.get("conf", func)

            func_entry = {
                "id": func.get("id", ""),
                "type": func_type,
                "filter": func.get("filter", ""),
                "disabled": func.get("disabled", False),
                "conf": func_conf,
            }
            pipeline["functions"].append(func_entry)

            # Classify the function
            if func_type in self.EVENT_BREAKER_TYPES or func_id in self.EVENT_BREAKER_TYPES:
                pipeline["event_breaker"] = {
                    "type": func_type,
                    "regex": func_conf.get("regex", func_conf.get("eventBreakerRegex", "")),
                    "rules": func_conf.get("rules", []),
                    "filter": func.get("filter", ""),
                }

            elif func_type in self.TIMESTAMP_TYPES:
                pipeline["timestamp"] = {
                    "type": func_type,
                    "format": func_conf.get("format", func_conf.get("strptimeFormat", "")),
                    "prefix": func_conf.get("prefix", ""),
                    "timezone": func_conf.get("timezone", ""),
                    "filter": func.get("filter", ""),
                }

            elif func_type in self.EVAL_TYPES:
                pipeline["evals"].append({
                    "id": func.get("id", ""),
                    "expression": func_conf.get("expression", func_conf.get("code", "")),
                    "fields": func_conf.get("fields", []),
                    "filter": func.get("filter", ""),
                })

        # Add metadata from conf
        if isinstance(conf_data, dict):
            pipeline["description"] = conf_data.get("description", "")
            pipeline["async_func_timeout"] = conf_data.get("asyncFuncTimeout", 0)
            pipeline["output"] = conf_data.get("output", "")

        return pipeline

    @staticmethod
    def _load_yaml_or_json(filepath: Path) -> Optional[Any]:
        """Load a YAML or JSON file, returning None on failure."""
        if not filepath.is_file():
            return None
        try:
            content = filepath.read_text(encoding="utf-8", errors="replace")
            if not content.strip():
                return None
            # Try YAML first (YAML is a superset of JSON)
            try:
                import yaml
                return yaml.safe_load(content)
            except ImportError:
                pass
            # Fall back to JSON
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                pass
            logger.debug("Could not parse %s as YAML or JSON", filepath)
            return None
        except OSError as exc:
            logger.debug("Cannot read %s: %s", filepath, exc)
            return None


# ---------------------------------------------------------------------------
# 6. SplunkCriblComparator — compare Splunk settings with Cribl pipelines
# ---------------------------------------------------------------------------


class SplunkCriblComparator:
    """Compare Splunk index-time settings with Cribl pipeline configurations.

    Takes a Splunk analysis report and Cribl pipeline scan results and produces
    a comparison showing coverage gaps, matches, and mismatches.
    """

    def compare(
        self,
        splunk_report: Dict[str, Any],
        cribl_pipelines: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Compare Splunk sourcetypes with Cribl pipelines.

        Args:
            splunk_report: Output from ReportGenerator.generate() (parsed JSON).
            cribl_pipelines: Output from CriblScanner.scan().

        Returns:
            Dict with matched, gaps, cribl_only, and mismatches lists.
        """
        # Build a set of all Splunk sourcetypes from the report
        splunk_sourcetypes: Dict[str, Dict[str, Any]] = {}
        by_app = splunk_report.get("by_app", {})
        for app_name, app_data in by_app.items():
            for st_name, st_data in (app_data.get("sourcetypes", {}) if isinstance(app_data, dict) else {}).items():
                # Skip non-sourcetype stanzas for comparison
                stanza_type = st_data.get("stanza_type", "sourcetype") if isinstance(st_data, dict) else "sourcetype"
                if stanza_type in ("source", "host"):
                    continue
                key = st_name.lower().strip()
                if key == "default":
                    continue
                splunk_sourcetypes[key] = {
                    "app_name": app_name,
                    "stanza": st_name,
                    "data": st_data,
                }

        # Build a set of Cribl pipeline names and any sourcetype hints
        cribl_by_name: Dict[str, Dict[str, Any]] = {}
        for pipe_key, pipe_data in cribl_pipelines.items():
            if not isinstance(pipe_data, dict):
                continue
            name_lower = pipe_data.get("name", pipe_key.split("/")[-1]).lower()
            cribl_by_name[name_lower] = {
                "pipeline_key": pipe_key,
                "data": pipe_data,
            }

        matched: List[Dict[str, Any]] = []
        gaps: List[Dict[str, Any]] = []
        cribl_only: List[Dict[str, Any]] = []
        mismatches: List[Dict[str, Any]] = []
        matched_cribl_keys: set = set()

        for st_key, st_info in sorted(splunk_sourcetypes.items()):
            # Try exact match, then fuzzy (pipeline name contains sourcetype or vice versa)
            cribl_match = self._find_cribl_match(st_key, cribl_by_name)

            if cribl_match is None:
                gaps.append({
                    "sourcetype": st_info["stanza"],
                    "app_name": st_info["app_name"],
                    "has_event_breaking": bool(st_info["data"].get("event_breaking")) if isinstance(st_info["data"], dict) else False,
                    "has_timestamp": bool(st_info["data"].get("timestamp")) if isinstance(st_info["data"], dict) else False,
                    "has_transforms": bool(st_info["data"].get("transforms")) if isinstance(st_info["data"], dict) else False,
                })
            else:
                pipe_key = cribl_match["pipeline_key"]
                matched_cribl_keys.add(pipe_key)
                pipe_data = cribl_match["data"]

                match_entry = {
                    "sourcetype": st_info["stanza"],
                    "app_name": st_info["app_name"],
                    "cribl_pipeline": pipe_key,
                    "cribl_group": pipe_data.get("group", ""),
                }

                # Check for mismatches between Splunk settings and Cribl config
                setting_mismatches = self._compare_settings(st_info["data"], pipe_data)
                if setting_mismatches:
                    match_entry["mismatches"] = setting_mismatches
                    mismatches.append(match_entry)
                else:
                    matched.append(match_entry)

        # Find Cribl pipelines with no Splunk match
        for pipe_key, pipe_data in cribl_pipelines.items():
            if pipe_key not in matched_cribl_keys:
                cribl_only.append({
                    "pipeline": pipe_key,
                    "group": pipe_data.get("group", "") if isinstance(pipe_data, dict) else "",
                    "has_event_breaker": bool(pipe_data.get("event_breaker")) if isinstance(pipe_data, dict) else False,
                    "function_count": len(pipe_data.get("functions", [])) if isinstance(pipe_data, dict) else 0,
                })

        return {
            "summary": {
                "total_splunk_sourcetypes": len(splunk_sourcetypes),
                "total_cribl_pipelines": len(cribl_pipelines),
                "matched_count": len(matched),
                "gap_count": len(gaps),
                "cribl_only_count": len(cribl_only),
                "mismatch_count": len(mismatches),
                "coverage_pct": round(
                    (len(matched) + len(mismatches)) / max(len(splunk_sourcetypes), 1) * 100, 1
                ),
            },
            "matched": matched,
            "gaps": gaps,
            "cribl_only": cribl_only,
            "mismatches": mismatches,
        }

    def _find_cribl_match(
        self,
        sourcetype_key: str,
        cribl_by_name: Dict[str, Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Find the best matching Cribl pipeline for a Splunk sourcetype.

        Matching strategies (in priority order):
        1. Exact name match
        2. Sourcetype name contained in pipeline name
        3. Pipeline name contained in sourcetype name
        4. Normalized match (strip common prefixes/suffixes)
        """
        # Exact match
        if sourcetype_key in cribl_by_name:
            return cribl_by_name[sourcetype_key]

        # Normalize: strip common prefixes
        normalized = sourcetype_key
        for prefix in ("stash:", "source::", "host::"):
            if normalized.startswith(prefix):
                normalized = normalized[len(prefix):]

        if normalized in cribl_by_name:
            return cribl_by_name[normalized]

        # Containment matches
        for pipe_name, pipe_info in cribl_by_name.items():
            if sourcetype_key in pipe_name or pipe_name in sourcetype_key:
                return pipe_info
            if normalized and (normalized in pipe_name or pipe_name in normalized):
                return pipe_info

        return None

    @staticmethod
    def _compare_settings(
        splunk_data: Any,
        cribl_data: Dict[str, Any],
    ) -> List[Dict[str, str]]:
        """Compare specific settings between Splunk sourcetype and Cribl pipeline.

        Returns a list of mismatch descriptions.
        """
        if not isinstance(splunk_data, dict):
            return []

        mismatches: List[Dict[str, str]] = []

        # Compare event breaking
        splunk_eb = splunk_data.get("event_breaking", {})
        cribl_eb = cribl_data.get("event_breaker")
        if splunk_eb and not cribl_eb:
            mismatches.append({
                "category": "event_breaking",
                "issue": "Splunk has event breaking rules but Cribl pipeline has no event breaker function",
                "splunk_settings": list(splunk_eb.keys()),
            })
        elif splunk_eb and cribl_eb:
            # Check LINE_BREAKER vs Cribl regex
            splunk_lb = splunk_eb.get("LINE_BREAKER", "")
            cribl_regex = cribl_eb.get("regex", "")
            if splunk_lb and cribl_regex and splunk_lb != cribl_regex:
                mismatches.append({
                    "category": "event_breaking",
                    "issue": "LINE_BREAKER regex differs from Cribl event breaker regex",
                    "splunk_value": splunk_lb,
                    "cribl_value": cribl_regex,
                })

        # Compare timestamp
        splunk_ts = splunk_data.get("timestamp", {})
        cribl_ts = cribl_data.get("timestamp")
        if splunk_ts and not cribl_ts:
            mismatches.append({
                "category": "timestamp",
                "issue": "Splunk has timestamp settings but Cribl pipeline has no timestamp function",
                "splunk_settings": list(splunk_ts.keys()),
            })

        return mismatches


# ---------------------------------------------------------------------------
# 7. BtoolImporter — import from btoolinfo CSV output
# ---------------------------------------------------------------------------


class BtoolImporter:
    """Import Splunk configuration from btoolinfo command output.

    btoolinfo output format (CSV)::

        confpath, stanza, property, value

    This provides the *merged* view of Splunk config as btool resolves it,
    including all layering precedence.
    """

    def import_from_csv(self, csv_content: str) -> Dict[str, Dict[str, Dict[str, str]]]:
        """Parse btoolinfo CSV output into a nested structure.

        Supports two CSV formats:
        - 4 columns: confpath, stanza, property, value
        - 6 columns: confpath, stanza, property, value, app_name, layer

        When 6 columns are present, app_name from column 5 is used to group
        results by app rather than hardcoding "btool_merged".

        Args:
            csv_content: CSV string with columns as described above.

        Returns:
            Dict mapping conf_type -> stanza -> key -> value.
            Example: {"props": {"syslog": {"TIME_FORMAT": "%b %d ..."}}}
        """
        result: Dict[str, Dict[str, Dict[str, str]]] = {}
        self._last_import_apps: Dict[str, str] = {}  # stanza -> app_name mapping

        reader = csv.reader(io.StringIO(csv_content))
        header_skipped = False
        has_six_columns = False

        for row in reader:
            if not row or len(row) < 4:
                continue

            # Skip header row if present
            if not header_skipped:
                if row[0].strip().lower() in ("confpath", "conf_path", "path"):
                    # Detect column format from header
                    if len(row) >= 6 and row[4].strip().lower() in ("app_name", "app", "appname"):
                        has_six_columns = True
                    header_skipped = True
                    continue
                header_skipped = True
                # Auto-detect 6-column format from first data row
                if len(row) >= 6:
                    has_six_columns = True

            confpath = row[0].strip()
            stanza = row[1].strip()
            prop = row[2].strip()
            value = row[3].strip() if len(row) > 3 else ""

            # Handle 6-column format: confpath, stanza, property, value, app_name, layer
            app_name = ""
            if has_six_columns and len(row) >= 6:
                app_name = row[4].strip()
                # value is exactly column 4 (index 3), not joined
            elif len(row) > 4 and not has_six_columns:
                # Legacy: value may contain commas
                value = ",".join(row[3:]).strip()

            # Determine conf type from path
            conf_type = self._extract_conf_type(confpath)
            if conf_type not in ("props", "transforms"):
                continue

            result.setdefault(conf_type, {}).setdefault(stanza, {})[prop] = value
            # Track which app each stanza came from
            if app_name:
                self._last_import_apps[stanza] = app_name

        logger.info(
            "Imported btool CSV: %d conf types, %d total stanzas",
            len(result),
            sum(len(stanzas) for stanzas in result.values()),
        )
        return result

    def import_from_file(self, filepath: str) -> Dict[str, Dict[str, Dict[str, str]]]:
        """Read btoolinfo CSV from a file on disk.

        Args:
            filepath: Path to the btoolinfo CSV file.

        Returns:
            Same structure as import_from_csv().
        """
        path = Path(filepath)
        if not path.is_file():
            logger.warning("btoolinfo CSV file does not exist: %s", filepath)
            return {}

        content = path.read_text(encoding="utf-8", errors="replace")
        return self.import_from_csv(content)

    def to_conf_files(self, btool_data: Dict[str, Dict[str, Dict[str, str]]]) -> list:
        """Convert btool import data into synthetic ConfFile objects.

        Creates virtual ConfFile objects that can be processed by the existing
        extraction pipeline. The btool output represents the *merged* view,
        so all files are marked as layer="merged".

        When the CSV contained app_name columns, creates one ConfFile per
        unique app rather than a single "btool_merged" entry.

        Returns:
            List of ConfFile objects (one per conf_type per app found).
        """
        ConfFile = _get_conf_file_class()
        results = []
        app_names = set(getattr(self, "_last_import_apps", {}).values())

        if app_names:
            # Create one ConfFile per app per conf_type
            for conf_type in btool_data:
                for app_name in sorted(app_names):
                    results.append(ConfFile(
                        app_name=app_name,
                        app_path="btool_import",
                        conf_type=conf_type,
                        layer="merged",
                        file_path="btool_import",
                        app_category="btool",
                        deployment_group="merged",
                    ))
        else:
            for conf_type in btool_data:
                results.append(ConfFile(
                    app_name="btool_merged",
                    app_path="btool_import",
                    conf_type=conf_type,
                    layer="merged",
                    file_path="btool_import",
                    app_category="btool",
                    deployment_group="merged",
                ))

        return results

    @staticmethod
    def _extract_conf_type(confpath: str) -> str:
        """Extract conf type (props, transforms, etc.) from a btool confpath.

        Examples:
            /opt/splunk/etc/apps/TA-myapp/default/props.conf -> props
            /opt/splunk/etc/system/local/transforms.conf -> transforms
        """
        basename = os.path.basename(confpath)
        if basename.endswith(".conf"):
            return basename[:-5]
        return basename
