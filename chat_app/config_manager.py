"""
Config Manager — Full CRUD management for config.yaml.

Provides:
1. Section-level read/write for every config.yaml section
2. Backup before writes (config.yaml.bak)
3. Validation of values before writing
4. Audit trail integration
5. Profile switching
6. Live reload after changes

Every section in config.yaml is editable:
- active_profile, profiles, directories, database, ingestion, retrieval,
  prompts, ui, security, features, mcp_gateway, sharepoint, github, organization
"""
import copy
import logging
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)


class ConfigManager:
    """Manages config.yaml with section-level CRUD, backup, and validation."""

    def __init__(self, config_path: Optional[str] = None):
        self._config_path = self._resolve_config_path(config_path)
        self._cache: Optional[Dict[str, Any]] = None
        self._last_loaded: float = 0

    @staticmethod
    def _resolve_config_path(explicit_path: Optional[str] = None) -> Path:
        """Find the config.yaml file.

        Write path: prefers /app/data/config.yaml (persistent volume) so
        config changes survive container rebuilds. Falls back to /app/config.yaml
        for reading the baked-in default.
        """
        # Writable persistent path (volume-backed, survives rebuilds)
        persistent_path = Path(os.getenv("CONFIG_YAML_WRITABLE", "/app/data/config.yaml"))
        if persistent_path.is_file():
            return persistent_path.resolve()

        candidates = [
            Path(explicit_path) if explicit_path else Path(""),
            Path(os.getenv("CONFIG_YAML", "")),
            Path("/app/config.yaml"),
            Path.cwd() / "config.yaml",
            Path(__file__).resolve().parent.parent / "config.yaml",
        ]
        for p in candidates:
            if p.is_file():
                # If we found a read-only source, copy to persistent path for writing
                if persistent_path.parent.exists() or persistent_path.parent == Path("/app/data"):
                    try:
                        persistent_path.parent.mkdir(parents=True, exist_ok=True)
                        import shutil
                        shutil.copy2(str(p), str(persistent_path))
                        logger.info("[CONFIG-MGR] Copied %s → %s (persistent)", p, persistent_path)
                        return persistent_path.resolve()
                    except (PermissionError, OSError):
                        pass  # Fall back to in-place path
                return p.resolve()
        return (Path(__file__).resolve().parent.parent / "config.yaml").resolve()

    @property
    def config_path(self) -> str:
        return str(self._config_path)

    def load(self, force: bool = False) -> Dict[str, Any]:
        """Load config.yaml, using cache if available."""
        if self._cache is not None and not force:
            return copy.deepcopy(self._cache)

        try:
            if self._config_path.is_file():
                with open(self._config_path, encoding="utf-8") as fh:
                    data = yaml.safe_load(fh) or {}
                self._cache = data
                logger.info("[CONFIG-MGR] Loaded config from %s", self._config_path)
                return copy.deepcopy(data)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("[CONFIG-MGR] Failed to load config: %s", exc)

        self._cache = {}
        return {}

    def save(self, data: Dict[str, Any], reason: str = "") -> bool:
        """Save config data to config.yaml with backup.

        Uses ruamel.yaml when available to preserve comments in the file.
        Falls back to standard yaml.dump (which strips comments).
        """
        try:
            # Create backup
            self._backup()

            # Try comment-preserving save via ruamel.yaml
            if self._save_with_ruamel(data):
                self._cache = copy.deepcopy(data)
                logger.info("[CONFIG-MGR] Saved config with ruamel (%s)", reason or "no reason")
                return True

            # Fallback: standard yaml.dump (strips comments)
            with open(self._config_path, "w", encoding="utf-8") as fh:
                yaml.dump(
                    data,
                    fh,
                    default_flow_style=False,
                    allow_unicode=True,
                    sort_keys=False,
                    width=120,
                )

            self._cache = copy.deepcopy(data)
            logger.info("[CONFIG-MGR] Saved config (%s)", reason or "no reason")
            return True

        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.error("[CONFIG-MGR] Failed to save config: %s", exc)
            return False

    def _save_with_ruamel(self, data: Dict[str, Any]) -> bool:
        """Try to save using ruamel.yaml to preserve comments.

        Loads the existing file (with comments), merges new data values in,
        then writes back.  Returns False if ruamel is not available.
        """
        try:
            from ruamel.yaml import YAML  # type: ignore[import-untyped]
        except ImportError:
            return False

        try:
            ryaml = YAML()
            ryaml.preserve_quotes = True
            ryaml.width = 120

            # Load existing file with comments
            if self._config_path.is_file():
                with open(self._config_path, encoding="utf-8") as fh:
                    existing = ryaml.load(fh)
                if existing is None:
                    existing = {}
            else:
                existing = {}

            # Deep-update existing with new data values
            self._ruamel_deep_update(existing, data)

            with open(self._config_path, "w", encoding="utf-8") as fh:
                ryaml.dump(existing, fh)

            return True
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.debug("[CONFIG-MGR] ruamel save failed, will fallback: %s", exc)
            return False

    @staticmethod
    def _ruamel_deep_update(base: Any, overlay: Dict[str, Any]) -> None:
        """Recursively update ruamel CommentedMap values from a plain dict."""
        for key, value in overlay.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                ConfigManager._ruamel_deep_update(base[key], value)
            else:
                base[key] = value

    def _backup(self) -> Optional[str]:
        """Create a backup of config.yaml before writing."""
        if not self._config_path.is_file():
            return None

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        backup_dir = self._config_path.parent / "config_backups"
        backup_dir.mkdir(parents=True, exist_ok=True)

        backup_path = backup_dir / f"config_{timestamp}.yaml"
        shutil.copy2(self._config_path, backup_path)

        # Also maintain a simple .bak file
        shutil.copy2(self._config_path, self._config_path.with_suffix(".yaml.bak"))

        # Keep only last 20 backups
        backups = sorted(backup_dir.glob("config_*.yaml"))
        if len(backups) > 20:
            for old in backups[:-20]:
                old.unlink(missing_ok=True)

        logger.info("[CONFIG-MGR] Backup created: %s", backup_path.name)
        return str(backup_path)

    # ------------------------------------------------------------------
    # Section-level CRUD
    # ------------------------------------------------------------------

    def get_section(self, section: str) -> Dict[str, Any]:
        """Get a specific top-level section from config."""
        data = self.load()
        if section not in data:
            return {}
        val = data[section]
        return val if isinstance(val, dict) else {"value": val}

    def update_section(self, section: str, updates: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Update a section with partial values. Returns (success, updated_section)."""
        data = self.load(force=True)

        if section not in data:
            data[section] = {}

        current = data[section]
        if isinstance(current, dict):
            previous = copy.deepcopy(current)
            current = self._deep_merge(current, updates)
            data[section] = current
        else:
            previous = current
            data[section] = updates.get("value", updates)

        success = self.save(data, reason=f"update section '{section}'")

        # Record versioned commit
        if success:
            try:
                from chat_app.config_versioning import get_config_version_store
                store = get_config_version_store()
                store.commit(
                    section=section,
                    old_value=previous,
                    new_value=data.get(section, {}),
                    message=f"Update section '{section}'",
                )
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.debug("[CONFIG-MGR] Version commit failed: %s", exc)

        return success, data.get(section, {})

    def replace_section(self, section: str, new_data: Any) -> Tuple[bool, Any]:
        """Completely replace a section. Returns (success, new_section)."""
        data = self.load(force=True)
        previous = copy.deepcopy(data.get(section))
        data[section] = new_data
        success = self.save(data, reason=f"replace section '{section}'")

        # Record versioned commit
        if success:
            try:
                from chat_app.config_versioning import get_config_version_store
                store = get_config_version_store()
                store.commit(
                    section=section,
                    old_value=previous,
                    new_value=new_data,
                    message=f"Replace section '{section}'",
                )
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.debug("[CONFIG-MGR] Version commit failed: %s", exc)

        return success, new_data

    def delete_section_key(self, section: str, key: str) -> bool:
        """Delete a specific key from a section."""
        data = self.load(force=True)
        if section not in data or not isinstance(data[section], dict):
            return False
        if key not in data[section]:
            return False
        previous = copy.deepcopy(data[section])
        del data[section][key]
        success = self.save(data, reason=f"delete key '{key}' from section '{section}'")

        # Record versioned commit
        if success:
            try:
                from chat_app.config_versioning import get_config_version_store
                store = get_config_version_store()
                store.commit(
                    section=section,
                    old_value=previous,
                    new_value=data[section],
                    message=f"Delete key '{key}' from section '{section}'",
                )
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.debug("[CONFIG-MGR] Version commit failed: %s", exc)

        return success

    # ------------------------------------------------------------------
    # Profile management
    # ------------------------------------------------------------------

    def get_active_profile(self) -> str:
        """Get the active deployment profile name."""
        data = self.load()
        return data.get("active_profile", "LLM_MED")

    def get_profile(self, name: str) -> Dict[str, Any]:
        """Get a specific profile's configuration."""
        data = self.load()
        profiles = data.get("profiles", {})
        return profiles.get(name, {})

    def list_profiles(self) -> Dict[str, Any]:
        """List all available profiles with their descriptions."""
        data = self.load()
        profiles = data.get("profiles", {})
        result = {}
        for name, cfg in profiles.items():
            result[name] = {
                "description": cfg.get("description", ""),
                "hardware": cfg.get("hardware", {}),
                "llm_model": cfg.get("llm", {}).get("model", ""),
                "context_length": cfg.get("llm", {}).get("context_length", 0),
            }
        return result

    def switch_profile(self, profile_name: str) -> Tuple[bool, str]:
        """Switch active profile. Returns (success, message)."""
        data = self.load(force=True)
        profiles = data.get("profiles", {})

        if profile_name not in profiles:
            return False, f"Profile '{profile_name}' not found. Available: {list(profiles.keys())}"

        data["active_profile"] = profile_name
        success = self.save(data, reason=f"switch profile to '{profile_name}'")
        if success:
            return True, f"Switched to profile '{profile_name}'. Restart required."
        return False, "Failed to save config."

    def update_profile(self, profile_name: str, updates: Dict[str, Any]) -> Tuple[bool, Dict[str, Any]]:
        """Update a specific profile's settings."""
        data = self.load(force=True)
        profiles = data.setdefault("profiles", {})

        if profile_name not in profiles:
            return False, {}

        profiles[profile_name] = self._deep_merge(profiles[profile_name], updates)
        success = self.save(data, reason=f"update profile '{profile_name}'")
        return success, profiles[profile_name]

    # ------------------------------------------------------------------
    # Specialized section helpers
    # ------------------------------------------------------------------

    def get_all_sections(self) -> Dict[str, Any]:
        """Get all config sections with metadata."""
        data = self.load()
        sections = {}
        for key, val in data.items():
            if isinstance(val, dict):
                sections[key] = {
                    "type": "object",
                    "keys": list(val.keys()),
                    "key_count": len(val),
                }
            elif isinstance(val, list):
                sections[key] = {"type": "list", "count": len(val)}
            else:
                sections[key] = {"type": type(val).__name__, "value": val}
        return sections

    def get_full_config(self) -> Dict[str, Any]:
        """Get the entire config (for export/backup)."""
        return self.load()

    def import_config(self, new_config: Dict[str, Any]) -> Tuple[bool, str]:
        """Import a complete config (with backup of current)."""
        if not isinstance(new_config, dict):
            return False, "Config must be a dictionary."
        success = self.save(new_config, reason="full config import")
        return success, "Config imported successfully." if success else "Import failed."

    def get_backups(self) -> List[Dict[str, Any]]:
        """List available config backups."""
        backup_dir = self._config_path.parent / "config_backups"
        if not backup_dir.is_dir():
            return []

        backups = []
        for f in sorted(backup_dir.glob("config_*.yaml"), reverse=True):
            stat = f.stat()
            backups.append({
                "filename": f.name,
                "path": str(f),
                "size_bytes": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
            })
        return backups[:20]

    def restore_backup(self, filename: str) -> Tuple[bool, str]:
        """Restore config from a backup file."""
        backup_dir = self._config_path.parent / "config_backups"
        # Path traversal protection
        if ".." in filename or "/" in filename or "\\" in filename:
            return False, "Invalid filename."
        backup_path = backup_dir / filename
        try:
            if not str(backup_path.resolve(strict=False)).startswith(str(backup_dir.resolve())):
                return False, "Invalid filename."
        except (OSError, ValueError):
            return False, "Invalid filename."

        if not backup_path.is_file():
            return False, "Backup not found."

        try:
            with open(backup_path, encoding="utf-8") as fh:
                data = yaml.safe_load(fh) or {}

            success = self.save(data, reason=f"restore from backup '{filename}'")
            return success, "Config restored." if success else "Restore failed."
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.error("Config restore failed: %s", exc, exc_info=True)
            return False, "Restore error. Check server logs for details."

    # ------------------------------------------------------------------
    # Validation helpers
    # ------------------------------------------------------------------

    def validate_section(self, section: str, data: Dict[str, Any]) -> Tuple[bool, List[str]]:
        """Validate section data against known constraints."""
        errors = []

        if section == "active_profile":
            cfg = self.load()
            profiles = cfg.get("profiles", {})
            if data.get("value") not in profiles:
                errors.append(f"Invalid profile. Available: {list(profiles.keys())}")

        elif section == "database":
            pg = data.get("postgres", {})
            if pg.get("port") and not (1 <= pg["port"] <= 65535):
                errors.append("postgres.port must be 1-65535")
            if pg.get("max_connections") and pg["max_connections"] < 1:
                errors.append("postgres.max_connections must be >= 1")

        elif section == "retrieval":
            for key in ("top_k", "similarity_threshold"):
                sub = data.get(key, {})
                if isinstance(sub, dict):
                    for k, v in sub.items():
                        if key == "top_k" and isinstance(v, int) and v < 1:
                            errors.append(f"retrieval.top_k.{k} must be >= 1")
                        if key == "similarity_threshold" and isinstance(v, (int, float)):
                            if not (0 <= v <= 1):
                                errors.append(f"retrieval.similarity_threshold.{k} must be 0-1")

        elif section == "security":
            rl = data.get("rate_limiting", {})
            if "max_queries_per_minute" in rl and isinstance(rl["max_queries_per_minute"], (int, float)):
                if rl["max_queries_per_minute"] < 1:
                    errors.append("rate_limiting.max_queries_per_minute must be >= 1")

        elif section == "ingestion":
            perf = data.get("performance", {})
            if perf.get("max_file_size_mb") and perf["max_file_size_mb"] < 1:
                errors.append("ingestion.performance.max_file_size_mb must be >= 1")

        return len(errors) == 0, errors

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _deep_merge(base: Dict, override: Dict) -> Dict:
        """Deep merge override into base (override wins)."""
        result = copy.deepcopy(base)
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ConfigManager._deep_merge(result[key], value)
            else:
                result[key] = copy.deepcopy(value)
        return result


# Singleton
_manager: Optional[ConfigManager] = None


def get_config_manager() -> ConfigManager:
    """Get or create the singleton ConfigManager."""
    global _manager
    if _manager is None:
        _manager = ConfigManager()
    return _manager
