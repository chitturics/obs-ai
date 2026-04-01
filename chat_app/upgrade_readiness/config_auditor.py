"""Configuration Auditor — scans conf files against the Breaking Changes Database.

This is the CORE VALUE engine. It takes your actual Splunk configuration files
and cross-references every setting against known breaking changes for the
target version, producing specific, actionable findings.

Example:
    auditor = ConfigAuditor()
    findings = auditor.audit(
        conf_files={"server.conf": {"sslConfig": {"sslVersions": "tls1.0"}}},
        from_version="9.3.0",
        to_version="10.3.0",
    )
    # Returns: [Finding(severity="blocker", title="Minimum TLS 1.2 enforced", ...)]
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from chat_app.upgrade_readiness.breaking_changes_db import (
    BreakingChange,
    BreakingChangesDB,
    get_breaking_changes_db,
)

logger = logging.getLogger(__name__)


@dataclass
class AuditFinding:
    """A specific configuration issue found during audit."""
    breaking_change_id: str
    severity: str  # blocker, warning, info
    title: str
    description: str
    conf_file: str = ""
    stanza: str = ""
    key: str = ""
    current_value: str = ""
    migration: str = ""
    category: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.breaking_change_id,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "conf_file": self.conf_file,
            "stanza": self.stanza,
            "key": self.key,
            "current_value": self.current_value,
            "migration": self.migration,
            "category": self.category,
        }


@dataclass
class AuditReport:
    """Complete audit report."""
    from_version: str = ""
    to_version: str = ""
    findings: List[AuditFinding] = field(default_factory=list)
    blockers: int = 0
    warnings: int = 0
    infos: int = 0
    readiness_score: int = 100  # 0-100, starts at 100, deducted per finding
    recommendation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "from_version": self.from_version,
            "to_version": self.to_version,
            "findings": [f.to_dict() for f in self.findings],
            "summary": {
                "blockers": self.blockers,
                "warnings": self.warnings,
                "infos": self.infos,
                "total": len(self.findings),
                "readiness_score": self.readiness_score,
                "recommendation": self.recommendation,
            },
        }


class ConfigAuditor:
    """Audits Splunk configuration against the breaking changes database."""

    def __init__(self, db: Optional[BreakingChangesDB] = None):
        self._db = db or get_breaking_changes_db()

    def audit(
        self,
        conf_files: Dict[str, Dict[str, Dict[str, str]]],
        from_version: str,
        to_version: str,
    ) -> AuditReport:
        """Run a full configuration audit.

        Args:
            conf_files: Parsed conf data. Structure: {conf_name: {stanza: {key: value}}}
                        e.g., {"server": {"sslConfig": {"sslVersions": "tls1.0"}}}
            from_version: Current Splunk version (e.g., "9.3.0")
            to_version: Target Splunk version (e.g., "10.3.0")

        Returns:
            AuditReport with all findings, counts, and readiness score.
        """
        report = AuditReport(from_version=from_version, to_version=to_version)

        # Get all breaking changes between versions
        changes = self._db.get_changes_between(from_version, to_version)
        if not changes:
            report.recommendation = "No known breaking changes between these versions."
            return report

        # Check each breaking change against the configuration
        for change in changes:
            finding = self._check_change(change, conf_files)
            if finding:
                report.findings.append(finding)

        # Also run generic detection patterns
        self._run_generic_checks(conf_files, from_version, to_version, report)

        # Count by severity
        report.blockers = sum(1 for f in report.findings if f.severity == "blocker")
        report.warnings = sum(1 for f in report.findings if f.severity == "warning")
        report.infos = sum(1 for f in report.findings if f.severity == "info")

        # Calculate readiness score
        report.readiness_score = max(0, 100 - (report.blockers * 30) - (report.warnings * 10) - (report.infos * 2))

        # Generate recommendation
        if report.blockers > 0:
            report.recommendation = f"CANNOT UPGRADE: {report.blockers} blocker(s) must be resolved first."
        elif report.warnings > 3:
            report.recommendation = f"PROCEED WITH CAUTION: {report.warnings} warnings to review."
        elif report.warnings > 0:
            report.recommendation = f"LOW RISK: {report.warnings} minor item(s) to review."
        else:
            report.recommendation = "READY TO UPGRADE: No configuration issues found."

        return report

    def _check_change(
        self,
        change: BreakingChange,
        conf_files: Dict[str, Dict[str, Dict[str, str]]],
    ) -> Optional[AuditFinding]:
        """Check if a specific breaking change affects the given configuration."""

        # Skip non-conf changes (hardware, platform checks)
        if not change.conf_file and not change.detection:
            return None

        # Check conf_file + key match
        if change.conf_file:
            conf_name = change.conf_file.replace(".conf", "")
            conf_data = conf_files.get(conf_name, {})

            if change.stanza and change.key:
                # Specific stanza + key check
                stanza_data = conf_data.get(change.stanza, {})
                if change.key in stanza_data:
                    return AuditFinding(
                        breaking_change_id=change.id,
                        severity=change.severity,
                        title=change.title,
                        description=change.description,
                        conf_file=change.conf_file,
                        stanza=change.stanza,
                        key=change.key,
                        current_value=stanza_data[change.key],
                        migration=change.migration,
                        category=change.category,
                    )
            elif change.key:
                # Key check across all stanzas
                for stanza_name, stanza_data in conf_data.items():
                    if change.key in stanza_data:
                        return AuditFinding(
                            breaking_change_id=change.id,
                            severity=change.severity,
                            title=change.title,
                            description=change.description,
                            conf_file=change.conf_file,
                            stanza=stanza_name,
                            key=change.key,
                            current_value=stanza_data[change.key],
                            migration=change.migration,
                            category=change.category,
                        )

        # Check detection pattern (grep-style)
        if change.detection and "grep" in change.detection.lower():
            search_term = ""
            m = re.search(r"grep.*for\s+(\S+)", change.detection)
            if m:
                search_term = m.group(1)
            if search_term:
                for conf_name, stanzas in conf_files.items():
                    for stanza_name, keys in stanzas.items():
                        for key, value in keys.items():
                            if search_term in key or search_term in str(value):
                                return AuditFinding(
                                    breaking_change_id=change.id,
                                    severity=change.severity,
                                    title=change.title,
                                    description=change.description,
                                    conf_file=f"{conf_name}.conf",
                                    stanza=stanza_name,
                                    key=key,
                                    current_value=str(value),
                                    migration=change.migration,
                                    category=change.category,
                                )

        return None

    def _run_generic_checks(
        self,
        conf_files: Dict[str, Dict[str, Dict[str, str]]],
        from_version: str,
        to_version: str,
        report: AuditReport,
    ) -> None:
        """Run generic configuration checks not tied to specific breaking changes."""

        # Check for deprecated TLS versions
        server_conf = conf_files.get("server", {})
        for stanza_name, keys in server_conf.items():
            ssl_versions = keys.get("sslVersions", "")
            if "tls1.0" in ssl_versions.lower() or "ssl3" in ssl_versions.lower():
                report.findings.append(AuditFinding(
                    breaking_change_id="GENERIC-TLS",
                    severity="blocker",
                    title="Insecure TLS version configured",
                    description=f"Found deprecated TLS version in [{stanza_name}]: {ssl_versions}",
                    conf_file="server.conf",
                    stanza=stanza_name,
                    key="sslVersions",
                    current_value=ssl_versions,
                    migration="Remove tls1.0/ssl3, use 'tls1.2' only",
                    category="security",
                ))

        # Check for master_uri (deprecated in 10.0+)
        if _version_ge(to_version, "10.0"):
            for stanza_name, keys in server_conf.items():
                if "master_uri" in keys:
                    report.findings.append(AuditFinding(
                        breaking_change_id="GENERIC-MASTER-URI",
                        severity="warning",
                        title="Deprecated master_uri setting",
                        description=f"master_uri found in [{stanza_name}]. Renamed to manager_uri in 10.0+",
                        conf_file="server.conf",
                        stanza=stanza_name,
                        key="master_uri",
                        current_value=keys["master_uri"],
                        migration="Rename to manager_uri",
                        category="configuration",
                    ))


def _version_ge(a: str, b: str) -> bool:
    """Check if version a >= version b."""
    try:
        at = tuple(int(x) for x in a.split(".")[:3])
        bt = tuple(int(x) for x in b.split(".")[:3])
        return at >= bt
    except (ValueError, TypeError):
        return False
