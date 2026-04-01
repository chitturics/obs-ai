"""Breaking Changes Database — versioned knowledge base of Splunk breaking changes.

Loads structured YAML files from data/breaking_changes/ and provides
query APIs for finding changes relevant to an upgrade path.

Each breaking change has:
- id: unique identifier (BC-{version}-{number})
- category: hardware, runtime, security, configuration, platform
- severity: blocker, warning, info
- title: human-readable summary
- description: detailed explanation
- detection: how to check if this affects you
- conf_file: which .conf file to check (if applicable)
- stanza/key: specific setting to check
- migration: steps to fix
"""

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

_DB_PATH = Path(os.getenv("BREAKING_CHANGES_PATH", "data/breaking_changes"))


@dataclass
class BreakingChange:
    """A single breaking change between Splunk versions."""
    id: str
    version: str  # Splunk version that introduced this change
    category: str  # hardware, runtime, security, configuration, platform
    severity: str  # blocker, warning, info
    title: str
    description: str = ""
    detection: str = ""
    conf_file: str = ""
    stanza: str = ""
    key: str = ""
    migration: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "version": self.version,
            "category": self.category,
            "severity": self.severity,
            "title": self.title,
            "description": self.description,
            "detection": self.detection,
            "conf_file": self.conf_file,
            "stanza": self.stanza,
            "key": self.key,
            "migration": self.migration,
        }


class BreakingChangesDB:
    """Loads and queries the breaking changes database."""

    def __init__(self, db_path: Optional[str] = None):
        self._path = Path(db_path) if db_path else _DB_PATH
        self._changes: Dict[str, List[BreakingChange]] = {}  # version -> changes
        self._loaded = False

    def load(self) -> None:
        """Load all YAML files from the database directory."""
        if not self._path.exists():
            logger.warning("[BREAKING-DB] Path not found: %s", self._path)
            return

        for yaml_file in sorted(self._path.glob("*.yaml")):
            try:
                data = yaml.safe_load(yaml_file.read_text(encoding="utf-8"))
                if not data:
                    continue
                version = data.get("version", yaml_file.stem)
                changes = []
                for c in data.get("changes", []):
                    changes.append(BreakingChange(
                        id=c.get("id", ""),
                        version=version,
                        category=c.get("category", ""),
                        severity=c.get("severity", "info"),
                        title=c.get("title", ""),
                        description=c.get("description", ""),
                        detection=c.get("detection", ""),
                        conf_file=c.get("conf_file", ""),
                        stanza=c.get("stanza", ""),
                        key=c.get("key", ""),
                        migration=c.get("migration", ""),
                    ))
                self._changes[version] = changes
                logger.debug("[BREAKING-DB] Loaded %d changes for v%s", len(changes), version)
            except (OSError, ValueError, yaml.YAMLError) as exc:
                logger.warning("[BREAKING-DB] Failed to load %s: %s", yaml_file, exc)

        self._loaded = True
        total = sum(len(v) for v in self._changes.values())
        logger.info("[BREAKING-DB] Loaded %d breaking changes across %d versions", total, len(self._changes))

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    def get_changes_for_version(self, version: str) -> List[BreakingChange]:
        """Get all breaking changes introduced in a specific version."""
        self._ensure_loaded()
        # Try exact match first, then major.minor match
        if version in self._changes:
            return self._changes[version]
        major_minor = ".".join(version.split(".")[:2])
        return self._changes.get(major_minor, [])

    def get_changes_between(self, from_version: str, to_version: str) -> List[BreakingChange]:
        """Get all breaking changes between two versions (exclusive of from, inclusive of to)."""
        self._ensure_loaded()
        result = []
        for version, changes in sorted(self._changes.items()):
            if _version_gt(version, from_version) and _version_le(version, to_version):
                result.extend(changes)
        return result

    def get_blockers(self, from_version: str, to_version: str) -> List[BreakingChange]:
        """Get only blocker-severity changes between two versions."""
        return [c for c in self.get_changes_between(from_version, to_version) if c.severity == "blocker"]

    def get_config_changes(self, from_version: str, to_version: str) -> List[BreakingChange]:
        """Get only configuration-related changes (have conf_file set)."""
        return [c for c in self.get_changes_between(from_version, to_version) if c.conf_file]

    def get_all_versions(self) -> List[str]:
        """Get all versions in the database."""
        self._ensure_loaded()
        return sorted(self._changes.keys())

    def get_summary(self) -> Dict[str, Any]:
        """Get database summary."""
        self._ensure_loaded()
        return {
            "versions": self.get_all_versions(),
            "total_changes": sum(len(v) for v in self._changes.values()),
            "by_version": {v: len(c) for v, c in self._changes.items()},
            "db_path": str(self._path),
        }


def _version_tuple(v: str) -> tuple:
    """Parse version string to tuple for comparison."""
    try:
        return tuple(int(x) for x in v.split(".")[:3])
    except (ValueError, TypeError):
        return (0, 0, 0)


def _version_gt(a: str, b: str) -> bool:
    return _version_tuple(a) > _version_tuple(b)


def _version_le(a: str, b: str) -> bool:
    return _version_tuple(a) <= _version_tuple(b)


# Singleton
_instance: Optional[BreakingChangesDB] = None


def get_breaking_changes_db(db_path: Optional[str] = None) -> BreakingChangesDB:
    """Get the singleton BreakingChangesDB instance."""
    global _instance
    if _instance is None:
        _instance = BreakingChangesDB(db_path)
    return _instance
