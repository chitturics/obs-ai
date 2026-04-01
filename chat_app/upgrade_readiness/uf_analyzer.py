"""
Universal Forwarder (UF) specific upgrade analysis for the Splunk Upgrade
Readiness Testing System.

UFs have a different risk profile from full Splunk instances:
- inputs.conf removal → immediate DATA LOSS (events stop being collected)
- outputs.conf changes → ROUTING risk (events sent to wrong indexers)
- props.conf LINE_BREAKER/TIME_FORMAT changes → INDEX-TIME PARSING risk
- SSL/TLS setting changes → CONNECTION risk (forwarder cannot connect)
- deploymentclient.conf changes → MANAGEMENT risk (forwarder becomes unmanaged)

Version compatibility matrix for UF ↔ indexer TLS negotiation:
- Splunk 9.0+ requires TLS 1.2 minimum by default
- Splunk 9.3+ drops TLS 1.0/1.1 support entirely
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from chat_app.upgrade_readiness.models import AppBaseline, UpgradeRisk

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# UF-specific risk factor constants
# ---------------------------------------------------------------------------

# props.conf keys that affect index-time parsing on the UF side
UF_INDEX_TIME_KEYS = frozenset(
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
        "TRUNCATE",
    }
)

# SSL/TLS keys in outputs.conf and inputs.conf
SSL_KEYS = frozenset(
    {
        "sslCertPath",
        "sslRootCAPath",
        "sslPassword",
        "sslVerifyServerCert",
        "sslCommonNameToCheck",
        "sslAltNameToCheck",
        "useSSL",
        "requireClientCert",
        "sslVersions",
        "cipherSuite",
    }
)

# Splunk version compatibility for UF ↔ indexer connections.
# Each entry: (min_uf_version, min_indexer_version, note)
# Versions stored as comparable tuples (major, minor, patch).
VERSION_COMPAT_MATRIX = [
    ((9, 0, 0), (8, 0, 0), "UF 9.0+ requires indexer 8.0+ for full TLS 1.2 support"),
    ((9, 3, 0), (9, 0, 0), "UF 9.3+ dropped TLS 1.0/1.1; indexer must be 9.0+"),
    ((9, 3, 0), (9, 3, 0), "UF 9.3+ strict cert validation; peer must also be 9.3+"),
]


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class UFRiskFinding:
    """
    A single risk finding from the UF upgrade analysis.

    Attributes:
        risk: Severity of this finding.
        category: Short category label (e.g. "DATA_LOSS", "ROUTING").
        conf_file: Which conf file the finding comes from.
        stanza: Stanza name involved.
        key: Optional key within the stanza.
        description: Human-readable description.
        recommendation: Suggested remediation.
        old_value: Value before upgrade (may be None for new stanzas).
        new_value: Value after upgrade (may be None for removed stanzas).
    """

    risk: UpgradeRisk
    category: str
    conf_file: str
    stanza: str
    key: Optional[str]
    description: str
    recommendation: str
    old_value: Optional[str] = None
    new_value: Optional[str] = None


@dataclass
class UFUpgradeReport:
    """
    Aggregated result of a UF-specific upgrade analysis.

    Attributes:
        forwarder_group: Name of the UF deployment group or host class.
        app_ids_analyzed: Apps that were compared.
        findings: All UF risk findings.
        overall_risk: Maximum risk across all findings.
        data_loss_risk: True if any DATA_LOSS category finding exists.
        routing_risk: True if any ROUTING category finding exists.
        connection_risk: True if any CONNECTION category finding exists.
        summary: Free-form dict for dashboard display.
    """

    forwarder_group: str
    app_ids_analyzed: List[str] = field(default_factory=list)
    findings: List[UFRiskFinding] = field(default_factory=list)
    overall_risk: UpgradeRisk = UpgradeRisk.INFO
    data_loss_risk: bool = False
    routing_risk: bool = False
    connection_risk: bool = False
    summary: Dict[str, object] = field(default_factory=dict)

    @property
    def critical_count(self) -> int:
        """Number of CRITICAL findings."""
        return sum(1 for f in self.findings if f.risk == UpgradeRisk.CRITICAL)

    @property
    def high_count(self) -> int:
        """Number of HIGH findings."""
        return sum(1 for f in self.findings if f.risk == UpgradeRisk.HIGH)


@dataclass
class CompatResult:
    """
    Result of a UF ↔ indexer version compatibility check.

    Attributes:
        uf_version: UF version string being evaluated.
        indexer_version: Indexer version string being evaluated.
        is_compatible: True if the version pair is fully compatible.
        warnings: List of compatibility warnings.
        blocking_issues: List of issues that will prevent connectivity.
    """

    uf_version: str
    indexer_version: str
    is_compatible: bool
    warnings: List[str] = field(default_factory=list)
    blocking_issues: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_version_tuple(version_string: str) -> tuple:
    """
    Convert a version string to a comparable integer tuple.

    Args:
        version_string: e.g. "9.3.1" or "9.0.2312".

    Returns:
        Tuple of integers, e.g. (9, 3, 1).  Non-numeric segments become 0.
    """
    parts = []
    for segment in version_string.split(".")[:3]:
        try:
            parts.append(int(segment))
        except ValueError:
            parts.append(0)
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts)


def _strip_lines_meta(stanza_data: Dict[str, str]) -> Dict[str, str]:
    """Remove the __lines__ bookkeeping key inserted by the conf parser."""
    return {k: v for k, v in stanza_data.items() if k != "__lines__"}


def _compare_stanza_dicts(
    old_stanzas: Dict[str, Dict[str, str]],
    new_stanzas: Dict[str, Dict[str, str]],
) -> Dict[str, Dict]:
    """
    Produce a structural comparison of two stanza dicts.

    Returns a dict with keys: removed_stanzas, added_stanzas,
    changed_keys (per stanza).
    """
    old_clean = {s: _strip_lines_meta(k) for s, k in old_stanzas.items()}
    new_clean = {s: _strip_lines_meta(k) for s, k in new_stanzas.items()}

    removed_stanzas = set(old_clean) - set(new_clean)
    added_stanzas = set(new_clean) - set(old_clean)
    changed_keys: Dict[str, Dict[str, tuple]] = {}

    for stanza in set(old_clean) & set(new_clean):
        old_keys = old_clean[stanza]
        new_keys = new_clean[stanza]
        for key in set(old_keys) | set(new_keys):
            old_val = old_keys.get(key)
            new_val = new_keys.get(key)
            if old_val != new_val:
                changed_keys.setdefault(stanza, {})[key] = (old_val, new_val)

    return {
        "removed_stanzas": removed_stanzas,
        "added_stanzas": added_stanzas,
        "changed_keys": changed_keys,
    }


def _effective_stanzas(app: AppBaseline, conf_name: str) -> Dict[str, Dict[str, str]]:
    """
    Return merged default + local stanzas for a conf file.

    Local keys override default keys within each stanza.
    """
    default = app.get_default_stanzas(conf_name)
    local = app.get_local_stanzas(conf_name)
    merged: Dict[str, Dict[str, str]] = {}
    for stanza, keys in default.items():
        merged[stanza] = dict(keys)
    for stanza, keys in local.items():
        if stanza in merged:
            merged[stanza].update(keys)
        else:
            merged[stanza] = dict(keys)
    return merged


# ---------------------------------------------------------------------------
# Risk analysis functions
# ---------------------------------------------------------------------------


def _check_inputs_conf(
    old_stanzas: Dict[str, Dict[str, str]],
    new_stanzas: Dict[str, Dict[str, str]],
) -> List[UFRiskFinding]:
    """
    Detect removed or disabled inputs that would cause data loss.

    An input stanza removal means the UF stops collecting that data source.
    A stanza with disabled = 1 / disabled = true in the new version is
    treated as a removal from a data-flow perspective.
    """
    findings: List[UFRiskFinding] = []
    diff = _compare_stanza_dicts(old_stanzas, new_stanzas)

    # Removed stanzas → data loss
    for stanza in diff["removed_stanzas"]:
        findings.append(
            UFRiskFinding(
                risk=UpgradeRisk.CRITICAL,
                category="DATA_LOSS",
                conf_file="inputs.conf",
                stanza=stanza,
                key=None,
                description=(
                    f"Input stanza [{stanza}] was removed in the new version. "
                    f"Data collection for this source will stop immediately."
                ),
                recommendation=(
                    f"Add [{stanza}] back to inputs.conf in local/ to preserve "
                    f"data collection, or confirm this source is intentionally retired."
                ),
            )
        )

    # Changed stanzas: check for disabled flag change
    for stanza, key_changes in diff["changed_keys"].items():
        if "disabled" in key_changes:
            old_val, new_val = key_changes["disabled"]
            if str(new_val).lower() in ("1", "true") and str(old_val).lower() not in ("1", "true"):
                findings.append(
                    UFRiskFinding(
                        risk=UpgradeRisk.HIGH,
                        category="DATA_LOSS",
                        conf_file="inputs.conf",
                        stanza=stanza,
                        key="disabled",
                        description=(
                            f"Input [{stanza}] was enabled before but is now disabled. "
                            f"Data collection will stop."
                        ),
                        recommendation=(
                            f"Set 'disabled = false' in local/inputs.conf [{stanza}] "
                            f"to re-enable data collection."
                        ),
                        old_value=old_val,
                        new_value=new_val,
                    )
                )

        # Monitor path changes
        if "path" in key_changes or "monitor" in key_changes:
            changed_key = "path" if "path" in key_changes else "monitor"
            old_val, new_val = key_changes[changed_key]
            findings.append(
                UFRiskFinding(
                    risk=UpgradeRisk.HIGH,
                    category="DATA_LOSS",
                    conf_file="inputs.conf",
                    stanza=stanza,
                    key=changed_key,
                    description=(
                        f"Input [{stanza}] monitor path changed from "
                        f"{old_val!r} to {new_val!r}. "
                        f"Events from the old path will no longer be collected."
                    ),
                    recommendation=(
                        f"Verify the new path {new_val!r} is correct, "
                        f"or override in local/inputs.conf to keep the old path."
                    ),
                    old_value=old_val,
                    new_value=new_val,
                )
            )

    return findings


def _check_outputs_conf(
    old_stanzas: Dict[str, Dict[str, str]],
    new_stanzas: Dict[str, Dict[str, str]],
) -> List[UFRiskFinding]:
    """
    Detect output routing changes that could redirect event flow.

    Checks server list changes in tcpout stanzas.
    """
    findings: List[UFRiskFinding] = []
    diff = _compare_stanza_dicts(old_stanzas, new_stanzas)

    for stanza in diff["removed_stanzas"]:
        findings.append(
            UFRiskFinding(
                risk=UpgradeRisk.HIGH,
                category="ROUTING",
                conf_file="outputs.conf",
                stanza=stanza,
                key=None,
                description=(
                    f"Output stanza [{stanza}] was removed. "
                    f"Forwarding configuration has changed."
                ),
                recommendation=(
                    f"Verify the new outputs.conf still routes to the correct indexers. "
                    f"Restore [{stanza}] in local/outputs.conf if needed."
                ),
            )
        )

    for stanza, key_changes in diff["changed_keys"].items():
        # Server list change → routing risk
        if "server" in key_changes:
            old_val, new_val = key_changes["server"]
            findings.append(
                UFRiskFinding(
                    risk=UpgradeRisk.HIGH,
                    category="ROUTING",
                    conf_file="outputs.conf",
                    stanza=stanza,
                    key="server",
                    description=(
                        f"Output [{stanza}] server list changed from "
                        f"{old_val!r} to {new_val!r}. "
                        f"Events may be routed to different indexers."
                    ),
                    recommendation=(
                        f"Confirm the new server list is correct, or set "
                        f"'server = {old_val}' in local/outputs.conf to preserve routing."
                    ),
                    old_value=old_val,
                    new_value=new_val,
                )
            )

        # SSL changes → connection risk
        for ssl_key in SSL_KEYS:
            if ssl_key in key_changes:
                old_val, new_val = key_changes[ssl_key]
                findings.append(
                    UFRiskFinding(
                        risk=UpgradeRisk.HIGH,
                        category="CONNECTION",
                        conf_file="outputs.conf",
                        stanza=stanza,
                        key=ssl_key,
                        description=(
                            f"SSL setting {ssl_key!r} in [{stanza}] changed from "
                            f"{old_val!r} to {new_val!r}. "
                            f"The forwarder may fail to connect to indexers."
                        ),
                        recommendation=(
                            f"Test the SSL configuration in a staging environment "
                            f"before deploying. Override {ssl_key!r} in local/ if needed."
                        ),
                        old_value=old_val,
                        new_value=new_val,
                    )
                )

    return findings


def _check_props_conf_indextime(
    old_stanzas: Dict[str, Dict[str, str]],
    new_stanzas: Dict[str, Dict[str, str]],
) -> List[UFRiskFinding]:
    """
    Detect index-time props changes that will alter event parsing on the UF.

    Only UF_INDEX_TIME_KEYS are checked; search-time props are irrelevant on a UF.
    """
    findings: List[UFRiskFinding] = []
    diff = _compare_stanza_dicts(old_stanzas, new_stanzas)

    for stanza, key_changes in diff["changed_keys"].items():
        for key, (old_val, new_val) in key_changes.items():
            if key.upper() in UF_INDEX_TIME_KEYS:
                findings.append(
                    UFRiskFinding(
                        risk=UpgradeRisk.CRITICAL,
                        category="INDEX_TIME_PARSING",
                        conf_file="props.conf",
                        stanza=stanza,
                        key=key,
                        description=(
                            f"Index-time key {key!r} in [{stanza}] changed from "
                            f"{old_val!r} to {new_val!r}. "
                            f"Event parsing will change at index time — "
                            f"existing data may become inconsistent with new data."
                        ),
                        recommendation=(
                            f"Pin the old value by adding '{key} = {old_val}' "
                            f"to local/props.conf [{stanza}], or test carefully "
                            f"before upgrading production forwarders."
                        ),
                        old_value=old_val,
                        new_value=new_val,
                    )
                )

    return findings


def _check_ssl_settings(
    old_stanzas: Dict[str, Dict[str, str]],
    new_stanzas: Dict[str, Dict[str, str]],
    conf_file: str,
) -> List[UFRiskFinding]:
    """
    Generic SSL settings checker for any conf file (inputs/outputs).

    Args:
        old_stanzas: Stanzas before upgrade.
        new_stanzas: Stanzas after upgrade.
        conf_file: Name of the conf file (for finding attribution).

    Returns:
        List of UFRiskFinding for SSL key changes.
    """
    findings: List[UFRiskFinding] = []
    diff = _compare_stanza_dicts(old_stanzas, new_stanzas)

    for stanza, key_changes in diff["changed_keys"].items():
        for key, (old_val, new_val) in key_changes.items():
            if key in SSL_KEYS:
                findings.append(
                    UFRiskFinding(
                        risk=UpgradeRisk.HIGH,
                        category="CONNECTION",
                        conf_file=conf_file,
                        stanza=stanza,
                        key=key,
                        description=(
                            f"SSL key {key!r} in [{stanza}] changed from "
                            f"{old_val!r} to {new_val!r}. "
                            f"This may break TLS connectivity."
                        ),
                        recommendation=(
                            f"Validate SSL configuration in staging. "
                            f"Override in local/{conf_file} if needed."
                        ),
                        old_value=old_val,
                        new_value=new_val,
                    )
                )

    return findings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def analyze_uf_upgrade(
    old_apps: List[AppBaseline],
    new_apps: List[AppBaseline],
    forwarder_group: str,
) -> UFUpgradeReport:
    """
    Perform a comprehensive UF-specific upgrade analysis.

    Compares old and new app baselines for a UF deployment group, focusing
    on conf files that affect data collection, forwarding, and connectivity.

    Args:
        old_apps: List of AppBaseline objects from the currently deployed apps.
        new_apps: List of AppBaseline objects from the upgraded app versions.
        forwarder_group: Name of the deployment group or host class being analysed.

    Returns:
        UFUpgradeReport with all findings and an overall risk assessment.
    """
    # Index new apps by app_id for pairing
    new_app_index: Dict[str, AppBaseline] = {a.app_id: a for a in new_apps}

    all_findings: List[UFRiskFinding] = []
    app_ids_analyzed: List[str] = []

    for old_app in old_apps:
        new_app = new_app_index.get(old_app.app_id)
        if new_app is None:
            # App removed in new version
            logger.debug("[UF] App %s has no counterpart in new_apps", old_app.app_id)
            continue

        app_ids_analyzed.append(old_app.app_id)

        old_inputs = _effective_stanzas(old_app, "inputs")
        new_inputs = _effective_stanzas(new_app, "inputs")
        old_outputs = _effective_stanzas(old_app, "outputs")
        new_outputs = _effective_stanzas(new_app, "outputs")
        old_props = _effective_stanzas(old_app, "props")
        new_props = _effective_stanzas(new_app, "props")

        all_findings.extend(_check_inputs_conf(old_inputs, new_inputs))
        all_findings.extend(_check_outputs_conf(old_outputs, new_outputs))
        all_findings.extend(_check_props_conf_indextime(old_props, new_props))
        # Also check SSL on inputs.conf
        all_findings.extend(_check_ssl_settings(old_inputs, new_inputs, "inputs.conf"))

    # Compute overall risk
    risk_order = {
        UpgradeRisk.CRITICAL: 0,
        UpgradeRisk.HIGH: 1,
        UpgradeRisk.MEDIUM: 2,
        UpgradeRisk.LOW: 3,
        UpgradeRisk.INFO: 4,
    }
    overall_risk = (
        min(all_findings, key=lambda f: risk_order[f.risk]).risk
        if all_findings
        else UpgradeRisk.INFO
    )

    data_loss_risk = any(f.category == "DATA_LOSS" for f in all_findings)
    routing_risk = any(f.category == "ROUTING" for f in all_findings)
    connection_risk = any(f.category == "CONNECTION" for f in all_findings)

    # Sort by severity
    all_findings.sort(key=lambda f: (risk_order[f.risk], f.conf_file, f.stanza))

    summary = {
        "total_findings": len(all_findings),
        "critical": sum(1 for f in all_findings if f.risk == UpgradeRisk.CRITICAL),
        "high": sum(1 for f in all_findings if f.risk == UpgradeRisk.HIGH),
        "data_loss_risk": data_loss_risk,
        "routing_risk": routing_risk,
        "connection_risk": connection_risk,
        "apps_analyzed": len(app_ids_analyzed),
    }

    logger.info(
        "[UF] %s: %d findings, overall_risk=%s",
        forwarder_group,
        len(all_findings),
        overall_risk.value,
    )

    return UFUpgradeReport(
        forwarder_group=forwarder_group,
        app_ids_analyzed=app_ids_analyzed,
        findings=all_findings,
        overall_risk=overall_risk,
        data_loss_risk=data_loss_risk,
        routing_risk=routing_risk,
        connection_risk=connection_risk,
        summary=summary,
    )


def check_indexer_compat(
    uf_version: str,
    indexer_version: str,
) -> CompatResult:
    """
    Check compatibility between a UF version and an indexer version.

    Uses the VERSION_COMPAT_MATRIX to identify known incompatibilities.

    Args:
        uf_version: Version string of the Universal Forwarder, e.g. "9.3.1".
        indexer_version: Version string of the indexer, e.g. "9.0.4".

    Returns:
        CompatResult with compatibility status and any warnings or blocking issues.
    """
    uf_tuple = _parse_version_tuple(uf_version)
    indexer_tuple = _parse_version_tuple(indexer_version)

    warnings: List[str] = []
    blocking_issues: List[str] = []

    for min_uf, min_indexer, note in VERSION_COMPAT_MATRIX:
        if uf_tuple >= min_uf and indexer_tuple < min_indexer:
            blocking_issues.append(
                f"UF {uf_version} requires indexer >= "
                f"{'.'.join(str(x) for x in min_indexer)}: {note}"
            )

    # Warn when UF is significantly newer than indexer (general guidance)
    if uf_tuple[0] > indexer_tuple[0]:
        warnings.append(
            f"UF major version ({uf_tuple[0]}) is ahead of indexer major version "
            f"({indexer_tuple[0]}). Test compatibility thoroughly."
        )
    elif uf_tuple > indexer_tuple and uf_tuple[0] == indexer_tuple[0]:
        warnings.append(
            f"UF {uf_version} is newer than indexer {indexer_version}. "
            f"Minor version ahead is generally supported but verify release notes."
        )

    is_compatible = len(blocking_issues) == 0

    return CompatResult(
        uf_version=uf_version,
        indexer_version=indexer_version,
        is_compatible=is_compatible,
        warnings=warnings,
        blocking_issues=blocking_issues,
    )
