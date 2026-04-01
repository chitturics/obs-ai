"""
/mcp command handler.
"""
import logging
from typing import Optional

import chainlit as cl
from mcp_registry import list_servers as list_mcp_servers, get_server as get_mcp_server
from feedback_logger import (
    save_mcp_token, delete_mcp_token,
)
from helper import current_username

logger = logging.getLogger(__name__)


async def mcp_command(args: str, *, engine=None):
    """Manage MCP servers and per-user tokens."""
    servers = list_mcp_servers()
    tokens = cl.user_session.get("mcp_tokens", {})

    if not args or args.strip().lower() == "status":
        if not servers:
            await cl.Message(
                content="**MCP**\n\nNo admin-provided MCP servers are configured."
            ).send()
            return

        lines = ["# MCP Servers"]
        for srv in servers:
            name = srv["name"]
            auth_scheme = srv.get("auth_scheme", "none")
            target = srv.get("endpoint") or srv.get("command") or "configured endpoint"
            has_token = name in tokens
            token_state = "token saved" if has_token else "token required"
            lines.append(f"- **{name}** ({auth_scheme}) -> `{target}` -- {token_state}")

        lines.append("\nUse `/mcp token <server>` to add a token, or `/mcp logout <server>` to remove it.")
        await cl.Message(content="\n".join(lines)).send()
        return

    parts = args.split(maxsplit=1)
    action = parts[0].lower()
    target = parts[1].strip() if len(parts) > 1 else ""

    if action in ["token", "auth", "login"]:
        if not target:
            await cl.Message(
                content="**Missing server name.**\n\nUsage: `/mcp token <server>`"
            ).send()
            return
        await _request_and_store_mcp_token(target, engine=engine)
        return

    if action in ["logout", "clear"]:
        if not target:
            await cl.Message(
                content="**Missing server name.**\n\nUsage: `/mcp logout <server>`"
            ).send()
            return
        if not get_mcp_server(target):
            await cl.Message(
                content=f"**Unknown MCP server:** `{target}`."
            ).send()
            return
        await _clear_mcp_token(target, engine=engine)
        await cl.Message(content=f"Token removed for **{target}**.").send()
        return

    await cl.Message(
        content="**Unknown MCP action.**\n\n"
                "Use `/mcp`, `/mcp status`, `/mcp token <server>`, or `/mcp logout <server>`."
    ).send()


async def _request_and_store_mcp_token(server_name: str, *, engine=None) -> Optional[str]:
    """Prompt user for a token for the given MCP server and persist it."""
    server = get_mcp_server(server_name)
    if not server or not server.get("enabled", True):
        await cl.Message(
            content=f"**Unknown MCP server:** `{server_name}`. Ask your admin to enable it."
        ).send()
        return None

    auth_scheme = server.get("auth_scheme", "bearer").lower()
    hints = server.get("auth_hints", {}) or {}
    target = server.get("endpoint") or server.get("command") or "configured endpoint"

    prompt = [
        f"**{server_name}** requires a `{auth_scheme}` token.",
        f"Target: `{target}`",
    ]
    if hints:
        hint_lines = [f"- {k}: {v}" for k, v in hints.items()]
        prompt.append("Hints:")
        prompt.extend(hint_lines)
    prompt.append("\nEnter your token below. It will be stored only for your account.")

    res = await cl.AskUserMessage(
        content="\n".join(prompt),
        timeout=180,
    ).send()

    token = (getattr(res, "content", "") or "").strip() if res else ""
    if not token:
        await cl.Message(content="No token provided. MCP connection not updated.").send()
        return None

    await save_mcp_token(
        engine=engine,
        user_id=current_username(),
        server_name=server_name,
        access_token=token,
        auth_scheme=auth_scheme,
        refresh_token=None,
        expires_at=None,
    )

    tokens = cl.user_session.get("mcp_tokens", {})
    tokens[server_name] = {
        "auth_scheme": auth_scheme,
        "token": token,
    }
    cl.user_session.set("mcp_tokens", tokens)

    await cl.Message(
        content=f"Token saved for **{server_name}** ({auth_scheme})."
    ).send()
    return token


async def _clear_mcp_token(server_name: str, *, engine=None):
    """Remove stored token for a server."""
    await delete_mcp_token(engine, current_username(), server_name)
    tokens = cl.user_session.get("mcp_tokens", {})
    tokens.pop(server_name, None)
    cl.user_session.set("mcp_tokens", tokens)
