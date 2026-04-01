"""
MCP client utilities — lightweight HTTP-based MCP tool loading and execution.

Connects to MCP servers defined in config.yaml ``mcp_gateway.servers``,
discovers available tools via ``POST /tools/list``, and exposes them as
callable ``MCPTool`` objects that invoke ``POST /tools/call`` at runtime.

Only SSE and Streamable-HTTP transports are supported (stdio is skipped
with a warning).  Auth tokens (bearer / api_key) are injected from per-user
session data when available.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

# MCP JSON-RPC request IDs (monotonic per-process)
_REQ_ID = 0


def _next_id() -> int:
    global _REQ_ID
    _REQ_ID += 1
    return _REQ_ID


# ---------------------------------------------------------------------------
# MCPTool wrapper
# ---------------------------------------------------------------------------

@dataclass
class MCPTool:
    """Lightweight wrapper around a remote MCP tool.

    Attributes:
        name:        Tool name as advertised by the MCP server.
        description: Human-readable description.
        input_schema: JSON Schema for the tool's arguments (if provided).
        server_name: Registry name of the owning MCP server.
        endpoint:    Base URL of the MCP server (SSE / HTTP).
        auth_headers: Pre-built auth headers for requests.
        timeout:     Per-call timeout in seconds.
    """

    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)
    server_name: str = ""
    endpoint: str = ""
    auth_headers: Dict[str, str] = field(default_factory=dict)
    timeout: int = 30

    # ------------------------------------------------------------------
    # Execution interface (matches what tool_executor.execute_tool_call
    # checks for: ainvoke / invoke / __call__)
    # ------------------------------------------------------------------

    async def ainvoke(self, args: Dict[str, Any] | None = None) -> str:
        """Call the tool on the remote MCP server and return the text result."""
        payload = {
            "jsonrpc": "2.0",
            "id": _next_id(),
            "method": "tools/call",
            "params": {
                "name": self.name,
                "arguments": args or {},
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    self.endpoint.rstrip("/") + "/mcp",
                    json=payload,
                    headers={**self.auth_headers, "Content-Type": "application/json"},
                )
                resp.raise_for_status()
                body = resp.json()

                # MCP JSON-RPC: result.content[].text
                result = body.get("result", {})
                content_blocks = result.get("content", [])
                texts = [
                    b.get("text", "")
                    for b in content_blocks
                    if isinstance(b, dict) and b.get("type") == "text"
                ]
                if texts:
                    return "\n".join(texts)

                # Fallback: return raw result
                if result:
                    return json.dumps(result, indent=2)
                return "Tool executed (no output)."

        except httpx.HTTPStatusError as exc:
            logger.error("[MCP] Tool %s HTTP error: %s", self.name, exc)
            return f"MCP tool error: HTTP {exc.response.status_code}"
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            logger.error("[MCP] Tool %s connection failed: %s", self.name, exc)
            return f"MCP tool error: {exc}"
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, AttributeError, json.JSONDecodeError) as exc:
            logger.error("[MCP] Tool %s call failed: %s", self.name, exc)
            return f"MCP tool error: {exc}"

    def invoke(self, args: Dict[str, Any] | None = None) -> str:
        """Sync wrapper (used by tool_executor fallback)."""

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, self.ainvoke(args)).result()
        return asyncio.run(self.ainvoke(args))

    def __repr__(self) -> str:
        return f"MCPTool(name={self.name!r}, server={self.server_name!r})"


# ---------------------------------------------------------------------------
# Tool discovery
# ---------------------------------------------------------------------------

def _build_auth_headers(server: Dict[str, Any], user_token: Optional[str] = None) -> Dict[str, str]:
    """Build HTTP headers for a server's auth scheme."""
    scheme = (server.get("auth_scheme") or "none").lower()
    hints = server.get("auth_hints") or {}

    if scheme == "bearer" and user_token:
        prefix = hints.get("prefix", "Bearer ")
        header_name = hints.get("header", "Authorization")
        return {header_name: f"{prefix}{user_token}"}

    if scheme == "api_key" and user_token:
        header_name = hints.get("header", "X-API-Key")
        return {header_name: user_token}

    return {}


async def _discover_tools(
    server: Dict[str, Any],
    auth_headers: Dict[str, str],
    timeout: int = 30,
    max_retries: int = 2,
) -> List[Dict[str, Any]]:
    """Discover tools from an MCP server via JSON-RPC ``tools/list``.

    Tries the ``/mcp`` endpoint first (Streamable HTTP convention),
    then falls back to ``/sse`` if available.
    """
    endpoint = (server.get("endpoint") or "").rstrip("/")
    if not endpoint:
        return []

    payload = {
        "jsonrpc": "2.0",
        "id": _next_id(),
        "method": "tools/list",
        "params": {},
    }

    urls_to_try = [
        f"{endpoint}/mcp",
        f"{endpoint}",
    ]

    for attempt in range(max_retries + 1):
        for url in urls_to_try:
            try:
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.post(
                        url,
                        json=payload,
                        headers={**auth_headers, "Content-Type": "application/json"},
                    )
                    if resp.status_code == 404:
                        continue
                    resp.raise_for_status()
                    body = resp.json()
                    tools = body.get("result", {}).get("tools", [])
                    logger.info(
                        "[MCP] Discovered %d tools from %s (%s)",
                        len(tools), server["name"], url,
                    )
                    return tools
            except httpx.ConnectError:
                logger.debug("[MCP] %s unreachable at %s (attempt %d)", server["name"], url, attempt + 1)
            except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
                logger.debug("[MCP] %s discovery error at %s: %s", server["name"], url, exc)

    logger.warning("[MCP] Could not discover tools from %s after %d attempts", server["name"], max_retries + 1)
    return []


async def load_mcp_tools_from_registry(
    user_tokens: Optional[Dict[str, str]] = None,
) -> List[MCPTool]:
    """Load tools from all enabled MCP servers in the config registry.

    Args:
        user_tokens: Optional mapping of ``server_name -> access_token``
                     for per-user auth injection.

    Returns:
        List of :class:`MCPTool` objects ready for execution.
    """
    try:
        from mcp_registry import list_servers
    except ImportError:
        from chat_app.mcp_registry import list_servers

    try:
        from chat_app.settings import get_settings
        settings = get_settings()
        timeout = settings.mcp_gateway.connection_timeout
        max_retries = settings.mcp_gateway.max_retries
    except Exception as _exc:  # broad catch — resilience against all failures
        timeout = 30
        max_retries = 2

    servers = list_servers()
    if not servers:
        logger.info("[MCP] No enabled MCP servers in registry")
        return []

    user_tokens = user_tokens or {}
    all_tools: List[MCPTool] = []

    for server in servers:
        transport = (server.get("client_type") or "sse").lower()

        if transport == "stdio":
            logger.info(
                "[MCP] Skipping stdio server %s (HTTP-only mode)", server["name"]
            )
            continue

        endpoint = server.get("endpoint") or ""
        if not endpoint:
            logger.warning("[MCP] Server %s has no endpoint, skipping", server["name"])
            continue

        token = user_tokens.get(server["name"])
        auth_headers = _build_auth_headers(server, token)

        raw_tools = await _discover_tools(server, auth_headers, timeout, max_retries)

        for t in raw_tools:
            tool = MCPTool(
                name=t.get("name", "unknown"),
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
                server_name=server["name"],
                endpoint=endpoint,
                auth_headers=auth_headers,
                timeout=timeout,
            )
            all_tools.append(tool)

    logger.info("[MCP] Loaded %d tools from %d servers", len(all_tools), len(servers))
    return all_tools


# ---------------------------------------------------------------------------
# Backward-compatible wrapper
# ---------------------------------------------------------------------------

def load_splunk_mcp_tools(
    uri: str = "ws://127.0.0.1:8181",
    client_name: str = "splunk-mcp",
) -> List[MCPTool]:
    """Legacy entry point — now delegates to :func:`load_mcp_tools_from_registry`.

    The *uri* and *client_name* parameters are ignored; tool loading is driven
    entirely by the ``mcp_gateway`` section in ``config.yaml``.
    """

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # Called from within an async context at module load — return empty
        # and let bootstrap_mcp_session load tools later.
        logger.info("[MCP] Deferring tool load (async context)")
        return []

    try:
        return asyncio.run(load_mcp_tools_from_registry())
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[MCP] Failed to load tools from registry: %s", exc)
        return []
