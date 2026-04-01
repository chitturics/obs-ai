"""
/splunk command handler — Splunk administration commands.

Sub-commands:
    /splunk info       — Server info and version
    /splunk license    — License usage
    /splunk apps       — List installed apps
    /splunk indexes    — List indexes with sizes
    /splunk users      — List users and roles
    /splunk inputs     — List data inputs
    /splunk messages   — System messages/warnings
    /splunk forwarders — Connected forwarders
"""

from __future__ import annotations

import logging
from typing import Optional

import chainlit as cl

logger = logging.getLogger(__name__)

# Cached client — reused across commands within the same process
_cached_client = None


def _get_client():
    """Get a connected SplunkClient, reusing a cached instance if available."""
    global _cached_client
    if _cached_client is not None and _cached_client.service is not None:
        return _cached_client

    try:
        from chat_app.splunk_client import SplunkClient
        sc = SplunkClient()
        sc.connect()
        _cached_client = sc
        return sc
    except Exception as exc:
        _cached_client = None
        return str(exc)


def _table(rows: list[dict], columns: Optional[list[str]] = None) -> str:
    """Build a markdown table from a list of dicts."""
    if not rows:
        return "_No results._"
    cols = columns or list(rows[0].keys())
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join("---" for _ in cols) + " |"
    body = "\n".join(
        "| " + " | ".join(str(r.get(c, ""))[:80] for c in cols) + " |"
        for r in rows[:30]
    )
    return f"{header}\n{sep}\n{body}"


async def splunk_admin_command(args: str = "") -> None:
    """Route /splunk sub-commands."""
    parts = args.strip().split(maxsplit=1)
    sub = parts[0].lower() if parts else "help"

    if sub == "help" or not sub:
        await cl.Message(content="""**Splunk Administration Commands**

| Command | Description |
|---------|-------------|
| `/splunk info` | Server version and roles |
| `/splunk license` | License usage summary |
| `/splunk apps` | List installed apps |
| `/splunk indexes` | List indexes with sizes |
| `/splunk users` | List users and roles |
| `/splunk inputs [type]` | List data inputs (monitor/tcp/udp/http) |
| `/splunk messages` | System messages and warnings |
| `/splunk forwarders` | Connected forwarders |
""").send()
        return

    sc = _get_client()
    if isinstance(sc, str):
        await cl.Message(
            content=f"Could not connect to Splunk: `{sc}`\n\n"
            "Ensure `SPLUNK_HOST`, `SPLUNK_PORT`, and credentials are configured."
        ).send()
        return

    if sub == "info":
        info = sc.get_server_info()
        lines = ["**Splunk Server Info**\n"]
        for k, v in info.items():
            if isinstance(v, list):
                v = ", ".join(v)
            lines.append(f"- **{k}:** {v}")
        await cl.Message(content="\n".join(lines)).send()

    elif sub == "license":
        lic = sc.get_license_usage()
        if not lic:
            await cl.Message(content="Could not retrieve license info.").send()
            return
        bar_len = 20
        filled = int(bar_len * lic["usage_percent"] / 100)
        bar = "█" * filled + "░" * (bar_len - filled)
        await cl.Message(content=f"""**License Usage**

- **Quota:** {lic['quota_gb']} GB
- **Used:** {lic['used_gb']} GB ({lic['usage_percent']}%)
- **Usage:** `[{bar}]`
""").send()

    elif sub == "apps":
        apps = sc.list_apps()
        await cl.Message(
            content=f"**Installed Apps** ({len(apps)})\n\n"
            + _table(apps, ["name", "label", "version", "visible", "disabled"])
        ).send()

    elif sub == "indexes":
        indexes = sc.list_indexes()
        await cl.Message(
            content=f"**Indexes** ({len(indexes)})\n\n"
            + _table(indexes, ["name", "total_event_count", "current_db_size_mb",
                               "max_total_data_size_mb", "datatype", "disabled"])
        ).send()

    elif sub == "users":
        users = sc.list_users()
        for u in users:
            u["roles"] = ", ".join(u.get("roles", []))
        await cl.Message(
            content=f"**Users** ({len(users)})\n\n"
            + _table(users, ["name", "realname", "email", "roles", "type"])
        ).send()

    elif sub == "inputs":
        kind = parts[1].strip().lower() if len(parts) > 1 else "all"
        inputs = sc.list_inputs(kind=kind)
        await cl.Message(
            content=f"**Data Inputs** (type={kind}, count={len(inputs)})\n\n"
            + _table(inputs, ["type", "name", "index", "sourcetype", "disabled"])
        ).send()

    elif sub == "messages":
        msgs = sc.get_messages()
        if not msgs:
            await cl.Message(content="No system messages.").send()
            return
        lines = ["**System Messages**\n"]
        for m in msgs:
            sev = m["severity"].upper()
            lines.append(f"- [{sev}] **{m['name']}**: {m['message'][:200]}")
        await cl.Message(content="\n".join(lines)).send()

    elif sub == "forwarders":
        fwds = sc.list_forwarders()
        if not fwds:
            await cl.Message(
                content="No forwarder data. This requires deployment server role."
            ).send()
            return
        await cl.Message(
            content=f"**Connected Forwarders** ({len(fwds)})\n\n"
            + _table(fwds)
        ).send()

    else:
        await cl.Message(
            content=f"Unknown sub-command: `{sub}`\n\nType `/splunk help` for available commands."
        ).send()
