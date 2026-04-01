"""
Baseline builder for the Splunk Upgrade Readiness Testing System.

Scans app directories on disk to build AppBaseline and ClusterInventory
objects.  Uses parse_conf_file_advanced() from shared/conf_parser.py for
conf parsing, and optionally enriches with Splunkbase catalog data.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Dict, List, Optional

from chat_app.upgrade_readiness.models import (
    AppBaseline,
    AppVersion,
    ClusterInventory,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Conf files we care about when building a baseline
# ---------------------------------------------------------------------------

# Scan ALL .conf files — no artificial limits
# Any file ending in .conf is a Splunk configuration file and should be analyzed
TRACKED_CONF_FILES = None  # None = scan all *.conf files


# ---------------------------------------------------------------------------
# Lazy import helpers (avoid hard dep on shared/ at module level)
# ---------------------------------------------------------------------------


def _parse_conf(content: str, filename: str = "unknown") -> Dict[str, Dict]:
    """
    Parse .conf file content using shared/conf_parser.parse_conf_file_advanced().

    Falls back to an empty dict on any parse error rather than propagating
    exceptions into the baseline builder.
    """
    try:
        from shared.conf_parser import parse_conf_file_advanced  # noqa: PLC0415

        return parse_conf_file_advanced(content, filename)
    except ImportError:
        # Minimal fallback parser for environments where shared/ is not on sys.path
        return _fallback_parse_conf(content)
    except Exception as exc:
        logger.warning("[BASELINE] Failed to parse %s: %s", filename, exc)
        return {}


def _fallback_parse_conf(content: str) -> Dict[str, Dict]:
    """
    Minimal .conf parser used when shared/conf_parser is unavailable.

    Handles comments, stanza headers, and simple key=value pairs.
    Does NOT support multi-line values.
    """
    import re

    result: Dict[str, Dict] = {}
    current_stanza: Optional[str] = None

    for line in content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        stanza_match = re.match(r"^\[([^\]]+)\]$", stripped)
        if stanza_match:
            current_stanza = stanza_match.group(1)
            result.setdefault(current_stanza, {"__lines__": {}})
            continue
        if current_stanza:
            kv_match = re.match(r"^([a-zA-Z_][\w-]*)\s*=\s*(.*)$", stripped)
            if kv_match:
                key, value = kv_match.group(1), kv_match.group(2)
                result[current_stanza][key] = value

    return result


# ---------------------------------------------------------------------------
# Core public functions
# ---------------------------------------------------------------------------


def extract_app_version(app_dir: str) -> AppVersion:
    """
    Extract version metadata from an app's default/app.conf (or app.conf).

    Reads the [launcher] and [ui] stanzas to find version, author, and label.
    Falls back to [id] and [package] stanzas used in older TAs.

    Args:
        app_dir: Path to the root of the Splunk app directory.

    Returns:
        AppVersion with as much information as could be found.
        Falls back to version "0.0.0" if app.conf is missing or unparseable.
    """
    app_path = Path(app_dir)
    app_id = app_path.name

    # Try default/app.conf first, then top-level app.conf
    candidates = [
        app_path / "default" / "app.conf",
        app_path / "app.conf",
    ]

    conf_data: Dict[str, Dict] = {}
    for candidate in candidates:
        if candidate.is_file():
            try:
                content = candidate.read_text(encoding="utf-8", errors="replace")
                conf_data = _parse_conf(content, "app.conf")
                break
            except OSError as exc:
                logger.warning(
                    "[BASELINE] Cannot read %s: %s", candidate, exc
                )

    if not conf_data:
        logger.debug("[BASELINE] No app.conf found in %s", app_dir)
        return AppVersion(app_id=app_id, version="0.0.0")

    # Gather fields from multiple stanzas
    launcher = conf_data.get("launcher", {})
    ui = conf_data.get("ui", {})
    package = conf_data.get("package", {})
    id_stanza = conf_data.get("id", {})

    version = (
        launcher.get("version")
        or package.get("version")
        or id_stanza.get("version")
        or "0.0.0"
    )
    author = launcher.get("author") or id_stanza.get("author") or ""
    label = ui.get("label") or launcher.get("label") or app_id
    description = launcher.get("description") or ""
    build = launcher.get("build") or ""

    return AppVersion(
        app_id=app_id,
        version=version,
        build=build,
        author=author,
        label=label,
        description=description,
    )


def scan_app_directory(app_dir: str) -> AppBaseline:
    """
    Scan a Splunk app directory and parse all tracked .conf files.

    Walks default/ and local/ sub-directories.  Only files listed in
    TRACKED_CONF_FILES are parsed; others are silently skipped.

    Args:
        app_dir: Path to the root of the Splunk app directory.

    Returns:
        AppBaseline with parsed default_confs and local_confs.
        Errors during individual file reads are logged and skipped.
    """
    app_path = Path(app_dir)
    app_id = app_path.name
    version = extract_app_version(app_dir)

    default_confs: Dict[str, Dict[str, Dict]] = {}
    local_confs: Dict[str, Dict[str, Dict]] = {}

    for subdir_name, target_dict in (
        ("default", default_confs),
        ("local", local_confs),
    ):
        subdir = app_path / subdir_name
        if not subdir.is_dir():
            continue

        for conf_file in subdir.iterdir():
            if not conf_file.is_file():
                continue
            # Scan ALL .conf files — no artificial limits
            if not conf_file.name.endswith(".conf"):
                continue

            try:
                content = conf_file.read_text(encoding="utf-8", errors="replace")
                parsed = _parse_conf(content, conf_file.name)
            except OSError as exc:
                logger.warning(
                    "[BASELINE] Failed to read %s: %s", conf_file, exc
                )
                continue

            # Key by the conf stem, e.g. "props" for props.conf
            conf_key = conf_file.stem
            target_dict[conf_key] = parsed

    baseline = AppBaseline(
        app_id=app_id,
        version=version,
        default_confs=default_confs,
        local_confs=local_confs,
        app_dir=str(app_dir),
    )

    logger.debug(
        "[BASELINE] %s v%s — %d default confs, %d local confs",
        app_id,
        version.version,
        len(default_confs),
        len(local_confs),
    )
    return baseline


def scan_cluster_directory(cluster_dir: str) -> ClusterInventory:
    """
    Scan a cluster's app directory and build baselines for each app.

    Expects cluster_dir to contain one sub-directory per app:
      cluster_dir/
        Splunk_TA_windows/
        Splunk_SA_CIM/
        ...

    Directories that do not look like Splunk apps (no default/ or app.conf)
    are silently skipped.

    Args:
        cluster_dir: Path to the directory containing all apps for a cluster.

    Returns:
        ClusterInventory with one AppBaseline per discovered app.
    """
    cluster_path = Path(cluster_dir)
    cluster_name = cluster_path.name

    inventory = ClusterInventory(cluster_name=cluster_name)

    if not cluster_path.is_dir():
        logger.warning("[BASELINE] Cluster dir does not exist: %s", cluster_dir)
        inventory.errors.append(f"Directory not found: {cluster_dir}")
        return inventory

    for entry in sorted(cluster_path.iterdir()):
        if not entry.is_dir():
            continue

        # Quick sanity check: must look like a Splunk app
        has_default = (entry / "default").is_dir()
        has_app_conf = (entry / "app.conf").is_file() or (
            entry / "default" / "app.conf"
        ).is_file()

        if not (has_default or has_app_conf):
            logger.debug("[BASELINE] Skipping non-app directory: %s", entry.name)
            continue

        try:
            baseline = scan_app_directory(str(entry))
            inventory.apps[entry.name] = baseline
        except Exception as exc:
            msg = f"Failed to scan {entry.name}: {exc}"
            logger.warning("[BASELINE] %s", msg)
            inventory.errors.append(msg)

    logger.info(
        "[BASELINE] Cluster %s: %d apps scanned, %d errors",
        cluster_name,
        len(inventory.apps),
        len(inventory.errors),
    )
    return inventory


def scan_splunk_repo(repo_dir: str) -> ClusterInventory:
    """
    Recursively scan a full Splunk deployment repo and find ALL apps.

    Understands Splunk directory structures:
        repo/
        ├── deployment-apps/serverclass/AppName/
        ├── master-apps/_cluster/AppName/
        ├── shcluster/cluster-name/apps/AppName/
        └── etc/apps/AppName/

    Finds apps by looking for directories that contain:
        - default/ subdirectory, OR
        - app.conf file, OR
        - any .conf file in default/ or local/

    Returns a single ClusterInventory with all discovered apps,
    using the path as context (e.g., "shcluster/cluster-es/SA-CIM").
    """
    repo_path = Path(repo_dir)
    inventory = ClusterInventory(cluster_name=repo_path.name)

    if not repo_path.is_dir():
        inventory.errors.append(f"Repository directory not found: {repo_dir}")
        return inventory

    # Recursively find all Splunk app directories
    seen_apps: Dict[str, str] = {}  # app_name → first_found_path (dedup)

    for root, dirs, files in os.walk(str(repo_path)):
        root_path = Path(root)
        depth = len(root_path.relative_to(repo_path).parts)

        # Don't go deeper than 6 levels
        if depth > 6:
            dirs.clear()
            continue

        # Skip hidden dirs and common non-app directories
        dirs[:] = [d for d in dirs if not d.startswith('.') and d not in (
            '__pycache__', 'node_modules', '.git', 'bin', 'lib', 'lookups',
            'static', 'appserver', 'samples', 'README',
        )]

        # Check if THIS directory is a Splunk app
        has_default = (root_path / "default").is_dir()
        has_local = (root_path / "local").is_dir()
        has_app_conf = (
            (root_path / "app.conf").is_file() or
            (root_path / "default" / "app.conf").is_file()
        )
        has_conf_files = any(
            f.endswith('.conf') for f in files
        ) or (has_default and any(
            (root_path / "default" / f).is_file() and f.endswith('.conf')
            for f in os.listdir(root_path / "default")
        ) if has_default else False)

        is_app = has_app_conf or (has_default and has_conf_files) or (has_local and has_conf_files)

        if is_app:
            app_name = root_path.name
            rel_path = str(root_path.relative_to(repo_path))

            # Skip if we've already seen this app (dedup by name)
            if app_name in seen_apps:
                # Keep both — use path as unique key
                app_key = f"{app_name}@{rel_path.replace('/', '_')}"
            else:
                app_key = app_name
                seen_apps[app_name] = rel_path

            try:
                baseline = scan_app_directory(str(root_path))
                # Store deployment context in the baseline
                baseline.app_dir = str(root_path)
                inventory.apps[app_key] = baseline
            except Exception as exc:
                inventory.errors.append(f"Failed to scan {rel_path}: {exc}")

            # Don't descend into app subdirs (default/, local/ are not apps)
            dirs[:] = [d for d in dirs if d not in ('default', 'local', 'metadata', 'bin', 'lib')]

    logger.info(
        "[BASELINE] Repo %s: %d apps found, %d unique, %d errors",
        repo_path.name,
        len(inventory.apps),
        len(seen_apps),
        len(inventory.errors),
    )
    return inventory


def match_splunkbase_versions(
    inventory: ClusterInventory,
    catalog_path: Optional[str] = None,
) -> ClusterInventory:
    """
    Enrich a ClusterInventory with Splunkbase version data.

    Loads the SplunkbaseCatalog and attempts to find each app by app_id.
    Adds latest_version information to each AppBaseline where a catalog
    entry is found.

    This function modifies the inventory in-place and also returns it for
    chaining convenience.

    Args:
        inventory: ClusterInventory to enrich.
        catalog_path: Optional override for the catalog JSON file path.
            Defaults to the standard location from SplunkbaseCatalog.

    Returns:
        The same ClusterInventory, now enriched with upgrade candidates.
    """
    try:
        from chat_app.splunkbase_catalog import get_splunkbase_catalog  # noqa: PLC0415

        catalog = get_splunkbase_catalog()
        if catalog_path:
            catalog._catalog_path = Path(catalog_path)
        catalog.load_catalog()
    except ImportError:
        logger.warning("[BASELINE] splunkbase_catalog not available — skipping version match")
        return inventory

    apps_data = catalog.catalog.get("apps", {})

    # Build lookup by app_id (case-insensitive) for flexible matching
    by_app_id: Dict[str, Dict] = {}
    for _uid, app_entry in apps_data.items():
        aid = app_entry.get("app_id", "")
        if aid:
            by_app_id[aid.lower()] = app_entry

    upgrade_candidates: List[str] = []
    for app_name, baseline in inventory.apps.items():
        catalog_entry = by_app_id.get(app_name.lower())
        if not catalog_entry:
            continue

        latest_version = catalog_entry.get("latest_version", "")
        if not latest_version:
            continue

        installed_tuple = baseline.version.as_tuple()
        latest_tuple_parts = []
        for segment in latest_version.split("."):
            try:
                latest_tuple_parts.append(int(segment))
            except ValueError:
                latest_tuple_parts.append(0)
        latest_tuple = tuple(latest_tuple_parts)

        if installed_tuple < latest_tuple:
            upgrade_candidates.append(
                f"{app_name}: {baseline.version.version} → {latest_version}"
            )
            logger.info(
                "[BASELINE] Upgrade available for %s: %s → %s",
                app_name,
                baseline.version.version,
                latest_version,
            )

    if upgrade_candidates:
        logger.info(
            "[BASELINE] %d upgrade candidates in cluster %s",
            len(upgrade_candidates),
            inventory.cluster_name,
        )

    return inventory
