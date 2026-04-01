"""
App Config — Static configuration constants and chat profile definitions.

Extracted from app.py to keep that file under 600 lines.
Imported by app.py and re-exported for backward compatibility.
"""
import json
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Starter options — shown in the Chainlit chat start screen
# ---------------------------------------------------------------------------

STARTER_OPTIONS = [
    {
        "label": "Admin Console & Settings",
        "message": (
            "**Admin & Management:**\n"
            "- `/admin` -- Open admin console with config editor, user management\n"
            "- `/config` -- View or change session settings\n"
            "- `/health` -- Run health checks on all services\n"
            "- `/stats` -- View usage statistics and metrics"
        ),
    },
    {
        "label": "Knowledge Management",
        "message": (
            "**Knowledge Management Examples:**\n"
            "- Index Splunk documentation (URLs or files)\n"
            "- Add conf/spec files to shared knowledge base\n"
            "- Upload custom runbooks or procedures"
        ),
    },
    {
        "label": "Configuration",
        "message": (
            "**Configuration Examples:**\n"
            "- Explain inputs.conf monitor stanza parameters\n"
            "- Show props.conf line-breaking configuration\n"
            "- Provide transforms.conf field extraction example"
        ),
    },
    {
        "label": "Troubleshooting",
        "message": (
            "**Troubleshooting Examples:**\n"
            "- Events not breaking correctly - props.conf check\n"
            "- Monitor input not ingesting - inputs.conf validation\n"
            "- CIM datamodel acceleration issues"
        ),
    },
]


# ---------------------------------------------------------------------------
# Source-to-URL mapping
# ---------------------------------------------------------------------------

def map_source_to_url(source: str, documents_root: str, docs_base_url: str) -> str:
    """Maps a file path to a public URL."""
    if not source or not source.startswith("file://"):
        return source
    file_path = source[7:]
    if file_path.startswith('/app/public/'):
        return f"/public/{file_path.split('/public/', 1)[-1]}"
    if file_path.startswith(documents_root):
        return f"{docs_base_url}/{file_path.split(documents_root, 1)[-1]}"
    return source


# ---------------------------------------------------------------------------
# Static context loader
# ---------------------------------------------------------------------------

def load_static_context(base_dir: str) -> List[str]:
    """Load static context from context.json."""
    ctx_file = Path(base_dir) / "context.json"
    if not ctx_file.exists():
        return []
    try:
        data = json.loads(ctx_file.read_text(encoding="utf-8"))
        notes = []
        if desc := data.get("description"):
            notes.append(str(desc))
        for note in data.get("notes", []):
            if note:
                notes.append(str(note))
        return notes
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        logger.warning(f"Failed to load context.json: {exc}")
        return []


# ---------------------------------------------------------------------------
# Chat profile definitions
# ---------------------------------------------------------------------------

def build_chat_profiles() -> list:
    """Build and return the list of Chainlit ChatProfile objects."""
    try:
        from chainlit.types import ChatProfile
    except ImportError:
        from chainlit import ChatProfile

    return [
        ChatProfile(
            name="general",
            markdown_description=(
                "**General Splunk Assistant**\n\n"
                "All-purpose help for any Splunk question. Automatically "
                "detects if your query is about configs, SPL, troubleshooting, "
                "or your organization and routes to the best specialist.\n\n"
                "**Best for:** Getting started, mixed questions, general guidance\n\n"
                "**Try:** \"How do I use the stats command?\", \"Show me my saved searches\""
            ),
            icon="/public/avatars/generic_assistant.svg",
            default=True,
        ),
        ChatProfile(
            name="spl_expert",
            markdown_description=(
                "**SPL Query Expert**\n\n"
                "Deep mastery of 173+ SPL commands, query optimization, "
                "tstats, data models, CIM compliance, and search performance tuning.\n\n"
                "**Best for:** Writing queries, optimizing searches, stats/timechart help, "
                "understanding command syntax\n\n"
                "**Try:** \"Optimize: index=main | stats count by host\", "
                "\"When should I use tstats vs stats?\""
            ),
            icon="/public/avatars/spl_expert.svg",
        ),
        ChatProfile(
            name="config_helper",
            markdown_description=(
                "**Configuration Expert**\n\n"
                "Authoritative reference for Splunk .conf file syntax, .spec file options, "
                "stanza structure, and best practices from official docs.\n\n"
                "**Best for:** inputs.conf setup, props.conf syntax, transforms.conf rules, "
                "any .conf file questions\n\n"
                "**Try:** \"What are all the options for inputs.conf monitor stanzas?\", "
                "\"Build a props.conf stanza for JSON parsing\""
            ),
            icon="/public/avatars/config_helper.svg",
        ),
        ChatProfile(
            name="troubleshooter",
            markdown_description=(
                "**Troubleshooting Specialist**\n\n"
                "Systematic problem solver for Splunk issues: data ingestion problems, "
                "search performance, indexer errors, parsing failures, and permission issues.\n\n"
                "**Best for:** Error diagnosis, missing data, slow searches, "
                "configuration conflicts\n\n"
                "**Try:** \"My forwarder is not sending data\", "
                "\"Searches are timing out on the search head\""
            ),
            icon="/public/avatars/troubleshooter.svg",
        ),
        ChatProfile(
            name="org_expert",
            markdown_description=(
                "**Organization Expert**\n\n"
                "Deep knowledge of YOUR specific Splunk deployment: apps, saved searches, "
                "inputs, custom configurations, and org setup from your GitHub repo.\n\n"
                "**Best for:** Exploring your configs, understanding your saved searches, "
                "auditing your apps\n\n"
                "**Try:** \"Show my saved searches in org-search\", "
                "\"What inputs.conf stanzas do we have?\""
            ),
            icon="/public/avatars/org_expert.svg",
        ),
        ChatProfile(
            name="cribl_expert",
            markdown_description=(
                "**Cribl Stream/Edge Expert**\n\n"
                "Data pipeline architect for Cribl Stream, Edge, Search, and Lake. "
                "Routes, pipelines, functions, packs, and data routing optimization.\n\n"
                "**Best for:** Data routing, pipeline config, Splunk-to-Cribl migration, "
                "data reduction, event breaking\n\n"
                "**Try:** \"How do I reduce Splunk license cost with Cribl?\", "
                "\"Create a pipeline to mask PII\""
            ),
            icon="/public/avatars/cribl_expert.svg",
        ),
        ChatProfile(
            name="observability_expert",
            markdown_description=(
                "**Observability Engineer**\n\n"
                "Full-stack observability: Splunk metrics (mstats/mcatalog), OpenTelemetry, "
                "distributed tracing, SLI/SLO, Prometheus, and monitoring best practices.\n\n"
                "**Best for:** Metrics queries, OTEL integration, RED/USE methods, "
                "SLO alerting, infrastructure monitoring\n\n"
                "**Try:** \"Write an mstats query for CPU utilization by host\", "
                "\"Set up SLO-based alerting\""
            ),
            icon="/public/avatars/observability_expert.svg",
        ),
    ]
