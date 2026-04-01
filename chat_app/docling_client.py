"""
Docling HTTP client for document conversion via docling-serve sidecar.

Wraps the docling-serve REST API (/v1/convert/file, /v1/chunk/hybrid/file, /health)
to provide structured document conversion with OCR, table extraction, and
intelligent chunking. Feature-flagged via settings.docling.enabled.

Falls back gracefully: returns None on any failure so callers can use existing parsers.
"""

import hashlib
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------

@dataclass
class DoclingResult:
    """Structured output from Docling document conversion."""

    markdown: str = ""
    tables: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    pages: int = 0
    processing_time_ms: float = 0.0


@dataclass
class DoclingChunk:
    """A single chunk produced by Docling's hybrid chunker."""

    text: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class DoclingClient:
    """Async HTTP client for docling-serve REST API."""

    def __init__(self, settings: Any = None):
        if settings is None:
            from chat_app.settings import get_settings
            settings = get_settings().docling
        self.base_url = settings.base_url.rstrip("/")
        self.timeout = settings.timeout
        self.ocr_enabled = settings.ocr_enabled
        self.extract_tables = settings.extract_tables
        self.chunk_tokens = getattr(settings, "chunk_tokens", 250)
        self.max_doc_size_mb = getattr(settings, "max_doc_size_mb", 100)

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    async def health(self) -> Dict[str, Any]:
        """Check docling-serve health. Returns dict with status, version."""
        import httpx

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self.base_url}/health")
                resp.raise_for_status()
                return resp.json()
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[DOCLING] Health check failed: %s", exc)
            return {"status": "unhealthy", "error": str(exc)}

    # ------------------------------------------------------------------
    # Convert
    # ------------------------------------------------------------------

    async def convert(self, file_path: str) -> Optional[DoclingResult]:
        """
        Convert a document file to structured markdown via docling-serve.

        Returns DoclingResult on success, None on failure.
        """
        import httpx

        if not os.path.isfile(file_path):
            logger.warning("[DOCLING] File not found: %s", file_path)
            return None

        # Check file size
        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if size_mb > self.max_doc_size_mb:
            logger.warning("[DOCLING] File too large (%.1f MB > %d MB limit): %s",
                           size_mb, self.max_doc_size_mb, file_path)
            return None

        start = time.monotonic()
        filename = os.path.basename(file_path)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                with open(file_path, "rb") as f:
                    files = {"files": (filename, f)}
                    data = {
                        "to_formats": "md",
                        "do_ocr": str(self.ocr_enabled).lower(),
                    }
                    resp = await client.post(
                        f"{self.base_url}/v1/convert/file",
                        files=files,
                        data=data,
                    )
                    resp.raise_for_status()
                    result_json = resp.json()

            elapsed_ms = (time.monotonic() - start) * 1000
            return self._parse_convert_response(result_json, elapsed_ms)

        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[DOCLING] Conversion failed for %s: %s", filename, exc)
            return None

    # ------------------------------------------------------------------
    # Chunk via hybrid chunker
    # ------------------------------------------------------------------

    async def chunk(self, file_path: str) -> Optional[List[DoclingChunk]]:
        """
        Convert + chunk a document via docling-serve hybrid chunker.

        Returns list of DoclingChunk on success, None on failure.
        """
        import httpx

        if not os.path.isfile(file_path):
            return None

        size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if size_mb > self.max_doc_size_mb:
            logger.warning("[DOCLING] File too large for chunking: %s", file_path)
            return None

        filename = os.path.basename(file_path)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                with open(file_path, "rb") as f:
                    files = {"files": (filename, f)}
                    data = {
                        "do_ocr": str(self.ocr_enabled).lower(),
                    }
                    resp = await client.post(
                        f"{self.base_url}/v1/chunk/hybrid/file",
                        files=files,
                        data=data,
                    )
                    resp.raise_for_status()
                    result_json = resp.json()

            return self._parse_chunk_response(result_json)

        except (OSError, ValueError, KeyError, TypeError, RuntimeError, AttributeError, ConnectionError, TimeoutError) as exc:
            logger.warning("[DOCLING] Chunking failed for %s: %s", filename, exc)
            return None

    # ------------------------------------------------------------------
    # Response parsing helpers
    # ------------------------------------------------------------------

    def _parse_convert_response(
        self, data: Dict[str, Any], elapsed_ms: float
    ) -> DoclingResult:
        """Parse docling-serve /v1/convert/file response into DoclingResult."""
        # docling-serve returns {"document": {...}} or {"documents": [...]}
        doc = data.get("document", {})
        if not doc and "documents" in data:
            docs = data["documents"]
            doc = docs[0] if docs else {}

        # Handle case where doc is a raw string
        if isinstance(doc, str):
            return DoclingResult(markdown=doc, processing_time_ms=elapsed_ms)

        markdown = doc.get("md_content", "") or doc.get("text_content", "") or ""

        tables = []
        if self.extract_tables:
            tables = self._extract_tables(doc)

        metadata = {}
        meta_raw = doc.get("metadata", {})
        if isinstance(meta_raw, dict):
            metadata = meta_raw

        pages = metadata.get("num_pages", 0) or doc.get("num_pages", 0)

        return DoclingResult(
            markdown=markdown,
            tables=tables,
            metadata=metadata,
            pages=pages,
            processing_time_ms=elapsed_ms,
        )

    def _parse_chunk_response(
        self, data: Dict[str, Any]
    ) -> List[DoclingChunk]:
        """Parse docling-serve /v1/chunk/hybrid/file response into chunks."""
        chunks = []
        raw_chunks = data.get("chunks", [])
        if not raw_chunks:
            raw_chunks = data.get("output", {}).get("chunks", [])

        for rc in raw_chunks:
            text = ""
            meta = {}
            if isinstance(rc, dict):
                text = rc.get("text", "") or rc.get("content", "")
                meta = rc.get("meta", {}) or rc.get("metadata", {})
            elif isinstance(rc, str):
                text = rc
            if text.strip():
                chunks.append(DoclingChunk(text=text.strip(), metadata=meta))

        return chunks

    def _extract_tables(self, doc: Dict[str, Any]) -> List[str]:
        """Extract table content from docling document output."""
        tables = []
        # docling may include tables as part of the structured output
        for item in doc.get("tables", []):
            if isinstance(item, dict):
                table_md = item.get("markdown", "") or item.get("text", "")
                if table_md:
                    tables.append(table_md)
            elif isinstance(item, str):
                tables.append(item)
        return tables


# ---------------------------------------------------------------------------
# Utility: chunk Docling markdown output using document structure
# ---------------------------------------------------------------------------

def chunk_docling_output(
    result: DoclingResult,
    chunk_tokens: int = 250,
    overlap_tokens: int = 40,
) -> List[Dict[str, Any]]:
    """
    Split Docling markdown output into chunks using heading structure.

    Falls back to simple token-based splitting if no headings found.
    Returns list of dicts with 'text' and 'metadata' keys (compatible with
    IngestedDocument.chunks format).
    """
    if not result.markdown:
        return []

    lines = result.markdown.split("\n")
    sections: List[Dict[str, Any]] = []
    current_heading = ""
    current_lines: List[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#"):
            # Save previous section
            if current_lines:
                sections.append({
                    "heading": current_heading,
                    "text": "\n".join(current_lines).strip(),
                })
            current_heading = stripped.lstrip("#").strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    # Save last section
    if current_lines:
        sections.append({
            "heading": current_heading,
            "text": "\n".join(current_lines).strip(),
        })

    if not sections:
        return _simple_token_split(result.markdown, chunk_tokens, overlap_tokens,
                                   result.metadata)

    # Build chunks from sections, splitting large sections further
    chunks = []
    chunk_idx = 0
    for section in sections:
        text = section["text"]
        if not text:
            continue
        word_count = len(text.split())
        if word_count <= chunk_tokens:
            chunks.append({
                "text": text,
                "metadata": {
                    **result.metadata,
                    "heading": section["heading"],
                    "source": "docling",
                    "chunk_index": chunk_idx,
                },
            })
            chunk_idx += 1
        else:
            # Split large sections
            sub_chunks = _simple_token_split(
                text, chunk_tokens, overlap_tokens, result.metadata
            )
            for sc in sub_chunks:
                sc["metadata"]["heading"] = section["heading"]
                sc["metadata"]["chunk_index"] = chunk_idx
                chunk_idx += 1
            chunks.extend(sub_chunks)

    return chunks


def _simple_token_split(
    text: str, chunk_tokens: int, overlap_tokens: int, base_metadata: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Simple word-based splitting as fallback."""
    words = text.split()
    chunks = []
    step = max(1, chunk_tokens - overlap_tokens)  # Guard against zero/negative step
    i = 0
    while i < len(words):
        chunk_words = words[i : i + chunk_tokens]
        chunk_text = " ".join(chunk_words)
        chunks.append({
            "text": chunk_text,
            "metadata": {**base_metadata, "source": "docling"},
        })
        i += step
    return chunks


def compute_docling_fingerprint(markdown: str) -> str:
    """Compute a fingerprint for dedup of docling-processed documents."""
    return hashlib.sha256(markdown[:10000].encode("utf-8")).hexdigest()[:16]
