"""Unified SLO Tracker — availability, tool success, retrieval quality, response correctness.

Defines Service Level Objectives and tracks compliance in real time.
Each SLO has:
- A target (e.g., 99.5% availability)
- A measurement window (e.g., rolling 1 hour)
- Current compliance (good/total requests)
- Status: met, at_risk (within 5% of target), breached

Dashboard-ready output for single red/yellow/green health view.

Usage:
    from chat_app.slo_tracker import get_slo_tracker

    tracker = get_slo_tracker()
    tracker.record("tool_success", success=True)
    tracker.record("retrieval_quality", success=quality_score >= 0.7)

    dashboard = tracker.get_dashboard()
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# SLO Status
# ---------------------------------------------------------------------------

class SLOStatus(str, Enum):
    MET = "met"            # Green — within target
    AT_RISK = "at_risk"    # Yellow — within 5% of target
    BREACHED = "breached"  # Red — below target
    NO_DATA = "no_data"    # Gray — insufficient data


# ---------------------------------------------------------------------------
# SLO Definition
# ---------------------------------------------------------------------------

@dataclass
class SLODefinition:
    """Definition of a Service Level Objective."""
    name: str
    description: str
    target: float  # 0.0 to 1.0 (e.g., 0.995 = 99.5%)
    window_seconds: int = 3600  # Rolling measurement window (default 1 hour)
    min_samples: int = 10  # Minimum samples before evaluation
    category: str = "system"  # system, tool, retrieval, response


# ---------------------------------------------------------------------------
# SLO Definitions
# ---------------------------------------------------------------------------

DEFAULT_SLOS: List[SLODefinition] = [
    # System availability
    SLODefinition(
        name="system_availability",
        description="Overall system availability (health checks passing)",
        target=0.995,
        window_seconds=3600,
        category="system",
    ),
    SLODefinition(
        name="api_availability",
        description="Admin API endpoint availability",
        target=0.999,
        window_seconds=3600,
        category="system",
    ),

    # Tool execution
    SLODefinition(
        name="tool_success_rate",
        description="Tool execution success rate (no errors/timeouts)",
        target=0.95,
        window_seconds=3600,
        category="tool",
    ),
    SLODefinition(
        name="tool_latency_budget",
        description="Tool executions completing within latency budget",
        target=0.95,
        window_seconds=3600,
        category="tool",
    ),

    # Retrieval quality
    SLODefinition(
        name="retrieval_quality",
        description="Retrieval results above quality threshold (relevance >= 0.7)",
        target=0.90,
        window_seconds=3600,
        category="retrieval",
    ),
    SLODefinition(
        name="retrieval_latency",
        description="Retrieval completing within 5 seconds",
        target=0.95,
        window_seconds=3600,
        category="retrieval",
    ),

    # Response quality
    SLODefinition(
        name="response_correctness",
        description="Responses rated correct by feedback/evaluation",
        target=0.90,
        window_seconds=86400,  # 24-hour window for feedback-based SLOs
        min_samples=20,
        category="response",
    ),
    SLODefinition(
        name="response_latency",
        description="End-to-end response time within 15 seconds",
        target=0.90,
        window_seconds=3600,
        category="response",
    ),
]


# ---------------------------------------------------------------------------
# SLO sample
# ---------------------------------------------------------------------------

@dataclass
class _Sample:
    timestamp: float  # monotonic time
    success: bool


# ---------------------------------------------------------------------------
# SLO instance (runtime state)
# ---------------------------------------------------------------------------

class _SLOInstance:
    """Runtime state for a single SLO."""

    def __init__(self, definition: SLODefinition):
        self.definition = definition
        self.samples: deque = deque()
        self._lock = threading.Lock()

    def record(self, success: bool) -> None:
        with self._lock:
            self.samples.append(_Sample(timestamp=time.monotonic(), success=success))

    def _trim(self) -> None:
        """Remove samples outside the window."""
        cutoff = time.monotonic() - self.definition.window_seconds
        while self.samples and self.samples[0].timestamp < cutoff:
            self.samples.popleft()

    def evaluate(self) -> Dict[str, Any]:
        """Evaluate current SLO compliance."""
        with self._lock:
            self._trim()
            samples = list(self.samples)

        total = len(samples)
        good = sum(1 for s in samples if s.success)

        if total < self.definition.min_samples:
            status = SLOStatus.NO_DATA
            compliance = 0.0
        else:
            compliance = good / total
            target = self.definition.target
            if compliance >= target:
                status = SLOStatus.MET
            elif compliance >= target - 0.05:
                status = SLOStatus.AT_RISK
            else:
                status = SLOStatus.BREACHED

        return {
            "name": self.definition.name,
            "description": self.definition.description,
            "target": self.definition.target,
            "target_pct": f"{self.definition.target * 100:.1f}%",
            "compliance": round(compliance, 4),
            "compliance_pct": f"{compliance * 100:.1f}%" if total >= self.definition.min_samples else "N/A",
            "status": status.value,
            "good": good,
            "total": total,
            "window_seconds": self.definition.window_seconds,
            "category": self.definition.category,
            "min_samples": self.definition.min_samples,
            "error_budget_remaining": round(max(0, compliance - self.definition.target), 4) if total >= self.definition.min_samples else None,
        }


# ---------------------------------------------------------------------------
# SLO Tracker
# ---------------------------------------------------------------------------

class SLOTracker:
    """Tracks all SLOs and provides dashboard-ready output."""

    def __init__(self, slo_definitions: Optional[List[SLODefinition]] = None):
        self._instances: Dict[str, _SLOInstance] = {}
        definitions = slo_definitions or DEFAULT_SLOS
        for slo_def in definitions:
            self._instances[slo_def.name] = _SLOInstance(slo_def)

    def record(self, slo_name: str, success: bool) -> None:
        """Record a sample for an SLO."""
        instance = self._instances.get(slo_name)
        if instance:
            instance.record(success)
        else:
            logger.debug("[SLO] Unknown SLO: %s", slo_name)

    def evaluate(self, slo_name: str) -> Optional[Dict[str, Any]]:
        """Evaluate a single SLO."""
        instance = self._instances.get(slo_name)
        return instance.evaluate() if instance else None

    def evaluate_all(self) -> List[Dict[str, Any]]:
        """Evaluate all SLOs."""
        return [inst.evaluate() for inst in self._instances.values()]

    def get_dashboard(self) -> Dict[str, Any]:
        """Get a dashboard-ready view of all SLOs.

        Returns overall status (worst SLO determines color), per-category
        breakdown, and list of breached SLOs for action.
        """
        evaluations = self.evaluate_all()

        # Overall status: worst status wins
        statuses = [e["status"] for e in evaluations if e["status"] != SLOStatus.NO_DATA.value]
        if not statuses:
            overall = SLOStatus.NO_DATA.value
        elif SLOStatus.BREACHED.value in statuses:
            overall = SLOStatus.BREACHED.value
        elif SLOStatus.AT_RISK.value in statuses:
            overall = SLOStatus.AT_RISK.value
        else:
            overall = SLOStatus.MET.value

        # Status color mapping
        color_map = {
            SLOStatus.MET.value: "green",
            SLOStatus.AT_RISK.value: "yellow",
            SLOStatus.BREACHED.value: "red",
            SLOStatus.NO_DATA.value: "gray",
        }

        # Per-category breakdown
        categories: Dict[str, Dict[str, Any]] = {}
        for e in evaluations:
            cat = e["category"]
            if cat not in categories:
                categories[cat] = {"slos": [], "worst_status": SLOStatus.MET.value}
            categories[cat]["slos"].append(e)
            if _status_priority(e["status"]) > _status_priority(categories[cat]["worst_status"]):
                categories[cat]["worst_status"] = e["status"]

        # Breached SLOs for action
        breached = [e for e in evaluations if e["status"] == SLOStatus.BREACHED.value]
        at_risk = [e for e in evaluations if e["status"] == SLOStatus.AT_RISK.value]

        return {
            "overall_status": overall,
            "overall_color": color_map.get(overall, "gray"),
            "categories": {k: {
                "status": v["worst_status"],
                "color": color_map.get(v["worst_status"], "gray"),
                "slos": v["slos"],
            } for k, v in categories.items()},
            "breached": breached,
            "at_risk": at_risk,
            "total_slos": len(evaluations),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_slo_names(self) -> List[str]:
        """Get all registered SLO names."""
        return list(self._instances.keys())

    def add_slo(self, definition: SLODefinition) -> None:
        """Register a new SLO at runtime."""
        self._instances[definition.name] = _SLOInstance(definition)


def _status_priority(status: str) -> int:
    """Higher = worse."""
    return {
        SLOStatus.MET.value: 0,
        SLOStatus.NO_DATA.value: 1,
        SLOStatus.AT_RISK.value: 2,
        SLOStatus.BREACHED.value: 3,
    }.get(status, 0)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_tracker_instance: Optional[SLOTracker] = None
_tracker_lock = threading.Lock()


def get_slo_tracker() -> SLOTracker:
    """Get the global SLOTracker singleton."""
    global _tracker_instance
    if _tracker_instance is None:
        with _tracker_lock:
            if _tracker_instance is None:
                _tracker_instance = SLOTracker()
    return _tracker_instance
