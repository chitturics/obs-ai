"""
ObsAI Observability Stack — Tracing, SLOs, Alerting, and Metrics.

Provides:
1. Distributed tracing (spans for each pipeline stage)
2. SLO definitions and tracking (latency, quality, availability)
3. Alert rule evaluation
4. Metrics aggregation and export
5. Dashboard data for admin UI

All data is kept in-memory with configurable retention.
"""
import logging
import time
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

# Type definitions extracted to keep this file under 600 lines
from chat_app.observability_types import (  # noqa: F401
    SpanStatus, Span, Trace,
    SLOType, SLODefinition, SLOStatus,
    AlertSeverity, AlertRule, FiredAlert,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Observability Manager
# ---------------------------------------------------------------------------

class ObservabilityManager:
    """Central manager for tracing, SLOs, alerting, and metrics."""

    def __init__(self, max_traces: int = 500, max_alerts: int = 200):
        # Tracing
        self._traces: deque = deque(maxlen=max_traces)
        self._active_traces: Dict[str, Trace] = {}

        # SLOs
        self._slo_definitions: Dict[str, SLODefinition] = {}
        self._slo_data: Dict[str, List[Tuple[float, float]]] = defaultdict(list)  # name -> [(timestamp, value)]
        self._init_default_slos()

        # Alerting
        self._alert_rules: Dict[str, AlertRule] = {}
        self._fired_alerts: deque = deque(maxlen=max_alerts)
        self._init_default_alerts()

        # Metrics
        self._counters: Dict[str, int] = defaultdict(int)
        self._gauges: Dict[str, float] = {}
        self._histograms: Dict[str, List[float]] = defaultdict(list)

    def _init_default_slos(self):
        """Initialize default SLO definitions."""
        defaults = [
            SLODefinition(
                name="response_latency_p95",
                slo_type=SLOType.LATENCY,
                target=0.95,
                latency_threshold_ms=10000,
                description="95% of requests complete within 10 seconds",
            ),
            SLODefinition(
                name="response_quality",
                slo_type=SLOType.QUALITY,
                target=0.80,
                description="80% of responses score >= 0.5 quality",
            ),
            SLODefinition(
                name="availability",
                slo_type=SLOType.AVAILABILITY,
                target=0.995,
                description="99.5% of requests succeed (no errors)",
            ),
            SLODefinition(
                name="error_rate",
                slo_type=SLOType.ERROR_RATE,
                target=0.01,
                description="Less than 1% of requests result in errors",
            ),
        ]
        for slo in defaults:
            self._slo_definitions[slo.name] = slo

    def _init_default_alerts(self):
        """Initialize default alert rules."""
        defaults = [
            AlertRule(
                name="high_latency",
                condition="P95 response latency > 15 seconds",
                severity=AlertSeverity.WARNING,
                metric="latency_p95_ms",
                threshold=15000,
            ),
            AlertRule(
                name="critical_latency",
                condition="P95 response latency > 30 seconds",
                severity=AlertSeverity.CRITICAL,
                metric="latency_p95_ms",
                threshold=30000,
            ),
            AlertRule(
                name="high_error_rate",
                condition="Error rate > 5%",
                severity=AlertSeverity.WARNING,
                metric="error_rate",
                threshold=0.05,
            ),
            AlertRule(
                name="low_quality",
                condition="Average quality score < 0.4",
                severity=AlertSeverity.WARNING,
                metric="avg_quality",
                threshold=0.4,
                operator="<",
            ),
            AlertRule(
                name="slo_breach",
                condition="Any SLO is breached",
                severity=AlertSeverity.CRITICAL,
                metric="slo_breaches",
                threshold=0,
            ),
        ]
        for rule in defaults:
            self._alert_rules[rule.name] = rule

    # --- Tracing ---

    def start_trace(self, query: str = "", user_id: str = None, intent: str = "") -> Trace:
        """Start a new trace for a request."""
        trace = Trace(query=query, user_id=user_id, intent=intent)
        self._active_traces[trace.trace_id] = trace
        return trace

    def finish_trace(self, trace_id: str):
        """Finish a trace and move it to completed."""
        trace = self._active_traces.pop(trace_id, None)
        if trace:
            self._traces.append(trace)
            # Record metrics from trace
            self._record_trace_metrics(trace)
            # Export to Splunk HEC if configured
            if _hec_enabled:
                import asyncio
                try:
                    asyncio.ensure_future(export_trace_to_splunk(trace.to_dict()))
                except RuntimeError:
                    pass  # No running event loop (e.g., during tests)

    def get_trace(self, trace_id: str) -> Optional[Trace]:
        """Get a trace by ID (active or completed)."""
        if trace_id in self._active_traces:
            return self._active_traces[trace_id]
        for trace in reversed(self._traces):
            if trace.trace_id == trace_id:
                return trace
        return None

    def get_recent_traces(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get recent completed traces."""
        traces = list(self._traces)[-limit:]
        return [t.to_dict() for t in reversed(traces)]

    def _record_trace_metrics(self, trace: Trace):
        """Record metrics from a completed trace."""
        self._counters["traces_total"] += 1
        self._histograms["trace_duration_ms"].append(trace.total_duration_ms)

        if trace.has_errors:
            self._counters["traces_with_errors"] += 1

        for span in trace.spans:
            self._counters[f"span_{span.operation}_total"] += 1
            self._histograms[f"span_{span.operation}_ms"].append(span.duration_ms)

    # --- SLO Tracking ---

    def record_slo_data(self, slo_name: str, value: float):
        """Record a data point for an SLO."""
        if slo_name in self._slo_definitions:
            self._slo_data[slo_name].append((time.time(), value))
            # Trim old data (keep last 2 hours)
            cutoff = time.time() - 7200
            self._slo_data[slo_name] = [
                (t, v) for t, v in self._slo_data[slo_name] if t > cutoff
            ]

    def get_slo_status(self, slo_name: str = None) -> List[SLOStatus]:
        """Get current status for one or all SLOs."""
        results = []
        definitions = (
            {slo_name: self._slo_definitions[slo_name]}
            if slo_name and slo_name in self._slo_definitions
            else self._slo_definitions
        )

        for name, defn in definitions.items():
            data = self._slo_data.get(name, [])
            window_cutoff = time.time() - defn.window_seconds
            window_data = [(t, v) for t, v in data if t > window_cutoff]

            if not window_data:
                results.append(SLOStatus(definition=defn))
                continue

            values = [v for _, v in window_data]

            if defn.slo_type == SLOType.LATENCY:
                # % of requests under threshold
                within = sum(1 for v in values if v <= defn.latency_threshold_ms)
                current = within / len(values)
            elif defn.slo_type == SLOType.QUALITY:
                # % of responses meeting quality bar
                good = sum(1 for v in values if v >= 0.5)
                current = good / len(values)
            elif defn.slo_type == SLOType.AVAILABILITY:
                # % of successful requests (value = 1 for success, 0 for failure)
                current = sum(values) / len(values)
            elif defn.slo_type == SLOType.ERROR_RATE:
                # Error rate (lower is better)
                current = 1.0 - (sum(values) / len(values))
            else:
                current = sum(values) / len(values)

            is_met = current >= defn.target if defn.slo_type != SLOType.ERROR_RATE else current <= defn.target
            budget = max(0, (current - defn.target) / (1 - defn.target)) if defn.target < 1 else (1.0 if is_met else 0.0)

            results.append(SLOStatus(
                definition=defn,
                current_value=current,
                is_met=is_met,
                error_budget_remaining=budget,
                sample_count=len(values),
            ))

        return results

    # --- Alerting ---

    def evaluate_alerts(self) -> List[FiredAlert]:
        """Evaluate all alert rules against current metrics."""
        fired = []

        metrics = self._compute_current_metrics()

        for name, rule in self._alert_rules.items():
            value = metrics.get(rule.metric)
            if value is None:
                continue

            if rule.should_fire(value):
                rule.fire()
                alert = FiredAlert(
                    alert_name=name,
                    severity=rule.severity,
                    metric=rule.metric,
                    value=value,
                    threshold=rule.threshold,
                    message=f"Alert: {rule.condition} (current: {value:.3f}, threshold: {rule.threshold})",
                )
                fired.append(alert)
                self._fired_alerts.append(alert)
                self._persist_alert(alert)
                self._emit_alert_prometheus(alert)
                logger.warning(f"[ALERT] {alert.message}")

        # Emit SLO status to Prometheus
        self._emit_slo_prometheus()

        # Check SLO breaches
        slo_statuses = self.get_slo_status()
        slo_breaches = sum(1 for s in slo_statuses if not s.is_met and s.sample_count > 0)
        if slo_breaches > 0:
            slo_rule = self._alert_rules.get("slo_breach")
            if slo_rule and slo_rule.should_fire(slo_breaches):
                slo_rule.fire()
                breached_names = [s.definition.name for s in slo_statuses if not s.is_met and s.sample_count > 0]
                alert = FiredAlert(
                    alert_name="slo_breach",
                    severity=AlertSeverity.CRITICAL,
                    metric="slo_breaches",
                    value=slo_breaches,
                    threshold=0,
                    message=f"SLO breach: {', '.join(breached_names)}",
                )
                fired.append(alert)
                self._fired_alerts.append(alert)
                self._persist_alert(alert)

        return fired

    def get_fired_alerts(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent fired alerts."""
        alerts = list(self._fired_alerts)[-limit:]
        return [
            {
                "alert_name": a.alert_name,
                "severity": a.severity.value,
                "metric": a.metric,
                "value": round(a.value, 4),
                "threshold": a.threshold,
                "message": a.message,
                "timestamp": a.timestamp,
            }
            for a in reversed(alerts)
        ]

    def _emit_alert_prometheus(self, alert: FiredAlert):
        """Emit fired alert to Prometheus metrics."""
        try:
            from chat_app.prometheus_metrics import record_alert_fired
            record_alert_fired(alert.alert_name, alert.severity.value)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

    def _emit_slo_prometheus(self):
        """Emit current SLO statuses to Prometheus gauges."""
        try:
            from chat_app.prometheus_metrics import record_slo_status, record_active_alerts
            for status in self.get_slo_status():
                record_slo_status(
                    status.definition.name,
                    status.definition.slo_type.value,
                    status.is_met,
                    status.error_budget_remaining,
                )
            # Active alert counts by severity
            from collections import Counter as Ctr
            severity_counts = Ctr(a.severity.value for a in self._fired_alerts
                                  if time.time() - a.timestamp < 300)
            record_active_alerts(
                severity_counts.get("info", 0),
                severity_counts.get("warning", 0),
                severity_counts.get("critical", 0),
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

    def _persist_alert(self, alert: FiredAlert):
        """Persist a fired alert to JSONL file for historical tracking (max 10MB, auto-rotated)."""
        try:
            import json
            from pathlib import Path
            alerts_file = Path("/app/data/alerts.jsonl")
            alerts_file.parent.mkdir(parents=True, exist_ok=True)

            # Rotate if file exceeds 10MB — keep last half
            _MAX_ALERT_FILE_BYTES = 10 * 1024 * 1024
            if alerts_file.exists() and alerts_file.stat().st_size > _MAX_ALERT_FILE_BYTES:
                lines = alerts_file.read_text().splitlines()
                keep = lines[len(lines) // 2:]
                alerts_file.write_text("\n".join(keep) + "\n")
                logger.info("[ALERT] Rotated alerts.jsonl: kept %d of %d entries", len(keep), len(lines))

            entry = {
                "alert_name": alert.alert_name,
                "severity": alert.severity.value,
                "metric": alert.metric,
                "value": round(alert.value, 4),
                "threshold": alert.threshold,
                "message": alert.message,
                "timestamp": alert.timestamp,
            }
            with open(alerts_file, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.debug(f"[ALERT] Failed to persist alert: {exc}")

    def _compute_current_metrics(self) -> Dict[str, float]:
        """Compute current metric values for alert evaluation."""
        metrics = {}

        # Latency P95
        latencies = self._histograms.get("trace_duration_ms", [])
        if latencies:
            recent = latencies[-100:]
            sorted_lat = sorted(recent)
            idx = int(len(sorted_lat) * 0.95)
            metrics["latency_p95_ms"] = sorted_lat[min(idx, len(sorted_lat) - 1)]

        # Error rate
        total = self._counters.get("traces_total", 0)
        errors = self._counters.get("traces_with_errors", 0)
        if total > 0:
            metrics["error_rate"] = errors / total

        # Average quality
        qualities = self._histograms.get("quality_scores", [])
        if qualities:
            metrics["avg_quality"] = sum(qualities[-50:]) / len(qualities[-50:])

        return metrics

    # --- Metrics ---

    def increment(self, name: str, value: int = 1):
        self._counters[name] += value

    def set_gauge(self, name: str, value: float):
        self._gauges[name] = value

    def record_histogram(self, name: str, value: float):
        self._histograms[name].append(value)
        if len(self._histograms[name]) > 5000:
            self._histograms[name] = self._histograms[name][-2500:]

    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get a summary of all metrics."""
        histogram_summaries = {}
        for name, values in self._histograms.items():
            if values:
                recent = values[-100:]
                sorted_v = sorted(recent)
                histogram_summaries[name] = {
                    "count": len(values),
                    "avg": round(sum(recent) / len(recent), 2),
                    "min": round(sorted_v[0], 2),
                    "max": round(sorted_v[-1], 2),
                    "p50": round(sorted_v[len(sorted_v) // 2], 2),
                    "p95": round(sorted_v[int(len(sorted_v) * 0.95)], 2) if len(sorted_v) > 1 else round(sorted_v[0], 2),
                }

        return {
            "counters": dict(self._counters),
            "gauges": dict(self._gauges),
            "histograms": histogram_summaries,
        }

    # --- Dashboard ---

    def get_dashboard_data(self) -> Dict[str, Any]:
        """Get comprehensive observability dashboard data."""
        slo_statuses = self.get_slo_status()

        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tracing": {
                "active_traces": len(self._active_traces),
                "completed_traces": len(self._traces),
                "recent_traces": self.get_recent_traces(limit=10),
            },
            "slos": {
                "definitions": [d.to_dict() for d in self._slo_definitions.values()],
                "status": [s.to_dict() for s in slo_statuses],
                "all_met": all(s.is_met for s in slo_statuses if s.sample_count > 0),
            },
            "alerts": {
                "rules": [
                    {
                        "name": r.name,
                        "severity": r.severity.value,
                        "condition": r.condition,
                        "fire_count": r.fire_count,
                    }
                    for r in self._alert_rules.values()
                ],
                "recent_fired": self.get_fired_alerts(limit=20),
            },
            "metrics": self.get_metrics_summary(),
        }


# ---------------------------------------------------------------------------
# Splunk HEC Export — Send observability events to Splunk
# ---------------------------------------------------------------------------

_hec_url: Optional[str] = None
_hec_token: Optional[str] = None
_hec_enabled: bool = False


def init_hec_export():
    """Initialize Splunk HEC export from environment variables."""
    import os
    global _hec_url, _hec_token, _hec_enabled
    _hec_url = os.environ.get("SPLUNK_HEC_URL", "").strip()
    _hec_token = os.environ.get("SPLUNK_HEC_TOKEN", "").strip()
    _hec_enabled = bool(_hec_url and _hec_token)
    if _hec_enabled:
        logger.info("[OBSERVABILITY] Splunk HEC export enabled: %s", _hec_url)
    else:
        logger.debug("[OBSERVABILITY] Splunk HEC export disabled (SPLUNK_HEC_URL/TOKEN not set)")


async def export_to_splunk(event_payload: Dict[str, Any], sourcetype: str = "ai_agent:event"):
    """Export an event to Splunk via HEC.

    Args:
        event_payload: The event data to send.
        sourcetype: The Splunk sourcetype for the event.
    """
    if not _hec_enabled:
        return

    try:
        import httpx

        hec_event = {
            "sourcetype": sourcetype,
            "event": event_payload,
            "time": time.time(),
        }

        from chat_app.settings import get_settings
        _ssl_verify = get_settings().splunk.get_ssl_verify()

        async with httpx.AsyncClient(
            timeout=httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0),
            verify=_ssl_verify,
        ) as client:
            resp = await client.post(
                f"{_hec_url}/services/collector/event",
                json=hec_event,
                headers={
                    "Authorization": f"Splunk {_hec_token}",
                    "Content-Type": "application/json",
                },
            )
            if resp.status_code != 200:
                logger.warning("[HEC] Export failed (HTTP %d): %s", resp.status_code, resp.text[:200])
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        logger.debug("[HEC] Export failed: %s", exc)


async def export_trace_to_splunk(trace_dict: Dict[str, Any]):
    """Export a completed trace to Splunk."""
    await export_to_splunk(trace_dict, sourcetype="ai_agent:trace")


async def export_orchestration_to_splunk(orch_dict: Dict[str, Any]):
    """Export an orchestration result to Splunk."""
    await export_to_splunk(orch_dict, sourcetype="ai_agent:orchestration:result")


async def export_alert_to_splunk(alert_dict: Dict[str, Any]):
    """Export a fired alert to Splunk."""
    await export_to_splunk(alert_dict, sourcetype="ai_agent:alert")


# Singleton
_manager: Optional[ObservabilityManager] = None


def get_observability_manager() -> ObservabilityManager:
    """Get or create the singleton ObservabilityManager."""
    global _manager
    if _manager is None:
        _manager = ObservabilityManager()
        init_hec_export()
    return _manager


def get_active_alerts(window_minutes: int = 60) -> List[Dict[str, Any]]:
    """Read persisted alerts from alerts.jsonl and return those within *window_minutes*.

    This is a simple read-and-filter: parse every line, keep entries whose
    timestamp falls within ``now - window_minutes``.  The file is append-only
    and auto-rotated at 10 MB by ``_persist_alert``, so it stays bounded.

    Returns a list of alert dicts sorted newest-first.
    """
    import json
    from pathlib import Path

    alerts_file = Path("/app/data/alerts.jsonl")
    if not alerts_file.exists():
        return []

    cutoff = time.time() - (window_minutes * 60)
    active: List[Dict[str, Any]] = []

    try:
        with open(alerts_file, "r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts = entry.get("timestamp", 0)
                if ts >= cutoff:
                    active.append(entry)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        logger.debug("[ALERT] Failed to read alerts.jsonl: %s", exc)
        return []

    # Newest first
    active.sort(key=lambda a: a.get("timestamp", 0), reverse=True)
    return active
