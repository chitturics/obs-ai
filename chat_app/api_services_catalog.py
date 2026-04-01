"""
API Services Catalog — The complete service registry (all ServiceDefinition entries).

Extracted from api_services.py to keep that file under 600 lines.
Imported by api_services.py and re-exported for backward compatibility.
"""
from typing import Dict

from chat_app.api_services_types import (
    ServiceAccess,
    ServiceCategory,
    ServiceDefinition,
)


def _build_service_catalog() -> Dict[str, ServiceDefinition]:
    """Build the complete service catalog."""
    services = {}

    def _add(svc: ServiceDefinition):
        services[svc.service_id] = svc

    # ── SPL Services ──

    _add(ServiceDefinition(
        service_id="spl-validate",
        name="Validate SPL",
        description="Validate SPL search query syntax and detect dangerous patterns.",
        category=ServiceCategory.SPL,
        handler_key="validate_spl",
        access_level=ServiceAccess.USER,
        input_schema={"type": "object", "properties": {"input": {"type": "string", "description": "SPL query to validate"}}, "required": ["input"]},
        example_input={"input": "index=main sourcetype=syslog | stats count by host"},
        example_output={"success": True, "output": {"valid": True, "issues": [], "dangerous_patterns": []}},
        tags=["spl", "validation"],
    ))

    _add(ServiceDefinition(
        service_id="spl-analyze",
        name="Analyze SPL",
        description="Analyze SPL search for performance issues, anti-patterns, and optimization opportunities.",
        category=ServiceCategory.SPL,
        handler_key="analyze_spl",
        access_level=ServiceAccess.USER,
        input_schema={"type": "object", "properties": {"input": {"type": "string", "description": "SPL query to analyze"}}, "required": ["input"]},
        example_input={"input": "index=* | stats count by host | sort -count | head 10"},
        example_output={"success": True, "output": {"issues": ["Uses index=* (scans all data)", "Consider adding time bounds"], "score": 6.5}},
        tags=["spl", "analysis", "performance"],
    ))

    _add(ServiceDefinition(
        service_id="spl-optimize",
        name="Optimize SPL",
        description="Optimize SPL search query for better performance.",
        category=ServiceCategory.SPL,
        handler_key="optimize_spl",
        access_level=ServiceAccess.USER,
        input_schema={"type": "object", "properties": {"input": {"type": "string", "description": "SPL query to optimize"}}, "required": ["input"]},
        example_input={"input": "index=main | search sourcetype=syslog | stats count by host"},
        example_output={"success": True, "output": "index=main sourcetype=syslog | stats count by host"},
        tags=["spl", "optimization"],
    ))

    _add(ServiceDefinition(
        service_id="spl-explain",
        name="Explain SPL",
        description="Get a step-by-step explanation of an SPL search query.",
        category=ServiceCategory.SPL,
        handler_key="explain_spl",
        access_level=ServiceAccess.USER,
        input_schema={"type": "object", "properties": {"input": {"type": "string", "description": "SPL query to explain"}}, "required": ["input"]},
        example_input={"input": "index=main sourcetype=syslog | timechart count by host"},
        example_output={"success": True, "output": "Step 1: Search index=main for syslog events..."},
        tags=["spl", "explanation"],
    ))

    _add(ServiceDefinition(
        service_id="spl-generate",
        name="Generate SPL",
        description="Generate an SPL search query from a natural language description.",
        category=ServiceCategory.SPL,
        handler_key="generate_spl",
        access_level=ServiceAccess.ANALYST,
        input_schema={"type": "object", "properties": {"input": {"type": "string", "description": "Natural language description of what you want to search for"}}, "required": ["input"]},
        example_input={"input": "Show me the top 10 hosts with the most errors in the last 24 hours"},
        example_output={"success": True, "output": "index=main level=ERROR earliest=-24h | stats count by host | sort -count | head 10"},
        tags=["spl", "generation", "nlp"],
    ))

    _add(ServiceDefinition(
        service_id="spl-bulk",
        name="Bulk SPL Analysis",
        description="Analyze, validate, or optimize multiple SPL queries in one request.",
        category=ServiceCategory.SPL,
        handler_key="_bulk_spl",
        access_level=ServiceAccess.ANALYST,
        rate_limit_per_minute=10,
        timeout_seconds=120,
        input_schema={"type": "object", "properties": {
            "params": {"type": "object", "properties": {
                "queries": {"type": "array", "items": {"type": "string"}},
                "action": {"type": "string", "enum": ["validate", "optimize", "explain", "analyze"]},
            }},
        }},
        example_input={"params": {"queries": ["index=main | stats count", "index=* | top host"], "action": "validate"}},
        example_output={"success": True, "output": {"results": [{"query": "...", "valid": True}]}},
        tags=["spl", "bulk", "batch"],
    ))

    # ── Search Services ──

    _add(ServiceDefinition(
        service_id="knowledge-search",
        name="Knowledge Base Search",
        description="Semantic search across the ObsAI knowledge base (vector store).",
        category=ServiceCategory.SEARCH,
        handler_key="search_knowledge_base",
        access_level=ServiceAccess.USER,
        input_schema={"type": "object", "properties": {
            "input": {"type": "string", "description": "Search query"},
            "params": {"type": "object", "properties": {"k": {"type": "integer", "default": 5}}},
        }, "required": ["input"]},
        example_input={"input": "How to configure HEC token in Splunk", "params": {"k": 5}},
        example_output={"success": True, "output": [{"text": "...", "score": 0.85, "collection": "spl_docs"}]},
        tags=["search", "knowledge", "rag"],
    ))

    _add(ServiceDefinition(
        service_id="deep-search",
        name="Deep Multi-Pass Search",
        description="Deep search with multiple retrieval passes across all collections.",
        category=ServiceCategory.SEARCH,
        handler_key="deep_search",
        access_level=ServiceAccess.ANALYST,
        rate_limit_per_minute=10,
        timeout_seconds=90,
        input_schema={"type": "object", "properties": {"input": {"type": "string"}}, "required": ["input"]},
        example_input={"input": "props.conf TIME_FORMAT configuration for custom sourcetypes"},
        example_output={"success": True, "output": "Detailed multi-pass search results..."},
        tags=["search", "deep", "comprehensive"],
    ))

    # ── Config Services ──

    _add(ServiceDefinition(
        service_id="config-parse",
        name="Parse Configuration File",
        description="Parse and validate a Splunk .conf file, returning stanzas and settings.",
        category=ServiceCategory.CONFIG,
        handler_key="conf_parser",
        access_level=ServiceAccess.USER,
        input_schema={"type": "object", "properties": {
            "input": {"type": "string", "description": "Configuration file content (paste the .conf content)"},
        }, "required": ["input"]},
        example_input={"input": "[default]\nhost = myserver\n\n[monitor:///var/log/syslog]\nindex = main\nsourcetype = syslog"},
        example_output={"success": True, "output": {"stanzas": [{"name": "default", "settings": {"host": "myserver"}}]}},
        tags=["config", "parsing", "validation"],
    ))

    _add(ServiceDefinition(
        service_id="config-generate",
        name="Generate Configuration",
        description="Generate Splunk configuration files (inputs.conf, props.conf, transforms.conf, etc.).",
        category=ServiceCategory.CONFIG,
        handler_key="config_generator",
        access_level=ServiceAccess.ANALYST,
        input_schema={"type": "object", "properties": {
            "input": {"type": "string", "description": "Description of what config to generate"},
            "params": {"type": "object", "properties": {"config_type": {"type": "string"}}},
        }, "required": ["input"]},
        example_input={"input": "Create an inputs.conf to monitor /var/log/apache2/access.log with sourcetype=access_combined"},
        example_output={"success": True, "output": "[monitor:///var/log/apache2/access.log]\nindex = main\nsourcetype = access_combined"},
        tags=["config", "generation"],
    ))

    _add(ServiceDefinition(
        service_id="security-audit",
        name="Security Audit",
        description="Audit Splunk configuration for security issues and best practices.",
        category=ServiceCategory.CONFIG,
        handler_key="security_audit",
        access_level=ServiceAccess.ANALYST,
        input_schema={"type": "object", "properties": {"input": {"type": "string", "description": "Config content or description to audit"}}, "required": ["input"]},
        example_input={"input": "[default]\npassword = admin123\nallowRemoteLogin = always"},
        example_output={"success": True, "output": {"issues": [{"severity": "critical", "finding": "Hardcoded password"}]}},
        tags=["security", "audit", "compliance"],
    ))

    # ── Monitoring Services ──

    _add(ServiceDefinition(
        service_id="health-check",
        name="System Health Check",
        description="Check overall system health including all services.",
        category=ServiceCategory.MONITORING,
        handler_key="check_system_health",
        method="GET",
        access_level=ServiceAccess.USER,
        input_schema={},
        example_output={"success": True, "output": {"status": "healthy", "services": {"ollama": "up", "chromadb": "up"}}},
        tags=["health", "monitoring"],
    ))

    _add(ServiceDefinition(
        service_id="create-alert",
        name="Create Alert Definition",
        description="Generate a Splunk alert configuration from a description.",
        category=ServiceCategory.MONITORING,
        handler_key="create_alert",
        access_level=ServiceAccess.ANALYST,
        input_schema={"type": "object", "properties": {
            "input": {"type": "string", "description": "Description of alert to create"},
            "params": {"type": "object", "properties": {
                "alert_name": {"type": "string"},
                "threshold": {"type": "number"},
            }},
        }, "required": ["input"]},
        example_input={"input": "Alert when error count exceeds 100 in 5 minutes", "params": {"alert_name": "high_error_rate"}},
        example_output={"success": True, "output": {"alert_config": "..."}},
        tags=["alert", "monitoring"],
    ))

    # ── Splunkbase Services ──

    _add(ServiceDefinition(
        service_id="splunkbase-check",
        name="Splunkbase App Version Check",
        description="Check installed Splunk apps against Splunkbase for available updates. "
                    "Accepts a list of app names with optional versions.",
        category=ServiceCategory.SPLUNKBASE,
        handler_key="_splunkbase_check",
        access_level=ServiceAccess.USER,
        rate_limit_per_minute=5,
        timeout_seconds=120,
        input_schema={"type": "object", "properties": {
            "params": {"type": "object", "properties": {
                "apps": {"type": "array", "items": {"type": "object", "properties": {
                    "name": {"type": "string"},
                    "version": {"type": "string"},
                }}, "description": "List of installed apps"},
            }, "required": ["apps"]},
        }},
        example_input={"params": {"apps": [
            {"name": "Splunk_TA_windows", "version": "8.5.0"},
            {"name": "SplunkEnterpriseSecuritySuite", "version": "7.1.0"},
        ]}},
        example_output={"success": True, "output": {
            "total_apps": 2, "outdated": 1,
            "results": [{"name": "Splunk_TA_windows", "installed": "8.5.0", "latest": "8.8.0", "outdated": True}],
        }},
        tags=["splunkbase", "apps", "updates"],
    ))

    # ── Scripting Services ──

    for lang, prefix in [("ansible", "ansible"), ("shell", "shell"), ("python", "python")]:
        for action, suffix, desc in [
            ("generate", "generate", f"Generate a {lang} script from a description"),
            ("analyze", "analyze", f"Analyze a {lang} script for issues and improvements"),
            ("explain", "explain", f"Explain a {lang} script step by step"),
        ]:
            _add(ServiceDefinition(
                service_id=f"{lang}-{action}",
                name=f"{action.title()} {lang.title()} Script",
                description=desc,
                category=ServiceCategory.SCRIPTING,
                handler_key=f"{prefix}_{suffix}_{'playbook' if lang == 'ansible' else 'script'}",
                access_level=ServiceAccess.ANALYST,
                input_schema={"type": "object", "properties": {
                    "input": {"type": "string", "description": f"{'Description of' if action == 'generate' else ''} {lang} script {'to generate' if action == 'generate' else 'content'}"},
                }, "required": ["input"]},
                tags=[lang, "scripting", action],
            ))

    # ── Knowledge Services ──

    _add(ServiceDefinition(
        service_id="qa-ask",
        name="Ask a Question",
        description="Ask a question and get an AI-powered answer using the full RAG pipeline.",
        category=ServiceCategory.KNOWLEDGE,
        handler_key="general_qa",
        access_level=ServiceAccess.USER,
        timeout_seconds=120,
        input_schema={"type": "object", "properties": {"input": {"type": "string"}}, "required": ["input"]},
        example_input={"input": "What is the difference between props.conf and transforms.conf?"},
        example_output={"success": True, "output": "props.conf defines data parsing rules..."},
        tags=["qa", "knowledge", "rag"],
    ))

    # ── Ingestion Services ──

    _add(ServiceDefinition(
        service_id="ingest-trigger",
        name="Trigger Document Ingestion",
        description="Trigger ingestion of documents from configured directories.",
        category=ServiceCategory.INGESTION,
        handler_key="_ingest_trigger",
        access_level=ServiceAccess.ADMIN,
        rate_limit_per_minute=2,
        input_schema={"type": "object", "properties": {
            "params": {"type": "object", "properties": {"directory": {"type": "string"}}},
        }},
        example_input={"params": {"directory": "/app/shared/public/documents/commands"}},
        example_output={"success": True, "output": {"status": "ingestion_started"}},
        tags=["ingestion", "documents"],
    ))

    # ── System Services ──

    _add(ServiceDefinition(
        service_id="evolution-assess",
        name="Run Evolution Assessment",
        description="Run a full evolution assessment: staleness detection, root cause analysis, target evaluation.",
        category=ServiceCategory.SYSTEM,
        handler_key="_evolution_assess",
        access_level=ServiceAccess.ADMIN,
        rate_limit_per_minute=5,
        input_schema={},
        example_output={"success": True, "output": {"gaps_count": 2, "staleness": {"stale_or_critical": 1}}},
        tags=["evolution", "assessment", "system"],
    ))

    return services
