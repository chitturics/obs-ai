"""
Multi-Format Document Ingestion — PDF, HTML, SharePoint, Confluence, JSON, CSV.

Universal document parser that can ingest content from multiple sources
and formats, chunk it appropriately, and store in ChromaDB collections.

Supports:
- PDF files (with text extraction)
- HTML pages (with cleanup)
- SharePoint sites (via Microsoft Graph API)
- Confluence spaces (via Atlassian REST API)
- JSON data files (structured extraction)
- CSV files (row-by-row or columnar)
- YAML/TOML config files

Data structures are in document_ingestor_types.py.
Parser implementations are in document_parsers.py.
"""
import hashlib
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Re-export data structures for backward compatibility
# ---------------------------------------------------------------------------
from chat_app.document_ingestor_types import (  # noqa: F401 — re-exported
    IngestedDocument,
    IngestionResult,
)

# ---------------------------------------------------------------------------
# Re-export parsers and connectors for backward compatibility
# ---------------------------------------------------------------------------
from chat_app.document_parsers import (  # noqa: F401 — re-exported
    ConfluenceConnector,
    SharePointConnector,
    _convert_via_docling,
    _flatten_dict,
    parse_csv,
    parse_html,
    parse_json,
    parse_pdf,
)


# Local wrappers so tests can patch chat_app.document_ingestor._convert_via_docling
# and have the patch take effect on calls within this module.

async def _parse_pdf_via_docling(filepath: str, chunk_size: int = 500) -> Optional[IngestedDocument]:
    """Try parsing PDF via Docling sidecar. Returns None if unavailable or failed."""
    return await _convert_via_docling(filepath, source_type="pdf")


async def _ingest_via_docling(filepath: str, chunk_size: int = 500) -> Optional[IngestedDocument]:
    """Ingest non-PDF formats (docx, pptx, xlsx, odt) via Docling sidecar."""
    ext = Path(filepath).suffix.lower().lstrip(".")
    return await _convert_via_docling(filepath, source_type=ext)


# ---------------------------------------------------------------------------
# Incremental Ingestion — Chunk-Level Change Detection
# ---------------------------------------------------------------------------

def _content_hash(text: str) -> str:
    """Compute a stable SHA-256 hash for chunk content (change detection)."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]


# In-memory store: doc_source -> {chunk_seq: content_hash}
_chunk_hash_store: Dict[str, Dict[int, str]] = {}

# Cumulative incremental ingestion statistics
_incremental_stats: Dict[str, int] = {
    "total_chunks_seen": 0,
    "chunks_changed": 0,
    "chunks_unchanged": 0,
    "chunks_deleted": 0,
    "ingestion_runs": 0,
}


def get_incremental_stats() -> Dict[str, Any]:
    """Return current incremental ingestion statistics."""
    return {
        **_incremental_stats,
        "tracked_documents": len(_chunk_hash_store),
        "tracked_chunks": sum(len(v) for v in _chunk_hash_store.values()),
    }


def _detect_chunk_changes(
    doc_source: str,
    new_chunks: List[Dict[str, Any]],
) -> Tuple[List[int], List[int], List[int]]:
    """Compare new chunks against stored hashes to find changes.

    Returns:
        (changed_indices, unchanged_indices, deleted_seq_numbers)
    """
    old_hashes = _chunk_hash_store.get(doc_source, {})
    new_hashes: Dict[int, str] = {}
    changed: List[int] = []
    unchanged: List[int] = []

    for idx, chunk in enumerate(new_chunks):
        text = chunk.get("text", "")
        h = _content_hash(text)
        new_hashes[idx] = h

        old_h = old_hashes.get(idx)
        if old_h is None or old_h != h:
            changed.append(idx)
        else:
            unchanged.append(idx)

    # Detect deleted chunks (old seq numbers not in new set)
    deleted = [seq for seq in old_hashes if seq not in new_hashes]

    # Update the store with new hashes
    _chunk_hash_store[doc_source] = new_hashes

    return changed, unchanged, deleted


# ---------------------------------------------------------------------------
# Chunking strategies — extracted to ingest_chunkers.py
# ---------------------------------------------------------------------------
from chat_app.ingest_chunkers import (  # noqa: F401 — re-export
    CHUNKING_STRATEGIES,
    _chunk_text,
    chunk_by_ast,
    chunk_by_headings,
    chunk_by_paragraphs,
    chunk_conversation,
    chunk_late,
    chunk_propositions,
    chunk_sliding_window,
    chunk_structured_data,
    chunk_table,
    chunk_with_strategy,
    select_chunking_strategy,
)


# ---------------------------------------------------------------------------
# Universal Ingestion Interface
# ---------------------------------------------------------------------------

async def ingest_file(filepath: str, chunk_size: int = 500) -> IngestedDocument:
    """Ingest a single file based on its extension."""
    ext = Path(filepath).suffix.lower()

    # Formats that Docling handles exclusively (when enabled)
    _DOCLING_ONLY_FORMATS = {".docx", ".pptx", ".xlsx", ".odt"}
    if ext in _DOCLING_ONLY_FORMATS:
        result = await _ingest_via_docling(filepath, chunk_size)
        if result:
            return result
        return IngestedDocument(
            source=filepath, source_type="unknown",
            error=f"Docling not available for {ext} files. Enable docling sidecar.",
        )

    if ext == ".pdf":
        # Try Docling first (OCR + table extraction), fall back to legacy parsers
        docling_result = await _parse_pdf_via_docling(filepath, chunk_size)
        if docling_result:
            return docling_result
        return parse_pdf(filepath, chunk_size)
    elif ext in (".html", ".htm"):
        content = Path(filepath).read_text(encoding="utf-8", errors="ignore")
        return parse_html(content, source_url=f"file://{filepath}", chunk_size=chunk_size)
    elif ext == ".json":
        return parse_json(filepath, chunk_size)
    elif ext == ".csv":
        return parse_csv(filepath, chunk_size)
    elif ext in (".yaml", ".yml"):
        return _parse_yaml(filepath, chunk_size)
    elif ext in (".conf", ".spec", ".txt", ".md", ".ini", ".cfg", ".toml", ".log",
                  ".py", ".js", ".ts", ".go", ".java", ".rst", ".markdown"):
        return _parse_text(filepath, chunk_size)
    else:
        return IngestedDocument(
            source=filepath, source_type="unknown",
            error=f"Unsupported file type: {ext}",
        )


def _parse_yaml(filepath: str, chunk_size: int = 500) -> IngestedDocument:
    """Parse YAML file."""
    doc = IngestedDocument(source=filepath, source_type="yaml")
    try:
        import yaml
        with open(filepath, "r") as f:
            data = yaml.safe_load(f)
        text = _flatten_dict(data) if isinstance(data, dict) else str(data)
        doc.title = Path(filepath).stem
        doc.chunks = _chunk_text(text, chunk_size=chunk_size, metadata={"source": filepath, "kind": "yaml"})
        doc.chunk_count = len(doc.chunks)
        doc.fingerprint = hashlib.sha256(text[:5000].encode()).hexdigest()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        doc.error = f"YAML parse error: {exc}"
    return doc


def _parse_text(filepath: str, chunk_size: int = 500) -> IngestedDocument:
    """Parse plain text / markdown / conf / code files using auto-selected chunking strategy."""
    doc = IngestedDocument(source=filepath, source_type="text")
    try:
        text = Path(filepath).read_text(encoding="utf-8", errors="ignore")
        doc.title = Path(filepath).stem
        ext = Path(filepath).suffix.lower()
        kind = "text"
        if ext in ('.md', '.markdown'):
            kind = "markdown"
        elif ext in ('.py', '.js', '.ts', '.go', '.java'):
            kind = "code"

        doc.chunks = chunk_with_strategy(
            text,
            filepath=filepath,
            chunk_size=chunk_size,
            metadata={"source": filepath, "kind": kind},
        )
        doc.chunk_count = len(doc.chunks)
        doc.fingerprint = hashlib.sha256(text[:5000].encode()).hexdigest()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        doc.error = f"Text parse error: {exc}"
    return doc


async def ingest_directory(
    directory: str,
    patterns: List[str] = None,
    chunk_size: int = 500,
    max_files: int = 500,
) -> IngestionResult:
    """
    Ingest all supported files from a directory.

    Args:
        directory: Path to scan.
        patterns: File glob patterns to include.
        chunk_size: Chunk size for text splitting.
        max_files: Maximum files to process.
    """
    result = IngestionResult()

    if not os.path.isdir(directory):
        result.errors.append(f"Directory not found: {directory}")
        return result

    file_patterns = patterns or ["*.pdf", "*.html", "*.htm", "*.json", "*.csv",
                                  "*.yaml", "*.yml", "*.md", "*.markdown", "*.rst",
                                  "*.txt", "*.conf", "*.spec", "*.ini", "*.cfg",
                                  "*.py", "*.js", "*.ts", "*.go", "*.java",
                                  "*.docx", "*.pptx", "*.xlsx", "*.odt"]

    files_found = []
    for pattern in file_patterns:
        files_found.extend(Path(directory).rglob(pattern))

    files_found = files_found[:max_files]

    for filepath in files_found:
        try:
            doc = await ingest_file(str(filepath), chunk_size)
            if doc.error:
                result.errors.append(f"{filepath.name}: {doc.error}")
                result.documents_skipped += 1
            else:
                result.documents_processed += 1
                result.chunks_created += doc.chunk_count
                result.sources.append(str(filepath))
        except (OSError, ValueError, KeyError, TypeError) as exc:
            result.errors.append(f"{filepath.name}: {exc}")

    logger.info(
        f"[INGEST] Directory {directory}: "
        f"{result.documents_processed} docs, {result.chunks_created} chunks, "
        f"{len(result.errors)} errors"
    )
    return result


async def ingest_to_vectorstore(
    documents: List[IngestedDocument],
    vector_store,
    collection_name: str = "ingested_docs",
) -> int:
    """
    Store parsed documents into ChromaDB with incremental change detection.

    Only re-embeds changed chunks; skips unchanged ones. Detects and removes
    stale chunks (deleted sections). Returns the number of chunks stored/updated.
    """
    if not documents or not vector_store:
        return 0

    # Build Ollama embedder to match the search pipeline
    embedder = None
    try:
        from chat_app.vectorstore import get_embeddings_model
        embedder = get_embeddings_model()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[INGEST] Could not init OllamaEmbeddings, "
                       "falling back to ChromaDB default: %s", exc)

    total = 0
    run_changed = 0
    run_unchanged = 0
    run_deleted = 0
    run_total_chunks = 0

    try:
        # vector_store may be a Langchain Chroma wrapper — extract the raw client
        client = getattr(vector_store, "_client", None) or vector_store
        collection = client.get_or_create_collection(collection_name)

        # Delete old chunks for documents that have changed (prevent stale accumulation)
        for doc in documents:
            if doc.error or not doc.chunks:
                continue
            try:
                # Check if source exists with different fingerprint
                res = collection.get(
                    where={"source": doc.source}, limit=1, include=["metadatas"]
                )
                if res and res.get("ids"):
                    old_fp = (res["metadatas"][0] or {}).get("fingerprint", "")
                    if old_fp and old_fp != doc.fingerprint:
                        collection.delete(where={"source": doc.source})
                        logger.info(f"[INGEST] Deleted stale chunks for changed source: {doc.source}")
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as del_exc:
                logger.debug(f"[INGEST] Stale check failed for {doc.source}: {del_exc}")

        batch_ids = []
        batch_docs = []
        batch_meta = []

        for doc in documents:
            if doc.error or not doc.chunks:
                continue

            # --- Incremental change detection at chunk level ---
            changed_indices, unchanged_indices, deleted_seqs = _detect_chunk_changes(
                doc.source, doc.chunks,
            )
            run_total_chunks += len(doc.chunks)
            run_changed += len(changed_indices)
            run_unchanged += len(unchanged_indices)
            run_deleted += len(deleted_seqs)

            # Remove stale chunks (deleted sections) from the collection
            if deleted_seqs:
                for seq in deleted_seqs:
                    stale_id = hashlib.sha256(
                        f"{doc.source}:{seq}:".encode()
                    ).hexdigest()
                    try:
                        collection.delete(ids=[stale_id])
                    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                        logger.debug("%s", _exc)
                logger.info(
                    "[INGEST] Removed %d stale chunks from %s",
                    len(deleted_seqs), doc.source,
                )

            # Only process changed chunks (skip unchanged to save embedding cost)
            changed_set = set(changed_indices)
            for idx, chunk in enumerate(doc.chunks):
                if idx not in changed_set:
                    continue  # Skip unchanged chunk

                text = chunk.get("text", "")
                meta = chunk.get("metadata", {})
                doc_id = hashlib.sha256(f"{doc.source}:{meta.get('chunk_index', 0)}:{text[:100]}".encode()).hexdigest()

                batch_ids.append(doc_id)
                batch_docs.append(text)
                batch_meta.append({
                    "source": doc.source,
                    "source_type": doc.source_type,
                    "title": doc.title,
                    "kind": meta.get("kind", doc.source_type),
                    "fingerprint": doc.fingerprint,
                    **{k: v for k, v in meta.items() if isinstance(v, (str, int, float, bool))},
                })

                if len(batch_ids) >= 100:
                    upsert_kw = dict(ids=batch_ids, documents=batch_docs, metadatas=batch_meta)
                    if embedder:
                        try:
                            upsert_kw["embeddings"] = embedder.embed_documents(batch_docs)
                        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as emb_exc:
                            logger.warning("[INGEST] Embedding batch failed: %s", emb_exc)
                    collection.upsert(**upsert_kw)
                    total += len(batch_ids)
                    batch_ids, batch_docs, batch_meta = [], [], []

        if batch_ids:
            upsert_kw = dict(ids=batch_ids, documents=batch_docs, metadatas=batch_meta)
            if embedder:
                try:
                    upsert_kw["embeddings"] = embedder.embed_documents(batch_docs)
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as emb_exc:
                    logger.warning("[INGEST] Embedding final batch failed: %s", emb_exc)
            collection.upsert(**upsert_kw)
            total += len(batch_ids)

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error(f"[INGEST] Vectorstore ingestion failed: {exc}")

    # Update cumulative incremental stats
    _incremental_stats["ingestion_runs"] += 1
    _incremental_stats["total_chunks_seen"] += run_total_chunks
    _incremental_stats["chunks_changed"] += run_changed
    _incremental_stats["chunks_unchanged"] += run_unchanged
    _incremental_stats["chunks_deleted"] += run_deleted

    logger.info(
        "[INGEST] Incremental stats: total=%d changed=%d unchanged=%d deleted=%d embedded=%d",
        run_total_chunks, run_changed, run_unchanged, run_deleted, total,
    )

    return total
