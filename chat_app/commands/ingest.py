"""
/ingest command — Ingest documents from various sources.

Usage:
  /ingest <file_path>           — Ingest a local file (PDF, HTML, JSON, CSV, etc.)
  /ingest dir <directory_path>  — Ingest all files from a directory
  /ingest sharepoint            — Ingest from configured SharePoint library
  /ingest confluence <space>    — Ingest from a Confluence space
  /ingest status                — Show ingestion statistics
"""
import logging
import chainlit as cl

logger = logging.getLogger(__name__)


async def ingest_command(args: str):
    """Ingest documents from various sources."""
    if not args.strip():
        await cl.Message(content=(
            "**Document Ingestion**\n\n"
            "**Usage:**\n"
            "- `/ingest <file_path>` — Ingest a local file (PDF, HTML, JSON, CSV)\n"
            "- `/ingest dir <directory_path>` — Ingest all files from a directory\n"
            "- `/ingest sharepoint` — Ingest from configured SharePoint library\n"
            "- `/ingest confluence <space_key>` — Ingest from a Confluence space\n"
            "- `/ingest status` — Show ingestion statistics\n\n"
            "**Supported formats:** PDF, HTML, JSON, CSV, YAML, Markdown, Text, .conf, .spec"
        )).send()
        return

    parts = args.strip().split(maxsplit=1)
    subcommand = parts[0].lower()
    sub_args = parts[1] if len(parts) > 1 else ""

    if subcommand == "dir":
        await _ingest_directory(sub_args)
    elif subcommand == "sharepoint":
        await _ingest_sharepoint()
    elif subcommand == "confluence":
        await _ingest_confluence(sub_args)
    elif subcommand == "status":
        await _ingest_status()
    else:
        # Treat as file path
        await _ingest_file(args.strip())


async def _ingest_file(filepath: str):
    """Ingest a single file."""
    msg = await cl.Message(content=f"Ingesting file: `{filepath}`...").send()
    try:
        from chat_app.document_ingestor import ingest_file

        doc = await ingest_file(filepath)
        if doc.error:
            msg.content = f"Ingestion failed: {doc.error}"
        else:
            msg.content = (
                f"**File ingested successfully**\n"
                f"- Source: `{doc.source}`\n"
                f"- Type: {doc.source_type}\n"
                f"- Title: {doc.title}\n"
                f"- Chunks created: {doc.chunk_count}"
            )
        await msg.update()

    except Exception as exc:
        msg.content = f"Error: {exc}"
        await msg.update()


async def _ingest_directory(directory: str):
    """Ingest all files from a directory."""
    if not directory:
        await cl.Message(content="Please specify a directory path: `/ingest dir /path/to/docs`").send()
        return

    msg = await cl.Message(content=f"Ingesting directory: `{directory}`...").send()
    try:
        from chat_app.document_ingestor import ingest_directory

        result = await ingest_directory(directory)

        parts = ["**Directory Ingestion Complete**\n"]
        parts.append(f"- Documents processed: {result.documents_processed}")
        parts.append(f"- Documents skipped: {result.documents_skipped}")
        parts.append(f"- Chunks created: {result.chunks_created}")
        if result.errors:
            parts.append(f"- Errors: {len(result.errors)}")
            for err in result.errors[:5]:
                parts.append(f"  - {err}")

        msg.content = "\n".join(parts)
        await msg.update()

    except Exception as exc:
        msg.content = f"Error: {exc}"
        await msg.update()


async def _ingest_sharepoint():
    """Ingest from SharePoint."""
    msg = await cl.Message(content="Connecting to SharePoint...").send()
    try:
        from chat_app.document_ingestor import SharePointConnector

        connector = SharePointConnector()
        if not connector.is_configured:
            msg.content = (
                "SharePoint is not configured. Set the following environment variables:\n"
                "- `SHAREPOINT_TENANT_ID`\n"
                "- `SHAREPOINT_CLIENT_ID`\n"
                "- `SHAREPOINT_CLIENT_SECRET`\n"
                "- `SHAREPOINT_SITE_URL`"
            )
            await msg.update()
            return

        result = await connector.ingest_library()
        parts = ["**SharePoint Ingestion Complete**\n"]
        parts.append(f"- Documents processed: {result.documents_processed}")
        parts.append(f"- Chunks created: {result.chunks_created}")
        if result.errors:
            parts.append(f"- Errors: {len(result.errors)}")

        msg.content = "\n".join(parts)
        await msg.update()

    except Exception as exc:
        msg.content = f"SharePoint error: {exc}"
        await msg.update()


async def _ingest_confluence(space_key: str):
    """Ingest from Confluence."""
    if not space_key:
        await cl.Message(content="Please specify a Confluence space key: `/ingest confluence MYSPACE`").send()
        return

    msg = await cl.Message(content=f"Connecting to Confluence space '{space_key}'...").send()
    try:
        from chat_app.document_ingestor import ConfluenceConnector

        connector = ConfluenceConnector()
        if not connector.is_configured:
            msg.content = (
                "Confluence is not configured. Set the following environment variables:\n"
                "- `CONFLUENCE_URL`\n"
                "- `CONFLUENCE_USERNAME`\n"
                "- `CONFLUENCE_API_TOKEN`"
            )
            await msg.update()
            return

        result = await connector.ingest_space(space_key)
        parts = ["**Confluence Ingestion Complete**\n"]
        parts.append(f"- Pages processed: {result.documents_processed}")
        parts.append(f"- Chunks created: {result.chunks_created}")
        if result.errors:
            parts.append(f"- Errors: {len(result.errors)}")

        msg.content = "\n".join(parts)
        await msg.update()

    except Exception as exc:
        msg.content = f"Confluence error: {exc}"
        await msg.update()


async def _ingest_status():
    """Show ingestion statistics."""
    try:
        from chat_app.health_monitor import get_internal_metrics
        metrics = get_internal_metrics()
        data = metrics.get_all()

        parts = ["**Ingestion Statistics**\n"]
        parts.append(f"- Documents ingested: {data['counters'].get('documents_ingested', 0)}")
        parts.append(f"- Q&A pairs generated: {data['counters'].get('qa_pairs_generated', 0)}")
        parts.append(f"- Learning cycles: {data['counters'].get('learning_cycles', 0)}")

        await cl.Message(content="\n".join(parts)).send()

    except Exception as exc:
        await cl.Message(content=f"Error: {exc}").send()
