"""Comprehensive tests for chat_app/self_learning.py — the self-learning pipeline.

Covers:
  - Q&A generation from SPL docs, configs, metadata, saved searches, macros, indexes, org config
  - Answer reassessment against current collections
  - Feedback pattern analysis and semantic fact learning
  - Dynamic prompt overlay generation
  - Q&A ingestion to vector store
  - Cross-collection consolidation
  - Model customization (export, Modelfile generation, custom model creation)
  - Learning cycle orchestration
  - Quality scoring (_calculate_coverage)
  - Error handling (LLM unavailable, ChromaDB down, DB errors)
  - Edge cases (empty docs, no feedback, missing directories)
"""
import asyncio
import hashlib
import json
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch, mock_open

import pytest

# ---------------------------------------------------------------------------
# Pre-mock unavailable runtime dependencies so local imports inside
# self_learning.py functions resolve without error.
# ---------------------------------------------------------------------------
# sqlalchemy is an optional runtime dependency.  Try the real import first;
# only fall back to a MagicMock if it is genuinely unavailable.  A bare
# MagicMock breaks `from sqlalchemy.ext.asyncio import ...` used by other
# modules (e.g. health.py) that may be imported later in the same process.
if "sqlalchemy" not in sys.modules:
    try:
        import sqlalchemy  # noqa: F401
    except ImportError:
        _sa_mock = MagicMock()
        _sa_mock.text = MagicMock(side_effect=lambda s: s)
        sys.modules["sqlalchemy"] = _sa_mock
        sys.modules["sqlalchemy.ext"] = MagicMock()
        sys.modules["sqlalchemy.ext.asyncio"] = MagicMock()

# chat_app.vectorstore requires chromadb at import time
if "chat_app.vectorstore" not in sys.modules:
    _vs_mock = MagicMock()
    sys.modules["chat_app.vectorstore"] = _vs_mock

# chat_app.episodic_memory requires sqlalchemy top-level imports
if "chat_app.episodic_memory" not in sys.modules:
    _em_mock = MagicMock()
    _em_mock.store_semantic_fact = AsyncMock()
    _em_mock.get_relevant_facts = AsyncMock(return_value=[])
    _em_mock.consolidate_episodes_to_facts = AsyncMock(return_value=0)
    sys.modules["chat_app.episodic_memory"] = _em_mock

# aiohttp may not be installed in the test environment
if "aiohttp" not in sys.modules:
    _aiohttp_mock = MagicMock()
    _aiohttp_mock.ClientTimeout = MagicMock()
    sys.modules["aiohttp"] = _aiohttp_mock

from chat_app.self_learning import (
    QAPair,
    ReassessmentResult,
    LearningReport,
    ModelCustomizationReport,
    _extract_qa_from_spl_doc,
    _extract_qa_from_config,
    _extract_qa_from_metadata,
    _extract_qa_from_savedsearches,
    _extract_qa_from_macros,
    _extract_qa_from_indexes,
    _extract_qa_from_org_config,
    generate_qa_pairs_from_directory,
    reassess_past_answers,
    _calculate_coverage,
    analyze_feedback_patterns,
    _extract_topic,
    learn_facts_from_feedback,
    get_dynamic_prompt_overlay,
    rebuild_prompt_overlay,
    ingest_qa_pairs_to_vectorstore,
    _extract_cross_ref_terms,
    _query_collection_for_term,
    consolidate_cross_collection_insights,
    run_learning_cycle,
    get_cached_boost_scores,
    get_retrieval_boost_scores,
    export_qa_to_training_data,
    build_combined_training_file,
    generate_modelfile,
    create_custom_model,
    run_model_customization,
)


# ---------------------------------------------------------------------------
# Helpers & fixtures
# ---------------------------------------------------------------------------

def _make_spl_doc(cmd_name: str, description: str = "", syntax: str = "", examples: str = "") -> str:
    """Build a minimal SPL doc markdown string."""
    parts = [f"# {cmd_name}\n"]
    if description:
        parts.append(f"## Description\n{description}\n")
    if syntax:
        parts.append(f"## Syntax\n{syntax}\n")
    if examples:
        parts.append(f"## Examples\n{examples}\n")
    return "\n".join(parts)


def _make_conf_content(stanzas: dict) -> str:
    """Build a .conf file string from a dict of stanza_name -> body."""
    lines = []
    for name, body in stanzas.items():
        lines.append(f"[{name}]")
        lines.append(body)
        lines.append("")
    return "\n".join(lines)


def _make_metadata_md(sections: dict) -> str:
    """Build a markdown file with ## headings."""
    parts = ["# Top Level\n"]
    for heading, body in sections.items():
        parts.append(f"## {heading}\n{body}\n")
    return "\n".join(parts)


@pytest.fixture
def spl_doc_dir(tmp_path):
    """Create a temp directory with SPL doc files."""
    d = tmp_path / "spl_docs"
    d.mkdir()
    doc = _make_spl_doc(
        "stats",
        description="Calculates aggregate statistics over results.",
        syntax="stats <function>(<field>) [as <alias>] [by <field-list>]",
        examples="index=main | stats count by host",
    )
    (d / "spl_cmd_stats.md").write_text(doc)

    doc2 = _make_spl_doc(
        "eval",
        description="Evaluates an expression and assigns the result to a field.",
        syntax="eval <field>=<expression>",
    )
    (d / "spl_cmd_eval.md").write_text(doc2)
    return d


@pytest.fixture
def config_dir(tmp_path):
    """Create a temp directory with .conf files."""
    d = tmp_path / "configs"
    d.mkdir()
    conf = _make_conf_content({
        "source::syslog": "SHOULD_LINEMERGE = false\nTIME_FORMAT = %b %d %H:%M:%S",
        "default": "MAX_TIMESTAMP_LOOKAHEAD = 128",
    })
    (d / "props.conf").write_text(conf)
    return d


@pytest.fixture
def savedsearch_dir(tmp_path):
    """Create a temp directory with a savedsearches.conf file."""
    d = tmp_path / "savedsearches"
    d.mkdir()
    content = _make_conf_content({
        "Failed Logins": "search = index=security EventCode=4625 | stats count by src_ip\ncron_schedule = 0 */4 * * *\ndescription = Detects failed login attempts",
        "default": "",
    })
    (d / "savedsearches.conf").write_text(content)
    return d


@pytest.fixture
def macros_dir(tmp_path):
    """Create a temp directory with a macros.conf file."""
    d = tmp_path / "macros"
    d.mkdir()
    content = _make_conf_content({
        "get_notable(2)": "definition = `notable` src=$src$ dest=$dest$\nargs = src, dest\ndescription = Find notable events for src/dest pair",
        "default": "",
    })
    (d / "macros.conf").write_text(content)
    return d


@pytest.fixture
def indexes_dir(tmp_path):
    """Create a temp directory with an indexes.conf file."""
    d = tmp_path / "indexes"
    d.mkdir()
    content = _make_conf_content({
        "main": "frozenTimePeriodInSecs = 7776000\nmaxDataSizeMB = 500000\nhomePath = $SPLUNK_DB/main/db",
        "security": "frozenTimePeriodInSecs = 15552000\ndatatype = event",
        "volume:primary": "path = /opt/splunk/var/lib/splunk",
        "default": "",
    })
    (d / "indexes.conf").write_text(content)
    return d


@pytest.fixture
def metadata_dir(tmp_path):
    """Create a temp directory with metadata markdown files."""
    d = tmp_path / "metadata"
    d.mkdir()
    md = _make_metadata_md({
        "Splunk Architecture": "Splunk uses indexers, search heads, and forwarders.",
        "CIM Data Models": "The Common Information Model (CIM) provides a normalized schema.",
    })
    (d / "rag_context.md").write_text(md)
    return d


@pytest.fixture
def sample_qa_pairs():
    """A list of sample QAPair objects."""
    return [
        QAPair(question="What does stats do?", answer="Calculates aggregate stats.",
               source_file="/docs/spl_cmd_stats.md", source_type="spl_doc", topic="spl_stats"),
        QAPair(question="What is index=main?", answer="The default Splunk index.",
               source_file="/docs/indexes.md", source_type="config", topic="indexing"),
        QAPair(question="Show me the saved search 'Failed Logins'",
               answer="index=security EventCode=4625 | stats count by src_ip",
               source_file="/docs/savedsearches.conf", source_type="savedsearch", topic="savedsearch"),
    ]


@pytest.fixture
def mock_db_engine():
    """Mock async SQLAlchemy engine with configurable query results."""
    engine = MagicMock()
    mock_conn = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchall = MagicMock(return_value=[])
    mock_conn.execute = AsyncMock(return_value=mock_result)

    # engine.begin() returns an async context manager yielding mock_conn
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=mock_conn)
    ctx.__aexit__ = AsyncMock(return_value=False)
    engine.begin = MagicMock(return_value=ctx)

    # Attach internals for test customization
    engine._mock_conn = mock_conn
    engine._mock_result = mock_result
    return engine


@pytest.fixture
def mock_vector_store():
    """Mock ChromaDB-like vector store with no _client attribute."""
    store = MagicMock(spec=[])  # empty spec -> no _client attribute
    mock_collection = MagicMock()
    mock_collection.get = MagicMock(return_value={"ids": [], "documents": []})
    mock_collection.upsert = MagicMock()
    store.get_or_create_collection = MagicMock(return_value=mock_collection)
    store.get_collection = MagicMock(return_value=mock_collection)
    store._mock_collection = mock_collection
    return store


# ===================================================================
# 1. Q&A Generation from Documents
# ===================================================================

class TestQAGenerationSPLDoc:
    """Tests for _extract_qa_from_spl_doc."""

    def test_extracts_description(self, spl_doc_dir):
        filepath = str(spl_doc_dir / "spl_cmd_stats.md")
        pairs = _extract_qa_from_spl_doc(filepath)
        desc_pairs = [p for p in pairs if "what does" in p.question.lower()]
        assert len(desc_pairs) >= 1
        assert "stats" in desc_pairs[0].question.lower()
        assert desc_pairs[0].source_type == "spl_doc"

    def test_extracts_syntax(self, spl_doc_dir):
        filepath = str(spl_doc_dir / "spl_cmd_stats.md")
        pairs = _extract_qa_from_spl_doc(filepath)
        syntax_pairs = [p for p in pairs if "syntax" in p.question.lower()]
        assert len(syntax_pairs) >= 1

    def test_extracts_examples(self, spl_doc_dir):
        filepath = str(spl_doc_dir / "spl_cmd_stats.md")
        pairs = _extract_qa_from_spl_doc(filepath)
        example_pairs = [p for p in pairs if "example" in p.question.lower()]
        assert len(example_pairs) >= 1

    def test_three_pairs_for_complete_doc(self, spl_doc_dir):
        """A doc with all three sections should produce 3 pairs."""
        filepath = str(spl_doc_dir / "spl_cmd_stats.md")
        pairs = _extract_qa_from_spl_doc(filepath)
        assert len(pairs) == 3

    def test_partial_doc_fewer_pairs(self, spl_doc_dir):
        """eval doc has no Examples section, should produce 2 pairs."""
        filepath = str(spl_doc_dir / "spl_cmd_eval.md")
        pairs = _extract_qa_from_spl_doc(filepath)
        assert len(pairs) == 2

    def test_topic_set_correctly(self, spl_doc_dir):
        filepath = str(spl_doc_dir / "spl_cmd_stats.md")
        pairs = _extract_qa_from_spl_doc(filepath)
        assert all(p.topic == "spl_stats" for p in pairs)

    def test_missing_file_returns_empty(self):
        pairs = _extract_qa_from_spl_doc("/nonexistent/file.md")
        assert pairs == []

    def test_empty_file_returns_empty(self, tmp_path):
        empty_file = tmp_path / "spl_cmd_empty.md"
        empty_file.write_text("")
        pairs = _extract_qa_from_spl_doc(str(empty_file))
        assert pairs == []


class TestQAGenerationConfig:
    """Tests for _extract_qa_from_config."""

    def test_extracts_stanzas(self, config_dir):
        filepath = str(config_dir / "props.conf")
        pairs = _extract_qa_from_config(filepath)
        assert len(pairs) >= 1
        assert any("source::syslog" in p.question for p in pairs)

    def test_source_type_is_config(self, config_dir):
        filepath = str(config_dir / "props.conf")
        pairs = _extract_qa_from_config(filepath)
        assert all(p.source_type == "config" for p in pairs)

    def test_limits_stanzas_to_10(self, tmp_path):
        """If a config has 15 stanzas, only the first 10 produce pairs."""
        stanzas = {f"stanza_{i}": f"key{i} = val{i}" for i in range(15)}
        (tmp_path / "big.conf").write_text(_make_conf_content(stanzas))
        pairs = _extract_qa_from_config(str(tmp_path / "big.conf"))
        assert len(pairs) == 10


class TestQAGenerationMetadata:
    """Tests for _extract_qa_from_metadata."""

    def test_extracts_sections(self, metadata_dir):
        filepath = str(metadata_dir / "rag_context.md")
        pairs = _extract_qa_from_metadata(filepath)
        assert len(pairs) == 2
        topics = {p.topic for p in pairs}
        assert "splunk_architecture" in topics

    def test_source_type_is_metadata(self, metadata_dir):
        filepath = str(metadata_dir / "rag_context.md")
        pairs = _extract_qa_from_metadata(filepath)
        assert all(p.source_type == "metadata" for p in pairs)


class TestQAGenerationSavedSearches:
    """Tests for _extract_qa_from_savedsearches."""

    def test_extracts_saved_search(self, savedsearch_dir):
        filepath = str(savedsearch_dir / "savedsearches.conf")
        pairs = _extract_qa_from_savedsearches(filepath)
        # Should produce 2 pairs per saved search (description + SPL)
        # 'default' stanza is skipped
        assert len(pairs) == 2
        assert any("Failed Logins" in p.question for p in pairs)

    def test_skips_default_stanza(self, savedsearch_dir):
        filepath = str(savedsearch_dir / "savedsearches.conf")
        pairs = _extract_qa_from_savedsearches(filepath)
        assert not any("default" in p.question.lower() for p in pairs)


class TestQAGenerationMacros:
    """Tests for _extract_qa_from_macros."""

    def test_extracts_macro(self, macros_dir):
        filepath = str(macros_dir / "macros.conf")
        pairs = _extract_qa_from_macros(filepath)
        assert len(pairs) >= 1
        assert any("get_notable" in p.question for p in pairs)
        assert pairs[0].source_type == "macro"

    def test_arg_count_in_answer(self, macros_dir):
        filepath = str(macros_dir / "macros.conf")
        pairs = _extract_qa_from_macros(filepath)
        assert any("2 argument" in p.answer for p in pairs)


class TestQAGenerationIndexes:
    """Tests for _extract_qa_from_indexes."""

    def test_extracts_indexes(self, indexes_dir):
        filepath = str(indexes_dir / "indexes.conf")
        pairs = _extract_qa_from_indexes(filepath)
        # 'main' and 'security' stanzas (default and volume: skipped)
        assert len(pairs) == 2
        names = [p.question for p in pairs]
        assert any("main" in n for n in names)
        assert any("security" in n for n in names)

    def test_retention_calculation(self, indexes_dir):
        filepath = str(indexes_dir / "indexes.conf")
        pairs = _extract_qa_from_indexes(filepath)
        main_pair = [p for p in pairs if "main" in p.question][0]
        # 7776000 / 86400 = 90 days
        assert "90 days" in main_pair.answer


class TestQAGenerationOrgConfig:
    """Tests for _extract_qa_from_org_config."""

    @patch("chat_app.utils.load_config")
    def test_index_mappings(self, mock_load):
        mock_load.return_value = {
            "organization": {
                "index_mappings": {"security": "idx_security", "network": "idx_network"},
            }
        }
        pairs = _extract_qa_from_org_config("/fake/config.yaml")
        assert len(pairs) == 2
        assert any("security" in p.question.lower() for p in pairs)
        assert all(p.source_type == "org_config" for p in pairs)

    @patch("chat_app.utils.load_config")
    def test_field_mappings(self, mock_load):
        mock_load.return_value = {
            "organization": {
                "field_mappings": {"source_ip": "src_ip"},
            }
        }
        pairs = _extract_qa_from_org_config("/fake/config.yaml")
        assert len(pairs) == 1
        assert "source_ip" in pairs[0].question

    @patch("chat_app.utils.load_config")
    def test_empty_org_config(self, mock_load):
        mock_load.return_value = {"organization": {}}
        pairs = _extract_qa_from_org_config("/fake/config.yaml")
        assert pairs == []

    @patch("chat_app.utils.load_config", side_effect=RuntimeError("file not found"))
    def test_error_returns_empty(self, mock_load):
        pairs = _extract_qa_from_org_config("/fake/config.yaml")
        assert pairs == []


# ===================================================================
# 2. Directory-Level Q&A Generation
# ===================================================================

class TestGenerateQAPairsFromDirectory:

    def test_generates_from_spl_docs(self, spl_doc_dir):
        pairs = generate_qa_pairs_from_directory(str(spl_doc_dir))
        assert len(pairs) >= 4  # 3 from stats + 2 from eval = 5

    def test_deduplicates_by_question(self, tmp_path):
        """Same question in two files should only appear once."""
        d = tmp_path / "dedup"
        d.mkdir()
        doc = _make_spl_doc("cmd", description="Same description.")
        (d / "spl_cmd_cmd.md").write_text(doc)
        # Duplicate with same filename pattern
        sub = d / "sub"
        sub.mkdir()
        (sub / "spl_cmd_cmd.md").write_text(doc)
        pairs = generate_qa_pairs_from_directory(str(d))
        questions = [p.question for p in pairs]
        assert len(questions) == len(set(q.lower() for q in questions))

    def test_missing_directory_returns_empty(self):
        pairs = generate_qa_pairs_from_directory("/nonexistent/path")
        assert pairs == []

    def test_empty_directory_returns_empty(self, tmp_path):
        d = tmp_path / "empty"
        d.mkdir()
        pairs = generate_qa_pairs_from_directory(str(d))
        assert pairs == []

    def test_mixed_file_types(self, tmp_path):
        """Both SPL docs and config files are processed."""
        d = tmp_path / "mixed"
        d.mkdir()
        doc = _make_spl_doc("head", description="Returns first N results.")
        (d / "spl_cmd_head.md").write_text(doc)
        conf = _make_conf_content({"source::apache": "SHOULD_LINEMERGE = false"})
        (d / "props.conf").write_text(conf)
        pairs = generate_qa_pairs_from_directory(str(d))
        types = {p.source_type for p in pairs}
        assert "spl_doc" in types
        assert "config" in types


# ===================================================================
# 3. Coverage Scoring
# ===================================================================

class TestCalculateCoverage:

    def test_full_coverage(self):
        score = _calculate_coverage("how does the stats command work", "the stats command works by aggregating data")
        assert score > 0.5

    def test_no_coverage(self):
        score = _calculate_coverage("how does the stats command work", "completely unrelated text about nothing")
        assert score < 0.5

    def test_empty_question_returns_half(self):
        """All key terms removed by stop words -> return 0.5."""
        score = _calculate_coverage("the and for", "some text")
        assert score == 0.5

    def test_partial_coverage(self):
        score = _calculate_coverage("splunk stats command optimization", "the stats command")
        # 'stats' and 'command' match, 'splunk' and 'optimization' don't -> 2/4 = 0.5
        assert 0.3 <= score <= 0.7


# ===================================================================
# 4. Topic Extraction
# ===================================================================

class TestExtractTopic:

    def test_spl_topic(self):
        assert _extract_topic("How do I use the stats command in SPL?") == "spl"

    def test_config_topic(self):
        assert _extract_topic("Show me the props.conf stanza for syslog") == "config"

    def test_troubleshooting_topic(self):
        # "error" matches troubleshooting; avoid "search" which matches spl
        assert _extract_topic("My application is failing with an error") == "troubleshooting"

    def test_general_fallback(self):
        assert _extract_topic("Tell me about the weather today") == "general"

    def test_security_topic(self):
        assert _extract_topic("Show me security alert details") == "security"

    def test_cribl_topic(self):
        assert _extract_topic("How do I configure a cribl pipeline?") == "cribl"


# ===================================================================
# 5. Answer Reassessment
# ===================================================================

class TestReassessPastAnswers:

    @pytest.mark.asyncio
    async def test_returns_results_for_interactions(self, mock_db_engine):
        """When DB has interactions, each is reassessed."""
        mock_db_engine._mock_result.fetchall.return_value = [
            ("What does stats do?", "stats aggregates data", "2026-01-01"),
        ]

        def mock_search(vs, q, k=10):
            return [{"text": "stats calculates aggregate statistics over results"}]

        results = await reassess_past_answers(
            mock_db_engine, mock_search, MagicMock(), limit=10
        )
        assert len(results) == 1
        assert isinstance(results[0], ReassessmentResult)

    @pytest.mark.asyncio
    async def test_empty_interactions_returns_empty(self, mock_db_engine):
        mock_db_engine._mock_result.fetchall.return_value = []
        results = await reassess_past_answers(
            mock_db_engine, MagicMock(), MagicMock()
        )
        assert results == []

    @pytest.mark.asyncio
    async def test_db_failure_returns_empty(self):
        """Database error should be caught and return empty list."""
        engine = MagicMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("connection refused"))
        ctx.__aexit__ = AsyncMock(return_value=False)
        engine.begin = MagicMock(return_value=ctx)

        results = await reassess_past_answers(engine, MagicMock(), MagicMock())
        assert results == []

    @pytest.mark.asyncio
    async def test_skips_null_questions(self, mock_db_engine):
        mock_db_engine._mock_result.fetchall.return_value = [
            (None, "some answer", "2026-01-01"),
            ("", "another answer", "2026-01-01"),
        ]
        results = await reassess_past_answers(
            mock_db_engine, MagicMock(), MagicMock()
        )
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_improvement_detected(self, mock_db_engine):
        """When new retrieval has much better coverage, improved=True."""
        mock_db_engine._mock_result.fetchall.return_value = [
            ("how does the eval command work in splunk", "it works somehow", "2026-01-01"),
        ]

        def mock_search(vs, q, k=10):
            return [{"text": "The eval command evaluates an expression and assigns it to a field in Splunk SPL. eval command work splunk"}]

        results = await reassess_past_answers(
            mock_db_engine, mock_search, MagicMock()
        )
        assert len(results) == 1
        # The new retrieval should cover more key terms than the original vague answer
        assert results[0].confidence_delta != 0.0


# ===================================================================
# 6. Feedback Pattern Analysis
# ===================================================================

class TestAnalyzeFeedbackPatterns:

    @pytest.mark.asyncio
    async def test_returns_insights_structure(self, mock_db_engine):
        insights = await analyze_feedback_patterns(mock_db_engine)
        assert "low_satisfaction_topics" in insights
        assert "high_success_patterns" in insights
        assert "common_failure_modes" in insights
        assert "prompt_suggestions" in insights

    @pytest.mark.asyncio
    async def test_db_error_returns_empty_insights(self):
        engine = MagicMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("DB down"))
        ctx.__aexit__ = AsyncMock(return_value=False)
        engine.begin = MagicMock(return_value=ctx)

        insights = await analyze_feedback_patterns(engine)
        assert insights["low_satisfaction_topics"] == []
        assert insights["prompt_suggestions"] == []

    @pytest.mark.asyncio
    async def test_disliked_queries_populate_low_satisfaction(self, mock_db_engine):
        """Simulate disliked queries being returned from DB."""
        call_count = 0

        async def multi_execute(query, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # disliked queries
                result.fetchall = MagicMock(return_value=[
                    ("how to use eval", 3),
                    ("what is stats", 2),
                ])
            elif call_count == 2:
                # liked queries
                result.fetchall = MagicMock(return_value=[])
            else:
                # failures
                result.fetchall = MagicMock(return_value=[])
            return result

        mock_db_engine._mock_conn.execute = multi_execute

        insights = await analyze_feedback_patterns(mock_db_engine)
        assert len(insights["low_satisfaction_topics"]) >= 1


# ===================================================================
# 7. Semantic Fact Learning
# ===================================================================

class TestLearnFactsFromFeedback:

    @pytest.mark.asyncio
    async def test_creates_facts_from_patterns(self, mock_db_engine):
        mock_store = AsyncMock()
        mock_analyze = AsyncMock(return_value={
            "high_success_patterns": [{"topic": "spl", "count": 5}],
            "common_failure_modes": [{"intent": "config_lookup", "count": 10}],
            "low_satisfaction_topics": [{"topic": "troubleshooting", "dislike_count": 4}],
        })
        em_mod = sys.modules["chat_app.episodic_memory"]
        orig = em_mod.store_semantic_fact
        em_mod.store_semantic_fact = mock_store
        try:
            with patch("chat_app.self_learning.analyze_feedback_patterns", mock_analyze):
                count = await learn_facts_from_feedback(mock_db_engine)
            assert count == 3  # 1 high_success + 1 failure + 1 low_satisfaction
            assert mock_store.call_count == 3
        finally:
            em_mod.store_semantic_fact = orig

    @pytest.mark.asyncio
    async def test_no_patterns_no_facts(self, mock_db_engine):
        mock_store = AsyncMock()
        mock_analyze = AsyncMock(return_value={
            "high_success_patterns": [],
            "common_failure_modes": [],
            "low_satisfaction_topics": [],
        })
        em_mod = sys.modules["chat_app.episodic_memory"]
        orig = em_mod.store_semantic_fact
        em_mod.store_semantic_fact = mock_store
        try:
            with patch("chat_app.self_learning.analyze_feedback_patterns", mock_analyze):
                count = await learn_facts_from_feedback(mock_db_engine)
            assert count == 0
            mock_store.assert_not_called()
        finally:
            em_mod.store_semantic_fact = orig

    @pytest.mark.asyncio
    async def test_error_returns_zero(self, mock_db_engine):
        """If the import of episodic_memory or analysis fails, return 0."""
        mock_analyze = AsyncMock(side_effect=RuntimeError("boom"))
        with patch("chat_app.self_learning.analyze_feedback_patterns", mock_analyze):
            count = await learn_facts_from_feedback(mock_db_engine)
        assert count == 0


# ===================================================================
# 8. Dynamic Prompt Overlay
# ===================================================================

class TestPromptOverlay:

    def test_get_dynamic_prompt_overlay_returns_string(self):
        result = get_dynamic_prompt_overlay()
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_rebuild_with_facts_and_patterns(self, mock_db_engine):
        mock_facts_fn = AsyncMock(return_value=[
            {"rule": "Always include SPL examples", "confidence": 0.8},
            {"rule": "Reference spec files for config questions", "confidence": 0.7},
        ])
        mock_analyze = AsyncMock(return_value={
            "low_satisfaction_topics": [{"topic": "config", "dislike_count": 5}],
            "high_success_patterns": [{"topic": "spl", "count": 10}],
            "common_failure_modes": [{"intent": "troubleshoot", "count": 7, "reason": "no context"}],
        })
        mock_boost = MagicMock(return_value={"spl_commands_mxbai": 1.3, "assistant_memory_mxbai_v2": 0.8})

        em_mod = sys.modules["chat_app.episodic_memory"]
        orig = em_mod.get_relevant_facts
        em_mod.get_relevant_facts = mock_facts_fn
        try:
            with patch("chat_app.self_learning.analyze_feedback_patterns", mock_analyze), \
                 patch("chat_app.self_learning.get_cached_boost_scores", mock_boost):
                overlay = await rebuild_prompt_overlay(mock_db_engine)
        finally:
            em_mod.get_relevant_facts = orig

        assert "Learned Behavioral Rules" in overlay
        assert "Always include SPL examples" in overlay
        assert "Areas Needing Improvement" in overlay
        assert "config" in overlay
        assert "What's Working Well" in overlay
        assert "Common Failure Modes" in overlay
        assert "Collection Effectiveness" in overlay

    @pytest.mark.asyncio
    async def test_rebuild_with_no_data(self, mock_db_engine):
        mock_facts_fn = AsyncMock(return_value=[])
        mock_analyze = AsyncMock(return_value={
            "low_satisfaction_topics": [],
            "high_success_patterns": [],
            "common_failure_modes": [],
        })
        mock_boost = MagicMock(return_value={})

        em_mod = sys.modules["chat_app.episodic_memory"]
        orig = em_mod.get_relevant_facts
        em_mod.get_relevant_facts = mock_facts_fn
        try:
            with patch("chat_app.self_learning.analyze_feedback_patterns", mock_analyze), \
                 patch("chat_app.self_learning.get_cached_boost_scores", mock_boost):
                overlay = await rebuild_prompt_overlay(mock_db_engine)
        finally:
            em_mod.get_relevant_facts = orig

        assert overlay == ""


# ===================================================================
# 9. Q&A Ingestion to Vector Store
# ===================================================================

class TestIngestQAPairs:

    @pytest.mark.asyncio
    async def test_ingest_pairs(self, sample_qa_pairs, mock_vector_store):
        vs_mod = sys.modules["chat_app.vectorstore"]
        vs_mod.get_embeddings_model = MagicMock(return_value=None)
        count = await ingest_qa_pairs_to_vectorstore(
            sample_qa_pairs, mock_vector_store, collection_name="test_qa"
        )
        assert count == len(sample_qa_pairs)
        mock_vector_store.get_or_create_collection.assert_called_with("test_qa")

    @pytest.mark.asyncio
    async def test_empty_pairs_returns_zero(self, mock_vector_store):
        count = await ingest_qa_pairs_to_vectorstore([], mock_vector_store)
        assert count == 0

    @pytest.mark.asyncio
    async def test_none_store_returns_zero(self, sample_qa_pairs):
        count = await ingest_qa_pairs_to_vectorstore(sample_qa_pairs, None)
        assert count == 0

    @pytest.mark.asyncio
    async def test_ingestion_without_embedder(self, sample_qa_pairs, mock_vector_store):
        """When embedder fails to init, ingestion should still work (ChromaDB default)."""
        vs_mod = sys.modules["chat_app.vectorstore"]
        vs_mod.get_embeddings_model = MagicMock(side_effect=RuntimeError("Ollama down"))
        count = await ingest_qa_pairs_to_vectorstore(
            sample_qa_pairs, mock_vector_store
        )
        assert count == len(sample_qa_pairs)

    @pytest.mark.asyncio
    async def test_chromadb_failure_returns_zero(self, sample_qa_pairs):
        """When ChromaDB fails entirely, ingested count is 0."""
        vs_mod = sys.modules["chat_app.vectorstore"]
        vs_mod.get_embeddings_model = MagicMock(return_value=None)
        store = MagicMock(spec=[])
        store.get_or_create_collection = MagicMock(side_effect=RuntimeError("ChromaDB unreachable"))
        count = await ingest_qa_pairs_to_vectorstore(sample_qa_pairs, store)
        assert count == 0


# ===================================================================
# 10. Cross-Collection Consolidation
# ===================================================================

class TestCrossCollectionConsolidation:

    def test_extract_cross_ref_terms_finds_cross_type(self):
        pairs = [
            QAPair(question="How to use stats?", answer="stats count by host for index=main",
                   source_type="spl_doc"),
            QAPair(question="What is index main?", answer="index=main is the default Splunk index. stats are fast.",
                   source_type="config"),
        ]
        cross_refs = _extract_cross_ref_terms(pairs)
        # 'stats' and 'main' appear in both spl_doc and config source types
        assert "stats" in cross_refs or "main" in cross_refs

    def test_no_cross_refs_for_single_type(self):
        pairs = [
            QAPair(question="stats info", answer="stats aggregates", source_type="spl_doc"),
            QAPair(question="eval info", answer="eval computes", source_type="spl_doc"),
        ]
        cross_refs = _extract_cross_ref_terms(pairs)
        # Same source_type for all -> no cross-references
        assert len(cross_refs) == 0

    def test_query_collection_for_term_success(self):
        """The function uses getattr(store, '_client', None) or store, then .get_collection()."""
        mock_collection = MagicMock()
        mock_collection.get.return_value = {"documents": ["Doc about stats command"]}
        store = MagicMock(spec=[])  # no _client attribute
        store.get_collection = MagicMock(return_value=mock_collection)
        docs = _query_collection_for_term(store, "test_coll", "stats")
        assert len(docs) == 1

    def test_query_collection_for_term_error(self):
        store = MagicMock(spec=[])
        store.get_collection = MagicMock(side_effect=RuntimeError("collection not found"))
        docs = _query_collection_for_term(store, "missing_coll", "stats")
        assert docs == []

    @pytest.mark.asyncio
    async def test_consolidation_empty_cross_refs(self, mock_vector_store):
        pairs = [QAPair(question="hello", answer="world", source_type="test")]
        insights = await consolidate_cross_collection_insights(pairs, mock_vector_store)
        assert insights == []


# ===================================================================
# 11. Retrieval Boost Scores
# ===================================================================

class TestRetrievalBoostScores:

    def test_get_cached_boost_scores_returns_dict(self):
        result = get_cached_boost_scores()
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_boost_scores_from_db(self, mock_db_engine):
        mock_db_engine._mock_result.fetchall.return_value = [
            ('["spl_commands_mxbai", "assistant_memory_mxbai_v2"]', 0.8, 10),
        ]
        boosts = await get_retrieval_boost_scores(mock_db_engine)
        assert "spl_commands_mxbai" in boosts
        assert "assistant_memory_mxbai_v2" in boosts
        # 0.5 + 0.8 = 1.3
        assert boosts["spl_commands_mxbai"] == pytest.approx(1.3)

    @pytest.mark.asyncio
    async def test_boost_scores_db_error(self):
        engine = MagicMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=RuntimeError("DB error"))
        ctx.__aexit__ = AsyncMock(return_value=False)
        engine.begin = MagicMock(return_value=ctx)

        boosts = await get_retrieval_boost_scores(engine)
        assert boosts == {}


# ===================================================================
# 12. Model Customization: Export
# ===================================================================

class TestExportQAToTrainingData:

    def test_exports_to_jsonl(self, tmp_path, sample_qa_pairs):
        filepath, count = export_qa_to_training_data(
            sample_qa_pairs, output_dir=str(tmp_path)
        )
        assert count == 3
        assert filepath.endswith(".jsonl")

        lines = Path(filepath).read_text().strip().split("\n")
        assert len(lines) == 3

        entry = json.loads(lines[0])
        assert "messages" in entry
        assert len(entry["messages"]) == 3
        assert entry["messages"][0]["role"] == "system"
        assert entry["messages"][1]["role"] == "user"
        assert entry["messages"][2]["role"] == "assistant"

    def test_skips_empty_qa_pairs(self, tmp_path):
        pairs = [
            QAPair(question="", answer="no question"),
            QAPair(question="has question", answer=""),
            QAPair(question="valid", answer="valid"),
        ]
        filepath, count = export_qa_to_training_data(pairs, output_dir=str(tmp_path))
        assert count == 1

    def test_custom_system_prompt(self, tmp_path, sample_qa_pairs):
        filepath, count = export_qa_to_training_data(
            sample_qa_pairs, output_dir=str(tmp_path), system_prompt="Custom prompt"
        )
        entry = json.loads(Path(filepath).read_text().strip().split("\n")[0])
        assert entry["messages"][0]["content"] == "Custom prompt"

    def test_metadata_in_export(self, tmp_path, sample_qa_pairs):
        filepath, _ = export_qa_to_training_data(sample_qa_pairs, output_dir=str(tmp_path))
        entry = json.loads(Path(filepath).read_text().strip().split("\n")[0])
        assert "metadata" in entry
        assert "source_file" in entry["metadata"]
        assert "source_type" in entry["metadata"]


class TestBuildCombinedTrainingFile:

    def test_combines_files(self, tmp_path):
        # Write two JSONL files
        (tmp_path / "file1.jsonl").write_text('{"a":1}\n{"b":2}\n')
        (tmp_path / "file2.jsonl").write_text('{"c":3}\n')
        filepath, total = build_combined_training_file(output_dir=str(tmp_path))
        assert total == 3
        assert "combined_training.jsonl" in filepath

    def test_deduplicates(self, tmp_path):
        same_line = '{"key":"same"}'
        (tmp_path / "file1.jsonl").write_text(same_line + "\n")
        (tmp_path / "file2.jsonl").write_text(same_line + "\n")
        filepath, total = build_combined_training_file(output_dir=str(tmp_path))
        assert total == 1

    def test_empty_directory(self, tmp_path):
        d = tmp_path / "empty_train"
        d.mkdir()
        filepath, total = build_combined_training_file(output_dir=str(d))
        assert total == 0

    def test_missing_directory(self):
        filepath, total = build_combined_training_file(output_dir="/nonexistent/dir")
        assert filepath == ""
        assert total == 0


# ===================================================================
# 13. Model Customization: Modelfile Generation
# ===================================================================

class TestGenerateModelfile:

    def test_generates_modelfile(self, tmp_path):
        mock_settings = MagicMock()
        mock_settings.ollama.model = "qwen2.5:3b"
        with patch("chat_app.settings.get_settings", return_value=mock_settings), \
             patch("chat_app.self_learning.get_dynamic_prompt_overlay", return_value=""):
            path = generate_modelfile(output_dir=str(tmp_path))
        content = Path(path).read_text()
        assert "FROM qwen2.5:3b" in content
        assert "PARAMETER temperature" in content
        assert "SYSTEM" in content

    def test_includes_overlay_rules(self, tmp_path):
        mock_settings = MagicMock()
        mock_settings.ollama.model = "llama3:8b"
        with patch("chat_app.settings.get_settings", return_value=mock_settings), \
             patch("chat_app.self_learning.get_dynamic_prompt_overlay", return_value="- Rule 1\n- Rule 2"):
            path = generate_modelfile(output_dir=str(tmp_path))
        content = Path(path).read_text()
        assert "Learned rules" in content
        assert "Rule 1" in content

    def test_custom_base_model(self, tmp_path):
        mock_settings = MagicMock()
        mock_settings.ollama.model = "default"
        with patch("chat_app.settings.get_settings", return_value=mock_settings), \
             patch("chat_app.self_learning.get_dynamic_prompt_overlay", return_value=""):
            path = generate_modelfile(base_model="custom:7b", output_dir=str(tmp_path))
        content = Path(path).read_text()
        assert "FROM custom:7b" in content


# ===================================================================
# 14. Model Customization: Create Custom Model
# ===================================================================

class TestCreateCustomModel:

    @pytest.mark.asyncio
    async def test_aiohttp_success(self, tmp_path):
        from chat_app import settings as _settings_mod
        mock_settings = MagicMock()
        mock_settings.ollama.model = "qwen2.5:3b"
        mock_settings.ollama.base_url = "http://localhost:11430"

        mf_path = tmp_path / "Modelfile"
        mf_path.write_text("FROM qwen2.5:3b\nSYSTEM test")

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        aiohttp_mod = sys.modules["aiohttp"]
        aiohttp_mod.ClientSession = MagicMock(return_value=mock_session)
        aiohttp_mod.ClientTimeout = MagicMock()

        with patch.object(_settings_mod, "get_settings", return_value=mock_settings), \
             patch("chat_app.self_learning.generate_modelfile", return_value=str(mf_path)):
            report = await create_custom_model(modelfile_path=str(mf_path))
        assert report.model_created is True
        assert report.error == ""

    @pytest.mark.asyncio
    async def test_aiohttp_api_error(self, tmp_path):
        from chat_app import settings as _settings_mod
        mock_settings = MagicMock()
        mock_settings.ollama.model = "qwen2.5:3b"
        mock_settings.ollama.base_url = "http://localhost:11430"

        mf_path = tmp_path / "Modelfile"
        mf_path.write_text("FROM qwen2.5:3b\nSYSTEM test")

        mock_resp = AsyncMock()
        mock_resp.status = 500
        mock_resp.text = AsyncMock(return_value="Internal Server Error")
        mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_resp.__aexit__ = AsyncMock(return_value=False)

        mock_session = AsyncMock()
        mock_session.post = MagicMock(return_value=mock_resp)
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=False)

        aiohttp_mod = sys.modules["aiohttp"]
        aiohttp_mod.ClientSession = MagicMock(return_value=mock_session)
        aiohttp_mod.ClientTimeout = MagicMock()

        with patch.object(_settings_mod, "get_settings", return_value=mock_settings), \
             patch("chat_app.self_learning.generate_modelfile", return_value=str(mf_path)):
            report = await create_custom_model(modelfile_path=str(mf_path))
        assert report.model_created is False
        assert "500" in report.error


# ===================================================================
# 15. Full Learning Cycle
# ===================================================================

class TestRunLearningCycle:

    @pytest.mark.asyncio
    @patch("chat_app.self_learning_cycle._save_learning_report")
    @patch("chat_app.self_learning_cycle._get_default_directories", return_value=[])
    @patch("chat_app.self_learning._extract_qa_from_org_config", return_value=[])
    async def test_minimal_cycle_no_engine(self, mock_org, mock_dirs, mock_save):
        """Cycle with no engine/vector_store/search_func runs step 1 only."""
        report = await run_learning_cycle(engine=None, vector_store=None, search_func=None)
        assert isinstance(report, LearningReport)
        assert report.qa_pairs_generated == 0
        assert report.answers_reassessed == 0
        assert report.duration_seconds >= 0
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    @patch("chat_app.self_learning_cycle._save_learning_report")
    @patch("chat_app.self_learning_cycle._get_default_directories")
    @patch("chat_app.self_learning._extract_qa_from_org_config", return_value=[])
    @patch("chat_app.self_learning.ingest_qa_pairs_to_vectorstore", new_callable=AsyncMock, return_value=5)
    @patch("chat_app.self_learning.reassess_past_answers", new_callable=AsyncMock)
    @patch("chat_app.self_learning.learn_facts_from_feedback", new_callable=AsyncMock, return_value=2)
    @patch("chat_app.self_learning.rebuild_prompt_overlay", new_callable=AsyncMock, return_value="overlay text")
    @patch("chat_app.self_learning.get_retrieval_boost_scores", new_callable=AsyncMock, return_value={})
    async def test_full_cycle_with_all_components(
        self, mock_boost, mock_overlay, mock_facts, mock_reassess,
        mock_ingest, mock_org, mock_dirs, mock_save,
        spl_doc_dir, mock_db_engine, mock_vector_store,
    ):
        mock_dirs.return_value = [str(spl_doc_dir)]
        mock_reassess.return_value = [
            ReassessmentResult(original_question="q1", original_answer="a1", improved=True),
            ReassessmentResult(original_question="q2", original_answer="a2", improved=False),
        ]

        report = await run_learning_cycle(
            engine=mock_db_engine,
            vector_store=mock_vector_store,
            search_func=MagicMock(),
            doc_directories=[str(spl_doc_dir)],
        )

        assert report.qa_pairs_generated >= 4  # stats(3) + eval(2)
        assert report.answers_reassessed == 2
        assert report.answers_improved == 1
        assert report.facts_learned >= 2
        assert report.prompts_refined == 1
        assert report.duration_seconds > 0

    @pytest.mark.asyncio
    @patch("chat_app.self_learning_cycle._save_learning_report")
    @patch("chat_app.self_learning_cycle._get_default_directories", return_value=[])
    @patch("chat_app.self_learning._extract_qa_from_org_config", return_value=[])
    @patch("chat_app.self_learning.learn_facts_from_feedback", new_callable=AsyncMock, return_value=0)
    @patch("chat_app.self_learning.rebuild_prompt_overlay", new_callable=AsyncMock, side_effect=RuntimeError("overlay error"))
    @patch("chat_app.self_learning.get_retrieval_boost_scores", new_callable=AsyncMock, side_effect=RuntimeError("boost error"))
    async def test_cycle_continues_on_step_failure(
        self, mock_boost, mock_overlay, mock_facts, mock_org, mock_dirs, mock_save,
        mock_db_engine,
    ):
        """Even if steps 5 and 6 fail, the cycle completes."""
        report = await run_learning_cycle(engine=mock_db_engine)
        assert isinstance(report, LearningReport)
        # Should still complete without raising
        mock_save.assert_called_once()


# ===================================================================
# 16. Model Customization Pipeline
# ===================================================================

class TestRunModelCustomization:

    @pytest.mark.asyncio
    @patch("chat_app.self_learning_cycle._get_default_directories", return_value=[])
    @patch("chat_app.self_learning._extract_qa_from_org_config", return_value=[])
    async def test_too_few_pairs_skips(self, mock_org, mock_dirs):
        """Fewer than _MODEL_CUSTOMIZE_MIN_QA pairs -> skip (without force)."""
        report = await run_model_customization()
        assert "Not enough Q&A pairs" in report.error
        assert report.model_created is False

    @pytest.mark.asyncio
    @patch("chat_app.self_learning_cycle._get_default_directories", return_value=[])
    @patch("chat_app.self_learning._extract_qa_from_org_config", return_value=[])
    @patch("chat_app.self_learning_cycle.export_qa_to_training_data", return_value=("/fake/file.jsonl", 5))
    @patch("chat_app.self_learning_cycle.build_combined_training_file", return_value=("/fake/combined.jsonl", 5))
    @patch("chat_app.self_learning_cycle.generate_modelfile", return_value="/fake/Modelfile")
    @patch("chat_app.self_learning_cycle.create_custom_model", new_callable=AsyncMock)
    async def test_force_bypasses_minimum(
        self, mock_create, mock_gen, mock_combine, mock_export, mock_org, mock_dirs, tmp_path,
    ):
        mock_create.return_value = ModelCustomizationReport(
            model_created=True, model_name="test-model"
        )
        import os
        os.environ["LEARNING_DATA_DIR"] = str(tmp_path)
        try:
            report = await run_model_customization(force=True)
            assert report.model_created is True
            mock_export.assert_called_once()
        finally:
            os.environ.pop("LEARNING_DATA_DIR", None)


# ===================================================================
# 17. Data Structures
# ===================================================================

class TestDataStructures:

    def test_qa_pair_defaults(self):
        pair = QAPair(question="Q", answer="A")
        assert pair.source_file == ""
        assert pair.source_type == ""
        assert pair.confidence == 0.7
        assert pair.topic == ""

    def test_reassessment_result_defaults(self):
        r = ReassessmentResult(original_question="Q", original_answer="A")
        assert r.new_answer is None
        assert r.improved is False
        assert r.confidence_delta == 0.0

    def test_learning_report_defaults(self):
        r = LearningReport()
        assert r.qa_pairs_generated == 0
        assert r.topics_covered == []
        assert r.duration_seconds == 0.0

    def test_model_customization_report_defaults(self):
        r = ModelCustomizationReport()
        assert r.model_created is False
        assert r.error == ""


# ===================================================================
# 18. Edge Cases
# ===================================================================

class TestEdgeCases:

    def test_spl_doc_with_only_heading(self, tmp_path):
        """A markdown file with only a heading and no sections."""
        (tmp_path / "spl_cmd_bare.md").write_text("# bare command\n\nSome intro text.\n")
        pairs = _extract_qa_from_spl_doc(str(tmp_path / "spl_cmd_bare.md"))
        assert pairs == []

    def test_config_with_empty_stanzas(self, tmp_path):
        """Stanzas with no body should not generate pairs."""
        content = "[empty_stanza]\n\n[another]\n\n"
        (tmp_path / "test.conf").write_text(content)
        pairs = _extract_qa_from_config(str(tmp_path / "test.conf"))
        assert pairs == []

    def test_metadata_with_no_sections(self, tmp_path):
        """Markdown file with no ## headings."""
        (tmp_path / "no_sections.md").write_text("Just some plain text without headings.\n")
        pairs = _extract_qa_from_metadata(str(tmp_path / "no_sections.md"))
        assert pairs == []

    def test_savedsearch_no_search_key(self, tmp_path):
        """Stanza without search= should not produce pairs."""
        content = "[My Alert]\ncron_schedule = 0 * * * *\ndescription = No search key\n"
        (tmp_path / "savedsearches.conf").write_text(content)
        pairs = _extract_qa_from_savedsearches(str(tmp_path / "savedsearches.conf"))
        assert pairs == []

    def test_macros_no_definition(self, tmp_path):
        """Macro without definition= should not produce pairs."""
        content = "[my_macro]\nargs = arg1\ndescription = No definition\n"
        (tmp_path / "macros.conf").write_text(content)
        pairs = _extract_qa_from_macros(str(tmp_path / "macros.conf"))
        assert pairs == []

    @pytest.mark.asyncio
    async def test_ingestion_with_large_batch(self):
        """Batch ingestion with more items than batch_size triggers multiple upserts."""
        os.environ["LEARNING_BATCH_SIZE"] = "2"
        os.environ["LEARNING_BATCH_DELAY_S"] = "0"
        try:
            pairs = [
                QAPair(question=f"Q{i}", answer=f"A{i}", source_file=f"/f{i}")
                for i in range(5)
            ]
            collection = MagicMock()
            collection.get = MagicMock(return_value={"ids": []})
            collection.upsert = MagicMock()
            store = MagicMock(spec=[])
            store.get_or_create_collection = MagicMock(return_value=collection)

            vs_mod = sys.modules["chat_app.vectorstore"]
            vs_mod.get_embeddings_model = MagicMock(return_value=None)
            count = await ingest_qa_pairs_to_vectorstore(pairs, store)
            assert count == 5
            # 5 items with batch_size=2 -> 2 full batches + 1 final batch = 3 upsert calls
            assert collection.upsert.call_count == 3
        finally:
            os.environ.pop("LEARNING_BATCH_SIZE", None)
            os.environ.pop("LEARNING_BATCH_DELAY_S", None)

    def test_calculate_coverage_empty_text(self):
        score = _calculate_coverage("what is splunk", "")
        assert score == 0.0

    def test_calculate_coverage_empty_both(self):
        # No key terms after stop word removal -> 0.5
        score = _calculate_coverage("", "")
        assert score == 0.5

    @pytest.mark.asyncio
    async def test_boost_scores_handles_invalid_json(self, mock_db_engine):
        """Non-JSON collections_searched should be skipped."""
        mock_db_engine._mock_result.fetchall.return_value = [
            ("not valid json", 0.9, 10),
        ]
        boosts = await get_retrieval_boost_scores(mock_db_engine)
        assert boosts == {}


# ===================================================================
# 19. Learning Report Persistence
# ===================================================================

class TestLearningReportPersistence:

    @patch("chat_app.self_learning.Path.mkdir")
    @patch("builtins.open", new_callable=mock_open)
    @patch("chat_app.self_learning.Path.glob", return_value=[])
    def test_save_learning_report(self, mock_glob, mock_file, mock_mkdir):
        from chat_app.self_learning_cycle import _save_learning_report
        report = LearningReport(
            timestamp="2026-01-01T00:00:00Z",
            qa_pairs_generated=10,
            answers_reassessed=5,
            answers_improved=2,
            facts_learned=3,
        )
        _save_learning_report(report)
        mock_mkdir.assert_called_once()
        mock_file.assert_called_once()
        # Verify JSON was written
        written = "".join(
            call.args[0] for call in mock_file().write.call_args_list
        )
        data = json.loads(written)
        assert data["qa_pairs_generated"] == 10
        assert data["answers_improved"] == 2
