"""Cribl Migration Generators — Analysis, pipeline YAML, checklist, CLI, regex tester.

Extracted from conf_cribl_migration.py to keep file sizes manageable.
All public names are re-exported from the parent module for backward compatibility.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

from chat_app.conf_index_time_analyzer import (
    ConfFile,
    ConfsScanner,
    IndexTimeExtractor,
    IndexTimeSetting,
    ReportGenerator,
    SourcetypeReport,
)
from shared.conf_parser import parse_conf_file_advanced
from chat_app.conf_cribl_migration import CriblMigrationMapper

logger = logging.getLogger(__name__)


def _get_migration_classes():
    """Lazy import to avoid circular dependency with conf_cribl_migration.py."""
    from chat_app.conf_cribl_migration import (
        BtoolImporter,
        CriblMigrationMapper,
        CriblScanner,
        SplunkCriblComparator,
    )
    return BtoolImporter, CriblMigrationMapper, CriblScanner, SplunkCriblComparator

# ---------------------------------------------------------------------------
# 8. Orchestrator — ties everything together
# ---------------------------------------------------------------------------

def run_analysis(
    apps_dir: str = "",
    output_format: str = "json",
    *,
    splunk_repo: str = "",
    cribl_repo: str = "",
    btool_csv: str = "",
    app_filter: str = "",
    category_filter: str = "",
    group_filter: str = "",
) -> str:
    """Run the full analysis pipeline and return the formatted report.

    Supports multiple input modes:
    - ``apps_dir``: Legacy direct path to a Splunk apps directory.
    - ``splunk_repo``: Structured org repo (TAs/BAs/IAs/... layout).
    - ``btool_csv``: Paste of btoolinfo CSV output (no file scan needed).
    - ``cribl_repo``: Optional Cribl repo for cross-platform comparison.

    If neither ``apps_dir`` nor ``splunk_repo`` is provided, auto-detects
    from ``settings.paths.org_repo_root``.

    Args:
        apps_dir: Path to Splunk apps directory (e.g., /opt/splunk/etc/apps).
        output_format: "json", "csv", or "yaml".
        splunk_repo: Structured Splunk repo root (auto: org_repo_root/splunk).
        cribl_repo: Cribl repo root (auto: org_repo_root/cribl).
        btool_csv: btoolinfo CSV content string.
        app_filter: Regex filter for app names.
        category_filter: Filter by TAs, BAs, IAs, etc.
        group_filter: Filter by deployment group.

    Returns:
        Formatted report string.
    """
    BtoolImporter, CriblMigrationMapper, CriblScanner, SplunkCriblComparator = _get_migration_classes()
    scanner = ConfsScanner()
    extractor = IndexTimeExtractor()
    mapper = CriblMigrationMapper()
    reporter = ReportGenerator()

    # ---- Determine conf files from the best available source ----

    conf_files: List[ConfFile] = []
    btool_data: Dict[str, Dict[str, Dict[str, str]]] = {}
    scan_source = "unknown"

    if btool_csv:
        # Mode 1: btoolinfo CSV import
        importer = BtoolImporter()
        btool_data = importer.import_from_csv(btool_csv)
        conf_files = importer.to_conf_files(btool_data)
        scan_source = "btool_csv"
    elif splunk_repo:
        # Mode 2: Structured org repo scan
        conf_files = scanner.scan_splunk_repo(
            repo_root=splunk_repo,
            app_filter=app_filter,
            category_filter=category_filter,
            group_filter=group_filter,
        )
        scan_source = f"splunk_repo:{splunk_repo}"
    elif apps_dir:
        # Mode 3: Legacy direct directory scan
        conf_files = scanner.scan(apps_dir)
        scan_source = f"apps_dir:{apps_dir}"
    else:
        # Mode 4: Auto-detect from settings
        try:
            from chat_app.settings import get_settings
            org_root = get_settings().paths.org_repo_root or ""
            splunk_auto = os.path.join(org_root, "splunk")
            if os.path.isdir(splunk_auto):
                conf_files = scanner.scan_splunk_repo(
                    repo_root=splunk_auto,
                    app_filter=app_filter,
                    category_filter=category_filter,
                    group_filter=group_filter,
                )
                scan_source = f"auto_splunk_repo:{splunk_auto}"
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

        if not conf_files:
            # Try legacy auto-detect
            try:
                from chat_app.settings import get_settings
                org_root = get_settings().paths.org_repo_root or ""
                if os.path.isdir(org_root):
                    conf_files = scanner.scan(org_root)
                    scan_source = f"auto_org_root:{org_root}"
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                logger.debug("%s", _exc)  # was: pass

    scan_label = apps_dir or splunk_repo or scan_source

    if not conf_files and not btool_data:
        return json.dumps({
            "scan_summary": {
                "total_apps": 0,
                "total_sourcetypes": 0,
                "total_index_time_settings": 0,
                "critical_settings": 0,
                "apps_scanned": [],
                "scan_source": scan_source,
                "error": f"No props.conf or transforms.conf found ({scan_source})",
            },
            "by_app": {},
            "by_sourcetype": {},
            "cribl_summary": {
                "pipelines_needed": 0,
                "event_breakers_needed": 0,
                "total_functions": 0,
                "by_function_type": {},
            },
        }, indent=2)

    # ---- Build merged data from conf files or btool import ----

    by_app: Dict[str, Dict[str, SourcetypeReport]] = {}

    if btool_data:
        # btool CSV already provides the merged view
        merged_props = btool_data.get("props", {})
        merged_transforms = btool_data.get("transforms", {})

        # When 6-column CSV was used, partition stanzas by app_name
        importer_apps = getattr(importer, "_last_import_apps", {}) if 'importer' in dir() else {}
        if not importer_apps:
            # Try to get from the importer local variable (btool_csv path)
            try:
                importer_apps = importer._last_import_apps  # noqa: F841
            except (NameError, AttributeError):
                importer_apps = {}

        if merged_props and importer_apps:
            # Group stanzas by app_name for accurate per-app reporting
            apps_stanzas: Dict[str, Dict[str, Dict[str, str]]] = {}
            for stanza, app_name in importer_apps.items():
                if stanza in merged_props:
                    apps_stanzas.setdefault(app_name, {})[stanza] = merged_props[stanza]

            # Include stanzas with no app mapping under "btool_merged"
            for stanza in merged_props:
                if stanza not in importer_apps:
                    apps_stanzas.setdefault("btool_merged", {})[stanza] = merged_props[stanza]

            # Process each app separately
            for app_name, app_props in sorted(apps_stanzas.items()):
                props_settings = extractor.extract_from_props(app_props, f"btool_import/{app_name}/props.conf")
                app_results = _process_props_settings(
                    props_settings, app_name, merged_transforms, merged_transforms,
                    extractor, mapper,
                )
                by_app.update(app_results)
        elif merged_props:
            props_settings = extractor.extract_from_props(merged_props, "btool_import/props.conf")
            by_app = _process_props_settings(
                props_settings, "btool_merged", merged_transforms, merged_transforms,
                extractor, mapper,
            )
    else:
        # Group conf files by app
        apps_confs: Dict[str, Dict[str, List[ConfFile]]] = {}
        for cf in conf_files:
            apps_confs.setdefault(cf.app_name, {}).setdefault(cf.conf_type, []).append(cf)

        # Build GLOBAL transforms lookup (cross-app resolution)
        all_transforms_files: List[ConfFile] = []
        for app_confs in apps_confs.values():
            all_transforms_files.extend(app_confs.get("transforms", []))
        global_transforms = _merge_conf_layers(all_transforms_files)
        logger.info(
            "Global transforms lookup: %d stanzas from %d files",
            len(global_transforms), len(all_transforms_files),
        )

        # Process each app
        for app_name, conf_types in sorted(apps_confs.items()):
            merged_props = _merge_conf_layers(conf_types.get("props", []))
            app_transforms = _merge_conf_layers(conf_types.get("transforms", []))

            if not merged_props:
                continue

            props_settings = extractor.extract_from_props(merged_props, f"{app_name}/props.conf")
            if not props_settings:
                continue

            app_results = _process_props_settings(
                props_settings, app_name, app_transforms, global_transforms,
                extractor, mapper,
            )
            by_app.update(app_results)

    # ---- Generate the Splunk report ----

    report_str = reporter.generate(by_app, scan_label, output_format)

    # ---- Cribl comparison (if available) ----

    if not cribl_repo:
        # Auto-detect
        try:
            from chat_app.settings import get_settings
            org_root = get_settings().paths.org_repo_root or ""
            cribl_auto = os.path.join(org_root, "cribl")
            if os.path.isdir(cribl_auto):
                cribl_repo = cribl_auto
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

    if cribl_repo and os.path.isdir(cribl_repo):
        cribl_scanner = CriblScanner()
        cribl_pipelines = cribl_scanner.scan(cribl_repo)

        if cribl_pipelines:
            comparator = SplunkCriblComparator()

            # Parse the Splunk report for comparison input
            if output_format == "json":
                try:
                    splunk_parsed = json.loads(report_str)
                except json.JSONDecodeError:
                    splunk_parsed = {}
            else:
                # For non-JSON formats, regenerate as JSON for comparison
                splunk_parsed = json.loads(reporter.generate(by_app, scan_label, "json"))

            comparison = comparator.compare(splunk_parsed, cribl_pipelines)

            # Merge comparison into the report
            if output_format == "json":
                try:
                    report_data = json.loads(report_str)
                except json.JSONDecodeError:
                    report_data = {}
                report_data["cribl_comparison"] = comparison
                report_data["cribl_pipelines_scanned"] = {
                    "total": len(cribl_pipelines),
                    "repo": cribl_repo,
                    "pipelines": {
                        k: {
                            "group": v.get("group", ""),
                            "has_event_breaker": v.get("event_breaker") is not None,
                            "has_timestamp": v.get("timestamp") is not None,
                            "function_count": len(v.get("functions", [])),
                        }
                        for k, v in cribl_pipelines.items()
                        if isinstance(v, dict)
                    },
                }
                # Inject repo metadata into scan_summary
                if "scan_summary" in report_data:
                    report_data["scan_summary"]["scan_source"] = scan_source
                    report_data["scan_summary"]["cribl_repo"] = cribl_repo

                    # Add category/group breakdowns for repo scans
                    if conf_files and conf_files[0].app_category:
                        report_data["scan_summary"]["by_category"] = {}
                        for cf in conf_files:
                            cat = cf.app_category or "uncategorized"
                            report_data["scan_summary"]["by_category"].setdefault(cat, 0)
                            report_data["scan_summary"]["by_category"][cat] += 1
                        report_data["scan_summary"]["by_deployment_group"] = {}
                        for cf in conf_files:
                            grp = cf.deployment_group or "ungrouped"
                            report_data["scan_summary"]["by_deployment_group"].setdefault(grp, 0)
                            report_data["scan_summary"]["by_deployment_group"][grp] += 1

                report_str = json.dumps(report_data, indent=2, default=str)

    return report_str


def _process_props_settings(
    props_settings: Dict[str, List[IndexTimeSetting]],
    app_name: str,
    app_transforms: Dict[str, Dict[str, Any]],
    global_transforms: Dict[str, Dict[str, Any]],
    extractor: IndexTimeExtractor,
    mapper: CriblMigrationMapper,
) -> Dict[str, Dict[str, SourcetypeReport]]:
    """Process extracted props settings into SourcetypeReports grouped by app.

    Shared logic between btool-import and file-scan paths.
    """
    sourcetypes: Dict[str, SourcetypeReport] = {}

    for stanza_name, settings in props_settings.items():
        st_report = SourcetypeReport(sourcetype=stanza_name, app_name=app_name)

        # Detect stanza type from naming convention
        if stanza_name.startswith("source::"):
            st_report.stanza_type = "source"
        elif stanza_name.startswith("host::"):
            st_report.stanza_type = "host"
        elif stanza_name == "default":
            st_report.stanza_type = "default"
        else:
            st_report.stanza_type = "sourcetype"

        # Collect transform references for bulk resolution
        transform_refs: List[str] = []

        for setting in settings:
            # Populate the appropriate bucket
            if setting.category == "event_breaking":
                st_report.event_breaking[setting.key] = setting.value
            elif setting.category == "timestamp":
                st_report.timestamp[setting.key] = setting.value
            elif setting.category == "sedcmd":
                st_report.sedcmds[setting.key] = setting.value
            elif setting.category == "ingest_eval":
                st_report.ingest_eval.append(setting.value)
            elif setting.category == "structured_data":
                st_report.structured_data[setting.key] = setting.value
            elif setting.category == "sourcetype":
                st_report.sourcetype_settings[setting.key] = setting.value
            elif setting.category == "encoding":
                st_report.encoding[setting.key] = setting.value
            elif setting.category == "metrics":
                st_report.metrics[setting.key] = setting.value
            elif setting.category == "transforms":
                for ref in setting.value.split(","):
                    ref = ref.strip()
                    if ref:
                        transform_refs.append(ref)

            # Map to Cribl equivalent
            cribl_mapping = mapper.map_setting(setting)
            st_report.cribl_pipeline.append(cribl_mapping)

        # Resolve transforms — try app-local first, then global lookup
        if transform_refs:
            combined_transforms = dict(global_transforms)
            combined_transforms.update(app_transforms)
            resolved = extractor.resolve_transforms(transform_refs, combined_transforms)
            st_report.transforms = resolved

            # Replace generic "Pipeline Reference" entries with detailed mappings
            st_report.cribl_pipeline = [
                m for m in st_report.cribl_pipeline
                if m.cribl_function != "Pipeline Reference"
            ]
            for detail in resolved:
                st_report.cribl_pipeline.append(mapper.map_transform(detail))

        sourcetypes[stanza_name] = st_report

    if sourcetypes:
        return {app_name: sourcetypes}
    return {}


def _merge_conf_layers(conf_files: List[ConfFile]) -> Dict[str, Dict[str, Any]]:
    """Merge default and local conf file layers with proper Splunk precedence.

    Splunk conf layer precedence (lowest to highest):
    1. system/default  (built-in defaults)
    2. app/default     (app-provided defaults)
    3. app/local       (admin customizations)
    4. system/local    (global admin overrides)

    Within the same layer, app type matters:
    system < SA-* < TA-* < DA-* < regular apps < custom/org apps

    At each layer, settings MERGE at the key level within each stanza:
    - default provides base key=value pairs
    - local overrides individual keys (not the whole stanza)

    Args:
        conf_files: List of ConfFile objects for the same conf_type within one app.

    Returns:
        Merged dict of stanza_name -> key/value pairs with provenance tracking.
    """
    merged: Dict[str, Dict[str, Any]] = {}

    # Sort by precedence: (layer_priority, app_priority)
    # Lower values processed first → overridden by higher values
    layer_priority = {"default": 0, "local": 10}

    def sort_key(conf_file: ConfFile) -> Tuple[int, int, str]:
        app_priority = ConfsScanner.get_app_priority(conf_file.app_name)
        layer_prio = layer_priority.get(conf_file.layer, 5)
        return (layer_prio, app_priority, conf_file.app_name)

    sorted_files = sorted(conf_files, key=sort_key)

    for conf_file in sorted_files:
        try:
            content = Path(conf_file.file_path).read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("Cannot read %s: %s", conf_file.file_path, exc)
            continue

        parsed = parse_conf_file_advanced(content, conf_file.file_path)

        for stanza_name, stanza_kv in parsed.items():
            if stanza_name not in merged:
                merged[stanza_name] = {}
            # Key-level merge: each key in local overrides the same key in default
            for key, value in stanza_kv.items():
                merged[stanza_name][key] = value
                # Track provenance (which file provided this value)
                merged[stanza_name].setdefault("__provenance__", {})
                merged[stanza_name]["__provenance__"][key] = {
                    "file": conf_file.file_path,
                    "layer": conf_file.layer,
                    "app": conf_file.app_name,
                }

    return merged


# ---------------------------------------------------------------------------
# Re-exports from extracted modules (backward compatibility)
# ---------------------------------------------------------------------------
from chat_app.conf_cribl_migration_generators_ext import (  # noqa: E402,F401
    generate_cribl_pipeline_yaml,
    _yaml_escape,
    generate_migration_checklist,
)
from chat_app.conf_cribl_migration_generators_ext2 import (  # noqa: E402,F401
    main,
    validate_regex_pattern,
)


if __name__ == "__main__":
    main()

