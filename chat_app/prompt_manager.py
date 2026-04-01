"""Prompt Template Manager -- Versioned prompts with quality tracking."""
import copy
import hashlib
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from functools import lru_cache
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_TEMPLATES = [
    {"id": "system_default", "name": "Default System Prompt", "category": "system",
     "template": "You are ObsAI, an AI assistant specialized in Splunk, Cribl, and observability. "
                 "{personalization}\n\nAnswer based on the provided context. If unsure, say so.",
     "variables": ["personalization"]},
    {"id": "rag_generation", "name": "RAG Generation", "category": "rag",
     "template": "Based on the following context, answer the user's question.\n\nContext:\n{context}\n\n"
                 "Question: {question}\n\nProvide a clear, accurate answer with references to the source material.",
     "variables": ["context", "question"]},
    {"id": "spl_generation", "name": "SPL Generation", "category": "generation",
     "template": "Generate a Splunk SPL query for the following request.\n\nRequest: {request}\n\n"
                 "Available indexes: {indexes}\nAvailable sourcetypes: {sourcetypes}\n\nReturn only the SPL query.",
     "variables": ["request", "indexes", "sourcetypes"]},
    {"id": "concise_answer", "name": "Concise Answer", "category": "generation",
     "template": "Answer this question concisely in 2-4 sentences. No code blocks unless asked.\n\nQuestion: {question}",
     "variables": ["question"]},
]


def _new_template(id: str, name: str, category: str, template: str, variables: list = None, **kw) -> Dict:
    return {"id": id, "name": name, "category": category, "template": template,
            "variables": variables or [], "version": kw.get("version", 1),
            "status": kw.get("status", "active"), "ab_group": kw.get("ab_group"),
            "created_by": kw.get("created_by", "system"),
            "created_at": kw.get("created_at", datetime.now(timezone.utc).isoformat()),
            "metrics": kw.get("metrics", {"uses": 0, "avg_quality": 0.0, "avg_latency_ms": 0.0,
                                          "avg_tokens": 0, "positive_feedback": 0, "negative_feedback": 0, "last_used": ""})}

# Keep old names as aliases
PromptTemplate = _new_template
PromptMetrics = dict


class PromptManager:
    def __init__(self):
        self._templates: Dict[str, Dict] = {}
        self._versions: Dict[str, List[Dict]] = defaultdict(list)
        now = datetime.now(timezone.utc).isoformat()
        for d in _DEFAULT_TEMPLATES:
            t = _new_template(**d, created_at=now)
            self._templates[t["id"]] = t

    def get(self, template_id: str) -> Optional[Dict]:
        return self._templates.get(template_id)

    def list_all(self) -> List[Dict]:
        return [{"id": t["id"], "name": t["name"], "category": t["category"], "version": t["version"],
                 "status": t["status"], "variables": t["variables"], "metrics": t["metrics"], "ab_group": t["ab_group"]}
                for t in self._templates.values()]

    def create(self, name: str, category: str, template: str, variables=None, author="admin") -> Dict:
        tid = hashlib.sha256(f"{name}:{time.time()}".encode()).hexdigest()[:12]
        t = _new_template(tid, name, category, template, variables, created_by=author)
        self._templates[tid] = t
        self._versions[name].append(t)
        return t

    def update(self, template_id: str, new_template: str, author="admin") -> Optional[Dict]:
        t = self._templates.get(template_id)
        if not t:
            return None
        self._versions[t["name"]].append(copy.deepcopy(t))
        t["template"] = new_template
        t["version"] += 1
        return t

    def get_versions(self, template_id: str) -> List[Dict]:
        t = self._templates.get(template_id)
        if not t:
            return []
        return [{"id": v["id"], "name": v["name"], "version": v["version"],
                 "template": v["template"], "created_by": v["created_by"], "created_at": v["created_at"]}
                for v in self._versions.get(t["name"], [])]

    def record_usage(self, template_id: str, quality=0.0, latency_ms=0.0, tokens=0):
        t = self._templates.get(template_id)
        if not t:
            return
        m = t["metrics"]
        m["uses"] += 1
        n = m["uses"]
        m["avg_quality"] = (m["avg_quality"] * (n - 1) + quality) / n
        m["avg_latency_ms"] = (m["avg_latency_ms"] * (n - 1) + latency_ms) / n
        m["avg_tokens"] = int((m["avg_tokens"] * (n - 1) + tokens) / n)
        m["last_used"] = datetime.now(timezone.utc).isoformat()

    def record_feedback(self, template_id: str, positive: bool):
        t = self._templates.get(template_id)
        if t:
            t["metrics"]["positive_feedback" if positive else "negative_feedback"] += 1


@lru_cache(maxsize=1)
def get_prompt_manager() -> PromptManager:
    return PromptManager()
