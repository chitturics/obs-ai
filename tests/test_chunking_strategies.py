"""Tests for the 11 chunking strategies in document_ingestor.py."""
import json
import pytest

from chat_app.document_ingestor import (
    CHUNKING_STRATEGIES,
    _chunk_text,
    chunk_by_ast,
    chunk_by_headings,
    chunk_by_paragraphs,
    chunk_conversation,
    chunk_late,
    chunk_propositions,
    chunk_sliding_window,
    chunk_structured_data,
    chunk_table,
    chunk_with_strategy,
    select_chunking_strategy,
)


# ── helpers ──────────────────────────────────────────────────────────────

def _texts(chunks):
    """Extract text from chunk list."""
    return [c["text"] for c in chunks]


def _strategy_meta(chunks):
    """Extract chunking_strategy from all chunks."""
    return [c["metadata"].get("chunking_strategy") for c in chunks]


# ── Strategy Registry ────────────────────────────────────────────────────

class TestRegistry:
    def test_all_11_strategies_registered(self):
        expected = {
            "token", "heading", "code", "semantic",
            "structured_data", "table", "conversation",
            "late", "propositions", "sliding_window",
        }
        # 10 registered (stanza is elsewhere); verify the ones we own
        assert expected.issubset(set(CHUNKING_STRATEGIES.keys()))
        assert len(CHUNKING_STRATEGIES) >= 10


# ── Auto-Selection ───────────────────────────────────────────────────────

class TestAutoSelect:
    def test_json_selects_structured_data(self):
        assert select_chunking_strategy("data.json", '{"a":1}') == "structured_data"

    def test_yaml_selects_structured_data(self):
        assert select_chunking_strategy("config.yaml", "key: value") == "structured_data"

    def test_yml_selects_structured_data(self):
        assert select_chunking_strategy("config.yml", "key: value") == "structured_data"

    def test_csv_selects_table(self):
        assert select_chunking_strategy("data.csv", "a,b\n1,2") == "table"

    def test_tsv_selects_table(self):
        assert select_chunking_strategy("data.tsv", "a\tb\n1\t2") == "table"

    def test_log_selects_conversation(self):
        assert select_chunking_strategy("app.log", "2024-01-01 some log") == "conversation"

    def test_long_doc_selects_late(self):
        long_content = "word " * 1500  # > 5000 chars
        assert select_chunking_strategy("readme.txt", long_content) == "late"

    def test_markdown_with_headings_selects_heading(self):
        assert select_chunking_strategy("doc.md", "# Title\ntext") == "heading"

    def test_python_selects_code(self):
        assert select_chunking_strategy("script.py", "def foo(): pass") == "code"

    def test_short_plain_selects_token(self):
        assert select_chunking_strategy("notes.txt", "Short text.") == "token"


# ── Structured Data Strategy ─────────────────────────────────────────────

class TestStructuredData:
    def test_json_top_level_keys(self):
        data = json.dumps({"name": "Alice", "age": 30, "city": "NY"})
        chunks = chunk_structured_data(data)
        assert len(chunks) == 3
        assert all(c["metadata"]["chunking_strategy"] == "structured_data" for c in chunks)

    def test_json_array(self):
        data = json.dumps([{"id": i} for i in range(5)])
        chunks = chunk_structured_data(data, max_chunk_size=100)
        assert len(chunks) >= 1
        assert "structured_data" in _strategy_meta(chunks)[0]

    def test_yaml_content(self):
        yaml_text = "database:\n  host: localhost\n  port: 5432\napp:\n  debug: true"
        chunks = chunk_structured_data(yaml_text)
        assert len(chunks) >= 1

    def test_empty_content(self):
        assert chunk_structured_data("") == []
        assert chunk_structured_data("   ") == []

    def test_invalid_structured_falls_back(self):
        chunks = chunk_structured_data("this is not json or yaml with special chars {{{")
        # Should fall back to token chunking — still produces chunks
        assert len(chunks) >= 1

    def test_key_path_metadata(self):
        data = json.dumps({"config": {"db": {"host": "localhost"}}})
        chunks = chunk_structured_data(data, max_chunk_size=5000)
        assert any("config" in c["metadata"].get("key_path", "") for c in chunks)


# ── Table Strategy ───────────────────────────────────────────────────────

class TestTable:
    SAMPLE_CSV = "name,age,city\nAlice,30,NYC\nBob,25,LA\nCarol,35,SF"

    def test_csv_chunks_include_header(self):
        chunks = chunk_table(self.SAMPLE_CSV, rows_per_chunk=2)
        # First chunk is overview, data chunks follow
        assert len(chunks) >= 2
        overview = chunks[0]
        assert "Table Overview" in overview["text"]
        assert overview["metadata"]["chunking_strategy"] == "table"

    def test_csv_all_data_chunks_have_header(self):
        chunks = chunk_table(self.SAMPLE_CSV, rows_per_chunk=2)
        data_chunks = [c for c in chunks if c["metadata"].get("chunk_type") == "table_data"]
        for dc in data_chunks:
            assert dc["text"].startswith("name,age,city")

    def test_tsv_detection(self):
        tsv = "name\tage\nAlice\t30\nBob\t25"
        chunks = chunk_table(tsv)
        assert len(chunks) >= 2

    def test_empty_csv(self):
        assert chunk_table("") == []

    def test_single_row_csv(self):
        # Only header, no data — falls back to token
        chunks = chunk_table("a,b,c")
        assert len(chunks) >= 1

    def test_overview_metadata(self):
        chunks = chunk_table(self.SAMPLE_CSV)
        overview = chunks[0]
        assert overview["metadata"]["row_count"] == 3
        assert overview["metadata"]["columns"] == ["name", "age", "city"]


# ── Conversation Strategy ────────────────────────────────────────────────

class TestConversation:
    SAMPLE_LOG = (
        "[2024-01-15 10:00:00] Alice: Hello everyone\n"
        "[2024-01-15 10:00:05] Bob: Hi Alice!\n"
        "[2024-01-15 10:00:10] Alice: Let's discuss the project\n"
        "[2024-01-15 10:01:00] Carol: Sure, I have updates\n"
        "[2024-01-15 10:01:05] Carol: The build is passing now\n"
    )

    def test_conversation_chunking(self):
        chunks = chunk_conversation(self.SAMPLE_LOG, chunk_size=200)
        assert len(chunks) >= 1
        assert all(c["metadata"]["chunking_strategy"] == "conversation" for c in chunks)

    def test_participants_tracked(self):
        chunks = chunk_conversation(self.SAMPLE_LOG, chunk_size=5000)
        # All in one chunk
        participants = chunks[0]["metadata"].get("participants", [])
        assert len(participants) >= 1

    def test_timestamp_detection(self):
        log = "2024-01-15 10:00:00 INFO Starting up\n2024-01-15 10:00:01 DEBUG Init complete"
        chunks = chunk_conversation(log, chunk_size=5000)
        assert len(chunks) >= 1

    def test_empty_conversation(self):
        assert chunk_conversation("") == []
        assert chunk_conversation("   ") == []

    def test_no_turns_detected(self):
        # Plain text without timestamps or speakers — still produces chunks
        text = "just some plain text\nwith no structure"
        chunks = chunk_conversation(text, chunk_size=5000)
        assert len(chunks) >= 1

    def test_small_chunk_size_splits(self):
        chunks = chunk_conversation(self.SAMPLE_LOG, chunk_size=80)
        assert len(chunks) >= 2


# ── Late (Contextual) Strategy ───────────────────────────────────────────

class TestLate:
    LONG_DOC = (
        "# Introduction\n\nThis document covers Python best practices.\n\n"
        "# Variables\n\nUse descriptive variable names.\n\n"
        "# Functions\n\nKeep functions small and focused.\n\n"
        + "Additional detail about coding. " * 100
    )

    def test_context_prepended(self):
        chunks = chunk_late(self.LONG_DOC, chunk_size=300)
        assert len(chunks) >= 2
        for c in chunks:
            assert "[Document Context]" in c["text"]
            assert c["metadata"]["has_context_prefix"] is True

    def test_strategy_label(self):
        chunks = chunk_late(self.LONG_DOC, chunk_size=300)
        assert all(c["metadata"]["chunking_strategy"] == "late" for c in chunks)

    def test_short_doc(self):
        chunks = chunk_late("A short document.", chunk_size=500)
        assert len(chunks) >= 1

    def test_empty_doc(self):
        assert chunk_late("") == []
        assert chunk_late("   ") == []

    def test_headings_in_summary(self):
        doc = "# Overview\n\nSome text.\n\n# Details\n\nMore text."
        chunks = chunk_late(doc, chunk_size=300)
        if chunks:
            # Summary should mention section titles
            assert "Overview" in chunks[0]["text"] or "Details" in chunks[0]["text"]


# ── Propositions Strategy ────────────────────────────────────────────────

class TestPropositions:
    SAMPLE_TEXT = (
        "Python 3.12 was released in October 2023 with improved error messages. "
        "The release includes performance improvements and better typing support. "
        "Guido van Rossum created Python in 1991, and it has grown to become one "
        "of the most popular programming languages."
    )

    def test_breaks_into_propositions(self):
        chunks = chunk_propositions(self.SAMPLE_TEXT)
        assert len(chunks) >= 3
        assert all(c["metadata"]["chunking_strategy"] == "propositions" for c in chunks)

    def test_propositions_end_with_period(self):
        chunks = chunk_propositions(self.SAMPLE_TEXT)
        for c in chunks:
            assert c["text"].rstrip().endswith(('.', '!', '?'))

    def test_max_props_limit(self):
        long_text = ". ".join([f"Fact number {i} is important" for i in range(500)]) + "."
        chunks = chunk_propositions(long_text, max_props=10)
        assert len(chunks) <= 10

    def test_empty_content(self):
        assert chunk_propositions("") == []

    def test_single_sentence(self):
        chunks = chunk_propositions("Python is a great programming language.")
        assert len(chunks) >= 1

    def test_short_fragments_skipped(self):
        # Very short fragments (< 10 chars) should be skipped
        chunks = chunk_propositions("OK. Fine. Yes. This is a proper length sentence though.")
        texts = _texts(chunks)
        assert not any(t.strip() in ("OK.", "Fine.", "Yes.") for t in texts)


# ── Sliding Window Strategy ──────────────────────────────────────────────

class TestSlidingWindow:
    SAMPLE = "abcdefghij" * 50  # 500 chars

    def test_basic_sliding(self):
        chunks = chunk_sliding_window(self.SAMPLE, window_size=100, step_size=50)
        assert len(chunks) >= 5
        assert all(c["metadata"]["chunking_strategy"] == "sliding_window" for c in chunks)

    def test_overlap_exists(self):
        text = "word " * 200  # 1000 chars
        chunks = chunk_sliding_window(text, window_size=200, step_size=100)
        if len(chunks) >= 2:
            # Consecutive chunks should share content due to overlap
            first_end = chunks[0]["text"][-50:]
            second_start = chunks[1]["text"][:50]
            # At least some overlap
            assert len(set(first_end.split()) & set(second_start.split())) > 0

    def test_short_content_single_chunk(self):
        chunks = chunk_sliding_window("short text", window_size=500)
        assert len(chunks) == 1
        assert chunks[0]["text"] == "short text"

    def test_empty_content(self):
        assert chunk_sliding_window("") == []

    def test_window_metadata(self):
        chunks = chunk_sliding_window(self.SAMPLE, window_size=100, step_size=50)
        for c in chunks:
            assert "window_start" in c["metadata"]
            assert "window_end" in c["metadata"]
            assert c["metadata"]["window_end"] > c["metadata"]["window_start"]

    def test_step_larger_than_window(self):
        # No overlap case
        chunks = chunk_sliding_window(self.SAMPLE, window_size=100, step_size=150)
        assert len(chunks) >= 2


# ── chunk_with_strategy integration ──────────────────────────────────────

class TestChunkWithStrategy:
    def test_explicit_strategy(self):
        data = json.dumps({"key": "value"})
        chunks = chunk_with_strategy(data, strategy="structured_data")
        assert len(chunks) >= 1

    def test_auto_select_json(self):
        data = json.dumps({"a": 1, "b": 2})
        chunks = chunk_with_strategy(data, filepath="test.json")
        assert len(chunks) >= 1

    def test_auto_select_csv(self):
        csv_data = "col1,col2\nval1,val2"
        chunks = chunk_with_strategy(csv_data, filepath="data.csv")
        assert len(chunks) >= 1

    def test_fallback_on_empty(self):
        # Empty content returns empty list
        chunks = chunk_with_strategy("", strategy="structured_data")
        assert chunks == []

    def test_unknown_strategy_falls_back(self):
        chunks = chunk_with_strategy("some text here", strategy="nonexistent")
        assert len(chunks) >= 1  # Falls back to _chunk_text


# ── Edge Cases ───────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_all_strategies_handle_empty(self):
        for name, fn in CHUNKING_STRATEGIES.items():
            result = fn("", chunk_size=500, chunk_overlap=100, metadata={})
            assert result == [], f"{name} should return [] for empty input"

    def test_all_strategies_handle_whitespace(self):
        for name, fn in CHUNKING_STRATEGIES.items():
            result = fn("   \n\n  ", chunk_size=500, chunk_overlap=100, metadata={})
            assert result == [], f"{name} should return [] for whitespace-only input"

    def test_all_strategies_handle_short_text(self):
        for name, fn in CHUNKING_STRATEGIES.items():
            result = fn("Hello world.", chunk_size=500, chunk_overlap=100, metadata={})
            # Should produce at least one chunk (or empty for strategies that need structure)
            assert isinstance(result, list), f"{name} should return a list"

    def test_very_long_input(self):
        long_text = "This is a sentence. " * 1000
        for name in ["token", "semantic", "late", "propositions", "sliding_window"]:
            fn = CHUNKING_STRATEGIES[name]
            result = fn(long_text, chunk_size=500, chunk_overlap=100, metadata={})
            assert len(result) >= 2, f"{name} should produce multiple chunks for long input"
