"""
CIM (Common Information Model) compliance checker for the Splunk Upgrade
Readiness Testing System.

Determines which CIM data models an app feeds based on its eventtypes.conf
and tags.conf, then verifies that props.conf/transforms.conf provide the
required fields for each model.  Also detects CIM compliance regressions
introduced by an upgrade.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Set

from chat_app.upgrade_readiness.models import AppBaseline, UpgradeRisk

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Embedded CIM data model definitions
# Sourced from Splunk_SA_CIM documentation and the CIM add-on spec.
# ---------------------------------------------------------------------------

CIM_MODELS: Dict[str, Dict] = {
    "Authentication": {
        "constraints": "tag=authentication",
        "required_fields": ["action", "app", "dest", "src", "user"],
        "optional_fields": [
            "authentication_method",
            "duration",
            "reason",
            "signature",
        ],
        "related_tags": {"authentication": ["authentication"]},
    },
    "Network_Traffic": {
        "constraints": "tag=network tag=communicate",
        "required_fields": [
            "action",
            "bytes_in",
            "bytes_out",
            "dest",
            "dest_port",
            "src",
            "transport",
        ],
        "optional_fields": ["bytes", "direction", "dvc", "protocol", "src_port"],
        "related_tags": {"network_traffic": ["network", "communicate"]},
    },
    "Endpoint_Processes": {
        "constraints": "tag=process tag=report",
        "required_fields": ["dest", "process", "process_id", "user"],
        "optional_fields": [
            "action",
            "parent_process",
            "parent_process_id",
            "process_path",
        ],
        "related_tags": {"endpoint_processes": ["process", "report"]},
    },
    "Malware": {
        "constraints": "tag=malware tag=attack",
        "required_fields": ["action", "dest", "file_name", "signature"],
        "optional_fields": ["category", "file_path", "severity", "user", "vendor_product"],
        "related_tags": {"malware": ["malware", "attack"]},
    },
    "Change": {
        "constraints": "tag=change",
        "required_fields": ["action", "object", "object_category", "result", "status"],
        "optional_fields": ["command", "dvc", "src", "user"],
        "related_tags": {"change": ["change"]},
    },
    "Web": {
        "constraints": "tag=web",
        "required_fields": ["dest", "http_method", "src", "status", "url"],
        "optional_fields": [
            "bytes_in",
            "bytes_out",
            "http_content_type",
            "http_user_agent",
            "uri_path",
            "user",
        ],
        "related_tags": {"web": ["web"]},
    },
    "Intrusion_Detection": {
        "constraints": "tag=ids tag=attack",
        "required_fields": [
            "action",
            "category",
            "dest",
            "severity",
            "signature",
            "src",
        ],
        "optional_fields": ["dvc", "ids_type", "transport", "user", "vendor_product"],
        "related_tags": {"intrusion_detection": ["ids", "attack"]},
    },
    "Vulnerability": {
        "constraints": "tag=vulnerability",
        "required_fields": ["category", "dest", "severity", "signature", "url"],
        "optional_fields": ["cvss", "mskb", "os", "src", "user"],
        "related_tags": {"vulnerability": ["vulnerability"]},
    },
    "Email": {
        "constraints": "tag=email",
        "required_fields": [
            "action",
            "dest",
            "message_id",
            "recipient",
            "sender",
            "size",
            "src",
            "subject",
        ],
        "optional_fields": ["file_name", "protocol", "relay"],
        "related_tags": {"email": ["email"]},
    },
    "DNS": {
        "constraints": "tag=network tag=dns",
        "required_fields": ["answer", "message_type", "name", "query", "query_type", "src"],
        "optional_fields": ["dest", "duration", "record_type"],
        "related_tags": {"dns": ["network", "dns"]},
    },
    "Endpoint_Filesystem": {
        "constraints": "tag=endpoint tag=filesystem",
        "required_fields": ["action", "dest", "file_name", "file_path", "user"],
        "optional_fields": ["file_acl", "file_hash", "file_size", "process"],
        "related_tags": {"endpoint_filesystem": ["endpoint", "filesystem"]},
    },
    "Endpoint_Registry": {
        "constraints": "tag=endpoint tag=registry",
        "required_fields": [
            "action",
            "dest",
            "registry_hive",
            "registry_key_name",
            "registry_path",
            "user",
        ],
        "optional_fields": ["registry_value_data", "registry_value_name", "registry_value_type"],
        "related_tags": {"endpoint_registry": ["endpoint", "registry"]},
    },
    "Certificate": {
        "constraints": "tag=certificate",
        "required_fields": [
            "dest",
            "ssl_end_time",
            "ssl_issuer",
            "ssl_serial",
            "ssl_start_time",
            "ssl_subject",
        ],
        "optional_fields": ["ssl_issuer_common_name", "ssl_subject_common_name", "ssl_version"],
        "related_tags": {"certificate": ["certificate"]},
    },
    "Ticket_Management": {
        "constraints": "tag=ticketing",
        "required_fields": ["action", "dest", "id", "priority", "severity", "status"],
        "optional_fields": ["category", "description", "src_user", "user"],
        "related_tags": {"ticket_management": ["ticketing"]},
    },
    "Alerts": {
        "constraints": "tag=alert",
        "required_fields": ["app", "body", "dest", "id", "severity", "src", "type"],
        "optional_fields": ["description", "signature", "user"],
        "related_tags": {"alerts": ["alert"]},
    },
}

# Tag combinations that identify a CIM model.
# Key = frozenset of tags; value = model name.
_TAG_TO_MODEL: Dict[FrozenSet[str], str] = {
    frozenset(["authentication"]): "Authentication",
    frozenset(["network", "communicate"]): "Network_Traffic",
    frozenset(["process", "report"]): "Endpoint_Processes",
    frozenset(["malware", "attack"]): "Malware",
    frozenset(["change"]): "Change",
    frozenset(["web"]): "Web",
    frozenset(["ids", "attack"]): "Intrusion_Detection",
    frozenset(["vulnerability"]): "Vulnerability",
    frozenset(["email"]): "Email",
    frozenset(["network", "dns"]): "DNS",
    frozenset(["endpoint", "filesystem"]): "Endpoint_Filesystem",
    frozenset(["endpoint", "registry"]): "Endpoint_Registry",
    frozenset(["certificate"]): "Certificate",
    frozenset(["ticketing"]): "Ticket_Management",
    frozenset(["alert"]): "Alerts",
}


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass
class CIMValidationResult:
    """
    Result of checking one app against one CIM data model.

    Attributes:
        model_name: CIM model name, e.g. "Authentication".
        eventtype_name: The eventtype that triggers this model, e.g. "authentication".
        sourcetypes: Source types inferred from the eventtype search string.
        provided_fields: Fields found in props.conf/transforms.conf for these sourcetypes.
        required_fields: Fields required by the CIM model.
        missing_fields: required_fields that are absent from provided_fields.
        is_compliant: True if no required fields are missing.
        compliance_score: Fraction of required fields present (0.0–1.0).
        app_id: App that was checked.
    """

    model_name: str
    eventtype_name: str
    sourcetypes: List[str]
    provided_fields: List[str]
    required_fields: List[str]
    missing_fields: List[str]
    is_compliant: bool
    compliance_score: float
    app_id: str = ""


@dataclass
class CIMRegressionFinding:
    """
    A CIM compliance regression introduced by an upgrade.

    Attributes:
        model_name: CIM model affected.
        eventtype_name: Eventtype that triggers this model.
        field: The field that regressed.
        was_provided: Whether the field was present before upgrade.
        now_provided: Whether the field is present after upgrade.
        risk: Risk level of this regression.
        description: Human-readable description.
        recommendation: Suggested remediation step.
    """

    model_name: str
    eventtype_name: str
    field: str
    was_provided: bool
    now_provided: bool
    risk: UpgradeRisk
    description: str
    recommendation: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_sourcetypes_from_search(search_string: str) -> List[str]:
    """
    Parse sourcetype= references from an eventtype search string.

    Args:
        search_string: The raw search string from eventtypes.conf.

    Returns:
        List of sourcetype names found (may be empty).
    """
    # Match sourcetype="value" or sourcetype=value
    pattern = r'sourcetype\s*=\s*"?([^"\s\)]+)"?'
    return re.findall(pattern, search_string, re.IGNORECASE)


def _get_eventtype_tags(
    tags_conf: Dict[str, Dict[str, str]],
    eventtype_name: str,
) -> Set[str]:
    """
    Find the tags assigned to an eventtype in tags.conf.

    Tags.conf stanzas look like: [eventtype=authentication]
    with keys like:  authentication = enabled

    Args:
        tags_conf: Parsed tags.conf stanzas (stanza_name → {key → value}).
        eventtype_name: Eventtype to look up, e.g. "authentication".

    Returns:
        Set of enabled tag names for this eventtype.
    """
    stanza_key = f"eventtype={eventtype_name}"
    stanza = tags_conf.get(stanza_key, {})
    return {tag for tag, value in stanza.items() if value.lower() == "enabled"}


def _resolve_cim_models_for_tags(tags: Set[str]) -> List[str]:
    """
    Map a set of tags to CIM model names.

    Args:
        tags: Set of tag names, e.g. {"network", "communicate"}.

    Returns:
        List of matching CIM model names.
    """
    matched_models: List[str] = []
    for tag_combo, model_name in _TAG_TO_MODEL.items():
        if tag_combo.issubset(tags):
            matched_models.append(model_name)
    return matched_models


def _collect_provided_fields(
    props_conf: Dict[str, Dict[str, str]],
    transforms_conf: Dict[str, Dict[str, str]],
    sourcetypes: List[str],
) -> Set[str]:
    """
    Enumerate fields provided for a set of sourcetypes via props.conf.

    Looks at FIELDALIAS, EVAL, EXTRACT, and REPORT keys.

    FIELDALIAS-x = old_name AS new_name  → provides new_name
    EVAL-field = ...                      → provides field
    EXTRACT-name = REGEX with named groups → provides group names
    REPORT-name = transform_stanza        → lookup fields from transforms.conf

    Args:
        props_conf: Parsed props.conf stanzas.
        transforms_conf: Parsed transforms.conf stanzas.
        sourcetypes: List of sourcetype names to inspect.

    Returns:
        Set of field names declared for these sourcetypes.
    """
    provided: Set[str] = set()

    # Stanza names in props.conf can be the sourcetype name directly,
    # or prefixed with "source::" or "host::".
    relevant_stanzas: List[Dict[str, str]] = []
    for sourcetype in sourcetypes:
        for stanza_name, keys in props_conf.items():
            if stanza_name == sourcetype or stanza_name.endswith(f":{sourcetype}"):
                relevant_stanzas.append(keys)

    for stanza_keys in relevant_stanzas:
        for key, value in stanza_keys.items():
            if key == "__lines__":
                continue

            upper_key = key.upper()

            # FIELDALIAS-* = src_field AS dest_field [, ...]
            if upper_key.startswith("FIELDALIAS-") or upper_key.startswith("FIELDALIAS_"):
                # Parse aliases: "old AS new" or "old AS new, old2 AS new2"
                for alias_pair in re.split(r",\s*", value):
                    alias_match = re.search(r"\bAS\s+(\S+)", alias_pair, re.IGNORECASE)
                    if alias_match:
                        provided.add(alias_match.group(1))
                # The source fields are also available
                for alias_pair in re.split(r",\s*", value):
                    src_match = re.match(r"(\S+)\s+AS", alias_pair, re.IGNORECASE)
                    if src_match:
                        provided.add(src_match.group(1))

            # EVAL-field = expression → provides field
            elif upper_key.startswith("EVAL-") or upper_key.startswith("EVAL_"):
                field_name = key[key.index("-") + 1:] if "-" in key else key[5:]
                provided.add(field_name)

            # EXTRACT-name = REGEX with named groups  (e.g. (?P<field>...))
            elif upper_key.startswith("EXTRACT-") or upper_key.startswith("EXTRACT_"):
                named_groups = re.findall(r"\(\?P<([^>]+)>", value)
                provided.update(named_groups)

            # REPORT-name = transform_stanza_name(s)
            elif upper_key.startswith("REPORT-") or upper_key.startswith("REPORT_"):
                for transform_name in re.split(r",\s*", value):
                    transform_name = transform_name.strip()
                    transform_stanza = transforms_conf.get(transform_name, {})
                    # Extract FORMAT field names from FORMAT = field1::$1 field2::$2
                    fmt = transform_stanza.get("FORMAT", "")
                    for field_name in re.findall(r"(\w+)::", fmt):
                        provided.add(field_name)
                    # FIELDS key lists extracted field names
                    fields_val = transform_stanza.get("FIELDS", "")
                    for field_name in re.split(r",\s*", fields_val):
                        if field_name:
                            provided.add(field_name.strip())

    return provided


def _build_cim_result(
    model_name: str,
    eventtype_name: str,
    sourcetypes: List[str],
    provided_fields: Set[str],
    app_id: str,
) -> CIMValidationResult:
    """
    Construct a CIMValidationResult for a model/eventtype/sourcetype tuple.

    Args:
        model_name: Name of the CIM model being checked.
        eventtype_name: Eventtype that feeds this model.
        sourcetypes: Sourcetypes involved.
        provided_fields: Fields confirmed to be present.
        app_id: App being checked.

    Returns:
        Fully populated CIMValidationResult.
    """
    model_def = CIM_MODELS.get(model_name, {})
    required = model_def.get("required_fields", [])
    # Normalise case for comparison
    provided_lower = {f.lower() for f in provided_fields}
    missing = [f for f in required if f.lower() not in provided_lower]

    total_required = len(required)
    score = (total_required - len(missing)) / total_required if total_required else 1.0

    return CIMValidationResult(
        model_name=model_name,
        eventtype_name=eventtype_name,
        sourcetypes=sourcetypes,
        provided_fields=sorted(provided_fields),
        required_fields=required,
        missing_fields=missing,
        is_compliant=len(missing) == 0,
        compliance_score=round(score, 4),
        app_id=app_id,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_cim_compliance(app_baseline: AppBaseline) -> List[CIMValidationResult]:
    """
    Check which CIM data models this app feeds and whether required fields exist.

    Algorithm:
    1. Parse eventtypes.conf → build eventtype_name → sourcetypes mapping.
    2. Parse tags.conf → find which eventtypes have CIM-relevant tags.
    3. Map tag combinations → CIM model names via _TAG_TO_MODEL.
    4. Parse props.conf + transforms.conf → collect provided fields per sourcetype.
    5. For each (eventtype, CIM model): compare provided vs required fields.

    Args:
        app_baseline: Parsed AppBaseline for the app under test.

    Returns:
        List of CIMValidationResult, one per (eventtype, CIM model) pair found.
        Returns an empty list if the app has no CIM-tagged eventtypes.
    """
    # Merge default and local conf data; local overrides default at the key level.
    def _merged(conf_name: str) -> Dict[str, Dict[str, str]]:
        default = app_baseline.get_default_stanzas(conf_name)
        local = app_baseline.get_local_stanzas(conf_name)
        merged: Dict[str, Dict[str, str]] = {}
        for stanza, keys in default.items():
            merged[stanza] = dict(keys)
        for stanza, keys in local.items():
            if stanza in merged:
                merged[stanza].update(keys)
            else:
                merged[stanza] = dict(keys)
        return merged

    eventtypes_conf = _merged("eventtypes")
    tags_conf = _merged("tags")
    props_conf = _merged("props")
    transforms_conf = _merged("transforms")

    results: List[CIMValidationResult] = []

    for eventtype_name, eventtype_data in eventtypes_conf.items():
        search_string = eventtype_data.get("search", "")
        sourcetypes = _extract_sourcetypes_from_search(search_string)

        # Find tags for this eventtype from tags.conf
        active_tags = _get_eventtype_tags(tags_conf, eventtype_name)
        if not active_tags:
            continue

        # Match tags to CIM models
        matched_models = _resolve_cim_models_for_tags(active_tags)
        if not matched_models:
            continue

        # Collect fields available for the sourcetypes in this eventtype
        provided_fields = _collect_provided_fields(
            props_conf, transforms_conf, sourcetypes
        )

        for model_name in matched_models:
            result = _build_cim_result(
                model_name=model_name,
                eventtype_name=eventtype_name,
                sourcetypes=sourcetypes,
                provided_fields=provided_fields,
                app_id=app_baseline.app_id,
            )
            results.append(result)

    logger.debug(
        "[CIM] %s: %d model/eventtype pairs checked, %d compliant",
        app_baseline.app_id,
        len(results),
        sum(1 for r in results if r.is_compliant),
    )
    return results


def check_upgrade_cim_impact(
    old_baseline: AppBaseline,
    new_confs: Dict[str, Dict[str, Dict[str, str]]],
) -> List[CIMRegressionFinding]:
    """
    Compare CIM compliance before and after an upgrade; return regressions.

    The old_baseline represents the currently installed app (default + local).
    new_confs represents the default/ conf files from the new version only —
    the org's local/ customisations are carried over from old_baseline.

    Args:
        old_baseline: Current app state (default + local merged).
        new_confs: Dict of conf_name → stanzas from the new app's default/ only.
                   Keys match AppBaseline.default_confs convention (e.g. "props").

    Returns:
        List of CIMRegressionFinding for fields that were present before
        but are absent after the upgrade.
    """
    # Build a synthetic "new" AppBaseline using the new default confs
    # and the existing local confs unchanged.
    from chat_app.upgrade_readiness.models import AppBaseline as _AppBaseline  # noqa: PLC0415

    new_baseline = _AppBaseline(
        app_id=old_baseline.app_id,
        version=old_baseline.version,
        default_confs=new_confs,
        local_confs=old_baseline.local_confs,
        app_dir=old_baseline.app_dir,
    )

    before_results = check_cim_compliance(old_baseline)
    after_results = check_cim_compliance(new_baseline)

    # Index after results by (model_name, eventtype_name) for fast lookup
    after_index: Dict[tuple, CIMValidationResult] = {
        (r.model_name, r.eventtype_name): r for r in after_results
    }

    regressions: List[CIMRegressionFinding] = []

    for before in before_results:
        key = (before.model_name, before.eventtype_name)
        after = after_index.get(key)

        if after is None:
            # Entire model/eventtype mapping disappeared — flag each required field
            for required_field in before.required_fields:
                if required_field.lower() in {f.lower() for f in before.provided_fields}:
                    regressions.append(
                        CIMRegressionFinding(
                            model_name=before.model_name,
                            eventtype_name=before.eventtype_name,
                            field=required_field,
                            was_provided=True,
                            now_provided=False,
                            risk=UpgradeRisk.HIGH,
                            description=(
                                f"CIM model {before.model_name!r} via eventtype "
                                f"{before.eventtype_name!r} lost field "
                                f"{required_field!r} after upgrade."
                            ),
                            recommendation=(
                                f"Add a FIELDALIAS or EXTRACT for {required_field!r} "
                                f"in the new version of this app."
                            ),
                        )
                    )
            continue

        # Compare field-by-field — only flag regressions (was present, now missing)
        before_provided_lower = {f.lower() for f in before.provided_fields}
        after_provided_lower = {f.lower() for f in after.provided_fields}

        for required_field in before.required_fields:
            was_present = required_field.lower() in before_provided_lower
            now_present = required_field.lower() in after_provided_lower

            if was_present and not now_present:
                # Determine risk: required fields that regress are HIGH
                risk = UpgradeRisk.HIGH
                regressions.append(
                    CIMRegressionFinding(
                        model_name=before.model_name,
                        eventtype_name=before.eventtype_name,
                        field=required_field,
                        was_provided=True,
                        now_provided=False,
                        risk=risk,
                        description=(
                            f"CIM model {before.model_name!r} required field "
                            f"{required_field!r} was present before the upgrade "
                            f"but is missing after. This will break CIM compliance."
                        ),
                        recommendation=(
                            f"Restore the extraction for {required_field!r}. "
                            f"Check if a FIELDALIAS, EXTRACT, or REPORT stanza "
                            f"was removed in the new default."
                        ),
                    )
                )

    logger.info(
        "[CIM] Upgrade impact for %s: %d regressions found",
        old_baseline.app_id,
        len(regressions),
    )
    return regressions


def get_cim_summary(results: List[CIMValidationResult]) -> Dict[str, object]:
    """
    Return a compact summary dict suitable for API responses or dashboard display.

    Args:
        results: List of CIMValidationResult objects.

    Returns:
        Dict with total, compliant, non_compliant, compliance_rate, models_checked.
    """
    total = len(results)
    compliant = sum(1 for r in results if r.is_compliant)
    return {
        "total_checks": total,
        "compliant": compliant,
        "non_compliant": total - compliant,
        "compliance_rate": round(compliant / total, 4) if total else 1.0,
        "models_checked": sorted({r.model_name for r in results}),
        "missing_fields_by_model": {
            r.model_name: r.missing_fields
            for r in results
            if r.missing_fields
        },
    }
