"""
Splunk Documentation Loader - Parse and index official Splunk docs.

Loads command documentation (markdown) and configuration specifications
from the documents/ directory and provides lookup APIs for the knowledge
base, analyzer, and optimizer.

Usage:
    from shared.docs_loader import get_docs, CommandDoc, SpecDoc

    docs = get_docs()
    cmd = docs.get_command("stats")
    spec = docs.get_spec("limits")
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class CommandDoc:
    """Parsed SPL command documentation from official Splunk markdown."""
    name: str
    source_url: str = ""
    title: str = ""
    description: str = ""
    sections: Dict[str, str] = field(default_factory=dict)
    examples: List[str] = field(default_factory=list)
    related_commands: List[str] = field(default_factory=list)
    usage_notes: List[str] = field(default_factory=list)
    limitations: List[str] = field(default_factory=list)
    raw_text: str = ""

    @property
    def summary(self) -> str:
        """First paragraph of description, for brief display."""
        if not self.description:
            return ""
        first_para = self.description.split("\n\n")[0]
        return first_para.strip()[:500]


@dataclass
class SpecSetting:
    """A single setting within a .spec file stanza."""
    name: str
    type_hint: str = ""
    description: str = ""
    default: str = ""


@dataclass
class SpecStanza:
    """A stanza from a Splunk .spec file."""
    name: str
    settings: Dict[str, SpecSetting] = field(default_factory=dict)
    description: str = ""


@dataclass
class SpecDoc:
    """Parsed Splunk configuration spec file."""
    config_name: str  # e.g. "limits", "savedsearches"
    version: str = ""
    overview: str = ""
    stanzas: Dict[str, SpecStanza] = field(default_factory=dict)
    raw_text: str = ""


# ---------------------------------------------------------------------------
# Markdown parser for command docs
# ---------------------------------------------------------------------------

def _parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """Extract YAML frontmatter from markdown text."""
    meta = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1].strip()
            body = parts[2].strip()
            for line in fm_text.split("\n"):
                line = line.strip()
                if ":" in line:
                    key, _, val = line.partition(":")
                    meta[key.strip()] = val.strip()
    return meta, body


def _extract_sections(body: str) -> Dict[str, str]:
    """Split markdown into sections by h4 (####) headings."""
    sections = {}
    current_heading = ""
    current_lines = []

    for line in body.split("\n"):
        if line.startswith("#### "):
            if current_heading:
                sections[current_heading] = "\n".join(current_lines).strip()
            current_heading = line[5:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_heading:
        sections[current_heading] = "\n".join(current_lines).strip()

    return sections


def _extract_examples_from_sections(sections: Dict[str, str]) -> List[str]:
    """Pull numbered example descriptions from section headings."""
    examples = []
    for heading, content in sections.items():
        # Match patterns like "1. ..." or "2. ..."
        if re.match(r"\d+\.\s+", heading):
            examples.append(heading.strip())
    return examples


def _extract_limitations(sections: Dict[str, str]) -> List[str]:
    """Extract limitation/constraint sections."""
    limits = []
    limit_keywords = {"limitation", "wildcard", "not support", "cannot", "restriction"}
    for heading, content in sections.items():
        heading_lower = heading.lower()
        if any(kw in heading_lower for kw in limit_keywords):
            # Take first sentence of the content
            first_sentence = content.split(".")[0].strip() if content else heading
            if first_sentence:
                limits.append(f"{heading}: {first_sentence}")
    return limits


def _extract_usage_notes(sections: Dict[str, str]) -> List[str]:
    """Extract usage notes and performance hints."""
    notes = []
    note_keywords = {"usage", "performance", "memory", "functions", "ensure", "numeric"}
    for heading, content in sections.items():
        heading_lower = heading.lower()
        if any(kw in heading_lower for kw in note_keywords):
            # Take first sentence
            first = content.split(".")[0].strip() if content else ""
            if first and len(first) > 20:
                notes.append(f"{heading}: {first}")
    return notes


def _extract_related(body: str) -> List[str]:
    """Extract related commands from the last line if it looks like a list."""
    lines = body.strip().split("\n")
    if not lines:
        return []
    last_line = lines[-1].strip()
    # Related commands line is typically comma-separated command names
    if "," in last_line and len(last_line) < 200 and not last_line.startswith("|"):
        candidates = [c.strip() for c in last_line.split(",")]
        # Filter to valid-looking command names
        related = [c for c in candidates if re.match(r"^[a-z_]+$", c)]
        if len(related) >= 2:
            return related
    return []


def parse_command_doc(file_path: str) -> Optional[CommandDoc]:
    """Parse a single command markdown file into a CommandDoc."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except Exception as e:
        logger.warning(f"Failed to read command doc {file_path}: {e}")
        return None

    meta, body = _parse_frontmatter(text)
    if not body:
        return None

    cmd_name = meta.get("command", "")
    if not cmd_name:
        # Try to extract from filename: spl_cmd_stats.md -> stats
        basename = os.path.basename(file_path).replace(".md", "")
        if basename.startswith("spl_cmd_"):
            cmd_name = basename[8:]
        else:
            cmd_name = basename

    # Description is the text before the first heading
    description = ""
    first_heading_idx = body.find("#### ")
    if first_heading_idx > 0:
        description = body[:first_heading_idx].strip()
        # Strip the h1 title line
        if description.startswith("# "):
            description = description.split("\n", 1)[-1].strip()
    elif body.startswith("# "):
        description = body.split("\n", 1)[-1].strip()
    else:
        description = body[:1000]

    sections = _extract_sections(body)
    examples = _extract_examples_from_sections(sections)
    limitations = _extract_limitations(sections)
    usage_notes = _extract_usage_notes(sections)
    related = _extract_related(body)

    return CommandDoc(
        name=cmd_name,
        source_url=meta.get("source_url", ""),
        title=meta.get("title", cmd_name),
        description=description,
        sections=sections,
        examples=examples,
        related_commands=related,
        usage_notes=usage_notes,
        limitations=limitations,
        raw_text=text,
    )


# ---------------------------------------------------------------------------
# Spec file parser
# ---------------------------------------------------------------------------

def parse_spec_file(file_path: str) -> Optional[SpecDoc]:
    """Parse a Splunk .spec file into a SpecDoc."""
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            text = f.read()
    except Exception as e:
        logger.warning(f"Failed to read spec file {file_path}: {e}")
        return None

    # Extract config name: limits.conf.spec -> limits
    basename = os.path.basename(file_path)
    config_name = basename.replace(".conf.spec", "").replace(".spec", "")

    # Extract version
    version = ""
    ver_match = re.search(r"#\s+Version\s+(\S+)", text)
    if ver_match:
        version = ver_match.group(1)

    # Extract overview (between OVERVIEW markers)
    overview = ""
    ov_match = re.search(
        r"# OVERVIEW\s*\n#{3,}\n(.*?)(?=\n#{3,}|\n\[)",
        text, re.DOTALL
    )
    if ov_match:
        overview_raw = ov_match.group(1).strip()
        # Clean comment markers
        overview = "\n".join(
            line.lstrip("# ").rstrip()
            for line in overview_raw.split("\n")
        ).strip()

    # Parse stanzas and settings
    stanzas = {}
    current_stanza = None
    current_desc_lines = []
    current_setting = None
    current_setting_desc = []

    for line in text.split("\n"):
        stripped = line.strip()

        # Skip comment-only lines in the header area
        if stripped.startswith("##"):
            continue

        # Stanza header: [stanza_name]
        stanza_match = re.match(r"^\[([^\]]+)\]", stripped)
        if stanza_match:
            # Save previous setting
            if current_setting and current_stanza:
                current_setting.description = "\n".join(current_setting_desc).strip()
                current_stanza.settings[current_setting.name] = current_setting
                current_setting = None
                current_setting_desc = []

            stanza_name = stanza_match.group(1)
            current_stanza = SpecStanza(name=stanza_name)
            stanzas[stanza_name] = current_stanza
            current_desc_lines = []
            continue

        # Setting definition: key = <type>
        setting_match = re.match(r"^(\w[\w.\-]*)(?:\s*=\s*)(.+)?$", stripped)
        if setting_match and current_stanza and not stripped.startswith("#") and not stripped.startswith("*"):
            # Save previous setting
            if current_setting:
                current_setting.description = "\n".join(current_setting_desc).strip()
                current_stanza.settings[current_setting.name] = current_setting

            name = setting_match.group(1)
            type_hint = (setting_match.group(2) or "").strip()
            current_setting = SpecSetting(name=name, type_hint=type_hint)
            current_setting_desc = []
            continue

        # Setting description lines (start with *)
        if stripped.startswith("*") and current_setting:
            desc_text = stripped.lstrip("* ").rstrip()
            current_setting_desc.append(desc_text)

            # Check for default value
            if desc_text.lower().startswith("default:"):
                current_setting.default = desc_text[8:].strip()
            continue

    # Save last setting
    if current_setting and current_stanza:
        current_setting.description = "\n".join(current_setting_desc).strip()
        current_stanza.settings[current_setting.name] = current_setting

    return SpecDoc(
        config_name=config_name,
        version=version,
        overview=overview,
        stanzas=stanzas,
        raw_text=text,
    )


# ---------------------------------------------------------------------------
# Documentation index
# ---------------------------------------------------------------------------

class SplunkDocsIndex:
    """
    Indexed collection of official Splunk documentation.

    Loads command docs and spec files on first access, providing fast
    lookups for the knowledge base, analyzer, and optimizer.
    """

    def __init__(self, docs_root: Optional[str] = None):
        self._docs_root = docs_root
        self._commands: Dict[str, CommandDoc] = {}
        self._specs: Dict[str, SpecDoc] = {}
        self._metadata: Dict[str, Any] = {}
        self._loaded = False

    def _resolve_docs_root(self) -> str:
        """Find the documents directory."""
        if self._docs_root:
            return self._docs_root

        # Check environment variable
        env_root = os.getenv("SPLUNK_DOCS_ROOT")
        if env_root and os.path.isdir(env_root):
            return env_root

        # Standard search paths (container mounts and local dev)
        candidates = [
            "/app/documents",                  # search_opt container (baked in)
            "/app/public/documents",           # search_opt container (volume mount)
            "/app/shared/public/documents",    # main app container (volume mount)
            os.path.join(os.path.dirname(os.path.dirname(__file__)), "documents"),
            os.path.join(os.getcwd(), "documents"),
        ]
        for path in candidates:
            if os.path.isdir(path):
                return path

        return ""

    def _ensure_loaded(self):
        """Load docs on first access (lazy init)."""
        if self._loaded:
            return
        self._loaded = True

        root = self._resolve_docs_root()
        if not root:
            logger.info("No documents directory found; docs enrichment disabled")
            return

        commands_dir = os.path.join(root, "commands")
        specs_dir = os.path.join(root, "specs")

        # Load command docs
        if os.path.isdir(commands_dir):
            self._load_commands(commands_dir)

        # Load spec files
        if os.path.isdir(specs_dir):
            self._load_specs(specs_dir)

        total = len(self._commands) + len(self._specs)
        if total > 0:
            logger.info(
                f"Loaded Splunk docs: {len(self._commands)} commands, "
                f"{len(self._specs)} spec files"
            )

    def _load_commands(self, commands_dir: str):
        """Load all command markdown files."""
        # Load metadata if available
        meta_path = os.path.join(commands_dir, ".spl_docs_metadata.json")
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    self._metadata = json.load(f)
            except Exception:
                pass

        for fname in sorted(os.listdir(commands_dir)):
            if not fname.endswith(".md"):
                continue
            fpath = os.path.join(commands_dir, fname)
            doc = parse_command_doc(fpath)
            if doc:
                self._commands[doc.name.lower()] = doc

    def _load_specs(self, specs_dir: str):
        """Load all .spec files."""
        for fname in sorted(os.listdir(specs_dir)):
            if not fname.endswith(".spec"):
                continue
            fpath = os.path.join(specs_dir, fname)
            doc = parse_spec_file(fpath)
            if doc:
                self._specs[doc.config_name.lower()] = doc

    # --- Public API ---

    def get_command(self, name: str) -> Optional[CommandDoc]:
        """Look up a command by name."""
        self._ensure_loaded()
        return self._commands.get(name.lower())

    def get_command_description(self, name: str) -> str:
        """Get the official description for a command, or empty string."""
        doc = self.get_command(name)
        return doc.summary if doc else ""

    def get_command_limitations(self, name: str) -> List[str]:
        """Get known limitations for a command."""
        doc = self.get_command(name)
        return doc.limitations if doc else []

    def get_command_usage_notes(self, name: str) -> List[str]:
        """Get usage/performance notes for a command."""
        doc = self.get_command(name)
        return doc.usage_notes if doc else []

    def get_command_url(self, name: str) -> str:
        """Get the official Splunk documentation URL."""
        doc = self.get_command(name)
        return doc.source_url if doc else ""

    def get_all_command_names(self) -> List[str]:
        """Get all documented command names."""
        self._ensure_loaded()
        return sorted(self._commands.keys())

    def get_spec(self, config_name: str) -> Optional[SpecDoc]:
        """Look up a spec by config name (e.g. 'limits', 'savedsearches')."""
        self._ensure_loaded()
        return self._specs.get(config_name.lower())

    def get_spec_setting(
        self, config_name: str, stanza: str, setting: str
    ) -> Optional[SpecSetting]:
        """Look up a specific setting from a spec file."""
        spec = self.get_spec(config_name)
        if not spec:
            return None
        stanza_obj = spec.stanzas.get(stanza)
        if not stanza_obj:
            return None
        return stanza_obj.settings.get(setting)

    def get_limits_info(self, command: str) -> Dict[str, str]:
        """Get limits.conf settings relevant to a command."""
        limits_spec = self.get_spec("limits")
        if not limits_spec:
            return {}

        result = {}
        # Try exact stanza match
        stanza = limits_spec.stanzas.get(command)
        if stanza:
            for setting_name, setting in stanza.settings.items():
                desc = setting.description[:200] if setting.description else ""
                default = f" (default: {setting.default})" if setting.default else ""
                result[setting_name] = f"{desc}{default}"
        return result

    def get_all_spec_names(self) -> List[str]:
        """Get all loaded spec config names."""
        self._ensure_loaded()
        return sorted(self._specs.keys())

    def search_commands(self, keyword: str) -> List[CommandDoc]:
        """Search commands by keyword in name or description."""
        self._ensure_loaded()
        keyword_lower = keyword.lower()
        results = []
        for doc in self._commands.values():
            if (keyword_lower in doc.name.lower() or
                keyword_lower in doc.description.lower()):
                results.append(doc)
        return results

    @property
    def command_count(self) -> int:
        self._ensure_loaded()
        return len(self._commands)

    @property
    def spec_count(self) -> int:
        self._ensure_loaded()
        return len(self._specs)

    @property
    def metadata(self) -> Dict:
        self._ensure_loaded()
        return self._metadata


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_docs_index: Optional[SplunkDocsIndex] = None


def get_docs(docs_root: Optional[str] = None) -> SplunkDocsIndex:
    """Get the singleton docs index instance."""
    global _docs_index
    if _docs_index is None:
        _docs_index = SplunkDocsIndex(docs_root=docs_root)
    return _docs_index
