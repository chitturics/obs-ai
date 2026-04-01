"""Upgrade Advisor — intelligent upgrade guidance engine.

Provides deep context for each upgrade decision:
1. App lookup with version history from Splunkbase catalog
2. Release notes analysis between versions
3. Upgrade path recommendation (skip versions or step-by-step)
4. Per-type capability description (what the tool checks for each type)
5. Pre-flight requirements (what data is needed)
6. Step-by-step execution plan with progress

This is the "brain" that makes the upgrade readiness tool intelligent.
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Upgrade type capabilities — what we check for each type
# ---------------------------------------------------------------------------

UPGRADE_TYPE_INFO: Dict[str, Dict[str, Any]] = {
    "ta": {
        "label": "Technology Add-on (TA)",
        "description": "TAs provide field extractions, transforms, lookups, and event typing for specific data sources.",
        "what_we_check": [
            "props.conf — field extractions (EXTRACT, REPORT, FIELDALIAS, EVAL)",
            "transforms.conf — transform definitions (REGEX, FORMAT, lookup definitions)",
            "eventtypes.conf — event classification for CIM compliance",
            "tags.conf — CIM tag assignments",
            "Index-time settings — LINE_BREAKER, TIME_FORMAT, TIME_PREFIX (CRITICAL)",
            "CIM compliance — 15 data models verified against field extractions",
            "Cross-app dependencies — which apps/searches depend on this TA's fields",
            "Local customization conflicts — your org overrides vs new defaults",
        ],
        "what_we_need": [
            "App/TA name (e.g., Splunk_TA_windows)",
            "Current version installed (auto-detected from repo if available)",
            "Target version (defaults to latest from Splunkbase)",
            "Cluster name (which search head cluster has this TA)",
        ],
        "risks": [
            "CRITICAL: Index-time field changes require re-indexing",
            "HIGH: Renamed field extractions break saved searches",
            "HIGH: CIM compliance regression breaks ES correlation searches",
            "MEDIUM: New default stanzas may conflict with local overrides",
        ],
    },
    "app": {
        "label": "Splunk App",
        "description": "Apps provide dashboards, saved searches, reports, alerts, and UI components.",
        "what_we_check": [
            "savedsearches.conf — all saved searches, reports, alerts",
            "macros.conf — macro definitions used by searches",
            "data/ui/views — dashboard XML changes",
            "lookups — lookup table file changes",
            "Navigation — app nav menu changes",
            "Local customization conflicts",
        ],
        "what_we_need": [
            "App name",
            "Current and target versions",
            "Cluster name",
        ],
        "risks": [
            "HIGH: Saved search SPL changes may alter results",
            "MEDIUM: Dashboard layout changes may confuse users",
            "LOW: New navigation items",
        ],
    },
    "es": {
        "label": "Splunk Enterprise Security (ES)",
        "description": "ES is the SIEM platform. Upgrades affect security monitoring, detection, and incident response.",
        "what_we_check": [
            "Correlation searches — new/modified/removed detection rules",
            "Risk rules — risk scoring framework changes",
            "Notable event types — severity and workflow changes",
            "Identity/asset management — lookup and correlation changes",
            "Threat intelligence — feed framework changes",
            "ES Content Update — DA-ESS-ContentUpdate changes",
            "Security domain macros — authentication, network, endpoint, etc.",
            "CIM compliance across ALL TAs feeding ES",
            "MITRE ATT&CK mapping changes",
            "Dashboard and investigation changes",
        ],
        "what_we_need": [
            "Current ES version",
            "Target ES version",
            "ES cluster name (typically cluster-es)",
            "List of installed TAs feeding ES data",
            "Current correlation search customizations",
        ],
        "risks": [
            "CRITICAL: Removed correlation searches create detection blind spots",
            "CRITICAL: CIM field changes break ALL correlation searches using that field",
            "HIGH: Risk framework changes affect notable event scoring",
            "HIGH: Security domain macro changes affect many searches simultaneously",
            "MEDIUM: New correlation searches may generate false positives initially",
        ],
    },
    "itsi": {
        "label": "IT Service Intelligence (ITSI)",
        "description": "ITSI monitors IT services via KPIs, glass tables, and service dependencies.",
        "what_we_check": [
            "Service definitions — dependency tree changes",
            "KPI definitions — threshold changes affect alerting sensitivity",
            "Glass table compatibility — visualization changes",
            "Notable event aggregation — policy changes",
            "Entity management — rules and classification",
            "Deep dive changes — investigation workflow",
            "Module visualization changes",
            "Maintenance window definitions",
        ],
        "what_we_need": [
            "Current ITSI version",
            "Target ITSI version",
            "ITSI cluster name (typically cluster-itsi)",
            "Custom KPI thresholds (local overrides)",
        ],
        "risks": [
            "CRITICAL: KPI threshold changes alter alerting sensitivity immediately",
            "HIGH: Service dependency changes break glass tables",
            "HIGH: Aggregation policy changes affect incident management",
            "MEDIUM: Entity rule changes affect service membership",
        ],
    },
    "uf": {
        "label": "Universal Forwarder (UF)",
        "description": "UFs collect and forward data to indexers. Upgrades affect data collection and forwarding.",
        "what_we_check": [
            "inputs.conf — data collection changes (file monitors, WMI, perfmon, scripted)",
            "outputs.conf — forwarding topology and load balancing",
            "deploymentclient.conf — deployment server communication",
            "SSL/TLS settings — certificate and cipher changes",
            "props.conf — index-time field extraction changes",
            "Version compatibility — UF vs indexer cluster version matrix",
            "Resource usage — memory and CPU impact",
        ],
        "what_we_need": [
            "Current UF version",
            "Target UF version",
            "Indexer cluster version",
            "Forwarder group (which deployment server app set)",
            "SSL certificate configuration",
        ],
        "risks": [
            "CRITICAL: Input removal causes DATA LOSS",
            "CRITICAL: SSL/TLS incompatibility disconnects forwarder from indexers",
            "HIGH: Index-time props changes require indexer cluster coordination",
            "HIGH: Output topology changes may route data to wrong indexers",
            "MEDIUM: New defaults may increase resource usage",
        ],
    },
    "splunk_core": {
        "label": "Splunk Enterprise (Core Platform)",
        "description": "Core Splunk platform upgrade affects all apps, TAs, and infrastructure.",
        "what_we_check": [
            "Platform compatibility — all installed apps vs new Splunk version",
            "Deprecated features — removed or changed platform APIs",
            "Python version changes — script compatibility",
            "REST API changes — custom integrations",
            "Search command changes — SPL syntax evolution",
            "Cluster upgrade order — indexer vs search head vs deployer",
            "License compatibility",
        ],
        "what_we_need": [
            "Current Splunk version",
            "Target Splunk version",
            "All installed apps and their versions",
            "Custom Python scripts",
            "Custom search commands",
            "Cluster topology",
        ],
        "risks": [
            "CRITICAL: Incompatible apps may fail to load",
            "CRITICAL: Python 2→3 migration breaks scripts",
            "HIGH: Deprecated REST endpoints break integrations",
            "HIGH: Search command syntax changes break saved searches",
            "MEDIUM: Performance characteristics may change",
        ],
    },
}


# ---------------------------------------------------------------------------
# Upgrade path analysis
# ---------------------------------------------------------------------------

@dataclass
class VersionInfo:
    """Information about a specific version of an app."""
    version: str
    release_date: str = ""
    supported_splunk_versions: List[str] = field(default_factory=list)
    is_latest: bool = False
    is_current: bool = False


@dataclass
class UpgradePath:
    """Recommended upgrade path between two versions."""
    from_version: str
    to_version: str
    intermediate_versions: List[str] = field(default_factory=list)
    total_releases_skipped: int = 0
    recommendation: str = ""  # "direct" or "step-by-step"
    reason: str = ""


@dataclass
class UpgradeAdvisorResult:
    """Complete advisor output for a selected app/type."""
    app_id: str = ""
    app_title: str = ""
    upgrade_type: str = ""
    type_info: Dict[str, Any] = field(default_factory=dict)
    current_version: str = ""
    latest_version: str = ""
    all_versions: List[VersionInfo] = field(default_factory=list)
    upgrade_path: Optional[UpgradePath] = None
    pre_flight_checklist: List[str] = field(default_factory=list)
    execution_steps: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "app_id": self.app_id,
            "app_title": self.app_title,
            "upgrade_type": self.upgrade_type,
            "type_info": self.type_info,
            "current_version": self.current_version,
            "latest_version": self.latest_version,
            "all_versions": [
                {"version": v.version, "release_date": v.release_date,
                 "supported_splunk": v.supported_splunk_versions[:3],
                 "is_latest": v.is_latest, "is_current": v.is_current}
                for v in self.all_versions
            ],
            "upgrade_path": {
                "from": self.upgrade_path.from_version,
                "to": self.upgrade_path.to_version,
                "skipped": self.upgrade_path.total_releases_skipped,
                "recommendation": self.upgrade_path.recommendation,
                "reason": self.upgrade_path.reason,
                "intermediate": self.upgrade_path.intermediate_versions,
            } if self.upgrade_path else None,
            "pre_flight_checklist": self.pre_flight_checklist,
            "execution_steps": self.execution_steps,
        }


def get_type_info(upgrade_type: str) -> Dict[str, Any]:
    """Get detailed capability info for an upgrade type."""
    return UPGRADE_TYPE_INFO.get(upgrade_type, UPGRADE_TYPE_INFO.get("app", {}))


def lookup_app(app_id: str) -> Optional[Dict[str, Any]]:
    """Look up an app in the Splunkbase catalog."""
    try:
        from chat_app.splunkbase_catalog import get_splunkbase_catalog
        catalog = get_splunkbase_catalog()
        cat_data = catalog.catalog
        apps = cat_data.get("apps", {})

        # Search by app_id (case-insensitive)
        app_id_lower = app_id.lower()
        for uid, app in apps.items():
            if app.get("app_id", "").lower() == app_id_lower:
                return app
            if app.get("title", "").lower() == app_id_lower:
                return app

        # Fuzzy search
        for uid, app in apps.items():
            if app_id_lower in app.get("app_id", "").lower() or app_id_lower in app.get("title", "").lower():
                return app

        return None
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[UPGRADE] Catalog lookup failed: %s", exc)
        return None


def get_version_history(app_data: Dict[str, Any]) -> List[VersionInfo]:
    """Extract version history from Splunkbase app data."""
    releases = app_data.get("releases", [])
    latest = app_data.get("latest_version", "")
    versions = []
    for r in releases:
        versions.append(VersionInfo(
            version=r.get("version", ""),
            release_date=r.get("release_date", "")[:10] if r.get("release_date") else "",
            supported_splunk_versions=r.get("product_versions", []),
            is_latest=(r.get("version") == latest),
        ))
    return versions


def compute_upgrade_path(
    from_version: str,
    to_version: str,
    all_versions: List[VersionInfo],
) -> UpgradePath:
    """Compute the recommended upgrade path."""
    version_list = [v.version for v in all_versions]

    # Find indices
    from_idx = -1
    to_idx = -1
    for i, v in enumerate(version_list):
        if v == from_version:
            from_idx = i
        if v == to_version:
            to_idx = i

    skipped = abs(to_idx - from_idx) - 1 if from_idx >= 0 and to_idx >= 0 else 0
    intermediate = version_list[min(from_idx, to_idx) + 1:max(from_idx, to_idx)] if from_idx >= 0 and to_idx >= 0 else []

    # Major version jump detection
    try:
        from_major = int(from_version.split(".")[0])
        to_major = int(to_version.split(".")[0])
        major_jump = to_major - from_major
    except (ValueError, IndexError):
        major_jump = 0

    if major_jump >= 2:
        recommendation = "step-by-step"
        reason = f"Major version jump ({from_major}.x → {to_major}.x). Recommend testing intermediate major versions."
    elif skipped > 10:
        recommendation = "step-by-step"
        reason = f"Skipping {skipped} releases. Consider testing a mid-point version first."
    else:
        recommendation = "direct"
        reason = f"Direct upgrade is safe ({skipped} intermediate releases)."

    return UpgradePath(
        from_version=from_version,
        to_version=to_version,
        intermediate_versions=intermediate[:10],  # Cap at 10
        total_releases_skipped=skipped,
        recommendation=recommendation,
        reason=reason,
    )


def build_execution_steps(upgrade_type: str, app_id: str) -> List[Dict[str, str]]:
    """Build step-by-step execution plan."""
    common_steps = [
        {"step": "1", "action": "Backup current configuration", "detail": f"Export current {app_id} default/ and local/ configs"},
        {"step": "2", "action": "Review release notes", "detail": "Check for breaking changes, deprecated features, new requirements"},
        {"step": "3", "action": "Run static analysis", "detail": "Three-way diff: old default ⟷ new default ⟷ local customizations"},
    ]

    type_steps = {
        "ta": [
            {"step": "4", "action": "Check CIM compliance", "detail": "Verify field extractions still satisfy CIM data models"},
            {"step": "5", "action": "Check index-time impact", "detail": "LINE_BREAKER/TIME_FORMAT changes require re-indexing"},
            {"step": "6", "action": "Trace dependencies", "detail": "Find saved searches and apps that depend on this TA's fields"},
            {"step": "7", "action": "Test in staging", "detail": "Deploy to test cluster, verify field extractions"},
            {"step": "8", "action": "Deploy to production", "detail": "Apply via deployment server, monitor for errors"},
        ],
        "es": [
            {"step": "4", "action": "Audit correlation searches", "detail": "Compare old vs new detection rules, identify gaps"},
            {"step": "5", "action": "Check risk framework", "detail": "Review risk scoring and notable event changes"},
            {"step": "6", "action": "Verify CIM across all TAs", "detail": "Ensure ALL TAs feeding ES still provide required fields"},
            {"step": "7", "action": "Test in staging ES", "detail": "Deploy to test ES instance, run detection validation"},
            {"step": "8", "action": "Deploy with change window", "detail": "ES upgrades require security team coordination"},
        ],
        "itsi": [
            {"step": "4", "action": "Check KPI thresholds", "detail": "Verify threshold changes won't alter alerting sensitivity"},
            {"step": "5", "action": "Verify glass tables", "detail": "Check visualization compatibility"},
            {"step": "6", "action": "Test in staging ITSI", "detail": "Deploy to test ITSI, verify service health views"},
            {"step": "7", "action": "Deploy with maintenance window", "detail": "ITSI upgrades may temporarily affect monitoring"},
        ],
        "uf": [
            {"step": "4", "action": "Check input compatibility", "detail": "Verify all monitored paths/WMI/perfmon still valid"},
            {"step": "5", "action": "Check SSL/TLS", "detail": "Ensure certificates and ciphers are compatible with indexers"},
            {"step": "6", "action": "Test data flow", "detail": "Deploy to test forwarder, verify events reach indexers"},
            {"step": "7", "action": "Rolling upgrade", "detail": "Upgrade forwarders in batches, monitoring for data gaps"},
        ],
    }

    return common_steps + type_steps.get(upgrade_type, [
        {"step": "4", "action": "Review changes", "detail": "Check all modified configurations"},
        {"step": "5", "action": "Deploy to staging", "detail": "Test in non-production environment"},
        {"step": "6", "action": "Deploy to production", "detail": "Apply changes with monitoring"},
    ])


def build_preflight_checklist(upgrade_type: str) -> List[str]:
    """Build pre-flight requirements checklist."""
    common = [
        "✅ Current configuration backed up",
        "✅ Target version identified and available",
        "✅ Change window scheduled (if production)",
    ]

    type_specific = {
        "ta": [
            "✅ Org repo has current default/ and local/ configs",
            "✅ CIM data model definitions available",
            "✅ List of dependent saved searches identified",
        ],
        "es": [
            "✅ Current correlation search inventory captured",
            "✅ Risk framework configuration documented",
            "✅ All TA versions feeding ES verified",
            "✅ Security team notified of change window",
        ],
        "itsi": [
            "✅ Current KPI thresholds documented",
            "✅ Service dependency tree mapped",
            "✅ Glass table inventory captured",
            "✅ Maintenance window configured",
        ],
        "uf": [
            "✅ Indexer cluster version confirmed compatible",
            "✅ SSL certificates valid and compatible",
            "✅ Deployment server app inventory current",
            "✅ Rollback plan prepared (keep old .tgz)",
        ],
    }

    return common + type_specific.get(upgrade_type, [])


def get_upgrade_advice(
    app_id: str,
    upgrade_type: str = "ta",
    current_version: str = "",
) -> UpgradeAdvisorResult:
    """Get comprehensive upgrade advice for an app.

    This is the main entry point — combines catalog lookup, version analysis,
    type-specific capability info, and execution planning.
    """
    result = UpgradeAdvisorResult(
        app_id=app_id,
        upgrade_type=upgrade_type,
        type_info=get_type_info(upgrade_type),
    )

    # Look up app in Splunkbase catalog
    app_data = lookup_app(app_id)
    if app_data:
        result.app_title = app_data.get("title", app_id)
        result.latest_version = app_data.get("latest_version", "")
        result.all_versions = get_version_history(app_data)

        # Mark current version
        if current_version:
            result.current_version = current_version
            for v in result.all_versions:
                if v.version == current_version:
                    v.is_current = True

        # Compute upgrade path
        if current_version and result.latest_version:
            result.upgrade_path = compute_upgrade_path(
                current_version, result.latest_version, result.all_versions,
            )
    else:
        result.app_title = app_id
        result.latest_version = "unknown (not in Splunkbase catalog)"

    # Build execution plan
    result.execution_steps = build_execution_steps(upgrade_type, app_id)
    result.pre_flight_checklist = build_preflight_checklist(upgrade_type)

    return result
