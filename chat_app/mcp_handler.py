"""
MCP (Model Context Protocol) handlers for the Splunk Assistant.

Import this module in ``app.py`` so that the ``@cl.on_mcp_connect`` and
``@cl.on_mcp_disconnect`` decorators are registered with Chainlit at startup.
"""
import asyncio
import logging
import chainlit as cl

logger = logging.getLogger(__name__)

__all__ = ["on_mcp_connect", "on_mcp_disconnect", "execute_mcp_tool"]

def execute_mcp_tool(server_name: str, tool_name: str, params: dict = None) -> str:
    """Execute an MCP tool on a connected server.

    Looks up the named server in the current Chainlit user session's MCP
    connections and calls the specified tool.  Returns the tool output as a
    string, or ``None`` if the server/tool is unavailable.
    """
    import concurrent.futures
    params = params or {}
    try:
        mcp_sessions = cl.user_session.get("mcp_sessions", {})
        session = mcp_sessions.get(server_name)
        if not session:
            logger.debug("[MCP] No active session for server '%s'", server_name)
            return None

        # Chainlit MCP sessions expose a call_tool coroutine

        async def _call():
            result = await session.call_tool(tool_name, params)
            if hasattr(result, "content"):
                return str(result.content)
            if isinstance(result, dict):
                return str(result.get("content", result))
            return str(result)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _call()).result(timeout=30)
        else:
            return asyncio.run(_call())

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[MCP] execute_mcp_tool failed for %s/%s: %s", server_name, tool_name, exc)
        return None


@cl.on_mcp_connect
async def on_mcp_connect(connection, session):
    logger.info(f"[MCP] Connected to: {connection.name}")
    mcp_sessions = cl.user_session.get("mcp_sessions", {})
    mcp_sessions[connection.name] = session
    cl.user_session.set("mcp_sessions", mcp_sessions)
    await cl.Message(content=f"**MCP Connected:** {connection.name}", author="System").send()


@cl.on_mcp_disconnect
async def on_mcp_disconnect(name, session):
    logger.info(f"[MCP] Disconnected from: {name}")
    mcp_sessions = cl.user_session.get("mcp_sessions", {})
    mcp_sessions.pop(name, None)
    cl.user_session.set("mcp_sessions", mcp_sessions)
    await cl.Message(content=f"**MCP Disconnected:** {name}", author="System").send()
