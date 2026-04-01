"""
Organization Data Loader - Initializes pipeline components with org-specific data.

Reads organization config from config.yaml, parses .conf files from the
configured paths, and registers macros, saved searches, index mappings,
field mappings, and CIM models with:
  - NLPtoSPL (few-shot learning examples)
  - SPLQueryOptimizer (macro expansion + CIM models)
  - SPLAnalyzer (index mappings)

Called once at app startup.  Graceful degradation: if no org data is
available, components continue with their built-in defaults.
"""

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from shared.conf_loader import (
    load_commands_from_conf,
    load_indexes_from_conf,
    load_macros_from_conf,
    load_searches_from_conf,
)
from shared.spl_query_optimizer import SPLQueryOptimizer
from shared.nlp_to_spl import get_nlp_generator
from shared.spl_analyzer import SPLAnalyzer


def _create_spl_llm():
    """Create a dedicated LLM for SPL generation from centralized settings."""
    try:
        from langchain_ollama import ChatOllama
    except ImportError:
        logger.debug("langchain-ollama not available - NLPtoSPL will use direct-match only")
        return None

    from chat_app.settings import get_settings
    cfg = get_settings().ollama

    model = cfg.spl_model or cfg.model
    temperature = cfg.spl_temperature

    try:
        llm = ChatOllama(
            model=model,
            base_url=cfg.base_url,
            temperature=temperature,
            num_predict=cfg.spl_num_predict,
            streaming=False,
        )
        logger.info("SPL LLM created: model=%s, temp=%s", model, temperature)
        return llm
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.warning("Failed to create SPL LLM: %s", e)
        return None


logger = logging.getLogger(__name__)

# Singleton guard
_initialized = False
_org_stats: Dict[str, Any] = {}


def _load_config() -> Dict[str, Any]:
    """Load the organization section from config.yaml."""
    candidates = [
        Path(os.getenv("CONFIG_YAML", "")),
        Path("/app/config.yaml"),
        Path.cwd() / "config.yaml",
        Path(__file__).resolve().parent.parent / "config.yaml",
    ]
    for path in candidates:
        try:
            if path.is_file():
                with open(path, encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                return cfg.get("organization", {})
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.debug(f"Config candidate {path} skipped: {e}")
    return {}


def _resolve_config_paths(org_cfg: Dict) -> list[Path]:
    """Resolve config_paths to existing directories."""
    raw_paths = org_cfg.get("config_paths", [])
    project_root = Path(__file__).resolve().parent.parent
    resolved = []
    for p in raw_paths:
        candidate = Path(p)
        if not candidate.is_absolute():
            candidate = project_root / candidate
        if candidate.is_dir():
            resolved.append(candidate)
    return resolved


def _load_feedback_qa() -> list[Dict[str, Any]]:
    """Load liked queries from feedback file for NLP learning."""
    candidates = [
        Path.cwd() / "feedback" / "liked_queries.json",
        Path(__file__).resolve().parent.parent / "feedback" / "liked_queries.json",
    ]
    for path in candidates:
        if path.is_file():
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    return data
                # If it's a dict with metadata, skip it
                if isinstance(data, dict) and "notes" in data:
                    return []
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
                logger.debug(f"Could not load feedback from {path}: {e}")
    return []


def initialize_org_data(config: Optional[Dict] = None) -> Dict[str, Any]:
    """
    Load org data and register with all pipeline components.

    Args:
        config: Optional pre-loaded organization config dict.
                If None, reads from config.yaml.

    Returns:
        Stats dict with counts of loaded items.
    """
    global _initialized, _org_stats
    if _initialized:
        return _org_stats

    org_cfg = config or _load_config()
    stats: Dict[str, Any] = {
        "macros": 0,
        "saved_searches": 0,
        "commands": 0,
        "indexes": 0,
        "feedback_qa": 0,
        "cim_models_added": 0,
        "config_paths_found": 0,
    }

    # Resolve config paths
    config_paths = _resolve_config_paths(org_cfg)
    stats["config_paths_found"] = len(config_paths)
    if not config_paths:
        logger.info("No organization config paths found - using built-in defaults")
        _initialized = True
        _org_stats = stats
        return stats

    logger.info(f"Loading org data from {len(config_paths)} paths: {config_paths}")

    # --- Aggregate data from all config paths ---
    all_macros: Dict[str, Dict] = {}
    all_searches: Dict[str, Dict] = {}
    all_commands: Dict[str, Dict] = {}
    all_indexes: list[str] = []

    for path in config_paths:
        try:
            macros = load_macros_from_conf(path)
            all_macros.update(macros)
            stats["macros"] += len(macros)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning(f"Failed to load macros from {path}: {e}")

        try:
            searches = load_searches_from_conf(path)
            all_searches.update(searches)
            stats["saved_searches"] += len(searches)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning(f"Failed to load saved searches from {path}: {e}")

        try:
            commands = load_commands_from_conf(path)
            all_commands.update(commands)
            stats["commands"] += len(commands)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning(f"Failed to load commands from {path}: {e}")

        try:
            indexes = load_indexes_from_conf(path)
            all_indexes.extend(i for i in indexes if i not in all_indexes)
            stats["indexes"] += len(indexes)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning(f"Failed to load indexes from {path}: {e}")

    # --- Load feedback Q&A ---
    feedback_qa = _load_feedback_qa()
    stats["feedback_qa"] = len(feedback_qa)

    # --- Get mappings from config ---
    index_mappings = org_cfg.get("index_mappings", {})
    field_mappings = org_cfg.get("field_mappings", {})
    additional_cim = org_cfg.get("additional_cim_models", {})

    # --- Register with SPLQueryOptimizer ---
    try:
        if all_macros:
            SPLQueryOptimizer.register_macros(all_macros)
            logger.info(f"Registered {len(all_macros)} macros with SPLQueryOptimizer")
        if additional_cim:
            SPLQueryOptimizer.register_cim_models(additional_cim)
            stats["cim_models_added"] = len(additional_cim)
            logger.info(f"Registered {len(additional_cim)} additional CIM models")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.warning(f"Failed to register with SPLQueryOptimizer: {e}")

    # --- Register with NLPtoSPL (with LLM for generation) ---
    try:
        spl_llm = _create_spl_llm()
        gen = get_nlp_generator(llm=spl_llm)

        if all_macros:
            gen.load_macros(all_macros)
        if all_searches:
            gen.load_saved_searches(all_searches)
        if feedback_qa:
            gen.load_feedback_qa(feedback_qa)
        if index_mappings:
            gen.set_index_mappings(index_mappings)
        if field_mappings:
            gen.set_field_mappings(field_mappings)

        logger.info(f"NLP generator stats: {gen.get_stats()}")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.warning(f"Failed to register with NLPtoSPL: {e}")

    # --- Register with SPLAnalyzer ---
    try:
        if index_mappings:
            SPLAnalyzer.set_index_mappings(index_mappings)
            logger.info(f"Set {len(index_mappings)} index mappings on SPLAnalyzer")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.warning(f"Failed to register with SPLAnalyzer: {e}")

    # --- Seed feedback_qa collection from liked_queries.json ---
    if feedback_qa:
        try:
            from chat_app.vectorstore_ingest import add_feedback_qa_to_memory
            _seeded = 0
            for entry in feedback_qa:
                q = entry.get("question", "")
                a = entry.get("answer", "")
                if q and a:
                    ok, _ = add_feedback_qa_to_memory(q, a, username=entry.get("liked_by", "seed"))
                    if ok:
                        _seeded += 1
            if _seeded:
                stats["feedback_qa_seeded"] = _seeded
                logger.info(f"Seeded {_seeded} Q&A pairs into feedback_qa collection from liked_queries.json")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning(f"Failed to seed feedback_qa collection: {e}")

    _initialized = True
    _org_stats = stats
    logger.info(f"Organization data loaded: {stats}")
    return stats


def get_org_stats() -> Dict[str, Any]:
    """Return stats from the last initialization (empty if not yet run)."""
    return _org_stats
