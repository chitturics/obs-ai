"""Workflow memory — cross-session workflow arc tracking."""
import hashlib
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from types import SimpleNamespace

def WorkflowStep(*, query, answer_summary, intent, timestamp, session_id,
                 confidence=0.0, resources_used=None):
    return SimpleNamespace(query=query, answer_summary=answer_summary, intent=intent,
                           timestamp=timestamp, session_id=session_id,
                           confidence=confidence, resources_used=resources_used or [])

def WorkflowArc(*, id, user_id, title, steps=None, topics=None,
                status="active", created_at="", last_activity=""):
    arc = SimpleNamespace(id=id, user_id=user_id, title=title, steps=steps or [],
                          topics=topics or [], status=status,
                          created_at=created_at, last_activity=last_activity)
    def add_step(step):
        arc.steps.append(step)
        arc.last_activity = datetime.now(timezone.utc).isoformat()
    def summary():
        if not arc.steps:
            return ""
        lines = [f"Workflow: {arc.title} ({len(arc.steps)} steps)"]
        lines += [f"  {i}. Q: {s.query[:80]} -> {s.intent}" for i, s in enumerate(arc.steps[-3:], 1)]
        return "\n".join(lines)
    arc.add_step, arc.summary = add_step, summary
    return arc


class WorkflowMemory:
    def __init__(self, max_arcs_per_user: int = 20, stale_hours: int = 72):
        self._arcs: dict[str, list] = defaultdict(list)
        self._max_arcs = max_arcs_per_user
        self._stale_hours = stale_hours

    def detect_continuation(self, query: str, user_id: str, intent: str):
        if not (user_arcs := self._arcs.get(user_id)):
            return None
        qtok = set(query.lower().split())
        best, best_score = None, 0.0
        for arc in user_arcs:
            if arc.status != "active":
                continue
            if arc.last_activity:
                if datetime.now(timezone.utc) - datetime.fromisoformat(arc.last_activity) > timedelta(hours=self._stale_hours):
                    arc.status = "stalled"
                    continue
            atok = {w for s in arc.steps for w in s.query.lower().split()}
            score = (len(qtok & atok) / max(len(qtok), 1)) * 0.5 + (1.0 if any(s.intent == intent for s in arc.steps[-3:]) else 0.0) * 0.3 + 0.2
            if score > best_score and score > 0.3:
                best, best_score = arc, score
        return best

    def record_step(self, user_id: str, query: str, answer_summary: str,
                    intent: str, session_id: str, confidence: float = 0.0,
                    workflow_arc=None):
        step = WorkflowStep(query=query, answer_summary=answer_summary[:200], intent=intent,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            session_id=session_id, confidence=confidence)
        if workflow_arc:
            workflow_arc.add_step(step)
            return workflow_arc
        now = datetime.now(timezone.utc).isoformat()
        arc = WorkflowArc(id=hashlib.sha256(f"{user_id}:{query}:{time.time()}".encode()).hexdigest()[:16],
                          user_id=user_id, title=query[:60], created_at=now,
                          last_activity=now, topics=[intent])
        arc.add_step(step)
        arcs = self._arcs[user_id]
        arcs.append(arc)
        if len(arcs) > self._max_arcs:
            self._arcs[user_id] = arcs[-self._max_arcs:]
        return arc

    def get_active_arcs(self, user_id: str) -> list:
        return [a for a in self._arcs.get(user_id, []) if a.status == "active"]

    def get_suggestions(self, user_id: str) -> list[dict]:
        return [{"arc_id": a.id, "title": a.title, "last_query": a.steps[-1].query[:80],
                 "steps": len(a.steps), "last_activity": a.last_activity}
                for a in self.get_active_arcs(user_id)[-3:] if a.steps]


_workflow_memory: WorkflowMemory | None = None

def get_workflow_memory() -> WorkflowMemory:
    global _workflow_memory
    if _workflow_memory is None:
        _workflow_memory = WorkflowMemory()
    return _workflow_memory
