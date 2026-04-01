"""Documentation Generator — create professional docs from code, configs, or text.

Supports two primary modes:
1. **Snippet mode**: User provides text, images, comments → professional documentation
2. **Scan mode**: User provides a zip file or directory → comprehensive auto-documentation

Output formats:
- **Markdown** (.md) — clean, structured, ready for GitHub/wikis
- **SharePoint HTML** — styled for SharePoint pages with tables and formatting

Integrates as: Skill, Slash Command (/doc), MCP Tool (obsai_generate_docs),
and Admin API endpoint.

Usage:
    from chat_app.doc_generator import DocGenerator

    gen = DocGenerator()

    # From snippets
    result = gen.from_snippets(
        snippets=["HEC is configured via Settings > Data Inputs"],
        title="HEC Configuration Guide",
        format="markdown",
    )

    # From directory scan
    result = gen.from_directory("/app/chat_app/", title="ObsAI Module Reference")

    # From zip file
    result = gen.from_zip("/tmp/upload.zip", title="Project Documentation")
"""

import json
import logging
import re
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Output formats
# ---------------------------------------------------------------------------

class DocFormat:
    MARKDOWN = "markdown"
    SHAREPOINT = "sharepoint"


# ---------------------------------------------------------------------------
# Documentation section
# ---------------------------------------------------------------------------

@dataclass
class DocSection:
    """A section of generated documentation."""
    title: str
    content: str
    level: int = 2  # Heading level (1=h1, 2=h2, etc.)
    subsections: List["DocSection"] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Generation result
# ---------------------------------------------------------------------------

@dataclass
class DocResult:
    """Result of document generation."""
    title: str
    content: str
    format: str
    sections: List[DocSection] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "content": self.content,
            "format": self.format,
            "section_count": len(self.sections),
            "content_length": len(self.content),
            "metadata": self.metadata,
            "warnings": self.warnings,
        }


# ---------------------------------------------------------------------------
# File analysis
# ---------------------------------------------------------------------------

# Extension → language mapping
_LANG_MAP: Dict[str, str] = {
    ".py": "python", ".js": "javascript", ".ts": "typescript", ".tsx": "typescript",
    ".jsx": "javascript", ".java": "java", ".go": "golang", ".rs": "rust",
    ".rb": "ruby", ".php": "php", ".c": "c", ".cpp": "cpp", ".h": "c",
    ".cs": "csharp", ".sh": "bash", ".bash": "bash", ".zsh": "bash",
    ".yaml": "yaml", ".yml": "yaml", ".json": "json", ".toml": "toml",
    ".xml": "xml", ".html": "html", ".css": "css", ".sql": "sql",
    ".md": "markdown", ".rst": "rst", ".txt": "text",
    ".conf": "ini", ".ini": "ini", ".cfg": "ini",
    ".dockerfile": "dockerfile", ".tf": "terraform",
}

# Files to skip
_SKIP_PATTERNS: Set[str] = {
    "__pycache__", ".git", ".svn", "node_modules", ".venv", "venv",
    ".pytest_cache", ".mypy_cache", "dist", "build", ".egg-info",
    ".tox", ".coverage", "htmlcov",
}

_SKIP_EXTENSIONS: Set[str] = {
    ".pyc", ".pyo", ".so", ".dll", ".exe", ".bin", ".o", ".a",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
    ".woff", ".woff2", ".ttf", ".eot",
    ".zip", ".tar", ".gz", ".bz2", ".xz",
    ".db", ".sqlite", ".sqlite3",
}

_MAX_FILE_SIZE = 500_000  # 500KB max per file for analysis
_MAX_FILES = 200  # Max files to analyze in a directory


# ---------------------------------------------------------------------------
# File analyzer
# ---------------------------------------------------------------------------

@dataclass
class FileAnalysis:
    """Analysis result for a single file."""
    path: str
    language: str
    size: int
    line_count: int
    has_docstring: bool = False
    classes: List[str] = field(default_factory=list)
    functions: List[str] = field(default_factory=list)
    imports: List[str] = field(default_factory=list)
    description: str = ""


def _analyze_file(file_path: str, content: str) -> FileAnalysis:
    """Analyze a single file and extract documentation-relevant information."""
    ext = Path(file_path).suffix.lower()
    language = _LANG_MAP.get(ext, "text")
    lines = content.split("\n")

    analysis = FileAnalysis(
        path=file_path,
        language=language,
        size=len(content),
        line_count=len(lines),
    )

    if language == "python":
        _analyze_python(content, analysis)
    elif language in ("yaml", "json", "toml", "ini"):
        _analyze_config(content, language, analysis)
    elif language in ("javascript", "typescript"):
        _analyze_js_ts(content, analysis)
    elif language == "markdown":
        _analyze_markdown(content, analysis)

    return analysis


def _analyze_python(content: str, analysis: FileAnalysis) -> None:
    """Extract Python-specific documentation info."""
    # Module docstring
    docstring_match = re.match(r'^(?:"""|\'\'\')(.*?)(?:"""|\'\'\')' , content, re.DOTALL)
    if docstring_match:
        analysis.has_docstring = True
        analysis.description = docstring_match.group(1).strip()[:200]

    # Classes
    analysis.classes = re.findall(r'^class\s+(\w+)', content, re.MULTILINE)

    # Functions (top-level and methods)
    analysis.functions = re.findall(r'^(?:async\s+)?def\s+(\w+)', content, re.MULTILINE)
    # Filter out private methods for doc purposes
    analysis.functions = [f for f in analysis.functions if not f.startswith("__")]

    # Imports
    imports = re.findall(r'^(?:from\s+(\S+)\s+import|import\s+(\S+))', content, re.MULTILINE)
    analysis.imports = [i[0] or i[1] for i in imports][:20]  # Limit


def _analyze_config(content: str, language: str, analysis: FileAnalysis) -> None:
    """Extract config file documentation info."""
    if language == "yaml":
        # Top-level keys
        top_keys = re.findall(r'^(\w[\w_-]*):', content, re.MULTILINE)
        analysis.description = f"Configuration with {len(top_keys)} sections: {', '.join(top_keys[:10])}"
    elif language == "json":
        try:
            data = json.loads(content)
            if isinstance(data, dict):
                analysis.description = f"JSON with {len(data)} top-level keys: {', '.join(list(data.keys())[:10])}"
        except json.JSONDecodeError as _exc:
            logger.debug("Could not parse JSON for doc analysis: %s", _exc)


def _analyze_js_ts(content: str, analysis: FileAnalysis) -> None:
    """Extract JS/TS documentation info."""
    analysis.classes = re.findall(r'(?:export\s+)?class\s+(\w+)', content)
    analysis.functions = re.findall(r'(?:export\s+)?(?:async\s+)?function\s+(\w+)', content)
    # React components
    components = re.findall(r'(?:export\s+)?(?:default\s+)?(?:const|function)\s+(\w+).*?(?:=>|{)', content)
    analysis.functions.extend([c for c in components if c[0].isupper()])


def _analyze_markdown(content: str, analysis: FileAnalysis) -> None:
    """Extract Markdown headings."""
    headings = re.findall(r'^#+\s+(.+)$', content, re.MULTILINE)
    analysis.description = f"Document with {len(headings)} sections"
    analysis.functions = headings[:10]  # Reuse functions field for headings


# ---------------------------------------------------------------------------
# Documentation Generator
# ---------------------------------------------------------------------------

class DocGenerator:
    """Generates professional documentation from various sources."""

    def from_snippets(
        self,
        snippets: List[str],
        title: str = "Documentation",
        format: str = DocFormat.MARKDOWN,
        comments: Optional[List[str]] = None,
        image_descriptions: Optional[List[str]] = None,
        style: str = "technical",
    ) -> DocResult:
        """Generate documentation from text snippets, comments, and image descriptions.

        Args:
            snippets: List of text content to document.
            title: Document title.
            format: Output format (markdown or sharepoint).
            comments: Optional reviewer/author comments.
            image_descriptions: Descriptions of images to reference.
            style: Documentation style (technical, user-friendly, api-reference).
        """
        sections: List[DocSection] = []

        # Title section
        sections.append(DocSection(title=title, content="", level=1))

        # Overview from first snippet
        if snippets:
            sections.append(DocSection(
                title="Overview",
                content=self._format_snippet(snippets[0], style),
            ))

        # Content sections from remaining snippets
        for i, snippet in enumerate(snippets[1:], 2):
            section_title = self._infer_section_title(snippet, i)
            sections.append(DocSection(
                title=section_title,
                content=self._format_snippet(snippet, style),
            ))

        # Image references
        if image_descriptions:
            img_content = "\n".join(
                f"- **Figure {i+1}**: {desc}" for i, desc in enumerate(image_descriptions)
            )
            sections.append(DocSection(title="Figures", content=img_content))

        # Comments/notes
        if comments:
            notes_content = "\n".join(f"> {comment}" for comment in comments)
            sections.append(DocSection(title="Notes", content=notes_content))

        # Metadata footer
        sections.append(DocSection(
            title="Document Info",
            content=f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\nStyle: {style}",
        ))

        content = self._render(sections, format)
        return DocResult(
            title=title,
            content=content,
            format=format,
            sections=sections,
            metadata={"style": style, "snippet_count": len(snippets),
                      "image_count": len(image_descriptions or [])},
        )

    def from_directory(
        self,
        directory: str,
        title: str = "Project Documentation",
        format: str = DocFormat.MARKDOWN,
        include_patterns: Optional[List[str]] = None,
        exclude_patterns: Optional[List[str]] = None,
    ) -> DocResult:
        """Scan a directory and generate comprehensive documentation.

        Args:
            directory: Path to the directory to scan.
            title: Document title.
            format: Output format.
            include_patterns: Optional glob patterns to include.
            exclude_patterns: Optional glob patterns to exclude.
        """
        dir_path = Path(directory)
        if not dir_path.exists():
            return DocResult(title=title, content="Error: Directory not found", format=format,
                             warnings=[f"Directory not found: {directory}"])

        # Collect files
        files = self._collect_files(dir_path)
        if not files:
            return DocResult(title=title, content="No analyzable files found", format=format,
                             warnings=["No files to analyze"])

        # Analyze files
        analyses: List[FileAnalysis] = []
        for file_path in files[:_MAX_FILES]:
            try:
                content = file_path.read_text(encoding="utf-8", errors="ignore")
                if len(content) > _MAX_FILE_SIZE:
                    content = content[:_MAX_FILE_SIZE]
                rel_path = str(file_path.relative_to(dir_path))
                analyses.append(_analyze_file(rel_path, content))
            except Exception as _exc:  # broad catch — resilience against all failures
                continue

        # Generate documentation sections
        sections = self._build_project_doc(title, analyses, dir_path)
        content = self._render(sections, format)

        return DocResult(
            title=title,
            content=content,
            format=format,
            sections=sections,
            metadata={
                "directory": str(directory),
                "files_analyzed": len(analyses),
                "total_lines": sum(a.line_count for a in analyses),
                "languages": list(set(a.language for a in analyses)),
            },
        )

    def from_zip(
        self,
        zip_path: str,
        title: str = "Project Documentation",
        format: str = DocFormat.MARKDOWN,
    ) -> DocResult:
        """Extract a zip file and generate documentation.

        Args:
            zip_path: Path to the zip file.
            title: Document title.
            format: Output format.
        """
        path = Path(zip_path)
        if not path.exists() or not zipfile.is_zipfile(str(path)):
            return DocResult(title=title, content="Error: Invalid zip file", format=format,
                             warnings=[f"Invalid zip file: {zip_path}"])

        analyses: List[FileAnalysis] = []
        warnings: List[str] = []

        try:
            with zipfile.ZipFile(str(path), "r") as zf:
                for info in zf.infolist()[:_MAX_FILES]:
                    if info.is_dir():
                        continue
                    ext = Path(info.filename).suffix.lower()
                    if ext in _SKIP_EXTENSIONS:
                        continue
                    if any(skip in info.filename for skip in _SKIP_PATTERNS):
                        continue
                    try:
                        content = zf.read(info.filename).decode("utf-8", errors="ignore")
                        if len(content) > _MAX_FILE_SIZE:
                            content = content[:_MAX_FILE_SIZE]
                        analyses.append(_analyze_file(info.filename, content))
                    except Exception as _exc:  # broad catch — resilience against all failures
                        warnings.append(f"Could not read: {info.filename}")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return DocResult(title=title, content=f"Error reading zip: {exc}", format=format,
                             warnings=[str(exc)])

        sections = self._build_project_doc(title, analyses, path.parent)
        content = self._render(sections, format)

        return DocResult(
            title=title,
            content=content,
            format=format,
            sections=sections,
            metadata={
                "source": str(zip_path),
                "files_analyzed": len(analyses),
                "total_lines": sum(a.line_count for a in analyses),
            },
            warnings=warnings,
        )

    # ----- Internal helpers -----

    def _collect_files(self, dir_path: Path) -> List[Path]:
        """Collect analyzable files from a directory."""
        files = []
        for path in sorted(dir_path.rglob("*")):
            if not path.is_file():
                continue
            if any(skip in str(path) for skip in _SKIP_PATTERNS):
                continue
            if path.suffix.lower() in _SKIP_EXTENSIONS:
                continue
            if path.stat().st_size > _MAX_FILE_SIZE:
                continue
            files.append(path)
        return files

    def _build_project_doc(
        self,
        title: str,
        analyses: List[FileAnalysis],
        base_path: Path,
    ) -> List[DocSection]:
        """Build structured documentation from file analyses."""
        sections: List[DocSection] = []

        # Title
        sections.append(DocSection(title=title, content="", level=1))

        # Overview
        lang_counts: Dict[str, int] = defaultdict(int)
        total_lines = 0
        for a in analyses:
            lang_counts[a.language] += 1
            total_lines += a.line_count

        overview_lines = [
            f"**Files analyzed**: {len(analyses)}",
            f"**Total lines**: {total_lines:,}",
            f"**Languages**: {', '.join(f'{lang} ({count})' for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1]))}",
        ]
        sections.append(DocSection(title="Project Overview", content="\n".join(overview_lines)))

        # Directory structure
        dirs = set()
        for a in analyses:
            parts = Path(a.path).parts
            for i in range(1, len(parts)):
                dirs.add("/".join(parts[:i]))
        if dirs:
            tree = "\n".join(f"- `{d}/`" for d in sorted(dirs)[:30])
            sections.append(DocSection(title="Directory Structure", content=tree))

        # Group by directory
        by_dir: Dict[str, List[FileAnalysis]] = defaultdict(list)
        for a in analyses:
            parent = str(Path(a.path).parent) if "/" in a.path else "."
            by_dir[parent].append(a)

        # Module documentation per directory
        for dir_name, dir_files in sorted(by_dir.items()):
            dir_content = []
            for fa in sorted(dir_files, key=lambda x: x.path):
                file_doc = self._document_file(fa)
                dir_content.append(file_doc)

            sections.append(DocSection(
                title=f"Module: {dir_name}" if dir_name != "." else "Root Files",
                content="\n\n".join(dir_content),
            ))

        # Summary statistics
        all_classes = [c for a in analyses for c in a.classes]
        all_functions = [f for a in analyses for f in a.functions]
        stats = [
            "| Metric | Value |",
            "|--------|-------|",
            f"| Total files | {len(analyses)} |",
            f"| Total lines | {total_lines:,} |",
            f"| Classes | {len(all_classes)} |",
            f"| Functions | {len(all_functions)} |",
            f"| Languages | {len(lang_counts)} |",
        ]
        sections.append(DocSection(title="Summary Statistics", content="\n".join(stats)))

        # Generation footer
        sections.append(DocSection(
            title="Document Info",
            content=f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}\nGenerator: ObsAI DocGenerator",
        ))

        return sections

    def _document_file(self, fa: FileAnalysis) -> str:
        """Generate documentation for a single file."""
        lines = [f"### `{fa.path}`"]
        lines.append(f"**Language**: {fa.language} | **Lines**: {fa.line_count}")

        if fa.description:
            lines.append(f"\n{fa.description}")

        if fa.classes:
            lines.append(f"\n**Classes**: {', '.join(f'`{c}`' for c in fa.classes)}")

        if fa.functions:
            displayed = fa.functions[:15]
            lines.append(f"\n**Functions**: {', '.join(f'`{f}`' for f in displayed)}")
            if len(fa.functions) > 15:
                lines.append(f"*...and {len(fa.functions) - 15} more*")

        if fa.imports:
            key_imports = [i for i in fa.imports if not i.startswith("__")][:10]
            if key_imports:
                lines.append(f"\n**Key imports**: {', '.join(f'`{i}`' for i in key_imports)}")

        return "\n".join(lines)

    def _format_snippet(self, snippet: str, style: str) -> str:
        """Format a text snippet according to the documentation style."""
        if style == "api-reference":
            return f"```\n{snippet}\n```"
        return snippet

    def _infer_section_title(self, snippet: str, index: int) -> str:
        """Infer a section title from snippet content."""
        first_line = snippet.strip().split("\n")[0][:60]
        if first_line.startswith("#"):
            return first_line.lstrip("# ").strip()
        if len(first_line) > 10:
            return first_line
        return f"Section {index}"

    def _render(self, sections: List[DocSection], format: str) -> str:
        """Render sections to the target format."""
        if format == DocFormat.SHAREPOINT:
            return self._render_sharepoint(sections)
        return self._render_markdown(sections)

    def _render_markdown(self, sections: List[DocSection]) -> str:
        """Render as clean Markdown."""
        parts = []
        for section in sections:
            heading = "#" * section.level
            parts.append(f"{heading} {section.title}")
            if section.content:
                parts.append(section.content)
            parts.append("")  # Blank line after section
        return "\n".join(parts)

    def _render_sharepoint(self, sections: List[DocSection]) -> str:
        """Render as SharePoint-compatible HTML."""
        parts = [
            "<!DOCTYPE html>",
            '<html><head><meta charset="utf-8">',
            "<style>",
            "body { font-family: 'Segoe UI', Tahoma, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; line-height: 1.6; }",
            "h1 { color: #0078d4; border-bottom: 2px solid #0078d4; padding-bottom: 8px; }",
            "h2 { color: #106ebe; margin-top: 24px; }",
            "h3 { color: #333; }",
            "code { background: #f4f4f4; padding: 2px 6px; border-radius: 3px; font-family: Consolas, monospace; }",
            "pre { background: #f4f4f4; padding: 12px; border-radius: 4px; overflow-x: auto; }",
            "table { border-collapse: collapse; width: 100%; margin: 12px 0; }",
            "th, td { border: 1px solid #ddd; padding: 8px; text-align: left; }",
            "th { background: #0078d4; color: white; }",
            "blockquote { border-left: 4px solid #0078d4; margin: 12px 0; padding: 8px 16px; background: #f0f6ff; }",
            ".metadata { color: #666; font-size: 0.9em; margin-top: 30px; border-top: 1px solid #ddd; padding-top: 10px; }",
            "</style>",
            "</head><body>",
        ]

        for section in sections:
            tag = f"h{min(section.level, 6)}"
            parts.append(f"<{tag}>{_html_escape(section.title)}</{tag}>")
            if section.content:
                html_content = self._md_to_html(section.content)
                parts.append(html_content)

        parts.append("</body></html>")
        return "\n".join(parts)

    def _md_to_html(self, md: str) -> str:
        """Simple Markdown-to-HTML conversion for SharePoint."""
        html = _html_escape(md)
        # Code blocks
        html = re.sub(r'```(\w*)\n(.*?)```', r'<pre><code>\2</code></pre>', html, flags=re.DOTALL)
        # Inline code
        html = re.sub(r'`([^`]+)`', r'<code>\1</code>', html)
        # Bold
        html = re.sub(r'\*\*([^*]+)\*\*', r'<strong>\1</strong>', html)
        # Italic
        html = re.sub(r'\*([^*]+)\*', r'<em>\1</em>', html)
        # Lists
        html = re.sub(r'^- (.+)$', r'<li>\1</li>', html, flags=re.MULTILINE)
        html = html.replace("<li>", "<ul><li>").replace("</li>\n<ul>", "</li>")
        # Blockquotes
        html = re.sub(r'^&gt; (.+)$', r'<blockquote>\1</blockquote>', html, flags=re.MULTILINE)
        # Tables (basic)
        if "|" in html and "---" in html:
            html = self._md_table_to_html(html)
        # Paragraphs
        html = re.sub(r'\n\n+', '</p><p>', html)
        html = f"<p>{html}</p>"
        return html

    def _md_table_to_html(self, text: str) -> str:
        """Convert Markdown tables to HTML."""
        lines = text.split("\n")
        result = []
        in_table = False
        for line in lines:
            if "|" in line and "---" not in line:
                cells = [c.strip() for c in line.split("|")[1:-1]]
                if not in_table:
                    result.append("<table>")
                    result.append("<tr>" + "".join(f"<th>{c}</th>" for c in cells) + "</tr>")
                    in_table = True
                else:
                    result.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
            elif "---" in line and in_table:
                continue  # Skip separator
            else:
                if in_table:
                    result.append("</table>")
                    in_table = False
                result.append(line)
        if in_table:
            result.append("</table>")
        return "\n".join(result)


def _html_escape(text: str) -> str:
    """Escape HTML special characters."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[DocGenerator] = None


def get_doc_generator() -> DocGenerator:
    """Get the global DocGenerator singleton."""
    global _instance
    if _instance is None:
        _instance = DocGenerator()
    return _instance
