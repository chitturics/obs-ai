"""
Self-Learning Feedback — Reassessment, correctness gates, feedback analysis, and prompt overlay.

Extracted from self_learning.py for size management.
self_learning.py re-exports all public names.

Provides:
- reassess_past_answers, _calculate_coverage
- Correctness gate constants and stats (_gate_stats, etc.)
- get_gate_stats, _reset_gate_stats
- _check_answer_correctness, _check_rule_contradiction
- analyze_feedback_patterns, _extract_topic, learn_facts_from_feedback
- get_dynamic_prompt_overlay, rebuild_prompt_overlay
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, List

from chat_app.self_learning_models import QAPair, ReassessmentResult  # noqa: F401

logger = logging.getLogger(__name__)

async def reassess_past_answers(
    engine,
    search_func,
    vector_store,
    limit: int = 20,
) -> List[ReassessmentResult]:
    """
    Re-evaluate past answers using current collections.

    Fetches recent interactions, re-runs retrieval, and compares
    the new context quality against what was originally used.
    """
    results = []
    try:
        from sqlalchemy import text

        async with engine.begin() as conn:
            # Get recent interactions that haven't been reassessed
            rows = await conn.execute(text("""
                SELECT question, response, created_at
                FROM assistant_interactions
                WHERE created_at > NOW() - INTERVAL '7 days'
                ORDER BY created_at DESC
                LIMIT :lim
            """), {"lim": limit})
            interactions = rows.fetchall()

        for row in interactions:
            question = row[0]
            original_answer = row[1]
            if not question or not original_answer:
                continue

            try:
                # Re-retrieve chunks with current collections
                new_chunks = await asyncio.to_thread(
                    search_func, vector_store, question, k=10
                )

                # Build new answer text from retrieved chunks
                chunk_text = " ".join(c.get("text", "")[:200] for c in new_chunks[:5])

                # Gate 1: Score CORRECTNESS of both old and new using self_evaluator
                # (not just keyword coverage which drifts toward verbosity)
                old_quality = _check_answer_correctness(question, original_answer, new_chunks)
                new_quality = _check_answer_correctness(question, chunk_text, new_chunks)

                result = ReassessmentResult(
                    original_question=question,
                    original_answer=original_answer[:200],
                    confidence_delta=new_quality - old_quality,
                )

                # Gate 2: Only mark as improved if new score > old score + margin
                # This prevents marginal "improvements" that are really just verbosity drift
                if new_quality > old_quality + _REASSESS_QUALITY_MARGIN:
                    result.improved = True
                    result.improvement_reason = (
                        f"Quality improvement: new={new_quality:.2f} > old={old_quality:.2f} "
                        f"(margin={_REASSESS_QUALITY_MARGIN})"
                    )
                    _gate_stats["reassess_accepted"] += 1
                    logger.debug(
                        "[SELF-LEARN] Gate ACCEPTED reassessment for '%s': "
                        "old_quality=%.2f, new_quality=%.2f",
                        question[:60], old_quality, new_quality,
                    )
                else:
                    reason = (
                        "no_improvement" if new_quality <= old_quality
                        else "marginal"
                    )
                    if new_quality <= old_quality:
                        _gate_stats["reassess_rejected_no_improvement"] += 1
                    else:
                        _gate_stats["reassess_rejected_quality"] += 1
                    logger.debug(
                        "[SELF-LEARN] Gate REJECTED reassessment for '%s': "
                        "old_quality=%.2f, new_quality=%.2f, reason=%s",
                        question[:60], old_quality, new_quality, reason,
                    )

                results.append(result)
            except Exception as _exc:  # broad catch — resilience against all failures
                continue

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[SELF-LEARN] Reassessment failed: {exc}")

    return results


def _calculate_coverage(question: str, text: str) -> float:
    """Calculate how well text covers the question's key terms."""
    key_terms = set(re.findall(r'\b[a-z_]{3,}\b', question.lower()))
    stop_words = {'the', 'and', 'for', 'how', 'what', 'can', 'you', 'this', 'that', 'with', 'from', 'about'}
    key_terms -= stop_words
    if not key_terms:
        return 0.5
    text_lower = text.lower()
    matched = sum(1 for t in key_terms if t in text_lower)
    return matched / len(key_terms)


# ---------------------------------------------------------------------------
# Correctness Gates — Prevent drift toward verbosity over accuracy
# ---------------------------------------------------------------------------

# Counters for gate decision tracking (reset each learning cycle)
_gate_stats: Dict[str, int] = {
    "reassess_accepted": 0,
    "reassess_rejected_quality": 0,
    "reassess_rejected_no_improvement": 0,
    "overlay_rule_accepted": 0,
    "overlay_rule_rejected_contradiction": 0,
    "overlay_rule_rejected_quality": 0,
    "boost_accepted": 0,
    "boost_rejected_sample_size": 0,
    "boost_clamped": 0,
}

# Minimum quality improvement required to accept a reassessment update
_REASSESS_QUALITY_MARGIN = 0.1

# Minimum quality score for a new prompt overlay rule
_OVERLAY_RULE_MIN_QUALITY = 0.6

# Minimum sample size before adjusting retrieval boost weights
_BOOST_MIN_SAMPLES = 5

# Maximum per-cycle adjustment to retrieval boost scores
_BOOST_MAX_DELTA = 0.1


def get_gate_stats() -> Dict[str, int]:
    """Return current gate decision statistics (for monitoring/admin)."""
    return dict(_gate_stats)


def _reset_gate_stats():
    """Reset gate counters at the start of each learning cycle."""
    for key in _gate_stats:
        _gate_stats[key] = 0


def _check_answer_correctness(question: str, answer: str, context_chunks: List) -> float:
    """
    Score answer correctness (0-1) based on:
    - Factual grounding: % of answer claims supported by context chunks
    - Relevance: answer addresses the actual question
    - Consistency: no contradictions with retrieved knowledge

    Uses the heuristic-based self_evaluator to avoid LLM call overhead.
    """
    try:
        from chat_app.self_evaluator import evaluate_response_quality
    except ImportError:
        # Fallback to keyword coverage if self_evaluator unavailable
        return _calculate_coverage(question, answer)

    # Build context string from chunks
    if isinstance(context_chunks, list):
        context_parts = []
        for chunk in context_chunks[:5]:
            if isinstance(chunk, dict):
                context_parts.append(chunk.get("text", str(chunk))[:300])
            elif isinstance(chunk, str):
                context_parts.append(chunk[:300])
            else:
                context_parts.append(str(chunk)[:300])
        context = "\n".join(context_parts)
    else:
        context = str(context_chunks)[:1500]

    score = evaluate_response_quality(
        response=answer,
        user_query=question,
        context=context,
        chunks_found=len(context_chunks) if isinstance(context_chunks, list) else 0,
    )

    return score.overall


def _check_rule_contradiction(new_rule: str, existing_rules: List[str]) -> bool:
    """
    Check if a new rule contradicts any existing rules.

    Uses simple heuristic: if a new rule and existing rule share the same
    topic/entity but contain opposing sentiment markers, flag as contradiction.

    Returns True if contradiction detected.
    """
    if not existing_rules:
        return False

    new_lower = new_rule.lower()

    # Extract entity/topic from the rule (text inside quotes or after common prefixes)
    new_entities = set(re.findall(r"'([^']+)'", new_lower))
    new_entities.update(re.findall(r'"([^"]+)"', new_lower))

    if not new_entities:
        return False

    # Opposing sentiment pairs
    opposites = [
        ("reliable", "less reliable"),
        ("reliable", "unreliable"),
        ("improvement", "degradation"),
        ("high", "low"),
        ("increase", "decrease"),
        ("boost", "penalize"),
        ("keep doing", "needs improvement"),
        ("working well", "frequently fails"),
    ]

    for existing_rule in existing_rules:
        existing_lower = existing_rule.lower()

        # Check if they reference the same entity
        shared_entities = [e for e in new_entities if e in existing_lower]
        if not shared_entities:
            continue

        # Check for opposing sentiment about the same entity
        for positive, negative in opposites:
            if (positive in new_lower and negative in existing_lower) or \
               (negative in new_lower and positive in existing_lower):
                logger.info(
                    "[SELF-LEARN] Gate: Rule contradiction detected for entity '%s' — "
                    "new rule says '%s', existing says '%s'",
                    shared_entities[0],
                    positive if positive in new_lower else negative,
                    negative if negative in existing_lower else positive,
                )
                return True

    return False


# ---------------------------------------------------------------------------
# Prompt Improvement Engine
# ---------------------------------------------------------------------------

async def analyze_feedback_patterns(engine, min_samples: int = 5) -> Dict[str, Any]:
    """
    Analyze feedback patterns to identify areas for prompt improvement.

    Returns insights like:
    - Topics with consistently low satisfaction
    - Query types that frequently fail
    - Patterns in successful vs unsuccessful answers
    """
    insights = {
        "low_satisfaction_topics": [],
        "high_success_patterns": [],
        "common_failure_modes": [],
        "prompt_suggestions": [],
    }

    try:
        from sqlalchemy import text

        async with engine.begin() as conn:
            # Find topics with low satisfaction (disliked answers)
            result = await conn.execute(text("""
                SELECT question, COUNT(*) as cnt
                FROM assistant_disliked_queries
                WHERE created_at > NOW() - INTERVAL '30 days'
                GROUP BY question
                ORDER BY cnt DESC
                LIMIT 20
            """))
            disliked = result.fetchall()

            for row in disliked:
                question = row[0]
                count = row[1]
                if count >= 2:
                    # Extract the topic
                    topic = _extract_topic(question)
                    insights["low_satisfaction_topics"].append({
                        "topic": topic,
                        "sample_question": question,
                        "dislike_count": count,
                    })

            # Find patterns in successful answers (liked queries)
            result = await conn.execute(text("""
                SELECT question
                FROM assistant_liked_queries
                WHERE created_at > NOW() - INTERVAL '30 days'
                ORDER BY created_at DESC
                LIMIT 50
            """))
            liked = [r[0] for r in result.fetchall() if r[0]]

            if liked:
                topic_counts = {}
                for q in liked:
                    topic = _extract_topic(q)
                    topic_counts[topic] = topic_counts.get(topic, 0) + 1
                insights["high_success_patterns"] = sorted(
                    [{"topic": t, "count": c} for t, c in topic_counts.items()],
                    key=lambda x: x["count"], reverse=True
                )[:10]

            # Find common failure modes from episodes
            result = await conn.execute(text("""
                SELECT intent, failure_reason, COUNT(*) as cnt
                FROM assistant_episodes
                WHERE success = 0 AND created_at > NOW() - INTERVAL '30 days'
                GROUP BY intent, failure_reason
                HAVING COUNT(*) >= :min_samples
                ORDER BY cnt DESC
                LIMIT 10
            """), {"min_samples": min_samples})
            failures = result.fetchall()

            for row in failures:
                insights["common_failure_modes"].append({
                    "intent": row[0],
                    "reason": row[1],
                    "count": row[2],
                })

            # Generate prompt improvement suggestions
            for topic_info in insights["low_satisfaction_topics"][:5]:
                topic = topic_info["topic"]
                insights["prompt_suggestions"].append(
                    f"Consider adding more detailed guidance for '{topic}' queries in system prompt"
                )

            for failure in insights["common_failure_modes"][:3]:
                intent = failure["intent"]
                insights["prompt_suggestions"].append(
                    f"Intent '{intent}' has high failure rate - review retrieval strategy and prompt"
                )

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[SELF-LEARN] Feedback analysis failed: {exc}")

    return insights


def _extract_topic(question: str) -> str:
    """Extract the primary topic from a question."""
    lower = question.lower()
    topic_keywords = {
        "spl": r'\b(spl|query|search|stats|eval|where|tstats)\b',
        "config": r'\b(conf|config|stanza|inputs|props|transforms)\b',
        "troubleshooting": r'\b(error|fail|issue|debug|not working)\b',
        "indexing": r'\b(index|ingest|sourcetype|parsing)\b',
        "security": r'\b(security|alert|notable|threat|cim)\b',
        "dashboards": r'\b(dashboard|panel|visualization)\b',
        "cribl": r'\b(cribl|pipeline|route|pack)\b',
        "observability": r'\b(metric|trace|otel|opentelemetry|sli|slo)\b',
    }
    for topic, pattern in topic_keywords.items():
        if re.search(pattern, lower):
            return topic
    return "general"


# ---------------------------------------------------------------------------
# Semantic Fact Learning
# ---------------------------------------------------------------------------

async def learn_facts_from_feedback(engine, limit: int = 50) -> int:
    """
    Analyze recent feedback and generate semantic facts.

    Looks at patterns in liked/disliked answers to learn rules like:
    - "For SPL optimization queries, include tstats examples"
    - "For config queries, always quote stanza names verbatim"
    """
    facts_created = 0
    try:
        from chat_app.episodic_memory import store_semantic_fact, get_relevant_facts

        # Use lazy import so test patches on chat_app.self_learning.analyze_feedback_patterns are respected
        import chat_app.self_learning as _sl
        insights = await _sl.analyze_feedback_patterns(engine, min_samples=3)

        # Collect existing rules to check for contradictions
        existing_fact_rules = []
        try:
            existing_facts = await get_relevant_facts(engine, category=None, min_confidence=0.3, limit=30)
            existing_fact_rules = [f.get("rule", "") for f in existing_facts if f.get("rule")]
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

        # Learn from high success patterns
        for pattern in insights.get("high_success_patterns", [])[:5]:
            if pattern["count"] >= 3:
                rule = f"Users frequently ask about '{pattern['topic']}' - ensure comprehensive coverage in retrieval"
                # Gate: check contradiction with existing facts
                if _check_rule_contradiction(rule, existing_fact_rules):
                    logger.info("[SELF-LEARN] Gate REJECTED fact (contradiction): '%s'", rule[:80])
                    continue
                await store_semantic_fact(engine, rule, category="retrieval", confidence=0.6)
                existing_fact_rules.append(rule)
                facts_created += 1

        # Learn from failure modes
        for failure in insights.get("common_failure_modes", [])[:3]:
            rule = f"Intent '{failure['intent']}' frequently fails ({failure['count']} times) - consider alternative strategy"
            if _check_rule_contradiction(rule, existing_fact_rules):
                logger.info("[SELF-LEARN] Gate REJECTED fact (contradiction): '%s'", rule[:80])
                continue
            await store_semantic_fact(engine, rule, category="strategy", confidence=0.7)
            existing_fact_rules.append(rule)
            facts_created += 1

        # Learn from low satisfaction topics
        for topic_info in insights.get("low_satisfaction_topics", [])[:3]:
            rule = f"Topic '{topic_info['topic']}' has low user satisfaction - responses need improvement"
            if _check_rule_contradiction(rule, existing_fact_rules):
                logger.info("[SELF-LEARN] Gate REJECTED fact (contradiction): '%s'", rule[:80])
                continue
            await store_semantic_fact(engine, rule, category="quality", confidence=0.65)
            existing_fact_rules.append(rule)
            facts_created += 1

        logger.info(f"[SELF-LEARN] Created {facts_created} semantic facts from feedback")

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[SELF-LEARN] Fact learning failed: {exc}")

    return facts_created


# ---------------------------------------------------------------------------
# Dynamic Prompt Overlay — Apply learned patterns to inference
# ---------------------------------------------------------------------------

# Module-level cache for the dynamic prompt overlay
_prompt_overlay: str = ""
_prompt_overlay_timestamp: float = 0.0


def get_dynamic_prompt_overlay() -> str:
    """
    Return the current dynamic prompt overlay — learned behavioral rules
    that augment the static system prompt at inference time.

    This is THE key mechanism that closes the learning loop:
    the system learns patterns → they get injected into every response.
    """
    return _prompt_overlay


async def rebuild_prompt_overlay(engine) -> str:
    """
    Rebuild the dynamic prompt overlay from semantic facts, feedback patterns,
    and episode analysis. Called during learning cycles.

    The overlay is injected between the system prompt and user context,
    giving the LLM concrete behavioral rules learned from real interactions.
    """
    global _prompt_overlay, _prompt_overlay_timestamp
    overlay_parts = []

    try:
        from chat_app.episodic_memory import get_relevant_facts

        # 1. Inject high-confidence semantic facts as behavioral rules
        #    Gate: check each rule for contradictions and minimum quality
        facts = await get_relevant_facts(engine, category=None, min_confidence=0.6, limit=15)
        if facts:
            rules = []
            accepted_rule_texts = []  # Track plain text for contradiction checks
            for f in facts:
                rule = f.get("rule", "")
                conf = f.get("confidence", 0.5)
                if not rule or conf < _OVERLAY_RULE_MIN_QUALITY:
                    _gate_stats["overlay_rule_rejected_quality"] += 1
                    logger.debug(
                        "[SELF-LEARN] Gate REJECTED overlay rule (quality): "
                        "conf=%.2f < min=%.2f, rule='%s'",
                        conf, _OVERLAY_RULE_MIN_QUALITY, rule[:80],
                    )
                    continue

                # Check for contradictions with already-accepted rules
                if _check_rule_contradiction(rule, accepted_rule_texts):
                    _gate_stats["overlay_rule_rejected_contradiction"] += 1
                    logger.info(
                        "[SELF-LEARN] Gate REJECTED overlay rule (contradiction): '%s'",
                        rule[:80],
                    )
                    continue

                rules.append(f"- {rule}")
                accepted_rule_texts.append(rule)
                _gate_stats["overlay_rule_accepted"] += 1
                logger.debug(
                    "[SELF-LEARN] Gate ACCEPTED overlay rule: conf=%.2f, rule='%s'",
                    conf, rule[:80],
                )
            if rules:
                overlay_parts.append("## Learned Behavioral Rules (from feedback & episodes)")
                overlay_parts.extend(rules[:10])

        # 2. Apply feedback pattern insights as guidance
        # Use lazy import so test patches on chat_app.self_learning.analyze_feedback_patterns are respected
        import chat_app.self_learning as _sl
        insights = await _sl.analyze_feedback_patterns(engine, min_samples=2)

        # Low satisfaction warnings
        low_topics = insights.get("low_satisfaction_topics", [])
        if low_topics:
            overlay_parts.append("\n## Areas Needing Improvement (users frequently dislike these)")
            for t in low_topics[:5]:
                overlay_parts.append(
                    f"- Topic '{t['topic']}': {t['dislike_count']} dislikes — "
                    f"provide more detailed, accurate responses with concrete examples"
                )

        # High success patterns to reinforce
        high_patterns = insights.get("high_success_patterns", [])
        if high_patterns:
            overlay_parts.append("\n## What's Working Well (reinforce these patterns)")
            for p in high_patterns[:5]:
                if p["count"] >= 3:
                    overlay_parts.append(f"- Topic '{p['topic']}': {p['count']} positive responses — keep doing this")

        # Common failure modes to avoid
        failures = insights.get("common_failure_modes", [])
        if failures:
            overlay_parts.append("\n## Common Failure Modes (AVOID these)")
            for f in failures[:3]:
                overlay_parts.append(
                    f"- Intent '{f['intent']}' fails {f['count']} times: {f.get('reason', 'unknown reason')} — "
                    f"try alternative strategy"
                )

        # 3. Add collection effectiveness data for smarter retrieval references
        # Use lazy import so test patches on chat_app.self_learning.get_cached_boost_scores are respected
        import chat_app.self_learning as _sl
        boost_scores = _sl.get_cached_boost_scores()
        if boost_scores:
            top_collections = sorted(boost_scores.items(), key=lambda x: x[1], reverse=True)[:5]
            if top_collections:
                overlay_parts.append("\n## Collection Effectiveness (reference these sources)")
                for coll, score in top_collections:
                    quality = "highly reliable" if score > 1.2 else "reliable" if score > 0.9 else "less reliable"
                    overlay_parts.append(f"- {coll}: {quality} (score: {score:.2f})")

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[SELF-LEARN] Prompt overlay build failed: {exc}")

    _prompt_overlay = "\n".join(overlay_parts) if overlay_parts else ""
    _prompt_overlay_timestamp = time.monotonic()
    logger.info(f"[SELF-LEARN] Prompt overlay rebuilt: {len(overlay_parts)} rules, {len(_prompt_overlay)} chars")
    return _prompt_overlay


# ---------------------------------------------------------------------------
# Q&A Pair Ingestion to Vector Store
# ---------------------------------------------------------------------------

