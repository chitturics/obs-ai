"""Secrets Management — abstraction layer for credential storage and rotation.

Provides:
- **Secret registration**: Track where secrets are used
- **Rotation tracking**: When each secret was last rotated, next rotation due
- **Plaintext detection**: Scan config files for hardcoded secrets
- **Provider abstraction**: Environment vars (default), with Vault/KMS as future backends

Usage:
    from chat_app.secrets_manager import get_secrets_manager

    mgr = get_secrets_manager()
    mgr.register_secret("splunk_token", source="env:SPLUNK_HEC_TOKEN", rotation_days=90)
    report = mgr.get_rotation_report()
    violations = mgr.scan_for_plaintext("/app/config.yaml")
"""

import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Secret registration
# ---------------------------------------------------------------------------

@dataclass
class SecretEntry:
    """A registered secret with metadata."""
    name: str
    description: str = ""
    source: str = "env"  # env:VAR_NAME, vault:path/to/secret, kms:key-id
    rotation_days: int = 90  # Recommended rotation period
    last_rotated: Optional[str] = None  # ISO timestamp
    created_at: str = ""
    used_by: List[str] = field(default_factory=list)  # Components that use this secret
    is_set: bool = False  # Whether the secret has a value

    @property
    def rotation_overdue(self) -> bool:
        if not self.last_rotated or self.rotation_days <= 0:
            return False
        rotated = datetime.fromisoformat(self.last_rotated)
        due = rotated + timedelta(days=self.rotation_days)
        return datetime.now(timezone.utc) > due

    @property
    def days_until_rotation(self) -> Optional[int]:
        if not self.last_rotated or self.rotation_days <= 0:
            return None
        rotated = datetime.fromisoformat(self.last_rotated)
        due = rotated + timedelta(days=self.rotation_days)
        delta = due - datetime.now(timezone.utc)
        return delta.days

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "rotation_days": self.rotation_days,
            "last_rotated": self.last_rotated,
            "rotation_overdue": self.rotation_overdue,
            "days_until_rotation": self.days_until_rotation,
            "used_by": self.used_by,
            "is_set": self.is_set,
        }


# ---------------------------------------------------------------------------
# Plaintext detection patterns
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: List[re.Pattern] = [
    re.compile(r'(?i)(password|passwd|pwd)\s*[:=]\s*["\']?[^\s"\']{8,}'),
    re.compile(r'(?i)(api[_-]?key|apikey)\s*[:=]\s*["\']?[^\s"\']{16,}'),
    re.compile(r'(?i)(secret|token)\s*[:=]\s*["\']?[^\s"\']{16,}'),
    re.compile(r'(?i)(access[_-]?key)\s*[:=]\s*["\']?[^\s"\']{16,}'),
    re.compile(r'(?i)(private[_-]?key)\s*[:=]\s*["\']?[^\s"\']{16,}'),
    re.compile(r'(?i)(connection[_-]?string)\s*[:=]\s*["\']?[^\s"\']{20,}'),
]

# Patterns that are safe (env var references, not actual secrets)
_SAFE_PATTERNS: List[re.Pattern] = [
    re.compile(r'\$\{?\w+\}?'),           # ${ENV_VAR} or $ENV_VAR
    re.compile(r'os\.getenv|os\.environ'),  # Python env access
    re.compile(r'<PLACEHOLDER>|<YOUR_'),    # Placeholder values
    re.compile(r'xxx+|CHANGE_ME|TODO'),     # Obviously fake values
]


@dataclass
class PlaintextFinding:
    """A potential plaintext secret found in a file."""
    file_path: str
    line_number: int
    pattern_matched: str
    line_preview: str  # Masked preview

    def to_dict(self) -> Dict[str, Any]:
        return {
            "file": self.file_path,
            "line": self.line_number,
            "pattern": self.pattern_matched,
            "preview": self.line_preview,
        }


# ---------------------------------------------------------------------------
# Default secret registrations
# ---------------------------------------------------------------------------

_DEFAULT_SECRETS: List[SecretEntry] = [
    SecretEntry(
        name="database_password",
        description="PostgreSQL database password",
        source="env:DATABASE_PASSWORD",
        rotation_days=90,
        used_by=["chat_db_app", "chat_ui_app"],
    ),
    SecretEntry(
        name="redis_password",
        description="Redis cache password",
        source="env:REDIS_PASSWORD",
        rotation_days=90,
        used_by=["redis_cache", "chat_ui_app"],
    ),
    SecretEntry(
        name="splunk_hec_token",
        description="Splunk HTTP Event Collector token",
        source="env:SPLUNK_HEC_TOKEN",
        rotation_days=180,
        used_by=["splunk_client"],
    ),
    SecretEntry(
        name="splunk_password",
        description="Splunk admin password",
        source="env:SPLUNK_PASSWORD",
        rotation_days=90,
        used_by=["splunk_client"],
    ),
    SecretEntry(
        name="service_api_key",
        description="Internal service-to-service API key",
        source="env:SERVICE_API_KEY",
        rotation_days=90,
        used_by=["mcp_server", "admin_api"],
    ),
    SecretEntry(
        name="api_keys",
        description="External API access keys",
        source="env:API_KEYS",
        rotation_days=90,
        used_by=["admin_api", "auth_dependencies"],
    ),
    SecretEntry(
        name="oidc_client_secret",
        description="OIDC/OAuth client secret for SSO",
        source="env:OIDC_CLIENT_SECRET",
        rotation_days=365,
        used_by=["auth_providers"],
    ),
    SecretEntry(
        name="grafana_admin_password",
        description="Grafana admin password",
        source="env:GF_SECURITY_ADMIN_PASSWORD",
        rotation_days=90,
        used_by=["grafana_monitoring"],
    ),
]


# ---------------------------------------------------------------------------
# Secrets Manager
# ---------------------------------------------------------------------------

class SecretsManager:
    """Manages secret registration, rotation tracking, and plaintext detection."""

    def __init__(self):
        self._secrets: Dict[str, SecretEntry] = {}
        now = datetime.now(timezone.utc).isoformat()
        for s in _DEFAULT_SECRETS:
            s.created_at = now
            # Check if the env var is set
            if s.source.startswith("env:"):
                env_var = s.source[4:]
                s.is_set = bool(os.getenv(env_var, "").strip())
            self._secrets[s.name] = s

    def register_secret(
        self,
        name: str,
        description: str = "",
        source: str = "env",
        rotation_days: int = 90,
        used_by: Optional[List[str]] = None,
    ) -> SecretEntry:
        """Register a secret for tracking."""
        entry = SecretEntry(
            name=name,
            description=description,
            source=source,
            rotation_days=rotation_days,
            created_at=datetime.now(timezone.utc).isoformat(),
            used_by=used_by or [],
        )
        if source.startswith("env:"):
            entry.is_set = bool(os.getenv(source[4:], "").strip())
        self._secrets[name] = entry
        return entry

    def mark_rotated(self, name: str) -> Optional[SecretEntry]:
        """Mark a secret as just rotated."""
        entry = self._secrets.get(name)
        if entry:
            entry.last_rotated = datetime.now(timezone.utc).isoformat()
        return entry

    def get_secret(self, name: str) -> Optional[SecretEntry]:
        """Get a registered secret's metadata (never the value)."""
        return self._secrets.get(name)

    def get_all_secrets(self) -> List[SecretEntry]:
        """Get all registered secrets."""
        return list(self._secrets.values())

    def get_rotation_report(self) -> Dict[str, Any]:
        """Get rotation status for all secrets."""
        overdue = [s for s in self._secrets.values() if s.rotation_overdue]
        unset = [s for s in self._secrets.values() if not s.is_set]
        never_rotated = [s for s in self._secrets.values() if not s.last_rotated]

        return {
            "total_secrets": len(self._secrets),
            "overdue_count": len(overdue),
            "unset_count": len(unset),
            "never_rotated_count": len(never_rotated),
            "overdue": [s.to_dict() for s in overdue],
            "unset": [s.name for s in unset],
            "never_rotated": [s.name for s in never_rotated],
            "all_secrets": [s.to_dict() for s in self._secrets.values()],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def scan_for_plaintext(self, file_path: str) -> List[PlaintextFinding]:
        """Scan a file for potential plaintext secrets."""
        findings: List[PlaintextFinding] = []
        path = Path(file_path)
        if not path.exists() or not path.is_file():
            return findings

        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                for line_num, line in enumerate(fh, 1):
                    line = line.rstrip()
                    if not line or line.lstrip().startswith("#"):
                        continue

                    for pattern in _SECRET_PATTERNS:
                        match = pattern.search(line)
                        if not match:
                            continue

                        # Check if it's a safe pattern (env var reference)
                        matched_text = match.group()
                        if any(sp.search(matched_text) for sp in _SAFE_PATTERNS):
                            continue

                        # Mask the preview
                        preview = line[:60] + "..." if len(line) > 60 else line
                        findings.append(PlaintextFinding(
                            file_path=str(path),
                            line_number=line_num,
                            pattern_matched=pattern.pattern[:50],
                            line_preview=preview,
                        ))
                        break  # One finding per line is enough

        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[SECRETS] Failed to scan %s: %s", file_path, exc)

        return findings

    def scan_directory(self, directory: str, extensions: Optional[Set[str]] = None) -> List[PlaintextFinding]:
        """Scan a directory for plaintext secrets in config files."""
        if extensions is None:
            extensions = {".yaml", ".yml", ".toml", ".ini", ".conf", ".env", ".json", ".py"}

        findings: List[PlaintextFinding] = []
        dir_path = Path(directory)
        if not dir_path.exists():
            return findings

        for path in dir_path.rglob("*"):
            if path.is_file() and path.suffix in extensions:
                findings.extend(self.scan_for_plaintext(str(path)))

        return findings


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[SecretsManager] = None


def get_secrets_manager() -> SecretsManager:
    """Get the global SecretsManager singleton."""
    global _instance
    if _instance is None:
        _instance = SecretsManager()
    return _instance
