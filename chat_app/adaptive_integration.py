"""
Integration hooks for self-adaptive RAG system.

This module provides easy integration points for:
1. Updating retrieval profiles with adaptive weights
2. Processing feedback for learning
3. Monitoring adaptive learning progress
"""
import logging
from typing import Dict, List
from profiles import RetrievalStrategy, get_strategy
from self_adaptive_rag import get_adaptive_rag, apply_adaptive_learning

logger = logging.getLogger(__name__)


def get_adaptive_strategy(
    profile_name: str,
    enable_adaptation: bool = True
) -> RetrievalStrategy:
    """
    Get retrieval strategy with adaptive weights applied.

    Args:
        profile_name: Profile name (org_expert, spl_expert, etc.)
        enable_adaptation: Whether to apply adaptive learning (default: True)

    Returns:
        RetrievalStrategy with adjusted fetch_multipliers
    """
    # Get base strategy from profile
    base_strategy = get_strategy(profile_name)

    if not enable_adaptation:
        return base_strategy

    try:
        # Get adaptive multipliers
        adaptive_rag = get_adaptive_rag()
        adjusted_multipliers = adaptive_rag.get_adjusted_multipliers(
            base_strategy.fetch_multipliers
        )

        # Create new strategy with adjusted multipliers
        adaptive_strategy = RetrievalStrategy(
            top_n_per_collection=base_strategy.top_n_per_collection,
            keep_per_collection=base_strategy.keep_per_collection,
            fetch_multipliers=adjusted_multipliers,
            use_reranking=base_strategy.use_reranking,
            diversity_weight=base_strategy.diversity_weight
        )

        logger.info(
            f"[ADAPTIVE] Applied adaptive weights to {profile_name} profile. "
            f"Multipliers adjusted based on {adaptive_rag.get_stats()['total_feedback_entries']} feedback entries."
        )

        return adaptive_strategy

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.error(f"[ADAPTIVE] Failed to apply adaptive weights: {e}. Using base strategy.")
        return base_strategy


def process_feedback(
    feedback_value: int,
    query: str,
    response: str,
    chunks_used: List[Dict],
    username: str = "unknown"
):
    """
    Process user feedback for adaptive learning.

    Call this when user provides thumbs up/down feedback in the UI.

    Args:
        feedback_value: 1 for thumbs up, 0 for thumbs down
        query: User's original query
        response: LLM's response
        chunks_used: List of chunks/documents used in response
        username: Username for tracking

    Example:
        # In your feedback handler:
        @cl.on_message
        async def handle_feedback(message):
            if message.type == "user_feedback":
                process_feedback(
                    feedback_value=1 if message.value > 0 else 0,
                    query=message.parent_message.query,
                    response=message.parent_message.response,
                    chunks_used=message.parent_message.chunks,
                    username=cl.user_session.get("username")
                )
    """
    try:
        apply_adaptive_learning(
            feedback_value=feedback_value,
            query=query,
            response=response,
            chunks_used=chunks_used,
            username=username
        )

        logger.info(
            f"[ADAPTIVE] Processed {'positive' if feedback_value == 1 else 'negative'} feedback "
            f"from {username}. Query: {query[:50]}..."
        )

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.error(f"[ADAPTIVE] Failed to process feedback: {e}")


def get_adaptive_stats() -> Dict:
    """
    Get current adaptive learning statistics.

    Returns:
        Dictionary with learning stats and collection weights
    """
    try:
        adaptive_rag = get_adaptive_rag()
        return adaptive_rag.get_stats()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.error(f"[ADAPTIVE] Failed to get stats: {e}")
        return {"error": str(e)}


def get_adaptive_weight_summary() -> str:
    """
    Get human-readable summary of current adaptive weights.

    Returns:
        Formatted string showing collection weights and success rates
    """
    try:
        adaptive_rag = get_adaptive_rag()
        return adaptive_rag.get_weight_summary()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.error(f"[ADAPTIVE] Failed to get summary: {e}")
        return f"Error: {e}"


# Integration example for app.py
def example_integration():
    """
    Example showing how to integrate adaptive RAG into app.py

    Add this to your search_similar_chunks function:
    """
    example_code = '''
# In chat_app/app.py, modify search_similar_chunks:

from adaptive_integration import get_adaptive_strategy, process_feedback

async def search_similar_chunks(query: str, profile: str = "default"):
    """Search with adaptive learning"""

    # BEFORE (static strategy):
    # strategy = get_strategy(profile)

    # AFTER (adaptive strategy):
    strategy = get_adaptive_strategy(profile, enable_adaptation=True)

    # ... rest of search logic ...

    return chunks

# When user provides feedback (in on_action handler):

@cl.on_action
async def on_action(action):
    if action.name == "thumbs_up" or action.name == "thumbs_down":
        feedback_value = 1 if action.name == "thumbs_up" else 0

        # Get query, response, and chunks from message metadata
        message_id = action.value
        query = cl.user_session.get(f"query_{message_id}")
        response = cl.user_session.get(f"response_{message_id}")
        chunks_used = cl.user_session.get(f"chunks_{message_id}")
        username = cl.user_session.get("username", "unknown")

        # Apply adaptive learning
        process_feedback(
            feedback_value=feedback_value,
            query=query,
            response=response,
            chunks_used=chunks_used,
            username=username
        )

        await cl.Message(
            content=f"✅ Thank you! Your feedback helps me learn and improve."
        ).send()

# To monitor adaptive learning:

@cl.on_message
async def handle_message(message: cl.Message):
    if message.content.lower() == "/adaptive_stats":
        stats = get_adaptive_stats()
        summary = get_adaptive_weight_summary()

        response = f"""
📊 **Self-Adaptive Learning Statistics**

**Feedback Processed:** {stats['total_feedback_entries']} entries
**Patterns Learned:** {stats['total_patterns_learned']}
**Last Updated:** {stats['last_updated']}

**Collection Weights:**
{summary}

*Weights are dynamically adjusted based on thumbs up/down feedback.*
        """

        await cl.Message(content=response).send()
        return
    '''

    print(example_code)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("=== Self-Adaptive RAG Integration Guide ===\n")
    example_integration()

    print("\n=== Testing Adaptive Strategy ===\n")

    # Test getting adaptive strategy
    strategy = get_adaptive_strategy("org_expert", enable_adaptation=True)
    print("Adaptive Strategy for org_expert:")
    print(f"  top_n: {strategy.top_n_per_collection}")
    print(f"  keep: {strategy.keep_per_collection}")
    print(f"  multipliers: {strategy.fetch_multipliers}")

    print("\n=== Current Stats ===\n")
    print(get_adaptive_weight_summary())
