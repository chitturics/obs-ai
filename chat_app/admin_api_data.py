"""Static data constants for admin_api.py.

Split out to keep admin_api.py under 600 lines.
Contains: _SECTION_RESTART_POLICY, _PROMPT_CATALOG, _COMPOSITION_ORDER.
"""

from typing import Any, Dict


# ---------------------------------------------------------------------------
# Config section restart policy
# ---------------------------------------------------------------------------

_SECTION_RESTART_POLICY: Dict[str, Dict[str, Any]] = {
    "active_profile":  {"action": "app_restart",  "services": ["chat_ui_app"],
                        "description": "Profile switch changes LLM model, context length, and performance tuning"},
    "profiles":        {"action": "app_restart",  "services": ["chat_ui_app"],
                        "description": "Profile definitions affect LLM and performance settings"},
    "directories":     {"action": "app_restart",  "services": ["chat_ui_app"],
                        "description": "Path changes require app restart to re-mount directories"},
    "database":        {"action": "full_restart", "services": ["chat_db_app", "chat_ui_app"],
                        "description": "Database config changes require both DB and app restart"},
    "ingestion":       {"action": "hot_reload",   "services": [],
                        "description": "Chunking and ingestion settings reload dynamically"},
    "retrieval":       {"action": "hot_reload",   "services": [],
                        "description": "Retrieval top_k, thresholds, and strategy reload dynamically"},
    "prompts":         {"action": "hot_reload",   "services": [],
                        "description": "Prompt settings reload dynamically"},
    "ui":              {"action": "app_restart",  "services": ["chat_ui_app"],
                        "description": "UI framework changes require app restart"},
    "security":        {"action": "hot_reload",   "services": [],
                        "description": "Rate limiting and CORS settings reload dynamically"},
    "features":        {"action": "hot_reload",   "services": [],
                        "description": "Feature flags reload dynamically"},
    "mcp_gateway":     {"action": "app_restart",  "services": ["chat_ui_app"],
                        "description": "MCP server connections require app restart"},
    "sharepoint":      {"action": "hot_reload",   "services": [],
                        "description": "SharePoint ingestion settings reload dynamically"},
    "github":          {"action": "hot_reload",   "services": [],
                        "description": "GitHub ingestion settings reload dynamically"},
    "organization":    {"action": "hot_reload",   "services": [],
                        "description": "Index/field mappings reload dynamically"},
    "orchestration":   {"action": "hot_reload",   "services": [],
                        "description": "Orchestration strategy and thresholds reload dynamically"},
    "docling":         {"action": "hot_reload",   "services": [],
                        "description": "Docling conversion settings reload dynamically"},
    "splunkbase_catalog": {"action": "hot_reload", "services": [],
                           "description": "Splunkbase catalog settings reload dynamically"},
    "ports":             {"action": "full_restart", "services": ["chat_ui_app"],
                          "description": "Port changes require container restart with new port bindings"},
    "knowledge_graph":   {"action": "hot_reload",   "services": [],
                          "description": "Knowledge graph settings reload dynamically; rebuild via admin API"},
    "langfuse":          {"action": "hot_reload",   "services": [],
                          "description": "Langfuse deprecated — tracing handled by OpenTelemetry"},
}


# ---------------------------------------------------------------------------
# Prompt catalog — documentation for every prompt used in the system
# ---------------------------------------------------------------------------

_PROMPT_CATALOG: Dict[str, Dict[str, str]] = {
    "system": {
        "category": "system",
        "description": "Primary system prompt defining the assistant's identity, capabilities, and behavioral rules.",
        "when_used": "Every LLM call — injected as the base system prompt for all conversations.",
        "impact": "Changing this affects ALL responses: identity, tone, anti-hallucination rules, SPL query rules, collection priority, and tool usage strategy.",
        "active": "always",
        "editable": "true",
    },
    "SYSTEM_PROMPT": {
        "category": "system",
        "description": "Primary system prompt (inline fallback). Same as 'system' template but defined in prompts.py.",
        "when_used": "Used when system.md template file is not found.",
        "impact": "Same as system — fallback for the core system prompt.",
        "active": "always",
        "editable": "false",
    },
    "query_generation": {
        "category": "query",
        "description": "Guide for building Splunk SPL queries with default assumptions, command selection (stats vs tstats), CIM data model mapping, and few-shot examples.",
        "when_used": "When intent is 'spl_query' or 'raw_spl' — user asks to write/generate a Splunk search query.",
        "impact": "Controls query construction rules, default time range (-15m), default Splunk version (9.5.4), tstats templates, TERM()/PREFIX() usage, and CIM compliance.",
        "active": "always",
        "editable": "true",
    },
    "QUERY_GENERATION_PROMPT": {
        "category": "query",
        "description": "Query generation prompt (inline fallback).",
        "when_used": "Used when query_generation.md template file is not found.",
        "impact": "Same as query_generation template.",
        "active": "always",
        "editable": "false",
    },
    "query_analysis": {
        "category": "analysis",
        "description": "Framework for interpreting Splunk query results: fact-based analysis, handling empty results, distinguishing facts from hypotheses.",
        "when_used": "When analyzing results returned from a Splunk search execution.",
        "impact": "Controls how query results are interpreted. Changing affects factual accuracy of result explanations and whether the assistant speculates or stays factual.",
        "active": "always",
        "editable": "true",
    },
    "QUERY_ANALYSIS_PROMPT": {
        "category": "analysis",
        "description": "Query analysis prompt (inline fallback).",
        "when_used": "Used when query_analysis.md template file is not found.",
        "impact": "Same as query_analysis template.",
        "active": "always",
        "editable": "false",
    },
    "config_guidance": {
        "category": "config",
        "description": "Guidance for Splunk .conf file configuration questions — requires citing sources, provides response template (file, stanza, settings, example).",
        "when_used": "When intent is 'config_guidance' — user asks about .conf file settings, stanza syntax, or configuration best practices.",
        "impact": "Controls conf file advice format and citation requirements. Removing source-citation rules may cause hallucinated config values.",
        "active": "always",
        "editable": "true",
    },
    "CONFIG_GUIDANCE_PROMPT": {
        "category": "config",
        "description": "Config guidance prompt (inline fallback).",
        "when_used": "Used when config_guidance.md template file is not found.",
        "impact": "Same as config_guidance template.",
        "active": "always",
        "editable": "false",
    },
    "conceptual": {
        "category": "conceptual",
        "description": "Framework for explaining Splunk concepts and architecture — clear explanations with practical guidance.",
        "when_used": "When intent is 'conceptual' — user asks 'how does X work', 'what is X', architecture questions.",
        "impact": "Controls explanation depth, response structure (direct answer, explanation, practical application, next steps).",
        "active": "always",
        "editable": "true",
    },
    "CONCEPTUAL_PROMPT": {
        "category": "conceptual",
        "description": "Conceptual prompt (inline fallback).",
        "when_used": "Used when conceptual.md template file is not found.",
        "impact": "Same as conceptual template.",
        "active": "always",
        "editable": "false",
    },
    "SEARCH_OPTIMIZATION_PROMPT": {
        "category": "optimization",
        "description": "Systematic framework for analyzing and optimizing SPL queries — 11-point priority checklist.",
        "when_used": "When intent is 'search_optimization' — user asks to optimize or improve an existing SPL query.",
        "impact": "Controls optimization analysis priority order and anti-pattern detection.",
        "active": "always",
        "editable": "false",
    },
    "query_optimizer": {
        "category": "optimization",
        "description": "Specialized tstats converter — step-by-step process for converting raw searches to tstats with TERM()/PREFIX() and data model acceleration.",
        "when_used": "When intent is 'optimize_query' — user wants to convert a search to use tstats or accelerated data models.",
        "impact": "Controls the tstats conversion methodology.",
        "active": "always",
        "editable": "true",
    },
    "QUERY_OPTIMIZER_PROMPT": {
        "category": "optimization",
        "description": "Query optimizer prompt (inline fallback).",
        "when_used": "Used when query_optimizer.md template file is not found.",
        "impact": "Same as query_optimizer template.",
        "active": "always",
        "editable": "false",
    },
    "ROUTING_GUIDE": {
        "category": "system",
        "description": "Decision tree for selecting the appropriate prompt based on user input type.",
        "when_used": "Used internally to route queries to the correct intent-specific prompt.",
        "impact": "Changing affects which prompt is selected for a given query.",
        "active": "always",
        "editable": "false",
    },
    "AGENT_RESPONSE_TEMPLATES": {
        "category": "agent",
        "description": "Dictionary of response structure templates per department.",
        "when_used": "When an agent persona is dispatched — structures the response format based on department.",
        "impact": "Controls section headings and response organization per department.",
        "active": "always",
        "editable": "false",
    },
    "gemini_query_generation": {
        "category": "query",
        "description": "Alternative query generation prompt tuned for Gemini API.",
        "when_used": "When using Gemini as the LLM backend instead of Ollama.",
        "impact": "Only affects Gemini-based query generation.",
        "active": "conditional",
        "editable": "true",
    },
    "profile:org_expert": {
        "category": "profile",
        "description": "Organization's Splunk configuration specialist.",
        "when_used": "When active profile is 'org_expert' or auto-detected from org-specific keywords.",
        "impact": "Replaces base system prompt. Focuses all responses on the organization's specific Splunk environment.",
        "active": "conditional",
        "editable": "false",
    },
    "profile:troubleshooter": {
        "category": "profile",
        "description": "Splunk troubleshooting specialist.",
        "when_used": "When active profile is 'troubleshooter' or auto-detected from troubleshooting keywords.",
        "impact": "Replaces base system prompt.",
        "active": "conditional",
        "editable": "false",
    },
    "profile:config_helper": {
        "category": "profile",
        "description": "Splunk configuration assistant.",
        "when_used": "When active profile is 'config_helper' or auto-detected from config-related keywords.",
        "impact": "Replaces base system prompt.",
        "active": "conditional",
        "editable": "false",
    },
    "profile:spl_expert": {
        "category": "profile",
        "description": "SPL command mastery.",
        "when_used": "When active profile is 'spl_expert' or auto-detected from advanced SPL keywords.",
        "impact": "Replaces base system prompt.",
        "active": "conditional",
        "editable": "false",
    },
    "profile:cribl_expert": {
        "category": "profile",
        "description": "Cribl Stream/Edge expert.",
        "when_used": "When active profile is 'cribl_expert' or auto-detected from Cribl-related keywords.",
        "impact": "Replaces base system prompt.",
        "active": "conditional",
        "editable": "false",
    },
    "profile:observability_expert": {
        "category": "profile",
        "description": "Senior observability & platform engineer.",
        "when_used": "When active profile is 'observability_expert' or auto-detected from observability keywords.",
        "impact": "Replaces base system prompt.",
        "active": "conditional",
        "editable": "false",
    },
    "dynamic_overlay": {
        "category": "dynamic",
        "description": "Learned behavioral rules injected from the self-learning pipeline.",
        "when_used": "Prepended to EVERY system prompt when available.",
        "impact": "Adds learned rules. Removing clears learned behavior.",
        "active": "conditional",
        "editable": "false",
    },
}


# ---------------------------------------------------------------------------
# Prompt composition order documentation
# ---------------------------------------------------------------------------

_COMPOSITION_ORDER = [
    {"step": 1, "layer": "Dynamic Overlay", "description": "Learned behavioral rules from self-learning pipeline", "position": "prepended first"},
    {"step": 2, "layer": "Agent Prompt Fragment", "description": "Agent persona (department directive + expertise style + skills)", "position": "injected if agent dispatched"},
    {"step": 3, "layer": "Profile System Prompt", "description": "Role-specific prompt (org_expert, spl_expert, etc.)", "position": "replaces base if profile active"},
    {"step": 4, "layer": "Base System Prompt", "description": "SYSTEM_PROMPT — core identity and rules", "position": "fallback if no profile"},
    {"step": 5, "layer": "Intent-Specific Prompt", "description": "query_generation, config_guidance, conceptual, etc.", "position": "appended to context"},
    {"step": 6, "layer": "RAG Context", "description": "Retrieved documents from vector store collections", "position": "injected into user context"},
    {"step": 7, "layer": "Knowledge Graph Context", "description": "Structural facts from entity/relationship graph", "position": "appended after RAG context"},
    {"step": 8, "layer": "Final LLM Input", "description": "All layers combined into the prompt sent to the LLM", "position": "assembled by message_handler.py"},
]
