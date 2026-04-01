"""Tests for secrets management — registration, rotation, plaintext detection."""

import os
import pytest


@pytest.fixture
def mgr():
    from chat_app.secrets_manager import SecretsManager
    return SecretsManager()


class TestSecretRegistration:

    def test_default_secrets_registered(self, mgr):
        secrets = mgr.get_all_secrets()
        assert len(secrets) >= 8
        names = [s.name for s in secrets]
        assert "database_password" in names
        assert "splunk_hec_token" in names
        assert "service_api_key" in names

    def test_register_custom_secret(self, mgr):
        entry = mgr.register_secret(
            name="custom_key",
            description="My custom API key",
            source="env:CUSTOM_KEY",
            rotation_days=30,
            used_by=["my_service"],
        )
        assert entry.name == "custom_key"
        assert entry.rotation_days == 30

    def test_get_secret(self, mgr):
        entry = mgr.get_secret("database_password")
        assert entry is not None
        assert entry.source == "env:DATABASE_PASSWORD"

    def test_get_nonexistent(self, mgr):
        assert mgr.get_secret("nonexistent") is None


class TestRotation:

    def test_mark_rotated(self, mgr):
        entry = mgr.mark_rotated("database_password")
        assert entry is not None
        assert entry.last_rotated is not None

    def test_rotation_overdue(self, mgr):
        from datetime import datetime, timezone, timedelta
        entry = mgr.get_secret("database_password")
        # Set last rotated to 100 days ago (overdue for 90-day policy)
        entry.last_rotated = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
        assert entry.rotation_overdue is True

    def test_rotation_not_overdue(self, mgr):
        mgr.mark_rotated("database_password")
        entry = mgr.get_secret("database_password")
        assert entry.rotation_overdue is False

    def test_days_until_rotation(self, mgr):
        mgr.mark_rotated("database_password")
        entry = mgr.get_secret("database_password")
        days = entry.days_until_rotation
        assert days is not None
        assert 89 <= days <= 90

    def test_rotation_report(self, mgr):
        report = mgr.get_rotation_report()
        assert "total_secrets" in report
        assert report["total_secrets"] >= 8
        assert "never_rotated" in report
        assert len(report["never_rotated"]) >= 7  # None rotated by default


class TestPlaintextDetection:

    def test_detect_plaintext_password(self, tmp_path):
        from chat_app.secrets_manager import SecretsManager
        mgr = SecretsManager()

        # Create a test file with a plaintext secret
        test_file = tmp_path / "config.yaml"
        test_file.write_text("database:\n  password: my_secret_password_123\n  host: localhost\n")

        findings = mgr.scan_for_plaintext(str(test_file))
        assert len(findings) >= 1
        assert any("password" in f.pattern_matched.lower() for f in findings)

    def test_safe_env_var_reference(self, tmp_path):
        from chat_app.secrets_manager import SecretsManager
        mgr = SecretsManager()

        test_file = tmp_path / "config.yaml"
        test_file.write_text("database:\n  password: ${DATABASE_PASSWORD}\n")

        findings = mgr.scan_for_plaintext(str(test_file))
        assert len(findings) == 0  # Env var refs are safe

    def test_detect_api_key(self, tmp_path):
        from chat_app.secrets_manager import SecretsManager
        mgr = SecretsManager()

        test_file = tmp_path / "config.yaml"
        test_file.write_text("splunk:\n  api_key: abcdef1234567890abcdef\n")

        findings = mgr.scan_for_plaintext(str(test_file))
        assert len(findings) >= 1

    def test_clean_file(self, tmp_path):
        from chat_app.secrets_manager import SecretsManager
        mgr = SecretsManager()

        test_file = tmp_path / "config.yaml"
        test_file.write_text("database:\n  host: localhost\n  port: 5432\n")

        findings = mgr.scan_for_plaintext(str(test_file))
        assert len(findings) == 0

    def test_nonexistent_file(self, mgr):
        findings = mgr.scan_for_plaintext("/nonexistent/path/config.yaml")
        assert findings == []

    def test_scan_directory(self, tmp_path):
        from chat_app.secrets_manager import SecretsManager
        mgr = SecretsManager()

        # Create files
        (tmp_path / "clean.yaml").write_text("host: localhost\n")
        (tmp_path / "dirty.yaml").write_text("password: hardcoded_secret_value\n")

        findings = mgr.scan_directory(str(tmp_path))
        assert len(findings) >= 1


class TestSecretSerialization:

    def test_to_dict(self, mgr):
        entry = mgr.get_secret("database_password")
        d = entry.to_dict()
        assert d["name"] == "database_password"
        assert "source" in d
        assert "rotation_days" in d
        assert "is_set" in d

    def test_finding_to_dict(self, tmp_path):
        from chat_app.secrets_manager import SecretsManager
        mgr = SecretsManager()

        test_file = tmp_path / "config.yaml"
        test_file.write_text("api_key: hardcoded_secret_value_here\n")

        findings = mgr.scan_for_plaintext(str(test_file))
        if findings:
            d = findings[0].to_dict()
            assert "file" in d
            assert "line" in d
            assert "pattern" in d
