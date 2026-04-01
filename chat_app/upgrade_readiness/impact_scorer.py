"""
Impact scoring and recommendation engine for upgrade findings.

Converts raw UpgradeFinding lists into actionable risk assessments and
human-readable recommendations suitable for a change-review board.
"""
from __future__ import annotations

import logging
from typing import Dict, List

from chat_app.upgrade_readiness.models import (
    FindingCategory,
    UpgradeFinding,
    UpgradeImpactReport,
    UpgradeRisk,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Risk thresholds for overall recommendation
# ---------------------------------------------------------------------------

# Any critical finding triggers "Do not upgrade" immediately
CRITICAL_THRESHOLD = 1

# ≥ this many HIGH findings → "Review required"
HIGH_REVIEW_THRESHOLD = 1

# ≥ this many MEDIUM findings (with no HIGH) → "Review required"
MEDIUM_REVIEW_THRESHOLD = 3


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_risk(finding: UpgradeFinding) -> UpgradeRisk:
    """
    Re-classify the risk for a finding based on its category and key.

    The differ assigns initial risks; this function can override them
    based on additional context rules:

    - INDEX_TIME_CHANGE always → CRITICAL
    - ORPHANED_LOCAL always → CRITICAL
    - STANZA_REMOVED with no local → MEDIUM (retain original)
    - KEY_REMOVED / KEY_CHANGED without local override → HIGH
    - KEY_REMOVED / KEY_CHANGED with local override → LOW

    This function is idempotent — it is safe to call it multiple times.

    Args:
        finding: An UpgradeFinding to re-evaluate.

    Returns:
        The authoritative UpgradeRisk for this finding.
    """
    if finding.category in (
        FindingCategory.INDEX_TIME_CHANGE,
        FindingCategory.ORPHANED_LOCAL,
    ):
        return UpgradeRisk.CRITICAL

    if finding.category == FindingCategory.MERGE_CONFLICT:
        return UpgradeRisk.MEDIUM

    if finding.category in (FindingCategory.KEY_REMOVED, FindingCategory.KEY_CHANGED):
        if finding.local_value is not None:
            # Local override insulates the org from the default change
            return UpgradeRisk.LOW
        return UpgradeRisk.HIGH

    if finding.category == FindingCategory.KEY_ADDED:
        if finding.local_value is not None:
            return UpgradeRisk.MEDIUM
        return UpgradeRisk.INFO

    if finding.category == FindingCategory.STANZA_REMOVED:
        return UpgradeRisk.MEDIUM

    if finding.category == FindingCategory.STANZA_ADDED:
        return UpgradeRisk.INFO

    # Fall back to the finding's existing risk
    return finding.risk


def score_findings(findings: List[UpgradeFinding]) -> List[UpgradeFinding]:
    """
    Re-score, deduplicate, and sort a list of findings.

    Deduplication is based on (conf_type, stanza, key, category) so that the
    same logical issue reported from multiple conf files appears only once.
    The highest-risk copy is retained.

    Args:
        findings: Raw findings from the differ.

    Returns:
        Deduplicated list sorted by risk descending (CRITICAL first),
        then conf_type, stanza, key for deterministic ordering.
    """
    # Apply risk reclassification
    reclassified: List[UpgradeFinding] = []
    for finding in findings:
        new_risk = classify_risk(finding)
        if new_risk != finding.risk:
            # Rebuild frozen dataclass with corrected risk
            finding = UpgradeFinding(
                finding_id=finding.finding_id,
                risk=new_risk,
                category=finding.category,
                conf_type=finding.conf_type,
                stanza=finding.stanza,
                key=finding.key,
                description=finding.description,
                old_value=finding.old_value,
                new_value=finding.new_value,
                local_value=finding.local_value,
                recommendation=finding.recommendation,
                app_id=finding.app_id,
            )
        reclassified.append(finding)

    # Deduplicate — keep highest risk per (conf_type, stanza, key, category)
    dedup_key_to_finding: Dict[tuple, UpgradeFinding] = {}
    risk_order = {
        UpgradeRisk.CRITICAL: 0,
        UpgradeRisk.HIGH: 1,
        UpgradeRisk.MEDIUM: 2,
        UpgradeRisk.LOW: 3,
        UpgradeRisk.INFO: 4,
    }

    for finding in reclassified:
        key = (finding.conf_type, finding.stanza, finding.key or "", finding.category)
        existing = dedup_key_to_finding.get(key)
        if existing is None or risk_order[finding.risk] < risk_order[existing.risk]:
            dedup_key_to_finding[key] = finding

    deduplicated = list(dedup_key_to_finding.values())

    # Sort by risk descending, then stable secondary keys
    deduplicated.sort(
        key=lambda f: (risk_order[f.risk], f.conf_type, f.stanza, f.key or "")
    )

    logger.debug(
        "[SCORER] %d findings in → %d findings out after dedup/score",
        len(findings),
        len(deduplicated),
    )
    return deduplicated


def generate_recommendation(findings: List[UpgradeFinding]) -> str:
    """
    Generate a human-readable upgrade recommendation from the findings.

    Decision logic:
    - Any CRITICAL → "Do not upgrade without remediation"
    - Any HIGH → "Review required before upgrade"
    - ≥ MEDIUM_REVIEW_THRESHOLD MEDIUMs → "Review required before upgrade"
    - Otherwise → "Safe to upgrade"

    Args:
        findings: Scored and deduplicated findings.

    Returns:
        One of:
        - "Safe to upgrade"
        - "Review required before upgrade"
        - "Do not upgrade without remediation"
    """
    critical_count = sum(1 for f in findings if f.risk == UpgradeRisk.CRITICAL)
    high_count = sum(1 for f in findings if f.risk == UpgradeRisk.HIGH)
    medium_count = sum(1 for f in findings if f.risk == UpgradeRisk.MEDIUM)

    if critical_count >= CRITICAL_THRESHOLD:
        return "Do not upgrade without remediation"
    if high_count >= HIGH_REVIEW_THRESHOLD:
        return "Review required before upgrade"
    if medium_count >= MEDIUM_REVIEW_THRESHOLD:
        return "Review required before upgrade"
    return "Safe to upgrade"


def compute_overall_risk(findings: List[UpgradeFinding]) -> UpgradeRisk:
    """
    Determine the single highest-risk level across all findings.

    Args:
        findings: Scored and deduplicated findings.

    Returns:
        The maximum UpgradeRisk present, or UpgradeRisk.INFO if no findings.
    """
    if not findings:
        return UpgradeRisk.INFO

    risk_order = {
        UpgradeRisk.CRITICAL: 0,
        UpgradeRisk.HIGH: 1,
        UpgradeRisk.MEDIUM: 2,
        UpgradeRisk.LOW: 3,
        UpgradeRisk.INFO: 4,
    }
    return min(findings, key=lambda f: risk_order[f.risk]).risk


def summarize_impact(report: UpgradeImpactReport) -> Dict[str, object]:
    """
    Return a dict summary of the report suitable for dashboard display.

    Args:
        report: A completed UpgradeImpactReport.

    Returns:
        Dict with keys: risk_counts, overall_risk, recommendation,
        affected_conf_types, total_findings.
    """
    risk_counts: Dict[str, int] = {
        "CRITICAL": report.critical_count,
        "HIGH": report.high_count,
        "MEDIUM": report.medium_count,
        "LOW": report.low_count,
        "INFO": report.info_count,
    }

    affected_conf_types = sorted(
        {f.conf_type for f in report.findings}
    )

    return {
        "risk_counts": risk_counts,
        "overall_risk": report.overall_risk.value,
        "recommendation": report.recommendation,
        "affected_conf_types": affected_conf_types,
        "total_findings": len(report.findings),
        "app_id": report.app_id,
        "from_version": report.from_version,
        "to_version": report.to_version,
    }


def build_impact_report(
    findings: List[UpgradeFinding],
    app_id: str = "",
    from_version: str = "",
    to_version: str = "",
    cluster: str = "",
) -> UpgradeImpactReport:
    """
    Construct a complete UpgradeImpactReport from a list of raw findings.

    Applies scoring, deduplication, overall risk computation, and
    recommendation generation in one call.

    Args:
        findings: Raw findings from the differ (may contain duplicates).
        app_id: App being upgraded.
        from_version: Current installed version.
        to_version: Target upgrade version.
        cluster: Cluster name for context.

    Returns:
        Fully populated UpgradeImpactReport ready for display or export.
    """
    scored = score_findings(findings)
    overall_risk = compute_overall_risk(scored)
    recommendation = generate_recommendation(scored)

    risk_counts = {
        "CRITICAL": sum(1 for f in scored if f.risk == UpgradeRisk.CRITICAL),
        "HIGH": sum(1 for f in scored if f.risk == UpgradeRisk.HIGH),
        "MEDIUM": sum(1 for f in scored if f.risk == UpgradeRisk.MEDIUM),
        "LOW": sum(1 for f in scored if f.risk == UpgradeRisk.LOW),
        "INFO": sum(1 for f in scored if f.risk == UpgradeRisk.INFO),
    }
    affected_conf_types = sorted({f.conf_type for f in scored})

    return UpgradeImpactReport(
        app_id=app_id,
        from_version=from_version,
        to_version=to_version,
        cluster=cluster,
        findings=scored,
        overall_risk=overall_risk,
        recommendation=recommendation,
        risk_counts=risk_counts,
        affected_conf_types=affected_conf_types,
    )
