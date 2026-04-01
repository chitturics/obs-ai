"""
Standalone FastAPI entry point for ObsAI - Observability AI Assistant (Open WebUI mode).

Starts a plain FastAPI server exposing OpenAI-compatible endpoints.
This is used when config.yaml has ``ui.framework: open-webui``.

Run with: uvicorn app_api:app --host 0.0.0.0 --port 8000
"""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from chat_app.settings import get_settings
from chat_app import openai_compat
from chat_app.session_store import session_store
from chat_app.admin_api import router as admin_router, public_router as admin_public_router

# ---------------------------------------------------------------------------
# Settings & logging
# ---------------------------------------------------------------------------
_settings = get_settings()

LOG_LEVEL = _settings.app.log_level.upper()
from logging_utils import setup_logging
logger = setup_logging(app_name="splunk_assistant_api", level=LOG_LEVEL)

# Paths
DOCUMENTS_ROOT = _settings.paths.documents_root

# ---------------------------------------------------------------------------
# Globals initialised at startup
# ---------------------------------------------------------------------------
engine = None
VECTOR_STORE = None


async def _init_backend():
    """Initialise DB engine, vector store, and LLM chain."""
    global engine, VECTOR_STORE

    from sqlalchemy.ext.asyncio import create_async_engine
    from feedback_logger import init_storage
    from vectorstore import ensure_vector_store

    DB_URL = _settings.database.url
    if not DB_URL:
        logger.warning("DATABASE_URL not set — running without persistence")
    else:
        engine = create_async_engine(
            DB_URL,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=False,
            connect_args={
                "server_settings": {"application_name": "splunk_assistant_api"},
                "command_timeout": 60,
                "timeout": 10,
            },
        )
        await init_storage(DB_URL, existing_engine=engine)
        logger.info("Database connection pool initialised")

        try:
            from chat_app.episodic_memory import ensure_episode_tables
            await ensure_episode_tables(engine)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("Episodic memory table setup skipped: %s", exc)

    VECTOR_STORE = ensure_vector_store()
    logger.info("Vector store initialised")


async def _create_context():
    """Build a MessageHandlerContext (same shape as Chainlit app.py)."""
    from chat_app.message_context import MessageHandlerContext
    from chat_app.utils import import_optional_module
    from prompts import SYSTEM_PROMPT

    PROFILES_AVAILABLE, profiles_imports = import_optional_module(
        "profiles", ["detect_profile_from_query", "get_profile_prompt", "get_retrieval_strategy"],
    )
    FEEDBACK_GUARDRAILS_AVAILABLE, _ = import_optional_module(
        "feedback_guardrails", ["extract_feedback_guardrails", "extract_negative_feedback_warnings"],
    )

    LOCAL_DOCS_ROOT = _settings.paths.local_docs_root
    SPEC_STATIC_ROOT = _settings.paths.spec_static_root
    SPEC_SRC_ROOT = _settings.paths.spec_src_root

    def _noop_services():
        pass

    def _load_static_context():
        import json as _json
        ctx_file = Path(__file__).resolve().parent.parent / "context.json"
        if not ctx_file.exists():
            return []
        try:
            data = _json.loads(ctx_file.read_text(encoding="utf-8"))
            notes = []
            if desc := data.get("description"):
                notes.append(str(desc))
            for note in data.get("notes", []):
                if note:
                    notes.append(str(note))
            return notes
        except Exception as _exc:  # broad catch — resilience against all failures
            return []

    def _map_source_to_url(source: str) -> str:
        if not source or not source.startswith("file://"):
            return source
        file_path = source[7:]
        if file_path.startswith("/app/public/"):
            return f"/public/{file_path.split('/public/', 1)[-1]}"
        if file_path.startswith(DOCUMENTS_ROOT):
            return f"{_settings.paths.docs_base_url}/{file_path.split(DOCUMENTS_ROOT, 1)[-1]}"
        return source

    from llm_utils import LLM
    from langchain_core.output_parsers import StrOutputParser
    from langchain_core.prompts import ChatPromptTemplate

    prompt = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", "{input}")])
    chain = prompt | LLM | StrOutputParser()

    SEARCH_ROOTS = [LOCAL_DOCS_ROOT, _settings.paths.repo_docs_root, SPEC_SRC_ROOT, SPEC_STATIC_ROOT]

    ctx = MessageHandlerContext(
        vector_store=VECTOR_STORE,
        engine=engine,
        starter_options=[],
        search_roots=SEARCH_ROOTS,
        profiles_available=PROFILES_AVAILABLE,
        feedback_guardrails_available=FEEDBACK_GUARDRAILS_AVAILABLE,
        system_prompt=SYSTEM_PROMPT,
        chain=chain,
        llm=LLM,
        ensure_services_ready=_noop_services,
        load_static_context=_load_static_context,
        map_source_to_url=_map_source_to_url,
        SPEC_STATIC_ROOT=SPEC_STATIC_ROOT,
        LOCAL_DOCS_ROOT=LOCAL_DOCS_ROOT,
        SPEC_SRC_ROOT=SPEC_SRC_ROOT,
        settings=_settings,
    )

    # Configure the openai_compat module
    openai_compat.configure(
        context_factory=_create_context,
        chain=chain,
        llm=LLM,
        system_prompt=SYSTEM_PROMPT,
        model_name=_settings.ollama.model,
    )

    return ctx


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting ObsAI - Observability AI Assistant (Open WebUI mode)")
    await _init_backend()
    await _create_context()

    # Periodic session cleanup

    async def _session_cleanup_loop():
        while True:
            await asyncio.sleep(600)
            session_store.cleanup_expired()

    cleanup_task = asyncio.create_task(_session_cleanup_loop())

    # Background learning cycle (if enabled)
    learning_task = None
    try:
        if _settings.learning.enabled and _settings.learning.daily_learning_cycle:
            async def _learning_loop():
                await asyncio.sleep(300)  # Wait 5 min after startup
                while True:
                    try:
                        from chat_app.self_learning import run_learning_cycle
                        report = await run_learning_cycle(engine=engine, vector_store=VECTOR_STORE)
                        logger.info(
                            f"[LEARNING] Cycle: {report.qa_pairs_generated} QA, "
                            f"{report.answers_reassessed} reassessed, {report.facts_learned} facts"
                        )
                    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                        logger.warning(f"[LEARNING] Cycle failed: {exc}")
                    await asyncio.sleep(86400)

            learning_task = asyncio.create_task(_learning_loop())
            logger.info("[LEARNING] Daily learning cycle scheduled")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # Start idle worker for background self-improvement
    idle_worker = None
    try:
        from chat_app.idle_worker import get_idle_worker
        idle_worker = get_idle_worker()
        idle_worker.configure(engine=engine, vector_store=VECTOR_STORE)
        await idle_worker.start()
        logger.info("[IDLE-WORKER] Background self-improvement worker started")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[IDLE-WORKER] Could not start: %s", exc)

    logger.info("ObsAI API server ready — waiting for connections")
    yield
    cleanup_task.cancel()
    if learning_task:
        learning_task.cancel()
    if idle_worker:
        await idle_worker.stop()


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="ObsAI - Observability AI Assistant",
    description="Agentic AI for Splunk, Cribl, and Observability with Human-in-the-Loop",
    version=_settings.app.version,
    lifespan=lifespan,
)

# Mount health routes
try:
    from health_routes import router as health_router
    app.include_router(health_router)
    logger.info("Health routes mounted: /live, /ready, /metrics")
except ImportError as exc:
    logger.info("Health routes not available: %s", exc)

# Mount Admin API (main router + all sub-routers)
app.include_router(admin_router)
app.include_router(admin_public_router)
try:
    from chat_app.admin_api import (
        config_router, settings_router, tools_router, users_router, security_router,
        observability_router, skills_router, collections_router, learning_router,
        operations_router, dashboard_router, pages_router, pages_public_router,
        interactive_tools_public_router, interactive_tools_router,
    )
    from chat_app.admin_security_audit_routes import security_ext_router
    from chat_app.admin_security_infra_routes import security_infra_router
    from chat_app.admin_tools_routes_ext import tools_ext_router
    from chat_app.admin_tools_routes_ext2 import tools_ext2_router
    from chat_app.admin_config_helpers import config_ext_router
    from chat_app.admin_skills_orchestration_routes import skills_orch_router
    from chat_app.admin_skills_workflow_routes import workflow_templates_router
    from chat_app.admin_learning_ext_routes import learning_ext_router
    from chat_app.admin_learning_routes import learning_public_router
    from chat_app.admin_network_routes import network_router
    from chat_app.admin_upgrade_routes import upgrade_router
    from chat_app.admin_upgrade_platform_routes import upgrade_platform_router
    for _sub in [config_router, config_ext_router, settings_router, tools_router, tools_ext_router,
                 tools_ext2_router, users_router,
                 security_router, security_ext_router, security_infra_router,
                 observability_router, skills_router, skills_orch_router, workflow_templates_router,
                 collections_router, learning_router, learning_ext_router, operations_router,
                 dashboard_router, pages_router,
                 pages_public_router, interactive_tools_public_router, interactive_tools_router,
                 network_router, upgrade_router, upgrade_platform_router]:
        app.include_router(_sub)
except ImportError as _sub_exc:
    logger.debug("Sub-router mount skipped: %s", _sub_exc)
logger.info("Admin API mounted: /api/admin/*")

# Mount public feedback API (accessible to all users, no admin required)
try:
    app.include_router(learning_public_router)
    logger.info("Public feedback API mounted: /api/feedback/*")
except (NameError, ImportError):
    logger.debug("Public feedback router not available")

# Mount Human-in-the-Loop API
try:
    from chat_app.human_loop_api import router as human_loop_router
    app.include_router(human_loop_router)
    logger.info("Human-in-the-Loop API mounted: /api/hitl/*")
except ImportError:
    pass

# Mount Observability API
try:
    from chat_app.observability_api import router as obs_router
    app.include_router(obs_router)
    logger.info("Observability API mounted: /api/observability/*")
except ImportError:
    pass

# Mount OpenAI-compatible routes
app.include_router(openai_compat.router)

# Mount static file directories
_mounts = [
    ("/public/documents/specs", f"{DOCUMENTS_ROOT}/specs"),
    ("/public/documents/commands", f"{DOCUMENTS_ROOT}/commands"),
    ("/public/documents/repo", f"{DOCUMENTS_ROOT}/repo"),
    ("/public/documents/pdfs", f"{DOCUMENTS_ROOT}/pdfs"),
    ("/public/documents/cribl", f"{DOCUMENTS_ROOT}/cribl"),
    ("/public/documents/feedback", f"{DOCUMENTS_ROOT}/feedback"),
]
for mount_path, directory in _mounts:
    try:
        if Path(directory).is_dir():
            app.mount(mount_path, StaticFiles(directory=directory), name=mount_path.split("/")[-1])
    except (OSError, ValueError, KeyError, TypeError) as _exc:
        logger.debug("%s", _exc)  # was: pass


@app.get("/")
async def root():
    return {
        "name": "ObsAI - Observability AI Assistant",
        "version": _settings.app.version,
        "mode": "open-webui",
        "human_in_the_loop": True,
        "endpoints": {
            "chat": ["/v1/models", "/v1/chat/completions"],
            "health": ["/live", "/ready", "/metrics", "/api/health/stats", "/api/health/alerts"],
            "admin": [
                "/api/admin/settings", "/api/admin/features",
                "/api/admin/skills", "/api/admin/skills/discover",
                "/api/admin/dashboard", "/api/admin/activity",
                "/api/admin/approvals",
                "/api/admin/llm", "/api/admin/collections",
                "/api/admin/prompts", "/api/admin/agent-tasks",
                "/api/admin/feedback", "/api/admin/mcp",
                "/api/admin/marketplace", "/api/admin/uploads",
            ],
            "human_loop": ["/api/hitl/approvals", "/api/hitl/feedback", "/api/hitl/insights"],
            "system": [
                "/api/system/resources", "/api/system/healing",
                "/api/learn/trigger", "/api/learning/history",
            ],
        },
    }


@app.get("/api/health/stats")
async def health_stats():
    """Comprehensive health status including learning effectiveness."""
    try:
        from chat_app.health_monitor import get_comprehensive_health
        health = await get_comprehensive_health(engine)
        return {
            "overall": health.overall,
            "services": [{
                "name": s.name, "status": s.status,
                "latency_ms": s.latency_ms, "error": s.error,
                "details": s.details,
            } for s in health.services],
            "metrics": health.metrics,
            "learning": health.learning,
            "timestamp": health.timestamp,
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@app.get("/api/health/alerts")
async def health_alerts():
    """Check for active health alerts."""
    try:
        from chat_app.health_monitor import check_for_alerts
        alerts = await check_for_alerts(engine)
        return {
            "alerts": [{
                "severity": a.severity, "service": a.service,
                "message": a.message, "timestamp": a.timestamp,
            } for a in alerts],
            "count": len(alerts),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@app.get("/api/metrics/internal")
async def internal_metrics():
    """Internal assistant metrics in Prometheus text format."""
    try:
        from chat_app.health_monitor import get_internal_metrics
        return get_internal_metrics().to_prometheus()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return f"# error: {exc}\n"


@app.post("/api/learn/trigger")
async def trigger_learning():
    """Trigger a manual learning cycle."""
    try:
        from chat_app.self_learning import run_learning_cycle
        report = await run_learning_cycle(engine=engine, vector_store=VECTOR_STORE)
        return {
            "status": "completed",
            "qa_pairs_generated": report.qa_pairs_generated,
            "answers_reassessed": report.answers_reassessed,
            "facts_learned": report.facts_learned,
            "duration_seconds": report.duration_seconds,
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "error": str(exc)}


@app.post("/api/model/customize")
async def trigger_model_customization():
    """Trigger a manual model customization cycle."""
    try:
        from chat_app.self_learning import run_model_customization
        report = await run_model_customization(engine=engine, vector_store=VECTOR_STORE, force=True)
        return {
            "status": "completed" if report.model_created else "partial",
            "qa_pairs_exported": report.qa_pairs_exported,
            "training_file": report.training_file,
            "model_created": report.model_created,
            "model_name": report.model_name,
            "error": report.error or None,
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "error": str(exc)}


@app.get("/api/system/resources")
async def system_resources():
    """Get current system resource usage."""
    try:
        from chat_app.resource_manager import get_resource_snapshot, can_run_heavy_task
        snap = get_resource_snapshot()
        allowed, reason = can_run_heavy_task()
        return {
            "cpu_percent": snap.cpu_percent,
            "memory_percent": snap.memory_percent,
            "memory_available_mb": snap.memory_available_mb,
            "disk_percent": snap.disk_percent,
            "can_run_heavy_task": allowed,
            "reason": reason,
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@app.get("/api/system/healing")
async def healing_history():
    """Get auto-heal history and service health."""
    try:
        from chat_app.resource_manager import (
            get_healing_history, get_all_service_health,
        )
        return {
            "service_health": get_all_service_health(),
            "healing_events": get_healing_history(limit=20),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@app.post("/api/system/heal")
async def trigger_heal():
    """Trigger a manual auto-heal check."""
    try:
        from chat_app.resource_manager import auto_heal_check, get_all_service_health
        events = await auto_heal_check(engine=engine)
        return {
            "events_count": len(events),
            "successes": sum(1 for e in events if e.success),
            "failures": sum(1 for e in events if not e.success),
            "service_health": get_all_service_health(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@app.get("/api/idle-worker/status")
async def idle_worker_status():
    """Get idle worker status and improvement history."""
    try:
        from chat_app.idle_worker import get_idle_worker
        worker = get_idle_worker()
        return worker.get_status()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}


@app.get("/api/learning/history")
async def learning_history_endpoint():
    """Get learning history and trends."""
    try:
        from chat_app.resource_manager import get_learning_history, get_learning_trend
        return {
            "trend": get_learning_trend(),
            "history": get_learning_history(limit=20),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"error": str(exc)}
