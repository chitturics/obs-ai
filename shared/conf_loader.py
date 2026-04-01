"""
Shared Splunk .conf file parser and loaders.

Parses stanza-based configuration files (macros.conf, savedsearches.conf,
commands.conf, indexes.conf) into structured dicts for use by the NLP
generator, optimizer, and analyzer components.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from shared.conf_parser import parse_conf_file_advanced

logger = logging.getLogger(__name__)


def parse_conf_file(conf_path: Path) -> List[Dict[str, Any]]:
    """
    Parse a Splunk .conf file into a list of stanza dicts.
    """
    with conf_path.open(encoding="utf-8", errors="ignore") as f:
        content = f.read()
    
    parsed_data = parse_conf_file_advanced(content, filename=str(conf_path))
    
    stanzas = []
    for stanza_name, stanza_data in parsed_data.items():
        search = stanza_data.get('search')
        fields = {k: v for k, v in stanza_data.items() if k not in ('search', '__lines__')}
        stanzas.append({
            "name": stanza_name,
            "fields": fields,
            "search": search,
            "file": str(conf_path)
        })
    return stanzas


def load_macros_from_conf(root: Path) -> Dict[str, Dict[str, Any]]:
    """
    Load macros from all macros.conf files under root.

    Returns dict: macro_name -> {definition, description, arg_count, ...}
    """
    macros: Dict[str, Dict[str, Any]] = {}

    for conf_path in root.rglob("macros.conf"):
        for stanza in parse_conf_file(conf_path):
            name = stanza["name"]
            if name == "default":
                continue

            fields = stanza.get("fields", {})
            definition = stanza.get("search") or fields.get("definition", "")
            if not definition:
                continue

            arg_list = [a.strip() for a in fields.get("args", "").split(",")] if fields.get("args") else []

            # Parse argument count from name (e.g. my_macro(2))
            arg_match = re.match(r"(.+)\((\d+)\)$", name)
            if arg_match:
                base_name = arg_match.group(1)
                # If args are defined, they take precedence over the number in the name
                arg_count = len(arg_list) if arg_list else int(arg_match.group(2))
            else:
                base_name = name
                arg_count = len(arg_list)

            macros[name] = {
                "name": name,
                "base_name": base_name,
                "definition": definition,
                "description": fields.get("description", ""),
                "args": arg_list,
                "arg_count": arg_count,
                "iseval": fields.get("iseval", "false").lower() == "true",
                "file": str(conf_path),
            }

    return macros


def load_searches_from_conf(root: Path) -> Dict[str, Dict[str, Any]]:
    """
    Load saved searches from all savedsearches.conf files under root.

    Returns dict: search_name -> {search, description, cron_schedule, ...}
    """
    searches: Dict[str, Dict[str, Any]] = {}

    for conf_path in root.rglob("savedsearches.conf"):
        for stanza in parse_conf_file(conf_path):
            name = stanza["name"]
            if name == "default":
                continue

            fields = stanza.get("fields", {})
            search = stanza.get("search") or fields.get("search", "")
            if not search:
                continue

            searches[name] = {
                "name": name,
                "search": search,
                "description": fields.get("description", ""),
                "is_scheduled": fields.get("enableSched", "0") == "1",
                "cron_schedule": fields.get("cron_schedule", ""),
                "is_alert": bool(fields.get("alert.track") or fields.get("actions")),
                "dispatch_earliest": fields.get("dispatch.earliest_time", ""),
                "dispatch_latest": fields.get("dispatch.latest_time", ""),
                "file": str(conf_path),
            }

    return searches


def load_commands_from_conf(root: Path) -> Dict[str, Dict[str, Any]]:
    """
    Load custom commands from all commands.conf files under root.

    Returns dict: command_name -> {type, streaming, generating, ...}
    """
    commands: Dict[str, Dict[str, Any]] = {}

    for conf_path in root.rglob("commands.conf"):
        for stanza in parse_conf_file(conf_path):
            name = stanza["name"]
            if name == "default":
                continue

            fields = stanza.get("fields", {})
            commands[name] = {
                "name": name,
                "type": fields.get("type", "python"),
                "filename": fields.get("filename", ""),
                "streaming": fields.get("streaming", "false").lower() == "true",
                "generating": fields.get("generating", "false").lower() == "true",
                "retainsevents": fields.get("retainsevents", "false").lower() == "true",
                "description": fields.get("description", ""),
                "file": str(conf_path),
            }

    return commands


def load_indexes_from_conf(root: Path) -> List[str]:
    """
    Load index names from all indexes.conf files under root.

    Returns list of index names (excluding internal/default stanzas).
    """
    indexes: List[str] = []
    skip_names = {"default", "volume:"}

    for conf_path in root.rglob("indexes.conf"):
        for stanza in parse_conf_file(conf_path):
            name = stanza["name"]
            if name in skip_names or name.startswith("volume:"):
                continue
            if name not in indexes:
                indexes.append(name)

    return indexes


def load_macros_flat(root: Path) -> Dict[str, str]:
    """
    Load macros as a flat name->definition dict (for SPLQueryOptimizer.register_macros).
    """
    result: Dict[str, str] = {}
    for name, macro in load_macros_from_conf(root).items():
        if macro.get("definition"):
            result[name] = macro["definition"]
    return result
