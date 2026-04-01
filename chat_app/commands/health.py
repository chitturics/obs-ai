"""
/health command handler — comprehensive health check with learning stats.
"""
import chainlit as cl
import logging

logger = logging.getLogger(__name__)


async def health_command():
    """Run comprehensive health checks and display results."""
    msg = cl.Message(content="Running comprehensive health checks...")
    await msg.send()

    parts = []

    # Try new comprehensive health monitor first
    try:
        from chat_app.health_monitor import get_comprehensive_health
        engine = cl.user_session.get("engine")
        health = await get_comprehensive_health(engine)

        status_icon = {"healthy": "🟢", "degraded": "🟡", "unhealthy": "🔴"}.get(health.overall, "⚪")
        parts.append(f"## System Health: {status_icon} {health.overall.upper()}\n")

        # Service status
        parts.append("### Services")
        for svc in health.services:
            icon = {"healthy": "✅", "degraded": "⚠️", "unhealthy": "❌", "unknown": "❓"}.get(svc.status, "❓")
            line = f"- {icon} **{svc.name}**: {svc.status} ({svc.latency_ms:.0f}ms)"
            if svc.error:
                line += f" — {svc.error}"
            parts.append(line)

            # Show details for important services
            if svc.details:
                for k, v in svc.details.items():
                    if k not in ("enabled",):
                        parts.append(f"  - {k}: {v}")

        # Internal metrics
        metrics = health.metrics
        if metrics:
            counters = metrics.get("counters", {})
            parts.append("\n### Performance Metrics")
            parts.append(f"- Queries: {counters.get('queries_total', 0)} total")
            parts.append(f"- Cache: {counters.get('cache_hits', 0)} hits / {counters.get('cache_misses', 0)} misses")
            parts.append(f"- Latency p50: {metrics.get('latency_p50', 0):.0f}ms")
            parts.append(f"- Latency p95: {metrics.get('latency_p95', 0):.0f}ms")
            parts.append(f"- Avg quality: {metrics.get('quality_p50', 0):.2f}")

        # Learning stats
        learning = health.learning
        if learning:
            parts.append("\n### Learning System")
            parts.append(f"- Episodes: {learning.get('episodes_total', 0)} (30d)")
            parts.append(f"- Success rate: {learning.get('success_rate', 0):.0%}")
            parts.append(f"- Avg confidence: {learning.get('avg_confidence', 0):.2f}")
            parts.append(f"- Semantic facts: {learning.get('semantic_facts', 0)}")
            trend = learning.get("improvement_trend", "unknown")
            trend_icon = {"improving": "📈", "stable": "➡️", "declining": "📉"}.get(trend, "❓")
            parts.append(f"- Trend: {trend_icon} {trend}")

    except Exception as exc:
        logger.warning(f"[HEALTH] Comprehensive check failed, falling back: {exc}")
        # Fall back to legacy health check
        try:
            from chat_app.proactive_monitor import run_health_check_now
            result = await run_health_check_now()
            parts.append(result)
        except Exception as exc2:
            parts.append(f"Health check failed: {exc2}")

    # Skill execution metrics
    try:
        from chat_app.skill_executor import get_skill_executor
        executor = get_skill_executor()
        metrics = executor.get_metrics()
        parts.append("\n### Skill Execution")
        parts.append(f"- Executions: {metrics['total_executions']}")
        parts.append(f"- Errors: {metrics['total_errors']} ({metrics['error_rate']:.1%})")
        parts.append(f"- Avg latency: {metrics['avg_latency_ms']:.0f}ms")
        parts.append(f"- Available skills: {metrics['available_skills']}/{metrics['total_catalog_skills']}")
    except Exception:
        pass

    # Orchestration stats
    try:
        from chat_app.orchestration_strategies import get_orchestration_summary
        orch = get_orchestration_summary()
        if orch.get("total", 0) > 0:
            parts.append("\n### Orchestration")
            parts.append(f"- Executions: {orch['total']}")
            parts.append(f"- Success rate: {orch['success_rate']:.1%}")
            parts.append(f"- Fallback rate: {orch['fallback_rate']:.1%}")
            parts.append(f"- Avg quality: {orch['avg_quality']:.2f}")
            parts.append(f"- Avg duration: {orch['avg_duration_ms']:.0f}ms")
            if orch.get("by_strategy"):
                top = sorted(orch["by_strategy"].items(), key=lambda x: -x[1])[:3]
                parts.append(f"- Top strategies: {', '.join(f'{s} ({c})' for s, c in top)}")
    except Exception:
        pass

    # Knowledge graph stats
    try:
        from chat_app.knowledge_graph import get_knowledge_graph
        kg = get_knowledge_graph()
        if kg:
            kg_stats = kg.get_stats()
            parts.append("\n### Knowledge Graph")
            parts.append(f"- Entities: {kg_stats['total_entities']}")
            parts.append(f"- Relationships: {kg_stats['total_relationships']}")
            parts.append(f"- Build time: {kg_stats.get('build_time_ms', 0):.0f}ms")
    except Exception:
        pass

    msg.content = "\n".join(parts)
    await msg.update()
