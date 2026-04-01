"""
Report generation for the Splunk Upgrade Readiness Testing System.

Combines static analysis findings, container test results, CIM compliance
data, and UF analysis into a single UpgradeImpactReport and serialises it
to JSON or Markdown.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from chat_app.upgrade_readiness.models import (
    ContainerTestResult,
    TestStatus,
    UpgradeFinding,
    UpgradeImpactReport,
    UpgradeRisk,
)

logger = logging.getLogger(__name__)

# Default directory for saved reports
DEFAULT_REPORTS_DIR = "/app/data/upgrade_readiness/reports"

# Risk level ordering (highest first) used for Markdown section ordering
_RISK_ORDER = [UpgradeRisk.CRITICAL, UpgradeRisk.HIGH, UpgradeRisk.MEDIUM, UpgradeRisk.LOW, UpgradeRisk.INFO]

# Markdown heading separator
_HR = "---"


class ReportBuilder:
    """
    Assembles and serialises upgrade impact reports.

    Accepts the raw analysis outputs (findings list, optional container
    results, optional UF analysis) and produces an UpgradeImpactReport that
    can be saved as JSON or rendered as Markdown.
    """

    def __init__(self, reports_dir: str = DEFAULT_REPORTS_DIR) -> None:
        self.reports_dir = Path(reports_dir)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Main builder
    # ------------------------------------------------------------------

    def build_report(
        self,
        analysis_result: UpgradeImpactReport,
        container_results: Optional[List[ContainerTestResult]] = None,
        uf_results: Optional[Any] = None,
    ) -> UpgradeImpactReport:
        """
        Combine static analysis and optional runtime data into one report.

        This is a lightweight merge step: container test failures may
        escalate the overall risk level.  The report_id, timestamps, and
        finding list from analysis_result are preserved.

        Args:
            analysis_result:   The UpgradeImpactReport produced by the static
                               analysis pipeline (conf_differ + impact_scorer).
            container_results: Optional list of ContainerTestResult from a live
                               container test run.
            uf_results:        Optional UFUpgradeReport from uf_analyzer.

        Returns:
            An UpgradeImpactReport (potentially with upgraded overall_risk
            and richer risk_counts).
        """
        # Start from the static analysis report; we may need to upgrade risk
        report = analysis_result

        container_failure_count = 0
        if container_results:
            container_failure_count = sum(
                1 for r in container_results
                if r.status in (TestStatus.FAILED, TestStatus.ERROR)
            )
            if container_failure_count > 0 and report.overall_risk < UpgradeRisk.HIGH:
                # Escalate risk when live tests fail
                report.overall_risk = UpgradeRisk.HIGH
                report.recommendation = (
                    f"{report.recommendation} "
                    f"Container tests detected {container_failure_count} failure(s) — "
                    "review before proceeding."
                ).strip()

        # Enrich risk_counts with container test summary
        report.risk_counts["container_failures"] = container_failure_count
        if container_results:
            report.risk_counts["container_passed"] = sum(
                1 for r in container_results if r.status == TestStatus.PASSED
            )

        # Attach UF summary if present
        if uf_results is not None:
            uf_risk = getattr(uf_results, "overall_risk", None)
            if uf_risk and uf_risk > report.overall_risk:
                report.overall_risk = uf_risk

        logger.info(
            "[REPORT] Built report %s for %s %s→%s: risk=%s, findings=%d",
            report.report_id,
            report.app_id,
            report.from_version,
            report.to_version,
            report.overall_risk.value,
            len(report.findings),
        )
        return report

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_json(self, report: UpgradeImpactReport) -> str:
        """
        Serialise an UpgradeImpactReport to a JSON string.

        All enum values are serialised to their string value.  Datetime
        objects are serialised to ISO 8601 strings.

        Args:
            report: The report to serialise.

        Returns:
            A formatted JSON string.
        """
        findings_list = [
            {
                "finding_id": f.finding_id,
                "risk": f.risk.value,
                "category": f.category.value,
                "conf_type": f.conf_type,
                "stanza": f.stanza,
                "key": f.key,
                "description": f.description,
                "old_value": f.old_value,
                "new_value": f.new_value,
                "local_value": f.local_value,
                "recommendation": f.recommendation,
                "app_id": f.app_id,
            }
            for f in report.findings
        ]

        doc: Dict[str, Any] = {
            "report_id": report.report_id,
            "app_id": report.app_id,
            "from_version": report.from_version,
            "to_version": report.to_version,
            "cluster": report.cluster,
            "overall_risk": report.overall_risk.value,
            "recommendation": report.recommendation,
            "generated_at": report.generated_at.isoformat(),
            "risk_counts": {
                "CRITICAL": report.critical_count,
                "HIGH": report.high_count,
                "MEDIUM": report.medium_count,
                "LOW": report.low_count,
                "INFO": report.info_count,
                **{k: v for k, v in report.risk_counts.items()
                   if k not in ("CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO")},
            },
            "affected_conf_types": report.affected_conf_types,
            "findings": findings_list,
        }
        return json.dumps(doc, indent=2, default=str)

    def to_markdown(self, report: UpgradeImpactReport) -> str:
        """
        Generate a human-readable Markdown report.

        Sections:
        1. Summary (risk level, recommendation, counts)
        2. Findings by severity (CRITICAL first)
        3. Affected Conf Types
        4. Remediation Plan

        Args:
            report: The report to render.

        Returns:
            Markdown-formatted string.
        """
        lines: List[str] = []
        risk_emoji = {
            "CRITICAL": "🔴",
            "HIGH": "🟠",
            "MEDIUM": "🟡",
            "LOW": "🔵",
            "INFO": "⚪",
        }

        # ------------------------------------------------------------------
        # Title
        # ------------------------------------------------------------------
        lines.append(f"# Upgrade Readiness Report: {report.app_id}")
        lines.append("")
        lines.append(
            f"**Version:** `{report.from_version}` → `{report.to_version}`  "
        )
        lines.append(f"**Cluster:** `{report.cluster}`  ")
        lines.append(
            f"**Generated:** {report.generated_at.strftime('%Y-%m-%d %H:%M UTC')}  "
        )
        lines.append(f"**Report ID:** `{report.report_id}`  ")
        lines.append("")
        lines.append(_HR)

        # ------------------------------------------------------------------
        # Summary
        # ------------------------------------------------------------------
        lines.append("## Summary")
        lines.append("")
        risk_icon = risk_emoji.get(report.overall_risk.value, "")
        lines.append(f"**Overall Risk:** {risk_icon} **{report.overall_risk.value}**")
        lines.append("")
        lines.append(f"**Recommendation:** {report.recommendation}")
        lines.append("")
        lines.append("### Finding Counts")
        lines.append("")
        lines.append("| Severity | Count |")
        lines.append("|----------|-------|")
        for risk in _RISK_ORDER:
            count = sum(1 for f in report.findings if f.risk == risk)
            icon = risk_emoji.get(risk.value, "")
            lines.append(f"| {icon} {risk.value} | {count} |")

        # Container test summary if present
        if "container_failures" in report.risk_counts:
            lines.append("")
            lines.append("### Container Test Results")
            passed = report.risk_counts.get("container_passed", 0)
            failed = report.risk_counts.get("container_failures", 0)
            lines.append(f"- Passed: **{passed}**")
            lines.append(f"- Failed: **{failed}**")

        lines.append("")
        lines.append(_HR)

        # ------------------------------------------------------------------
        # Findings by severity
        # ------------------------------------------------------------------
        lines.append("## Findings by Severity")
        lines.append("")

        for risk in _RISK_ORDER:
            risk_findings = [f for f in report.findings if f.risk == risk]
            if not risk_findings:
                continue

            icon = risk_emoji.get(risk.value, "")
            lines.append(f"### {icon} {risk.value} ({len(risk_findings)})")
            lines.append("")

            for finding in risk_findings:
                lines.append(f"#### `{finding.conf_type}` / `{finding.stanza}`")
                lines.append("")
                lines.append(f"- **Category:** {finding.category.value}")
                if finding.key:
                    lines.append(f"- **Key:** `{finding.key}`")
                lines.append(f"- **Description:** {finding.description}")
                if finding.old_value is not None:
                    lines.append(f"- **Old value:** `{finding.old_value}`")
                if finding.new_value is not None:
                    lines.append(f"- **New value:** `{finding.new_value}`")
                if finding.local_value is not None:
                    lines.append(f"- **Local override:** `{finding.local_value}`")
                lines.append(f"- **Recommendation:** {finding.recommendation}")
                lines.append("")

        lines.append(_HR)

        # ------------------------------------------------------------------
        # Affected conf types
        # ------------------------------------------------------------------
        if report.affected_conf_types:
            lines.append("## Affected Conf Types")
            lines.append("")
            for conf_type in sorted(set(report.affected_conf_types)):
                lines.append(f"- `{conf_type}.conf`")
            lines.append("")
            lines.append(_HR)

        # ------------------------------------------------------------------
        # Remediation plan
        # ------------------------------------------------------------------
        lines.append("## Remediation Plan")
        lines.append("")
        critical_findings = [f for f in report.findings if f.risk == UpgradeRisk.CRITICAL]
        high_findings = [f for f in report.findings if f.risk == UpgradeRisk.HIGH]

        if not critical_findings and not high_findings:
            lines.append(
                "No critical or high-risk findings. Review medium-risk items "
                "before proceeding with the upgrade."
            )
        else:
            lines.append(
                "Address the following items **before** upgrading to production:"
            )
            lines.append("")
            step = 1
            for finding in critical_findings + high_findings:
                stanza_ref = f"`{finding.conf_type}` / `{finding.stanza}`"
                if finding.key:
                    stanza_ref += f" / `{finding.key}`"
                lines.append(
                    f"{step}. **{finding.risk.value}**: {stanza_ref} — {finding.recommendation}"
                )
                step += 1

        lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_report(
        self, report: UpgradeImpactReport, path: Optional[str] = None
    ) -> str:
        """
        Save the report as a JSON file.

        Args:
            report: The report to persist.
            path:   Optional explicit path.  If omitted, the report is saved
                    to ``<reports_dir>/<report_id>.json``.

        Returns:
            Absolute path to the saved file.
        """
        if path is None:
            dest = self.reports_dir / f"{report.report_id}.json"
        else:
            dest = Path(path)
            dest.parent.mkdir(parents=True, exist_ok=True)

        dest.write_text(self.to_json(report), encoding="utf-8")
        logger.info("[REPORT] Saved report %s to %s", report.report_id, dest)
        return str(dest)

    def load_report(self, report_id: str) -> Optional[UpgradeImpactReport]:
        """
        Load a previously saved report from disk.

        Args:
            report_id: The UUID report identifier.

        Returns:
            An UpgradeImpactReport, or None if the file is not found or
            cannot be parsed.
        """
        from chat_app.upgrade_readiness.models import (
            FindingCategory,
        )

        path = self.reports_dir / f"{report_id}.json"
        if not path.is_file():
            logger.warning("[REPORT] Report file not found: %s", path)
            return None

        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.error("[REPORT] Failed to parse report %s: %s", report_id, exc)
            return None

        findings = []
        for f_dict in raw.get("findings", []):
            try:
                findings.append(
                    UpgradeFinding(
                        finding_id=f_dict["finding_id"],
                        risk=UpgradeRisk(f_dict["risk"]),
                        category=FindingCategory(f_dict["category"]),
                        conf_type=f_dict["conf_type"],
                        stanza=f_dict["stanza"],
                        key=f_dict.get("key"),
                        description=f_dict["description"],
                        old_value=f_dict.get("old_value"),
                        new_value=f_dict.get("new_value"),
                        local_value=f_dict.get("local_value"),
                        recommendation=f_dict["recommendation"],
                        app_id=f_dict.get("app_id", ""),
                    )
                )
            except (KeyError, ValueError) as exc:
                logger.warning("[REPORT] Skipping malformed finding: %s", exc)

        try:
            generated_at = datetime.fromisoformat(raw.get("generated_at", ""))
        except (ValueError, TypeError):
            generated_at = datetime.now(timezone.utc)

        return UpgradeImpactReport(
            report_id=raw.get("report_id", report_id),
            app_id=raw.get("app_id", ""),
            from_version=raw.get("from_version", ""),
            to_version=raw.get("to_version", ""),
            cluster=raw.get("cluster", ""),
            findings=findings,
            overall_risk=UpgradeRisk(raw.get("overall_risk", UpgradeRisk.INFO.value)),
            recommendation=raw.get("recommendation", ""),
            generated_at=generated_at,
            risk_counts=raw.get("risk_counts", {}),
            affected_conf_types=raw.get("affected_conf_types", []),
        )

    def list_reports(self) -> List[Dict[str, Any]]:
        """
        Return a summary list of all saved reports.

        Returns:
            List of dicts with keys: report_id, app_id, from_version,
            to_version, cluster, overall_risk, generated_at, path.
        """
        summaries: List[Dict[str, Any]] = []
        for json_file in sorted(self.reports_dir.glob("*.json"), reverse=True):
            try:
                raw = json.loads(json_file.read_text(encoding="utf-8"))
                summaries.append(
                    {
                        "report_id": raw.get("report_id", json_file.stem),
                        "app_id": raw.get("app_id", ""),
                        "from_version": raw.get("from_version", ""),
                        "to_version": raw.get("to_version", ""),
                        "cluster": raw.get("cluster", ""),
                        "overall_risk": raw.get("overall_risk", ""),
                        "generated_at": raw.get("generated_at", ""),
                        "path": str(json_file),
                    }
                )
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("[REPORT] Skipping unreadable report %s: %s", json_file, exc)

        return summaries
