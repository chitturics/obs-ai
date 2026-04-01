"""Background job method implementations for IdleWorker.

Provides IdleWorkerJobsMixin — all 12 async job methods.
IdleWorker (in idle_worker.py) inherits from this mixin.

Kept separate to stay under 600 lines per file.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class IdleWorkerJobsMixin:
    """Mixin providing all background job method implementations for IdleWorker."""

    async def _review_feedback(self) -> int:
        """Review recent feedback to identify patterns and improvement areas."""
        try:
            from chat_app.human_loop import get_human_loop_manager
            hlm = get_human_loop_manager()
            feedback = hlm.get_recent_feedback(limit=50)

            if not feedback:
                return 0

            low_rated = [f for f in feedback if f.get("rating", 5) <= 2]
            high_rated = [f for f in feedback if f.get("rating", 5) >= 4]
            findings = len(low_rated)

            if low_rated:
                hlm.add_insight(
                    insight_type="improvement",
                    message=f"Found {len(low_rated)} low-rated interactions in recent feedback. "
                            f"Common queries: {', '.join(f.get('query', '')[:50] for f in low_rated[:3])}",
                    data={"low_rated_count": len(low_rated), "high_rated_count": len(high_rated)},
                )
                self._improvements_made.append({
                    "type": "feedback_review",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "details": f"Identified {len(low_rated)} low-rated interactions",
                })

            if len(feedback) >= 10:
                recent_avg = sum(f.get("rating", 3) for f in feedback[:10]) / 10
                older_avg = sum(f.get("rating", 3) for f in feedback[-10:]) / 10
                if recent_avg < older_avg - 0.5:
                    hlm.add_insight(
                        insight_type="drift",
                        message=f"Satisfaction declining: recent avg {recent_avg:.1f} vs older avg {older_avg:.1f}",
                        severity_str="medium" if recent_avg < 3 else "low",
                        data={"recent_avg": recent_avg, "older_avg": older_avg},
                    )
                    findings += 1

            return findings
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[IDLE-WORKER] Feedback review failed: %s", exc)
            return 0

    async def _update_tool_rankings(self) -> int:
        """Update tool effectiveness rankings based on recent executions."""
        try:
            from chat_app.tool_effectiveness import get_effectiveness_tracker
            tracker = get_effectiveness_tracker()
            matrix = tracker.get_intent_tool_matrix()

            if not matrix:
                return 0

            findings = 0
            for intent, tools in matrix.items():
                for tool_info in tools:
                    if tool_info["executions"] >= 5 and tool_info["success_rate"] < 0.5:
                        from chat_app.human_loop import get_human_loop_manager
                        hlm = get_human_loop_manager()
                        hlm.add_insight(
                            insight_type="anomaly",
                            message=f"Tool '{tool_info['tool']}' has low success rate "
                                    f"({tool_info['success_rate']:.0%}) for intent '{intent}'",
                            data=tool_info,
                        )
                        findings += 1

            self._improvements_made.append({
                "type": "tool_ranking_update",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "details": f"Analyzed {len(matrix)} intent-tool mappings",
            })
            return findings
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[IDLE-WORKER] Tool ranking update failed: %s", exc)
            return 0

    async def _detect_knowledge_gaps(self) -> int:
        """Detect knowledge gaps from recent queries with low confidence."""
        try:
            from chat_app.human_loop import get_human_loop_manager
            from chat_app.knowledge_gap_detector import detect_knowledge_gaps

            hlm = get_human_loop_manager()
            feedback = hlm.get_recent_feedback(limit=20)
            findings = 0

            for fb in feedback:
                if fb.get("rating", 5) <= 2 and fb.get("has_correction"):
                    gaps = detect_knowledge_gaps(
                        user_query=fb.get("query", ""),
                        retrieved_chunks=[],
                        chunk_threshold=2,
                    )
                    if gaps:
                        hlm.add_insight(
                            insight_type="gap",
                            message=f"Knowledge gap detected for query: '{fb.get('query', '')[:80]}'. "
                                    f"Gaps: {', '.join(g.get('topic', '') for g in gaps[:3])}",
                            data={"query": fb.get("query", ""), "gaps": gaps[:5]},
                        )
                        findings += 1

            return findings
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[IDLE-WORKER] Knowledge gap detection failed: %s", exc)
            return 0

    async def _improve_followups(self) -> int:
        """Generate better follow-up questions from past interactions."""
        try:
            from chat_app.episodic_memory import get_recent_episodes

            if not self._engine:
                return 0

            episodes = await get_recent_episodes(self._engine, limit=20)
            if not episodes:
                return 0

            followup_patterns = []
            for i, ep in enumerate(episodes[:-1]):
                next_ep = episodes[i + 1]
                if hasattr(ep, "query") and hasattr(next_ep, "query"):
                    followup_patterns.append({
                        "original": ep.query[:100],
                        "followup": next_ep.query[:100],
                    })

            if followup_patterns:
                self._improvements_made.append({
                    "type": "followup_analysis",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "details": f"Analyzed {len(followup_patterns)} follow-up patterns",
                    "patterns": followup_patterns[:5],
                })

            return len(followup_patterns)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[IDLE-WORKER] Follow-up improvement failed: %s", exc)
            return 0

    async def _quality_check_recent(self) -> int:
        """Run quality checks on recent responses."""
        try:
            from chat_app.human_loop import get_human_loop_manager

            hlm = get_human_loop_manager()
            feedback = hlm.get_recent_feedback(limit=10)

            quality_issues = 0
            for fb in feedback:
                if fb.get("rating", 5) <= 3:
                    quality_issues += 1

            if quality_issues > len(feedback) * 0.3 and len(feedback) >= 5:
                hlm.add_insight(
                    insight_type="warning",
                    message=f"Quality alert: {quality_issues}/{len(feedback)} recent interactions "
                            f"rated 3 or below. Consider reviewing prompt templates and context.",
                    data={"quality_issues": quality_issues, "total_reviewed": len(feedback)},
                )

            return quality_issues
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[IDLE-WORKER] Quality check failed: %s", exc)
            return 0

    async def _run_evolution_assessment(self) -> int:
        """Run the evolution engine's continuous assessment cycle."""
        try:
            from chat_app.evolution_engine import get_evolution_engine
            engine = get_evolution_engine()
            result = await engine.run_assessment()

            gaps = result.get("gaps_count", 0)
            stale = result.get("staleness", {}).get("stale_or_critical", 0)
            cycle = result.get("cycle_number", 0)

            if gaps > 0 or stale > 0:
                self._improvements_made.append({
                    "type": "evolution_assessment",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "details": f"Cycle #{cycle}: {gaps} gaps, {stale} stale components",
                    "diagnosis": result.get("diagnosis", {}).get("primary_cause", "unknown"),
                })

            return gaps + stale
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[IDLE-WORKER] Evolution assessment failed: %s", exc)
            return 0

    async def _execute_evolution_improvement(self) -> int:
        """Execute the next improvement action from the evolution engine queue."""
        try:
            from chat_app.evolution_engine import get_evolution_engine
            engine = get_evolution_engine()
            result = await engine.execute_next_improvement()

            if result:
                self._improvements_made.append({
                    "type": "evolution_action",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "details": f"{result['action']}: {result['status']}",
                })
                return 1
            return 0
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[IDLE-WORKER] Evolution improvement execution failed: %s", exc)
            return 0

    async def _evaluate_observability(self) -> int:
        """Evaluate SLOs and alert rules proactively during idle time."""
        try:
            from chat_app.observability import get_observability_manager
            obs = get_observability_manager()

            fired_alerts = obs.evaluate_alerts()
            slo_statuses = obs.get_slo_status()
            breached = [s for s in slo_statuses if not s.is_met and s.sample_count > 0]

            if breached or fired_alerts:
                from chat_app.human_loop import get_human_loop_manager
                hlm = get_human_loop_manager()

                for slo in breached:
                    hlm.add_insight(
                        insight_type="warning",
                        message=f"SLO '{slo.definition.name}' breached: "
                                f"current={slo.current_value:.2%}, target={slo.definition.target:.2%}",
                        data={
                            "slo_name": slo.definition.name,
                            "current": slo.current_value,
                            "target": slo.definition.target,
                            "budget_remaining": slo.error_budget_remaining,
                        },
                    )

                for alert in fired_alerts:
                    hlm.add_insight(
                        insight_type="anomaly",
                        message=f"Alert fired: {alert.message}",
                        data={
                            "alert_name": alert.alert_name,
                            "severity": alert.severity.value,
                            "value": alert.value,
                        },
                    )

                self._improvements_made.append({
                    "type": "observability_evaluation",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "details": f"Evaluated {len(slo_statuses)} SLOs, {len(breached)} breached, "
                               f"{len(fired_alerts)} alerts fired",
                })

            return len(breached) + len(fired_alerts)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[IDLE-WORKER] Observability evaluation failed: %s", exc)
            return 0

    async def _check_config_drift(self) -> int:
        """Compare in-memory settings with config.yaml on disk."""
        # Access _job_results from the module-level dict in idle_worker.py
        from chat_app.idle_worker import _job_results
        try:
            from chat_app.settings import get_settings, _load_yaml_config

            current = get_settings()
            on_disk = _load_yaml_config()
            drifts: List[Dict[str, Any]] = []

            active = current.app.active_profile
            disk_profile = on_disk.get("profiles", {}).get(active, {}).get("llm", {})
            disk_model = disk_profile.get("model", "")
            if disk_model and current.ollama.model != disk_model:
                drifts.append({"setting": "ollama.model", "memory": current.ollama.model, "disk": disk_model})

            disk_embed = disk_profile.get("embed_model", "")
            if disk_embed and current.ollama.embed_model != disk_embed:
                drifts.append({"setting": "ollama.embed_model", "memory": current.ollama.embed_model, "disk": disk_embed})

            disk_orch = on_disk.get("orchestration", {})
            disk_strategy = disk_orch.get("default_strategy", "")
            if disk_strategy and current.orchestration.default_strategy != disk_strategy:
                drifts.append({"setting": "orchestration.default_strategy",
                               "memory": current.orchestration.default_strategy, "disk": disk_strategy})

            disk_retrieval = on_disk.get("retrieval", {})
            disk_top_k = disk_retrieval.get("top_k", {})
            if disk_top_k and current.retrieval.top_k != disk_top_k:
                drifts.append({"setting": "retrieval.top_k",
                               "memory": str(current.retrieval.top_k), "disk": str(disk_top_k)})

            disk_sec = on_disk.get("security", {}).get("rate_limiting", {})
            disk_max_qpm = disk_sec.get("max_queries_per_minute")
            if disk_max_qpm is not None and current.security.max_queries_per_minute != int(disk_max_qpm):
                drifts.append({"setting": "security.max_queries_per_minute",
                               "memory": current.security.max_queries_per_minute, "disk": int(disk_max_qpm)})

            disk_iw = on_disk.get("idle_worker", {})
            disk_iw_enabled = disk_iw.get("enabled")
            if disk_iw_enabled is not None and current.idle_worker.enabled != disk_iw_enabled:
                drifts.append({"setting": "idle_worker.enabled",
                               "memory": current.idle_worker.enabled, "disk": disk_iw_enabled})

            if drifts:
                logger.info("[IDLE-WORKER] Config drift detected: %d setting(s) differ", len(drifts))
                self._improvements_made.append({
                    "type": "config_drift",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "details": f"{len(drifts)} config drift(s) detected",
                    "drifts": drifts,
                })
                _job_results["config_drift"] = {**_job_results.get("config_drift", {}), "drifts": drifts}

            return len(drifts)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[IDLE-WORKER] Config drift check failed: %s", exc)
            return 0

    async def _check_collection_freshness(self) -> int:
        """Check collection document counts and staleness."""
        from chat_app.idle_worker import _job_results
        try:
            from chat_app.vectorstore import get_vectorstore

            vs = get_vectorstore()
            if vs is None:
                return 0

            client = getattr(vs, "_client", None) or getattr(vs, "client", None)
            if client is None:
                return 0

            collections_info: List[Dict[str, Any]] = []
            findings = 0

            try:
                collections = client.list_collections()
            except Exception:  # broad catch — resilience at boundary
                return 0

            for col in collections:
                try:
                    name = col.name if hasattr(col, "name") else str(col)
                    col_obj = client.get_collection(name)
                    count = col_obj.count()
                    collections_info.append({"name": name, "count": count})

                    if count == 0:
                        findings += 1
                        logger.info("[IDLE-WORKER] Collection '%s' is empty", name)
                    elif count < 5:
                        findings += 1
                        logger.info("[IDLE-WORKER] Collection '%s' has very few documents (%d)", name, count)
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                    logger.debug("[IDLE-WORKER] Could not inspect collection: %s", exc)

            if findings:
                self._improvements_made.append({
                    "type": "collection_freshness",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "details": f"{findings} collection(s) may need attention",
                    "collections": collections_info,
                })

            _job_results["collection_freshness"] = {
                **_job_results.get("collection_freshness", {}),
                "collections": collections_info,
                "total_collections": len(collections_info),
            }
            return findings
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[IDLE-WORKER] Collection freshness check failed: %s", exc)
            return 0

    async def _check_pipeline_quality(self) -> int:
        """Check if average query quality is declining."""
        from chat_app.idle_worker import _job_results
        try:
            from chat_app.observability import get_observability_manager
            obs = get_observability_manager()

            obs.get_metrics_snapshot() if hasattr(obs, "get_metrics_snapshot") else {}
            quality_data: Dict[str, Any] = {}
            findings = 0

            try:
                from chat_app.prometheus_metrics import get_metrics_snapshot
                prom = get_metrics_snapshot()
                quality_data["prometheus"] = {
                    "total_queries": prom.get("total_queries", 0),
                    "avg_latency_ms": prom.get("avg_latency_ms", 0),
                    "error_rate": prom.get("error_rate", 0),
                }
                error_rate = prom.get("error_rate", 0)
                if error_rate > 0.1:
                    findings += 1
                    logger.info("[IDLE-WORKER] High error rate detected: %.1f%%", error_rate * 100)
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                logger.debug("%s", _exc)

            try:
                slo_statuses = obs.get_slo_status()
                breached = [s for s in slo_statuses if not s.is_met and s.sample_count > 0]
                quality_data["slo_breached"] = len(breached)
                quality_data["slo_total"] = len(slo_statuses)
                if breached:
                    findings += len(breached)
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                logger.debug("%s", _exc)

            try:
                from chat_app.human_loop import get_human_loop_manager
                hlm = get_human_loop_manager()
                recent_fb = hlm.get_recent_feedback(limit=20)
                if len(recent_fb) >= 10:
                    ratings = [f.get("rating", 3) for f in recent_fb]
                    avg = sum(ratings) / len(ratings)
                    first_half = sum(ratings[:len(ratings)//2]) / (len(ratings)//2)
                    second_half = sum(ratings[len(ratings)//2:]) / (len(ratings) - len(ratings)//2)
                    quality_data["feedback"] = {
                        "avg_rating": round(avg, 2),
                        "recent_half_avg": round(first_half, 2),
                        "older_half_avg": round(second_half, 2),
                        "trend": "declining" if first_half < second_half - 0.3 else "stable",
                    }
                    if first_half < second_half - 0.3:
                        findings += 1
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                logger.debug("%s", _exc)

            if findings:
                self._improvements_made.append({
                    "type": "pipeline_quality",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "details": f"{findings} quality concern(s) detected",
                    "quality_data": quality_data,
                })

            _job_results["pipeline_quality"] = {
                **_job_results.get("pipeline_quality", {}),
                "quality_data": quality_data,
            }
            return findings
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[IDLE-WORKER] Pipeline quality check failed: %s", exc)
            return 0

    async def _run_daily_evolution(self) -> int:
        """Run the daily self-improvement evolution cycle."""
        from chat_app.idle_worker import _job_results
        try:
            from chat_app.daily_evolution import run_daily_evolution
            result = await run_daily_evolution()
            _job_results["daily_evolution"] = result.to_dict()
            logger.info(
                "[IDLE-WORKER] Daily evolution: %d lessons, %.0f%% quality, %d recs",
                result.lessons_extracted,
                result.knowledge_quality_score * 100,
                len(result.recommendations),
            )
            return result.lessons_extracted + len(result.recommendations)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[IDLE-WORKER] Daily evolution failed: %s", exc)
            return 0

    async def _refresh_security_advisories(self) -> int:
        """
        Refresh Splunk security advisory cache from advisory.splunk.com.

        Runs at most once per day (cache TTL enforced inside the scraper).
        Returns the number of advisories fetched as the finding count so the
        scheduler's episodic prioritisation sees it as productive work.
        """
        from chat_app.idle_worker import _job_results
        try:
            from chat_app.upgrade_readiness.advisory_scraper import get_advisory_scraper
            scraper = get_advisory_scraper()

            # Scraper returns cached list if fresh — no unnecessary HTTP calls
            advisories = await scraper.fetch_advisories(max_pages=5)
            meta = scraper.get_cache_metadata()

            _job_results["refresh_security_advisories"] = {
                "status": "ok",
                "record_count": len(advisories),
                "last_updated": meta.get("last_updated"),
                "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            }
            logger.info(
                "[IDLE-WORKER] Security advisories refreshed: %d advisories cached",
                len(advisories),
            )
            return len(advisories)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[IDLE-WORKER] Security advisory refresh failed: %s", exc)
            _job_results["refresh_security_advisories"] = {
                "status": "error",
                "error": str(exc),
                "timestamp": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            }
            return 0
