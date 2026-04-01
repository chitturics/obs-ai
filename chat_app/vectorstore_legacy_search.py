"""Legacy sequential search implementation for vectorstore.

Extracted from vectorstore.py. This is the compatibility fallback used when the
parallelized search (vectorstore_search.py) is unavailable.

Called by vectorstore.search_similar_chunks() when the parallel path fails.
"""
import re
import logging
from typing import Dict, List, Optional

from langchain_chroma import Chroma
from ollama import ResponseError

logger = logging.getLogger(__name__)


def _token_overlap_score(text: str, query_tokens: set[str]) -> int:
    low = text.lower()
    return sum(1 for t in query_tokens if t and t in low)


def search_similar_chunks_legacy(
    store: Chroma,
    query: str,
    k: int = 4,
    profile: str = None,
    weight_map_override: Optional[Dict[str, int]] = None,
    user_settings: Optional[Dict] = None,
    get_surrounding_chunks_func=None,
    public_url_mapper=None,
) -> list[dict]:
    """Legacy sequential search across all configured Chroma collections.

    This is the fallback when vectorstore_search.search_similar_chunks_parallel
    is unavailable. Signature matches the public search_similar_chunks API.
    """
    # Late imports to avoid circular dependency — vectorstore_legacy_search
    # must not import from vectorstore at module load time.
    from chat_app.vectorstore_init import ensure_secondary_store, ensure_feedback_store
    from chat_app.vectorstore_collections import ensure_additional_stores

    if not store or not query:
        logger.warning("[VECTORSTORE] Empty store or query, returning empty results")
        return []

    user_settings = user_settings or {}

    try:
        from profiles import get_retrieval_strategy, get_fetch_count, detect_profile_from_query
        if profile is None:
            detected = detect_profile_from_query(query)
            if detected:
                logger.info(f"[VECTORSTORE] Auto-detected profile: {detected}")
                profile = detected
        strategy = get_retrieval_strategy(profile)
        top_n_per_collection = strategy.top_n_per_collection
        keep_per_collection = strategy.keep_per_collection
        weight_map = strategy.weight_map
        use_profile_strategy = True
        logger.info(f"[VECTORSTORE] Using profile strategy: {strategy.description}")
    except ImportError:
        logger.warning("profiles.py not available, using default strategy")
        top_n_per_collection = 30
        keep_per_collection = 15
        weight_map = None
        use_profile_strategy = False
        strategy = None

    if weight_map_override:
        weight_map = weight_map_override
        logger.info(f"[VECTORSTORE] Using weight map override: {weight_map}")

    def _search(s: Chroma, collection_name: str = "unknown", k_local: int = 10) -> List:
        try:
            logger.info(f"[VECTORSTORE] Searching {collection_name} with k={k_local}")
            try:
                results_with_scores = s.similarity_search_with_score(query, k=k_local)
                docs = []
                for doc, distance in results_with_scores:
                    similarity = 1.0 / (1.0 + distance)
                    if not hasattr(doc, "metadata") or doc.metadata is None:
                        doc.metadata = {}
                    doc.metadata["_similarity_score"] = similarity
                    docs.append(doc)
                logger.info(f"[VECTORSTORE] {collection_name} returned {len(docs)} results with scores")
                return docs
            except (AttributeError, TypeError):
                res = s.similarity_search(query, k=k_local)
                logger.info(f"[VECTORSTORE] {collection_name} returned {len(res)} raw results (no scores)")
                return res
        except ResponseError as exc:
            logger.error(f"[VECTORSTORE] similarity_search failed on {collection_name}: {exc}")
            return []
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.error(f"[VECTORSTORE] similarity_search unexpected error on {collection_name}: {exc}")
            return []

    query_lower = query.lower()
    prefers_conf = (
        ".conf" in query_lower
        or "configuration" in query_lower
        or "savedsearch" in query_lower
        or "saved search" in query_lower
        or "saved_search" in query_lower
        or "stanza" in query_lower
        or any(f"{cf}" in query_lower for cf in [
            "inputs.conf", "outputs.conf", "props.conf", "transforms.conf",
            "savedsearches", "macros", "indexes.conf", "server.conf",
            "authentication.conf", "authorize.conf", "limits.conf",
        ])
    )
    role_keywords = {"indexer", "search head", "searchhead", "forwarder", "deployment server", "cluster", "standalone"}
    role_hits = {rk for rk in role_keywords if rk in query_lower}
    version_tokens = [tok for tok in query_lower.replace("version", " ").split() if tok and tok[0].isdigit()]
    query_tokens = {tok for tok in re.split(r"[^a-z0-9]+", query_lower) if len(tok) >= 3}

    repo_keywords = {"repo", "repository", "our", "my", "organization", "org", "custom", "local"}
    is_repo_query = any(kw in query_lower for kw in repo_keywords)

    conf_file_pattern = r'\b\w+\.conf\b'
    has_conf_reference = bool(re.search(conf_file_pattern, query_lower))

    spl_keywords = {"timechart", "stats", "search", "eval", "where", "rename", "table", "chart", "tstats"}
    has_spl_reference = any(cmd in query_lower for cmd in spl_keywords)

    feedback = ensure_feedback_store()
    secondary = ensure_secondary_store()
    additional = ensure_additional_stores()

    logger.info(f"[VECTORSTORE] Query type: {'CONFIG' if prefers_conf else 'GENERAL'}, "
                f"Repo-centric: {is_repo_query}, Conf: {has_conf_reference}, SPL: {has_spl_reference}")

    additional_names = []
    for extra in additional:
        try:
            coll_obj = getattr(extra, "_collection", None)
            additional_names.append(coll_obj.name if coll_obj else f"additional_{len(additional_names)+1}")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            additional_names.append(f"additional_{len(additional_names)+1}")

    repo_fetch_multiplier = 1.0
    if use_profile_strategy:
        logger.info("[VECTORSTORE] Using profile strategy weights (skipping intent-based)")
    elif is_repo_query or has_conf_reference or prefers_conf:
        logger.info("[VECTORSTORE] REPO-CENTRIC query detected (intent-based)")
        weight_map = {
            "org_repo_mxbai": 100, "secondary_specs": 5, "spl_commands_mxbai": 5,
            "local_docs_mxbai": 2, "cribl_docs_mxbai": 2, "primary": 1, "feedback_qa": 1,
        }
        repo_fetch_multiplier = 4.0
    elif has_spl_reference:
        logger.info("[VECTORSTORE] SPL-CENTRIC query detected (intent-based)")
        weight_map = {
            "spl_commands_mxbai": 100, "org_repo_mxbai": 8, "secondary_specs": 3,
            "local_docs_mxbai": 2, "cribl_docs_mxbai": 2, "primary": 1, "feedback_qa": 1,
        }
    else:
        logger.info("[VECTORSTORE] GENERAL/SPEC query detected (intent-based)")
        weight_map = {
            "secondary_specs": 50, "spl_commands_mxbai": 10, "org_repo_mxbai": 8,
            "local_docs_mxbai": 5, "cribl_docs_mxbai": 5, "primary": 3, "feedback_qa": 1,
        }

    collections: List[tuple[str, Chroma]] = []
    if feedback:
        collections.append(("feedback_qa", feedback))
    for idx, extra in enumerate(additional):
        name = additional_names[idx] if idx < len(additional_names) else f"additional_{idx+1}"
        collections.append((name, extra))
    if secondary:
        collections.append(("secondary_specs", secondary))
    collections.append(("primary", store))

    def _strip_history(text: str) -> str:
        lines = []
        for line in text.splitlines():
            low = line.lower()
            if "| q:" in low or "| a:" in low:
                continue
            if re.match(r"^20\d{2}-\d{2}-\d{2}", line):
                continue
            lines.append(line)
        return "\n".join(lines).strip()

    qa_strategy = (user_settings or {}).get("qa_retrieval_strategy", "balanced")
    per_collection_results: dict[str, List[tuple[float, str | None, str | None, str]]] = {}
    for coll_name, client in collections:
        if strategy:
            from profiles import get_fetch_count
            k_fetch = get_fetch_count(strategy, coll_name)
            logger.info(f"[VECTORSTORE] Fetching {k_fetch} chunks from {coll_name} (profile-based)")
        elif coll_name == "org_repo_mxbai" and repo_fetch_multiplier > 1.0:
            k_fetch = int(top_n_per_collection * repo_fetch_multiplier)
            logger.info(f"[VECTORSTORE] Fetching {k_fetch} chunks from repo (multiplier: {repo_fetch_multiplier}x)")
        else:
            k_fetch = top_n_per_collection

        raw_docs = _search(client, coll_name, k_local=k_fetch)
        scored: List[tuple[float, str | None, str | None, str, dict]] = []
        weight = weight_map.get(coll_name, 1) if weight_map else 1
        for doc in raw_docs:
            text = _strip_history(doc.page_content.strip())
            text = re.sub(r"^User:[^\n]+\n", "", text)
            doc_filename = str(doc.metadata.get("filename", "")).lower() if hasattr(doc, "metadata") else ""
            is_conf_chunk = (
                doc_filename.endswith((".conf", ".spec"))
                or (doc.metadata.get("stanza") if hasattr(doc, "metadata") and isinstance(doc.metadata, dict) else False)
            )
            max_text_len = 3000 if is_conf_chunk else 1500
            if len(text) > max_text_len:
                text = text[:max_text_len] + " ..."

            source = None
            source_url = None
            doc_metadata = {}
            try:
                if hasattr(doc, "metadata") and isinstance(doc.metadata, dict):
                    doc_metadata = doc.metadata.copy()
                    source = doc.metadata.get("source")
                    source_url = doc.metadata.get("source_url")
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                source = None
                source_url = None
            if not source_url and public_url_mapper:
                source_url = public_url_mapper(str(source)) if source else None
                if not source_url and source:
                    import os
                    basename = os.path.basename(str(source))
                    if basename.endswith((".spec", ".conf")):
                        source_url = f"/public/documents/specs/{basename}"

            similarity_score = doc_metadata.get("_similarity_score", 0.5)
            score = weight * 10 + int(similarity_score * 50)
            src_lower = str(source).lower() if source else ""
            if "feedback:" in src_lower or coll_name == "feedback_qa":
                score = weight * 10 + int(similarity_score * 20)

            if prefers_conf:
                if "feedback:" not in src_lower and ".conf" not in src_lower and "spec" not in src_lower:
                    continue
                if ".conf" in src_lower or "spec" in src_lower:
                    score += 4
            else:
                score += 1

            overlap = _token_overlap_score(text, query_tokens)
            score += overlap
            if role_hits and any(rk in text.lower() for rk in role_hits):
                score += 2
            if version_tokens and any(v in text.lower() for v in version_tokens):
                score += 1

            kind = doc_metadata.get("kind", "")
            if qa_strategy == "prefer_generated" and kind == "generated_qa_v1":
                score += 25
            elif qa_strategy == "prefer_raw" and kind != "generated_qa_v1":
                score += 10

            scored.append((score, source, source_url, text, doc_metadata))

        seen_local = set()
        deduped_local = []
        for score, source, source_url, text, metadata in scored:
            if text in seen_local:
                continue
            seen_local.add(text)
            deduped_local.append((score, source, source_url, text, metadata))

        deduped_local.sort(key=lambda x: (-x[0], str(x[1]) if x[1] else "", x[3][:40]))
        per_collection_results[coll_name] = deduped_local[:keep_per_collection]
        logger.info(
            f"[VECTORSTORE] {coll_name}: kept {len(per_collection_results[coll_name])} of "
            f"{len(deduped_local)} after weighting/dedup (weight={weight}x)"
        )

    global_seen = set()
    merged: List[tuple[float, str | None, str | None, str, str, dict]] = []
    for coll_name, entries in per_collection_results.items():
        for score, source, source_url, text, metadata in entries:
            if text in global_seen:
                continue
            global_seen.add(text)
            merged.append((score, source, source_url, text, coll_name, metadata))

    merged.sort(key=lambda x: (-x[0], x[4], str(x[1]) if x[1] else "", x[3][:40]))

    final_cap = max(k, keep_per_collection * len(per_collection_results))
    chunks: List[dict] = []
    for score, source, source_url, text, coll_name, metadata in merged[:final_cap]:
        context_chunks = []
        if score >= 500 and coll_name in ["org_repo_mxbai", "spl_commands_mxbai", "secondary_specs"]:
            if get_surrounding_chunks_func:
                for stored_coll_name, stored_client in collections:
                    if stored_coll_name == coll_name:
                        try:
                            surrounding = get_surrounding_chunks_func(stored_client, metadata, context_window=2)
                            if surrounding:
                                context_texts = [chunk_text for chunk_text, _ in surrounding]
                                context_chunks = context_texts
                                logger.info(f"[CONTEXT] Added {len(context_chunks)} context chunks for {source}")
                        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                            logger.warning(f"[CONTEXT] Failed to get context for {source}: {e}")
                        break

        chunk_dict = {
            "text": text if text is not None else None,
            "source": source if source is not None else None,
            "source_url": source_url if source_url is not None else None,
            "collection": coll_name if coll_name is not None else None,
            "score": score if score is not None else None,
            "context": context_chunks if context_chunks else None,
        }

        if metadata:
            for key in ["stanza", "conf_type", "is_savedsearch", "app_type", "app_name", "app_path", "app_subdir", "filename", "full_app_path"]:
                if key in metadata:
                    chunk_dict[key] = metadata[key]

        if "app_name" not in chunk_dict or not chunk_dict.get("app_name"):
            source_path = chunk_dict.get("source", "")
            if source_path:
                try:
                    from obsai_context import extract_app_context
                    app_ctx = extract_app_context(source_path)
                    if app_ctx:
                        chunk_dict["app_name"] = app_ctx.app_name
                        if "app_type" not in chunk_dict:
                            chunk_dict["app_type"] = app_ctx.app_type
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                    logger.debug("%s", _exc)

        chunks.append(chunk_dict)

    logger.info(
        f"[VECTORSTORE] Total raw results: {sum(len(v) for v in per_collection_results.values())} | "
        f"Returning {len(chunks)} chunks (cap={final_cap})"
    )
    if chunks:
        top5 = [(c.get('collection'), c.get('score'), (c.get('source') or '')[:40]) for c in chunks[:5]]
        logger.info(f"[VECTORSTORE] Top 5 merged: {top5}")
    return chunks
