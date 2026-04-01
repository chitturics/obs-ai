"""
Error Recovery & Failure Analysis — Graceful degradation with learning.

Categorizes failures, suggests recovery strategies, and logs
failure patterns for the episodic memory system to learn from.
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class FailureType(str, Enum):
    RETRIEVAL_EMPTY = "retrieval_empty"
    RETRIEVAL_SPARSE = "retrieval_sparse"
    LLM_TIMEOUT = "llm_timeout"
    LLM_ERROR = "llm_error"
    LLM_EMPTY_RESPONSE = "llm_empty_response"
    TOOL_FAILED = "tool_failed"
    TOOL_TIMEOUT = "tool_timeout"
    HALLUCINATION_DETECTED = "hallucination_detected"
    SPL_INVALID = "spl_invalid"
    SPLUNK_AUTH_FAILED = "splunk_auth_failed"
    SPLUNK_CONNECTION_FAILED = "splunk_connection_failed"
    CRIBL_CONNECTION_FAILED = "cribl_connection_failed"
    REACT_LOOP_FAILED = "react_loop_failed"
    UNKNOWN = "unknown"


class RecoveryAction(str, Enum):
    RETRY_BROADER = "retry_broader"         # Retry with broader profile/k
    RETRY_SIMPLIFIED = "retry_simplified"   # Retry with simplified query
    USE_CACHE = "use_cache"                 # Fall back to cached response
    ASK_CLARIFICATION = "ask_clarification" # Ask user for more details
    ADMIT_UNCERTAINTY = "admit_uncertainty"  # Honestly say "I don't know"
    FALLBACK_DOCS = "fallback_docs"         # Suggest searching docs directly
    SKIP_TOOL = "skip_tool"                 # Skip tool and use RAG only
    RETRY_DIFFERENT_MODEL = "retry_model"   # Try different LLM model
    NONE = "none"                           # No recovery possible


@dataclass
class FailureReport:
    """Detailed failure analysis."""
    failure_type: FailureType
    severity: str = "medium"  # low, medium, high, critical
    message: str = ""
    recovery_actions: List[RecoveryAction] = field(default_factory=list)
    context: Dict[str, Any] = field(default_factory=dict)


def categorize_failure(
    exception: Exception,
    context: Dict[str, Any] = None,
) -> FailureReport:
    """
    Categorize an exception into a typed failure with recovery actions.

    Args:
        exception: The exception that occurred.
        context: Additional context (intent, profile, chunks_found, etc.)

    Returns:
        FailureReport with categorization and suggested recovery.
    """
    ctx = context or {}
    exc_str = str(exception).lower()
    exc_type = type(exception).__name__

    # Try exception-type-based classification first (more reliable than string matching)
    report = _classify_by_type(exception, exc_type, exc_str, ctx)
    if report:
        return report

    # Fall back to string-matching for untyped errors
    report = _classify_by_message(exc_str, exc_type, exception, ctx)
    return report


def _classify_by_type(
    exception: Exception, exc_type: str, exc_str: str, ctx: Dict[str, Any]
) -> Optional[FailureReport]:
    """Classify by exception type (isinstance checks — more reliable)."""
    # TimeoutError and subclasses
    if isinstance(exception, (TimeoutError, )):
        return FailureReport(
            failure_type=FailureType.LLM_TIMEOUT,
            severity="medium",
            message=f"LLM request timed out: {exception}",
            context=ctx,
            recovery_actions=[RecoveryAction.USE_CACHE, RecoveryAction.ADMIT_UNCERTAINTY],
        )

    # ConnectionError and subclasses
    if isinstance(exception, (ConnectionError, OSError)):
        if "splunk" in exc_str:
            return FailureReport(
                failure_type=FailureType.SPLUNK_CONNECTION_FAILED,
                severity="medium",
                message="Could not connect to Splunk",
                context=ctx,
                recovery_actions=[RecoveryAction.SKIP_TOOL, RecoveryAction.FALLBACK_DOCS],
            )
        return FailureReport(
            failure_type=FailureType.LLM_ERROR,
            severity="high",
            message=f"Service connection failed: {exception}",
            context=ctx,
            recovery_actions=[RecoveryAction.USE_CACHE, RecoveryAction.ADMIT_UNCERTAINTY],
        )

    # RuntimeError (often wraps model not found, etc.)
    if isinstance(exception, RuntimeError) and "model" in exc_str:
        return FailureReport(
            failure_type=FailureType.LLM_ERROR,
            severity="critical",
            message=f"LLM model not available: {exception}",
            context=ctx,
            recovery_actions=[RecoveryAction.ADMIT_UNCERTAINTY],
        )

    return None


def _classify_by_message(
    exc_str: str, exc_type: str, exception: Exception, ctx: Dict[str, Any]
) -> FailureReport:
    """Fall back to string-matching for unrecognized exception types."""
    # LLM timeouts
    if "timeout" in exc_str or "timed out" in exc_str:
        return FailureReport(
            failure_type=FailureType.LLM_TIMEOUT,
            severity="medium",
            message=f"LLM request timed out: {exception}",
            context=ctx,
            recovery_actions=[RecoveryAction.USE_CACHE, RecoveryAction.ADMIT_UNCERTAINTY],
        )

    # LLM connection errors
    if "connection" in exc_str or "refused" in exc_str:
        return FailureReport(
            failure_type=FailureType.LLM_ERROR,
            severity="high",
            message=f"LLM service unavailable: {exception}",
            context=ctx,
            recovery_actions=[RecoveryAction.USE_CACHE, RecoveryAction.ADMIT_UNCERTAINTY],
        )

    # Splunk auth errors
    if "authentication" in exc_str or "401" in exc_str:
        return FailureReport(
            failure_type=FailureType.SPLUNK_AUTH_FAILED,
            severity="medium",
            message="Splunk authentication failed",
            context=ctx,
            recovery_actions=[RecoveryAction.SKIP_TOOL, RecoveryAction.FALLBACK_DOCS],
        )

    # Model not found
    if "not found" in exc_str and "model" in exc_str:
        return FailureReport(
            failure_type=FailureType.LLM_ERROR,
            severity="critical",
            message=f"LLM model not available: {exception}",
            context=ctx,
            recovery_actions=[RecoveryAction.ADMIT_UNCERTAINTY],
        )

    # Tool execution failures
    if "tool" in exc_str and ("failed" in exc_str or "timeout" in exc_str or "error" in exc_str):
        return FailureReport(
            failure_type=FailureType.TOOL_FAILED,
            severity="medium",
            message=f"Agentic tool execution failed: {exception}",
            context=ctx,
            recovery_actions=[RecoveryAction.SKIP_TOOL, RecoveryAction.ADMIT_UNCERTAINTY],
        )

    # Cribl connection errors
    if "cribl" in exc_str:
        return FailureReport(
            failure_type=FailureType.CRIBL_CONNECTION_FAILED,
            severity="medium",
            message="Could not connect to Cribl service",
            context=ctx,
            recovery_actions=[RecoveryAction.FALLBACK_DOCS, RecoveryAction.ADMIT_UNCERTAINTY],
        )

    # ChromaDB / vector store errors (check for "chromadb" specifically, not generic "collection")
    if "chroma" in exc_str or "chromadb" in exc_str or "vector" in exc_str:
        return FailureReport(
            failure_type=FailureType.RETRIEVAL_EMPTY,
            severity="medium",
            message=f"Vector store error: {exception}",
            context=ctx,
            recovery_actions=[RecoveryAction.RETRY_BROADER, RecoveryAction.ADMIT_UNCERTAINTY],
        )

    # Generic fallback
    intent = ctx.get("intent", "unknown")
    logger.warning(f"[FAILURE] Unclassified error (intent={intent}, type={exc_type}): {exception}")
    return FailureReport(
        failure_type=FailureType.UNKNOWN,
        severity="medium",
        message=f"Unexpected error ({exc_type}): {exception}",
        context=ctx,
        recovery_actions=[RecoveryAction.ADMIT_UNCERTAINTY],
    )


def categorize_quality_failure(
    chunks_found: int,
    confidence: float,
    response_length: int,
) -> Optional[FailureReport]:
    """
    Categorize quality-level failures (not exceptions).

    Called when the pipeline succeeds but the output quality is poor.
    """
    if chunks_found == 0:
        return FailureReport(
            failure_type=FailureType.RETRIEVAL_EMPTY,
            severity="high",
            message="No relevant chunks found in any collection",
            recovery_actions=[
                RecoveryAction.RETRY_BROADER,
                RecoveryAction.RETRY_SIMPLIFIED,
                RecoveryAction.FALLBACK_DOCS,
            ],
        )

    if chunks_found < 3 and confidence < 0.4:
        return FailureReport(
            failure_type=FailureType.RETRIEVAL_SPARSE,
            severity="medium",
            message=f"Only {chunks_found} chunks with low confidence ({confidence:.2f})",
            recovery_actions=[
                RecoveryAction.RETRY_BROADER,
                RecoveryAction.ASK_CLARIFICATION,
            ],
        )

    if response_length < 50:
        return FailureReport(
            failure_type=FailureType.LLM_EMPTY_RESPONSE,
            severity="medium",
            message="LLM generated a very short response",
            recovery_actions=[
                RecoveryAction.RETRY_BROADER,
                RecoveryAction.ADMIT_UNCERTAINTY,
            ],
        )

    return None


async def execute_recovery(
    failure: FailureReport,
    user_input: str = "",
    user_query: str = "",
    search_func: Optional[Callable] = None,
    store: Any = None,
    user_settings: dict = None,
    context: Any = None,
) -> Optional[str]:
    """
    Execute the first viable recovery action.

    Checks episodic memory for past recovery successes before trying standard actions.
    Returns a recovery message/response if successful, None if all fail.
    """
    query = user_input or user_query

    # Check episodic memory for past recovery patterns
    try:
        engine = getattr(context, 'engine', None) if context else None
        if engine:
            from chat_app.episodic_memory import get_relevant_facts
            facts = await get_relevant_facts(engine, category="failure_recovery", min_confidence=0.6, limit=3)
            for fact in facts:
                rule = fact.get("rule", "")
                if failure.failure_type.value in rule.lower():
                    logger.info(f"[RECOVERY] Found learned pattern: {rule[:80]}")
                    # Learned facts inform but don't replace recovery — they're logged for context
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[RECOVERY] Failed to retrieve learned patterns: {exc}")

    for action in failure.recovery_actions:
        try:
            result = await _try_recovery(
                action, failure, query, search_func, store, user_settings
            )
            if result:
                logger.info(f"[RECOVERY] Action {action.value} succeeded for failure={failure.failure_type.value}")

                # Store successful recovery as an episode for future learning
                try:
                    if engine:
                        from chat_app.episodic_memory import store_episode
                        await store_episode(
                            engine=engine,
                            username="system",
                            query=f"[RECOVERY] {failure.failure_type.value}: {query[:200]}",
                            intent="error_recovery",
                            profile="system",
                            strategy_used=action.value,
                            success=1,
                            extra_metadata={
                                "failure_type": failure.failure_type.value,
                                "recovery_action": action.value,
                                "severity": failure.severity,
                            },
                        )
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                    logger.debug(f"[RECOVERY] Failed to store recovery episode: {exc}")

                return result
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning(f"[RECOVERY] Action {action.value} failed: {exc}")
            continue

    return None


async def _try_recovery(
    action: RecoveryAction,
    failure: FailureReport,
    user_query: str,
    search_func,
    store,
    user_settings,
) -> Optional[str]:
    """Attempt a single recovery action."""

    if action == RecoveryAction.ADMIT_UNCERTAINTY:
        return (
            "I wasn't able to find a confident answer for your question. "
            "This could be because:\n"
            "- The topic isn't covered in my knowledge base\n"
            "- The query may need to be more specific\n"
            "- A required service may be temporarily unavailable\n\n"
            "You can try:\n"
            "- Rephrasing your question with more detail\n"
            "- Using `/search <topic>` to search directly\n"
            "- Uploading relevant documentation with `read_url:` or `read_file:`"
        )

    if action == RecoveryAction.ASK_CLARIFICATION:
        return (
            "I found limited information on this topic. "
            "Could you help me narrow down your question?\n\n"
            "For example:\n"
            "- Which specific .conf file are you asking about?\n"
            "- What Splunk version are you running?\n"
            "- Can you share the specific error message or SPL query?"
        )

    if action == RecoveryAction.FALLBACK_DOCS:
        return (
            "I don't have enough context in my knowledge base for this question. "
            "You might find the answer in:\n"
            "- [Splunk Documentation](https://docs.splunk.com)\n"
            "- [Splunk Answers](https://community.splunk.com)\n"
            "- Your organization's internal wiki\n\n"
            "You can also ingest documentation directly: `read_url: <documentation_url>`"
        )

    if action == RecoveryAction.SKIP_TOOL:
        return None  # Handled by caller — skip the tool and continue with RAG

    return None
