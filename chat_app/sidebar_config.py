"""Sidebar Configuration — admin-customizable navigation layout.

Stores sidebar group/item visibility and ordering in a JSON file.
Defaults to the built-in layout if no customization exists.

Usage:
    from chat_app.sidebar_config import get_sidebar_config, save_sidebar_config

    config = get_sidebar_config()  # Returns current layout
    config["groups"][0]["order"] = 5  # Move first group to 5th position
    save_sidebar_config(config)
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(os.getenv("SIDEBAR_CONFIG_PATH", "/app/data/sidebar_config.json"))

# Default groups matching frontend/src/constants/sections.ts
_DEFAULT_GROUPS: List[Dict[str, Any]] = [
    {
        "label": "Overview", "order": 0, "visible": True,
        "items": [
            {"id": "dashboard", "label": "Dashboard", "visible": True, "order": 0},
        ],
    },
    {
        "label": "AI & Retrieval", "order": 1, "visible": True,
        "items": [
            {"id": "profiles", "label": "Profiles", "visible": True, "order": 0},
            {"id": "llm", "label": "LLM", "visible": True, "order": 1},
            {"id": "retrieval", "label": "Retrieval", "visible": True, "order": 2},
            {"id": "prompts", "label": "Prompts", "visible": True, "order": 3},
            {"id": "ingestion", "label": "Ingestion", "visible": True, "order": 4},
            {"id": "chunking", "label": "Chunking", "visible": True, "order": 5},
        ],
    },
    {
        "label": "Intelligence", "order": 2, "visible": True,
        "items": [
            {"id": "skills", "label": "Skills & Agents", "visible": True, "order": 0},
            {"id": "orchestration", "label": "Orchestration", "visible": True, "order": 1},
            {"id": "workflow-designer", "label": "Workflow Designer", "visible": True, "order": 2},
            {"id": "mcp", "label": "MCP Gateway", "visible": True, "order": 3},
            {"id": "knowledge-graph", "label": "Knowledge Graph", "visible": True, "order": 4},
            {"id": "learning", "label": "Self-Learning", "visible": True, "order": 5},
            {"id": "prompt-templates", "label": "Prompt Templates", "visible": True, "order": 6},
            {"id": "quality-monitor", "label": "Quality Monitor", "visible": True, "order": 7},
            {"id": "evolution", "label": "Evolution Engine", "visible": True, "order": 8},
            {"id": "features", "label": "Feature Flags", "visible": True, "order": 9},
        ],
    },
    {
        "label": "Developer Tools", "order": 3, "visible": True,
        "items": [
            {"id": "script-builder", "label": "Script Builder", "visible": True, "order": 0},
            {"id": "api-services", "label": "API Services", "visible": True, "order": 1},
            {"id": "action-engine", "label": "Action Engine", "visible": True, "order": 2},
        ],
    },
    {
        "label": "Infrastructure", "order": 4, "visible": True,
        "items": [
            {"id": "ssl", "label": "Network & SSL", "visible": True, "order": 0},
            {"id": "database", "label": "Database", "visible": True, "order": 1},
            {"id": "cache", "label": "Cache", "visible": True, "order": 2},
            {"id": "security", "label": "Security", "visible": True, "order": 3},
            {"id": "users", "label": "Users & Roles", "visible": True, "order": 4},
            {"id": "paths", "label": "Paths", "visible": True, "order": 5},
            {"id": "ui-settings", "label": "UI Settings", "visible": True, "order": 6},
            {"id": "auth", "label": "Authentication", "visible": True, "order": 7},
            {"id": "journal", "label": "Execution Journal", "visible": True, "order": 8},
        ],
    },
    {
        "label": "Integrations", "order": 5, "visible": True,
        "items": [
            {"id": "splunk", "label": "Splunk", "visible": True, "order": 0},
            {"id": "github", "label": "GitHub", "visible": True, "order": 1},
            {"id": "organization", "label": "Organization", "visible": True, "order": 2},
            {"id": "sharepoint", "label": "SharePoint", "visible": True, "order": 3},
            {"id": "docling", "label": "Docling", "visible": True, "order": 4},
            {"id": "otel", "label": "OpenTelemetry", "visible": True, "order": 5},
        ],
    },
    {
        "label": "Operations", "order": 6, "visible": True,
        "items": [
            {"id": "containers", "label": "Containers", "visible": True, "order": 0},
            {"id": "observability", "label": "Observability", "visible": True, "order": 1},
            {"id": "traces", "label": "Query Traces", "visible": True, "order": 2},
            {"id": "collections", "label": "Collections", "visible": True, "order": 3},
            {"id": "config-editor", "label": "Config Editor", "visible": True, "order": 4},
            {"id": "audit", "label": "Audit Log", "visible": True, "order": 5},
            {"id": "backup", "label": "Backup", "visible": True, "order": 6},
            {"id": "version", "label": "Version", "visible": True, "order": 7},
            {"id": "docs", "label": "Documentation", "visible": True, "order": 8},
            {"id": "module-docs", "label": "Module Reference", "visible": True, "order": 9},
            {"id": "commands", "label": "Commands", "visible": True, "order": 10},
        ],
    },
]


def get_sidebar_config() -> Dict[str, Any]:
    """Load sidebar config from file, or return defaults."""
    if _CONFIG_PATH.exists():
        try:
            with open(_CONFIG_PATH) as f:
                config = json.load(f)
            if "groups" in config:
                return config
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.warning("[SIDEBAR] Failed to load config: %s", exc)

    import copy
    return {
        "groups": copy.deepcopy(_DEFAULT_GROUPS),
        "updated_at": None,
        "updated_by": None,
    }


def save_sidebar_config(config: Dict[str, Any], actor: str = "admin") -> Dict[str, Any]:
    """Save sidebar config to file."""
    config["updated_at"] = datetime.now(timezone.utc).isoformat()
    config["updated_by"] = actor
    try:
        _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
        logger.info("[SIDEBAR] Config saved by %s", actor)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        logger.error("[SIDEBAR] Failed to save config: %s", exc)
        raise
    return config


def reset_sidebar_config() -> Dict[str, Any]:
    """Reset to default sidebar layout."""
    if _CONFIG_PATH.exists():
        _CONFIG_PATH.unlink()
    return get_sidebar_config()
