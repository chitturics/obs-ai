"""Runbook Attachment — links alerts to runbooks and fix-it workflows.

Every alert/health issue maps to a runbook with:
- Description of the problem
- Diagnostic steps
- Fix actions (manual and automated)
- Escalation path
- Related tools/skills that can help

Usage:
    from chat_app.runbooks import get_runbook_registry

    registry = get_runbook_registry()
    runbook = registry.get_for_alert("postgres_unhealthy")
    # Returns runbook with steps, fix commands, and skill references
"""

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class RunbookStep:
    """A single step in a runbook."""
    order: int
    description: str
    command: Optional[str] = None  # Shell command to run
    skill: Optional[str] = None   # Skill to invoke
    automated: bool = False       # Can this step be auto-executed?


@dataclass
class Runbook:
    """A runbook for diagnosing and fixing an issue."""
    alert_key: str
    title: str
    description: str
    severity: str = "warning"  # info, warning, critical
    category: str = "infrastructure"
    diagnostic_steps: List[RunbookStep] = field(default_factory=list)
    fix_steps: List[RunbookStep] = field(default_factory=list)
    escalation: str = ""
    related_tools: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "alert_key": self.alert_key,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "category": self.category,
            "diagnostic_steps": [
                {"order": s.order, "description": s.description,
                 "command": s.command, "skill": s.skill, "automated": s.automated}
                for s in self.diagnostic_steps
            ],
            "fix_steps": [
                {"order": s.order, "description": s.description,
                 "command": s.command, "skill": s.skill, "automated": s.automated}
                for s in self.fix_steps
            ],
            "escalation": self.escalation,
            "related_tools": self.related_tools,
            "tags": self.tags,
        }


# ---------------------------------------------------------------------------
# Built-in runbooks
# ---------------------------------------------------------------------------

_BUILTIN_RUNBOOKS: List[Runbook] = [
    Runbook(
        alert_key="postgres_unhealthy",
        title="PostgreSQL Database Unhealthy",
        description="PostgreSQL is not responding to health checks or connections are failing.",
        severity="critical",
        category="database",
        diagnostic_steps=[
            RunbookStep(1, "Check if PostgreSQL container is running", "podman ps | grep chat_db_app"),
            RunbookStep(2, "Check PostgreSQL logs for errors", "podman logs --tail 50 chat_db_app"),
            RunbookStep(3, "Verify disk space on data volume", "podman exec chat_db_app df -h /var/lib/postgresql/data"),
            RunbookStep(4, "Test direct connection", "podman exec chat_db_app pg_isready -U chainlit"),
        ],
        fix_steps=[
            RunbookStep(1, "Restart PostgreSQL container", "podman restart chat_db_app", automated=True),
            RunbookStep(2, "If restart fails, check and repair data volume"),
            RunbookStep(3, "If data is corrupt, restore from latest backup", skill="restore_backup"),
        ],
        escalation="If PostgreSQL cannot be recovered, escalate to infrastructure team. Check backup integrity.",
        related_tools=["health_check", "restore_backup", "create_backup"],
        tags=["database", "postgres", "critical"],
    ),
    Runbook(
        alert_key="ollama_unhealthy",
        title="Ollama LLM Service Unhealthy",
        description="Ollama is not responding. LLM inference will fail.",
        severity="critical",
        category="llm",
        diagnostic_steps=[
            RunbookStep(1, "Check if Ollama container is running", "podman ps | grep llm_api_service"),
            RunbookStep(2, "Check Ollama logs", "podman logs --tail 50 llm_api_service"),
            RunbookStep(3, "Check GPU/CPU availability", "podman exec llm_api_service ollama list"),
            RunbookStep(4, "Check memory usage", "podman stats --no-stream llm_api_service"),
        ],
        fix_steps=[
            RunbookStep(1, "Restart Ollama container", "podman restart llm_api_service", automated=True),
            RunbookStep(2, "If model is missing, pull it", "podman exec llm_api_service ollama pull llama3"),
            RunbookStep(3, "If OOM, increase memory limit in start_all.sh"),
        ],
        escalation="If Ollama cannot load the model, check if another process is using GPU memory.",
        related_tools=["health_check"],
        tags=["llm", "ollama", "critical"],
    ),
    Runbook(
        alert_key="chromadb_unhealthy",
        title="ChromaDB Vector Store Unhealthy",
        description="ChromaDB is not responding. Retrieval and search will fail.",
        severity="critical",
        category="retrieval",
        diagnostic_steps=[
            RunbookStep(1, "Check container status", "podman ps | grep chat_chroma_db"),
            RunbookStep(2, "Check ChromaDB logs", "podman logs --tail 50 chat_chroma_db"),
            RunbookStep(3, "Test heartbeat", "podman exec chat_chroma_db bash -c 'echo > /dev/tcp/localhost/8001'"),
        ],
        fix_steps=[
            RunbookStep(1, "Restart ChromaDB container", "podman restart chat_chroma_db", automated=True),
            RunbookStep(2, "If data is corrupt, reindex collections", skill="reindex_collection"),
        ],
        escalation="If ChromaDB data volume is corrupt, rebuild from ingestion sources.",
        related_tools=["health_check", "reindex_collection", "collection_stats"],
        tags=["retrieval", "chromadb", "critical"],
    ),
    Runbook(
        alert_key="redis_unhealthy",
        title="Redis Cache Unhealthy",
        description="Redis is not responding. Caching and rate limiting will fall back to in-memory.",
        severity="warning",
        category="cache",
        diagnostic_steps=[
            RunbookStep(1, "Check container status", "podman ps | grep redis_cache"),
            RunbookStep(2, "Check Redis logs", "podman logs --tail 30 redis_cache"),
            RunbookStep(3, "Test connection", "podman exec redis_cache redis-cli ping"),
        ],
        fix_steps=[
            RunbookStep(1, "Restart Redis container", "podman restart redis_cache", automated=True),
            RunbookStep(2, "Clear stale data if needed", "podman exec redis_cache redis-cli FLUSHALL"),
        ],
        escalation="Redis failure is non-critical. System degrades gracefully to in-memory caching.",
        related_tools=["health_check", "clear_cache"],
        tags=["cache", "redis", "warning"],
    ),
    Runbook(
        alert_key="disk_space_low",
        title="Disk Space Low",
        description="Available disk space is below threshold. May affect logging, backups, and ingestion.",
        severity="warning",
        category="infrastructure",
        diagnostic_steps=[
            RunbookStep(1, "Check disk usage", "df -h /app/data"),
            RunbookStep(2, "Find large files", "du -sh /app/data/* | sort -rh | head -20"),
            RunbookStep(3, "Check backup retention", skill="list_backups"),
        ],
        fix_steps=[
            RunbookStep(1, "Clean old backups (keep last 5)", skill="cleanup_backups"),
            RunbookStep(2, "Remove old audit log rotations"),
            RunbookStep(3, "Prune old container images", "podman image prune -f"),
        ],
        escalation="If disk is critically low, stop ingestion and expand storage.",
        related_tools=["create_backup", "collection_stats"],
        tags=["disk", "infrastructure", "warning"],
    ),
    Runbook(
        alert_key="high_error_rate",
        title="High Error Rate Detected",
        description="Tool or API error rate exceeds threshold. Users may be experiencing failures.",
        severity="warning",
        category="reliability",
        diagnostic_steps=[
            RunbookStep(1, "Check circuit breaker status for open circuits", skill="get_circuit_breakers"),
            RunbookStep(2, "Check recent audit log for error patterns", skill="get_audit_entries"),
            RunbookStep(3, "Check SLO dashboard for breached SLOs", skill="get_slo_dashboard"),
        ],
        fix_steps=[
            RunbookStep(1, "Reset circuit breakers for affected tools", skill="reset_circuit_breaker"),
            RunbookStep(2, "Check and restart unhealthy services", skill="health_check"),
            RunbookStep(3, "Review recent config changes that may have caused the issue"),
        ],
        escalation="If error rate persists after service restarts, check for upstream dependency issues.",
        related_tools=["health_check", "get_circuit_breakers"],
        tags=["reliability", "errors", "warning"],
    ),
    Runbook(
        alert_key="latency_budget_exceeded",
        title="Tool Latency Budget Exceeded",
        description="One or more tools consistently exceed their latency budget (p95 > timeout).",
        severity="warning",
        category="performance",
        diagnostic_steps=[
            RunbookStep(1, "Check latency reports for violations", skill="get_latency_reports"),
            RunbookStep(2, "Check system resource utilization (CPU/memory)"),
            RunbookStep(3, "Check if dependent services are slow"),
        ],
        fix_steps=[
            RunbookStep(1, "Increase timeout budget if the tool legitimately needs more time"),
            RunbookStep(2, "Activate fallback path if available"),
            RunbookStep(3, "Scale dependent services or optimize the tool"),
        ],
        escalation="If latency is caused by external services, check their health and SLAs.",
        related_tools=["health_check"],
        tags=["performance", "latency", "warning"],
    ),
    Runbook(
        alert_key="slo_breached",
        title="SLO Breached",
        description="A Service Level Objective is below its target threshold.",
        severity="critical",
        category="reliability",
        diagnostic_steps=[
            RunbookStep(1, "Check SLO dashboard for details", skill="get_slo_dashboard"),
            RunbookStep(2, "Identify which SLO is breached and review recent changes"),
            RunbookStep(3, "Check circuit breakers and latency reports"),
        ],
        fix_steps=[
            RunbookStep(1, "Address the root cause identified in diagnostics"),
            RunbookStep(2, "Reset counters after fix is deployed"),
        ],
        escalation="SLO breaches should be reviewed in the next team standup with action items.",
        related_tools=["health_check", "get_circuit_breakers"],
        tags=["slo", "reliability", "critical"],
    ),
]


# ---------------------------------------------------------------------------
# Runbook Registry
# ---------------------------------------------------------------------------

class RunbookRegistry:
    """Registry of runbooks keyed by alert name."""

    def __init__(self):
        self._runbooks: Dict[str, Runbook] = {}
        for rb in _BUILTIN_RUNBOOKS:
            self._runbooks[rb.alert_key] = rb

    def get_for_alert(self, alert_key: str) -> Optional[Runbook]:
        """Get the runbook for a specific alert."""
        return self._runbooks.get(alert_key)

    def get_all(self) -> List[Runbook]:
        """Get all registered runbooks."""
        return list(self._runbooks.values())

    def search(self, query: str) -> List[Runbook]:
        """Search runbooks by keyword (title, description, tags)."""
        query_lower = query.lower()
        results = []
        for rb in self._runbooks.values():
            if (query_lower in rb.title.lower() or
                query_lower in rb.description.lower() or
                any(query_lower in t for t in rb.tags)):
                results.append(rb)
        return results

    def register(self, runbook: Runbook) -> None:
        """Register a custom runbook."""
        self._runbooks[runbook.alert_key] = runbook
        logger.info("[RUNBOOK] Registered: %s", runbook.alert_key)

    def get_categories(self) -> Dict[str, int]:
        """Get runbook count by category."""
        counts: Dict[str, int] = {}
        for rb in self._runbooks.values():
            counts[rb.category] = counts.get(rb.category, 0) + 1
        return counts

    def to_list(self) -> List[Dict[str, Any]]:
        """Serialize all runbooks for API response."""
        return [rb.to_dict() for rb in self._runbooks.values()]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_registry_instance: Optional[RunbookRegistry] = None


def get_runbook_registry() -> RunbookRegistry:
    """Get the global RunbookRegistry singleton."""
    global _registry_instance
    if _registry_instance is None:
        _registry_instance = RunbookRegistry()
    return _registry_instance
