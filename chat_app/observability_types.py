"""
ObsAI Observability Type Definitions — Tracing, SLOs, and Alert data types.

Extracted from observability.py to keep file sizes manageable.
All public names are re-exported from observability.py for backward compatibility.
"""
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Tracing
# ---------------------------------------------------------------------------

class SpanStatus(str, Enum):
    OK = "ok"
    ERROR = "error"
    TIMEOUT = "timeout"


@dataclass
class Span:
    """A single trace span representing a pipeline stage."""
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    trace_id: str = ""
    parent_id: Optional[str] = None
    operation: str = ""
    service: str = "obsai"
    start_time: float = field(default_factory=time.time)
    end_time: Optional[float] = None
    duration_ms: float = 0.0
    status: SpanStatus = SpanStatus.OK
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None

    def finish(self, status: SpanStatus = SpanStatus.OK, error: str = None):
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000
        self.status = status
        self.error = error

    def add_event(self, name: str, attributes: Dict[str, Any] = None):
        self.events.append({
            "name": name,
            "timestamp": time.time(),
            "attributes": attributes or {},
        })

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "operation": self.operation,
            "service": self.service,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": round(self.duration_ms, 2),
            "status": self.status.value,
            "attributes": self.attributes,
            "events": self.events,
            "error": self.error,
        }


@dataclass
class Trace:
    """A distributed trace representing a full request lifecycle."""
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    spans: List[Span] = field(default_factory=list)
    start_time: float = field(default_factory=time.time)
    user_id: Optional[str] = None
    query: str = ""
    intent: str = ""

    def create_span(self, operation: str, parent_id: str = None, **attributes) -> Span:
        span = Span(
            trace_id=self.trace_id,
            parent_id=parent_id or (self.spans[-1].span_id if self.spans else None),
            operation=operation,
            attributes=attributes,
        )
        self.spans.append(span)
        return span

    @property
    def total_duration_ms(self) -> float:
        if not self.spans:
            return 0.0
        return sum(s.duration_ms for s in self.spans if s.duration_ms > 0)

    @property
    def has_errors(self) -> bool:
        return any(s.status == SpanStatus.ERROR for s in self.spans)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "user_id": self.user_id,
            "query": self.query[:200],
            "intent": self.intent,
            "total_duration_ms": round(self.total_duration_ms, 2),
            "span_count": len(self.spans),
            "has_errors": self.has_errors,
            "spans": [s.to_dict() for s in self.spans],
        }


# ---------------------------------------------------------------------------
# SLO Definitions
# ---------------------------------------------------------------------------

class SLOType(str, Enum):
    LATENCY = "latency"
    QUALITY = "quality"
    AVAILABILITY = "availability"
    ERROR_RATE = "error_rate"
    THROUGHPUT = "throughput"


@dataclass
class SLODefinition:
    """Service Level Objective definition."""
    name: str
    slo_type: SLOType
    target: float  # Target value (e.g., 0.95 for 95%)
    window_seconds: int = 3600  # Evaluation window (1 hour default)
    description: str = ""

    # For latency SLOs: threshold in ms
    latency_threshold_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "type": self.slo_type.value,
            "target": self.target,
            "window_seconds": self.window_seconds,
            "description": self.description,
            "latency_threshold_ms": self.latency_threshold_ms,
        }


@dataclass
class SLOStatus:
    """Current status of an SLO."""
    definition: SLODefinition
    current_value: float = 0.0
    is_met: bool = True
    error_budget_remaining: float = 1.0
    sample_count: int = 0
    window_start: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.definition.name,
            "type": self.definition.slo_type.value,
            "target": self.definition.target,
            "current_value": round(self.current_value, 4),
            "is_met": self.is_met,
            "error_budget_remaining": round(self.error_budget_remaining, 4),
            "sample_count": self.sample_count,
        }


# ---------------------------------------------------------------------------
# Alert Rules
# ---------------------------------------------------------------------------

class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class AlertRule:
    """Alert rule definition."""
    name: str
    condition: str  # Human-readable condition description
    severity: AlertSeverity
    metric: str  # Metric to monitor
    threshold: float
    operator: str = ">"  # >, <, >=, <=, ==
    cooldown_seconds: int = 300
    description: str = ""
    last_fired: float = 0.0
    fire_count: int = 0

    def evaluate(self, value: float) -> bool:
        """Evaluate the alert condition."""
        ops = {
            ">": lambda v, t: v > t,
            "<": lambda v, t: v < t,
            ">=": lambda v, t: v >= t,
            "<=": lambda v, t: v <= t,
            "==": lambda v, t: abs(v - t) < 0.001,
        }
        op_func = ops.get(self.operator, ops[">"])
        return op_func(value, self.threshold)

    def should_fire(self, value: float) -> bool:
        """Check if alert should fire (respects cooldown)."""
        if not self.evaluate(value):
            return False
        if time.time() - self.last_fired < self.cooldown_seconds:
            return False
        return True

    def fire(self):
        self.last_fired = time.time()
        self.fire_count += 1


@dataclass
class FiredAlert:
    """Record of a fired alert."""
    alert_name: str
    severity: AlertSeverity
    metric: str
    value: float
    threshold: float
    message: str
    timestamp: float = field(default_factory=time.time)
