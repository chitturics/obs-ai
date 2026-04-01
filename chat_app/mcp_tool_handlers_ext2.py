"""MCP Tool Handlers Extended 2 — Phase 6 admin/ops/intelligence tools.

Contains handler functions for:
- Operations: backup, audit_log, version, manage_containers
- User & Security: manage_users, manage_tokens, ssl_status, manage_ports
- Configuration: manage_settings, manage_features, manage_prompts, manage_profiles
- Intelligence: manage_collections, knowledge_graph, observability, guardrails,
  artifacts, manage_workflows, splunkbase
- Upgrade Readiness: upgrade_es, upgrade_itsi

Also exports _HANDLERS_EXT2: mapping from MCP tool name to handler callable.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------

async def _handle_backup(args: Dict) -> Dict:
    """Create or list backups (config, collections, state, database)."""
    action = args.get("action", "list")
    try:
        if action == "create":
            from chat_app.admin_operations_routes import create_unified_backup
            from chat_app.admin_operations_routes import UnifiedBackupRequest
            body = UnifiedBackupRequest(config=True, collections=True, state=True, database=False)
            result = await create_unified_backup(body)
            return {"success": True, "action": "create", **result}

        if action == "list":
            from chat_app.admin_operations_routes import list_all_backups
            result = await list_all_backups()
            return {"success": True, "action": "list", **result}

        if action == "status":
            from chat_app.admin_operations_routes import get_backup_status
            result = await get_backup_status()
            return {"success": True, "action": "status", **result}

        return {"error": f"Unknown action: {action}"}
    except (ImportError, AttributeError):
        # Graceful degradation when admin routes are not loaded in MCP context
        try:
            from chat_app.config_manager import get_config_manager
            mgr = get_config_manager()
            backup_path = mgr._backup() if hasattr(mgr, "_backup") else None
            return {
                "success": True,
                "action": action,
                "config_backup": str(backup_path) if backup_path else "unavailable",
                "note": "Full backup API not available in this context",
            }
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            return {"error": str(exc)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_backup failed: %s", exc)
        return {"error": str(exc)}


async def _handle_audit_log(args: Dict) -> Dict:
    """Query audit trail entries."""
    limit = args.get("limit", 20)
    section = args.get("section", "")
    try:
        from chat_app.admin_operations_routes import get_audit_entries
        result = await get_audit_entries(limit=limit, section=section or None)
        return {"success": True, **result}
    except (ImportError, AttributeError):
        # Fallback: read from config manager audit log directly
        try:
            from chat_app.config_manager import get_config_manager
            mgr = get_config_manager()
            entries = mgr.get_audit_log(limit=limit) if hasattr(mgr, "get_audit_log") else []
            if section:
                entries = [e for e in entries if e.get("section") == section]
            return {"success": True, "entries": entries, "note": "Direct config manager audit"}
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            return {"error": str(exc)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_audit_log failed: %s", exc)
        return {"error": str(exc)}


async def _handle_version(args: Dict) -> Dict:
    """Get app version, git info, and changelog."""
    try:
        from chat_app.admin_operations_routes import get_version
        result = await get_version()
        return {"success": True, **result}
    except (ImportError, AttributeError):
        # Fallback via settings
        try:
            from chat_app.settings import get_settings
            cfg = get_settings()
            return {
                "success": True,
                "version": cfg.app.version,
                "environment": cfg.app.environment,
                "profile": cfg.app.active_profile,
            }
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            return {"version": "3.5.0", "note": str(exc)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_version failed: %s", exc)
        return {"error": str(exc)}


async def _handle_manage_containers(args: Dict) -> Dict:
    """List, restart, or check health of containers."""
    action = args.get("action", "list")
    service = args.get("service", "")
    try:
        if action == "list":
            from chat_app.admin_containers import list_containers
            result = await list_containers()
            return {"success": True, "action": "list", **result}

        if action == "health":
            from chat_app.admin_containers import get_container_health
            result = await get_container_health()
            return {"success": True, "action": "health", **result}

        if action == "restart":
            if not service:
                return {"error": "service is required for restart action"}
            from chat_app.admin_containers import restart_container
            result = await restart_container(service=service)
            return {"success": True, "action": "restart", "service": service, **result}

        if action == "logs":
            if not service:
                return {"error": "service is required for logs action"}
            from chat_app.admin_containers import get_container_logs
            result = await get_container_logs(service=service)
            return {"success": True, "action": "logs", "service": service, **result}

        return {"error": f"Unknown action: {action}"}
    except (ImportError, AttributeError):
        return {
            "success": False,
            "action": action,
            "note": "Container management API not available in this context",
            "guidance": "Use podman ps / podman restart <container> directly",
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_manage_containers failed: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# User & Security
# ---------------------------------------------------------------------------

async def _handle_manage_users(args: Dict) -> Dict:
    """List users, roles, and manage access."""
    action = args.get("action", "list")
    try:
        if action == "list":
            from chat_app.admin_users_routes import list_users
            result = await list_users()
            return {"success": True, "action": "list", **result}

        if action == "roles":
            from chat_app.admin_users_routes import list_roles
            result = await list_roles()
            return {"success": True, "action": "roles", **result}

        return {"error": f"Unknown action: {action}"}
    except (ImportError, AttributeError):
        return {
            "success": False,
            "note": "User management API not available — authentication may be disabled",
            "guidance": "Enable ENABLE_AUTHENTICATION=true in environment to activate user management",
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_manage_users failed: %s", exc)
        return {"error": str(exc)}


async def _handle_manage_tokens(args: Dict) -> Dict:
    """List or create API tokens."""
    action = args.get("action", "list")
    label = args.get("label", "")
    try:
        if action == "list":
            from chat_app.admin_users_routes import list_tokens
            result = await list_tokens()
            return {"success": True, "action": "list", **result}

        if action == "create":
            if not label:
                return {"error": "label is required for create action"}
            from chat_app.admin_users_routes import create_token
            from chat_app.admin_users_routes import CreateTokenRequest
            body = CreateTokenRequest(label=label)
            result = await create_token(body)
            return {"success": True, "action": "create", "label": label, **result}

        return {"error": f"Unknown action: {action}"}
    except (ImportError, AttributeError):
        return {
            "success": False,
            "note": "Token management API not available — authentication may be disabled",
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_manage_tokens failed: %s", exc)
        return {"error": str(exc)}


async def _handle_ssl_status(args: Dict) -> Dict:
    """Check SSL/TLS certificate status and network connectivity."""
    action = args.get("action", "status")
    try:
        if action == "status":
            from chat_app.admin_network_routes import get_ssl_status
            result = await get_ssl_status()
            return {"success": True, "action": "status", **result}

        if action == "test_network":
            from chat_app.admin_network_routes import run_network_test
            result = await run_network_test()
            return {"success": True, "action": "test_network", **result}

        return {"error": f"Unknown action: {action}"}
    except (ImportError, AttributeError):
        return {
            "success": False,
            "note": "SSL/network routes not available in this context",
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_ssl_status failed: %s", exc)
        return {"error": str(exc)}


async def _handle_manage_ports(args: Dict) -> Dict:
    """Get or update port configuration."""
    action = args.get("action", "get")
    try:
        if action == "get":
            from chat_app.admin_network_routes import get_ports
            result = await get_ports()
            return {"success": True, "action": "get", **result}

        if action == "update":
            return {
                "success": False,
                "action": "update",
                "note": "Port update requires a full request body — use the admin console",
                "guidance": "Navigate to Admin > SSL & Ports to modify port configuration",
            }

        return {"error": f"Unknown action: {action}"}
    except (ImportError, AttributeError):
        return {
            "success": False,
            "note": "Network/port routes not available in this context",
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_manage_ports failed: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

async def _handle_manage_settings(args: Dict) -> Dict:
    """Get or update application settings by section."""
    action = args.get("action", "get")
    section = args.get("section", "")
    values = args.get("values", {})
    try:
        if action == "get":
            from chat_app.admin_settings_routes import get_all_settings
            result = await get_all_settings()
            if section and isinstance(result, dict):
                section_data = result.get(section, result.get("settings", {}).get(section))
                if section_data is not None:
                    return {"success": True, "action": "get", "section": section, "values": section_data}
            return {"success": True, "action": "get", **result}

        if action == "update":
            if not section:
                return {"error": "section is required for update action"}
            if not values:
                return {"error": "values dict is required for update action"}
            from chat_app.admin_settings_routes import update_settings_section
            from chat_app.admin_settings_routes import SettingsUpdateRequest
            body = SettingsUpdateRequest(values=values)
            result = await update_settings_section(section=section, body=body)
            return {"success": True, "action": "update", "section": section, **result}

        return {"error": f"Unknown action: {action}"}
    except (ImportError, AttributeError):
        # Fallback via settings object
        try:
            from chat_app.settings import get_settings
            cfg = get_settings()
            section_obj = getattr(cfg, section, None) if section else None
            data = section_obj.model_dump() if section_obj and hasattr(section_obj, "model_dump") else {}
            return {"success": True, "action": action, "section": section, "values": data,
                    "note": "Read-only via settings object — update requires running app"}
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            return {"error": str(exc)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_manage_settings failed: %s", exc)
        return {"error": str(exc)}


async def _handle_manage_features(args: Dict) -> Dict:
    """List, enable, or disable feature flags."""
    action = args.get("action", "list")
    feature = args.get("feature", "")
    try:
        if action == "list":
            from chat_app.admin_settings_routes import list_features
            result = await list_features()
            return {"success": True, "action": "list", **result}

        if action in ("enable", "disable"):
            if not feature:
                return {"error": f"feature name is required for {action} action"}
            from chat_app.admin_settings_routes import toggle_feature
            from chat_app.admin_settings_routes import FeatureToggleRequest
            enabled = action == "enable"
            body = FeatureToggleRequest(enabled=enabled)
            result = await toggle_feature(feature=feature, body=body)
            return {"success": True, "action": action, "feature": feature, **result}

        return {"error": f"Unknown action: {action}"}
    except (ImportError, AttributeError):
        try:
            from chat_app.settings import get_settings
            cfg = get_settings()
            flags = cfg.features.model_dump() if hasattr(cfg, "features") else {}
            return {"success": True, "action": "list", "features": flags,
                    "note": "Read-only — toggle requires running app"}
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            return {"error": str(exc)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_manage_features failed: %s", exc)
        return {"error": str(exc)}


async def _handle_manage_prompts(args: Dict) -> Dict:
    """List or update prompt templates."""
    action = args.get("action", "list")
    name = args.get("name", "")
    content = args.get("content", "")
    try:
        if action == "list":
            from chat_app.admin_settings_routes import list_prompts
            result = await list_prompts()
            return {"success": True, "action": "list", **result}

        if action == "get":
            if not name:
                return {"error": "name is required for get action"}
            from chat_app.admin_settings_routes import list_prompts
            all_prompts = await list_prompts()
            prompt_list = all_prompts.get("prompts", []) if isinstance(all_prompts, dict) else []
            matched = next((p for p in prompt_list if p.get("name") == name), None)
            if matched is None:
                return {"error": f"Prompt '{name}' not found"}
            return {"success": True, "action": "get", "prompt": matched}

        if action == "update":
            if not name or not content:
                return {"error": "name and content are required for update action"}
            from chat_app.admin_settings_routes import update_prompt
            from chat_app.admin_settings_routes import PromptUpdateRequest
            body = PromptUpdateRequest(content=content)
            result = await update_prompt(name=name, body=body)
            return {"success": True, "action": "update", "name": name, **result}

        return {"error": f"Unknown action: {action}"}
    except (ImportError, AttributeError):
        return {
            "success": False,
            "note": "Prompt management API not available in this context",
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_manage_prompts failed: %s", exc)
        return {"error": str(exc)}


async def _handle_manage_profiles(args: Dict) -> Dict:
    """List LLM profiles and their configurations."""
    try:
        from chat_app.admin_config_routes import list_profiles
        result = await list_profiles()
        return {"success": True, **result}
    except (ImportError, AttributeError):
        try:
            from chat_app.settings import get_settings
            cfg = get_settings()
            profiles = list(cfg.profiles.keys()) if hasattr(cfg, "profiles") else []
            active = cfg.app.active_profile if hasattr(cfg, "app") else "default"
            return {"success": True, "profiles": profiles, "active_profile": active,
                    "note": "Summary only — full profile details require running app"}
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            return {"error": str(exc)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_manage_profiles failed: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Intelligence
# ---------------------------------------------------------------------------

async def _handle_manage_collections(args: Dict) -> Dict:
    """List, browse, or manage ChromaDB collections."""
    action = args.get("action", "list")
    collection = args.get("collection", "")
    try:
        if action == "list":
            from chat_app.admin_collections_routes import list_collections
            result = await list_collections()
            return {"success": True, "action": "list", **result}

        if action == "browse":
            if not collection:
                return {"error": "collection is required for browse action"}
            from chat_app.admin_collections_routes import browse_collection_chunks
            result = await browse_collection_chunks(name=collection)
            return {"success": True, "action": "browse", "collection": collection, **result}

        if action == "stats":
            from chat_app.admin_collections_routes import get_collection_stats
            result = await get_collection_stats()
            return {"success": True, "action": "stats", **result}

        return {"error": f"Unknown action: {action}"}
    except (ImportError, AttributeError):
        try:
            from chat_app.vectorstore_search import list_all_collections
            collections = list_all_collections()
            return {"success": True, "action": "list", "collections": collections,
                    "note": "Minimal listing — full management requires running app"}
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            return {"error": str(exc)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_manage_collections failed: %s", exc)
        return {"error": str(exc)}


async def _handle_knowledge_graph(args: Dict) -> Dict:
    """Query knowledge graph entities and relationships."""
    action = args.get("action", "stats")
    query = args.get("query", "")
    entity_type = args.get("entity_type", "")
    try:
        if action == "stats":
            from chat_app.admin_learning_ext_routes import get_kg_stats
            result = await get_kg_stats()
            return {"success": True, "action": "stats", **result}

        if action == "entities":
            from chat_app.admin_learning_ext_routes import get_kg_entities
            kwargs: Dict[str, Any] = {}
            if entity_type:
                kwargs["entity_type"] = entity_type
            result = await get_kg_entities(**kwargs)
            return {"success": True, "action": "entities", **result}

        if action == "query":
            if not query:
                return {"error": "query is required for query action"}
            from chat_app.admin_learning_ext_routes import query_kg
            from chat_app.admin_learning_ext_routes import KGQueryRequest
            body = KGQueryRequest(query=query)
            result = await query_kg(body)
            return {"success": True, "action": "query", "query": query, **result}

        return {"error": f"Unknown action: {action}"}
    except (ImportError, AttributeError):
        try:
            from chat_app.knowledge_graph import get_knowledge_graph
            kg = get_knowledge_graph()
            if not kg:
                return {"success": False, "error": "Knowledge graph not initialized"}
            stats = kg.get_stats() if hasattr(kg, "get_stats") else {}
            return {"success": True, "action": action, "stats": stats,
                    "note": "Direct knowledge graph access — admin API unavailable"}
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            return {"error": str(exc)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_knowledge_graph failed: %s", exc)
        return {"error": str(exc)}


async def _handle_observability(args: Dict) -> Dict:
    """Get observability dashboard, traces, and analytics."""
    action = args.get("action", "dashboard")
    try:
        if action == "dashboard":
            from chat_app.admin_observability_routes import observability_summary
            result = await observability_summary()
            return {"success": True, "action": "dashboard", **result}

        if action == "traces":
            from chat_app.admin_observability_routes import get_pipeline_traces
            result = await get_pipeline_traces()
            return {"success": True, "action": "traces", **result}

        if action == "analytics":
            from chat_app.admin_observability_routes import get_agent_performance_metrics
            result = await get_agent_performance_metrics()
            return {"success": True, "action": "analytics", **result}

        return {"error": f"Unknown action: {action}"}
    except (ImportError, AttributeError):
        return {
            "success": False,
            "note": "Observability routes not available in this context",
            "guidance": "Access Grafana at /grafana/ for metrics dashboards",
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_observability failed: %s", exc)
        return {"error": str(exc)}


async def _handle_guardrails(args: Dict) -> Dict:
    """Check guardrail configuration and trigger stats."""
    try:
        from chat_app.admin_learning_ext_routes import get_guardrail_stats
        stats_result = await get_guardrail_stats()
        try:
            from chat_app.admin_learning_ext_routes import get_guardrails
            config_result = await get_guardrails()
        except (ImportError, AttributeError, OSError, ValueError, KeyError, TypeError, RuntimeError):
            config_result = {}
        return {
            "success": True,
            "stats": stats_result,
            "configuration": config_result,
        }
    except (ImportError, AttributeError):
        try:
            from chat_app.settings import get_settings
            cfg = get_settings()
            guardrail_cfg = cfg.guardrails.model_dump() if hasattr(cfg, "guardrails") else {}
            return {"success": True, "configuration": guardrail_cfg,
                    "note": "Stats unavailable — admin routes not loaded"}
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            return {"error": str(exc)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_guardrails failed: %s", exc)
        return {"error": str(exc)}


async def _handle_artifacts(args: Dict) -> Dict:
    """List generated artifacts and exports."""
    try:
        from chat_app.admin_learning_ext_routes import get_artifacts
        result = await get_artifacts()
        return {"success": True, **result}
    except (ImportError, AttributeError):
        # Fallback: scan the data/exports directory
        try:
            import os
            data_dir = "/app/data"
            artifacts: list = []
            for sub in ("exports", "artifacts", "training"):
                sub_path = os.path.join(data_dir, sub)
                if os.path.isdir(sub_path):
                    for fname in sorted(os.listdir(sub_path))[:20]:
                        fpath = os.path.join(sub_path, fname)
                        artifacts.append({
                            "name": fname,
                            "type": sub,
                            "size_bytes": os.path.getsize(fpath),
                        })
            return {"success": True, "artifacts": artifacts,
                    "note": "Directory scan fallback — admin API unavailable"}
        except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            return {"error": str(exc)}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_artifacts failed: %s", exc)
        return {"error": str(exc)}


async def _handle_manage_workflows(args: Dict) -> Dict:
    """List workflow templates, history, and designer blocks."""
    action = args.get("action", "templates")
    try:
        if action == "templates":
            from chat_app.admin_skills_workflow_routes import list_workflow_templates
            result = await list_workflow_templates()
            return {"success": True, "action": "templates", **result}

        if action == "history":
            from chat_app.workflow_orchestrator import get_workflow_orchestrator
            orchestrator = get_workflow_orchestrator()
            history = orchestrator.get_workflow_history() if hasattr(orchestrator, "get_workflow_history") else []
            return {"success": True, "action": "history", "history": history}

        if action == "designer":
            from chat_app.admin_skills_workflow_routes import list_workflow_templates
            result = await list_workflow_templates()
            return {"success": True, "action": "designer",
                    "templates": result.get("templates", []),
                    "note": "Use admin console at /api/admin/v2/ for the visual workflow designer"}

        return {"error": f"Unknown action: {action}"}
    except (ImportError, AttributeError):
        return {
            "success": False,
            "note": "Workflow management routes not available in this context",
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_manage_workflows failed: %s", exc)
        return {"error": str(exc)}


async def _handle_splunkbase(args: Dict) -> Dict:
    """Search Splunkbase catalog, check app versions, compare installed."""
    action = args.get("action", "catalog")
    query = args.get("query", "")
    try:
        if action in ("catalog", "search"):
            from chat_app.admin_learning_ext_routes import get_splunkbase_all_apps
            kwargs: Dict[str, Any] = {}
            if query:
                kwargs["search"] = query
            result = await get_splunkbase_all_apps(**kwargs)
            return {"success": True, "action": action, **result}

        if action == "compare":
            from chat_app.admin_learning_ext_routes import get_splunkbase_outdated
            result = await get_splunkbase_outdated()
            return {"success": True, "action": "compare", **result}

        return {"error": f"Unknown action: {action}"}
    except (ImportError, AttributeError):
        return {
            "success": False,
            "note": "Splunkbase catalog not available — run ingestion to populate",
            "guidance": "Use /api/admin/learning/splunkbase/refresh to populate the catalog",
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_splunkbase failed: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Upgrade Readiness — ES and ITSI specific
# ---------------------------------------------------------------------------

async def _handle_upgrade_es(args: Dict) -> Dict:
    """Analyze Splunk Enterprise Security upgrade readiness."""
    cluster = args.get("cluster", "cluster-es")
    app_name = "SplunkEnterpriseSecuritySuite"
    try:
        from upgrade_readiness import get_upgrade_scanner
        scanner = get_upgrade_scanner()
        baseline = scanner.baseline_scan(app_name=app_name, cluster=cluster)
        diff = scanner.diff_confs(app_name=app_name, cluster=cluster)
        impact = scanner.impact_analysis(app_name=app_name, cluster=cluster)
        es_specific: Dict[str, Any] = {}
        if hasattr(scanner, "es_readiness_check"):
            es_specific = scanner.es_readiness_check(cluster=cluster)
        return {
            "success": True,
            "cluster": cluster,
            "app_name": app_name,
            "baseline": baseline,
            "conf_diff": diff,
            "impact": impact,
            "es_readiness": es_specific,
        }
    except ImportError:
        return {
            "success": False,
            "cluster": cluster,
            "app_name": app_name,
            "error": "upgrade_readiness package not available",
            "guidance": (
                "ES Upgrade Checklist:\n"
                "1. Verify ES version compatibility matrix at https://docs.splunk.com/Documentation/ES\n"
                "2. Check all custom correlation searches against new ES data models\n"
                "3. Verify threat intelligence integrations\n"
                "4. Test notable event suppression rules\n"
                "5. Backup $SPLUNK_HOME/etc/apps/SplunkEnterpriseSecuritySuite/"
            ),
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_upgrade_es failed: %s", exc)
        return {"error": str(exc)}


async def _handle_upgrade_itsi(args: Dict) -> Dict:
    """Analyze ITSI upgrade readiness (KPIs, services, thresholds)."""
    cluster = args.get("cluster", "cluster-itsi")
    app_name = "itsi"
    try:
        from upgrade_readiness import get_upgrade_scanner
        scanner = get_upgrade_scanner()
        baseline = scanner.baseline_scan(app_name=app_name, cluster=cluster)
        diff = scanner.diff_confs(app_name=app_name, cluster=cluster)
        impact = scanner.impact_analysis(app_name=app_name, cluster=cluster)
        itsi_specific: Dict[str, Any] = {}
        if hasattr(scanner, "itsi_readiness_check"):
            itsi_specific = scanner.itsi_readiness_check(cluster=cluster)
        return {
            "success": True,
            "cluster": cluster,
            "app_name": app_name,
            "baseline": baseline,
            "conf_diff": diff,
            "impact": impact,
            "itsi_readiness": itsi_specific,
        }
    except ImportError:
        return {
            "success": False,
            "cluster": cluster,
            "app_name": app_name,
            "error": "upgrade_readiness package not available",
            "guidance": (
                "ITSI Upgrade Checklist:\n"
                "1. Export all KPI base searches and service definitions before upgrade\n"
                "2. Verify notable event aggregation policies\n"
                "3. Check glass table configurations for deprecated components\n"
                "4. Validate ITSI module dependencies (ITSI Add-ons)\n"
                "5. Test threshold templates and adaptive thresholding settings\n"
                "6. Backup $SPLUNK_HOME/etc/apps/itsi/lookups/ (service definitions)"
            ),
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP obsai_upgrade_itsi failed: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Handlers Registry — Phase 6 additions
# ---------------------------------------------------------------------------

_HANDLERS_EXT2: Dict[str, Any] = {
    "obsai_backup":            _handle_backup,
    "obsai_audit_log":         _handle_audit_log,
    "obsai_version":           _handle_version,
    "obsai_manage_containers": _handle_manage_containers,
    "obsai_manage_users":      _handle_manage_users,
    "obsai_manage_tokens":     _handle_manage_tokens,
    "obsai_ssl_status":        _handle_ssl_status,
    "obsai_manage_ports":      _handle_manage_ports,
    "obsai_manage_settings":   _handle_manage_settings,
    "obsai_manage_features":   _handle_manage_features,
    "obsai_manage_prompts":    _handle_manage_prompts,
    "obsai_manage_profiles":   _handle_manage_profiles,
    "obsai_manage_collections": _handle_manage_collections,
    "obsai_knowledge_graph":   _handle_knowledge_graph,
    "obsai_observability":     _handle_observability,
    "obsai_guardrails":        _handle_guardrails,
    "obsai_artifacts":         _handle_artifacts,
    "obsai_manage_workflows":  _handle_manage_workflows,
    "obsai_splunkbase":        _handle_splunkbase,
    "obsai_upgrade_es":        _handle_upgrade_es,
    "obsai_upgrade_itsi":      _handle_upgrade_itsi,
    # Phase 7: Platform intelligence
}


# ---------------------------------------------------------------------------
# Phase 7 — Platform Version Intelligence MCP Tools
# ---------------------------------------------------------------------------

async def _handle_enterprise_versions(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get Splunk Enterprise/UF version history with features, breaks, CVEs."""
    try:
        from chat_app.upgrade_readiness.platform_versions import get_enterprise_versions
        return {"versions": get_enterprise_versions(), "product": "enterprise/uf"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_es_versions(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get ES version history with release notes."""
    try:
        from chat_app.upgrade_readiness.platform_versions import get_es_versions
        return {"versions": get_es_versions(), "product": "es"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_version_diff(args: Dict[str, Any]) -> Dict[str, Any]:
    """Compare two platform versions — features, breaks, CVEs between them."""
    try:
        from chat_app.upgrade_readiness.platform_versions import get_version_diff
        product = args.get("product", "enterprise")
        from_v = args.get("from_version", "")
        to_v = args.get("to_version", "")
        if not from_v or not to_v:
            return {"error": "Both from_version and to_version are required"}
        return get_version_diff(product, from_v, to_v)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_security_advisories(args: Dict[str, Any]) -> Dict[str, Any]:
    """Get Splunk security advisories (CVEs), optionally filtered by version."""
    try:
        from chat_app.upgrade_readiness.platform_versions import get_security_advisories
        from_v = args.get("from_version", "")
        to_v = args.get("to_version", "")
        advisories = get_security_advisories(from_v, to_v)
        return {"advisories": advisories, "total": len(advisories)}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


_HANDLERS_EXT2["obsai_enterprise_versions"] = _handle_enterprise_versions
_HANDLERS_EXT2["obsai_es_versions"] = _handle_es_versions
_HANDLERS_EXT2["obsai_version_diff"] = _handle_version_diff
_HANDLERS_EXT2["obsai_security_advisories"] = _handle_security_advisories
