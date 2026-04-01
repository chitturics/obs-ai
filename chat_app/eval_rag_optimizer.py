#!/usr/bin/env python3
"""
RAG Configuration Optimizer — Grid search over retrieval parameters.

Evaluates different configurations of:
  - chunk_size (tokens): smart_chunk_tokens
  - chunk_overlap (tokens): smart_chunk_overlap_tokens
  - k (retrieval depth): how many chunks to fetch
  - score_threshold: minimum score to include a chunk
  - collection_weights: weight multipliers for each collection
  - reranking: whether to enable cross-encoder reranking

Metrics:
  - Hit Rate (HR@k): % of queries where at least one relevant chunk was found
  - Mean Reciprocal Rank (MRR): average 1/rank of first relevant result
  - Precision@k: % of returned chunks that are relevant
  - Recall@k: % of relevant chunks that were returned
  - NDCG@k: Normalized Discounted Cumulative Gain
  - Latency: average query time

Run inside the container:
    python3 /app/chat_app/eval_rag_optimizer.py

Or from host:
    docker exec chat_ui_app python3 /app/chat_app/eval_rag_optimizer.py
"""

import asyncio
import argparse
import json
import logging
import math
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/chat_app')
os.chdir('/app')

logger = logging.getLogger("rag_optimizer")


# ============================================================================
# Metrics
# ============================================================================

@dataclass
class RetrievalMetrics:
    """Aggregated retrieval quality metrics."""
    config_name: str = ""
    total_queries: int = 0
    hit_rate: float = 0.0        # % queries with >= 1 relevant hit
    mrr: float = 0.0             # Mean Reciprocal Rank
    precision_at_k: float = 0.0  # Avg precision across queries
    recall_at_k: float = 0.0     # Avg recall across queries
    ndcg_at_k: float = 0.0       # Normalized DCG
    avg_chunks_returned: float = 0.0
    avg_latency_ms: float = 0.0
    p95_latency_ms: float = 0.0
    # Per-collection breakdown
    collection_hit_rates: Dict[str, float] = field(default_factory=dict)
    # Per-difficulty breakdown
    difficulty_scores: Dict[str, float] = field(default_factory=dict)
    # Per-type breakdown
    type_scores: Dict[str, float] = field(default_factory=dict)
    # Config params
    config: Dict[str, Any] = field(default_factory=dict)

    @property
    def composite_score(self) -> float:
        """Weighted composite of all metrics for ranking configs."""
        return (
            self.hit_rate * 0.30 +
            self.mrr * 0.25 +
            self.precision_at_k * 0.20 +
            self.ndcg_at_k * 0.15 +
            self.recall_at_k * 0.10
        )


def _dcg(relevances: List[float], k: int) -> float:
    """Discounted Cumulative Gain."""
    dcg = 0.0
    for i, rel in enumerate(relevances[:k]):
        dcg += rel / math.log2(i + 2)  # i+2 because log2(1)=0
    return dcg


def _ndcg(relevances: List[float], k: int) -> float:
    """Normalized DCG."""
    dcg = _dcg(relevances, k)
    ideal = _dcg(sorted(relevances, reverse=True), k)
    return dcg / ideal if ideal > 0 else 0.0


# ============================================================================
# Config Parameter Grid
# ============================================================================

@dataclass
class RAGConfig:
    """A single RAG configuration to evaluate."""
    name: str
    smart_chunk_tokens: int = 250
    smart_chunk_overlap_tokens: int = 40
    conf_max_chunk_size: int = 1200
    k: int = 20
    k_per_collection: int = 15
    score_threshold: int = 0      # Minimum score to include
    # Collection weights
    weight_spl_commands: int = 100
    weight_feedback: int = 25
    weight_org_repo: int = 8
    weight_specs: int = 3
    weight_local_docs: int = 2
    weight_primary: int = 1
    # Reranking
    reranking_enabled: bool = False
    reranking_top_n: int = 5


DEFAULT_CONFIGS = [
    # Current default
    RAGConfig(name="current_default", smart_chunk_tokens=250, smart_chunk_overlap_tokens=40,
              k=20, k_per_collection=15, conf_max_chunk_size=1200),

    # Smaller chunks — more granular retrieval
    RAGConfig(name="small_chunks_150", smart_chunk_tokens=150, smart_chunk_overlap_tokens=30,
              k=20, k_per_collection=15, conf_max_chunk_size=800),
    RAGConfig(name="small_chunks_200", smart_chunk_tokens=200, smart_chunk_overlap_tokens=40,
              k=20, k_per_collection=15, conf_max_chunk_size=1000),

    # Larger chunks — more context per chunk
    RAGConfig(name="large_chunks_350", smart_chunk_tokens=350, smart_chunk_overlap_tokens=60,
              k=15, k_per_collection=10, conf_max_chunk_size=1400),
    RAGConfig(name="large_chunks_400", smart_chunk_tokens=400, smart_chunk_overlap_tokens=80,
              k=12, k_per_collection=8, conf_max_chunk_size=1500),

    # More overlap — better boundary coverage
    RAGConfig(name="high_overlap_60", smart_chunk_tokens=250, smart_chunk_overlap_tokens=60,
              k=20, k_per_collection=15, conf_max_chunk_size=1200),
    RAGConfig(name="high_overlap_80", smart_chunk_tokens=250, smart_chunk_overlap_tokens=80,
              k=20, k_per_collection=15, conf_max_chunk_size=1200),

    # Different k values
    RAGConfig(name="k_10", smart_chunk_tokens=250, smart_chunk_overlap_tokens=40,
              k=10, k_per_collection=8, conf_max_chunk_size=1200),
    RAGConfig(name="k_30", smart_chunk_tokens=250, smart_chunk_overlap_tokens=40,
              k=30, k_per_collection=20, conf_max_chunk_size=1200),
    RAGConfig(name="k_50", smart_chunk_tokens=250, smart_chunk_overlap_tokens=40,
              k=50, k_per_collection=30, conf_max_chunk_size=1200),

    # Higher score threshold — only keep high-quality matches
    RAGConfig(name="score_200", smart_chunk_tokens=250, smart_chunk_overlap_tokens=40,
              k=20, k_per_collection=15, score_threshold=200, conf_max_chunk_size=1200),
    RAGConfig(name="score_500", smart_chunk_tokens=250, smart_chunk_overlap_tokens=40,
              k=20, k_per_collection=15, score_threshold=500, conf_max_chunk_size=1200),

    # Balanced collection weights (less SPL dominance)
    RAGConfig(name="balanced_weights", smart_chunk_tokens=250, smart_chunk_overlap_tokens=40,
              k=20, k_per_collection=15, weight_spl_commands=50, weight_specs=20,
              weight_org_repo=15, weight_local_docs=10, weight_primary=5, conf_max_chunk_size=1200),

    # SPL-heavy weights
    RAGConfig(name="spl_heavy", smart_chunk_tokens=250, smart_chunk_overlap_tokens=40,
              k=20, k_per_collection=15, weight_spl_commands=200, weight_specs=5,
              weight_org_repo=3, weight_local_docs=1, weight_primary=1, conf_max_chunk_size=1200),

    # With reranking
    RAGConfig(name="reranking_default", smart_chunk_tokens=250, smart_chunk_overlap_tokens=40,
              k=30, k_per_collection=20, reranking_enabled=True, reranking_top_n=10,
              conf_max_chunk_size=1200),

    # Optimized combo 1: small chunks + high k + reranking
    RAGConfig(name="combo_small_rerank", smart_chunk_tokens=200, smart_chunk_overlap_tokens=40,
              k=40, k_per_collection=25, reranking_enabled=True, reranking_top_n=8,
              conf_max_chunk_size=1000),

    # Optimized combo 2: medium chunks + balanced weights
    RAGConfig(name="combo_balanced", smart_chunk_tokens=250, smart_chunk_overlap_tokens=50,
              k=25, k_per_collection=18, weight_spl_commands=80, weight_specs=15,
              weight_org_repo=12, weight_local_docs=5, weight_primary=3, conf_max_chunk_size=1200),

    # Optimized combo 3: larger chunks + less overlap + high k
    RAGConfig(name="combo_large_k", smart_chunk_tokens=300, smart_chunk_overlap_tokens=50,
              k=35, k_per_collection=22, conf_max_chunk_size=1300),
]


# ============================================================================
# Evaluator
# ============================================================================

class RAGEvaluator:
    """Evaluates RAG retrieval quality across configurations."""

    def __init__(self, test_cases=None, sample_size: int = 500):
        from chat_app.eval_test_cases import generate_all_test_cases, get_stratified_sample
        all_cases = test_cases or generate_all_test_cases()
        self.all_cases = all_cases
        self.test_cases = get_stratified_sample(all_cases, n=sample_size)
        self._stores = {}  # Cache stores per config

    def _is_relevant(self, doc, test_case) -> float:
        """
        Score document relevance for a test case (0.0 - 1.0).

        Checks:
        1. Does the doc contain expected keywords?
        2. Does it come from the expected collection?
        3. Does the metadata match?
        """
        relevance = 0.0
        doc_text = ""
        doc_meta = {}

        # Extract text and metadata from different doc formats
        if hasattr(doc, 'page_content'):
            doc_text = doc.page_content.lower()
            doc_meta = doc.metadata if hasattr(doc, 'metadata') else {}
        elif isinstance(doc, dict):
            doc_text = (doc.get('text', '') or doc.get('page_content', '')).lower()
            doc_meta = doc.get('metadata', {})
        elif isinstance(doc, tuple) and len(doc) >= 2:
            doc_obj = doc[0]
            if hasattr(doc_obj, 'page_content'):
                doc_text = doc_obj.page_content.lower()
                doc_meta = doc_obj.metadata if hasattr(doc_obj, 'metadata') else {}
        else:
            doc_text = str(doc).lower()

        if not doc_text:
            return 0.0

        # Check expected keywords
        keyword_matches = 0
        for kw in test_case.expected_keywords:
            if kw.lower() in doc_text:
                keyword_matches += 1
        if test_case.expected_keywords:
            keyword_score = keyword_matches / len(test_case.expected_keywords)
            relevance += keyword_score * 0.6

        # Check collection match
        doc_collection = str(doc_meta.get('collection', '')).lower()
        doc_source = str(doc_meta.get('source', '')).lower()
        expected_coll = test_case.expected_collection.lower()
        if expected_coll in doc_collection or expected_coll.split('_')[0] in doc_collection:
            relevance += 0.3
        elif expected_coll.split('_')[0] in doc_source:
            relevance += 0.2

        # Bonus for category match
        doc_category = str(doc_meta.get('category', '')).lower()
        if test_case.category and test_case.category.split('_')[0] in doc_category:
            relevance += 0.1

        return min(1.0, relevance)

    def _is_relevant_dict(self, result: dict, test_case) -> float:
        """Score relevance for a dict result from search_similar_chunks_parallel."""
        relevance = 0.0
        doc_text = (result.get("text", "") or "").lower()
        doc_collection = (result.get("collection", "") or "").lower()
        doc_source = (result.get("source", "") or "").lower()

        if not doc_text:
            return 0.0

        # Check expected keywords
        keyword_matches = 0
        for kw in test_case.expected_keywords:
            if kw.lower() in doc_text:
                keyword_matches += 1
        if test_case.expected_keywords:
            keyword_score = keyword_matches / len(test_case.expected_keywords)
            relevance += keyword_score * 0.6

        # Check collection match
        expected_coll = test_case.expected_collection.lower()
        if expected_coll in doc_collection or expected_coll.split("_")[0] in doc_collection:
            relevance += 0.3
        elif expected_coll.split("_")[0] in doc_source:
            relevance += 0.2

        # Bonus for category match in source path
        if test_case.category and test_case.category.split("_")[0] in doc_source:
            relevance += 0.1

        return min(1.0, relevance)

    def evaluate_config(self, config: RAGConfig, verbose: bool = False) -> RetrievalMetrics:
        """Evaluate a single RAG configuration against the test cases.

        Uses the real multi-collection search pipeline (search_similar_chunks_parallel)
        to accurately measure retrieval quality across all collections.
        """
        from chat_app.settings import get_settings

        settings = get_settings()

        # Apply config to settings (temporarily)
        orig_chunk = settings.chunking.smart_chunk_tokens
        orig_overlap = settings.chunking.smart_chunk_overlap_tokens
        orig_conf_chunk = settings.chunking.conf_max_chunk_size

        settings.chunking.smart_chunk_tokens = config.smart_chunk_tokens
        settings.chunking.smart_chunk_overlap_tokens = config.smart_chunk_overlap_tokens
        settings.chunking.conf_max_chunk_size = config.conf_max_chunk_size

        # Build weight map from config
        weight_map = {
            "spl_commands_mxbai": config.weight_spl_commands,
            "feedback_qa": config.weight_feedback,
            "org_repo_mxbai": config.weight_org_repo,
            "specs_mxbai_embed_large_v3": config.weight_specs,
            "local_docs_mxbai": config.weight_local_docs,
            "assistant_memory_mxbai_v2": config.weight_primary,
        }

        # Get primary vector store
        try:
            from chat_app.vectorstore import ensure_vector_store
            store = ensure_vector_store()
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.error("Failed to init vector store: %s", exc)
            return RetrievalMetrics(config_name=config.name, config=asdict(config))

        # Import async search function
        try:
            from chat_app.vectorstore_search import search_similar_chunks_parallel
            use_parallel = True
        except ImportError:
            use_parallel = False

        metrics = RetrievalMetrics(config_name=config.name, config=asdict(config))
        metrics.total_queries = len(self.test_cases)

        hit_count = 0
        reciprocal_ranks = []
        precisions = []
        recalls = []
        ndcgs = []
        latencies = []
        chunks_returned = []

        # Per-breakdown accumulators
        coll_hits: Dict[str, List[int]] = {}
        diff_scores: Dict[str, List[float]] = {}
        type_scores: Dict[str, List[float]] = {}

        # Get or create event loop for async calls
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        for i, tc in enumerate(self.test_cases):
            start_t = time.monotonic()

            try:
                if use_parallel:
                    # Use the real multi-collection search pipeline
                    results_dicts = loop.run_until_complete(
                        search_similar_chunks_parallel(
                            store=store,
                            query=tc.query,
                            k=config.k,
                            weight_map_override=weight_map,
                        )
                    )
                    # Convert dict results to (doc-like, score) tuples
                    results = []
                    for d in results_dicts:
                        results.append(d)
                else:
                    # Fallback: single-store search
                    raw = store.similarity_search_with_score(tc.query, k=config.k)
                    results = [{"text": doc.page_content, "score": score,
                                "collection": "primary",
                                "source": doc.metadata.get("source", ""),
                                "metadata": doc.metadata}
                               for doc, score in raw]
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.warning("Search failed for '%s': %s", tc.query[:50], exc)
                latencies.append(0)
                chunks_returned.append(0)
                precisions.append(0.0)
                recalls.append(0.0)
                reciprocal_ranks.append(0.0)
                ndcgs.append(0.0)
                continue

            elapsed_ms = (time.monotonic() - start_t) * 1000
            latencies.append(elapsed_ms)

            # Apply score threshold filter (higher score = better in parallel search)
            if config.score_threshold > 0:
                results = [r for r in results
                           if r.get("score", 0) >= config.score_threshold]

            chunks_returned.append(len(results))

            # Calculate relevance for each result
            relevances = []
            for result in results:
                rel = self._is_relevant_dict(result, tc)
                relevances.append(rel)

            # Hit Rate: any relevant result?
            has_hit = any(r >= 0.3 for r in relevances)
            if has_hit:
                hit_count += 1

            # MRR: reciprocal rank of first relevant result
            rr = 0.0
            for rank, rel in enumerate(relevances):
                if rel >= 0.3:
                    rr = 1.0 / (rank + 1)
                    break
            reciprocal_ranks.append(rr)

            # Precision@k: fraction of returned that are relevant
            relevant_count = sum(1 for r in relevances if r >= 0.3)
            prec = relevant_count / len(relevances) if relevances else 0.0
            precisions.append(prec)

            # Recall@k: assume each query has ~3 relevant docs in the corpus
            expected_relevant = max(1, min(3, len(tc.expected_keywords)))
            rec = min(1.0, relevant_count / expected_relevant)
            recalls.append(rec)

            # NDCG@k
            ndcg = _ndcg(relevances, config.k)
            ndcgs.append(ndcg)

            # Per-collection tracking
            coll = tc.expected_collection
            coll_hits.setdefault(coll, []).append(1 if has_hit else 0)

            # Per-difficulty tracking
            diff_scores.setdefault(tc.difficulty, []).append(rr)

            # Per-type tracking
            type_scores.setdefault(tc.expected_type, []).append(rr)

            if verbose and (i + 1) % 50 == 0:
                print(f"    [{i+1}/{len(self.test_cases)}] "
                      f"HR={hit_count/(i+1):.3f} MRR={sum(reciprocal_ranks)/len(reciprocal_ranks):.3f} "
                      f"P@k={sum(precisions)/len(precisions):.3f} "
                      f"lat={sum(latencies)/len(latencies):.0f}ms")

        # Aggregate metrics
        n = len(self.test_cases)
        metrics.hit_rate = hit_count / n if n > 0 else 0.0
        metrics.mrr = sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0
        metrics.precision_at_k = sum(precisions) / len(precisions) if precisions else 0.0
        metrics.recall_at_k = sum(recalls) / len(recalls) if recalls else 0.0
        metrics.ndcg_at_k = sum(ndcgs) / len(ndcgs) if ndcgs else 0.0
        metrics.avg_chunks_returned = sum(chunks_returned) / len(chunks_returned) if chunks_returned else 0.0
        metrics.avg_latency_ms = sum(latencies) / len(latencies) if latencies else 0.0
        sorted_lat = sorted(latencies)
        metrics.p95_latency_ms = sorted_lat[int(len(sorted_lat) * 0.95)] if sorted_lat else 0.0

        # Per-collection hit rates
        for coll, hits in coll_hits.items():
            metrics.collection_hit_rates[coll] = sum(hits) / len(hits) if hits else 0.0

        # Per-difficulty scores
        for diff, scores in diff_scores.items():
            metrics.difficulty_scores[diff] = sum(scores) / len(scores) if scores else 0.0

        # Per-type scores
        for t, scores in type_scores.items():
            metrics.type_scores[t] = sum(scores) / len(scores) if scores else 0.0

        # Restore original settings
        settings.chunking.smart_chunk_tokens = orig_chunk
        settings.chunking.smart_chunk_overlap_tokens = orig_overlap
        settings.chunking.conf_max_chunk_size = orig_conf_chunk

        return metrics

    def run_grid_search(
        self,
        configs: List[RAGConfig] = None,
        verbose: bool = True,
    ) -> List[RetrievalMetrics]:
        """Run evaluation across all configurations."""
        configs = configs or DEFAULT_CONFIGS
        results = []

        print("=" * 80)
        print("RAG Configuration Optimizer — Grid Search")
        print("=" * 80)
        print(f"  Test cases:     {len(self.all_cases)} total, {len(self.test_cases)} sampled")
        print(f"  Configurations: {len(configs)}")
        print()

        for i, config in enumerate(configs):
            print(f"\n--- Config {i+1}/{len(configs)}: {config.name} ---")
            print(f"    chunks={config.smart_chunk_tokens}t/{config.smart_chunk_overlap_tokens}o "
                  f"k={config.k} k_per={config.k_per_collection} "
                  f"threshold={config.score_threshold} "
                  f"rerank={config.reranking_enabled}")

            metrics = self.evaluate_config(config, verbose=verbose)
            results.append(metrics)

            print("    Results:")
            print(f"      Hit Rate:    {metrics.hit_rate:.4f}")
            print(f"      MRR:         {metrics.mrr:.4f}")
            print(f"      Precision:   {metrics.precision_at_k:.4f}")
            print(f"      Recall:      {metrics.recall_at_k:.4f}")
            print(f"      NDCG:        {metrics.ndcg_at_k:.4f}")
            print(f"      Composite:   {metrics.composite_score:.4f}")
            print(f"      Avg chunks:  {metrics.avg_chunks_returned:.1f}")
            print(f"      Avg latency: {metrics.avg_latency_ms:.0f}ms")
            print(f"      P95 latency: {metrics.p95_latency_ms:.0f}ms")

            if metrics.collection_hit_rates:
                print("      By collection:")
                for coll, hr in sorted(metrics.collection_hit_rates.items()):
                    print(f"        {coll}: {hr:.4f}")

            if metrics.difficulty_scores:
                print("      By difficulty:")
                for diff, score in sorted(metrics.difficulty_scores.items()):
                    print(f"        {diff}: MRR={score:.4f}")

            if metrics.type_scores:
                print("      By type:")
                for t, score in sorted(metrics.type_scores.items()):
                    print(f"        {t}: MRR={score:.4f}")

        # Rank by composite score
        results.sort(key=lambda m: m.composite_score, reverse=True)

        print("\n" + "=" * 80)
        print("RANKING (by composite score)")
        print("=" * 80)
        print(f"{'Rank':>4} {'Config':30s} {'Composite':>10} {'HR':>8} {'MRR':>8} "
              f"{'P@k':>8} {'NDCG':>8} {'Lat(ms)':>8}")
        print("-" * 80)
        for rank, m in enumerate(results, 1):
            print(f"{rank:4d} {m.config_name:30s} {m.composite_score:10.4f} "
                  f"{m.hit_rate:8.4f} {m.mrr:8.4f} "
                  f"{m.precision_at_k:8.4f} {m.ndcg_at_k:8.4f} "
                  f"{m.avg_latency_ms:8.0f}")

        # Show best config
        best = results[0]
        print(f"\n{'='*80}")
        print(f"BEST CONFIGURATION: {best.config_name}")
        print(f"{'='*80}")
        print(f"  Composite Score: {best.composite_score:.4f}")
        print(f"  Hit Rate:        {best.hit_rate:.4f}")
        print(f"  MRR:             {best.mrr:.4f}")
        print(f"  Precision@k:     {best.precision_at_k:.4f}")
        print(f"  Recall@k:        {best.recall_at_k:.4f}")
        print(f"  NDCG@k:          {best.ndcg_at_k:.4f}")
        print(f"  Avg Latency:     {best.avg_latency_ms:.0f}ms")
        print()
        print("  Recommended settings:")
        print(f"    chunking.smart_chunk_tokens:         {best.config['smart_chunk_tokens']}")
        print(f"    chunking.smart_chunk_overlap_tokens:  {best.config['smart_chunk_overlap_tokens']}")
        print(f"    chunking.conf_max_chunk_size:         {best.config['conf_max_chunk_size']}")
        print(f"    retrieval.k:                          {best.config['k']}")
        print(f"    retrieval.k_per_collection:            {best.config['k_per_collection']}")
        print(f"    retrieval.score_threshold:             {best.config['score_threshold']}")
        print(f"    weights.spl_commands:                  {best.config['weight_spl_commands']}")
        print(f"    weights.feedback:                      {best.config['weight_feedback']}")
        print(f"    weights.org_repo:                      {best.config['weight_org_repo']}")
        print(f"    weights.specs:                         {best.config['weight_specs']}")
        print(f"    weights.local_docs:                    {best.config['weight_local_docs']}")
        print(f"    weights.primary:                       {best.config['weight_primary']}")
        print(f"    reranking.enabled:                     {best.config['reranking_enabled']}")

        return results

    def save_results(self, results: List[RetrievalMetrics], path: str = "/tmp/rag_eval_results.json"):
        """Save evaluation results to JSON."""
        data = []
        for m in results:
            d = asdict(m)
            d["composite_score"] = m.composite_score
            data.append(d)

        with open(path, 'w') as f:
            json.dump(data, f, indent=2, default=str)
        print(f"\nResults saved to {path}")


def main():
    parser = argparse.ArgumentParser(description="RAG Configuration Optimizer")
    parser.add_argument("--sample", type=int, default=500,
                        help="Number of test cases to sample (default: 500)")
    parser.add_argument("--full", action="store_true",
                        help="Run on ALL test cases (slow)")
    parser.add_argument("--config", type=str,
                        help="Run only a specific config by name")
    parser.add_argument("--output", type=str, default="/tmp/rag_eval_results.json",
                        help="Output JSON path")
    parser.add_argument("--quiet", action="store_true",
                        help="Less verbose output")
    args = parser.parse_args()

    # Suppress noisy loggers
    logging.basicConfig(level=logging.WARNING)
    for name in ["chromadb", "httpx", "httpcore", "urllib3", "chat_app"]:
        logging.getLogger(name).setLevel(logging.ERROR)

    sample_size = len(generate_all_test_cases()) if args.full else args.sample

    evaluator = RAGEvaluator(sample_size=sample_size)

    configs = DEFAULT_CONFIGS
    if args.config:
        configs = [c for c in DEFAULT_CONFIGS if c.name == args.config]
        if not configs:
            print(f"Unknown config: {args.config}")
            print(f"Available: {', '.join(c.name for c in DEFAULT_CONFIGS)}")
            sys.exit(1)

    results = evaluator.run_grid_search(configs, verbose=not args.quiet)
    evaluator.save_results(results, args.output)


def generate_all_test_cases():
    """Import and return all test cases."""
    from chat_app.eval_test_cases import generate_all_test_cases as _gen
    return _gen()


if __name__ == "__main__":
    main()
