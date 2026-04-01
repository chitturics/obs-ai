"""Extended Chunking Strategies — Table, Conversation, Late, Propositions, Sliding Window.

Extracted from ingest_chunkers.py to keep file sizes manageable.
Contains:
- chunk_table: CSV/tabular row-grouped chunks
- chunk_conversation: log/chat session-aware chunks
- chunk_late: contextual chunks for long documents
- chunk_propositions: sentence-level atomic fact chunks
- chunk_sliding_window: overlapping fixed-size windows
- CHUNKING_STRATEGIES: strategy registry
- select_chunking_strategy: auto-selection logic
- chunk_with_strategy: orchestration entry point

All public names are re-exported for backward compatibility.
"""

import csv
import io
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from chat_app.ingest_chunkers import (
    _chunk_text,
    _HEADING_PATTERN,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Table/CSV Chunking
# ---------------------------------------------------------------------------

def chunk_table(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
    metadata: Dict[str, Any] = None,
    rows_per_chunk: int = 50,
) -> List[Dict[str, Any]]:
    """Chunk tabular data preserving headers in each chunk.

    Splits CSV/TSV by rows, includes headers in every chunk, adds schema
    metadata (column names), and creates an overview chunk with summary
    statistics (row count, column count).

    Args:
        text: CSV or TSV content.
        chunk_size: Target chunk size (used as fallback).
        chunk_overlap: Overlap (unused — boundaries are row-based).
        metadata: Base metadata dict.
        rows_per_chunk: Maximum data rows per chunk.

    Returns:
        List of chunk dicts.
    """
    if not text or not text.strip():
        return []

    meta = metadata or {}
    chunks: List[Dict[str, Any]] = []

    # Detect delimiter
    first_line = text.split('\n', 1)[0]
    delimiter = '\t' if '\t' in first_line else ','

    try:
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows = list(reader)
    except csv.Error:
        return _chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap, metadata=meta)

    if len(rows) < 2:
        return _chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap, metadata=meta)

    header = rows[0]
    data_rows = rows[1:]
    header_line = delimiter.join(header)

    # Overview chunk with summary statistics
    overview_parts = [
        f"Table Overview: {len(header)} columns, {len(data_rows)} rows",
        f"Columns: {', '.join(header)}",
    ]
    chunks.append({
        "text": "\n".join(overview_parts),
        "metadata": {
            **meta,
            "chunk_index": 0,
            "chunk_type": "table_overview",
            "columns": header,
            "row_count": len(data_rows),
            "chunking_strategy": "table",
        },
    })

    # Data chunks — each includes the header row
    for batch_start in range(0, len(data_rows), rows_per_chunk):
        batch = data_rows[batch_start:batch_start + rows_per_chunk]
        chunk_lines = [header_line]
        for row in batch:
            chunk_lines.append(delimiter.join(row))

        chunks.append({
            "text": "\n".join(chunk_lines),
            "metadata": {
                **meta,
                "chunk_index": len(chunks),
                "chunk_type": "table_data",
                "row_range": f"{batch_start + 1}-{batch_start + len(batch)}",
                "columns": header,
                "chunking_strategy": "table",
            },
        })

    return chunks


# ---------------------------------------------------------------------------
# Conversation/Log Chunking
# ---------------------------------------------------------------------------

_TIMESTAMP_PATTERN = re.compile(
    r'^\[?(\d{4}[-/]\d{2}[-/]\d{2}[\sT]\d{2}:\d{2}(?::\d{2})?)\]?',
    re.MULTILINE,
)
_SPEAKER_PATTERN = re.compile(
    r'^(?:\[.*?\]\s*)?([A-Z][\w\s]{0,30}?):\s',
    re.MULTILINE,
)


def chunk_conversation(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
    metadata: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """Chunk conversation logs by topic/time boundaries.

    Detects conversation turns (timestamps, speaker changes) and groups
    related messages into coherent segments. Each chunk gets participant
    metadata.

    Args:
        text: Conversation or log content.
        chunk_size: Maximum chunk size in characters.
        chunk_overlap: Overlap (unused — boundaries are turn-based).
        metadata: Base metadata dict.

    Returns:
        List of chunk dicts.
    """
    if not text or not text.strip():
        return []

    meta = metadata or {}
    chunks: List[Dict[str, Any]] = []

    # Split into individual messages/lines
    lines = text.strip().split('\n')

    # Detect turns: a new turn starts when we see a timestamp or speaker change
    turns: List[List[str]] = []
    current_turn: List[str] = []

    for line in lines:
        is_new_turn = bool(
            _TIMESTAMP_PATTERN.match(line) or _SPEAKER_PATTERN.match(line)
        )
        if is_new_turn and current_turn:
            turns.append(current_turn)
            current_turn = []
        current_turn.append(line)

    if current_turn:
        turns.append(current_turn)

    if not turns:
        return _chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap, metadata=meta)

    # Group turns into chunks that fit within chunk_size
    current_group: List[str] = []
    current_len = 0
    current_participants: set = set()

    for turn in turns:
        turn_text = "\n".join(turn)
        turn_len = len(turn_text)

        # Extract participant from first line
        speaker_match = _SPEAKER_PATTERN.match(turn[0])
        if speaker_match:
            current_participants.add(speaker_match.group(1).strip())

        if current_len + turn_len + 1 > chunk_size and current_group:
            # Emit chunk
            chunks.append({
                "text": "\n".join(current_group),
                "metadata": {
                    **meta,
                    "chunk_index": len(chunks),
                    "participants": sorted(current_participants),
                    "chunking_strategy": "conversation",
                },
            })
            current_group = []
            current_len = 0
            current_participants = set()
            # Re-add participant for the new chunk
            if speaker_match:
                current_participants.add(speaker_match.group(1).strip())

        current_group.extend(turn)
        current_len += turn_len + 1

    # Emit final chunk
    if current_group:
        chunks.append({
            "text": "\n".join(current_group),
            "metadata": {
                **meta,
                "chunk_index": len(chunks),
                "participants": sorted(current_participants),
                "chunking_strategy": "conversation",
            },
        })

    return chunks if chunks else _chunk_text(text, chunk_size=chunk_size,
                                              chunk_overlap=chunk_overlap, metadata=meta)


# ---------------------------------------------------------------------------
# Late Chunking (Contextual)
# ---------------------------------------------------------------------------

def chunk_late(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
    metadata: Dict[str, Any] = None,
) -> List[Dict[str, Any]]:
    """Late chunking -- split after understanding full document context.

    Creates a brief document summary first, then prepends it to each chunk
    so every chunk has document-level awareness. This simulates late chunking
    without requiring a long-context embedding model.

    Args:
        text: Document content.
        chunk_size: Target chunk size (for the body portion, excluding summary).
        chunk_overlap: Overlap between body chunks.
        metadata: Base metadata dict.

    Returns:
        List of chunk dicts.
    """
    if not text or not text.strip():
        return []

    meta = metadata or {}

    # Step 1: Build document summary
    summary_parts: List[str] = []

    # Extract headings
    headings = _HEADING_PATTERN.findall(text)
    if headings:
        heading_titles = [title.strip() for _, title in headings[:10]]
        summary_parts.append("Sections: " + " | ".join(heading_titles))

    # Extract first paragraph (up to 200 chars)
    paragraphs = re.split(r'\n\s*\n', text.strip())
    if paragraphs:
        first_para = paragraphs[0].strip()[:200]
        summary_parts.append(first_para)

    summary = "[Document Context] " + " — ".join(summary_parts) if summary_parts else ""

    # Step 2: Split into standard chunks (with reduced size to make room for summary)
    summary_len = len(summary) + 1  # +1 for newline separator
    body_chunk_size = max(100, chunk_size - summary_len)

    base_chunks = _chunk_text(
        text,
        chunk_size=body_chunk_size,
        chunk_overlap=chunk_overlap,
        metadata=meta,
    )

    if not base_chunks:
        return []

    # Step 3: Prepend summary to each chunk
    contextual_chunks: List[Dict[str, Any]] = []
    for chunk in base_chunks:
        chunk_text = chunk["text"]
        if summary:
            chunk_text = f"{summary}\n{chunk_text}"

        contextual_chunks.append({
            "text": chunk_text,
            "metadata": {
                **chunk.get("metadata", meta),
                "chunk_index": len(contextual_chunks),
                "has_context_prefix": True,
                "chunking_strategy": "late",
            },
        })

    return contextual_chunks


# ---------------------------------------------------------------------------
# Proposition-Based Chunking
# ---------------------------------------------------------------------------

_CONJUNCTION_SPLITTERS = re.compile(
    r'(?:,\s*(?:and|but|or|which|who|that|with|while|whereas)\s+)|'
    r'(?:\s+(?:and|but|or)\s+)',
    re.IGNORECASE,
)


def chunk_propositions(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
    metadata: Dict[str, Any] = None,
    max_props: int = 200,
) -> List[Dict[str, Any]]:
    """Break content into atomic factual propositions.

    Each proposition is a single, self-contained fact.

    Args:
        text: Input text.
        chunk_size: Unused (each proposition is its own chunk).
        chunk_overlap: Unused.
        metadata: Base metadata dict.
        max_props: Maximum number of propositions to generate.

    Returns:
        List of chunk dicts (one per proposition).
    """
    if not text or not text.strip():
        return []

    meta = metadata or {}
    chunks: List[Dict[str, Any]] = []

    # Split into sentences first
    sentences = re.split(r'(?<=[.!?])\s+', text.strip())

    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence or len(sentence) < 10:
            continue

        # Try to split compound sentences into atomic propositions
        parts = _CONJUNCTION_SPLITTERS.split(sentence)
        parts = [p.strip().rstrip('.,;') for p in parts if p and p.strip() and len(p.strip()) >= 10]

        if not parts:
            parts = [sentence]

        for part in parts:
            if len(chunks) >= max_props:
                break

            prop = part.strip()
            if not prop:
                continue
            if not prop.endswith(('.', '!', '?')):
                prop += '.'

            chunks.append({
                "text": prop,
                "metadata": {
                    **meta,
                    "chunk_index": len(chunks),
                    "chunk_type": "proposition",
                    "chunking_strategy": "propositions",
                },
            })

        if len(chunks) >= max_props:
            break

    return chunks if chunks else _chunk_text(text, chunk_size=chunk_size,
                                              chunk_overlap=chunk_overlap, metadata=meta)


# ---------------------------------------------------------------------------
# Sliding Window Chunking
# ---------------------------------------------------------------------------

def chunk_sliding_window(
    text: str,
    chunk_size: int = 500,
    chunk_overlap: int = 100,
    metadata: Dict[str, Any] = None,
    window_size: int = 500,
    step_size: int = 250,
) -> List[Dict[str, Any]]:
    """Sliding window with configurable overlap.

    Args:
        text: Input text.
        chunk_size: Unused (``window_size`` and ``step_size`` control sizing).
        chunk_overlap: Unused.
        metadata: Base metadata dict.
        window_size: Size of each window in characters.
        step_size: Step size between windows in characters.

    Returns:
        List of chunk dicts.
    """
    if not text or not text.strip():
        return []

    meta = metadata or {}
    chunks: List[Dict[str, Any]] = []
    content = text.strip()

    if len(content) <= window_size:
        return [{
            "text": content,
            "metadata": {
                **meta,
                "chunk_index": 0,
                "window_start": 0,
                "window_end": len(content),
                "chunking_strategy": "sliding_window",
            },
        }]

    pos = 0
    while pos < len(content):
        end = min(pos + window_size, len(content))
        window_text = content[pos:end].strip()

        if window_text:
            chunks.append({
                "text": window_text,
                "metadata": {
                    **meta,
                    "chunk_index": len(chunks),
                    "window_start": pos,
                    "window_end": end,
                    "chunking_strategy": "sliding_window",
                },
            })

        pos += step_size

        # Avoid tiny trailing windows
        if pos < len(content) and len(content) - pos < step_size // 2:
            remainder = content[pos:].strip()
            if remainder and remainder != window_text:
                chunks.append({
                    "text": remainder,
                    "metadata": {
                        **meta,
                        "chunk_index": len(chunks),
                        "window_start": pos,
                        "window_end": len(content),
                        "chunking_strategy": "sliding_window",
                    },
                })
            break

    return chunks


# ---------------------------------------------------------------------------
# Chunking Strategy Registry
# ---------------------------------------------------------------------------

# Import strategies from the main module to include them in registry
from chat_app.ingest_chunkers import (  # noqa: E402
    chunk_by_headings,
    chunk_by_ast,
    chunk_by_paragraphs,
    chunk_structured_data,
)

CHUNKING_STRATEGIES = {
    "token": _chunk_text,
    "heading": chunk_by_headings,
    "code": chunk_by_ast,
    "semantic": chunk_by_paragraphs,
    "structured_data": chunk_structured_data,
    "table": chunk_table,
    "conversation": chunk_conversation,
    "late": chunk_late,
    "propositions": chunk_propositions,
    "sliding_window": chunk_sliding_window,
}


def select_chunking_strategy(filepath: str, content: str) -> str:
    """Auto-select the best chunking strategy based on file extension and content.

    Args:
        filepath: Path to the source file.
        content: The file content.

    Returns:
        Strategy key from ``CHUNKING_STRATEGIES``.
    """
    ext = Path(filepath).suffix.lower()

    if ext in ('.json', '.yaml', '.yml'):
        return "structured_data"

    if ext in ('.csv', '.tsv'):
        return "table"

    if ext in ('.log',):
        return "conversation"

    if ext in ('.md', '.markdown', '.rst'):
        if _HEADING_PATTERN.search(content):
            return "heading"
        return "semantic" if content.count('\n\n') > 3 else "token"

    if ext in ('.py',):
        return "code"

    if ext in ('.conf', '.spec'):
        return "token"  # stanza chunker is used in vectorstore.py, not here

    if len(content) > 5000:
        return "late"

    if content.count('\n\n') > 5:
        return "semantic"

    return "token"


def chunk_with_strategy(
    text: str,
    filepath: str = "",
    chunk_size: int = 500,
    chunk_overlap: int = 100,
    metadata: Dict[str, Any] = None,
    strategy: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Chunk text using the appropriate strategy.

    If *strategy* is not specified, auto-selects based on file type and content.

    Args:
        text: Content to chunk.
        filepath: Source file path (used for strategy selection).
        chunk_size: Target chunk size.
        chunk_overlap: Overlap between chunks.
        metadata: Base metadata dict.
        strategy: Explicit strategy name, or None for auto-selection.

    Returns:
        List of chunk dicts with ``text`` and ``metadata``.
    """
    if not strategy:
        strategy = select_chunking_strategy(filepath, text) if filepath else "token"

    chunk_fn = CHUNKING_STRATEGIES.get(strategy, _chunk_text)
    logger.debug("[CHUNK] Using '%s' strategy for %s", strategy, filepath or "(inline)")

    result = chunk_fn(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap, metadata=metadata)

    # Fallback: if the chosen strategy produced nothing, try token chunking
    if not result and strategy != "token":
        logger.debug("[CHUNK] '%s' produced no chunks, falling back to token", strategy)
        result = _chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap, metadata=metadata)

    return result
