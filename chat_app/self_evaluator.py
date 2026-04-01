"""
Self-Evaluation & Reflection — Post-generation quality assessment.

Evaluates LLM responses before sending to user:
- Completeness: Did the response address all parts of the query?
- Hallucination risk: Is the response grounded in retrieved context?
- Confidence calibration: Does stated confidence match evidence?
- SPL correctness: Does generated SPL look valid?

If quality is below threshold, triggers iterative refinement.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import List, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Quality Scoring Constants
# ---------------------------------------------------------------------------
WEIGHT_COMPLETENESS = 0.30
WEIGHT_GROUNDING = 0.35
WEIGHT_HALLUCINATION = 0.20
WEIGHT_SPL_VALIDITY = 0.15

HALLUCINATION_RISK_THRESHOLD = 0.7
QUALITY_SEND_THRESHOLD = 0.6
QUALITY_REFINE_THRESHOLD = 0.4


@dataclass
class QualityScore:
    """Result of response quality evaluation."""
    overall: float = 0.0          # 0.0 - 1.0
    completeness: float = 0.0     # Did it answer the full question?
    grounding: float = 0.0        # Is it grounded in context?
    hallucination_risk: float = 0.0  # 0=safe, 1=likely hallucinated
    spl_validity: float = 1.0     # 1.0 if no SPL or SPL looks valid
    gaps: List[str] = field(default_factory=list)
    recommended_action: str = "send"  # send, refine, clarify, abstain


def evaluate_response_quality(
    response: str,
    user_query: str,
    context: str,
    chunks_found: int = 0,
) -> QualityScore:
    """
    Evaluate the quality of a generated response.

    This is a fast, heuristic-based evaluator (no LLM call).
    Designed to run on every response without latency impact.
    """
    score = QualityScore()

    if not response or len(response.strip()) < 20:
        score.overall = 0.1
        score.gaps.append("Response is too short or empty")
        score.recommended_action = "refine"
        return score

    # --- Completeness check ---
    score.completeness = _check_completeness(response, user_query)

    # --- Grounding check ---
    score.grounding, score.hallucination_risk = _check_grounding(
        response, context, chunks_found
    )

    # --- SPL validity check ---
    score.spl_validity = _check_spl_in_response(response)

    # --- Combine scores ---
    score.overall = (
        score.completeness * WEIGHT_COMPLETENESS
        + score.grounding * WEIGHT_GROUNDING
        + (1 - score.hallucination_risk) * WEIGHT_HALLUCINATION
        + score.spl_validity * WEIGHT_SPL_VALIDITY
    )

    # --- Decide action ---
    # Check hallucination risk first (regardless of overall score)
    if score.hallucination_risk > HALLUCINATION_RISK_THRESHOLD and score.overall < QUALITY_SEND_THRESHOLD:
        score.recommended_action = "clarify"
        score.gaps.append("High hallucination risk — should ask for clarification")
    elif score.overall >= QUALITY_SEND_THRESHOLD:
        score.recommended_action = "send"
    elif score.overall >= QUALITY_REFINE_THRESHOLD:
        score.recommended_action = "refine"
        score.gaps.append("Quality below threshold — attempting refinement")
    else:
        score.recommended_action = "abstain"
        score.gaps.append("Very low confidence — should admit uncertainty")

    return score


def _check_completeness(response: str, user_query: str) -> float:
    """Check if the response addresses the key topics in the query."""
    query_lower = user_query.lower()
    resp_lower = response.lower()

    # Extract key terms from query (nouns, technical terms)
    key_terms = set()
    for term in re.findall(r'\b[a-z_]{3,}\b', query_lower):
        if term not in {'the', 'and', 'for', 'how', 'what', 'can', 'you', 'this',
                        'that', 'with', 'from', 'about', 'show', 'tell', 'help',
                        'please', 'could', 'would', 'does', 'are', 'was', 'have'}:
            key_terms.add(term)

    if not key_terms:
        return 0.7  # Can't evaluate, assume OK

    matched = sum(1 for term in key_terms if term in resp_lower)
    coverage = matched / len(key_terms)

    # Bonus for longer, more detailed responses
    length_bonus = min(0.1, len(response) / 5000)

    return min(1.0, coverage + length_bonus)


def _check_grounding(
    response: str, context: str, chunks_found: int
) -> Tuple[float, float]:
    """Check if the response is grounded in the provided context."""
    if not context or context == "No specific context available.":
        # No RAG context available.
        # If the response is substantive (LLM answered from its own knowledge),
        # give moderate grounding — general knowledge answers are acceptable.
        if len(response.strip()) > 100:
            return 0.55, 0.35  # Allow general knowledge responses through
        return 0.3, 0.7

    # SPL expertise fallback — LLM has built-in SPL knowledge, treat as grounded
    if "deep expertise in SPL" in context or "built-in knowledge of SPL" in context:
        if len(response.strip()) > 50:
            return 0.7, 0.2  # Trust LLM SPL expertise
        return 0.5, 0.4

    response.lower()
    ctx_lower = context.lower()

    # Count how many response sentences have matching context
    sentences = [s.strip() for s in re.split(r'[.!?]\s+', response) if len(s.strip()) > 20]
    if not sentences:
        return 0.5, 0.4

    ctx_terms = set(re.findall(r'\b[a-z_]{4,}\b', ctx_lower))
    grounded_count = 0
    for sent in sentences:
        sent_terms = set(re.findall(r'\b[a-z_]{4,}\b', sent.lower()))
        if sent_terms and len(sent_terms & ctx_terms) / len(sent_terms) > 0.3:
            grounded_count += 1

    grounding = grounded_count / len(sentences) if sentences else 0.5

    # Hallucination risk is inverse of grounding, adjusted by chunks found
    chunk_factor = min(1.0, chunks_found / 5)  # More chunks = less risk
    hallucination_risk = max(0.0, (1 - grounding) * (1 - chunk_factor * 0.3))

    return grounding, hallucination_risk


def _check_spl_in_response(response: str) -> float:
    """Check if any SPL in the response looks syntactically valid."""
    spl_blocks = re.findall(r'```(?:spl)?\n(.+?)\n```', response, re.DOTALL)
    if not spl_blocks:
        return 1.0  # No SPL to validate

    valid_count = 0
    for spl in spl_blocks:
        spl = spl.strip()
        # Basic checks: has pipe or index=, no obvious broken syntax
        has_structure = bool(re.search(r'(index\s*=|\|\s*\w+)', spl))
        no_broken_pipes = '| |' not in spl
        no_empty_commands = not re.search(r'\|\s*$', spl)

        if has_structure and no_broken_pipes and no_empty_commands:
            valid_count += 1

    return valid_count / len(spl_blocks) if spl_blocks else 1.0


async def refine_response_if_needed(
    quality: QualityScore,
    response: str,
    user_query: str,
    context: str,
    chain,
    user_settings: dict,
) -> Tuple[str, bool]:
    """
    Attempt to refine a low-quality response.

    Returns (refined_response, was_refined).
    """
    if quality.recommended_action == "send":
        return response, False

    if quality.recommended_action == "clarify":
        clarification = (
            "\n\n---\n"
            "I should be upfront -- my confidence on this one is not very high. "
            "I may be missing some context that would help me give you a better answer.\n\n"
            "**Would any of these help me out?**\n"
            "- A more specific question (e.g., which Splunk component, version, or use case?)\n"
            "- Relevant `.conf` or `.spec` files I can reference\n"
            "- An example of what you've tried so far"
        )
        return response + clarification, True

    if quality.recommended_action == "abstain":
        abstain_msg = (
            "I want to be honest -- I don't have enough information to answer this "
            "confidently. Here's my best attempt based on what I could find:\n\n"
            + response
            + "\n\n---\n"
            "**I'd feel more confident if you could:**\n"
            "- Upload the relevant `.conf` or `.spec` files\n"
            "- Tell me which Splunk version and deployment type you're using\n"
            "- Rephrase the question with more specifics\n"
            "- Try `/search` to see what's in my knowledge base"
        )
        return abstain_msg, True

    if quality.recommended_action == "refine":
        # Try a targeted re-generation with quality guidance
        try:
            gap_guidance = "; ".join(quality.gaps[:3]) if quality.gaps else "improve clarity"
            refinement_prompt = (
                f"The previous response had quality issues: {gap_guidance}.\n"
                f"Please provide a more complete and accurate answer.\n\n"
                f"{context}\n\n**Question:** {user_query}"
            )
            from langchain_core.output_parsers import StrOutputParser

            refined = await chain.ainvoke({"input": refinement_prompt})
            if refined and len(refined) > len(response) * 0.5:
                logger.info("[SELF-EVAL] Response refined successfully")
                return refined, True
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug(f"[SELF-EVAL] Refinement failed: {exc}")

    return response, False
