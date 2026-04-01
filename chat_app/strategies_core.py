"""
Core orchestration strategy implementations (strategies 1-12).

This module re-exports all core strategy classes from the sub-modules
that hold the actual implementations.  All existing imports of the form:

    from chat_app.strategies_core import SingleAgentStrategy

continue to work without modification.

Implementation is split for maintainability:
    strategies_core_a.py — Strategies 1-6  (SingleAgent … Voting)
    strategies_core_b.py — Strategies 7-12 (React … Adaptive)
"""

from __future__ import annotations

# Group A: strategies 1-6
from chat_app.strategies_core_a import (  # noqa: F401
    SingleAgentStrategy,
    ParallelStrategy,
    HierarchicalStrategy,
    IterativeStrategy,
    CoordinatorStrategy,
    VotingStrategy,
)

# Group B: strategies 7-12
from chat_app.strategies_core_b import (  # noqa: F401
    ReactStrategy,
    ReviewCritiqueStrategy,
    WorkflowStrategy,
    SwarmStrategy,
    HumanInLoopStrategy,
    AdaptiveStrategy,
)

__all__ = [
    "SingleAgentStrategy",
    "ParallelStrategy",
    "HierarchicalStrategy",
    "IterativeStrategy",
    "CoordinatorStrategy",
    "VotingStrategy",
    "ReactStrategy",
    "ReviewCritiqueStrategy",
    "WorkflowStrategy",
    "SwarmStrategy",
    "HumanInLoopStrategy",
    "AdaptiveStrategy",
]
