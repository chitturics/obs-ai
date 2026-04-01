"""
Knowledge Base Management Skill — Search knowledge, ingest documents,
list collections, and track learning statistics.

Each function is a standalone action handler invoked by the SkillsManager.
"""
import asyncio
import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful imports from the existing codebase
# ---------------------------------------------------------------------------
try:
    from chat_app.self_learning import (
        LearningReport,
        run_learning_cycle,
        generate_qa_pairs_from_directory,
        get_cached_boost_scores,
    )
    _SELF_LEARNING_AVAILABLE = True
except ImportError:
    _SELF_LEARNING_AVAILABLE = False
    logger.debug("chat_app.self_learning not available — learning stats use fallback")

try:
    from shared.conf_parser import (
        parse_conf_file,
        parse_conf_file_advanced,
        chunk_conf_file,
        extract_app_metadata,
    )
    _CONF_PARSER_AVAILABLE = True
except ImportError:
    _CONF_PARSER_AVAILABLE = False
    logger.debug("shared.conf_parser not available — .conf ingestion uses basic fallback")

try:
    import chromadb
    _CHROMADB_AVAILABLE = True
except ImportError:
    _CHROMADB_AVAILABLE = False
    logger.debug("chromadb not available — collection listing and direct search disabled")

try:
    from chat_app.vectorstore_search import search_similar_chunks_parallel
    _VECTOR_SEARCH_AVAILABLE = True
except ImportError:
    _VECTOR_SEARCH_AVAILABLE = False
    logger.debug("chat_app.vectorstore_search not available — vector search disabled")

try:
    from chat_app.document_ingestor import ingest_file
    _DOCUMENT_INGESTOR_AVAILABLE = True
except ImportError:
    _DOCUMENT_INGESTOR_AVAILABLE = False
    logger.debug("chat_app.document_ingestor not available — document ingestion disabled")

try:
    from chat_app.vectorstore import COLLECTION_NAME, DEFAULT_EMBED_MODEL
    _VECTORSTORE_AVAILABLE = True
except ImportError:
    _VECTORSTORE_AVAILABLE = False
    COLLECTION_NAME = "assistant_memory"
    DEFAULT_EMBED_MODEL = "mxbai-embed-large"
    logger.debug("chat_app.vectorstore not available — using default collection names")

try:
    from chat_app.settings import get_settings
    _SETTINGS_AVAILABLE = True
except ImportError:
    _SETTINGS_AVAILABLE = False
    logger.debug("chat_app.settings not available — using defaults")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_chroma_client():
    """Get a ChromaDB client using environment settings."""
    if not _CHROMADB_AVAILABLE:
        return None

    chroma_host = os.getenv("CHROMA_HOST", "localhost")
    chroma_port = int(os.getenv("CHROMA_PORT", "8100"))

    try:
        client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
        client.heartbeat()
        return client
    except Exception:
        pass

    # Fallback: try persistent client
    chroma_dir = os.getenv("CHROMA_DIR", "./chroma_data")
    try:
        client = chromadb.PersistentClient(path=chroma_dir)
        return client
    except Exception:
        return None


def _detect_doc_type(filepath: str) -> str:
    """Detect document type from file extension."""
    ext = Path(filepath).suffix.lower()
    type_map = {
        ".pdf": "pdf",
        ".html": "html",
        ".htm": "html",
        ".json": "json",
        ".csv": "csv",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".txt": "text",
        ".md": "markdown",
        ".conf": "splunk_conf",
        ".log": "text",
    }
    return type_map.get(ext, "text")


def _run_async(coro):
    """Run an async coroutine from a sync context, handling nested event loops."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(asyncio.run, coro)
            return future.result(timeout=30)
    else:
        return asyncio.run(coro)


def _parse_conf_simple(filepath: Path) -> Dict[str, Dict[str, str]]:
    """Simple .conf parser fallback when shared.conf_parser is unavailable."""
    stanzas: Dict[str, Dict[str, str]] = {}
    current_stanza = "default"
    stanzas[current_stanza] = {}

    try:
        with open(filepath, "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    current_stanza = line[1:-1]
                    stanzas.setdefault(current_stanza, {})
                elif "=" in line:
                    key, _, value = line.partition("=")
                    stanzas[current_stanza][key.strip()] = value.strip()
    except OSError:
        pass

    return stanzas


def _chunk_text_simple(text: str, chunk_size: int = 500, overlap: int = 100) -> List[str]:
    """Simple text chunker fallback for non-.conf documents."""
    if len(text) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end]
        chunks.append(chunk)
        start = end - overlap
    return chunks


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def search_knowledge(query: str, collection: Optional[str] = None) -> str:
    """
    Search the knowledge base using semantic similarity.

    Queries vector collections for relevant documents, SPL examples,
    and configuration knowledge.

    Args:
        query: The search query in natural language.
        collection: Optional collection name to restrict the search to.

    Returns:
        JSON string with search results.
    """
    if not query or not query.strip():
        return json.dumps({
            "status": "error",
            "error": "Query cannot be empty",
        })

    now = datetime.now(timezone.utc).isoformat()

    # Use the full vector search pipeline if available
    if _VECTOR_SEARCH_AVAILABLE:
        try:
            start = time.monotonic()
            results = _run_async(search_similar_chunks_parallel(
                query=query,
                collection_name=collection,
            ))
            elapsed_ms = (time.monotonic() - start) * 1000

            formatted_results = []
            for doc in results:
                formatted_results.append({
                    "content": doc.page_content if hasattr(doc, "page_content") else str(doc),
                    "metadata": doc.metadata if hasattr(doc, "metadata") else {},
                    "score": getattr(doc, "score", None),
                })

            return json.dumps({
                "status": "ok",
                "timestamp": now,
                "query": query,
                "collection": collection or "all",
                "results_count": len(formatted_results),
                "search_latency_ms": round(elapsed_ms, 2),
                "results": formatted_results[:10],
            }, indent=2)
        except Exception as exc:
            logger.warning(f"Vector search failed: {exc}")

    # Fallback: direct ChromaDB query
    if _CHROMADB_AVAILABLE:
        client = _get_chroma_client()
        if client:
            try:
                target_collection = collection or COLLECTION_NAME
                col = client.get_collection(target_collection)

                start = time.monotonic()
                results = col.query(
                    query_texts=[query],
                    n_results=5,
                )
                elapsed_ms = (time.monotonic() - start) * 1000

                formatted_results = []
                if results and results.get("documents"):
                    for i, doc in enumerate(results["documents"][0]):
                        meta = results["metadatas"][0][i] if results.get("metadatas") else {}
                        distance = results["distances"][0][i] if results.get("distances") else None
                        formatted_results.append({
                            "content": doc,
                            "metadata": meta,
                            "distance": distance,
                        })

                return json.dumps({
                    "status": "ok",
                    "timestamp": now,
                    "query": query,
                    "collection": target_collection,
                    "results_count": len(formatted_results),
                    "search_latency_ms": round(elapsed_ms, 2),
                    "results": formatted_results,
                }, indent=2)
            except Exception as exc:
                logger.warning(f"Direct ChromaDB query failed: {exc}")

    return json.dumps({
        "status": "unavailable",
        "timestamp": now,
        "query": query,
        "error": "No vector search backend is available. Ensure ChromaDB is running and chat_app.vectorstore_search is importable.",
        "results": [],
    }, indent=2)


def ingest_document(path: str, doc_type: Optional[str] = None) -> str:
    """
    Ingest a document into the knowledge base.

    Supports markdown, .conf, and other text formats. Chunks and
    embeds the content for semantic retrieval.  For .conf files the
    shared.conf_parser is used to produce stanza-aware chunks with
    rich app metadata.

    Args:
        path: File path of the document to ingest.
        doc_type: Optional document type hint (markdown, splunk_conf, text, etc.).
                  Auto-detected from extension if omitted.

    Returns:
        JSON string with ingestion results.
    """
    if not path or not path.strip():
        return json.dumps({
            "status": "error",
            "error": "Path cannot be empty",
        })

    now = datetime.now(timezone.utc).isoformat()

    # Validate file exists
    filepath = Path(path)
    if not filepath.exists():
        return json.dumps({
            "status": "error",
            "error": f"File not found: {path}",
        })
    if not filepath.is_file():
        return json.dumps({
            "status": "error",
            "error": f"Path is not a file: {path}",
        })

    # Detect document type
    detected_type = doc_type or _detect_doc_type(path)

    # -------------------------------------------------------------------
    # .conf files — use shared.conf_parser for stanza-aware chunking
    # -------------------------------------------------------------------
    if detected_type == "splunk_conf":
        try:
            content = filepath.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            return json.dumps({
                "status": "error",
                "timestamp": now,
                "path": path,
                "error": f"Could not read file: {exc}",
            }, indent=2)

        chunks: List[Dict[str, Any]] = []

        if _CONF_PARSER_AVAILABLE:
            try:
                raw_chunks = chunk_conf_file(
                    content,
                    file_path=path,
                    max_chunk_size=500,
                    chunk_overlap=100,
                )
                for chunk_text, meta in raw_chunks:
                    chunks.append({"text": chunk_text, "metadata": meta})
            except Exception as exc:
                logger.warning(f"conf_parser chunking failed, using fallback: {exc}")

        # Fallback: simple stanza-based split
        if not chunks:
            stanzas = _parse_conf_simple(filepath)
            for stanza_name, settings in stanzas.items():
                if not settings:
                    continue
                body = "\n".join(f"{k} = {v}" for k, v in settings.items())
                chunk_text = f"[{stanza_name}]\n{body}"
                chunks.append({
                    "text": chunk_text,
                    "metadata": {
                        "stanza": stanza_name,
                        "filename": filepath.name,
                        "type": "conf_complete",
                    },
                })

        # Store chunks in ChromaDB if available
        stored = 0
        if _CHROMADB_AVAILABLE and chunks:
            client = _get_chroma_client()
            if client:
                try:
                    col = client.get_or_create_collection(COLLECTION_NAME)
                    ids = [f"{filepath.stem}_{i}" for i in range(len(chunks))]
                    documents = [c["text"] for c in chunks]
                    metadatas = [c["metadata"] for c in chunks]
                    col.upsert(ids=ids, documents=documents, metadatas=metadatas)
                    stored = len(chunks)
                except Exception as exc:
                    logger.warning(f"ChromaDB upsert failed: {exc}")

        return json.dumps({
            "status": "ok",
            "timestamp": now,
            "path": path,
            "doc_type": detected_type,
            "title": filepath.name,
            "chunks_created": len(chunks),
            "chunks_stored": stored,
            "parser": "conf_parser" if (_CONF_PARSER_AVAILABLE and chunks) else "fallback",
        }, indent=2)

    # -------------------------------------------------------------------
    # Markdown and other text — use document_ingestor when available
    # -------------------------------------------------------------------
    if _DOCUMENT_INGESTOR_AVAILABLE:
        try:
            start = time.monotonic()
            result = _run_async(ingest_file(path))
            elapsed_ms = (time.monotonic() - start) * 1000

            return json.dumps({
                "status": "ok",
                "timestamp": now,
                "path": path,
                "doc_type": detected_type,
                "source_type": result.source_type if hasattr(result, "source_type") else detected_type,
                "title": result.title if hasattr(result, "title") else filepath.name,
                "chunks_created": result.chunk_count if hasattr(result, "chunk_count") else 0,
                "fingerprint": result.fingerprint if hasattr(result, "fingerprint") else "",
                "error": result.error if hasattr(result, "error") else None,
                "ingestion_latency_ms": round(elapsed_ms, 2),
            }, indent=2)
        except Exception as exc:
            logger.warning(f"Document ingestor failed: {exc}")

    # -------------------------------------------------------------------
    # Fallback: read, chunk, and store manually
    # -------------------------------------------------------------------
    try:
        content = filepath.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return json.dumps({
            "status": "error",
            "timestamp": now,
            "path": path,
            "error": f"Could not read file: {exc}",
        }, indent=2)

    text_chunks = _chunk_text_simple(content, chunk_size=500, overlap=100)

    stored = 0
    if _CHROMADB_AVAILABLE and text_chunks:
        client = _get_chroma_client()
        if client:
            try:
                col = client.get_or_create_collection(COLLECTION_NAME)
                ids = [f"{filepath.stem}_{i}" for i in range(len(text_chunks))]
                documents = text_chunks
                metadatas = [{"filename": filepath.name, "doc_type": detected_type, "chunk_index": i}
                             for i in range(len(text_chunks))]
                col.upsert(ids=ids, documents=documents, metadatas=metadatas)
                stored = len(text_chunks)
            except Exception as exc:
                logger.warning(f"ChromaDB upsert failed: {exc}")

    return json.dumps({
        "status": "ok",
        "timestamp": now,
        "path": path,
        "doc_type": detected_type,
        "title": filepath.name,
        "chunks_created": len(text_chunks),
        "chunks_stored": stored,
        "parser": "fallback_text",
        "note": "Install chat_app.document_ingestor for richer ingestion support.",
    }, indent=2)


def list_collections() -> str:
    """
    List all available ChromaDB vector collections with document counts
    and metadata.

    Returns:
        JSON string with collection details.
    """
    now = datetime.now(timezone.utc).isoformat()

    if not _CHROMADB_AVAILABLE:
        return json.dumps({
            "status": "unavailable",
            "timestamp": now,
            "error": "chromadb package is not installed",
            "collections": [],
        }, indent=2)

    client = _get_chroma_client()
    if not client:
        return json.dumps({
            "status": "unavailable",
            "timestamp": now,
            "error": "Could not connect to ChromaDB. Check CHROMA_HOST and CHROMA_PORT.",
            "collections": [],
        }, indent=2)

    try:
        collections_list = client.list_collections()
        collections: List[Dict[str, Any]] = []
        total_documents = 0

        for col in collections_list:
            col_name = col.name if hasattr(col, "name") else str(col)
            try:
                collection = client.get_collection(col_name)
                count = collection.count()
                total_documents += count

                # Get a sample of metadata to show schema
                meta_keys: List[str] = []
                try:
                    peek = collection.peek(limit=1)
                    sample_meta = peek.get("metadatas", [[]])[0]
                    if sample_meta:
                        if isinstance(sample_meta, list) and sample_meta:
                            meta_keys = list(sample_meta[0].keys())
                        elif isinstance(sample_meta, dict):
                            meta_keys = list(sample_meta.keys())
                except Exception:
                    pass

                collections.append({
                    "name": col_name,
                    "document_count": count,
                    "metadata_fields": meta_keys[:20],
                    "is_default": col_name == COLLECTION_NAME,
                })
            except Exception as exc:
                collections.append({
                    "name": col_name,
                    "document_count": -1,
                    "error": str(exc),
                })

        return json.dumps({
            "status": "ok",
            "timestamp": now,
            "total_collections": len(collections),
            "total_documents": total_documents,
            "default_collection": COLLECTION_NAME,
            "embed_model": DEFAULT_EMBED_MODEL,
            "collections": collections,
        }, indent=2)
    except Exception as exc:
        return json.dumps({
            "status": "error",
            "timestamp": now,
            "error": f"Failed to list collections: {str(exc)}",
            "collections": [],
        }, indent=2)


def get_learning_stats() -> str:
    """
    Get self-learning pipeline statistics including episode counts,
    success rates, confidence trends, and improvement trajectory.

    Uses chat_app.self_learning when available, falling back to local
    file-based stats collection.

    Returns:
        JSON string with learning statistics.
    """
    now = datetime.now(timezone.utc).isoformat()

    stats: Dict[str, Any] = {
        "episodes_total": 0,
        "episodes_successful": 0,
        "episodes_failed": 0,
        "success_rate": 0.0,
        "avg_confidence": 0.0,
        "qa_pairs_generated": 0,
        "facts_learned": 0,
        "prompts_refined": 0,
        "semantic_facts": 0,
        "boost_scores": {},
        "topics_covered": [],
        "improvement_trend": "unknown",
    }

    # -------------------------------------------------------------------
    # Try chat_app.self_learning for authoritative stats
    # -------------------------------------------------------------------
    if _SELF_LEARNING_AVAILABLE:
        # Retrieve cached boost scores (lightweight, no DB needed)
        try:
            stats["boost_scores"] = get_cached_boost_scores()
        except Exception as exc:
            logger.debug(f"Failed to get cached boost scores: {exc}")

        # Read the latest learning report from disk
        report_dir = Path(os.getenv("LEARNING_REPORT_DIR", "data/learning_reports"))
        if report_dir.is_dir():
            try:
                report_files = sorted(report_dir.glob("*.json"), reverse=True)
                if report_files:
                    latest_report = json.loads(report_files[0].read_text(encoding="utf-8"))
                    stats["qa_pairs_generated"] = latest_report.get("qa_pairs_generated", 0)
                    stats["facts_learned"] = latest_report.get("facts_learned", 0)
                    stats["prompts_refined"] = latest_report.get("prompts_refined", 0)
                    stats["topics_covered"] = latest_report.get("topics_covered", [])
                    stats["last_cycle_timestamp"] = latest_report.get("timestamp", "")
                    stats["last_cycle_duration_s"] = latest_report.get("duration_seconds", 0.0)
                    stats["answers_reassessed"] = latest_report.get("answers_reassessed", 0)
                    stats["answers_improved"] = latest_report.get("answers_improved", 0)
                    stats["total_reports"] = len(report_files)
            except Exception as exc:
                logger.debug(f"Failed to read learning reports: {exc}")

    # -------------------------------------------------------------------
    # Count vector store documents as a proxy for knowledge breadth
    # -------------------------------------------------------------------
    if _CHROMADB_AVAILABLE:
        client = _get_chroma_client()
        if client:
            try:
                total_docs = 0
                for col in client.list_collections():
                    col_name = col.name if hasattr(col, "name") else str(col)
                    try:
                        collection = client.get_collection(col_name)
                        total_docs += collection.count()
                    except Exception:
                        pass
                stats["semantic_facts"] = total_docs
            except Exception:
                pass

    # -------------------------------------------------------------------
    # Check for episodic memory data on disk
    # -------------------------------------------------------------------
    episodic_dir = Path(os.getenv("EPISODIC_MEMORY_DIR", "data/episodic"))
    if episodic_dir.is_dir():
        try:
            episode_files = list(episodic_dir.glob("*.json"))
            stats["episodes_total"] = len(episode_files)

            # Sample a batch to estimate success/failure rates
            successes = 0
            confidences: List[float] = []
            sample_size = min(len(episode_files), 100)
            for ep_file in episode_files[:sample_size]:
                try:
                    data = json.loads(ep_file.read_text(encoding="utf-8"))
                    if data.get("success", False):
                        successes += 1
                    conf = data.get("confidence", 0)
                    if conf:
                        confidences.append(conf)
                except Exception:
                    pass

            if sample_size > 0:
                stats["episodes_successful"] = int(successes * len(episode_files) / sample_size)
                stats["episodes_failed"] = stats["episodes_total"] - stats["episodes_successful"]
                stats["success_rate"] = round(successes / sample_size, 3)
            if confidences:
                stats["avg_confidence"] = round(sum(confidences) / len(confidences), 3)

            # Estimate trend from recent vs. older episodes
            if len(episode_files) >= 20:
                try:
                    recent = episode_files[-10:]
                    older = episode_files[:10]
                    recent_conf = []
                    older_conf = []
                    for ep in recent:
                        try:
                            d = json.loads(ep.read_text(encoding="utf-8"))
                            c = d.get("confidence", 0)
                            if c:
                                recent_conf.append(c)
                        except Exception:
                            pass
                    for ep in older:
                        try:
                            d = json.loads(ep.read_text(encoding="utf-8"))
                            c = d.get("confidence", 0)
                            if c:
                                older_conf.append(c)
                        except Exception:
                            pass

                    if recent_conf and older_conf:
                        recent_avg = sum(recent_conf) / len(recent_conf)
                        older_avg = sum(older_conf) / len(older_conf)
                        if recent_avg > older_avg + 0.02:
                            stats["improvement_trend"] = "improving"
                        elif recent_avg < older_avg - 0.02:
                            stats["improvement_trend"] = "declining"
                        else:
                            stats["improvement_trend"] = "stable"
                except Exception:
                    pass
        except Exception:
            pass

    # Determine data source for transparency
    source_note = []
    if _SELF_LEARNING_AVAILABLE:
        source_note.append("self_learning")
    if _CHROMADB_AVAILABLE:
        source_note.append("chromadb")
    if episodic_dir.is_dir():
        source_note.append("episodic_memory")

    return json.dumps({
        "status": "ok",
        "timestamp": now,
        "data_sources": source_note or ["none"],
        **stats,
    }, indent=2)


# ---------------------------------------------------------------------------
# Cleanup hook (called by SkillsManager on uninstall)
# ---------------------------------------------------------------------------

def cleanup():
    """Release any resources held by this skill."""
    logger.debug("knowledge_base skill cleaned up")
