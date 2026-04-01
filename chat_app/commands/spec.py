"""
/spec command handler -- Look up Splunk .spec file documentation.
"""
import logging
from pathlib import Path

import chainlit as cl

logger = logging.getLogger(__name__)

# Directories to search for spec files (first match wins)
_SPEC_DIRS = [
    Path("/app/ingest_specs"),
    Path("/app/project/ingest_specs"),
    Path(__file__).resolve().parents[2] / "ingest_specs",
]


def _find_spec_file(filename: str) -> "Path | None":
    """Find a spec file by name, trying multiple patterns."""
    # Normalize input
    name = filename.strip().lower()

    # Build candidate filenames
    candidates = [name]
    if not name.endswith(".spec"):
        if name.endswith(".conf"):
            candidates.append(name + ".spec")
        else:
            candidates.append(name + ".conf.spec")
            candidates.append(name + ".spec")

    for spec_dir in _SPEC_DIRS:
        if not spec_dir.is_dir():
            continue
        for candidate in candidates:
            p = spec_dir / candidate
            if p.is_file():
                return p
        # Also try partial match (e.g., "inputs" matches "inputs.conf.spec")
        for p in spec_dir.glob("*.spec"):
            stem = p.name.replace(".conf.spec", "").replace(".spec", "")
            if stem == name:
                return p
    return None


def _list_available_specs() -> list[str]:
    """List all available spec files."""
    specs = set()
    for spec_dir in _SPEC_DIRS:
        if not spec_dir.is_dir():
            continue
        for p in spec_dir.glob("*.spec"):
            specs.add(p.name.replace(".conf.spec", "").replace(".spec", ""))
    return sorted(specs)


async def spec_command(filename: str):
    """Look up a Splunk spec file and display its contents."""
    if not filename or not filename.strip():
        specs = _list_available_specs()
        if specs:
            lines = ["**Available Spec Files:**\n"]
            # Group in columns
            for i in range(0, len(specs), 4):
                row = specs[i:i + 4]
                lines.append("  ".join(f"`{s}`" for s in row))
            lines.append("\n**Usage:** `/spec <name>` (e.g., `/spec inputs`)")
            await cl.Message(content="\n".join(lines)).send()
        else:
            await cl.Message(
                content="No spec files found.\n\n**Usage:** `/spec <filename>`"
            ).send()
        return

    query = filename.strip()

    # Handle "list" subcommand
    if query.lower() in ("list", "ls", "all"):
        specs = _list_available_specs()
        if specs:
            lines = ["**Available Spec Files** ({} total):\n".format(len(specs))]
            for s in specs:
                lines.append(f"- `{s}.conf.spec`")
            await cl.Message(content="\n".join(lines)).send()
        else:
            await cl.Message(content="No spec files found.").send()
        return

    spec_path = _find_spec_file(query)
    if not spec_path:
        specs = _list_available_specs()
        # Fuzzy match suggestions
        suggestions = [s for s in specs if query.lower() in s.lower()]
        msg = f"Spec file not found: `{query}`"
        if suggestions:
            msg += "\n\n**Did you mean:**\n" + "\n".join(f"- `/spec {s}`" for s in suggestions[:8])
        else:
            msg += "\n\n**Usage:** `/spec <name>` (e.g., `/spec inputs`, `/spec props`)"
        await cl.Message(content=msg).send()
        return

    # Read the file
    try:
        content = spec_path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        await cl.Message(content=f"Error reading `{spec_path.name}`: {e}").send()
        return

    # Truncate if too long for a single message
    max_chars = 12000
    truncated = False
    if len(content) > max_chars:
        content = content[:max_chars]
        truncated = True

    header = f"**{spec_path.name}**\n\n"
    footer = ""
    if truncated:
        footer = "\n\n*... (truncated -- file is too large to display in full)*"

    await cl.Message(
        content=f"{header}```ini\n{content}\n```{footer}"
    ).send()
    logger.info(f"[SPEC] Displayed {spec_path.name} ({len(content)} chars)")
