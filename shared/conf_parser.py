"""
Splunk Configuration File Parser
Handles .conf files with proper stanza-aware chunking.

Enhanced with rich metadata extraction for app directory structure:
- TAs/ (Technology Add-ons)
- IAs/ (Input Apps)
- Scripts/ (Administrative Scripts)
- BAs/ (Base Apps)
- UIs/ (UI Apps: soc-dev, org-search, org-es, org-ds, etc.)
- And all subdirectories

Each chunk includes:
- Stanza name
- App type (TAs, IAs, BAs, UIs, Scripts)
- App name (TA-nmap, org-search, etc.)
- Full app path (UIs/org-search/local/savedsearches.conf)

Supports 3-level deployment-tier structure:
  app_type / deployment_tier / app_name / subdir / file
  e.g. TAs/_global/TA-windows/local/inputs.conf

Deployment tiers (_global, deployment-apps, manager-apps, cluster-*, soc-dev, etc.)
are detected automatically and stored as metadata alongside a human-readable
deployment target description.
"""
import re
import logging
import os
from typing import Any, List, Tuple, Dict
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Deployment tier detection for 3-level repo structures
# ---------------------------------------------------------------------------

# Exact tier names that are always deployment tiers
KNOWN_DEPLOYMENT_TIERS = {
    "_global",
    "deployment-apps",
    "manager-apps",
    "soc-dev",
}

# Regex patterns for deployment tier names (cluster-*, org-*, _*)
DEPLOYMENT_TIER_PATTERN = re.compile(
    r"^(?:cluster-\w+|org-\w+|_\w+|deployment-\w+|manager-\w+|soc-\w+)$"
)

# Subdirectories that indicate we're already inside an app (2-level, not a tier)
_APP_SUBDIRS = {"default", "local", "metadata", "bin", "lookups", "appserver",
                "static", "README", "samples", "lib", "windows", "linux"}

# Human-readable deployment target descriptions
DEPLOYMENT_TIER_TARGETS: Dict[str, str] = {
    "_global": "All Splunk Enterprise instances (HFs, Indexers, Search Heads)",
    "deployment-apps": "Heavy Forwarders and Universal Forwarders via Deployment Server (serverclass-based)",
    "manager-apps": "Indexers via Cluster Manager (cluster bundle push)",
    "soc-dev": "SOC team development environment",
}


def is_deployment_tier(name: str, next_component: str | None = None) -> bool:
    """
    Determine if a path component is a deployment tier rather than an app name.

    Disambiguation: if the *next* path component is a well-known app subdirectory
    (default, local, metadata, bin ...) then ``name`` is actually a 2-level app name.
    """
    if next_component and next_component.lower() in _APP_SUBDIRS:
        return False
    if name in KNOWN_DEPLOYMENT_TIERS:
        return True
    return bool(DEPLOYMENT_TIER_PATTERN.match(name))


def get_deployment_target(app_type: str, deployment_tier: str | None) -> str | None:
    """
    Return a human-readable deployment target description for a tier.

    For cluster-{name} tiers the description references the specific Search Head
    Cluster by name.
    """
    if not deployment_tier:
        return None
    if deployment_tier in DEPLOYMENT_TIER_TARGETS:
        return DEPLOYMENT_TIER_TARGETS[deployment_tier]
    m = re.match(r"^cluster-(\w+)$", deployment_tier)
    if m:
        return f"Search Head Cluster: {m.group(1)}"
    m = re.match(r"^org-(\w+)$", deployment_tier)
    if m:
        return f"Organization app group: {m.group(1)}"
    if deployment_tier.startswith("_"):
        return f"Global tier: {deployment_tier}"
    return f"Deployment tier: {deployment_tier}"


@dataclass
class ConfStanza:
    """Represents a single stanza in a .conf file"""
    name: str  # e.g., [default], [savedsearch_name]
    content: str  # The settings under this stanza
    line_start: int  # Starting line number
    line_end: int  # Ending line number


def parse_conf_file(content: str, filename: str = "unknown") -> List[ConfStanza]:
    """
    Parse .conf file content into a list of ConfStanza objects.

    Each stanza includes name, raw content, and line numbers.
    Content before the first stanza header is captured as '__preamble__'.
    """
    stanzas: List[ConfStanza] = []
    lines = content.splitlines()

    current_name: str | None = None
    current_lines: list[str] = []
    stanza_start = 0

    def _flush():
        nonlocal current_name, current_lines, stanza_start
        if current_name is not None or current_lines:
            name = current_name if current_name is not None else "__preamble__"
            stanzas.append(ConfStanza(
                name=name,
                content="\n".join(current_lines),
                line_start=stanza_start,
                line_end=stanza_start + len(current_lines) - 1,
            ))
        current_lines = []

    for i, line in enumerate(lines):
        stanza_match = re.match(r'^\s*\[\s*([^\]]+)\s*\]\s*$', line)
        if stanza_match:
            _flush()
            current_name = stanza_match.group(1)
            stanza_start = i + 1  # 1-based
            current_lines = [line]
        else:
            current_lines.append(line)

    _flush()
    return stanzas


def parse_conf_file_advanced(content: str, filename: str = "unknown") -> Dict[str, Dict[str, Any]]:
    """
    A more advanced .conf file parser that handles comments and multi-line values.
    """
    conf_data = {}
    current_stanza = None
    line_number = 0
    lines = content.splitlines()

    for i, line in enumerate(lines):
        line_number += 1
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        
        stanza_match = re.match(r'^\s*\[\s*([^\]]+)\s*\]\s*$', line)
        if stanza_match:
            current_stanza = stanza_match.group(1)
            if current_stanza not in conf_data:
                conf_data[current_stanza] = {'__lines__': {}}
            continue

        if current_stanza:
            kv_match = re.match(r'^\s*([a-zA-Z_][\w-]*)\s*=\s*(.*)\s*$', line)
            if kv_match:
                key, value = kv_match.groups()
                # Handle multi-line values
                j = i + 1
                while j < len(lines) and lines[j].strip().startswith('\\'):
                    value += lines[j].strip().lstrip('\\')
                    j += 1
                
                conf_data[current_stanza][key] = value
                conf_data[current_stanza]['__lines__'][key] = line_number
    return conf_data


def extract_app_metadata(file_path: str) -> Dict[str, str]:
    """
    Extract app directory structure metadata from file path.

    Supports ALL repo structures:
    - /repo/TAs/TA-nmap/local/inputs.conf
    - /repo/IAs/IA-example/default/app.conf
    - /repo/BAs/BA-common/local/props.conf
    - /repo/UIs/org-search/local/savedsearches.conf
    - /repo/UIs/_global/default/indexes.conf
    - /repo/Scripts/maintenance.py
    - etc.

    Returns:
        Dict with:
        - app_type: TAs, IAs, BAs, UIs, Scripts, etc.
        - app_name: TA-nmap, org-search, _global, etc.
        - app_path: TAs/TA-nmap
        - app_subdir: local, default, etc. (or None if directly in app)
        - filename: inputs.conf
        - full_app_path: TAs/TA-nmap/local/inputs.conf
    """
    try:
        path = Path(file_path)
        parts = path.parts

        # Find 'repo' in path - use the LAST occurrence to handle
        # paths like /app/public/documents/repo/splunk/repo/UIs/obsai_UI_home/...
        if 'repo' in parts:
            # Find last 'repo' index (rindex equivalent for tuples)
            repo_idx = len(parts) - 1 - list(reversed(parts)).index('repo')
            after_repo = parts[repo_idx + 1:]

            if len(after_repo) == 0:
                # File directly in repo root (rare)
                return {
                    "app_type": "repo_root",
                    "app_name": "repo_root",
                    "app_path": "repo_root",
                    "app_subdir": None,
                    "deployment_tier": None,
                    "deployment_target": None,
                    "filename": path.name,
                    "full_app_path": path.name,
                }

            app_type = after_repo[0]  # TAs, IAs, BAs, UIs, Scripts, etc.

            if len(after_repo) == 1:
                # File directly in app_type directory (e.g., /repo/TAs/README.md)
                return {
                    "app_type": app_type,
                    "app_name": app_type,
                    "app_path": app_type,
                    "app_subdir": None,
                    "deployment_tier": None,
                    "deployment_target": None,
                    "filename": path.name,
                    "full_app_path": f"{app_type}/{path.name}",
                }

            # ---- 3-level detection ----
            # Check if after_repo[1] is a deployment tier
            # Disambiguation: peek at after_repo[2] to avoid false positives
            candidate_tier = after_repo[1]
            next_comp = after_repo[2] if len(after_repo) > 2 else None
            tier_detected = (
                len(after_repo) >= 3
                and is_deployment_tier(candidate_tier, next_comp)
            )

            if tier_detected:
                # 3-level: app_type / deployment_tier / app_name / subdir / file
                deployment_tier = candidate_tier
                deployment_target = get_deployment_target(app_type, deployment_tier)
                app_name = after_repo[2] if len(after_repo) > 2 else deployment_tier

                if len(after_repo) == 2:
                    # File directly in tier dir (rare)
                    return {
                        "app_type": app_type,
                        "app_name": deployment_tier,
                        "app_path": f"{app_type}/{deployment_tier}",
                        "app_subdir": None,
                        "deployment_tier": deployment_tier,
                        "deployment_target": deployment_target,
                        "filename": path.name,
                        "full_app_path": f"{app_type}/{deployment_tier}/{path.name}",
                    }

                if len(after_repo) == 3:
                    # File directly in app dir under tier
                    return {
                        "app_type": app_type,
                        "app_name": app_name,
                        "app_path": f"{app_type}/{deployment_tier}/{app_name}",
                        "app_subdir": None,
                        "deployment_tier": deployment_tier,
                        "deployment_target": deployment_target,
                        "filename": path.name,
                        "full_app_path": f"{app_type}/{deployment_tier}/{app_name}/{path.name}",
                    }

                app_subdir = after_repo[3]
                remaining_path = after_repo[4:] if len(after_repo) > 4 else []

                if remaining_path:
                    full_relative = str(Path(*after_repo[3:]))
                else:
                    full_relative = f"{app_subdir}/{path.name}"

                return {
                    "app_type": app_type,
                    "app_name": app_name,
                    "app_path": f"{app_type}/{deployment_tier}/{app_name}",
                    "app_subdir": app_subdir,
                    "deployment_tier": deployment_tier,
                    "deployment_target": deployment_target,
                    "filename": path.name,
                    "full_app_path": f"{app_type}/{deployment_tier}/{app_name}/{full_relative}",
                }

            # ---- 2-level (original behavior) ----
            app_name = after_repo[1]

            if len(after_repo) == 2:
                # File directly in app directory (e.g., /repo/TAs/TA-nmap/app.conf)
                return {
                    "app_type": app_type,
                    "app_name": app_name,
                    "app_path": f"{app_type}/{app_name}",
                    "app_subdir": None,
                    "deployment_tier": None,
                    "deployment_target": None,
                    "filename": path.name,
                    "full_app_path": f"{app_type}/{app_name}/{path.name}",
                }

            # Standard case: /repo/TAs/TA-nmap/local/inputs.conf
            app_subdir = after_repo[2]  # local, default, metadata, etc.
            remaining_path = after_repo[3:] if len(after_repo) > 3 else []

            if remaining_path:
                # File in nested subdirectory
                full_relative = str(Path(*after_repo[2:]))
            else:
                full_relative = f"{app_subdir}/{path.name}"

            return {
                "app_type": app_type,
                "app_name": app_name,
                "app_path": f"{app_type}/{app_name}",
                "app_subdir": app_subdir,
                "deployment_tier": None,
                "deployment_target": None,
                "filename": path.name,
                "full_app_path": f"{app_type}/{app_name}/{full_relative}",
            }

        # Fallback: file not in repo structure
        return {
            "app_type": "unknown",
            "app_name": "unknown",
            "app_path": "unknown",
            "app_subdir": None,
            "deployment_tier": None,
            "deployment_target": None,
            "filename": path.name,
            "full_app_path": path.name,
        }

    except Exception as e:
        logger.warning(f"Failed to extract app metadata from {file_path}: {e}")
        return {
            "app_type": "unknown",
            "app_name": "unknown",
            "app_path": "unknown",
            "app_subdir": None,
            "deployment_tier": None,
            "deployment_target": None,
            "filename": os.path.basename(file_path),
            "full_app_path": os.path.basename(file_path),
        }





def chunk_conf_stanzas(
    stanzas: List[ConfStanza],
    max_chunk_size: int = 500,
    filename: str = "unknown",
    chunk_overlap: int = 100
) -> List[Tuple[str, Dict[str, any]]]:
    """
    Convert stanzas into chunks suitable for embedding.

    Strategy:
    - Each stanza is ONE chunk (never mix stanzas)
    - If stanza < max_chunk_size: Keep as single chunk
    - If stanza > max_chunk_size: Split with overlap, keep stanza header in each part

    Special handling:
    - savedsearches.conf: NEVER split (keep entire search together)
    - Large stanzas: Use larger chunk size to avoid breaking critical content

    Args:
        stanzas: List of ConfStanza objects
        max_chunk_size: Maximum characters per chunk (default: 500)
        filename: Name of file for metadata
        chunk_overlap: Overlap between split chunks (default: 100)

    Returns:
        List of (chunk_content, metadata) tuples
    """
    chunks = []

    # Respect the configured max_chunk_size (default from settings.chunking.conf_max_chunk_size).
    # mxbai-embed-large has a 512 token limit (~1200-1500 chars safe).
    # The old 3000 char override exceeded the embedding model context window.
    effective_chunk_size = max_chunk_size

    # Derive conf_type from filename for richer metadata
    is_savedsearches = 'savedsearches.conf' in filename.lower()
    fname_lower = filename.lower().replace('.conf.spec', '').replace('.conf', '').replace('.spec', '')
    conf_type_map = {
        'savedsearches': 'savedsearch', 'inputs': 'input', 'outputs': 'output',
        'props': 'props', 'transforms': 'transforms', 'indexes': 'index',
        'server': 'server', 'web': 'web', 'authentication': 'authentication',
        'authorize': 'authorize', 'macros': 'macro', 'collections': 'collection',
        'eventtypes': 'eventtype', 'tags': 'tag', 'limits': 'limits',
        'alert_actions': 'alert_action', 'commands': 'command',
        'distsearch': 'distsearch', 'deploymentclient': 'deploymentclient',
    }
    conf_type = conf_type_map.get(fname_lower, fname_lower)

    for stanza in stanzas:
        # Format stanza for embedding
        stanza_header = f"[{stanza.name}]" if stanza.name != "__preamble__" else "# File Header Comments"
        stanza_text = f"{stanza_header}\n{stanza.content}"
        stanza_size = len(stanza_text)

        # Case 1: Stanza is too large, needs splitting
        if stanza_size > effective_chunk_size:
            # Split large stanza into multiple chunks
            lines = stanza.content.splitlines()
            sub_chunk_lines = []
            sub_chunk_size = len(stanza_header) + 1  # +1 for newline

            for line in lines:
                line_size = len(line) + 1  # +1 for newline

                if sub_chunk_size + line_size > effective_chunk_size and sub_chunk_lines:
                    # Finalize current sub-chunk
                    sub_content = f"{stanza_header}\n" + '\n'.join(sub_chunk_lines)
                    metadata = {
                        "stanza": stanza.name,
                        "filename": filename,
                        "conf_type": conf_type,
                        "lines": f"{stanza.line_start}-{stanza.line_end}",
                        "type": "conf_partial"
                    }
                    chunks.append((sub_content, metadata))

                    # Start new sub-chunk with overlap
                    # Take last chunk_overlap characters worth of lines for context
                    overlap_lines = []
                    overlap_size = 0
                    for prev_line in reversed(sub_chunk_lines):
                        if overlap_size + len(prev_line) + 1 <= chunk_overlap:
                            overlap_lines.insert(0, prev_line)
                            overlap_size += len(prev_line) + 1
                        else:
                            break

                    sub_chunk_lines = overlap_lines + [line]
                    sub_chunk_size = len(stanza_header) + 1 + sum(len(l) + 1 for l in sub_chunk_lines)
                else:
                    sub_chunk_lines.append(line)
                    sub_chunk_size += line_size

            # Add final sub-chunk
            if sub_chunk_lines:
                sub_content = f"{stanza_header}\n" + '\n'.join(sub_chunk_lines)
                metadata = {
                    "stanza": stanza.name,
                    "filename": filename,
                    "lines": f"{stanza.line_start}-{stanza.line_end}",
                    "type": "conf_partial"
                }
                chunks.append((sub_content, metadata))

        # Case 2: Stanza fits as single chunk
        else:
            metadata = {
                "stanza": stanza.name,
                "filename": filename,
                "conf_type": conf_type,
                "lines": f"{stanza.line_start}-{stanza.line_end}",
                "type": "conf_complete"
            }
            # Mark if this is a saved search for special UI handling
            if is_savedsearches:
                metadata["is_savedsearch"] = True
            chunks.append((stanza_text, metadata))

    logger.info(f"Chunked {filename}: {len(stanzas)} stanzas → {len(chunks)} chunks")
    return chunks


def chunk_conf_file(
    content: str,
    file_path: str,
    max_chunk_size: int = 500,
    chunk_overlap: int = 100
) -> List[Tuple[str, Dict]]:
    """
    High-level function to parse and chunk a .conf file with rich metadata.

    Strategy:
    - Use smaller chunks (500 chars default) for better precision
    - 100 char overlap between chunks for context
    - Each chunk includes full app/stanza/file metadata

    Usage:
        chunks = chunk_conf_file(file_content, "/opt/obsai/documents/repo/UIs/org-search/local/savedsearches.conf")
        for chunk_text, metadata in chunks:
            # Add to vector store with metadata:
            # - stanza: savedsearch name
            # - app_type: UIs
            # - app_name: org-search
            # - app_path: UIs/org-search
            # - full_app_path: UIs/org-search/local/savedsearches.conf
            ...

    Args:
        content: Full content of .conf file
        file_path: Full path to file (for metadata extraction)
        max_chunk_size: Maximum characters per chunk (default: 500)
        chunk_overlap: Overlap between chunks in characters (default: 100)

    Returns:
        List of (chunk_text, metadata) tuples with rich app metadata
    """
    filename = os.path.basename(file_path)
    app_metadata = extract_app_metadata(file_path)

    stanzas = parse_conf_file(content, filename)
    chunks = chunk_conf_stanzas(stanzas, max_chunk_size, filename, chunk_overlap)

    # Enrich each chunk with app metadata
    enriched_chunks = []
    for chunk_text, metadata in chunks:
        enriched_metadata = {
            **metadata,
            **app_metadata,
            "source": file_path,
        }
        enriched_chunks.append((chunk_text, enriched_metadata))

    return enriched_chunks


def enrich_chunk_for_search(chunk_text: str, metadata: Dict[str, any]) -> str:
    """
    Lightly enrich chunk text for embedding search.

    IMPORTANT: Keep the prefix MINIMAL to avoid polluting the embedding vector.
    Metadata is already stored in ChromaDB metadata fields and used for filtering/boosting.
    The prefix here is only for cases where vector similarity needs to match app/stanza names.

    Only includes stanza name (most important for search) and filename.
    App path, type, etc. are already in metadata and used by scoring logic.

    Args:
        chunk_text: Original chunk content (e.g., "[default]\\nenableSched = 0")
        metadata: Rich metadata dict with app_type, app_name, stanza, etc.

    Returns:
        Chunk text with minimal metadata context for embedding
    """
    # Only add stanza context if it's not already in the text (i.e., stanza header [name] is present)
    # This avoids polluting the embedding while ensuring stanza names are searchable
    stanza = metadata.get("stanza", "")
    filename = metadata.get("filename", "")

    # If the chunk already starts with [stanza_name], no prefix needed — the stanza name
    # is already in the text and will be embedded naturally
    if chunk_text.strip().startswith("[") and stanza:
        return chunk_text

    # For chunks that don't have the stanza header (e.g., continuation chunks),
    # add a minimal context line
    if stanza and stanza != "__preamble__":
        return f"[{stanza}] ({filename})\n{chunk_text}"

    return chunk_text


# Example usage and testing
if __name__ == "__main__":
    # Example savedsearches.conf content
    test_content = """
# This is a comment before any stanza

[default]
enableSched = 0
dispatch.earliest_time = -24h@h
dispatch.latest_time = now

[my_saved_search]
search = index=main sourcetype=access | stats count by host
description = Count events by host
enableSched = 1
cron_schedule = 0 */6 * * *
dispatch.earliest_time = -6h@h
dispatch.latest_time = now
action.email = 1
action.email.to = admin@example.com

[another_search]
search = index=_internal | stats count
description = Simple count search
"""

    # Parse and chunk
    chunks = chunk_conf_file(test_content, "savedsearches.conf", max_chunk_size=400)

    print(f"Generated {len(chunks)} chunks:\n")
    for i, (content, metadata) in enumerate(chunks, 1):
        print(f"=== Chunk {i} ===")
        print(f"Metadata: {metadata}")
        print(f"Content preview (first 200 chars):")
        print(content[:200])
        print()