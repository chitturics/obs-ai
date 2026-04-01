"""
Data models for the Splunk Upgrade Readiness Testing System.

Frozen dataclasses are used for immutable result objects.
Regular dataclasses are used for mutable state containers.
Pydantic models are used for API request/response boundaries.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional


def _utcnow() -> datetime:
    """Return current UTC datetime as a timezone-aware object."""
    return datetime.now(timezone.utc)

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class UpgradeRisk(str, Enum):
    """Risk level for an upgrade finding, ordered low → high."""

    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    def __lt__(self, other: "UpgradeRisk") -> bool:
        order = list(UpgradeRisk)
        return order.index(self) < order.index(other)

    def __le__(self, other: "UpgradeRisk") -> bool:
        return self == other or self < other


class UpgradeType(str, Enum):
    """Type of Splunk component being upgraded."""

    APP = "app"                         # Generic Splunk app (dashboards, saved searches)
    TA = "ta"                           # Technology Add-on (field extractions, transforms)
    UF = "uf"                           # Universal Forwarder (inputs, outputs, forwarding)
    ES = "es"                           # Enterprise Security (correlation searches, risk rules)
    ITSI = "itsi"                       # IT Service Intelligence (KPIs, services, glass tables)
    ES_CONTENT = "es_content"           # ES Content Update (DA-ESS-ContentUpdate)
    SA = "sa"                           # Supporting Add-on (SA-CIM, SA-NetworkProtection, etc.)
    DA = "da"                           # Domain Add-on (DA-ESS-*, DA-ITSI-*)
    SPLUNK_CORE = "splunk_core"         # Splunk Enterprise core platform upgrade


class FindingCategory(str, Enum):
    """Broad category for an upgrade finding."""

    STANZA_REMOVED = "STANZA_REMOVED"
    STANZA_ADDED = "STANZA_ADDED"
    KEY_REMOVED = "KEY_REMOVED"
    KEY_ADDED = "KEY_ADDED"
    KEY_CHANGED = "KEY_CHANGED"
    INDEX_TIME_CHANGE = "INDEX_TIME_CHANGE"
    MERGE_CONFLICT = "MERGE_CONFLICT"
    ORPHANED_LOCAL = "ORPHANED_LOCAL"
    # ES-specific
    CORRELATION_SEARCH_BROKEN = "CORRELATION_SEARCH_BROKEN"
    RISK_RULE_CHANGED = "RISK_RULE_CHANGED"
    NOTABLE_EVENT_CHANGED = "NOTABLE_EVENT_CHANGED"
    THREAT_INTEL_CHANGED = "THREAT_INTEL_CHANGED"
    # ITSI-specific
    KPI_DEFINITION_CHANGED = "KPI_DEFINITION_CHANGED"
    SERVICE_DEFINITION_CHANGED = "SERVICE_DEFINITION_CHANGED"
    GLASS_TABLE_BROKEN = "GLASS_TABLE_BROKEN"
    THRESHOLD_CHANGED = "THRESHOLD_CHANGED"
    # UF-specific
    DATA_LOSS_RISK = "DATA_LOSS_RISK"
    FORWARDING_CHANGED = "FORWARDING_CHANGED"
    SSL_INCOMPATIBLE = "SSL_INCOMPATIBLE"


class ConfFileType(str, Enum):
    """Known Splunk .conf file types tracked by the differ."""

    PROPS = "props"
    TRANSFORMS = "transforms"
    INPUTS = "inputs"
    OUTPUTS = "outputs"
    SAVEDSEARCHES = "savedsearches"
    EVENTTYPES = "eventtypes"
    TAGS = "tags"
    MACROS = "macros"
    COLLECTIONS = "collections"
    APP = "app"
    ALERT_ACTIONS = "alert_actions"
    INDEXES = "indexes"
    OTHER = "other"

    @classmethod
    def from_filename(cls, filename: str) -> "ConfFileType":
        """Infer ConfFileType from a .conf filename."""
        stem = filename.lower().removesuffix(".conf")
        mapping = {
            "props": cls.PROPS,
            "transforms": cls.TRANSFORMS,
            "inputs": cls.INPUTS,
            "outputs": cls.OUTPUTS,
            "savedsearches": cls.SAVEDSEARCHES,
            "eventtypes": cls.EVENTTYPES,
            "tags": cls.TAGS,
            "macros": cls.MACROS,
            "collections": cls.COLLECTIONS,
            "app": cls.APP,
            "alert_actions": cls.ALERT_ACTIONS,
            "indexes": cls.INDEXES,
        }
        return mapping.get(stem, cls.OTHER)


class TestStatus(str, Enum):
    """Status of a container-based test case."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"
    ERROR = "ERROR"


# ---------------------------------------------------------------------------
# Index-time keys — changes to these keys are always CRITICAL
# ---------------------------------------------------------------------------

INDEX_TIME_KEYS = frozenset(
    {
        "LINE_BREAKER",
        "TIME_FORMAT",
        "TIME_PREFIX",
        "SHOULD_LINEMERGE",
        "MAX_TIMESTAMP_LOOKAHEAD",
        "BREAK_ONLY_BEFORE",
        "BREAK_ONLY_BEFORE_DATE",
        "MUST_BREAK_AFTER",
        "MUST_NOT_BREAK_AFTER",
        "MUST_NOT_BREAK_BEFORE",
        "EVENT_BREAKER",
        "EVENT_BREAKER_ENABLE",
        "DATETIME_CONFIG",
        "MAX_EVENTS",
        "TRUNCATE",
        "NO_BINARY_CHECK",
    }
)


# ---------------------------------------------------------------------------
# Baseline models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AppVersion:
    """Immutable snapshot of an app version extracted from app.conf."""

    app_id: str
    version: str
    build: str = ""
    author: str = ""
    label: str = ""
    description: str = ""

    def as_tuple(self) -> tuple:
        """Return a comparable version tuple, e.g. (1, 0, 0)."""
        parts = []
        for segment in self.version.split("."):
            try:
                parts.append(int(segment))
            except ValueError:
                parts.append(0)
        return tuple(parts)


@dataclass
class StanzaSnapshot:
    """Key-value pairs for a single stanza in a .conf file."""

    stanza_name: str
    keys: Dict[str, str] = field(default_factory=dict)
    source_file: str = ""
    line_start: int = 0


@dataclass
class AppBaseline:
    """Full parsed state of a Splunk app from its on-disk .conf files."""

    app_id: str
    version: AppVersion
    default_confs: Dict[str, Dict[str, Dict[str, str]]] = field(default_factory=dict)
    local_confs: Dict[str, Dict[str, Dict[str, str]]] = field(default_factory=dict)
    app_dir: str = ""

    def get_default_stanzas(self, conf_name: str) -> Dict[str, Dict[str, str]]:
        """Return stanzas for a conf type from default/, stripping __lines__ metadata."""
        raw = self.default_confs.get(conf_name, {})
        return {
            stanza: {k: v for k, v in keys.items() if k != "__lines__"}
            for stanza, keys in raw.items()
        }

    def get_local_stanzas(self, conf_name: str) -> Dict[str, Dict[str, str]]:
        """Return stanzas for a conf type from local/, stripping __lines__ metadata."""
        raw = self.local_confs.get(conf_name, {})
        return {
            stanza: {k: v for k, v in keys.items() if k != "__lines__"}
            for stanza, keys in raw.items()
        }


@dataclass
class ClusterInventory:
    """All apps found in a cluster's app directory."""

    cluster_name: str
    apps: Dict[str, AppBaseline] = field(default_factory=dict)
    scanned_at: datetime = field(default_factory=_utcnow)
    errors: List[str] = field(default_factory=list)


@dataclass
class OrgInventory:
    """All cluster inventories for an organisation."""

    clusters: Dict[str, ClusterInventory] = field(default_factory=dict)
    scanned_at: datetime = field(default_factory=_utcnow)


# ---------------------------------------------------------------------------
# Analysis models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StanzaDiff:
    """Records the difference for a single stanza between old and new default."""

    stanza_name: str
    conf_type: str
    old_keys: Dict[str, str]
    new_keys: Dict[str, str]
    local_keys: Dict[str, str]
    added_keys: frozenset
    removed_keys: frozenset
    changed_keys: frozenset  # keys present in both old and new with different values


@dataclass(frozen=True)
class UpgradeFinding:
    """A single actionable finding from the three-way conf diff analysis."""

    finding_id: str
    risk: UpgradeRisk
    category: FindingCategory
    conf_type: str
    stanza: str
    key: Optional[str]
    description: str
    old_value: Optional[str]
    new_value: Optional[str]
    local_value: Optional[str]
    recommendation: str
    app_id: str = ""

    @classmethod
    def create(
        cls,
        risk: UpgradeRisk,
        category: FindingCategory,
        conf_type: str,
        stanza: str,
        description: str,
        recommendation: str,
        key: Optional[str] = None,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
        local_value: Optional[str] = None,
        app_id: str = "",
    ) -> "UpgradeFinding":
        """Convenience constructor that auto-generates a finding_id."""
        return cls(
            finding_id=str(uuid.uuid4()),
            risk=risk,
            category=category,
            conf_type=conf_type,
            stanza=stanza,
            key=key,
            description=description,
            old_value=old_value,
            new_value=new_value,
            local_value=local_value,
            recommendation=recommendation,
            app_id=app_id,
        )


@dataclass
class UpgradeImpactReport:
    """Aggregated result of a full upgrade impact analysis."""

    report_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    app_id: str = ""
    from_version: str = ""
    to_version: str = ""
    cluster: str = ""
    findings: List[UpgradeFinding] = field(default_factory=list)
    overall_risk: UpgradeRisk = UpgradeRisk.INFO
    recommendation: str = ""
    generated_at: datetime = field(default_factory=_utcnow)
    risk_counts: Dict[str, int] = field(default_factory=dict)
    affected_conf_types: List[str] = field(default_factory=list)

    @property
    def critical_count(self) -> int:
        return sum(1 for f in self.findings if f.risk == UpgradeRisk.CRITICAL)

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.risk == UpgradeRisk.HIGH)

    @property
    def medium_count(self) -> int:
        return sum(1 for f in self.findings if f.risk == UpgradeRisk.MEDIUM)

    @property
    def low_count(self) -> int:
        return sum(1 for f in self.findings if f.risk == UpgradeRisk.LOW)

    @property
    def info_count(self) -> int:
        return sum(1 for f in self.findings if f.risk == UpgradeRisk.INFO)


# ---------------------------------------------------------------------------
# Container test models
# ---------------------------------------------------------------------------


@dataclass
class ContainerTestCase:
    """Definition of a single test category to run in a container."""

    test_id: str
    name: str
    description: str
    category: str
    command: str
    expected_exit_code: int = 0
    timeout_seconds: int = 60


@dataclass
class ContainerTestResult:
    """Result of executing a single ContainerTestCase."""

    test_id: str
    name: str
    status: TestStatus
    duration_seconds: float = 0.0
    output: str = ""
    error: str = ""
    before_value: Optional[Any] = None
    after_value: Optional[Any] = None
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ContainerTestSuite:
    """Collection of test cases and their results for one upgrade test run."""

    suite_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    app_id: str = ""
    from_version: str = ""
    to_version: str = ""
    container_id: str = ""
    splunk_version: str = "9.3.2"
    status: TestStatus = TestStatus.PENDING
    test_cases: List[ContainerTestCase] = field(default_factory=list)
    results: List[ContainerTestResult] = field(default_factory=list)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    before_snapshot: Dict[str, Any] = field(default_factory=dict)
    after_snapshot: Dict[str, Any] = field(default_factory=dict)

    @property
    def passed_count(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.PASSED)

    @property
    def failed_count(self) -> int:
        return sum(1 for r in self.results if r.status == TestStatus.FAILED)


# ---------------------------------------------------------------------------
# API models (Pydantic)
# ---------------------------------------------------------------------------


class AnalyzeUpgradeRequest(BaseModel):
    """Request body for POST /upgrade/analyze."""

    app_id: str = Field(..., description="App directory name, e.g. Splunk_TA_windows")
    cluster: str = Field(..., description="Cluster name, e.g. cluster-es")
    target_version: Optional[str] = Field(
        None, description="Target version; defaults to latest available"
    )
    include_container_test: bool = Field(
        False, description="Whether to run live container-based tests"
    )
    check_cim: bool = Field(True, description="Whether to run CIM compliance checks")
    validate_specs: bool = Field(True, description="Whether to validate against spec files")


class FindingResponse(BaseModel):
    """API-safe representation of a single UpgradeFinding."""

    finding_id: str
    risk: str
    category: str
    conf_type: str
    stanza: str
    key: Optional[str]
    description: str
    old_value: Optional[str]
    new_value: Optional[str]
    local_value: Optional[str]
    recommendation: str

    @classmethod
    def from_finding(cls, finding: UpgradeFinding) -> "FindingResponse":
        """Convert a domain UpgradeFinding to an API response model."""
        return cls(
            finding_id=finding.finding_id,
            risk=finding.risk.value,
            category=finding.category.value,
            conf_type=finding.conf_type,
            stanza=finding.stanza,
            key=finding.key,
            description=finding.description,
            old_value=finding.old_value,
            new_value=finding.new_value,
            local_value=finding.local_value,
            recommendation=finding.recommendation,
        )


class UpgradeReportResponse(BaseModel):
    """API response for an UpgradeImpactReport."""

    report_id: str
    app_id: str
    from_version: str
    to_version: str
    cluster: str
    overall_risk: str
    recommendation: str
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    info_count: int
    findings: List[FindingResponse]
    generated_at: str

    @classmethod
    def from_report(cls, report: UpgradeImpactReport) -> "UpgradeReportResponse":
        """Convert a domain UpgradeImpactReport to an API response."""
        return cls(
            report_id=report.report_id,
            app_id=report.app_id,
            from_version=report.from_version,
            to_version=report.to_version,
            cluster=report.cluster,
            overall_risk=report.overall_risk.value,
            recommendation=report.recommendation,
            critical_count=report.critical_count,
            high_count=report.high_count,
            medium_count=report.medium_count,
            low_count=report.low_count,
            info_count=report.info_count,
            findings=[FindingResponse.from_finding(f) for f in report.findings],
            generated_at=report.generated_at.isoformat(),
        )
