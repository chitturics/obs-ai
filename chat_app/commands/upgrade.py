"""
/upgrade command handler — Check Splunk app/TA/ES/ITSI/UF upgrade readiness.

Usage:
    /upgrade                         — Show upgrade readiness summary
    /upgrade <app_name> <cluster>    — Analyze specific app on a cluster
    /upgrade es [cluster]            — Enterprise Security upgrade analysis
    /upgrade itsi [cluster]          — ITSI upgrade analysis
    /upgrade uf [cluster]            — Universal Forwarder upgrade check
"""
import logging

import chainlit as cl

logger = logging.getLogger(__name__)

# Default cluster names used when no cluster is specified
_DEFAULT_ES_CLUSTER = "cluster-es"
_DEFAULT_ITSI_CLUSTER = "cluster-itsi"
_DEFAULT_CLUSTER = "cluster-search"


async def upgrade_command(args: str):
    """Route /upgrade to the appropriate upgrade readiness handler."""
    parts = args.strip().split() if args.strip() else []

    # Determine mode from first argument
    if not parts:
        await _show_upgrade_summary()
        return

    mode = parts[0].lower()

    if mode == "es":
        cluster = parts[1] if len(parts) > 1 else _DEFAULT_ES_CLUSTER
        await _analyze_es(cluster)
    elif mode == "itsi":
        cluster = parts[1] if len(parts) > 1 else _DEFAULT_ITSI_CLUSTER
        await _analyze_itsi(cluster)
    elif mode == "uf":
        cluster = parts[1] if len(parts) > 1 else _DEFAULT_CLUSTER
        await _analyze_uf(cluster)
    elif len(parts) >= 2:
        app_name = parts[0]
        cluster = parts[1]
        await _analyze_app(app_name, cluster)
    else:
        # Single arg: treat as app name on default cluster
        await _analyze_app(parts[0], _DEFAULT_CLUSTER)


async def _show_upgrade_summary():
    """Display a general upgrade readiness overview."""
    lines = [
        "**Splunk Upgrade Readiness**",
        "",
        "Usage: `/upgrade <app_or_mode> [cluster]`",
        "",
        "**Modes:**",
        "| Mode | Example | Description |",
        "|------|---------|-------------|",
        "| `es [cluster]` | `/upgrade es cluster-es` | Enterprise Security upgrade analysis |",
        "| `itsi [cluster]` | `/upgrade itsi cluster-itsi` | ITSI upgrade analysis |",
        "| `uf [cluster]` | `/upgrade uf cluster-search` | Universal Forwarder upgrade check |",
        "| `<app> <cluster>` | `/upgrade Splunk_TA_windows cluster-search` | App/TA readiness |",
        "",
        "**MCP Tools Available:**",
        "- `obsai_upgrade_es` — ES upgrade readiness",
        "- `obsai_upgrade_itsi` — ITSI upgrade readiness",
        "- `obsai_check_upgrade_readiness` — App/TA upgrade readiness",
        "- `obsai_check_dependencies` — Cross-app dependency map",
        "- `obsai_check_cim` — CIM compliance check",
        "",
        "**Admin Console:** Navigate to Admin > Upgrade Readiness for a full dashboard.",
    ]
    await cl.Message(content="\n".join(lines)).send()


async def _analyze_es(cluster: str):
    """Analyze Enterprise Security upgrade readiness."""
    thinking_msg = cl.Message(content=f"Analyzing Enterprise Security upgrade readiness on `{cluster}`...")
    await thinking_msg.send()

    try:
        from chat_app.mcp_tool_handlers_ext2 import _handle_upgrade_es
        result = await _handle_upgrade_es({"cluster": cluster})
        await _format_and_send_upgrade_result(result, "Enterprise Security", cluster)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("upgrade_command ES analysis failed: %s", exc)
        await cl.Message(content=f"ES upgrade analysis encountered an error: `{exc}`").send()


async def _analyze_itsi(cluster: str):
    """Analyze ITSI upgrade readiness."""
    thinking_msg = cl.Message(content=f"Analyzing ITSI upgrade readiness on `{cluster}`...")
    await thinking_msg.send()

    try:
        from chat_app.mcp_tool_handlers_ext2 import _handle_upgrade_itsi
        result = await _handle_upgrade_itsi({"cluster": cluster})
        await _format_and_send_upgrade_result(result, "ITSI", cluster)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("upgrade_command ITSI analysis failed: %s", exc)
        await cl.Message(content=f"ITSI upgrade analysis encountered an error: `{exc}`").send()


async def _analyze_uf(cluster: str):
    """Analyze Universal Forwarder upgrade readiness."""
    thinking_msg = cl.Message(content=f"Checking Universal Forwarder upgrade readiness on `{cluster}`...")
    await thinking_msg.send()

    try:
        from chat_app.mcp_tool_handlers_ext import _handle_check_upgrade_readiness
        result = await _handle_check_upgrade_readiness({
            "app_name": "universalforwarder",
            "cluster": cluster,
            "run_cim_check": False,
        })
        await _format_and_send_upgrade_result(result, "Universal Forwarder", cluster)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("upgrade_command UF analysis failed: %s", exc)
        await cl.Message(content=f"UF upgrade analysis encountered an error: `{exc}`").send()


async def _analyze_app(app_name: str, cluster: str):
    """Analyze a specific app or TA upgrade readiness."""
    thinking_msg = cl.Message(content=f"Analyzing upgrade readiness for `{app_name}` on `{cluster}`...")
    await thinking_msg.send()

    try:
        from chat_app.mcp_tool_handlers_ext import _handle_check_upgrade_readiness
        result = await _handle_check_upgrade_readiness({
            "app_name": app_name,
            "cluster": cluster,
            "run_cim_check": True,
        })
        await _format_and_send_upgrade_result(result, app_name, cluster)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("upgrade_command app analysis failed: %s", exc)
        await cl.Message(content=f"Upgrade analysis encountered an error: `{exc}`").send()


async def _format_and_send_upgrade_result(result: dict, label: str, cluster: str):
    """Format and display an upgrade readiness result."""
    if not result.get("success"):
        error_msg = result.get("error", "Unknown error")
        guidance = result.get("guidance", "")
        lines = [
            f"**{label} Upgrade Readiness — `{cluster}`**",
            "",
            f"Status: upgrade_readiness package not available",
            f"Error: `{error_msg}`",
        ]
        if guidance:
            lines += ["", "**Manual Checklist:**", ""]
            lines += [f"  {line}" for line in guidance.split("\n") if line.strip()]
        await cl.Message(content="\n".join(lines)).send()
        return

    lines = [
        f"**{label} Upgrade Readiness — `{cluster}`**",
        "",
    ]

    baseline = result.get("baseline")
    if baseline:
        if isinstance(baseline, dict):
            lines.append("**Baseline Scan:**")
            for key, value in list(baseline.items())[:8]:
                lines.append(f"- {key}: `{value}`")
            lines.append("")
        else:
            lines += ["**Baseline:**", str(baseline)[:500], ""]

    diff = result.get("conf_diff")
    if diff:
        lines.append("**Configuration Changes Detected** — review before upgrading")
        lines.append("")

    impact = result.get("impact")
    if impact:
        lines.append("**Impact Analysis:**")
        if isinstance(impact, dict):
            for key, value in list(impact.items())[:5]:
                lines.append(f"- {key}: `{value}`")
        else:
            lines.append(str(impact)[:300])
        lines.append("")

    cim = result.get("cim_compliance") or result.get("es_readiness") or result.get("itsi_readiness")
    if cim:
        lines.append("**Readiness Check:**")
        if isinstance(cim, dict):
            for key, value in list(cim.items())[:5]:
                lines.append(f"- {key}: `{value}`")
        else:
            lines.append(str(cim)[:300])
        lines.append("")

    lines += [
        "**Next Steps:**",
        "- Review conf diffs before upgrading",
        "- Run `/upgrade <app> <cluster>` for per-app analysis",
        "- See Admin > Upgrade Readiness for full dashboard",
    ]

    await cl.Message(content="\n".join(lines)).send()
