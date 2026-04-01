"""Admin sub-router: Collection management, search, browse, backup/restore.

Handles these endpoint groups:
- GET  /api/admin/collections              — List vector store collections
- POST /api/admin/collections/action       — Manage a collection (create/delete/reset)
- POST /api/admin/collections/reindex      — Delete all and re-ingest
- GET  /api/admin/collections/reindex/status — Check reindex progress
- POST /api/admin/collections/search       — Search chunks across collections
- GET  /api/admin/collections/{name}/chunks — Browse chunks in a collection
- GET  /api/admin/collections/{name}/facets — Get distinct metadata values
- DELETE /api/admin/collections/chunks     — Delete specific chunks
- POST /api/admin/collections/backup       — Backup all ChromaDB collections
- GET  /api/admin/collections/backups      — List collection backups
- POST /api/admin/collections/restore      — Restore collections from backup

Mount with:
    from chat_app.admin_collections_routes import collections_router
    # Already included via admin_api.py router.include_router()
"""

import logging
import os
import subprocess

from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from chat_app.auth_dependencies import require_admin
from chat_app.settings import get_settings
from chat_app.admin_shared import (
    _append_audit,
    _csrf_check,
    _human_size,
    _now_iso,
    _rate_limit,
    _safe_error,
    _track_audit_user,
)

logger = logging.getLogger(__name__)

collections_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-collections"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CollectionActionRequest(BaseModel):
    """Request for collection operations."""
    collection_name: str
    action: str = Field(..., description="Action: create, delete, reset")


class CollectionSearchRequest(BaseModel):
    """Search across collections."""
    query: str = Field(..., min_length=1, description="Search string")
    collections: Optional[List[str]] = Field(None, description="Limit to these collections")
    limit: int = Field(20, ge=1, le=100, description="Max results per collection")
    app_type: Optional[str] = Field(None, description="Filter by app_type (TAs, BAs, etc.)")
    deployment_tier: Optional[str] = Field(None, description="Filter by deployment_tier (_global, etc.)")
    deployment_target: Optional[str] = Field(None, description="Filter by deployment_target")
    stanza_type: Optional[str] = Field(None, description="Filter by conf_type")


class ChunkDeleteRequest(BaseModel):
    """Delete specific chunks."""
    collection_name: str
    chunk_ids: List[str] = Field(..., min_length=1)


class CollectionRestoreRequest(BaseModel):
    filename: str
    overwrite: bool = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_chroma_client():
    """Get the ChromaDB client, reusing the vectorstore's client to avoid SQLite lock conflicts."""
    try:
        from chat_app.vectorstore import get_vector_store
        _store = get_vector_store()
        _client = getattr(_store, '_client', None)
        if _client is not None:
            return _client
    except (ImportError, AttributeError, RuntimeError):
        pass
    # Fallback: create a new client
    import chromadb
    from chromadb.config import Settings as ChromaSettings
    settings = get_settings()
    chroma_cfg = settings.chroma
    chroma_dir = chroma_cfg.dir or "/app/chroma_store"
    try:
        return chromadb.PersistentClient(
            path=chroma_dir,
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    except (OSError, ValueError, RuntimeError):
        host = chroma_cfg.http_url.replace("http://", "").split(":")[0]
        port_str = chroma_cfg.http_url.split(":")[-1] if ":" in chroma_cfg.http_url.split("//")[-1] else "8000"
        return chromadb.HttpClient(host=host, port=int(port_str))


def _build_where_filter(**kwargs) -> dict | None:
    """Build a ChromaDB where filter from non-None keyword arguments."""
    clauses = []
    for key, val in kwargs.items():
        if val is not None:
            clauses.append({key: {"$eq": val}})
    if not clauses:
        return None
    if len(clauses) == 1:
        return clauses[0]
    return {"$and": clauses}


def _do_collection_backup() -> dict:
    """Shared helper: export all ChromaDB collections to gzipped JSON. Returns result dict."""
    import gzip
    import json as _json

    client = _get_chroma_client()
    collections = client.list_collections()
    backup_data = {}
    total_chunks = 0

    for col_name in collections:
        try:
            col = client.get_collection(name=col_name)
            data = col.get(include=["documents", "metadatas"])
            chunk_count = len(data.get("ids", []))
            total_chunks += chunk_count
            backup_data[col_name] = {
                "ids": data.get("ids", []),
                "documents": data.get("documents", []),
                "metadatas": data.get("metadatas", []),
            }
        except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as col_exc:
            logger.warning("[BACKUP] Failed to export collection %s: %s", col_name, col_exc)
            backup_data[col_name] = {"error": str(col_exc)}

    backup_dir = Path("/app/data/collection_backups")
    backup_dir.mkdir(parents=True, exist_ok=True)

    from datetime import datetime
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"collections_backup_{timestamp}.json.gz"
    filepath = backup_dir / filename

    json_bytes = _json.dumps(backup_data, default=str).encode("utf-8")
    with gzip.open(str(filepath), "wb") as f:
        f.write(json_bytes)

    return {
        "file": filename,
        "collections_count": len(backup_data),
        "total_chunks": total_chunks,
        "size_bytes": filepath.stat().st_size,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@collections_router.get("/collections", summary="List vector store collections")
async def list_collections(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List all ChromaDB collections with document counts and metadata."""
    settings = get_settings()
    chroma_cfg = settings.chroma

    collections_info = []
    try:
        import chromadb
        from chromadb.config import Settings as ChromaSettings
        chroma_dir = chroma_cfg.dir or "/app/chroma_store"
        client = None
        try:
            from chat_app.vectorstore import get_vector_store
            _store = get_vector_store()
            _client = getattr(_store, '_client', None)
            if _client is not None:
                client = _client
                logger.debug("[COLLECTIONS] Reusing vectorstore's ChromaDB client")
        except (ImportError, AttributeError, RuntimeError):
            pass
        if client is None:
            try:
                client = chromadb.PersistentClient(
                    path=chroma_dir,
                    settings=ChromaSettings(anonymized_telemetry=False),
                )
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as pce:
                logger.warning("[COLLECTIONS] PersistentClient failed (%s), falling back to HTTP", pce)
                from urllib.parse import urlparse
                parsed = urlparse(chroma_cfg.http_url)
                host = parsed.hostname or "127.0.0.1"
                port = parsed.port or 8001
                client = chromadb.HttpClient(host=host, port=port)
        raw_cols = client.list_collections()
        for c in raw_cols:
            try:
                if hasattr(c, "name"):
                    col_name = c.name
                    count = c.count()
                    meta = c.metadata or {}
                else:
                    col_name = str(c)
                    col_obj = client.get_collection(col_name)
                    count = col_obj.count()
                    meta = col_obj.metadata or {}
                collections_info.append({
                    "name": col_name,
                    "document_count": count,
                    "metadata": meta,
                })
            except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as col_exc:
                collections_info.append({
                    "name": c.name if hasattr(c, "name") else str(c),
                    "document_count": 0,
                    "error": str(col_exc),
                })
    except (ValueError, KeyError, TypeError, AttributeError, RuntimeError, OSError) as exc:
        collections_info = [{"error": f"Cannot connect to ChromaDB: {exc}"}]

    # Include expected collections that don't exist yet
    existing_names = {c["name"] for c in collections_info if "name" in c}
    expected = [
        chroma_cfg.collection,
        chroma_cfg.secondary_collection,
        "spl_commands_mxbai",
        "local_docs_mxbai",
        "self_learned_qa",
        "org_repo_mxbai",
        "cribl_docs_mxbai",
        "negative_feedback_mxbai_embed_large",
    ]
    for name in expected:
        if name and name not in existing_names:
            collections_info.append({
                "name": name,
                "document_count": 0,
                "metadata": {},
                "status": "not_created",
            })

    total = len(collections_info)
    page = collections_info[offset:offset + limit]
    return {
        "collections": page,
        "config": {
            "primary_collection": chroma_cfg.collection,
            "secondary_collection": chroma_cfg.secondary_collection,
            "http_url": chroma_cfg.http_url,
        },
        "total": total,
        "timestamp": _now_iso(),
    }


@collections_router.post("/collections/action", summary="Manage a collection")
async def manage_collection(body: CollectionActionRequest):
    """Create, delete, or reset a ChromaDB collection."""
    settings = get_settings()
    chroma_cfg = settings.chroma

    try:
        import chromadb
        client = chromadb.HttpClient(
            host=chroma_cfg.http_url.replace("http://", "").split(":")[0],
            port=int(chroma_cfg.http_url.split(":")[-1]) if ":" in chroma_cfg.http_url.split("//")[-1] else 8000,
        )

        if body.action == "create":
            client.get_or_create_collection(name=body.collection_name)
            result = {"action": "created", "collection": body.collection_name}
        elif body.action == "delete":
            client.delete_collection(name=body.collection_name)
            result = {"action": "deleted", "collection": body.collection_name}
        elif body.action == "reset":
            client.delete_collection(name=body.collection_name)
            client.get_or_create_collection(name=body.collection_name)
            result = {"action": "reset", "collection": body.collection_name}
        else:
            raise HTTPException(status_code=400, detail=f"Unknown action: {body.action}")

        _append_audit(section="collections", action=body.action, changes={"collection": body.collection_name})
        return {**result, "timestamp": _now_iso()}

    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@collections_router.post("/collections/reindex", summary="Delete all collections and re-ingest everything")
async def reindex_all_collections(
    skip_delete: bool = Query(False, description="Skip deletion, only add missing files"),
    collection: Optional[str] = Query(None, description="Only reindex a specific collection label"),
):
    """Delete all ChromaDB collections and re-ingest from source files."""
    _append_audit(section="collections", action="reindex_all", changes={
        "trigger": "admin_api", "skip_delete": skip_delete, "collection": collection,
    })

    cmd = ["python3", "/app/chat_app/run_quick_ingest.py"]
    if skip_delete:
        cmd.append("--skip-delete")
    if collection:
        cmd.extend(["--collection", collection])

    try:
        with open("/tmp/reindex.log", "w") as log_fh:
            proc = subprocess.Popen(
                cmd,
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                cwd="/app",
            )
        with open("/tmp/reindex.pid", "w") as pf:
            pf.write(str(proc.pid))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc, "reindex start"))

    return {
        "status": "started",
        "message": "Reindex started in background. All collections will be deleted and re-ingested with current chunking settings.",
        "note": "Check GET /api/admin/collections to monitor progress. Logs at /tmp/reindex.log",
        "timestamp": _now_iso(),
    }


@collections_router.get("/collections/reindex/status", summary="Check reindex progress")
async def get_reindex_status():
    """Check if reindex is currently running and return progress."""
    reindex_running = False
    log_tail = ""
    try:
        with open("/tmp/reindex.pid", "r") as pf:
            pid = int(pf.read().strip())
        reindex_running = os.path.exists(f"/proc/{pid}")
        if not reindex_running:
            os.remove("/tmp/reindex.pid")
    except (FileNotFoundError, ValueError) as _exc:
        logger.debug("Could not read reindex PID file: %s", _exc)
    try:
        with open("/tmp/reindex.log", "r") as f:
            lines = f.readlines()
            log_tail = "".join(lines[-10:]) if lines else ""
    except FileNotFoundError:
        log_tail = ""
    return {
        "running": reindex_running,
        "log_tail": log_tail,
        "timestamp": _now_iso(),
    }


@collections_router.post("/collections/search", summary="Search chunks across collections")
async def search_collections(body: CollectionSearchRequest):
    """Search for chunks matching a query string across all (or specified) collections."""
    try:
        client = _get_chroma_client()
        target_collections = body.collections or [c.name for c in client.list_collections()]

        query_embedding = None
        try:
            from chat_app.vectorstore import get_embeddings_model
            _embed_fn = get_embeddings_model()
            query_embedding = _embed_fn.embed_query(body.query)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as embed_err:
            logger.warning("[ADMIN] Failed to embed search query via Ollama: %s — falling back to query_texts", embed_err)

        where_filter = _build_where_filter(
            app_type=body.app_type,
            deployment_tier=body.deployment_tier,
            deployment_target=body.deployment_target,
            conf_type=body.stanza_type,
        )

        results = {}
        for col_name in target_collections:
            try:
                col = client.get_collection(name=col_name)
                doc_count = col.count() or 0
                if doc_count == 0:
                    continue
                n = min(body.limit, doc_count)
                if query_embedding is not None:
                    query_kwargs = dict(query_embeddings=[query_embedding], n_results=n, include=["documents", "metadatas", "distances"])
                else:
                    query_kwargs = dict(query_texts=[body.query], n_results=n, include=["documents", "metadatas", "distances"])
                if where_filter:
                    query_kwargs["where"] = where_filter
                res = col.query(**query_kwargs)
                items = []
                if res and res.get("ids") and res["ids"][0]:
                    for i, doc_id in enumerate(res["ids"][0]):
                        items.append({
                            "id": doc_id,
                            "content": (res["documents"][0][i] or "")[:500],
                            "metadata": res["metadatas"][0][i] if res.get("metadatas") else {},
                            "distance": round(res["distances"][0][i], 4) if res.get("distances") else None,
                        })
                if items:
                    results[col_name] = {"count": len(items), "items": items}
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _col_err:
                logger.warning("[ADMIN] Failed to query collection %s (query_len=%d): %s", col_name, len(body.query), _col_err)
                continue

        logger.info("[ADMIN] Collection search: query=%r collections=%d matches=%d",
                     body.query[:80], len(target_collections), sum(r["count"] for r in results.values()))
        return {
            "query": body.query,
            "results": results,
            "collections_searched": len(target_collections),
            "total_matches": sum(r["count"] for r in results.values()),
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@collections_router.get("/collections/{name}/chunks", summary="Browse chunks in a collection")
async def browse_collection_chunks(
    name: str,
    offset: int = 0,
    limit: int = 50,
    source_filter: Optional[str] = None,
    app_type: Optional[str] = None,
    deployment_tier: Optional[str] = None,
    conf_type: Optional[str] = None,
):
    """Browse chunks in a specific collection with pagination and metadata filters."""
    try:
        client = _get_chroma_client()
        col = client.get_collection(name=name)
        total = col.count()

        filter_clauses = []
        if source_filter:
            filter_clauses.append({"source": {"$contains": source_filter}})
        if app_type:
            filter_clauses.append({"app_type": {"$eq": app_type}})
        if deployment_tier:
            filter_clauses.append({"deployment_tier": {"$eq": deployment_tier}})
        if conf_type:
            filter_clauses.append({"conf_type": {"$eq": conf_type}})

        if len(filter_clauses) == 0:
            where_filter = None
        elif len(filter_clauses) == 1:
            where_filter = filter_clauses[0]
        else:
            where_filter = {"$and": filter_clauses}

        res = col.get(
            limit=min(limit, 200),
            offset=offset,
            include=["documents", "metadatas"],
            where=where_filter,
        )

        chunks = []
        if res and res.get("ids"):
            for i, doc_id in enumerate(res["ids"]):
                doc = res["documents"][i] if res.get("documents") else ""
                meta = res["metadatas"][i] if res.get("metadatas") else {}
                chunks.append({
                    "id": doc_id,
                    "content_preview": (doc or "")[:300],
                    "content_length": len(doc or ""),
                    "metadata": meta,
                })

        return {
            "collection": name,
            "total": total,
            "offset": offset,
            "limit": limit,
            "chunks": chunks,
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@collections_router.get("/collections/{name}/facets", summary="Get distinct metadata values for filtering")
async def get_collection_facets(name: str):
    """Sample chunks and return distinct metadata field values for filter dropdowns."""
    try:
        client = _get_chroma_client()
        col = client.get_collection(name=name)
        total = col.count()
        sample_size = min(total, 500)

        if sample_size == 0:
            return {"collection": name, "total": 0, "sampled": 0, "facets": {}}

        res = col.get(limit=sample_size, include=["metadatas"])
        facet_fields = ["app_type", "deployment_tier", "deployment_target", "conf_type", "category", "app_name"]
        facets: dict = {f: set() for f in facet_fields}

        if res and res.get("metadatas"):
            for meta in res["metadatas"]:
                if not meta:
                    continue
                for field in facet_fields:
                    val = meta.get(field)
                    if val is not None and val != "":
                        facets[field].add(str(val))

        return {
            "collection": name,
            "total": total,
            "sampled": sample_size,
            "facets": {k: sorted(v) for k, v in facets.items()},
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@collections_router.delete("/collections/chunks", summary="Delete specific chunks")
async def delete_chunks(body: ChunkDeleteRequest):
    """Delete specific chunks by ID from a collection."""
    try:
        client = _get_chroma_client()
        col = client.get_collection(name=body.collection_name)
        before_count = col.count()
        col.delete(ids=body.chunk_ids)
        after_count = col.count()
        deleted = before_count - after_count

        _append_audit(
            section="collections",
            action="delete_chunks",
            changes={"collection": body.collection_name, "chunk_ids": body.chunk_ids[:10], "deleted": deleted},
        )

        return {
            "collection": body.collection_name,
            "requested": len(body.chunk_ids),
            "deleted": deleted,
            "remaining": after_count,
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))


# ---------------------------------------------------------------------------
# Collection Backup & Restore
# ---------------------------------------------------------------------------

@collections_router.post("/collections/backup", summary="Backup all ChromaDB collections")
async def backup_collections():
    """Export all ChromaDB collections to a compressed JSON file."""
    try:
        result = _do_collection_backup()
        _append_audit(
            section="collections",
            action="backup",
            changes={"file": result["file"], "collections": result["collections_count"], "chunks": result["total_chunks"]},
        )
        return {"status": "ok", **result, "timestamp": _now_iso()}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error("[BACKUP] Collection backup failed: %s", exc)
        raise HTTPException(status_code=500, detail=_safe_error(exc))


@collections_router.get("/collections/backups", summary="List collection backups")
async def list_collection_backups(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List available ChromaDB collection backups."""
    backup_dir = Path("/app/data/collection_backups")
    backups = []
    if backup_dir.exists():
        for f in sorted(backup_dir.glob("collections_backup_*.json.gz"), reverse=True):
            backups.append({
                "filename": f.name,
                "size_bytes": f.stat().st_size,
                "timestamp": f.stat().st_mtime,
            })
    total = len(backups)
    page = backups[offset:offset + limit]
    return {"backups": page, "total": total, "timestamp": _now_iso()}


@collections_router.post("/collections/restore", summary="Restore collections from backup")
async def restore_collections(body: CollectionRestoreRequest):
    """Restore ChromaDB collections from a backup file."""
    import gzip
    import json as _json

    backup_dir = Path("/app/data/collection_backups")
    filepath = backup_dir / body.filename

    # Security: ensure filename doesn't escape backup directory
    if ".." in body.filename or "/" in body.filename or "\\" in body.filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    if Path(body.filename).name != body.filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    try:
        resolved = filepath.resolve(strict=False)
        if not str(resolved).startswith(str(backup_dir.resolve())):
            raise HTTPException(status_code=400, detail="Invalid filename")
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="Invalid filename")
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Backup file not found")

    try:
        with gzip.open(str(filepath), "rb") as f:
            backup_data = _json.loads(f.read().decode("utf-8"))

        client = _get_chroma_client()
        restored_collections = 0
        total_chunks = 0
        errors = []

        for col_name, col_data in backup_data.items():
            if "error" in col_data:
                continue
            try:
                ids = col_data.get("ids", [])
                if not ids:
                    continue

                if body.overwrite:
                    try:
                        client.delete_collection(name=col_name)
                    except (ValueError, RuntimeError) as _exc:
                        logger.debug("Could not delete collection %r before overwrite: %s", col_name, _exc)

                try:
                    col = client.get_or_create_collection(name=col_name)
                except (ValueError, RuntimeError):
                    col = client.create_collection(name=col_name)

                batch_size = 500
                for i in range(0, len(ids), batch_size):
                    batch_ids = ids[i:i + batch_size]
                    batch_docs = col_data.get("documents", [])[i:i + batch_size]
                    batch_meta = col_data.get("metadatas", [])[i:i + batch_size]
                    col.add(ids=batch_ids, documents=batch_docs, metadatas=batch_meta)

                total_chunks += len(ids)
                restored_collections += 1
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as col_exc:
                logger.warning(f"[RESTORE] Failed to restore collection {col_name}: {col_exc}")
                errors.append({"collection": col_name, "error": str(col_exc)})

        _append_audit(
            section="collections",
            action="restore",
            changes={"file": body.filename, "collections": restored_collections, "chunks": total_chunks},
        )

        return {
            "status": "ok",
            "restored_collections": restored_collections,
            "total_chunks": total_chunks,
            "errors": errors,
            "timestamp": _now_iso(),
        }
    except HTTPException:
        raise
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error(f"[RESTORE] Collection restore failed: {exc}")
        raise HTTPException(status_code=500, detail=_safe_error(exc))


# ---------------------------------------------------------------------------
# GET /api/admin/collections/stats — per-collection size and document counts
# ---------------------------------------------------------------------------

@collections_router.get("/collections/stats", summary="Collection statistics")
async def get_collection_stats():
    """Return per-collection document counts, estimated storage size, and totals.

    Aggregates count() from all ChromaDB collections and annotates with the
    number of unique sources per collection where metadata is available.
    """
    try:
        client = _get_chroma_client()
        collections = client.list_collections()

        stats = []
        total_documents = 0
        total_size_estimate_bytes = 0

        for col in collections:
            try:
                count = col.count()
                # Estimate storage: ~1 KB per chunk (embedding + text + metadata)
                size_estimate = count * 1024
                total_documents += count
                total_size_estimate_bytes += size_estimate

                # Sample metadata to count unique sources (limit query to avoid OOM)
                sources: set = set()
                try:
                    sample = col.get(limit=min(count, 500), include=["metadatas"])
                    for meta in (sample.get("metadatas") or []):
                        if meta and meta.get("source"):
                            sources.add(meta["source"])
                except Exception:  # broad catch — resilience at boundary
                    pass

                stats.append({
                    "name": col.name,
                    "document_count": count,
                    "unique_sources": len(sources),
                    "size_estimate_bytes": size_estimate,
                    "size_estimate_human": _human_size(size_estimate),
                })
            except Exception as col_exc:  # broad catch — resilience at boundary
                logger.warning("[STATS] Failed to query collection %s: %s", col.name, col_exc)
                stats.append({
                    "name": col.name,
                    "document_count": None,
                    "unique_sources": None,
                    "size_estimate_bytes": None,
                    "size_estimate_human": "unknown",
                    "error": str(col_exc),
                })

        return {
            "status": "ok",
            "collection_count": len(stats),
            "total_documents": total_documents,
            "total_size_estimate_bytes": total_size_estimate_bytes,
            "total_size_estimate_human": _human_size(total_size_estimate_bytes),
            "collections": stats,
            "timestamp": _now_iso(),
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        raise HTTPException(status_code=500, detail=_safe_error(exc))
