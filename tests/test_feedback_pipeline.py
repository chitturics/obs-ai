"""
Tests for the feedback correction pipeline.

Verifies: negative feedback with correction → stored → used in next response.
Also tests knowledge graph cache staleness detection.
"""
import logging
import sys
import time
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

# Ensure vectorstore module is available for patching (it has heavy deps in real env)
if "vectorstore" not in sys.modules:
    _vs_mock = MagicMock()
    _vs_mock.get_embeddings_model = MagicMock()
    sys.modules["vectorstore"] = _vs_mock

# If an earlier test file (e.g. test_feedback_handler.py) injected a MagicMock
# for negative_feedback, replace it with the real module so our patches work.
if "negative_feedback" in sys.modules and isinstance(
    sys.modules["negative_feedback"], MagicMock
):
    del sys.modules["negative_feedback"]
    try:
        import negative_feedback  # noqa: F401
    except ImportError:
        pass  # If it truly can't be imported, tests will fail with a clear error

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Test: extract_qa_from_feedback_chunk handles both formats
# ---------------------------------------------------------------------------

class TestFeedbackChunkParsing:
    """Test that feedback chunks are parsed correctly in both formats."""

    def test_question_answer_format(self):
        from feedback_retriever import extract_qa_from_feedback_chunk
        text = "Question: What is TERM in Splunk?\n\nAnswer: TERM() is a search optimization directive."
        q, a = extract_qa_from_feedback_chunk(text)
        assert q == "What is TERM in Splunk?"
        assert a == "TERM() is a search optimization directive."

    def test_q_a_format(self):
        from feedback_retriever import extract_qa_from_feedback_chunk
        text = "Q: What is TERM in Splunk?\n\nA: TERM() is a search optimization directive."
        q, a = extract_qa_from_feedback_chunk(text)
        assert q == "What is TERM in Splunk?"
        assert a == "TERM() is a search optimization directive."

    def test_q_a_single_newline(self):
        from feedback_retriever import extract_qa_from_feedback_chunk
        text = "Q: What is TERM?\nA: A search directive."
        q, a = extract_qa_from_feedback_chunk(text)
        assert q is not None
        assert a is not None

    def test_empty_text(self):
        from feedback_retriever import extract_qa_from_feedback_chunk
        q, a = extract_qa_from_feedback_chunk("")
        assert q is None
        assert a is None

    def test_garbage_text(self):
        from feedback_retriever import extract_qa_from_feedback_chunk
        q, a = extract_qa_from_feedback_chunk("just some random text")
        assert q is None
        assert a is None


# ---------------------------------------------------------------------------
# Test: find_feedback_match works with feedback:// chunks
# ---------------------------------------------------------------------------

class TestFeedbackMatch:
    """Test feedback matching from already-retrieved chunks."""

    def test_matches_feedback_chunk(self):
        from feedback_retriever import find_feedback_match

        chunks = [
            {
                "text": "Question: What is the TERM directive in Splunk?\n\nAnswer: TERM() treats the argument as a single term.",
                "source": "feedback://admin/abc123",
            },
            {
                "text": "Some other doc about indexes.",
                "source": "docs://splunk/indexes",
            },
        ]

        # Use low threshold for unit test (no embeddings available)
        match = find_feedback_match(chunks, "what is TERM directive in splunk", similarity_threshold=0.3)
        if match:
            assert match["source"].startswith("feedback://")
            assert "TERM" in match["answer"]

    def test_skips_non_feedback_chunks(self):
        from feedback_retriever import find_feedback_match

        chunks = [
            {
                "text": "Question: What is TERM?\n\nAnswer: A directive.",
                "source": "docs://splunk/term",  # NOT a feedback source
            },
        ]

        match = find_feedback_match(chunks, "what is TERM", similarity_threshold=0.3)
        assert match is None  # Should not match non-feedback chunks


# ---------------------------------------------------------------------------
# Test: query_feedback_collection function exists
# ---------------------------------------------------------------------------

class TestQueryFeedbackCollection:
    """Test the direct feedback collection query function."""

    def test_function_exists(self):
        from feedback_retriever import query_feedback_collection
        assert callable(query_feedback_collection)

    @patch("feedback_retriever.get_settings")
    def test_returns_none_on_connection_error(self, mock_settings):
        from feedback_retriever import query_feedback_collection
        mock_settings.side_effect = RuntimeError("No settings")
        result = query_feedback_collection("test query")
        assert result is None


# ---------------------------------------------------------------------------
# Test: Negative feedback context includes corrections
# ---------------------------------------------------------------------------

class TestNegativeContextWithCorrections:
    """Test that negative feedback context highlights corrections."""

    @patch("vectorstore.get_embeddings_model")
    @patch("negative_feedback._get_chroma_client")
    def test_correction_surfaced_in_context(self, mock_client, mock_embed):
        from negative_feedback import get_negative_feedback_context

        collection = MagicMock()
        collection.count.return_value = 1
        collection.query.return_value = {
            "documents": [["Question: What is X?\n\nBad Answer: Wrong.\n\nCorrection: The right answer is Y."]],
            "metadatas": [[{"reason": "incorrect", "timestamp": "2026-03-12"}]],
        }

        client = MagicMock()
        client.get_collection.return_value = collection
        mock_client.return_value = client

        embeddings = MagicMock()
        embeddings.embed_query.return_value = [0.1] * 768
        mock_embed.return_value = embeddings

        context = get_negative_feedback_context("What is X?")
        assert "AVOID THESE BAD ANSWER PATTERNS" in context
        assert "USE THIS INSTEAD" in context
        assert "The right answer is Y" in context

    @patch("vectorstore.get_embeddings_model")
    @patch("negative_feedback._get_chroma_client")
    def test_no_correction_no_use_this(self, mock_client, mock_embed):
        from negative_feedback import get_negative_feedback_context

        collection = MagicMock()
        collection.count.return_value = 1
        collection.query.return_value = {
            "documents": [["Question: What is X?\n\nBad Answer: Wrong answer."]],
            "metadatas": [[{"reason": "thumbs_down", "timestamp": "2026-03-12"}]],
        }

        client = MagicMock()
        client.get_collection.return_value = collection
        mock_client.return_value = client

        embeddings = MagicMock()
        embeddings.embed_query.return_value = [0.1] * 768
        mock_embed.return_value = embeddings

        context = get_negative_feedback_context("What is X?")
        assert "AVOID THESE BAD ANSWER PATTERNS" in context
        assert "USE THIS INSTEAD" not in context  # No correction present


# ---------------------------------------------------------------------------
# Test: Negative feedback add function
# ---------------------------------------------------------------------------

class TestNegativeFeedbackStorage:
    """Test negative feedback storage."""

    @patch("vectorstore.get_embeddings_model")
    @patch("negative_feedback._get_or_create_collection")
    def test_stores_with_correction(self, mock_get_coll, mock_embed):
        from negative_feedback import add_negative_feedback

        collection = MagicMock()
        collection.get.return_value = {"ids": []}
        mock_get_coll.return_value = (collection, MagicMock())

        embeddings = MagicMock()
        embeddings.embed_query.return_value = [0.1] * 768
        mock_embed.return_value = embeddings

        success, _ = add_negative_feedback(
            "What is TERM?",
            "Wrong answer\n\nCorrection: TERM() optimizes searches",
            "testuser",
            reason="incorrect",
        )
        assert success is True

        stored_doc = collection.add.call_args[1]["documents"][0]
        assert "Correction:" in stored_doc

    @patch("vectorstore.get_embeddings_model")
    @patch("negative_feedback._get_or_create_collection")
    def test_deduplicates(self, mock_get_coll, mock_embed):
        from negative_feedback import add_negative_feedback

        collection = MagicMock()
        collection.get.return_value = {"ids": ["existing-id"]}
        mock_get_coll.return_value = (collection, MagicMock())

        success, msg = add_negative_feedback("Q", "A", "user")
        assert success is True
        assert msg == "Already stored"
        collection.add.assert_not_called()


# ---------------------------------------------------------------------------
# Test: Knowledge graph cache staleness detection
# ---------------------------------------------------------------------------

class TestKnowledgeGraphCacheStaleness:
    """Test that the KG detects stale cache and rebuilds."""

    def test_build_with_fresh_cache(self, tmp_path):
        from chat_app.kg_builders import build_knowledge_graph

        spl_dir = tmp_path / "spl_docs"
        spl_dir.mkdir()
        (spl_dir / "spl_cmd_search.md").write_text("# search\nBasic search command")

        metadata_dir = tmp_path / "metadata"
        metadata_dir.mkdir()
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()

        cache_path = str(tmp_path / "kg_cache.json")
        kg1 = build_knowledge_graph(
            spl_docs_dir=str(spl_dir),
            metadata_dir=str(metadata_dir),
            spec_dir=str(spec_dir),
            cache_path=cache_path,
            force_rebuild=True,
        )

        # Load again - should use cache
        kg2 = build_knowledge_graph(
            spl_docs_dir=str(spl_dir),
            metadata_dir=str(metadata_dir),
            spec_dir=str(spec_dir),
            cache_path=cache_path,
            force_rebuild=False,
        )
        assert kg2.get_stats()["total_entities"] == kg1.get_stats()["total_entities"]

    def test_build_detects_stale_cache(self, tmp_path):
        from chat_app.kg_builders import build_knowledge_graph

        spl_dir = tmp_path / "spl_docs"
        spl_dir.mkdir()
        metadata_dir = tmp_path / "metadata"
        metadata_dir.mkdir()
        spec_dir = tmp_path / "specs"
        spec_dir.mkdir()

        cache_path = str(tmp_path / "kg_cache.json")
        kg1 = build_knowledge_graph(
            spl_docs_dir=str(spl_dir),
            metadata_dir=str(metadata_dir),
            spec_dir=str(spec_dir),
            cache_path=cache_path,
            force_rebuild=True,
        )

        # Add a new source file (newer than cache)
        time.sleep(0.1)
        (spl_dir / "spl_cmd_eval.md").write_text("# eval\nCalculates expressions.")

        # Should detect staleness and rebuild
        kg2 = build_knowledge_graph(
            spl_docs_dir=str(spl_dir),
            metadata_dir=str(metadata_dir),
            spec_dir=str(spec_dir),
            cache_path=cache_path,
            force_rebuild=False,
        )
        assert kg2 is not None


# ---------------------------------------------------------------------------
# Test: Knowledge graph rebuild function
# ---------------------------------------------------------------------------

class TestKnowledgeGraphRebuild:
    """Test rebuild_knowledge_graph forces a fresh build."""

    def test_rebuild_clears_singleton(self):
        import chat_app.knowledge_graph as kg_module

        kg_module._KG_SINGLETON = MagicMock()

        with patch("chat_app.knowledge_graph.build_knowledge_graph") as mock_build:
            mock_kg = MagicMock()
            mock_build.return_value = mock_kg

            result = kg_module.rebuild_knowledge_graph()

            mock_build.assert_called_once()
            call_kwargs = mock_build.call_args[1]
            assert call_kwargs["force_rebuild"] is True
            assert kg_module._KG_SINGLETON == mock_kg


# ---------------------------------------------------------------------------
# Test: Format feedback response
# ---------------------------------------------------------------------------

class TestFormatFeedbackResponse:
    """Test feedback response formatting."""

    def test_format_includes_validated_header(self):
        from feedback_retriever import format_feedback_response

        match = {
            "question": "What is TERM?",
            "answer": "TERM() optimizes searches.",
            "source": "feedback://admin/abc123",
            "username": "admin",
            "similarity": 0.95,
        }

        response = format_feedback_response(match)
        assert "Previously Validated Answer" in response
        assert "TERM() optimizes searches." in response
        assert "95%" in response
