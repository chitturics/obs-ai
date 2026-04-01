"""
Slash command router for the Splunk Assistant.

Routes user commands (e.g. /help, /search, /splunk) to their
respective handler modules in ``chat_app.commands.*``.

Adding a new command:
    1. Create ``chat_app/commands/my_command.py`` with an async handler function.
    2. Import it here and add a routing entry in ``handle_slash_command()``.
    3. Add the command to ``chat_app/commands/help.py``.
    4. Register the command button in ``chat_lifecycle.py`` -> ``on_chat_start()``.
"""
import logging
from typing import List, Dict

import chainlit as cl

# -- Command handler imports --------------------------------------------------
from chat_app.commands.help import help_command
from chat_app.commands.search import search_command
from chat_app.commands.spec import spec_command
from chat_app.commands.config import config_command
from chat_app.commands.stats import stats_command
from chat_app.commands.clear import clear_command
from chat_app.commands.profile import profile_command
from chat_app.commands.analyze_searches import analyze_searches_command
from chat_app.commands.check_configs import check_configs_command
from chat_app.commands.run import run_command
from chat_app.commands.create_alert import create_alert_command
from chat_app.commands.mcp import mcp_command
from chat_app.commands.build_config import build_config_command
from chat_app.commands.health import health_command
from chat_app.commands.splunk_admin import splunk_admin_command
from chat_app.commands.explain import explain_command
from chat_app.commands.learn import learn_command
from chat_app.commands.ingest import ingest_command
from chat_app.commands.tutorial import tutorial_command
from chat_app.commands.version import version_command
from chat_app.commands.admin import admin_command
from chat_app.commands.skill_cmd import skill_command
from chat_app.commands.kg_cmd import kg_command
from chat_app.commands.doc import doc_command
from chat_app.commands.upgrade import upgrade_command

logger = logging.getLogger(__name__)


def _format_results_as_table(results: List[Dict]) -> str:
    """Format a list of dicts as a Markdown table (max 20 rows)."""
    if not results:
        return ""
    headers = list(results[0].keys())
    header_line = "| " + " | ".join(headers) + " |"
    separator = "| " + " | ".join("---" for _ in headers) + " |"
    rows = [
        "| " + " | ".join(str(row.get(h, "")) for h in headers) + " |"
        for row in results[:20]
    ]
    return "\n".join([header_line, separator] + rows)


# -- Command routing ----------------------------------------------------------

# Map of command name -> (handler, needs_args, needs_kwargs)
# This makes it easy to add new commands without editing a long if-chain.
_COMMAND_TABLE = {
    "/help":             (help_command, True, False),
    "/search":           (search_command, True, True),
    "/spec":             (spec_command, True, False),
    "/config":           (config_command, True, False),
    "/stats":            (stats_command, False, False),
    "/clear":            (clear_command, False, False),
    "/profile":          (profile_command, False, False),
    "/analyze_searches": (analyze_searches_command, False, False),
    "/check_configs":    (check_configs_command, False, False),
    "/run":              (run_command, True, False),
    "/create_alert":     (create_alert_command, False, False),
    "/mcp":              (mcp_command, True, True),
    "/build_config":     (build_config_command, True, False),
    "/build-config":     (build_config_command, True, False),
    "/health":           (health_command, False, False),
    "/status":           (health_command, False, False),
    "/splunk":           (splunk_admin_command, True, False),
    "/explain":          (explain_command, True, False),
    "/learn":            (learn_command, True, False),
    "/ingest":           (ingest_command, True, False),
    "/tutorial":         (tutorial_command, True, False),
    "/version":          (version_command, False, False),
    "/ver":              (version_command, False, False),
    "/about":            (version_command, False, False),
    "/admin":            (admin_command, True, False),
    "/skill":            (skill_command, True, False),
    "/kg":               (kg_command, True, False),
    "/doc":              (doc_command, True, False),
    "/upgrade":          (upgrade_command, True, False),
}


async def handle_slash_command(command: str, *, vector_store=None, engine=None):
    """Route a slash command string to the appropriate handler.

    Args:
        command: Full command string (e.g. "/search stats command").
        vector_store: Optional vector store instance for search commands.
        engine: Optional SQLAlchemy engine for MCP token persistence.
    """
    parts = command.split(maxsplit=1)
    cmd = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    entry = _COMMAND_TABLE.get(cmd)
    if entry is None:
        await cl.Message(
            content=f"Unknown command: `{cmd}`\n\nType `/help` for available commands."
        ).send()
        return

    handler, needs_args, needs_kwargs = entry

    # Track every command execution for observability
    try:
        from chat_app.execution_tracker import track_execution_ctx, ExecCategory
        async with track_execution_ctx(ExecCategory.COMMAND, cmd, input_preview=args[:100]) as trace:
            if needs_args and needs_kwargs:
                await handler(args, vector_store=vector_store, engine=engine)
            elif needs_args:
                await handler(args)
            else:
                await handler()
            trace.success = True
    except ImportError:
        # Fallback: execute without tracking
        if needs_args and needs_kwargs:
            await handler(args, vector_store=vector_store, engine=engine)
        elif needs_args:
            await handler(args)
        else:
            await handler()
