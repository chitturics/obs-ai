"""MCP Tool Handlers Extended — Docs, SPL, scripting, utilities, admin, and _HANDLERS registry.

Extracted from mcp_server_mode.py to keep file sizes manageable.
Contains handler functions for:
- Document generation (generate_docs)
- Core SPL (explain_spl, generate_spl, optimize_spl, run_search, create_alert, deep_search, reason)
- Scripting (ansible, shell_script, python_script, _run_skill_handler helper)
- Utilities (encode_decode, hash, transform_data, text_tools, spl_tools, validate_conf)
- Admin and orchestration (security_audit, manage_learning, orchestrate, agent_dispatch,
  spec_lookup, build_config, manage_collection, ingest, compare)

Also provides _HANDLERS: the canonical mapping from MCP tool name to handler callable.
"""

import logging
from typing import Dict

from chat_app.mcp_tool_handlers import _get_inventory_items  # noqa: F401 — re-export

logger = logging.getLogger(__name__)


async def _handle_generate_docs(args: Dict) -> Dict:
    """Generate documentation from content, directory, or zip file."""
    from chat_app.doc_generator import get_doc_generator

    content = args.get("content", "")
    title = args.get("title", "Documentation")
    fmt = args.get("format", "markdown")
    mode = args.get("mode", "snippet")
    style = args.get("style", "technical")

    if not content:
        return {"error": "Missing required parameter: content"}

    gen = get_doc_generator()

    try:
        if mode == "directory":
            result = gen.from_directory(content, title=title, format=fmt)
        elif mode == "zip":
            result = gen.from_zip(content, title=title, format=fmt)
        else:
            result = gen.from_snippets(
                snippets=[content], title=title, format=fmt, style=style,
            )
        return {
            "success": True,
            "documentation": result.content,
            "format": result.format,
            "metadata": result.metadata,
            "warnings": result.warnings,
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP generate_docs failed: %s", exc)
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Phase 1: Core SPL Tool Handlers
# ---------------------------------------------------------------------------

async def _handle_explain_spl(args: Dict) -> Dict:
    """Explain SPL query step by step."""
    spl = args.get("spl", "")
    if not spl:
        return {"error": "Missing required parameter: spl"}
    try:
        from chat_app.skill_executor import get_internal_handler
        handler = get_internal_handler("explain_spl")
        if handler:
            result = handler(user_input=spl)
            return {"explanation": result, "spl": spl}
        return {"error": "explain_spl handler not available"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_generate_spl(args: Dict) -> Dict:
    """Generate SPL from natural language."""
    desc = args.get("description", "")
    if not desc:
        return {"error": "Missing required parameter: description"}
    try:
        from chat_app.skill_executor import get_internal_handler
        handler = get_internal_handler("nlp_to_spl")
        if handler:
            result = handler(user_input=desc, index=args.get("index", ""), sourcetype=args.get("sourcetype", ""))
            return {"spl": result, "description": desc}
        return {"error": "nlp_to_spl handler not available"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_optimize_spl(args: Dict) -> Dict:
    """Optimize an SPL query."""
    spl = args.get("spl", "")
    if not spl:
        return {"error": "Missing required parameter: spl"}
    try:
        from chat_app.skill_executor import get_internal_handler
        handler = get_internal_handler("optimize_spl")
        if handler:
            result = handler(user_input=spl)
            return {"optimized": result, "original": spl}
        # Fallback to local optimizer
        from chat_app.spl_optimizer import SPLQueryOptimizer
        opt = SPLQueryOptimizer.optimize(spl)
        return {"optimized": str(opt), "original": spl}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_run_search(args: Dict) -> Dict:
    """Execute a Splunk search."""
    spl = args.get("spl", "")
    if not spl:
        return {"error": "Missing required parameter: spl"}
    try:
        from chat_app.skill_executor import get_internal_handler
        handler = get_internal_handler("run_splunk_search")
        if handler:
            result = handler(user_input=spl, earliest=args.get("earliest", "-1h"),
                           latest=args.get("latest", "now"), max_results=args.get("max_results", 100))
            return {"results": result, "spl": spl}
        return {"error": "run_splunk_search handler not available — Splunk connection required"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_create_alert(args: Dict) -> Dict:
    """Create a Splunk alert."""
    name = args.get("name", "")
    search = args.get("search", "")
    if not name or not search:
        return {"error": "Missing required parameters: name, search"}
    dry_run = args.get("dry_run", True)
    try:
        from chat_app.skill_executor import get_internal_handler
        handler = get_internal_handler("create_alert")
        if handler:
            result = handler(user_input=f"name={name} search={search} cron={args.get('cron', '')} severity={args.get('severity', 'warn')}")
            return {"result": result, "dry_run": dry_run, "name": name}
        return {"error": "create_alert handler not available"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_deep_search(args: Dict) -> Dict:
    """Deep multi-collection search."""
    query = args.get("query", "")
    if not query:
        return {"error": "Missing required parameter: query"}
    try:
        from chat_app.skill_executor import get_internal_handler
        handler = get_internal_handler("deep_search")
        if handler:
            result = handler(user_input=query, collections=args.get("collections"), k=args.get("k", 10))
            return {"results": result, "query": query}
        # Fallback to standard search
        from chat_app.vectorstore_search import search_similar_chunks_parallel
        chunks = await search_similar_chunks_parallel(query, k=args.get("k", 10))
        return {"results": chunks[:args.get("k", 10)], "query": query}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_reason(args: Dict) -> Dict:
    """Multi-step ReAct reasoning."""
    question = args.get("question", "")
    if not question:
        return {"error": "Missing required parameter: question"}
    try:
        from chat_app.skill_executor import get_internal_handler
        handler = get_internal_handler("react_loop")
        if handler:
            result = handler(user_input=question, max_steps=args.get("max_steps", 5))
            return {"reasoning": result, "question": question}
        return {"error": "react_loop handler not available"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Phase 2: Scripting Handlers
# ---------------------------------------------------------------------------

async def _handle_ansible(args: Dict) -> Dict:
    """Ansible automation operations."""
    action = args.get("action", "")
    content = args.get("content", "")
    if not action or not content:
        return {"error": "Missing required parameters: action, content"}
    handler_map = {
        "validate": "ansible_validate_playbook",
        "generate": "ansible_generate_playbook",
        "explain": "ansible_explain_playbook",
        "improve": "ansible_improve_playbook",
        "module_reference": "ansible_module_reference",
    }
    return await _run_skill_handler(handler_map.get(action, ""), content, f"ansible_{action}")


async def _handle_shell_script(args: Dict) -> Dict:
    """Shell scripting operations."""
    action = args.get("action", "")
    content = args.get("content", "")
    if not action or not content:
        return {"error": "Missing required parameters: action, content"}
    handler_map = {
        "analyze": "shell_analyze_script",
        "generate": "shell_generate_script",
        "improve": "shell_improve_script",
        "explain": "shell_explain_script",
    }
    return await _run_skill_handler(handler_map.get(action, ""), content, f"shell_{action}")


async def _handle_python_script(args: Dict) -> Dict:
    """Python scripting operations."""
    action = args.get("action", "")
    content = args.get("content", "")
    if not action or not content:
        return {"error": "Missing required parameters: action, content"}
    handler_map = {
        "analyze": "python_analyze_script",
        "generate": "python_generate_script",
        "improve": "python_improve_script",
        "explain": "python_explain_script",
    }
    return await _run_skill_handler(handler_map.get(action, ""), content, f"python_{action}")


async def _run_skill_handler(handler_key: str, content: str, label: str) -> Dict:
    """Generic helper to run a skill handler via MCP."""
    if not handler_key:
        return {"error": f"Unknown action: {label}"}
    try:
        from chat_app.skill_executor import get_internal_handler
        handler = get_internal_handler(handler_key)
        if handler:
            result = handler(user_input=content)
            return {"result": result, "handler": handler_key}
        return {"error": f"{handler_key} handler not registered"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Phase 3: Utility Handlers
# ---------------------------------------------------------------------------

async def _handle_encode_decode(args: Dict) -> Dict:
    """Encode/decode data."""
    operation = args.get("operation", "")
    data = args.get("data", "")
    if not operation or not data:
        return {"error": "Missing required parameters: operation, data"}
    return await _run_skill_handler(operation, data, operation)


async def _handle_hash(args: Dict) -> Dict:
    """Generate cryptographic hash."""
    data = args.get("data", "")
    algorithm = args.get("algorithm", "sha256")
    if not data:
        return {"error": "Missing required parameter: data"}
    return await _run_skill_handler(algorithm, data, f"hash_{algorithm}")


async def _handle_transform_data(args: Dict) -> Dict:
    """Transform data formats."""
    operation = args.get("operation", "")
    data = args.get("data", "")
    if not operation or not data:
        return {"error": "Missing required parameters: operation, data"}
    return await _run_skill_handler(operation, data, operation)


async def _handle_text_tools(args: Dict) -> Dict:
    """Text manipulation."""
    operation = args.get("operation", "")
    text = args.get("text", "")
    if not operation or not text:
        return {"error": "Missing required parameters: operation, text"}
    op_map = {
        "upper": "text_upper", "lower": "text_lower", "reverse": "text_reverse",
        "trim": "text_trim", "line_sort": "line_sort", "unique_lines": "unique_lines",
        "remove_empty_lines": "remove_empty_lines",
    }
    return await _run_skill_handler(op_map.get(operation, ""), text, operation)


async def _handle_spl_tools(args: Dict) -> Dict:
    """SPL utility operations."""
    operation = args.get("operation", "")
    data = args.get("data", "")
    if not operation or not data:
        return {"error": "Missing required parameters: operation, data"}
    extra = {}
    if args.get("pattern"):
        extra["pattern"] = args["pattern"]
    try:
        from chat_app.skill_executor import get_internal_handler
        handler = get_internal_handler(operation)
        if handler:
            result = handler(user_input=data, **extra)
            return {"result": result, "operation": operation}
        return {"error": f"{operation} handler not registered"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_validate_conf(args: Dict) -> Dict:
    """Validate Splunk conf or CIM."""
    operation = args.get("operation", "")
    data = args.get("data", "")
    if not operation or not data:
        return {"error": "Missing required parameters: operation, data"}
    return await _run_skill_handler(operation, data, operation)


# ---------------------------------------------------------------------------
# Phase 4: Admin & Orchestration Handlers
# ---------------------------------------------------------------------------

async def _handle_security_audit(args: Dict) -> Dict:
    """Run security audit."""
    scope = args.get("scope", "full")
    try:
        from chat_app.skill_executor import get_internal_handler
        handler = get_internal_handler("security_audit")
        if handler:
            result = handler(user_input=f"scope={scope} target={args.get('target', '')}")
            return {"audit": result, "scope": scope}
        return {"error": "security_audit handler not available"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_manage_learning(args: Dict) -> Dict:
    """Manage self-learning operations."""
    action = args.get("action", "status")
    try:
        from chat_app.skill_executor import get_internal_handler
        handler_map = {
            "generate_qa": "self_learning_qa",
            "reassess": "self_learning_reassess",
            "export_training": "export_training",
            "status": "idle_worker",
        }
        handler = get_internal_handler(handler_map.get(action, "idle_worker"))
        if handler:
            result = handler(user_input=action)
            return {"result": result, "action": action}
        return {"status": "Learning system available via idle worker", "action": action}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_orchestrate(args: Dict) -> Dict:
    """Execute multi-agent orchestration."""
    query = args.get("query", "")
    strategy = args.get("strategy", "adaptive")
    if not query:
        return {"error": "Missing required parameter: query"}
    try:
        from chat_app.skill_executor import get_internal_handler
        handler = get_internal_handler("orchestrator")
        if handler:
            result = handler(user_input=query, strategy=strategy)
            return {"result": result, "strategy": strategy}
        return {"error": "orchestrator handler not available"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_agent_dispatch(args: Dict) -> Dict:
    """Dispatch query to best-fit agent."""
    query = args.get("query", "")
    if not query:
        return {"error": "Missing required parameter: query"}
    try:
        from chat_app.skill_executor import get_internal_handler
        handler = get_internal_handler("agent_dispatch")
        if handler:
            result = handler(user_input=query, department=args.get("department", ""))
            return {"result": result, "query": query}
        return {"error": "agent_dispatch handler not available"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_spec_lookup(args: Dict) -> Dict:
    """Look up .conf.spec files."""
    query = args.get("query", "")
    if not query:
        return {"error": "Missing required parameter: query"}
    try:
        from chat_app.skill_executor import get_internal_handler
        handler = get_internal_handler("conf_parser")
        if handler:
            result = handler(user_input=query)
            return {"spec": result, "query": query}
        return {"error": "conf_parser handler not available"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_build_config(args: Dict) -> Dict:
    """Generate .conf stanzas."""
    config_type = args.get("config_type", "")
    description = args.get("description", "")
    if not config_type or not description:
        return {"error": "Missing required parameters: config_type, description"}
    try:
        from chat_app.skill_executor import get_internal_handler
        handler = get_internal_handler("config_generator")
        if handler:
            result = handler(user_input=f"{config_type}: {description}")
            return {"config": result, "type": config_type}
        return {"error": "config_generator handler not available"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_manage_collection_tool(args: Dict) -> Dict:
    """Manage vector store collections."""
    action = args.get("action", "list")
    collection = args.get("collection", "")
    dry_run = args.get("dry_run", True)
    try:
        if action == "list":
            from chat_app.vectorstore_search import list_all_collections
            collections = list_all_collections()
            return {"collections": collections}
        elif action == "stats":
            from chat_app.vectorstore_search import get_collection_stats
            stats = get_collection_stats(collection) if collection else {}
            return {"stats": stats, "collection": collection}
        elif action in ("create", "reindex", "delete") and dry_run:
            return {"dry_run": True, "action": action, "collection": collection,
                    "message": f"Would {action} collection '{collection}'. Set dry_run=false to execute."}
        return {"error": f"Action '{action}' requires collection name or dry_run=false"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_ingest(args: Dict) -> Dict:
    """Ingest documents into knowledge base."""
    source = args.get("source", "")
    if not source:
        return {"error": "Missing required parameter: source"}
    try:
        from chat_app.skill_executor import get_internal_handler
        handler = get_internal_handler("ingest_document")
        if handler:
            result = handler(user_input=source, collection=args.get("collection", "ingested_docs"),
                           doc_type=args.get("doc_type", "auto"))
            return {"result": result, "source": source}
        return {"error": "ingest_document handler not available"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


async def _handle_compare(args: Dict) -> Dict:
    """Compare SPL commands or configs."""
    items = args.get("items", "")
    if not items:
        return {"error": "Missing required parameter: items"}
    try:
        from chat_app.skill_executor import get_internal_handler
        handler = get_internal_handler("compare")
        if handler:
            result = handler(user_input=items, context=args.get("context", ""))
            return {"comparison": result, "items": items}
        return {"error": "compare handler not available"}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


# ---------------------------------------------------------------------------
# Phase 5: Upgrade Readiness, SLO, CIM, Lessons, Evolution, Dependencies
# ---------------------------------------------------------------------------

async def _handle_check_upgrade_readiness(args: Dict) -> Dict:
    """Analyze Splunk app/TA upgrade readiness."""
    app_name = args.get("app_name", "")
    cluster = args.get("cluster", "")
    if not app_name or not cluster:
        return {"error": "Missing required parameters: app_name, cluster"}
    run_cim_check = args.get("run_cim_check", True)
    try:
        from upgrade_readiness import get_upgrade_scanner
        scanner = get_upgrade_scanner()
        baseline = scanner.baseline_scan(app_name=app_name, cluster=cluster)
        diff = scanner.diff_confs(app_name=app_name, cluster=cluster)
        impact = scanner.impact_analysis(app_name=app_name, cluster=cluster)
        result: Dict = {
            "app_name": app_name,
            "cluster": cluster,
            "baseline": baseline,
            "conf_diff": diff,
            "impact": impact,
        }
        if run_cim_check:
            cim_result = scanner.cim_check(app_name=app_name, cluster=cluster)
            result["cim_compliance"] = cim_result
        return {"success": True, **result}
    except ImportError:
        # Graceful degradation: upgrade_readiness package not installed
        return {
            "success": False,
            "app_name": app_name,
            "cluster": cluster,
            "error": "upgrade_readiness package not available — install it to enable this tool",
            "guidance": (
                "Manual checklist: (1) backup current conf files, "
                "(2) diff against new version, "
                "(3) verify CIM field mappings, "
                "(4) check app dependencies"
            ),
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP check_upgrade_readiness failed: %s", exc)
        return {"error": str(exc)}


async def _handle_generate_runbook(args: Dict) -> Dict:
    """Generate a step-by-step upgrade runbook with real Splunk CLI commands."""
    from_version = args.get("from_version", "")
    to_version = args.get("to_version", "")
    if not from_version or not to_version:
        return {"error": "Missing required parameters: from_version, to_version"}

    upgrade_type = args.get("upgrade_type", "splunk_core")
    app_id = args.get("app_id", "")
    cluster = args.get("cluster", "")
    conf_files = args.get("conf_files") or {}

    try:
        from chat_app.upgrade_readiness.runbook_generator import RunbookGenerator
        from chat_app.upgrade_readiness.config_auditor import ConfigAuditor
        from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer
        from chat_app.upgrade_readiness.breaking_changes_db import get_breaking_changes_db

        config_audit = None
        if conf_files:
            auditor = ConfigAuditor()
            config_audit = auditor.audit(
                conf_files=conf_files,
                from_version=from_version,
                to_version=to_version,
            )

        db = get_breaking_changes_db()
        breaking_changes = db.get_changes_between(from_version, to_version)

        scorer = ReadinessScorer()
        readiness_score = scorer.calculate_score(
            config_audit=config_audit,
            breaking_changes=breaking_changes,
        )

        generator = RunbookGenerator()
        runbook = generator.generate(
            from_version=from_version,
            to_version=to_version,
            upgrade_type=upgrade_type,
            config_audit=config_audit,
            breaking_changes=breaking_changes,
            readiness_score=readiness_score,
            app_id=app_id,
            cluster=cluster,
        )

        return {
            "success": True,
            "runbook": runbook.to_dict(),
            "markdown": runbook.to_markdown(),
            "readiness_score": readiness_score.to_dict(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP generate_runbook failed: %s", exc)
        return {"error": str(exc), "success": False}


async def _handle_check_slo(args: Dict) -> Dict:
    """Check SLO compliance status and error budgets."""
    try:
        from slo_gate import evaluate_all
        report = evaluate_all()
        return {"success": True, "report": report}
    except ImportError:
        return {
            "success": False,
            "error": "slo_gate package not available",
            "guidance": "Configure SLO targets in config.yaml under the slo: section",
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP check_slo failed: %s", exc)
        return {"error": str(exc)}


async def _handle_check_cim(args: Dict) -> Dict:
    """Check CIM compliance for a Splunk app on a cluster."""
    app_name = args.get("app_name", "")
    cluster = args.get("cluster", "")
    if not app_name or not cluster:
        return {"error": "Missing required parameters: app_name, cluster"}
    try:
        from upgrade_readiness import get_upgrade_scanner
        scanner = get_upgrade_scanner()
        cim_result = scanner.cim_check(app_name=app_name, cluster=cluster)
        return {"success": True, "app_name": app_name, "cluster": cluster, "cim_compliance": cim_result}
    except ImportError:
        return {
            "success": False,
            "app_name": app_name,
            "cluster": cluster,
            "error": "upgrade_readiness package not available",
            "guidance": (
                "Manual CIM check: verify props.conf FIELDALIAS and EVAL-* entries map to "
                "CIM field names. Use | tstats count FROM datamodel= to validate."
            ),
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP check_cim failed: %s", exc)
        return {"error": str(exc)}


async def _handle_manage_lessons(args: Dict) -> Dict:
    """Query or record lessons learned from failures and corrections."""
    action = args.get("action", "query")
    try:
        from chat_app.self_learning import get_self_learning_manager
        manager = get_self_learning_manager()

        if action == "stats":
            stats = manager.get_lessons_stats() if hasattr(manager, "get_lessons_stats") else {}
            return {"success": True, "action": "stats", "stats": stats}

        if action == "record":
            description = args.get("description", "")
            fix = args.get("fix", "")
            category = args.get("category", "general")
            if not description:
                return {"error": "Missing required parameter: description (for record action)"}
            lesson = {
                "category": category,
                "description": description,
                "fix": fix,
            }
            if hasattr(manager, "record_lesson"):
                lesson_id = manager.record_lesson(lesson)
                return {"success": True, "action": "record", "lesson_id": lesson_id, "lesson": lesson}
            return {"success": False, "error": "record_lesson not available on self_learning manager"}

        # Default: query
        query = args.get("query", "")
        category = args.get("category", "")
        if hasattr(manager, "query_lessons"):
            results = manager.query_lessons(query=query, category=category)
        else:
            results = []
        return {"success": True, "action": "query", "query": query, "results": results}
    except ImportError:
        return {"success": False, "error": "self_learning module not available"}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP manage_lessons failed: %s", exc)
        return {"error": str(exc)}


async def _handle_run_evolution(args: Dict) -> Dict:
    """Trigger daily self-improvement evolution cycle."""
    try:
        from chat_app.idle_worker import get_idle_worker
        worker = get_idle_worker()
        if hasattr(worker, "run_evolution_cycle"):
            result = await worker.run_evolution_cycle()
            return {"success": True, "result": result}
        # Fallback: trigger via self_learning
        from chat_app.self_learning import get_self_learning_manager
        manager = get_self_learning_manager()
        if hasattr(manager, "run_evolution"):
            result = manager.run_evolution()
            return {"success": True, "result": result}
        return {"success": False, "error": "Evolution cycle not available — idle worker or self_learning required"}
    except ImportError:
        return {"success": False, "error": "Evolution modules not available"}
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP run_evolution failed: %s", exc)
        return {"error": str(exc)}


async def _handle_check_dependencies(args: Dict) -> Dict:
    """Map cross-app dependencies for a Splunk cluster."""
    cluster = args.get("cluster", "")
    if not cluster:
        return {"error": "Missing required parameter: cluster"}
    try:
        from upgrade_readiness import get_upgrade_scanner
        scanner = get_upgrade_scanner()
        if hasattr(scanner, "map_dependencies"):
            dep_map = scanner.map_dependencies(cluster=cluster)
            return {"success": True, "cluster": cluster, "dependencies": dep_map}
        return {"success": False, "error": "map_dependencies not available on upgrade_readiness scanner"}
    except ImportError:
        # Graceful degradation: try knowledge graph as fallback
        try:
            from chat_app.knowledge_graph import get_knowledge_graph
            kg = get_knowledge_graph()
            if kg:
                entities = kg.get_entities_by_type("ConfigStanza")
                return {
                    "success": True,
                    "cluster": cluster,
                    "source": "knowledge_graph",
                    "note": "upgrade_readiness package not installed — using knowledge graph for dependency hints",
                    "config_stanzas": [str(e) for e in list(entities)[:50]] if entities else [],
                }
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("KG fallback failed: %s", _exc)
        return {
            "success": False,
            "cluster": cluster,
            "error": "upgrade_readiness package not available",
            "guidance": "Check app dependencies manually via: splunk btool --debug list all",
        }
    except (OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("MCP check_dependencies failed: %s", exc)
        return {"error": str(exc)}



# ---------------------------------------------------------------------------
# Handlers Registry — maps MCP tool names to handler callables
# ---------------------------------------------------------------------------

from chat_app.mcp_tool_handlers import (  # noqa: E402
    _handle_search,
    _handle_ask,
    _handle_kg_query,
    _handle_validate_spl,
    _handle_health,
    _handle_config_diff,
    _handle_inventory,
    _handle_config_update,
    _handle_container_action,
    _handle_analyze_confs,
)
from chat_app.mcp_tool_handlers_ext2 import _HANDLERS_EXT2  # noqa: E402

_HANDLERS = {
    "obsai_search": _handle_search,
    "obsai_ask": _handle_ask,
    "obsai_kg_query": _handle_kg_query,
    "obsai_validate_spl": _handle_validate_spl,
    "obsai_health": _handle_health,
    "obsai_config_diff": _handle_config_diff,
    "obsai_inventory": _handle_inventory,
    "obsai_config_update": _handle_config_update,
    "obsai_container_action": _handle_container_action,
    "obsai_analyze_confs": _handle_analyze_confs,
    "obsai_generate_docs": _handle_generate_docs,
    "obsai_explain_spl": _handle_explain_spl,
    "obsai_generate_spl": _handle_generate_spl,
    "obsai_optimize_spl": _handle_optimize_spl,
    "obsai_run_search": _handle_run_search,
    "obsai_create_alert": _handle_create_alert,
    "obsai_deep_search": _handle_deep_search,
    "obsai_reason": _handle_reason,
    "obsai_ansible": _handle_ansible,
    "obsai_shell_script": _handle_shell_script,
    "obsai_python_script": _handle_python_script,
    "obsai_encode_decode": _handle_encode_decode,
    "obsai_hash": _handle_hash,
    "obsai_transform_data": _handle_transform_data,
    "obsai_text_tools": _handle_text_tools,
    "obsai_spl_tools": _handle_spl_tools,
    "obsai_validate_conf": _handle_validate_conf,
    "obsai_security_audit": _handle_security_audit,
    "obsai_manage_learning": _handle_manage_learning,
    "obsai_orchestrate": _handle_orchestrate,
    "obsai_agent_dispatch": _handle_agent_dispatch,
    "obsai_spec_lookup": _handle_spec_lookup,
    "obsai_build_config": _handle_build_config,
    "obsai_manage_collection": _handle_manage_collection_tool,
    "obsai_ingest": _handle_ingest,
    "obsai_compare": _handle_compare,
    "obsai_check_upgrade_readiness": _handle_check_upgrade_readiness,
    "obsai_generate_runbook": _handle_generate_runbook,
    "obsai_check_slo": _handle_check_slo,
    "obsai_check_cim": _handle_check_cim,
    "obsai_manage_lessons": _handle_manage_lessons,
    "obsai_run_evolution": _handle_run_evolution,
    "obsai_check_dependencies": _handle_check_dependencies,
    # Phase 6 handlers (loaded from mcp_tool_handlers_ext2)
    **_HANDLERS_EXT2,
}
