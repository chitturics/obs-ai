"""ObsAI as MCP Server -- Expose capabilities via Model Context Protocol."""
import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Role hierarchy for access control (higher index = more privilege)
_ROLE_LEVELS = {"VIEWER": 0, "USER": 1, "ANALYST": 2, "ADMIN": 3}

MCP_RESOURCES = [
    {"uri": "obsai://knowledge/{query}", "name": "ObsAI Knowledge Search",
     "description": "Search ObsAI's knowledge base across all collections", "mimeType": "text/plain"},
    {"uri": "obsai://collections", "name": "Collection List",
     "description": "List all available vector collections with document counts", "mimeType": "application/json"},
    {"uri": "obsai://graph/{entity}", "name": "Knowledge Graph Entity",
     "description": "Get entity details and relationships from the knowledge graph", "mimeType": "application/json"},
]

MCP_TOOLS = [
    # --- Read-only knowledge tools ---
    {"name": "obsai_search", "description": "Search ObsAI's knowledge base for Splunk/Cribl/observability information",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["query"], "properties": {
         "query": {"type": "string", "description": "Search query"},
         "collections": {"type": "array", "items": {"type": "string"}, "description": "Collections to search"},
         "k": {"type": "integer", "description": "Number of results", "default": 5}}}},
    {"name": "obsai_ask", "description": "Ask ObsAI a question and get an AI-powered answer with sources",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["question"], "properties": {
         "question": {"type": "string", "description": "Question to ask"}}}},
    {"name": "obsai_kg_query", "description": "Query the Splunk knowledge graph for entity relationships",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["entity"], "properties": {
         "entity": {"type": "string", "description": "Entity name"},
         "depth": {"type": "integer", "description": "Traversal depth", "default": 2}}}},
    {"name": "obsai_validate_spl", "description": "Validate and analyze an SPL query",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "required": ["spl"], "properties": {
         "spl": {"type": "string", "description": "SPL query to validate"}}}},
    # --- Read-only admin tools ---
    {"name": "obsai_health", "description": "Check ObsAI system health: services, containers, collections, pipeline status",
     "min_role": "VIEWER",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "obsai_config_diff", "description": "Show what config has changed since last save/reload",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "obsai_inventory", "description": "List configured Splunk indexes, sourcetypes, saved searches, or Cribl pipelines",
     "min_role": "USER",
     "inputSchema": {"type": "object", "properties": {
         "asset_type": {"type": "string", "enum": ["indexes", "sourcetypes", "saved_searches", "cribl_pipelines"],
                        "description": "Type of asset to list", "default": "indexes"}}}},
    # --- Controlled write tools (support dry_run) ---
    {"name": "obsai_config_update", "description": "Update a configuration section. Requires admin role. Shows diff before applying.",
     "min_role": "ADMIN",
     "inputSchema": {"type": "object", "required": ["section", "values"], "properties": {
         "section": {"type": "string", "description": "Config section name (e.g. retrieval, ingestion, features)"},
         "values": {"type": "object", "description": "Key-value pairs to update"},
         "dry_run": {"type": "boolean", "description": "Preview changes without applying", "default": True}}}},
    {"name": "obsai_container_action", "description": "Restart, stop, or start a container service. Requires admin role.",
     "min_role": "ADMIN",
     "inputSchema": {"type": "object", "required": ["service", "action"], "properties": {
         "service": {"type": "string", "description": "Container service name (e.g. chat_ui_app, llm_api_service)"},
         "action": {"type": "string", "enum": ["restart", "stop", "start"], "description": "Action to perform"},
         "dry_run": {"type": "boolean", "description": "Preview action without executing", "default": True}}}},
    {"name": "obsai_analyze_confs", "description": "Analyze Splunk props/transforms configurations for Cribl migration",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["apps_dir"], "properties": {
         "apps_dir": {"type": "string", "description": "Path to Splunk apps directory (e.g. /opt/splunk/etc/apps)"},
         "app_filter": {"type": "string", "description": "Filter to specific app name (optional)"}}}},
    {"name": "obsai_generate_docs", "description": "Generate professional documentation from code, configs, text, directories, or zip files",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["content"], "properties": {
         "content": {"type": "string", "description": "Text content, file path, directory path, or zip path to document"},
         "title": {"type": "string", "description": "Document title", "default": "Documentation"},
         "format": {"type": "string", "enum": ["markdown", "sharepoint"], "description": "Output format", "default": "markdown"},
         "mode": {"type": "string", "enum": ["snippet", "directory", "zip"], "description": "Generation mode", "default": "snippet"},
         "style": {"type": "string", "enum": ["technical", "user-friendly", "api-reference"], "description": "Documentation style", "default": "technical"}}}},

    # --- Phase 1: Core SPL Tools ---
    {"name": "obsai_explain_spl", "description": "Explain an SPL query step-by-step in plain language",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["spl"], "properties": {
         "spl": {"type": "string", "description": "SPL query to explain"}}}},
    {"name": "obsai_generate_spl", "description": "Generate SPL from a natural language description",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["description"], "properties": {
         "description": {"type": "string", "description": "What you want to search for, in plain English"},
         "index": {"type": "string", "description": "Target index (optional)"},
         "sourcetype": {"type": "string", "description": "Target sourcetype (optional)"}}}},
    {"name": "obsai_optimize_spl", "description": "Analyze and optimize an SPL query for better performance",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "required": ["spl"], "properties": {
         "spl": {"type": "string", "description": "SPL query to optimize"}}}},
    {"name": "obsai_run_search", "description": "Execute a Splunk search and return results",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "required": ["spl"], "properties": {
         "spl": {"type": "string", "description": "SPL query to execute"},
         "earliest": {"type": "string", "description": "Earliest time (e.g. -1h, -24h)", "default": "-1h"},
         "latest": {"type": "string", "description": "Latest time", "default": "now"},
         "max_results": {"type": "integer", "description": "Max results to return", "default": 100}}}},
    {"name": "obsai_create_alert", "description": "Create or configure a Splunk alert/saved search with scheduling",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "required": ["name", "search"], "properties": {
         "name": {"type": "string", "description": "Alert name"},
         "search": {"type": "string", "description": "SPL search query"},
         "cron": {"type": "string", "description": "Cron schedule (e.g. */5 * * * *)", "default": ""},
         "severity": {"type": "string", "enum": ["info", "warn", "error", "critical"], "default": "warn"},
         "dry_run": {"type": "boolean", "description": "Validate without creating", "default": True}}}},
    {"name": "obsai_deep_search", "description": "Deep multi-collection search with reranking and source attribution",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["query"], "properties": {
         "query": {"type": "string", "description": "Search query for deep analysis"},
         "collections": {"type": "array", "items": {"type": "string"}, "description": "Specific collections to search"},
         "k": {"type": "integer", "description": "Number of results per collection", "default": 10}}}},
    {"name": "obsai_reason", "description": "Multi-step ReAct reasoning: think, act, observe loop for complex questions",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["question"], "properties": {
         "question": {"type": "string", "description": "Complex question requiring multi-step reasoning"},
         "max_steps": {"type": "integer", "description": "Maximum reasoning steps", "default": 5}}}},

    # --- Phase 2: Scripting Automation (batched) ---
    {"name": "obsai_ansible", "description": "Ansible automation: validate, generate, explain, or improve playbooks",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["action", "content"], "properties": {
         "action": {"type": "string", "enum": ["validate", "generate", "explain", "improve", "module_reference"], "description": "Ansible operation"},
         "content": {"type": "string", "description": "Playbook YAML, task description, or module name"}}}},
    {"name": "obsai_shell_script", "description": "Shell scripting: analyze, generate, improve, or explain bash/shell scripts",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["action", "content"], "properties": {
         "action": {"type": "string", "enum": ["analyze", "generate", "improve", "explain"], "description": "Script operation"},
         "content": {"type": "string", "description": "Script content or description of what to generate"}}}},
    {"name": "obsai_python_script", "description": "Python scripting: analyze, generate, improve, or explain Python code",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["action", "content"], "properties": {
         "action": {"type": "string", "enum": ["analyze", "generate", "improve", "explain"], "description": "Script operation"},
         "content": {"type": "string", "description": "Python code or description of what to generate"}}}},

    # --- Phase 3: Utility Tools (compound) ---
    {"name": "obsai_encode_decode", "description": "Encode or decode data: base64, URL, hex, HTML",
     "min_role": "VIEWER",
     "inputSchema": {"type": "object", "required": ["operation", "data"], "properties": {
         "operation": {"type": "string", "enum": ["base64_encode", "base64_decode", "url_encode", "url_decode", "hex_encode", "hex_decode", "html_encode", "html_decode"],
                       "description": "Encoding/decoding operation"},
         "data": {"type": "string", "description": "Data to encode/decode"}}}},
    {"name": "obsai_hash", "description": "Generate cryptographic hash: MD5, SHA1, SHA256, SHA512",
     "min_role": "VIEWER",
     "inputSchema": {"type": "object", "required": ["data"], "properties": {
         "data": {"type": "string", "description": "Data to hash"},
         "algorithm": {"type": "string", "enum": ["md5", "sha1", "sha256", "sha512"], "default": "sha256"}}}},
    {"name": "obsai_transform_data", "description": "Transform data: JSON prettify/minify, CSV↔JSON, XML→JSON, KV parse",
     "min_role": "VIEWER",
     "inputSchema": {"type": "object", "required": ["operation", "data"], "properties": {
         "operation": {"type": "string", "enum": ["json_prettify", "json_minify", "csv_to_json", "json_to_csv", "xml_to_json", "kv_parse", "json_parse", "csv_parse"],
                       "description": "Transform operation"},
         "data": {"type": "string", "description": "Data to transform"}}}},
    {"name": "obsai_text_tools", "description": "Text manipulation: upper, lower, reverse, trim, sort lines, unique, remove empty",
     "min_role": "VIEWER",
     "inputSchema": {"type": "object", "required": ["operation", "text"], "properties": {
         "operation": {"type": "string", "enum": ["upper", "lower", "reverse", "trim", "line_sort", "unique_lines", "remove_empty_lines"],
                       "description": "Text operation"},
         "text": {"type": "string", "description": "Text to process"}}}},
    {"name": "obsai_spl_tools", "description": "SPL utilities: escape values, quote, rex extract, regex test, timestamp convert",
     "min_role": "VIEWER",
     "inputSchema": {"type": "object", "required": ["operation", "data"], "properties": {
         "operation": {"type": "string", "enum": ["spl_escape", "quote_values", "rex_extract", "regex_test", "timestamp_convert"],
                       "description": "SPL utility operation"},
         "data": {"type": "string", "description": "Data to process"},
         "pattern": {"type": "string", "description": "Regex pattern (for rex_extract/regex_test)"}}}},
    {"name": "obsai_validate_conf", "description": "Validate Splunk .conf files or check CIM compliance",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["operation", "data"], "properties": {
         "operation": {"type": "string", "enum": ["conf_validate", "cim_validate"], "description": "Validation type"},
         "data": {"type": "string", "description": "Conf content or field list to validate"}}}},

    # --- Phase 4: Admin, Security & Orchestration ---
    {"name": "obsai_security_audit", "description": "Run a security audit: check configs, permissions, vulnerabilities",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "properties": {
         "scope": {"type": "string", "enum": ["full", "configs", "permissions", "network"], "default": "full"},
         "target": {"type": "string", "description": "Specific target to audit (optional)"}}}},
    {"name": "obsai_manage_learning", "description": "Trigger self-learning: Q&A generation, reassessment, export training data",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "required": ["action"], "properties": {
         "action": {"type": "string", "enum": ["generate_qa", "reassess", "export_training", "status"], "description": "Learning operation"}}}},
    {"name": "obsai_orchestrate", "description": "Execute multi-agent orchestration with a specific strategy",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["query"], "properties": {
         "query": {"type": "string", "description": "Task or question for multi-agent processing"},
         "strategy": {"type": "string", "enum": ["adaptive", "single_agent", "parallel", "hierarchical", "review_critique", "voting", "react"],
                      "description": "Orchestration strategy", "default": "adaptive"}}}},
    {"name": "obsai_agent_dispatch", "description": "Route a query to the best-fit agent based on intent and expertise",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["query"], "properties": {
         "query": {"type": "string", "description": "Query to dispatch to an agent"},
         "department": {"type": "string", "description": "Preferred department (optional)"}}}},
    {"name": "obsai_spec_lookup", "description": "Look up Splunk .conf.spec reference files for configuration documentation",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["query"], "properties": {
         "query": {"type": "string", "description": "Spec file name or search term (e.g. 'inputs', 'props', 'transforms')"}}}},
    {"name": "obsai_build_config", "description": "Generate Splunk .conf configuration stanzas from requirements",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["config_type", "description"], "properties": {
         "config_type": {"type": "string", "enum": ["inputs", "props", "transforms", "savedsearches", "outputs", "alert_actions"],
                         "description": "Type of .conf to generate"},
         "description": {"type": "string", "description": "What the configuration should do"}}}},
    {"name": "obsai_manage_collection", "description": "Manage vector store collections: create, reindex, delete, stats",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "required": ["action"], "properties": {
         "action": {"type": "string", "enum": ["list", "stats", "create", "reindex", "delete"], "description": "Collection operation"},
         "collection": {"type": "string", "description": "Collection name (required for create/reindex/delete)"},
         "dry_run": {"type": "boolean", "description": "Preview without executing", "default": True}}}},
    {"name": "obsai_ingest", "description": "Ingest documents into the knowledge base: PDF, HTML, markdown, configs",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "required": ["source"], "properties": {
         "source": {"type": "string", "description": "File path, URL, or directory to ingest"},
         "collection": {"type": "string", "description": "Target collection", "default": "ingested_docs"},
         "doc_type": {"type": "string", "enum": ["auto", "pdf", "html", "markdown", "conf", "csv"], "default": "auto"}}}},
    {"name": "obsai_compare", "description": "Compare SPL commands, configs, or Splunk/Cribl approaches side-by-side",
     "min_role": "USER",
     "inputSchema": {"type": "object", "required": ["items"], "properties": {
         "items": {"type": "string", "description": "Two items to compare, separated by 'vs' (e.g. 'stats vs eventstats')"},
         "context": {"type": "string", "description": "Additional context for comparison"}}}},
    # --- Upgrade readiness and SLO tools ---
    {"name": "obsai_check_upgrade_readiness",
     "description": "Analyze Splunk app/TA upgrade readiness: conf diffs, CIM compliance, dependency impact",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "required": ["app_name", "cluster"], "properties": {
         "app_name": {"type": "string", "description": "Splunk app or TA name to evaluate"},
         "cluster": {"type": "string", "description": "Target Splunk cluster (e.g. cluster-search)"},
         "run_cim_check": {"type": "boolean", "description": "Also run CIM compliance check", "default": True}}}},
    {"name": "obsai_generate_runbook",
     "description": "Generate a step-by-step upgrade runbook with real Splunk CLI commands for a version transition",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "required": ["from_version", "to_version"], "properties": {
         "from_version": {"type": "string", "description": "Currently installed version, e.g. 9.3.2"},
         "to_version": {"type": "string", "description": "Target version, e.g. 10.2.1"},
         "upgrade_type": {"type": "string",
                          "enum": ["splunk_core", "es", "itsi", "uf", "app", "ta"],
                          "description": "Type of upgrade", "default": "splunk_core"},
         "app_id": {"type": "string", "description": "App directory name (for app/TA upgrades)"},
         "cluster": {"type": "string", "description": "Target cluster name"},
         "conf_files": {"type": "object",
                        "description": "Optional parsed conf files for config audit: {conf_name: {stanza: {key: value}}}"}}}},
    {"name": "obsai_check_slo",
     "description": "Check SLO compliance status and error budgets",
     "min_role": "USER",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "obsai_check_cim",
     "description": "Check CIM compliance for a Splunk app on a cluster",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "required": ["app_name", "cluster"], "properties": {
         "app_name": {"type": "string", "description": "Splunk app or TA name"},
         "cluster": {"type": "string", "description": "Target Splunk cluster"}}}},
    {"name": "obsai_manage_lessons",
     "description": "Query or record lessons learned from failures and corrections",
     "min_role": "USER",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["query", "record", "stats"], "description": "Operation to perform"},
         "query": {"type": "string", "description": "Search term for querying lessons"},
         "category": {"type": "string", "description": "Lesson category (e.g. deployment, upgrade, config)"},
         "description": {"type": "string", "description": "Description of the failure or issue (for record)"},
         "fix": {"type": "string", "description": "Resolution or fix applied (for record)"}}}},
    {"name": "obsai_run_evolution",
     "description": "Trigger daily self-improvement evolution cycle",
     "min_role": "ADMIN",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "obsai_check_dependencies",
     "description": "Map cross-app dependencies for a Splunk cluster",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "required": ["cluster"], "properties": {
         "cluster": {"type": "string", "description": "Splunk cluster to analyze"}}}},

    # --- Phase 6: Operations, User/Security, Configuration, Intelligence ---
    {"name": "obsai_backup",
     "description": "Create or list backups (config, collections, state, database)",
     "min_role": "ADMIN",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["create", "list", "status"], "default": "list"}}}},

    {"name": "obsai_audit_log",
     "description": "Query audit trail entries for configuration and admin actions",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "properties": {
         "limit": {"type": "integer", "default": 20, "description": "Max entries to return"},
         "section": {"type": "string", "description": "Filter by config section name"}}}},

    {"name": "obsai_version",
     "description": "Get app version, git info, and changelog",
     "min_role": "VIEWER",
     "inputSchema": {"type": "object", "properties": {}}},

    {"name": "obsai_manage_containers",
     "description": "List, restart, or check health of containers",
     "min_role": "ADMIN",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["list", "health", "restart", "logs"], "default": "list"},
         "service": {"type": "string", "description": "Container service name (required for restart/logs)"}}}},

    {"name": "obsai_manage_users",
     "description": "List users, roles, and manage access",
     "min_role": "ADMIN",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["list", "roles"], "default": "list"}}}},

    {"name": "obsai_manage_tokens",
     "description": "List or create API tokens",
     "min_role": "ADMIN",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["list", "create"], "default": "list"},
         "label": {"type": "string", "description": "Token label (required for create)"}}}},

    {"name": "obsai_ssl_status",
     "description": "Check SSL/TLS certificate status and network connectivity",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["status", "test_network"], "default": "status"}}}},

    {"name": "obsai_manage_ports",
     "description": "Get or update port configuration",
     "min_role": "ADMIN",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["get", "update"], "default": "get"}}}},

    {"name": "obsai_manage_settings",
     "description": "Get or update application settings by section",
     "min_role": "ADMIN",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["get", "update"], "default": "get"},
         "section": {"type": "string", "description": "Settings section name (e.g. retrieval, ingestion)"},
         "values": {"type": "object", "description": "Key-value pairs to update (required for update)"}}}},

    {"name": "obsai_manage_features",
     "description": "List, enable, or disable feature flags",
     "min_role": "ADMIN",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["list", "enable", "disable"], "default": "list"},
         "feature": {"type": "string", "description": "Feature flag name (required for enable/disable)"}}}},

    {"name": "obsai_manage_prompts",
     "description": "List or update prompt templates",
     "min_role": "ADMIN",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["list", "get", "update"], "default": "list"},
         "name": {"type": "string", "description": "Prompt name (required for get/update)"},
         "content": {"type": "string", "description": "New prompt content (required for update)"}}}},

    {"name": "obsai_manage_profiles",
     "description": "List LLM profiles and their configurations",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "properties": {}}},

    {"name": "obsai_manage_collections",
     "description": "List, browse, or manage ChromaDB collections",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["list", "browse", "stats"], "default": "list"},
         "collection": {"type": "string", "description": "Collection name (required for browse)"}}}},

    {"name": "obsai_knowledge_graph",
     "description": "Query knowledge graph entities and relationships",
     "min_role": "USER",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["stats", "query", "entities"], "default": "stats"},
         "query": {"type": "string", "description": "Search query (required for query action)"},
         "entity_type": {"type": "string", "description": "Filter by entity type (for entities action)"}}}},

    {"name": "obsai_observability",
     "description": "Get observability dashboard, traces, and analytics",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["dashboard", "traces", "analytics"], "default": "dashboard"}}}},

    {"name": "obsai_guardrails",
     "description": "Check guardrail configuration and trigger stats",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "properties": {}}},

    {"name": "obsai_artifacts",
     "description": "List generated artifacts and exports",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "properties": {}}},

    {"name": "obsai_manage_workflows",
     "description": "List workflow templates, history, and designer blocks",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["templates", "history", "designer"], "default": "templates"}}}},

    {"name": "obsai_splunkbase",
     "description": "Search Splunkbase catalog, check app versions, compare installed",
     "min_role": "USER",
     "inputSchema": {"type": "object", "properties": {
         "action": {"type": "string", "enum": ["search", "catalog", "compare"], "default": "catalog"},
         "query": {"type": "string", "description": "Search term for app lookup"}}}},

    {"name": "obsai_upgrade_es",
     "description": "Analyze Splunk Enterprise Security upgrade readiness",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "properties": {
         "cluster": {"type": "string", "default": "cluster-es", "description": "Target ES cluster name"}}}},

    {"name": "obsai_upgrade_itsi",
     "description": "Analyze ITSI upgrade readiness (KPIs, services, thresholds)",
     "min_role": "ANALYST",
     "inputSchema": {"type": "object", "properties": {
         "cluster": {"type": "string", "default": "cluster-itsi", "description": "Target ITSI cluster name"}}}},
    # Platform version intelligence
    {"name": "obsai_enterprise_versions", "description": "Get Splunk Enterprise/UF version history with features, breaking changes, and CVEs", "min_role": "USER", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "obsai_es_versions", "description": "Get Splunk Enterprise Security version history with release notes", "min_role": "USER", "inputSchema": {"type": "object", "properties": {}}},
    {"name": "obsai_version_diff", "description": "Compare two Splunk platform versions — features, breaking changes, CVEs between them", "min_role": "USER", "inputSchema": {"type": "object", "required": ["product", "from_version", "to_version"], "properties": {"product": {"type": "string", "enum": ["enterprise", "uf", "es"]}, "from_version": {"type": "string"}, "to_version": {"type": "string"}}}},
    {"name": "obsai_security_advisories", "description": "Get Splunk security advisories (CVEs) with severity and affected versions", "min_role": "USER", "inputSchema": {"type": "object", "properties": {"from_version": {"type": "string"}, "to_version": {"type": "string"}}}},
]

MCP_PROMPTS = [
    {"name": "splunk_expert", "description": "System prompt for Splunk expertise with ObsAI context",
     "arguments": [{"name": "topic", "description": "Specific Splunk topic", "required": False}]},
    {"name": "spl_generator", "description": "Generate SPL queries from natural language",
     "arguments": [{"name": "description", "description": "What to search for", "required": True}]},
]

# ---------------------------------------------------------------------------
# Handler Registry — imported from mcp_tool_handlers_ext for dispatch
# ---------------------------------------------------------------------------
from chat_app.mcp_tool_handlers_ext import _HANDLERS  # noqa: E402,F401


def check_tool_access(tool_name: str, user_role: Optional[str] = None) -> bool:
    """Check if a user role has access to the given MCP tool.

    Returns True if access is allowed, False otherwise.
    If user_role is None, access is denied by default.
    """
    if user_role is None:
        return False
    user_level = _ROLE_LEVELS.get(user_role.upper(), -1)
    tool_def = next((t for t in MCP_TOOLS if t["name"] == tool_name), None)
    if tool_def is None:
        return False
    required_level = _ROLE_LEVELS.get(tool_def.get("min_role", "USER"), 1)
    return user_level >= required_level


async def handle_mcp_tool_call(tool_name: str, arguments: Dict[str, Any], user_role: Optional[str] = None) -> Dict[str, Any]:
    """Execute an MCP tool call with optional role-based access control.

    If *user_role* is provided, the caller's role is checked against
    the tool's ``min_role`` before execution.
    """
    if user_role is not None and not check_tool_access(tool_name, user_role):
        logger.warning("MCP tool access denied: tool=%s user_role=%s", tool_name, user_role)
        return {"error": f"Access denied: role '{user_role}' cannot invoke tool '{tool_name}'"}
    handler = _HANDLERS.get(tool_name)
    if not handler:
        return {"error": f"Unknown tool: {tool_name}"}

    # Track every MCP tool call for observability
    try:
        from chat_app.execution_tracker import track_execution_ctx, ExecCategory
        handler_key = tool_name
        async with track_execution_ctx(
            ExecCategory.MCP_TOOL, tool_name,
            handler_key=handler_key,
            input_preview=str(arguments)[:200],
        ) as trace:
            result = await handler(arguments)
            trace.success = "error" not in result
            if "error" in result:
                trace.error = result["error"]
            return result
    except ImportError:
        return await handler(arguments)


def get_mcp_server_capabilities() -> Dict:
    return {"name": "obsai", "version": "3.5.0", "description": "ObsAI -- Splunk & Observability AI Assistant",
            "resources": MCP_RESOURCES, "tools": MCP_TOOLS, "prompts": MCP_PROMPTS}
