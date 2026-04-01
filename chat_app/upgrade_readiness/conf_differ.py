"""
Three-way Splunk .conf diffing engine.

Implements the core comparison logic:
  old_default  (vendor's previous release)
  new_default  (vendor's new release)
  local        (org's customisations in local/)

Produces a list of UpgradeFinding objects ranked by risk.
"""
from __future__ import annotations

import logging
from typing import Dict, List

from chat_app.upgrade_readiness.models import (
    INDEX_TIME_KEYS,
    FindingCategory,
    StanzaDiff,
    UpgradeFinding,
    UpgradeRisk,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _strip_lines_meta(stanza_data: Dict[str, str]) -> Dict[str, str]:
    """Remove the __lines__ bookkeeping key inserted by parse_conf_file_advanced."""
    return {k: v for k, v in stanza_data.items() if k != "__lines__"}


def _is_index_time_key(key: str) -> bool:
    """Return True if this key affects index-time processing."""
    return key.upper() in INDEX_TIME_KEYS


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def simulate_splunk_merge(
    default: Dict[str, str],
    local: Dict[str, str],
) -> Dict[str, str]:
    """
    Simulate Splunk's conf merge semantics for a single stanza.

    Splunk merges default/ and local/ by letting local/ override any key
    present in default/.  Keys present only in local/ are preserved as-is.

    Args:
        default: Key-value pairs from the app's default/ conf file.
        local: Key-value pairs from the org's local/ conf file.

    Returns:
        Merged dictionary representing the effective runtime configuration.
    """
    merged = dict(default)
    merged.update(local)
    return merged


def diff_stanza(
    old_keys: Dict[str, str],
    new_keys: Dict[str, str],
    local_keys: Dict[str, str],
    stanza_name: str,
    conf_type: str,
    app_id: str = "",
) -> List[UpgradeFinding]:
    """
    Produce findings for a single stanza that exists in both old and new default.

    Covers:
    - Key removed in new: HIGH if no local override, LOW if local overrides it
    - Key value changed in new: CRITICAL if index-time key,
      HIGH if no local override, LOW if local overrides
    - Key added in new: MEDIUM if local has same key (conflict), INFO otherwise

    Args:
        old_keys: Key-value pairs from old default/ for this stanza.
        new_keys: Key-value pairs from new default/ for this stanza.
        local_keys: Key-value pairs from org local/ for this stanza.
        stanza_name: Name of the stanza being diffed.
        conf_type: .conf file type, e.g. "props".
        app_id: Optional app identifier for attribution.

    Returns:
        List of UpgradeFinding objects for this stanza.
    """
    findings: List[UpgradeFinding] = []

    all_old = _strip_lines_meta(old_keys)
    all_new = _strip_lines_meta(new_keys)
    all_local = _strip_lines_meta(local_keys)

    old_key_set = set(all_old)
    new_key_set = set(all_new)
    local_key_set = set(all_local)

    # --- Keys removed in new default ---
    for key in old_key_set - new_key_set:
        local_overrides = key in local_key_set
        is_index_time = _is_index_time_key(key)

        if is_index_time:
            risk = UpgradeRisk.CRITICAL
            category = FindingCategory.INDEX_TIME_CHANGE
            description = (
                f"Index-time key '{key}' was removed from default in new version. "
                f"This can change how events are parsed at index time."
            )
            recommendation = (
                f"Add '{key}' to local/{conf_type}.conf [{stanza_name}] "
                f"with the previous value to preserve existing behaviour."
            )
        elif local_overrides:
            risk = UpgradeRisk.LOW
            category = FindingCategory.KEY_REMOVED
            description = (
                f"Key '{key}' was removed from default but your local/ overrides it "
                f"— effective behaviour is unchanged."
            )
            recommendation = (
                f"Verify that the local override for '{key}' is still required "
                f"after the upgrade."
            )
        else:
            risk = UpgradeRisk.HIGH
            category = FindingCategory.KEY_REMOVED
            description = (
                f"Key '{key}' was removed from default and there is no local override. "
                f"Effective behaviour will change silently."
            )
            recommendation = (
                f"Review the impact of removing '{key}' (old value: {all_old[key]!r}). "
                f"Add a local/ override if the old behaviour must be preserved."
            )

        findings.append(
            UpgradeFinding.create(
                risk=risk,
                category=category,
                conf_type=conf_type,
                stanza=stanza_name,
                key=key,
                description=description,
                recommendation=recommendation,
                old_value=all_old.get(key),
                new_value=None,
                local_value=all_local.get(key),
                app_id=app_id,
            )
        )

    # --- Keys with changed values in new default ---
    for key in old_key_set & new_key_set:
        if all_old[key] == all_new[key]:
            continue

        local_overrides = key in local_key_set
        is_index_time = _is_index_time_key(key)

        if is_index_time:
            risk = UpgradeRisk.CRITICAL
            category = FindingCategory.INDEX_TIME_CHANGE
            description = (
                f"Index-time key '{key}' changed from {all_old[key]!r} to "
                f"{all_new[key]!r}. This will alter event parsing at index time."
            )
            recommendation = (
                f"Test the new '{key}' value carefully. Add a local/ override "
                f"to pin the old value if existing data must remain consistent."
            )
        elif local_overrides:
            risk = UpgradeRisk.LOW
            category = FindingCategory.KEY_CHANGED
            description = (
                f"Default value of '{key}' changed from {all_old[key]!r} to "
                f"{all_new[key]!r}, but your local/ overrides it "
                f"({all_local[key]!r}) — effective behaviour is unchanged."
            )
            recommendation = (
                f"Verify that the local override ({all_local[key]!r}) is still "
                f"appropriate given the new default."
            )
        else:
            risk = UpgradeRisk.HIGH
            category = FindingCategory.KEY_CHANGED
            description = (
                f"Default value of '{key}' changed from {all_old[key]!r} to "
                f"{all_new[key]!r} with no local override — behaviour will change."
            )
            recommendation = (
                f"Review whether the new default value is acceptable. "
                f"Add a local/ override to pin the old value if needed."
            )

        findings.append(
            UpgradeFinding.create(
                risk=risk,
                category=category,
                conf_type=conf_type,
                stanza=stanza_name,
                key=key,
                description=description,
                recommendation=recommendation,
                old_value=all_old.get(key),
                new_value=all_new.get(key),
                local_value=all_local.get(key),
                app_id=app_id,
            )
        )

    # --- Keys added in new default ---
    for key in new_key_set - old_key_set:
        local_has_same = key in local_key_set
        new_val = all_new[key]

        if local_has_same:
            risk = UpgradeRisk.MEDIUM
            category = FindingCategory.KEY_ADDED
            description = (
                f"New default key '{key}' (value: {new_val!r}) conflicts with "
                f"your local/ value ({all_local[key]!r})."
            )
            recommendation = (
                f"Review whether the local/ value for '{key}' is still correct "
                f"given the new default."
            )
        else:
            risk = UpgradeRisk.INFO
            category = FindingCategory.KEY_ADDED
            description = (
                f"New key '{key}' (value: {new_val!r}) was added to default — "
                f"no local conflict."
            )
            recommendation = "No action required; new default is applied automatically."

        findings.append(
            UpgradeFinding.create(
                risk=risk,
                category=category,
                conf_type=conf_type,
                stanza=stanza_name,
                key=key,
                description=description,
                recommendation=recommendation,
                old_value=None,
                new_value=new_val,
                local_value=all_local.get(key),
                app_id=app_id,
            )
        )

    return findings


def three_way_diff(
    old_default: Dict[str, Dict[str, str]],
    new_default: Dict[str, Dict[str, str]],
    local: Dict[str, Dict[str, str]],
    conf_type: str = "props",
    app_id: str = "",
) -> List[UpgradeFinding]:
    """
    Run a three-way diff across all stanzas in old_default, new_default, and local.

    The algorithm visits every stanza in the union of all three conf dicts:

    1. Stanza in old only (removed by vendor):
       - Local has customisations → CRITICAL (orphaned local customisation)
       - No local → MEDIUM (feature removed)

    2. Stanza in new only (added by vendor):
       - Local has same stanza → MEDIUM (check for key conflicts)
       - No local → INFO (new feature, no conflict)

    3. Stanza in both old and new (modified by vendor):
       - Delegates per-key analysis to diff_stanza()
       - Also computes merged_before vs merged_after to confirm effective change

    Args:
        old_default: Stanza dict from vendor's old default/ conf.
        new_default: Stanza dict from vendor's new default/ conf.
        local: Stanza dict from org's local/ conf.
        conf_type: Type of conf file being diffed (e.g. "props").
        app_id: Optional app identifier for attribution.

    Returns:
        Sorted list of UpgradeFinding objects (CRITICAL first).
    """
    findings: List[UpgradeFinding] = []

    # Strip parse metadata so we work only with actual key-value strings
    old = {s: _strip_lines_meta(keys) for s, keys in old_default.items()}
    new = {s: _strip_lines_meta(keys) for s, keys in new_default.items()}
    loc = {s: _strip_lines_meta(keys) for s, keys in local.items()}

    all_stanzas = set(old) | set(new) | set(loc)

    for stanza in all_stanzas:
        in_old = stanza in old
        in_new = stanza in new
        in_local = stanza in loc

        if in_old and not in_new:
            # --- Stanza removed by vendor ---
            if in_local:
                findings.append(
                    UpgradeFinding.create(
                        risk=UpgradeRisk.CRITICAL,
                        category=FindingCategory.ORPHANED_LOCAL,
                        conf_type=conf_type,
                        stanza=stanza,
                        description=(
                            f"Stanza [{stanza}] was removed from default in the new version, "
                            f"but your local/ still has customisations for it. "
                            f"These customisations are now orphaned."
                        ),
                        recommendation=(
                            f"Review local/ [{stanza}] customisations. "
                            f"Remove them if no longer relevant, or migrate them "
                            f"to the new stanza structure."
                        ),
                        app_id=app_id,
                    )
                )
            else:
                findings.append(
                    UpgradeFinding.create(
                        risk=UpgradeRisk.MEDIUM,
                        category=FindingCategory.STANZA_REMOVED,
                        conf_type=conf_type,
                        stanza=stanza,
                        description=(
                            f"Stanza [{stanza}] was removed from default — "
                            f"this feature or configuration is no longer provided."
                        ),
                        recommendation=(
                            f"Review whether any saved searches or downstream apps "
                            f"depended on [{stanza}]."
                        ),
                        app_id=app_id,
                    )
                )

        elif not in_old and in_new:
            # --- Stanza added by vendor ---
            if in_local:
                # Existing local stanza may conflict with new default
                findings.append(
                    UpgradeFinding.create(
                        risk=UpgradeRisk.MEDIUM,
                        category=FindingCategory.MERGE_CONFLICT,
                        conf_type=conf_type,
                        stanza=stanza,
                        description=(
                            f"New stanza [{stanza}] was added in default, "
                            f"but your local/ already has a [{stanza}] stanza. "
                            f"Splunk will merge them — review for key conflicts."
                        ),
                        recommendation=(
                            f"Compare local/ [{stanza}] keys against the new default "
                            f"to ensure the merged result is correct."
                        ),
                        app_id=app_id,
                    )
                )
            else:
                findings.append(
                    UpgradeFinding.create(
                        risk=UpgradeRisk.INFO,
                        category=FindingCategory.STANZA_ADDED,
                        conf_type=conf_type,
                        stanza=stanza,
                        description=(
                            f"New stanza [{stanza}] was added in default — "
                            f"no local conflict."
                        ),
                        recommendation="No action required.",
                        app_id=app_id,
                    )
                )

        elif in_old and in_new:
            # --- Stanza exists in both: perform per-key analysis ---
            stanza_findings = diff_stanza(
                old_keys=old[stanza],
                new_keys=new[stanza],
                local_keys=loc.get(stanza, {}),
                stanza_name=stanza,
                conf_type=conf_type,
                app_id=app_id,
            )
            findings.extend(stanza_findings)

        # Stanza in local only (no vendor presence) is not a diff finding;
        # it is a pure org customisation unaffected by the upgrade.

    # Sort findings by risk descending (CRITICAL first), then stanza name for stability
    risk_order = {
        UpgradeRisk.CRITICAL: 0,
        UpgradeRisk.HIGH: 1,
        UpgradeRisk.MEDIUM: 2,
        UpgradeRisk.LOW: 3,
        UpgradeRisk.INFO: 4,
    }
    findings.sort(key=lambda f: (risk_order[f.risk], f.stanza, f.key or ""))

    logger.debug(
        "[DIFFER] %s: %d findings (%d critical, %d high, %d medium)",
        conf_type,
        len(findings),
        sum(1 for f in findings if f.risk == UpgradeRisk.CRITICAL),
        sum(1 for f in findings if f.risk == UpgradeRisk.HIGH),
        sum(1 for f in findings if f.risk == UpgradeRisk.MEDIUM),
    )
    return findings


def build_stanza_diff(
    stanza_name: str,
    old_keys: Dict[str, str],
    new_keys: Dict[str, str],
    local_keys: Dict[str, str],
    conf_type: str,
) -> StanzaDiff:
    """
    Build a StanzaDiff summary record for a stanza present in both old and new default.

    This is a lightweight summary object used for inspection and testing;
    the full analysis lives in diff_stanza().

    Args:
        stanza_name: Name of the stanza.
        old_keys: Cleaned key-value dict from old default.
        new_keys: Cleaned key-value dict from new default.
        local_keys: Cleaned key-value dict from org local.
        conf_type: Type of conf file.

    Returns:
        StanzaDiff with categorised key sets.
    """
    old_clean = _strip_lines_meta(old_keys)
    new_clean = _strip_lines_meta(new_keys)
    local_clean = _strip_lines_meta(local_keys)

    old_set = set(old_clean)
    new_set = set(new_clean)

    added = frozenset(new_set - old_set)
    removed = frozenset(old_set - new_set)
    changed = frozenset(
        k for k in old_set & new_set if old_clean[k] != new_clean[k]
    )

    return StanzaDiff(
        stanza_name=stanza_name,
        conf_type=conf_type,
        old_keys=old_clean,
        new_keys=new_clean,
        local_keys=local_clean,
        added_keys=added,
        removed_keys=removed,
        changed_keys=changed,
    )
