"""Cribl Migration Generators Ext2 — CLI entry point and regex tester.

Extracted from conf_cribl_migration_generators.py to keep file sizes manageable.
Contains: main (CLI entry point), validate_regex_pattern.
All public names are re-exported from conf_cribl_migration_generators for backward compat.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 6. CLI support
# ---------------------------------------------------------------------------

def main() -> None:
    """CLI entry point for the Splunk conf analyzer."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Analyze Splunk confs for Cribl migration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m chat_app.conf_index_time_analyzer /opt/splunk/etc/apps\n"
            "  python -m chat_app.conf_index_time_analyzer /opt/splunk/etc/apps -o report.json\n"
            "  python -m chat_app.conf_index_time_analyzer /opt/splunk/etc/apps --format csv -o report.csv\n"
        ),
    )
    parser.add_argument("apps_dir", help="Path to Splunk apps directory (e.g., /opt/splunk/etc/apps)")
    parser.add_argument("-o", "--output", default="cribl_migration_report.json", help="Output file path")
    parser.add_argument(
        "--format",
        choices=["json", "csv", "yaml"],
        default="json",
        dest="output_format",
        help="Output format (default: json)",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not os.path.isdir(args.apps_dir):
        logger.error("Directory does not exist: %s", args.apps_dir)
        raise SystemExit(1)

    from chat_app.conf_cribl_migration_generators import run_analysis
    report = run_analysis(args.apps_dir, args.output_format)

    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write(report)

    logger.info("Report written to %s", args.output)

    # Print summary to stdout
    if args.output_format == "json":
        try:
            data = json.loads(report)
            summary = data.get("scan_summary", {})
            print("\nScan complete:")
            print(f"  Apps scanned:              {summary.get('total_apps', 0)}")
            print(f"  Sourcetypes found:         {summary.get('total_sourcetypes', 0)}")
            print(f"  Index-time settings:       {summary.get('total_index_time_settings', 0)}")
            print(f"  Critical settings:         {summary.get('critical_settings', 0)}")
            cribl = data.get("cribl_summary", {})
            print(f"  Cribl pipelines needed:    {cribl.get('pipelines_needed', 0)}")
            print(f"  Cribl functions total:     {cribl.get('total_functions', 0)}")
            print(f"\nReport saved to: {args.output}")
        except json.JSONDecodeError as _exc:
            logger.debug("Could not parse migration report JSON for display: %s", _exc)


# ---------------------------------------------------------------------------
# 7. Regex tester for migration validation
# ---------------------------------------------------------------------------


def validate_regex_pattern(pattern: str, sample: str, mode: str = "line_breaker") -> Dict[str, Any]:
    """Test a regex against sample data for migration validation.

    Modes:
        line_breaker — Split *sample* using the regex capturing group and return
                       the resulting event list (mirrors Splunk LINE_BREAKER behaviour).
        time_prefix  — Find the first match position and highlight it with
                       markers (``>>`` / ``<<``).
        extraction   — Run regex and return all captured groups across the sample.

    Returns a dict with ``ok``, ``mode``, ``matches``, and mode-specific keys.
    """
    result: Dict[str, Any] = {"ok": True, "mode": mode, "pattern": pattern}

    try:
        compiled = re.compile(pattern)
    except re.error as exc:
        return {"ok": False, "mode": mode, "pattern": pattern, "error": f"Invalid regex: {exc}"}

    if mode == "line_breaker":
        # Splunk LINE_BREAKER uses the *capturing group* as the split point.
        # re.split keeps capturing-group text as interleaved elements.
        parts = re.split(pattern, sample)
        # Reassemble: every odd element is the captured separator.  Prepend it
        # to the following element so behaviour matches Splunk event boundaries.
        events: List[str] = []
        i = 0
        while i < len(parts):
            chunk = parts[i]
            if i + 1 < len(parts) and compiled.groups > 0:
                # Next part is the captured separator — belongs to the *next* event.
                i += 1
                sep = parts[i]
                if events:
                    events.append(sep + (parts[i + 1] if i + 1 < len(parts) else ""))
                    i += 1
                    continue
                else:
                    chunk = chunk + sep
            if chunk.strip():
                events.append(chunk)
            i += 1

        result["events"] = events
        result["event_count"] = len(events)
        result["matches"] = len(events) - 1 if len(events) > 1 else 0

    elif mode == "time_prefix":
        m = compiled.search(sample)
        if m:
            start, end = m.start(), m.end()
            highlighted = sample[:start] + ">>" + sample[start:end] + "<<" + sample[end:]
            result["match"] = m.group()
            result["start"] = start
            result["end"] = end
            result["highlighted"] = highlighted
            result["matches"] = 1
            # Show per-line first-match positions
            lines: List[Dict[str, Any]] = []
            for idx, line in enumerate(sample.split("\n")):
                lm = compiled.search(line)
                if lm:
                    lines.append({"line": idx + 1, "pos": lm.start(), "match": lm.group()})
            result["line_matches"] = lines
            result["match_count"] = len(lines)
            result["matches"] = len(lines)
        else:
            result["match"] = None
            result["matches"] = 0
            result["highlighted"] = sample

    elif mode == "extraction":
        all_matches: List[Dict[str, Any]] = []
        for m in compiled.finditer(sample):
            entry: Dict[str, Any] = {
                "full_match": m.group(),
                "start": m.start(),
                "end": m.end(),
            }
            if m.groups():
                entry["groups"] = list(m.groups())
            if m.groupdict():
                entry["named_groups"] = {k: v for k, v in m.groupdict().items() if v is not None}
            all_matches.append(entry)
        result["matches"] = len(all_matches)
        result["extractions"] = all_matches

    else:
        return {"ok": False, "mode": mode, "error": f"Unknown mode '{mode}'. Use: line_breaker, time_prefix, extraction"}

    return result
