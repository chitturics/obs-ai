"""
/build_config — Interactive Splunk Configuration Builder.

Guides the user step-by-step through building inputs.conf, props.conf,
or transforms.conf stanzas using Chainlit actions and questions.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List

import chainlit as cl

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration templates
# ---------------------------------------------------------------------------

_CONF_TYPES = {
    "inputs.conf": {
        "description": "Data inputs — how data enters Splunk",
        "stanza_types": {
            "monitor": {
                "label": "File/Directory Monitor",
                "required": ["path"],
                "optional": {
                    "disabled": ("false", "Enable/disable this input"),
                    "index": ("main", "Target index"),
                    "sourcetype": ("", "Source type assignment"),
                    "whitelist": ("", "Regex — only matching files"),
                    "blacklist": ("", "Regex — exclude matching files"),
                    "crcSalt": ("", "Set to <SOURCE> for unique file tracking"),
                    "followTail": ("0", "Start reading from end of file (0 or 1)"),
                    "recursive": ("true", "Monitor subdirectories"),
                    "ignoreOlderThan": ("", "Skip files older than (e.g. 7d)"),
                },
            },
            "tcp": {
                "label": "TCP Network Input",
                "required": ["port"],
                "optional": {
                    "disabled": ("false", "Enable/disable"),
                    "index": ("main", "Target index"),
                    "sourcetype": ("syslog", "Source type"),
                    "connection_host": ("dns", "How to set host: ip, dns, none"),
                    "queueSize": ("500KB", "In-memory queue size"),
                    "persistentQueueSize": ("0", "Persistent queue size (0=off)"),
                },
            },
            "udp": {
                "label": "UDP Network Input",
                "required": ["port"],
                "optional": {
                    "disabled": ("false", "Enable/disable"),
                    "index": ("main", "Target index"),
                    "sourcetype": ("syslog", "Source type"),
                    "connection_host": ("dns", "How to set host: ip, dns, none"),
                    "no_appending_timestamp": ("false", "Don't add receive time"),
                },
            },
            "script": {
                "label": "Scripted Input",
                "required": ["script_path", "interval"],
                "optional": {
                    "disabled": ("false", "Enable/disable"),
                    "index": ("main", "Target index"),
                    "sourcetype": ("", "Source type"),
                    "passAuth": ("", "Splunk user for auth token"),
                },
            },
            "http": {
                "label": "HTTP Event Collector (HEC)",
                "required": [],
                "optional": {
                    "disabled": ("false", "Enable/disable"),
                    "index": ("main", "Default target index"),
                    "token": ("", "Authentication token"),
                    "indexes": ("", "Comma-separated allowed indexes"),
                    "sourcetype": ("", "Default source type"),
                    "useACK": ("false", "Enable indexer acknowledgment"),
                },
            },
        },
    },
    "props.conf": {
        "description": "Parsing and field extraction configuration",
        "stanza_types": {
            "sourcetype": {
                "label": "Source Type Definition",
                "required": ["sourcetype_name"],
                "optional": {
                    "TIME_FORMAT": ("", "strftime format (e.g. %Y-%m-%d %H:%M:%S)"),
                    "TIME_PREFIX": ("", "Regex before timestamp"),
                    "MAX_TIMESTAMP_LOOKAHEAD": ("128", "Chars to search for timestamp"),
                    "LINE_BREAKER": ("([\\r\\n]+)", "Regex for event boundaries"),
                    "SHOULD_LINEMERGE": ("true", "Merge multi-line events"),
                    "TRUNCATE": ("10000", "Max event size in bytes"),
                    "TRANSFORMS-custom": ("", "Name of transforms.conf stanza"),
                    "REPORT-custom": ("", "Name of transforms.conf extraction"),
                    "EXTRACT-custom": ("", "Inline regex field extraction"),
                    "KV_MODE": ("auto", "auto, json, xml, none"),
                    "SEDCMD-clean": ("", "Sed command for data masking"),
                    "category": ("", "Category for data model mapping"),
                    "description": ("", "Human-readable description"),
                },
            },
        },
    },
    "transforms.conf": {
        "description": "Field transformations, lookups, and routing",
        "stanza_types": {
            "extraction": {
                "label": "Field Extraction (REPORT/TRANSFORMS)",
                "required": ["stanza_name"],
                "optional": {
                    "REGEX": ("", "Regular expression with named groups"),
                    "FORMAT": ("", "Output format (e.g. $1::$2)"),
                    "DEST_KEY": ("_raw", "Destination key"),
                    "SOURCE_KEY": ("_raw", "Source key to apply regex to"),
                    "MV_ADD": ("false", "Add to multi-value field"),
                    "CLEAN_KEYS": ("true", "Clean leading/trailing whitespace"),
                },
            },
            "lookup": {
                "label": "Lookup Definition",
                "required": ["stanza_name", "filename"],
                "optional": {
                    "max_matches": ("1", "Max lookup matches per event"),
                    "min_matches": ("1", "Min matches (0=optional)"),
                    "default_match": ("", "Default if no match found"),
                    "case_sensitive_match": ("true", "Case-sensitive key matching"),
                    "batch_index_query": ("0", "Enable batch indexing"),
                    "match_type": ("", "WILDCARD(field), CIDR(field)"),
                },
            },
            "routing": {
                "label": "Index-Time Routing",
                "required": ["stanza_name"],
                "optional": {
                    "REGEX": ("", "Regex to match events"),
                    "DEST_KEY": ("_MetaData:Index", "Routing destination"),
                    "FORMAT": ("", "Target index name"),
                    "SOURCE_KEY": ("_raw", "Field to match against"),
                },
            },
        },
    },
}


# ---------------------------------------------------------------------------
# Builder flow
# ---------------------------------------------------------------------------

from chat_app.config_validator import validate_user_input


async def build_config_command(args: str = "") -> None:
    """Interactive configuration builder entry point."""

    # Step 1: Choose conf file type
    actions = [
        cl.Action(
            name="build_config_type",
            label=conf_type,
            payload={"conf_type": conf_type},
            description=info["description"],
        )
        for conf_type, info in _CONF_TYPES.items()
    ]

    res = await cl.AskActionMessage(
        content="**Configuration Builder**\n\nWhich configuration file do you want to build?",
        actions=actions,
    ).send()

    if not res:
        await cl.Message(content="Configuration builder cancelled.").send()
        return

    conf_type = res.get("payload", {}).get("conf_type", "")
    if conf_type not in _CONF_TYPES:
        await cl.Message(content=f"Unknown conf type: {conf_type}").send()
        return

    conf_info = _CONF_TYPES[conf_type]

    # Step 2: Choose stanza type
    stanza_actions = [
        cl.Action(
            name="build_config_stanza",
            label=info["label"],
            payload={"stanza_type": stype, "conf_type": conf_type},
        )
        for stype, info in conf_info["stanza_types"].items()
    ]

    res = await cl.AskActionMessage(
        content=f"**{conf_type}** — Choose the type of stanza to create:",
        actions=stanza_actions,
    ).send()

    if not res:
        await cl.Message(content="Configuration builder cancelled.").send()
        return

    stanza_type = res.get("payload", {}).get("stanza_type", "")
    stanza_info = conf_info["stanza_types"].get(stanza_type)
    if not stanza_info:
        await cl.Message(content=f"Unknown stanza type: {stanza_type}").send()
        return

    # Step 3: Collect required fields
    collected: Dict[str, str] = {}

    for field_name in stanza_info["required"]:
        while True:
            res = await cl.AskUserMessage(
                content=f"Enter **{field_name}** (required):",
                timeout=120,
            ).send()
            if not res:
                await cl.Message(content="Configuration builder cancelled.").send()
                return

            user_input = res["output"].strip()
            is_valid, error_message = validate_user_input(user_input, field_name)

            if is_valid:
                collected[field_name] = user_input
                break
            else:
                await cl.Message(content=f"Invalid input: {error_message}").send()

    # Step 4: Ask about optional fields
    optional_fields = stanza_info.get("optional", {})
    if optional_fields:
        # Show what's available
        opt_list = "\n".join(
            f"- `{name}` — {desc} (default: `{default}`)"
            for name, (default, desc) in optional_fields.items()
        )

        res = await cl.AskActionMessage(
            content=f"**Optional settings available:**\n\n{opt_list}\n\nWould you like to customize any optional settings?",
            actions=[
                cl.Action(name="build_config_opt", label="Yes, customize", payload={"customize": True}),
                cl.Action(name="build_config_opt", label="No, use defaults", payload={"customize": False}),
            ],
        ).send()

        if res and res.get("payload", {}).get("customize"):
            for name, (default, desc) in optional_fields.items():
                while True:
                    res = await cl.AskUserMessage(
                        content=f"**{name}** — {desc}\n(default: `{default}`, press Enter/type `skip` to use default):",
                        timeout=60,
                    ).send()
                    if not res:
                        break

                    val = res["output"].strip()
                    if not val or val.lower() == "skip":
                        break

                    is_valid, error_message = validate_user_input(val, name)
                    if is_valid:
                        collected[name] = val
                        break
                    else:
                        await cl.Message(content=f"Invalid input: {error_message}").send()

    # Step 5: Generate the configuration
    output = _generate_conf_output(conf_type, stanza_type, stanza_info, collected)

    await cl.Message(
        content=f"**Generated {conf_type} stanza:**\n\n```ini\n{output}\n```\n\n"
        f"Copy this into your `{conf_type}` file in the appropriate app directory "
        f"(e.g., `$SPLUNK_HOME/etc/apps/your_app/local/{conf_type}`).",
    ).send()


def _generate_conf_output(
    conf_type: str,
    stanza_type: str,
    stanza_info: Dict[str, Any],
    collected: Dict[str, str],
) -> str:
    """Generate the .conf stanza text from collected values."""
    lines: List[str] = []

    # Build stanza header
    if stanza_type == "monitor":
        path = collected.pop("path", "/var/log/myapp")
        lines.append(f"[monitor://{path}]")
    elif stanza_type == "tcp":
        port = collected.pop("port", "514")
        lines.append(f"[tcp://{port}]")
    elif stanza_type == "udp":
        port = collected.pop("port", "514")
        lines.append(f"[udp://{port}]")
    elif stanza_type == "script":
        script_path = collected.pop("script_path", "/opt/scripts/myscript.sh")
        lines.append(f"[script://{script_path}]")
        if "interval" in collected:
            lines.append(f"interval = {collected.pop('interval')}")
    elif stanza_type == "http":
        lines.append("[http]")
    elif stanza_type == "sourcetype":
        name = collected.pop("sourcetype_name", "my_sourcetype")
        lines.append(f"[{name}]")
    elif stanza_type in ("extraction", "lookup", "routing"):
        name = collected.pop("stanza_name", "my_transform")
        lines.append(f"[{name}]")
        if stanza_type == "lookup" and "filename" in collected:
            lines.append(f"filename = {collected.pop('filename')}")
    else:
        lines.append(f"[{stanza_type}]")

    # Add all collected key-value pairs
    for key, value in collected.items():
        if value:
            lines.append(f"{key} = {value}")

    return "\n".join(lines)
