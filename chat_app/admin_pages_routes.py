"""Admin sub-router: UI pages, Auth, Commands, Docs, Registry, and Prompts catalog.

Handles these endpoint groups:
- GET  /api/admin/page               — Redirect to V2 admin
- GET  /api/admin/v2{path}           — Serve React admin SPA
- GET  /api/admin/docs               — Docs HTML page
- GET  /api/admin/docs/data          — Structured documentation data
- GET  /api/admin/whoami             — Current user identity
- POST /api/admin/auth/oidc/callback — OIDC callback
- GET  /api/admin/commands           — Commands HTML page
- GET  /api/admin/tools/{tool_name}  — Redirect to commands
- GET  /api/admin/commands-data      — Slash commands data
- GET  /api/admin/registry           — Unified registry dump
- GET  /api/admin/sections-data      — Admin UI sections
- GET  /api/admin/capabilities-context — LLM capabilities context
- GET  /api/admin/spl-commands       — SPL command reference data

Mount with:
    from chat_app.admin_pages_routes import pages_router, pages_public_router
    router.include_router(pages_router)
    public_router.include_router(pages_public_router)  # or mount directly
"""

import json as _json
import logging
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from chat_app.auth_dependencies import get_authenticated_user, require_admin
from chat_app.settings import get_settings
from chat_app.admin_shared import (
    _csrf_check,
    _now_iso,
    _PROJECT_ROOT_ADMIN,
    _rate_limit,
    _track_audit_user,
)

logger = logging.getLogger(__name__)

# Authenticated admin router
pages_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-pages"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)

# Public router (rate-limited, CSRF-protected, no auth)
# Only UI serving, docs, whoami, and OIDC callback should be public.
# Registry/capabilities/sections data moved to authenticated router.
pages_public_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-pages-public"],
    dependencies=[Depends(_rate_limit), Depends(_csrf_check)],
)


# ---------------------------------------------------------------------------
# Admin UI page redirect
# ---------------------------------------------------------------------------

@pages_router.get("/page", include_in_schema=False)
async def admin_page():
    """Redirect legacy V1 admin page to V2 React admin."""
    from starlette.responses import RedirectResponse
    return RedirectResponse("/api/admin/v2/", status_code=302)


# ---------------------------------------------------------------------------
# React Admin SPA
# ---------------------------------------------------------------------------

@pages_public_router.get("/v2/{path:path}", include_in_schema=False)
@pages_public_router.get("/v2", include_in_schema=False)
async def admin_v2(path: str = ""):
    """Serve React admin SPA with client-side routing."""
    import mimetypes
    from fastapi.responses import FileResponse

    admin_ui_dirs = [
        Path("/app/admin-ui"),
        _PROJECT_ROOT_ADMIN / "frontend" / "dist",
    ]
    for admin_ui in admin_ui_dirs:
        if not admin_ui.is_dir():
            continue
        if path:
            static_file = (admin_ui / path).resolve()
            if not str(static_file).startswith(str(admin_ui.resolve())):
                return HTMLResponse("Forbidden", status_code=403)
            if static_file.is_file():
                media_type, _ = mimetypes.guess_type(str(static_file))
                return FileResponse(static_file, media_type=media_type)
        index = admin_ui / "index.html"
        if index.is_file():
            return FileResponse(index, media_type="text/html")

    return HTMLResponse(
        content="<html><body style='background:#111;color:#eee;font-family:sans-serif;padding:40px'>"
        "<h1>Admin UI v2 not built</h1>"
        "<p>Run <code>cd frontend && npm ci && npm run build</code> to build the React admin.</p>"
        "</body></html>",
        status_code=404,
    )


# ---------------------------------------------------------------------------
# Docs page
# ---------------------------------------------------------------------------

@pages_public_router.get("/docs", include_in_schema=False)
async def admin_docs():
    """Serve the documentation HTML page directly."""
    from fastapi.responses import FileResponse
    for base in [Path("/app/shared/public"), _PROJECT_ROOT_ADMIN / "public"]:
        f = base / "docs.html"
        if f.is_file():
            return FileResponse(f, media_type="text/html")
    return HTMLResponse("<html><body style='background:#111;color:#eee;padding:40px'><h1>docs.html not found</h1></body></html>", status_code=404)


@pages_router.get("/docs/data", summary="Structured documentation data for the admin UI")
async def get_docs_data():
    """Return structured documentation sections for the React DocsPage."""
    settings = get_settings()

    # Collect API endpoint info — import the main router lazily to avoid circular imports
    api_endpoints = []
    try:
        from chat_app.admin_api import router as main_router
        for route in main_router.routes:
            if hasattr(route, "methods") and hasattr(route, "path"):
                methods = route.methods - {"HEAD"} if route.methods else set()
                if not methods:
                    continue
                api_endpoints.append({
                    "method": sorted(methods)[0],
                    "path": route.path,
                    "summary": getattr(route, "summary", "") or getattr(route, "name", ""),
                })
        api_endpoints.sort(key=lambda x: x["path"])
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[ADMIN] Failed to collect API endpoints for docs: %s", exc)

    return {
        "system": {
            "version": settings.app.version,
            "containers": [
                {"name": "PostgreSQL", "desc": "User sessions, chat history, feedback storage", "port": 5432},
                {"name": "ChromaDB", "desc": "Vector store for document embeddings and RAG retrieval", "port": 8001},
                {"name": "Ollama", "desc": "Local LLM inference (embedding + chat completion)", "port": 11430},
                {"name": "Redis", "desc": "Caching layer for query results and session data", "port": 6379},
                {"name": "Search Optimizer", "desc": "Background service for search quality optimization", "port": 9005},
                {"name": "App (Chainlit)", "desc": "Main application — chat UI, admin API, RAG pipeline", "port": 8090},
                {"name": "Prometheus", "desc": "Metrics collection and alerting", "port": 9090},
                {"name": "Grafana", "desc": "Monitoring dashboards and visualization", "port": 3100},
                {"name": "Nginx Gateway", "desc": "Single-port reverse proxy — all traffic routes through here", "port": 8000},
            ],
            "architecture": [
                "Single-port nginx gateway — all services accessed via port 8000",
                "Bridge network (chainlit_net) — containers communicate by name",
                "Persistent volumes for PostgreSQL, ChromaDB, Ollama models, and Redis data",
                "RAG pipeline: Query → Intent Classification → Vector Retrieval → LLM Generation",
                "Self-learning: Q&A generation → Fact extraction → Prompt overlay → Model customization",
            ],
        },
        "config_sections": [
            {"section": "llm", "title": "LLM Settings", "desc": "Model name, temperature, token limits, timeout", "restart": "hot_reload"},
            {"section": "retrieval", "title": "Retrieval", "desc": "Top-K, similarity threshold, reranking, collection weights", "restart": "hot_reload"},
            {"section": "prompts", "title": "Prompts", "desc": "System prompt, persona, response format instructions", "restart": "hot_reload"},
            {"section": "ingestion", "title": "Ingestion", "desc": "Document sources, file patterns, scan directories", "restart": "hot_reload"},
            {"section": "chunking", "title": "Chunking", "desc": "Chunk size, overlap, embedding model, stanza-aware parsing", "restart": "hot_reload"},
            {"section": "database", "title": "Database", "desc": "PostgreSQL connection string, pool settings", "restart": "full_restart"},
            {"section": "security", "title": "Security", "desc": "Rate limiting, CORS, authentication settings", "restart": "hot_reload"},
            {"section": "features", "title": "Features", "desc": "Feature flags for optional capabilities", "restart": "hot_reload"},
            {"section": "orchestration", "title": "Orchestration", "desc": "Multi-agent strategy, governance model, resource limits", "restart": "hot_reload"},
            {"section": "knowledge_graph", "title": "Knowledge Graph", "desc": "Entity extraction, relationship mapping, graph rebuild", "restart": "hot_reload"},
        ],
        "slash_commands": [
            {"cmd": "/help", "desc": "Show available commands and usage guide"},
            {"cmd": "/search <query>", "desc": "Search across all vector store collections"},
            {"cmd": "/spec <conf_type>", "desc": "Look up .spec file documentation for a Splunk config type"},
            {"cmd": "/config [section]", "desc": "View or modify configuration settings"},
            {"cmd": "/stats", "desc": "Show system statistics and usage metrics"},
            {"cmd": "/profile [name]", "desc": "View or switch LLM profiles"},
            {"cmd": "/health", "desc": "Check health status of all services"},
            {"cmd": "/build-config", "desc": "Generate Splunk configuration from natural language"},
            {"cmd": "/splunk <action>", "desc": "Splunk-specific operations (health, deploy status)"},
            {"cmd": "/explain <SPL>", "desc": "Explain a Splunk search command or query"},
            {"cmd": "/learn", "desc": "Trigger self-learning pipeline cycle"},
            {"cmd": "/ingest", "desc": "Trigger document re-ingestion"},
            {"cmd": "/tutorial [topic]", "desc": "Interactive guided tutorials"},
            {"cmd": "/version", "desc": "Show version and update information"},
            {"cmd": "/admin", "desc": "Open the admin configuration console"},
            {"cmd": "/clear", "desc": "Clear chat history"},
        ],
        "deployment_tiers": [
            {"tier": "_global", "target": "All Splunk Enterprise instances (HFs, Indexers, Search Heads)"},
            {"tier": "deployment-apps", "target": "Heavy Forwarders and Universal Forwarders via Deployment Server"},
            {"tier": "manager-apps", "target": "Indexers via Cluster Manager (cluster bundle push)"},
            {"tier": "cluster-{name}", "target": "Specific Search Head Cluster identified by name"},
            {"tier": "soc-dev", "target": "SOC team development environment"},
        ],
        "api_endpoints": api_endpoints[:100],
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Authentication info
# ---------------------------------------------------------------------------

@pages_public_router.get("/whoami", summary="Get current user identity")
async def whoami(user: dict = Depends(get_authenticated_user)):
    """Return the current user's identity and role (auth-aware but accessible)."""
    return {
        "username": user["identifier"],
        "role": user.get("metadata", {}).get("role", "USER"),
        "authenticated": user["identifier"] != "anonymous",
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# OIDC Callback
# ---------------------------------------------------------------------------

class _OIDCCallbackRequest(BaseModel):
    code: str = Field(..., description="Authorization code from OIDC provider")
    redirect_uri: str = Field("", description="Redirect URI used in the authorization request")
    provider_name: str = Field("oidc", description="Name of the OIDC provider")
    state: str = Field("", description="OIDC state parameter (CSRF protection)")


@pages_public_router.post("/auth/oidc/callback", summary="Handle OIDC callback")
async def oidc_callback(body: _OIDCCallbackRequest, request: Request = None):
    """Exchange OIDC authorization code for tokens and return user identity.

    SECURITY: Validates state parameter to prevent CSRF/state-fixation attacks.
    """
    from chat_app.auth_providers import get_provider, init_auth_providers, get_all_providers
    if not get_all_providers():
        init_auth_providers()
    provider = get_provider(body.provider_name)
    if not provider:
        raise HTTPException(status_code=404, detail=f"Auth provider '{body.provider_name}' not found")
    if provider.provider_type != "oidc":
        raise HTTPException(status_code=400, detail=f"Provider '{body.provider_name}' is not an OIDC provider")

    # SECURITY: State is MANDATORY (fail-closed CSRF protection)
    if not body.state:
        raise HTTPException(status_code=400, detail="Missing OIDC state parameter (CSRF protection requires state)")
    expected_nonce = provider.validate_state(body.state)
    if expected_nonce is None:
        raise HTTPException(status_code=403, detail="Invalid or expired OIDC state parameter (possible CSRF)")

    redirect_uri = body.redirect_uri
    if not redirect_uri and request:
        redirect_uri = str(request.base_url).rstrip("/") + "/api/admin/auth/oidc/callback"

    identity = await provider.authenticate({
        "code": body.code,
        "redirect_uri": redirect_uri,
        "expected_nonce": expected_nonce,  # Pass nonce for id_token verification
    })
    if not identity:
        raise HTTPException(status_code=401, detail="OIDC authentication failed")

    return {
        "user_id": identity.user_id,
        "email": identity.email,
        "display_name": identity.display_name,
        "roles": identity.roles,
        "groups": identity.groups,
        "provider": identity.provider,
        "access_token": identity.access_token,
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Commands page
# ---------------------------------------------------------------------------

@pages_public_router.get("/commands", include_in_schema=False)
async def commands_page(redirect: str = ""):
    """Serve interactive commands HTML directly (full-page, no iframe)."""
    if redirect == "v2":
        from starlette.responses import RedirectResponse
        return RedirectResponse("/api/admin/v2/commands", status_code=302)
    import pathlib
    for candidate in [
        pathlib.Path("/app/chat_app/public/commands.html"),
        pathlib.Path("/app/public/commands.html"),
        pathlib.Path(__file__).resolve().parent / "public" / "commands.html",
        pathlib.Path(__file__).resolve().parent.parent / "public" / "commands.html",
    ]:
        if candidate.is_file():
            return HTMLResponse(
                candidate.read_text(encoding="utf-8"),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
    return HTMLResponse("<h1>commands.html not found</h1>", status_code=404)


@pages_public_router.get("/tools/{tool_name}", include_in_schema=False)
async def tool_page_redirect(tool_name: str):
    """Redirect /tools/<name> to V2 commands page."""
    from starlette.responses import RedirectResponse
    return RedirectResponse("/api/admin/v2/commands", status_code=302)


# Commands data on public router — safe to expose without auth (read-only metadata)
@pages_public_router.get("/commands-data", summary="Commands and tools data")
async def commands_data():
    """Return slash commands and tool metadata. Public endpoint — no auth required."""
    from chat_app.registry import get_commands_for_api
    commands = get_commands_for_api()
    return {"status": "ok", "commands": commands, "total": len(commands)}


# Registry/sections/capabilities moved to authenticated router (security hardening)
@pages_router.get("/registry", summary="Unified registry dump")
async def registry_dump():
    """Return full registry: intents, routing tags, commands, sections, validation."""
    from chat_app.registry import get_registry_dump
    return get_registry_dump()


@pages_router.get("/sections-data", summary="Admin UI sections for sidebar")
async def sections_data():
    """Return admin UI sidebar sections grouped by category."""
    from chat_app.registry import get_sections_for_api
    groups = get_sections_for_api()
    total = sum(len(g["items"]) for g in groups)
    return {"status": "ok", "groups": groups, "total": total}


@pages_router.get("/capabilities-context", summary="LLM capabilities context")
async def capabilities_context():
    """Return the capabilities context string injected into LLM prompts."""
    from chat_app.registry import build_capabilities_context
    ctx = build_capabilities_context()
    return {"status": "ok", "context": ctx, "length": len(ctx)}


# ---------------------------------------------------------------------------
# SPL Command Reference
# ---------------------------------------------------------------------------

# Public endpoint — SPL command reference is read-only documentation metadata
@pages_public_router.get("/spl-commands", summary="SPL command reference data")
async def spl_commands_data():
    """Return SPL command metadata from documents/commands/ directory."""
    spl_cmds = []
    for base in [Path("/app/shared/public/documents/commands"), _PROJECT_ROOT_ADMIN / "documents" / "commands"]:
        meta_file = base / ".spl_docs_metadata.json"
        if not meta_file.is_file():
            continue
        try:
            meta = _json.loads(meta_file.read_text())
            for cmd_name, cmd_info in meta.get("commands", {}).items():
                md_file = base / f"spl_cmd_{cmd_name}.md"
                description = ""
                if md_file.is_file():
                    try:
                        text = md_file.read_text(errors="ignore")
                        in_frontmatter = False
                        past_heading = False
                        for line in text.split("\n"):
                            stripped = line.strip()
                            if stripped == "---":
                                in_frontmatter = not in_frontmatter
                                continue
                            if in_frontmatter:
                                continue
                            if stripped.startswith("#"):
                                past_heading = True
                                continue
                            if past_heading and stripped:
                                description = stripped[:200]
                                break
                    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                        logger.debug("[%s] %%s", "admin_pages_routes.py", _exc)
                if not description:
                    description = cmd_info.get("title", cmd_name)
                spl_cmds.append({
                    "name": cmd_name,
                    "description": description,
                    "url": cmd_info.get("url", ""),
                })
            break
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[ADMIN] Failed to parse SPL command metadata: %s", exc)
            continue
    spl_cmds.sort(key=lambda c: c["name"])
    return {"status": "ok", "commands": spl_cmds, "total": len(spl_cmds)}
