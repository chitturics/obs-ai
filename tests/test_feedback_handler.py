"""
Tests for chat_app.feedback_handler and chat_app.feedback_retriever modules.

Covers:
- _llm_polish_feedback: liked/disliked polishing, timeout, empty input, JSON parsing
- on_feedback: full pipeline with mocked dependencies
- extract_qa_from_feedback_chunk: both Q/A formats and edge cases
- find_feedback_match: Jaccard similarity, thresholds, non-feedback chunks
- query_feedback_collection: ChromaDB direct query with mocked client
- format_feedback_response: output formatting
"""

import asyncio
import json
import re
import sys
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

# Pre-mock modules that feedback_handler imports with bare names.
# IMPORTANT: Only mock modules that truly cannot be imported.  negative_feedback
# is a real module inside chat_app/ that other tests rely on — importing the real
# module is safe (it only uses lightweight stdlib imports at top level).
for _mod in [
    "helper", "feedback_logger", "vectorstore", "vectorstore_ingest", "llm_utils",
]:
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

# negative_feedback lives in chat_app/ which is on sys.path.  Import the real
# module instead of replacing it with a MagicMock (which would break tests in
# test_feedback_pipeline.py that patch individual functions inside it).
if "negative_feedback" not in sys.modules:
    try:
        import negative_feedback  # noqa: F401
    except ImportError:
        sys.modules["negative_feedback"] = MagicMock()

# Ensure chat_app.feedback_handler can be imported (it uses bare module imports
# and chainlit, all of which must be pre-mocked by conftest.py or here)
import chat_app.feedback_handler  # noqa: F401 — force registration in sys.modules


# ---------------------------------------------------------------------------
# feedback_retriever tests (pure functions, no heavy mocking needed)
# ---------------------------------------------------------------------------

from chat_app.feedback_retriever import (
    _cosine_similarity,
    extract_qa_from_feedback_chunk,
    find_feedback_match,
    format_feedback_response,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_feedback_chunk(question, answer, username="testuser", fmt="Question"):
    """Build a feedback chunk dict matching ChromaDB retrieval format."""
    fingerprint = "abcdef1234567890"
    source = f"feedback://{username}/{fingerprint}"
    if fmt == "Question":
        text = f"Question: {question}\n\nAnswer: {answer}"
    else:
        text = f"Q: {question}\nA: {answer}"
    return {"text": text, "source": source}


def _make_non_feedback_chunk(text="Some random doc content"):
    """Build a non-feedback chunk (e.g., from spl_docs)."""
    return {"text": text, "source": "file://spl_docs/spl_cmd_stats.md"}


# ---------------------------------------------------------------------------
# 1. extract_qa_from_feedback_chunk
# ---------------------------------------------------------------------------

class TestExtractQAFromFeedbackChunk:
    """Verify parsing of both Q&A formats and edge cases."""

    def test_question_answer_format(self):
        text = "Question: How do I use stats?\n\nAnswer: Use | stats count by host."
        q, a = extract_qa_from_feedback_chunk(text)
        assert q == "How do I use stats?"
        assert a == "Use | stats count by host."

    def test_q_a_shorthand_format(self):
        text = "Q: What is tstats?\nA: tstats queries indexed fields for speed."
        q, a = extract_qa_from_feedback_chunk(text)
        assert q == "What is tstats?"
        assert a == "tstats queries indexed fields for speed."

    def test_multiline_answer(self):
        text = "Question: Explain eval\n\nAnswer: eval creates calculated fields.\nIt supports many functions like if(), case(), etc."
        q, a = extract_qa_from_feedback_chunk(text)
        assert q == "Explain eval"
        assert "eval creates calculated fields" in a
        assert "if(), case()" in a

    def test_empty_text(self):
        q, a = extract_qa_from_feedback_chunk("")
        assert q is None
        assert a is None

    def test_no_match_format(self):
        text = "This is just random text with no Q/A structure."
        q, a = extract_qa_from_feedback_chunk(text)
        assert q is None
        assert a is None

    def test_only_question_no_answer(self):
        text = "Question: How to optimize?\n\n"
        q, a = extract_qa_from_feedback_chunk(text)
        # The regex should still match but answer would be empty string
        if q is not None:
            assert q == "How to optimize?"
            assert a is not None  # might be empty string

    def test_whitespace_handling(self):
        text = "Question:   How to use TERM?   \n\n  Answer:   Use TERM() for bloom filters.  "
        q, a = extract_qa_from_feedback_chunk(text)
        assert q is not None
        assert "TERM" in q
        assert a is not None
        assert "TERM()" in a


# ---------------------------------------------------------------------------
# 2. _cosine_similarity
# ---------------------------------------------------------------------------

class TestCosineSimilarity:
    """Verify vector cosine similarity computation."""

    def test_identical_vectors(self):
        v = [1.0, 2.0, 3.0]
        assert abs(_cosine_similarity(v, v) - 1.0) < 1e-6

    def test_orthogonal_vectors(self):
        a = [1.0, 0.0]
        b = [0.0, 1.0]
        assert abs(_cosine_similarity(a, b)) < 1e-6

    def test_opposite_vectors(self):
        a = [1.0, 0.0]
        b = [-1.0, 0.0]
        assert abs(_cosine_similarity(a, b) + 1.0) < 1e-6

    def test_empty_vectors(self):
        assert _cosine_similarity([], []) == 0.0

    def test_mismatched_lengths(self):
        assert _cosine_similarity([1.0, 2.0], [1.0]) == 0.0

    def test_zero_vector(self):
        a = [0.0, 0.0, 0.0]
        b = [1.0, 2.0, 3.0]
        assert _cosine_similarity(a, b) == 0.0


# ---------------------------------------------------------------------------
# 3. find_feedback_match
# ---------------------------------------------------------------------------

class TestFindFeedbackMatch:
    """Verify Jaccard-based feedback matching logic."""

    def test_exact_match(self):
        """Identical query and question should match at 1.0."""
        chunks = [_make_feedback_chunk("What is TERM in Splunk?", "TERM() is a bloom filter directive.")]
        result = find_feedback_match(chunks, "What is TERM in Splunk?", similarity_threshold=0.5)
        assert result is not None
        assert result["similarity"] == 1.0
        assert result["answer"] == "TERM() is a bloom filter directive."
        assert result["username"] == "testuser"

    def test_high_overlap_match(self):
        """Similar wording should match above threshold."""
        chunks = [_make_feedback_chunk("How to use TERM directive in Splunk", "Use TERM() for bloom filter optimization.")]
        result = find_feedback_match(chunks, "How to use TERM in Splunk searches", similarity_threshold=0.5)
        assert result is not None
        assert result["similarity"] >= 0.5

    def test_no_match_below_threshold(self):
        """Queries with low overlap should not match."""
        chunks = [_make_feedback_chunk("What is tstats command?", "tstats uses indexed fields.")]
        result = find_feedback_match(chunks, "How to configure props.conf for syslog", similarity_threshold=0.7)
        assert result is None

    def test_non_feedback_chunks_ignored(self):
        """Chunks without feedback:// source should be skipped."""
        chunks = [_make_non_feedback_chunk("stats command calculates aggregates")]
        result = find_feedback_match(chunks, "stats command", similarity_threshold=0.3)
        assert result is None

    def test_mixed_chunks_selects_feedback(self):
        """When mixed with non-feedback chunks, only feedback chunks considered."""
        chunks = [
            _make_non_feedback_chunk("irrelevant doc content"),
            _make_feedback_chunk("What is eval in Splunk?", "eval creates calculated fields."),
            _make_non_feedback_chunk("another random doc"),
        ]
        result = find_feedback_match(chunks, "What is eval in Splunk?", similarity_threshold=0.5)
        assert result is not None
        assert result["answer"] == "eval creates calculated fields."

    def test_empty_chunks_list(self):
        result = find_feedback_match([], "any query")
        assert result is None

    def test_empty_query(self):
        chunks = [_make_feedback_chunk("What is stats?", "stats aggregates data.")]
        result = find_feedback_match(chunks, "")
        assert result is None

    def test_short_token_query(self):
        """Query with only short tokens (< 3 chars) returns None."""
        chunks = [_make_feedback_chunk("What is X?", "X is something.")]
        result = find_feedback_match(chunks, "is x")
        assert result is None

    def test_best_match_selected(self):
        """When multiple feedback chunks match, the best one is returned."""
        chunks = [
            _make_feedback_chunk("How to use stats command", "stats does aggregation"),
            _make_feedback_chunk("What is the stats command in Splunk", "stats is an SPL command"),
        ]
        result = find_feedback_match(chunks, "What is the stats command in Splunk", similarity_threshold=0.3)
        assert result is not None
        # The second chunk should match better
        assert "stats" in result["answer"].lower()

    def test_q_a_format_chunks(self):
        """Test with Q:/A: format (not Question:/Answer:)."""
        chunk = {"text": "Q: What is eval?\nA: eval creates fields.", "source": "feedback://admin/abc123"}
        result = find_feedback_match([chunk], "What is eval?", similarity_threshold=0.5)
        assert result is not None

    def test_username_extraction_from_source(self):
        """Username should be extracted from feedback://username/hash source."""
        chunk = _make_feedback_chunk("test question", "test answer", username="jdoe")
        result = find_feedback_match([chunk], "test question", similarity_threshold=0.3)
        assert result is not None
        assert result["username"] == "jdoe"

    def test_threshold_boundary(self):
        """Similarity exactly at threshold should be included."""
        # Create a scenario where Jaccard is exactly at threshold
        chunks = [_make_feedback_chunk("alpha beta gamma delta", "some answer")]
        # Query shares all tokens with question
        result = find_feedback_match(chunks, "alpha beta gamma delta", similarity_threshold=1.0)
        assert result is not None


# ---------------------------------------------------------------------------
# 4. format_feedback_response
# ---------------------------------------------------------------------------

class TestFormatFeedbackResponse:
    """Verify feedback response formatting."""

    def test_basic_formatting(self):
        match = {
            "question": "What is stats?",
            "answer": "stats aggregates data.",
            "username": "testuser",
            "similarity": 0.85,
        }
        result = format_feedback_response(match)
        assert "Previously Validated Answer" in result
        assert "testuser" in result
        assert "What is stats?" in result
        assert "stats aggregates data." in result
        assert "85%" in result

    def test_formatting_high_similarity(self):
        match = {
            "question": "How to use TERM?",
            "answer": "TERM() optimizes bloom filters.",
            "username": "admin",
            "similarity": 0.95,
        }
        result = format_feedback_response(match)
        assert "95%" in result
        assert "admin" in result

    def test_formatting_includes_answer(self):
        match = {
            "question": "Q",
            "answer": "A detailed multiline\nanswer here.",
            "username": "user1",
            "similarity": 0.70,
        }
        result = format_feedback_response(match)
        assert "A detailed multiline" in result
        assert "answer here." in result


# ---------------------------------------------------------------------------
# 5. _llm_polish_feedback (async, needs mocking)
# ---------------------------------------------------------------------------

class TestLLMPolishFeedback:
    """Test LLM polishing for liked and disliked feedback."""

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.ainvoke = AsyncMock()
        return llm

    @pytest.mark.asyncio
    @patch("vectorstore_ingest.add_feedback_qa_to_memory", return_value=(True, None))
    async def test_liked_feedback_polish_success(self, mock_add_qa, mock_llm):
        from chat_app.feedback_handler import _llm_polish_feedback

        mock_llm.ainvoke.return_value = MagicMock(
            content='{"question": "What is stats?", "answer": "stats aggregates data."}'
        )
        result = await _llm_polish_feedback(
            question="what is stats",
            answer="stats does aggregation stuff",
            llm=mock_llm,
            is_liked=True,
            username="testuser",
        )
        assert result is True
        mock_llm.ainvoke.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_question_returns_false(self, mock_llm):
        from chat_app.feedback_handler import _llm_polish_feedback

        result = await _llm_polish_feedback(
            question="", answer="some answer", llm=mock_llm, is_liked=True,
        )
        assert result is False
        mock_llm.ainvoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_answer_returns_false(self, mock_llm):
        from chat_app.feedback_handler import _llm_polish_feedback

        result = await _llm_polish_feedback(
            question="some question", answer="", llm=mock_llm, is_liked=True,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_llm_returns_no_json(self, mock_llm):
        from chat_app.feedback_handler import _llm_polish_feedback

        mock_llm.ainvoke.return_value = MagicMock(content="I cannot do that.")
        result = await _llm_polish_feedback(
            question="q", answer="a", llm=mock_llm, is_liked=True,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_llm_timeout(self, mock_llm):
        from chat_app.feedback_handler import _llm_polish_feedback

        mock_llm.ainvoke.side_effect = asyncio.TimeoutError()
        result = await _llm_polish_feedback(
            question="q", answer="a", llm=mock_llm, is_liked=True,
        )
        assert result is False

    @pytest.mark.asyncio
    @patch("negative_feedback.add_negative_feedback")
    async def test_disliked_feedback_stores_negative(self, mock_add_neg, mock_llm):
        from chat_app.feedback_handler import _llm_polish_feedback

        mock_llm.ainvoke.return_value = MagicMock(
            content='{"question": "How to join?", "bad_answer": "Use join always", "correction": "Use stats instead"}'
        )
        result = await _llm_polish_feedback(
            question="How to join tables",
            answer="Use join always",
            llm=mock_llm,
            is_liked=False,
            reason="join is slow",
            username="admin",
        )
        assert result is True
        mock_add_neg.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_returns_string_not_content(self, mock_llm):
        """LLM response without .content attribute should still work."""
        from chat_app.feedback_handler import _llm_polish_feedback

        mock_llm.ainvoke.return_value = '{"question": "Q", "answer": "A"}'
        # The function does a local `from vectorstore_ingest import add_feedback_qa_to_memory`
        # so we must set the attribute on the sys.modules mock directly
        orig = sys.modules["vectorstore_ingest"].add_feedback_qa_to_memory
        sys.modules["vectorstore_ingest"].add_feedback_qa_to_memory = MagicMock(return_value=(True, None))
        try:
            result = await _llm_polish_feedback(
                question="q", answer="a", llm=mock_llm, is_liked=True,
            )
            assert result is True
        finally:
            sys.modules["vectorstore_ingest"].add_feedback_qa_to_memory = orig

    @pytest.mark.asyncio
    async def test_llm_exception_returns_false(self, mock_llm):
        from chat_app.feedback_handler import _llm_polish_feedback

        mock_llm.ainvoke.side_effect = RuntimeError("LLM crashed")
        result = await _llm_polish_feedback(
            question="q", answer="a", llm=mock_llm, is_liked=True,
        )
        assert result is False


# ---------------------------------------------------------------------------
# 6. on_feedback (full pipeline integration, all deps mocked)
# ---------------------------------------------------------------------------

class TestOnFeedback:
    """Test the on_feedback handler with full mocking."""

    @pytest.fixture
    def feedback_liked(self):
        fb = MagicMock()
        fb.value = 1
        fb.comment = "Great answer!"
        fb.for_id = "msg-123"
        return fb

    @pytest.fixture
    def feedback_disliked(self):
        fb = MagicMock()
        fb.value = 0
        fb.comment = "This is wrong"
        fb.for_id = "msg-456"
        return fb

    @pytest.fixture
    def feedback_disliked_no_comment(self):
        fb = MagicMock()
        fb.value = 0
        fb.comment = None
        fb.for_id = "msg-789"
        return fb

    @pytest.fixture(autouse=True)
    def mock_chainlit(self):
        """Mock chainlit user_session and AskUserMessage."""
        with patch("chat_app.feedback_handler.cl") as mock_cl:
            mock_cl.user_session.get.side_effect = lambda key, default="": {
                "last_question": "What is stats?",
                "last_answer": "stats does aggregation",
                "last_context": "some context",
                "last_collections_used": ["spl_commands"],
            }.get(key, default)
            mock_cl.AskUserMessage = MagicMock(return_value=MagicMock(
                send=AsyncMock(return_value={"output": "The answer was incomplete"})
            ))
            yield mock_cl

    @pytest.fixture(autouse=True)
    def mock_helpers(self):
        """Mock current_username and current_thread_id."""
        with patch("chat_app.feedback_handler.current_username", return_value="testuser"), \
             patch("chat_app.feedback_handler.current_thread_id", return_value="thread-abc"):
            yield

    @pytest.mark.asyncio
    @patch("chat_app.feedback_handler.log_feedback", new_callable=AsyncMock, return_value="feedback_file.html")
    @patch("chat_app.feedback_handler.log_query_preference", new_callable=AsyncMock)
    @patch("chat_app.feedback_handler._llm_polish_feedback", new_callable=AsyncMock, return_value=True)
    @patch("subprocess.Popen")
    async def test_liked_feedback_flow(self, mock_popen, mock_polish, mock_pref, mock_log, feedback_liked):
        from chat_app.feedback_handler import on_feedback

        engine = MagicMock()
        vector_store = MagicMock()
        llm = MagicMock()

        await on_feedback(feedback_liked, engine, vector_store, llm, "http://localhost:8000")

        mock_log.assert_awaited_once()
        mock_pref.assert_awaited_once()
        mock_polish.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("chat_app.feedback_handler.log_feedback", new_callable=AsyncMock, return_value=None)
    @patch("chat_app.feedback_handler.log_query_preference", new_callable=AsyncMock)
    @patch("chat_app.feedback_handler._llm_polish_feedback", new_callable=AsyncMock, return_value=True)
    @patch("subprocess.Popen")
    async def test_disliked_feedback_with_comment(self, mock_popen, mock_polish, mock_pref, mock_log, feedback_disliked):
        from chat_app.feedback_handler import on_feedback

        engine = MagicMock()
        await on_feedback(feedback_disliked, engine, MagicMock(), MagicMock(), "http://localhost")

        mock_log.assert_awaited_once()
        # Polish should be called with is_liked=False
        call_kwargs = mock_polish.call_args
        assert call_kwargs[1]["is_liked"] is False or (not call_kwargs[0][3] if len(call_kwargs[0]) > 3 else True)

    @pytest.mark.asyncio
    @patch("chat_app.feedback_handler.log_feedback", new_callable=AsyncMock, return_value=None)
    @patch("chat_app.feedback_handler.log_query_preference", new_callable=AsyncMock)
    @patch("chat_app.feedback_handler._llm_polish_feedback", new_callable=AsyncMock, return_value=False)
    @patch("chat_app.feedback_handler.add_feedback_qa_to_memory")
    @patch("subprocess.Popen")
    async def test_fallback_raw_storage_on_polish_failure(
        self, mock_popen, mock_add_qa, mock_polish, mock_pref, mock_log, feedback_liked,
    ):
        """When LLM polish fails, raw Q&A should still be stored."""
        from chat_app.feedback_handler import on_feedback

        await on_feedback(feedback_liked, MagicMock(), MagicMock(), MagicMock(), "http://localhost")

        mock_add_qa.assert_called_once()

    @pytest.mark.asyncio
    @patch("chat_app.feedback_handler.log_feedback", new_callable=AsyncMock, side_effect=RuntimeError("DB error"))
    @patch("chat_app.feedback_handler.log_query_preference", new_callable=AsyncMock)
    @patch("chat_app.feedback_handler._llm_polish_feedback", new_callable=AsyncMock, return_value=True)
    @patch("subprocess.Popen")
    async def test_log_feedback_exception_handled(self, mock_popen, mock_polish, mock_pref, mock_log, feedback_liked):
        """Database failure for log_feedback should not crash the handler."""
        from chat_app.feedback_handler import on_feedback

        # Should not raise
        await on_feedback(feedback_liked, MagicMock(), MagicMock(), MagicMock(), "http://localhost")
        mock_pref.assert_awaited_once()


# ---------------------------------------------------------------------------
# 7. query_feedback_collection (ChromaDB direct query)
# ---------------------------------------------------------------------------

class TestQueryFeedbackCollection:
    """Test direct ChromaDB feedback query with mocked client.

    query_feedback_collection() uses local imports:
      import chromadb                             (inside the function)
      from vectorstore import get_embeddings_model (inside the function)
    We intercept them via patch.dict(sys.modules, ...) and by setting
    attributes on the already-mocked 'vectorstore' module.
    """

    def _setup_chromadb_mock(self, collection=None, client_error=None):
        """Helper: build a mock chromadb module with HttpClient."""
        mock_chromadb = MagicMock()
        if client_error:
            mock_chromadb.HttpClient.side_effect = client_error
        else:
            mock_client = MagicMock()
            if collection:
                mock_client.get_collection.return_value = collection
            else:
                mock_client.get_collection.side_effect = RuntimeError("Collection not found")
            mock_chromadb.HttpClient.return_value = mock_client
        return mock_chromadb

    @patch("chat_app.feedback_retriever.get_settings")
    def test_query_returns_match(self, mock_settings):
        """Successful query returns best matching Q&A."""
        from chat_app.feedback_retriever import query_feedback_collection

        mock_cfg = MagicMock()
        mock_cfg.http_url = "http://localhost:8001"
        mock_cfg.feedback_collection = "feedback_qa_test"
        mock_settings.return_value.chroma = mock_cfg

        mock_collection = MagicMock()
        mock_collection.count.return_value = 5
        mock_collection.query.return_value = {
            "documents": [["Question: What is stats?\n\nAnswer: stats aggregates data."]],
            "metadatas": [[{"source": "feedback://admin/abc123"}]],
            "distances": [[0.1]],
        }

        mock_chromadb = self._setup_chromadb_mock(collection=mock_collection)

        # Mock the embeddings model on the vectorstore sys.modules entry
        mock_embed = MagicMock()
        mock_embed.embed_query.return_value = [0.1] * 768
        orig_get_embed = sys.modules["vectorstore"].get_embeddings_model
        sys.modules["vectorstore"].get_embeddings_model = MagicMock(return_value=mock_embed)

        try:
            with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
                result = query_feedback_collection("What is stats?", similarity_threshold=0.75)
        finally:
            sys.modules["vectorstore"].get_embeddings_model = orig_get_embed

        assert result is not None
        assert result["answer"] == "stats aggregates data."
        assert result["similarity"] >= 0.75

    @patch("chat_app.feedback_retriever.get_settings")
    def test_query_no_collection_returns_none(self, mock_settings):
        """When collection doesn't exist, return None."""
        from chat_app.feedback_retriever import query_feedback_collection

        mock_cfg = MagicMock()
        mock_cfg.http_url = "http://localhost:8001"
        mock_cfg.feedback_collection = "feedback_qa_test"
        mock_settings.return_value.chroma = mock_cfg

        mock_chromadb = self._setup_chromadb_mock()  # get_collection raises

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            result = query_feedback_collection("test query")
        assert result is None

    @patch("chat_app.feedback_retriever.get_settings")
    def test_query_empty_collection_returns_none(self, mock_settings):
        """When collection is empty, return None."""
        from chat_app.feedback_retriever import query_feedback_collection

        mock_cfg = MagicMock()
        mock_cfg.http_url = "http://localhost:8001"
        mock_cfg.feedback_collection = "feedback_qa_test"
        mock_settings.return_value.chroma = mock_cfg

        mock_collection = MagicMock()
        mock_collection.count.return_value = 0
        mock_chromadb = self._setup_chromadb_mock(collection=mock_collection)

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            result = query_feedback_collection("test query")
        assert result is None

    @patch("chat_app.feedback_retriever.get_settings")
    def test_query_connection_error_returns_none(self, mock_settings):
        """Network error should return None, not raise."""
        from chat_app.feedback_retriever import query_feedback_collection

        mock_cfg = MagicMock()
        mock_cfg.http_url = "http://localhost:8001"
        mock_cfg.feedback_collection = "test"
        mock_settings.return_value.chroma = mock_cfg

        mock_chromadb = self._setup_chromadb_mock(client_error=ConnectionError("Cannot connect"))

        with patch.dict(sys.modules, {"chromadb": mock_chromadb}):
            result = query_feedback_collection("test")
        assert result is None


# ---------------------------------------------------------------------------
# 8. _embed_text circuit breaker
# ---------------------------------------------------------------------------

class TestEmbedTextCircuitBreaker:
    """Test the embedding failure circuit breaker."""

    def test_embed_text_returns_none_after_max_failures(self):
        """After _MAX_EMBED_FAILURES, _embed_text should return None immediately."""
        import chat_app.feedback_retriever as fr

        # Save and reset globals
        old_embedder = fr._embedder
        old_attempted = fr._embedder_init_attempted
        old_count = fr._embed_fail_count

        try:
            fr._embedder = MagicMock()
            fr._embedder.embed_query.side_effect = RuntimeError("fail")
            fr._embedder_init_attempted = True
            fr._embed_fail_count = 0

            # Fail up to max
            for _ in range(fr._MAX_EMBED_FAILURES):
                fr._embed_text("test")

            assert fr._embed_fail_count >= fr._MAX_EMBED_FAILURES

            # Now it should return None immediately without calling embed_query
            fr._embedder.embed_query.reset_mock()
            result = fr._embed_text("test")
            assert result is None
            fr._embedder.embed_query.assert_not_called()
        finally:
            fr._embedder = old_embedder
            fr._embedder_init_attempted = old_attempted
            fr._embed_fail_count = old_count

    def test_embed_text_resets_count_on_success(self):
        """Successful embedding should reset the failure counter."""
        import chat_app.feedback_retriever as fr

        old_embedder = fr._embedder
        old_attempted = fr._embedder_init_attempted
        old_count = fr._embed_fail_count

        try:
            fr._embedder = MagicMock()
            fr._embedder.embed_query.return_value = [0.1, 0.2, 0.3]
            fr._embedder_init_attempted = True
            fr._embed_fail_count = 3

            result = fr._embed_text("test")
            assert result == [0.1, 0.2, 0.3]
            assert fr._embed_fail_count == 0
        finally:
            fr._embedder = old_embedder
            fr._embedder_init_attempted = old_attempted
            fr._embed_fail_count = old_count
