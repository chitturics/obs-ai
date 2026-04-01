"""Tests for the immutable audit log with hash chaining."""

import json
import os
import tempfile
import time

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_log_dir(tmp_path):
    """Provide a temporary directory for audit log files."""
    return str(tmp_path / "audit")


@pytest.fixture
def audit_log(temp_log_dir):
    """Create a fresh ImmutableAuditLog instance."""
    from chat_app.audit_log import ImmutableAuditLog
    return ImmutableAuditLog(log_dir=temp_log_dir, max_in_memory=100)


# ---------------------------------------------------------------------------
# Hash Chaining Tests
# ---------------------------------------------------------------------------

class TestHashChaining:
    """Verify that hash chaining creates tamper-evident entries."""

    def test_first_entry_chains_to_genesis(self, audit_log):
        """First entry's previous_hash should be the genesis hash."""
        from chat_app.audit_log import _GENESIS_HASH

        entry = audit_log.append(
            event_type="test", actor="tester", action="create",
            target="test_resource",
        )
        assert entry["previous_hash"] == _GENESIS_HASH
        assert entry["hash"] != _GENESIS_HASH
        assert entry["sequence"] == 0

    def test_second_entry_chains_to_first(self, audit_log):
        """Second entry's previous_hash should be the first entry's hash."""
        entry1 = audit_log.append(
            event_type="test", actor="tester", action="create", target="r1",
        )
        entry2 = audit_log.append(
            event_type="test", actor="tester", action="update", target="r2",
        )
        assert entry2["previous_hash"] == entry1["hash"]
        assert entry2["sequence"] == 1

    def test_chain_of_ten(self, audit_log):
        """Verify chain integrity over 10 entries."""
        entries = []
        for i in range(10):
            entry = audit_log.append(
                event_type="test", actor="tester", action="action",
                target=f"resource_{i}", details={"index": i},
            )
            entries.append(entry)

        # Verify sequential chaining
        for i in range(1, 10):
            assert entries[i]["previous_hash"] == entries[i - 1]["hash"]

        # Verify chain via verify_chain()
        result = audit_log.verify_chain()
        assert result["valid"] is True
        assert result["entries_checked"] == 10

    def test_hash_deterministic(self, audit_log):
        """Same data should produce the same hash."""
        from chat_app.audit_log import _compute_hash

        data = {
            "timestamp": "2026-03-23T00:00:00+00:00",
            "event_type": "test",
            "actor": "tester",
            "action": "create",
            "target": "resource",
            "details": {"key": "value"},
            "severity": "low",
        }
        hash1 = _compute_hash(data, "0" * 64)
        hash2 = _compute_hash(data, "0" * 64)
        assert hash1 == hash2

    def test_different_data_different_hash(self, audit_log):
        """Different data should produce different hashes."""
        from chat_app.audit_log import _compute_hash

        data1 = {
            "timestamp": "2026-03-23T00:00:00+00:00",
            "event_type": "test", "actor": "tester",
            "action": "create", "target": "r1",
            "details": {}, "severity": "low",
        }
        data2 = dict(data1, target="r2")
        hash1 = _compute_hash(data1, "0" * 64)
        hash2 = _compute_hash(data2, "0" * 64)
        assert hash1 != hash2


# ---------------------------------------------------------------------------
# Persistence Tests
# ---------------------------------------------------------------------------

class TestPersistence:
    """Verify file-based persistence and recovery."""

    def test_entries_persisted_to_file(self, audit_log, temp_log_dir):
        """Entries should be written to the JSONL file."""
        audit_log.append(event_type="test", actor="tester", action="create", target="r1")
        audit_log.append(event_type="test", actor="tester", action="update", target="r2")

        log_file = os.path.join(temp_log_dir, "audit_log.jsonl")
        assert os.path.exists(log_file)

        with open(log_file) as fh:
            lines = [l for l in fh.readlines() if l.strip()]
        assert len(lines) == 2

        entry = json.loads(lines[0])
        assert entry["event_type"] == "test"
        assert "hash" in entry
        assert "previous_hash" in entry

    def test_reload_from_file(self, temp_log_dir):
        """A new instance should load and verify existing entries."""
        from chat_app.audit_log import ImmutableAuditLog

        # Write entries
        log1 = ImmutableAuditLog(log_dir=temp_log_dir)
        log1.append(event_type="test", actor="a", action="create", target="r1")
        log1.append(event_type="test", actor="b", action="update", target="r2")
        log1.append(event_type="test", actor="c", action="delete", target="r3")

        # Reload
        log2 = ImmutableAuditLog(log_dir=temp_log_dir)
        assert log2._chain_valid is True
        assert log2._entry_count == 3

        # New entries should chain correctly
        entry4 = log2.append(event_type="test", actor="d", action="create", target="r4")
        assert entry4["sequence"] == 3

        result = log2.verify_chain()
        assert result["valid"] is True
        assert result["entries_checked"] == 4

    def test_tamper_detection(self, temp_log_dir):
        """Tampering with the file should be detected on reload."""
        from chat_app.audit_log import ImmutableAuditLog

        log1 = ImmutableAuditLog(log_dir=temp_log_dir)
        log1.append(event_type="test", actor="a", action="create", target="r1")
        log1.append(event_type="test", actor="b", action="update", target="r2")

        # Tamper with the file
        log_file = os.path.join(temp_log_dir, "audit_log.jsonl")
        with open(log_file, "r") as fh:
            lines = fh.readlines()

        # Modify the first entry's actor
        entry = json.loads(lines[0])
        entry["actor"] = "tampered"
        lines[0] = json.dumps(entry) + "\n"
        with open(log_file, "w") as fh:
            fh.writelines(lines)

        # Reload should detect tampering
        log2 = ImmutableAuditLog(log_dir=temp_log_dir)
        assert log2._chain_valid is False


# ---------------------------------------------------------------------------
# Query Tests
# ---------------------------------------------------------------------------

class TestQuery:
    """Verify filtering and querying."""

    def test_query_by_event_type(self, audit_log):
        audit_log.append(event_type="auth", actor="a", action="login", target="system")
        audit_log.append(event_type="config", actor="b", action="update", target="llm")
        audit_log.append(event_type="auth", actor="c", action="logout", target="system")

        results = audit_log.query(event_type="auth")
        assert len(results) == 2
        assert all(e["event_type"] == "auth" for e in results)

    def test_query_by_actor(self, audit_log):
        audit_log.append(event_type="test", actor="Alice", action="create", target="r1")
        audit_log.append(event_type="test", actor="Bob", action="create", target="r2")
        audit_log.append(event_type="test", actor="alice_admin", action="create", target="r3")

        results = audit_log.query(actor="alice")
        assert len(results) == 2  # Case-insensitive substring

    def test_query_by_severity(self, audit_log):
        audit_log.append(event_type="test", actor="a", action="read", target="r1", severity="low")
        audit_log.append(event_type="test", actor="a", action="delete", target="r2", severity="critical")
        audit_log.append(event_type="test", actor="a", action="update", target="r3", severity="medium")

        results = audit_log.query(severity="critical")
        assert len(results) == 1
        assert results[0]["severity"] == "critical"

    def test_query_limit_and_offset(self, audit_log):
        for i in range(20):
            audit_log.append(event_type="test", actor="a", action="create", target=f"r{i}")

        page1 = audit_log.query(limit=5, offset=0)
        page2 = audit_log.query(limit=5, offset=5)
        assert len(page1) == 5
        assert len(page2) == 5
        assert page1[0]["target"] != page2[0]["target"]

    def test_query_most_recent_first(self, audit_log):
        audit_log.append(event_type="test", actor="a", action="create", target="first")
        audit_log.append(event_type="test", actor="a", action="create", target="second")
        audit_log.append(event_type="test", actor="a", action="create", target="third")

        results = audit_log.query()
        assert results[0]["target"] == "third"
        assert results[-1]["target"] == "first"


# ---------------------------------------------------------------------------
# Export Tests
# ---------------------------------------------------------------------------

class TestExport:
    """Verify export formats."""

    def test_export_json(self, audit_log):
        audit_log.append(event_type="test", actor="a", action="create", target="r1")
        data = audit_log.export(format="json")
        assert isinstance(data, list)
        assert len(data) == 1

    def test_export_csv(self, audit_log):
        audit_log.append(event_type="test", actor="a", action="create", target="r1")
        audit_log.append(event_type="test", actor="b", action="update", target="r2")
        csv_str = audit_log.export(format="csv")
        assert isinstance(csv_str, str)
        lines = csv_str.strip().split("\n")
        assert len(lines) == 3  # header + 2 rows
        assert "timestamp" in lines[0]

    def test_export_splunk(self, audit_log):
        audit_log.append(event_type="test", actor="a", action="create", target="r1")
        hec_events = audit_log.export(format="splunk")
        assert isinstance(hec_events, list)
        assert len(hec_events) == 1
        assert hec_events[0]["sourcetype"] == "obsai:audit"
        assert "event" in hec_events[0]


# ---------------------------------------------------------------------------
# Stats Tests
# ---------------------------------------------------------------------------

class TestStats:
    """Verify statistics computation."""

    def test_stats_empty(self, audit_log):
        stats = audit_log.get_stats()
        assert stats["total_entries"] == 0
        assert stats["chain_valid"] is True

    def test_stats_populated(self, audit_log):
        audit_log.append(event_type="auth", actor="a", action="login", target="sys", severity="low")
        audit_log.append(event_type="config", actor="b", action="update", target="llm", severity="medium")
        audit_log.append(event_type="auth", actor="a", action="logout", target="sys", severity="low")

        stats = audit_log.get_stats()
        assert stats["total_entries"] == 3
        assert stats["by_type"]["auth"] == 2
        assert stats["by_type"]["config"] == 1
        assert stats["by_severity"]["low"] == 2
        assert stats["by_severity"]["medium"] == 1


# ---------------------------------------------------------------------------
# Verify Chain Tests
# ---------------------------------------------------------------------------

class TestVerifyChain:
    """Verify chain validation functionality."""

    def test_verify_empty_chain(self, audit_log):
        result = audit_log.verify_chain()
        assert result["valid"] is True
        assert result["entries_checked"] == 0

    def test_verify_valid_chain(self, audit_log):
        for i in range(5):
            audit_log.append(event_type="test", actor="a", action="create", target=f"r{i}")
        result = audit_log.verify_chain()
        assert result["valid"] is True
        assert result["entries_checked"] == 5

    def test_verify_full_from_file(self, temp_log_dir):
        from chat_app.audit_log import ImmutableAuditLog

        log = ImmutableAuditLog(log_dir=temp_log_dir)
        for i in range(5):
            log.append(event_type="test", actor="a", action="create", target=f"r{i}")

        result = log.verify_chain(full=True)
        assert result["valid"] is True
        assert result["entries_checked"] == 5
