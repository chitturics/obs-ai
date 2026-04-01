"""
Context Compression — Manages context window for long conversations.

Summarizes old conversation turns into compact facts,
keeping recent turns in full detail while compressing older ones.
Prevents context bloat in extended sessions.
"""
import logging
import re
from dataclasses import dataclass, field
from typing import List

logger = logging.getLogger(__name__)

# Maximum turns to keep in full detail
_FULL_DETAIL_TURNS = 4
# Maximum compressed summary length (chars)
_MAX_SUMMARY_LENGTH = 800


@dataclass
class CompressedTurn:
    """A compressed representation of a conversation turn."""
    turn_number: int
    summary: str
    key_facts: List[str] = field(default_factory=list)
    query_topic: str = ""


def compress_interaction_history(
    interactions: List[str],
    max_full_turns: int = _FULL_DETAIL_TURNS,
) -> str:
    """
    Compress interaction history for context injection.

    Keeps the most recent `max_full_turns` in full detail,
    and summarizes older ones into compact facts.

    Args:
        interactions: List of formatted interaction strings
            (e.g., "User: question\\nAssistant: answer")
        max_full_turns: Number of recent turns to keep in full.

    Returns:
        Compressed context string.
    """
    if not interactions:
        return ""

    if len(interactions) <= max_full_turns:
        return "\n".join(interactions)

    # Split into old (to compress) and recent (keep full)
    old_turns = interactions[:-max_full_turns]
    recent_turns = interactions[-max_full_turns:]

    # Compress old turns
    compressed = _summarize_turns(old_turns)

    # Combine
    parts = []
    if compressed:
        parts.append(f"[Previous conversation summary: {compressed}]")
    parts.extend(recent_turns)

    return "\n".join(parts)


def _summarize_turns(turns: List[str]) -> str:
    """Summarize a list of conversation turns into key facts."""
    facts = []

    for turn in turns:
        # Extract the user question
        user_match = re.search(r'User:\s*(.+?)(?:\n|$)', turn)
        if user_match:
            question = user_match.group(1).strip()
            # Shorten to key topic
            topic = _extract_topic(question)
            if topic:
                facts.append(topic)

    if not facts:
        return ""

    # Deduplicate and limit
    unique_facts = list(dict.fromkeys(facts))[:8]
    summary = "Topics discussed: " + "; ".join(unique_facts)

    if len(summary) > _MAX_SUMMARY_LENGTH:
        summary = summary[:_MAX_SUMMARY_LENGTH] + "..."

    return summary


def _extract_topic(question: str) -> str:
    """Extract the core topic from a question."""
    # Remove common question prefixes
    cleaned = re.sub(
        r'^(how|what|can|could|please|help|show|explain|tell)\s+(do|to|me|is|are|about|with)?\s*',
        '', question, flags=re.IGNORECASE,
    ).strip()

    # Truncate to reasonable length
    words = cleaned.split()[:8]
    return " ".join(words) if words else ""


def estimate_context_tokens(context: str) -> int:
    """Rough estimate of token count (4 chars ≈ 1 token)."""
    return len(context) // 4


def should_compress(
    context: str,
    max_tokens: int = 4000,
) -> bool:
    """Check if the context needs compression."""
    return estimate_context_tokens(context) > max_tokens


def compress_context_if_needed(
    context: str,
    max_tokens: int = 4000,
) -> str:
    """
    Compress context sections if approaching token limit.

    Prioritizes keeping:
    1. Feedback guardrails (highest priority)
    2. Recent conversation history
    3. Top document snippets
    4. Older context (lowest priority — compressed first)
    """
    if not should_compress(context, max_tokens):
        return context

    logger.info(f"[COMPRESS] Context at ~{estimate_context_tokens(context)} tokens, compressing")

    sections = context.split("\n\n")
    compressed_sections = []
    total_chars = 0
    max_chars = max_tokens * 4

    for section in sections:
        if total_chars + len(section) > max_chars:
            # Truncate this section
            remaining = max_chars - total_chars
            if remaining > 200:
                compressed_sections.append(section[:remaining] + "\n[...truncated]")
            break
        compressed_sections.append(section)
        total_chars += len(section)

    result = "\n\n".join(compressed_sections)
    logger.info(f"[COMPRESS] Compressed to ~{estimate_context_tokens(result)} tokens")
    return result
