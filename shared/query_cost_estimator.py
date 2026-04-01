"""
Real-Time Query Cost Estimation

Estimates query cost before execution using multiple factors:
- Volume: How many events will be scanned? (index scope, time range)
- Cardinality: How many unique values in BY clauses?
- Command complexity: Per-command cost weights
- Memory footprint: Memory-intensive operations
- CPU intensity: Regex, ML, complex expressions
- Distribution: Whether query can run distributed on indexers

Cost scale 0-100:
- 0-20:  Trivial (instant, sub-second)
- 21-40: Light (< 5 seconds)
- 41-60: Moderate (5-30 seconds)
- 61-80: Heavy (30-120 seconds)
- 81-100: Extreme (> 2 minutes, may timeout)
"""

from __future__ import annotations

import re
from typing import Any, Dict

from shared.constants import COMMAND_COSTS
from shared.utils import estimate_cardinality, parse_relative_time

# Cost thresholds for memory-heavy commands (scaled to 0-100 per-command)
_MEMORY_COSTS: dict[str, int] = {
    "transaction": 40, "join": 30, "eventstats": 25,
    "streamstats": 15, "sort": 20, "dedup": 15,
    "cluster": 35, "kmeans": 40, "anomalydetection": 30,
    "append": 15, "appendcols": 20, "map": 25,
    "mvexpand": 10, "selfjoin": 20,
}

# Cost thresholds for CPU-heavy commands (scaled to 0-100 per-command)
_CPU_COSTS: dict[str, int] = {
    "rex": 20, "regex": 20, "spath": 15, "xmlkv": 15,
    "cluster": 30, "kmeans": 35, "anomalydetection": 35,
    "predict": 25, "transaction": 15, "erex": 25,
    "foreach": 10,
}


def _cmd_name(cmd: Any) -> str:
    """Extract command name from either an object or dict."""
    if hasattr(cmd, "name"):
        return cmd.name
    if isinstance(cmd, dict):
        return cmd.get("name", "")
    return ""


class QueryCostEstimator:
    """Estimate query cost before execution."""

    def __init__(self, splunk_metadata: Dict[str, Any] | None = None):
        self.splunk_metadata = splunk_metadata or {}

    def estimate(self, result: Any) -> Dict[str, Any]:
        """
        Full cost estimation.

        Returns dict with total_cost (0-100) and breakdown.
        """
        volume = self._estimate_volume_cost(result)
        command = self._estimate_command_cost(result)
        cardinality = self._estimate_cardinality_cost(result)
        time = self._estimate_time_range_cost(result)
        memory = self._estimate_memory_cost(result)
        cpu = self._estimate_cpu_cost(result)

        total_cost = int(min(100, max(0,
            volume * 0.25 + command * 0.20 + cardinality * 0.15 +
            time * 0.15 + memory * 0.15 + cpu * 0.10
        )))

        costs = {
            "volume": volume, "commands": command, "cardinality": cardinality,
            "time_range": time, "memory": memory, "cpu": cpu,
        }
        bottlenecks = [f"{n} ({c}/100)" for n, c in
                       sorted(costs.items(), key=lambda x: x[1], reverse=True)
                       if c >= 60]

        recommendations = []
        if volume >= 60:
            recommendations.append("Narrow index scope — specify exact index names")
        if time >= 60:
            recommendations.append("Add or narrow time range (earliest/latest)")
        if cardinality >= 50:
            recommendations.append("High-cardinality BY fields — add limits or pre-filter")
        if memory >= 60:
            recommendations.append("Memory-intensive commands — consider alternatives or add limits")
        if command >= 60:
            recommendations.append("Expensive commands — consider tstats, lookup, or stats alternatives")
        if cpu >= 50:
            recommendations.append("CPU-intensive regex/ML — pre-filter to reduce event count")

        if total_cost <= 20:
            runtime = "< 1 second"
        elif total_cost <= 40:
            runtime = "1-5 seconds"
        elif total_cost <= 60:
            runtime = "5-30 seconds"
        elif total_cost <= 80:
            runtime = "30-120 seconds"
        else:
            runtime = "> 2 minutes (may timeout)"

        return {
            "total_cost": total_cost,
            "volume_cost": volume,
            "command_cost": command,
            "cardinality_cost": cardinality,
            "time_cost": time,
            "memory_cost": memory,
            "cpu_cost": cpu,
            "bottlenecks": bottlenecks,
            "recommendations": recommendations,
            "estimated_runtime": runtime,
        }

    def _estimate_volume_cost(self, result: Any) -> int:
        """Estimate cost based on data volume scanned."""
        components = getattr(result, "parsed_components", {})
        if not components:
            return 50

        if components.get("has_index_wildcard"):
            return 100
        indexes = components.get("indexes", [])
        if not indexes:
            return 80
        if len(indexes) > 3:
            return 60
        if len(indexes) > 1:
            return 40
        if components.get("sourcetypes"):
            return 15
        return 25

    def _estimate_command_cost(self, result: Any) -> int:
        """Estimate cost based on commands used."""
        commands = getattr(result, "commands", None)
        if not commands:
            return 10

        total = sum(COMMAND_COSTS.get(_cmd_name(cmd), 5) for cmd in commands)
        # 10 commands * avg cost 5 = 50, normalized to 0-100
        return min(100, int(total * 100 / 50))

    def _estimate_cardinality_cost(self, result: Any) -> int:
        """Estimate cost based on BY clause field cardinality."""
        cost = 0
        aggregation_cmds = {"stats", "chart", "timechart", "eventstats", "streamstats", "top", "rare"}

        for cmd in getattr(result, "commands", []):
            name = _cmd_name(cmd)
            if name not in aggregation_cmds:
                continue
            args = cmd.args if hasattr(cmd, "args") else cmd.get("args", "")
            by_match = re.search(r"\bby\s+(.+?)(?:\s*$|\s*\|)", args, re.IGNORECASE)
            if not by_match:
                continue
            fields = [f.strip() for f in re.split(r"[,\s]+", by_match.group(1))
                      if f.strip() and not f.startswith("span=")]
            for f in fields:
                card = estimate_cardinality(f)
                if card == "very_high":
                    cost += 30
                elif card == "high":
                    cost += 15
                else:
                    cost += 5
            if len(fields) >= 3:
                cost = int(cost * 1.5)

        return min(100, cost)

    def _estimate_time_range_cost(self, result: Any) -> int:
        """Estimate cost based on time range."""
        components = getattr(result, "parsed_components", {})
        if not components:
            return 50
        if not components.get("has_time_constraint"):
            return 30  # UI time picker likely handles it

        earliest = components.get("time_earliest", "")
        if not earliest:
            return 50

        seconds = parse_relative_time(earliest)
        if seconds is None:
            return 30

        seconds = abs(seconds)
        if seconds == 0:
            return 100

        if seconds <= 3600:
            return 10
        elif seconds <= 86400:
            return 30
        elif seconds <= 604800:
            return 50
        elif seconds <= 2592000:
            return 70
        elif seconds <= 7776000:
            return 85
        else:
            return 95

    def _estimate_memory_cost(self, result: Any) -> int:
        """Estimate memory footprint cost."""
        cost = sum(
            _MEMORY_COSTS[_cmd_name(cmd)]
            for cmd in getattr(result, "commands", [])
            if _cmd_name(cmd) in _MEMORY_COSTS
        )
        return min(100, cost)

    def _estimate_cpu_cost(self, result: Any) -> int:
        """Estimate CPU intensity cost."""
        cost = sum(
            _CPU_COSTS[_cmd_name(cmd)]
            for cmd in getattr(result, "commands", [])
            if _cmd_name(cmd) in _CPU_COSTS
        )
        return min(100, cost)
