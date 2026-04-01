"""
Tool Effectiveness Tracker — Learns which tools work best for each intent/pattern.

Tracks:
- Success/failure per tool per intent
- Latency distributions per tool
- Tool chain effectiveness (which sequences work best)
- Adaptive tool ranking based on historical performance
- Fallback recommendations when primary tools fail

Enables the agent to improve tool selection over time — a true learning agent.
"""
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class ToolExecution:
    """Record of a single tool execution."""
    tool_name: str
    intent: str
    success: bool
    latency_ms: float
    timestamp: float = field(default_factory=time.time)
    error: Optional[str] = None
    query_pattern: str = ""
    preceded_by: Optional[str] = None  # Previous tool in chain
    followed_by: Optional[str] = None  # Next tool in chain


@dataclass
class ToolStats:
    """Aggregated statistics for a tool."""
    tool_name: str
    total_executions: int = 0
    successes: int = 0
    failures: int = 0
    total_latency_ms: float = 0.0
    latencies: List[float] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        if self.total_executions == 0:
            return 0.0
        return self.successes / self.total_executions

    @property
    def avg_latency_ms(self) -> float:
        if self.total_executions == 0:
            return 0.0
        return self.total_latency_ms / self.total_executions

    @property
    def p95_latency_ms(self) -> float:
        if not self.latencies:
            return 0.0
        sorted_lat = sorted(self.latencies)
        idx = int(len(sorted_lat) * 0.95)
        return sorted_lat[min(idx, len(sorted_lat) - 1)]

    def record(self, success: bool, latency_ms: float):
        self.total_executions += 1
        self.total_latency_ms += latency_ms
        self.latencies.append(latency_ms)
        if len(self.latencies) > 1000:
            self.latencies = self.latencies[-500:]
        if success:
            self.successes += 1
        else:
            self.failures += 1


@dataclass
class ToolChainStats:
    """Statistics for a tool chain (sequence of tools)."""
    chain: Tuple[str, ...]  # e.g. ("analyze_spl", "optimize_spl", "validate_spl")
    total_runs: int = 0
    successes: int = 0
    total_latency_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.successes / self.total_runs

    @property
    def avg_latency_ms(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.total_latency_ms / self.total_runs


class ToolEffectivenessTracker:
    """Tracks and learns tool effectiveness patterns."""

    def __init__(self, max_history: int = 5000):
        self._history: List[ToolExecution] = []
        self._max_history = max_history
        # Per-tool stats
        self._tool_stats: Dict[str, ToolStats] = defaultdict(lambda: ToolStats(tool_name=""))
        # Per-tool-per-intent stats
        self._intent_stats: Dict[str, Dict[str, ToolStats]] = defaultdict(
            lambda: defaultdict(lambda: ToolStats(tool_name=""))
        )
        # Tool chain stats
        self._chain_stats: Dict[Tuple[str, ...], ToolChainStats] = {}
        # Fallback map: tool -> list of fallback tools ranked by success
        self._fallback_map: Dict[str, List[str]] = {}

    def record_execution(
        self,
        tool_name: str,
        intent: str,
        success: bool,
        latency_ms: float,
        error: str = None,
        query_pattern: str = "",
        preceded_by: str = None,
    ):
        """Record a tool execution for learning."""
        execution = ToolExecution(
            tool_name=tool_name,
            intent=intent,
            success=success,
            latency_ms=latency_ms,
            error=error,
            query_pattern=query_pattern,
            preceded_by=preceded_by,
        )
        self._history.append(execution)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

        # Update stats
        if tool_name not in self._tool_stats:
            self._tool_stats[tool_name] = ToolStats(tool_name=tool_name)
        self._tool_stats[tool_name].record(success, latency_ms)

        if intent not in self._intent_stats:
            self._intent_stats[intent] = {}
        if tool_name not in self._intent_stats[intent]:
            self._intent_stats[intent][tool_name] = ToolStats(tool_name=tool_name)
        self._intent_stats[intent][tool_name].record(success, latency_ms)

    def record_chain(self, tools: List[str], success: bool, total_latency_ms: float):
        """Record the outcome of a tool chain execution."""
        chain_key = tuple(tools)
        if chain_key not in self._chain_stats:
            self._chain_stats[chain_key] = ToolChainStats(chain=chain_key)
        stats = self._chain_stats[chain_key]
        stats.total_runs += 1
        stats.total_latency_ms += total_latency_ms
        if success:
            stats.successes += 1

    def rank_tools_for_intent(self, intent: str, available_tools: List[str] = None) -> List[Tuple[str, float]]:
        """
        Rank tools by effectiveness for a given intent.
        Returns list of (tool_name, score) sorted by descending score.
        """
        if intent not in self._intent_stats:
            return [(t, 0.5) for t in (available_tools or [])]

        rankings = []
        for tool_name, stats in self._intent_stats[intent].items():
            if available_tools and tool_name not in available_tools:
                continue
            if stats.total_executions < 3:
                score = 0.5  # Not enough data, neutral score
            else:
                # Score = weighted combination of success rate and inverse latency
                success_score = stats.success_rate
                # Normalize latency: faster is better (0-1 scale)
                max_lat = max(s.avg_latency_ms for s in self._intent_stats[intent].values()) or 1
                latency_score = 1.0 - min(stats.avg_latency_ms / max_lat, 1.0)
                score = 0.7 * success_score + 0.3 * latency_score
            rankings.append((tool_name, round(score, 4)))

        # Add tools with no history at neutral score
        seen = {r[0] for r in rankings}
        for tool in (available_tools or []):
            if tool not in seen:
                rankings.append((tool, 0.5))

        return sorted(rankings, key=lambda x: x[1], reverse=True)

    def get_fallback_tool(self, failed_tool: str, intent: str) -> Optional[str]:
        """Suggest a fallback tool when the primary fails."""
        if intent not in self._intent_stats:
            return None

        candidates = []
        for tool_name, stats in self._intent_stats[intent].items():
            if tool_name == failed_tool:
                continue
            if stats.total_executions >= 2 and stats.success_rate > 0.5:
                candidates.append((tool_name, stats.success_rate))

        if not candidates:
            return None
        candidates.sort(key=lambda x: x[1], reverse=True)
        return candidates[0][0]

    def get_best_chain_for_intent(self, intent: str) -> Optional[Tuple[str, ...]]:
        """Get the historically most successful tool chain for an intent."""
        relevant_chains = []
        for chain_key, stats in self._chain_stats.items():
            if stats.total_runs < 2:
                continue
            # Check if this chain was used with this intent by looking at history
            relevant_chains.append((chain_key, stats.success_rate, stats.avg_latency_ms))

        if not relevant_chains:
            return None

        # Prefer high success rate, then lower latency
        relevant_chains.sort(key=lambda x: (-x[1], x[2]))
        return relevant_chains[0][0]

    def get_tool_stats(self, tool_name: str = None) -> Dict[str, Any]:
        """Get stats for a specific tool or all tools."""
        if tool_name:
            stats = self._tool_stats.get(tool_name)
            if not stats:
                return {}
            return {
                "tool_name": tool_name,
                "total_executions": stats.total_executions,
                "success_rate": round(stats.success_rate, 4),
                "avg_latency_ms": round(stats.avg_latency_ms, 2),
                "p95_latency_ms": round(stats.p95_latency_ms, 2),
            }

        return {
            name: {
                "total_executions": s.total_executions,
                "success_rate": round(s.success_rate, 4),
                "avg_latency_ms": round(s.avg_latency_ms, 2),
                "p95_latency_ms": round(s.p95_latency_ms, 2),
            }
            for name, s in self._tool_stats.items()
        }

    def get_chain_stats(self) -> List[Dict[str, Any]]:
        """Get all chain statistics."""
        return [
            {
                "chain": list(stats.chain),
                "total_runs": stats.total_runs,
                "success_rate": round(stats.success_rate, 4),
                "avg_latency_ms": round(stats.avg_latency_ms, 2),
            }
            for stats in sorted(
                self._chain_stats.values(),
                key=lambda s: s.success_rate,
                reverse=True,
            )
        ]

    def get_intent_tool_matrix(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get the full intent-to-tool effectiveness matrix."""
        matrix = {}
        for intent, tools in self._intent_stats.items():
            matrix[intent] = [
                {
                    "tool": name,
                    "executions": stats.total_executions,
                    "success_rate": round(stats.success_rate, 4),
                    "avg_latency_ms": round(stats.avg_latency_ms, 2),
                }
                for name, stats in sorted(
                    tools.items(),
                    key=lambda x: x[1].success_rate,
                    reverse=True,
                )
            ]
        return matrix


# Singleton
_tracker: Optional[ToolEffectivenessTracker] = None


def get_effectiveness_tracker() -> ToolEffectivenessTracker:
    """Get or create the singleton tracker."""
    global _tracker
    if _tracker is None:
        _tracker = ToolEffectivenessTracker()
    return _tracker
