"""
Self-Learning Models — Data classes for the self-learning pipeline.

Extracted from self_learning.py for size management.
self_learning.py and self_learning_generators.py import from here.

Provides:
- QAPair dataclass
- ReassessmentResult dataclass
- LearningReport dataclass
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class QAPair:
    """A generated question-answer pair."""
    question: str
    answer: str
    source_file: str = ""
    source_type: str = ""  # spl_doc, config, feedback, metadata
    confidence: float = 0.7
    generated_at: str = ""
    topic: str = ""


@dataclass
class ReassessmentResult:
    """Result of reassessing a past answer."""
    original_question: str
    original_answer: str
    new_answer: Optional[str] = None
    improved: bool = False
    improvement_reason: str = ""
    confidence_delta: float = 0.0


@dataclass
class LearningReport:
    """Summary of a learning cycle."""
    timestamp: str = ""
    qa_pairs_generated: int = 0
    answers_reassessed: int = 0
    answers_improved: int = 0
    facts_learned: int = 0
    prompts_refined: int = 0
    topics_covered: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
