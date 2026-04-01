"""Tenant Quotas & Budgets — per-tenant resource limits and tracking.

Provides:
- Quota definitions per resource type (LLM tokens, storage, API calls, etc.)
- Real-time usage tracking against quotas
- Enforcement (warn, soft-limit, hard-limit)
- Budget alerts when approaching limits

Usage:
    from chat_app.tenant_quotas import get_quota_manager

    mgr = get_quota_manager()
    mgr.record_usage("tenant_a", "llm_tokens", 500)
    status = mgr.check_quota("tenant_a", "llm_tokens")
    # status.within_quota, status.usage_pct, status.remaining
"""

import logging
import threading
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Quota enforcement levels
# ---------------------------------------------------------------------------

class EnforcementLevel:
    WARN = "warn"           # Log warning, allow request
    SOFT_LIMIT = "soft_limit"  # Return warning to caller, allow request
    HARD_LIMIT = "hard_limit"  # Reject request


# ---------------------------------------------------------------------------
# Quota definition
# ---------------------------------------------------------------------------

@dataclass
class QuotaDefinition:
    """Definition of a resource quota."""
    resource: str
    description: str
    limit: int
    period: str = "monthly"  # daily, weekly, monthly
    enforcement: str = EnforcementLevel.SOFT_LIMIT
    unit: str = "count"  # count, tokens, bytes, requests

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource": self.resource,
            "description": self.description,
            "limit": self.limit,
            "period": self.period,
            "enforcement": self.enforcement,
            "unit": self.unit,
        }


# ---------------------------------------------------------------------------
# Quota check result
# ---------------------------------------------------------------------------

@dataclass
class QuotaStatus:
    """Result of a quota check."""
    resource: str
    tenant: str
    within_quota: bool
    current_usage: int
    limit: int
    remaining: int
    usage_pct: float
    enforcement: str
    warning: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "resource": self.resource,
            "tenant": self.tenant,
            "within_quota": self.within_quota,
            "current_usage": self.current_usage,
            "limit": self.limit,
            "remaining": self.remaining,
            "usage_pct": round(self.usage_pct, 1),
            "enforcement": self.enforcement,
            "warning": self.warning,
        }


# ---------------------------------------------------------------------------
# Default quotas
# ---------------------------------------------------------------------------

_DEFAULT_QUOTAS: List[QuotaDefinition] = [
    QuotaDefinition(
        resource="llm_tokens",
        description="LLM token usage per month",
        limit=1_000_000,
        period="monthly",
        enforcement=EnforcementLevel.SOFT_LIMIT,
        unit="tokens",
    ),
    QuotaDefinition(
        resource="api_calls",
        description="Admin API calls per day",
        limit=10_000,
        period="daily",
        enforcement=EnforcementLevel.SOFT_LIMIT,
        unit="requests",
    ),
    QuotaDefinition(
        resource="storage_mb",
        description="Vector store storage per tenant",
        limit=5_000,
        period="monthly",
        enforcement=EnforcementLevel.HARD_LIMIT,
        unit="megabytes",
    ),
    QuotaDefinition(
        resource="ingestion_docs",
        description="Document ingestion per month",
        limit=1_000,
        period="monthly",
        enforcement=EnforcementLevel.SOFT_LIMIT,
        unit="documents",
    ),
    QuotaDefinition(
        resource="tool_executions",
        description="Tool executions per day",
        limit=5_000,
        period="daily",
        enforcement=EnforcementLevel.WARN,
        unit="executions",
    ),
    QuotaDefinition(
        resource="concurrent_sessions",
        description="Concurrent chat sessions",
        limit=50,
        period="daily",
        enforcement=EnforcementLevel.HARD_LIMIT,
        unit="sessions",
    ),
]

_WARN_THRESHOLD = 0.80  # Warn at 80% usage
_CRITICAL_THRESHOLD = 0.95  # Critical at 95%


# ---------------------------------------------------------------------------
# Quota Manager
# ---------------------------------------------------------------------------

class QuotaManager:
    """Manages per-tenant resource quotas and budgets."""

    def __init__(self):
        self._quotas: Dict[str, QuotaDefinition] = {q.resource: q for q in _DEFAULT_QUOTAS}
        self._usage: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self._lock = threading.Lock()

    def record_usage(self, tenant: str, resource: str, amount: int = 1) -> QuotaStatus:
        """Record resource usage for a tenant. Returns current quota status."""
        with self._lock:
            self._usage[tenant][resource] += amount
            current = self._usage[tenant][resource]

        return self._check(tenant, resource, current)

    def check_quota(self, tenant: str, resource: str) -> QuotaStatus:
        """Check current quota status without recording usage."""
        with self._lock:
            current = self._usage[tenant][resource]
        return self._check(tenant, resource, current)

    def _check(self, tenant: str, resource: str, current: int) -> QuotaStatus:
        """Internal quota check."""
        quota = self._quotas.get(resource)
        if not quota:
            return QuotaStatus(
                resource=resource, tenant=tenant, within_quota=True,
                current_usage=current, limit=0, remaining=0,
                usage_pct=0, enforcement="none",
            )

        remaining = max(0, quota.limit - current)
        pct = (current / quota.limit * 100) if quota.limit > 0 else 0
        within = current <= quota.limit

        warning = None
        if pct >= _CRITICAL_THRESHOLD * 100:
            warning = f"CRITICAL: {resource} usage at {pct:.0f}% of quota"
        elif pct >= _WARN_THRESHOLD * 100:
            warning = f"WARNING: {resource} usage at {pct:.0f}% of quota"

        if not within:
            warning = f"EXCEEDED: {resource} quota exceeded ({current}/{quota.limit})"

        return QuotaStatus(
            resource=resource,
            tenant=tenant,
            within_quota=within,
            current_usage=current,
            limit=quota.limit,
            remaining=remaining,
            usage_pct=pct,
            enforcement=quota.enforcement,
            warning=warning,
        )

    def get_tenant_usage(self, tenant: str) -> Dict[str, Any]:
        """Get all quota statuses for a tenant."""
        statuses = []
        for resource in self._quotas:
            statuses.append(self.check_quota(tenant, resource).to_dict())
        return {
            "tenant": tenant,
            "quotas": statuses,
            "any_exceeded": any(not s["within_quota"] for s in statuses),
            "warnings": [s["warning"] for s in statuses if s.get("warning")],
        }

    def get_all_tenants(self) -> List[str]:
        """Get all tenants with recorded usage."""
        return list(self._usage.keys())

    def get_quota_definitions(self) -> List[Dict[str, Any]]:
        """Get all quota definitions."""
        return [q.to_dict() for q in self._quotas.values()]

    def set_quota(self, resource: str, limit: int, enforcement: Optional[str] = None) -> QuotaDefinition:
        """Update a quota limit."""
        quota = self._quotas.get(resource)
        if quota:
            quota.limit = limit
            if enforcement:
                quota.enforcement = enforcement
        else:
            quota = QuotaDefinition(resource=resource, description=f"Custom: {resource}", limit=limit)
            if enforcement:
                quota.enforcement = enforcement
            self._quotas[resource] = quota
        return quota

    def reset_usage(self, tenant: str, resource: Optional[str] = None) -> None:
        """Reset usage counters for a tenant."""
        with self._lock:
            if resource:
                self._usage[tenant][resource] = 0
            else:
                self._usage[tenant] = defaultdict(int)

    def get_stats(self) -> Dict[str, Any]:
        """Get global quota statistics."""
        total_tenants = len(self._usage)
        exceeded = 0
        for tenant in self._usage:
            for resource in self._quotas:
                status = self.check_quota(tenant, resource)
                if not status.within_quota:
                    exceeded += 1

        return {
            "total_quotas": len(self._quotas),
            "total_tenants": total_tenants,
            "exceeded_count": exceeded,
            "quota_definitions": self.get_quota_definitions(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[QuotaManager] = None
_instance_lock = threading.Lock()


def get_quota_manager() -> QuotaManager:
    """Get the global QuotaManager singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = QuotaManager()
    return _instance
