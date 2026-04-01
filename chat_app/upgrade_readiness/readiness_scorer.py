"""
Readiness Scorer — combines all analysis engines into a single 0-100 score.

The scorer aggregates findings from four sources:
- Config auditor (breaking changes detected in conf files)
- Conf diff findings (three-way diff findings from the upgrade analysis)
- CIM compliance results (CIM model regressions)
- Security advisories (CVEs affecting the upgrade path)

Scoring starts at 100 and deductions are applied per finding severity:
- Each blocker:           -30 points
- Each high finding:      -10 points
- Each medium finding:     -5 points
- Each low finding:        -2 points
- Each critical CVE (unpatched): -15 points
- Each high CVE (unpatched):      -8 points
- Each CIM model regression:     -10 points

The overall score is clamped to [0, 100].

Four sub-categories are also scored on 0-25 scales:
- config_score:     based on config auditor findings
- app_compat_score: based on conf diff + CIM results
- security_score:   based on CVE advisories
- infra_score:      based on platform-level blockers/warnings

The final ReadinessScore also provides a human-readable recommendation
string and a readiness grade (PASS / CAUTION / FAIL).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring constants — named for clarity on why each value was chosen
# ---------------------------------------------------------------------------

# Severity-based deductions from the overall score
BLOCKER_DEDUCTION = 30          # A blocker means upgrade cannot proceed safely
HIGH_FINDING_DEDUCTION = 10     # High findings require immediate remediation
MEDIUM_FINDING_DEDUCTION = 5    # Medium findings are recommended to fix
LOW_FINDING_DEDUCTION = 2       # Low findings are nice-to-fix

# CVE-severity deductions
CRITICAL_CVE_DEDUCTION = 15     # Critical CVE unpatched is a near-blocker
HIGH_CVE_DEDUCTION = 8          # High CVE is a significant risk

# CIM regression deduction per impacted model
CIM_REGRESSION_DEDUCTION = 10   # Each broken CIM model damages analytics quality

# Sub-category maximum scores (all four sum to 100)
MAX_CONFIG_SCORE = 25
MAX_APP_COMPAT_SCORE = 25
MAX_SECURITY_SCORE = 25
MAX_INFRA_SCORE = 25


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class ReadinessScore:
    """Combined readiness score with per-category breakdown."""

    # Overall score 0-100
    overall_score: int = 100

    # Sub-category scores 0-25 each
    config_score: int = 25
    app_compat_score: int = 25
    security_score: int = 25
    infra_score: int = 25

    # Human-readable summary
    grade: str = "PASS"          # PASS / CAUTION / FAIL
    recommendation: str = ""

    # Breakdown counters used for the calculation
    blocker_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    critical_cve_count: int = 0
    high_cve_count: int = 0
    cim_regression_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict for API responses."""
        return {
            "overall_score": self.overall_score,
            "grade": self.grade,
            "recommendation": self.recommendation,
            "categories": {
                "config_score": self.config_score,
                "app_compat_score": self.app_compat_score,
                "security_score": self.security_score,
                "infra_score": self.infra_score,
            },
            "breakdown": {
                "blockers": self.blocker_count,
                "high_findings": self.high_count,
                "medium_findings": self.medium_count,
                "low_findings": self.low_count,
                "critical_cves": self.critical_cve_count,
                "high_cves": self.high_cve_count,
                "cim_regressions": self.cim_regression_count,
            },
        }


# ---------------------------------------------------------------------------
# Scorer
# ---------------------------------------------------------------------------


class ReadinessScorer:
    """Combines all upgrade-readiness engines into a single 0-100 readiness score."""

    def calculate_score(
        self,
        config_audit: Optional[Any] = None,
        conf_diff_findings: Optional[List[Any]] = None,
        cim_results: Optional[List[Any]] = None,
        breaking_changes: Optional[List[Any]] = None,
        security_advisories: Optional[List[Any]] = None,
    ) -> ReadinessScore:
        """
        Calculate a combined upgrade readiness score.

        Args:
            config_audit:       AuditReport from ConfigAuditor (has .findings list
                                with .severity in {blocker, warning, info}).
            conf_diff_findings: List of UpgradeFinding objects from conf_differ
                                (have .risk with UpgradeRisk enum values).
            cim_results:        List of CIM compliance result objects (have
                                .is_compliant boolean).
            breaking_changes:   List of BreakingChange objects (have .severity
                                in {blocker, warning, info}).
            security_advisories: List of advisory dicts or objects with a
                                 .severity / ["severity"] key in
                                 {critical, high, medium, low}.

        Returns:
            ReadinessScore with overall + per-category scores and recommendation.
        """
        result = ReadinessScore()
        total_deduction = 0

        # ------------------------------------------------------------------
        # 1. Config auditor findings
        # ------------------------------------------------------------------
        config_deduction = 0
        if config_audit is not None:
            for finding in getattr(config_audit, "findings", []):
                severity = getattr(finding, "severity", "").lower()
                if severity == "blocker":
                    config_deduction += BLOCKER_DEDUCTION
                    result.blocker_count += 1
                elif severity == "warning":
                    config_deduction += MEDIUM_FINDING_DEDUCTION
                    result.medium_count += 1
                elif severity == "info":
                    config_deduction += LOW_FINDING_DEDUCTION
                    result.low_count += 1

        # ------------------------------------------------------------------
        # 2. Breaking changes (from BreakingChangesDB)
        # ------------------------------------------------------------------
        bc_deduction = 0
        if breaking_changes:
            for change in breaking_changes:
                severity = getattr(change, "severity", "").lower()
                if severity == "blocker":
                    bc_deduction += BLOCKER_DEDUCTION
                    result.blocker_count += 1
                elif severity == "warning":
                    bc_deduction += MEDIUM_FINDING_DEDUCTION
                    result.medium_count += 1
                elif severity == "info":
                    bc_deduction += LOW_FINDING_DEDUCTION
                    result.low_count += 1

        # ------------------------------------------------------------------
        # 3. Conf diff findings (UpgradeFinding — risk enum)
        # ------------------------------------------------------------------
        diff_deduction = 0
        if conf_diff_findings:
            for finding in conf_diff_findings:
                # UpgradeRisk values: INFO, LOW, MEDIUM, HIGH, CRITICAL
                risk_value = ""
                risk_attr = getattr(finding, "risk", None)
                if risk_attr is not None:
                    risk_value = (
                        risk_attr.value
                        if hasattr(risk_attr, "value")
                        else str(risk_attr)
                    ).upper()

                if risk_value == "CRITICAL":
                    diff_deduction += BLOCKER_DEDUCTION
                    result.blocker_count += 1
                elif risk_value == "HIGH":
                    diff_deduction += HIGH_FINDING_DEDUCTION
                    result.high_count += 1
                elif risk_value == "MEDIUM":
                    diff_deduction += MEDIUM_FINDING_DEDUCTION
                    result.medium_count += 1
                elif risk_value in ("LOW", "INFO"):
                    diff_deduction += LOW_FINDING_DEDUCTION
                    result.low_count += 1

        # ------------------------------------------------------------------
        # 4. CIM compliance regressions
        # ------------------------------------------------------------------
        cim_deduction = 0
        if cim_results:
            for cim in cim_results:
                if not getattr(cim, "is_compliant", True):
                    cim_deduction += CIM_REGRESSION_DEDUCTION
                    result.cim_regression_count += 1

        # ------------------------------------------------------------------
        # 5. Security advisories (CVEs)
        # ------------------------------------------------------------------
        security_deduction = 0
        if security_advisories:
            for advisory in security_advisories:
                # Support both dict-style and object-style advisories
                if isinstance(advisory, dict):
                    severity = advisory.get("severity", "").lower()
                else:
                    severity = getattr(advisory, "severity", "").lower()

                if severity == "critical":
                    security_deduction += CRITICAL_CVE_DEDUCTION
                    result.critical_cve_count += 1
                elif severity == "high":
                    security_deduction += HIGH_CVE_DEDUCTION
                    result.high_cve_count += 1

        # ------------------------------------------------------------------
        # Compute overall score
        # ------------------------------------------------------------------
        total_deduction = (
            config_deduction
            + bc_deduction
            + diff_deduction
            + cim_deduction
            + security_deduction
        )
        result.overall_score = max(0, 100 - total_deduction)

        # ------------------------------------------------------------------
        # Compute per-category sub-scores (each 0-25)
        # ------------------------------------------------------------------
        result.config_score = max(
            0, MAX_CONFIG_SCORE - (config_deduction + bc_deduction) // 2
        )
        result.app_compat_score = max(
            0, MAX_APP_COMPAT_SCORE - (diff_deduction + cim_deduction) // 2
        )
        result.security_score = max(0, MAX_SECURITY_SCORE - security_deduction)
        # Infra score is primarily driven by hard blockers from config + breaking changes
        infra_blockers = result.blocker_count
        result.infra_score = max(0, MAX_INFRA_SCORE - infra_blockers * 8)

        # ------------------------------------------------------------------
        # Derive grade and recommendation
        # ------------------------------------------------------------------
        result.grade, result.recommendation = self._grade(result)

        logger.info(
            "[READINESS-SCORER] score=%d grade=%s blockers=%d",
            result.overall_score,
            result.grade,
            result.blocker_count,
        )
        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _grade(self, score: ReadinessScore) -> tuple:
        """Derive a letter grade and recommendation from the score."""
        if score.blocker_count > 0:
            return (
                "FAIL",
                (
                    f"CANNOT UPGRADE: {score.blocker_count} blocker(s) must be resolved "
                    "before proceeding. Address all blockers, then re-run the readiness check."
                ),
            )

        if score.overall_score >= 80:
            return (
                "PASS",
                (
                    "Upgrade appears safe. Review any warnings before proceeding "
                    "and test in a staging environment first."
                ),
            )

        if score.overall_score >= 50:
            return (
                "CAUTION",
                (
                    "Upgrade is possible but there are significant findings to address. "
                    "Resolve high-severity findings and validate in staging before production."
                ),
            )

        return (
            "FAIL",
            (
                "Upgrade readiness is low. Multiple high-severity or medium findings detected. "
                "Resolve critical issues before attempting the upgrade."
            ),
        )
