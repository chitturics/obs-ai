"""Data Governance — retention policies, PII tagging, and redaction rules.

Manages data lifecycle across all storage:
- **Retention policies**: Per-source retention periods with auto-cleanup
- **PII detection & tagging**: Regex-based PII identification in content
- **Redaction rules**: Define which PII types to redact in which contexts
- **Compliance reporting**: Track what data is stored, where, and how long

Usage:
    from chat_app.data_governance import get_governance_manager

    mgr = get_governance_manager()

    # Check retention for a source
    policy = mgr.get_retention_policy("audit_log")

    # Scan text for PII
    findings = mgr.scan_for_pii("Contact john@example.com or 555-0123")

    # Redact PII from text
    redacted = mgr.redact_pii("Call me at 555-0123", redact_types=["phone"])
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PII Types
# ---------------------------------------------------------------------------

class PIIType:
    EMAIL = "email"
    PHONE = "phone"
    SSN = "ssn"
    CREDIT_CARD = "credit_card"
    IP_ADDRESS = "ip_address"
    API_KEY = "api_key"
    PASSWORD = "password"
    USERNAME = "username"


# PII detection patterns
_PII_PATTERNS: Dict[str, re.Pattern] = {
    PIIType.EMAIL: re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'),
    PIIType.PHONE: re.compile(r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'),
    PIIType.SSN: re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),
    PIIType.CREDIT_CARD: re.compile(r'\b(?:\d{4}[-\s]?){3}\d{4}\b'),
    PIIType.IP_ADDRESS: re.compile(r'\b(?:\d{1,3}\.){3}\d{1,3}\b'),
    PIIType.API_KEY: re.compile(r'\b(?:obsai_|sk-|key-|token-)[a-zA-Z0-9_-]{20,}\b'),
    PIIType.PASSWORD: re.compile(r'(?i)(?:password|passwd|pwd)\s*[:=]\s*\S+'),
}

# Redaction replacement strings
_REDACTION_MAP: Dict[str, str] = {
    PIIType.EMAIL: "[REDACTED_EMAIL]",
    PIIType.PHONE: "[REDACTED_PHONE]",
    PIIType.SSN: "[REDACTED_SSN]",
    PIIType.CREDIT_CARD: "[REDACTED_CC]",
    PIIType.IP_ADDRESS: "[REDACTED_IP]",
    PIIType.API_KEY: "[REDACTED_KEY]",
    PIIType.PASSWORD: "[REDACTED_PASSWORD]",
}


# ---------------------------------------------------------------------------
# PII Finding
# ---------------------------------------------------------------------------

@dataclass
class PIIFinding:
    """A PII detection result."""
    pii_type: str
    value: str
    start: int
    end: int
    context: str = ""  # Surrounding text for review

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.pii_type,
            "value": self.value[:4] + "..." if len(self.value) > 8 else "***",
            "start": self.start,
            "end": self.end,
            "context": self.context,
        }


# ---------------------------------------------------------------------------
# Retention Policy
# ---------------------------------------------------------------------------

@dataclass
class RetentionPolicy:
    """Data retention policy for a storage source."""
    source: str
    description: str
    retention_days: int
    storage_type: str  # file, database, vector_store, cache
    contains_pii: bool = False
    auto_cleanup: bool = True
    cleanup_action: str = "delete"  # delete, archive, anonymize
    compliance_notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "description": self.description,
            "retention_days": self.retention_days,
            "storage_type": self.storage_type,
            "contains_pii": self.contains_pii,
            "auto_cleanup": self.auto_cleanup,
            "cleanup_action": self.cleanup_action,
            "compliance_notes": self.compliance_notes,
        }


# ---------------------------------------------------------------------------
# Default retention policies
# ---------------------------------------------------------------------------

_DEFAULT_POLICIES: List[RetentionPolicy] = [
    RetentionPolicy(
        source="audit_log",
        description="Immutable audit log entries",
        retention_days=365,
        storage_type="file",
        contains_pii=True,
        auto_cleanup=False,
        cleanup_action="archive",
        compliance_notes="Audit logs must be retained for 1 year minimum. Archive after retention period.",
    ),
    RetentionPolicy(
        source="activity_timeline",
        description="In-memory activity events",
        retention_days=7,
        storage_type="memory",
        contains_pii=True,
        auto_cleanup=True,
        cleanup_action="delete",
    ),
    RetentionPolicy(
        source="chat_history",
        description="User chat sessions in PostgreSQL",
        retention_days=90,
        storage_type="database",
        contains_pii=True,
        auto_cleanup=True,
        cleanup_action="anonymize",
        compliance_notes="Anonymize user identifiers after 90 days. Keep content for training.",
    ),
    RetentionPolicy(
        source="vector_collections",
        description="ChromaDB document collections",
        retention_days=0,  # No automatic expiry
        storage_type="vector_store",
        contains_pii=False,
        auto_cleanup=False,
        compliance_notes="Collections are managed manually. Reindex to refresh.",
    ),
    RetentionPolicy(
        source="feedback",
        description="User feedback (likes/dislikes)",
        retention_days=180,
        storage_type="file",
        contains_pii=True,
        auto_cleanup=True,
        cleanup_action="anonymize",
    ),
    RetentionPolicy(
        source="config_backups",
        description="Configuration file backups",
        retention_days=30,
        storage_type="file",
        contains_pii=False,
        auto_cleanup=True,
        cleanup_action="delete",
        compliance_notes="Keep last 10 backups regardless of age.",
    ),
    RetentionPolicy(
        source="session_cache",
        description="Redis session and cache data",
        retention_days=1,
        storage_type="cache",
        contains_pii=True,
        auto_cleanup=True,
        cleanup_action="delete",
    ),
    RetentionPolicy(
        source="cost_tracking",
        description="LLM cost and token usage records",
        retention_days=90,
        storage_type="memory",
        contains_pii=True,
        auto_cleanup=True,
        cleanup_action="anonymize",
    ),
    RetentionPolicy(
        source="rbac_overrides",
        description="Per-user RBAC permission overrides",
        retention_days=0,  # No automatic expiry
        storage_type="file",
        contains_pii=True,
        auto_cleanup=False,
        compliance_notes="Review quarterly. Remove overrides for departed users.",
    ),
]


# ---------------------------------------------------------------------------
# Governance Manager
# ---------------------------------------------------------------------------

class GovernanceManager:
    """Manages data governance policies, PII detection, and compliance."""

    def __init__(self):
        self._policies: Dict[str, RetentionPolicy] = {}
        for policy in _DEFAULT_POLICIES:
            self._policies[policy.source] = policy

    # ----- Retention Policies -----

    def get_retention_policy(self, source: str) -> Optional[RetentionPolicy]:
        """Get the retention policy for a data source."""
        return self._policies.get(source)

    def get_all_policies(self) -> List[RetentionPolicy]:
        """Get all retention policies."""
        return list(self._policies.values())

    def set_retention_policy(self, policy: RetentionPolicy) -> None:
        """Register or update a retention policy."""
        self._policies[policy.source] = policy
        logger.info("[GOVERNANCE] Updated retention policy: %s (%d days)", policy.source, policy.retention_days)

    def get_pii_sources(self) -> List[RetentionPolicy]:
        """Get all sources that contain PII."""
        return [p for p in self._policies.values() if p.contains_pii]

    # ----- PII Detection -----

    def scan_for_pii(
        self,
        text: str,
        pii_types: Optional[Set[str]] = None,
    ) -> List[PIIFinding]:
        """Scan text for PII occurrences.

        Args:
            text: The text to scan.
            pii_types: Optional set of PII types to check. Checks all if None.

        Returns:
            List of PII findings with type, position, and masked value.
        """
        findings: List[PIIFinding] = []
        patterns_to_check = _PII_PATTERNS if pii_types is None else {
            k: v for k, v in _PII_PATTERNS.items() if k in pii_types
        }

        for pii_type, pattern in patterns_to_check.items():
            for match in pattern.finditer(text):
                start, end = match.start(), match.end()
                context_start = max(0, start - 20)
                context_end = min(len(text), end + 20)
                findings.append(PIIFinding(
                    pii_type=pii_type,
                    value=match.group(),
                    start=start,
                    end=end,
                    context=text[context_start:context_end],
                ))

        return findings

    def redact_pii(
        self,
        text: str,
        redact_types: Optional[Set[str]] = None,
    ) -> str:
        """Redact PII from text.

        Args:
            text: The text to redact.
            redact_types: Optional set of PII types to redact. Redacts all if None.

        Returns:
            Text with PII replaced by redaction markers.
        """
        patterns = _PII_PATTERNS if redact_types is None else {
            k: v for k, v in _PII_PATTERNS.items() if k in redact_types
        }

        result = text
        for pii_type, pattern in patterns.items():
            replacement = _REDACTION_MAP.get(pii_type, "[REDACTED]")
            result = pattern.sub(replacement, result)
        return result

    def has_pii(self, text: str) -> bool:
        """Quick check: does the text contain any PII?"""
        for pattern in _PII_PATTERNS.values():
            if pattern.search(text):
                return True
        return False

    # ----- Compliance Report -----

    def get_compliance_report(self) -> Dict[str, Any]:
        """Generate a data governance compliance report."""
        policies = self.get_all_policies()
        pii_sources = self.get_pii_sources()

        auto_cleanup_sources = [p for p in policies if p.auto_cleanup]
        manual_sources = [p for p in policies if not p.auto_cleanup]

        return {
            "total_sources": len(policies),
            "pii_sources": len(pii_sources),
            "auto_cleanup_sources": len(auto_cleanup_sources),
            "manual_review_sources": len(manual_sources),
            "policies": [p.to_dict() for p in policies],
            "pii_source_names": [p.source for p in pii_sources],
            "storage_types": list(set(p.storage_type for p in policies)),
            "pii_types_detected": list(_PII_PATTERNS.keys()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[GovernanceManager] = None


def get_governance_manager() -> GovernanceManager:
    """Get the global GovernanceManager singleton."""
    global _instance
    if _instance is None:
        _instance = GovernanceManager()
    return _instance
