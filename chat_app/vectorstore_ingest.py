"""
Document ingestion into ChromaDB vector stores.

Handles indexing of files, URLs, text blocks, and feedback Q&A pairs.
Extracted from vectorstore.py to separate ingestion from retrieval concerns.
"""
import html
import os
import re
import shutil
import logging
from typing import Optional, Tuple

from langchain_chroma import Chroma

from vectorstore import (
    _clean_text,
    _delete_source,
    _fingerprint_bytes,
    _pdf_bytes_to_chunks,
    _persist,
    _playwright_fetch,
    _public_url_for_path,
    _should_replace,
    _split_text,
    _split_text_simple,
    _with_contextual_previews,
    ensure_feedback_store,
    has_fingerprint,
)


logger = logging.getLogger(__name__)

# Optional dependencies (same as vectorstore.py)
try:
    from bs4 import BeautifulSoup  # type: ignore
except (ImportError, ModuleNotFoundError):  # optional dep — graceful fallback
    BeautifulSoup = None
try:
    import cloudscraper  # type: ignore
except (ImportError, ModuleNotFoundError):  # optional dep — graceful fallback
    cloudscraper = None
try:
    from playwright.sync_api import sync_playwright  # type: ignore
except (ImportError, ModuleNotFoundError):  # optional dep — graceful fallback
    sync_playwright = None
try:
    from puppeteer import puppeteer_fetch  # type: ignore
except (ImportError, ModuleNotFoundError):  # optional dep — graceful fallback
    puppeteer_fetch = None

import requests

# ---------------------------------------------------------------------------
# Interaction / Feedback note ingestion
# ---------------------------------------------------------------------------

def add_interaction_to_memory(
    store: Chroma,
    question: str,
    answer: str,
    username: str,
    thread_id: str | None,
) -> None:
    if not store:
        return
    # Disabled: only persist when explicitly liked/feedback
    return


def add_feedback_note_to_memory(
    store: Chroma,
    feedback,
    username: str,
    thread_id: str | None,
    source_url: str | None = None,
    source_name: str | None = None,
) -> None:
    if not store or feedback is None:
        return
    feedback_id = getattr(feedback, "for_id", None) or getattr(feedback, "id", None) or getattr(
        feedback, "message_id", None
    )
    note = feedback.comment or ""
    text = (
        f"Feedback from {username} | Thread:{thread_id} | Message:{feedback_id} "
        f"| Value:{getattr(feedback, 'value', None)} | Comment:{note}"
    )
    metadata = {"kind": "feedback", "username": username or "anonymous"}
    if source_url:
        metadata["source_url"] = source_url
    if source_name:
        metadata["source"] = source_name
    store.add_texts([text], metadatas=[metadata])
    _persist(store)


# ---------------------------------------------------------------------------
# URL ingestion
# ---------------------------------------------------------------------------

def index_url_to_memory(store: Chroma, url: str) -> Tuple[bool, str | None]:
    if not store:
        return False, "Vector store not ready"
    headers = {
        "User-Agent": os.getenv(
            "USER_AGENT",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }
    # Minimal SharePoint support
    if "sharepoint.com" in url.lower():
        token = os.getenv("SHAREPOINT_BEARER_TOKEN")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        else:
            return False, "SHAREPOINT_BEARER_TOKEN is not set for SharePoint URL"

    raw_bytes, html_text, content_type, used_playwright = _fetch_url(url, headers)
    if raw_bytes is None:
        return False, html_text  # html_text holds the error message

    try:
        text_blob = ""
        fingerprint = _fingerprint_bytes(raw_bytes)

        if has_fingerprint(store, fingerprint):
            logger.info(f"Skipping {url} (fingerprint already indexed)")
            return True, "Already indexed"

        lower_url = url.lower()
        ext = ""
        if "." in lower_url.rsplit("/", 1)[-1]:
            ext = lower_url.rsplit(".", 1)[-1]
        is_pdf = "pdf" in content_type or ext == "pdf"
        is_html = "html" in content_type or ext in {"html", "htm"}

        if is_pdf:
            chunks = _pdf_bytes_to_chunks(raw_bytes)
            if not chunks:
                return False, "Failed to parse PDF"
        elif is_html:
            text_blob = _extract_text_from_html(html_text)
        else:
            try:
                text_blob = raw_bytes.decode("utf-8", errors="ignore")
            except Exception as _exc:  # broad catch — resilience against all failures
                text_blob = html_text or ""
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error(f"Fetch/parse failed for {url}: {exc}")
        return False, str(exc)

    if not is_pdf:
        text_blob = (text_blob or "").strip()
        if not text_blob:
            return False, "No text extracted from document"

        # Retry with headless browser if blocked
        if "unsupported browser" in text_blob.lower():
            text_blob = _retry_headless(url, headers, text_blob)

        ext_hint = "html" if "html" in content_type else None
        chunks = _split_text_simple(text_blob, ext=ext_hint)
        if not chunks:
            return False, "No content to index"

    source_meta = {"kind": "url", "source": url, "fingerprint": fingerprint}
    if _should_replace(store, url, fingerprint):
        _delete_source(store, url)
    else:
        return True, {"success": True, "url": url, "chunks": 0, "skipped": True, "reason": "content unchanged"}
    metadatas = [dict(source_meta) for _ in chunks]
    try:
        store.add_texts(chunks, metadatas=metadatas)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error(f"add_texts failed for {url}: {exc}")
        return False, f"Embedding failed: {exc}"
    _persist(store)

    logger.info(f"Indexed url {url} chunks={len(chunks)}")
    return True, {
        "success": True,
        "url": url,
        "chunks": len(chunks),
        "preview": chunks[0][:200] if chunks else "",
        "type": "pdf" if is_pdf else ("html" if is_html else "text"),
        "content_type": content_type,
    }


def _fetch_url(url: str, headers: dict) -> Tuple[Optional[bytes], str, str, bool]:
    """
    Fetch URL content trying requests → cloudscraper → playwright → puppeteer.
    Returns (raw_bytes, html_text, content_type, used_playwright) or (None, error_msg, '', False).
    """
    # Try plain requests
    try:
        resp = requests.get(url, headers=headers, timeout=30)
        if resp.status_code >= 400 or "unsupported browser" in resp.text.lower():
            raise requests.HTTPError(f"Status {resp.status_code}")
        resp.raise_for_status()
        return resp.content, resp.text, resp.headers.get("content-type", "").lower(), False
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as _exc:
        logger.debug("Direct HTTP fetch failed for %s, trying cloudscraper: %s", url, _exc)

    # Try cloudscraper
    if cloudscraper is not None:
        try:
            scraper = cloudscraper.create_scraper()
            resp = scraper.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.content, resp.text, resp.headers.get("content-type", "").lower(), False
        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

    # Try playwright
    if sync_playwright is not None:
        try:
            ctype, html_text = _playwright_fetch(url, headers=headers, timeout_ms=30000)
            raw = html_text.encode("utf-8", errors="ignore")
            return raw, html_text, str(ctype).lower(), True
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

    # Try puppeteer
    if shutil.which("node") is not None and puppeteer_fetch:
        try:
            ctype, html_text = puppeteer_fetch(url, headers=headers, timeout_ms=30000)
            raw = html_text.encode("utf-8", errors="ignore")
            return raw, html_text, str(ctype).lower(), False
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            return None, str(exc), "", False

    return None, f"All fetch methods failed for {url}", "", False


def _extract_text_from_html(html_text: str) -> str:
    """Extract text from HTML using BeautifulSoup or regex fallback."""
    if BeautifulSoup:
        try:
            soup = BeautifulSoup(html_text, "html.parser")
            for tag in soup(["script", "style", "noscript", "header", "footer"]):
                tag.decompose()
            return soup.get_text(" ", strip=True)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass
    # Regex fallback
    text = re.sub(r"<script[^>]*>.*?</script>", " ", html_text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", " ", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    return html.unescape(text)


def _retry_headless(url: str, headers: dict, current_text: str) -> str:
    """Retry fetch with headless browser if current text shows a block page."""
    if sync_playwright is not None:
        try:
            ctype, html_text = _playwright_fetch(url, headers=headers, timeout_ms=30000)
            return html_text
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass
    if shutil.which("node") is not None and puppeteer_fetch:
        try:
            ctype, html_text = puppeteer_fetch(url, headers=headers, timeout_ms=30000)
            return html_text
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass
    return current_text


# ---------------------------------------------------------------------------
# Feedback Q&A ingestion
# ---------------------------------------------------------------------------

def add_feedback_qa_to_memory(
    question: str,
    answer: str,
    username: str = "unknown",
    feedback_file: str | None = None,
    docs_base_url: str | None = None,
) -> Tuple[bool, str | None]:
    """Add a liked Q&A pair to the feedback collection (highest priority)."""
    feedback_store = ensure_feedback_store()
    if not feedback_store:
        return False, "Feedback store not available"

    if not question or not answer:
        return False, "Question and answer required"

    qa_text = f"Question: {question.strip()}\n\nAnswer: {answer.strip()}"
    fingerprint = _fingerprint_bytes(qa_text.encode("utf-8", errors="ignore"))
    source = f"feedback://{username}/{fingerprint[:16]}"

    if has_fingerprint(feedback_store, fingerprint):
        logger.info("Q&A already in feedback collection (skipping duplicate)")
        return True, "Already indexed"

    metadata = {
        "kind": "feedback",
        "source": source,
        "fingerprint": fingerprint,
        "question": question[:500],
        "username": username,
        "chunk_id": f"{fingerprint}-0",
        "chunk_index": 0,
    }

    if feedback_file and docs_base_url:
        metadata["source_url"] = f"{docs_base_url.rstrip('/')}/feedback/{feedback_file}"

    try:
        feedback_store.add_texts([qa_text], metadatas=[metadata])
        _persist(feedback_store)
        logger.info(f"Added Q&A to feedback collection: {question[:50]}...")
        return True, None
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error(f"Failed to add Q&A to feedback collection: {exc}")
        return False, str(exc)


# ---------------------------------------------------------------------------
# Text block ingestion
# ---------------------------------------------------------------------------

def index_text_to_memory(store: Chroma, text: str, label: str = "read_text") -> Tuple[bool, str | None]:
    """Index an arbitrary text payload into the vector store."""
    if not store:
        return False, "Vector store not ready"
    if not text or not text.strip():
        return False, "No text provided"

    normalized = text.strip()
    fingerprint = _fingerprint_bytes(normalized.encode("utf-8", errors="ignore"))
    source = f"read_text://{label}"
    source_meta = {"kind": "text", "source": source, "fingerprint": fingerprint}

    force_reindex = os.getenv("FORCE_REINDEX", "0") == "1"
    if has_fingerprint(store, fingerprint) and not force_reindex:
        return True, "Already indexed"

    if _should_replace(store, source, fingerprint):
        _delete_source(store, source)
    else:
        return True, "Already indexed (content unchanged)"

    chunks = _split_text_simple(normalized, kind="text")
    chunks = [_clean_text(c) for c in chunks if c]
    if not chunks:
        return False, "No chunks generated from text"

    metadatas = []
    for idx, chunk in enumerate(chunks):
        meta = dict(source_meta)
        meta["chunk_id"] = f"{fingerprint}-{idx}"
        meta["chunk_index"] = idx
        meta["chunk_preview"] = chunk[:200]
        metadatas.append(meta)

    try:
        store.add_texts(chunks, metadatas=metadatas)
        _persist(store)
        logger.info(f"Indexed read_text {label} chunks={len(chunks)}")
        return True, {
            "success": True,
            "label": label,
            "chunks": len(chunks),
            "preview": chunks[0][:200] if chunks else "",
            "type": "text",
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error(f"Failed to add text chunk for {source}: {exc}")
        return False, str(exc)


# ---------------------------------------------------------------------------
# File ingestion
# ---------------------------------------------------------------------------

def index_file_to_memory(store: Chroma, path: str) -> Tuple[bool, str | None]:
    """
    Load a local file into the vector store based on extension.
    Supported: pdf, html/htm, conf/spec (stanza-aware), txt.
    """
    if not store:
        return False, "Vector store not ready"
    if not os.path.exists(path):
        return False, f"File not found: {path}"

    with open(path, "rb") as fb:
        raw_bytes = fb.read()
    fingerprint = _fingerprint_bytes(raw_bytes)
    if has_fingerprint(store, fingerprint):
        logger.info(f"Skipping {path} (fingerprint already indexed)")
        return True, "Already indexed"

    ext = path.lower().rsplit(".", 1)[-1] if "." in path else ""
    file_name = os.path.basename(path)
    public_url = _public_url_for_path(path)
    source_meta = {"kind": "file", "source": f"file://{os.path.abspath(path)}", "fingerprint": fingerprint}
    if public_url:
        source_meta["source_url"] = public_url
    if _should_replace(store, source_meta["source"], fingerprint):
        _delete_source(store, source_meta["source"])
    else:
        return True, "Already indexed (content unchanged)"

    try:
        if ext == "pdf":
            chunks = _pdf_bytes_to_chunks(raw_bytes)
            contextual_chunks = _with_contextual_previews(chunks)
            metadatas = [dict(source_meta) for _ in contextual_chunks]
        elif ext in {"html", "htm"}:
            raw = raw_bytes.decode("utf-8", errors="ignore")
            text_blob = _extract_text_from_html(raw)
            text_blob = _clean_text(text_blob)
            chunks = _split_text_simple(text_blob, ext=ext)
            contextual_chunks = _with_contextual_previews(chunks)
            metadatas = [dict(source_meta) for _ in contextual_chunks]
        elif ext in {"conf", "spec"}:
            text_blob = _clean_text(raw_bytes.decode("utf-8", errors="ignore"))
            chunks_with_metadata = _split_text(text_blob, ext=ext, filename=file_name, file_path=path)

            contextual_chunks = []
            metadatas = []

            for chunk_text, chunk_meta in chunks_with_metadata:
                meta_copy = dict(source_meta)
                if chunk_meta:
                    meta_copy.update(chunk_meta)

                try:
                    from conf_parser import enrich_chunk_for_search
                    enriched_text = enrich_chunk_for_search(chunk_text, meta_copy)
                except (ImportError, Exception) as e:
                    logger.warning(f"Failed to enrich chunk: {e}")
                    enriched_text = chunk_text

                contextual_chunks.append((enriched_text, {}))
                metadatas.append(meta_copy)
        else:
            text_blob = _clean_text(raw_bytes.decode("utf-8", errors="ignore"))
            chunks = _split_text_simple(text_blob, ext=ext)
            contextual_chunks = _with_contextual_previews(chunks)
            metadatas = [dict(source_meta) for _ in contextual_chunks]
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return False, f"Failed to read file: {exc}"

    if not contextual_chunks:
        return False, f"No text extracted from file: {path}"
    try:
        store.add_texts([c for c, _ in contextual_chunks], metadatas=metadatas)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error(f"add_texts failed for file {path}: {exc}")
        return False, f"Embedding failed: {exc}"
    _persist(store)

    logger.info(f"Indexed file {path} chunks={len(contextual_chunks)}")
    return True, {
        "success": True,
        "file_name": file_name,
        "chunks": len(contextual_chunks),
        "preview": contextual_chunks[0][0][:200] if contextual_chunks else "",
        "type": ext or "text",
    }
