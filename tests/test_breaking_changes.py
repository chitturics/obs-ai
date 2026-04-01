"""Tests for breaking changes DB and config auditor."""
import pytest
import os

# Use the real YAML files in data/breaking_changes/
BC_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "breaking_changes")


class TestBreakingChangesDB:
    def test_load_from_yaml(self):
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChangesDB
        db = BreakingChangesDB(BC_PATH)
        db.load()
        assert db.get_all_versions()
        assert "10.0" in db.get_all_versions()

    def test_changes_for_10_0(self):
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChangesDB
        db = BreakingChangesDB(BC_PATH)
        changes = db.get_changes_for_version("10.0")
        assert len(changes) >= 8
        assert any(c.severity == "blocker" for c in changes)

    def test_blockers_between_versions(self):
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChangesDB
        db = BreakingChangesDB(BC_PATH)
        blockers = db.get_blockers("9.3.0", "10.3.0")
        assert len(blockers) >= 2  # CPU + TLS + Python

    def test_config_changes(self):
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChangesDB
        db = BreakingChangesDB(BC_PATH)
        config_changes = db.get_config_changes("9.0.0", "10.3.0")
        assert any(c.conf_file == "server.conf" for c in config_changes)

    def test_summary(self):
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChangesDB
        db = BreakingChangesDB(BC_PATH)
        summary = db.get_summary()
        assert summary["total_changes"] >= 10


class TestConfigAuditor:
    def test_detects_tls_blocker(self):
        from chat_app.upgrade_readiness.config_auditor import ConfigAuditor
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChangesDB
        db = BreakingChangesDB(BC_PATH)
        auditor = ConfigAuditor(db)
        report = auditor.audit(
            conf_files={"server": {"sslConfig": {"sslVersions": "tls1.0,tls1.2"}}},
            from_version="9.3.0",
            to_version="10.3.0",
        )
        assert report.blockers >= 1
        assert any("TLS" in f.title for f in report.findings)

    def test_detects_master_uri(self):
        from chat_app.upgrade_readiness.config_auditor import ConfigAuditor
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChangesDB
        db = BreakingChangesDB(BC_PATH)
        auditor = ConfigAuditor(db)
        report = auditor.audit(
            conf_files={"server": {"License": {"master_uri": "https://lm:8089"}}},
            from_version="9.3.0",
            to_version="10.3.0",
        )
        assert any("master_uri" in f.title.lower() or "master_uri" in f.key for f in report.findings)

    def test_clean_config_passes(self):
        from chat_app.upgrade_readiness.config_auditor import ConfigAuditor
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChangesDB
        db = BreakingChangesDB(BC_PATH)
        auditor = ConfigAuditor(db)
        report = auditor.audit(
            conf_files={"server": {"general": {"serverName": "idx01"}}},
            from_version="9.3.0",
            to_version="9.4.0",
        )
        assert report.blockers == 0
        assert report.readiness_score >= 80

    def test_readiness_score_decreases_with_blockers(self):
        from chat_app.upgrade_readiness.config_auditor import ConfigAuditor
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChangesDB
        db = BreakingChangesDB(BC_PATH)
        auditor = ConfigAuditor(db)
        report = auditor.audit(
            conf_files={"server": {"sslConfig": {"sslVersions": "tls1.0"}}},
            from_version="9.3.0",
            to_version="10.3.0",
        )
        assert report.readiness_score < 100

    def test_recommendation_for_blockers(self):
        from chat_app.upgrade_readiness.config_auditor import ConfigAuditor
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChangesDB
        db = BreakingChangesDB(BC_PATH)
        auditor = ConfigAuditor(db)
        report = auditor.audit(
            conf_files={"server": {"sslConfig": {"sslVersions": "ssl3"}}},
            from_version="9.3.0",
            to_version="10.3.0",
        )
        assert "CANNOT UPGRADE" in report.recommendation or "blocker" in report.recommendation.lower()

    def test_report_to_dict(self):
        from chat_app.upgrade_readiness.config_auditor import ConfigAuditor
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChangesDB
        db = BreakingChangesDB(BC_PATH)
        auditor = ConfigAuditor(db)
        report = auditor.audit(
            conf_files={},
            from_version="9.3.0",
            to_version="10.3.0",
        )
        d = report.to_dict()
        assert "findings" in d
        assert "summary" in d
        assert "readiness_score" in d["summary"]

    def test_no_changes_same_version(self):
        from chat_app.upgrade_readiness.config_auditor import ConfigAuditor
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChangesDB
        db = BreakingChangesDB(BC_PATH)
        auditor = ConfigAuditor(db)
        report = auditor.audit(
            conf_files={"server": {"general": {"foo": "bar"}}},
            from_version="9.3.0",
            to_version="9.3.0",
        )
        assert report.readiness_score == 100
        assert "No known breaking changes" in report.recommendation


class TestReadinessScorer:
    """Tests for the ReadinessScorer that combines all analysis engines."""

    def test_clean_input_returns_100(self):
        """No findings → perfect score."""
        from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer

        scorer = ReadinessScorer()
        result = scorer.calculate_score()
        assert result.overall_score == 100
        assert result.grade == "PASS"
        assert result.blocker_count == 0

    def test_single_blocker_deducts_30(self):
        """One blocker from breaking changes reduces score by 30."""
        from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChange

        blocker = BreakingChange(
            id="BC-TEST-001",
            version="10.0",
            category="security",
            severity="blocker",
            title="Test blocker",
        )
        scorer = ReadinessScorer()
        result = scorer.calculate_score(breaking_changes=[blocker])
        assert result.overall_score == 70
        assert result.grade == "FAIL"
        assert result.blocker_count == 1
        assert "CANNOT UPGRADE" in result.recommendation

    def test_multiple_findings_compound_deductions(self):
        """Multiple findings across categories stack correctly."""
        from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChange

        changes = [
            BreakingChange(
                id="BC-T-001", version="10.0", category="security",
                severity="blocker", title="Blocker A",
            ),
            BreakingChange(
                id="BC-T-002", version="10.0", category="config",
                severity="warning", title="Warning B",
            ),
            BreakingChange(
                id="BC-T-003", version="10.0", category="platform",
                severity="info", title="Info C",
            ),
        ]
        scorer = ReadinessScorer()
        result = scorer.calculate_score(breaking_changes=changes)
        # blocker(-30) + warning(-5) + info(-2) = -37 → 63
        assert result.overall_score == 63
        assert result.blocker_count == 1
        assert result.medium_count == 1
        assert result.low_count == 1

    def test_score_clamps_to_zero_not_negative(self):
        """Score cannot go below zero regardless of finding count."""
        from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChange

        # 5 blockers would deduct 150 points — should clamp at 0
        many_blockers = [
            BreakingChange(
                id=f"BC-T-{i:03d}", version="10.0", category="security",
                severity="blocker", title=f"Blocker {i}",
            )
            for i in range(5)
        ]
        scorer = ReadinessScorer()
        result = scorer.calculate_score(breaking_changes=many_blockers)
        assert result.overall_score == 0
        assert result.grade == "FAIL"

    def test_critical_cve_deducts_15(self):
        """A critical CVE advisory deducts 15 points from security score."""
        from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer

        advisories = [{"severity": "critical", "id": "CVE-2024-0001"}]
        scorer = ReadinessScorer()
        result = scorer.calculate_score(security_advisories=advisories)
        assert result.overall_score == 85
        assert result.critical_cve_count == 1

    def test_high_cve_deducts_8(self):
        """A high CVE advisory deducts 8 points."""
        from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer

        advisories = [{"severity": "high", "id": "CVE-2024-0002"}]
        scorer = ReadinessScorer()
        result = scorer.calculate_score(security_advisories=advisories)
        assert result.overall_score == 92
        assert result.high_cve_count == 1

    def test_cim_regression_deducts_10_per_model(self):
        """Each non-compliant CIM model deducts 10 points."""
        from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer

        class FakeCIMResult:
            def __init__(self, compliant: bool):
                self.is_compliant = compliant

        results = [FakeCIMResult(False), FakeCIMResult(True), FakeCIMResult(False)]
        scorer = ReadinessScorer()
        result = scorer.calculate_score(cim_results=results)
        assert result.overall_score == 80  # 2 regressions * 10 = -20
        assert result.cim_regression_count == 2

    def test_to_dict_contains_required_keys(self):
        """ReadinessScore.to_dict() includes all required response keys."""
        from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer

        scorer = ReadinessScorer()
        result = scorer.calculate_score()
        as_dict = result.to_dict()
        assert "overall_score" in as_dict
        assert "grade" in as_dict
        assert "recommendation" in as_dict
        assert "categories" in as_dict
        assert "breakdown" in as_dict
        categories = as_dict["categories"]
        assert "config_score" in categories
        assert "app_compat_score" in categories
        assert "security_score" in categories
        assert "infra_score" in categories

    def test_sub_scores_sum_capped_at_100(self):
        """All four sub-scores each stay within [0, 25]."""
        from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer

        scorer = ReadinessScorer()
        result = scorer.calculate_score()
        assert 0 <= result.config_score <= 25
        assert 0 <= result.app_compat_score <= 25
        assert 0 <= result.security_score <= 25
        assert 0 <= result.infra_score <= 25

    def test_combined_sources_all_zero_gives_zero(self):
        """Enough inputs from every source combined should push score to 0."""
        from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChange

        class FakeCIMResult:
            is_compliant = False

        class FakeAuditFinding:
            severity = "blocker"

        class FakeAuditReport:
            findings = [FakeAuditFinding() for _ in range(4)]

        many_changes = [
            BreakingChange(
                id=f"BC-T-{i:03d}", version="10.0", category="security",
                severity="blocker", title=f"Blocker {i}",
            )
            for i in range(4)
        ]
        many_advisories = [{"severity": "critical"}] * 6
        many_cim = [FakeCIMResult()] * 5

        scorer = ReadinessScorer()
        result = scorer.calculate_score(
            config_audit=FakeAuditReport(),
            breaking_changes=many_changes,
            security_advisories=many_advisories,
            cim_results=many_cim,
        )
        assert result.overall_score == 0
        assert result.grade == "FAIL"


# ---------------------------------------------------------------------------
# TestRunbookGenerator
# ---------------------------------------------------------------------------


class TestRunbookGenerator:
    """Tests for the RunbookGenerator that synthesizes upgrade analysis into runbooks."""

    def _make_generator(self):
        from chat_app.upgrade_readiness.runbook_generator import RunbookGenerator
        return RunbookGenerator()

    def test_generates_all_required_phases(self):
        """A basic runbook must contain pre-upgrade, execution, validation, and rollback phases."""
        gen = self._make_generator()
        runbook = gen.generate(from_version="9.3.2", to_version="10.2.1")
        assert "pre-upgrade" in runbook.phases
        assert "execution" in runbook.phases
        assert "validation" in runbook.phases
        assert "rollback" in runbook.phases

    def test_pre_upgrade_always_has_backup_step(self):
        """Pre-upgrade phase must always include a config backup step."""
        gen = self._make_generator()
        runbook = gen.generate(from_version="9.3.2", to_version="10.2.1")
        pre_steps = runbook.phases["pre-upgrade"]
        assert len(pre_steps) >= 1
        # First step should be backup
        first = pre_steps[0]
        assert "backup" in first.title.lower()
        assert any("tar" in cmd or "backup" in cmd.lower() for cmd in first.commands)

    def test_execution_steps_contain_real_commands(self):
        """Execution steps must include real splunk CLI commands."""
        gen = self._make_generator()
        runbook = gen.generate(
            from_version="9.3.2",
            to_version="10.2.1",
            upgrade_type="splunk_core",
        )
        exec_steps = runbook.phases["execution"]
        all_commands = [cmd for step in exec_steps for cmd in step.commands]
        # Must contain actual splunk binary references
        assert any("splunk" in cmd and not cmd.startswith("#") for cmd in all_commands)

    def test_rollback_phase_always_present(self):
        """Rollback phase must always be generated with at least one step."""
        gen = self._make_generator()
        runbook = gen.generate(from_version="9.3.2", to_version="10.2.1")
        rollback_steps = runbook.phases.get("rollback", [])
        assert len(rollback_steps) >= 1
        # Rollback must reference the from_version
        all_cmds = [cmd for step in rollback_steps for cmd in step.commands]
        all_text = " ".join(all_cmds + [s.description for s in rollback_steps])
        assert "9.3.2" in all_text

    def test_markdown_output_contains_all_phases(self):
        """to_markdown() must produce text containing each phase header."""
        gen = self._make_generator()
        runbook = gen.generate(from_version="9.3.2", to_version="10.2.1")
        md = runbook.to_markdown()
        assert "Pre-Upgrade" in md or "pre-upgrade" in md.lower()
        assert "Execution" in md
        assert "Validation" in md
        assert "Rollback" in md

    def test_to_dict_contains_required_keys(self):
        """to_dict() must include title, phases, readiness_score, and estimated_hours."""
        gen = self._make_generator()
        runbook = gen.generate(from_version="9.3.2", to_version="10.2.1")
        d = runbook.to_dict()
        assert "title" in d
        assert "phases" in d
        assert "readiness_score" in d
        assert "estimated_hours" in d
        assert d["from_version"] == "9.3.2"
        assert d["to_version"] == "10.2.1"

    def test_estimated_hours_is_positive(self):
        """Estimated hours must be greater than zero for any runbook."""
        gen = self._make_generator()
        runbook = gen.generate(from_version="9.3.2", to_version="10.2.1")
        assert runbook.estimated_hours > 0.0
        assert runbook.total_steps > 0

    def test_configuration_phase_generated_for_audit_findings(self):
        """When audit findings are present, a configuration phase must appear in the runbook."""
        from chat_app.upgrade_readiness.config_auditor import ConfigAuditor
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChangesDB

        db = BreakingChangesDB(BC_PATH)
        auditor = ConfigAuditor(db)
        audit_report = auditor.audit(
            conf_files={"server": {"sslConfig": {"sslVersions": "tls1.0"}}},
            from_version="9.3.0",
            to_version="10.2.1",
        )

        gen = self._make_generator()
        runbook = gen.generate(
            from_version="9.3.0",
            to_version="10.2.1",
            config_audit=audit_report,
        )
        # Audit has findings → configuration phase must appear
        assert "configuration" in runbook.phases
        config_steps = runbook.phases["configuration"]
        assert len(config_steps) >= 1

    def test_uf_upgrade_type_generates_uf_steps(self):
        """Universal Forwarder upgrade type must produce UF-specific execution steps."""
        gen = self._make_generator()
        runbook = gen.generate(
            from_version="9.3.2",
            to_version="10.2.1",
            upgrade_type="uf",
        )
        exec_steps = runbook.phases.get("execution", [])
        assert len(exec_steps) >= 1
        # UF steps reference forwarder or deployment server
        all_text = " ".join(
            cmd for step in exec_steps for cmd in step.commands
        ).lower()
        assert "forwarder" in all_text or "deploy" in all_text or "splunkforwarder" in all_text


# ---------------------------------------------------------------------------
# TestConfigAuditorIntegration
# ---------------------------------------------------------------------------


class TestConfigAuditorIntegration:
    """Tests that the config auditor is properly wired into the upgrade check flow."""

    def test_audit_report_included_in_readiness_score(self):
        """Readiness scorer must incorporate config audit blockers into the score."""
        from chat_app.upgrade_readiness.config_auditor import ConfigAuditor, AuditReport, AuditFinding
        from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer

        # Build a mock audit report with one blocker
        audit = AuditReport(from_version="9.3.0", to_version="10.2.1")
        audit.findings.append(AuditFinding(
            breaking_change_id="TEST-001",
            severity="blocker",
            title="Test blocker",
            description="A test configuration blocker",
            conf_file="server.conf",
            stanza="sslConfig",
            key="sslVersions",
            current_value="tls1.0",
            migration="Use tls1.2",
            category="security",
        ))
        audit.blockers = 1

        scorer = ReadinessScorer()
        score = scorer.calculate_score(config_audit=audit)
        # One blocker deducts 30 points
        assert score.overall_score == 70
        assert score.blocker_count >= 1
        assert score.grade == "FAIL"

    def test_audit_findings_surfaced_in_runbook(self):
        """Config audit findings must cause configuration remediation steps in runbook."""
        from chat_app.upgrade_readiness.config_auditor import ConfigAuditor
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChangesDB

        db = BreakingChangesDB(BC_PATH)
        auditor = ConfigAuditor(db)
        audit_report = auditor.audit(
            conf_files={"server": {"License": {"master_uri": "https://lm:8089"}}},
            from_version="9.3.0",
            to_version="10.2.1",
        )
        assert len(audit_report.findings) >= 1

        from chat_app.upgrade_readiness.runbook_generator import RunbookGenerator
        gen = RunbookGenerator()
        runbook = gen.generate(
            from_version="9.3.0",
            to_version="10.2.1",
            config_audit=audit_report,
        )
        assert "configuration" in runbook.phases

    def test_readiness_score_returned_has_grade(self):
        """ReadinessScore returned by scorer must have a grade string."""
        from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer
        from chat_app.upgrade_readiness.config_auditor import ConfigAuditor
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChangesDB

        db = BreakingChangesDB(BC_PATH)
        auditor = ConfigAuditor(db)
        audit_report = auditor.audit(
            conf_files={},
            from_version="9.3.0",
            to_version="10.2.1",
        )

        scorer = ReadinessScorer()
        score = scorer.calculate_score(config_audit=audit_report)
        assert score.grade in ("PASS", "CAUTION", "FAIL")
        assert 0 <= score.overall_score <= 100

    def test_blockers_field_in_score_dict(self):
        """ReadinessScore.to_dict() must expose blockers count at top level."""
        from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer
        from chat_app.upgrade_readiness.config_auditor import ConfigAuditor, AuditReport, AuditFinding

        audit = AuditReport()
        audit.findings.append(AuditFinding(
            breaking_change_id="BC-X-001",
            severity="blocker",
            title="Blocker test",
            description="",
            conf_file="server.conf",
            stanza="general",
            key="testkey",
            current_value="bad",
            migration="fix it",
            category="config",
        ))
        audit.blockers = 1

        scorer = ReadinessScorer()
        score = scorer.calculate_score(config_audit=audit)
        d = score.to_dict()
        assert d["breakdown"]["blockers"] >= 1

    def test_clean_config_gives_pass_grade(self):
        """A clean config with no findings must result in PASS grade."""
        from chat_app.upgrade_readiness.config_auditor import ConfigAuditor
        from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer
        from chat_app.upgrade_readiness.breaking_changes_db import BreakingChangesDB

        db = BreakingChangesDB(BC_PATH)
        auditor = ConfigAuditor(db)
        audit_report = auditor.audit(
            conf_files={"server": {"general": {"serverName": "myidx01"}}},
            from_version="9.3.0",
            to_version="9.3.5",  # tiny version bump, no breaking changes expected
        )

        scorer = ReadinessScorer()
        score = scorer.calculate_score(config_audit=audit_report)
        # No blockers for a patch-level version bump on clean config
        assert score.blocker_count == 0
        # Grade is PASS or CAUTION (not FAIL)
        assert score.grade in ("PASS", "CAUTION")

# ---------------------------------------------------------------------------
# End-to-End Integration Tests
# ---------------------------------------------------------------------------

class TestFullUpgradePipeline:
    """Test the complete upgrade pipeline from scan to report."""

    def test_scan_diff_score_report(self):
        """Full pipeline: scan → diff → score → report."""
        import os
        repo = "documents/repo/splunk/shcluster/cluster-search/apps/Splunk_TA_windows"
        upgrade = "/tmp/upgrade_test/Splunk_TA_windows_v10"
        if not os.path.exists(repo) or not os.path.exists(upgrade):
            pytest.skip("Test data not available")

        from chat_app.upgrade_readiness.baseline_builder import scan_app_directory
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.impact_scorer import score_findings, build_impact_report
        from chat_app.upgrade_readiness.report_builder import ReportBuilder

        old = scan_app_directory(repo)
        new = scan_app_directory(upgrade)

        findings = []
        for ct in set(list(old.default_confs.keys()) + list(new.default_confs.keys())):
            if ct == "app": continue
            findings.extend(three_way_diff(
                old.default_confs.get(ct, {}),
                new.default_confs.get(ct, {}),
                old.local_confs.get(ct, {}),
                conf_type=ct))

        scored = score_findings(findings)
        report = build_impact_report(scored, app_id=old.app_id,
            from_version=old.version.version, to_version=new.version.version)

        assert report.overall_risk.value == "CRITICAL"
        assert len(report.findings) >= 10

        builder = ReportBuilder(reports_dir="/tmp/test_reports")
        md = builder.to_markdown(report)
        assert "CRITICAL" in md
        assert len(md) > 1000

    def test_config_auditor_with_real_data(self):
        """Config auditor against real breaking changes."""
        from chat_app.upgrade_readiness.config_auditor import ConfigAuditor
        auditor = ConfigAuditor()
        report = auditor.audit(
            conf_files={
                "server": {
                    "sslConfig": {"sslVersions": "tls1.0,tls1.2"},
                    "License": {"master_uri": "https://lm:8089"},
                },
            },
            from_version="9.3.0",
            to_version="10.2.1",
        )
        assert report.blockers >= 1  # TLS 1.0
        assert report.readiness_score < 100
        assert "CANNOT UPGRADE" in report.recommendation

    def test_readiness_scorer_with_audit(self):
        """Readiness scorer combines audit + findings."""
        from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer
        from chat_app.upgrade_readiness.config_auditor import ConfigAuditor, AuditReport, AuditFinding
        
        scorer = ReadinessScorer()
        
        # Create a report with 1 blocker
        audit = AuditReport(from_version="9.3.0", to_version="10.2.1")
        audit.findings.append(AuditFinding(
            breaking_change_id="BC-10.0-003",
            severity="blocker",
            title="TLS 1.0 configured",
            description="Must remove TLS 1.0",
            conf_file="server.conf",
            category="security",
        ))
        audit.blockers = 1
        
        score = scorer.calculate_score(config_audit=audit)
        assert score.overall_score < 100
        assert score.grade in ("CAUTION", "FAIL")

    def test_platform_versions_loaded(self):
        """Verify real versions are loaded from YAML."""
        from chat_app.upgrade_readiness.platform_versions import SPLUNK_ENTERPRISE_RELEASES
        assert len(SPLUNK_ENTERPRISE_RELEASES) >= 50
        versions = [r.version for r in SPLUNK_ENTERPRISE_RELEASES]
        assert "9.4.9" in versions
        assert "10.0.0" in versions

    def test_es_versions_from_catalog(self):
        """Verify ES versions come from Splunkbase catalog."""
        from chat_app.upgrade_readiness.platform_versions import get_es_versions
        versions = get_es_versions()
        if not versions:
            pytest.skip("Splunkbase catalog not loaded in test env")
        assert len(versions) >= 20

    def test_upgrade_advisor_lookup(self):
        """Verify advisor can look up apps."""
        from chat_app.upgrade_readiness.upgrade_advisor import lookup_app, get_type_info
        app = lookup_app("Splunk_TA_windows")
        if app is None:
            pytest.skip("Splunkbase catalog not loaded in test env")
        assert app.get("latest_version")
        
        info = get_type_info("ta")
        assert len(info["what_we_check"]) >= 5
        assert len(info["risks"]) >= 3
