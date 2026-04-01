"""MFA Enforcement — TOTP-based multi-factor authentication for admin role.

Provides:
- TOTP secret generation and QR code URI
- TOTP code verification (RFC 6238)
- Per-user MFA enrollment and enforcement
- Configurable enforcement policy (admin-only, all users, optional)

The TOTP implementation uses HMAC-SHA1 with 30-second time steps and 6-digit codes,
compatible with Google Authenticator, Authy, and other standard TOTP apps.

Usage:
    from chat_app.mfa import get_mfa_manager

    mgr = get_mfa_manager()
    enrollment = mgr.enroll("admin@example.com")  # Returns secret + QR URI
    valid = mgr.verify("admin@example.com", "123456")  # Verify TOTP code
"""

import hashlib
import hmac
import logging
import os
import struct
import threading
import time
from base64 import b32encode
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# TOTP implementation (RFC 6238)
# ---------------------------------------------------------------------------

_TOTP_DIGITS = 6
_TOTP_PERIOD = 30  # seconds
_TOTP_WINDOW = 1   # Allow +/- 1 period for clock drift


def _generate_secret(length: int = 20) -> bytes:
    """Generate a random TOTP secret."""
    return os.urandom(length)


def _totp_code(secret: bytes, timestamp: Optional[int] = None) -> str:
    """Generate a TOTP code for the given secret and time."""
    if timestamp is None:
        timestamp = int(time.time())
    counter = timestamp // _TOTP_PERIOD
    msg = struct.pack(">Q", counter)
    h = hmac.new(secret, msg, hashlib.sha1).digest()
    offset = h[-1] & 0x0F
    truncated = struct.unpack(">I", h[offset:offset + 4])[0] & 0x7FFFFFFF
    code = truncated % (10 ** _TOTP_DIGITS)
    return str(code).zfill(_TOTP_DIGITS)


def _verify_totp(secret: bytes, code: str, window: int = _TOTP_WINDOW) -> bool:
    """Verify a TOTP code with clock drift tolerance."""
    now = int(time.time())
    for offset in range(-window, window + 1):
        expected = _totp_code(secret, now + offset * _TOTP_PERIOD)
        if hmac.compare_digest(expected, code):
            return True
    return False


def _totp_uri(secret: bytes, username: str, issuer: str = "ObsAI") -> str:
    """Generate an otpauth:// URI for QR code generation."""
    b32_secret = b32encode(secret).decode("ascii").rstrip("=")
    return f"otpauth://totp/{quote(issuer)}:{quote(username)}?secret={b32_secret}&issuer={quote(issuer)}&digits={_TOTP_DIGITS}&period={_TOTP_PERIOD}"


# ---------------------------------------------------------------------------
# MFA enrollment
# ---------------------------------------------------------------------------

class MFAEnforcementPolicy:
    DISABLED = "disabled"      # MFA not available
    OPTIONAL = "optional"      # Users can opt in
    ADMIN_REQUIRED = "admin_required"  # Required for ADMIN role
    ALL_REQUIRED = "all_required"      # Required for all users


@dataclass
class MFAEnrollment:
    """MFA enrollment record for a user."""
    username: str
    secret: bytes
    enrolled_at: str
    verified: bool = False  # Set True after first successful verification
    last_used: Optional[str] = None
    backup_codes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "username": self.username,
            "enrolled": True,
            "verified": self.verified,
            "enrolled_at": self.enrolled_at,
            "last_used": self.last_used,
            "backup_codes_remaining": len(self.backup_codes),
        }


# ---------------------------------------------------------------------------
# MFA Manager
# ---------------------------------------------------------------------------

class MFAManager:
    """Manages MFA enrollment, verification, and enforcement."""

    def __init__(self, policy: str = MFAEnforcementPolicy.ADMIN_REQUIRED):
        self._enrollments: Dict[str, MFAEnrollment] = {}
        self._lock = threading.Lock()
        self._policy = policy
        self._verification_attempts = 0
        self._verification_successes = 0

    @property
    def policy(self) -> str:
        return self._policy

    @policy.setter
    def policy(self, value: str) -> None:
        self._policy = value

    def enroll(self, username: str) -> Dict[str, Any]:
        """Generate a TOTP secret and enrollment URI for a user.

        Returns dict with secret (base32), QR URI, and backup codes.
        """
        secret = _generate_secret()
        b32_secret = b32encode(secret).decode("ascii").rstrip("=")
        uri = _totp_uri(secret, username)

        # Generate backup codes (one-time use)
        backup_codes = [os.urandom(4).hex() for _ in range(8)]

        enrollment = MFAEnrollment(
            username=username,
            secret=secret,
            enrolled_at=datetime.now(timezone.utc).isoformat(),
            backup_codes=backup_codes,
        )

        with self._lock:
            self._enrollments[username] = enrollment

        logger.info("[MFA] User enrolled: %s", username)
        return {
            "username": username,
            "secret": b32_secret,
            "uri": uri,
            "backup_codes": backup_codes,
            "message": "Scan the QR code with your authenticator app, then verify with a code.",
        }

    def verify(self, username: str, code: str) -> bool:
        """Verify a TOTP code for a user.

        Also accepts backup codes (one-time use).
        """
        self._verification_attempts += 1
        enrollment = self._enrollments.get(username)
        if not enrollment:
            return False

        # Check backup codes first
        if code in enrollment.backup_codes:
            enrollment.backup_codes.remove(code)
            enrollment.verified = True
            enrollment.last_used = datetime.now(timezone.utc).isoformat()
            self._verification_successes += 1
            logger.info("[MFA] Backup code used by %s (%d remaining)", username, len(enrollment.backup_codes))
            return True

        # Check TOTP
        if _verify_totp(enrollment.secret, code):
            enrollment.verified = True
            enrollment.last_used = datetime.now(timezone.utc).isoformat()
            self._verification_successes += 1
            return True

        logger.warning("[MFA] Failed verification for %s", username)
        return False

    def is_enrolled(self, username: str) -> bool:
        """Check if a user has MFA enrolled."""
        return username in self._enrollments

    def is_required(self, role: str) -> bool:
        """Check if MFA is required for a given role."""
        if self._policy == MFAEnforcementPolicy.DISABLED:
            return False
        if self._policy == MFAEnforcementPolicy.ALL_REQUIRED:
            return True
        if self._policy == MFAEnforcementPolicy.ADMIN_REQUIRED:
            return role == "ADMIN"
        return False  # optional

    def unenroll(self, username: str) -> bool:
        """Remove MFA enrollment for a user."""
        with self._lock:
            if username in self._enrollments:
                del self._enrollments[username]
                logger.info("[MFA] User unenrolled: %s", username)
                return True
        return False

    def get_enrollment(self, username: str) -> Optional[Dict[str, Any]]:
        """Get MFA enrollment status (no secrets exposed)."""
        enrollment = self._enrollments.get(username)
        return enrollment.to_dict() if enrollment else None

    def get_all_enrollments(self) -> List[Dict[str, Any]]:
        """Get all MFA enrollments (admin view)."""
        return [e.to_dict() for e in self._enrollments.values()]

    def get_stats(self) -> Dict[str, Any]:
        """Get MFA statistics."""
        enrolled = len(self._enrollments)
        verified = sum(1 for e in self._enrollments.values() if e.verified)
        return {
            "policy": self._policy,
            "enrolled_users": enrolled,
            "verified_users": verified,
            "total_attempts": self._verification_attempts,
            "total_successes": self._verification_successes,
            "success_rate": round(
                self._verification_successes / max(self._verification_attempts, 1), 3
            ),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[MFAManager] = None
_instance_lock = threading.Lock()


def get_mfa_manager() -> MFAManager:
    """Get the global MFAManager singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                policy = os.getenv("MFA_POLICY", MFAEnforcementPolicy.ADMIN_REQUIRED)
                _instance = MFAManager(policy=policy)
    return _instance
