"""
Confidence Calibration — Nuanced confidence scoring with reasoning.

Replaces the simple HIGH/MEDIUM/LOW labels with a scored confidence
system that communicates uncertainty to both the LLM and user.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ScoredConfidence:
    """Scored confidence with reasoning."""
    score: float = 0.5            # 0.0 - 1.0
    label: str = "MEDIUM"         # HIGH, MEDIUM, LOW, VERY_LOW
    reasoning: str = ""
    sources_used: List[str] = field(default_factory=list)
    knowledge_gaps: List[str] = field(default_factory=list)
    should_clarify: bool = False
    clarification_question: Optional[str] = None


def score_confidence(
    local_spec_content: List[str],
    retrieved_chunks: List[dict],
    user_query: str,
    all_refs: List[str] = None,
    feedback_match: dict = None,
) -> ScoredConfidence:
    """
    Score confidence with detailed reasoning.

    Factors:
    - Number and quality of retrieved chunks
    - Presence of authoritative sources (spec files, org configs)
    - Feedback match (previously validated answer)
    - Query specificity vs. available context
    """
    result = ScoredConfidence()
    score_parts = []
    reasoning_parts = []

    # Factor 1: Retrieved chunks volume (up to 0.35)
    chunk_count = len(retrieved_chunks)
    if chunk_count >= 8:
        chunk_score = 0.35
        reasoning_parts.append(f"{chunk_count} relevant chunks retrieved")
    elif chunk_count >= 5:
        chunk_score = 0.30
        reasoning_parts.append(f"{chunk_count} chunks (good coverage)")
    elif chunk_count >= 3:
        chunk_score = 0.20
        reasoning_parts.append(f"{chunk_count} chunks (moderate coverage)")
    elif chunk_count >= 1:
        chunk_score = 0.10
        reasoning_parts.append(f"Only {chunk_count} chunks found (sparse)")
    else:
        chunk_score = 0.0
        reasoning_parts.append("No relevant chunks found")
        result.knowledge_gaps.append("No matching documents in knowledge base")
    score_parts.append(chunk_score)

    # Factor 2: Source diversity and authority
    collections_used = set()
    has_org_repo = False
    has_spec_files = False
    has_feedback = False

    for chunk in retrieved_chunks:
        coll = chunk.get("collection", "")
        collections_used.add(coll)
        if "org_repo" in coll:
            has_org_repo = True
        if "spec" in coll or "secondary" in coll:
            has_spec_files = True
        if "feedback" in coll:
            has_feedback = True

    source_score = min(0.10, len(collections_used) * 0.05)  # Base: up to 0.10 for 2+ collections
    if has_org_repo:
        source_score += 0.05
        reasoning_parts.append("Organization configs available")
    if has_spec_files:
        source_score += 0.05
        reasoning_parts.append("Official spec files matched")
    if has_feedback:
        source_score += 0.03
        reasoning_parts.append("Similar feedback Q&A found")
    source_score = min(0.30, source_score)
    score_parts.append(source_score)
    result.sources_used = list(collections_used)

    # Factor 3: Local spec files (authoritative)
    if local_spec_content:
        spec_score = min(0.20, len(local_spec_content) * 0.10)
        reasoning_parts.append(f"{len(local_spec_content)} authoritative spec stanzas")
    else:
        spec_score = 0.0
    score_parts.append(spec_score)

    # Factor 4: Feedback match (previously validated)
    if feedback_match:
        match_sim = feedback_match.get("similarity", 0)
        feedback_score = match_sim * 0.15
        reasoning_parts.append(f"Validated answer match (sim={match_sim:.2f})")
    else:
        feedback_score = 0.0
    score_parts.append(feedback_score)

    # Factor 5: Query specificity penalty
    query_length = len(user_query.split())
    if query_length <= 3:
        specificity_penalty = -0.05
        reasoning_parts.append("Query is very short/vague")
    elif query_length >= 15:
        specificity_penalty = 0.05
        reasoning_parts.append("Detailed query helps accuracy")
    else:
        specificity_penalty = 0.0
    score_parts.append(specificity_penalty)

    # Calculate final score
    raw_score = sum(score_parts)
    result.score = max(0.0, min(1.0, raw_score))

    # Assign label
    if result.score >= 0.7:
        result.label = "HIGH"
    elif result.score >= 0.45:
        result.label = "MEDIUM"
    elif result.score >= 0.25:
        result.label = "LOW"
    else:
        result.label = "VERY_LOW"

    result.reasoning = "; ".join(reasoning_parts) if reasoning_parts else "Insufficient data"

    # Determine if clarification is needed
    if result.score < 0.3 and chunk_count < 2:
        result.should_clarify = True
        result.clarification_question = _generate_clarification(user_query, result.knowledge_gaps)

    # Detect knowledge gaps
    _detect_knowledge_gaps(user_query, retrieved_chunks, result)

    return result


def _generate_clarification(query: str, gaps: List[str]) -> str:
    """Generate a clarification question for low-confidence queries."""
    lower = query.lower()

    if any(kw in lower for kw in ['.conf', 'stanza', 'config']):
        return "Could you specify which .conf file and stanza you're asking about? This will help me find the exact configuration."
    if any(kw in lower for kw in ['error', 'failing', 'not working']):
        return "Can you provide the error message or relevant log entries? This will help me diagnose the issue more accurately."
    if any(kw in lower for kw in ['spl', 'query', 'search']):
        return "Could you share the specific SPL query or describe the data you're searching? This will help me provide a more accurate answer."

    return "Could you provide more details about what you're looking for? I have limited context for this question."


def _detect_knowledge_gaps(
    query: str,
    chunks: List[dict],
    result: ScoredConfidence,
):
    """Identify specific knowledge gaps."""
    lower = query.lower()

    # Check for topics that might not be in the KB
    topic_patterns = {
        r'\b(cribl|stream|edge)\b': "Cribl documentation",
        r'\b(soar|phantom)\b': "Splunk SOAR/Phantom",
        r'\b(itsi|it service)\b': "Splunk ITSI",
        r'\b(enterprise security|es|notable)\b': "Enterprise Security",
        r'\b(uba|user behavior)\b': "Splunk UBA",
        r'\b(aws|azure|gcp|cloud)\b': "Cloud platform integration",
    }

    chunk_text = " ".join(c.get("text", "")[:200] for c in chunks[:5]).lower()

    for pattern, topic in topic_patterns.items():
        if re.search(pattern, lower) and not re.search(pattern, chunk_text):
            result.knowledge_gaps.append(f"May lack coverage for: {topic}")


def format_confidence_for_context(confidence: ScoredConfidence) -> str:
    """Format confidence info to inject into LLM context."""
    parts = [f"[CONFIDENCE: {confidence.label} ({confidence.score:.2f})]"]
    if confidence.reasoning:
        parts.append(f"Basis: {confidence.reasoning}")
    if confidence.knowledge_gaps:
        parts.append(f"Gaps: {'; '.join(confidence.knowledge_gaps[:3])}")
    if confidence.label == "VERY_LOW":
        parts.append(
            "CRITICAL INSTRUCTION: You have almost NO relevant context for this question. "
            "You MUST respond with: \"I don't have enough information in my knowledge base to answer this question accurately. "
            "Could you provide more details or rephrase your question?\" "
            "Do NOT attempt to answer from general knowledge. Do NOT guess. Do NOT hallucinate."
        )
    elif confidence.label == "LOW":
        parts.append(
            "IMPORTANT INSTRUCTION: You have very LIMITED context for this question. "
            "Start your response with a clear disclaimer like: \"Based on limited information in my knowledge base...\" "
            "If the retrieved context does not directly answer the question, say so honestly. "
            "Do NOT invent details, configs, paths, or parameter values."
        )
    elif confidence.label == "MEDIUM":
        parts.append(
            "NOTE: Only answer based on the retrieved context below. "
            "If any part of your answer is not supported by the context, explicitly state that."
        )
    return " | ".join(parts)


def format_confidence_for_user(confidence: ScoredConfidence) -> str:
    """Format a user-facing confidence indicator."""
    icons = {"HIGH": "HIGH", "MEDIUM": "MEDIUM", "LOW": "LOW", "VERY_LOW": "VERY LOW"}
    label = icons.get(confidence.label, confidence.label)

    sources = f" | Sources: {', '.join(confidence.sources_used[:4])}" if confidence.sources_used else ""
    return f"**Confidence:** {label}{sources}"
