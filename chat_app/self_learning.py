"""
Self-Learning Pipeline — Continuous knowledge improvement.

This module implements the core self-learning loop:
1. Q&A Generation: Creates Q&A pairs from all documentation directories
2. Answer Reassessment: Re-evaluates past answers against current collections
3. Prompt Improvement: Continuously refines prompts based on feedback patterns
4. Memory Baking: Stores learned patterns as semantic facts for future use

Runs as a background task on a schedule and can be triggered manually.

Data models: self_learning_models.py
Q&A extraction: self_learning_generators.py
Feedback/gates/overlay: self_learning_feedback.py
Vector store ingestion: self_learning_ingestion.py
Learning cycle orchestration: self_learning_cycle.py
"""
from __future__ import annotations

import logging
from pathlib import Path  # noqa: F401 — re-exported for test patching (test_save_learning_report patches self_learning.Path)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures (re-exported for backward compatibility)
# ---------------------------------------------------------------------------

from chat_app.self_learning_models import (  # noqa: F401
    LearningReport,
    QAPair,
    ReassessmentResult,
)


# ---------------------------------------------------------------------------
# Q&A generators (re-exported for backward compatibility)
# ---------------------------------------------------------------------------

from chat_app.self_learning_generators import (  # noqa: F401
    _extract_qa_from_config,
    _extract_qa_from_indexes,
    _extract_qa_from_macros,
    _extract_qa_from_metadata,
    _extract_qa_from_org_config,
    _extract_qa_from_savedsearches,
    _extract_qa_from_spl_doc,
    generate_qa_pairs_from_directory,
)


# ---------------------------------------------------------------------------
# Feedback, gates, reassessment, prompt overlay (re-exported for backward compatibility)
# ---------------------------------------------------------------------------

from chat_app.self_learning_feedback import (  # noqa: F401
    _BOOST_MAX_DELTA,
    _BOOST_MIN_SAMPLES,
    _calculate_coverage,
    _check_answer_correctness,
    _check_rule_contradiction,
    _extract_topic,
    _gate_stats,
    _OVERLAY_RULE_MIN_QUALITY,
    _REASSESS_QUALITY_MARGIN,
    _reset_gate_stats,
    analyze_feedback_patterns,
    get_dynamic_prompt_overlay,
    get_gate_stats,
    learn_facts_from_feedback,
    reassess_past_answers,
    rebuild_prompt_overlay,
)


# ---------------------------------------------------------------------------
# Vector store ingestion (re-exported for backward compatibility)
# ---------------------------------------------------------------------------

from chat_app.self_learning_ingestion import (  # noqa: F401
    _extract_cross_ref_terms,
    _query_collection_for_term,
    consolidate_cross_collection_insights,
    ingest_qa_pairs_to_vectorstore,
)


# ---------------------------------------------------------------------------
# Learning cycle orchestration (re-exported for backward compatibility)
# ---------------------------------------------------------------------------

from chat_app.self_learning_cycle import (  # noqa: F401, E402
    run_learning_cycle,
    _get_default_directories,
    _save_learning_report,
    get_cached_boost_scores,
    get_retrieval_boost_scores,
    ModelCustomizationReport,
    export_qa_to_training_data,
    build_combined_training_file,
    generate_modelfile,
    create_custom_model,
    run_model_customization,
)
