"""Latency Budgets — per-tool timeouts with fallback paths.

Assigns each tool a latency budget (maximum execution time) and tracks
actual latency to detect degradation. Integrates with circuit breakers
to auto-disable tools that consistently exceed their budgets.

Features:
- Per-tool timeout configuration (default + overrides)
- Latency tracking with percentile computation (p50, p95, p99)
- Budget violation detection and alerting
- Fallback path configuration (what to do when a tool times out)
- Integration point for circuit breaker

Usage:
    from chat_app.latency_budgets import get_latency_tracker

    tracker = get_latency_tracker()

    # Get timeout for a tool
    timeout = tracker.get_timeout("splunk_search")  # e.g., 30.0

    # Record actual latency
    tracker.record("splunk_search", latency_ms=1250.5)

    # Check if tool is within budget
    report = tracker.get_report("splunk_search")
"""

import logging
import math
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default timeouts per tool category (seconds)
# ---------------------------------------------------------------------------

_DEFAULT_TIMEOUT = 30.0  # Default for unknown tools

_TOOL_TIMEOUTS: Dict[str, float] = {
    # Fast tools (< 5s)
    "base64_encode": 2.0,
    "base64_decode": 2.0,
    "url_encode": 2.0,
    "url_decode": 2.0,
    "json_prettify": 2.0,
    "json_minify": 2.0,
    "md5": 2.0,
    "sha256": 2.0,
    "timestamp_convert": 2.0,
    "uuid_generate": 2.0,
    "regex_test": 5.0,
    "validate_spl": 5.0,

    # Medium tools (5-30s)
    "splunk_search": 30.0,
    "knowledge_graph_query": 10.0,
    "explain_spl": 15.0,
    "health_check": 10.0,
    "collection_stats": 10.0,
    "list_saved_searches": 15.0,
    "list_indexes": 15.0,
    "get_splunk_health": 15.0,

    # Slow tools (30-120s)
    "ingest_document": 120.0,
    "reindex_collection": 120.0,
    "create_collection": 60.0,
    "rebuild_knowledge_graph": 120.0,
    "create_backup": 60.0,
    "restore_backup": 120.0,

    # External tools (variable, generous timeout)
    "deploy_pipeline": 60.0,
    "update_saved_search": 30.0,
    "create_saved_search": 30.0,
    "send_hec_event": 15.0,
}

# Fallback paths: tool -> fallback tool or action
_FALLBACK_PATHS: Dict[str, str] = {
    "splunk_search": "cached_search",
    "knowledge_graph_query": "vector_search",
    "explain_spl": "static_docs",
    "deploy_pipeline": "queue_for_retry",
}


# ---------------------------------------------------------------------------
# Latency sample window
# ---------------------------------------------------------------------------

_MAX_SAMPLES = 100  # Per-tool sample window


@dataclass
class _LatencySamples:
    """Sliding window of latency samples for a single tool."""
    tool: str
    samples: deque = field(default_factory=lambda: deque(maxlen=_MAX_SAMPLES))
    total_calls: int = 0
    violations: int = 0  # Exceeded budget
    timeout_budget: float = _DEFAULT_TIMEOUT

    def add(self, latency_ms: float) -> bool:
        """Add a sample. Returns True if this violates the budget."""
        self.samples.append(latency_ms)
        self.total_calls += 1
        exceeded = latency_ms > (self.timeout_budget * 1000)
        if exceeded:
            self.violations += 1
        return exceeded

    def percentile(self, p: float) -> float:
        """Compute the pth percentile of latency samples."""
        if not self.samples:
            return 0.0
        sorted_samples = sorted(self.samples)
        idx = (p / 100.0) * (len(sorted_samples) - 1)
        lower = int(math.floor(idx))
        upper = int(math.ceil(idx))
        if lower == upper:
            return sorted_samples[lower]
        frac = idx - lower
        return sorted_samples[lower] * (1 - frac) + sorted_samples[upper] * frac

    def stats(self) -> Dict[str, Any]:
        """Compute latency statistics."""
        if not self.samples:
            return {
                "tool": self.tool,
                "samples": 0,
                "total_calls": self.total_calls,
            }
        sample_list = list(self.samples)
        return {
            "tool": self.tool,
            "samples": len(sample_list),
            "total_calls": self.total_calls,
            "violations": self.violations,
            "violation_rate": round(self.violations / self.total_calls, 3) if self.total_calls > 0 else 0.0,
            "timeout_budget_ms": self.timeout_budget * 1000,
            "min_ms": round(min(sample_list), 1),
            "max_ms": round(max(sample_list), 1),
            "mean_ms": round(sum(sample_list) / len(sample_list), 1),
            "p50_ms": round(self.percentile(50), 1),
            "p95_ms": round(self.percentile(95), 1),
            "p99_ms": round(self.percentile(99), 1),
            "within_budget": self.percentile(95) <= (self.timeout_budget * 1000),
        }


# ---------------------------------------------------------------------------
# Latency Tracker
# ---------------------------------------------------------------------------

class LatencyTracker:
    """Tracks per-tool latency with budget enforcement."""

    def __init__(self):
        self._tools: Dict[str, _LatencySamples] = {}
        self._lock = threading.Lock()

    def _get_or_create(self, tool_name: str) -> _LatencySamples:
        if tool_name not in self._tools:
            with self._lock:
                if tool_name not in self._tools:
                    timeout = _TOOL_TIMEOUTS.get(tool_name, _DEFAULT_TIMEOUT)
                    self._tools[tool_name] = _LatencySamples(tool=tool_name, timeout_budget=timeout)
        return self._tools[tool_name]

    def get_timeout(self, tool_name: str) -> float:
        """Get the timeout budget (seconds) for a tool."""
        return _TOOL_TIMEOUTS.get(tool_name, _DEFAULT_TIMEOUT)

    def set_timeout(self, tool_name: str, timeout_seconds: float) -> None:
        """Override the timeout for a tool."""
        _TOOL_TIMEOUTS[tool_name] = timeout_seconds
        samples = self._tools.get(tool_name)
        if samples:
            samples.timeout_budget = timeout_seconds

    def get_fallback(self, tool_name: str) -> Optional[str]:
        """Get the fallback path for a tool (if configured)."""
        return _FALLBACK_PATHS.get(tool_name)

    def set_fallback(self, tool_name: str, fallback: str) -> None:
        """Set a fallback path for a tool."""
        _FALLBACK_PATHS[tool_name] = fallback

    def record(self, tool_name: str, latency_ms: float) -> bool:
        """Record a latency measurement. Returns True if budget was violated."""
        samples = self._get_or_create(tool_name)
        violated = samples.add(latency_ms)
        if violated:
            logger.warning(
                "[LATENCY] %s exceeded budget: %.1fms > %.0fms",
                tool_name, latency_ms, samples.timeout_budget * 1000,
            )
        return violated

    def get_report(self, tool_name: str) -> Dict[str, Any]:
        """Get latency report for a tool."""
        samples = self._tools.get(tool_name)
        if not samples:
            return {
                "tool": tool_name,
                "samples": 0,
                "timeout_budget_ms": _TOOL_TIMEOUTS.get(tool_name, _DEFAULT_TIMEOUT) * 1000,
                "fallback": _FALLBACK_PATHS.get(tool_name),
            }
        report = samples.stats()
        report["fallback"] = _FALLBACK_PATHS.get(tool_name)
        return report

    def get_all_reports(self) -> List[Dict[str, Any]]:
        """Get latency reports for all tracked tools."""
        return [s.stats() for s in self._tools.values()]

    def get_violations(self) -> List[Dict[str, Any]]:
        """Get tools that are currently violating their budget (p95 > timeout)."""
        violations = []
        for samples in self._tools.values():
            stats = samples.stats()
            if stats.get("samples", 0) > 0 and not stats.get("within_budget", True):
                stats["fallback"] = _FALLBACK_PATHS.get(samples.tool)
                violations.append(stats)
        return violations

    def get_summary(self) -> Dict[str, Any]:
        """Get aggregate latency summary."""
        total_tools = len(self._tools)
        total_calls = sum(s.total_calls for s in self._tools.values())
        total_violations = sum(s.violations for s in self._tools.values())
        within_budget = sum(
            1 for s in self._tools.values()
            if s.samples and s.percentile(95) <= (s.timeout_budget * 1000)
        )
        tracked_with_data = sum(1 for s in self._tools.values() if s.samples)

        return {
            "total_tools_tracked": total_tools,
            "total_calls": total_calls,
            "total_violations": total_violations,
            "violation_rate": round(total_violations / total_calls, 3) if total_calls > 0 else 0.0,
            "tools_within_budget": within_budget,
            "tools_exceeding_budget": tracked_with_data - within_budget,
            "configured_timeouts": len(_TOOL_TIMEOUTS),
            "configured_fallbacks": len(_FALLBACK_PATHS),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_all_timeouts(self) -> Dict[str, float]:
        """Return all configured timeouts."""
        return dict(_TOOL_TIMEOUTS)

    def get_all_fallbacks(self) -> Dict[str, str]:
        """Return all configured fallback paths."""
        return dict(_FALLBACK_PATHS)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_tracker_instance: Optional[LatencyTracker] = None
_tracker_lock = threading.Lock()


def get_latency_tracker() -> LatencyTracker:
    """Get the global LatencyTracker singleton."""
    global _tracker_instance
    if _tracker_instance is None:
        with _tracker_lock:
            if _tracker_instance is None:
                _tracker_instance = LatencyTracker()
    return _tracker_instance
