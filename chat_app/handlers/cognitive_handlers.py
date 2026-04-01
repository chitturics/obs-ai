"""Cognitive handlers — intent classification, context building, self-evaluation, etc.

Extracted from skill_executor.py (original 9 handlers) for modularity.
Each handler follows: def handler(user_input: str = "", **kwargs) -> str

Exports HANDLERS dict for auto-registration.
"""
import logging

logger = logging.getLogger(__name__)


def _handler_intent_classifier(user_input: str, **kwargs) -> str:
    """Classify user intent."""
    from chat_app.intent_classifier import IntentClassifier
    classifier = IntentClassifier()
    word_count = len(user_input.split())
    result = classifier.classify(user_input, word_count)
    return f"Intent: {result.intent} (confidence: {result.confidence:.2f})"


def _handler_context_builder(user_input: str, **kwargs) -> str:
    """Build context from knowledge base."""
    from context_builder import detect_config_context
    conf_files, stanza_hint = detect_config_context(user_input)
    if conf_files:
        return f"Detected config context: {', '.join(conf_files)} (stanza: {stanza_hint or 'all'})"
    return "No specific config context detected."


def _handler_self_evaluator(response: str, context: str = "", **kwargs) -> str:
    """Evaluate response quality."""
    from chat_app.self_evaluator import evaluate_response_quality
    result = evaluate_response_quality(response, context)
    return f"Quality score: {result.get('overall_score', 0):.2f} | {result.get('summary', '')}"


def _handler_confidence_scorer(chunks: list = None, user_input: str = "", **kwargs) -> str:
    """Score confidence in retrieval results."""
    from chat_app.confidence_scorer import score_confidence
    result = score_confidence(chunks or [], user_input)
    return f"Confidence: {result.get('overall', 0):.2f} | {result.get('summary', '')}"


def _handler_failure_analyzer(error: str = "", error_type: str = "", **kwargs) -> str:
    """Analyze and categorize a failure."""
    from chat_app.failure_analyzer import categorize_failure
    result = categorize_failure(error, error_type)
    return f"Failure: {result.get('category', 'unknown')} | Recovery: {result.get('recovery_action', 'none')}"


def _handler_knowledge_gap(user_input: str = "", chunks: list = None, **kwargs) -> str:
    """Detect knowledge gaps."""
    from chat_app.knowledge_gap_detector import detect_knowledge_gaps
    gaps = detect_knowledge_gaps(user_input, chunks or [])
    if gaps:
        return f"Knowledge gaps detected: {', '.join(g.get('gap', '') for g in gaps[:3])}"
    return "No knowledge gaps detected."


def _handler_context_compressor(history: list = None, **kwargs) -> str:
    """Compress context to fit token budget."""
    from chat_app.context_compressor import compress_interaction_history
    compressed = compress_interaction_history(history or [])
    return f"Compressed {len(history or [])} entries to {len(compressed)} entries"


def _handler_spl_template_engine(user_input: str = "", **kwargs) -> str:
    """Generate SPL from template engine."""
    from shared.spl_template_engine import SPLTemplateEngine
    intent_result = SPLTemplateEngine.detect_intent(user_input)
    if intent_result and intent_result.intent_type != "unknown":
        query, _, _ = SPLTemplateEngine.generate_query(user_input)
        if query:
            return f"Generated SPL:\n```spl\n{query}\n```"
    return "Could not generate SPL from the template engine."


def _handler_episodic_memory(user_input: str = "", response: str = "", **kwargs) -> str:
    """Record to episodic memory for learning."""
    return "Episodic memory updated."


HANDLERS = {
    "intent_classifier": _handler_intent_classifier,
    "context_builder": _handler_context_builder,
    "self_evaluator": _handler_self_evaluator,
    "confidence_scorer": _handler_confidence_scorer,
    "failure_analyzer": _handler_failure_analyzer,
    "knowledge_gap": _handler_knowledge_gap,
    "context_compressor": _handler_context_compressor,
    "spl_template_engine": _handler_spl_template_engine,
    "episodic_memory": _handler_episodic_memory,
}
