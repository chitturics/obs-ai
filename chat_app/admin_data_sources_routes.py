"""
Admin Data Sources API — All data sources the system pulls from.

Provides a single endpoint that lists every data source with its refresh
frequency, last update time, record count, and status.  Designed for the
admin console's Data Sources page so operators can see at a glance what the
system knows, how fresh it is, and whether anything needs attention.

Mount with:
    from chat_app.admin_data_sources_routes import data_sources_router
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends

from chat_app.admin_shared import (
    _csrf_check,
    _rate_limit,
    _track_audit_user,
)
from chat_app.auth_dependencies import require_admin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

data_sources_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-data-sources"],
    dependencies=[
        Depends(_rate_limit),
        Depends(require_admin),
        Depends(_track_audit_user),
        Depends(_csrf_check),
    ],
)

# ---------------------------------------------------------------------------
# Internal helpers — each returns a source dict
# ---------------------------------------------------------------------------

# Sentinel for "unknown" that serialises cleanly to JSON null
_UNKNOWN = None


def _iso_mtime(path: Path) -> Optional[str]:
    """Return the ISO-8601 mtime of a file, or None if it does not exist."""
    try:
        mtime = path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except (OSError, ValueError):
        return None


def _count_files(directory: Path, glob: str = "*") -> int:
    """Count files matching a glob inside a directory tree."""
    try:
        return sum(1 for _ in directory.glob(glob) if _.is_file())
    except OSError:
        return 0


def _source_splunkbase_catalog() -> Dict[str, Any]:
    """Metadata for the Splunkbase app/TA catalog."""
    catalog_path = Path("/app/data/splunkbase_catalog.json")
    last_updated: Optional[str] = None
    record_count: int = 0
    status = "unknown"

    try:
        if catalog_path.is_file():
            raw = json.loads(catalog_path.read_text(encoding="utf-8"))
            meta = raw.get("metadata", {})
            last_updated = meta.get("last_updated") or _iso_mtime(catalog_path)
            record_count = meta.get("total_apps", len(raw.get("apps", {})))
            status = "active"
        else:
            status = "not_found"
    except (json.JSONDecodeError, OSError, KeyError):
        status = "error"
        last_updated = _iso_mtime(catalog_path)

    return {
        "name": "Splunkbase Catalog",
        "description": "App/TA version catalog fetched from Splunkbase. Used for upgrade readiness checks and outdated-app detection.",
        "source_url": "https://splunkbase.splunk.com/api/v1/app/",
        "refresh_frequency": "Daily (skips if <12 h old)",
        "last_updated": last_updated,
        "status": status,
        "record_count": record_count,
        "cache_path": str(catalog_path),
    }


def _source_security_advisories() -> Dict[str, Any]:
    """Metadata for the Splunk CVE / advisory cache."""
    cache_path = Path("/app/data/security_advisories/advisories_cache.json")
    last_updated: Optional[str] = None
    record_count: int = 0
    status = "unknown"

    # Also count bundled advisories from YAML as fallback
    bundled_path = Path("/app/data/security_advisories/advisories.yaml")
    bundled_count: int = 0
    try:
        if bundled_path.is_file():
            import yaml
            with open(bundled_path) as fh:
                data = yaml.safe_load(fh)
            bundled_count = len(data.get("advisories", []))
    except Exception:
        pass

    try:
        if cache_path.is_file():
            raw = json.loads(cache_path.read_text(encoding="utf-8"))
            last_updated = raw.get("cached_at") or _iso_mtime(cache_path)
            record_count = raw.get("count", len(raw.get("advisories", [])))
            status = "active"
        elif bundled_count:
            last_updated = _iso_mtime(bundled_path)
            record_count = bundled_count
            status = "bundled"  # live cache missing but bundled YAML present
        else:
            status = "not_found"
    except (json.JSONDecodeError, OSError):
        status = "error"
        record_count = bundled_count
        last_updated = _iso_mtime(bundled_path)

    return {
        "name": "Security Advisories",
        "description": "Splunk CVEs scraped from advisory.splunk.com. Used for version risk scoring and upgrade readiness.",
        "source_url": "https://advisory.splunk.com/advisories",
        "refresh_frequency": "Daily (idle-worker job: refresh_security_advisories)",
        "last_updated": last_updated,
        "status": status,
        "record_count": record_count,
        "cache_path": str(cache_path),
    }


def _source_splunk_versions() -> Dict[str, Any]:
    """Metadata for the Splunk Enterprise version YAML."""
    yaml_path = Path("/app/data/splunk_versions.yaml")
    if not yaml_path.is_file():
        # Bundled copy inside the package directory
        yaml_path = Path("/app/chat_app/upgrade_readiness/splunk_versions.yaml")

    record_count: int = 0
    status = "not_found"

    try:
        if yaml_path.is_file():
            import yaml
            with open(yaml_path) as fh:
                data = yaml.safe_load(fh)
            record_count = len(data.get("enterprise", {}).get("versions", []))
            status = "active"
    except Exception:
        status = "error"

    return {
        "name": "Splunk Enterprise Versions",
        "description": "Verified platform version list sourced from advisory.splunk.com release history.",
        "source_url": "data/splunk_versions.yaml",
        "refresh_frequency": "Manual (update YAML file + redeploy)",
        "last_updated": _iso_mtime(yaml_path),
        "status": status,
        "record_count": record_count,
        "data_path": str(yaml_path),
    }


def _source_breaking_changes() -> Dict[str, Any]:
    """Metadata for the breaking changes YAML database."""
    breaking_changes_dir = Path("/app/chat_app/upgrade_readiness")
    yaml_files = list(breaking_changes_dir.glob("[0-9]*.yaml"))

    total_changes: int = 0
    status = "not_found"
    last_updated: Optional[str] = None

    if yaml_files:
        try:
            import yaml
            for yaml_file in yaml_files:
                with open(yaml_file) as fh:
                    data = yaml.safe_load(fh) or {}
                # Each file may have a list of changes or a dict with version keys
                if isinstance(data, dict):
                    for value in data.values():
                        if isinstance(value, list):
                            total_changes += len(value)
                elif isinstance(data, list):
                    total_changes += len(data)

            # Most recently modified YAML file
            latest = max(yaml_files, key=lambda p: p.stat().st_mtime)
            last_updated = _iso_mtime(latest)
            status = "active"
        except Exception:
            status = "error"
            last_updated = _iso_mtime(yaml_files[0]) if yaml_files else None

    return {
        "name": "Breaking Changes Database",
        "description": "Known breaking changes per Splunk version (per-major-version YAML files).",
        "source_url": "chat_app/upgrade_readiness/*.yaml",
        "refresh_frequency": "Manual (YAML files updated per Splunk release cycle)",
        "last_updated": last_updated,
        "status": status,
        "record_count": total_changes,
        "file_count": len(yaml_files),
        "data_path": str(breaking_changes_dir),
    }


def _source_org_repository() -> Dict[str, Any]:
    """Metadata for the organisation's Splunk configuration repository."""
    repo_dir = Path("/app/documents/repo/splunk")
    status = "not_found"
    conf_count: int = 0
    last_updated: Optional[str] = None

    if repo_dir.is_dir():
        try:
            conf_files = list(repo_dir.rglob("*.conf"))
            conf_count = len(conf_files)
            if conf_files:
                latest = max(conf_files, key=lambda p: p.stat().st_mtime)
                last_updated = _iso_mtime(latest)
            status = "active" if conf_count else "empty"
        except OSError:
            status = "error"

    return {
        "name": "Org Repository",
        "description": "Organisation Splunk .conf files (deployment-apps, master-apps, shcluster). "
                       "Scanned on-demand for upgrade impact analysis.",
        "source_url": "documents/repo/splunk/",
        "refresh_frequency": "On-demand scan (triggered by upgrade analysis)",
        "last_updated": last_updated,
        "status": status,
        "record_count": conf_count,
        "data_path": str(repo_dir),
    }


def _source_spec_files() -> Dict[str, Any]:
    """Metadata for Splunk .spec configuration reference files."""
    specs_dir = Path("/app/documents/specs")
    ingest_specs_dir = Path("/app/ingest_specs")

    spec_count: int = 0
    last_updated: Optional[str] = None
    status = "not_found"

    for directory in (specs_dir, ingest_specs_dir):
        if directory.is_dir():
            try:
                spec_files = list(directory.glob("*.spec"))
                spec_count += len(spec_files)
                if spec_files:
                    latest = max(spec_files, key=lambda p: p.stat().st_mtime)
                    candidate = _iso_mtime(latest)
                    if candidate and (last_updated is None or candidate > last_updated):
                        last_updated = candidate
                status = "active"
            except OSError:
                status = "error"

    return {
        "name": "Spec Files",
        "description": "Splunk .spec configuration reference files used for conf-file validation and RAG context.",
        "source_url": "documents/specs/",
        "refresh_frequency": "Manual (bundled with deployment)",
        "last_updated": last_updated,
        "status": status,
        "record_count": spec_count,
        "data_path": str(specs_dir),
    }


def _source_spl_docs() -> Dict[str, Any]:
    """Metadata for Splunk SPL command documentation."""
    docs_dir = Path("/app/documents/commands")
    doc_count: int = 0
    last_updated: Optional[str] = None
    status = "not_found"

    if docs_dir.is_dir():
        try:
            doc_files = list(docs_dir.glob("*.md")) + list(docs_dir.glob("*.txt"))
            doc_count = len(doc_files)
            if doc_files:
                latest = max(doc_files, key=lambda p: p.stat().st_mtime)
                last_updated = _iso_mtime(latest)
            status = "active" if doc_count else "empty"
        except OSError:
            status = "error"

    return {
        "name": "SPL Command Docs",
        "description": "Splunk Search Processing Language command reference documentation "
                       "ingested into the vector knowledge base.",
        "source_url": "documents/commands/",
        "refresh_frequency": "On ingestion (manual trigger or startup)",
        "last_updated": last_updated,
        "status": status,
        "record_count": doc_count,
        "data_path": str(docs_dir),
    }


def _source_vector_collections() -> Dict[str, Any]:
    """Metadata for ChromaDB vector collections."""
    collection_count: int = 0
    status = "unknown"

    try:
        from chat_app.context_builder import get_vector_store
        vector_store = get_vector_store()
        if vector_store is not None:
            collections = vector_store.list_collections()
            collection_count = len(collections) if collections else 0
            status = "active"
        else:
            status = "unavailable"
    except Exception as exc:
        logger.debug("[DATA-SOURCES] Could not query vector store: %s", exc)
        status = "unavailable"

    return {
        "name": "Vector Knowledge Base",
        "description": "ChromaDB vector collections for semantic search (SPL docs, specs, Q&A, org config).",
        "source_url": "ChromaDB (internal: chat_chroma_db:8001)",
        "refresh_frequency": "Updated during ingestion and self-learning cycles",
        "last_updated": None,  # ChromaDB doesn't expose a collection-level mtime easily
        "status": status,
        "record_count": collection_count,
    }


def _source_feedback_store() -> Dict[str, Any]:
    """Metadata for the user feedback / liked queries store."""
    feedback_path = Path("/app/feedback/liked_queries.json")
    record_count: int = 0
    status = "not_found"

    try:
        if feedback_path.is_file():
            raw = json.loads(feedback_path.read_text(encoding="utf-8"))
            record_count = len(raw) if isinstance(raw, list) else 0
            status = "active"
    except (json.JSONDecodeError, OSError):
        status = "error"

    return {
        "name": "User Feedback Store",
        "description": "Liked/disliked query pairs driving self-learning and retrieval boost scores.",
        "source_url": "feedback/liked_queries.json",
        "refresh_frequency": "Continuous (updated on every user thumbs-up/down)",
        "last_updated": _iso_mtime(feedback_path),
        "status": status,
        "record_count": record_count,
        "data_path": str(feedback_path),
    }


def _source_cribl_docs() -> Dict[str, Any]:
    """Metadata for Cribl documentation files."""
    cribl_dir = Path("/app/documents/cribl")
    doc_count: int = 0
    last_updated: Optional[str] = None
    status = "not_found"

    if cribl_dir.is_dir():
        try:
            doc_files = list(cribl_dir.rglob("*.md")) + list(cribl_dir.rglob("*.txt"))
            doc_count = len(doc_files)
            if doc_files:
                latest = max(doc_files, key=lambda p: p.stat().st_mtime)
                last_updated = _iso_mtime(latest)
            status = "active" if doc_count else "empty"
        except OSError:
            status = "error"

    return {
        "name": "Cribl Docs",
        "description": "Cribl Stream/Edge/Lake documentation ingested for Cribl-aware queries.",
        "source_url": "documents/cribl/",
        "refresh_frequency": "On ingestion (manual trigger)",
        "last_updated": last_updated,
        "status": status,
        "record_count": doc_count,
        "data_path": str(cribl_dir),
    }


def _source_pdf_documents() -> Dict[str, Any]:
    """Metadata for user-uploaded PDF documents."""
    pdf_dir = Path("/app/documents/pdfs")
    pdf_count: int = 0
    last_updated: Optional[str] = None
    status = "not_found"

    if pdf_dir.is_dir():
        try:
            pdf_files = list(pdf_dir.rglob("*.pdf"))
            pdf_count = len(pdf_files)
            if pdf_files:
                latest = max(pdf_files, key=lambda p: p.stat().st_mtime)
                last_updated = _iso_mtime(latest)
            status = "active" if pdf_count else "empty"
        except OSError:
            status = "error"

    return {
        "name": "PDF Documents",
        "description": "User-uploaded PDF files processed via Docling for ingestion into the knowledge base.",
        "source_url": "documents/pdfs/",
        "refresh_frequency": "On-demand upload",
        "last_updated": last_updated,
        "status": status,
        "record_count": pdf_count,
        "data_path": str(pdf_dir),
    }


def _source_knowledge_graph() -> Dict[str, Any]:
    """Metadata for the in-memory knowledge graph."""
    kg_cache_path = Path("/app/data/knowledge_graph.json")
    node_count: int = 0
    status = "not_found"

    try:
        if kg_cache_path.is_file():
            raw = json.loads(kg_cache_path.read_text(encoding="utf-8"))
            node_count = len(raw.get("nodes", raw.get("entities", [])))
            status = "active"
    except (json.JSONDecodeError, OSError):
        status = "error"

    return {
        "name": "Knowledge Graph",
        "description": "In-memory NetworkX entity-relationship graph for SPL commands, fields, lookups, and indexes.",
        "source_url": "data/knowledge_graph.json",
        "refresh_frequency": "Rebuilt at startup and on-demand via admin API",
        "last_updated": _iso_mtime(kg_cache_path),
        "status": status,
        "record_count": node_count,
        "data_path": str(kg_cache_path),
    }


def _source_splunk_search_history() -> Dict[str, Any]:
    """Metadata for the SPL search history training file."""
    history_path = Path("/app/data/spl_search_history.json")
    record_count: int = 0
    status = "not_found"

    try:
        if history_path.is_file():
            raw = json.loads(history_path.read_text(encoding="utf-8"))
            record_count = len(raw) if isinstance(raw, list) else 0
            status = "active"
    except (json.JSONDecodeError, OSError):
        status = "error"

    return {
        "name": "SPL Search History",
        "description": "Historical SPL searches used as training signals and self-learning context.",
        "source_url": "data/spl_search_history.json",
        "refresh_frequency": "Continuous (appended during query processing)",
        "last_updated": _iso_mtime(history_path),
        "status": status,
        "record_count": record_count,
        "data_path": str(history_path),
    }


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


def _gather_all_sources() -> List[Dict[str, Any]]:
    """Collect metadata from all registered data sources."""
    source_builders = [
        _source_splunkbase_catalog,
        _source_security_advisories,
        _source_splunk_versions,
        _source_breaking_changes,
        _source_org_repository,
        _source_spec_files,
        _source_spl_docs,
        _source_vector_collections,
        _source_feedback_store,
        _source_cribl_docs,
        _source_pdf_documents,
        _source_knowledge_graph,
        _source_splunk_search_history,
    ]

    sources: List[Dict[str, Any]] = []
    for builder in source_builders:
        try:
            sources.append(builder())
        except Exception as exc:
            logger.warning("[DATA-SOURCES] Builder %s failed: %s", builder.__name__, exc)
    return sources


def _compute_summary(sources: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute a summary health snapshot across all sources."""
    status_counts: Dict[str, int] = {}
    for source in sources:
        status = source.get("status", "unknown")
        status_counts[status] = status_counts.get(status, 0) + 1

    active_count = status_counts.get("active", 0) + status_counts.get("bundled", 0)
    total_count = len(sources)
    unhealthy = status_counts.get("error", 0) + status_counts.get("not_found", 0)

    return {
        "total_sources": total_count,
        "active": active_count,
        "unavailable": status_counts.get("unavailable", 0),
        "not_found": status_counts.get("not_found", 0),
        "error": status_counts.get("error", 0),
        "health": "ok" if unhealthy == 0 else ("degraded" if unhealthy < total_count else "down"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@data_sources_router.get(
    "/data-sources",
    summary="List all data sources and refresh status",
    response_description="List of data sources with metadata, refresh frequency, and record counts.",
)
async def get_data_sources() -> Dict[str, Any]:
    """
    Return metadata for every data source the system pulls from.

    Includes: Splunkbase catalog, security advisories, Splunk versions,
    breaking changes DB, org repository, spec files, SPL docs, vector
    collections, feedback store, Cribl docs, PDFs, knowledge graph, and
    SPL search history.
    """
    sources = _gather_all_sources()
    return {
        "sources": sources,
        "summary": _compute_summary(sources),
    }


@data_sources_router.get(
    "/data-sources/{source_name}",
    summary="Get metadata for a specific data source by name",
)
async def get_data_source_by_name(source_name: str) -> Dict[str, Any]:
    """
    Return metadata for a single data source matched by name (case-insensitive).

    Args:
        source_name: Partial or full data source name, e.g. "splunkbase", "advisories".
    """
    sources = _gather_all_sources()
    name_lower = source_name.lower()
    matches = [s for s in sources if name_lower in s.get("name", "").lower()]
    if not matches:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=404,
            detail=f"No data source matching '{source_name}'. "
                   f"Available: {[s['name'] for s in sources]}",
        )
    return matches[0] if len(matches) == 1 else {"matches": matches}
