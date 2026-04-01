"""
Admin-managed MCP server registry.

Loads server definitions from config.yaml (or MCP_CONFIG_PATH env override)
and normalizes them so the UI/backend can enforce per-server auth schemes.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# Default to project-root config.yaml unless overridden
DEFAULT_CONFIG_PATH = Path(
    os.getenv("MCP_CONFIG_PATH")
    or Path(__file__).resolve().parents[1] / "config.yaml"
)

# Fallback servers if config is missing
_BUILTIN_SERVERS = [
    {
        "name": "splunk-mcp",
        "client_type": "sse",
        "endpoint": "http://127.0.0.1:8181",
        "auth_scheme": "bearer",
        "auth_hints": {"header": "Authorization", "prefix": "Bearer "},
        "description": "Local Splunk MCP server",
        "enabled": True,
    }
]


def _safe_load_yaml(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as _exc:  # broad catch — resilience against all failures
        return {}


def _normalize_server(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not entry:
        return None

    name = entry.get("name")
    if not name:
        return None

    server = {
        "name": name,
        "client_type": entry.get("client_type") or entry.get("type"),
        "endpoint": entry.get("endpoint") or entry.get("url"),
        "command": entry.get("command"),
        "description": entry.get("description"),
        "auth_scheme": (entry.get("auth_scheme") or "none").lower(),
        "auth_hints": entry.get("auth_hints") or {},
        "enabled": bool(entry.get("enabled", True)),
    }
    return server


def load_registry(config_path: Optional[Path] = None) -> Dict[str, Any]:
    """Load MCP registry from YAML; returns {'enabled': bool, 'servers': [...]}."""
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    cfg = _safe_load_yaml(path)
    gateway_cfg = cfg.get("mcp_gateway") or {}

    servers = gateway_cfg.get("servers") or []
    normalized = [_normalize_server(s) for s in servers]
    normalized = [s for s in normalized if s]

    if not normalized:
        normalized = _BUILTIN_SERVERS.copy()

    return {
        # Default to enabled; respect explicit ``enabled: false``.
        "enabled": bool(gateway_cfg.get("enabled", True)),
        "servers": normalized,
    }


def list_servers(include_disabled: bool = False) -> List[Dict[str, Any]]:
    registry = load_registry()
    if not registry.get("enabled", False):
        return []
    servers = registry["servers"]
    if include_disabled:
        return servers
    return [s for s in servers if s.get("enabled", True)]


def get_server(name: str) -> Optional[Dict[str, Any]]:
    for srv in list_servers(include_disabled=True):
        if srv["name"] == name:
            return srv
    return None
