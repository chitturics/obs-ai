"""
/doc command — Generate professional documentation from chat.

Usage:
    /doc                          → show help
    /doc <text>                   → generate docs from text snippet
    /doc scan <path>              → scan directory or zip and document it
    /doc format sharepoint <text> → output as SharePoint HTML
    /doc style api-reference <text> → use API reference style

Supports multiple snippets separated by --- (triple dash).
"""
import logging
import chainlit as cl

logger = logging.getLogger(__name__)


async def doc_command(args: str):
    """Generate professional documentation."""
    args = args.strip()

    if not args:
        return await _doc_help()

    lower = args.lower()

    # /doc scan <path>
    if lower.startswith("scan "):
        return await _doc_scan(args[5:].strip())

    # /doc format sharepoint <text>
    if lower.startswith("format sharepoint "):
        return await _doc_from_text(args[18:].strip(), format="sharepoint")

    if lower.startswith("format markdown "):
        return await _doc_from_text(args[16:].strip(), format="markdown")

    # /doc style <style> <text>
    if lower.startswith("style "):
        parts = args[6:].split(" ", 1)
        if len(parts) == 2:
            return await _doc_from_text(parts[1].strip(), style=parts[0].strip())

    # Default: generate from text
    return await _doc_from_text(args)


async def _doc_help():
    """Show documentation generator help."""
    help_text = """**Documentation Generator**

Generate professional documentation in Markdown or SharePoint format.

**Usage:**
- `/doc <text>` — Generate docs from text snippet(s)
- `/doc scan <directory>` — Scan a directory and document all files
- `/doc scan <file.zip>` — Extract and document a zip file
- `/doc format sharepoint <text>` — Output as SharePoint HTML
- `/doc style api-reference <text>` — Use API reference style

**Multiple sections:** Separate with `---` (triple dash):
```
/doc First section content
---
Second section about configuration
---
Third section with examples
```

**Styles:** `technical` (default), `user-friendly`, `api-reference`
**Formats:** `markdown` (default), `sharepoint`"""

    await cl.Message(content=help_text).send()


async def _doc_from_text(text: str, format: str = "markdown", style: str = "technical"):
    """Generate documentation from text input."""
    from chat_app.doc_generator import get_doc_generator

    if not text:
        await cl.Message(content="Please provide text to document. Use `/doc` for help.").send()
        return

    gen = get_doc_generator()

    # Split on --- for multiple sections
    snippets = text.split("\n---\n") if "\n---\n" in text else [text]

    # Infer title from first line
    first_line = snippets[0].strip().split("\n")[0][:60]
    title = first_line if len(first_line) > 5 else "Documentation"

    await cl.Message(content=f"Generating {format} documentation ({style} style)...").send()

    result = gen.from_snippets(
        snippets=snippets,
        title=title,
        format=format,
        style=style,
    )

    # For SharePoint, wrap in a code block so HTML is visible
    if format == "sharepoint":
        content = f"**SharePoint HTML Generated** ({len(result.content)} chars)\n\n```html\n{result.content[:3000]}\n```"
        if len(result.content) > 3000:
            content += f"\n\n*Output truncated. Full document: {len(result.content)} chars.*"
    else:
        content = result.content

    await cl.Message(content=content).send()


async def _doc_scan(path: str):
    """Scan a directory or zip file and generate documentation."""
    from chat_app.doc_generator import get_doc_generator
    from pathlib import Path

    if not path:
        await cl.Message(content="Please provide a directory or zip file path.").send()
        return

    target = Path(path)
    gen = get_doc_generator()

    await cl.Message(content=f"Scanning `{path}`...").send()

    if target.is_dir():
        result = gen.from_directory(str(target), title=f"Documentation: {target.name}")
    elif target.exists() and path.endswith(".zip"):
        result = gen.from_zip(str(target), title=f"Documentation: {target.name}")
    else:
        await cl.Message(content=f"Path not found or not a valid directory/zip: `{path}`").send()
        return

    meta = result.metadata
    stats = ""
    if "files_analyzed" in meta:
        langs = ", ".join(meta.get("languages", []))
        stats = f"\n\n*Analyzed {meta['files_analyzed']} files, {meta.get('total_lines', 0):,} lines ({langs})*"

    warnings = ""
    if result.warnings:
        warnings = f"\n\n**Warnings:** {', '.join(result.warnings)}"

    await cl.Message(content=result.content + stats + warnings).send()
