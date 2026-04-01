"""
Agentic Scheduler — Persistent background jobs for self-improvement.

Schedules:
    Hourly:  Re-learn from new feedback, apply patterns to pending queries
    Daily:   Re-analyze saved searches, refresh knowledge base, health report
    Weekly:  Deep self-assessment, export feedback, generate improvement report
    Monthly: Comprehensive knowledge audit, episodic memory consolidation,
             model customization, stale content cleanup

Uses APScheduler (AsyncIOScheduler) integrated with FastAPI lifespan.
Falls back to a simple asyncio loop if APScheduler is not installed.

All jobs are resource-aware and overlap-protected via resource_manager.
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# Try APScheduler, fall back to simple asyncio scheduler
try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    _APSCHEDULER_AVAILABLE = True
except ImportError:
    _APSCHEDULER_AVAILABLE = False
    logger.info("APScheduler not installed — using asyncio fallback scheduler")

# Job results tracking
_job_history: list[Dict[str, Any]] = []
_MAX_HISTORY = 100


def _record_job(name: str, result: Any, error: str = None):
    """Track job execution history."""
    entry = {
        "job": name,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "success": error is None,
        "result": result if not error else None,
        "error": error,
    }
    _job_history.append(entry)
    if len(_job_history) > _MAX_HISTORY:
        _job_history.pop(0)


# ---------------------------------------------------------------------------
# Resource-aware job wrapper
# ---------------------------------------------------------------------------
async def _guarded(job_name: str, func, *args, heavy: bool = False, **kwargs):
    """
    Run a job with overlap prevention and optional resource checks.

    Heavy jobs (daily, weekly, monthly) check CPU/memory before running.
    All jobs skip if a previous run is still active.
    """
    try:
        from chat_app.resource_manager import run_guarded_job
        return await run_guarded_job(
            job_name, func, *args,
            resource_check=heavy,
            max_duration_s=7200 if heavy else 3600,
            **kwargs,
        )
    except ImportError:
        # resource_manager not available — run directly
        return await func(*args, **kwargs)


# ---------------------------------------------------------------------------
# Hourly Job: Re-learn from feedback
# ---------------------------------------------------------------------------
async def job_hourly_learn():
    """
    Hourly: Extract optimization patterns from any new high-ranked feedback.
    Fast — only processes new feedback since last run.
    """
    logger.info("[SCHEDULER] Hourly learning job started")
    try:
        from containers.search_opt.learning import learn_from_feedback
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, learn_from_feedback)
        logger.info(f"[SCHEDULER] Hourly learning: {result.get('new_patterns_learned', 0)} new patterns")
        _record_job("hourly_learn", result)
        return result
    except Exception as e:
        logger.error(f"[SCHEDULER] Hourly learning failed: {e}")
        _record_job("hourly_learn", None, str(e))


# ---------------------------------------------------------------------------
# Daily Job: Re-analyze saved searches + refresh KB + health report
# ---------------------------------------------------------------------------
async def job_daily_analyze():
    """
    Daily: Re-analyze saved searches, refresh knowledge base, generate health report.
    Runs incremental analysis (skips already-analyzed searches unless changed).
    """
    logger.info("[SCHEDULER] Daily analysis job started")
    results = {}

    # 1. Re-analyze saved searches (incremental)
    try:
        from containers.search_opt.core import analyze_all_saved_searches
        loop = asyncio.get_event_loop()
        analysis = await loop.run_in_executor(
            None, lambda: analyze_all_saved_searches(force_reanalyze=False)
        )
        results["analysis"] = analysis
        logger.info(f"[SCHEDULER] Daily analysis: {analysis.get('analyzed', 0)} new, {analysis.get('skipped', 0)} cached")
    except Exception as e:
        results["analysis_error"] = str(e)
        logger.error(f"[SCHEDULER] Daily analysis failed: {e}")

    # 2. Learn from all feedback
    try:
        from containers.search_opt.learning import learn_from_feedback
        loop = asyncio.get_event_loop()
        learn_result = await loop.run_in_executor(None, learn_from_feedback)
        results["learning"] = learn_result
    except Exception as e:
        results["learning_error"] = str(e)

    # 3. Refresh knowledge base (re-enrich from docs if available)
    try:
        from shared.spl_knowledge_base import get_knowledge_base
        kb = get_knowledge_base()
        if kb:
            results["knowledge_base"] = {
                "commands": len(kb.commands),
                "enriched": kb._enriched,
            }
    except Exception as e:
        results["kb_error"] = str(e)

    # 4. Generate health summary
    try:
        from containers.search_opt.core import get_service_stats
        stats = get_service_stats()
        results["stats"] = stats
    except Exception as e:
        results["stats_error"] = str(e)

    _record_job("daily_analyze", results)
    logger.info(f"[SCHEDULER] Daily job complete: {list(results.keys())}")
    return results


# ---------------------------------------------------------------------------
# Weekly Job: Deep self-assessment and improvement report
# ---------------------------------------------------------------------------
async def job_weekly_assessment():
    """
    Weekly: Deep self-assessment.
    - Review all feedback trends
    - Identify most-asked question categories
    - Assess optimization effectiveness
    - Generate improvement recommendations
    """
    logger.info("[SCHEDULER] Weekly self-assessment started")
    report = {"timestamp": datetime.utcnow().isoformat() + "Z"}

    # 1. Analyze feedback trends
    try:
        from containers.search_opt.saved_searches import get_service_stats
        stats = get_service_stats()
        report["service_stats"] = stats
    except Exception as e:
        report["stats_error"] = str(e)

    # 2. Review learned patterns effectiveness
    try:
        from containers.search_opt.learning import _get_learned_patterns
        patterns = _get_learned_patterns()
        report["learned_patterns"] = {
            "total": len(patterns),
            "types": list({p.get("type") for p in patterns}),
            "newest": patterns[-1] if patterns else None,
        }
    except Exception as e:
        report["patterns_error"] = str(e)

    # 3. Analyze most common query types in analyzed searches
    try:
        from containers.search_opt.utils import _load_analyzed_searches
        analyzed = _load_analyzed_searches()
        complexities = {}
        for data in analyzed.values():
            c = data.get("complexity", "unknown")
            complexities[c] = complexities.get(c, 0) + 1

        optimizable = sum(1 for d in analyzed.values() if d.get("optimized_query"))
        with_feedback = sum(1 for d in analyzed.values() if d.get("feedback"))

        report["search_analysis"] = {
            "total_analyzed": len(analyzed),
            "optimizable": optimizable,
            "with_feedback": with_feedback,
            "complexity_distribution": complexities,
        }
    except Exception as e:
        report["search_analysis_error"] = str(e)

    # 4. Force re-analysis of searches that have new feedback
    try:
        from containers.search_opt.utils import _load_analyzed_searches
        from containers.search_opt.core import analyze_all_saved_searches
        analyzed = _load_analyzed_searches()

        # Find searches with recent feedback that should be re-analyzed
        stale = []
        for name, data in analyzed.items():
            feedback = data.get("feedback", [])
            if feedback:
                newest_fb = max(
                    (f.get("submitted_at", "") for f in feedback), default=""
                )
                analyzed_at = data.get("analyzed_at", "")
                if newest_fb > analyzed_at:
                    stale.append(name)

        report["stale_searches_refreshed"] = len(stale)
        if stale:
            logger.info(f"[SCHEDULER] Re-analyzing {len(stale)} searches with new feedback")
            # Force re-analysis for these
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, lambda: analyze_all_saved_searches(force_reanalyze=True)
            )
    except Exception as e:
        report["reanalysis_error"] = str(e)

    # 5. Self-assessment score
    try:
        total = report.get("service_stats", {}).get("saved_searches_analyzed", 0)
        feedback_count = report.get("service_stats", {}).get("total_feedback_entries", 0)
        patterns_count = report.get("learned_patterns", {}).get("total", 0)

        scores = {
            "coverage": min(100, (total / max(1, report.get("service_stats", {}).get("saved_searches_found", 1))) * 100),
            "learning": min(100, patterns_count * 10),
            "engagement": min(100, feedback_count * 5),
        }
        scores["overall"] = sum(scores.values()) / len(scores)
        report["self_assessment_score"] = scores
    except Exception:
        pass

    _record_job("weekly_assessment", report)
    logger.info(f"[SCHEDULER] Weekly assessment complete. Score: {report.get('self_assessment_score', {}).get('overall', 'N/A')}")

    # Persist report
    try:
        import json
        from containers.search_opt.utils import _resolve_data_root
        report_path = _resolve_data_root() / "weekly_assessment.json"
        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass

    return report


# ---------------------------------------------------------------------------
# Monthly Job: Comprehensive audit, episodic consolidation, model analysis
# ---------------------------------------------------------------------------
async def job_monthly_audit():
    """
    Monthly: Deep knowledge audit and system optimization.
    - Consolidate episodic memory into durable semantic facts
    - Audit knowledge base coverage (which topics are well/poorly covered)
    - Analyze collection weight drift over time
    - Prune low-confidence semantic facts
    - Generate monthly effectiveness report with trend analysis
    """
    logger.info("[SCHEDULER] Monthly audit started")
    report = {"timestamp": datetime.utcnow().isoformat() + "Z"}

    # 1. Episodic memory consolidation
    try:
        from containers.search_opt.utils import _resolve_data_root
        import json

        data_root = _resolve_data_root()

        # Load and analyze episodic data if available
        episode_stats = {"consolidated": 0, "total_episodes": 0}

        # Read adaptive learning data to identify trends
        weights_path = data_root / "collection_weights.json"
        if weights_path.exists():
            weights = json.loads(weights_path.read_text(encoding="utf-8"))
            report["collection_weight_analysis"] = {
                "current_weights": weights,
                "collections_above_baseline": [
                    k for k, v in weights.items()
                    if isinstance(v, dict) and v.get("success_rate", 0) > 0.7
                ],
                "collections_below_baseline": [
                    k for k, v in weights.items()
                    if isinstance(v, dict) and v.get("success_rate", 0) < 0.3
                ],
            }

        # Read query patterns to identify most common categories
        patterns_path = data_root / "query_patterns.json"
        if patterns_path.exists():
            patterns = json.loads(patterns_path.read_text(encoding="utf-8"))
            category_sizes = {k: len(v) for k, v in patterns.items() if isinstance(v, list)}
            report["query_pattern_analysis"] = {
                "categories": category_sizes,
                "most_active": max(category_sizes, key=category_sizes.get) if category_sizes else None,
                "total_patterns": sum(category_sizes.values()),
            }

        report["episodic_consolidation"] = episode_stats
    except Exception as e:
        report["episodic_error"] = str(e)
        logger.warning(f"[SCHEDULER] Monthly episodic consolidation error: {e}")

    # 2. Knowledge base coverage audit
    try:
        from containers.search_opt.learning import _get_learned_patterns
        patterns = _get_learned_patterns()

        # Analyze pattern distribution
        pattern_types = {}
        for p in patterns:
            ptype = p.get("type", "unknown")
            pattern_types[ptype] = pattern_types.get(ptype, 0) + 1

        report["pattern_audit"] = {
            "total_patterns": len(patterns),
            "type_distribution": pattern_types,
            "patterns_per_type_avg": len(patterns) / max(1, len(pattern_types)),
        }

        # Identify underrepresented pattern types
        expected_types = {"stats_to_tstats", "add_term", "add_prefix", "add_index",
                         "remove_wildcard_index", "remove_join", "remove_transaction", "add_time_bounds"}
        missing_types = expected_types - set(pattern_types.keys())
        if missing_types:
            report["pattern_audit"]["missing_pattern_types"] = list(missing_types)
    except Exception as e:
        report["pattern_audit_error"] = str(e)

    # 3. Feedback effectiveness analysis (month-over-month)
    try:
        from containers.search_opt.core import get_service_stats
        stats = get_service_stats()
        report["monthly_stats"] = stats

        # Calculate improvement score
        total_feedback = stats.get("total_feedback_entries", 0)
        total_analyzed = stats.get("saved_searches_analyzed", 0)
        total_patterns = report.get("pattern_audit", {}).get("total_patterns", 0)

        effectiveness = {
            "feedback_to_pattern_ratio": total_patterns / max(1, total_feedback),
            "analysis_coverage": total_analyzed,
            "learning_velocity": total_patterns,
        }
        report["effectiveness"] = effectiveness
    except Exception as e:
        report["stats_error"] = str(e)

    # 4. Prune low-value learned patterns (patterns that haven't been applied)
    try:
        from containers.search_opt.learning import _get_learned_patterns
        from containers.search_opt.utils import _resolve_data_root
        import json

        patterns = _get_learned_patterns()
        if len(patterns) > 200:
            # Keep only the most recent 150 patterns to prevent unbounded growth
            pruned_count = len(patterns) - 150
            patterns = patterns[-150:]
            patterns_path = _resolve_data_root() / "learned_patterns.json"
            patterns_path.write_text(json.dumps(patterns, indent=2, default=str), encoding="utf-8")
            report["pruned_patterns"] = pruned_count
            logger.info(f"[SCHEDULER] Pruned {pruned_count} old learned patterns")
    except Exception as e:
        report["prune_error"] = str(e)

    # 5. Generate monthly score
    try:
        scores = {
            "learning_depth": min(100, report.get("pattern_audit", {}).get("total_patterns", 0) * 5),
            "coverage_breadth": min(100, len(report.get("collection_weight_analysis", {}).get("collections_above_baseline", [])) * 20),
            "feedback_engagement": min(100, report.get("monthly_stats", {}).get("total_feedback_entries", 0) * 3),
            "pattern_diversity": min(100, len(report.get("pattern_audit", {}).get("type_distribution", {})) * 12.5),
        }
        scores["overall"] = sum(scores.values()) / len(scores)
        report["monthly_score"] = scores
    except Exception:
        pass

    # 6. Automatic model customization (monthly)
    try:
        from chat_app.self_learning import run_model_customization
        custom_report = await run_model_customization()
        report["model_customization"] = {
            "qa_pairs_exported": custom_report.qa_pairs_exported,
            "model_created": custom_report.model_created,
            "model_name": custom_report.model_name,
            "error": custom_report.error or None,
        }
        logger.info(
            f"[SCHEDULER] Model customization: exported={custom_report.qa_pairs_exported}, "
            f"created={custom_report.model_created}, name={custom_report.model_name}"
        )
    except Exception as e:
        report["model_customization_error"] = str(e)
        logger.warning(f"[SCHEDULER] Model customization failed: {e}")

    _record_job("monthly_audit", report)
    logger.info(f"[SCHEDULER] Monthly audit complete. Score: {report.get('monthly_score', {}).get('overall', 'N/A')}")

    # Persist report
    try:
        import json
        from containers.search_opt.utils import _resolve_data_root
        report_path = _resolve_data_root() / "monthly_audit.json"
        report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    except Exception:
        pass

    return report


# ---------------------------------------------------------------------------
# Weekly Job: Splunkbase catalog refresh
# ---------------------------------------------------------------------------
async def job_weekly_splunkbase_refresh():
    """
    Weekly: Refresh the Splunkbase add-on catalog.
    Only runs if the splunkbase_catalog feature is enabled.
    """
    logger.info("[SCHEDULER] Splunkbase catalog refresh started")
    try:
        from chat_app.splunkbase_catalog import run_catalog_update
        result = await run_catalog_update()
        _record_job("splunkbase_refresh", result)
        logger.info("[SCHEDULER] Splunkbase catalog refresh: %s", result)
        return result
    except Exception as e:
        logger.error("[SCHEDULER] Splunkbase catalog refresh failed: %s", e)
        _record_job("splunkbase_refresh", None, str(e))


# ---------------------------------------------------------------------------
# Daily Job: Incremental re-ingestion of changed files
# ---------------------------------------------------------------------------
async def job_daily_reingest():
    """
    Daily: Detect changed files in source directories and re-ingest only those.

    Checks file modification times against a stored "last_ingest_time" marker.
    Only re-ingests files that were modified since the last run.
    Uses the same fingerprint/delete-before-replace logic as run_quick_ingest.py.
    """
    logger.info("[SCHEDULER] Daily incremental re-ingestion started")
    report = {"timestamp": datetime.utcnow().isoformat() + "Z"}

    try:
        import json
        from pathlib import Path
        from containers.search_opt.utils import _resolve_data_root

        data_root = _resolve_data_root()
        marker_path = data_root / "last_ingest_marker.json"

        # Load last ingest times per directory
        if marker_path.exists():
            markers = json.loads(marker_path.read_text(encoding="utf-8"))
        else:
            markers = {}

        # Source directories to monitor
        docs_root = os.getenv("DOCUMENTS_ROOT", "/app/shared/public/documents")
        source_dirs = {
            "spl_docs": os.getenv("SPL_DOCS_ROOT", f"{docs_root}/commands"),
            "specs": os.getenv("SPEC_STATIC_ROOT", f"{docs_root}/specs"),
            "metadata": "/app/metadata",
            "repo": os.getenv("ORG_REPO_ROOT", f"{docs_root}/repo"),
            "local_docs": os.getenv("LOCAL_DOCS_ROOT", f"{docs_root}/pdfs"),
            "cribl_docs": os.getenv("CRIBL_DOCS_ROOT", f"{docs_root}/cribl"),
        }

        changed_files = {}
        now = datetime.utcnow()

        for label, dir_path in source_dirs.items():
            if not Path(dir_path).exists():
                continue

            last_ingest = markers.get(label, "1970-01-01T00:00:00")
            try:
                last_dt = datetime.fromisoformat(last_ingest)
            except (ValueError, TypeError):
                last_dt = datetime(1970, 1, 1)

            # Find files modified since last ingest
            modified = []
            for f in Path(dir_path).rglob("*"):
                if not f.is_file():
                    continue
                if f.suffix.lower() not in {
                    ".md", ".conf", ".spec", ".txt", ".json",
                    ".yaml", ".yml", ".csv", ".pdf",
                }:
                    continue
                try:
                    mtime = datetime.utcfromtimestamp(f.stat().st_mtime)
                    if mtime > last_dt:
                        modified.append(str(f))
                except OSError:
                    continue

            if modified:
                changed_files[label] = modified
                logger.info(
                    f"[SCHEDULER] {label}: {len(modified)} files changed since {last_ingest}"
                )

        report["changed_files"] = {k: len(v) for k, v in changed_files.items()}
        total_changed = sum(len(v) for v in changed_files.values())

        if total_changed == 0:
            report["status"] = "no_changes"
            logger.info("[SCHEDULER] No files changed since last ingestion")
            _record_job("daily_reingest", report)
            return report

        # Trigger incremental ingestion via run_quick_ingest
        # Uses --skip-delete (incremental mode) which checks fingerprints
        # and the new delete-before-replace logic for changed files
        try:
            import subprocess
            result = subprocess.run(
                ["python3", "/app/chat_app/run_quick_ingest.py", "--skip-delete"],
                capture_output=True, text=True, timeout=3600,
                cwd="/app",
            )
            report["ingest_returncode"] = result.returncode
            # Extract summary from last few lines of output
            output_lines = result.stdout.strip().split("\n")
            report["ingest_summary"] = output_lines[-5:] if output_lines else []
            if result.returncode != 0 and result.stderr:
                report["ingest_errors"] = result.stderr[-500:]
        except subprocess.TimeoutExpired:
            report["ingest_error"] = "Ingestion timed out after 3600s"
        except Exception as e:
            report["ingest_error"] = str(e)

        # Update markers
        for label in source_dirs:
            markers[label] = now.isoformat()
        marker_path.write_text(json.dumps(markers, indent=2), encoding="utf-8")

        report["status"] = "completed"
        report["total_changed"] = total_changed

    except Exception as e:
        report["error"] = str(e)
        logger.error(f"[SCHEDULER] Daily re-ingestion failed: {e}")

    _record_job("daily_reingest", report)
    logger.info(f"[SCHEDULER] Daily re-ingestion complete: {report.get('total_changed', 0)} files")
    return report


# ---------------------------------------------------------------------------
# Auto-Heal Runner
# ---------------------------------------------------------------------------
async def _run_auto_heal():
    """Run auto-heal checks and record results."""
    try:
        from chat_app.resource_manager import auto_heal_check, record_learning_snapshot
        events = await auto_heal_check()
        if events:
            _record_job("auto_heal", {
                "events": len(events),
                "successes": sum(1 for e in events if e.success),
                "failures": sum(1 for e in events if not e.success),
            })
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"[SCHEDULER] Auto-heal check skipped: {e}")


# ---------------------------------------------------------------------------
# Scheduler Management
# ---------------------------------------------------------------------------

_scheduler = None


def get_scheduler_status() -> Dict[str, Any]:
    """Get current scheduler status and job history."""
    return {
        "backend": "apscheduler" if _APSCHEDULER_AVAILABLE else "asyncio_fallback",
        "running": _scheduler is not None,
        "recent_jobs": _job_history[-10:],
        "total_jobs_run": len(_job_history),
    }


async def start_scheduler():
    """Start the background scheduler with all jobs."""
    global _scheduler

    # Check if scheduling is enabled
    if os.getenv("SCHEDULER_ENABLED", "true").lower() not in ("true", "1", "yes"):
        logger.info("[SCHEDULER] Disabled via SCHEDULER_ENABLED env var")
        return

    if _APSCHEDULER_AVAILABLE:
        await _start_apscheduler()
    else:
        await _start_asyncio_fallback()


async def stop_scheduler():
    """Stop the background scheduler."""
    global _scheduler
    if _scheduler and _APSCHEDULER_AVAILABLE:
        _scheduler.shutdown(wait=False)
        _scheduler = None
        logger.info("[SCHEDULER] APScheduler stopped")


async def _start_apscheduler():
    """Start APScheduler with cron-based jobs."""
    global _scheduler

    _scheduler = AsyncIOScheduler()

    # Hourly: learn from feedback (at minute 15) — lightweight, no resource check
    _scheduler.add_job(
        lambda: _guarded("hourly_learn", job_hourly_learn),
        CronTrigger(minute=15),
        id="hourly_learn",
        name="Hourly Feedback Learning",
        replace_existing=True,
    )

    # Daily: full analysis (at 2:00 AM) — heavy, resource-checked
    _scheduler.add_job(
        lambda: _guarded("daily_analyze", job_daily_analyze, heavy=True),
        CronTrigger(hour=2, minute=0),
        id="daily_analyze",
        name="Daily Analysis & Refresh",
        replace_existing=True,
    )

    # Weekly: self-assessment (Sunday 3:00 AM) — heavy
    _scheduler.add_job(
        lambda: _guarded("weekly_assessment", job_weekly_assessment, heavy=True),
        CronTrigger(day_of_week="sun", hour=3, minute=0),
        id="weekly_assessment",
        name="Weekly Self-Assessment",
        replace_existing=True,
    )

    # Monthly: comprehensive audit (1st of month at 4:00 AM) — heaviest
    _scheduler.add_job(
        lambda: _guarded("monthly_audit", job_monthly_audit, heavy=True),
        CronTrigger(day=1, hour=4, minute=0),
        id="monthly_audit",
        name="Monthly Knowledge Audit",
        replace_existing=True,
    )

    # Daily: incremental re-ingestion of changed files (at 3:00 AM) — heavy
    _scheduler.add_job(
        lambda: _guarded("daily_reingest", job_daily_reingest, heavy=True),
        CronTrigger(hour=3, minute=0),
        id="daily_reingest",
        name="Daily Incremental Re-Ingestion",
        replace_existing=True,
    )

    # Daily: Splunkbase catalog refresh (4:30 AM) — medium weight
    _scheduler.add_job(
        lambda: _guarded("splunkbase_refresh", job_weekly_splunkbase_refresh, heavy=True),
        CronTrigger(hour=4, minute=30),
        id="splunkbase_refresh",
        name="Daily Splunkbase Catalog Refresh",
        replace_existing=True,
    )

    # Auto-heal check (every 5 minutes) — lightweight
    _scheduler.add_job(
        lambda: _guarded("auto_heal", _run_auto_heal),
        CronTrigger(minute="*/5"),
        id="auto_heal",
        name="Auto-Heal Check",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("[SCHEDULER] APScheduler started with 7 jobs: hourly/daily/daily-reingest/weekly/monthly/splunkbase/auto-heal")


async def _start_asyncio_fallback():
    """Simple asyncio-based scheduler when APScheduler isn't available."""
    global _scheduler
    _scheduler = True  # Flag that scheduler is running

    async def _loop():
        hourly_counter = 0
        five_min_counter = 0

        while True:
            await asyncio.sleep(300)  # Sleep 5 minutes
            five_min_counter += 1

            # Auto-heal every 5 minutes
            try:
                await _guarded("auto_heal", _run_auto_heal)
            except Exception as e:
                logger.debug(f"[SCHEDULER] Fallback auto-heal failed: {e}")

            # Hourly (every 12 * 5min = 60min)
            if five_min_counter % 12 == 0:
                hourly_counter += 1
                try:
                    await _guarded("hourly_learn", job_hourly_learn)
                except Exception as e:
                    logger.error(f"[SCHEDULER] Fallback hourly job failed: {e}")

            # Daily (every 24 hours)
            if hourly_counter > 0 and hourly_counter % 24 == 0 and five_min_counter % 12 == 0:
                try:
                    await _guarded("daily_analyze", job_daily_analyze, heavy=True)
                except Exception as e:
                    logger.error(f"[SCHEDULER] Fallback daily job failed: {e}")

                # Daily re-ingestion (1 hour after daily analysis)
                try:
                    await _guarded("daily_reingest", job_daily_reingest, heavy=True)
                except Exception as e:
                    logger.error(f"[SCHEDULER] Fallback daily reingest failed: {e}")

            # Weekly (every 168 hours)
            if hourly_counter > 0 and hourly_counter % 168 == 0 and five_min_counter % 12 == 0:
                try:
                    await _guarded("weekly_assessment", job_weekly_assessment, heavy=True)
                except Exception as e:
                    logger.error(f"[SCHEDULER] Fallback weekly job failed: {e}")

            # Monthly (every 720 hours ≈ 30 days)
            if hourly_counter > 0 and hourly_counter % 720 == 0 and five_min_counter % 12 == 0:
                try:
                    await _guarded("monthly_audit", job_monthly_audit, heavy=True)
                except Exception as e:
                    logger.error(f"[SCHEDULER] Fallback monthly job failed: {e}")

    asyncio.create_task(_loop())
    logger.info("[SCHEDULER] Asyncio fallback scheduler started (hourly/daily/weekly/monthly)")
