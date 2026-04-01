"""User profiles — adaptive personalization based on query patterns."""
from datetime import datetime, timezone

_EXPERTISE = {
    "spl_advanced": (['tstats', 'datamodel', 'acceleration', 'summary', 'mcollect', 'mstats'], "spl", 1.0, 0.3, 0.05),
    "spl_admin":    (['tstats', 'datamodel', 'acceleration', 'summary', 'mcollect', 'mstats'], "splunk_admin", 1.0, 0.3, 0.03),
    "spl_mid":      (['stats', 'eval', 'rex', 'transaction', 'join', 'lookup'], "spl", 0.8, 0.2, 0.03),
    "config":       (['.conf', 'stanza', 'props', 'transforms', 'inputs'], "splunk_config", 1.0, 0.2, 0.04),
    "cribl":        (['cribl', 'pipeline'], "cribl", 1.0, 0.1, 0.05),
    "obs":          (['prometheus', 'grafana', 'otel', 'opentelemetry', 'metrics', 'traces'], "observability", 1.0, 0.1, 0.04),
    "script":       (['ansible', 'playbook', 'bash', 'python', 'script'], "scripting", 1.0, 0.1, 0.04),
}
_TERSE = ["briefly", "tldr", "tl;dr", "short answer", "one liner", "quick"]
_VERBOSE = ["explain in detail", "elaborate", "comprehensive", "walk me through", "step by step"]


class UserProfile:
    __slots__ = ('user_id', 'expertise', 'preferred_verbosity', 'preferred_format',
                 'query_count', 'reformulation_count', 'avg_response_time_ms',
                 'frequent_intents', 'frequent_topics', 'last_active')

    def __init__(self, user_id: str, expertise: dict | None = None,
                 preferred_verbosity: str = "normal", preferred_format: str = "balanced",
                 query_count: int = 0, reformulation_count: int = 0, **_):
        self.user_id, self.expertise = user_id, expertise or {}
        self.preferred_verbosity, self.preferred_format = preferred_verbosity, preferred_format
        self.query_count, self.reformulation_count = query_count, reformulation_count
        self.avg_response_time_ms = 0.0
        self.frequent_intents: dict[str, int] = {}
        self.frequent_topics: dict[str, int] = {}
        self.last_active = ""

    @property
    def reformulation_rate(self) -> float:
        return self.reformulation_count / max(self.query_count, 1)

    @property
    def expertise_level(self) -> str:
        if not self.expertise:
            return "beginner"
        avg = sum(self.expertise.values()) / len(self.expertise)
        return "expert" if avg > 0.7 else "intermediate" if avg > 0.4 else "beginner"

    def get_personalization_prompt(self) -> str:
        parts = []
        lv = self.expertise_level
        if lv == "expert":
            parts.append("The user is an expert. Be concise, use technical terminology, skip basic explanations.")
        elif lv == "beginner":
            parts.append("The user is learning. Explain concepts clearly, provide examples, define technical terms.")
        if self.preferred_format == "code_first":
            parts.append("Lead with code examples before explanations.")
        if self.preferred_verbosity == "terse":
            parts.append("Keep responses brief and to the point.")
        elif self.preferred_verbosity == "detailed":
            parts.append("Provide comprehensive, detailed responses.")
        if top := sorted(self.expertise.items(), key=lambda x: -x[1])[:5]:
            parts.append(f"User's expertise areas: {', '.join(f'{k} ({v:.0%})' for k, v in top)}")
        return "\n".join(parts) if parts else ""

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id, "expertise": dict(self.expertise),
            "expertise_level": self.expertise_level, "preferred_verbosity": self.preferred_verbosity,
            "preferred_format": self.preferred_format, "query_count": self.query_count,
            "reformulation_count": self.reformulation_count,
            "reformulation_rate": round(self.reformulation_rate, 4),
            "avg_response_time_ms": round(self.avg_response_time_ms, 1),
            "frequent_intents": dict(self.frequent_intents),
            "frequent_topics": dict(self.frequent_topics), "last_active": self.last_active,
        }


class UserProfileManager:
    def __init__(self):
        self._profiles: dict[str, UserProfile] = {}

    def get_profile(self, user_id: str) -> UserProfile:
        if user_id not in self._profiles:
            self._profiles[user_id] = UserProfile(user_id=user_id)
        return self._profiles[user_id]

    def list_profiles(self) -> list[dict]:
        return [p.to_dict() for p in self._profiles.values()]

    def record_query(self, user_id: str, query: str, intent: str,
                     response_time_ms: float = 0, topics: list[str] | None = None):
        p = self.get_profile(user_id)
        p.query_count += 1
        p.last_active = datetime.now(timezone.utc).isoformat()
        p.frequent_intents[intent] = p.frequent_intents.get(intent, 0) + 1
        for t in (topics or []):
            p.frequent_topics[t] = p.frequent_topics.get(t, 0) + 1
        if response_time_ms > 0:
            p.avg_response_time_ms = (p.avg_response_time_ms * (p.query_count - 1) + response_time_ms) / p.query_count
        q = query.lower()
        for keywords, area, cap, base, step in _EXPERTISE.values():
            if any(kw in q for kw in keywords):
                p.expertise[area] = min(cap, p.expertise.get(area, base) + step)
        if any(s in q for s in _TERSE):
            p.preferred_verbosity = "terse"
        elif any(s in q for s in _VERBOSE):
            p.preferred_verbosity = "detailed"

    def record_feedback(self, user_id: str, liked: bool, query: str):
        pass

    def detect_reformulation(self, user_id: str, query: str, previous_query: str):
        q1, q2 = set(query.lower().split()), set(previous_query.lower().split())
        if len(q1 & q2) / max(len(q1 | q2), 1) > 0.5:
            self.get_profile(user_id).reformulation_count += 1


_manager: UserProfileManager | None = None

def get_profile_manager() -> UserProfileManager:
    global _manager
    if _manager is None:
        _manager = UserProfileManager()
    return _manager
