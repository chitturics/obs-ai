"""Tests for chat_app.execution_journal — JSONL persistence."""

import asyncio
import json
import os
import tempfile
import time

import pytest

from chat_app.execution_journal import JournalWriter
from chat_app.schemas import (
    AgentDispatchEvent,
    OrchestrationEvent,
    SkillExecutionEvent,
)


@pytest.fixture
def tmp_journal_dir():
    with tempfile.TemporaryDirectory() as d:
        yield d


@pytest.fixture
def journal(tmp_journal_dir):
    return JournalWriter(
        base_dir=tmp_journal_dir,
        flush_interval=0.1,  # fast for tests
        retention_days=30,
    )


class TestJournalWriter:
    def test_log_dict(self, journal):
        """Can log plain dicts."""
        result = journal.log({"event_type": "test", "data": "hello"})
        assert result is True
        assert journal._queue.qsize() == 1

    def test_log_pydantic(self, journal):
        """Can log Pydantic events."""
        event = SkillExecutionEvent(
            skill_name="analyze_spl",
            handler_key="analyze_spl",
            source="internal",
            success=True,
            duration_ms=10.0,
        )
        result = journal.log(event)
        assert result is True

    def test_log_queue_full(self, tmp_journal_dir):
        """Returns False when queue full."""
        j = JournalWriter(base_dir=tmp_journal_dir, max_queue_size=2)
        j.log({"event_type": "a"})
        j.log({"event_type": "b"})
        result = j.log({"event_type": "c"})
        assert result is False

    @pytest.mark.asyncio
    async def test_flush_writes_files(self, journal, tmp_journal_dir):
        """Flushing writes JSONL files."""
        journal.log(SkillExecutionEvent(
            skill_name="test1", success=True, duration_ms=5.0,
        ))
        journal.log(AgentDispatchEvent(
            agent_name="agent1", department="eng",
        ))
        journal.log(OrchestrationEvent(
            strategy_used="adaptive", intent="spl_help",
        ))

        await journal._flush_all()

        # Check files exist
        files = list(journal.base_dir.glob("*.jsonl"))
        assert len(files) == 3  # 3 event types

        # Check content
        for f in files:
            with open(f) as fh:
                lines = [l.strip() for l in fh if l.strip()]
            assert len(lines) == 1
            data = json.loads(lines[0])
            assert "event_type" in data

    @pytest.mark.asyncio
    async def test_stats(self, journal):
        """Stats reflect events logged."""
        journal.log({"event_type": "test", "x": 1})
        journal.log({"event_type": "test", "x": 2})
        await journal._flush_all()

        stats = journal.get_stats()
        assert stats["total_events"] == 2
        assert stats["event_counts"]["test"] == 2
        assert stats["total_flushes"] == 1

    @pytest.mark.asyncio
    async def test_query_events(self, journal):
        """Query returns events from files."""
        journal.log(SkillExecutionEvent(
            skill_name="test1", success=True,
        ))
        journal.log(SkillExecutionEvent(
            skill_name="test2", success=False, error="fail",
        ))
        await journal._flush_all()

        events = journal.query_events(event_type="skill_execution", limit=10)
        assert len(events) == 2
        # Most recent first
        assert events[0]["skill_name"] == "test2"

    @pytest.mark.asyncio
    async def test_query_all_types(self, journal):
        """Query without event_type returns all events for date."""
        journal.log(SkillExecutionEvent(skill_name="s1"))
        journal.log(AgentDispatchEvent(agent_name="a1"))
        await journal._flush_all()

        events = journal.query_events(limit=50)
        assert len(events) == 2

    def test_list_files_empty(self, journal):
        """List files on empty dir returns empty."""
        files = journal.list_files()
        assert files == []

    @pytest.mark.asyncio
    async def test_list_files_after_write(self, journal):
        """List files shows written files."""
        journal.log({"event_type": "test"})
        await journal._flush_all()

        files = journal.list_files()
        assert len(files) == 1
        assert files[0]["name"].startswith("test_")
        assert files[0]["size_bytes"] > 0

    @pytest.mark.asyncio
    async def test_start_stop(self, journal):
        """Start and stop lifecycle."""
        await journal.start()
        assert journal._running is True

        journal.log({"event_type": "test", "data": 1})
        await asyncio.sleep(0.3)  # Let flush loop run

        await journal.stop()
        assert journal._running is False

        # Event should be flushed
        assert journal._total_events >= 1

    @pytest.mark.asyncio
    async def test_cleanup_old_files(self, journal, tmp_journal_dir):
        """Cleanup removes old files."""
        import datetime
        from pathlib import Path

        # Create an old file
        old_date = (datetime.date.today() - datetime.timedelta(days=60)).isoformat()
        old_file = Path(tmp_journal_dir) / f"test_{old_date}.jsonl"
        old_file.write_text('{"event_type":"test"}\n')

        # Create a recent file
        today = datetime.date.today().isoformat()
        new_file = Path(tmp_journal_dir) / f"test_{today}.jsonl"
        new_file.write_text('{"event_type":"test"}\n')

        removed = await journal.cleanup_old_files()
        assert removed == 1
        assert not old_file.exists()
        assert new_file.exists()


class TestGetJournal:
    def test_singleton(self):
        """get_journal returns a singleton."""
        from chat_app.execution_journal import get_journal, _journal_instance
        j1 = get_journal()
        j2 = get_journal()
        assert j1 is j2
