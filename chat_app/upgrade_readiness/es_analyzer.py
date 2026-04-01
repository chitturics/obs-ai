"""Enterprise Security (ES) Upgrade Analyzer.

Handles ES-specific upgrade risks:
- Correlation search changes (new/modified/removed rules)
- Risk rule framework changes
- Notable event schema changes
- Threat intelligence feed changes
- ES Content Update (DA-ESS-ContentUpdate) impact
- Identity/asset lookup changes
- Dashboard and investigation changes

ES upgrade is the HIGHEST RISK upgrade type because:
1. Correlation searches are the heart of security monitoring
2. Risk rules affect notable event scoring
3. Content updates can silently change detection logic
4. Identity correlation changes affect all security alerts
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


# ---------------------------------------------------------------------------
# ES-specific conf files and their risk significance
# ---------------------------------------------------------------------------

ES_CRITICAL_CONFS = {
    "savedsearches.conf": "Correlation searches, reports, alerts",
    "correlationsearches.conf": "ES correlation search definitions",
    "transforms.conf": "Lookup definitions for identity/asset/threat intel",
    "macros.conf": "Security domain macros used in searches",
    "eventtypes.conf": "Event classification for CIM",
    "tags.conf": "CIM tag assignments",
}

ES_HIGH_RISK_CONFS = {
    "analytic_stories.conf": "MITRE ATT&CK story mappings",
    "governance.conf": "Compliance framework rules",
    "identities.conf": "Identity management configuration",
    "notable_event_types.conf": "Notable event severity and workflow",
    "risk_analysis.conf": "Risk scoring configuration",
}

# Key ES macros that if changed break many correlation searches
ES_CRITICAL_MACROS = [
    "authentication", "change", "endpoint_processes", "endpoint_services",
    "endpoint_filesystem", "endpoint_registry", "intrusion_detection",
    "malware", "network_traffic", "web", "email", "dns", "certificate",
    "vulnerability", "security_domain", "notable", "risk_object_type",
    "get_notable_info", "risk_correlation_by_system",
]


@dataclass
class ESUpgradeFinding:
    """Extended finding for ES-specific issues."""
    finding_id: str = ""
    category: FindingCategory = FindingCategory.CORRELATION_SEARCH_BROKEN
    risk: UpgradeRisk = UpgradeRisk.INFO
    conf_type: str = ""
    stanza: str = ""
    key: str = ""
    old_value: str = ""
    new_value: str = ""
    description: str = ""
    remediation: str = ""
    """Extended finding for ES-specific issues."""
    affected_correlation_searches: List[str] = field(default_factory=list)
    affected_risk_rules: List[str] = field(default_factory=list)
    mitre_techniques_affected: List[str] = field(default_factory=list)
    detection_gap: bool = False  # True if this creates a monitoring blind spot


@dataclass
class ESUpgradeReport:
    """ES-specific upgrade analysis report."""
    upgrade_type: str = UpgradeType.ES.value
    old_version: str = ""
    new_version: str = ""

    # Counts
    correlation_searches_added: int = 0
    correlation_searches_removed: int = 0
    correlation_searches_modified: int = 0
    risk_rules_changed: int = 0
    macros_changed: int = 0
    lookups_changed: int = 0

    # Findings
    findings: List[ESUpgradeFinding] = field(default_factory=list)
    overall_risk: UpgradeRisk = UpgradeRisk.INFO
    recommendation: str = ""

    # Detection coverage
    detection_gaps: List[str] = field(default_factory=list)  # Techniques no longer covered
    new_detections: List[str] = field(default_factory=list)  # New techniques covered

    def to_dict(self) -> Dict[str, Any]:
        return {
            "upgrade_type": self.upgrade_type,
            "old_version": self.old_version,
            "new_version": self.new_version,
            "correlation_searches": {
                "added": self.correlation_searches_added,
                "removed": self.correlation_searches_removed,
                "modified": self.correlation_searches_modified,
            },
            "risk_rules_changed": self.risk_rules_changed,
            "macros_changed": self.macros_changed,
            "lookups_changed": self.lookups_changed,
            "findings_count": len(self.findings),
            "overall_risk": self.overall_risk.value,
            "recommendation": self.recommendation,
            "detection_gaps": self.detection_gaps,
            "new_detections": self.new_detections,
        }


def analyze_es_upgrade(
    old_confs: Dict[str, Dict[str, Dict[str, str]]],
    new_confs: Dict[str, Dict[str, Dict[str, str]]],
    local_confs: Dict[str, Dict[str, Dict[str, str]]],
) -> ESUpgradeReport:
    """Analyze Enterprise Security upgrade impact.

    Args:
        old_confs: conf_type -> stanza -> key-value (old ES version default/)
        new_confs: conf_type -> stanza -> key-value (new ES version default/)
        local_confs: conf_type -> stanza -> key-value (org local/ overrides)

    Returns:
        ESUpgradeReport with findings and risk assessment.
    """
    report = ESUpgradeReport()
    findings: List[ESUpgradeFinding] = []

    # 1. Analyze correlation searches
    old_searches = old_confs.get("savedsearches", {})
    new_searches = new_confs.get("savedsearches", {})
    local_searches = local_confs.get("savedsearches", {})

    _analyze_correlation_searches(old_searches, new_searches, local_searches, report, findings)

    # 2. Analyze macros (critical for ES)
    old_macros = old_confs.get("macros", {})
    new_macros = new_confs.get("macros", {})
    local_macros = local_confs.get("macros", {})

    _analyze_es_macros(old_macros, new_macros, local_macros, report, findings)

    # 3. Analyze lookups (identity, asset, threat intel)
    old_transforms = old_confs.get("transforms", {})
    new_transforms = new_confs.get("transforms", {})

    _analyze_es_lookups(old_transforms, new_transforms, report, findings)

    # 4. Score overall risk
    report.findings = findings
    if any(f.detection_gap for f in findings):
        report.overall_risk = UpgradeRisk.CRITICAL
        report.recommendation = "DO NOT UPGRADE without addressing detection gaps"
    elif report.correlation_searches_removed > 0:
        report.overall_risk = UpgradeRisk.HIGH
        report.recommendation = "Review removed correlation searches before upgrade"
    elif report.correlation_searches_modified > 5:
        report.overall_risk = UpgradeRisk.HIGH
        report.recommendation = "Review modified correlation searches — detection logic changed"
    elif len(findings) > 0:
        max_risk = max(f.risk for f in findings) if findings else UpgradeRisk.INFO
        report.overall_risk = max_risk
        report.recommendation = f"Review {len(findings)} findings before upgrade"
    else:
        report.recommendation = "Safe to upgrade — no ES-specific issues found"

    return report


def _analyze_correlation_searches(
    old_searches: Dict[str, Dict[str, str]],
    new_searches: Dict[str, Dict[str, str]],
    local_searches: Dict[str, Dict[str, str]],
    report: ESUpgradeReport,
    findings: List[ESUpgradeFinding],
) -> None:
    """Analyze changes to correlation searches."""
    # Find correlation searches (have action.correlationsearch.enabled = 1)
    def _is_correlation(stanza: Dict[str, str]) -> bool:
        return stanza.get("action.correlationsearch.enabled") == "1"

    old_corr = {k: v for k, v in old_searches.items() if _is_correlation(v)}
    new_corr = {k: v for k, v in new_searches.items() if _is_correlation(v)}

    # Removed correlation searches
    for name in old_corr:
        if name not in new_corr:
            report.correlation_searches_removed += 1
            is_customized = name in local_searches
            findings.append(ESUpgradeFinding(
                finding_id=f"es_corr_removed_{name[:30]}",
                category=FindingCategory.CORRELATION_SEARCH_BROKEN,
                risk=UpgradeRisk.CRITICAL if is_customized else UpgradeRisk.HIGH,
                conf_type="savedsearches",
                stanza=name,
                description=f"Correlation search '{name}' removed in new version" +
                           (" (has local customizations)" if is_customized else ""),
                remediation="Add back as custom correlation search in local/savedsearches.conf",
                detection_gap=True,
                affected_correlation_searches=[name],
            ))

    # Added correlation searches
    for name in new_corr:
        if name not in old_corr:
            report.correlation_searches_added += 1

    # Modified correlation searches
    for name in old_corr:
        if name in new_corr:
            old_search = old_corr[name].get("search", "")
            new_search = new_corr[name].get("search", "")
            if old_search != new_search:
                report.correlation_searches_modified += 1
                local_override = local_searches.get(name, {}).get("search", "")
                findings.append(ESUpgradeFinding(
                    finding_id=f"es_corr_modified_{name[:30]}",
                    category=FindingCategory.CORRELATION_SEARCH_BROKEN,
                    risk=UpgradeRisk.LOW if local_override else UpgradeRisk.MEDIUM,
                    conf_type="savedsearches",
                    stanza=name,
                    key="search",
                    old_value=old_search[:200],
                    new_value=new_search[:200],
                    description=f"Correlation search '{name}' SPL changed" +
                               (" (local override exists — yours wins)" if local_override else ""),
                    remediation="Review new detection logic for false positive/negative impact",
                    affected_correlation_searches=[name],
                ))


def _analyze_es_macros(
    old_macros: Dict[str, Dict[str, str]],
    new_macros: Dict[str, Dict[str, str]],
    local_macros: Dict[str, Dict[str, str]],
    report: ESUpgradeReport,
    findings: List[ESUpgradeFinding],
) -> None:
    """Analyze changes to ES security domain macros."""
    for macro_name in ES_CRITICAL_MACROS:
        old_def = old_macros.get(macro_name, {}).get("definition", "")
        new_def = new_macros.get(macro_name, {}).get("definition", "")

        if old_def and new_def and old_def != new_def:
            report.macros_changed += 1
            local_def = local_macros.get(macro_name, {}).get("definition", "")
            findings.append(ESUpgradeFinding(
                finding_id=f"es_macro_{macro_name}",
                category=FindingCategory.CORRELATION_SEARCH_BROKEN,
                risk=UpgradeRisk.LOW if local_def else UpgradeRisk.HIGH,
                conf_type="macros",
                stanza=macro_name,
                key="definition",
                old_value=old_def[:200],
                new_value=new_def[:200],
                description=f"Critical ES macro '{macro_name}' definition changed — affects many correlation searches" +
                           (" (local override exists)" if local_def else ""),
                remediation=f"Review all correlation searches using `{macro_name}` macro",
            ))
        elif old_def and not new_def:
            report.macros_changed += 1
            findings.append(ESUpgradeFinding(
                finding_id=f"es_macro_removed_{macro_name}",
                category=FindingCategory.CORRELATION_SEARCH_BROKEN,
                risk=UpgradeRisk.CRITICAL,
                conf_type="macros",
                stanza=macro_name,
                description=f"Critical ES macro '{macro_name}' REMOVED — will break correlation searches",
                remediation=f"Add macro back in local/macros.conf with definition: {old_def[:100]}",
                detection_gap=True,
            ))


def _analyze_es_lookups(
    old_transforms: Dict[str, Dict[str, str]],
    new_transforms: Dict[str, Dict[str, str]],
    report: ESUpgradeReport,
    findings: List[ESUpgradeFinding],
) -> None:
    """Analyze changes to ES lookup definitions (identity, asset, threat intel)."""
    es_lookup_prefixes = ("identity_", "asset_", "threat_", "notable_", "cim_", "urgency_")

    for stanza, keys in old_transforms.items():
        if not any(stanza.startswith(p) or stanza.endswith("_lookup") for p in es_lookup_prefixes):
            continue
        if not keys.get("filename"):
            continue  # Not a lookup definition

        new_keys = new_transforms.get(stanza, {})
        if not new_keys:
            report.lookups_changed += 1
            findings.append(ESUpgradeFinding(
                finding_id=f"es_lookup_removed_{stanza}",
                category=FindingCategory.THREAT_INTEL_CHANGED,
                risk=UpgradeRisk.HIGH,
                conf_type="transforms",
                stanza=stanza,
                description=f"ES lookup '{stanza}' removed — may affect identity/asset correlation",
                remediation="Check if lookup was renamed or replaced by a new definition",
            ))
        else:
            old_fields = keys.get("fields_list", "")
            new_fields = new_keys.get("fields_list", "")
            if old_fields and new_fields and old_fields != new_fields:
                report.lookups_changed += 1
                findings.append(ESUpgradeFinding(
                    finding_id=f"es_lookup_changed_{stanza}",
                    category=FindingCategory.THREAT_INTEL_CHANGED,
                    risk=UpgradeRisk.MEDIUM,
                    conf_type="transforms",
                    stanza=stanza,
                    key="fields_list",
                    old_value=old_fields,
                    new_value=new_fields,
                    description=f"ES lookup '{stanza}' fields changed",
                    remediation="Update saved searches using old field names",
                ))


def detect_upgrade_type(app_id: str, app_title: str = "") -> UpgradeType:
    """Auto-detect the upgrade type from app_id and title.

    Returns the most specific UpgradeType matching the app_id pattern (TA, ES, ITSI, etc.).
    """
    aid = app_id.lower()
    title = app_title.lower()

    if aid.startswith("splunk_ta_") or aid.startswith("ta-") or aid.startswith("ta_") or "add-on" in title:
        return UpgradeType.TA
    if "enterprisesecurity" in aid or "da-ess" in aid or aid == "splunkenterprisesecurityinstaller":
        return UpgradeType.ES
    if "itsi" in aid or "itsi" in title:
        return UpgradeType.ITSI
    if "sa-" in aid or "sa_" in aid:
        return UpgradeType.SA
    if "da-" in aid or "da_" in aid:
        return UpgradeType.DA
    if aid == "da-ess-contentupdate":
        return UpgradeType.ES_CONTENT
    if "universalforwarder" in aid or "uf" in aid:
        return UpgradeType.UF
    return UpgradeType.APP
