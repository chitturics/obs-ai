"""
Shared SPL analysis, optimization, and NLP-to-SPL modules.

Used by both the main Chainlit app (chat_app/) and the
search optimizer microservice (containers/search_opt/).

Public API — import from here for stable, documented interfaces.
"""

# --- Constants (single source of truth) ---
from shared.constants import (
    COMMAND_COSTS,
    CPU_WEIGHTS,
    DANGEROUS_COMMANDS,
    DISTRIBUTABLE_COMMANDS,
    EXPENSIVE_COMMAND_RISKS,
    GENERATING_COMMANDS,
    HIGH_CARDINALITY_FIELDS,
    INVALID_PATTERNS,
    KNOWN_COMMANDS,
    LOW_CARDINALITY_FIELDS,
    MEDIUM_CARDINALITY_FIELDS,
    MEMORY_WEIGHTS,
    METRIC_FIELD_PATTERNS,
    METRIC_INDEX_PATTERNS,
    NON_DISTRIBUTABLE_COMMANDS,
    STREAMING_COMMANDS,
    TIME_MULTIPLIERS,
    TIME_UNITS,
    TRANSFORMING_COMMANDS,
    TSTATS_BLOCKERS,
    TSTATS_OPPORTUNITY_COMMANDS,
)

# --- Utilities ---
from shared.utils import (
    estimate_cardinality,
    extract_by_fields,
    extract_command,
    extract_earliest_latest,
    extract_indexes,
    extract_sourcetypes,
    extract_time_range_seconds,
    parse_relative_time,
    seconds_to_human,
    split_pipeline,
)

# --- Core Analysis ---
from shared.spl_analyzer import SPLAnalyzer, UserIntent
from shared.spl_validator import (
    RiskLevel,
    SPLValidator,
    ValidationResult,
    ValidationStatus,
    validate_spl,
    validate_spl_response,
    is_valid_spl,
    get_risk_score,
)

# --- Knowledge Base ---
from shared.spl_knowledge_base import SPLKnowledgeBase, get_knowledge_base

# --- Query Optimization ---
from shared.spl_query_optimizer import (
    ConversionStatus,
    OptimizationStrategy,
    OptimizedQuery,
    SPLQueryOptimizer,
)

# --- Template Engine ---
from shared.spl_template_engine import SPLTemplateEngine

# --- Robust Analyzer ---
from shared.spl_robust_analyzer import (
    RobustSPLAnalyzer,
    analyze_spl,
    get_robust_analyzer,
    suggest_search,
    validate_and_optimize,
)

# --- Deep Analysis ---
from shared.spl_deep_analysis import (
    DeepAnalysisResult,
    SPLDeepAnalyzer,
    deep_analyze,
    get_deep_analyzer,
)

# --- Cost Estimation ---
from shared.query_cost_estimator import QueryCostEstimator

# --- Rules ---
from shared.spl_rules import ANTI_PATTERNS, BEST_PRACTICES

# --- Config Management ---
from shared.conf_parser import (
    chunk_conf_file,
    enrich_chunk_for_search,
    extract_app_metadata,
    parse_conf_file_advanced,
)
from shared.conf_loader import (
    load_commands_from_conf,
    load_indexes_from_conf,
    load_macros_from_conf,
    load_macros_flat,
    load_searches_from_conf,
    parse_conf_file,
)
from shared.config_analyzer import ConfigAnalyzer

# --- NLP to SPL ---
from shared.nlp_to_spl import NLPtoSPL, get_nlp_generator, SPLGenerationResult

# --- Intents ---
from shared.spl_intents import SPLIntent, INTENT_TEMPLATES

# --- Splunk Documentation ---
from shared.docs_loader import get_docs, SplunkDocsIndex, CommandDoc, SpecDoc


__all__ = [
    # Constants
    "COMMAND_COSTS", "CPU_WEIGHTS", "DANGEROUS_COMMANDS",
    "DISTRIBUTABLE_COMMANDS", "EXPENSIVE_COMMAND_RISKS",
    "GENERATING_COMMANDS", "HIGH_CARDINALITY_FIELDS",
    "INVALID_PATTERNS", "KNOWN_COMMANDS", "LOW_CARDINALITY_FIELDS",
    "MEDIUM_CARDINALITY_FIELDS", "MEMORY_WEIGHTS",
    "METRIC_FIELD_PATTERNS", "METRIC_INDEX_PATTERNS",
    "NON_DISTRIBUTABLE_COMMANDS", "STREAMING_COMMANDS",
    "TIME_MULTIPLIERS", "TIME_UNITS", "TRANSFORMING_COMMANDS",
    "TSTATS_BLOCKERS", "TSTATS_OPPORTUNITY_COMMANDS",
    # Utilities
    "estimate_cardinality", "extract_by_fields", "extract_command",
    "extract_earliest_latest", "extract_indexes", "extract_sourcetypes",
    "extract_time_range_seconds", "parse_relative_time",
    "seconds_to_human", "split_pipeline",
    # Analysis
    "SPLAnalyzer", "UserIntent",
    # Validation
    "SPLValidator", "ValidationStatus", "ValidationResult", "RiskLevel",
    "validate_spl", "validate_spl_response", "is_valid_spl", "get_risk_score",
    # Knowledge Base
    "SPLKnowledgeBase", "get_knowledge_base",
    # Optimization
    "SPLQueryOptimizer", "ConversionStatus", "OptimizationStrategy", "OptimizedQuery",
    # Template Engine
    "SPLTemplateEngine",
    # Robust Analyzer
    "RobustSPLAnalyzer", "analyze_spl", "get_robust_analyzer",
    "suggest_search", "validate_and_optimize",
    # Deep Analysis
    "SPLDeepAnalyzer", "DeepAnalysisResult", "deep_analyze", "get_deep_analyzer",
    # Cost Estimation
    "QueryCostEstimator",
    # Rules
    "ANTI_PATTERNS", "BEST_PRACTICES",
    # Config Management
    "ConfigAnalyzer", "chunk_conf_file", "enrich_chunk_for_search",
    "extract_app_metadata", "parse_conf_file_advanced",
    "load_commands_from_conf", "load_indexes_from_conf",
    "load_macros_from_conf", "load_macros_flat",
    "load_searches_from_conf", "parse_conf_file",
    # NLP to SPL
    "NLPtoSPL", "get_nlp_generator", "SPLGenerationResult",
    # Intents
    "SPLIntent", "INTENT_TEMPLATES",
    # Documentation
    "get_docs", "SplunkDocsIndex", "CommandDoc", "SpecDoc",
]
