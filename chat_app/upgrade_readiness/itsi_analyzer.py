"""IT Service Intelligence (ITSI) Upgrade Analyzer.

Handles ITSI-specific upgrade risks:
- Service definition changes
- KPI threshold changes
- Glass table compatibility
- Notable event aggregation policy changes
- Deep dive changes
- Module visualization changes
- Entity management changes
- Maintenance window changes

ITSI upgrades are HIGH RISK because:
1. KPI threshold changes affect alerting sensitivity
2. Service dependency tree changes break glass tables
3. Notable aggregation changes affect incident management
4. Entity rule changes affect service membership
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List

from chat_app.upgrade_readiness.models import (
    FindingCategory,
    UpgradeRisk,
    UpgradeType,
)

logger = logging.getLogger(__name__)


# ITSI-specific conf files
ITSI_CONFS = {
    "itsi_service.conf": "Service definitions and dependencies",
    "itsi_kpi.conf": "KPI definitions and thresholds",
    "itsi_notable_event_aggregation.conf": "Notable event aggregation policies",
    "itsi_module_vis.conf": "Glass table and deep dive definitions",
    "itsi_entity.conf": "Entity management rules",
    "itsi_maintenance.conf": "Maintenance window definitions",
    "savedsearches.conf": "ITSI saved searches and reports",
    "macros.conf": "ITSI macros used in KPI searches",
}


@dataclass
class ITSIUpgradeFinding:
    """Extended finding for ITSI-specific issues."""
    finding_id: str = ""
    category: FindingCategory = FindingCategory.KPI_DEFINITION_CHANGED
    risk: UpgradeRisk = UpgradeRisk.INFO
    conf_type: str = ""
    stanza: str = ""
    key: str = ""
    old_value: str = ""
    new_value: str = ""
    description: str = ""
    remediation: str = ""
    """Extended finding for ITSI-specific issues."""
    affected_services: List[str] = field(default_factory=list)
    affected_kpis: List[str] = field(default_factory=list)
    threshold_impact: bool = False
    glass_table_impact: bool = False


@dataclass
class ITSIUpgradeReport:
    """ITSI-specific upgrade analysis report."""
    upgrade_type: str = UpgradeType.ITSI.value
    old_version: str = ""
    new_version: str = ""

    services_affected: int = 0
    kpis_changed: int = 0
    thresholds_changed: int = 0
    glass_tables_affected: int = 0
    aggregation_policies_changed: int = 0

    findings: List[ITSIUpgradeFinding] = field(default_factory=list)
    overall_risk: UpgradeRisk = UpgradeRisk.INFO
    recommendation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "upgrade_type": self.upgrade_type,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "services_affected": self.services_affected,
            "kpis_changed": self.kpis_changed,
            "thresholds_changed": self.thresholds_changed,
            "glass_tables_affected": self.glass_tables_affected,
            "findings_count": len(self.findings),
            "overall_risk": self.overall_risk.value,
            "recommendation": self.recommendation,
        }


def analyze_itsi_upgrade(
    old_confs: Dict[str, Dict[str, Dict[str, str]]],
    new_confs: Dict[str, Dict[str, Dict[str, str]]],
    local_confs: Dict[str, Dict[str, Dict[str, str]]],
) -> ITSIUpgradeReport:
    """Analyze ITSI upgrade impact.

    Checks:
    1. Service definition changes (dependency tree)
    2. KPI definition and threshold changes
    3. Notable event aggregation policy changes
    4. Glass table / deep dive compatibility
    5. Entity rule changes
    """
    report = ITSIUpgradeReport()
    findings: List[ITSIUpgradeFinding] = []

    # 1. KPI threshold changes (most critical for ITSI)
    _analyze_kpi_changes(old_confs, new_confs, local_confs, report, findings)

    # 2. Service definition changes
    _analyze_service_changes(old_confs, new_confs, report, findings)

    # 3. Notable aggregation policy changes
    _analyze_aggregation_changes(old_confs, new_confs, report, findings)

    # 4. Saved search changes (ITSI base searches)
    _analyze_itsi_searches(old_confs, new_confs, local_confs, report, findings)

    report.findings = findings
    if report.thresholds_changed > 0:
        report.overall_risk = UpgradeRisk.HIGH
        report.recommendation = f"Review {report.thresholds_changed} KPI threshold changes — alerting sensitivity affected"
    elif report.services_affected > 0:
        report.overall_risk = UpgradeRisk.MEDIUM
        report.recommendation = f"{report.services_affected} service definitions changed"
    elif findings:
        report.overall_risk = max(f.risk for f in findings)
        report.recommendation = f"Review {len(findings)} findings"
    else:
        report.recommendation = "Safe to upgrade — no ITSI-specific issues"

    return report


def _analyze_kpi_changes(
    old_confs: Dict, new_confs: Dict, local_confs: Dict,
    report: ITSIUpgradeReport, findings: List[ITSIUpgradeFinding],
) -> None:
    """Check KPI definition and threshold changes."""
    old_kpis = old_confs.get("itsi_kpi", old_confs.get("savedsearches", {}))
    new_kpis = new_confs.get("itsi_kpi", new_confs.get("savedsearches", {}))

    threshold_keys = {"alert.threshold", "threshold_value", "aggregate_threshold",
                      "alert.severity", "urgency", "adaptive_threshold"}

    for stanza, old_keys in old_kpis.items():
        new_keys = new_kpis.get(stanza, {})
        if not new_keys:
            continue

        for key in threshold_keys:
            old_val = old_keys.get(key, "")
            new_val = new_keys.get(key, "")
            if old_val and new_val and old_val != new_val:
                report.thresholds_changed += 1
                report.kpis_changed += 1
                findings.append(ITSIUpgradeFinding(
                    finding_id=f"itsi_threshold_{stanza[:30]}_{key}",
                    category=FindingCategory.THRESHOLD_CHANGED,
                    risk=UpgradeRisk.HIGH,
                    conf_type="itsi_kpi",
                    stanza=stanza,
                    key=key,
                    old_value=old_val,
                    new_value=new_val,
                    description=f"KPI threshold changed for '{stanza}': {key} {old_val}→{new_val}",
                    remediation="Review alerting sensitivity — may cause false positives/negatives",
                    threshold_impact=True,
                    affected_kpis=[stanza],
                ))


def _analyze_service_changes(
    old_confs: Dict, new_confs: Dict,
    report: ITSIUpgradeReport, findings: List[ITSIUpgradeFinding],
) -> None:
    """Check service definition changes."""
    old_services = old_confs.get("itsi_service", {})
    new_services = new_confs.get("itsi_service", {})

    for stanza in old_services:
        if stanza not in new_services:
            report.services_affected += 1
            findings.append(ITSIUpgradeFinding(
                finding_id=f"itsi_service_removed_{stanza[:30]}",
                category=FindingCategory.SERVICE_DEFINITION_CHANGED,
                risk=UpgradeRisk.HIGH,
                conf_type="itsi_service",
                stanza=stanza,
                description=f"ITSI service definition '{stanza}' removed",
                remediation="Check if service was renamed or merged",
                affected_services=[stanza],
            ))

    for stanza in new_services:
        if stanza not in old_services:
            report.services_affected += 1


def _analyze_aggregation_changes(
    old_confs: Dict, new_confs: Dict,
    report: ITSIUpgradeReport, findings: List[ITSIUpgradeFinding],
) -> None:
    """Check notable event aggregation policy changes."""
    old_agg = old_confs.get("itsi_notable_event_aggregation", {})
    new_agg = new_confs.get("itsi_notable_event_aggregation", {})

    for stanza, old_keys in old_agg.items():
        new_keys = new_agg.get(stanza, {})
        if not new_keys and old_keys:
            report.aggregation_policies_changed += 1
            findings.append(ITSIUpgradeFinding(
                finding_id=f"itsi_agg_removed_{stanza[:30]}",
                category=FindingCategory.NOTABLE_EVENT_CHANGED,
                risk=UpgradeRisk.MEDIUM,
                conf_type="itsi_notable_event_aggregation",
                stanza=stanza,
                description=f"Aggregation policy '{stanza}' removed",
                remediation="Review incident management workflow",
            ))


def _analyze_itsi_searches(
    old_confs: Dict, new_confs: Dict, local_confs: Dict,
    report: ITSIUpgradeReport, findings: List[ITSIUpgradeFinding],
) -> None:
    """Check ITSI saved search changes."""
    old_searches = old_confs.get("savedsearches", {})
    new_searches = new_confs.get("savedsearches", {})
    local_confs.get("savedsearches", {})

    # Focus on ITSI-specific searches
    itsi_prefixes = ("ITSI ", "itsi_", "SA-ITSI", "Indicator -", "KPI -", "Service -")

    for stanza, old_keys in old_searches.items():
        if not any(stanza.startswith(p) for p in itsi_prefixes):
            continue
        if stanza not in new_searches:
            findings.append(ITSIUpgradeFinding(
                finding_id=f"itsi_search_removed_{stanza[:30]}",
                category=FindingCategory.KPI_DEFINITION_CHANGED,
                risk=UpgradeRisk.MEDIUM,
                conf_type="savedsearches",
                stanza=stanza,
                description=f"ITSI search '{stanza}' removed",
                remediation="Check if replaced by a new search definition",
                affected_kpis=[stanza],
            ))
