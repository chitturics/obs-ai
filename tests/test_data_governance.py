"""Tests for data governance — retention policies, PII detection, redaction."""

import pytest


@pytest.fixture
def mgr():
    from chat_app.data_governance import GovernanceManager
    return GovernanceManager()


class TestRetentionPolicies:

    def test_audit_log_policy(self, mgr):
        policy = mgr.get_retention_policy("audit_log")
        assert policy is not None
        assert policy.retention_days == 365
        assert policy.auto_cleanup is False
        assert policy.contains_pii is True

    def test_session_cache_policy(self, mgr):
        policy = mgr.get_retention_policy("session_cache")
        assert policy is not None
        assert policy.retention_days == 1
        assert policy.auto_cleanup is True

    def test_vector_collections_no_expiry(self, mgr):
        policy = mgr.get_retention_policy("vector_collections")
        assert policy.retention_days == 0  # No auto-expiry

    def test_all_policies_populated(self, mgr):
        policies = mgr.get_all_policies()
        assert len(policies) >= 9

    def test_pii_sources(self, mgr):
        pii_sources = mgr.get_pii_sources()
        assert len(pii_sources) >= 5
        source_names = [p.source for p in pii_sources]
        assert "audit_log" in source_names
        assert "chat_history" in source_names

    def test_custom_policy(self, mgr):
        from chat_app.data_governance import RetentionPolicy
        custom = RetentionPolicy(
            source="custom_data",
            description="Custom data source",
            retention_days=60,
            storage_type="database",
        )
        mgr.set_retention_policy(custom)
        result = mgr.get_retention_policy("custom_data")
        assert result.retention_days == 60


class TestPIIDetection:

    def test_detect_email(self, mgr):
        findings = mgr.scan_for_pii("Contact john@example.com for details")
        assert len(findings) >= 1
        assert any(f.pii_type == "email" for f in findings)

    def test_detect_phone(self, mgr):
        findings = mgr.scan_for_pii("Call us at 555-123-4567")
        assert len(findings) >= 1
        assert any(f.pii_type == "phone" for f in findings)

    def test_detect_ssn(self, mgr):
        findings = mgr.scan_for_pii("SSN: 123-45-6789")
        assert len(findings) >= 1
        assert any(f.pii_type == "ssn" for f in findings)

    def test_detect_credit_card(self, mgr):
        findings = mgr.scan_for_pii("Card: 4111-1111-1111-1111")
        assert len(findings) >= 1
        assert any(f.pii_type == "credit_card" for f in findings)

    def test_detect_ip(self, mgr):
        findings = mgr.scan_for_pii("Server at 192.168.1.100")
        assert len(findings) >= 1
        assert any(f.pii_type == "ip_address" for f in findings)

    def test_detect_api_key(self, mgr):
        findings = mgr.scan_for_pii("Key: obsai_abc123def456ghi789jkl012mno345")
        assert len(findings) >= 1
        assert any(f.pii_type == "api_key" for f in findings)

    def test_detect_password(self, mgr):
        findings = mgr.scan_for_pii("password: mysecret123")
        assert len(findings) >= 1
        assert any(f.pii_type == "password" for f in findings)

    def test_no_pii(self, mgr):
        findings = mgr.scan_for_pii("This is a clean text with no sensitive data")
        assert len(findings) == 0

    def test_filter_by_type(self, mgr):
        text = "Email: john@example.com, Phone: 555-123-4567"
        findings = mgr.scan_for_pii(text, pii_types={"email"})
        assert all(f.pii_type == "email" for f in findings)

    def test_has_pii_quick_check(self, mgr):
        assert mgr.has_pii("john@example.com") is True
        assert mgr.has_pii("no pii here") is False


class TestPIIRedaction:

    def test_redact_email(self, mgr):
        result = mgr.redact_pii("Contact john@example.com")
        assert "john@example.com" not in result
        assert "[REDACTED_EMAIL]" in result

    def test_redact_phone(self, mgr):
        result = mgr.redact_pii("Call 555-123-4567", redact_types={"phone"})
        assert "555-123-4567" not in result
        assert "[REDACTED_PHONE]" in result

    def test_redact_multiple_types(self, mgr):
        text = "Email: john@example.com, SSN: 123-45-6789"
        result = mgr.redact_pii(text)
        assert "john@example.com" not in result
        assert "123-45-6789" not in result

    def test_redact_preserves_clean_text(self, mgr):
        text = "Hello, this is a normal message"
        result = mgr.redact_pii(text)
        assert result == text

    def test_selective_redaction(self, mgr):
        text = "Email: john@example.com, Phone: 555-123-4567"
        result = mgr.redact_pii(text, redact_types={"email"})
        assert "[REDACTED_EMAIL]" in result
        # Phone should NOT be redacted
        assert "555-123-4567" in result


class TestPIIFinding:

    def test_finding_masking(self, mgr):
        findings = mgr.scan_for_pii("john@example.com")
        assert findings[0].to_dict()["value"] == "john..."  # Masked in dict output

    def test_finding_has_position(self, mgr):
        findings = mgr.scan_for_pii("Contact john@example.com")
        assert findings[0].start > 0
        assert findings[0].end > findings[0].start


class TestComplianceReport:

    def test_report_structure(self, mgr):
        report = mgr.get_compliance_report()
        assert "total_sources" in report
        assert "pii_sources" in report
        assert "auto_cleanup_sources" in report
        assert "policies" in report
        assert "pii_types_detected" in report
        assert report["total_sources"] >= 9

    def test_report_pii_types(self, mgr):
        report = mgr.get_compliance_report()
        assert "email" in report["pii_types_detected"]
        assert "ssn" in report["pii_types_detected"]
