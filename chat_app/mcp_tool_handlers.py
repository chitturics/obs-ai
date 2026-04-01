"""MCP Tool Handlers — Core handler functions for MCP tool calls.

Extracted from mcp_server_mode.py to keep file sizes manageable.
Contains handler functions for:
- Knowledge search (search, ask, kg_query, validate_spl)
- Admin read-only (health, config_diff, inventory)
- Controlled write (config_update, container_action, analyze_confs)

Extended handlers (docs, SPL, scripting, utilities, admin) are in
mcp_tool_handlers_ext.py.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def _handle_search(args: Dict) -> Dict:
    from chat_app.vectorstore_search import search_similar_chunks_parallel
    from chat_app.vectorstore import get_vector_store
    store = get_vector_store()
    if not store:
        return {"error": "Vector store not available", "results": []}
    k = args.get("k", 5)
    chunks = await search_similar_chunks_parallel(store, args["query"], k=k)
    return {"results": [{"text": c.get("text", "")[:500], "source": c.get("source", ""), "score": c.get("score", 0)}
                         for c in chunks[:k]], "total": len(chunks)}


async def _handle_ask(args: Dict) -> Dict:
    from chat_app.vectorstore_search import search_similar_chunks_parallel
    from chat_app.vectorstore import get_vector_store
    chunks = await search_similar_chunks_parallel(get_vector_store(), args["question"], k=3)
    context = "\n\n".join(c.get("text", "")[:300] for c in chunks[:3])
    return {"answer": f"Based on {len(chunks)} results:\n\n{context}" if chunks else "No relevant information found.",
            "sources": [c.get("source", "") for c in chunks[:3]], "chunks_found": len(chunks)}


async def _handle_kg_query(args: Dict) -> Dict:
    from chat_app.knowledge_graph import get_knowledge_graph
    kg = get_knowledge_graph()
    if not kg:
        return {"error": "Knowledge graph not available"}
    entity = args["entity"]
    results = kg.search_entities(entity, limit=5) if hasattr(kg, "search_entities") else []
    return {"entity": entity, "context": kg.generate_context_for_query(entity, "general_qa"), "matches": len(results)}


async def _handle_validate_spl(args: Dict) -> Dict:
    from shared.spl_robust_analyzer import analyze_spl
    result = analyze_spl(args["spl"])
    return {"valid": True, "analysis": str(result)[:500]}


# ---------------------------------------------------------------------------
# Admin read-only handlers
# ---------------------------------------------------------------------------

async def _handle_health(args: Dict) -> Dict:
    """Check system health: services, containers, collections, pipeline status."""
    from chat_app.health_monitor import get_comprehensive_health
    try:
        health = await get_comprehensive_health()
        services = {}
        for svc in health.services:
            services[svc.name] = {
                "status": svc.status,
                "latency_ms": svc.latency_ms,
                "error": svc.error,
            }

        # Collection count
        collection_count = 0
        try:
            from chat_app.vectorstore import get_vector_store
            store = get_vector_store()
            if store and hasattr(store, "_client"):
                collection_count = len(store._client.list_collections())
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

        return {
            "overall": health.overall,
            "services": services,
            "collections_count": collection_count,
            "metrics": health.metrics,
            "timestamp": health.timestamp,
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP health check failed: %s", exc)
        return {"overall": "unknown", "error": str(exc)}


async def _handle_config_diff(args: Dict) -> Dict:
    """Show pending config changes by comparing on-disk vs in-memory config."""
    import copy
    try:
        from chat_app.config_manager import get_config_manager
        mgr = get_config_manager()
        # Load fresh from disk
        disk_config = mgr.load(force=True)
        # Compare with cached version (the last-loaded state)
        cached = copy.deepcopy(mgr._cache) if mgr._cache else {}

        if not cached:
            return {"status": "no_cache", "message": "No cached config state to compare against"}

        diffs: Dict[str, Any] = {}
        all_keys = set(list(disk_config.keys()) + list(cached.keys()))
        for key in sorted(all_keys):
            disk_val = disk_config.get(key)
            cached_val = cached.get(key)
            if disk_val != cached_val:
                diffs[key] = {"disk": _safe_repr(disk_val), "memory": _safe_repr(cached_val)}

        return {
            "has_changes": bool(diffs),
            "changed_sections": list(diffs.keys()),
            "diffs": diffs,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP config_diff failed: %s", exc)
        return {"error": str(exc)}


async def _handle_inventory(args: Dict) -> Dict:
    """List configured Splunk assets (indexes, sourcetypes, saved searches, etc.)."""
    asset_type = args.get("asset_type", "indexes")
    try:
        from chat_app.org_data_loader import get_org_stats
        stats = get_org_stats()

        if asset_type == "indexes":
            # Try to get actual index list from org data
            items = _get_inventory_items("indexes")
            return {"asset_type": "indexes", "count": stats.get("indexes", 0), "items": items}

        elif asset_type == "saved_searches":
            items = _get_inventory_items("saved_searches")
            return {"asset_type": "saved_searches", "count": stats.get("saved_searches", 0), "items": items}

        elif asset_type == "sourcetypes":
            items = _get_inventory_items("sourcetypes")
            return {"asset_type": "sourcetypes", "count": len(items), "items": items}

        elif asset_type == "cribl_pipelines":
            items = _get_inventory_items("cribl_pipelines")
            return {"asset_type": "cribl_pipelines", "count": len(items), "items": items}

        else:
            return {"error": f"Unknown asset_type: {asset_type}. Use: indexes, sourcetypes, saved_searches, cribl_pipelines"}

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP inventory failed: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Controlled write handlers (support dry_run)
# ---------------------------------------------------------------------------

async def _handle_config_update(args: Dict) -> Dict:
    """Update a config section. Supports dry_run preview."""
    import copy
    section = args.get("section", "")
    values = args.get("values", {})
    dry_run = args.get("dry_run", True)

    if not section:
        return {"error": "Missing required parameter: section"}
    if not values:
        return {"error": "Missing required parameter: values"}

    try:
        from chat_app.config_manager import get_config_manager
        mgr = get_config_manager()
        current = mgr.get_section(section)

        if dry_run:
            # Preview: show what would change
            preview = copy.deepcopy(current)
            if isinstance(preview, dict):
                preview.update(values)
            else:
                preview = values
            changed_keys = [k for k in values if current.get(k) != values[k]] if isinstance(current, dict) else list(values.keys())
            return {
                "action": "preview",
                "section": section,
                "current": _safe_repr(current),
                "proposed": _safe_repr(preview),
                "changed_keys": changed_keys,
                "message": "Set dry_run=false to apply these changes",
            }
        else:
            # Apply the change
            success, updated = mgr.update_section(section, values)
            return {
                "action": "applied",
                "section": section,
                "success": success,
                "result": _safe_repr(updated),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP config_update failed: %s", exc)
        return {"error": str(exc)}


async def _handle_container_action(args: Dict) -> Dict:
    """Restart, stop, or start a container. Supports dry_run preview."""
    import subprocess
    service = args.get("service", "")
    action = args.get("action", "")
    dry_run = args.get("dry_run", True)

    if not service or not action:
        return {"error": "Missing required parameters: service, action"}

    if action not in ("restart", "stop", "start"):
        return {"error": f"Invalid action: {action}. Use: restart, stop, start"}

    # Validate service name against allowlist
    from chat_app.admin_shared import _ALLOWED_CONTAINER_SERVICES
    if service not in _ALLOWED_CONTAINER_SERVICES:
        return {"error": f"Unknown service: {service}. Valid: {sorted(_ALLOWED_CONTAINER_SERVICES)}"}

    if dry_run:
        return {
            "action": "preview",
            "service": service,
            "command": f"{action} {service}",
            "message": f"Would {action} container '{service}'. Set dry_run=false to execute.",
        }

    # Execute the action
    from chat_app.admin_shared import _container_cmd, _arun
    runtime = _container_cmd()
    if runtime is None:
        return {"error": "No container runtime (podman/docker) available inside this container"}

    try:
        result = await _arun(
            [runtime, action, service],
            capture_output=True, text=True, timeout=120,
        )
        return {
            "action": "applied",
            "service": service,
            "command": action,
            "success": result.returncode == 0,
            "stdout": (result.stdout or "")[-2000:],
            "stderr": (result.stderr or "")[-2000:],
            "exit_code": result.returncode,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
    except subprocess.TimeoutExpired:
        return {"error": f"Container action '{action}' on '{service}' timed out after 120s"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_analyze_confs(args: Dict) -> Dict:
    """Analyze Splunk props/transforms configurations for Cribl migration."""
    from pathlib import Path
    apps_dir = args.get("apps_dir", "")
    app_filter = args.get("app_filter")

    if not apps_dir:
        return {"error": "Missing required parameter: apps_dir"}

    apps_path = Path(apps_dir)
    if not apps_path.is_dir():
        return {"error": f"Directory not found: {apps_dir}"}

    try:
        from shared.conf_parser import parse_conf_file_advanced

        results: Dict[str, Any] = {"apps": {}, "summary": {"total_props_stanzas": 0, "total_transforms": 0, "apps_analyzed": 0}}

        for entry in sorted(apps_path.iterdir()):
            if not entry.is_dir():
                continue
            app_name = entry.name
            if app_filter and app_filter.lower() not in app_name.lower():
                continue

            app_result: Dict[str, Any] = {"props": {}, "transforms": {}}

            # Parse props.conf
            for conf_variant in ("local/props.conf", "default/props.conf"):
                props_path = entry / conf_variant
                if props_path.is_file():
                    content = props_path.read_text(encoding="utf-8", errors="replace")
                    stanzas = parse_conf_file_advanced(content, filename=str(props_path))
                    for stanza_name, kv in stanzas.items():
                        clean = {k: v for k, v in kv.items() if k != "__lines__"}
                        app_result["props"][stanza_name] = clean
                        results["summary"]["total_props_stanzas"] += 1

            # Parse transforms.conf
            for conf_variant in ("local/transforms.conf", "default/transforms.conf"):
                tf_path = entry / conf_variant
                if tf_path.is_file():
                    content = tf_path.read_text(encoding="utf-8", errors="replace")
                    stanzas = parse_conf_file_advanced(content, filename=str(tf_path))
                    for stanza_name, kv in stanzas.items():
                        clean = {k: v for k, v in kv.items() if k != "__lines__"}
                        app_result["transforms"][stanza_name] = clean
                        results["summary"]["total_transforms"] += 1

            if app_result["props"] or app_result["transforms"]:
                results["apps"][app_name] = app_result
                results["summary"]["apps_analyzed"] += 1

        # Add migration hints
        migration_hints = []
        for app_name, app_data in results["apps"].items():
            for stanza, kv in app_data.get("props", {}).items():
                if "TRANSFORMS" in kv or "REPORT" in kv:
                    migration_hints.append(f"{app_name}/{stanza}: has TRANSFORMS/REPORT — map to Cribl pipeline functions")
                if "TIME_FORMAT" in kv or "TIME_PREFIX" in kv:
                    migration_hints.append(f"{app_name}/{stanza}: has timestamp extraction — use Cribl Auto Timestamp or Regex")
                if "SEDCMD" in kv or any(k.startswith("SEDCMD") for k in kv):
                    migration_hints.append(f"{app_name}/{stanza}: has SEDCMD — convert to Cribl Regex Extract/Replace")
            for stanza, kv in app_data.get("transforms", {}).items():
                if "REGEX" in kv and "FORMAT" in kv:
                    migration_hints.append(f"{app_name}/transforms/{stanza}: REGEX+FORMAT — map to Cribl Regex Extract")
                if "LOOKUP" in str(kv).upper() or kv.get("filename"):
                    migration_hints.append(f"{app_name}/transforms/{stanza}: lookup transform — use Cribl Lookup function")

        results["migration_hints"] = migration_hints[:50]  # Cap at 50 hints
        return results

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP analyze_confs failed: %s", exc)
        return {"error": str(exc)}

# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def _safe_repr(val: Any) -> Any:
    """Return a JSON-safe representation of a value, truncating large dicts."""
    if isinstance(val, dict):
        if len(val) > 30:
            keys = list(val.keys())[:30]
            return {k: _safe_repr(val[k]) for k in keys} | {"__truncated__": f"{len(val)} total keys"}
        return {k: _safe_repr(v) for k, v in val.items()}
    if isinstance(val, (list, tuple)):
        if len(val) > 50:
            return [_safe_repr(v) for v in val[:50]] + [f"... {len(val)} total items"]
        return [_safe_repr(v) for v in val]
    if isinstance(val, (str, int, float, bool, type(None))):
        return val
    return str(val)[:200]


def _get_inventory_items(asset_type: str) -> list:
    """Extract inventory items from org data or config paths."""
    try:
        from chat_app.settings import get_settings
        settings = get_settings()
        org_cfg = getattr(settings, "organization", None)
        config_paths = []
        if org_cfg and hasattr(org_cfg, "config_paths"):
            config_paths = org_cfg.config_paths or []

        if asset_type == "indexes":
            from shared.conf_loader import load_indexes_from_conf
            items = []
            for p in config_paths:
                try:
                    items.extend(load_indexes_from_conf(p))
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                    logger.debug("%s", _exc)  # was: pass
            return sorted(set(items))

        elif asset_type == "saved_searches":
            from shared.conf_loader import load_searches_from_conf
            items = {}
            for p in config_paths:
                try:
                    items.update(load_searches_from_conf(p))
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                    logger.debug("%s", _exc)  # was: pass
            return sorted(items.keys())

        elif asset_type == "sourcetypes":
            # Extract sourcetypes from props.conf stanzas across config paths
            from pathlib import Path
            from shared.conf_parser import parse_conf_file_advanced
            sourcetypes = set()
            for p in config_paths:
                props_path = Path(p) / "props.conf"
                if not props_path.is_file():
                    # Search recursively
                    for pp in Path(p).rglob("props.conf"):
                        try:
                            stanzas = parse_conf_file_advanced(pp.read_text(errors="replace"))
                            sourcetypes.update(s for s in stanzas if not s.startswith("__"))
                        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                            logger.debug("%s", _exc)  # was: pass
                else:
                    try:
                        stanzas = parse_conf_file_advanced(props_path.read_text(errors="replace"))
                        sourcetypes.update(s for s in stanzas if not s.startswith("__"))
                    except (OSError, ValueError, KeyError, TypeError) as _exc:
                        logger.debug("%s", _exc)  # was: pass
            return sorted(sourcetypes)

        elif asset_type == "cribl_pipelines":
            # Cribl pipelines from config if available
            from chat_app.config_manager import get_config_manager
            mgr = get_config_manager()
            cribl_cfg = mgr.get_section("cribl") or mgr.get_section("organization")
            pipelines = cribl_cfg.get("pipelines", []) if isinstance(cribl_cfg, dict) else []
            return pipelines if isinstance(pipelines, list) else []

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("Failed to get inventory items for %s: %s", asset_type, exc)
    return []
