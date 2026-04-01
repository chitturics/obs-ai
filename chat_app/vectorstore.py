"""Vectorstore public API — search, ingestion helpers, URL mapping, and re-exports.

Sub-modules:
  vectorstore_init.py          — embedding model, get_vector_store, ensure_* singletons
  vectorstore_fingerprint.py   — fingerprint deduplication helpers
  vectorstore_collections.py   — collection listing, auto-discovery, additional stores
  vectorstore_legacy_search.py — legacy sequential search (fallback)
  vectorstore_ingest.py        — bulk ingestion helpers
  vectorstore_search.py        — parallel search implementation
"""
import asyncio
import os
import re
import tempfile
import logging
from io import BytesIO
from typing import Dict, List, Optional, Tuple

from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pypdf import PdfReader

try:
    from langchain_community.document_loaders import PyPDFLoader  # type: ignore
except (ImportError, ModuleNotFoundError):
    PyPDFLoader = None
try:
    from bs4 import BeautifulSoup  # type: ignore
except (ImportError, ModuleNotFoundError):
    BeautifulSoup = None
try:
    import cloudscraper  # type: ignore
except (ImportError, ModuleNotFoundError):
    cloudscraper = None
try:
    from playwright.sync_api import sync_playwright  # type: ignore
except (ImportError, ModuleNotFoundError):
    sync_playwright = None
try:
    from puppeteer import puppeteer_fetch  # type: ignore
except (ImportError, ModuleNotFoundError):
    puppeteer_fetch = None

from chat_app.settings import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Re-exports from sub-modules (backward compatibility — existing imports unchanged)
# ---------------------------------------------------------------------------
from chat_app.vectorstore_init import (  # noqa: F401
    _ensure_model_available,
    InstructionPrefixEmbeddings,
    _embedding_model,
    get_embeddings_model,
    _ensure_collection_exists,
    get_vector_store,
    ensure_vector_store,
    ensure_secondary_store,
    ensure_feedback_store,
    CHROMA_DIR,
    DEFAULT_EMBED_MODEL,
    DEFAULT_COLLECTION,
    COLLECTION_NAME,
    CHROMA_HTTP_URL,
    SECONDARY_COLLECTION,
    SECONDARY_DIR,
    SECONDARY_EMBED_MODEL,
    FEEDBACK_COLLECTION,
)
from chat_app.vectorstore_fingerprint import (  # noqa: F401
    _fingerprint_bytes,
    has_fingerprint,
    get_existing_fingerprints,
    _should_replace,
    _delete_source,
    fingerprint_file,
    fingerprint_bytes,
)
from chat_app.vectorstore_collections import (  # noqa: F401
    _list_all_collections,
    _resolve_auto_collections,
    ensure_additional_stores,
    ADDITIONAL_COLLECTIONS,
    EXCLUDE_COLLECTIONS,
    _AUTO_COLLECTIONS,   # mutable list — same object as vectorstore_collections._AUTO_COLLECTIONS
    _ADDITIONAL_STORES,  # type: ignore[attr-defined]  # noqa: F401
)
# Also expose sub-module singleton names for backward-compat test access.
# These are *imported references*; setting them here only affects this namespace,
# so callers that need to reset singletons should target the sub-modules directly.
from chat_app.vectorstore_init import (  # noqa: F401
    _VECTOR_STORE,    # type: ignore[attr-defined]
    _SECONDARY_STORE, # type: ignore[attr-defined]
    _FEEDBACK_STORE,  # type: ignore[attr-defined]
)

# ---------------------------------------------------------------------------
# Centralized settings (chunk sizes, paths)
# ---------------------------------------------------------------------------
_cfg = get_settings()

# Conservative chunk sizes to prevent embedding context length errors
# mxbai-embed-large max: 512 tokens ~= 2048 chars (safe estimate: 1500 chars)
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))
PDF_CHUNK_SIZE = int(os.getenv("PDF_CHUNK_SIZE", "500"))
PDF_CHUNK_OVERLAP = int(os.getenv("PDF_CHUNK_OVERLAP", "100"))
CODE_CHUNK_SIZE = int(os.getenv("CODE_CHUNK_SIZE", "500"))
CODE_CHUNK_OVERLAP = int(os.getenv("CODE_CHUNK_OVERLAP", "100"))
CHAT_CHUNK_SIZE = int(os.getenv("CHAT_CHUNK_SIZE", str(CODE_CHUNK_SIZE)))
CHAT_CHUNK_OVERLAP = int(os.getenv("CHAT_CHUNK_OVERLAP", str(CODE_CHUNK_OVERLAP)))
MAX_FINAL_CHUNK_SIZE = int(os.getenv("MAX_FINAL_CHUNK_SIZE", "1500"))
CHROMA_SECONDARY_HTTP_URL = _cfg.chroma.secondary_http_url or CHROMA_HTTP_URL
# Paths
DOCS_BASE_URL = os.getenv("DOCS_BASE_URL", "/public")
SPECS_PUBLIC_PATH = os.getenv("SPECS_PUBLIC_PATH", "/public/ingest_specs")
LOCAL_DOCS_ROOT = os.getenv("LOCAL_DOCS_ROOT", "/app/public/documents/pdfs")
REPO_DOCS_ROOT = os.getenv("REPO_DOCS_ROOT", "/app/docs")
ORG_REPO_ROOT = _cfg.paths.org_repo_root
SPEC_SRC_ROOT = os.getenv("SPEC_SRC_ROOT", "/tmp/specs")
SPEC_STATIC_ROOT = os.getenv("SPEC_STATIC_ROOT", "/app/public/documents/specs")
SPEC_INGEST_ROOT = os.getenv("SPEC_INGEST_ROOT", "/app/public/documents/specs")
SPL_DOCS_ROOT = os.getenv("SPL_DOCS_ROOT", "/app/public/documents/commands")
FEEDBACK_ROOT = os.getenv("FEEDBACK_ROOT", "/app/public/feedback")

# Import canonical allowed-lists (re-exported for backward compatibility)
try:
    from splunk_constants import ALLOWED_SEARCH_COMMANDS, ALLOWED_CONF_FILES  # noqa: E402, F401
except ImportError:
    from chat_app.splunk_constants import ALLOWED_SEARCH_COMMANDS, ALLOWED_CONF_FILES  # noqa: E402, F401


# ---------------------------------------------------------------------------
# Persistence helper
# ---------------------------------------------------------------------------

def _persist(store: Chroma) -> None:
    """Chroma client persistence changed across versions. Try available hooks,
    but don't crash if not supported.
    """
    if store is None:
        return
    try:
        if hasattr(store, "persist"):
            store.persist()  # type: ignore[attr-defined]
        elif hasattr(store, "_client") and hasattr(store._client, "persist"):
            store._client.persist()  # type: ignore[attr-defined]
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"Persist skipped: {exc}")


# ---------------------------------------------------------------------------
# URL mapping
# ---------------------------------------------------------------------------

def _public_url_for_path(path: str) -> Optional[str]:
    """Map a local file path to a public URL (served by the static server)."""
    try:
        norm = os.path.abspath(path).replace("\\", "/")

        def _normalize(base: str) -> str:
            if not base.startswith(("http://", "https://", "/")):
                base = f"/{base}"
            return base.rstrip("/")

        docs_base = _normalize(DOCS_BASE_URL or "/public")
        specs_base = _normalize(SPECS_PUBLIC_PATH or "/public/ingest_specs")
        local_root = os.path.abspath(LOCAL_DOCS_ROOT).replace("\\", "/")
        repo_root = os.path.abspath(REPO_DOCS_ROOT).replace("\\", "/")
        org_repo_root = os.path.abspath(ORG_REPO_ROOT).replace("\\", "/")
        spec_src_root = os.path.abspath(SPEC_SRC_ROOT).replace("\\", "/")
        spec_static_root = os.path.abspath(SPEC_STATIC_ROOT).replace("\\", "/")
        spec_ingest_root = os.path.abspath(SPEC_INGEST_ROOT).replace("\\", "/")
        spl_docs_root = os.path.abspath(SPL_DOCS_ROOT).replace("\\", "/")
        feedback_root = os.path.abspath(FEEDBACK_ROOT).replace("\\", "/")
        basename = os.path.basename(norm)
        if basename.endswith((".conf", ".conf.spec")) and basename.replace(".spec", "") not in ALLOWED_CONF_FILES:
            return None
        if norm.startswith(local_root):
            rel = norm[len(local_root):].lstrip("/")
            return f"{docs_base}/documents/{rel}"
        if norm.startswith(repo_root):
            rel = norm[len(repo_root):].lstrip("/")
            return f"{docs_base}/docs/{rel}"
        if norm.startswith(org_repo_root):
            rel = norm[len(org_repo_root):].lstrip("/")
            return f"{docs_base}/documents/repo/{rel}"
        if norm.startswith(spec_src_root):
            rel = norm[len(spec_src_root):].lstrip("/")
            return f"{specs_base}/{rel}"
        if norm.startswith(spec_static_root):
            rel = norm[len(spec_static_root):].lstrip("/")
            return f"{specs_base}/{rel}"
        if norm.startswith(spec_ingest_root):
            rel = norm[len(spec_ingest_root):].lstrip("/")
            return f"{specs_base}/{rel}"
        if norm.startswith(spl_docs_root):
            rel = norm[len(spl_docs_root):].lstrip("/")
            base = os.path.basename(norm)
            if base.startswith("spl_cmd_") and base.endswith(".md"):
                cmd = base[len("spl_cmd_"):-3]
                if cmd not in ALLOWED_SEARCH_COMMANDS:
                    return None
            return f"{docs_base}/spl_docs/{rel}"
        if norm.startswith(feedback_root):
            rel = norm[len(feedback_root):].lstrip("/")
            return f"{docs_base}/feedback/{rel}"
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        return None
    return None


# ---------------------------------------------------------------------------
# Chunking helpers
# ---------------------------------------------------------------------------

def _choose_chunk_params(kind: str | None = None, ext: str | None = None) -> tuple[int, int]:
    """Pick chunk size/overlap based on content type."""
    ext = (ext or "").lower()
    if kind == "pdf" or ext == "pdf":
        return PDF_CHUNK_SIZE, PDF_CHUNK_OVERLAP
    if kind == "chat":
        return CHAT_CHUNK_SIZE, CHAT_CHUNK_OVERLAP
    if ext in {"conf", "spec", "py", "js", "ts", "toml", "yaml", "yml", "ini", "cfg"}:
        return CODE_CHUNK_SIZE, CODE_CHUNK_OVERLAP
    return CHUNK_SIZE, CHUNK_OVERLAP


def _split_text_simple(text_blob: str, *, kind: str | None = None, ext: str | None = None) -> List[str]:
    """Simple text splitting — returns just chunk texts (backward compatible)."""
    try:
        from smart_chunker import get_smart_splitter
        file_type = f".{ext}" if ext and not ext.startswith(".") else ext
        splitter = get_smart_splitter(
            file_type=file_type,
            chunk_size=_cfg.chunking.smart_chunk_tokens,
            chunk_overlap=_cfg.chunking.smart_chunk_overlap_tokens,
        )
        return splitter.split_text(text_blob)
    except ImportError:
        logger.warning("smart_chunker not available, using character-based chunking")
        chunk_size, chunk_overlap = _choose_chunk_params(kind=kind, ext=ext)
        splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        return splitter.split_text(text_blob)


def _split_text(
    text_blob: str,
    *,
    kind: str | None = None,
    ext: str | None = None,
    filename: str = "",
    file_path: str | None = None,
) -> List[Tuple[str, Dict | None]]:
    """Split text with special handling for .conf files (stanza-aware chunking).

    Returns list of (chunk_text, metadata_dict | None) tuples.
    """
    results = None
    if ext in ("conf", "spec") and file_path:
        try:
            from shared.conf_parser import chunk_conf_file
            chunks_with_metadata = chunk_conf_file(
                text_blob, file_path,
                max_chunk_size=_cfg.chunking.conf_max_chunk_size,
                chunk_overlap=_cfg.chunking.conf_chunk_overlap,
            )
            logger.info(f"[CONF_PARSER] Chunked {filename}: {len(chunks_with_metadata)} chunks with stanza metadata")
            results = chunks_with_metadata
        except ImportError:
            logger.warning("[CONF_PARSER] conf_parser not available, using default chunking")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning(f"[CONF_PARSER] Error parsing {filename}: {e}, falling back to default chunking")

    if results is None:
        chunks = _split_text_simple(text_blob, kind=kind, ext=ext)
        results = [(chunk, None) for chunk in chunks]

    safe = []
    for text, meta in results:
        if len(text) <= MAX_FINAL_CHUNK_SIZE:
            safe.append((text, meta))
        else:
            start = 0
            while start < len(text):
                end = start + MAX_FINAL_CHUNK_SIZE
                piece = text[start:end]
                if end < len(text):
                    nl = piece.rfind('\n')
                    if nl > MAX_FINAL_CHUNK_SIZE // 3:
                        piece = piece[:nl]
                        end = start + nl
                if piece.strip():
                    safe.append((piece.strip(), dict(meta) if meta else None))
                start = end
    return safe


def _clean_text(text: str) -> str:
    """Strip common header/footer/PII noise (emails, generated-for, copyright lines)."""
    text = re.sub(r"(?<![=@/])\b[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}\b(?![^\s])", "[redacted]", text)
    cleaned_lines = []
    for line in text.splitlines():
        low = line.lower()
        if "listen to your data" in low:
            continue
        stripped_low = low.strip()
        if stripped_low.startswith("#") or not stripped_low or "=" not in stripped_low:
            if any(key in low for key in ["generated for", "not for distribution", "all rights reserved"]):
                continue
            if stripped_low.startswith(("# copyright", "# ©", "copyright ", "©")):
                continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def _split_conf_spec_sections(text_blob: str, file_name: str) -> List[dict]:
    """Split conf/spec files by stanza blocks like [stanza]."""
    sections: List[dict] = []
    current_header = "global"
    current_lines: List[str] = []
    for line in text_blob.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]") and len(stripped) > 2:
            if current_lines:
                sections.append({"stanza": current_header, "text": "\n".join(current_lines).strip()})
            current_header = stripped.strip("[]").strip() or "unnamed"
            current_lines = [line]
        else:
            current_lines.append(line)
    if current_lines:
        sections.append({"stanza": current_header, "text": "\n".join(current_lines).strip()})
    return [s for s in sections if s.get("text")]


def _with_contextual_previews(chunks: List[str], window: int = 100) -> List[tuple[str, dict]]:
    """Add small previews from neighboring chunks to give the model local context."""
    contextual: List[tuple[str, dict]] = []
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        prev_tail = chunks[i - 1][-window:] if i > 0 else ""
        next_head = chunks[i + 1][:window] if i + 1 < total else ""
        meta = {"chunk_index": i, "total_chunks": total}
        body = chunk
        if prev_tail or next_head:
            body = "\n".join([
                ("[prev...]" + prev_tail) if prev_tail else "",
                chunk,
                ("[next...]" + next_head) if next_head else "",
            ]).strip()
        contextual.append((body, meta))
    return contextual


def _pdf_bytes_to_chunks(pdf_bytes: bytes) -> List[str]:
    """Robust PDF parsing: prefer PyPDFLoader when available; fallback to PdfReader."""
    chunk_size, chunk_overlap = _choose_chunk_params(kind="pdf", ext="pdf")
    if PyPDFLoader is not None:
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                tmp.write(pdf_bytes)
                tmp_path = tmp.name
            try:
                loader = PyPDFLoader(tmp_path)
                docs = loader.load()
                splitter = RecursiveCharacterTextSplitter(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
                docs = splitter.split_documents(docs)
                chunks = [_clean_text(d.page_content or "") for d in docs if d.page_content]
                return [c.strip() for c in chunks if c and c.strip()]
            finally:
                try:
                    os.remove(tmp_path)
                except (OSError, ValueError) as _exc:
                    logger.debug("%s", _exc)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            print(f"[vectorstore] PyPDFLoader failed, falling back: {exc}")
    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        joined = "\n\n".join(p.extract_text() or "" for p in reader.pages)
        chunks = _split_text_simple(joined, kind="pdf", ext="pdf")
        chunks = [_clean_text(c) for c in chunks if c]
        return [c.strip() for c in chunks if c and c.strip()]
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        print(f"[vectorstore] PdfReader failed: {exc}")
        return []


def _playwright_fetch(url: str, headers: dict | None = None, timeout_ms: int = 30000) -> tuple[str, str]:
    """Fetch a page using Playwright (headless Chromium). Returns (content_type, html_text)."""
    if sync_playwright is None:
        raise RuntimeError("playwright not installed")
    ua = os.getenv(
        "PLAYWRIGHT_USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    )
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--disable-blink-features=AutomationControlled"])
        try:
            page = browser.new_page(
                user_agent=ua,
                viewport={"width": 1366, "height": 768},
                locale="en-US",
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9", **(headers or {})},
            )
            page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            page.wait_for_timeout(2000)
            content = page.content()
            ctype = page.evaluate("() => document.contentType") or "text/html"
            return str(ctype), content
        finally:
            browser.close()


# ---------------------------------------------------------------------------
# Search — delegates to parallel or legacy implementation
# ---------------------------------------------------------------------------

def search_similar_chunks(
    store: Chroma,
    query: str,
    k: int = 4,
    profile: str = None,
    weight_map_override: Optional[Dict[str, int]] = None,
    user_settings: Optional[Dict] = None,
) -> list[dict]:
    """Retrieve similar chunks with profile-based weighting strategies.

    Delegates to vectorstore_search.search_similar_chunks_parallel (fast path,
    50-70% faster for multi-collection queries), falling back to the legacy
    sequential implementation in vectorstore_legacy_search.

    Returns:
        List of dicts with keys: text, source, source_url, collection, score, context
    """
    logger.info(f"[VECTORSTORE] search_similar_chunks query='{query[:100]}' k={k} profile={profile}")
    user_settings = user_settings or {}

    try:
        from vectorstore_search import search_similar_chunks_parallel
        try:
            asyncio.get_running_loop()
            logger.info("[VECTORSTORE] Using parallel search (in executor)")
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(
                    asyncio.run,
                    search_similar_chunks_parallel(
                        store, query, k, profile,
                        get_surrounding_chunks_func=get_surrounding_chunks,
                        public_url_mapper=_public_url_for_path,
                        weight_map_override=weight_map_override,
                        user_settings=user_settings,
                    )
                )
                return future.result()
        except RuntimeError:
            logger.info("[VECTORSTORE] Using parallel search (new event loop)")
            return asyncio.run(
                search_similar_chunks_parallel(
                    store, query, k, profile,
                    get_surrounding_chunks_func=get_surrounding_chunks,
                    public_url_mapper=_public_url_for_path,
                    weight_map_override=weight_map_override,
                    user_settings=user_settings,
                )
            )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.warning(f"[VECTORSTORE] Parallel search unavailable, using legacy: {e}")

    # Fallback to legacy sequential search
    from chat_app.vectorstore_legacy_search import search_similar_chunks_legacy
    return search_similar_chunks_legacy(
        store, query, k, profile, weight_map_override, user_settings,
        get_surrounding_chunks_func=get_surrounding_chunks,
        public_url_mapper=_public_url_for_path,
    )


# ---------------------------------------------------------------------------
# Chunk retrieval by metadata filter
# ---------------------------------------------------------------------------

def _get_by_filter(store: Chroma, where: dict, limit: int = 4, label: Optional[str] = None) -> List[str]:
    """Generic fetch helper from underlying collection."""
    if not store or not where:
        return []
    try:
        coll = getattr(store, "_collection", None)
        if coll is None:
            print("[vectorstore] no underlying collection to fetch by source")
            return []
        res = coll.get(where=where, limit=limit)
        docs = res.get("documents") or []
        flat = []
        for d in docs:
            if isinstance(d, list):
                flat.extend(d)
            elif isinstance(d, str):
                flat.append(d)
        cleaned = []
        for text in flat:
            snippet = (text or "").strip()
            if len(snippet) > 600:
                snippet = snippet[:600] + " ..."
            if snippet:
                prefix = f"{label}\n" if label else ""
                cleaned.append(f"{prefix}{snippet}")
        return cleaned[:limit]
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        print(f"[vectorstore] _get_by_filter failed: {exc}")
        return []


def get_chunks_by_source(store: Chroma, source: str, limit: int = 4) -> List[str]:
    if not source:
        return []
    return _get_by_filter(store, {"source": source}, limit=limit, label=f"Source: {source}")


def get_chunks_by_fingerprint(store: Chroma, fingerprint: str, limit: int = 4) -> List[str]:
    if not fingerprint:
        return []
    return _get_by_filter(store, {"fingerprint": fingerprint}, limit=limit, label=None)


def get_surrounding_chunks(store: Chroma, doc_metadata: dict, context_window: int = 2) -> List[Tuple[str, dict]]:
    """Retrieve surrounding chunks (±context_window) for better context.

    Returns list of (chunk_text, metadata) tuples sorted by chunk_index.
    """
    try:
        source = doc_metadata.get("source")
        fingerprint = doc_metadata.get("fingerprint")
        chunk_index = doc_metadata.get("chunk_index", 0)

        if not source and not fingerprint:
            return []

        filter_dict = {}
        if fingerprint:
            filter_dict["fingerprint"] = fingerprint
        elif source:
            filter_dict["source"] = source

        try:
            coll = store._collection
            results = coll.get(where=filter_dict, limit=100, include=["metadatas", "documents"])
            if not results or not results.get("documents"):
                return []

            chunks_with_index = []
            for doc_text, meta in zip(results["documents"], results["metadatas"]):
                idx = meta.get("chunk_index", 0)
                chunks_with_index.append((idx, doc_text, meta))

            chunks_with_index.sort(key=lambda x: x[0])

            surrounding = [
                (text, meta)
                for idx, text, meta in chunks_with_index
                if abs(idx - chunk_index) <= context_window
            ]
            surrounding.sort(key=lambda x: x[1].get("chunk_index", 0))
            logger.info(f"[CONTEXT] Retrieved {len(surrounding)} surrounding chunks for chunk_index={chunk_index}")
            return surrounding

        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning(f"[CONTEXT] Failed to get surrounding chunks: {e}")
            return []

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.error(f"[CONTEXT] Error in get_surrounding_chunks: {e}")
        return []


# ---------------------------------------------------------------------------
# Backward-compat alias
# ---------------------------------------------------------------------------
get_vectorstore = ensure_vector_store
