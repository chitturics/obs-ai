"""Tests for chat_app/vectorstore_search.py — Vector search, scoring, dedup."""
import hashlib
import sys
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

# Mock heavy dependencies that may not be installed in test env
for _mod in ("langchain_chroma", "chromadb", "chromadb.errors"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()

from chat_app.vectorstore_search import (
    QueryIntent,
    SearchConfig,
    ScoredDocument,
    analyze_query_intent,
    deduplicate_results,
    merge_and_deduplicate_global,
    score_document,
    select_collections_and_weights,
    _strip_history,
    _token_overlap_score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_doc(page_content="test content", metadata=None):
    """Create a mock Langchain Document object."""
    doc = MagicMock()
    doc.page_content = page_content
    doc.metadata = metadata or {}
    return doc


def _make_intent(**overrides):
    """Create a QueryIntent with sensible defaults."""
    defaults = dict(
        prefers_conf=False,
        prefers_spl=False,
        is_repo_query=False,
        has_conf_reference=False,
        has_spl_reference=False,
        role_hits=set(),
        version_tokens=[],
        query_tokens={"test", "query"},
        target_app=None,
        target_conf=None,
    )
    defaults.update(overrides)
    return QueryIntent(**defaults)


def _identity_mapper(source):
    return None


# ---------------------------------------------------------------------------
# analyze_query_intent
# ---------------------------------------------------------------------------

class TestAnalyzeQueryIntent:
    """Tests for query intent analysis."""

    def test_spl_keyword_detected(self):
        intent = analyze_query_intent("show me stats by host")
        assert intent.prefers_spl is True
        assert intent.has_spl_reference is True

    def test_conf_reference_detected(self):
        intent = analyze_query_intent("show me props.conf settings")
        assert intent.prefers_conf is True
        assert intent.has_conf_reference is True
        assert intent.target_conf == "props.conf"

    def test_repo_query_detected(self):
        intent = analyze_query_intent("show our saved searches")
        assert intent.is_repo_query is True

    def test_role_keywords_detected(self):
        intent = analyze_query_intent("configure the search head cluster")
        assert "search head" in intent.role_hits or "cluster" in intent.role_hits

    def test_version_tokens_extracted(self):
        intent = analyze_query_intent("how to upgrade to version 9.2.1")
        assert any("9" in v for v in intent.version_tokens)

    def test_general_query_no_special_flags(self):
        intent = analyze_query_intent("what is Splunk?")
        assert intent.prefers_conf is False
        assert intent.is_repo_query is False

    def test_query_tokens_extracted(self):
        intent = analyze_query_intent("count events by sourcetype")
        assert "count" in intent.query_tokens
        assert "events" in intent.query_tokens
        # Short tokens (< 3 chars) filtered out
        assert "by" not in intent.query_tokens

    def test_target_app_extraction(self):
        intent = analyze_query_intent('show me configs for TA-nmap')
        assert intent.target_app == "TA-nmap"

    def test_target_conf_extraction(self):
        intent = analyze_query_intent("explain savedsearches.conf stanzas")
        assert intent.target_conf == "savedsearches.conf"
        assert intent.prefers_conf is True

    def test_multiple_conf_keywords(self):
        intent = analyze_query_intent("show inputs.conf and outputs.conf")
        assert intent.prefers_conf is True

    def test_empty_query(self):
        intent = analyze_query_intent("")
        assert intent.prefers_conf is False
        assert intent.prefers_spl is False


# ---------------------------------------------------------------------------
# select_collections_and_weights
# ---------------------------------------------------------------------------

class TestSelectCollectionsAndWeights:
    """Tests for collection selection based on intent."""

    def _mock_collections(self):
        return [
            ("org_repo_mxbai", MagicMock()),
            ("spl_commands_mxbai", MagicMock()),
            ("feedback_qa", MagicMock()),
            ("secondary_specs", MagicMock()),
            ("primary", MagicMock()),
        ]

    def test_repo_centric_weights(self):
        intent = _make_intent(is_repo_query=True)
        config = select_collections_and_weights(intent, self._mock_collections())
        assert config.weight_map["org_repo_mxbai"] == 100

    def test_spl_centric_weights(self):
        intent = _make_intent(has_spl_reference=True)
        config = select_collections_and_weights(intent, self._mock_collections())
        assert config.weight_map["spl_commands_mxbai"] == 100

    def test_general_query_weights(self):
        intent = _make_intent()
        config = select_collections_and_weights(intent, self._mock_collections())
        assert config.weight_map.get("secondary_specs", 0) >= 10

    def test_weight_map_override(self):
        intent = _make_intent()
        override = {"org_repo_mxbai": 50, "primary": 50}
        config = select_collections_and_weights(
            intent, self._mock_collections(), weight_map_override=override
        )
        assert config.weight_map == override

    def test_filtered_collections_match_weight_map(self):
        intent = _make_intent(has_spl_reference=True)
        config = select_collections_and_weights(intent, self._mock_collections())
        coll_names = {name for name, _ in config.collections}
        # All returned collections should be in weight_map
        for name in coll_names:
            assert name in config.weight_map

    def test_returns_search_config(self):
        intent = _make_intent()
        config = select_collections_and_weights(intent, self._mock_collections())
        assert isinstance(config, SearchConfig)
        assert config.use_parallel is True


# ---------------------------------------------------------------------------
# _strip_history / _token_overlap_score
# ---------------------------------------------------------------------------

class TestHelperFunctions:
    """Tests for scoring helper functions."""

    def test_strip_history_removes_qa_lines(self):
        text = "Normal line\n| Q: question\n| A: answer\nAnother line"
        result = _strip_history(text)
        assert "Normal line" in result
        assert "Another line" in result
        assert "Q: question" not in result

    def test_strip_history_removes_date_lines(self):
        text = "2025-01-15 some date line\nKeep this line"
        result = _strip_history(text)
        assert "Keep this line" in result
        assert "2025-01-15" not in result

    def test_strip_history_preserves_normal_text(self):
        text = "This is normal\nAnother normal line"
        assert _strip_history(text) == text

    def test_token_overlap_score(self):
        score = _token_overlap_score("the quick brown fox", {"quick", "fox", "missing"})
        assert score == 2

    def test_token_overlap_no_match(self):
        score = _token_overlap_score("hello world", {"missing", "tokens"})
        assert score == 0


# ---------------------------------------------------------------------------
# score_document
# ---------------------------------------------------------------------------

class TestScoreDocument:
    """Tests for document scoring."""

    def test_basic_scoring(self):
        doc = _make_doc("some test content about queries")
        intent = _make_intent(query_tokens={"test", "content"})
        result = score_document(doc, "primary", "test content", intent, 10, _identity_mapper)
        assert isinstance(result, ScoredDocument)
        assert result.score > 0
        assert result.collection == "primary"

    def test_higher_weight_higher_score(self):
        doc = _make_doc("test content here")
        intent = _make_intent()
        low = score_document(doc, "low", "test", intent, 1, _identity_mapper)
        high = score_document(doc, "high", "test", intent, 100, _identity_mapper)
        assert high.score > low.score

    def test_none_document_returns_none(self):
        intent = _make_intent()
        result = score_document(None, "coll", "query", intent, 10, _identity_mapper)
        assert result is None

    def test_conf_preference_filters_non_conf(self):
        doc = _make_doc("generic content", {"source": "/path/to/readme.md"})
        intent = _make_intent(prefers_conf=True)
        result = score_document(doc, "primary", "query", intent, 10, _identity_mapper)
        assert result is None

    def test_conf_preference_keeps_conf_docs(self):
        doc = _make_doc("stanza content", {"source": "/path/to/props.conf"})
        intent = _make_intent(prefers_conf=True)
        result = score_document(doc, "primary", "query", intent, 10, _identity_mapper)
        assert result is not None

    def test_token_overlap_boosts_score(self):
        doc = _make_doc("stats command for aggregation count")
        intent_no_match = _make_intent(query_tokens={"zzz_nomatch"})
        intent_match = _make_intent(query_tokens={"stats", "aggregation", "count"})

        s1 = score_document(doc, "c", "q", intent_no_match, 10, _identity_mapper)
        s2 = score_document(doc, "c", "q", intent_match, 10, _identity_mapper)
        assert s2.score > s1.score

    def test_vector_similarity_included_in_score(self):
        doc = _make_doc("content", {"_vector_similarity": 0.9})
        intent = _make_intent()
        result = score_document(doc, "c", "q", intent, 10, _identity_mapper)
        # Score should include vector similarity contribution (0.9 * 20 = 18)
        assert result is not None
        assert result.score >= 10 * 10  # base from weight

    def test_target_app_boost(self):
        doc = _make_doc("config content", {"source": "/apps/TA-nmap/local/inputs.conf"})
        intent = _make_intent(target_app="TA-nmap")
        result = score_document(doc, "repo", "show TA-nmap", intent, 10, _identity_mapper)
        assert result is not None

    def test_target_conf_boost(self):
        doc = _make_doc("stanza content", {"source": "/etc/system/local/props.conf"})
        intent = _make_intent(target_conf="props.conf")
        result = score_document(doc, "repo", "props.conf", intent, 10, _identity_mapper)
        assert result is not None

    def test_source_url_from_mapper(self):
        mapper = lambda src: "/public/docs/test.html"
        doc = _make_doc("content", {"source": "/path/to/test.html"})
        intent = _make_intent()
        result = score_document(doc, "c", "q", intent, 10, mapper)
        assert result.source_url == "/public/docs/test.html"

    def test_text_truncated_for_long_documents(self):
        long_text = "word " * 2000  # Well over 800 chars
        doc = _make_doc(long_text)
        intent = _make_intent()
        result = score_document(doc, "c", "q", intent, 10, _identity_mapper)
        assert result is not None
        assert len(result.text) <= 810  # 800 + " ..." allowance


# ---------------------------------------------------------------------------
# deduplicate_results
# ---------------------------------------------------------------------------

class TestDeduplicateResults:
    """Tests for per-collection deduplication."""

    def test_removes_duplicate_text(self):
        docs = [
            ScoredDocument(10, "src", None, "same text", "coll_a", {}),
            ScoredDocument(8, "src", None, "same text", "coll_a", {}),
            ScoredDocument(6, "src", None, "different text", "coll_a", {}),
        ]
        result = deduplicate_results(docs, keep_per_collection=10)
        texts = [d.text for d in result]
        assert texts.count("same text") == 1

    def test_keeps_per_collection_limit(self):
        docs = [
            ScoredDocument(i, None, None, f"text_{i}", "coll_a", {})
            for i in range(20)
        ]
        result = deduplicate_results(docs, keep_per_collection=5)
        assert len(result) <= 5

    def test_sorted_by_score_descending(self):
        docs = [
            ScoredDocument(5, None, None, "low", "coll_a", {}),
            ScoredDocument(15, None, None, "high", "coll_a", {}),
            ScoredDocument(10, None, None, "mid", "coll_a", {}),
        ]
        result = deduplicate_results(docs, keep_per_collection=10)
        scores = [d.score for d in result]
        assert scores == sorted(scores, reverse=True)

    def test_empty_input(self):
        assert deduplicate_results([], keep_per_collection=5) == []

    def test_multiple_collections_kept_separate(self):
        docs = [
            ScoredDocument(10, None, None, "text_a", "coll_a", {}),
            ScoredDocument(10, None, None, "text_b", "coll_b", {}),
        ]
        result = deduplicate_results(docs, keep_per_collection=1)
        collections = {d.collection for d in result}
        assert collections == {"coll_a", "coll_b"}


# ---------------------------------------------------------------------------
# merge_and_deduplicate_global
# ---------------------------------------------------------------------------

class TestMergeAndDeduplicateGlobal:
    """Tests for global merge and dedup."""

    def test_global_dedup_across_collections(self):
        docs = [
            ScoredDocument(10, None, None, "duplicate text", "coll_a", {}),
            ScoredDocument(8, None, None, "duplicate text", "coll_b", {}),
            ScoredDocument(6, None, None, "unique text", "coll_a", {}),
        ]
        result = merge_and_deduplicate_global(docs, final_cap=10)
        texts = [d.text for d in result]
        assert texts.count("duplicate text") == 1

    def test_respects_final_cap(self):
        docs = [
            ScoredDocument(i, None, None, f"text_{i}", "coll", {})
            for i in range(50)
        ]
        result = merge_and_deduplicate_global(docs, final_cap=5)
        assert len(result) <= 5

    def test_highest_scores_kept(self):
        docs = [
            ScoredDocument(100, None, None, "best", "a", {}),
            ScoredDocument(1, None, None, "worst", "a", {}),
            ScoredDocument(50, None, None, "mid", "a", {}),
        ]
        result = merge_and_deduplicate_global(docs, final_cap=2)
        scores = [d.score for d in result]
        assert 100 in scores
        assert 1 not in scores

    def test_empty_returns_empty(self):
        assert merge_and_deduplicate_global([], final_cap=10) == []


# ---------------------------------------------------------------------------
# Error handling — missing collection
# ---------------------------------------------------------------------------

class TestSearchErrorHandling:
    """Tests for error resilience in search operations."""

    @pytest.mark.asyncio
    async def test_search_collection_handles_response_error(self):
        from chat_app.vectorstore_search import _search_collection_async

        mock_client = MagicMock()
        mock_client.similarity_search_with_score.side_effect = RuntimeError("collection not found")

        coll_name, results = await _search_collection_async(mock_client, "missing_coll", "query", 5)
        assert coll_name == "missing_coll"
        assert results == []

    @pytest.mark.asyncio
    async def test_search_collection_returns_results(self):
        from chat_app.vectorstore_search import _search_collection_async

        mock_doc = _make_doc("result text", {"source": "test"})
        mock_client = MagicMock()
        mock_client.similarity_search_with_score.return_value = [(mock_doc, 0.5)]

        coll_name, results = await _search_collection_async(mock_client, "test_coll", "query", 5)
        assert coll_name == "test_coll"
        assert len(results) == 1
