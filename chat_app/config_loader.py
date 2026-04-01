"""
Unified configuration loader — reads from config/ directory (Splunk-style) or config.yaml (legacy).

If config/ directory exists, loads individual YAML files and merges them.
Falls back to config.yaml for backward compatibility.

Config directory structure:
    config/
    ├── app.yaml              # Core app settings
    ├── llm.yaml              # LLM model, profiles
    ├── retrieval.yaml         # RAG retrieval
    ├── ...
    ├── workers/wk_*.yaml     # Scheduled task configs
    ├── skills/sk_*.yaml      # Skill configs
    ├── integrations/int_*.yaml  # External integrations
    └── profiles/*.yaml       # LLM profiles
"""

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

logger = logging.getLogger(__name__)

# Default paths
_CONFIG_DIR = Path(os.environ.get("OBSAI_CONFIG_DIR", "/app/config"))
_CONFIG_FILE = Path(os.environ.get("OBSAI_CONFIG_FILE", "/app/config.yaml"))

# Mapping: config file name → config.yaml section name (for backward compat)
_FILE_TO_SECTION = {
    "app": ["active_profile", "ui", "ports"],
    "llm": ["profiles", "prompts"],
    "retrieval": ["retrieval"],
    "ingestion": ["ingestion"],
    "database": ["database"],
    "security": ["security", "auth"],
    "organization": ["organization"],
    "features": ["features"],
    "orchestration": ["orchestration"],
    "knowledge_graph": ["knowledge_graph"],
    "mcp_gateway": ["mcp_gateway"],
    "directories": ["directories"],
    "upgrade_readiness": ["upgrade_readiness"],
}

_INTEGRATION_MAP = {
    "int_splunk": "splunk",
    "int_sharepoint": "sharepoint",
    "int_github": "github",
    "int_langfuse": "langfuse",
    "int_docling": "docling",
}


def _load_yaml(path: Path) -> Dict[str, Any]:
    """Load a single YAML file, returning empty dict on any error."""
    try:
        if path.is_file():
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
                return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.warning("[CONFIG] Failed to load %s: %s", path, exc)
    return {}


def load_config_directory(config_dir: Optional[Path] = None) -> Dict[str, Any]:
    """
    Load configuration from the config/ directory.

    Merges all YAML files into a single dict matching the legacy config.yaml structure.
    """
    cdir = config_dir or _CONFIG_DIR
    if not cdir.is_dir():
        return {}

    merged: Dict[str, Any] = {}

    # Load top-level config files
    for yaml_file in sorted(cdir.glob("*.yaml")):
        name = yaml_file.stem
        data = _load_yaml(yaml_file)

        if name in _FILE_TO_SECTION:
            # Map file contents to legacy section names
            for section_name in _FILE_TO_SECTION[name]:
                if section_name in data:
                    merged[section_name] = data[section_name]
                elif name == "app" and section_name == "active_profile":
                    merged["active_profile"] = data.get("active_profile", "LLM_LITE")
                else:
                    # The file IS the section
                    merged[section_name] = data
        else:
            # Direct mapping: file name = section name
            merged[name] = data

    # Load workers
    workers_dir = cdir / "workers"
    if workers_dir.is_dir():
        workers = {}
        for wf in sorted(workers_dir.glob("wk_*.yaml")):
            worker_name = wf.stem.replace("wk_", "")
            workers[worker_name] = _load_yaml(wf)
        if workers:
            merged["workers"] = workers
            # Also merge idle_worker settings from evolution worker
            if "evolution" in workers:
                merged["idle_worker"] = {
                    "enabled": workers["evolution"].get("enabled", True),
                    "idle_threshold_seconds": workers["evolution"].get("idle_threshold_seconds", 60),
                    "min_cycle_interval": workers["evolution"].get("interval_minutes", 5) * 60,
                    "max_tasks_per_cycle": workers["evolution"].get("max_tasks_per_cycle", 12),
                }

    # Load integrations
    integrations_dir = cdir / "integrations"
    if integrations_dir.is_dir():
        for inf in sorted(integrations_dir.glob("int_*.yaml")):
            int_name = inf.stem
            legacy_name = _INTEGRATION_MAP.get(int_name, int_name.replace("int_", ""))
            data = _load_yaml(inf)
            # Remove internal fields
            data.pop("description", None)
            merged[legacy_name] = data

    # Load profiles
    profiles_dir = cdir / "profiles"
    if profiles_dir.is_dir():
        profiles = {}
        for pf in sorted(profiles_dir.glob("*.yaml")):
            profiles[pf.stem] = _load_yaml(pf)
        if profiles:
            merged.setdefault("profiles", {}).update(profiles)

    # Load skills
    skills_dir = cdir / "skills"
    if skills_dir.is_dir():
        skills = {}
        for sf in sorted(skills_dir.glob("sk_*.yaml")):
            skill_name = sf.stem.replace("sk_", "")
            skills[skill_name] = _load_yaml(sf)
        if skills:
            merged["skill_configs"] = skills

    logger.info(
        "[CONFIG] Loaded from directory %s: %d sections, %d workers, %d integrations",
        cdir,
        len([k for k in merged if k not in ("workers", "skill_configs")]),
        len(merged.get("workers", {})),
        len([k for k in merged if k in _INTEGRATION_MAP.values()]),
    )

    return merged


def load_config(
    config_dir: Optional[Path] = None,
    config_file: Optional[Path] = None,
) -> Tuple[Dict[str, Any], str]:
    """
    Load configuration from directory or file.

    Returns:
        (config_dict, source) where source is "directory" or "file".
    """
    cdir = config_dir or _CONFIG_DIR
    cfile = config_file or _CONFIG_FILE

    # Prefer directory if it exists and has files
    if cdir.is_dir() and any(cdir.glob("*.yaml")):
        config = load_config_directory(cdir)
        if config:
            return config, f"directory:{cdir}"

    # Fall back to single file
    config = _load_yaml(cfile)
    if config:
        return config, f"file:{cfile}"

    logger.warning("[CONFIG] No configuration found at %s or %s", cdir, cfile)
    return {}, "default"


def list_config_files(config_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """List all config files with metadata for the admin UI."""
    cdir = config_dir or _CONFIG_DIR
    if not cdir.is_dir():
        return []

    files = []
    for yaml_file in sorted(cdir.rglob("*.yaml")):
        rel_path = yaml_file.relative_to(cdir)
        category = "core"
        if "workers" in str(rel_path):
            category = "worker"
        elif "integrations" in str(rel_path):
            category = "integration"
        elif "profiles" in str(rel_path):
            category = "profile"
        elif "skills" in str(rel_path):
            category = "skill"

        data = _load_yaml(yaml_file)
        enabled = data.get("enabled", True) if isinstance(data, dict) else True

        files.append({
            "name": yaml_file.stem,
            "path": str(rel_path),
            "category": category,
            "enabled": enabled,
            "description": data.get("description", "") if isinstance(data, dict) else "",
            "size_bytes": yaml_file.stat().st_size,
            "modified": yaml_file.stat().st_mtime,
        })

    return files


def save_config_file(
    relative_path: str,
    data: Dict[str, Any],
    config_dir: Optional[Path] = None,
) -> bool:
    """Save a single config file."""
    cdir = config_dir or _CONFIG_DIR
    target = cdir / relative_path

    # Security: prevent path traversal
    try:
        target.resolve().relative_to(cdir.resolve())
    except ValueError:
        logger.error("[CONFIG] Path traversal attempt: %s", relative_path)
        return False

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True)
        logger.info("[CONFIG] Saved config file: %s", relative_path)
        return True
    except Exception as exc:
        logger.error("[CONFIG] Failed to save %s: %s", relative_path, exc)
        return False
