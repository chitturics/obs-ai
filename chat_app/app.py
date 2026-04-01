"""
Enterprise Splunk Configuration Assistant with RAG.

Professional chatbot for Splunk administrators with:
- Local LLM via Ollama
- PostgreSQL: Thread persistence and interaction tracking
- ChromaDB: Shared knowledge base with feedback learning
- Intelligent config file lookup and validation
- Redis caching for performance
- Circuit breakers and retry logic for resilience
- Health monitoring and metrics
"""
import asyncio
import os
from pathlib import Path
from typing import List, Optional, Dict, Any

import chainlit as cl
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from sqlalchemy.engine.url import make_url
from chat_app.settings import get_settings
from chat_app.utils import import_optional_module
from helper import current_username
from search_opt_client import call_robust_analyzer
from feedback_logger import (
    init_storage,
)
from feedback_handler import on_feedback
from health import get_health_status
from logging_utils import setup_logging
from config_validator import log_startup_config
from mcp_utils import load_splunk_mcp_tools
from mcp_registry import list_servers as list_mcp_servers
import mcp_handler  # noqa: F401 — registers @cl.on_mcp_connect/disconnect
from prompts import SYSTEM_PROMPT
from chat_app.message_context import MessageHandlerContext
from vectorstore import (
    ensure_vector_store,
)

# New extracted modules
from org_data_loader import initialize_org_data
from chat_app import on_message
from chat_lifecycle import on_chat_start, on_chat_end, on_chat_resume, on_settings_update, on_stop
from action_handler import on_followup, on_optimize_query, on_ignore_optimization
from llm_utils import LLM
from chat_app.tool_executor import bind_tools_to_llm
from chat_app.lifecycle_context import ChatLifecycleContext
from chat_app.storage_client import get_storage_client
from chat_app.data_layer import LenientSQLAlchemyDataLayer

# Optional modules
PROFILES_AVAILABLE, profiles_imports = import_optional_module('profiles', ['detect_profile_from_query', 'get_profile_prompt', 'get_retrieval_strategy'])
FEEDBACK_GUARDRAILS_AVAILABLE, feedback_guardrails_imports = import_optional_module('feedback_guardrails', ['extract_feedback_guardrails', 'extract_negative_feedback_warnings'])

# ------------------------------------------------------------------
# Configuration (centralized via pydantic-settings)
# ------------------------------------------------------------------
_settings = get_settings()

DB_CONNINFO_ASYNC = _settings.database.url
if not DB_CONNINFO_ASYNC:
    raise ValueError("Database URL is not configured. Please set DATABASE_URL in your .env file.")

try:
    _ = make_url(DB_CONNINFO_ASYNC)
except ValueError as e:
    raise ValueError(f"Invalid DB URL configured: {e}")

LOG_LEVEL = _settings.app.log_level.upper()
logger = setup_logging(app_name="splunk_assistant", level=LOG_LEVEL)
log_startup_config()

# Registry validation — verify cross-component references at startup
try:
    from chat_app.registry import validate_all as _validate_registry  # noqa: F401
    _reg_results = _validate_registry()
    _reg_issues = sum(len(v) for v in _reg_results.values())
    if _reg_issues:
        logger.warning("[STARTUP] Registry validation: %d issue(s)", _reg_issues)
    else:
        logger.info("[STARTUP] Registry validation: all checks passed")
except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _reg_exc:
    logger.warning("[STARTUP] Registry validation skipped: %s", _reg_exc)

# Graceful shutdown handler — flush caches, close connections, persist metrics
# Extracted to app_lifecycle.py; registered here so it can access _shutdown_event.
_shutdown_event = None  # Set by ensure_services_ready for learning loop cancellation

from chat_app.app_lifecycle import register_shutdown_handler as _register_shutdown
_register_shutdown(shutdown_event_getter=lambda: _shutdown_event)

# Initialize OpenTelemetry distributed tracing (replaces Langfuse)
try:
    from chat_app.otel_tracing import init_otel  # noqa: F401
    _otel_ok = init_otel(
        service_name=_settings.otel.service_name,
        endpoint=_settings.otel.endpoint,
        max_spans=_settings.otel.max_spans,
    )
    if _otel_ok:
        logger.info("[STARTUP] OpenTelemetry tracing active")
    else:
        logger.info("[STARTUP] OpenTelemetry tracing: no-op mode (SDK not installed or disabled)")
except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _otel_err:
    logger.warning("[STARTUP] OpenTelemetry init skipped: %s", _otel_err)

# Initialize Prometheus app info
try:
    from prometheus_metrics import set_app_info  # noqa: F401
    set_app_info(
        version=_settings.app.version,
        environment=_settings.app.environment,
        model=_settings.ollama.model,
    )
except (ImportError, ModuleNotFoundError, OSError, ValueError, AttributeError):
    pass  # optional module


# Mount health/metrics routes, security middleware, and admin API EARLY (before catch-all).
# Extracted to app_routes.py to keep this file under 600 lines.
from chat_app.app_routes import mount_all_routes as _mount_all_routes
_mount_all_routes(_settings)

DOCUMENTS_ROOT = _settings.paths.documents_root
DOCS_BASE_URL = _settings.paths.docs_base_url
LOCAL_DOCS_ROOT = _settings.paths.local_docs_root
REPO_DOCS_ROOT = _settings.paths.repo_docs_root
SPEC_SRC_ROOT = _settings.paths.spec_src_root
SPEC_INGEST_ROOT = _settings.paths.spec_ingest_root
SPEC_STATIC_ROOT = _settings.paths.spec_static_root
SPL_DOCS_ROOT = _settings.paths.spl_docs_root
ORG_REPO_ROOT = _settings.paths.org_repo_root
ENABLE_AUTHENTICATION = _settings.auth.enabled

SEARCH_ROOTS = [LOCAL_DOCS_ROOT, REPO_DOCS_ROOT, SPEC_SRC_ROOT, SPEC_STATIC_ROOT]

# Starter options and chat profile definitions extracted to app_config.py
from chat_app.app_config import STARTER_OPTIONS, build_chat_profiles  # noqa: F401 — re-exported

# Globals
engine = None
VECTOR_STORE = None
MCP_TOOLS: list = []
try:
    from chat_app.settings import get_settings as _get_settings  # noqa: F401
    if _get_settings().mcp_gateway.enabled:
        MCP_TOOLS = load_splunk_mcp_tools()
    else:
        logger.info("[MCP] Gateway disabled in settings — skipping tool load")
except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
    logger.warning("[MCP] Could not check settings, loading tools anyway: %s", _exc)
    MCP_TOOLS = load_splunk_mcp_tools()


# ------------------------------------------------------------------
# Core Utilities
# ------------------------------------------------------------------
async def ensure_services_ready():
    """Initialize database and vector store with improved connection pooling."""
    global engine, VECTOR_STORE
    if engine is None:
        from sqlalchemy.ext.asyncio import create_async_engine
        engine = create_async_engine(
            DB_CONNINFO_ASYNC,
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=1800,
            echo=False,
            connect_args={
                "server_settings": {"application_name": "splunk_assistant"},
                "command_timeout": 60,
                "timeout": 10,
            }
        )
        await init_storage(DB_CONNINFO_ASYNC, existing_engine=engine)
        logger.info("Database connection pool initialized")

        # Ensure episodic memory tables exist
        try:
            from chat_app.episodic_memory import ensure_episode_tables
            await ensure_episode_tables(engine)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning(f"Episodic memory table setup skipped: {exc}")

        # Start background learning cycle (if enabled)
        try:
            from chat_app.settings import get_settings as _get_settings
            _learn_settings = _get_settings().learning
            if _learn_settings.enabled and _learn_settings.daily_learning_cycle:
                global _shutdown_event
                _shutdown_event = asyncio.Event()

                async def _background_learning_loop():
                    """Run learning cycles on a schedule with graceful shutdown."""
                    try:
                        await asyncio.wait_for(_shutdown_event.wait(), timeout=900)
                        return  # Shutdown requested during initial wait
                    except asyncio.TimeoutError:
                        pass  # Normal — 15-min delay elapsed, Ollama free for users
                    while not _shutdown_event.is_set():
                        try:
                            from chat_app.self_learning import run_learning_cycle
                            report = await run_learning_cycle(engine=engine, vector_store=VECTOR_STORE)
                            logger.info(
                                "[LEARNING] Cycle complete: %d QA, %d reassessed, %d facts in %.1fs",
                                report.qa_pairs_generated, report.answers_reassessed,
                                report.facts_learned, report.duration_seconds,
                            )
                        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                            logger.warning("[LEARNING] Background cycle failed: %s", exc)
                        try:
                            await asyncio.wait_for(_shutdown_event.wait(), timeout=86400)
                            return  # Shutdown requested
                        except asyncio.TimeoutError:
                            pass  # Normal — daily interval elapsed

                asyncio.get_running_loop().create_task(_background_learning_loop())
                logger.info("[LEARNING] Background daily learning cycle scheduled")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[LEARNING] Background scheduler skipped: %s", exc)

    if VECTOR_STORE is None:
        VECTOR_STORE = ensure_vector_store()
        logger.info("Vector store initialized")

    # Start execution journal background writer
    try:
        from chat_app.execution_journal import get_journal
        _journal = get_journal()
        asyncio.get_running_loop().create_task(_journal.start())
        logger.info("[JOURNAL] Execution journal started")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[JOURNAL] Journal start skipped: %s", exc)

    # Start idle worker DELAYED — give Ollama 10 min to serve user queries first
    try:
        from chat_app.idle_worker import get_idle_worker
        _idle_worker = get_idle_worker()
        _idle_worker.configure(engine=engine, vector_store=VECTOR_STORE)

        async def _delayed_idle_start():
            await asyncio.sleep(600)  # 10 min delay — let Ollama serve users first
            await _idle_worker.start()

        asyncio.get_running_loop().create_task(_delayed_idle_start())
        logger.info("[IDLE-WORKER] Scheduled to start in 10 minutes")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[IDLE-WORKER] Idle worker start skipped: %s", exc)

    # Run startup warmup (background: pre-warm caches, verify services)
    try:
        from chat_app.startup_warmup import run_startup_warmup, is_warmup_complete
        if not is_warmup_complete():
            asyncio.get_running_loop().create_task(run_startup_warmup(
                vector_store=VECTOR_STORE, engine=engine,
            ))
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[WARMUP] Startup warmup skipped: %s", exc)


def map_source_to_url(source: str) -> str:
    """Maps a file path to a public URL."""
    from chat_app.app_config import map_source_to_url as _map  # noqa: F401
    return _map(source, DOCUMENTS_ROOT, DOCS_BASE_URL)


def load_static_context() -> List[str]:
    """Load static context from context.json."""
    from chat_app.app_config import load_static_context as _load  # noqa: F401
    base_dir = str(Path(__file__).resolve().parent.parent)
    return _load(base_dir)


# ------------------------------------------------------------------
# MCP Session Management
# ------------------------------------------------------------------
async def bootstrap_mcp_session():
    """Load admin MCP registry and any saved user tokens into the session."""
    from feedback_logger import load_mcp_token  # noqa: F401
    username = current_username()
    servers = list_mcp_servers()
    cl.user_session.set("mcp_servers", servers)

    token_cache: Dict[str, Dict[str, Any]] = {}
    if engine is None:
        cl.user_session.set("mcp_tokens", token_cache)
        return

    for server in servers:
        try:
            existing = await load_mcp_token(engine, username, server["name"])
            if existing:
                token_cache[server["name"]] = {
                    "auth_scheme": existing.get("auth_scheme", "none"),
                    "token": existing.get("access_token"),
                    "expires_at": existing.get("expires_at"),
                }
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning(f"[MCP] Failed to load token for {server['name']}: {exc}")

    cl.user_session.set("mcp_tokens", token_cache)





@cl.data_layer
def get_data_layer():
    storage_client = get_storage_client()
    try:
        return LenientSQLAlchemyDataLayer(
            conninfo=DB_CONNINFO_ASYNC, storage_provider=storage_client
        )
    except TypeError:
        return LenientSQLAlchemyDataLayer(conninfo=DB_CONNINFO_ASYNC)


# ------------------------------------------------------------------
# Chat Starters & Profiles
# ------------------------------------------------------------------
@cl.set_starters
async def set_starters():
    return [cl.Starter(label=opt["label"], message=opt["message"]) for opt in STARTER_OPTIONS]


@cl.set_chat_profiles
async def chat_profiles():
    return build_chat_profiles()


# ------------------------------------------------------------------
# Authentication
# ------------------------------------------------------------------
if ENABLE_AUTHENTICATION:
    @cl.password_auth_callback
    def auth_callback(username: str, password: str) -> Optional[cl.User]:
        # Admin user (always available)
        if username == _settings.auth.admin_user and password == _settings.auth.admin_password:
            return cl.User(identifier=username, metadata={"role": "ADMIN", "provider": "credentials"})
        # Additional users from AUTH_USERS env var (format: "user1:pass1,user2:pass2")
        extra_users = os.getenv("AUTH_USERS", "")
        if extra_users:
            for pair in extra_users.split(","):
                parts = pair.strip().split(":", 1)
                if len(parts) == 2 and parts[0] == username and parts[1] == password:
                    return cl.User(
                        identifier=username,
                        metadata={"role": "USER", "provider": "credentials"},
                    )
        # Check database-stored users (created via admin API)
        try:
            import hashlib
            from sqlalchemy import text, create_engine as _sync_create
            _db_url = _settings.database.url.replace("+asyncpg", "").replace("postgresql://", "postgresql+psycopg2://")
            if _db_url:
                _eng = _sync_create(_db_url, pool_pre_ping=True)
                with _eng.connect() as conn:
                    row = conn.execute(text(
                        'SELECT "metadata" FROM users WHERE "identifier" = :u'
                    ), {"u": username}).fetchone()
                    if row:
                        import json as _json
                        meta = row[0] if isinstance(row[0], dict) else _json.loads(row[0]) if row[0] else {}
                        stored_hash = meta.get("password_hash", "")
                        if stored_hash:
                            import bcrypt as _bcrypt
                            # Support both bcrypt ($2b$) and legacy SHA-256 hashes
                            if stored_hash.startswith("$2"):
                                _pw_ok = _bcrypt.checkpw(password.encode(), stored_hash.encode())
                            else:
                                salt = meta.get("salt", "")
                                _pw_ok = salt and hashlib.sha256((password + salt).encode()).hexdigest() == stored_hash
                            if _pw_ok:
                                return cl.User(
                                    identifier=username,
                                    metadata={"role": meta.get("role", "USER"), "provider": "database"},
                                )
                _eng.dispose()
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _auth_exc:
            logger.debug("DB user auth check failed: %s", _auth_exc)
        return None
    _extra_count = len([p for p in os.getenv("AUTH_USERS", "").split(",") if ":" in p])
    logger.info("Authentication ENABLED (admin + %d extra users)", _extra_count)
else:
    logger.info("Authentication DISABLED - anonymous access (set ENABLE_AUTHENTICATION=true for session history)")


# ------------------------------------------------------------------
# LLM Chain
# ------------------------------------------------------------------
prompt = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", "{input}")])
chain = prompt | LLM | StrOutputParser()

# Bind MCP tools to LLM for tool-calling capabilities (non-blocking)
if MCP_TOOLS and LLM:
    TOOL_BOUND_LLM = bind_tools_to_llm(LLM, MCP_TOOLS)
else:
    TOOL_BOUND_LLM = None


# ------------------------------------------------------------------
# Action & MCP Handlers
# ------------------------------------------------------------------
async def create_message_handler_context():
    """Create a new MessageHandlerContext."""
    await ensure_services_ready()

    return MessageHandlerContext(
        vector_store=VECTOR_STORE,
        engine=engine,
        starter_options=STARTER_OPTIONS,
        search_roots=SEARCH_ROOTS,
        profiles_available=PROFILES_AVAILABLE,
        feedback_guardrails_available=FEEDBACK_GUARDRAILS_AVAILABLE,
        system_prompt=SYSTEM_PROMPT,
        chain=chain,
        llm=LLM,
        ensure_services_ready=ensure_services_ready,
        load_static_context=load_static_context,
        map_source_to_url=map_source_to_url,
        SPEC_STATIC_ROOT=SPEC_STATIC_ROOT,
        LOCAL_DOCS_ROOT=LOCAL_DOCS_ROOT,
        SPEC_SRC_ROOT=SPEC_SRC_ROOT,
        settings=_settings,
        mcp_tools=MCP_TOOLS,
    )


@cl.action_callback("followup")
async def _(action: cl.Action):
    context = await create_message_handler_context()
    await on_followup(
        action,
        on_message,
        context
    )

@cl.action_callback("optimize_query")
async def _(action: cl.Action):
    await on_optimize_query(action, call_robust_analyzer)

@cl.action_callback("ignore_optimization")
async def _(action: cl.Action):
    await on_ignore_optimization(action)





_static_mounts_done = False

def setup_static_file_serving():
    """Mount static file directories once (each mount is independent)."""
    global _static_mounts_done
    if _static_mounts_done:
        return
    _static_mounts_done = True

    try:
        from fastapi.staticfiles import StaticFiles
        from chainlit.server import app as fastapi_app
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"Cannot set up static file serving: {exc}")
        return

    # Health routes already mounted at module-import time (lines ~97-105).
    # Do NOT re-mount them here.

    static_mounts = [
        ("/public/documents/specs", f"{DOCUMENTS_ROOT}/specs", "specs"),
        ("/public/documents/commands", f"{DOCUMENTS_ROOT}/commands", "commands"),
        ("/public/documents/repo", f"{DOCUMENTS_ROOT}/repo", "repo"),
        ("/public/documents/pdfs", f"{DOCUMENTS_ROOT}/pdfs", "pdfs"),
        ("/public/documents/cribl", f"{DOCUMENTS_ROOT}/cribl", "cribl"),
        ("/public/documents/feedback", f"{DOCUMENTS_ROOT}/feedback", "feedback_docs"),
        ("/public/blobs", _settings.paths.blob_storage_path, "blobs"),
    ]

    for mount_path, directory, name in static_mounts:
        try:
            dir_path = Path(directory)
            if not dir_path.exists():
                logger.debug(f"Skipping static mount {mount_path}: {directory} not found")
                continue
            if not dir_path.is_dir():
                logger.debug(f"Skipping static mount {mount_path}: {directory} is not a directory")
                continue
            if not os.access(directory, os.R_OK | os.X_OK):
                logger.warning(f"Skipping {mount_path}: no read permission on {directory}")
                continue
            fastapi_app.mount(mount_path, StaticFiles(directory=directory), name=name)
            logger.info(f"Mounted {directory} at {mount_path}")
        except PermissionError:
            logger.warning(f"Permission denied mounting {mount_path} -> {directory}. "
                           f"Fix: chmod -R a+rX {DOCUMENTS_ROOT}")
        except (OSError, ValueError) as exc:
            logger.warning(f"Failed to mount {mount_path} -> {directory}: {exc}")

# ------------------------------------------------------------------
# Chat Lifecycle
# ------------------------------------------------------------------
@cl.on_chat_start
async def _():
    setup_static_file_serving()
    context = ChatLifecycleContext(
        ensure_services_ready=ensure_services_ready,
        bootstrap_mcp_session=bootstrap_mcp_session,
        initialize_org_data=initialize_org_data,
    )
    await on_chat_start(context)

@cl.on_settings_update
async def _(settings):
    await on_settings_update(settings)

@cl.on_stop
def _():
    on_stop()

@cl.on_chat_end
def _():
    on_chat_end()

@cl.on_chat_resume
async def _(thread):
    await on_chat_resume(thread, ensure_services_ready)


async def perform_health_check():
    """Perform health check and return status."""
    try:
        await ensure_services_ready()
        return await get_health_status(engine)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        return {"status": "unhealthy", "error": str(e)}


# ------------------------------------------------------------------
# Main Message Handler
# ------------------------------------------------------------------
@cl.on_message
async def _(message: cl.Message):
    import asyncio as _aio
    logger.info(f"[on_message] Entry: '{(message.content or '')[:80]}'")
    try:
        # Timeout only on context creation (DB/vector init) — safe because
        # this function does NOT use Chainlit context (cl.Message, cl.user_session).
        # on_message() is called WITHOUT wait_for to preserve Chainlit's contextvars.
        try:
            context = await _aio.wait_for(create_message_handler_context(), timeout=15)
        except _aio.TimeoutError:
            logger.error("Context creation timed out — database or vector store may be unreachable")
            await cl.Message(content="Services are still starting up. Please try again in a moment.").send()
            return

        logger.info("[on_message] Context created, calling on_message()")
        await on_message(message, context)
        logger.info("[on_message] Completed successfully")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.error(f"Failed to handle message: {e}", exc_info=True)
        await cl.Message(content="Sorry, I encountered an error while processing your request. Please try again later.").send()



# ------------------------------------------------------------------
# Feedback Handler
# ------------------------------------------------------------------
try:
    from chainlit.types import Feedback, ChatProfile  # noqa: F401
    from chainlit.data.storage_clients.base import BaseStorageClient  # noqa: F401
except ImportError:
    Feedback = None

if Feedback is not None:
    @cl.on_feedback
    async def _(feedback: "Feedback"):
        await on_feedback(feedback, engine, VECTOR_STORE, LLM, DOCS_BASE_URL)



