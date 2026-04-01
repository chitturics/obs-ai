"""
Governance & Continuous Improvement (GCI) Agent — The Meta-Evaluator.

Acts as the "intellectual conscience" of the multi-agent swarm.
Does NOT generate primary content; ensures content from other agents meets
the highest standards of accuracy, utility, and stylistic alignment.

Implements a Review-Analyze-Correct (RAC) loop:
1. REVIEW: Intercept every interaction triplet (Query / Response / Agent).
2. ANALYZE: Score across factuality, alignment, cohesion dimensions.
3. CORRECT: If quality < threshold, generate improvement directives or rewrite.

Trend awareness via a sliding window of recent interactions per agent.
Identifies when agents become repetitive, verbose, or consistently fail at tasks.

Architecture:
    GCIAgent (singleton)
    ├── InteractionBuffer     — sliding window of [query, response, agent_id, scores]
    ├── AgentPerformanceTracker — per-agent trend analysis
    ├── DirectiveGenerator    — produces [AGENT_ID | ERROR_TYPE | ROOT_CAUSE | REMEDIATION]
    └── TrendReporter         — periodic summary of top failure points
"""
import json
import logging
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class InteractionRecord:
    """A single interaction triplet with quality metadata."""
    query: str
    response: str
    agent_id: str
    intent: str = ""
    timestamp: float = field(default_factory=time.time)

    # Quality dimensions (1-10 scale)
    factuality: float = 0.0        # Hallucination / outdated info
    alignment: float = 0.0         # Does the answer address user intent?
    cohesion: float = 0.0          # Tone consistency, verbosity
    overall_score: float = 0.0

    # Metadata tags
    tags: List[str] = field(default_factory=list)  # e.g. #hallucination_risk, #brevity_issue
    intercepted: bool = False
    correction_applied: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "query": self.query[:200],
            "response_preview": self.response[:300],
            "agent_id": self.agent_id,
            "intent": self.intent,
            "timestamp": self.timestamp,
            "factuality": self.factuality,
            "alignment": self.alignment,
            "cohesion": self.cohesion,
            "overall_score": self.overall_score,
            "tags": self.tags,
            "intercepted": self.intercepted,
        }


@dataclass
class ImprovementDirective:
    """Structured feedback for a specific agent."""
    agent_id: str
    error_type: str            # hallucination, off_topic, verbose, incomplete, technical_error, repetitive
    root_cause: str            # Explanation of why the error occurred
    remediation_step: str      # Specific action the agent should take
    severity: str = "medium"   # low, medium, high, critical
    timestamp: float = field(default_factory=time.time)
    interaction_count: int = 0  # How many interactions showed this pattern

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_feedback_str(self) -> str:
        """Format as the standard [AGENT_ID | ERROR_TYPE | ROOT_CAUSE | REMEDIATION_STEP]."""
        return f"[{self.agent_id}] | [{self.error_type}] | [{self.root_cause}] | [{self.remediation_step}]"


@dataclass
class AgentTrend:
    """Performance trend for a specific agent."""
    agent_id: str
    total_interactions: int = 0
    avg_factuality: float = 0.0
    avg_alignment: float = 0.0
    avg_cohesion: float = 0.0
    avg_overall: float = 0.0
    trend_direction: str = "stable"   # improving, stable, declining
    common_tags: List[str] = field(default_factory=list)
    intercept_rate: float = 0.0       # Fraction of intercepted responses
    active_directives: int = 0


# ---------------------------------------------------------------------------
# Quality Scoring (Heuristic — No LLM Call)
# ---------------------------------------------------------------------------

# Error type keywords for tagging
_HALLUCINATION_MARKERS = [
    "i believe", "i think", "might be", "could be", "possibly",
    "from my understanding", "as far as i know", "i assume",
]
_VERBOSE_THRESHOLD = 2000       # chars — flag responses above this
_BREVITY_THRESHOLD = 50         # chars — flag responses below this
_REPETITION_WINDOW = 5          # check last N responses for agent


def _score_factuality(response: str, context: str, chunks_found: int) -> Tuple[float, List[str]]:
    """Score factuality (1-10). Detects hallucination risk."""
    tags = []
    score = 7.0  # Default: decent

    response_lower = response.lower()

    # Penalize hedging language (suggests uncertainty)
    hedge_count = sum(1 for m in _HALLUCINATION_MARKERS if m in response_lower)
    if hedge_count >= 3:
        score -= 2.0
        tags.append("#hallucination_risk")
    elif hedge_count >= 1:
        score -= 0.5

    # Penalize if no context was provided (higher hallucination risk)
    if chunks_found == 0 and len(response) > 200:
        score -= 2.0
        tags.append("#no_context_grounding")

    # Reward if response contains specific technical terms from context
    if context:
        context_terms = set(context.lower().split())
        response_terms = set(response_lower.split())
        overlap = len(context_terms & response_terms)
        if overlap > 20:
            score += 1.0
        elif overlap < 5 and len(response) > 200:
            score -= 1.0
            tags.append("#low_context_overlap")

    # Penalize "I don't know" without being helpful
    if any(p in response_lower for p in ["i don't know", "i'm not sure", "i cannot"]):
        if len(response) < 100:
            score -= 1.0
            tags.append("#unhelpful_refusal")

    return max(1.0, min(10.0, score)), tags


def _score_alignment(response: str, query: str, intent: str) -> Tuple[float, List[str]]:
    """Score alignment (1-10). Does the response address the user's intent?"""
    tags = []
    score = 7.0

    query_lower = query.lower()
    response_lower = response.lower()

    # Check keyword overlap between query and response
    query_words = set(query_lower.split()) - {"the", "a", "is", "what", "how", "why", "can", "do"}
    response_words = set(response_lower.split())
    overlap = len(query_words & response_words)

    if len(query_words) > 0:
        overlap_ratio = overlap / len(query_words)
        if overlap_ratio > 0.5:
            score += 1.5
        elif overlap_ratio < 0.2:
            score -= 2.0
            tags.append("#off_topic")

    # Check if response is relevant to intent
    intent_indicators = {
        "spl_generation": ["search", "|", "stats", "eval", "where", "index="],
        "spl_explanation": ["this spl", "this search", "command", "function"],
        "config_help": ["conf", "stanza", "setting", "parameter", "value"],
        "troubleshooting": ["check", "verify", "ensure", "issue", "error", "fix"],
    }
    if intent in intent_indicators:
        indicators = intent_indicators[intent]
        if any(ind in response_lower for ind in indicators):
            score += 0.5
        else:
            score -= 1.0

    return max(1.0, min(10.0, score)), tags


def _score_cohesion(response: str, agent_id: str, recent_responses: List[str]) -> Tuple[float, List[str]]:
    """Score cohesion (1-10). Tone, verbosity, repetition."""
    tags = []
    score = 7.0

    # Check verbosity
    if len(response) > _VERBOSE_THRESHOLD:
        score -= 1.0
        tags.append("#verbose")
    elif len(response) < _BREVITY_THRESHOLD:
        score -= 1.5
        tags.append("#too_brief")

    # Check for repetition against recent responses
    if recent_responses:
        for prev in recent_responses[-_REPETITION_WINDOW:]:
            if prev and response:
                # Simple Jaccard similarity on words
                r_words = set(response.lower().split())
                p_words = set(prev.lower().split())
                if r_words and p_words:
                    similarity = len(r_words & p_words) / len(r_words | p_words)
                    if similarity > 0.7:
                        score -= 2.0
                        tags.append("#repetitive")
                        break

    # Penalize excessive use of bullet points / lists
    bullet_count = response.count("\n- ") + response.count("\n* ") + response.count("\n1.")
    if bullet_count > 15:
        score -= 0.5
        tags.append("#over_structured")

    return max(1.0, min(10.0, score)), tags


# ---------------------------------------------------------------------------
# GCI Agent
# ---------------------------------------------------------------------------

class GCIAgent:
    """
    Governance & Continuous Improvement Agent.

    The intellectual conscience of the multi-agent swarm.
    Reviews every interaction, tracks trends, generates improvement directives.
    """

    INTERCEPT_THRESHOLD = 5.0   # Overall score below this triggers interception (on 1-10 scale)
    CRITICAL_THRESHOLD = 3.0    # Below this: rewrite required
    TREND_REPORT_INTERVAL = 50  # Generate trend report every N interactions
    STATE_FILE = "/app/data/gci_state.json"
    MAX_BUFFER_SIZE = 500

    def __init__(self):
        self._buffer: deque = deque(maxlen=self.MAX_BUFFER_SIZE)
        self._agent_records: Dict[str, deque] = defaultdict(lambda: deque(maxlen=50))
        self._agent_responses: Dict[str, deque] = defaultdict(lambda: deque(maxlen=20))
        self._directives: List[ImprovementDirective] = []
        self._trend_reports: List[Dict[str, Any]] = []
        self._total_interactions: int = 0
        self._total_intercepts: int = 0
        self._last_trend_report: int = 0

        self._load_state()

    # -------------------------------------------------------------------
    # Core RAC Loop
    # -------------------------------------------------------------------

    def review(
        self,
        query: str,
        response: str,
        agent_id: str,
        intent: str = "",
        context: str = "",
        chunks_found: int = 0,
    ) -> InteractionRecord:
        """
        REVIEW phase: Score an interaction across all quality dimensions.

        Returns the InteractionRecord with scores and tags.
        Call this after agent response generation but before sending to user.
        """
        recent_responses = list(self._agent_responses.get(agent_id, []))

        # Score each dimension
        factuality, f_tags = _score_factuality(response, context, chunks_found)
        alignment, a_tags = _score_alignment(response, query, intent)
        cohesion, c_tags = _score_cohesion(response, agent_id, recent_responses)

        # Weighted overall (factuality most important)
        overall = (factuality * 0.4 + alignment * 0.35 + cohesion * 0.25)

        all_tags = f_tags + a_tags + c_tags

        record = InteractionRecord(
            query=query,
            response=response,
            agent_id=agent_id,
            intent=intent,
            factuality=round(factuality, 1),
            alignment=round(alignment, 1),
            cohesion=round(cohesion, 1),
            overall_score=round(overall, 1),
            tags=all_tags,
        )

        # Store in buffer and per-agent history
        self._buffer.append(record)
        self._agent_records[agent_id].append(record)
        self._agent_responses[agent_id].append(response)
        self._total_interactions += 1

        # Check if interception is needed
        if overall < self.INTERCEPT_THRESHOLD:
            record.intercepted = True
            self._total_intercepts += 1
            logger.info(
                "[GCI] Intercepted low-quality response: agent=%s score=%.1f tags=%s",
                agent_id, overall, all_tags,
            )

        # Generate directives if patterns emerge
        self._analyze_and_generate_directives(agent_id)

        # Periodic trend report
        if self._total_interactions - self._last_trend_report >= self.TREND_REPORT_INTERVAL:
            self._generate_trend_report()
            self._last_trend_report = self._total_interactions

        return record

    def should_intercept(self, record: InteractionRecord) -> bool:
        """ANALYZE phase: Determine if this response needs correction."""
        return record.overall_score < self.INTERCEPT_THRESHOLD

    def get_correction_note(self, record: InteractionRecord) -> Optional[str]:
        """
        CORRECT phase: Generate a correction note for problematic responses.

        Returns a brief note to append to the response, or None if no correction needed.
        Does NOT call LLM — uses heuristic guidance.
        """
        if not record.intercepted:
            return None

        notes = []

        if "#hallucination_risk" in record.tags:
            notes.append(
                "Note: This response may contain unverified information. "
                "Please verify critical details against official documentation."
            )

        if "#off_topic" in record.tags:
            notes.append(
                "Note: The response may not fully address your specific question. "
                "Try rephrasing or providing more context."
            )

        if "#no_context_grounding" in record.tags:
            notes.append(
                "Note: Limited relevant documentation was found for this query. "
                "The response is based on general knowledge and may need verification."
            )

        if "#too_brief" in record.tags:
            notes.append(
                "Note: This is a brief response. Ask a follow-up for more detail."
            )

        if notes:
            record.correction_applied = " | ".join(notes)
            return "\n\n---\n" + "\n".join(notes)
        return None

    # -------------------------------------------------------------------
    # Directive Generation
    # -------------------------------------------------------------------

    def _analyze_and_generate_directives(self, agent_id: str):
        """Analyze recent agent interactions and generate improvement directives."""
        records = list(self._agent_records.get(agent_id, []))
        if len(records) < 5:
            return  # Need minimum data

        recent = records[-10:]

        # Check for consistent low factuality
        avg_factuality = sum(r.factuality for r in recent) / len(recent)
        if avg_factuality < 5.0:
            self._add_directive(
                agent_id=agent_id,
                error_type="hallucination",
                root_cause=f"Average factuality score is {avg_factuality:.1f}/10 over last {len(recent)} interactions. "
                           f"Agent may be generating content without sufficient context grounding.",
                remediation_step="Increase reliance on retrieved context. When context is sparse, "
                                 "explicitly state uncertainty rather than generating plausible-sounding content.",
                severity="high" if avg_factuality < 4.0 else "medium",
                count=len(recent),
            )

        # Check for consistent off-topic responses
        off_topic_count = sum(1 for r in recent if "#off_topic" in r.tags)
        if off_topic_count >= 3:
            self._add_directive(
                agent_id=agent_id,
                error_type="off_topic",
                root_cause=f"{off_topic_count}/{len(recent)} recent responses were off-topic. "
                           f"Agent may not be correctly interpreting user intent.",
                remediation_step="Focus on extracting the core question from the user query. "
                                 "Match response structure to the query type (SPL, config, troubleshooting).",
                severity="high",
                count=off_topic_count,
            )

        # Check for verbosity pattern
        verbose_count = sum(1 for r in recent if "#verbose" in r.tags)
        if verbose_count >= 4:
            self._add_directive(
                agent_id=agent_id,
                error_type="verbose",
                root_cause=f"{verbose_count}/{len(recent)} responses exceeded {_VERBOSE_THRESHOLD} chars. "
                           f"Agent may be over-explaining or including irrelevant details.",
                remediation_step="Prioritize concise, actionable answers. Lead with the direct answer, "
                                 "then provide supporting details only if necessary.",
                severity="low",
                count=verbose_count,
            )

        # Check for repetition
        repetitive_count = sum(1 for r in recent if "#repetitive" in r.tags)
        if repetitive_count >= 2:
            self._add_directive(
                agent_id=agent_id,
                error_type="repetitive",
                root_cause=f"{repetitive_count}/{len(recent)} responses showed high similarity to previous responses. "
                           f"Agent may be stuck in a response pattern.",
                remediation_step="Vary response structure and language. If the query is similar to a previous one, "
                                 "acknowledge this and provide new information or a different angle.",
                severity="medium",
                count=repetitive_count,
            )

    def _add_directive(
        self, agent_id: str, error_type: str, root_cause: str,
        remediation_step: str, severity: str, count: int,
    ):
        """Add a directive, avoiding duplicates for the same agent+error_type."""
        # Check for existing directive
        for d in self._directives[-20:]:
            if d.agent_id == agent_id and d.error_type == error_type:
                # Update existing
                d.root_cause = root_cause
                d.remediation_step = remediation_step
                d.severity = severity
                d.interaction_count = count
                d.timestamp = time.time()
                return

        directive = ImprovementDirective(
            agent_id=agent_id,
            error_type=error_type,
            root_cause=root_cause,
            remediation_step=remediation_step,
            severity=severity,
            interaction_count=count,
        )
        self._directives.append(directive)
        logger.info("[GCI] Directive: %s", directive.to_feedback_str())

        # Keep last 100 directives
        if len(self._directives) > 100:
            self._directives = self._directives[-100:]

    # -------------------------------------------------------------------
    # Trend Reporting
    # -------------------------------------------------------------------

    def _generate_trend_report(self):
        """Generate a trend report summarizing top failure points across the swarm."""
        recent = list(self._buffer)[-self.TREND_REPORT_INTERVAL:]
        if not recent:
            return

        # Aggregate tags
        tag_counts = defaultdict(int)
        agent_scores = defaultdict(list)
        for r in recent:
            for tag in r.tags:
                tag_counts[tag] += 1
            agent_scores[r.agent_id].append(r.overall_score)

        # Top failure tags
        top_failures = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:5]

        # Worst-performing agents
        agent_avgs = {
            agent: sum(scores) / len(scores)
            for agent, scores in agent_scores.items()
            if len(scores) >= 3
        }
        worst_agents = sorted(agent_avgs.items(), key=lambda x: x[1])[:3]

        report = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "interactions_analyzed": len(recent),
            "intercept_rate": sum(1 for r in recent if r.intercepted) / max(len(recent), 1),
            "avg_overall_score": sum(r.overall_score for r in recent) / max(len(recent), 1),
            "top_failure_tags": [{"tag": t, "count": c} for t, c in top_failures],
            "worst_performing_agents": [
                {"agent": a, "avg_score": round(s, 1), "interactions": len(agent_scores[a])}
                for a, s in worst_agents
            ],
            "active_directives": len([d for d in self._directives if time.time() - d.timestamp < 86400]),
            "total_interactions": self._total_interactions,
            "total_intercepts": self._total_intercepts,
        }

        self._trend_reports.append(report)
        if len(self._trend_reports) > 50:
            self._trend_reports = self._trend_reports[-50:]

        logger.info(
            "[GCI] Trend report: %d interactions, %.0f%% intercept rate, top failures: %s",
            len(recent), report["intercept_rate"] * 100,
            ", ".join(t["tag"] for t in top_failures[:3]),
        )

        self._save_state()

    # -------------------------------------------------------------------
    # Agent-Specific Feedback (for injection into agent prompts)
    # -------------------------------------------------------------------

    def get_agent_feedback(self, agent_id: str) -> Optional[str]:
        """
        Get improvement feedback for a specific agent.

        Returns a brief directive string to inject into the agent's context,
        or None if no active directives exist.
        """
        active = [
            d for d in self._directives
            if d.agent_id == agent_id
            and time.time() - d.timestamp < 86400  # Last 24 hours
            and d.severity in ("high", "critical")
        ]

        if not active:
            return None

        feedback_lines = [
            f"[GCI FEEDBACK] {d.error_type}: {d.remediation_step}"
            for d in active[:3]  # Max 3 directives
        ]
        return "\n".join(feedback_lines)

    # -------------------------------------------------------------------
    # Status & Reporting
    # -------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """Get comprehensive GCI status."""
        return {
            "total_interactions": self._total_interactions,
            "total_intercepts": self._total_intercepts,
            "intercept_rate": round(self._total_intercepts / max(self._total_interactions, 1), 3),
            "buffer_size": len(self._buffer),
            "agents_tracked": len(self._agent_records),
            "active_directives": len([d for d in self._directives if time.time() - d.timestamp < 86400]),
            "total_directives": len(self._directives),
            "trend_reports_generated": len(self._trend_reports),
            "thresholds": {
                "intercept": self.INTERCEPT_THRESHOLD,
                "critical": self.CRITICAL_THRESHOLD,
                "trend_interval": self.TREND_REPORT_INTERVAL,
            },
        }

    def get_agent_trends(self) -> List[Dict[str, Any]]:
        """Get per-agent performance trends."""
        trends = []
        for agent_id, records in self._agent_records.items():
            record_list = list(records)
            if not record_list:
                continue

            recent = record_list[-20:]
            avg_f = sum(r.factuality for r in recent) / len(recent)
            avg_a = sum(r.alignment for r in recent) / len(recent)
            avg_c = sum(r.cohesion for r in recent) / len(recent)
            avg_o = sum(r.overall_score for r in recent) / len(recent)

            # Trend direction from first half vs second half
            if len(recent) >= 6:
                first = recent[:len(recent)//2]
                second = recent[len(recent)//2:]
                first_avg = sum(r.overall_score for r in first) / len(first)
                second_avg = sum(r.overall_score for r in second) / len(second)
                if second_avg > first_avg + 0.3:
                    direction = "improving"
                elif second_avg < first_avg - 0.3:
                    direction = "declining"
                else:
                    direction = "stable"
            else:
                direction = "insufficient_data"

            # Common tags
            all_tags = [t for r in recent for t in r.tags]
            tag_freq = defaultdict(int)
            for t in all_tags:
                tag_freq[t] += 1
            common = sorted(tag_freq.items(), key=lambda x: x[1], reverse=True)[:5]

            # Active directives for this agent
            active_dirs = [d for d in self._directives if d.agent_id == agent_id and time.time() - d.timestamp < 86400]

            trends.append({
                "agent_id": agent_id,
                "total_interactions": len(record_list),
                "recent_interactions": len(recent),
                "avg_factuality": round(avg_f, 1),
                "avg_alignment": round(avg_a, 1),
                "avg_cohesion": round(avg_c, 1),
                "avg_overall": round(avg_o, 1),
                "trend_direction": direction,
                "common_tags": [{"tag": t, "count": c} for t, c in common],
                "intercept_rate": round(sum(1 for r in recent if r.intercepted) / len(recent), 2),
                "active_directives": len(active_dirs),
            })

        return sorted(trends, key=lambda t: t["avg_overall"])

    def get_directives(self, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get improvement directives, optionally filtered by agent."""
        directives = self._directives
        if agent_id:
            directives = [d for d in directives if d.agent_id == agent_id]
        return [d.to_dict() for d in directives[-30:]]

    def get_trend_reports(self) -> List[Dict[str, Any]]:
        """Get historical trend reports."""
        return self._trend_reports[-20:]

    def get_recent_interactions(self, limit: int = 20, agent_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get recent interaction records with quality scores."""
        records = list(self._buffer)
        if agent_id:
            records = [r for r in records if r.agent_id == agent_id]
        return [r.to_dict() for r in records[-limit:]]

    # -------------------------------------------------------------------
    # State Persistence
    # -------------------------------------------------------------------

    def _save_state(self):
        """Persist GCI state to disk."""
        try:
            state_dir = Path(self.STATE_FILE).parent
            state_dir.mkdir(parents=True, exist_ok=True)
            state = {
                "total_interactions": self._total_interactions,
                "total_intercepts": self._total_intercepts,
                "last_trend_report": self._last_trend_report,
                "directives": [d.to_dict() for d in self._directives[-50:]],
                "trend_reports": self._trend_reports[-20:],
            }
            with open(self.STATE_FILE, "w") as f:
                json.dump(state, f, indent=2, default=str)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            logger.debug("[GCI] Failed to save state: %s", exc)

    def _load_state(self):
        """Load GCI state from disk."""
        try:
            if not Path(self.STATE_FILE).exists():
                return
            with open(self.STATE_FILE) as f:
                data = json.load(f)

            self._total_interactions = data.get("total_interactions", 0)
            self._total_intercepts = data.get("total_intercepts", 0)
            self._last_trend_report = data.get("last_trend_report", 0)
            self._trend_reports = data.get("trend_reports", [])

            for ddata in data.get("directives", []):
                self._directives.append(ImprovementDirective(
                    agent_id=ddata.get("agent_id", ""),
                    error_type=ddata.get("error_type", ""),
                    root_cause=ddata.get("root_cause", ""),
                    remediation_step=ddata.get("remediation_step", ""),
                    severity=ddata.get("severity", "medium"),
                    timestamp=ddata.get("timestamp", 0),
                    interaction_count=ddata.get("interaction_count", 0),
                ))

            logger.info(
                "[GCI] Restored state: %d interactions, %d intercepts, %d directives",
                self._total_interactions, self._total_intercepts, len(self._directives),
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[GCI] Failed to load state: %s", exc)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_gci: Optional[GCIAgent] = None


def get_gci_agent() -> GCIAgent:
    """Get or create the singleton GCI Agent."""
    global _gci
    if _gci is None:
        _gci = GCIAgent()
    return _gci
