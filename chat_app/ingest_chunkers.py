"""
Document Chunking Strategies for Ingestion Pipeline — Core Strategies.

Contains 5 core chunking strategies:
- token: word-based overlapping chunks (default)
- heading: markdown heading-aware splitting
- code: Python AST-aware splitting
- semantic: paragraph-based splitting
- structured_data: JSON/YAML key-preserving chunks

Extended strategies (table, conversation, late, propositions, sliding_window),
the strategy registry, and auto-selection logic live in ingest_chunkers_conf.py
and are re-exported here for backward compatibility.
"""

import json
import logging
import re
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Text Chunking — Multiple Strategies
# ---------------------------------------------------------------------------

def _chunk_text(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
    metadata: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """Split text into overlapping chunks with metadata (token/word-based)."""
    if not text or not text.strip():
        return []

    meta = metadata or {}
    chunks = []
    words = text.split()

    # Approximate word-based chunking (more natural than char-based)
    words_per_chunk = max(50, chunk_size // 5)  # ~5 chars per word average
    overlap_words = max(10, chunk_overlap // 5)

    i = 0
    while i < len(words):
        chunk_words = words[i:i + words_per_chunk]
        chunk_text = " ".join(chunk_words)

        if chunk_text.strip():
            chunks.append({
                "text": chunk_text.strip(),
                "metadata": {
                    **meta,
                    "chunk_index": len(chunks),
                },
            })

        i += words_per_chunk - overlap_words

    return chunks


# ---------------------------------------------------------------------------
# Heading-Based Markdown Chunking
# ---------------------------------------------------------------------------

_HEADING_PATTERN = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)


def chunk_by_headings(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
    metadata: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """Split markdown by headings, maintaining hierarchy context.

    Each chunk starts with a breadcrumb of parent headings so the embedding
    model understands the section context.  Sections that exceed
    ``chunk_size`` are further split using ``_chunk_text``.

    Args:
        text: Markdown text content.
        chunk_size: Target chunk size in characters.
        chunk_overlap: Overlap between sub-chunks (when a section is too large).
        metadata: Base metadata to attach to each chunk.

    Returns:
        List of chunk dicts with ``text`` and ``metadata``.
    """
    if not text or not text.strip():
        return []

    meta = metadata or {}
    chunks: List[Dict[str, Any]] = []

    # Parse heading positions
    headings: List[Tuple[int, int, str, int]] = []  # (level, start_pos, title, end_pos)
    for m in _HEADING_PATTERN.finditer(text):
        level = len(m.group(1))
        title = m.group(2).strip()
        headings.append((level, m.start(), title, m.end()))

    if not headings:
        # No headings — fall back to token chunking
        return _chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap, metadata=meta)

    # Build sections with parent context
    sections: List[Tuple[str, str]] = []  # (breadcrumb, section_text)
    heading_stack: List[Tuple[int, str]] = []  # (level, title) — tracks hierarchy

    for idx, (level, start, title, hdr_end) in enumerate(headings):
        # Determine section text (from after heading to next heading or end)
        if idx + 1 < len(headings):
            section_text = text[hdr_end:headings[idx + 1][1]].strip()
        else:
            section_text = text[hdr_end:].strip()

        # Update heading stack (pop deeper/equal levels)
        while heading_stack and heading_stack[-1][0] >= level:
            heading_stack.pop()
        heading_stack.append((level, title))

        # Build breadcrumb from stack
        breadcrumb = " > ".join(t for _, t in heading_stack)

        if section_text:
            sections.append((breadcrumb, section_text))

    # Also capture any text before the first heading
    if headings and headings[0][1] > 0:
        preamble = text[:headings[0][1]].strip()
        if preamble:
            sections.insert(0, ("(preamble)", preamble))

    # Chunk each section
    for breadcrumb, section_text in sections:
        prefixed_text = f"[{breadcrumb}]\n{section_text}"

        if len(prefixed_text) <= chunk_size * 1.2:
            # Section fits in one chunk
            chunks.append({
                "text": prefixed_text,
                "metadata": {
                    **meta,
                    "chunk_index": len(chunks),
                    "section": breadcrumb,
                    "chunking_strategy": "heading",
                },
            })
        else:
            # Section is too large — sub-chunk with token strategy
            sub_chunks = _chunk_text(
                prefixed_text,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                metadata={
                    **meta,
                    "section": breadcrumb,
                    "chunking_strategy": "heading",
                },
            )
            for sc in sub_chunks:
                sc["metadata"]["chunk_index"] = len(chunks)
                chunks.append(sc)

    return chunks


# ---------------------------------------------------------------------------
# AST-Based Code Chunking (Python)
# ---------------------------------------------------------------------------

def chunk_by_ast(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
    metadata: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """Split Python source code by function/class definitions using AST.

    Each function or class becomes its own chunk.  Module-level code and
    imports are grouped into a preamble chunk.  Non-Python files fall back
    to ``_chunk_text``.

    Args:
        text: Source code content.
        chunk_size: Target chunk size (used for fallback and large bodies).
        chunk_overlap: Overlap for sub-chunking.
        metadata: Base metadata to attach to each chunk.

    Returns:
        List of chunk dicts.
    """
    import ast as _ast

    if not text or not text.strip():
        return []

    meta = metadata or {}

    try:
        tree = _ast.parse(text)
    except SyntaxError:
        # Not valid Python — fall back to token chunking
        logger.debug("[CHUNK_AST] SyntaxError, falling back to token chunking")
        return _chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap, metadata=meta)

    lines = text.splitlines(keepends=True)
    chunks: List[Dict[str, Any]] = []

    # Collect top-level definitions
    definitions: List[Tuple[str, int, int]] = []  # (label, start_line, end_line)
    for node in _ast.iter_child_nodes(tree):
        if isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
            label = f"function:{node.name}"
            definitions.append((label, node.lineno - 1, node.end_lineno or node.lineno))
        elif isinstance(node, _ast.ClassDef):
            label = f"class:{node.name}"
            definitions.append((label, node.lineno - 1, node.end_lineno or node.lineno))

    if not definitions:
        # No functions/classes — fall back to token chunking
        return _chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap, metadata=meta)

    # Sort by line number
    definitions.sort(key=lambda d: d[1])

    # Preamble: everything before the first definition
    if definitions[0][1] > 0:
        preamble = "".join(lines[:definitions[0][1]]).strip()
        if preamble:
            if len(preamble) <= chunk_size * 1.5:
                chunks.append({
                    "text": preamble,
                    "metadata": {
                        **meta,
                        "chunk_index": len(chunks),
                        "code_element": "module_preamble",
                        "chunking_strategy": "code",
                    },
                })
            else:
                for sc in _chunk_text(preamble, chunk_size=chunk_size,
                                      chunk_overlap=chunk_overlap,
                                      metadata={**meta, "code_element": "module_preamble",
                                                "chunking_strategy": "code"}):
                    sc["metadata"]["chunk_index"] = len(chunks)
                    chunks.append(sc)

    # Each definition becomes a chunk
    for label, start, end in definitions:
        code_block = "".join(lines[start:end]).rstrip()
        if not code_block:
            continue

        if len(code_block) <= chunk_size * 1.5:
            chunks.append({
                "text": code_block,
                "metadata": {
                    **meta,
                    "chunk_index": len(chunks),
                    "code_element": label,
                    "chunking_strategy": "code",
                },
            })
        else:
            # Large function/class — sub-chunk
            for sc in _chunk_text(code_block, chunk_size=chunk_size,
                                  chunk_overlap=chunk_overlap,
                                  metadata={**meta, "code_element": label,
                                            "chunking_strategy": "code"}):
                sc["metadata"]["chunk_index"] = len(chunks)
                chunks.append(sc)

    # Inter-definition gaps (module-level code between definitions)
    for i in range(len(definitions) - 1):
        gap_start = definitions[i][2]
        gap_end = definitions[i + 1][1]
        if gap_end > gap_start:
            gap_text = "".join(lines[gap_start:gap_end]).strip()
            if gap_text and len(gap_text) > 20:
                chunks.append({
                    "text": gap_text,
                    "metadata": {
                        **meta,
                        "chunk_index": len(chunks),
                        "code_element": "module_level",
                        "chunking_strategy": "code",
                    },
                })

    # Trailing code after last definition
    last_end = definitions[-1][2]
    if last_end < len(lines):
        trailing = "".join(lines[last_end:]).strip()
        if trailing and len(trailing) > 20:
            chunks.append({
                "text": trailing,
                "metadata": {
                    **meta,
                    "chunk_index": len(chunks),
                    "code_element": "module_trailing",
                    "chunking_strategy": "code",
                },
            })

    return chunks if chunks else _chunk_text(text, chunk_size=chunk_size,
                                              chunk_overlap=chunk_overlap, metadata=meta)


# ---------------------------------------------------------------------------
# Semantic (Paragraph-Based) Chunking
# ---------------------------------------------------------------------------

def chunk_by_paragraphs(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
    metadata: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """Split text on paragraph boundaries (double newlines) with overlap.

    Respects natural paragraph structure while keeping chunks within
    ``chunk_size``.  Adjacent paragraphs are merged until the limit is
    reached, and the last paragraph of each chunk is repeated at the start
    of the next for overlap.

    Args:
        text: Input text with paragraph separators.
        chunk_size: Maximum chunk size in characters.
        chunk_overlap: Approximate character overlap between chunks.
        metadata: Base metadata.

    Returns:
        List of chunk dicts.
    """
    if not text or not text.strip():
        return []

    meta = metadata or {}

    # Split on double-newlines (paragraph boundaries)
    raw_paragraphs = re.split(r'\n\s*\n', text)
    paragraphs = [p.strip() for p in raw_paragraphs if p.strip()]

    if not paragraphs:
        return _chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap, metadata=meta)

    if len(paragraphs) == 1:
        # Single paragraph — use token chunking
        return _chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap,
                           metadata={**meta, "chunking_strategy": "semantic"})

    chunks: List[Dict[str, Any]] = []
    current_parts: List[str] = []
    current_len = 0

    for para in paragraphs:
        para_len = len(para)

        if current_len + para_len + 2 > chunk_size and current_parts:
            # Emit current chunk
            chunk_text = "\n\n".join(current_parts)
            chunks.append({
                "text": chunk_text,
                "metadata": {
                    **meta,
                    "chunk_index": len(chunks),
                    "chunking_strategy": "semantic",
                },
            })

            # Overlap: keep the last paragraph(s) up to chunk_overlap chars
            overlap_parts: List[str] = []
            overlap_len = 0
            for p in reversed(current_parts):
                if overlap_len + len(p) > chunk_overlap:
                    break
                overlap_parts.insert(0, p)
                overlap_len += len(p)
            current_parts = overlap_parts
            current_len = overlap_len

        current_parts.append(para)
        current_len += para_len + 2  # +2 for the "\n\n" separator

    # Emit final chunk
    if current_parts:
        chunk_text = "\n\n".join(current_parts)
        chunks.append({
            "text": chunk_text,
            "metadata": {
                **meta,
                "chunk_index": len(chunks),
                "chunking_strategy": "semantic",
            },
        })

    return chunks


# ---------------------------------------------------------------------------
# Structured Data Chunking (JSON/YAML/XML)
# ---------------------------------------------------------------------------

def chunk_structured_data(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
    metadata: Dict[str, Any] = None,
    max_chunk_size: int = 500,
) -> List[Dict[str, Any]]:
    """Chunk structured data (JSON, YAML) by top-level keys or array items.

    For JSON: each top-level key becomes a chunk.
    For YAML: each document section becomes a chunk.
    Includes the key path as metadata (e.g., ``config.database.host``).

    Args:
        text: Structured data content (JSON or YAML string).
        chunk_size: Target chunk size in characters.
        chunk_overlap: Overlap (unused for structured data — boundaries are logical).
        metadata: Base metadata dict.
        max_chunk_size: Maximum chunk size before sub-chunking.

    Returns:
        List of chunk dicts.
    """
    if not text or not text.strip():
        return []

    meta = metadata or {}
    chunks: List[Dict[str, Any]] = []
    effective_max = max_chunk_size or chunk_size

    def _flatten_to_chunks(data: Any, path: str = "") -> None:
        """Recursively flatten a parsed structure into chunks."""
        if isinstance(data, dict):
            for key, value in data.items():
                key_path = f"{path}.{key}" if path else str(key)
                serialized = json.dumps({key: value}, indent=2, default=str)
                if len(serialized) <= effective_max * 1.2:
                    chunks.append({
                        "text": serialized,
                        "metadata": {
                            **meta,
                            "chunk_index": len(chunks),
                            "key_path": key_path,
                            "chunking_strategy": "structured_data",
                        },
                    })
                else:
                    # Recurse into nested structures
                    _flatten_to_chunks(value, key_path)
        elif isinstance(data, list):
            # Group array items into batches that fit chunk_size
            batch: List[Any] = []
            batch_len = 0
            for idx, item in enumerate(data):
                item_str = json.dumps(item, indent=2, default=str)
                if batch_len + len(item_str) > effective_max and batch:
                    chunks.append({
                        "text": json.dumps(batch, indent=2, default=str),
                        "metadata": {
                            **meta,
                            "chunk_index": len(chunks),
                            "key_path": f"{path}[{idx - len(batch)}..{idx - 1}]",
                            "chunking_strategy": "structured_data",
                        },
                    })
                    batch = []
                    batch_len = 0
                batch.append(item)
                batch_len += len(item_str)
            if batch:
                start_idx = len(data) - len(batch)
                chunks.append({
                    "text": json.dumps(batch, indent=2, default=str),
                    "metadata": {
                        **meta,
                        "chunk_index": len(chunks),
                        "key_path": f"{path}[{start_idx}..{len(data) - 1}]",
                        "chunking_strategy": "structured_data",
                    },
                })
        else:
            # Scalar value
            serialized = json.dumps(data, indent=2, default=str)
            chunks.append({
                "text": serialized,
                "metadata": {
                    **meta,
                    "chunk_index": len(chunks),
                    "key_path": path or "(root)",
                    "chunking_strategy": "structured_data",
                },
            })

    # Try JSON first, then YAML
    parsed = None
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        try:
            import yaml as _yaml
            parsed = _yaml.safe_load(text)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

    if parsed is None:
        # Cannot parse — fall back to token chunking
        logger.debug("[CHUNK_STRUCT] Cannot parse as JSON/YAML, falling back to token")
        return _chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap, metadata=meta)

    _flatten_to_chunks(parsed)
    return chunks if chunks else _chunk_text(text, chunk_size=chunk_size,
                                              chunk_overlap=chunk_overlap, metadata=meta)


# ---------------------------------------------------------------------------
# Re-export extended strategies for backward compatibility
# ---------------------------------------------------------------------------
from chat_app.ingest_chunkers_conf import (  # noqa: E402,F401
    chunk_table,
    chunk_conversation,
    chunk_late,
    chunk_propositions,
    chunk_sliding_window,
    CHUNKING_STRATEGIES,
    select_chunking_strategy,
    chunk_with_strategy,
)
