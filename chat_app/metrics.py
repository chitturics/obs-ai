"""
Metrics and observability for the Splunk Assistant.

Provides in-memory counters and timing utilities.
"""
import time
import logging
from collections import defaultdict
from contextlib import contextmanager
from typing import Dict, Any

logger = logging.getLogger(__name__)


class Metrics:
    """In-memory metrics collector."""

    def __init__(self):
        self.counters: Dict[str, int] = defaultdict(int)
        self.histograms: Dict[str, list] = defaultdict(list)
        self._max_histogram_size = 1000

    def increment(self, name: str, value: int = 1):
        """Increment a counter."""
        self.counters[name] += value

    def observe(self, name: str, value: float):
        """Record a value in a histogram."""
        h = self.histograms[name]
        h.append(value)
        if len(h) > self._max_histogram_size:
            self.histograms[name] = h[-self._max_histogram_size:]

    @contextmanager
    def timer(self, name: str):
        """Context manager to time a block and record as histogram."""
        start = time.monotonic()
        try:
            yield
        finally:
            elapsed = time.monotonic() - start
            self.observe(name, elapsed)

    def get_summary(self) -> Dict[str, Any]:
        """Get a summary of all metrics."""
        summary = {}

        # Counters
        for name, count in sorted(self.counters.items()):
            summary[name] = count

        # Histogram summaries
        for name, values in sorted(self.histograms.items()):
            if values:
                summary[f"{name}_count"] = len(values)
                summary[f"{name}_avg"] = round(sum(values) / len(values), 3)
                summary[f"{name}_max"] = round(max(values), 3)
                summary[f"{name}_min"] = round(min(values), 3)

        return summary

    def get_prometheus_summary(self) -> str:
        """Get a summary of all metrics in Prometheus format."""
        summary = self.get_summary()
        lines = []
        for key, value in summary.items():
            # Convert to Prometheus-like format
            safe_key = key.replace(".", "_").replace("-", "_")
            if isinstance(value, (int, float)):
                lines.append(f"chainlit_{safe_key} {value}")
        return "\n".join(lines)

    def reset(self):
        """Reset all metrics."""
        self.counters.clear()
        self.histograms.clear()


# Global metrics instance
_metrics = Metrics()


def get_metrics() -> Metrics:
    """Get the global metrics instance."""
    return _metrics


def get_stats_report() -> str:
    """Generate a formatted stats report for the /stats command."""
    m = _metrics
    summary = m.get_summary()

    if not summary:
        return "**Statistics**\n\nNo metrics collected yet. Start chatting to generate metrics!"

    lines = ["# Usage Statistics\n"]

    # Query counts
    query_keys = [k for k in summary if k.startswith("query_")]
    if query_keys:
        lines.append("## Queries")
        for k in sorted(query_keys):
            label = k.replace("query_", "").replace("_", " ").title()
            lines.append(f"- {label}: **{summary[k]}**")
        lines.append("")

    # Timing
    timing_keys = [k for k in summary if k.endswith("_avg")]
    if timing_keys:
        lines.append("## Performance")
        for k in sorted(timing_keys):
            base = k.replace("_avg", "")
            label = base.replace("_", " ").title()
            avg = summary.get(f"{base}_avg", 0)
            count = summary.get(f"{base}_count", 0)
            lines.append(f"- {label}: **{avg:.2f}s** avg ({count} calls)")
        lines.append("")

    # Cache
    cache_keys = [k for k in summary if k.startswith("cache_")]
    if cache_keys:
        lines.append("## Cache")
        for k in sorted(cache_keys):
            label = k.replace("cache_", "").replace("_", " ").title()
            lines.append(f"- {label}: **{summary[k]}**")
        lines.append("")

    # Errors
    error_keys = [k for k in summary if k.startswith("error_")]
    if error_keys:
        lines.append("## Errors")
        for k in sorted(error_keys):
            label = k.replace("error_", "").replace("_", " ").title()
            lines.append(f"- {label}: **{summary[k]}**")

    return "\n".join(lines)
