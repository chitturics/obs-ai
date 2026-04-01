"""LLM cost tracking — per-query, per-user, per-model cost attribution."""
import contextvars
import logging
import time
import threading
from collections import defaultdict, deque
from datetime import datetime, timezone
from functools import lru_cache

logger = logging.getLogger(__name__)

_ctx = {k: contextvars.ContextVar(f"_cost_{k}", default="")
        for k in ("user_id", "session_id", "request_id", "intent")}

def set_cost_context(**kwargs: str):
    for k, v in kwargs.items():
        if v and (var := _ctx.get(k)):
            var.set(v)

def clear_cost_context():
    for var in _ctx.values():
        var.set("")

# Per 1K tokens
MODEL_PRICING = {
    "qwen2.5:3b":       {"input": 0.0001,  "output": 0.0002, "provider": "ollama"},
    "qwen2.5:7b":       {"input": 0.0002,  "output": 0.0004, "provider": "ollama"},
    "qwen2.5:14b":      {"input": 0.0005,  "output": 0.001,  "provider": "ollama"},
    "qwen2.5:32b":      {"input": 0.001,   "output": 0.002,  "provider": "ollama"},
    "mxbai-embed-large": {"input": 0.00005, "output": 0.0,    "provider": "ollama"},
    "cloud-reasoning-large":   {"input": 0.015,   "output": 0.075,  "provider": "cloud_llm"},
    "cloud-reasoning-medium": {"input": 0.003,   "output": 0.015,  "provider": "cloud_llm"},
    "cloud-reasoning-fast":  {"input": 0.001,   "output": 0.005,  "provider": "cloud_llm"},
    "gpt-4o":           {"input": 0.005,   "output": 0.015,  "provider": "openai"},
    "gpt-4o-mini":      {"input": 0.00015, "output": 0.0006, "provider": "openai"},
}
_DEFAULT_PRICING = {"input": 0.0001, "output": 0.0002, "provider": "unknown"}


class CostTracker:
    def __init__(self, max_entries: int = 5000):
        self._entries: deque = deque(maxlen=max_entries)
        self._lock = threading.Lock()
        self._daily = defaultdict(float)
        self._by_user = defaultdict(float)
        self._by_model = defaultdict(float)

    def record(self, model: str, purpose: str, input_tokens: int, output_tokens: int,
               latency_ms: int = 0, **kwargs) -> dict:
        for k in ("user_id", "session_id", "request_id", "intent"):
            kwargs.setdefault(k, _ctx[k].get(""))

        pricing = MODEL_PRICING.get(model, _DEFAULT_PRICING)
        cost = (input_tokens * pricing["input"] + output_tokens * pricing["output"]) / 1000.0
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(), "model": model,
            "provider": pricing.get("provider", "unknown"), "purpose": purpose,
            "input_tokens": input_tokens, "output_tokens": output_tokens,
            "cost_usd": round(cost, 6), "latency_ms": latency_ms, **kwargs,
        }

        with self._lock:
            self._entries.append(entry)
            self._daily[datetime.now(timezone.utc).strftime("%Y-%m-%d")] += cost
            if uid := kwargs.get("user_id"):
                self._by_user[uid] += cost
            self._by_model[model] += cost

        try:
            from chat_app.prometheus_metrics import record_llm_cost_metric
            record_llm_cost_metric(model, purpose, cost, input_tokens, output_tokens)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass
        logger.debug("[COST] %s: %s %d+%d tok=$%.6f", purpose, model, input_tokens, output_tokens, cost)
        return entry

    def get_summary(self, hours: int = 24) -> dict:
        cutoff = time.time() - hours * 3600
        with self._lock:
            recent = [e for e in self._entries
                      if datetime.fromisoformat(e["timestamp"]).timestamp() > cutoff]

        by_model, by_purpose, by_user = defaultdict(float), defaultdict(float), defaultdict(float)
        for e in recent:
            by_model[e["model"]] += e["cost_usd"]
            by_purpose[e["purpose"]] += e["cost_usd"]
            if e.get("user_id"):
                by_user[e["user_id"]] += e["cost_usd"]

        total = sum(e["cost_usd"] for e in recent)
        ranked = lambda d, n=None: {k: round(v, 4) for k, v in sorted(d.items(), key=lambda x: -x[1])[:n]}
        return {
            "period_hours": hours, "total_usd": round(total, 4), "total_calls": len(recent),
            "total_input_tokens": sum(e["input_tokens"] for e in recent),
            "total_output_tokens": sum(e["output_tokens"] for e in recent),
            "avg_cost_per_query": round(total / max(len(recent), 1), 6),
            "by_model": ranked(by_model), "by_purpose": ranked(by_purpose),
            "by_user": ranked(by_user, 10),
            "daily_totals": dict(sorted(self._daily.items())[-7:]),
            "recent_entries": list(self._entries)[-20:],
        }

    def get_daily_trend(self, days: int = 30) -> dict:
        with self._lock:
            totals = dict(sorted(self._daily.items())[-days:])
        return {"days": days, "daily_totals": {k: round(v, 4) for k, v in totals.items()},
                "total_usd": round(sum(totals.values()), 4)}

    def get_by_user(self, top_n: int = 20) -> dict:
        with self._lock:
            ranked = sorted(self._by_user.items(), key=lambda x: -x[1])[:top_n]
        return {"users": [{"user_id": u, "total_usd": round(c, 4)} for u, c in ranked],
                "total_tracked_users": len(self._by_user)}


    # ------------------------------------------------------------------
    # Retrieval and tool cost tracking
    # ------------------------------------------------------------------

    def record_retrieval(self, user: str, collection: str, latency_ms: float,
                         chunks_returned: int) -> dict:
        """Record a retrieval operation with attribution."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": "retrieval",
            "collection": collection,
            "latency_ms": round(latency_ms, 1),
            "chunks_returned": chunks_returned,
            "user_id": user,
        }
        with self._lock:
            self._entries.append(entry)
            if user:
                self._by_user.setdefault(user, 0.0)  # Track user even if zero cost
        return entry

    def record_tool_execution(self, user: str, tool: str, latency_ms: float,
                              success: bool = True) -> dict:
        """Record a tool execution with attribution."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category": "tool",
            "tool": tool,
            "latency_ms": round(latency_ms, 1),
            "success": success,
            "user_id": user,
        }
        with self._lock:
            self._entries.append(entry)
            if user:
                self._by_user.setdefault(user, 0.0)
        return entry

    def get_dashboard(self, hours: int = 24) -> dict:
        """Get comprehensive cost/load dashboard."""
        cutoff = time.time() - hours * 3600
        with self._lock:
            recent = []
            for e in self._entries:
                ts = e.get("timestamp", "")
                try:
                    if datetime.fromisoformat(ts).timestamp() > cutoff:
                        recent.append(e)
                except Exception as _exc:  # broad catch — resilience against all failures
                    continue

        llm_entries = [e for e in recent if e.get("model")]
        retrieval_entries = [e for e in recent if e.get("category") == "retrieval"]
        tool_entries = [e for e in recent if e.get("category") == "tool"]

        total_cost = sum(e.get("cost_usd", 0) for e in llm_entries)
        total_tokens = sum(e.get("input_tokens", 0) + e.get("output_tokens", 0) for e in llm_entries)

        return {
            "period_hours": hours,
            "llm": {
                "total_calls": len(llm_entries),
                "total_cost_usd": round(total_cost, 4),
                "total_tokens": total_tokens,
                "avg_cost_per_query": round(total_cost / max(len(llm_entries), 1), 6),
            },
            "retrieval": {
                "total_calls": len(retrieval_entries),
                "total_chunks": sum(e.get("chunks_returned", 0) for e in retrieval_entries),
                "avg_latency_ms": round(
                    sum(e.get("latency_ms", 0) for e in retrieval_entries) / max(len(retrieval_entries), 1), 1
                ),
            },
            "tools": {
                "total_calls": len(tool_entries),
                "success_rate": round(
                    sum(1 for e in tool_entries if e.get("success", True)) / max(len(tool_entries), 1), 3
                ),
                "avg_latency_ms": round(
                    sum(e.get("latency_ms", 0) for e in tool_entries) / max(len(tool_entries), 1), 1
                ),
            },
            "top_users": self.get_by_user(10).get("users", []),
            "daily_totals": dict(sorted(self._daily.items())[-7:]),
            "model_pricing": MODEL_PRICING,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


@lru_cache(maxsize=1)
def get_cost_tracker() -> CostTracker:
    return CostTracker()

def record_llm_cost(model: str, purpose: str, input_tokens: int, output_tokens: int, **kw) -> dict:
    return get_cost_tracker().record(model, purpose, input_tokens, output_tokens, **kw)

def get_cost_summary(hours: int = 24) -> dict:
    return get_cost_tracker().get_summary(hours)
