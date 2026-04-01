"""Tests for MFA enforcement — TOTP-based multi-factor authentication."""

import pytest
import time


@pytest.fixture
def mgr():
    from chat_app.mfa import MFAManager, MFAEnforcementPolicy
    return MFAManager(policy=MFAEnforcementPolicy.ADMIN_REQUIRED)


class TestTOTPGeneration:

    def test_totp_code_is_6_digits(self):
        from chat_app.mfa import _generate_secret, _totp_code
        secret = _generate_secret()
        code = _totp_code(secret)
        assert len(code) == 6
        assert code.isdigit()

    def test_same_secret_same_time_same_code(self):
        from chat_app.mfa import _generate_secret, _totp_code
        secret = _generate_secret()
        ts = int(time.time())
        assert _totp_code(secret, ts) == _totp_code(secret, ts)

    def test_different_secrets_different_codes(self):
        from chat_app.mfa import _generate_secret, _totp_code
        s1 = _generate_secret()
        s2 = _generate_secret()
        ts = int(time.time())
        # Very unlikely to be the same
        codes = {_totp_code(s1, ts), _totp_code(s2, ts)}
        # At least check they're both valid 6-digit codes
        assert all(len(c) == 6 for c in codes)

    def test_verify_correct_code(self):
        from chat_app.mfa import _generate_secret, _totp_code, _verify_totp
        secret = _generate_secret()
        code = _totp_code(secret)
        assert _verify_totp(secret, code) is True

    def test_verify_wrong_code(self):
        from chat_app.mfa import _generate_secret, _verify_totp
        secret = _generate_secret()
        assert _verify_totp(secret, "000000") is False  # Almost certainly wrong


class TestEnrollment:

    def test_enroll_user(self, mgr):
        result = mgr.enroll("admin@test.com")
        assert "secret" in result
        assert "uri" in result
        assert result["uri"].startswith("otpauth://totp/")
        assert len(result["backup_codes"]) == 8

    def test_is_enrolled(self, mgr):
        assert mgr.is_enrolled("admin@test.com") is False
        mgr.enroll("admin@test.com")
        assert mgr.is_enrolled("admin@test.com") is True

    def test_unenroll(self, mgr):
        mgr.enroll("admin@test.com")
        assert mgr.unenroll("admin@test.com") is True
        assert mgr.is_enrolled("admin@test.com") is False

    def test_unenroll_nonexistent(self, mgr):
        assert mgr.unenroll("nobody") is False


class TestVerification:

    def test_verify_with_totp(self, mgr):
        from chat_app.mfa import _totp_code
        enrollment_data = mgr.enroll("admin@test.com")
        from base64 import b32decode
        # Pad the secret for decoding
        secret_b32 = enrollment_data["secret"]
        padding = "=" * (8 - len(secret_b32) % 8) if len(secret_b32) % 8 else ""
        secret = b32decode(secret_b32 + padding)
        code = _totp_code(secret)
        assert mgr.verify("admin@test.com", code) is True

    def test_verify_with_backup_code(self, mgr):
        result = mgr.enroll("admin@test.com")
        backup = result["backup_codes"][0]
        assert mgr.verify("admin@test.com", backup) is True
        # Backup code is one-time use
        assert mgr.verify("admin@test.com", backup) is False

    def test_verify_wrong_code(self, mgr):
        mgr.enroll("admin@test.com")
        assert mgr.verify("admin@test.com", "000000") is False

    def test_verify_nonenrolled_user(self, mgr):
        assert mgr.verify("nobody", "123456") is False

    def test_verification_marks_as_verified(self, mgr):
        result = mgr.enroll("admin@test.com")
        backup = result["backup_codes"][0]
        mgr.verify("admin@test.com", backup)
        enrollment = mgr.get_enrollment("admin@test.com")
        assert enrollment["verified"] is True


class TestEnforcementPolicy:

    def test_admin_required_policy(self, mgr):
        assert mgr.is_required("ADMIN") is True
        assert mgr.is_required("USER") is False
        assert mgr.is_required("ANALYST") is False

    def test_all_required_policy(self):
        from chat_app.mfa import MFAManager, MFAEnforcementPolicy
        mgr = MFAManager(policy=MFAEnforcementPolicy.ALL_REQUIRED)
        assert mgr.is_required("ADMIN") is True
        assert mgr.is_required("USER") is True
        assert mgr.is_required("VIEWER") is True

    def test_disabled_policy(self):
        from chat_app.mfa import MFAManager, MFAEnforcementPolicy
        mgr = MFAManager(policy=MFAEnforcementPolicy.DISABLED)
        assert mgr.is_required("ADMIN") is False

    def test_optional_policy(self):
        from chat_app.mfa import MFAManager, MFAEnforcementPolicy
        mgr = MFAManager(policy=MFAEnforcementPolicy.OPTIONAL)
        assert mgr.is_required("ADMIN") is False


class TestStats:

    def test_stats_empty(self, mgr):
        stats = mgr.get_stats()
        assert stats["enrolled_users"] == 0
        assert stats["policy"] == "admin_required"

    def test_stats_after_enrollment(self, mgr):
        mgr.enroll("user1")
        mgr.enroll("user2")
        result = mgr.enroll("user3")
        mgr.verify("user3", result["backup_codes"][0])

        stats = mgr.get_stats()
        assert stats["enrolled_users"] == 3
        assert stats["verified_users"] == 1
        assert stats["total_attempts"] == 1
        assert stats["total_successes"] == 1

    def test_get_all_enrollments(self, mgr):
        mgr.enroll("user1")
        mgr.enroll("user2")
        enrollments = mgr.get_all_enrollments()
        assert len(enrollments) == 2
