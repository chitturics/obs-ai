"""
Skill Executor Dispatch — Handler registration and alias mapping.

Extracted from skill_executor.py to keep that file under 600 lines.
Contains:
- _SKILL_FALLBACKS mapping
- _register_builtin_internal_handlers() with all alias mappings
- Imported by skill_executor.py at module level
"""
import logging
from typing import Callable, Dict

logger = logging.getLogger(__name__)

# Fallback mapping: when a skill fails, try this alternative handler
_SKILL_FALLBACKS: Dict[str, str] = {
    "deep_analysis": "search_knowledge_base",
    "generate_spl": "spl_template_engine",
    "optimize_spl_advanced": "optimize_spl",
    "analyze_metrics": "search_knowledge_base",
    "create_dashboard": "search_knowledge_base",
    "deploy": "check_system_health",
}


def build_handler_aliases(handlers: Dict[str, Callable]) -> Dict[str, Callable]:
    """
    Build and return alias mappings that bridge agent catalog skill names
    to existing handler keys. Ensures all 53 agents have 100% skill resolution.
    """
    aliases: Dict[str, str] = {
        # Cognitive / reasoning
        "reason": "react_loop",
        "plan_actions": "query_planner",
        "evaluate_quality": "self_evaluator",
        "score_confidence": "confidence_scorer",
        "diagnose_failure": "failure_analyzer",
        "parse_input": "intent_classifier",
        "recall_context": "context_builder",
        "parse_document": "conf_parser",
        # Generation / composition
        "compose_query": "generate_spl",
        "generate_response": "response_generator",
        "craft_config": "config_generator",
        "design_architecture": "design",
        "summarize_results": "summarize",
        "answer_question": "general_qa",
        "teach_concept": "teach",
        # Search / retrieval
        "execute_search": "run_splunk_search",
        "browse_knowledge": "search_knowledge",
        "retrieve_chunks": "search_knowledge",
        "deep_dive_analysis": "deep_search",
        "read": "search_knowledge",
        # Data operations
        "aggregate_data": "aggregate",
        "transform_data": "transform",
        "filter_results": "filter",
        "extract_fields": "extract",
        "compare_configs": "compare",
        "collect_metrics": "analyze_metrics",
        "ingest_data": "ingest_document",
        # Operations
        "deploy_config": "deploy",
        "rollback_change": "rollback",
        "stabilize_system": "stabilize",
        "schedule_task": "scheduler",
        "trigger_alert": "create_alert",
        "warn_issues": "notify_critical",
        "audit_trail": "audit",
        "security_check": "security_audit",
        "organize_knowledge": "organize",
        "self_learn": "episodic_memory",
        "build_pipeline": "analyze_cribl_pipeline",
        # Communication / social
        "guide_user": "guided_mode",
        "request_clarification": "clarification",
        "resolve_conflict": "conflict_resolution",
        # Multi-agent / orchestration
        "orchestrate_workflow": "workflow_orchestrator",
        "multi_agent_task": "orchestrator",
        "assign_to_agent": "agent_dispatch",
        # Scripting aliases (agent uses short names)
        "ansible_validate": "ansible_validate_playbook",
        "ansible_generate": "ansible_generate_playbook",
        "ansible_explain": "ansible_explain_playbook",
        "ansible_improve": "ansible_improve_playbook",
        "ansible_reference": "ansible_module_reference",
        "shell_analyze": "shell_analyze_script",
        "shell_generate": "shell_generate_script",
        "shell_improve": "shell_improve_script",
        "shell_explain": "shell_explain_script",
        "python_analyze": "python_analyze_script",
        "python_generate": "python_generate_script",
        "python_improve": "python_improve_script",
        "python_explain": "python_explain_script",
        # Catalog skills without explicit handlers -> map to closest match
        "classify_intent": "intent_classifier",
        "compress_context": "context_compressor",
        "escalate_issue": "notify_critical",
        "export_results": "summarize",
        "search_deep": "deep_search",
        "translate_query": "nlp_to_spl",
        "critical_notification": "create_alert",
        "suggest_quietly": "search_suggestion",
        "adaptive_response": "response_generator",
        "execute_instruction": "direct_execution",
        "idle_mode": "idle_worker",
        "self_repair": "health_monitor",
        "purge_stale": "cleanup",
        "warm_up": "health_monitor",
        "reduce_load": "cleanup",
        "cache_results": "search_knowledge",
    }

    aliased: Dict[str, Callable] = {}
    for alias, target in aliases.items():
        if alias not in handlers and target in handlers:
            aliased[alias] = handlers[target]
    return aliased


def register_builtin_internal_handlers(
    register_fn: Callable[[str, Callable], None],
) -> None:
    """
    Register all built-in internal handlers from handler modules.

    Args:
        register_fn: The register_internal_handler() function from skill_executor.
    """
    from chat_app.handlers.cognitive_handlers import HANDLERS as _COGNITIVE_HANDLERS
    from chat_app.handlers.skill_handlers import HANDLERS as _SKILL_HANDLERS
    from chat_app.handlers.scripting_handlers import HANDLERS as _SCRIPTING_HANDLERS
    from chat_app.handlers.meta_handlers import HANDLERS as _META_HANDLERS
    from chat_app.handlers.utility_handlers import HANDLERS as _UTILITY_HANDLERS

    # Merge all handler dicts from extracted modules
    handlers: Dict[str, Callable] = {}
    handlers.update(_COGNITIVE_HANDLERS)
    handlers.update(_SKILL_HANDLERS)
    handlers.update(_SCRIPTING_HANDLERS)
    handlers.update(_META_HANDLERS)
    handlers.update(_UTILITY_HANDLERS)

    # Add aliases
    aliased = build_handler_aliases(handlers)
    handlers.update(aliased)

    for key, fn in handlers.items():
        register_fn(key, fn)
