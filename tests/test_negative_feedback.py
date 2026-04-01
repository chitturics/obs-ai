"""
Tests for chat_app.negative_feedback module.

Covers:
- _fingerprint_text: deterministic hashing
- _get_chroma_client: URL parsing
- _get_or_create_collection: create vs get existing
- add_negative_feedback: storage, deduplication, error handling
- filter_negative_results: filtering bad answers from search results
- get_negative_feedback_context: prompt injection of bad examples
- get_negative_feedback_stats: collection statistics
- get_collection: dimension mismatch recovery
"""

import hashlib
import sys
import pytest
from unittest.mock import MagicMock, patch

# Pre-mock heavy dependencies not available in test environment.
# chromadb and vectorstore are imported lazily inside functions in negative_feedback.py
# via `import chromadb` and `from vectorstore import get_embeddings_model`.
if "chromadb" not in sys.modules:
    sys.modules["chromadb"] = MagicMock()

if "vectorstore" not in sys.modules:
    _vs_mock = MagicMock()
    _vs_mock.get_embeddings_model = MagicMock()
    sys.modules["vectorstore"] = _vs_mock

from chat_app.negative_feedback import (
    NEGATIVE_FEEDBACK_COLLECTION,
    _fingerprint_text,
    _get_or_create_collection,
    add_negative_feedback,
    filter_negative_results,
    get_negative_feedback_context,
    get_negative_feedback_stats,
    get_collection,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_embeddings():
    """Build a mock embeddings model."""
    embeddings = MagicMock()
    embeddings.embed_query.return_value = [0.1] * 768
    return embeddings


def _setup_vectorstore_embeddings():
    """Set up the vectorstore sys.modules mock to return proper embeddings."""
    mock_embed = _mock_embeddings()
    sys.modules["vectorstore"].get_embeddings_model = MagicMock(return_value=mock_embed)
    return mock_embed


# ---------------------------------------------------------------------------
# 1. _fingerprint_text
# ---------------------------------------------------------------------------

class TestFingerprintText:
    """Verify deterministic text fingerprinting."""

    def test_deterministic(self):
        fp1 = _fingerprint_text("hello world")
        fp2 = _fingerprint_text("hello world")
        assert fp1 == fp2

    def test_different_texts_different_fingerprints(self):
        fp1 = _fingerprint_text("question A")
        fp2 = _fingerprint_text("question B")
        assert fp1 != fp2

    def test_sha256_format(self):
        fp = _fingerprint_text("test")
        assert len(fp) == 64  # SHA256 hex digest
        assert all(c in "0123456789abcdef" for c in fp)

    def test_matches_hashlib(self):
        text = "What is tstats?"
        expected = hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()
        assert _fingerprint_text(text) == expected

    def test_empty_string(self):
        fp = _fingerprint_text("")
        assert len(fp) == 64  # Still produces valid hash

    def test_unicode_text(self):
        fp = _fingerprint_text("unicode test: cafe\u0301")
        assert len(fp) == 64


# ---------------------------------------------------------------------------
# 2. _get_or_create_collection
# ---------------------------------------------------------------------------

class TestGetOrCreateCollection:
    """Verify collection retrieval and creation."""

    def test_get_existing_collection(self):
        mock_coll = MagicMock()
        client = MagicMock()
        client.get_collection.return_value = mock_coll

        collection, returned_client = _get_or_create_collection(client)
        assert collection is mock_coll
        assert returned_client is client
        client.get_collection.assert_called_once_with(NEGATIVE_FEEDBACK_COLLECTION)

    def test_create_new_collection_when_missing(self):
        client = MagicMock()
        client.get_collection.side_effect = RuntimeError("not found")
        mock_coll = MagicMock()
        client.create_collection.return_value = mock_coll

        collection, returned_client = _get_or_create_collection(client)
        assert collection is mock_coll
        client.create_collection.assert_called_once()

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_creates_client_when_none(self, mock_get_client):
        mock_coll = MagicMock()
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_coll
        mock_get_client.return_value = mock_client

        collection, returned_client = _get_or_create_collection(client=None)
        mock_get_client.assert_called_once()
        assert collection is mock_coll


# ---------------------------------------------------------------------------
# 3. add_negative_feedback
# ---------------------------------------------------------------------------

class TestAddNegativeFeedback:
    """Test storing negative feedback in ChromaDB.

    add_negative_feedback() does a local `from vectorstore import get_embeddings_model`
    so we set up the mock on sys.modules["vectorstore"] and also mock
    _get_or_create_collection to avoid real ChromaDB calls.
    """

    @pytest.fixture(autouse=True)
    def setup_embed(self):
        """Ensure vectorstore.get_embeddings_model returns a proper mock."""
        _setup_vectorstore_embeddings()

    @patch("chat_app.negative_feedback._get_or_create_collection")
    def test_add_new_feedback(self, mock_get_coll):
        mock_coll = MagicMock()
        mock_coll.get.return_value = {"ids": []}  # Not a duplicate
        mock_get_coll.return_value = (mock_coll, MagicMock())

        success, error = add_negative_feedback(
            question="How to optimize joins?",
            bad_answer="Use join for everything",
            username="testuser",
            reason="join is slow",
        )

        assert success is True
        assert error is None
        mock_coll.add.assert_called_once()

        # Verify metadata fields
        call_kwargs = mock_coll.add.call_args
        metadata = call_kwargs[1]["metadatas"][0]
        assert metadata["kind"] == "negative_feedback"
        assert metadata["username"] == "testuser"
        assert metadata["reason"] == "join is slow"

    @patch("chat_app.negative_feedback._get_or_create_collection")
    def test_skip_duplicate(self, mock_get_coll):
        """Already-stored feedback should be skipped."""
        mock_coll = MagicMock()
        mock_coll.get.return_value = {"ids": ["existing-fingerprint"]}
        mock_get_coll.return_value = (mock_coll, MagicMock())

        success, error = add_negative_feedback(
            question="Q", bad_answer="A", username="user",
        )

        assert success is True
        assert error == "Already stored"
        mock_coll.add.assert_not_called()

    @patch("chat_app.negative_feedback._get_or_create_collection")
    def test_default_reason(self, mock_get_coll):
        """Reason defaults to 'thumbs_down' when not provided."""
        mock_coll = MagicMock()
        mock_coll.get.return_value = {"ids": []}
        mock_get_coll.return_value = (mock_coll, MagicMock())

        add_negative_feedback("Q", "A")

        call_kwargs = mock_coll.add.call_args
        metadata = call_kwargs[1]["metadatas"][0]
        assert metadata["reason"] == "thumbs_down"

    @patch("chat_app.negative_feedback._get_or_create_collection")
    def test_truncates_long_fields(self, mock_get_coll):
        """Question is truncated to 500 chars, bad_answer preview to 200."""
        mock_coll = MagicMock()
        mock_coll.get.return_value = {"ids": []}
        mock_get_coll.return_value = (mock_coll, MagicMock())

        long_question = "x" * 1000
        long_answer = "y" * 500

        add_negative_feedback(long_question, long_answer)

        call_kwargs = mock_coll.add.call_args
        metadata = call_kwargs[1]["metadatas"][0]
        assert len(metadata["question"]) <= 500
        assert len(metadata["bad_answer_preview"]) <= 200

    @patch("chat_app.negative_feedback._get_or_create_collection", side_effect=RuntimeError("ChromaDB down"))
    def test_chromadb_failure(self, mock_get_coll):
        success, error = add_negative_feedback("Q", "A")
        assert success is False
        assert "ChromaDB down" in error

    @patch("chat_app.negative_feedback._get_or_create_collection")
    def test_document_format(self, mock_get_coll):
        """Stored document should have Question/Bad Answer format."""
        mock_coll = MagicMock()
        mock_coll.get.return_value = {"ids": []}
        mock_get_coll.return_value = (mock_coll, MagicMock())

        add_negative_feedback("What is eval?", "eval deletes data")

        call_kwargs = mock_coll.add.call_args
        doc = call_kwargs[1]["documents"][0]
        assert "Question: What is eval?" in doc
        assert "Bad Answer: eval deletes data" in doc

    @patch("chat_app.negative_feedback._get_or_create_collection")
    def test_default_username(self, mock_get_coll):
        """Username defaults to 'unknown' when not provided."""
        mock_coll = MagicMock()
        mock_coll.get.return_value = {"ids": []}
        mock_get_coll.return_value = (mock_coll, MagicMock())

        add_negative_feedback("Q", "A")

        call_kwargs = mock_coll.add.call_args
        metadata = call_kwargs[1]["metadatas"][0]
        assert metadata["username"] == "unknown"


# ---------------------------------------------------------------------------
# 4. filter_negative_results
# ---------------------------------------------------------------------------

class TestFilterNegativeResults:
    """Test filtering bad answers from search results.

    filter_negative_results() does local imports:
      from vectorstore import get_embeddings_model
    We set up the mock on sys.modules["vectorstore"].
    """

    @pytest.fixture(autouse=True)
    def setup_embed(self):
        _setup_vectorstore_embeddings()

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_filter_removes_matching_results(self, mock_get_client):
        """Results with fingerprints matching negative feedback should be removed."""
        bad_text = "This is a bad answer"
        bad_fp = _fingerprint_text(bad_text)

        mock_coll = MagicMock()
        mock_coll.count.return_value = 1
        mock_coll.query.return_value = {
            "metadatas": [[{"fingerprint": bad_fp}]],
        }

        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_coll
        mock_get_client.return_value = mock_client

        search_results = [
            {"text": bad_text},  # This should be filtered
            {"text": "This is a good answer"},  # This should remain
        ]

        filtered = filter_negative_results(search_results, "test question")
        assert len(filtered) == 1
        assert filtered[0]["text"] == "This is a good answer"

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_no_collection_returns_original(self, mock_get_client):
        """When negative feedback collection doesn't exist, return all results."""
        mock_client = MagicMock()
        mock_client.get_collection.side_effect = RuntimeError("not found")
        mock_get_client.return_value = mock_client

        results = [{"text": "answer 1"}, {"text": "answer 2"}]
        filtered = filter_negative_results(results, "question")
        assert filtered == results

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_empty_collection_returns_original(self, mock_get_client):
        """Empty collection should return all results unchanged."""
        mock_coll = MagicMock()
        mock_coll.count.return_value = 0
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_coll
        mock_get_client.return_value = mock_client

        results = [{"text": "answer"}]
        filtered = filter_negative_results(results, "question")
        assert filtered == results

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_error_returns_original(self, mock_get_client):
        """Errors during filtering should return original results."""
        # Make the embedding call fail
        sys.modules["vectorstore"].get_embeddings_model = MagicMock(side_effect=RuntimeError("embed error"))

        mock_coll = MagicMock()
        mock_coll.count.return_value = 5
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_coll
        mock_get_client.return_value = mock_client

        results = [{"text": "answer"}]
        filtered = filter_negative_results(results, "question")
        assert filtered == results

        # Restore
        _setup_vectorstore_embeddings()

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_filter_with_tuple_results(self, mock_get_client):
        """Should handle (doc, score) tuple format."""
        bad_text = "bad answer here"
        bad_fp = _fingerprint_text(bad_text)

        mock_coll = MagicMock()
        mock_coll.count.return_value = 1
        mock_coll.query.return_value = {"metadatas": [[{"fingerprint": bad_fp}]]}
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_coll
        mock_get_client.return_value = mock_client

        # Create mock Document objects
        bad_doc = MagicMock()
        bad_doc.page_content = bad_text
        good_doc = MagicMock()
        good_doc.page_content = "good answer"

        results = [(bad_doc, 0.95), (good_doc, 0.80)]
        filtered = filter_negative_results(results, "question")
        assert len(filtered) == 1
        assert filtered[0][0].page_content == "good answer"

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_no_matches_returns_all(self, mock_get_client):
        """When no fingerprints match, all results should remain."""
        mock_coll = MagicMock()
        mock_coll.count.return_value = 1
        mock_coll.query.return_value = {
            "metadatas": [[{"fingerprint": "nonexistent_fingerprint"}]],
        }
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_coll
        mock_get_client.return_value = mock_client

        results = [{"text": "answer 1"}, {"text": "answer 2"}]
        filtered = filter_negative_results(results, "question")
        assert len(filtered) == 2


# ---------------------------------------------------------------------------
# 5. get_negative_feedback_context
# ---------------------------------------------------------------------------

class TestGetNegativeFeedbackContext:
    """Test prompt context generation from negative feedback."""

    @pytest.fixture(autouse=True)
    def setup_embed(self):
        _setup_vectorstore_embeddings()

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_returns_formatted_context(self, mock_get_client):
        mock_coll = MagicMock()
        mock_coll.count.return_value = 2
        mock_coll.query.return_value = {
            "documents": [["Question: Q1\n\nBad Answer: A1", "Question: Q2\n\nBad Answer: A2"]],
            "metadatas": [[
                {"reason": "inaccurate", "timestamp": "2026-01-01T00:00:00Z"},
                {"reason": "incomplete", "timestamp": "2026-01-02T00:00:00Z"},
            ]],
        }
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_coll
        mock_get_client.return_value = mock_client

        context = get_negative_feedback_context("test question")
        assert "AVOID THESE BAD ANSWER PATTERNS" in context
        assert "Bad Example 1" in context
        assert "Bad Example 2" in context
        assert "inaccurate" in context
        assert "incomplete" in context

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_no_collection_returns_empty(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.get_collection.side_effect = RuntimeError("not found")
        mock_get_client.return_value = mock_client

        context = get_negative_feedback_context("test question")
        assert context == ""

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_empty_collection_returns_empty(self, mock_get_client):
        mock_coll = MagicMock()
        mock_coll.count.return_value = 0
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_coll
        mock_get_client.return_value = mock_client

        context = get_negative_feedback_context("test question")
        assert context == ""

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_correction_highlighted(self, mock_get_client):
        """Documents with Correction: section should have USE THIS INSTEAD."""
        mock_coll = MagicMock()
        mock_coll.count.return_value = 1
        mock_coll.query.return_value = {
            "documents": [["Question: How to join?\n\nBad Answer: Use join\n\nCorrection: Use stats instead"]],
            "metadatas": [[{"reason": "slow", "timestamp": "2026-01-01"}]],
        }
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_coll
        mock_get_client.return_value = mock_client

        context = get_negative_feedback_context("join tables")
        assert "USE THIS INSTEAD" in context
        assert "Use stats instead" in context

    @patch("chat_app.negative_feedback._get_chroma_client", side_effect=RuntimeError("connection error"))
    def test_connection_error_returns_empty(self, mock_get_client):
        context = get_negative_feedback_context("test")
        assert context == ""


# ---------------------------------------------------------------------------
# 6. get_negative_feedback_stats
# ---------------------------------------------------------------------------

class TestGetNegativeFeedbackStats:
    """Test collection statistics retrieval."""

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_stats_existing_collection(self, mock_get_client):
        mock_coll = MagicMock()
        mock_coll.count.return_value = 10
        mock_coll.get.return_value = {
            "metadatas": [
                {"question": "Q1", "timestamp": "2026-01-01", "username": "admin", "reason": "bad"},
                {"question": "Q2", "timestamp": "2026-01-02", "username": "user1", "reason": "wrong"},
            ]
        }
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_coll
        mock_get_client.return_value = mock_client

        stats = get_negative_feedback_stats()
        assert stats["count"] == 10
        assert stats["exists"] is True
        assert len(stats["recent_examples"]) == 2
        assert stats["recent_examples"][0]["username"] == "admin"

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_stats_no_collection(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.get_collection.side_effect = RuntimeError("not found")
        mock_get_client.return_value = mock_client

        stats = get_negative_feedback_stats()
        assert stats["count"] == 0
        assert stats["exists"] is False

    @patch("chat_app.negative_feedback._get_chroma_client", side_effect=RuntimeError("connection failed"))
    def test_stats_connection_error(self, mock_get_client):
        stats = get_negative_feedback_stats()
        assert stats["count"] == 0
        assert stats["exists"] is False
        assert "error" in stats

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_stats_empty_collection(self, mock_get_client):
        mock_coll = MagicMock()
        mock_coll.count.return_value = 0
        mock_coll.get.return_value = {"metadatas": []}
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_coll
        mock_get_client.return_value = mock_client

        stats = get_negative_feedback_stats()
        assert stats["count"] == 0
        assert stats["exists"] is True
        assert stats["recent_examples"] == []


# ---------------------------------------------------------------------------
# 7. get_collection (dimension mismatch recovery)
# ---------------------------------------------------------------------------

class TestGetCollection:
    """Test collection retrieval with auto-recovery."""

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_get_existing_collection(self, mock_get_client):
        mock_coll = MagicMock()
        mock_coll.count.return_value = 5
        mock_coll.query.return_value = {"documents": [["test"]]}
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_coll
        mock_get_client.return_value = mock_client

        result = get_collection()
        assert result is mock_coll

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_create_collection_when_not_found(self, mock_get_client):
        mock_client = MagicMock()
        mock_client.get_collection.side_effect = RuntimeError("Collection does not exist")
        mock_new_coll = MagicMock()
        mock_client.create_collection.return_value = mock_new_coll
        mock_get_client.return_value = mock_client

        result = get_collection()
        assert result is mock_new_coll
        mock_client.create_collection.assert_called_once()

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_recreate_on_dimension_mismatch(self, mock_get_client):
        """Dimension mismatch should delete and recreate the collection."""
        mock_coll = MagicMock()
        mock_coll.count.return_value = 5
        mock_coll.query.side_effect = RuntimeError("Dimension mismatch: expected 384 got 768")

        mock_new_coll = MagicMock()
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_coll
        mock_client.create_collection.return_value = mock_new_coll
        mock_get_client.return_value = mock_client

        result = get_collection()
        assert result is mock_new_coll
        mock_client.delete_collection.assert_called_once_with(NEGATIVE_FEEDBACK_COLLECTION)
        mock_client.create_collection.assert_called_once()

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_empty_collection_skips_validation(self, mock_get_client):
        """Empty collection (count=0) should not attempt query validation."""
        mock_coll = MagicMock()
        mock_coll.count.return_value = 0
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_coll
        mock_get_client.return_value = mock_client

        result = get_collection()
        assert result is mock_coll
        mock_coll.query.assert_not_called()

    @patch("chat_app.negative_feedback._get_chroma_client", side_effect=RuntimeError("No ChromaDB"))
    def test_connection_failure_returns_none(self, mock_get_client):
        result = get_collection()
        assert result is None

    @patch("chat_app.negative_feedback._get_chroma_client")
    def test_non_dimension_query_error_reraises(self, mock_get_client):
        """Non-dimension query errors should propagate (then caught by outer try)."""
        mock_coll = MagicMock()
        mock_coll.count.return_value = 5
        mock_coll.query.side_effect = RuntimeError("Some other error")
        mock_client = MagicMock()
        mock_client.get_collection.return_value = mock_coll
        mock_get_client.return_value = mock_client

        # The outer except catches it and returns None
        result = get_collection()
        assert result is None
        mock_client.delete_collection.assert_not_called()


# ---------------------------------------------------------------------------
# 8. _get_chroma_client URL parsing
# ---------------------------------------------------------------------------

class TestGetChromaClient:
    """Test ChromaDB client URL parsing.

    _get_chroma_client() does `import chromadb` locally, so we must
    use patch.dict(sys.modules, ...) to intercept the import.
    """

    @patch("chat_app.negative_feedback.get_settings")
    def test_parses_http_url(self, mock_settings):
        from chat_app.negative_feedback import _get_chroma_client

        mock_cfg = MagicMock()
        mock_cfg.http_url = "http://chat_chroma_db:8001"
        mock_settings.return_value.chroma = mock_cfg

        mock_chromadb = MagicMock()
        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            _get_chroma_client()
        mock_chromadb.HttpClient.assert_called_once_with(host="chat_chroma_db", port=8001)

    @patch("chat_app.negative_feedback.get_settings")
    def test_parses_https_url(self, mock_settings):
        from chat_app.negative_feedback import _get_chroma_client

        mock_cfg = MagicMock()
        mock_cfg.http_url = "https://secure-chroma:9000"
        mock_settings.return_value.chroma = mock_cfg

        mock_chromadb = MagicMock()
        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            _get_chroma_client()
        mock_chromadb.HttpClient.assert_called_once_with(host="secure-chroma", port=9000)

    @patch("chat_app.negative_feedback.get_settings")
    def test_parses_localhost_url(self, mock_settings):
        from chat_app.negative_feedback import _get_chroma_client

        mock_cfg = MagicMock()
        mock_cfg.http_url = "http://localhost:8001"
        mock_settings.return_value.chroma = mock_cfg

        mock_chromadb = MagicMock()
        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            _get_chroma_client()
        mock_chromadb.HttpClient.assert_called_once_with(host="localhost", port=8001)
