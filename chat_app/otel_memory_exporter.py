"""In-memory span exporter for admin API trace queries."""
import threading
from collections import defaultdict, deque
from typing import Any, Dict, List, Sequence

try:
    from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
    from opentelemetry.sdk.trace import ReadableSpan
    HAS_OTEL = True
    _BASE = SpanExporter
except ImportError:
    HAS_OTEL = False
    _BASE = object

_memory_exporter_instance = None

def get_memory_exporter():
    return _memory_exporter_instance


class InMemorySpanExporter(_BASE):
    def __init__(self, max_spans: int = 500):
        self._spans: deque = deque(maxlen=max_spans)
        self._lock = threading.Lock()

    def export(self, spans: Sequence) -> Any:
        with self._lock:
            self._spans.extend(self._to_dict(s) for s in spans)
        return SpanExportResult.SUCCESS if HAS_OTEL else None

    def shutdown(self): pass
    def force_flush(self, timeout_millis=30000): return True

    @staticmethod
    def _to_dict(span) -> Dict[str, Any]:
        ctx = span.get_span_context()
        parent = format(span.parent.span_id, "016x") if span.parent else None
        return {
            "trace_id": format(ctx.trace_id, "032x"),
            "span_id": format(ctx.span_id, "016x"),
            "parent_span_id": parent,
            "name": span.name,
            "kind": str(span.kind),
            "start_ns": span.start_time,
            "end_ns": span.end_time,
            "duration_ms": round((span.end_time - span.start_time) / 1e6, 2) if span.end_time and span.start_time else 0,
            "status": span.status.status_code.name if span.status else "UNSET",
            "attributes": dict(span.attributes) if span.attributes else {},
            "events": [{"name": e.name, "timestamp": e.timestamp, "attributes": dict(e.attributes or {})} for e in (span.events or [])],
        }

    def get_spans(self, limit: int = 200) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._spans)[-limit:][::-1]

    def get_traces(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            spans = list(self._spans)
        groups: Dict[str, list] = defaultdict(list)
        for s in spans:
            if tid := s.get("trace_id"):
                groups[tid].append(s)
        result = []
        for tid, tspans in groups.items():
            roots = [s for s in tspans if not s.get("parent_span_id")]
            starts = [s["start_ns"] for s in tspans if s.get("start_ns")]
            ends = [s["end_ns"] for s in tspans if s.get("end_ns")]
            root_attrs = roots[0].get("attributes", {}) if roots else {}
            result.append({
                "trace_id": tid, "spans": tspans, "span_count": len(tspans),
                "root_name": (roots[0] if roots else tspans[0])["name"],
                "duration_ms": round((max(ends) - min(starts)) / 1e6, 2) if starts and ends else 0,
                "start_time": min(starts) if starts else 0,
                "intent": root_attrs.get("pipeline.intent", ""),
                "profile": root_attrs.get("pipeline.profile", ""),
                "user_query": root_attrs.get("pipeline.user_query", ""),
                "model": root_attrs.get("gen_ai.request.model", ""),
                "status": roots[0].get("status", "UNSET") if roots else "UNSET",
                "timestamp": round(min(starts) / 1e9, 3) if starts else 0,
            })
        result.sort(key=lambda t: t.get("start_time", 0), reverse=True)
        return result[:limit]

    def get_trace_by_id(self, trace_id: str) -> Dict[str, Any]:
        with self._lock:
            spans = [s for s in self._spans if s.get("trace_id") == trace_id]
        if not spans:
            return {}
        roots = [s for s in spans if not s.get("parent_span_id")]
        return {"trace_id": trace_id, "spans": spans, "span_count": len(spans),
                "root_name": (roots[0] if roots else spans[0])["name"],
                "root_status": roots[0].get("status", "UNSET") if roots else "UNSET"}

    def clear(self):
        with self._lock:
            self._spans.clear()
