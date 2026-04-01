"""
Self-Learning Ingestion — Vector store ingestion and cross-collection consolidation.

Extracted from self_learning.py for size management.
self_learning.py re-exports all public names.

Provides:
- ingest_qa_pairs_to_vectorstore
- _extract_cross_ref_terms, _query_collection_for_term, consolidate_cross_collection_insights
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import Dict, List

from chat_app.self_learning_models import QAPair  # noqa: F401

logger = logging.getLogger(__name__)

async def ingest_qa_pairs_to_vectorstore(
    qa_pairs: List[QAPair],
    vector_store,
    collection_name: str = "self_learned_qa",
) -> int:
    """
    Ingest generated Q&A pairs into the vector store for retrieval.

    Each pair is stored as a document with the question as the query text
    and the answer embedded in metadata.  Uses OllamaEmbeddings (mxbai-embed-large)
    so embeddings are consistent with the search pipeline.

    Throttled to avoid starving the chat pipeline of Ollama/CPU resources.
    Uses LEARNING_BATCH_SIZE (default 20) and sleeps LEARNING_BATCH_DELAY_S
    (default 1.0s) between embedding batches.
    """
    if not qa_pairs or not vector_store:
        return 0

    # Build the Ollama embedder to match the search pipeline
    embedder = None
    try:
        from chat_app.vectorstore import get_embeddings_model
        embedder = get_embeddings_model()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[SELF-LEARN] Could not init OllamaEmbeddings, "
                       "falling back to ChromaDB default: %s", exc)

    # Throttling: smaller batches + sleep to keep chat/UI responsive
    batch_size = int(os.environ.get("LEARNING_BATCH_SIZE", "20"))
    batch_delay = float(os.environ.get("LEARNING_BATCH_DELAY_S", "1.0"))

    ingested = 0
    try:
        # vector_store may be a Langchain Chroma wrapper — extract the raw client
        client = getattr(vector_store, "_client", None) or vector_store
        collection = client.get_or_create_collection(collection_name)

        # Clean up stale entries: delete old Q&A for source files that have new pairs
        # This prevents accumulation when questions/answers change for a source
        source_files_in_batch = {p.source_file for p in qa_pairs if p.source_file}
        for src in source_files_in_batch:
            try:
                existing = collection.get(where={"source": src}, limit=1)
                if existing and existing.get("ids"):
                    collection.delete(where={"source": src})
                    logger.debug(f"[SELF-LEARN] Cleared old Q&A for source: {src}")
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as del_exc:
                logger.debug(f"[SELF-LEARN] Stale cleanup failed for {src}: {del_exc}")

        batch_ids = []
        batch_docs = []
        batch_meta = []

        for pair in qa_pairs:
            doc_id = hashlib.sha256(f"{pair.question}:{pair.source_file}".encode()).hexdigest()
            doc_text = f"Q: {pair.question}\nA: {pair.answer}"

            batch_ids.append(doc_id)
            batch_docs.append(doc_text)
            batch_meta.append({
                "source": pair.source_file,
                "source_type": pair.source_type,
                "topic": pair.topic,
                "confidence": pair.confidence,
                "kind": "self_learned_qa",
            })

            # Batch upsert every N items (throttled)
            if len(batch_ids) >= batch_size:
                upsert_kwargs = dict(
                    ids=batch_ids,
                    documents=batch_docs,
                    metadatas=batch_meta,
                )
                if embedder:
                    try:
                        # Run blocking Ollama embed call in thread pool
                        # so the async event loop stays responsive for chat/API
                        loop = asyncio.get_running_loop()
                        _docs = list(batch_docs)
                        upsert_kwargs["embeddings"] = await loop.run_in_executor(
                            None, embedder.embed_documents, _docs
                        )
                    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as emb_exc:
                        logger.warning("[SELF-LEARN] Embedding batch failed: %s", emb_exc)
                collection.upsert(**upsert_kwargs)
                ingested += len(batch_ids)
                batch_ids, batch_docs, batch_meta = [], [], []
                # Yield to event loop so chat/API requests can be served
                await asyncio.sleep(batch_delay)

        # Final batch
        if batch_ids:
            upsert_kwargs = dict(
                ids=batch_ids,
                documents=batch_docs,
                metadatas=batch_meta,
            )
            if embedder:
                try:
                    loop = asyncio.get_running_loop()
                    _docs = list(batch_docs)
                    upsert_kwargs["embeddings"] = await loop.run_in_executor(
                        None, embedder.embed_documents, _docs
                    )
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as emb_exc:
                    logger.warning("[SELF-LEARN] Embedding final batch failed: %s", emb_exc)
            collection.upsert(**upsert_kwargs)
            ingested += len(batch_ids)

        logger.info(f"[SELF-LEARN] Ingested {ingested} Q&A pairs to '{collection_name}'")

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[SELF-LEARN] Q&A ingestion failed: {exc}")

    return ingested


# ---------------------------------------------------------------------------
# Cross-Collection Consolidation
# ---------------------------------------------------------------------------

_CONSOLIDATION_LAST_RUN: float = 0.0

_CROSS_REF_COLLECTIONS = [
    "spl_commands_mxbai",
    "specs_mxbai_embed_large_v3",
    "assistant_memory_mxbai_v2",
    "org_repo_mxbai",
]


def _extract_cross_ref_terms(qa_pairs: List[QAPair]) -> Dict[str, List[QAPair]]:
    """Extract SPL commands, index names, saved search names, stanza names
    from existing Q&A pairs. Returns only terms that appear in 2+ different
    source_type values (cross-collection candidates)."""
    term_map: Dict[str, List[QAPair]] = {}

    # Patterns for interesting entity extraction
    spl_cmd_re = re.compile(r'\b(stats|eval|where|search|table|rename|dedup|sort|head|tail|rex|spath|lookup|inputlookup|outputlookup|eventstats|streamstats|transaction|chart|timechart|tstats|collect|fields|fillnull|mvexpand|join|append|bin|bucket|rare|top|addtotals|foreach|replace|convert|predict|anomalydetection|cluster|kmeans|datamodel|mcatalog|mstats|union)\b', re.IGNORECASE)
    index_re = re.compile(r'\bindex\s*=\s*"?([a-zA-Z0-9_*-]+)"?', re.IGNORECASE)
    stanza_re = re.compile(r'\[([a-zA-Z0-9_:/.* -]+)\]')
    saved_search_re = re.compile(r'(?:saved\s*search|savedsearch|alert|report)\s*[:\s]+["\']?([A-Za-z0-9_ -]+)', re.IGNORECASE)

    for pair in qa_pairs:
        text = f"{pair.question} {pair.answer}"
        found_terms = set()

        for m in spl_cmd_re.finditer(text):
            found_terms.add(m.group(1).lower())
        for m in index_re.finditer(text):
            found_terms.add(m.group(1).lower())
        for m in stanza_re.finditer(text):
            val = m.group(1).strip()
            if len(val) >= 3 and not val.startswith("http"):
                found_terms.add(val.lower())
        for m in saved_search_re.finditer(text):
            val = m.group(1).strip()
            if len(val) >= 4:
                found_terms.add(val.lower())

        for term in found_terms:
            term_map.setdefault(term, []).append(pair)

    # Keep only terms referenced from 2+ different source_types
    cross_refs = {}
    for term, pairs in term_map.items():
        source_types = {p.source_type for p in pairs if p.source_type}
        if len(source_types) >= 2:
            cross_refs[term] = pairs
    return cross_refs


def _query_collection_for_term(vector_store, collection_name: str, term: str, n_results: int = 3) -> List[str]:
    """Query a ChromaDB collection for documents containing a term.
    Uses where_document $contains — zero embedding cost."""
    try:
        client = getattr(vector_store, "_client", None) or vector_store
        collection = client.get_collection(collection_name)
        results = collection.get(
            where_document={"$contains": term},
            limit=n_results,
        )
        return results.get("documents", []) if results else []
    except Exception as _exc:  # broad catch — resilience against all failures
        return []


async def consolidate_cross_collection_insights(
    all_qa_pairs: List[QAPair],
    vector_store,
    max_insights: int = 50,
) -> List[QAPair]:
    """Find entities shared across collections and generate bridging Q&A pairs."""
    cross_refs = _extract_cross_ref_terms(all_qa_pairs)
    if not cross_refs:
        return []

    insights: List[QAPair] = []
    count = 0
    for term, source_pairs in cross_refs.items():
        if len(insights) >= max_insights:
            break

        # Find which collections have content about this term
        collection_hits: Dict[str, List[str]] = {}
        for coll_name in _CROSS_REF_COLLECTIONS:
            docs = _query_collection_for_term(vector_store, coll_name, term)
            if docs:
                collection_hits[coll_name] = docs if isinstance(docs[0], str) else [str(d) for d in docs]

        if len(collection_hits) < 2:
            continue

        # Build a bridging Q&A pair
        coll_labels = ", ".join(sorted(collection_hits.keys()))
        sorted({p.source_type for p in source_pairs if p.source_type})
        context_snippets = []
        for coll_name, docs in collection_hits.items():
            for doc in docs[:1]:
                snippet = str(doc)[:200].strip()
                if snippet:
                    context_snippets.append(f"[{coll_name}] {snippet}")

        answer_parts = [
            f"The term '{term}' appears across multiple knowledge sources ({coll_labels}).",
        ]
        if context_snippets:
            answer_parts.append("Key references:")
            answer_parts.extend(f"- {s}" for s in context_snippets[:3])

        insights.append(QAPair(
            question=f"How is '{term}' referenced across different knowledge areas?",
            answer="\n".join(answer_parts),
            source_file=f"cross_collection:{','.join(sorted(collection_hits.keys()))}",
            source_type="cross_collection_insight",
            confidence=0.65,
            generated_at=datetime.now(timezone.utc).isoformat(),
            topic=f"cross_ref_{term}",
        ))

        count += 1
        if count % 10 == 0:
            await asyncio.sleep(0.5)

    logger.info(f"[SELF-LEARN] Cross-collection consolidation: {len(insights)} insights from {len(cross_refs)} candidate terms")
    return insights
