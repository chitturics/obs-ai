"""Admin sub-router: Knowledge Graph, Splunkbase, Guardrails, and Archival Memory endpoints.

Extracted from admin_learning_routes.py to keep file sizes manageable.
All routes use the same prefix/tags/dependencies as learning_router.

Endpoints:
- GET  /api/admin/knowledge-graph/stats           — Knowledge graph statistics
- GET  /api/admin/knowledge-graph/entities        — Browse entities by type
- GET  /api/admin/knowledge-graph/entity/{id}     — Get entity details
- POST /api/admin/knowledge-graph/rebuild         — Rebuild the knowledge graph
- GET  /api/admin/knowledge-graph/graph           — Graph visualization data
- GET  /api/admin/knowledge-graph/query           — Query the knowledge graph
- GET  /api/admin/splunkbase/catalog              — Splunkbase catalog summary
- GET  /api/admin/splunkbase/apps                 — All Splunkbase apps
- GET  /api/admin/splunkbase/outdated             — Outdated Splunk apps
- POST /api/admin/splunkbase/refresh              — Trigger catalog refresh
- POST /api/admin/splunkbase/compare              — Compare uploaded app list
- GET  /api/admin/guardrails/stats                — Guardrail event statistics
- POST /api/admin/guardrails/test                 — Test guardrails on sample text
- GET  /api/admin/memory/archival/stats           — Archival memory statistics
- GET  /api/admin/memory/archival/search          — Search archival memory
- POST /api/admin/memory/archival/store           — Store a memory note
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from chat_app.auth_dependencies import require_admin
from chat_app.admin_shared import (
    _append_audit,
    _csrf_check,
    _now_iso,
    _rate_limit,
    _safe_error,
    _track_audit_user,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Router — same prefix/tags/dependencies as learning_router so routes merge
# ---------------------------------------------------------------------------

learning_ext_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-learning"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class GuardrailTestRequest(BaseModel):
    """Test guardrails on sample text."""
    text: str = Field(..., min_length=1)
    mode: str = Field(default="input", pattern="^(input|output)$")
    sources: List[str] = Field(default_factory=list)


class ArchivalStoreRequest(BaseModel):
    """Store a note in archival memory."""
    content: str = Field(..., min_length=1)
    source: str = Field(default="admin")
    category: str = Field(default="general")
    tags: List[str] = Field(default_factory=list)
    user_id: str = Field(default="")
    importance: float = Field(default=0.5, ge=0.0, le=1.0)


# ---------------------------------------------------------------------------
# Knowledge Graph
# ---------------------------------------------------------------------------

def _get_knowledge_graph():
    """Import and return the KG singleton."""
    try:
        from chat_app.knowledge_graph import get_knowledge_graph
        return get_knowledge_graph()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[ADMIN] Failed to import knowledge graph: %s", exc)
        return None


@learning_ext_router.get("/knowledge-graph/stats", summary="Get knowledge graph statistics")
async def get_kg_stats():
    """Return entity counts, relationship counts, and build metadata."""
    kg = _get_knowledge_graph()
    if not kg:
        return {"enabled": False, "message": "Knowledge graph not initialized", "timestamp": _now_iso()}
    stats = kg.get_stats()
    return {"enabled": True, **stats, "timestamp": _now_iso()}


@learning_ext_router.get("/knowledge-graph/entities", summary="Browse entities by type")
async def get_kg_entities(
    entity_type: Optional[str] = Query(default=None, alias="entity_type"),
    type: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Return entities, optionally filtered by type or search term."""
    kg = _get_knowledge_graph()
    if not kg:
        raise HTTPException(status_code=503, detail="Knowledge graph not initialized")
    etype = entity_type or type
    if search:
        all_entities = kg.search_entities(search, entity_types=[etype] if etype else None, limit=500)
    elif etype:
        all_entities = kg.query_by_type(etype, limit=500)
    else:
        all_entities = kg.search_entities("", limit=500)
    total = len(all_entities)
    page = all_entities[offset:offset + limit]
    return {
        "entities": [
            {"id": e.id, "name": e.name, "type": e.entity_type,
             "description": e.description[:200] if e.description else ""}
            for e in page
        ],
        "total": total,
        "timestamp": _now_iso(),
    }


@learning_ext_router.get("/knowledge-graph/entity/{entity_id:path}", summary="Get entity details")
async def get_kg_entity(entity_id: str):
    """Return full entity details with all neighbors/relationships."""
    kg = _get_knowledge_graph()
    if not kg:
        raise HTTPException(status_code=503, detail="Knowledge graph not initialized")
    entity = kg.get_entity(entity_id)
    if not entity:
        raise HTTPException(status_code=404, detail=f"Entity not found: {entity_id}")
    neighbors = kg.get_neighbors(entity_id)
    return {
        "entity": {
            "id": entity.id, "name": entity.name, "type": entity.entity_type,
            "description": entity.description, "metadata": entity.metadata,
        },
        "relationships": neighbors,
        "timestamp": _now_iso(),
    }


@learning_ext_router.post("/knowledge-graph/rebuild", summary="Rebuild the knowledge graph")
async def rebuild_kg():
    """Force rebuild the knowledge graph from source files."""
    try:
        from chat_app.knowledge_graph import rebuild_knowledge_graph
        kg = rebuild_knowledge_graph()
        _append_audit(section="knowledge_graph", action="rebuild", changes=kg.get_stats())
        return {"rebuilt": True, "stats": kg.get_stats(), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "knowledge graph rebuild"))


@learning_ext_router.get("/knowledge-graph/graph", summary="Get graph visualization data")
async def get_kg_graph(
    limit: int = Query(default=200, ge=10, le=1000),
    offset: int = Query(default=0, ge=0),
    entity_types: Optional[str] = Query(default=None, description="Comma-separated entity types to filter"),
    min_connections: int = Query(default=0, ge=0, description="Minimum relationship count"),
):
    """Return nodes and edges for graph visualization with filtering and grouping."""
    kg = _get_knowledge_graph()
    if not kg:
        return {"nodes": [], "edges": [], "total": 0, "type_groups": {}, "available_types": [], "timestamp": _now_iso()}
    try:
        type_list = [t.strip() for t in entity_types.split(",")] if entity_types else None
        viz_data = kg.get_visualization_data(
            limit=limit, offset=offset,
            entity_types=type_list,
            min_connections=min_connections,
        )
        nodes = []
        for n in viz_data["nodes"]:
            nodes.append({
                "id": n["id"],
                "name": n["name"],
                "entity_type": n["entity_type"],
                "description": n.get("description", ""),
                "metadata": {
                    "relationship_count": n["relationship_count"],
                    "in_degree": n["in_degree"],
                    "out_degree": n["out_degree"],
                    **n.get("metadata", {}),
                },
            })
        edges = []
        for e in viz_data["edges"]:
            edges.append({
                "source_id": e["source"],
                "target_id": e["target"],
                "relationship_type": e["rel_type"],
                "label": e["label"],
                "weight": e["weight"],
            })
        return {
            "nodes": nodes,
            "edges": edges,
            "total": viz_data["total"],
            "type_groups": viz_data["type_groups"],
            "available_types": viz_data["available_types"],
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("KG graph endpoint: %s", exc)
        return {"nodes": [], "edges": [], "error": str(type(exc).__name__), "timestamp": _now_iso()}


@learning_ext_router.get("/knowledge-graph/query", summary="Query the knowledge graph")
async def query_kg(
    q: str = Query(..., description="Entity name or search term"),
    rel_types: Optional[str] = Query(default=None, description="Comma-separated relationship types"),
    max_depth: int = Query(default=2, ge=1, le=4),
):
    """Query the graph for related entities."""
    kg = _get_knowledge_graph()
    if not kg:
        raise HTTPException(status_code=503, detail="Knowledge graph not initialized")
    rel_list = [r.strip() for r in rel_types.split(",")] if rel_types else None
    results = kg.query_related(q, rel_types=rel_list, max_depth=max_depth)
    return {"query": q, "results": results, "count": len(results), "timestamp": _now_iso()}


# ---------------------------------------------------------------------------
# Splunkbase Catalog
# ---------------------------------------------------------------------------

@learning_ext_router.get("/splunkbase/catalog", summary="Get Splunkbase catalog summary")
async def get_splunkbase_catalog_summary():
    """Return a summary of the local Splunkbase app catalog."""
    try:
        from chat_app.splunkbase_catalog import get_splunkbase_catalog
        catalog = get_splunkbase_catalog()
        return {**catalog.get_catalog_summary(), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "catalog query"))


@learning_ext_router.get("/splunkbase/apps", summary="Get all Splunkbase apps from catalog")
async def get_splunkbase_all_apps(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Return the full catalog of Splunkbase apps for the frontend."""
    try:
        from chat_app.splunkbase_catalog import get_splunkbase_catalog
        catalog = get_splunkbase_catalog()
        cat_data = catalog.catalog
        apps = cat_data.get("apps", {})
        meta = cat_data.get("metadata", {})
        app_list = []
        for uid, app in apps.items():
            app_list.append({
                "uid": uid,
                "name": app.get("title", ""),
                "app_id": app.get("app_id", ""),
                "author": ", ".join(app.get("sourcetypes", [])[:3]) if not app.get("releases") else "",
                "ver": app.get("latest_version", "unknown"),
                "updated": (app.get("latest_release_date", "") or "")[:10],
                "compat": ", ".join(app.get("supported_splunk_versions", [])[:3]),
            })
            if app.get("releases"):
                app_list[-1]["author"] = app.get("app_id", "").split("_")[0].title() if "_" in app.get("app_id", "") else "Splunk"
        app_list.sort(key=lambda a: a["name"].lower())
        total = len(app_list)
        page = app_list[offset:offset + limit]
        return {
            "apps": page,
            "total": total,
            "last_updated": meta.get("last_updated"),
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "catalog query"))


@learning_ext_router.get("/splunkbase/outdated", summary="Get outdated Splunk apps")
async def get_splunkbase_outdated():
    """Compare installed Splunk apps against the catalog and return outdated ones."""
    try:
        from chat_app.splunkbase_catalog import run_comparison_report
        result = await run_comparison_report()
        if "error" in result:
            return {"error": result["error"], "timestamp": _now_iso()}
        return {**result, "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "comparison"))


@learning_ext_router.post("/splunkbase/refresh", summary="Trigger Splunkbase catalog refresh")
async def refresh_splunkbase_catalog(full: bool = False):
    """Trigger an immediate catalog refresh from the Splunkbase API."""
    try:
        from chat_app.splunkbase_catalog import run_catalog_update
        result = await run_catalog_update(full_rebuild=full)
        _append_audit(
            section="splunkbase_catalog",
            action="full_rebuild" if full else "refresh",
            changes=result,
        )
        return {**result, "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "catalog refresh"))


@learning_ext_router.post("/splunkbase/compare", summary="Upload CSV/Excel of installed apps and compare")
async def compare_splunkbase_upload(request: Request):
    """Compare uploaded spreadsheet of installed apps against the Splunkbase catalog."""
    import io

    content_type = request.headers.get("content-type", "")
    body = await request.body()

    if not body:
        raise HTTPException(status_code=400, detail="Empty request body. Upload a CSV or Excel file.")

    installed_apps: List[Dict[str, Any]] = []

    try:
        if "multipart" in content_type:
            form = await request.form()
            file_field = None
            for key in form:
                file_field = form[key]
                break
            if file_field is None:
                raise HTTPException(status_code=400, detail="No file in upload")
            file_bytes = await file_field.read() if hasattr(file_field, "read") else file_field
            filename = getattr(file_field, "filename", "upload.csv") or "upload.csv"
        else:
            file_bytes = body
            filename = "upload.csv"

        if isinstance(file_bytes, str):
            file_bytes = file_bytes.encode("utf-8")

        if filename.endswith((".xlsx", ".xls")):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(io.BytesIO(file_bytes), read_only=True)
                ws = wb.active
                rows = list(ws.iter_rows(values_only=True))
                if not rows:
                    raise HTTPException(status_code=400, detail="Empty spreadsheet")
                headers = [str(h).strip().lower() if h else "" for h in rows[0]]
                for row in rows[1:]:
                    if not row or not any(row):
                        continue
                    entry = {}
                    for i, val in enumerate(row):
                        if i < len(headers) and headers[i]:
                            entry[headers[i]] = str(val).strip() if val else ""
                    if entry.get("name") or entry.get("app_id"):
                        installed_apps.append({
                            "name": entry.get("name") or entry.get("app_id", ""),
                            "version": entry.get("version", "unknown"),
                            "label": entry.get("label") or entry.get("title") or entry.get("name") or entry.get("app_id", ""),
                        })
                wb.close()
            except ImportError:
                raise HTTPException(
                    status_code=400,
                    detail="Excel support requires openpyxl. Upload CSV instead, or install openpyxl.",
                )
        else:
            import csv
            text = file_bytes.decode("utf-8-sig")
            reader = csv.DictReader(io.StringIO(text))
            for row in reader:
                norm = {k.strip().lower(): v.strip() if v else "" for k, v in row.items() if k}
                name = norm.get("name") or norm.get("app_id") or norm.get("app") or norm.get("folder") or ""
                version = norm.get("version") or norm.get("installed_version") or norm.get("ver") or "unknown"
                label = norm.get("label") or norm.get("title") or norm.get("description") or name
                if name:
                    installed_apps.append({"name": name, "version": version, "label": label})

    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=_safe_error(exc, "file parse"))

    if not installed_apps:
        raise HTTPException(status_code=400, detail="No apps found in uploaded file. Check column headers (name, version).")

    try:
        from chat_app.splunkbase_catalog import get_splunkbase_catalog
        catalog = get_splunkbase_catalog()

        if catalog.app_count == 0:
            return {
                "error": "Splunkbase catalog is empty. Run POST /api/admin/splunkbase/refresh first to build the catalog.",
                "apps_in_file": len(installed_apps),
                "timestamp": _now_iso(),
            }

        comparison = catalog.compare_installed(installed_apps)
        report = catalog._format_comparison_report(comparison)

        _append_audit(
            section="splunkbase_catalog", action="compare_upload",
            changes={"apps_uploaded": len(installed_apps), **comparison.get("summary", {})},
        )

        return {
            **comparison,
            "report_markdown": report,
            "apps_uploaded": len(installed_apps),
            "catalog_size": catalog.app_count,
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "comparison"))


# ---------------------------------------------------------------------------
# Guardrails API
# ---------------------------------------------------------------------------

@learning_ext_router.get("/guardrails/stats", summary="Guardrail event statistics")
async def get_guardrail_stats():
    """Return counts of guardrail events (input/output checks, blocks, PII, injections)."""
    try:
        from chat_app.guardrails import get_guardrail_stats as _gr_stats
        return {"stats": _gr_stats(), "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, _safe_error(exc, "guardrails stats"))


@learning_ext_router.post("/guardrails/test", summary="Test guardrails on sample text")
async def test_guardrails(body: GuardrailTestRequest):
    """Run guardrails against sample text without processing as a real query."""
    try:
        from chat_app.guardrails import check_input, check_output, redact_pii
        if body.mode == "output":
            result = check_output(body.text, sources=body.sources)
        else:
            result = check_input(body.text)
        return {
            "passed": result.passed,
            "blocked": result.blocked,
            "warnings": result.warnings,
            "pii_detected": result.pii_detected,
            "injection_score": result.injection_score,
            "groundedness_score": result.groundedness_score,
            "redacted": redact_pii(body.text) if result.pii_detected else None,
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(500, _safe_error(exc, "guardrails test"))


# ---------------------------------------------------------------------------
# Archival Memory endpoints
# ---------------------------------------------------------------------------

@learning_ext_router.get("/memory/archival/stats", summary="Get archival memory statistics")
async def get_archival_memory_stats():
    """Return note counts, categories, sources, and storage info."""
    try:
        from chat_app.archival_memory import get_archival_memory
        mem = get_archival_memory()
        stats = mem.get_stats()
        return {"enabled": True, **stats, "timestamp": _now_iso()}
    except (ImportError, RuntimeError) as exc:
        return {"enabled": False, "message": str(exc), "timestamp": _now_iso()}


@learning_ext_router.get("/memory/archival/search", summary="Search archival memory")
async def search_archival_memory(
    q: str = Query(..., min_length=1, description="Search query"),
    user_id: str = Query(default="", description="Filter by user ID"),
    limit: int = Query(default=50, ge=1, le=500, description="Max results"),
    offset: int = Query(default=0, ge=0),
):
    """Search archival memory by keyword matching."""
    try:
        from chat_app.archival_memory import get_archival_memory
        mem = get_archival_memory()
        all_notes = mem.recall(q, user_id=user_id, limit=500)
        total = len(all_notes)
        page = all_notes[offset:offset + limit]
        return {
            "query": q,
            "results": [n.to_dict() for n in page],
            "total": total,
            "count": len(page),
            "timestamp": _now_iso(),
        }
    except (ImportError, RuntimeError) as exc:
        raise HTTPException(503, f"Archival memory not available: {exc}")


@learning_ext_router.post("/memory/archival/store", summary="Store a memory note")
async def store_archival_memory(body: ArchivalStoreRequest):
    """Manually store a note in archival memory."""
    try:
        from chat_app.archival_memory import get_archival_memory
        mem = get_archival_memory()
        note = mem.store(
            content=body.content,
            source=body.source,
            category=body.category,
            tags=body.tags,
            user_id=body.user_id,
            importance=body.importance,
        )
        mem.save()
        return {
            "success": True,
            "note": note.to_dict(),
            "timestamp": _now_iso(),
        }
    except (ImportError, RuntimeError) as exc:
        raise HTTPException(503, f"Archival memory not available: {exc}")


# ---------------------------------------------------------------------------
# GET /api/admin/guardrails — guardrail config and trigger statistics
# ---------------------------------------------------------------------------

@learning_ext_router.get("/guardrails", summary="Guardrail configuration and trigger statistics")
async def get_guardrails():
    """Return guardrail configuration and event counts.

    Combines the static guardrail configuration (rules, PII patterns, injection
    detection thresholds) with live event counts so admins can assess guardrail
    health and tune sensitivity without separate requests.
    """
    config_data: dict = {}
    stats_data: dict = {}

    # Guardrail stats (already implemented at /guardrails/stats)
    try:
        from chat_app.guardrails import get_guardrail_stats as _gr_stats
        stats_data = _gr_stats()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        stats_data = {"error": str(exc)}

    # Guardrail configuration from settings
    try:
        from chat_app.settings import get_settings
        settings = get_settings()
        security_cfg = getattr(settings, "security", None)
        if security_cfg:
            config_data = {
                "pii_detection_enabled": getattr(security_cfg, "pii_detection", True),
                "injection_detection_enabled": getattr(security_cfg, "injection_detection", True),
                "groundedness_check_enabled": getattr(security_cfg, "groundedness_check", False),
                "max_input_length": getattr(security_cfg, "max_input_length", 10000),
                "blocked_patterns_count": len(getattr(security_cfg, "blocked_patterns", []) or []),
            }
    except Exception:  # broad catch — resilience at boundary
        config_data = {}

    # Guardrail module config (best-effort)
    try:
        from chat_app.guardrails import GUARDRAIL_CONFIG
        config_data.update(GUARDRAIL_CONFIG)
    except (ImportError, AttributeError):
        pass

    return {
        "status": "ok",
        "config": config_data,
        "stats": stats_data,
        "endpoints": {
            "stats": "GET /api/admin/guardrails/stats",
            "test": "POST /api/admin/guardrails/test",
        },
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# GET /api/admin/artifacts — list generated artifacts and exports
# ---------------------------------------------------------------------------

@learning_ext_router.get("/artifacts", summary="List generated artifacts and exports")
async def get_artifacts(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Return a list of generated artifacts: training exports, evaluation reports, backups.

    Scans well-known artifact directories under /app/data/ and returns file
    metadata with type annotations so the frontend can offer download links.
    """
    from pathlib import Path as _Path

    artifact_dirs = {
        "training_export": ("/app/data/training_exports", "*.jsonl"),
        "eval_report":     ("/app/data/eval_reports",     "*.json"),
        "learning_report": ("/app/data/learning_reports",  "learning_*.json"),
        "kg_snapshot":     ("/app/data",                   "knowledge_graph.json"),
        "qa_export":       ("/app/data/qa_exports",        "*.jsonl"),
        "debug_export":    ("/app/data/debug",             "*.json"),
    }

    artifacts = []
    for artifact_type, (dir_path, glob_pattern) in artifact_dirs.items():
        d = _Path(dir_path)
        if not d.exists():
            continue
        try:
            for f in sorted(d.glob(glob_pattern), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    stat = f.stat()
                    artifacts.append({
                        "type": artifact_type,
                        "filename": f.name,
                        "path": str(f),
                        "size_bytes": stat.st_size,
                        "modified_at": stat.st_mtime,
                        "download_hint": f"podman exec chat_ui_app cat {f}",
                    })
                except Exception:  # broad catch — resilience at boundary
                    pass
        except Exception:  # broad catch — resilience at boundary
            pass

    total = len(artifacts)
    page = artifacts[offset:offset + limit]

    return {
        "status": "ok",
        "artifacts": page,
        "total": total,
        "artifact_types": list(artifact_dirs.keys()),
        "timestamp": _now_iso(),
    }
