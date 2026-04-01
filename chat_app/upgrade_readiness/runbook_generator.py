"""Runbook Generator — synthesizes upgrade analysis findings into an ordered, actionable plan.

Takes ReadinessScore, AuditReport, BreakingChange list, and UpgradeFinding list and
produces a RunbookStep-per-phase upgrade plan with real Splunk CLI commands.

Usage:
    generator = RunbookGenerator()
    runbook = generator.generate(
        from_version="9.3.2",
        to_version="10.2.1",
        upgrade_type="splunk_core",
        config_audit=audit_report,
        conf_diff_findings=findings,
        readiness_score=score,
    )
    print(runbook.to_markdown())
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Phase ordering — determines the canonical upgrade sequence
# ---------------------------------------------------------------------------

PHASE_ORDER = [
    "pre-upgrade",
    "infrastructure",
    "configuration",
    "app-updates",
    "execution",
    "validation",
    "rollback",
]

# Minutes per step category — used for time estimation
_DEFAULT_STEP_MINUTES = {
    "pre-upgrade": 10,
    "infrastructure": 20,
    "configuration": 15,
    "app-updates": 10,
    "execution": 30,
    "validation": 15,
    "rollback": 20,
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class RunbookStep:
    """A single executable step in an upgrade runbook."""

    phase: str                  # One of PHASE_ORDER values
    order: int                  # Sequence number within the phase (1-based)
    title: str
    description: str
    commands: List[str]         # Actual commands to run, in order
    expected_output: str        # What success looks like
    risk_if_skipped: str        # What breaks if you skip this step
    estimated_minutes: int
    requires_downtime: bool

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phase": self.phase,
            "order": self.order,
            "title": self.title,
            "description": self.description,
            "commands": self.commands,
            "expected_output": self.expected_output,
            "risk_if_skipped": self.risk_if_skipped,
            "estimated_minutes": self.estimated_minutes,
            "requires_downtime": self.requires_downtime,
        }


@dataclass
class UpgradeRunbook:
    """Complete upgrade runbook with all phases and steps."""

    title: str
    from_version: str
    to_version: str
    generated_at: str
    readiness_score: int
    readiness_grade: str
    total_steps: int
    estimated_hours: float
    downtime_required: bool
    phases: Dict[str, List[RunbookStep]] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "from_version": self.from_version,
            "to_version": self.to_version,
            "generated_at": self.generated_at,
            "readiness_score": self.readiness_score,
            "readiness_grade": self.readiness_grade,
            "total_steps": self.total_steps,
            "estimated_hours": self.estimated_hours,
            "downtime_required": self.downtime_required,
            "phases": {
                phase: [step.to_dict() for step in steps]
                for phase, steps in self.phases.items()
            },
        }

    def to_markdown(self) -> str:
        """Render the runbook as GitHub-flavored Markdown."""
        lines: List[str] = []

        lines.append(f"# {self.title}")
        lines.append("")
        lines.append(f"**Generated:** {self.generated_at}  ")
        lines.append(f"**Upgrade path:** {self.from_version} → {self.to_version}  ")
        lines.append(f"**Readiness score:** {self.readiness_score}/100 ({self.readiness_grade})  ")
        lines.append(f"**Estimated duration:** {self.estimated_hours:.1f} hours  ")
        lines.append(f"**Downtime required:** {'YES' if self.downtime_required else 'No'}  ")
        lines.append(f"**Total steps:** {self.total_steps}  ")
        lines.append("")
        lines.append("---")
        lines.append("")

        for phase_name in PHASE_ORDER:
            steps = self.phases.get(phase_name, [])
            if not steps:
                continue

            lines.append(f"## Phase: {phase_name.replace('-', ' ').title()}")
            lines.append("")

            for step in steps:
                downtime_badge = " ⚠️ DOWNTIME" if step.requires_downtime else ""
                lines.append(f"### Step {step.order}: {step.title}{downtime_badge}")
                lines.append("")
                lines.append(f"**Description:** {step.description}  ")
                lines.append(f"**Estimated time:** {step.estimated_minutes} minutes  ")
                lines.append(f"**Risk if skipped:** {step.risk_if_skipped}  ")
                lines.append("")

                if step.commands:
                    lines.append("**Commands:**")
                    lines.append("```bash")
                    lines.extend(step.commands)
                    lines.append("```")
                    lines.append("")

                if step.expected_output:
                    lines.append(f"**Expected output:** {step.expected_output}  ")
                    lines.append("")

                lines.append("---")
                lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class RunbookGenerator:
    """Generates a complete upgrade runbook from analysis results."""

    def generate(
        self,
        from_version: str,
        to_version: str,
        upgrade_type: str = "splunk_core",
        config_audit: Optional[Any] = None,
        conf_diff_findings: Optional[List[Any]] = None,
        readiness_score: Optional[Any] = None,
        breaking_changes: Optional[List[Any]] = None,
        app_id: str = "",
        cluster: str = "",
    ) -> UpgradeRunbook:
        """Generate a complete upgrade runbook.

        Args:
            from_version:       Currently installed version string.
            to_version:         Target version string.
            upgrade_type:       One of: splunk_core, es, itsi, uf, app, ta.
            config_audit:       AuditReport from ConfigAuditor (optional).
            conf_diff_findings: List of UpgradeFinding from conf_differ (optional).
            readiness_score:    ReadinessScore from ReadinessScorer (optional).
            breaking_changes:   List of BreakingChange objects (optional).
            app_id:             App identifier (for app/TA upgrades).
            cluster:            Target cluster name.

        Returns:
            UpgradeRunbook with ordered phases and real commands.
        """
        findings = conf_diff_findings or []
        bc_list = breaking_changes or []
        audit_findings = list(getattr(config_audit, "findings", []))

        has_blockers = (
            getattr(config_audit, "blockers", 0) > 0
            or any(getattr(bc, "severity", "") == "blocker" for bc in bc_list)
            or any(
                getattr(f, "risk", None) is not None
                and getattr(f.risk, "value", str(f.risk)) == "CRITICAL"
                for f in findings
            )
        )

        overall_score = getattr(readiness_score, "overall_score", 100) if readiness_score else 100
        grade = getattr(readiness_score, "grade", "PASS") if readiness_score else "PASS"

        phases: Dict[str, List[RunbookStep]] = {}

        # Build each phase
        phases["pre-upgrade"] = self._build_pre_upgrade_phase(
            from_version, to_version, app_id, cluster, upgrade_type
        )

        infra_steps = self._build_infrastructure_phase(
            from_version, to_version, bc_list, audit_findings, has_blockers
        )
        if infra_steps:
            phases["infrastructure"] = infra_steps

        config_steps = self._build_configuration_phase(audit_findings, findings, to_version)
        if config_steps:
            phases["configuration"] = config_steps

        app_steps = self._build_app_updates_phase(findings, app_id)
        if app_steps:
            phases["app-updates"] = app_steps

        phases["execution"] = self._build_execution_phase(
            from_version, to_version, upgrade_type, cluster
        )

        phases["validation"] = self._build_validation_phase(
            from_version, to_version, upgrade_type
        )

        phases["rollback"] = self._build_rollback_phase(
            from_version, to_version, upgrade_type
        )

        # Compute totals
        all_steps = [s for steps in phases.values() for s in steps]
        total_minutes = sum(s.estimated_minutes for s in all_steps)
        downtime_required = any(s.requires_downtime for s in all_steps)

        title = self._make_title(from_version, to_version, upgrade_type, app_id)

        runbook = UpgradeRunbook(
            title=title,
            from_version=from_version,
            to_version=to_version,
            generated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
            readiness_score=overall_score,
            readiness_grade=grade,
            total_steps=len(all_steps),
            estimated_hours=round(total_minutes / 60, 2),
            downtime_required=downtime_required,
            phases=phases,
        )

        logger.info(
            "[RUNBOOK] Generated: %s → %s | type=%s | steps=%d | hours=%.1f",
            from_version, to_version, upgrade_type, len(all_steps), runbook.estimated_hours,
        )
        return runbook

    # ------------------------------------------------------------------
    # Phase builders
    # ------------------------------------------------------------------

    def _build_pre_upgrade_phase(
        self,
        from_version: str,
        to_version: str,
        app_id: str,
        cluster: str,
        upgrade_type: str,
    ) -> List[RunbookStep]:
        """Always-present pre-upgrade steps: backup, baseline, health check."""
        steps: List[RunbookStep] = []
        order = 1

        # Step 1 — Backup current config
        steps.append(RunbookStep(
            phase="pre-upgrade",
            order=order,
            title="Backup Splunk configuration",
            description=(
                "Create a full backup of $SPLUNK_HOME/etc before any changes. "
                "This backup is the primary rollback artifact."
            ),
            commands=[
                "# Set your Splunk home if non-standard",
                "export SPLUNK_HOME=/opt/splunk",
                "",
                "# Create timestamped backup archive",
                f"tar czf /backup/splunk_etc_{from_version.replace('.', '_')}_$(date +%Y%m%d_%H%M%S).tar.gz "
                "-C $SPLUNK_HOME etc/",
                "",
                "# Verify archive integrity",
                "tar tzf /backup/splunk_etc_*.tar.gz | tail -5",
            ],
            expected_output="tar exits 0, file listing shows etc/ contents",
            risk_if_skipped="No rollback artifact — full recovery requires reinstallation",
            estimated_minutes=10,
            requires_downtime=False,
        ))
        order += 1

        # Step 2 — Capture health baseline
        steps.append(RunbookStep(
            phase="pre-upgrade",
            order=order,
            title="Capture health baseline",
            description=(
                "Record the current health state of Splunk so post-upgrade validation "
                "has a known-good reference point."
            ),
            commands=[
                "export SPLUNK_HOME=/opt/splunk",
                "BASELINE_FILE=/tmp/splunk_baseline_$(date +%Y%m%d).txt",
                "",
                "# Splunk process and version",
                "$SPLUNK_HOME/bin/splunk version >> $BASELINE_FILE",
                "$SPLUNK_HOME/bin/splunk status >> $BASELINE_FILE",
                "",
                "# License usage",
                "$SPLUNK_HOME/bin/splunk show license-usage >> $BASELINE_FILE 2>&1",
                "",
                "# Cluster status (if indexer cluster)",
                "$SPLUNK_HOME/bin/splunk show cluster-status --verbose >> $BASELINE_FILE 2>&1",
                "",
                "# Active saved searches count (REST via curl)",
                "curl -sk -u admin:changeme https://localhost:8089/services/saved/searches "
                "--get -d count=0 -d output_mode=json | python3 -c "
                "\"import json,sys; d=json.load(sys.stdin); "
                "print('saved_searches:', len(d.get('entry',[])))\" >> $BASELINE_FILE",
                "",
                "echo \"Baseline saved to $BASELINE_FILE\"",
            ],
            expected_output="Baseline file created with version, status, and search counts",
            risk_if_skipped="Cannot verify post-upgrade state matches pre-upgrade expectations",
            estimated_minutes=5,
            requires_downtime=False,
        ))
        order += 1

        # Step 3 — Verify backups are current
        steps.append(RunbookStep(
            phase="pre-upgrade",
            order=order,
            title="Verify backups are accessible and current",
            description=(
                "Confirm that the backup created in Step 1 is readable and that "
                "any secondary backups (Git, NFS, S3) are also current."
            ),
            commands=[
                "# Check backup file size and age",
                "ls -lh /backup/splunk_etc_*.tar.gz | tail -3",
                "",
                "# Spot-check archive contents",
                "tar tzf $(ls -t /backup/splunk_etc_*.tar.gz | head -1) | grep 'etc/system/local' | head -5",
                "",
                "# If using Git for conf management — confirm clean commit",
                "# git -C /repo/splunk status",
                "# git -C /repo/splunk log --oneline -5",
            ],
            expected_output="Backup file > 0 bytes, archive lists etc/system/local entries",
            risk_if_skipped="Stale or corrupted backup discovered only after upgrade failure",
            estimated_minutes=5,
            requires_downtime=False,
        ))
        order += 1

        # Step 4 — Document current state
        steps.append(RunbookStep(
            phase="pre-upgrade",
            order=order,
            title="Document current deployment state",
            description=(
                "Capture app versions, index counts, and forwarder counts "
                "to compare against post-upgrade state."
            ),
            commands=[
                "export SPLUNK_HOME=/opt/splunk",
                "",
                "# App versions via btool",
                "$SPLUNK_HOME/bin/splunk btool app list --app='*' 2>/dev/null | grep -E '^\\[|version' | head -40",
                "",
                "# Index configuration",
                "$SPLUNK_HOME/bin/splunk list index 2>/dev/null | head -20",
                "",
                "# Forwarder count from deployment server (if applicable)",
                "curl -sk -u admin:changeme https://localhost:8089/services/deployment/server/clients "
                "--get -d count=0 -d output_mode=json | python3 -c "
                "\"import json,sys; d=json.load(sys.stdin); "
                "print('forwarders:', len(d.get('entry',[])))\" 2>/dev/null || echo 'Not a deployment server'",
            ],
            expected_output="List of installed apps with versions, index names",
            risk_if_skipped="Cannot detect apps or indexes lost or changed during upgrade",
            estimated_minutes=5,
            requires_downtime=False,
        ))
        order += 1

        return steps

    def _build_infrastructure_phase(
        self,
        from_version: str,
        to_version: str,
        bc_list: List[Any],
        audit_findings: List[Any],
        has_blockers: bool,
    ) -> List[RunbookStep]:
        """Infrastructure steps driven by breaking changes (CPU, OS, TLS, disk)."""
        steps: List[RunbookStep] = []
        order = 1

        # Check if hardware/CPU breaking changes are present
        cpu_bc = [bc for bc in bc_list if "cpu" in getattr(bc, "category", "").lower()
                  or "hardware" in getattr(bc, "category", "").lower()]
        if cpu_bc:
            steps.append(RunbookStep(
                phase="infrastructure",
                order=order,
                title="Verify CPU and memory requirements",
                description=(
                    f"Splunk {to_version} has updated hardware requirements. "
                    "Verify each node meets minimums before proceeding."
                ),
                commands=[
                    "# CPU core count (minimum varies by role)",
                    "nproc",
                    "grep -c ^processor /proc/cpuinfo",
                    "",
                    "# Available memory",
                    "free -h",
                    "",
                    "# Disk space on $SPLUNK_HOME partition",
                    "df -h /opt/splunk",
                    "",
                    "# Check Splunk's own resource usage",
                    "/opt/splunk/bin/splunk search '| rest /services/server/info' "
                    "-auth admin:changeme -output_mode json 2>/dev/null | "
                    "python3 -c \"import json,sys; d=json.load(sys.stdin); "
                    "[print(e.get('content',{}).get('cpu_arch',''), "
                    "e.get('content',{}).get('numberOfCores','')) for e in d.get('results',[])]\"",
                ],
                expected_output="CPU count >= 8, RAM >= 12 GB, disk >= 10 GB free",
                risk_if_skipped="Splunk may start slowly or fail under load on undersized hardware",
                estimated_minutes=10,
                requires_downtime=False,
            ))
            order += 1

        # TLS-related blockers
        tls_findings = [
            f for f in audit_findings
            if "tls" in getattr(f, "title", "").lower()
            or "ssl" in getattr(f, "title", "").lower()
        ]
        tls_bc = [
            bc for bc in bc_list
            if "tls" in getattr(bc, "title", "").lower()
            or "ssl" in getattr(bc, "title", "").lower()
        ]
        if tls_findings or tls_bc:
            steps.append(RunbookStep(
                phase="infrastructure",
                order=order,
                title="Update TLS/SSL configuration to meet minimum version requirements",
                description=(
                    f"Splunk {to_version} enforces a minimum of TLS 1.2. "
                    "Deprecated TLS 1.0 and SSL 3 settings must be removed before upgrade."
                ),
                commands=[
                    "# Find all sslVersions settings across conf files",
                    "grep -r 'sslVersions' /opt/splunk/etc/system/local/ "
                    "/opt/splunk/etc/apps/*/local/ 2>/dev/null",
                    "",
                    "# Update sslVersions to TLS 1.2 only",
                    "# Edit /opt/splunk/etc/system/local/server.conf",
                    "# In [sslConfig] stanza:",
                    "#   sslVersions = tls1.2",
                    "",
                    "# Verify with btool",
                    "/opt/splunk/bin/splunk btool server list sslConfig --debug",
                ],
                expected_output="sslVersions = tls1.2 confirmed by btool",
                risk_if_skipped="Splunk will refuse to start if TLS 1.0 or SSL 3 is configured",
                estimated_minutes=20,
                requires_downtime=False,
            ))
            order += 1

        # Disk space check (always recommended for major version upgrades)
        if _version_major_bump(from_version, to_version):
            steps.append(RunbookStep(
                phase="infrastructure",
                order=order,
                title="Verify disk space for upgrade package",
                description=(
                    "A major version upgrade RPM or tarball typically requires "
                    "3-5 GB of free space during extraction."
                ),
                commands=[
                    "# Check all relevant mount points",
                    "df -h /opt /tmp /var 2>/dev/null",
                    "",
                    "# Estimated space needed for Splunk package",
                    "echo 'Upgrade package: ~1.5 GB compressed, ~4 GB extracted'",
                    "",
                    "# Download upgrade package (adjust URL/filename as appropriate)",
                    f"# wget -O /tmp/splunk-{to_version}-linux-2.6-x86_64.rpm "
                    f"https://download.splunk.com/products/splunk/releases/{to_version}/linux/"
                    f"splunk-{to_version}-linux-2.6-x86_64.rpm",
                ],
                expected_output="At least 5 GB free on /opt and /tmp partitions",
                risk_if_skipped="Upgrade extraction fails mid-process, leaving a broken installation",
                estimated_minutes=10,
                requires_downtime=False,
            ))
            order += 1

        return steps

    def _build_configuration_phase(
        self,
        audit_findings: List[Any],
        diff_findings: List[Any],
        to_version: str,
    ) -> List[RunbookStep]:
        """Configuration remediation steps from config auditor and conf diff."""
        steps: List[RunbookStep] = []
        order = 1

        # Group audit findings by conf_file for targeted steps
        findings_by_conf: Dict[str, List[Any]] = {}
        for finding in audit_findings:
            conf_file = getattr(finding, "conf_file", "unknown")
            findings_by_conf.setdefault(conf_file, []).append(finding)

        for conf_file, conf_findings in findings_by_conf.items():
            if not conf_file or conf_file == "unknown":
                continue

            # Build commands from findings
            commands = [f"# Configuration changes required in {conf_file}"]
            for finding in conf_findings:
                migration = getattr(finding, "migration", "")
                key = getattr(finding, "key", "")
                stanza = getattr(finding, "stanza", "")
                current_value = getattr(finding, "current_value", "")
                severity = getattr(finding, "severity", "info")

                severity_tag = "BLOCKER" if severity == "blocker" else "WARNING" if severity == "warning" else "INFO"
                commands.append(f"# [{severity_tag}] {getattr(finding, 'title', '')}")
                if stanza and key:
                    commands.append(f"# Location: [{stanza}] {key} = {current_value}")
                if migration:
                    commands.append(f"# Fix: {migration}")
                commands.append("")

            # Add concrete sed/grep commands for common patterns
            master_uri_findings = [f for f in conf_findings if getattr(f, "key", "") == "master_uri"]
            if master_uri_findings:
                commands.append("# Rename master_uri to manager_uri (Splunk 10.0+)")
                commands.append(f"sed -i 's/master_uri/manager_uri/g' "
                                f"/opt/splunk/etc/system/local/{conf_file}")
                commands.append("")
                commands.append("# Verify the change")
                commands.append(f"grep -n 'manager_uri\\|master_uri' "
                                f"/opt/splunk/etc/system/local/{conf_file}")

            blocker_count = sum(1 for f in conf_findings if getattr(f, "severity", "") == "blocker")
            warning_count = sum(1 for f in conf_findings if getattr(f, "severity", "") == "warning")
            risk_desc = (
                f"{blocker_count} blocker(s) will prevent upgrade"
                if blocker_count > 0
                else f"{warning_count} warning(s) may cause unexpected behavior"
            )

            steps.append(RunbookStep(
                phase="configuration",
                order=order,
                title=f"Remediate breaking changes in {conf_file}",
                description=(
                    f"Apply {len(conf_findings)} configuration fix(es) detected by the audit "
                    f"for the {conf_file} file."
                ),
                commands=commands,
                expected_output="btool validation passes with no errors for affected conf",
                risk_if_skipped=risk_desc,
                estimated_minutes=_DEFAULT_STEP_MINUTES["configuration"],
                requires_downtime=False,
            ))
            order += 1

        # High/critical diff findings that need manual remediation
        critical_diff = [
            f for f in diff_findings
            if getattr(getattr(f, "risk", None), "value", "") in ("CRITICAL", "HIGH")
        ]
        if critical_diff:
            commands = ["# High-risk conf diff findings requiring manual review"]
            for finding in critical_diff[:10]:  # Cap at 10 to keep runbook manageable
                commands.append(
                    f"# [{getattr(finding.risk, 'value', 'HIGH')}] "
                    f"{finding.conf_type} [{finding.stanza}] — {finding.description}"
                )
                commands.append(f"# Recommendation: {finding.recommendation}")
                if getattr(finding, "key", ""):
                    commands.append(
                        f"# Key: {finding.key}  "
                        f"Old: {finding.old_value!r}  "
                        f"New: {finding.new_value!r}  "
                        f"Local: {finding.local_value!r}"
                    )
                commands.append("")

            steps.append(RunbookStep(
                phase="configuration",
                order=order,
                title="Review and resolve high-risk conf diff findings",
                description=(
                    f"The three-way conf diff identified {len(critical_diff)} high/critical "
                    "findings where default values changed and you have local overrides. "
                    "Each must be reviewed before upgrade."
                ),
                commands=commands,
                expected_output="Each finding reviewed; local overrides confirmed intentional",
                risk_if_skipped="Local overrides may conflict with new defaults, causing data loss or incorrect behaviour",
                estimated_minutes=len(critical_diff) * 5,
                requires_downtime=False,
            ))
            order += 1

        return steps

    def _build_app_updates_phase(
        self,
        diff_findings: List[Any],
        app_id: str,
    ) -> List[RunbookStep]:
        """App updates required before platform upgrade."""
        steps: List[RunbookStep] = []

        # Only generate app update steps when doing a platform upgrade
        # and there are app-level findings
        if not app_id:
            return steps

        orphaned_local = [
            f for f in diff_findings
            if getattr(f, "category", None) is not None
            and getattr(f.category, "value", "") == "ORPHANED_LOCAL"
        ]
        if orphaned_local:
            steps.append(RunbookStep(
                phase="app-updates",
                order=1,
                title=f"Resolve orphaned local overrides in {app_id}",
                description=(
                    "These stanzas exist in local/ but the corresponding default/ stanza "
                    "has been removed in the new version. They are now orphaned. "
                    "Remove or migrate them before upgrading."
                ),
                commands=[
                    f"# List orphaned local settings in {app_id}",
                    f"grep -rn '.' /opt/splunk/etc/apps/{app_id}/local/ 2>/dev/null | head -30",
                    "",
                    "# For each orphaned stanza: either remove or migrate",
                    "# To remove an orphaned stanza:",
                    "# vi /opt/splunk/etc/apps/{app_id}/local/<conf_file>.conf",
                    "# Delete the [stanza_name] block and its keys",
                ],
                expected_output="No orphaned local stanzas remain",
                risk_if_skipped="Orphaned settings accumulate and may cause unexpected merges in future",
                estimated_minutes=10,
                requires_downtime=False,
            ))

        return steps

    def _build_execution_phase(
        self,
        from_version: str,
        to_version: str,
        upgrade_type: str,
        cluster: str,
    ) -> List[RunbookStep]:
        """Execution steps tailored to upgrade_type (cluster, standalone, ES, UF)."""
        steps: List[RunbookStep] = []

        if upgrade_type in ("splunk_core",):
            steps.extend(self._execution_cluster_steps(from_version, to_version))
        elif upgrade_type == "uf":
            steps.extend(self._execution_uf_steps(from_version, to_version))
        elif upgrade_type == "es":
            steps.extend(self._execution_es_steps(from_version, to_version))
        else:
            # Generic app/TA upgrade
            steps.extend(self._execution_app_steps(from_version, to_version, upgrade_type))

        return steps

    def _execution_cluster_steps(
        self, from_version: str, to_version: str
    ) -> List[RunbookStep]:
        """Cluster upgrade sequence: CM → indexers → search heads → deployer → forwarders."""
        rpm_filename = f"splunk-{to_version}-linux-2.6-x86_64.rpm"
        return [
            RunbookStep(
                phase="execution",
                order=1,
                title="Enable maintenance mode on cluster manager",
                description=(
                    "Maintenance mode prevents the cluster manager from triggering "
                    "bucket fixing and replication during indexer upgrades."
                ),
                commands=[
                    "# Enable maintenance mode",
                    "/opt/splunk/bin/splunk enable maintenance-mode --answer-yes",
                    "",
                    "# Verify maintenance mode is active",
                    "/opt/splunk/bin/splunk show maintenance-mode",
                ],
                expected_output="maintenance-mode = 1",
                risk_if_skipped="Cluster manager will attempt to re-replicate buckets during indexer restart, causing data inconsistency",
                estimated_minutes=5,
                requires_downtime=False,
            ),
            RunbookStep(
                phase="execution",
                order=2,
                title="Upgrade cluster manager",
                description=(
                    "The cluster manager must be upgraded first. "
                    "It remains backward compatible with older indexers during the window."
                ),
                commands=[
                    "# Stop Splunk on cluster manager",
                    "/opt/splunk/bin/splunk stop",
                    "",
                    f"# Install new version (RPM example)",
                    f"rpm -Uvh /tmp/{rpm_filename}",
                    "",
                    "# For tarball install:",
                    f"# tar xzf /tmp/splunk-{to_version}-Linux-x86_64.tgz -C /opt/",
                    "",
                    "# Start Splunk and accept license",
                    "/opt/splunk/bin/splunk start --accept-license --answer-yes",
                    "",
                    "# Verify version",
                    "/opt/splunk/bin/splunk version",
                ],
                expected_output=f"Splunk version shows {to_version}",
                risk_if_skipped="Indexers and search heads cannot be safely upgraded without CM upgrade first",
                estimated_minutes=20,
                requires_downtime=True,
            ),
            RunbookStep(
                phase="execution",
                order=3,
                title="Upgrade indexers in rolling batches",
                description=(
                    "Upgrade indexers in batches of 25% to maintain search availability. "
                    "Wait for cluster to stabilize between batches."
                ),
                commands=[
                    "# On each indexer (batch 1 of 4), run in parallel:",
                    "/opt/splunk/bin/splunk stop",
                    f"rpm -Uvh /tmp/{rpm_filename}",
                    "/opt/splunk/bin/splunk start --accept-license --answer-yes",
                    "",
                    "# After each batch: verify cluster status",
                    "/opt/splunk/bin/splunk show cluster-status --verbose",
                    "",
                    "# Wait for all peers to show 'Up' status before next batch",
                    "# cluster_status should show: All peers up, replication_factor met",
                ],
                expected_output="All indexer peers show Up status after each batch",
                risk_if_skipped="Upgrading all indexers simultaneously causes full cluster outage",
                estimated_minutes=45,
                requires_downtime=False,
            ),
            RunbookStep(
                phase="execution",
                order=4,
                title="Upgrade search heads",
                description=(
                    "Upgrade each search head after all indexers are upgraded. "
                    "For Search Head Cluster: use the SHC rolling upgrade procedure."
                ),
                commands=[
                    "# If Search Head Cluster — use rolling upgrade:",
                    "/opt/splunk/bin/splunk rolling-restart shcluster-members",
                    "",
                    "# For standalone search head:",
                    "/opt/splunk/bin/splunk stop",
                    f"rpm -Uvh /tmp/{rpm_filename}",
                    "/opt/splunk/bin/splunk start --accept-license --answer-yes",
                    "",
                    "# Verify search head cluster status",
                    "/opt/splunk/bin/splunk show shcluster-status 2>/dev/null || echo 'Standalone SH'",
                ],
                expected_output="All search heads running new version, SHC status shows healthy",
                risk_if_skipped="Old search heads may have compatibility issues querying upgraded indexers",
                estimated_minutes=30,
                requires_downtime=False,
            ),
            RunbookStep(
                phase="execution",
                order=5,
                title="Disable maintenance mode and verify cluster",
                description=(
                    "After all indexers and search heads are upgraded, "
                    "disable maintenance mode and confirm cluster health."
                ),
                commands=[
                    "# Disable maintenance mode",
                    "/opt/splunk/bin/splunk disable maintenance-mode",
                    "",
                    "# Verify cluster is healthy",
                    "/opt/splunk/bin/splunk show cluster-status --verbose",
                    "",
                    "# Check for any replication/fixup tasks pending",
                    "curl -sk -u admin:changeme https://localhost:8089/services/cluster/manager/peers "
                    "-d output_mode=json | python3 -c "
                    "\"import json,sys; peers=json.load(sys.stdin); "
                    "[print(e['title'], e.get('content',{}).get('status','?')) "
                    "for e in peers.get('entry',[])]\"",
                ],
                expected_output="maintenance-mode = 0, all peers Up, replication factor satisfied",
                risk_if_skipped="Cluster remains in maintenance mode, disabling automatic bucket replication",
                estimated_minutes=10,
                requires_downtime=False,
            ),
        ]

    def _execution_uf_steps(
        self, from_version: str, to_version: str
    ) -> List[RunbookStep]:
        """Universal Forwarder rolling upgrade steps."""
        rpm_filename = f"splunkforwarder-{to_version}-linux-2.6-x86_64.rpm"
        return [
            RunbookStep(
                phase="execution",
                order=1,
                title="Stage Universal Forwarder upgrade package on deployment server",
                description=(
                    "Upload the new UF package to the deployment server and create a "
                    "deployment app to push the upgrade."
                ),
                commands=[
                    "# Copy new UF package to deployment server",
                    f"scp /tmp/{rpm_filename} deploy-server:/opt/splunk/etc/deployment-apps/uf_upgrade/",
                    "",
                    "# Create install script in deployment app",
                    "mkdir -p /opt/splunk/etc/deployment-apps/uf_upgrade/linux_x86_64/bin",
                    f"echo 'rpm -Uvh /tmp/{rpm_filename}' > "
                    "/opt/splunk/etc/deployment-apps/uf_upgrade/linux_x86_64/bin/install.sh",
                ],
                expected_output="Deployment app created and staged",
                risk_if_skipped="Manual UF upgrades are error-prone and unauditable at scale",
                estimated_minutes=15,
                requires_downtime=False,
            ),
            RunbookStep(
                phase="execution",
                order=2,
                title="Deploy UF upgrade in rolling waves (10% then 100%)",
                description=(
                    "Push the upgrade to a pilot group (10% of forwarders) first, "
                    "monitor for 30 minutes, then roll out to all."
                ),
                commands=[
                    "# Assign pilot server class to 10% of forwarders",
                    "# Edit /opt/splunk/etc/system/local/serverclass.conf",
                    "# [serverClass:uf_upgrade_pilot]",
                    "#   whitelist.0 = *.pilot.example.com",
                    "",
                    "# Reload deployment server",
                    "/opt/splunk/bin/splunk reload deploy-server",
                    "",
                    "# Monitor data flow for 30 minutes",
                    "# After validation, extend to all forwarders:",
                    "# Edit serverclass.conf to include all machines",
                    "/opt/splunk/bin/splunk reload deploy-server",
                ],
                expected_output="Pilot forwarders running new version, data flowing normally",
                risk_if_skipped="Silent data loss if all forwarders upgrade simultaneously and fail",
                estimated_minutes=60,
                requires_downtime=False,
            ),
        ]

    def _execution_es_steps(
        self, from_version: str, to_version: str
    ) -> List[RunbookStep]:
        """Enterprise Security specific upgrade steps."""
        return [
            RunbookStep(
                phase="execution",
                order=1,
                title="Prepare ES for upgrade (disable correlation searches)",
                description=(
                    "Disable all enabled correlation searches before upgrade "
                    "to prevent alert storms during the process."
                ),
                commands=[
                    "# Disable all enabled correlation searches",
                    "curl -sk -u admin:changeme https://localhost:8089/services/saved/searches "
                    "--get -d count=0 -d search='is_scheduled=1 AND app=SplunkEnterpriseSecuritySuite' "
                    "-d output_mode=json | python3 -c \""
                    "import json,sys; "
                    "[print(e['name']) for e in json.load(sys.stdin).get('entry', []) "
                    "if e.get('content',{}).get('disabled','1')=='0']\"",
                    "",
                    "# Backup ES notable event index",
                    "/opt/splunk/bin/splunk backup index notable -f /backup/es_notable_$(date +%Y%m%d).tar.gz",
                ],
                expected_output="Correlation searches disabled, notable index backed up",
                risk_if_skipped="Alert storms and duplicate notables may flood analysts during upgrade",
                estimated_minutes=20,
                requires_downtime=False,
            ),
            RunbookStep(
                phase="execution",
                order=2,
                title="Upgrade ES application",
                description=(
                    "Install the new ES SPL package and run post-install migration scripts."
                ),
                commands=[
                    "# Install ES from extracted package",
                    f"cp -r /tmp/SplunkEnterpriseSecuritySuite-{to_version}/ "
                    "/opt/splunk/etc/apps/SplunkEnterpriseSecuritySuite/",
                    "",
                    "# Restart Splunk to apply ES upgrade",
                    "/opt/splunk/bin/splunk restart",
                    "",
                    "# Run ES post-upgrade migration",
                    "curl -sk -u admin:changeme -X POST "
                    "https://localhost:8089/services/apps/local/SplunkEnterpriseSecuritySuite/setup "
                    "-d output_mode=json",
                ],
                expected_output="ES app shows new version, setup endpoint returns success",
                risk_if_skipped="ES may be stuck in a partially upgraded state with broken correlation searches",
                estimated_minutes=30,
                requires_downtime=True,
            ),
        ]

    def _execution_app_steps(
        self, from_version: str, to_version: str, upgrade_type: str
    ) -> List[RunbookStep]:
        """Generic app/TA upgrade steps."""
        return [
            RunbookStep(
                phase="execution",
                order=1,
                title="Install new app/TA version",
                description=(
                    "Copy the new version over the existing installation. "
                    "Local/ directory is preserved automatically."
                ),
                commands=[
                    "APP_DIR=/opt/splunk/etc/apps/<app_name>",
                    "",
                    "# Backup current default/ directory",
                    "cp -r $APP_DIR/default/ /backup/app_default_$(date +%Y%m%d)/",
                    "",
                    "# Extract new version (preserves local/)",
                    "tar xzf /tmp/<app_name>-<new_version>.tar.gz -C /opt/splunk/etc/apps/",
                    "",
                    "# Verify local/ is intact",
                    "ls -la $APP_DIR/local/",
                    "",
                    "# Reload or restart Splunk",
                    "/opt/splunk/bin/splunk restart",
                ],
                expected_output="App shows new version in Splunk Web, local/ files preserved",
                risk_if_skipped="Running old app version loses bug fixes and updated field extractions",
                estimated_minutes=15,
                requires_downtime=True,
            ),
        ]

    def _build_validation_phase(
        self,
        from_version: str,
        to_version: str,
        upgrade_type: str,
    ) -> List[RunbookStep]:
        """Post-upgrade validation steps — always present."""
        steps: List[RunbookStep] = []
        order = 1

        steps.append(RunbookStep(
            phase="validation",
            order=order,
            title="Verify Splunk process and version",
            description="Confirm Splunk is running and reports the expected new version.",
            commands=[
                "/opt/splunk/bin/splunk status",
                "/opt/splunk/bin/splunk version",
                "",
                "# Confirm via REST",
                "curl -sk -u admin:changeme https://localhost:8089/services/server/info "
                "-d output_mode=json | python3 -c "
                "\"import json,sys; d=json.load(sys.stdin); "
                "print('version:', d['entry'][0]['content'].get('version','?'))\"",
            ],
            expected_output=f"Splunk version = {to_version}, status = running",
            risk_if_skipped="Cannot confirm upgrade completed successfully",
            estimated_minutes=5,
            requires_downtime=False,
        ))
        order += 1

        steps.append(RunbookStep(
            phase="validation",
            order=order,
            title="Run test search and verify data flow",
            description=(
                "Execute a simple SPL search to confirm data is being indexed "
                "and searches are returning results."
            ),
            commands=[
                "# Basic index health check",
                "/opt/splunk/bin/splunk search 'index=_internal sourcetype=splunkd "
                "| head 5' -auth admin:changeme",
                "",
                "# Check data latency (events in last 5 minutes)",
                "/opt/splunk/bin/splunk search 'index=* earliest=-5m | stats count by index' "
                "-auth admin:changeme -maxout 20",
                "",
                "# Verify saved searches can be parsed",
                "/opt/splunk/bin/splunk btool savedsearches list --app='*' 2>&1 | grep -i error | head -10",
            ],
            expected_output="Search returns results, no btool errors, recent data visible",
            risk_if_skipped="Data loss or search failures may go undetected",
            estimated_minutes=10,
            requires_downtime=False,
        ))
        order += 1

        steps.append(RunbookStep(
            phase="validation",
            order=order,
            title="Validate configuration with btool",
            description=(
                "Run btool to verify all configurations merge cleanly "
                "with no errors in the new version."
            ),
            commands=[
                "# Check props and transforms (most common issues)",
                "/opt/splunk/bin/splunk btool props list --debug 2>&1 | grep -i error | head -20",
                "/opt/splunk/bin/splunk btool transforms list --debug 2>&1 | grep -i error | head -20",
                "",
                "# Check all other confs",
                "/opt/splunk/bin/splunk btool check 2>&1 | head -30",
            ],
            expected_output="btool check exits 0 with no ERROR lines",
            risk_if_skipped="Silent configuration errors may cause incorrect field extraction or routing",
            estimated_minutes=10,
            requires_downtime=False,
        ))
        order += 1

        if upgrade_type in ("splunk_core",):
            steps.append(RunbookStep(
                phase="validation",
                order=order,
                title="Verify cluster health post-upgrade",
                description="Confirm the indexer cluster and search head cluster are fully healthy.",
                commands=[
                    "# Indexer cluster health",
                    "/opt/splunk/bin/splunk show cluster-status --verbose",
                    "",
                    "# Search head cluster health",
                    "/opt/splunk/bin/splunk show shcluster-status 2>/dev/null || echo 'Standalone'",
                    "",
                    "# Check for any pending fixup tasks",
                    "curl -sk -u admin:changeme https://localhost:8089/services/cluster/manager/health "
                    "-d output_mode=json | python3 -c "
                    "\"import json,sys; d=json.load(sys.stdin); "
                    "print(json.dumps(d.get('entry',[{}])[0].get('content',{}), indent=2))\"",
                ],
                expected_output="All peers Up, replication factor satisfied, no fixup tasks pending",
                risk_if_skipped="Hidden cluster issues may cause data loss or search failures later",
                estimated_minutes=15,
                requires_downtime=False,
            ))
            order += 1

        return steps

    def _build_rollback_phase(
        self,
        from_version: str,
        to_version: str,
        upgrade_type: str,
    ) -> List[RunbookStep]:
        """Rollback steps to revert to previous version — always present."""
        return [
            RunbookStep(
                phase="rollback",
                order=1,
                title="Stop Splunk and restore configuration backup",
                description=(
                    "If the upgrade has failed and Splunk cannot be recovered, "
                    "restore the pre-upgrade configuration from backup."
                ),
                commands=[
                    "# Stop Splunk",
                    "/opt/splunk/bin/splunk stop",
                    "",
                    "# Identify the pre-upgrade backup",
                    "ls -lt /backup/splunk_etc_*.tar.gz | head -5",
                    "",
                    "# Restore etc/ from backup (replace with actual backup filename)",
                    "BACKUP=$(ls -t /backup/splunk_etc_*.tar.gz | head -1)",
                    "tar xzf $BACKUP -C /opt/splunk/",
                    "",
                    "# Verify restore",
                    "ls -la /opt/splunk/etc/system/local/",
                ],
                expected_output="etc/ directory restored from backup, files show pre-upgrade timestamps",
                risk_if_skipped="No recovery path if upgraded Splunk fails to start",
                estimated_minutes=15,
                requires_downtime=True,
            ),
            RunbookStep(
                phase="rollback",
                order=2,
                title="Downgrade Splunk binary to previous version",
                description=(
                    "Reinstall the previous version of the Splunk binary. "
                    "Keep the restored etc/ directory."
                ),
                commands=[
                    f"# Remove new version",
                    f"rpm -e splunk 2>/dev/null || true",
                    "",
                    f"# Install old version (adjust filename)",
                    f"rpm -ivh /backup/splunk-{from_version}-linux-2.6-x86_64.rpm",
                    "",
                    "# For tarball install:",
                    f"# tar xzf /backup/splunk-{from_version}-Linux-x86_64.tgz -C /opt/",
                    "",
                    "# Start old version",
                    "/opt/splunk/bin/splunk start --accept-license --answer-yes",
                    "",
                    "# Confirm old version running",
                    "/opt/splunk/bin/splunk version",
                ],
                expected_output=f"Splunk running version {from_version}",
                risk_if_skipped="System stays on incompatible newer binary with restored old config",
                estimated_minutes=20,
                requires_downtime=True,
            ),
            RunbookStep(
                phase="rollback",
                order=3,
                title="Verify rollback success",
                description="Confirm the rollback is complete and Splunk is operational on the old version.",
                commands=[
                    "/opt/splunk/bin/splunk status",
                    "/opt/splunk/bin/splunk version",
                    "",
                    "# Verify data is flowing",
                    "/opt/splunk/bin/splunk search 'index=_internal | head 3' -auth admin:changeme",
                    "",
                    "# Post-rollback: document the failure reason before re-attempting",
                    "echo 'Document failure cause in incident ticket before retry'",
                ],
                expected_output=f"Splunk version = {from_version}, data flowing, no errors",
                risk_if_skipped="Rollback may be incomplete or partially reverted",
                estimated_minutes=10,
                requires_downtime=False,
            ),
        ]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_title(
        self,
        from_version: str,
        to_version: str,
        upgrade_type: str,
        app_id: str,
    ) -> str:
        type_labels = {
            "splunk_core": "Splunk Enterprise",
            "es": "Enterprise Security",
            "itsi": "IT Service Intelligence",
            "uf": "Universal Forwarder",
            "ta": f"Technology Add-on {app_id}",
            "app": f"App {app_id}",
        }
        label = type_labels.get(upgrade_type, upgrade_type.upper())
        return f"Upgrade Runbook: {label} {from_version} → {to_version}"


# ---------------------------------------------------------------------------
# Version comparison helpers
# ---------------------------------------------------------------------------


def _version_tuple(version_string: str) -> tuple:
    """Parse a version string into a comparable tuple."""
    try:
        return tuple(int(x) for x in version_string.split(".")[:3])
    except (ValueError, TypeError):
        return (0, 0, 0)


def _version_major_bump(from_version: str, to_version: str) -> bool:
    """Return True if the upgrade crosses a major version boundary."""
    from_tuple = _version_tuple(from_version)
    to_tuple = _version_tuple(to_version)
    return len(from_tuple) > 0 and len(to_tuple) > 0 and from_tuple[0] != to_tuple[0]
