"""
Chat lifecycle handlers for ObsAI - Observability AI Assistant.
"""
import logging
import uuid
import chainlit as cl
from chainlit.input_widget import Select, Slider, Switch

from helper import current_username
from chat_app.lifecycle_context import ChatLifecycleContext
from chat_app.proactive_monitor import start_monitoring, stop_monitoring

logger = logging.getLogger(__name__)

async def on_chat_start(context: ChatLifecycleContext):
    await context.ensure_services_ready()
    await context.bootstrap_mcp_session()

    # Load org data into pipeline components (singleton, runs once)
    try:
        org_stats = context.initialize_org_data()
        if org_stats and org_stats.get("macros", 0) > 0:
            logger.info(f"Org data loaded: {org_stats}")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.warning(f"Org data init failed (using defaults): {e}")

    request_id = str(uuid.uuid4())
    cl.user_session.set("request_id", request_id)
    logger.info(f"Chat started for user: {current_username()}, request_id={request_id}")

    try:
        await cl.context.emitter.set_commands([
            {"id": "help", "icon": "help-circle", "description": "Show available commands"},
            {"id": "search", "icon": "search", "description": "Search all knowledge collections"},
            {"id": "spec", "icon": "file-text", "description": "Look up a .spec file"},
            {"id": "config", "icon": "settings", "description": "View or update settings"},
            {"id": "profile", "icon": "user", "description": "View current profile"},
            {"id": "mcp", "icon": "plug", "description": "Manage MCP servers and tokens"},
            {"id": "stats", "icon": "bar-chart-2", "description": "View usage statistics"},
            {"id": "health", "icon": "activity", "description": "Run health checks"},
            {"id": "build-config", "icon": "wrench", "description": "Build Splunk conf stanzas"},
            {"id": "splunk", "icon": "server", "description": "Splunk admin commands"},
            {"id": "clear", "icon": "trash-2", "description": "Clear chat history"},
            {"id": "tutorial", "icon": "book-open", "description": "Interactive tutorial"},
            {"id": "version", "icon": "info", "description": "Show version and system info"},
            {"id": "admin", "icon": "shield", "description": "Admin console and config management"},
            {"id": "skill", "icon": "zap", "description": "Execute or browse skills"},
            {"id": "kg", "icon": "share-2", "description": "Query knowledge graph"},
        ])
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # Load defaults from config
    try:
        from chat_app.settings import get_settings
        _cfg = get_settings()
        _default_temp = _cfg.ollama.temperature
        _default_k_mult = _cfg.retrieval.k_multiplier
    except Exception as _exc:  # broad catch — resilience against all failures
        _default_temp = 0.1
        _default_k_mult = 6

    # Load additional config defaults
    try:
        _retrieval_cfg = _cfg.retrieval
        _default_strategy = _retrieval_cfg.strategy
    except Exception as _exc:  # broad catch — resilience at boundary  # narrowed
        _default_strategy = "multi_collection"

    await cl.ChatSettings([
        # --- Profile ---
        Select(id="chat_profile", label="Chat Profile",
               values=["general", "spl_expert", "config_helper", "troubleshooter",
                        "org_expert", "cribl_expert", "observability_expert"],
               initial_index=0,
               description="Specialized profile for query routing and retrieval weighting"),
        # --- Retrieval ---
        Slider(id="search_depth", label="Search Depth", initial=5, min=1, max=10, step=1,
               description="Number of results to retrieve per collection"),
        Select(id="collections", label="Search Collections",
               values=["all", "feedback_only", "specs_only", "org_only",
                        "commands_only", "cribl_only"], initial_index=0,
               description="Which knowledge sources to search"),
        Select(id="retrieval_strategy", label="Retrieval Strategy",
               values=["multi_collection", "hybrid", "semantic_only"],
               initial_index=["multi_collection", "hybrid", "semantic_only"].index(_default_strategy) if _default_strategy in ["multi_collection", "hybrid", "semantic_only"] else 0,
               description="Search strategy: multi-collection, hybrid, or semantic-only"),
        Slider(id="confidence_threshold", label="Confidence Threshold",
               initial=0.6, min=0.0, max=1.0, step=0.05,
               description="Minimum confidence to include results"),
        Slider(id="k_multiplier", label="Retrieval Multiplier",
               initial=_default_k_mult, min=1, max=12, step=1,
               description="Fetch multiplier for broader retrieval (higher = more candidates)"),
        Select(id="qa_retrieval_strategy", label="Q&A Retrieval Strategy",
               values=["balanced", "prefer_generated", "prefer_raw"], initial_index=0,
               description="Retrieval preference for generated Q&A vs raw docs"),
        # --- Response ---
        Select(id="response_style", label="Response Style",
               values=["concise", "detailed", "tutorial"], initial_index=1,
               description="How verbose should responses be"),
        Switch(id="include_examples", label="Include Examples", initial=True,
               description="Include SPL code examples in responses"),
        Switch(id="show_sources", label="Show Sources", initial=True,
               description="Display source references with links"),
        Slider(id="max_response_length", label="Max Response Length",
               initial=2000, min=500, max=5000, step=250,
               description="Maximum response length in characters"),
        # --- LLM ---
        Slider(id="temperature", label="LLM Temperature",
               initial=_default_temp, min=0.0, max=1.0, step=0.05,
               description="Lower = more deterministic, higher = more creative"),
        Switch(id="enable_streaming", label="Stream Responses", initial=True,
               description="Show responses as they are generated"),
        # --- Features ---
        Switch(id="liked_queries_boost", label="Boost Liked Queries", initial=True,
               description="Prioritize results from previously liked queries"),
        Switch(id="query_expansion", label="Query Expansion", initial=True,
               description="Expand queries with synonyms for broader retrieval"),
        Switch(id="reranking", label="Reranking", initial=True,
               description="Re-score retrieved chunks with cross-encoder (slower, more precise)"),
        Switch(id="compound_query_detection", label="Compound Query Detection", initial=True,
               description="Split complex questions into sub-queries for better coverage"),
        Switch(id="self_evaluation", label="Self-Evaluation", initial=True,
               description="Evaluate response quality before sending (may add clarification)"),
        Switch(id="knowledge_gap_detection", label="Knowledge Gap Detection", initial=True,
               description="Detect and notify when knowledge base is missing topics"),
        # --- Splunk Context ---
        Select(id="splunk_version", label="Default Splunk Version",
               values=["9.2.0", "9.3.0", "9.4.0", "9.4.3", "9.5.0", "9.5.4", "9.6.0"], initial_index=5,
               description="Assume this Splunk version for syntax references"),
    ]).send()

    cl.user_session.set("settings", {
        "chat_profile": "general",
        "search_depth": 5, "collections": "all", "retrieval_strategy": _default_strategy,
        "confidence_threshold": 0.6,
        "k_multiplier": _default_k_mult, "qa_retrieval_strategy": "balanced",
        "response_style": "detailed", "include_examples": True, "show_sources": True,
        "max_response_length": 2000,
        "temperature": _default_temp, "enable_streaming": True,
        "liked_queries_boost": True, "query_expansion": True,
        "reranking": True, "compound_query_detection": True,
        "self_evaluation": True, "knowledge_gap_detection": True,
        "splunk_version": "9.5.4",
    })

    # Build version string
    try:
        _app_version = _cfg.app.version
    except Exception as _exc:  # broad catch — resilience at boundary  # narrowed
        _app_version = "3.5.0"

    await cl.Message(content=f"""**ObsAI** `v{_app_version}` — Splunk, Cribl & Observability AI Assistant

Ask me anything about SPL, configurations, troubleshooting, or your deployment.

[Admin Console](/api/admin/v2/) · `/help` for commands""").send()

    # Start background health monitoring
    try:
        await start_monitoring()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.debug("Could not start health monitor: %s", e)


async def on_settings_update(settings):
    cl.user_session.set("settings", settings)


def on_stop():
    cl.user_session.set("cancelled", True)


def on_chat_end():
    stop_monitoring()


async def on_chat_resume(thread, ensure_services_ready):
    cl.user_session.set("request_id", str(uuid.uuid4()))
    cl.user_session.set("resumed_thread_id", thread.get("id", "unknown"))
    await ensure_services_ready()
    await cl.Message(content="""**Resumed previous conversation**

How can I help you today?""", author="System").send()
