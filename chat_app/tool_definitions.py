"""
Tool Definitions — Built-in tool registrations for the tool registry.

Extracted from tool_registry.py for size management.
tool_registry.py calls register_builtin_tools() from this module at import time.
Tool implementations are in tool_implementations.py.

Provides:
- register_builtin_tools() — registers all 24 built-in tools into the registry
"""
import logging

from chat_app.tool_registry import Tool, ToolCategory, ToolParameter, get_tool_registry
from chat_app.tool_implementations import (  # noqa: F401
    _tool_analyze_configs,
    _tool_analyze_cribl_pipeline,
    _tool_analyze_spl,
    _tool_check_splunk_health,
    _tool_create_knowledge_object,
    _tool_generate_cribl_route,
    _tool_generate_spl,
    _tool_get_license_usage,
    _tool_get_server_info,
    _tool_list_apps,
    _tool_list_deployment_clients,
    _tool_list_indexes,
    _tool_list_inputs,
    _tool_list_lookups,
    _tool_list_macros,
    _tool_list_saved_searches,
    _tool_list_users,
    _tool_lookup_config,
    _tool_optimize_spl,
    _tool_run_splunk_search,
    _tool_search_index_stats,
    _tool_search_kb,
    _tool_suggest_metrics_query,
    _tool_update_saved_search,
    _tool_validate_spl,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registration function
# ---------------------------------------------------------------------------

def register_builtin_tools():
    """Register all built-in tools into the tool registry. Called once at import time."""
    registry = get_tool_registry()

    # --- SPL Analysis Tools ---
    registry.register(Tool(
        name="analyze_spl",
        description="Analyze an SPL query for performance issues, anti-patterns, and optimization opportunities",
        category=ToolCategory.ANALYSIS,
        parameters=[
            ToolParameter("query", "The SPL query to analyze", required=True),
            ToolParameter("auto_fix", "Attempt automatic fixes", param_type="bool", default=True),
        ],
        intents=["spl_generation", "spl_optimization"],
        execute_fn=_tool_analyze_spl,
    ))

    registry.register(Tool(
        name="optimize_spl",
        description="Optimize an SPL query for better performance (tstats conversion, TERM/PREFIX usage, etc.)",
        category=ToolCategory.GENERATION,
        parameters=[
            ToolParameter("query", "The SPL query to optimize", required=True),
        ],
        intents=["spl_generation", "spl_optimization"],
        execute_fn=_tool_optimize_spl,
    ))

    registry.register(Tool(
        name="validate_spl",
        description="Validate SPL syntax and check for dangerous patterns",
        category=ToolCategory.ANALYSIS,
        parameters=[
            ToolParameter("query", "The SPL query to validate", required=True),
        ],
        intents=["spl_generation"],
        execute_fn=_tool_validate_spl,
    ))

    registry.register(Tool(
        name="generate_spl",
        description="Generate an SPL query from a natural language description",
        category=ToolCategory.GENERATION,
        parameters=[
            ToolParameter("description", "Natural language description of what to search for", required=True),
            ToolParameter("index", "Target Splunk index", default=None),
            ToolParameter("sourcetype", "Target sourcetype", default=None),
        ],
        intents=["spl_generation", "nlp_to_spl"],
        execute_fn=_tool_generate_spl,
    ))

    # --- Splunk Admin Tools ---
    registry.register(Tool(
        name="run_splunk_search",
        description="Execute an SPL query against the connected Splunk instance",
        category=ToolCategory.SPLUNK,
        parameters=[
            ToolParameter("query", "SPL query to execute", required=True),
            ToolParameter("earliest", "Earliest time (e.g., -24h)", default="-15m"),
            ToolParameter("latest", "Latest time", default="now"),
        ],
        requires={"splunk_connected"},
        intents=["run_search"],
        execute_fn=_tool_run_splunk_search,
    ))

    registry.register(Tool(
        name="list_saved_searches",
        description="List saved searches from the connected Splunk instance",
        category=ToolCategory.SPLUNK,
        requires={"splunk_connected"},
        intents=["saved_search_analysis"],
        execute_fn=_tool_list_saved_searches,
    ))

    registry.register(Tool(
        name="check_splunk_health",
        description="Check the health of the connected Splunk instance",
        category=ToolCategory.SPLUNK,
        requires={"splunk_connected"},
        intents=["troubleshooting"],
        execute_fn=_tool_check_splunk_health,
    ))

    # --- Config Analysis Tools ---
    registry.register(Tool(
        name="analyze_configs",
        description="Run health checks on Splunk configuration files (.conf)",
        category=ToolCategory.ADMIN,
        parameters=[
            ToolParameter("config_path", "Path to config directory", default=None),
        ],
        intents=["config_health_check", "config_lookup"],
        execute_fn=_tool_analyze_configs,
    ))

    registry.register(Tool(
        name="lookup_config",
        description="Look up a specific Splunk configuration stanza or parameter",
        category=ToolCategory.KNOWLEDGE,
        parameters=[
            ToolParameter("conf_file", "The .conf file name (e.g., inputs.conf)", required=True),
            ToolParameter("stanza", "Stanza name to look up", default=None),
            ToolParameter("parameter", "Specific parameter to find", default=None),
        ],
        intents=["config_lookup", "spec_lookup"],
        execute_fn=_tool_lookup_config,
    ))

    # --- Cribl Tools ---
    registry.register(Tool(
        name="analyze_cribl_pipeline",
        description="Analyze a Cribl Stream pipeline configuration for issues and optimizations",
        category=ToolCategory.CRIBL,
        parameters=[
            ToolParameter("pipeline_config", "Pipeline configuration (YAML/JSON)", required=True),
        ],
        intents=["cribl_pipeline", "cribl_config"],
        execute_fn=_tool_analyze_cribl_pipeline,
    ))

    registry.register(Tool(
        name="generate_cribl_route",
        description="Generate a Cribl Stream route configuration from a description",
        category=ToolCategory.CRIBL,
        parameters=[
            ToolParameter("description", "Description of routing requirements", required=True),
            ToolParameter("source_type", "Input source type", default=None),
            ToolParameter("destination", "Target destination", default=None),
        ],
        intents=["cribl_pipeline", "cribl_config"],
        execute_fn=_tool_generate_cribl_route,
    ))

    # --- Observability Tools ---
    registry.register(Tool(
        name="suggest_metrics_query",
        description="Suggest an mstats or mcatalog query for metrics exploration",
        category=ToolCategory.OBSERVABILITY,
        parameters=[
            ToolParameter("metric_name", "Name or pattern of the metric", required=True),
            ToolParameter("time_range", "Time range for the query", default="-1h"),
        ],
        intents=["observability_metrics", "spl_generation"],
        execute_fn=_tool_suggest_metrics_query,
    ))

    registry.register(Tool(
        name="search_knowledge_base",
        description="Search the assistant's knowledge base for relevant documentation",
        category=ToolCategory.KNOWLEDGE,
        parameters=[
            ToolParameter("query", "Search query", required=True),
            ToolParameter("collection", "Specific collection to search", default=None),
        ],
        intents=["general_qa", "troubleshooting"],
        execute_fn=_tool_search_kb,
    ))

    # --- Splunk Writer Tools (require approval) ---
    registry.register(Tool(
        name="update_saved_search",
        description="Update an existing Splunk saved search (query, schedule, description, etc.)",
        category=ToolCategory.SPLUNK,
        parameters=[
            ToolParameter("name", "Name of the saved search to update", required=True),
            ToolParameter("search", "New SPL query", default=None),
            ToolParameter("description", "New description", default=None),
            ToolParameter("cron_schedule", "New cron schedule", default=None),
            ToolParameter("app", "Splunk app context", default="search"),
        ],
        requires={"splunk_connected"},
        intents=["saved_search_analysis", "spl_optimization"],
        execute_fn=_tool_update_saved_search,
    ))

    registry.register(Tool(
        name="create_knowledge_object",
        description="Create a Splunk knowledge object (macro, eventtype, tag, or saved search)",
        category=ToolCategory.SPLUNK,
        parameters=[
            ToolParameter("object_type", "Type: macro, eventtypes, tags, saved_search", required=True),
            ToolParameter("name", "Name for the object", required=True),
            ToolParameter("definition", "The definition/search/value", required=True),
            ToolParameter("app", "Splunk app context", default="search"),
        ],
        requires={"splunk_connected"},
        intents=["saved_search_analysis", "config_health_check"],
        execute_fn=_tool_create_knowledge_object,
    ))

    # --- Splunk Admin Read Tools ---
    registry.register(Tool(
        name="list_indexes",
        description="List all Splunk indexes with size, event count, and retention settings",
        category=ToolCategory.SPLUNK,
        requires={"splunk_connected"},
        intents=["troubleshooting", "general_qa"],
        execute_fn=_tool_list_indexes,
    ))

    registry.register(Tool(
        name="list_inputs",
        description="List Splunk data inputs (monitors, TCP, UDP, HEC, scripted)",
        category=ToolCategory.SPLUNK,
        parameters=[
            ToolParameter("kind", "Input type filter: all, monitor, tcp, udp, http", default="all"),
        ],
        requires={"splunk_connected"},
        intents=["troubleshooting", "general_qa"],
        execute_fn=_tool_list_inputs,
    ))

    registry.register(Tool(
        name="list_apps",
        description="List installed Splunk apps with version, status, and visibility",
        category=ToolCategory.SPLUNK,
        requires={"splunk_connected"},
        intents=["general_qa", "troubleshooting"],
        execute_fn=_tool_list_apps,
    ))

    registry.register(Tool(
        name="list_users",
        description="List Splunk users with their roles and details",
        category=ToolCategory.SPLUNK,
        requires={"splunk_connected"},
        intents=["general_qa", "troubleshooting"],
        execute_fn=_tool_list_users,
    ))

    registry.register(Tool(
        name="get_server_info",
        description="Get Splunk server info (version, OS, license state, cluster roles)",
        category=ToolCategory.SPLUNK,
        requires={"splunk_connected"},
        intents=["troubleshooting", "general_qa"],
        execute_fn=_tool_get_server_info,
    ))

    registry.register(Tool(
        name="list_deployment_clients",
        description="List deployment server clients and their server classes",
        category=ToolCategory.SPLUNK,
        requires={"splunk_connected"},
        intents=["troubleshooting"],
        execute_fn=_tool_list_deployment_clients,
    ))

    registry.register(Tool(
        name="search_index_stats",
        description="Get per-index ingestion rates, sizes, and event counts",
        category=ToolCategory.SPLUNK,
        requires={"splunk_connected"},
        intents=["troubleshooting", "general_qa"],
        execute_fn=_tool_search_index_stats,
    ))

    registry.register(Tool(
        name="list_lookups",
        description="List Splunk lookup files and definitions",
        category=ToolCategory.SPLUNK,
        requires={"splunk_connected"},
        intents=["general_qa", "config_lookup"],
        execute_fn=_tool_list_lookups,
    ))

    registry.register(Tool(
        name="list_macros",
        description="List Splunk search macros with their definitions",
        category=ToolCategory.SPLUNK,
        requires={"splunk_connected"},
        intents=["general_qa", "config_lookup"],
        execute_fn=_tool_list_macros,
    ))

    registry.register(Tool(
        name="get_license_usage",
        description="Get current Splunk license consumption vs entitlement",
        category=ToolCategory.SPLUNK,
        requires={"splunk_connected"},
        intents=["troubleshooting", "general_qa"],
        execute_fn=_tool_get_license_usage,
    ))

    logger.info("[TOOLS] Registered %d built-in tools", len(registry._tools))
