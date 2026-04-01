"""
Splunk Administration Skill — Analyze saved searches, validate configs,
audit indexes, and check props.conf settings.

Each function is a standalone action handler invoked by the SkillsManager.
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful imports from the existing codebase
# ---------------------------------------------------------------------------
try:
    from shared.config_analyzer import ConfigAnalyzer
    _CONFIG_ANALYZER_AVAILABLE = True
except ImportError:
    _CONFIG_ANALYZER_AVAILABLE = False
    logger.debug("shared.config_analyzer not available — config health checks will use fallback")

try:
    from shared.conf_parser import parse_conf_file, parse_conf_file_advanced
    _CONF_PARSER_AVAILABLE = True
except ImportError:
    _CONF_PARSER_AVAILABLE = False
    logger.debug("shared.conf_parser not available — conf parsing will use built-in fallback")

try:
    from shared.spl_robust_analyzer import analyze_spl
    _SPL_ANALYZER_AVAILABLE = True
except ImportError:
    _SPL_ANALYZER_AVAILABLE = False
    logger.debug("shared.spl_robust_analyzer not available — saved search analysis limited")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_CONFIG_ROOT = os.getenv("SPLUNK_CONFIG_ROOT", "/opt/splunk/etc/apps")


def _find_conf_files(root: str, filename: str, app_name: Optional[str] = None) -> List[Path]:
    """Find .conf files under the Splunk config root, optionally scoped to an app."""
    root_path = Path(root)
    if not root_path.is_dir():
        return []

    if app_name:
        app_path = root_path / app_name
        if app_path.is_dir():
            return list(app_path.rglob(filename))
        return []

    return list(root_path.rglob(filename))


def _parse_conf_simple(filepath: Path) -> Dict[str, Dict[str, str]]:
    """Simple .conf parser fallback when shared.conf_parser is unavailable."""
    stanzas: Dict[str, Dict[str, str]] = {}
    current_stanza = "default"
    stanzas[current_stanza] = {}

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    current_stanza = line[1:-1]
                    stanzas.setdefault(current_stanza, {})
                elif "=" in line:
                    key, _, value = line.partition("=")
                    stanzas[current_stanza][key.strip()] = value.strip()
    except OSError:
        pass

    return stanzas


def _parse_conf(filepath: Path) -> Dict[str, Dict[str, Any]]:
    """Parse a .conf file using the best available parser."""
    if _CONF_PARSER_AVAILABLE:
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
            return parse_conf_file_advanced(content, filename=str(filepath))
        except Exception:
            pass
    return _parse_conf_simple(filepath)


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def analyze_saved_searches(index_filter: Optional[str] = None) -> str:
    """
    Analyze saved searches for performance issues, wildcard index usage,
    scheduling conflicts, and best-practice violations.

    Args:
        index_filter: Optional index name to filter saved searches by.

    Returns:
        JSON string with analysis summary.
    """
    config_root = _DEFAULT_CONFIG_ROOT
    conf_files = _find_conf_files(config_root, "savedsearches.conf")

    if not conf_files:
        return json.dumps({
            "status": "no_data",
            "message": f"No savedsearches.conf files found under {config_root}",
            "searches_analyzed": 0,
            "issues": [],
        })

    total_searches = 0
    issues: List[Dict[str, Any]] = []
    search_summaries: List[Dict[str, Any]] = []

    for conf_file in conf_files:
        stanzas = _parse_conf(conf_file)
        app_path = str(conf_file.relative_to(config_root)) if Path(config_root).is_dir() else str(conf_file)

        for stanza_name, settings in stanzas.items():
            if stanza_name == "default":
                continue

            search_query = settings.get("search", "")
            if not search_query:
                continue

            # Apply index filter if provided
            if index_filter:
                if f"index={index_filter}" not in search_query.lower() and f'index="{index_filter}"' not in search_query.lower():
                    continue

            total_searches += 1
            cron = settings.get("cron_schedule", "")
            is_scheduled = settings.get("enableSched", "0") == "1"
            dispatch_earliest = settings.get("dispatch.earliest_time", "")
            dispatch_latest = settings.get("dispatch.latest_time", "")

            summary: Dict[str, Any] = {
                "name": stanza_name,
                "file": app_path,
                "is_scheduled": is_scheduled,
                "cron_schedule": cron,
                "time_range": f"{dispatch_earliest} to {dispatch_latest}" if dispatch_earliest else "not set",
            }

            # Check for wildcard index
            if re.search(r"\bindex\s*=\s*\*", search_query, re.IGNORECASE):
                issues.append({
                    "severity": "high",
                    "search_name": stanza_name,
                    "file": app_path,
                    "issue": "Uses wildcard index (index=*) which scans all indexes",
                    "recommendation": "Specify explicit index names to reduce search scope",
                })

            # Check for broad time range with no time bounds
            if is_scheduled and not dispatch_earliest:
                issues.append({
                    "severity": "medium",
                    "search_name": stanza_name,
                    "file": app_path,
                    "issue": "Scheduled search has no earliest time set",
                    "recommendation": "Set dispatch.earliest_time to limit data scanned",
                })

            # Check for expensive commands in scheduled searches
            expensive_cmds = ["join", "transaction", "append", "map"]
            for cmd in expensive_cmds:
                if re.search(rf"\|\s*{cmd}\b", search_query, re.IGNORECASE):
                    issues.append({
                        "severity": "medium",
                        "search_name": stanza_name,
                        "file": app_path,
                        "issue": f"Uses expensive command '{cmd}' in scheduled search",
                        "recommendation": f"Consider replacing '{cmd}' with a more efficient alternative (e.g., stats, lookup)",
                    })

            # Run deeper analysis if available
            if _SPL_ANALYZER_AVAILABLE:
                try:
                    analysis = analyze_spl(search_query, auto_fix=False)
                    summary["estimated_cost"] = analysis.estimated_cost
                    summary["issue_count"] = len(analysis.issues)
                    for issue in analysis.issues:
                        if issue.severity.value in ("critical", "high"):
                            issues.append({
                                "severity": issue.severity.value,
                                "search_name": stanza_name,
                                "file": app_path,
                                "issue": issue.message,
                                "recommendation": issue.suggestion or "",
                            })
                except Exception:
                    pass

            search_summaries.append(summary)

    # Aggregate stats
    high_issues = sum(1 for i in issues if i["severity"] in ("high", "critical"))
    medium_issues = sum(1 for i in issues if i["severity"] == "medium")

    return json.dumps({
        "status": "ok",
        "searches_analyzed": total_searches,
        "files_scanned": len(conf_files),
        "issues_total": len(issues),
        "issues_high": high_issues,
        "issues_medium": medium_issues,
        "issues": issues[:50],  # Cap output size
        "searches": search_summaries[:100],
    }, indent=2)


def check_config_health(app_name: Optional[str] = None) -> str:
    """
    Validate Splunk configuration files for best practices, deprecated
    settings, and common misconfigurations.

    Args:
        app_name: Optional Splunk app name to scope the check.

    Returns:
        JSON string with findings.
    """
    config_root = _DEFAULT_CONFIG_ROOT

    # Use the codebase ConfigAnalyzer when available
    if _CONFIG_ANALYZER_AVAILABLE:
        try:
            check_root = os.path.join(config_root, app_name) if app_name else config_root
            analyzer = ConfigAnalyzer(check_root)
            findings = analyzer.run_checks()
            return json.dumps({
                "status": "ok",
                "config_root": check_root,
                "findings_count": len(findings),
                "findings": findings[:100],
            }, indent=2)
        except Exception as exc:
            logger.warning(f"ConfigAnalyzer failed, using fallback: {exc}")

    # Fallback: manual checks
    findings: List[Dict[str, Any]] = []
    conf_types = ["props.conf", "transforms.conf", "inputs.conf", "outputs.conf", "savedsearches.conf", "server.conf"]

    for conf_name in conf_types:
        conf_files = _find_conf_files(config_root, conf_name, app_name)
        for conf_file in conf_files:
            stanzas = _parse_conf(conf_file)
            rel_path = str(conf_file)

            # Check for deprecated settings
            deprecated = {
                "maxDist": "Deprecated in recent Splunk versions",
                "enablePreview": "Deprecated — use job inspector instead",
            }
            for stanza_name, settings in stanzas.items():
                for key in settings:
                    if key in deprecated:
                        findings.append({
                            "file": rel_path,
                            "stanza": stanza_name,
                            "severity": "low",
                            "title": f"Deprecated setting: {key}",
                            "description": deprecated[key],
                        })

            # props.conf specific checks
            if conf_name == "props.conf":
                for stanza_name, settings in stanzas.items():
                    tf = settings.get("TIME_FORMAT", "")
                    if tf and "%s" not in tf and "%Y" not in tf and "%y" not in tf:
                        findings.append({
                            "file": rel_path,
                            "stanza": stanza_name,
                            "severity": "medium",
                            "title": "TIME_FORMAT may be missing year",
                            "description": f"TIME_FORMAT '{tf}' does not include a year specifier (%Y/%y)",
                        })

            # outputs.conf specific checks
            if conf_name == "outputs.conf":
                for stanza_name, settings in stanzas.items():
                    if "server" in settings and "sslPassword" in settings:
                        if settings.get("sslPassword", "").startswith("$"):
                            pass  # Encrypted, OK
                        else:
                            findings.append({
                                "file": rel_path,
                                "stanza": stanza_name,
                                "severity": "high",
                                "title": "Plaintext SSL password",
                                "description": "sslPassword appears to be in plaintext. Use encrypted passwords.",
                            })

    return json.dumps({
        "status": "ok",
        "config_root": os.path.join(config_root, app_name) if app_name else config_root,
        "findings_count": len(findings),
        "findings": findings[:100],
    }, indent=2)


def audit_indexes(min_size_mb: float = 0) -> str:
    """
    List Splunk indexes with size statistics, retention settings,
    and usage notes.

    Args:
        min_size_mb: Minimum index size in MB to include.

    Returns:
        JSON string with index information.
    """
    config_root = _DEFAULT_CONFIG_ROOT
    indexes_files = _find_conf_files(config_root, "indexes.conf")

    if not indexes_files:
        return json.dumps({
            "status": "no_data",
            "message": f"No indexes.conf files found under {config_root}",
            "indexes": [],
        })

    indexes: List[Dict[str, Any]] = []

    for conf_file in indexes_files:
        stanzas = _parse_conf(conf_file)
        rel_path = str(conf_file)

        default_settings = stanzas.get("default", {})

        for stanza_name, settings in stanzas.items():
            if stanza_name == "default":
                continue
            # Skip volume stanzas
            if stanza_name.startswith("volume:"):
                continue

            home_path = settings.get("homePath", "")
            cold_path = settings.get("coldPath", "")
            thawed_path = settings.get("thawedPath", "")
            max_data_size = settings.get("maxDataSizeMB", default_settings.get("maxDataSizeMB", "auto"))
            frozen_time = settings.get("frozenTimePeriodInSecs", default_settings.get("frozenTimePeriodInSecs", "188697600"))
            max_total = settings.get("maxTotalDataSizeMB", default_settings.get("maxTotalDataSizeMB", "500000"))

            # Estimate size from maxTotalDataSizeMB if available
            try:
                total_mb = float(max_total)
            except (ValueError, TypeError):
                total_mb = 0

            if total_mb < min_size_mb:
                continue

            # Calculate retention in days
            try:
                retention_days = int(frozen_time) / 86400
            except (ValueError, TypeError):
                retention_days = 0

            warnings = []
            if retention_days > 365:
                warnings.append("Retention exceeds 1 year — review storage costs")
            if not home_path:
                warnings.append("No homePath defined")
            if stanza_name.startswith("_") and stanza_name not in ("_internal", "_audit", "_introspection", "_telemetry", "_metrics"):
                warnings.append("Non-standard internal index name")

            indexes.append({
                "name": stanza_name,
                "file": rel_path,
                "homePath": home_path,
                "coldPath": cold_path,
                "maxTotalDataSizeMB": max_total,
                "maxDataSizeMB": max_data_size,
                "retention_days": round(retention_days, 1),
                "frozenTimePeriodInSecs": frozen_time,
                "warnings": warnings,
            })

    # Sort by name
    indexes.sort(key=lambda x: x["name"])

    return json.dumps({
        "status": "ok",
        "files_scanned": len(indexes_files),
        "index_count": len(indexes),
        "indexes": indexes,
    }, indent=2)


def validate_props(sourcetype: Optional[str] = None) -> str:
    """
    Validate props.conf settings for correctness, including TRANSFORMS
    references, TIME_FORMAT patterns, and field extraction configurations.

    Args:
        sourcetype: Optional sourcetype stanza to validate.

    Returns:
        JSON string with validation results.
    """
    config_root = _DEFAULT_CONFIG_ROOT
    props_files = _find_conf_files(config_root, "props.conf")
    transforms_files = _find_conf_files(config_root, "transforms.conf")

    if not props_files:
        return json.dumps({
            "status": "no_data",
            "message": f"No props.conf files found under {config_root}",
            "stanzas_checked": 0,
            "issues": [],
        })

    # Build a set of known transforms stanza names for cross-reference
    known_transforms = set()
    for tf_file in transforms_files:
        tf_stanzas = _parse_conf(tf_file)
        for stanza_name in tf_stanzas:
            if stanza_name != "default":
                known_transforms.add(stanza_name)

    issues: List[Dict[str, Any]] = []
    stanzas_checked = 0

    for conf_file in props_files:
        stanzas = _parse_conf(conf_file)
        rel_path = str(conf_file)

        for stanza_name, settings in stanzas.items():
            if stanza_name == "default":
                continue
            if sourcetype and stanza_name != sourcetype:
                continue

            stanzas_checked += 1

            # Check TIME_FORMAT validity
            time_format = settings.get("TIME_FORMAT", "")
            if time_format:
                valid_specifiers = {"%Y", "%y", "%m", "%d", "%H", "%M", "%S", "%f",
                                    "%b", "%B", "%p", "%I", "%Z", "%z", "%s", "%N",
                                    "%e", "%k", "%3N", "%6N", "%9N", "%Q", "%+"}
                used = set(re.findall(r"%[A-Za-z0-9+]", time_format))
                unknown = used - valid_specifiers
                if unknown:
                    issues.append({
                        "file": rel_path,
                        "stanza": stanza_name,
                        "severity": "medium",
                        "issue": f"TIME_FORMAT contains potentially invalid specifiers: {', '.join(unknown)}",
                        "setting": f"TIME_FORMAT = {time_format}",
                    })

            # Check TRANSFORMS- references exist in transforms.conf
            for key, value in settings.items():
                if key.startswith("TRANSFORMS-") or key.startswith("REPORT-"):
                    transform_name = value.strip()
                    # Handle comma-separated transforms
                    for t_name in [t.strip() for t in transform_name.split(",")]:
                        if t_name and t_name not in known_transforms:
                            issues.append({
                                "file": rel_path,
                                "stanza": stanza_name,
                                "severity": "high",
                                "issue": f"Reference to undefined transform: '{t_name}'",
                                "setting": f"{key} = {value}",
                            })

            # Check EXTRACT regex validity
            for key, value in settings.items():
                if key.startswith("EXTRACT-"):
                    try:
                        re.compile(value)
                    except re.error as exc:
                        issues.append({
                            "file": rel_path,
                            "stanza": stanza_name,
                            "severity": "high",
                            "issue": f"Invalid regex in {key}: {exc}",
                            "setting": f"{key} = {value}",
                        })

            # Check LINE_BREAKER regex validity
            line_breaker = settings.get("LINE_BREAKER", "")
            if line_breaker:
                try:
                    re.compile(line_breaker)
                except re.error as exc:
                    issues.append({
                        "file": rel_path,
                        "stanza": stanza_name,
                        "severity": "high",
                        "issue": f"Invalid LINE_BREAKER regex: {exc}",
                        "setting": f"LINE_BREAKER = {line_breaker}",
                    })

            # Check for SHOULD_LINEMERGE + LINE_BREAKER conflict
            should_merge = settings.get("SHOULD_LINEMERGE", "").lower()
            if should_merge == "true" and line_breaker:
                issues.append({
                    "file": rel_path,
                    "stanza": stanza_name,
                    "severity": "low",
                    "issue": "SHOULD_LINEMERGE=true with LINE_BREAKER set — LINE_BREAKER is applied first, then line merging, which may cause unexpected event boundaries",
                    "setting": f"SHOULD_LINEMERGE = true, LINE_BREAKER = {line_breaker}",
                })

            # Check truncation setting
            truncate = settings.get("TRUNCATE", "")
            if truncate:
                try:
                    trunc_val = int(truncate)
                    if trunc_val < 256:
                        issues.append({
                            "file": rel_path,
                            "stanza": stanza_name,
                            "severity": "medium",
                            "issue": f"TRUNCATE={trunc_val} is very low — events may be cut off",
                            "setting": f"TRUNCATE = {truncate}",
                        })
                except ValueError:
                    pass

    high_issues = sum(1 for i in issues if i["severity"] == "high")
    medium_issues = sum(1 for i in issues if i["severity"] == "medium")

    return json.dumps({
        "status": "ok",
        "files_scanned": len(props_files),
        "stanzas_checked": stanzas_checked,
        "issues_total": len(issues),
        "issues_high": high_issues,
        "issues_medium": medium_issues,
        "issues": issues[:100],
    }, indent=2)


# ---------------------------------------------------------------------------
# Cleanup hook (called by SkillsManager on uninstall)
# ---------------------------------------------------------------------------

def cleanup():
    """Release any resources held by this skill."""
    logger.debug("splunk_admin skill cleaned up")
