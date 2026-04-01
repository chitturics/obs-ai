"""Tests for chat_app.docling_client — Docling sidecar HTTP client."""

import hashlib
import os
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from dataclasses import dataclass

from chat_app.docling_client import (
    DoclingClient,
    DoclingResult,
    DoclingChunk,
    chunk_docling_output,
    compute_docling_fingerprint,
    _simple_token_split,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@dataclass
class FakeDoclingSettings:
    enabled: bool = True
    base_url: str = "http://localhost:5001"
    timeout: int = 30
    ocr_enabled: bool = False
    extract_tables: bool = True
    chunk_tokens: int = 250
    max_doc_size_mb: int = 100


@pytest.fixture
def settings():
    return FakeDoclingSettings()


@pytest.fixture
def client(settings):
    return DoclingClient(settings)


def _mock_httpx_response(json_data, status_code=200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = RuntimeError(f"HTTP {status_code}")
    return resp


# ---------------------------------------------------------------------------
# TestDoclingResult
# ---------------------------------------------------------------------------

class TestDoclingResult:
    def test_default_values(self):
        r = DoclingResult()
        assert r.markdown == ""
        assert r.tables == []
        assert r.metadata == {}
        assert r.pages == 0
        assert r.processing_time_ms == 0.0

    def test_custom_values(self):
        r = DoclingResult(
            markdown="# Title\nContent",
            tables=["| A | B |"],
            metadata={"title": "Test"},
            pages=5,
            processing_time_ms=123.4,
        )
        assert r.markdown == "# Title\nContent"
        assert len(r.tables) == 1
        assert r.pages == 5


class TestDoclingChunk:
    def test_default_values(self):
        c = DoclingChunk()
        assert c.text == ""
        assert c.metadata == {}

    def test_custom_values(self):
        c = DoclingChunk(text="hello", metadata={"page": 1})
        assert c.text == "hello"
        assert c.metadata["page"] == 1


# ---------------------------------------------------------------------------
# TestDoclingClient
# ---------------------------------------------------------------------------

class TestDoclingClient:
    def test_init_from_settings(self, settings):
        c = DoclingClient(settings)
        assert c.base_url == "http://localhost:5001"
        assert c.timeout == 30
        assert c.ocr_enabled is False
        assert c.extract_tables is True

    def test_init_strips_trailing_slash(self):
        s = FakeDoclingSettings(base_url="http://localhost:5001/")
        c = DoclingClient(s)
        assert c.base_url == "http://localhost:5001"

    @pytest.mark.asyncio
    async def test_health_success(self, client):
        mock_resp = _mock_httpx_response({"status": "ok", "version": "1.0"})
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await client.health()
            assert result["status"] == "ok"
            assert result["version"] == "1.0"

    @pytest.mark.asyncio
    async def test_health_failure(self, client):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await client.health()
            assert result["status"] == "unhealthy"
            assert "Connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_convert_file_not_found(self, client):
        result = await client.convert("/nonexistent/file.pdf")
        assert result is None

    @pytest.mark.asyncio
    async def test_convert_file_too_large(self, client, tmp_path):
        # Create a file larger than max
        client.max_doc_size_mb = 0  # 0 MB limit
        f = tmp_path / "big.pdf"
        f.write_bytes(b"x" * 1024)
        result = await client.convert(str(f))
        assert result is None

    @pytest.mark.asyncio
    async def test_convert_success(self, client, tmp_path):
        f = tmp_path / "test.pdf"
        f.write_bytes(b"%PDF-1.4 test content")

        mock_resp = _mock_httpx_response({
            "document": {
                "md_content": "# Test\nSome content",
                "metadata": {"title": "Test Doc", "num_pages": 3},
                "tables": [],
            }
        })
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await client.convert(str(f))
            assert result is not None
            assert result.markdown == "# Test\nSome content"
            assert result.metadata["title"] == "Test Doc"
            assert result.pages == 3

    @pytest.mark.asyncio
    async def test_convert_with_documents_list(self, client, tmp_path):
        f = tmp_path / "test.pdf"
        f.write_bytes(b"%PDF-1.4")

        mock_resp = _mock_httpx_response({
            "documents": [
                {"md_content": "# Doc1", "metadata": {}, "tables": []}
            ]
        })
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await client.convert(str(f))
            assert result is not None
            assert result.markdown == "# Doc1"

    @pytest.mark.asyncio
    async def test_convert_http_error(self, client, tmp_path):
        f = tmp_path / "test.pdf"
        f.write_bytes(b"%PDF-1.4")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=RuntimeError("HTTP 500"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await client.convert(str(f))
            assert result is None

    @pytest.mark.asyncio
    async def test_chunk_success(self, client, tmp_path):
        f = tmp_path / "test.pdf"
        f.write_bytes(b"%PDF-1.4")

        mock_resp = _mock_httpx_response({
            "chunks": [
                {"text": "First chunk", "meta": {"page": 1}},
                {"text": "Second chunk", "meta": {"page": 2}},
            ]
        })
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await client.chunk(str(f))
            assert result is not None
            assert len(result) == 2
            assert result[0].text == "First chunk"
            assert result[1].text == "Second chunk"

    @pytest.mark.asyncio
    async def test_chunk_file_not_found(self, client):
        result = await client.chunk("/nonexistent/file.pdf")
        assert result is None

    @pytest.mark.asyncio
    async def test_chunk_failure(self, client, tmp_path):
        f = tmp_path / "test.pdf"
        f.write_bytes(b"%PDF-1.4")

        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=RuntimeError("timeout"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await client.chunk(str(f))
            assert result is None


# ---------------------------------------------------------------------------
# TestTableExtraction
# ---------------------------------------------------------------------------

class TestTableExtraction:
    def test_extract_tables_from_dict(self, client):
        doc = {
            "tables": [
                {"markdown": "| A | B |\n|---|---|\n| 1 | 2 |"},
                {"text": "Table 2 content"},
            ]
        }
        tables = client._extract_tables(doc)
        assert len(tables) == 2
        assert "| A | B |" in tables[0]

    def test_extract_tables_from_strings(self, client):
        doc = {"tables": ["raw table text"]}
        tables = client._extract_tables(doc)
        assert tables == ["raw table text"]

    def test_extract_tables_empty(self, client):
        doc = {"tables": []}
        assert client._extract_tables(doc) == []

    def test_extract_tables_missing(self, client):
        doc = {}
        assert client._extract_tables(doc) == []


# ---------------------------------------------------------------------------
# TestChunkDoclingOutput
# ---------------------------------------------------------------------------

class TestChunkDoclingOutput:
    def test_empty_result(self):
        r = DoclingResult()
        assert chunk_docling_output(r) == []

    def test_single_section(self):
        r = DoclingResult(markdown="# Title\nSome short content here")
        chunks = chunk_docling_output(r, chunk_tokens=250)
        assert len(chunks) >= 1
        assert chunks[0]["metadata"]["source"] == "docling"
        assert chunks[0]["metadata"]["heading"] == "Title"

    def test_multiple_sections(self):
        md = "# Section A\nContent A\n\n# Section B\nContent B"
        r = DoclingResult(markdown=md)
        chunks = chunk_docling_output(r, chunk_tokens=250)
        assert len(chunks) == 2
        assert chunks[0]["metadata"]["heading"] == "Section A"
        assert chunks[1]["metadata"]["heading"] == "Section B"

    def test_large_section_split(self):
        # Create a section larger than chunk_tokens
        long_text = "# BigSection\n" + " ".join(["word"] * 300)
        r = DoclingResult(markdown=long_text)
        chunks = chunk_docling_output(r, chunk_tokens=100, overlap_tokens=20)
        assert len(chunks) > 1
        for c in chunks:
            assert c["metadata"]["heading"] == "BigSection"

    def test_no_headings_fallback(self):
        r = DoclingResult(markdown="Just plain text without any headings at all")
        chunks = chunk_docling_output(r, chunk_tokens=250)
        assert len(chunks) >= 1
        # No headings → still gets source metadata
        assert chunks[0]["metadata"]["source"] == "docling"

    def test_metadata_preserved(self):
        r = DoclingResult(
            markdown="# Title\nContent",
            metadata={"author": "Test", "pages": 5},
        )
        chunks = chunk_docling_output(r, chunk_tokens=250)
        assert chunks[0]["metadata"]["author"] == "Test"
        assert chunks[0]["metadata"]["pages"] == 5


# ---------------------------------------------------------------------------
# TestSimpleTokenSplit
# ---------------------------------------------------------------------------

class TestSimpleTokenSplit:
    def test_short_text(self):
        chunks = _simple_token_split("hello world", 250, 40, {})
        assert len(chunks) == 1
        assert chunks[0]["text"] == "hello world"

    def test_long_text_split(self):
        text = " ".join(["word"] * 500)
        chunks = _simple_token_split(text, 100, 20, {"src": "test"})
        assert len(chunks) > 1
        for c in chunks:
            assert c["metadata"]["source"] == "docling"
            assert c["metadata"]["src"] == "test"

    def test_overlap(self):
        text = " ".join([f"w{i}" for i in range(200)])
        chunks = _simple_token_split(text, 100, 20, {})
        # With overlap, chunks should share some words
        assert len(chunks) >= 2


# ---------------------------------------------------------------------------
# TestFingerprint
# ---------------------------------------------------------------------------

class TestFingerprint:
    def test_deterministic(self):
        fp1 = compute_docling_fingerprint("hello world")
        fp2 = compute_docling_fingerprint("hello world")
        assert fp1 == fp2

    def test_different_content(self):
        fp1 = compute_docling_fingerprint("hello")
        fp2 = compute_docling_fingerprint("world")
        assert fp1 != fp2

    def test_length(self):
        fp = compute_docling_fingerprint("test")
        assert len(fp) == 16  # 16 hex chars


# ---------------------------------------------------------------------------
# TestDoclingSettings integration
# ---------------------------------------------------------------------------

class TestDoclingSettings:
    def test_import(self):
        from chat_app.settings import DoclingSettings
        s = DoclingSettings()
        assert s.enabled is False
        assert s.base_url == "http://127.0.0.1:5001"
        assert s.timeout == 300
        assert s.ocr_enabled is False
        assert s.extract_tables is True
        assert s.chunk_tokens == 250
        assert s.max_doc_size_mb == 100

    def test_custom_values(self):
        from chat_app.settings import DoclingSettings
        s = DoclingSettings(enabled=True, base_url="http://docling:5001", timeout=60)
        assert s.enabled is True
        assert s.base_url == "http://docling:5001"
        assert s.timeout == 60


# ---------------------------------------------------------------------------
# TestParseConvertResponse
# ---------------------------------------------------------------------------

class TestParseConvertResponse:
    def test_document_key(self, client):
        data = {
            "document": {
                "md_content": "# Hello",
                "metadata": {"title": "Test"},
                "tables": [],
            }
        }
        result = client._parse_convert_response(data, 100.0)
        assert result.markdown == "# Hello"
        assert result.processing_time_ms == 100.0

    def test_documents_list(self, client):
        data = {
            "documents": [
                {"md_content": "# First", "metadata": {}, "tables": []},
            ]
        }
        result = client._parse_convert_response(data, 50.0)
        assert result.markdown == "# First"

    def test_empty_response(self, client):
        data = {}
        result = client._parse_convert_response(data, 0)
        assert result.markdown == ""

    def test_string_document(self, client):
        data = {"document": "raw string content"}
        result = client._parse_convert_response(data, 10.0)
        assert result.markdown == "raw string content"


class TestParseChunkResponse:
    def test_chunks_key(self, client):
        data = {"chunks": [{"text": "chunk1", "meta": {}}, {"text": "chunk2"}]}
        chunks = client._parse_chunk_response(data)
        assert len(chunks) == 2
        assert chunks[0].text == "chunk1"

    def test_output_chunks_key(self, client):
        data = {"output": {"chunks": [{"content": "c1"}, {"content": "c2"}]}}
        chunks = client._parse_chunk_response(data)
        assert len(chunks) == 2
        assert chunks[0].text == "c1"

    def test_string_chunks(self, client):
        data = {"chunks": ["text1", "text2"]}
        chunks = client._parse_chunk_response(data)
        assert len(chunks) == 2
        assert chunks[0].text == "text1"

    def test_empty_chunks_filtered(self, client):
        data = {"chunks": [{"text": ""}, {"text": "  "}, {"text": "valid"}]}
        chunks = client._parse_chunk_response(data)
        assert len(chunks) == 1
        assert chunks[0].text == "valid"


# ---------------------------------------------------------------------------
# TestHealthMonitor integration
# ---------------------------------------------------------------------------

class TestHealthMonitorDocling:
    @pytest.mark.asyncio
    async def test_check_docling_disabled(self):
        from chat_app.health_monitor import check_docling

        fake_settings = MagicMock()
        fake_settings.docling.enabled = False

        with patch("chat_app.settings.get_settings", return_value=fake_settings):
            result = await check_docling()
            assert result.status == "disabled"

    @pytest.mark.asyncio
    async def test_check_docling_healthy(self):
        from chat_app.health_monitor import check_docling

        fake_settings = MagicMock()
        fake_settings.docling.enabled = True
        fake_settings.docling.base_url = "http://localhost:5001"

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "version": "1.0"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("chat_app.settings.get_settings", return_value=fake_settings), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = await check_docling()
            assert result.status == "healthy"

    @pytest.mark.asyncio
    async def test_check_docling_unhealthy(self):
        from chat_app.health_monitor import check_docling

        fake_settings = MagicMock()
        fake_settings.docling.enabled = True
        fake_settings.docling.base_url = "http://localhost:5001"

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=RuntimeError("Connection refused"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("chat_app.settings.get_settings", return_value=fake_settings), \
             patch("httpx.AsyncClient", return_value=mock_client):
            result = await check_docling()
            assert result.status == "degraded"
            assert "Connection refused" in result.error


# ---------------------------------------------------------------------------
# Edge case tests from review
# ---------------------------------------------------------------------------

class TestInfiniteLoopGuard:
    def test_overlap_exceeds_chunk_tokens(self):
        """Guard against infinite loop when overlap >= chunk_tokens."""
        from chat_app.docling_client import _simple_token_split
        # This would infinite loop without the max(1, ...) guard
        chunks = _simple_token_split("word1 word2 word3 word4 word5",
                                      chunk_tokens=3, overlap_tokens=5,
                                      base_metadata={})
        assert len(chunks) >= 1
        # Should still produce chunks without hanging

    def test_overlap_equals_chunk_tokens(self):
        from chat_app.docling_client import _simple_token_split
        chunks = _simple_token_split("a b c d e f g h i j",
                                      chunk_tokens=3, overlap_tokens=3,
                                      base_metadata={})
        assert len(chunks) >= 1

    def test_zero_chunk_tokens_guarded(self):
        from chat_app.docling_client import _simple_token_split
        chunks = _simple_token_split("word1 word2",
                                      chunk_tokens=0, overlap_tokens=0,
                                      base_metadata={})
        # Should not hang — step becomes max(1, 0-0) = 1
        assert isinstance(chunks, list)


class TestChunkIndex:
    def test_chunks_have_chunk_index(self):
        r = DoclingResult(markdown="# Section A\nContent A\n\n# Section B\nContent B")
        chunks = chunk_docling_output(r, chunk_tokens=250)
        assert len(chunks) == 2
        assert chunks[0]["metadata"]["chunk_index"] == 0
        assert chunks[1]["metadata"]["chunk_index"] == 1

    def test_large_section_chunks_have_sequential_index(self):
        md = "# Big\n" + " ".join(["word"] * 300)
        r = DoclingResult(markdown=md)
        chunks = chunk_docling_output(r, chunk_tokens=100, overlap_tokens=20)
        indices = [c["metadata"]["chunk_index"] for c in chunks]
        assert indices == list(range(len(chunks)))


class TestZeroByteFile:
    @pytest.mark.asyncio
    async def test_convert_zero_byte_file(self, client, tmp_path):
        f = tmp_path / "empty.pdf"
        f.write_bytes(b"")
        # zero-byte file passes size check (0 <= 100 MB) but should
        # return None when docling-serve returns an error
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(side_effect=RuntimeError("empty file"))
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            result = await client.convert(str(f))
            assert result is None


class TestTextContentFallback:
    def test_text_content_field_used(self, client):
        """Verify text_content is used when md_content is empty."""
        data = {
            "document": {
                "md_content": "",
                "text_content": "Fallback text content here",
                "metadata": {},
                "tables": [],
            }
        }
        result = client._parse_convert_response(data, 50.0)
        assert result.markdown == "Fallback text content here"


class TestIngestFileFormats:
    @pytest.mark.asyncio
    async def test_docx_without_docling_returns_error(self):
        from chat_app.document_ingestor import ingest_file

        with patch("chat_app.document_ingestor._ingest_via_docling",
                    new_callable=AsyncMock, return_value=None):
            result = await ingest_file("/tmp/fake.docx")
            assert result.error is not None
            assert "Docling not available" in result.error

    @pytest.mark.asyncio
    async def test_pdf_fallback_when_docling_unavailable(self):
        from chat_app.document_ingestor import ingest_file

        with patch("chat_app.document_ingestor._parse_pdf_via_docling",
                    new_callable=AsyncMock, return_value=None), \
             patch("chat_app.document_ingestor.parse_pdf") as mock_pdf:
            mock_pdf.return_value = MagicMock(
                source="/tmp/test.pdf", source_type="pdf",
                chunks=[{"text": "content"}], error=None
            )
            result = await ingest_file("/tmp/test.pdf")
            mock_pdf.assert_called_once()
            assert result.error is None


# ---------------------------------------------------------------------------
# Test overlap_tokens passed correctly
# ---------------------------------------------------------------------------

class TestOverlapTokens:
    @pytest.mark.asyncio
    async def test_convert_via_docling_passes_overlap(self):
        """_convert_via_docling should pass overlap_tokens from settings."""
        from chat_app.document_ingestor import _convert_via_docling

        mock_settings = MagicMock()
        mock_settings.docling.enabled = True
        mock_settings.docling.chunk_tokens = 200
        mock_settings.docling.overlap_tokens = 50

        mock_result = MagicMock()
        mock_result.markdown = "test content"
        mock_result.metadata = {}
        mock_result.tables = []

        with patch("chat_app.settings.get_settings",
                    return_value=mock_settings), \
             patch("chat_app.docling_client.DoclingClient") as mock_cls, \
             patch("chat_app.docling_client.chunk_docling_output",
                    return_value=[{"text": "chunk"}]) as mock_chunk, \
             patch("chat_app.docling_client.compute_docling_fingerprint",
                    return_value="abc123"):
            mock_cls.return_value.convert = AsyncMock(return_value=mock_result)
            result = await _convert_via_docling("/tmp/test.pdf", "pdf")

        mock_chunk.assert_called_once()
        call_kwargs = mock_chunk.call_args
        assert call_kwargs.kwargs.get("overlap_tokens") == 50 or \
               (len(call_kwargs.args) >= 3 and call_kwargs.args[2] == 50)

    def test_docling_settings_has_overlap_tokens(self):
        from chat_app.settings import DoclingSettings
        s = DoclingSettings()
        assert s.overlap_tokens == 40  # default

    def test_docling_settings_custom_overlap(self):
        from chat_app.settings import DoclingSettings
        s = DoclingSettings(overlap_tokens=60)
        assert s.overlap_tokens == 60


# ---------------------------------------------------------------------------
# Test _convert_via_docling dedup (shared helper)
# ---------------------------------------------------------------------------

class TestConvertViaDocling:
    @pytest.mark.asyncio
    async def test_pdf_and_docx_use_same_helper(self):
        """_parse_pdf_via_docling and _ingest_via_docling both call _convert_via_docling."""
        from chat_app.document_ingestor import (
            _parse_pdf_via_docling, _ingest_via_docling,
        )
        with patch("chat_app.document_ingestor._convert_via_docling",
                    new_callable=AsyncMock, return_value=None) as mock_convert:
            await _parse_pdf_via_docling("/tmp/test.pdf")
            mock_convert.assert_called_once_with("/tmp/test.pdf", source_type="pdf")

            mock_convert.reset_mock()
            await _ingest_via_docling("/tmp/test.docx")
            mock_convert.assert_called_once_with("/tmp/test.docx", source_type="docx")

    @pytest.mark.asyncio
    async def test_disabled_returns_none(self):
        from chat_app.document_ingestor import _convert_via_docling

        mock_settings = MagicMock()
        mock_settings.docling.enabled = False
        with patch("chat_app.settings.get_settings",
                    return_value=mock_settings):
            result = await _convert_via_docling("/tmp/test.pdf")
        assert result is None


# ---------------------------------------------------------------------------
# Test md_content takes precedence over text_content
# ---------------------------------------------------------------------------

class TestMdContentPriority:
    def test_md_content_preferred_over_text_content(self, client):
        """When both md_content and text_content exist, md_content wins."""
        data = {
            "document": {
                "md_content": "# Primary Markdown",
                "text_content": "Fallback plain text",
                "metadata": {},
                "tables": [],
            }
        }
        result = client._parse_convert_response(data, 50.0)
        assert result.markdown == "# Primary Markdown"


# ---------------------------------------------------------------------------
# Test empty documents list
# ---------------------------------------------------------------------------

class TestEmptyDocumentsList:
    def test_empty_documents_list(self, client):
        data = {"documents": []}
        result = client._parse_convert_response(data, 50.0)
        assert result.markdown == ""


# ---------------------------------------------------------------------------
# Test chunk_docling_output with heading-only sections (empty body)
# ---------------------------------------------------------------------------

class TestEmptyBodySections:
    def test_heading_only_section_produces_no_chunk(self):
        from chat_app.docling_client import DoclingResult, chunk_docling_output
        result = DoclingResult(
            markdown="# Heading 1\n\n# Heading 2\n\nSome actual content here",
        )
        chunks = chunk_docling_output(result, chunk_tokens=100)
        # Only the section with content should produce a chunk
        texts = [c["text"] for c in chunks]
        assert any("Some actual content" in t for t in texts)
        for c in chunks:
            assert c["text"].strip() != ""
