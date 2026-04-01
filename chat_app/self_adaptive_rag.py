"""
Self-Adaptive RAG: Learning from user feedback to improve responses over time.

Implements simple self-learning techniques:
1. Collection weight adaptation based on thumbs up/down feedback
2. Query pattern learning for better retrieval
3. Anti-hallucination strengthening from negative feedback
"""
import logging
import json
import os
from typing import Dict, List, Optional
from datetime import datetime
from dataclasses import dataclass, asdict

logger = logging.getLogger(__name__)

# Paths for persistence
ADAPTIVE_DATA_PATH = os.getenv("ADAPTIVE_DATA_PATH", "/app/chat_app/feedback")
COLLECTION_WEIGHTS_FILE = os.path.join(ADAPTIVE_DATA_PATH, "collection_weights.json")
QUERY_PATTERNS_FILE = os.path.join(ADAPTIVE_DATA_PATH, "query_patterns.json")
INTENT_WEIGHTS_FILE = os.path.join(ADAPTIVE_DATA_PATH, "intent_collection_weights.json")

# -----------------------------------------------------------------------
# Per-intent collection weight overrides
# These provide domain-aware retrieval boosts: a multiplier >1.0 means
# "fetch more from this collection for this intent".  Missing collections
# fall back to the base weight.
# -----------------------------------------------------------------------
INTENT_COLLECTION_WEIGHTS: Dict[str, Dict[str, float]] = {
    "spl_generation": {"spl_commands_mxbai": 2.0, "specs_mxbai_embed_large_v3": 1.5},
    "spl_explanation": {"spl_commands_mxbai": 2.0, "specs_mxbai_embed_large_v3": 1.5},
    "spl_optimization": {"spl_commands_mxbai": 2.0, "specs_mxbai_embed_large_v3": 1.2},
    "config_lookup": {"specs_mxbai_embed_large_v3": 2.0, "org_repo_mxbai": 1.5},
    "cribl_pipeline": {"cribl_docs_mxbai": 2.0, "spl_commands_mxbai": 1.0},
    "troubleshooting": {"local_docs_mxbai": 1.5, "feedback_qa_mxbai_embed_large": 1.5},
    "compare_commands": {"spl_commands_mxbai": 2.0, "specs_mxbai_embed_large_v3": 1.5},
    "general_qa": {},  # Use default weights
}


@dataclass
class FeedbackEntry:
    """Single feedback entry"""
    query: str
    response: str
    feedback_value: int  # 1 for thumbs up, 0 for thumbs down
    collections_used: List[str]
    timestamp: str
    username: str = "unknown"


@dataclass
class CollectionWeights:
    """Dynamic collection weights learned from feedback"""
    weights: Dict[str, float]  # collection_name -> weight
    success_counts: Dict[str, int]  # thumbs up per collection
    failure_counts: Dict[str, int]  # thumbs down per collection
    last_updated: str


class SelfAdaptiveRAG:
    """
    Simple self-learning system that adapts based on user feedback.

    Key features:
    - Learns which collections provide good answers (collection weight adaptation)
    - Identifies successful query patterns for better retrieval
    - Strengthens anti-hallucination when feedback indicates issues
    """

    def __init__(self):
        """Initialize self-adaptive system"""
        self.collection_weights = self._load_collection_weights()
        self.query_patterns = self._load_query_patterns()
        # Per-intent success tracking: {intent: {collection: {success: N, failure: N}}}
        self.intent_collection_stats: Dict[str, Dict[str, Dict[str, int]]] = self._load_intent_weights()

        # Ensure data directory exists
        os.makedirs(ADAPTIVE_DATA_PATH, exist_ok=True)

        logger.info(f"[SELF_ADAPTIVE] Initialized with {len(self.collection_weights.weights)} collection weights")

    def _load_collection_weights(self) -> CollectionWeights:
        """Load collection weights from disk or initialize defaults"""
        if os.path.exists(COLLECTION_WEIGHTS_FILE):
            try:
                with open(COLLECTION_WEIGHTS_FILE, 'r') as f:
                    data = json.load(f)
                    logger.info(f"[SELF_ADAPTIVE] Loaded collection weights from {COLLECTION_WEIGHTS_FILE}")
                    return CollectionWeights(**data)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
                logger.warning(f"[SELF_ADAPTIVE] Failed to load weights: {e}. Using defaults.")

        # Default weights - equal for all collections initially
        default_collections = [
            "specs_mxbai_embed_large_v3",
            "spl_commands_mxbai",
            "org_repo_mxbai",
            "local_docs_mxbai",
            "feedback_qa_mxbai_embed_large"
        ]

        return CollectionWeights(
            weights={c: 1.0 for c in default_collections},
            success_counts={c: 0 for c in default_collections},
            failure_counts={c: 0 for c in default_collections},
            last_updated=datetime.now().isoformat()
        )

    def _save_collection_weights(self):
        """Persist collection weights to disk"""
        try:
            with open(COLLECTION_WEIGHTS_FILE, 'w') as f:
                json.dump(asdict(self.collection_weights), f, indent=2)
            logger.info(f"[SELF_ADAPTIVE] Saved collection weights to {COLLECTION_WEIGHTS_FILE}")
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            logger.error(f"[SELF_ADAPTIVE] Failed to save weights: {e}")

    def _load_query_patterns(self) -> Dict[str, List[str]]:
        """Load successful query patterns"""
        if os.path.exists(QUERY_PATTERNS_FILE):
            try:
                with open(QUERY_PATTERNS_FILE, 'r') as f:
                    patterns = json.load(f)
                    logger.info(f"[SELF_ADAPTIVE] Loaded {len(patterns)} query patterns")
                    return patterns
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
                logger.warning(f"[SELF_ADAPTIVE] Failed to load patterns: {e}")

        return {
            "config_questions": [],
            "spl_questions": [],
            "troubleshooting": [],
            "org_repo": []
        }

    def _save_query_patterns(self):
        """Persist query patterns to disk"""
        try:
            with open(QUERY_PATTERNS_FILE, 'w') as f:
                json.dump(self.query_patterns, f, indent=2)
            logger.info("[SELF_ADAPTIVE] Saved query patterns")
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            logger.error(f"[SELF_ADAPTIVE] Failed to save patterns: {e}")

    def _load_intent_weights(self) -> Dict[str, Dict[str, Dict[str, int]]]:
        """Load per-intent collection success/failure tracking from disk."""
        if os.path.exists(INTENT_WEIGHTS_FILE):
            try:
                with open(INTENT_WEIGHTS_FILE, 'r') as f:
                    data = json.load(f)
                    logger.info(f"[SELF_ADAPTIVE] Loaded per-intent weights from {INTENT_WEIGHTS_FILE}")
                    return data
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
                logger.warning(f"[SELF_ADAPTIVE] Failed to load intent weights: {e}")
        return {}

    def _save_intent_weights(self):
        """Persist per-intent collection stats to disk."""
        try:
            with open(INTENT_WEIGHTS_FILE, 'w') as f:
                json.dump(self.intent_collection_stats, f, indent=2)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            logger.error(f"[SELF_ADAPTIVE] Failed to save intent weights: {e}")

    def record_intent_feedback(
        self,
        intent: str,
        collections_used: List[str],
        feedback_value: int,
    ):
        """
        Record which collections contributed to success/failure for a given intent.

        Over time this builds per-intent weight adjustments that improve retrieval.
        """
        if not intent or not collections_used:
            return
        if intent not in self.intent_collection_stats:
            self.intent_collection_stats[intent] = {}
        for coll in collections_used:
            if coll not in self.intent_collection_stats[intent]:
                self.intent_collection_stats[intent][coll] = {"success": 0, "failure": 0}
            if feedback_value == 1:
                self.intent_collection_stats[intent][coll]["success"] += 1
            else:
                self.intent_collection_stats[intent][coll]["failure"] += 1

        logger.debug(
            "[SELF_ADAPTIVE] Recorded intent feedback: intent=%s collections=%s value=%d",
            intent, collections_used, feedback_value,
        )
        self._save_intent_weights()

    def get_intent_weight_adjustments(self, intent: str) -> Dict[str, float]:
        """
        Compute per-collection weight adjustments learned from intent-specific feedback.

        Returns multipliers (default 1.0) for each collection that has enough data.
        Requires at least 5 feedback entries for a collection before adjusting.
        """
        stats = self.intent_collection_stats.get(intent, {})
        adjustments: Dict[str, float] = {}
        for coll, counts in stats.items():
            total = counts.get("success", 0) + counts.get("failure", 0)
            if total < 5:
                continue  # Not enough data to adjust
            success_rate = counts["success"] / total
            # Map success_rate (0-1) to a multiplier (0.7-1.3)
            adjustments[coll] = 0.7 + (success_rate * 0.6)

        return adjustments

    def update_from_feedback(
        self,
        query: str,
        response: str,
        feedback_value: int,
        collections_used: List[str],
        username: str = "unknown"
    ):
        """
        Update adaptive weights based on user feedback.

        Args:
            query: User's query
            response: LLM response
            feedback_value: 1 for thumbs up, 0 for thumbs down
            collections_used: List of collections that contributed to the response
            username: Username for tracking
        """
        logger.info(
            f"[SELF_ADAPTIVE] Processing feedback: "
            f"value={feedback_value}, collections={collections_used}"
        )

        # Update collection success/failure counts
        for collection in collections_used:
            if collection not in self.collection_weights.weights:
                self.collection_weights.weights[collection] = 1.0
                self.collection_weights.success_counts[collection] = 0
                self.collection_weights.failure_counts[collection] = 0

            if feedback_value == 1:
                # Thumbs up - increase weight
                self.collection_weights.success_counts[collection] += 1
            else:
                # Thumbs down - decrease weight
                self.collection_weights.failure_counts[collection] += 1

        # Recalculate weights using exponential moving average
        self._recalculate_weights()

        # Learn query patterns from successful queries
        if feedback_value == 1:
            self._learn_query_pattern(query, collections_used)

        # Save updated weights
        self.collection_weights.last_updated = datetime.now().isoformat()
        self._save_collection_weights()
        self._save_query_patterns()

        logger.info(f"[SELF_ADAPTIVE] Updated weights: {self.get_weight_summary()}")

    def _recalculate_weights(self):
        """
        Recalculate collection weights based on success/failure ratios.

        Formula: weight = (success_rate * 0.7) + (baseline * 0.3)
        - 70% based on actual performance
        - 30% baseline to prevent any collection from being completely ignored
        """
        for collection in self.collection_weights.weights.keys():
            successes = self.collection_weights.success_counts.get(collection, 0)
            failures = self.collection_weights.failure_counts.get(collection, 0)
            total = successes + failures

            if total == 0:
                # No feedback yet - keep default weight
                self.collection_weights.weights[collection] = 1.0
            else:
                # Calculate success rate (0-1)
                success_rate = successes / total

                # Apply formula with baseline
                baseline = 0.5  # Minimum weight to keep all collections viable
                adaptive_weight = (success_rate * 0.7) + (baseline * 0.3)

                self.collection_weights.weights[collection] = adaptive_weight

                logger.debug(
                    f"[SELF_ADAPTIVE] {collection}: "
                    f"success_rate={success_rate:.2f}, weight={adaptive_weight:.2f} "
                    f"({successes}/{total} successful)"
                )

    def _learn_query_pattern(self, query: str, collections_used: List[str]):
        """
        Learn patterns from successful queries.

        Categorizes queries and stores successful patterns for future matching.
        """
        query_lower = query.lower()

        # Categorize the query
        category = None
        if any(kw in query_lower for kw in ["cron", "schedule", "conf", "setting", "stanza"]):
            category = "config_questions"
        elif any(kw in query_lower for kw in ["search", "query", "spl", "stats", "eval"]):
            category = "spl_questions"
        elif any(kw in query_lower for kw in ["error", "why", "not working", "issue", "problem"]):
            category = "troubleshooting"
        elif "org_repo_mxbai" in collections_used:
            category = "org_repo"

        if category:
            # Store this query pattern (keep last 50 per category)
            if category not in self.query_patterns:
                self.query_patterns[category] = []

            pattern_entry = {
                "query_snippet": query[:100],  # First 100 chars
                "collections": collections_used,
                "timestamp": datetime.now().isoformat()
            }

            self.query_patterns[category].append(pattern_entry)

            # Keep only last 50 patterns per category
            if len(self.query_patterns[category]) > 50:
                self.query_patterns[category] = self.query_patterns[category][-50:]

            logger.debug(f"[SELF_ADAPTIVE] Learned pattern for category: {category}")

    def get_adjusted_multipliers(self, base_multipliers: Dict[str, float]) -> Dict[str, float]:
        """
        Adjust retrieval multipliers based on learned weights.

        Args:
            base_multipliers: Original multipliers from profile config

        Returns:
            Adjusted multipliers incorporating learned weights
        """
        adjusted = {}
        for collection, base_mult in base_multipliers.items():
            learned_weight = self.collection_weights.weights.get(collection, 1.0)

            # Blend base multiplier with learned weight (80% base, 20% learned)
            # This prevents too aggressive changes
            adjusted[collection] = (base_mult * 0.8) + (base_mult * learned_weight * 0.2)

        return adjusted

    def get_weight_summary(self) -> str:
        """Get human-readable summary of current weights"""
        lines = []
        for collection, weight in sorted(
            self.collection_weights.weights.items(),
            key=lambda x: x[1],
            reverse=True
        ):
            successes = self.collection_weights.success_counts.get(collection, 0)
            failures = self.collection_weights.failure_counts.get(collection, 0)
            total = successes + failures

            if total > 0:
                lines.append(
                    f"  {collection}: {weight:.2f} ({successes}/{total} successful)"
                )
            else:
                lines.append(f"  {collection}: {weight:.2f} (no feedback yet)")

        return "\n".join(lines) if lines else "No weights yet"

    def get_stats(self) -> Dict:
        """Get statistics for monitoring"""
        total_feedback = sum(self.collection_weights.success_counts.values()) + \
                        sum(self.collection_weights.failure_counts.values())

        total_patterns = sum(len(patterns) for patterns in self.query_patterns.values())

        return {
            "total_feedback_entries": total_feedback,
            "total_patterns_learned": total_patterns,
            "collections_tracked": len(self.collection_weights.weights),
            "last_updated": self.collection_weights.last_updated,
            "weights": dict(self.collection_weights.weights)
        }


# Global instance (singleton)
_adaptive_rag: Optional[SelfAdaptiveRAG] = None


def get_adaptive_rag() -> SelfAdaptiveRAG:
    """Get or create the global self-adaptive RAG instance"""
    global _adaptive_rag
    if _adaptive_rag is None:
        _adaptive_rag = SelfAdaptiveRAG()
    return _adaptive_rag


def apply_adaptive_learning(
    feedback_value: int,
    query: str,
    response: str,
    chunks_used: List[Dict],
    username: str = "unknown",
    intent: str = "",
):
    """
    Apply adaptive learning from user feedback.

    Call this function when user provides thumbs up/down feedback.

    Args:
        feedback_value: 1 for thumbs up, 0 for thumbs down
        query: User's original query
        response: LLM's response
        chunks_used: List of chunks/documents used in response
        username: Username for tracking
        intent: Query intent (for per-intent success tracking)
    """
    # Extract collections from chunks
    collections_used = []
    for chunk in chunks_used:
        collection = chunk.get("collection") or chunk.get("metadata", {}).get("collection")
        if collection and collection not in collections_used:
            collections_used.append(collection)

    if not collections_used:
        logger.warning("[SELF_ADAPTIVE] No collections found in chunks, skipping learning")
        return

    # Apply global learning
    adaptive_rag = get_adaptive_rag()
    adaptive_rag.update_from_feedback(
        query=query,
        response=response,
        feedback_value=feedback_value,
        collections_used=collections_used,
        username=username
    )

    # Apply per-intent success tracking
    if intent:
        adaptive_rag.record_intent_feedback(
            intent=intent,
            collections_used=collections_used,
            feedback_value=feedback_value,
        )


def get_adaptive_multipliers(
    base_multipliers: Dict[str, float],
    intent: str = "",
) -> Dict[str, float]:
    """
    Get retrieval multipliers adjusted by adaptive learning.

    Combines three learning signals:
    1. Static per-intent collection weights (INTENT_COLLECTION_WEIGHTS)
    2. Adaptive RAG weights (from real-time feedback within this session)
    3. Episodic learning boost scores (from historical episode success rates)
    4. Learned per-intent success tracking (from accumulated feedback)

    Args:
        base_multipliers: Base multipliers from profile
        intent: Current query intent (e.g. "spl_generation", "config_lookup")

    Returns:
        Adjusted multipliers incorporating learned weights
    """
    adaptive_rag = get_adaptive_rag()

    # --- Layer 1: Apply static per-intent weight overrides ---
    intent_overrides = INTENT_COLLECTION_WEIGHTS.get(intent, {})
    intent_adjusted = {}
    for collection, base_mult in base_multipliers.items():
        override = intent_overrides.get(collection)
        if override is not None:
            # Blend: 60% base, 40% intent override (prevents extreme swings)
            intent_adjusted[collection] = (base_mult * 0.6) + (override * base_mult * 0.4)
        else:
            intent_adjusted[collection] = base_mult
    if intent_overrides:
        logger.debug("[ADAPTIVE] Applied per-intent weights for intent=%s: %s", intent, intent_overrides)

    # --- Layer 2: Apply global feedback-based weights ---
    adjusted = adaptive_rag.get_adjusted_multipliers(intent_adjusted)

    # --- Layer 3: Apply learned per-intent success tracking ---
    if intent:
        intent_learned = adaptive_rag.get_intent_weight_adjustments(intent)
        if intent_learned:
            for collection, mult in adjusted.items():
                learned_factor = intent_learned.get(collection, 1.0)
                adjusted[collection] = mult * learned_factor
            logger.debug(
                "[ADAPTIVE] Applied learned intent adjustments for %s: %s",
                intent, intent_learned,
            )

    # --- Layer 4: Episodic learning boost scores ---
    try:
        from chat_app.self_learning import get_cached_boost_scores
        boost_scores = get_cached_boost_scores()
        if boost_scores:
            for collection, mult in adjusted.items():
                boost = boost_scores.get(collection, 1.0)
                # Apply boost as a secondary multiplier (capped at 0.5x to 1.5x range)
                clamped_boost = max(0.5, min(1.5, boost))
                adjusted[collection] = mult * clamped_boost
            logger.debug(f"[ADAPTIVE] Applied episodic boost to {len(boost_scores)} collections")
    except Exception as _exc:  # broad catch — resilience against all failures
        pass  # Episodic boost not available — no-op

    return adjusted


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Initialize
    rag = SelfAdaptiveRAG()

    # Simulate feedback
    print("\n=== Simulating Feedback ===\n")

    # Good answer from org_repo
    rag.update_from_feedback(
        query="What scheduled searches do we have?",
        response="In your savedsearches.conf:\n[daily_summary]\n...",
        feedback_value=1,
        collections_used=["org_repo_mxbai"],
        username="john"
    )

    # Bad answer from specs
    rag.update_from_feedback(
        query="How to configure inputs?",
        response="[file_name] has [setting] = value",  # Hallucinated
        feedback_value=0,
        collections_used=["specs_mxbai_embed_large_v3"],
        username="jane"
    )

    # Good answer from spl_commands
    rag.update_from_feedback(
        query="How to use stats command?",
        response="The stats command...",
        feedback_value=1,
        collections_used=["spl_commands_mxbai"],
        username="bob"
    )

    print("\n=== Current Weights ===\n")
    print(rag.get_weight_summary())

    print("\n=== Stats ===\n")
    print(json.dumps(rag.get_stats(), indent=2))

    print("\n=== Testing Multiplier Adjustment ===\n")
    base_multipliers = {
        "org_repo_mxbai": 2.0,
        "specs_mxbai_embed_large_v3": 1.5,
        "spl_commands_mxbai": 1.5
    }
    adjusted = rag.get_adjusted_multipliers(base_multipliers)

    for collection, mult in adjusted.items():
        base = base_multipliers.get(collection, 1.0)
        print(f"{collection}:")
        print(f"  Base: {base:.2f} → Adjusted: {mult:.2f}")
