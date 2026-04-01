"""
Splunk Configuration Analyzer for Cribl Migration.

Scans ALL Splunk apps' props.conf and transforms.conf files, identifies every
index-time setting, and produces a structured report grouped by app and sourcetype.

Usage as CLI:
    python -m chat_app.conf_index_time_analyzer /opt/splunk/etc/apps -o report.json

Usage as module:
    from chat_app.conf_index_time_analyzer import run_analysis
    report = run_analysis("/opt/splunk/etc/apps")
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — Index-time setting categories
# ---------------------------------------------------------------------------

EVENT_BREAKING_KEYS = frozenset({
    "LINE_BREAKER",
    "LINE_BREAKER_LOOKBEHIND",
    "SHOULD_LINEMERGE",
    "BREAK_ONLY_BEFORE",
    "BREAK_ONLY_BEFORE_DATE",
    "MUST_BREAK_AFTER",
    "MUST_NOT_BREAK_BEFORE",
    "MUST_NOT_BREAK_AFTER",
    "TRUNCATE",
    "MAX_EVENTS",
    "EVENT_BREAKER_ENABLE",
    "EVENT_BREAKER",
})

TIMESTAMP_KEYS = frozenset({
    "TIME_FORMAT",
    "TIME_PREFIX",
    "MAX_TIMESTAMP_LOOKAHEAD",
    "DATETIME_CONFIG",
    "TZ",
    "TZ_ALIAS",
    "MAX_DAYS_AGO",
    "MAX_DAYS_HENCE",
    "TIMESTAMP_FIELDS",
    "MAX_DIFF_SECS_AGO",
    "MAX_DIFF_SECS_HENCE",
    "ADD_EXTRA_TIME_FIELDS",
    "DETERMINE_TIMESTAMP_DATE_WITH_SYSTEM_TIME",
})

STRUCTURED_DATA_KEYS = frozenset({
    "INDEXED_EXTRACTIONS",
    "FIELD_DELIMITER",
    "FIELD_NAMES",
    "HEADER_FIELD_LINE_NUMBER",
    "HEADER_FIELD_DELIMITER",
    "FIELD_QUOTE",
    "HEADER_FIELD_QUOTE",
    "PREAMBLE_REGEX",
    "FIELD_HEADER_REGEX",
    "MISSING_VALUE_REGEX",
    "JSON_TRIM_BRACES_IN_ARRAY_NAMES",
    "HEADER_MODE",
    "CHECK_FOR_HEADER",
})

SOURCETYPE_KEYS = frozenset({
    "rename",
    "sourcetype",
})

ENCODING_KEYS = frozenset({
    "CHARSET",
    "NO_BINARY_CHECK",
})

METRICS_KEYS = frozenset({
    "METRICS_PROTOCOL",
    "STATSD-DIM-TRANSFORMS",
})

INLINE_EVAL_KEY = "INGEST_EVAL"


class Priority(str, Enum):
    """Migration priority levels."""
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TransformType(str, Enum):
    """Classification of transforms.conf stanzas."""
    FIELD_EXTRACTION = "field_extraction"
    INDEX_ROUTING = "index_routing"
    EVENT_DROPPING = "event_dropping"
    HOST_OVERRIDE = "host_override"
    SOURCE_OVERRIDE = "source_override"
    SOURCETYPE_OVERRIDE = "sourcetype_override"
    RAW_MODIFICATION = "raw_modification"
    CLONE = "clone"
    ROUTING = "routing"
    TIMESTAMP_OVERRIDE = "timestamp_override"
    UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ConfFile:
    """A discovered configuration file."""
    app_name: str
    app_path: str
    conf_type: str          # "props" or "transforms"
    layer: str              # "local" or "default"
    file_path: str
    app_category: str = ""  # "TAs", "BAs", "IAs", "UIs", "scripts", "legacy"
    deployment_group: str = ""  # "_global", "manager-apps", "cluster-prod-shc", "soc-soc-shc"


@dataclass
class IndexTimeSetting:
    """A single index-time setting extracted from props.conf."""
    key: str
    value: str
    category: str           # event_breaking, timestamp, sedcmd, transforms, ingest_eval, structured_data, sourcetype, encoding, metrics
    source_file: str
    stanza: str


@dataclass
class TransformDetail:
    """Resolved detail for a TRANSFORMS-* reference from transforms.conf."""
    transform_name: str
    stanza_name: str
    regex: Optional[str] = None
    format_str: Optional[str] = None
    dest_key: Optional[str] = None
    source_key: Optional[str] = None
    write_meta: Optional[str] = None
    lookahead: Optional[str] = None
    transform_type: TransformType = TransformType.UNKNOWN
    stop_processing_if: Optional[str] = None
    raw_settings: Dict[str, str] = field(default_factory=dict)


@dataclass
class CriblMapping:
    """Mapping of a Splunk setting to its Cribl equivalent."""
    splunk_setting: str
    splunk_value: str
    cribl_function: str
    cribl_config: Dict[str, Any]
    priority: Priority
    notes: str


@dataclass
class SourcetypeReport:
    """All index-time settings for a single sourcetype within an app."""
    sourcetype: str
    app_name: str
    event_breaking: Dict[str, str] = field(default_factory=dict)
    timestamp: Dict[str, str] = field(default_factory=dict)
    transforms: List[TransformDetail] = field(default_factory=list)
    sedcmds: Dict[str, str] = field(default_factory=dict)
    ingest_eval: List[str] = field(default_factory=list)
    structured_data: Dict[str, str] = field(default_factory=dict)
    sourcetype_settings: Dict[str, str] = field(default_factory=dict)
    encoding: Dict[str, str] = field(default_factory=dict)
    metrics: Dict[str, str] = field(default_factory=dict)
    cribl_pipeline: List[CriblMapping] = field(default_factory=list)
    stanza_type: str = ""  # "source", "host", "sourcetype", "default"


# ---------------------------------------------------------------------------
# 1. ConfsScanner — discovers all conf files
# ---------------------------------------------------------------------------

class ConfsScanner:
    """Scan a directory tree for all props.conf and transforms.conf files.

    Handles multiple directory structures:
    - Splunk deployment: /opt/splunk/etc/apps/*/default|local/
    - Splunk system: /opt/splunk/etc/system/default|local/
    - Git repos: any nested directory with props.conf or transforms.conf
    - Flat directories: directly containing conf files

    Properly identifies app names from directory structure and layer (default vs local).
    """

    TARGET_FILENAMES = {"props.conf", "transforms.conf"}
    CONF_SUBDIRS = ("local", "default")

    # Splunk app precedence (lower number = lower priority, overridden by higher)
    # system/default < app/default < app/local < system/local
    APP_TYPE_PRIORITY = {
        "system": 0,        # etc/system
        "framework": 10,    # SA-* (supporting addons)
        "addon": 20,        # TA-* (technology addons)
        "domain": 30,       # DA-* (domain addons)
        "app": 40,          # Regular apps
        "custom": 50,       # Custom/org-specific apps
    }

    LAYER_PRIORITY = {
        "default": 0,
        "local": 10,
    }

    def scan(self, root_dir: str) -> List[ConfFile]:
        """Recursively scan root_dir for all props.conf and transforms.conf files.

        Handles three scanning strategies:
        1. Standard Splunk layout: root_dir/*/default|local/*.conf
        2. Deep scan: find all props.conf/transforms.conf anywhere in tree
        3. Detect if root_dir itself IS an app directory

        Returns a list of ConfFile objects with proper app_name and layer.
        """
        results: List[ConfFile] = []
        root_path = Path(root_dir)

        if not root_path.is_dir():
            logger.warning("Directory does not exist: %s", root_dir)
            return results

        # Strategy 1: Check if root is itself an app (has default/ or local/ with conf files)
        if self._is_app_directory(root_path):
            results.extend(self._scan_single_app(root_path, root_path.name))
        else:
            # Strategy 2: Standard layout — look for app subdirectories
            standard_found = False
            for child in sorted(root_path.iterdir()):
                if not child.is_dir():
                    continue
                if self._is_app_directory(child):
                    results.extend(self._scan_single_app(child, child.name))
                    standard_found = True

            # Strategy 3: Deep scan — find conf files anywhere in tree
            if not standard_found:
                results.extend(self._deep_scan(root_path))

        logger.info(
            "Scanned %s: found %d conf files across %d apps",
            root_dir, len(results), len({cf.app_name for cf in results}),
        )
        return results

    def scan_splunk_repo(
        self,
        repo_root: str = "",
        app_filter: str = "",
        category_filter: str = "",
        group_filter: str = "",
    ) -> List[ConfFile]:
        """Scan an organizational Splunk repo with structured layout.

        Expected structure::

            repo_root/splunk/(TAs|BAs|IAs|UIs|scripts|legacy)/
                (_global|manager-apps|cluster-<shc>|soc-<shc>)/
                    <app_name>/(default|local)/<conf_file>.conf

        Args:
            repo_root: Path to the splunk repo root (parent of TAs/BAs/... dirs).
                       If empty, auto-detects from settings.paths.org_repo_root + "/splunk".
            app_filter: Regex pattern to filter app names.
            category_filter: Comma-separated list of categories (TAs, BAs, IAs, etc.).
            group_filter: Comma-separated list or glob for deployment groups.

        Returns:
            List of ConfFile objects with app_category and deployment_group populated.
        """
        if not repo_root:
            try:
                from chat_app.settings import get_settings
                repo_root = os.path.join(get_settings().paths.org_repo_root or "", "splunk")
            except Exception as _exc:  # broad catch — resilience against all failures
                logger.warning("Cannot auto-detect splunk repo root from settings")
                return []

        root_path = Path(repo_root)
        if not root_path.is_dir():
            logger.warning("Splunk repo root does not exist: %s", repo_root)
            return []

        results: List[ConfFile] = []
        app_re = re.compile(app_filter) if app_filter else None
        cat_set = {c.strip().lower() for c in category_filter.split(",") if c.strip()} if category_filter else None
        grp_set = {g.strip().lower() for g in group_filter.split(",") if g.strip()} if group_filter else None

        KNOWN_CATEGORIES = {"tas", "bas", "ias", "uis", "scripts", "legacy"}

        # Walk the directory tree looking for *.conf files
        for conf_path in sorted(root_path.rglob("*.conf")):
            if not conf_path.is_file():
                continue
            if conf_path.name not in self.TARGET_FILENAMES:
                continue

            # Parse path components relative to repo root
            try:
                relative = conf_path.relative_to(root_path)
            except ValueError:
                continue

            parts = relative.parts
            # Minimum: <conf_file>.conf (1 part) but we expect more structure
            conf_file_name = parts[-1]
            conf_type = conf_file_name.replace(".conf", "")

            # Determine layer, app_name, category, group from path depth
            app_category = ""
            deployment_group = ""
            app_name = ""
            layer = "unknown"

            if len(parts) >= 5:
                # Full structure: category/group/app_name/layer/file.conf
                app_category = parts[0]
                deployment_group = parts[1]
                app_name = parts[2]
                layer = parts[3] if parts[3] in ("default", "local") else "unknown"
            elif len(parts) >= 4:
                # Could be: category/app_name/layer/file.conf (no group)
                # Or: group/app_name/layer/file.conf (no category)
                if parts[0].lower() in KNOWN_CATEGORIES:
                    app_category = parts[0]
                    app_name = parts[1]
                    layer = parts[2] if parts[2] in ("default", "local") else "unknown"
                else:
                    deployment_group = parts[0]
                    app_name = parts[1]
                    layer = parts[2] if parts[2] in ("default", "local") else "unknown"
            elif len(parts) >= 3:
                # app_name/layer/file.conf
                app_name = parts[0]
                layer = parts[1] if parts[1] in ("default", "local") else "unknown"
            elif len(parts) >= 2:
                # layer/file.conf or app_name/file.conf
                if parts[0] in ("default", "local"):
                    app_name = root_path.name
                    layer = parts[0]
                else:
                    app_name = parts[0]
                    layer = "local"
            else:
                # Just file.conf at root
                app_name = root_path.name
                layer = "local"

            # Apply filters
            if cat_set and app_category.lower() not in cat_set:
                continue
            if grp_set and deployment_group.lower() not in grp_set:
                continue
            if app_re and not app_re.search(app_name):
                continue

            # Build app_path: everything up to the app_name directory
            if app_name and app_name in parts:
                app_idx = parts.index(app_name)
                app_path = str(root_path / Path(*parts[: app_idx + 1]))
            else:
                app_path = str(conf_path.parent.parent) if layer in ("default", "local") else str(conf_path.parent)

            results.append(ConfFile(
                app_name=app_name,
                app_path=app_path,
                conf_type=conf_type,
                layer=layer,
                file_path=str(conf_path),
                app_category=app_category,
                deployment_group=deployment_group,
            ))

        logger.info(
            "Scanned splunk repo %s: found %d conf files across %d apps, %d categories, %d groups",
            repo_root,
            len(results),
            len({cf.app_name for cf in results}),
            len({cf.app_category for cf in results if cf.app_category}),
            len({cf.deployment_group for cf in results if cf.deployment_group}),
        )
        return results

    def _is_app_directory(self, path: Path) -> bool:
        """Check if a directory looks like a Splunk app (has default/ or local/ with confs)."""
        for subdir in self.CONF_SUBDIRS:
            conf_dir = path / subdir
            if conf_dir.is_dir():
                for fname in self.TARGET_FILENAMES:
                    if (conf_dir / fname).is_file():
                        return True
        # Also check for app.conf or app.manifest (Splunk app markers)
        if (path / "default" / "app.conf").is_file():
            return True
        if (path / "app.manifest").is_file():
            return True
        return False

    def _scan_single_app(self, app_dir: Path, app_name: str) -> List[ConfFile]:
        """Scan a single Splunk app directory for conf files in default/ and local/."""
        results: List[ConfFile] = []
        for subdir in self.CONF_SUBDIRS:
            conf_dir = app_dir / subdir
            if not conf_dir.is_dir():
                continue
            for fname in self.TARGET_FILENAMES:
                conf_file = conf_dir / fname
                if conf_file.is_file():
                    conf_type = fname.replace(".conf", "")
                    results.append(ConfFile(
                        app_name=app_name,
                        app_path=str(app_dir),
                        conf_type=conf_type,
                        layer=subdir,
                        file_path=str(conf_file),
                    ))
        return results

    def _deep_scan(self, root: Path) -> List[ConfFile]:
        """Recursively find all props.conf and transforms.conf files anywhere in tree."""
        results: List[ConfFile] = []
        for conf_path in sorted(root.rglob("*")):
            if not conf_path.is_file() or conf_path.name not in self.TARGET_FILENAMES:
                continue

            # Determine app name and layer from path structure
            app_name, layer = self._infer_app_and_layer(conf_path, root)
            conf_type = conf_path.name.replace(".conf", "")

            results.append(ConfFile(
                app_name=app_name,
                app_path=str(conf_path.parent.parent) if layer in self.CONF_SUBDIRS else str(conf_path.parent),
                conf_type=conf_type,
                layer=layer,
                file_path=str(conf_path),
            ))
        return results

    def _infer_app_and_layer(self, conf_path: Path, root: Path) -> Tuple[str, str]:
        """Infer app name and layer (default/local) from file path.

        Handles patterns like:
        - repo/TA-myapp/default/props.conf → app=TA-myapp, layer=default
        - repo/apps/myapp/local/props.conf → app=myapp, layer=local
        - repo/system/local/props.conf → app=system, layer=local
        - repo/some/deep/path/props.conf → app=path, layer=unknown
        """
        relative = conf_path.relative_to(root)
        parts = relative.parts

        # If parent directory is "default" or "local", it's a proper layer
        if len(parts) >= 2 and parts[-2] in self.CONF_SUBDIRS:
            layer = parts[-2]
            # App name is the directory above default/local
            if len(parts) >= 3:
                app_name = parts[-3]
            else:
                app_name = root.name
            return app_name, layer

        # No standard layer — treat as "local" (highest priority)
        # App name from parent directory
        if len(parts) >= 2:
            app_name = parts[-2]
        else:
            app_name = root.name
        return app_name, "local"

    @classmethod
    def get_app_type(cls, app_name: str) -> str:
        """Classify a Splunk app by its naming convention."""
        name_lower = app_name.lower()
        if app_name == "system" or name_lower.startswith("etc_system"):
            return "system"
        if name_lower.startswith("sa-") or name_lower.startswith("sa_"):
            return "framework"
        if name_lower.startswith("ta-") or name_lower.startswith("ta_"):
            return "addon"
        if name_lower.startswith("da-") or name_lower.startswith("da_"):
            return "domain"
        if name_lower.startswith(("org-", "org_", "custom-", "custom_")):
            return "custom"
        return "app"

    @classmethod
    def get_app_priority(cls, app_name: str) -> int:
        """Get the precedence priority for an app (higher = overrides lower)."""
        app_type = cls.get_app_type(app_name)
        return cls.APP_TYPE_PRIORITY.get(app_type, 40)



# ---------------------------------------------------------------------------
# IndexTimeExtractor and ReportGenerator extracted to conf_index_time_helpers.py
# Re-exported here for backward compatibility
# ---------------------------------------------------------------------------
from chat_app.conf_index_time_helpers import (  # noqa: F401, E402
    IndexTimeExtractor,
    ReportGenerator,
)



# ---------------------------------------------------------------------------
# Cribl migration tools — extracted to conf_cribl_migration.py
# Re-exported here for backward compatibility via lazy __getattr__ to avoid
# circular imports (conf_cribl_migration imports from this module).
# ---------------------------------------------------------------------------
_CRIBL_MIGRATION_NAMES = {
    "BtoolImporter", "CriblMigrationMapper", "CriblScanner",
    "SplunkCriblComparator", "generate_cribl_pipeline_yaml",
    "generate_migration_checklist", "main", "validate_regex_pattern",
    "_yaml_escape", "run_analysis", "_process_props_settings",
    "_merge_conf_layers",
}


def __getattr__(name: str):
    if name in _CRIBL_MIGRATION_NAMES:
        import chat_app.conf_cribl_migration as _cm
        return getattr(_cm, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
