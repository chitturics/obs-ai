"""
Splunk Upgrade Readiness Testing System — Public API.

This package provides static analysis tools for assessing the risk of
upgrading Splunk Technology Add-ons (TAs) and apps within an organisation's
multi-cluster Splunk deployment.

Sprint 1 exports:
    models         — All data models (enums, dataclasses, Pydantic models)
    conf_differ    — Three-way conf diffing engine
    impact_scorer  — Risk scoring and recommendation generation
    baseline_builder — App directory scanning and baseline construction

Sprint 2 exports:
    cim_analyzer      — CIM data model compliance checker + upgrade regression detection
    dependency_tracer — Cross-app dependency graph + impact tracing
    uf_analyzer       — Universal Forwarder specific upgrade analysis

Quick-start example::

    from chat_app.upgrade_readiness import (
        scan_app_directory,
        three_way_diff,
        build_impact_report,
    )

    old_baseline = scan_app_directory("/path/to/TA_v1")
    new_baseline = scan_app_directory("/path/to/TA_v2")

    findings = three_way_diff(
        old_default=old_baseline.get_default_stanzas("props"),
        new_default=new_baseline.get_default_stanzas("props"),
        local=old_baseline.get_local_stanzas("props"),
        conf_type="props",
        app_id="Splunk_TA_example",
    )

    report = build_impact_report(
        findings=findings,
        app_id="Splunk_TA_example",
        from_version=old_baseline.version.version,
        to_version=new_baseline.version.version,
    )

    print(report.recommendation)
    print(f"Findings: {report.critical_count} critical, {report.high_count} high")
"""

from chat_app.upgrade_readiness.baseline_builder import (
    extract_app_version,
    match_splunkbase_versions,
    scan_app_directory,
    scan_cluster_directory,
)
from chat_app.upgrade_readiness.conf_differ import (
    build_stanza_diff,
    diff_stanza,
    simulate_splunk_merge,
    three_way_diff,
)
from chat_app.upgrade_readiness.impact_scorer import (
    build_impact_report,
    classify_risk,
    compute_overall_risk,
    generate_recommendation,
    score_findings,
    summarize_impact,
)
from chat_app.upgrade_readiness.uf_analyzer import (
    CompatResult,
    UFRiskFinding,
    UFUpgradeReport,
    analyze_uf_upgrade,
    check_indexer_compat,
)
from chat_app.upgrade_readiness.cim_analyzer import (
    CIM_MODELS,
    CIMRegressionFinding,
    CIMValidationResult,
    check_cim_compliance,
    check_upgrade_cim_impact,
    get_cim_summary,
)
from chat_app.upgrade_readiness.dependency_tracer import (
    DependencyGraph,
    GraphEdge,
    GraphNode,
    ImpactPath,
    build_dependency_graph,
    get_dependency_summary,
    trace_impact,
)
from chat_app.upgrade_readiness.models import (
    AnalyzeUpgradeRequest,
    AppBaseline,
    AppVersion,
    ClusterInventory,
    ConfFileType,
    ContainerTestCase,
    ContainerTestResult,
    ContainerTestSuite,
    FindingCategory,
    FindingResponse,
    INDEX_TIME_KEYS,
    OrgInventory,
    StanzaDiff,
    StanzaSnapshot,
    TestStatus,
    UpgradeFinding,
    UpgradeImpactReport,
    UpgradeReportResponse,
    UpgradeRisk,
)

__all__ = [
    # Models
    "UpgradeRisk",
    "FindingCategory",
    "ConfFileType",
    "TestStatus",
    "INDEX_TIME_KEYS",
    "AppVersion",
    "StanzaSnapshot",
    "AppBaseline",
    "ClusterInventory",
    "OrgInventory",
    "StanzaDiff",
    "UpgradeFinding",
    "UpgradeImpactReport",
    "ContainerTestCase",
    "ContainerTestResult",
    "ContainerTestSuite",
    "AnalyzeUpgradeRequest",
    "FindingResponse",
    "UpgradeReportResponse",
    # Differ
    "three_way_diff",
    "diff_stanza",
    "simulate_splunk_merge",
    "build_stanza_diff",
    # Scorer
    "score_findings",
    "classify_risk",
    "generate_recommendation",
    "compute_overall_risk",
    "summarize_impact",
    "build_impact_report",
    # Baseline
    "scan_app_directory",
    "extract_app_version",
    "scan_cluster_directory",
    "match_splunkbase_versions",
    # UF Analyzer (Sprint 2) — also exported below for consistency
    # CIM Analyzer (Sprint 2)
    "CIM_MODELS",
    "CIMValidationResult",
    "CIMRegressionFinding",
    "check_cim_compliance",
    "check_upgrade_cim_impact",
    "get_cim_summary",
    # Dependency Tracer (Sprint 2)
    "DependencyGraph",
    "GraphNode",
    "GraphEdge",
    "ImpactPath",
    "build_dependency_graph",
    "trace_impact",
    "get_dependency_summary",
    # UF Analyzer (Sprint 2)
    "UFUpgradeReport",
    "UFRiskFinding",
    "CompatResult",
    "analyze_uf_upgrade",
    "check_indexer_compat",
]

# Sprint 2+ exports: ES, ITSI, and upgrade type detection
from chat_app.upgrade_readiness.models import UpgradeType  # noqa: F401
from chat_app.upgrade_readiness.es_analyzer import (  # noqa: F401
    analyze_es_upgrade,
    detect_upgrade_type,
    ESUpgradeReport,
    ESUpgradeFinding,
)
from chat_app.upgrade_readiness.itsi_analyzer import (  # noqa: F401
    analyze_itsi_upgrade,
    ITSIUpgradeReport,
    ITSIUpgradeFinding,
)
