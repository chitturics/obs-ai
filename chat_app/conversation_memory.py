"""
Conversation Memory — Multi-turn context management.

Maintains a rolling window of recent exchanges to support:
- Pronoun resolution ("optimize that query")
- Follow-up questions ("what about for firewall logs?")
- Context accumulation across turns
- Goal continuity tracking
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Maximum conversation turns to retain
MAX_TURNS = 5


def get_conversation_context(max_turns: int = 3) -> Optional[str]:
    """
    Build a conversation context string from recent turns.

    Returns a formatted string for injection into the LLM prompt,
    or None if no history is available.
    """
    try:
        import chainlit as cl
        history = cl.user_session.get("conversation_history", [])
    except Exception as _exc:  # broad catch — resilience against all failures
        return None

    if not history:
        return None

    recent = history[-max_turns:]
    if not recent:
        return None

    lines = ["### Recent Conversation Context:"]
    for turn in recent:
        q = turn.get("question", "")[:200]
        a_summary = turn.get("answer_summary", "")[:150]
        intent = turn.get("intent", "")
        lines.append(f"**User:** {q}")
        if a_summary:
            lines.append(f"**Assistant:** {a_summary}")
        if intent:
            lines.append(f"*(Intent: {intent})*")
        lines.append("")

    return "\n".join(lines)


def store_conversation_turn(
    question: str,
    answer: str,
    intent: str = "",
    profile: str = "",
):
    """
    Store a conversation turn in the session history.

    Keeps a rolling window of MAX_TURNS entries.
    """
    try:
        import chainlit as cl
        history = cl.user_session.get("conversation_history", [])
    except Exception as _exc:  # broad catch — resilience against all failures
        return

    # Summarize the answer (first 2 sentences or 200 chars)
    answer_summary = _summarize_answer(answer)

    turn = {
        "question": question,
        "answer_summary": answer_summary,
        "intent": intent,
        "profile": profile,
    }

    history.append(turn)

    # Keep only the last MAX_TURNS entries
    if len(history) > MAX_TURNS:
        history = history[-MAX_TURNS:]

    try:
        cl.user_session.set("conversation_history", history)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass


def resolve_references(user_input: str) -> str:
    """
    Attempt to resolve pronoun references using conversation history.

    Handles cases like:
    - "optimize that" → uses last SPL query
    - "explain it" → uses last answer context
    - "what about for firewall?" → extends last question
    """
    import re
    lower = user_input.lower().strip()

    # Check for pronoun-heavy short queries
    pronoun_patterns = [
        (r'^(optimize|improve|fix|review|explain|analyze)\s+(that|it|this|the query|the search)\s*$',
         "last_question"),
        (r'^what about\s+(.+)$', "extend_last"),
        (r'^(and|also|plus)\s+(.+)$', "extend_last"),
        (r'^(same|similar)\s+(but|for|with)\s+(.+)$', "modify_last"),
    ]

    try:
        import chainlit as cl
        last_question = cl.user_session.get("last_question", "")
        last_answer = cl.user_session.get("last_answer", "")
    except Exception as _exc:  # broad catch — resilience against all failures
        return user_input

    for pattern, action in pronoun_patterns:
        match = re.match(pattern, lower)
        if not match:
            continue

        if action == "last_question" and last_question:
            # "optimize that" → "optimize <last SPL query>"
            verb = match.group(1)
            # Try to extract SPL from the last question/answer
            spl = _extract_last_spl(last_question, last_answer)
            if spl:
                resolved = f"{verb} this query: {spl}"
                logger.info(f"[CONVERSATION] Resolved '{user_input}' → '{resolved[:80]}...'")
                return resolved

        elif action == "extend_last" and last_question:
            # "what about for firewall?" → extend previous question
            extension = match.group(1) if match.lastindex else ""
            resolved = f"{last_question} {extension}".strip()
            logger.info(f"[CONVERSATION] Extended: '{user_input}' → '{resolved[:80]}...'")
            return resolved

        elif action == "modify_last" and last_question:
            modifier = match.group(3) if match.lastindex >= 3 else ""
            resolved = f"{last_question} but {modifier}".strip()
            logger.info(f"[CONVERSATION] Modified: '{user_input}' → '{resolved[:80]}...'")
            return resolved

    return user_input


def _summarize_answer(answer: str) -> str:
    """Create a brief summary of the answer for context."""
    if not answer:
        return ""

    # Remove markdown formatting noise
    clean = answer.replace("**Confidence:**", "").strip()
    # Take first meaningful line
    lines = [l.strip() for l in clean.split('\n') if l.strip() and not l.startswith('---')]

    # Skip metadata lines (confidence, retrieval status)
    content_lines = [l for l in lines if not l.startswith("**Confidence") and not l.startswith("ChromaDB")]

    if not content_lines:
        return answer[:150]

    # First 2 content lines
    summary = " ".join(content_lines[:2])
    if len(summary) > 200:
        summary = summary[:197] + "..."

    return summary


def _extract_last_spl(question: str, answer: str) -> Optional[str]:
    """Extract SPL from the last question or answer."""
    from shared.utils import extract_spl_from_text

    # Try extracting from the answer first (code blocks are most reliable)
    spl = extract_spl_from_text(answer)
    if spl:
        return spl

    # Fallback: check if the question itself is SPL
    spl = extract_spl_from_text(question)
    if spl:
        return spl

    return None
