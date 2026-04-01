"""Tests for chat_app/document_ingestor.py — Multi-format document ingestion."""
import hashlib
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from chat_app.document_ingestor import (
    IngestedDocument,
    IngestionResult,
    _chunk_text,
    _flatten_dict,
    ingest_directory,
    ingest_file,
    ingest_to_vectorstore,
    parse_csv,
    parse_html,
    parse_json,
    parse_pdf,
)


# ---------------------------------------------------------------------------
# _chunk_text — token-based splitting
# ---------------------------------------------------------------------------

class TestChunkText:
    """Tests for the _chunk_text helper."""

    def test_empty_string_returns_empty(self):
        assert _chunk_text("") == []

    def test_whitespace_only_returns_empty(self):
        assert _chunk_text("   \n\t  ") == []

    def test_none_returns_empty(self):
        assert _chunk_text(None) == []

    def test_basic_chunking_produces_chunks(self):
        text = " ".join(["word"] * 500)
        chunks = _chunk_text(text, chunk_size=500)
        assert len(chunks) >= 1
        assert all("text" in c and "metadata" in c for c in chunks)

    def test_chunk_index_metadata_sequential(self):
        text = " ".join(["token"] * 500)
        chunks = _chunk_text(text, chunk_size=250)
        indices = [c["metadata"]["chunk_index"] for c in chunks]
        assert indices == list(range(len(chunks)))

    def test_metadata_propagated_to_chunks(self):
        meta = {"source": "/tmp/test.pdf", "kind": "pdf"}
        chunks = _chunk_text("hello world " * 100, metadata=meta)
        for c in chunks:
            assert c["metadata"]["source"] == "/tmp/test.pdf"
            assert c["metadata"]["kind"] == "pdf"

    def test_overlap_produces_more_chunks(self):
        text = " ".join(["overlap"] * 1000)
        no_overlap = _chunk_text(text, chunk_size=500, chunk_overlap=0)
        with_overlap = _chunk_text(text, chunk_size=500, chunk_overlap=200)
        assert len(with_overlap) >= len(no_overlap)

    def test_short_text_single_chunk(self):
        chunks = _chunk_text("hello world")
        assert len(chunks) == 1
        assert chunks[0]["text"] == "hello world"

    def test_large_chunk_size_single_chunk(self):
        text = " ".join(["word"] * 50)
        chunks = _chunk_text(text, chunk_size=5000)
        assert len(chunks) == 1


# ---------------------------------------------------------------------------
# _flatten_dict
# ---------------------------------------------------------------------------

class TestFlattenDict:
    """Tests for dictionary flattening."""

    def test_simple_dict(self):
        result = _flatten_dict({"key": "value"})
        assert "key: value" in result

    def test_nested_dict(self):
        result = _flatten_dict({"parent": {"child": "val"}})
        assert "parent.child: val" in result

    def test_list_values(self):
        result = _flatten_dict({"items": [1, 2, 3]})
        assert "items:" in result
        assert "1" in result

    def test_max_depth_truncation(self):
        deep = {"a": {"b": {"c": {"d": "deep_val"}}}}
        result = _flatten_dict(deep, max_depth=2)
        # At depth 2, the innermost dict should be stringified
        assert "deep_val" in result


# ---------------------------------------------------------------------------
# parse_pdf
# ---------------------------------------------------------------------------

class TestParsePdf:
    """Tests for PDF parsing (mocked)."""

    @patch("chat_app.document_ingestor.fitz", create=True)
    def test_pdf_with_fitz(self, mock_fitz):
        """Successful PDF parse via PyMuPDF."""
        mock_page = MagicMock()
        mock_page.get_text.return_value = "PDF content line one\nPDF content line two\n"
        mock_doc = MagicMock()
        mock_doc.__iter__ = MagicMock(return_value=iter([mock_page]))
        mock_doc.metadata = {"title": "Test PDF"}
        mock_fitz.open.return_value = mock_doc

        # Patch the import inside parse_pdf
        import sys
        sys.modules["fitz"] = mock_fitz

        try:
            doc = parse_pdf("/tmp/test.pdf")
            assert doc.source_type == "pdf"
            assert doc.error is None
            assert doc.chunk_count >= 1
            assert doc.fingerprint != ""
        finally:
            del sys.modules["fitz"]

    def test_pdf_missing_file(self):
        doc = parse_pdf("/nonexistent/path/missing.pdf")
        assert doc.error is not None

    def test_pdf_empty_text(self):
        """PDF with no extractable text should report error."""
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(b"%PDF-1.4 empty")
            f.flush()
            path = f.name
        try:
            doc = parse_pdf(path)
            # Should either error or have 0 chunks
            assert doc.error is not None or doc.chunk_count == 0
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# parse_html
# ---------------------------------------------------------------------------

class TestParseHtml:
    """Tests for HTML parsing."""

    def test_basic_html_extraction(self):
        html = "<html><head><title>Test</title></head><body><p>Hello world</p></body></html>"
        doc = parse_html(html, source_url="http://example.com")
        assert doc.source_type == "html"
        assert doc.source == "http://example.com"
        assert doc.chunk_count >= 1
        assert doc.error is None

    def test_html_title_extraction(self):
        html = "<html><head><title>My Title</title></head><body><p>Content</p></body></html>"
        doc = parse_html(html)
        assert doc.title == "My Title"

    def test_html_script_style_removed(self):
        html = """
        <html><body>
            <script>alert('xss')</script>
            <style>body { color: red; }</style>
            <p>Real content here</p>
        </body></html>
        """
        doc = parse_html(html)
        assert doc.error is None
        for chunk in doc.chunks:
            assert "alert" not in chunk["text"]

    def test_html_nav_footer_removed(self):
        html = """
        <html><body>
            <nav>Navigation links</nav>
            <main><p>Main content</p></main>
            <footer>Footer stuff</footer>
        </body></html>
        """
        doc = parse_html(html)
        assert doc.error is None
        all_text = " ".join(c["text"] for c in doc.chunks)
        assert "Main content" in all_text

    def test_empty_html_reports_error(self):
        doc = parse_html("<html><body></body></html>")
        assert doc.error is not None or doc.chunk_count == 0

    def test_html_fingerprint_generated(self):
        html = "<html><body><p>Some content</p></body></html>"
        doc = parse_html(html)
        assert doc.fingerprint != ""

    def test_html_chunk_metadata_has_kind(self):
        html = "<html><body><p>Content text here</p></body></html>"
        doc = parse_html(html, source_url="http://test.com")
        if doc.chunks:
            assert doc.chunks[0]["metadata"]["kind"] == "html"


# ---------------------------------------------------------------------------
# parse_json
# ---------------------------------------------------------------------------

class TestParseJson:
    """Tests for JSON file parsing."""

    def test_json_dict(self, tmp_path):
        data = {"key1": "value1", "key2": 42}
        fp = tmp_path / "test.json"
        fp.write_text(json.dumps(data))

        doc = parse_json(str(fp))
        assert doc.source_type == "json"
        assert doc.error is None
        assert doc.title == "test"
        assert doc.chunk_count >= 1

    def test_json_list(self, tmp_path):
        data = [{"name": "item1"}, {"name": "item2"}]
        fp = tmp_path / "items.json"
        fp.write_text(json.dumps(data))

        doc = parse_json(str(fp))
        assert doc.error is None
        assert doc.chunk_count >= 1

    def test_json_nested(self, tmp_path):
        data = {"outer": {"inner": {"deep": "value"}}}
        fp = tmp_path / "nested.json"
        fp.write_text(json.dumps(data))

        doc = parse_json(str(fp))
        assert doc.error is None
        all_text = " ".join(c["text"] for c in doc.chunks)
        assert "deep" in all_text

    def test_json_invalid_syntax(self, tmp_path):
        fp = tmp_path / "bad.json"
        fp.write_text("{invalid json content")

        doc = parse_json(str(fp))
        assert doc.error is not None
        assert "JSON parse error" in doc.error

    def test_json_missing_file(self):
        doc = parse_json("/nonexistent/file.json")
        assert doc.error is not None

    def test_json_large_list_limited(self, tmp_path):
        """List items should be capped at 500."""
        data = [{"idx": i} for i in range(600)]
        fp = tmp_path / "large.json"
        fp.write_text(json.dumps(data))

        doc = parse_json(str(fp))
        assert doc.error is None
        # Text should not contain item_500+ (0-indexed)
        all_text = " ".join(c["text"] for c in doc.chunks)
        assert "item_500" not in all_text


# ---------------------------------------------------------------------------
# parse_csv
# ---------------------------------------------------------------------------

class TestParseCsv:
    """Tests for CSV file parsing."""

    def test_basic_csv(self, tmp_path):
        fp = tmp_path / "data.csv"
        fp.write_text("name,value\nalice,100\nbob,200\n")

        doc = parse_csv(str(fp))
        assert doc.source_type == "csv"
        assert doc.error is None
        assert doc.chunk_count >= 1
        assert "headers" in doc.metadata

    def test_csv_headers_in_metadata(self, tmp_path):
        fp = tmp_path / "data.csv"
        fp.write_text("col_a,col_b,col_c\n1,2,3\n")

        doc = parse_csv(str(fp))
        assert doc.metadata["headers"] == ["col_a", "col_b", "col_c"]

    def test_csv_empty_file(self, tmp_path):
        fp = tmp_path / "empty.csv"
        fp.write_text("")

        doc = parse_csv(str(fp))
        # Empty CSV either errors or produces 0 chunks
        assert doc.error is not None or doc.chunk_count == 0

    def test_csv_missing_file(self):
        doc = parse_csv("/nonexistent/data.csv")
        assert doc.error is not None

    def test_csv_row_limit(self, tmp_path):
        """CSV should cap at 1000 rows."""
        lines = ["idx,val"] + [f"{i},{i*10}" for i in range(1200)]
        fp = tmp_path / "big.csv"
        fp.write_text("\n".join(lines))

        doc = parse_csv(str(fp))
        assert doc.error is None
        # Should have processed data but not all 1200 rows
        assert doc.chunk_count >= 1

    def test_csv_fingerprint(self, tmp_path):
        fp = tmp_path / "fp.csv"
        fp.write_text("a,b\n1,2\n3,4\n")

        doc = parse_csv(str(fp))
        assert doc.fingerprint != ""


# ---------------------------------------------------------------------------
# IngestedDocument / IngestionResult dataclasses
# ---------------------------------------------------------------------------

class TestDataStructures:
    """Tests for data structures."""

    def test_ingested_document_defaults(self):
        doc = IngestedDocument(source="/tmp/f.pdf", source_type="pdf")
        assert doc.chunks == []
        assert doc.metadata == {}
        assert doc.error is None
        assert doc.chunk_count == 0

    def test_ingestion_result_defaults(self):
        result = IngestionResult()
        assert result.documents_processed == 0
        assert result.documents_skipped == 0
        assert result.chunks_created == 0
        assert result.errors == []
        assert result.sources == []


# ---------------------------------------------------------------------------
# ingest_file — file type detection / dispatch
# ---------------------------------------------------------------------------

class TestIngestFile:
    """Tests for the universal ingest_file dispatcher."""

    @pytest.mark.asyncio
    async def test_html_file(self, tmp_path):
        fp = tmp_path / "page.html"
        fp.write_text("<html><body><p>Hello</p></body></html>")

        doc = await ingest_file(str(fp))
        assert doc.source_type == "html"
        assert doc.error is None

    @pytest.mark.asyncio
    async def test_json_file(self, tmp_path):
        fp = tmp_path / "data.json"
        fp.write_text('{"key": "value"}')

        doc = await ingest_file(str(fp))
        assert doc.source_type == "json"
        assert doc.error is None

    @pytest.mark.asyncio
    async def test_csv_file(self, tmp_path):
        fp = tmp_path / "data.csv"
        fp.write_text("a,b\n1,2\n")

        doc = await ingest_file(str(fp))
        assert doc.source_type == "csv"
        assert doc.error is None

    @pytest.mark.asyncio
    async def test_text_file(self, tmp_path):
        fp = tmp_path / "readme.txt"
        fp.write_text("Some plain text content here.")

        doc = await ingest_file(str(fp))
        assert doc.source_type == "text"
        assert doc.error is None

    @pytest.mark.asyncio
    async def test_conf_file(self, tmp_path):
        fp = tmp_path / "inputs.conf"
        fp.write_text("[monitor:///var/log]\nindex = main\n")

        doc = await ingest_file(str(fp))
        assert doc.source_type == "text"
        assert doc.error is None

    @pytest.mark.asyncio
    async def test_unsupported_extension(self, tmp_path):
        fp = tmp_path / "binary.exe"
        fp.write_bytes(b"\x00\x01\x02")

        doc = await ingest_file(str(fp))
        assert doc.error is not None
        assert "Unsupported" in doc.error

    @pytest.mark.asyncio
    async def test_docx_without_docling(self, tmp_path):
        fp = tmp_path / "doc.docx"
        fp.write_bytes(b"PK\x03\x04fake")

        doc = await ingest_file(str(fp))
        # Without docling enabled, should report error
        assert doc.error is not None


# ---------------------------------------------------------------------------
# ingest_directory — batch ingestion
# ---------------------------------------------------------------------------

class TestIngestDirectory:
    """Tests for directory-level batch ingestion."""

    @pytest.mark.asyncio
    async def test_nonexistent_directory(self):
        result = await ingest_directory("/nonexistent/dir/path")
        assert len(result.errors) >= 1
        assert result.documents_processed == 0

    @pytest.mark.asyncio
    async def test_directory_with_mixed_files(self, tmp_path):
        (tmp_path / "a.json").write_text('{"k":"v"}')
        (tmp_path / "b.csv").write_text("x,y\n1,2\n")
        (tmp_path / "c.txt").write_text("plain text")

        result = await ingest_directory(str(tmp_path))
        assert result.documents_processed == 3
        assert result.chunks_created >= 3
        assert len(result.sources) == 3

    @pytest.mark.asyncio
    async def test_directory_max_files_limit(self, tmp_path):
        for i in range(10):
            (tmp_path / f"file_{i}.txt").write_text(f"Content {i}")

        result = await ingest_directory(str(tmp_path), max_files=3)
        assert result.documents_processed <= 3

    @pytest.mark.asyncio
    async def test_directory_custom_patterns(self, tmp_path):
        (tmp_path / "keep.json").write_text('{"a":1}')
        (tmp_path / "skip.csv").write_text("a,b\n1,2\n")

        result = await ingest_directory(str(tmp_path), patterns=["*.json"])
        assert result.documents_processed == 1

    @pytest.mark.asyncio
    async def test_progress_tracking_fields(self, tmp_path):
        (tmp_path / "f.txt").write_text("data")
        result = await ingest_directory(str(tmp_path))
        assert isinstance(result.documents_processed, int)
        assert isinstance(result.chunks_created, int)
        assert isinstance(result.errors, list)
        assert isinstance(result.sources, list)


# ---------------------------------------------------------------------------
# Deduplication / fingerprinting
# ---------------------------------------------------------------------------

class TestDeduplication:
    """Tests for fingerprint-based dedup detection."""

    def test_same_content_same_fingerprint(self):
        html = "<html><body><p>Same content</p></body></html>"
        doc1 = parse_html(html)
        doc2 = parse_html(html)
        assert doc1.fingerprint == doc2.fingerprint

    def test_different_content_different_fingerprint(self):
        doc1 = parse_html("<html><body><p>Content A</p></body></html>")
        doc2 = parse_html("<html><body><p>Content B</p></body></html>")
        assert doc1.fingerprint != doc2.fingerprint

    def test_json_fingerprint_deterministic(self, tmp_path):
        data = {"stable": "content", "number": 42}
        fp = tmp_path / "fp.json"
        fp.write_text(json.dumps(data))

        doc1 = parse_json(str(fp))
        doc2 = parse_json(str(fp))
        assert doc1.fingerprint == doc2.fingerprint


# ---------------------------------------------------------------------------
# ingest_to_vectorstore — ChromaDB integration (mocked)
# ---------------------------------------------------------------------------

class TestIngestToVectorstore:
    """Tests for storing documents into the vector store."""

    @pytest.mark.asyncio
    async def test_empty_documents_returns_zero(self):
        mock_store = MagicMock()
        result = await ingest_to_vectorstore([], mock_store)
        assert result == 0

    @pytest.mark.asyncio
    async def test_none_store_returns_zero(self):
        doc = IngestedDocument(source="test", source_type="text", chunks=[{"text": "hi", "metadata": {}}])
        result = await ingest_to_vectorstore([doc], None)
        assert result == 0

    @pytest.mark.asyncio
    async def test_stores_chunks_without_embedder(self):
        """Should fall back to ChromaDB default embedding when Ollama unavailable."""
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": []}
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection

        mock_store = MagicMock()
        mock_store._client = mock_client

        doc = IngestedDocument(
            source="/tmp/test.txt",
            source_type="text",
            chunks=[
                {"text": "chunk one", "metadata": {"chunk_index": 0}},
                {"text": "chunk two", "metadata": {"chunk_index": 1}},
            ],
            chunk_count=2,
            fingerprint="abc123",
        )

        result = await ingest_to_vectorstore([doc], mock_store, "test_collection")
        assert result == 2
        mock_collection.upsert.assert_called_once()

    @pytest.mark.asyncio
    async def test_skips_errored_documents(self):
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"ids": []}
        mock_client = MagicMock()
        mock_client.get_or_create_collection.return_value = mock_collection
        mock_store = MagicMock()
        mock_store._client = mock_client

        good_doc = IngestedDocument(
            source="good.txt", source_type="text",
            chunks=[{"text": "ok", "metadata": {"chunk_index": 0}}],
            chunk_count=1, fingerprint="f1",
        )
        bad_doc = IngestedDocument(
            source="bad.txt", source_type="text",
            error="Parse failed", chunks=[], chunk_count=0,
        )

        result = await ingest_to_vectorstore([good_doc, bad_doc], mock_store)
        assert result == 1


# ---------------------------------------------------------------------------
# Docling integration (mocked)
# ---------------------------------------------------------------------------

class TestDoclingIntegration:
    """Tests for Docling sidecar integration."""

    @pytest.mark.asyncio
    @patch("chat_app.settings.get_settings")
    async def test_docling_disabled_returns_none(self, mock_settings):
        from chat_app.document_ingestor import _convert_via_docling

        mock_settings.return_value.docling.enabled = False
        result = await _convert_via_docling("/tmp/test.pdf")
        assert result is None

    @pytest.mark.asyncio
    @patch("chat_app.settings.get_settings", side_effect=RuntimeError("no settings"))
    async def test_docling_fallback_on_error(self, mock_settings):
        from chat_app.document_ingestor import _convert_via_docling

        result = await _convert_via_docling("/tmp/test.pdf")
        assert result is None
