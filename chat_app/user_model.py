"""
User Modeling & Personalization — Per-user preference learning.

Builds a model of each user based on:
- Feedback history (what they like/dislike)
- Query patterns (what they typically ask about)
- Expertise signals (terminology complexity, question depth)
- Session behavior (search depth preferences, response style)
"""
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class UserModel:
    """Learned model of a specific user."""
    username: str = "anonymous"
    expertise_level: str = "intermediate"  # beginner, intermediate, expert
    preferred_profile: Optional[str] = None
    preferred_style: str = "detailed"  # concise, detailed, tutorial
    common_topics: List[str] = field(default_factory=list)  # Top query topics
    strengths: List[str] = field(default_factory=list)       # Topics they know well
    pain_points: List[str] = field(default_factory=list)     # Topics they struggle with
    total_queries: int = 0
    positive_feedback: int = 0
    negative_feedback: int = 0
    avg_query_complexity: float = 0.5  # 0=simple, 1=complex

    @property
    def satisfaction_rate(self) -> float:
        total = self.positive_feedback + self.negative_feedback
        return self.positive_feedback / total if total > 0 else 0.5


async def build_user_model(engine, username: str) -> UserModel:
    """
    Build a user model from their interaction and feedback history.

    Analyzes past queries, feedback patterns, and behavior to create
    a personalized model.
    """
    model = UserModel(username=username)

    if not engine:
        return model

    try:
        from sqlalchemy import select, func, text

        async with engine.begin() as conn:
            # Count interactions
            result = await conn.execute(
                text("SELECT COUNT(*) FROM assistant_interactions WHERE username = :u"),
                {"u": username},
            )
            row = result.scalar()
            model.total_queries = row or 0

            # Count positive feedback
            result = await conn.execute(
                text("SELECT COUNT(*) FROM assistant_liked_queries WHERE username = :u"),
                {"u": username},
            )
            model.positive_feedback = result.scalar() or 0

            # Count negative feedback
            result = await conn.execute(
                text("SELECT COUNT(*) FROM assistant_disliked_queries WHERE username = :u"),
                {"u": username},
            )
            model.negative_feedback = result.scalar() or 0

            # Analyze recent queries for expertise signals
            result = await conn.execute(
                text("""
                    SELECT question FROM assistant_interactions
                    WHERE username = :u
                    ORDER BY created_at DESC LIMIT 20
                """),
                {"u": username},
            )
            questions = [r[0] for r in result.fetchall() if r[0]]

            if questions:
                model.expertise_level = _infer_expertise(questions)
                model.common_topics = _extract_common_topics(questions)
                model.avg_query_complexity = _avg_complexity(questions)

            # Analyze negative feedback for pain points
            result = await conn.execute(
                text("""
                    SELECT question FROM assistant_disliked_queries
                    WHERE username = :u
                    ORDER BY created_at DESC LIMIT 10
                """),
                {"u": username},
            )
            disliked = [r[0] for r in result.fetchall() if r[0]]
            if disliked:
                model.pain_points = _extract_common_topics(disliked)[:3]

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[USER MODEL] Failed to build model for {username}: {exc}")

    return model


def _infer_expertise(questions: List[str]) -> str:
    """Infer expertise level from query patterns."""
    import re

    expert_signals = 0
    beginner_signals = 0

    for q in questions:
        lower = q.lower()
        # Expert signals
        if re.search(r'\btstats\b|\bprefix\(|\bTERM\(|\bdatamodel\b', lower):
            expert_signals += 1
        if re.search(r'\|\s*(map|multisearch|appendpipe|eventstats)', lower):
            expert_signals += 1
        if re.search(r'\bcim\b|\baccelerat|\brisk\s*based', lower):
            expert_signals += 1
        # Beginner signals
        if re.search(r'\bhow\s+(?:do|to|can)\b', lower):
            beginner_signals += 1
        if re.search(r'\bwhat\s+is\b|\bexplain\b|\bbasic\b', lower):
            beginner_signals += 1
        if len(q.split()) <= 5:
            beginner_signals += 0.5

    total = len(questions)
    if total == 0:
        return "intermediate"

    expert_ratio = expert_signals / total
    beginner_ratio = beginner_signals / total

    if expert_ratio > 0.4:
        return "expert"
    elif beginner_ratio > 0.5:
        return "beginner"
    return "intermediate"


def _extract_common_topics(questions: List[str]) -> List[str]:
    """Extract common topics from a list of questions."""
    import re
    from collections import Counter

    topic_patterns = {
        "spl_queries": r'\b(spl|query|search|stats|eval|where)\b',
        "configuration": r'\b(conf|config|stanza|inputs|props|transforms)\b',
        "troubleshooting": r'\b(error|fail|issue|debug|not working|broken)\b',
        "indexing": r'\b(index|ingest|sourcetype|parsing|event breaking)\b',
        "security": r'\b(security|alert|notable|threat|cim|es)\b',
        "dashboards": r'\b(dashboard|panel|visualization|chart|timechart)\b',
        "deployment": r'\b(deploy|cluster|forwarder|heavy|universal)\b',
        "performance": r'\b(slow|performance|optimize|fast|tstats)\b',
        "cribl": r'\b(cribl|pipeline|route|pack|stream|edge)\b',
        "observability": r'\b(metric|mstats|trace|otel|opentelemetry|sli|slo|observability|o11y)\b',
        "data_routing": r'\b(routing|destination|source|hec|kafka|s3|kinesis|syslog)\b',
    }

    counts = Counter()
    for q in questions:
        lower = q.lower()
        for topic, pattern in topic_patterns.items():
            if re.search(pattern, lower):
                counts[topic] += 1

    return [topic for topic, _ in counts.most_common(5)]


def _avg_complexity(questions: List[str]) -> float:
    """Estimate average query complexity (0-1)."""
    if not questions:
        return 0.5

    scores = []
    for q in questions:
        words = len(q.split())
        pipes = q.count('|')
        has_spl = bool('index=' in q.lower() or '|' in q)

        score = min(1.0, (words / 30) + (pipes * 0.15) + (0.2 if has_spl else 0))
        scores.append(score)

    return sum(scores) / len(scores)


def personalize_settings(user_model: UserModel, base_settings: dict) -> dict:
    """Adjust user settings based on the user model."""
    settings = dict(base_settings)

    # Adjust search depth based on expertise
    if user_model.expertise_level == "expert":
        settings.setdefault("search_depth", 7)
    elif user_model.expertise_level == "beginner":
        settings.setdefault("search_depth", 4)
        if "response_style" not in settings:
            settings["response_style"] = "tutorial"

    # Adjust response style based on satisfaction
    if user_model.satisfaction_rate < 0.4 and user_model.total_queries > 5:
        # User is often dissatisfied — try more detailed responses
        settings["response_style"] = "detailed"
        settings["include_examples"] = True

    return settings


def get_user_context_note(user_model: UserModel) -> Optional[str]:
    """Generate a context note about the user for the LLM."""
    if user_model.total_queries < 3:
        return None  # Not enough data

    parts = []
    parts.append(f"User expertise: {user_model.expertise_level}")

    if user_model.common_topics:
        parts.append(f"Frequent topics: {', '.join(user_model.common_topics[:3])}")

    if user_model.pain_points:
        parts.append(f"Areas needing extra care: {', '.join(user_model.pain_points[:2])}")

    if user_model.satisfaction_rate < 0.5 and user_model.total_queries > 5:
        parts.append("Note: This user has low satisfaction — be extra thorough and accurate")

    return " | ".join(parts)
