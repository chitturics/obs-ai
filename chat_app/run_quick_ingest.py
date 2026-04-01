#!/usr/bin/env python3
"""
Full reindex script — deletes all ChromaDB collections and re-ingests everything.

IMPORTANT: Each source type goes into its OWN ChromaDB collection matching
the names the search system expects:
  - spl_commands   → CHROMA_ADDITIONAL: spl_commands_mxbai
  - spec_files     → CHROMA_SECONDARY:  specs_mxbai_embed_large_v3
  - conf_reference → CHROMA_SECONDARY:  specs_mxbai_embed_large_v3
  - org_repo       → CHROMA_ADDITIONAL: org_repo_mxbai
  - local_docs     → CHROMA_ADDITIONAL: local_docs_mxbai
  - cribl_docs     → CHROMA_ADDITIONAL: cribl_docs_mxbai
  - metadata       → CHROMA_COLLECTION: assistant_memory_mxbai_v2  (primary)

Run inside the container:
    python3 /app/chat_app/run_quick_ingest.py

Or from host via docker exec:
    docker exec chat_ui_app python3 /app/chat_app/run_quick_ingest.py

Options:
    --skip-delete    Skip deletion, only ingest missing files (incremental)
    --collection X   Only reindex a specific collection label
    --dry-run        Show what would be done without making changes
    --list           List current collections and exit
    --debug          Show full tracebacks on errors
"""
import argparse
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/chat_app')
os.chdir('/app')

from chat_app.vectorstore import (
    get_vector_store,
    _fingerprint_bytes,
    has_fingerprint,
    _should_replace,
    _delete_source,
)

# ============================================================================
# Configuration
# ============================================================================

# Max chars per chunk — safe for mxbai-embed-large (512 tokens ~ 2048 chars)
# Leave headroom for metadata prefix
MAX_CHUNK_CHARS = 1500
SAFE_CHUNK_CHARS = 1200
CHUNK_OVERLAP_CHARS = 150

# ---------------------------------------------------------------------------
# Collection name mapping — must match what the search system expects
# ---------------------------------------------------------------------------
def _get_collection_map():
    """
    Map source labels → ChromaDB collection names.
    Reads from the same env vars that start_all.sh / docker-compose.yml set.
    """
    primary = os.getenv("CHROMA_COLLECTION", "assistant_memory_mxbai_v2")
    secondary = os.getenv("CHROMA_SECONDARY_COLLECTION", "specs_mxbai_embed_large_v3")

    # Parse additional collections from env
    additional_str = os.getenv("CHROMA_ADDITIONAL_COLLECTIONS", "")
    additional = [c.strip() for c in additional_str.split(",") if c.strip()]

    # Build lookup from additional list (order matters — matches source order)
    # Expected: spl_commands_mxbai, org_repo_mxbai, local_docs_mxbai, cribl_docs_mxbai
    def _find_additional(prefix):
        """Find additional collection name containing prefix."""
        for name in additional:
            if prefix in name:
                return name
        return None

    return {
        "spl_commands":   _find_additional("spl_command") or "spl_commands_mxbai",
        "spec_files":     secondary,
        "conf_reference": secondary,
        "org_repo":       _find_additional("org_repo") or "org_repo_mxbai",
        "local_docs":     _find_additional("local_doc") or "local_docs_mxbai",
        "cribl_docs":     _find_additional("cribl") or "cribl_docs_mxbai",
        "metadata":       primary,
    }


# Source directories: discovered from settings.paths (single source of truth)
# Each entry: (directory, glob_pattern, collection_label, description, recursive)
def _build_source_dirs():
    """Build source directory list from settings.paths configuration."""
    try:
        from chat_app.settings import get_settings
        paths = get_settings().paths
    except Exception as _exc:  # broad catch — resilience against all failures
        paths = None

    # Use settings.paths when available, fall back to env vars
    if paths:
        docs_root = paths.documents_root
        spl_docs = paths.spl_docs_root or f"{docs_root}/commands"
        spec_root = paths.spec_ingest_root or paths.spec_static_root or f"{docs_root}/specs"
        repo_root = paths.org_repo_root or paths.repo_docs_root or f"{docs_root}/repo"
        local_docs = paths.local_docs_root or f"{docs_root}/pdfs"
        cribl_docs = paths.cribl_docs_root or f"{docs_root}/cribl"
    else:
        docs_root = os.getenv("DOCUMENTS_ROOT", "/app/shared/public/documents")
        spl_docs = os.getenv("SPL_DOCS_ROOT", f"{docs_root}/commands")
        spec_root = os.getenv("SPEC_STATIC_ROOT", f"{docs_root}/specs")
        repo_root = os.getenv("ORG_REPO_ROOT", f"{docs_root}/repo")
        local_docs = os.getenv("LOCAL_DOCS_ROOT", f"{docs_root}/pdfs")
        cribl_docs = os.getenv("CRIBL_DOCS_ROOT", f"{docs_root}/cribl")

    sources = [
        # SPL command docs
        (spl_docs, "*.md", "spl_commands", "SPL command documentation", False),
        ("/app/spl_docs", "*.md", "spl_commands", "SPL command documentation (legacy)", False),
        # Spec files
        (spec_root, "*.spec", "spec_files", "Splunk spec files", False),
        (spec_root, "*.conf", "conf_reference", "Splunk conf reference", False),
        ("/app/ingest_specs", "*.spec", "spec_files", "Splunk spec files (legacy)", False),
        ("/app/ingest_specs", "*.conf", "conf_reference", "Splunk conf reference (legacy)", False),
        # Organization repo (recursive — may have subdirs like repo/splunk, repo/cribl)
        (repo_root, "**/*.*", "org_repo", "Organization configs & docs", True),
        # Local PDFs and docs (recursive — may have subdirs like pdfs/cim, pdfs/metadata)
        (local_docs, "**/*.*", "local_docs", "Local documents & PDFs", True),
        # Cribl docs
        (cribl_docs, "**/*.*", "cribl_docs", "Cribl documentation", True),
        # Metadata
        ("/app/metadata", "*.md", "metadata", "Metadata documents", False),
    ]

    # Deduplicate by (resolved directory, pattern) — keep first occurrence
    seen = set()
    unique = []
    for d, p, l, desc, rec in sources:
        key = (os.path.realpath(d) if os.path.exists(d) else d, p)
        if key not in seen:
            seen.add(key)
            unique.append((d, p, l, desc, rec))

    return unique


# File extensions we can ingest
INGESTABLE_TEXT = {".md", ".conf", ".spec", ".txt", ".json", ".yaml", ".yml", ".csv", ".log"}
INGESTABLE_PDF = {".pdf"}
INGESTABLE_ALL = INGESTABLE_TEXT | INGESTABLE_PDF


# ============================================================================
# Smart chunking with embedding-safe limits
# ============================================================================

def smart_chunk_text(content, fpath, kind="markdown"):
    """
    Chunk text intelligently based on file type, with safe size limits.

    Returns list of (chunk_text, metadata_dict) tuples.
    """
    ext = fpath.suffix.lstrip(".")

    # For .conf/.spec files: use stanza-aware chunking with SAFE limits
    if ext in ("conf", "spec"):
        try:
            from shared.conf_parser import chunk_conf_file
            chunks = chunk_conf_file(
                content, str(fpath),
                max_chunk_size=SAFE_CHUNK_CHARS,
                chunk_overlap=CHUNK_OVERLAP_CHARS,
            )
            # Verify no chunk exceeds limit, split oversized ones
            safe_chunks = []
            for text, meta in chunks:
                if len(text) <= MAX_CHUNK_CHARS:
                    safe_chunks.append((text, meta))
                else:
                    for sub in _force_split(text, MAX_CHUNK_CHARS, CHUNK_OVERLAP_CHARS):
                        safe_chunks.append((sub, dict(meta) if meta else {}))
            return safe_chunks
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            print(f"      conf_parser failed: {e}, using fallback chunking")

    # For markdown/text: use smart_chunker (token-based)
    try:
        from smart_chunker import get_smart_splitter
        from chat_app.settings import get_settings
        settings = get_settings()
        splitter = get_smart_splitter(
            file_type=f".{ext}" if ext else ".md",
            chunk_size=settings.chunking.smart_chunk_tokens,
            chunk_overlap=settings.chunking.smart_chunk_overlap_tokens,
        )
        texts = splitter.split_text(content)
        safe = []
        for t in texts:
            if len(t) <= MAX_CHUNK_CHARS:
                safe.append((t, None))
            else:
                for sub in _force_split(t, MAX_CHUNK_CHARS, CHUNK_OVERLAP_CHARS):
                    safe.append((sub, None))
        return safe
    except ImportError:
        pass

    # Final fallback: simple character-based splitting
    return [(chunk, None) for chunk in _force_split(content, SAFE_CHUNK_CHARS, CHUNK_OVERLAP_CHARS)]


def _force_split(text, max_size, overlap):
    """Force-split text into chunks of max_size with overlap. Last resort."""
    chunks = []
    start = 0
    while start < len(text):
        end = start + max_size
        chunk = text[start:end]
        # Try to break at a newline
        if end < len(text):
            last_nl = chunk.rfind('\n')
            if last_nl > max_size // 3:
                chunk = chunk[:last_nl]
                end = start + last_nl
        chunks.append(chunk.strip())
        start = end - overlap
        if start <= 0 and len(chunks) > 0:
            break
    return [c for c in chunks if c]


def read_pdf_text(fpath):
    """Extract text from a PDF file."""
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(fpath))
        pages = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text() or ""
            if text.strip():
                pages.append(f"[Page {i+1}]\n{text}")
        return "\n\n".join(pages)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        print(f"      PDF read failed: {e}")
        return ""


def build_metadata(fpath, collection_label, chunk_meta=None, chunk_index=None):
    """Build rich metadata for a chunk."""
    import datetime
    meta = {}

    # Base file info
    meta["source"] = fpath.name
    meta["file_path"] = str(fpath)
    meta["file_type"] = fpath.suffix.lstrip(".")
    meta["collection"] = collection_label
    meta["ingestion_timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    if chunk_index is not None:
        meta["chunk_index"] = chunk_index

    # Determine content category and doc_type from path
    path_str = str(fpath).lower()
    fname = fpath.stem.lower()

    if "/repo/" in path_str:
        meta["category"] = "organization"
        meta["doc_type"] = "org_config"
        parts = str(fpath).split("/repo/")
        if len(parts) > 1:
            meta["app_path"] = parts[1]
    elif "/specs/" in path_str:
        meta["category"] = "reference"
        meta["doc_type"] = "spec_file"
        # Extract conf type from filename (e.g., transforms.conf.spec → transforms)
        if fpath.name.endswith(".conf.spec"):
            meta["conf_type"] = fpath.name.replace(".conf.spec", "")
        elif fpath.name.endswith(".spec"):
            meta["conf_type"] = fpath.name.replace(".spec", "")
    elif "/commands/" in path_str or "spl_cmd" in path_str:
        meta["category"] = "spl_command"
        meta["doc_type"] = "spl_command"
        # Extract command name from filename (spl_cmd_stats.md → stats)
        if fname.startswith("spl_cmd_"):
            meta["command_name"] = fname[8:]  # strip "spl_cmd_"
    elif "/pdfs/" in path_str:
        meta["category"] = "documentation"
        meta["doc_type"] = "pdf_doc"
        for subcat in ["cim", "metadata", "optimization"]:
            if f"/{subcat}" in path_str:
                meta["subcategory"] = subcat
                break
    elif "/cribl/" in path_str:
        meta["category"] = "cribl"
        meta["doc_type"] = "cribl_doc"
    elif "/metadata/" in path_str:
        meta["category"] = "metadata"
        meta["doc_type"] = "metadata"
    else:
        meta["category"] = "general"
        meta["doc_type"] = "user_doc"

    # Merge chunk-level metadata (stanza, app_type, app_name from conf_parser)
    if chunk_meta:
        for key in ("stanza", "app_type", "app_name", "app_path", "full_app_path",
                     "conf_file", "file_type_detail", "deployment_tier"):
            if key in chunk_meta and chunk_meta[key] is not None:
                meta[key] = chunk_meta[key]

    # Compute deployment_target from conf_parser if deployment_tier is present
    if meta.get("deployment_tier"):
        try:
            from shared.conf_parser import get_deployment_target
            target = get_deployment_target(meta.get("app_type", ""), meta["deployment_tier"])
            if target:
                meta["deployment_target"] = target
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            pass  # optional module

    return meta


# ============================================================================
# Ingestion with retry
# ============================================================================

def ingest_with_retry(store, texts, metadatas, max_retries=2):
    """
    Add texts to store with retry on embedding errors.
    On failure, splits oversized chunks in half and retries.
    Falls back to one-by-one ingestion if batch retries are exhausted.
    """
    try:
        store.add_texts(texts=texts, metadatas=metadatas)
        return len(texts), 0
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        err_str = str(e).lower()
        if "context length" not in err_str and "input length" not in err_str:
            raise  # Not a chunk size issue

        if max_retries <= 0:
            # Final fallback: ingest one-by-one, truncating failures
            return _ingest_one_by_one(store, texts, metadatas)

        # Find and split oversized chunks, retry
        new_texts = []
        new_metas = []
        for t, m in zip(texts, metadatas):
            if len(t) > SAFE_CHUNK_CHARS:
                halves = _force_split(t, len(t) // 2, CHUNK_OVERLAP_CHARS)
                for h in halves:
                    new_texts.append(h)
                    new_metas.append(dict(m))
            else:
                new_texts.append(t)
                new_metas.append(m)

        return ingest_with_retry(store, new_texts, new_metas, max_retries - 1)


def _ingest_one_by_one(store, texts, metadatas):
    """Fallback: ingest chunks individually, truncating any that exceed token limits."""
    ingested = 0
    skipped = 0
    for t, m in zip(texts, metadatas):
        try:
            store.add_texts(texts=[t], metadatas=[m])
            ingested += 1
        except Exception as _exc:  # broad catch — resilience against all failures
            # Truncate to ~800 chars (well within 512 token limit) and retry once
            truncated = t[:800]
            try:
                store.add_texts(texts=[truncated], metadatas=[m])
                ingested += 1
            except Exception as _exc:  # broad catch — resilience against all failures
                skipped += 1  # Truly unparseable, skip
    return ingested, skipped


# ============================================================================
# ChromaDB helpers
# ============================================================================

def get_chroma_client():
    """Get a direct ChromaDB client for collection management.

    Prefers HttpClient when CHROMA_HTTP_URL is set (matches vectorstore.py),
    falls back to PersistentClient for local-only setups.
    """
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    http_url = os.getenv("CHROMA_HTTP_URL", "").strip()
    if http_url:
        from urllib.parse import urlparse
        parsed = urlparse(http_url if "://" in http_url else f"http://{http_url}")
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or 8001
        return chromadb.HttpClient(
            host=host, port=port,
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
        )
    chroma_dir = os.getenv("CHROMA_DIR", "/app/chroma_store")
    return chromadb.PersistentClient(
        path=chroma_dir,
        settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True),
    )


def list_collections(client):
    """List all collections with their document counts."""
    collections = client.list_collections()
    result = []
    for col in collections:
        name = col if isinstance(col, str) else col.name
        try:
            c = client.get_collection(name)
            count = c.count()
        except Exception as _exc:  # broad catch — resilience at boundary  # narrowed
            count = -1
        result.append((name, count))
    return sorted(result)


def delete_all_collections(client, dry_run=False):
    """Delete all ChromaDB collections."""
    collections = list_collections(client)
    if not collections:
        print("  No collections to delete.")
        return 0

    print(f"  Found {len(collections)} collections:")
    for name, count in collections:
        print(f"    - {name}: {count} documents")

    deleted = 0
    for name, _count in collections:
        if dry_run:
            print(f"    [DRY RUN] Would delete: {name}")
        else:
            try:
                client.delete_collection(name)
                print(f"    Deleted: {name}")
                deleted += 1
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                print(f"    ERROR deleting {name}: {e}")
    return deleted


# ============================================================================
# Per-collection vector store cache
# ============================================================================

_store_cache = {}  # collection_name → Chroma store

def _get_store_for_collection(chroma_collection_name):
    """Get or create a Chroma vector store for a specific collection name."""
    if chroma_collection_name in _store_cache:
        return _store_cache[chroma_collection_name]

    chroma_dir = os.getenv("CHROMA_DIR", "/app/chroma_store")
    store = get_vector_store(
        collection_name=chroma_collection_name,
        persist_directory=chroma_dir,
    )
    _store_cache[chroma_collection_name] = store
    return store


# ============================================================================
# Directory ingestion
# ============================================================================

def ingest_directory(collection_map, directory, pattern, collection_label, description,
                     recursive=False, dry_run=False, skip_fingerprint=False):
    """Ingest files matching pattern from directory into the correct collection."""
    dir_path = Path(directory)
    if not dir_path.exists():
        return 0, 0, 0

    # Collect files
    if recursive:
        files = sorted(f for f in dir_path.rglob(pattern) if f.is_file())
    else:
        files = sorted(f for f in dir_path.glob(pattern) if f.is_file())

    # Filter to ingestable files
    files = [f for f in files if f.suffix.lower() in INGESTABLE_ALL]

    if not files:
        return 0, 0, 0

    # Resolve the ChromaDB collection name for this source label
    chroma_name = collection_map.get(collection_label, collection_map.get("metadata"))

    print(f"\n  === {description} ===")
    print(f"      Dir: {directory}  Pattern: {pattern}  Files: {len(files)}")
    print(f"      → ChromaDB collection: {chroma_name}")

    if not dry_run:
        store = _get_store_for_collection(chroma_name)
    else:
        store = None

    success = 0
    skipped = 0
    errors = 0
    total_chunks = 0

    for i, fpath in enumerate(files, 1):
        try:
            # Read content
            if fpath.suffix.lower() in INGESTABLE_PDF:
                content = read_pdf_text(fpath)
            else:
                content = fpath.read_text(encoding='utf-8', errors='replace')

            if not content.strip():
                skipped += 1
                continue

            # Fingerprint check (incremental mode)
            fp = _fingerprint_bytes(content.encode('utf-8'))
            if not skip_fingerprint and store:
                if has_fingerprint(store, fp):
                    skipped += 1
                    continue
                # File is new or changed — delete old chunks for this source
                # so we don't accumulate stale versions
                if _should_replace(store, fpath.name, fp):
                    _delete_source(store, fpath.name)
                    if i <= 5 or i % 10 == 0:
                        print(f"    [{i}/{len(files)}] {fpath.name}: content changed, replacing old chunks")

            if dry_run:
                print(f"    [{i}/{len(files)}] {fpath.name}: would ingest → {chroma_name}")
                success += 1
                continue

            # Chunk with smart chunking
            chunks_with_meta = smart_chunk_text(content, fpath)

            if not chunks_with_meta:
                skipped += 1
                continue

            # Build texts and metadata
            texts = []
            metadatas = []
            for ci, (chunk_text, chunk_meta) in enumerate(chunks_with_meta):
                if not chunk_text.strip():
                    continue
                meta = build_metadata(fpath, collection_label, chunk_meta, chunk_index=ci)
                meta["fingerprint"] = fp
                texts.append(chunk_text)
                metadatas.append(meta)

            if texts:
                ingested, retry_splits = ingest_with_retry(store, texts, metadatas)
                success += 1
                total_chunks += ingested
                if i % 10 == 0 or i == len(files) or i <= 5:
                    extra = f" (retried {retry_splits})" if retry_splits else ""
                    print(f"    [{i}/{len(files)}] {fpath.name}: {ingested} chunks{extra}", flush=True)
            else:
                skipped += 1

        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            errors += 1
            print(f"    [{i}/{len(files)}] {fpath.name}: ERROR — {e}")
            if os.getenv("INGEST_DEBUG"):
                traceback.print_exc()

    print(f"      Result: {success} files ({total_chunks} chunks), {skipped} skipped, {errors} errors", flush=True)
    return success, errors, total_chunks


# ============================================================================
# Main
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="ChromaDB full reindex script")
    parser.add_argument("--skip-delete", action="store_true", help="Incremental ingest only")
    parser.add_argument("--collection", type=str, help="Only reindex a specific collection label")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--list", action="store_true", help="List current collections and exit")
    parser.add_argument("--debug", action="store_true", help="Show full tracebacks on errors")
    args = parser.parse_args()

    if args.debug:
        os.environ["INGEST_DEBUG"] = "1"

    start = time.time()
    source_dirs = _build_source_dirs()
    collection_map = _get_collection_map()

    print("=" * 72)
    print("ChromaDB Full Reindex")
    print("=" * 72)
    print(f"  CHROMA_DIR:  {os.getenv('CHROMA_DIR', '/app/chroma_store')}")
    print(f"  OLLAMA_HOST: {os.getenv('OLLAMA_HOST', 'localhost')}")
    print(f"  Mode:        {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"  Delete:      {'No (incremental)' if args.skip_delete else 'Yes (full reindex)'}")
    print(f"  Chunk limit: {MAX_CHUNK_CHARS} chars (safe: {SAFE_CHUNK_CHARS})")
    if args.collection:
        print(f"  Collection:  {args.collection} only")
    print()

    # Show collection mapping
    print("  Collection mapping (source label → ChromaDB collection):")
    for label, chroma_name in sorted(collection_map.items()):
        print(f"    {label:16s} → {chroma_name}")
    print()

    # Show discovered source directories
    print("  Source directories:")
    for d, p, l, desc, rec in source_dirs:
        exists = "OK" if Path(d).exists() else "MISSING"
        r = " (recursive)" if rec else ""
        chroma_name = collection_map.get(l, "?")
        print(f"    [{exists:7s}] {l:16s} {d} ({p}){r} → {chroma_name}")
    print()

    # Get ChromaDB client
    client = get_chroma_client()

    # List mode
    if args.list:
        print("Current collections:")
        collections = list_collections(client)
        if not collections:
            print("  (none)")
        for name, count in collections:
            print(f"  - {name}: {count} documents")
        return

    # Step 1: Delete all collections
    if not args.skip_delete:
        print("-" * 72)
        print("Step 1: Deleting all collections")
        print("-" * 72)
        deleted = delete_all_collections(client, dry_run=args.dry_run)
        print(f"\n  Total deleted: {deleted} collections")
        print()

    # Step 2: Re-ingest all source directories (each into its own collection)
    print("-" * 72)
    print("Step 2: Re-ingesting all source directories")
    print("-" * 72)

    total_success = 0
    total_errors = 0
    total_chunks = 0

    # Filter sources if --collection specified
    sources = source_dirs
    if args.collection:
        sources = [(d, p, l, desc, r) for d, p, l, desc, r in sources if l == args.collection]
        if not sources:
            all_labels = sorted(set(l for _, _, l, _, _ in source_dirs))
            print(f"\n  ERROR: Unknown collection '{args.collection}'")
            print(f"  Available: {', '.join(all_labels)}")
            sys.exit(1)

    for directory, pattern, label, description, recursive in sources:
        s, e, c = ingest_directory(
            collection_map, directory, pattern, label, description,
            recursive=recursive,
            dry_run=args.dry_run,
            skip_fingerprint=not args.skip_delete,
        )
        total_success += s
        total_errors += e
        total_chunks += c

    elapsed = time.time() - start

    # Step 3: Verify
    print()
    print("-" * 72)
    print("Step 3: Verification")
    print("-" * 72)

    if not args.dry_run:
        collections = list_collections(client)
        print(f"\n  ChromaDB collections ({len(collections)}):")
        total_docs = 0
        for name, count in collections:
            print(f"    - {name}: {count} documents")
            total_docs += max(count, 0)
        print(f"\n  Total documents across all collections: {total_docs}")

    # Step 4: Rebuild Knowledge Graph
    print()
    print("-" * 72)
    print("Step 4: Knowledge Graph Rebuild")
    print("-" * 72)

    if not args.dry_run:
        try:
            from chat_app.knowledge_graph import rebuild_knowledge_graph
            kg = rebuild_knowledge_graph()
            stats = kg.get_stats()
            print(f"  Knowledge graph rebuilt: {stats['total_entities']} entities, {stats['total_relationships']} relationships")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            print(f"  Knowledge graph rebuild failed (non-fatal): {exc}")
    else:
        print("  Skipped (dry run)")

    # Record metrics for dashboard counters
    if not args.dry_run:
        try:
            from chat_app.health_monitor import get_internal_metrics
            get_internal_metrics().increment("documents_ingested", total_success)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            pass  # optional module

    print()
    print("=" * 72)
    print("Reindex Complete")
    print("=" * 72)
    print(f"  Files ingested: {total_success}")
    print(f"  Total chunks:   {total_chunks}")
    print(f"  Errors:         {total_errors}")
    print(f"  Elapsed:        {elapsed:.1f}s")
    print()

    if total_errors > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
