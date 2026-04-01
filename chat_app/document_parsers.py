"""
Document Parsers — PDF, HTML, JSON, CSV parsers plus SharePoint/Confluence connectors.

Extracted from document_ingestor.py to keep that file under 600 lines.
All public names are re-exported from document_ingestor.py for backward compatibility.
"""
import csv
import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from chat_app.document_ingestor_types import IngestedDocument, IngestionResult

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Docling integration helpers
# ---------------------------------------------------------------------------

async def _convert_via_docling(filepath: str, source_type: str = "pdf") -> Optional[IngestedDocument]:
    """Convert any file via Docling sidecar. Returns None if unavailable or failed."""
    try:
        from chat_app.settings import get_settings
        settings = get_settings()
        if not settings.docling.enabled:
            return None

        from chat_app.docling_client import DoclingClient, chunk_docling_output, compute_docling_fingerprint
        client = DoclingClient(settings.docling)
        result = await client.convert(filepath)
        if not result or not result.markdown:
            return None

        chunks = chunk_docling_output(
            result,
            chunk_tokens=settings.docling.chunk_tokens,
            overlap_tokens=settings.docling.overlap_tokens,
        )
        title = result.metadata.get("title", "") or Path(filepath).stem
        return IngestedDocument(
            source=filepath,
            source_type=source_type,
            title=title,
            chunks=chunks,
            metadata={**result.metadata, "parser": "docling"},
            fingerprint=compute_docling_fingerprint(result.markdown),
            chunk_count=len(chunks),
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, RuntimeError, AttributeError) as exc:
        logger.warning("[INGEST] Docling failed for %s, falling back: %s", filepath, exc)
        return None


async def _parse_pdf_via_docling(filepath: str, chunk_size: int = 500) -> Optional[IngestedDocument]:
    """Try parsing PDF via Docling sidecar. Returns None if unavailable or failed."""
    return await _convert_via_docling(filepath, source_type="pdf")


async def _ingest_via_docling(filepath: str, chunk_size: int = 500) -> Optional[IngestedDocument]:
    """Ingest non-PDF formats (docx, pptx, xlsx, odt) via Docling sidecar."""
    ext = Path(filepath).suffix.lower().lstrip(".")
    return await _convert_via_docling(filepath, source_type=ext)


# ---------------------------------------------------------------------------
# PDF Parser
# ---------------------------------------------------------------------------

def parse_pdf(filepath: str, chunk_size: int = 500) -> IngestedDocument:
    """Parse a PDF file and extract text content."""
    from chat_app.ingest_chunkers import _chunk_text
    doc = IngestedDocument(source=filepath, source_type="pdf")

    try:
        text = ""
        # Try PyMuPDF (fitz) first — fastest and most accurate
        try:
            import fitz  # PyMuPDF
            pdf_doc = fitz.open(filepath)
            doc.title = pdf_doc.metadata.get("title", "") or Path(filepath).stem
            for page in pdf_doc:
                text += page.get_text() + "\n"
            pdf_doc.close()
        except ImportError:
            # Fall back to pdfplumber
            try:
                import pdfplumber
                with pdfplumber.open(filepath) as pdf:
                    doc.title = Path(filepath).stem
                    for page in pdf.pages:
                        page_text = page.extract_text()
                        if page_text:
                            text += page_text + "\n"
            except ImportError:
                # Last resort: pdfminer
                try:
                    from pdfminer.high_level import extract_text as pdf_extract
                    text = pdf_extract(filepath)
                    doc.title = Path(filepath).stem
                except ImportError:
                    doc.error = "No PDF library available. Install: pip install PyMuPDF or pdfplumber"
                    return doc

        if not text.strip():
            doc.error = "PDF appears to be empty or image-only (no extractable text)"
            return doc

        # Clean up extracted text
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r' {2,}', ' ', text)

        doc.chunks = _chunk_text(
            text, chunk_size=chunk_size,
            metadata={"source": filepath, "kind": "pdf", "title": doc.title},
        )
        doc.chunk_count = len(doc.chunks)
        doc.fingerprint = hashlib.sha256(text[:5000].encode()).hexdigest()

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        doc.error = f"PDF parse error: {exc}"
        logger.warning(f"[INGEST] PDF parse failed for {filepath}: {exc}")

    return doc


# ---------------------------------------------------------------------------
# HTML Parser
# ---------------------------------------------------------------------------

def parse_html(content: str, source_url: str = "", chunk_size: int = 500) -> IngestedDocument:
    """Parse HTML content and extract clean text."""
    from chat_app.ingest_chunkers import _chunk_text
    doc = IngestedDocument(source=source_url, source_type="html")

    try:
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(content, "html.parser")

            # Extract title
            title_tag = soup.find("title")
            doc.title = title_tag.get_text().strip() if title_tag else ""

            # Remove script, style, nav, footer elements
            for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
                tag.decompose()

            # Extract main content
            main = soup.find("main") or soup.find("article") or soup.find("body") or soup
            text = main.get_text(separator="\n", strip=True)

        except ImportError:
            # Fallback: regex-based HTML stripping
            text = re.sub(r'<script[^>]*>.*?</script>', '', content, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'&[a-z]+;', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            doc.title = ""

        if not text.strip():
            doc.error = "No text content found in HTML"
            return doc

        doc.chunks = _chunk_text(
            text, chunk_size=chunk_size,
            metadata={"source": source_url, "kind": "html", "title": doc.title},
        )
        doc.chunk_count = len(doc.chunks)
        doc.fingerprint = hashlib.sha256(text[:5000].encode()).hexdigest()

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        doc.error = f"HTML parse error: {exc}"

    return doc


# ---------------------------------------------------------------------------
# JSON Parser
# ---------------------------------------------------------------------------

def _flatten_dict(d: dict, prefix: str = "", max_depth: int = 3) -> str:
    """Flatten a dictionary into readable text."""
    if max_depth <= 0:
        return str(d)[:200]

    parts = []
    for key, value in d.items():
        full_key = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            parts.append(_flatten_dict(value, full_key, max_depth - 1))
        elif isinstance(value, list):
            items_str = ", ".join(str(v)[:100] for v in value[:10])
            parts.append(f"{full_key}: [{items_str}]")
        else:
            parts.append(f"{full_key}: {value}")

    return "\n".join(parts)


def parse_json(filepath: str, chunk_size: int = 500) -> IngestedDocument:
    """Parse a JSON file and extract structured content."""
    from chat_app.ingest_chunkers import _chunk_text
    doc = IngestedDocument(source=filepath, source_type="json")

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        doc.title = Path(filepath).stem
        text_parts = []

        if isinstance(data, list):
            for i, item in enumerate(data[:500]):  # Limit to 500 items
                if isinstance(item, dict):
                    text_parts.append(_flatten_dict(item, prefix=f"item_{i}"))
                else:
                    text_parts.append(str(item))
        elif isinstance(data, dict):
            text_parts.append(_flatten_dict(data))
        else:
            text_parts.append(str(data))

        text = "\n".join(text_parts)

        doc.chunks = _chunk_text(
            text, chunk_size=chunk_size,
            metadata={"source": filepath, "kind": "json", "title": doc.title},
        )
        doc.chunk_count = len(doc.chunks)
        doc.fingerprint = hashlib.sha256(text[:5000].encode()).hexdigest()

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        doc.error = f"JSON parse error: {exc}"

    return doc


# ---------------------------------------------------------------------------
# CSV Parser
# ---------------------------------------------------------------------------

def parse_csv(filepath: str, chunk_size: int = 500) -> IngestedDocument:
    """Parse a CSV file and extract content row-by-row."""
    from chat_app.ingest_chunkers import _chunk_text
    doc = IngestedDocument(source=filepath, source_type="csv")

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
            # Detect dialect
            sample = f.read(4096)
            f.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample)
            except csv.Error:
                dialect = csv.excel

            reader = csv.DictReader(f, dialect=dialect)
            headers = reader.fieldnames or []
            doc.title = Path(filepath).stem
            doc.metadata["headers"] = headers

            text_parts = []
            for i, row in enumerate(reader):
                if i >= 1000:  # Limit rows
                    break
                row_text = " | ".join(f"{k}: {v}" for k, v in row.items() if v)
                if row_text:
                    text_parts.append(row_text)

        text = "\n".join(text_parts)

        doc.chunks = _chunk_text(
            text, chunk_size=chunk_size,
            metadata={"source": filepath, "kind": "csv", "title": doc.title, "headers": ",".join(headers)},
        )
        doc.chunk_count = len(doc.chunks)
        doc.fingerprint = hashlib.sha256(text[:5000].encode()).hexdigest()

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        doc.error = f"CSV parse error: {exc}"

    return doc


# ---------------------------------------------------------------------------
# SharePoint Connector
# ---------------------------------------------------------------------------

class SharePointConnector:
    """
    Connect to SharePoint Online via Microsoft Graph API.

    Requires: SHAREPOINT_TENANT_ID, SHAREPOINT_CLIENT_ID, SHAREPOINT_CLIENT_SECRET
    """

    def __init__(self, tenant_id: str = "", client_id: str = "", client_secret: str = "", site_url: str = ""):
        self.tenant_id = tenant_id or os.getenv("SHAREPOINT_TENANT_ID", "")
        self.client_id = client_id or os.getenv("SHAREPOINT_CLIENT_ID", "")
        self.client_secret = client_secret or os.getenv("SHAREPOINT_CLIENT_SECRET", "")
        self.site_url = site_url or os.getenv("SHAREPOINT_SITE_URL", "")
        self._token = None
        self._token_expires = 0

    @property
    def is_configured(self) -> bool:
        return bool(self.tenant_id and self.client_id and self.client_secret and self.site_url)

    async def _get_token(self) -> str:
        """Get OAuth2 token from Azure AD."""
        import time
        if self._token and time.time() < self._token_expires - 60:
            return self._token

        try:
            import httpx
            url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
            data = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "scope": "https://graph.microsoft.com/.default",
                "grant_type": "client_credentials",
            }
            async with httpx.AsyncClient() as client:
                resp = await client.post(url, data=data)
                resp.raise_for_status()
                token_data = resp.json()
                self._token = token_data["access_token"]
                self._token_expires = time.time() + token_data.get("expires_in", 3600)
                return self._token
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.error(f"[SHAREPOINT] Auth failed: {exc}")
            raise

    async def list_documents(self, library: str = "Shared Documents", limit: int = 100) -> List[Dict]:
        """List documents in a SharePoint document library."""
        try:
            import httpx
            token = await self._get_token()

            # Parse site from URL
            parsed = urlparse(self.site_url)
            site_path = parsed.path.rstrip("/")

            headers = {"Authorization": f"Bearer {token}"}
            async with httpx.AsyncClient() as client:
                # Get site ID
                site_resp = await client.get(
                    f"https://graph.microsoft.com/v1.0/sites/{parsed.hostname}:{site_path}",
                    headers=headers,
                )
                site_resp.raise_for_status()
                site_id = site_resp.json()["id"]

                # Get drive (document library)
                drives_resp = await client.get(
                    f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
                    headers=headers,
                )
                drives_resp.raise_for_status()

                target_drive = None
                for drive in drives_resp.json().get("value", []):
                    if drive["name"] == library:
                        target_drive = drive
                        break

                if not target_drive:
                    return []

                # List files
                files_resp = await client.get(
                    f"https://graph.microsoft.com/v1.0/drives/{target_drive['id']}/root/children?$top={limit}",
                    headers=headers,
                )
                files_resp.raise_for_status()

                return [
                    {
                        "id": item["id"],
                        "name": item["name"],
                        "size": item.get("size", 0),
                        "modified": item.get("lastModifiedDateTime", ""),
                        "download_url": item.get("@microsoft.graph.downloadUrl", ""),
                        "web_url": item.get("webUrl", ""),
                        "mime_type": item.get("file", {}).get("mimeType", ""),
                    }
                    for item in files_resp.json().get("value", [])
                    if "file" in item  # Only files, not folders
                ]

        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.error(f"[SHAREPOINT] List documents failed: {exc}")
            return []

    async def download_document(self, download_url: str) -> bytes:
        """Download a document from SharePoint."""
        try:
            import httpx
            token = await self._get_token()
            headers = {"Authorization": f"Bearer {token}"}
            async with httpx.AsyncClient() as client:
                resp = await client.get(download_url, headers=headers, follow_redirects=True)
                resp.raise_for_status()
                return resp.content
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.error(f"[SHAREPOINT] Download failed: {exc}")
            return b""

    async def ingest_library(
        self,
        library: str = "Shared Documents",
        limit: int = 100,
        chunk_size: int = 500,
    ) -> IngestionResult:
        """Ingest all supported documents from a SharePoint library."""
        from chat_app.ingest_chunkers import _chunk_text
        result = IngestionResult()
        docs = await self.list_documents(library, limit)

        for doc_info in docs:
            name = doc_info["name"]
            mime = doc_info.get("mime_type", "")
            download_url = doc_info.get("download_url", "")

            if not download_url:
                continue

            try:
                content = await self.download_document(download_url)
                if not content:
                    continue

                if mime == "application/pdf" or name.endswith(".pdf"):
                    # Save temp and parse
                    tmp_path = f"/tmp/sp_{hashlib.sha256(name.encode()).hexdigest()}.pdf"
                    with open(tmp_path, "wb") as f:
                        f.write(content)
                    parsed = parse_pdf(tmp_path, chunk_size=chunk_size)
                    os.unlink(tmp_path)
                elif "html" in mime or name.endswith((".html", ".htm")):
                    parsed = parse_html(content.decode("utf-8", errors="ignore"), source_url=doc_info.get("web_url", ""))
                elif name.endswith((".txt", ".md")):
                    text = content.decode("utf-8", errors="ignore")
                    parsed = IngestedDocument(
                        source=doc_info.get("web_url", name),
                        source_type="sharepoint",
                        title=name,
                        chunks=_chunk_text(text, chunk_size=chunk_size, metadata={"source": name, "kind": "sharepoint"}),
                    )
                    parsed.chunk_count = len(parsed.chunks)
                else:
                    result.documents_skipped += 1
                    continue

                if parsed.error:
                    result.errors.append(f"{name}: {parsed.error}")
                else:
                    result.documents_processed += 1
                    result.chunks_created += parsed.chunk_count
                    result.sources.append(name)

            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                result.errors.append(f"{name}: {exc}")

        return result


# ---------------------------------------------------------------------------
# Confluence Connector
# ---------------------------------------------------------------------------

class ConfluenceConnector:
    """
    Connect to Confluence via REST API.

    Requires: CONFLUENCE_URL, CONFLUENCE_USERNAME, CONFLUENCE_API_TOKEN
    """

    def __init__(self, base_url: str = "", username: str = "", api_token: str = ""):
        self.base_url = (base_url or os.getenv("CONFLUENCE_URL", "")).rstrip("/")
        self.username = username or os.getenv("CONFLUENCE_USERNAME", "")
        self.api_token = api_token or os.getenv("CONFLUENCE_API_TOKEN", "")

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.username and self.api_token)

    async def list_pages(self, space_key: str, limit: int = 50) -> List[Dict]:
        """List pages in a Confluence space."""
        try:
            import httpx
            url = f"{self.base_url}/rest/api/content"
            params = {
                "spaceKey": space_key,
                "type": "page",
                "limit": limit,
                "expand": "body.storage,metadata.labels",
            }
            auth = (self.username, self.api_token)
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, params=params, auth=auth)
                resp.raise_for_status()
                data = resp.json()

                return [
                    {
                        "id": page["id"],
                        "title": page["title"],
                        "body_html": page.get("body", {}).get("storage", {}).get("value", ""),
                        "url": f"{self.base_url}/wiki/spaces/{space_key}/pages/{page['id']}",
                        "labels": [l["name"] for l in page.get("metadata", {}).get("labels", {}).get("results", [])],
                    }
                    for page in data.get("results", [])
                ]
        except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
            logger.error(f"[CONFLUENCE] List pages failed: {exc}")
            return []

    async def ingest_space(
        self,
        space_key: str,
        limit: int = 50,
        chunk_size: int = 500,
    ) -> IngestionResult:
        """Ingest all pages from a Confluence space."""
        result = IngestionResult()
        pages = await self.list_pages(space_key, limit)

        for page in pages:
            html_body = page.get("body_html", "")
            if not html_body:
                result.documents_skipped += 1
                continue

            parsed = parse_html(html_body, source_url=page.get("url", ""), chunk_size=chunk_size)
            parsed.title = page.get("title", "")

            if parsed.error:
                result.errors.append(f"{page['title']}: {parsed.error}")
            else:
                result.documents_processed += 1
                result.chunks_created += parsed.chunk_count
                result.sources.append(page["title"])

        return result
