"""Self-Learning Cycle & Model Customization — extracted from self_learning.py.

Contains:
- run_learning_cycle: Main orchestrator for the periodic learning loop
- Helper functions: _get_default_directories, _save_learning_report
- Retrieval boost scores: get_cached_boost_scores, get_retrieval_boost_scores
- Model customization pipeline: export, combine, generate Modelfile, create model
- run_model_customization: Full end-to-end customization orchestrator

All public names are re-exported from self_learning.py for backward compatibility.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Main Learning Cycle
# ---------------------------------------------------------------------------

async def run_learning_cycle(
    engine,
    vector_store=None,
    search_func=None,
    doc_directories: List[str] = None,
):
    """
    Execute a full self-learning cycle.

    Steps:
    1. Generate Q&A pairs from all documentation directories
    2. Ingest Q&A pairs into the vector store
    3. Reassess past answers against current collections
    4. Analyze feedback patterns and learn semantic facts
    5. Generate a learning report

    Should be called periodically (e.g., daily via scheduler).
    """
    # Lazy imports to avoid circular dependency with self_learning.py
    from chat_app.self_learning import (
        LearningReport, _extract_qa_from_org_config, _reset_gate_stats,
        consolidate_cross_collection_insights, generate_qa_pairs_from_directory,
        get_gate_stats, ingest_qa_pairs_to_vectorstore, learn_facts_from_feedback,
        reassess_past_answers, rebuild_prompt_overlay,
    )
    import chat_app.self_learning as _sl

    report = LearningReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
    start = time.monotonic()
    step_timings = {}

    # Reset gate decision counters for this cycle
    _reset_gate_stats()

    # Step 1: Generate Q&A pairs from documentation
    _s1 = time.monotonic()
    all_pairs = []
    directories = doc_directories or _get_default_directories()

    for directory in directories:
        pairs = generate_qa_pairs_from_directory(directory)
        all_pairs.extend(pairs)
        topic = Path(directory).name
        if topic not in report.topics_covered:
            report.topics_covered.append(topic)

    # Also extract Q&A from org config (config.yaml index_mappings, field_mappings, etc.)
    try:
        org_pairs = _extract_qa_from_org_config()
        all_pairs.extend(org_pairs)
        if org_pairs:
            logger.info(f"[SELF-LEARN] Step 1: +{len(org_pairs)} Q&A pairs from org config")
            if "org_config" not in report.topics_covered:
                report.topics_covered.append("org_config")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.debug(f"[SELF-LEARN] Org config Q&A extraction skipped: {exc}")

    report.qa_pairs_generated = len(all_pairs)
    step_timings["qa_generation"] = time.monotonic() - _s1
    logger.info(f"[SELF-LEARN] Step 1: Generated {len(all_pairs)} Q&A pairs from {len(directories)} dirs ({step_timings['qa_generation']:.1f}s)")

    # Step 2: Ingest Q&A pairs
    _s2 = time.monotonic()
    if vector_store and all_pairs:
        ingested = await ingest_qa_pairs_to_vectorstore(all_pairs, vector_store)
        logger.info(f"[SELF-LEARN] Step 2: Ingested {ingested} Q&A pairs")
    step_timings["ingestion"] = time.monotonic() - _s2

    # Step 2b: Cross-collection consolidation
    _s2b = time.monotonic()
    try:
        from chat_app.settings import get_settings as _get_settings
        _learn_settings = _get_settings().learning
        _interval_sec = _learn_settings.consolidation_interval_hours * 3600
        _should_run = (
            _learn_settings.cross_collection_consolidation
            and vector_store
            and all_pairs
            and (time.monotonic() - _sl._CONSOLIDATION_LAST_RUN) > _interval_sec
        )
        if _should_run:
            try:
                from chat_app.resource_manager import can_run_heavy_task
                _allowed, _reason = can_run_heavy_task()
            except ImportError:
                _allowed, _reason = True, "resource_manager unavailable"

            if _allowed:
                _insights = await consolidate_cross_collection_insights(
                    all_pairs, vector_store,
                    max_insights=_learn_settings.consolidation_max_insights,
                )
                if _insights:
                    _ingested_insights = await ingest_qa_pairs_to_vectorstore(
                        _insights, vector_store, collection_name="self_learned_qa",
                    )
                    logger.info(f"[SELF-LEARN] Step 2b: Ingested {_ingested_insights} cross-collection insights")
                _sl._CONSOLIDATION_LAST_RUN = time.monotonic()
            else:
                logger.info(f"[SELF-LEARN] Step 2b: Skipped (resources: {_reason})")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[SELF-LEARN] Step 2b cross-collection consolidation skipped: {exc}")
    step_timings["consolidation"] = time.monotonic() - _s2b

    # Step 2c: Seed feedback_qa from high-confidence self-learned pairs
    _s2c = time.monotonic()
    try:
        from chat_app.vectorstore import ensure_feedback_store
        from chat_app.vectorstore_ingest import add_feedback_qa_to_memory
        _fb_store = ensure_feedback_store()
        if _fb_store and all_pairs:
            # Only seed high-confidence SPL doc pairs (these are canonical Q&A)
            _high_conf = [p for p in all_pairs
                          if p.confidence >= 0.8 and p.source_type == "spl_doc"]
            _seeded = 0
            for pair in _high_conf[:50]:  # Cap at 50 to avoid slow embedding
                try:
                    ok, _ = add_feedback_qa_to_memory(
                        pair.question, pair.answer, username="self_learning",
                    )
                    if ok:
                        _seeded += 1
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                    logger.debug("%s", _exc)  # was: pass
            if _seeded:
                logger.info(f"[SELF-LEARN] Step 2c: Seeded {_seeded} high-confidence Q&A pairs into feedback_qa")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[SELF-LEARN] Step 2c feedback_qa seeding skipped: {exc}")
    step_timings["feedback_seed"] = time.monotonic() - _s2c

    # Step 3: Reassess past answers
    _s3 = time.monotonic()
    if engine and search_func and vector_store:
        reassessments = await reassess_past_answers(engine, search_func, vector_store)
        report.answers_reassessed = len(reassessments)
        report.answers_improved = sum(1 for r in reassessments if r.improved)
        logger.info(f"[SELF-LEARN] Step 3: Reassessed {len(reassessments)} answers, {report.answers_improved} improved")
    step_timings["reassessment"] = time.monotonic() - _s3

    # Step 4: Learn from feedback
    _s4 = time.monotonic()
    if engine:
        facts = await learn_facts_from_feedback(engine)
        report.facts_learned = facts
        logger.info(f"[SELF-LEARN] Step 4: Learned {facts} semantic facts")

        # Also consolidate episodes to facts
        try:
            from chat_app.episodic_memory import consolidate_episodes_to_facts
            extra_facts = await consolidate_episodes_to_facts(engine, min_episodes=3)
            report.facts_learned += extra_facts
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug(f"[SELF-LEARN] Episode consolidation skipped: {exc}")

        # Step 5: Rebuild dynamic prompt overlay from all learned knowledge
        try:
            overlay = await rebuild_prompt_overlay(engine)
            if overlay:
                report.prompts_refined = 1
                logger.info(f"[SELF-LEARN] Step 5: Rebuilt prompt overlay ({len(overlay)} chars)")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug(f"[SELF-LEARN] Prompt overlay rebuild skipped: {exc}")

        # Step 6: Refresh retrieval boost cache
        try:
            await get_retrieval_boost_scores(engine)
            logger.info("[SELF-LEARN] Step 6: Retrieval boost scores refreshed")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug(f"[SELF-LEARN] Retrieval boost refresh skipped: {exc}")

    step_timings["feedback_learning"] = time.monotonic() - _s4
    report.duration_seconds = time.monotonic() - start
    _timing_str = ", ".join(f"{k}={v:.1f}s" for k, v in step_timings.items())
    logger.info(
        f"[SELF-LEARN] Learning cycle complete: "
        f"qa={report.qa_pairs_generated}, reassessed={report.answers_reassessed}, "
        f"improved={report.answers_improved}, facts={report.facts_learned}, "
        f"duration={report.duration_seconds:.1f}s, steps=[{_timing_str}]"
    )

    # Log gate decision summary
    gs = get_gate_stats()
    total_reassess = gs["reassess_accepted"] + gs["reassess_rejected_quality"] + gs["reassess_rejected_no_improvement"]
    total_overlay = gs["overlay_rule_accepted"] + gs["overlay_rule_rejected_contradiction"] + gs["overlay_rule_rejected_quality"]
    total_boost = gs["boost_accepted"] + gs["boost_rejected_sample_size"] + gs["boost_clamped"]
    logger.info(
        "[SELF-LEARN] Gate summary: "
        "reassess=%d/%d accepted, "
        "overlay=%d/%d accepted (%d contradictions, %d low-quality), "
        "boost=%d/%d accepted (%d clamped, %d insufficient-samples)",
        gs["reassess_accepted"], total_reassess,
        gs["overlay_rule_accepted"], total_overlay,
        gs["overlay_rule_rejected_contradiction"], gs["overlay_rule_rejected_quality"],
        gs["boost_accepted"], total_boost,
        gs["boost_clamped"], gs["boost_rejected_sample_size"],
    )

    # Persist report
    _save_learning_report(report)

    # Record learning snapshot for history tracking
    try:
        from chat_app.resource_manager import record_learning_snapshot
        success_rate = (report.answers_improved / report.answers_reassessed) if report.answers_reassessed > 0 else 0.0
        record_learning_snapshot(
            qa_pairs=report.qa_pairs_generated,
            facts=report.facts_learned,
            episodes=report.answers_reassessed,
            quality_avg=success_rate,
            success_rate=success_rate,
            notes=[
                f"Topics: {', '.join(report.topics_covered[:5])}",
                f"Duration: {report.duration_seconds:.1f}s",
                f"Steps: {_timing_str}",
            ],
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[SELF-LEARN] Learning snapshot recording skipped: {exc}")

    # Record metrics for dashboard counters
    try:
        from chat_app.health_monitor import get_internal_metrics
        im = get_internal_metrics()
        im.increment("learning_cycles")
        im.increment("qa_pairs_generated", report.qa_pairs_generated)
        im.increment("facts_learned", report.facts_learned)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    return report


def _get_default_directories() -> List[str]:
    """Get default documentation directories to scan."""
    from chat_app.settings import get_settings
    settings = get_settings()

    candidates = [
        settings.paths.spl_docs_root,
        settings.paths.documents_root,
        settings.paths.org_repo_root,
        settings.paths.cribl_docs_root,
        settings.paths.feedback_root,
        settings.paths.spec_static_root,
    ]
    # Also check project-level directories
    project_dirs = [
        "/app/spl_docs",
        "/app/metadata",
    ]
    candidates.extend(project_dirs)

    return [d for d in candidates if d and os.path.isdir(d)]


def _save_learning_report(report):
    """Persist learning report to disk."""
    try:
        report_dir = Path("/app/data/learning_reports")
        report_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = report_dir / f"learning_{timestamp}.json"

        with open(report_path, "w") as f:
            json.dump({
                "timestamp": report.timestamp,
                "qa_pairs_generated": report.qa_pairs_generated,
                "answers_reassessed": report.answers_reassessed,
                "answers_improved": report.answers_improved,
                "facts_learned": report.facts_learned,
                "prompts_refined": report.prompts_refined,
                "topics_covered": report.topics_covered,
                "duration_seconds": report.duration_seconds,
            }, f, indent=2)

        # Keep only last 30 reports
        reports = sorted(report_dir.glob("learning_*.json"))
        for old in reports[:-30]:
            old.unlink(missing_ok=True)

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[SELF-LEARN] Failed to save report: {exc}")


# ---------------------------------------------------------------------------
# Feedback-Driven Retrieval Re-ranking
# ---------------------------------------------------------------------------

# Module-level cache for boost scores (refreshed async, read sync)
_boost_cache: Dict[str, float] = {}


def get_cached_boost_scores() -> Dict[str, float]:
    """Return the last computed boost scores (sync-safe, for retrieval pipeline)."""
    return dict(_boost_cache)


async def get_retrieval_boost_scores(engine) -> Dict[str, float]:
    """
    Calculate collection-level boost scores based on historical success rates.

    Returns a dict of collection_name -> boost_multiplier (0.5-2.0).
    Collections with high success rates get boosted; low success get penalized.
    """
    import chat_app.self_learning as _sl

    global _boost_cache
    boosts = {}
    try:
        from sqlalchemy import text

        async with engine.begin() as conn:
            result = await conn.execute(text("""
                SELECT
                    e.collections_searched,
                    AVG(CASE WHEN e.success = 1 THEN 1.0 ELSE 0.0 END) as success_rate,
                    COUNT(*) as sample_count
                FROM assistant_episodes e
                WHERE e.success >= 0
                  AND e.created_at > NOW() - INTERVAL '30 days'
                  AND e.collections_searched IS NOT NULL
                GROUP BY e.collections_searched
                HAVING COUNT(*) >= 5
            """))
            rows = result.fetchall()

            for row in rows:
                collections_json = row[0]
                success_rate = float(row[1])
                sample_count = int(row[2])
                try:
                    collections = json.loads(collections_json) if isinstance(collections_json, str) else []
                    for coll in collections:
                        if coll:
                            # Gate: require minimum sample size before adjusting weights
                            if sample_count < _sl._BOOST_MIN_SAMPLES:
                                _sl._gate_stats["boost_rejected_sample_size"] += 1
                                logger.debug(
                                    "[SELF-LEARN] Gate REJECTED boost for '%s': "
                                    "samples=%d < min=%d",
                                    coll, sample_count, _sl._BOOST_MIN_SAMPLES,
                                )
                                continue

                            # Map success rate to boost: 0% -> 0.5x, 50% -> 1.0x, 100% -> 1.5x
                            new_boost = 0.5 + success_rate

                            # Gate: clamp adjustment per cycle to +/-_BOOST_MAX_DELTA
                            # to prevent wild swings from noisy feedback.
                            # Only clamp when there is an established baseline
                            # (first-time scores are accepted as-is).
                            if coll in _boost_cache:
                                old_boost = _boost_cache[coll]
                                delta = new_boost - old_boost
                            else:
                                old_boost = None
                                delta = 0.0  # no baseline -- accept as-is
                            if old_boost is not None and abs(delta) > _sl._BOOST_MAX_DELTA:
                                clamped_boost = old_boost + (_sl._BOOST_MAX_DELTA if delta > 0 else -_sl._BOOST_MAX_DELTA)
                                _sl._gate_stats["boost_clamped"] += 1
                                logger.info(
                                    "[SELF-LEARN] Gate CLAMPED boost for '%s': "
                                    "wanted=%.2f, clamped=%.2f (delta %.2f > max %.2f)",
                                    coll, new_boost, clamped_boost, abs(delta), _sl._BOOST_MAX_DELTA,
                                )
                                new_boost = clamped_boost

                            boosts[coll] = max(boosts.get(coll, 0), new_boost)
                            _sl._gate_stats["boost_accepted"] += 1
                            logger.debug(
                                "[SELF-LEARN] Gate ACCEPTED boost for '%s': "
                                "boost=%.2f, samples=%d, success_rate=%.2f",
                                coll, new_boost, sample_count, success_rate,
                            )
                except (json.JSONDecodeError, TypeError):
                    continue

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[SELF-LEARN] Boost calculation failed: {exc}")

    # Update module-level cache for sync access from retrieval pipeline
    _boost_cache = boosts

    return boosts


# ---------------------------------------------------------------------------
# Automatic Model Customization Pipeline
# ---------------------------------------------------------------------------

_MODEL_CUSTOMIZE_MIN_QA = 50  # Minimum Q&A pairs to trigger model update
_TRAINING_DATA_DIR = Path("/app/data/training_data")
_MODELFILE_TEMPLATE = """FROM {base_model}

PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER num_ctx 4096

SYSTEM \"\"\"{system_prompt}\"\"\"
"""


@dataclass
class ModelCustomizationReport:
    """Summary of a model customization run."""
    timestamp: str = ""
    qa_pairs_exported: int = 0
    training_file: str = ""
    modelfile_path: str = ""
    model_created: bool = False
    model_name: str = ""
    error: str = ""


def export_qa_to_training_data(
    qa_pairs,
    output_dir: str = None,
    system_prompt: str = None,
) -> Tuple[str, int]:
    """
    Export Q&A pairs to training JSONL format for Ollama/fine-tuning.

    Returns (filepath, count) of the exported file.
    """
    out_dir = Path(output_dir) if output_dir else _TRAINING_DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = out_dir / f"self_learned_{timestamp}.jsonl"

    sys_prompt = system_prompt or (
        "You are a Splunk expert assistant with deep knowledge of SPL, "
        "Splunk configuration, log analysis, and observability best practices. "
        "Never use or suggest `index=*`. Prefer tstats with CIM data models."
    )

    count = 0
    with open(filepath, "w", encoding="utf-8") as f:
        for pair in qa_pairs:
            if not pair.question or not pair.answer:
                continue
            entry = {
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": pair.question},
                    {"role": "assistant", "content": pair.answer},
                ],
                "metadata": {
                    "source_file": pair.source_file,
                    "source_type": pair.source_type,
                    "topic": pair.topic,
                    "confidence": pair.confidence,
                },
            }
            f.write(json.dumps(entry) + "\n")
            count += 1

    logger.info(f"[MODEL-CUSTOM] Exported {count} Q&A pairs to {filepath}")
    return str(filepath), count


def build_combined_training_file(output_dir: str = None) -> Tuple[str, int]:
    """
    Combine all training JSONL files in the training data directory into one.

    Returns (filepath, total_count).
    """
    out_dir = Path(output_dir) if output_dir else _TRAINING_DATA_DIR
    if not out_dir.is_dir():
        return "", 0

    combined_path = out_dir / "combined_training.jsonl"
    seen_hashes = set()
    total = 0

    with open(combined_path, "w", encoding="utf-8") as out:
        for jsonl_file in sorted(out_dir.glob("*.jsonl")):
            if jsonl_file.name == "combined_training.jsonl":
                continue
            try:
                for line in jsonl_file.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    h = hashlib.sha256(line.encode()).hexdigest()
                    if h not in seen_hashes:
                        seen_hashes.add(h)
                        out.write(line + "\n")
                        total += 1
            except Exception as _exc:  # broad catch — resilience against all failures
                continue

    logger.info(f"[MODEL-CUSTOM] Combined training file: {total} entries at {combined_path}")
    return str(combined_path), total


def generate_modelfile(
    base_model: str = None,
    system_prompt: str = None,
    output_dir: str = None,
) -> str:
    """
    Generate an Ollama Modelfile with the current system prompt and learned rules.

    Returns the path to the generated Modelfile.
    """
    from chat_app.settings import get_settings
    from chat_app.self_learning import get_dynamic_prompt_overlay

    settings = get_settings()

    model = base_model or settings.ollama.model
    out_dir = Path(output_dir) if output_dir else _TRAINING_DATA_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # Build system prompt with dynamic overlay
    base_prompt = system_prompt or (
        "You are a Splunk expert assistant with deep knowledge of SPL, "
        "Splunk configuration (.conf/.spec files), log analysis, troubleshooting, "
        "and observability best practices.\n\n"
        "Key rules:\n"
        "- Never use or suggest `index=*` — always specify the correct index.\n"
        "- Prefer `| tstats` with CIM data models for performance.\n"
        "- Use TERM() and PREFIX() to leverage index-time tokenization.\n"
        "- When explaining configs, reference the relevant .spec file documentation.\n"
        "- Provide complete, working SPL queries with proper field names."
    )

    # Append learned behavioral rules if available
    overlay = get_dynamic_prompt_overlay()
    if overlay:
        # Extract just the rules, not section headers
        rules = [line.strip("- ").strip() for line in overlay.split("\n")
                 if line.strip().startswith("- ")]
        if rules:
            base_prompt += "\n\nLearned rules from past interactions:\n"
            base_prompt += "\n".join(f"- {r}" for r in rules[:15])

    content = _MODELFILE_TEMPLATE.format(
        base_model=model,
        system_prompt=base_prompt.replace('"""', '\\"\\"\\"'),
    )

    modelfile_path = out_dir / "Modelfile"
    modelfile_path.write_text(content, encoding="utf-8")
    logger.info(f"[MODEL-CUSTOM] Generated Modelfile at {modelfile_path} (base: {model})")
    return str(modelfile_path)


async def create_custom_model(
    model_name: str = None,
    modelfile_path: str = None,
    base_model: str = None,
) -> ModelCustomizationReport:
    """
    Create a custom Ollama model using the generated Modelfile.

    Calls `ollama create` with the Modelfile. Requires Ollama to be accessible.
    """
    from chat_app.settings import get_settings
    settings = get_settings()

    report = ModelCustomizationReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    try:
        base = base_model or settings.ollama.model
        name = model_name or f"{base.replace(':', '-')}-splunk-tuned"
        mf_path = modelfile_path or generate_modelfile(base_model=base)

        report.model_name = name
        report.modelfile_path = mf_path

        # Use ollama API to create the model
        ollama_url = settings.ollama.base_url.rstrip("/")

        import aiohttp
        async with aiohttp.ClientSession() as session:
            # Read the Modelfile content
            mf_content = Path(mf_path).read_text(encoding="utf-8")

            async with session.post(
                f"{ollama_url}/api/create",
                json={"name": name, "modelfile": mf_content},
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:
                if resp.status == 200:
                    report.model_created = True
                    logger.info(f"[MODEL-CUSTOM] Model '{name}' created successfully")
                else:
                    body = await resp.text()
                    report.error = f"Ollama API error {resp.status}: {body[:200]}"
                    logger.warning(f"[MODEL-CUSTOM] Model creation failed: {report.error}")

    except ImportError:
        # aiohttp not available -- fall back to subprocess
        import subprocess
        try:
            mf_path = report.modelfile_path or generate_modelfile()
            result = subprocess.run(
                ["ollama", "create", report.model_name, "-f", mf_path],
                capture_output=True, text=True, timeout=300,
            )
            if result.returncode == 0:
                report.model_created = True
                logger.info(f"[MODEL-CUSTOM] Model '{report.model_name}' created via CLI")
            else:
                report.error = result.stderr[:200]
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            report.error = f"CLI fallback failed: {exc}"

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        report.error = str(exc)
        logger.warning(f"[MODEL-CUSTOM] Model creation error: {exc}")

    return report


async def run_model_customization(
    engine=None,
    vector_store=None,
    doc_directories: List[str] = None,
    force: bool = False,
) -> ModelCustomizationReport:
    """
    Full model customization pipeline:
    1. Generate Q&A pairs from all sources
    2. Export to training JSONL
    3. Combine all training data
    4. Generate Modelfile with learned rules
    5. Create custom Ollama model

    Called monthly by the scheduler or manually via /learn trigger.
    """
    from chat_app.self_learning import _extract_qa_from_org_config, generate_qa_pairs_from_directory

    report = ModelCustomizationReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
    )

    try:
        # Step 1: Generate Q&A pairs
        all_pairs = []
        directories = doc_directories or _get_default_directories()
        for directory in directories:
            pairs = generate_qa_pairs_from_directory(directory)
            all_pairs.extend(pairs)

        # Add org config pairs
        try:
            org_pairs = _extract_qa_from_org_config()
            all_pairs.extend(org_pairs)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

        if len(all_pairs) < _MODEL_CUSTOMIZE_MIN_QA and not force:
            report.error = f"Not enough Q&A pairs ({len(all_pairs)} < {_MODEL_CUSTOMIZE_MIN_QA})"
            logger.info(f"[MODEL-CUSTOM] Skipping: {report.error}")
            return report

        # Step 2: Export to training JSONL
        training_file, count = export_qa_to_training_data(all_pairs)
        report.training_file = training_file
        report.qa_pairs_exported = count

        # Step 3: Combine all training data
        combined_file, total = build_combined_training_file()
        logger.info(f"[MODEL-CUSTOM] Combined training data: {total} entries")

        # Step 4: Generate Modelfile
        modelfile_path = generate_modelfile()
        report.modelfile_path = modelfile_path

        # Step 5: Create custom model
        creation = await create_custom_model(modelfile_path=modelfile_path)
        report.model_created = creation.model_created
        report.model_name = creation.model_name
        if creation.error:
            report.error = creation.error

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        report.error = str(exc)
        logger.warning(f"[MODEL-CUSTOM] Pipeline error: {exc}")

    # Persist report
    try:
        report_dir = Path("/app/data/learning_reports")
        report_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        with open(report_dir / f"model_custom_{timestamp}.json", "w") as f:
            json.dump({
                "timestamp": report.timestamp,
                "qa_pairs_exported": report.qa_pairs_exported,
                "training_file": report.training_file,
                "modelfile_path": report.modelfile_path,
                "model_created": report.model_created,
                "model_name": report.model_name,
                "error": report.error,
            }, f, indent=2)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    return report
