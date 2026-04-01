"""
/learn command — Trigger a self-learning cycle or check learning status.

Usage:
  /learn          — Show learning status and stats
  /learn run      — Trigger a manual learning cycle
  /learn facts    — Show learned semantic facts
  /learn insights — Show proactive insights
"""
import logging
import chainlit as cl

logger = logging.getLogger(__name__)


async def learn_command(args: str):
    """Self-learning system management."""
    subcommand = args.strip().lower() if args else ""

    if subcommand == "run":
        await _run_learning_cycle()
    elif subcommand == "facts":
        await _show_facts()
    elif subcommand == "insights":
        await _show_insights()
    else:
        await _show_status()


async def _show_status():
    """Show learning system status."""
    try:
        engine = cl.user_session.get("engine")
        if not engine:
            await cl.Message(content="Database not available. Learning stats require a database connection.").send()
            return

        from chat_app.health_monitor import get_learning_stats
        stats = await get_learning_stats(engine)

        parts = ["**Self-Learning System Status**\n"]
        parts.append(f"- **Episodes tracked (30d):** {stats.get('episodes_total', 0)}")
        parts.append(f"- **Successful:** {stats.get('episodes_successful', 0)}")
        parts.append(f"- **Failed:** {stats.get('episodes_failed', 0)}")
        parts.append(f"- **Success rate:** {stats.get('success_rate', 0):.0%}")
        parts.append(f"- **Avg confidence:** {stats.get('avg_confidence', 0):.2f}")
        parts.append(f"- **Semantic facts:** {stats.get('semantic_facts', 0)}")
        parts.append(f"- **Trend:** {stats.get('improvement_trend', 'unknown')}")

        top_intents = stats.get("top_intents", [])
        if top_intents:
            parts.append("\n**Top query intents:**")
            for ti in top_intents[:5]:
                parts.append(f"- {ti['intent']}: {ti['count']} queries")

        failures = stats.get("top_failure_reasons", [])
        if failures:
            parts.append("\n**Common failure reasons:**")
            for f in failures[:3]:
                parts.append(f"- {f['reason']}: {f['count']} times")

        parts.append("\n*Use `/learn run` to trigger a manual learning cycle*")
        parts.append("*Use `/learn facts` to see learned semantic facts*")
        parts.append("*Use `/learn insights` to see proactive insights*")

        await cl.Message(content="\n".join(parts)).send()

    except Exception as exc:
        logger.error(f"[LEARN] Status failed: {exc}")
        await cl.Message(content=f"Error getting learning status: {exc}").send()


async def _run_learning_cycle():
    """Trigger a manual learning cycle."""
    msg = await cl.Message(content="Starting self-learning cycle...").send()
    try:
        engine = cl.user_session.get("engine")
        vector_store = cl.user_session.get("vector_store")

        from chat_app.self_learning import run_learning_cycle
        report = await run_learning_cycle(
            engine=engine,
            vector_store=vector_store,
        )

        parts = ["**Learning Cycle Complete**\n"]
        parts.append(f"- Q&A pairs generated: {report.qa_pairs_generated}")
        parts.append(f"- Answers reassessed: {report.answers_reassessed}")
        parts.append(f"- Answers improved: {report.answers_improved}")
        parts.append(f"- Facts learned: {report.facts_learned}")
        parts.append(f"- Duration: {report.duration_seconds:.1f}s")

        if report.topics_covered:
            parts.append(f"- Topics covered: {', '.join(report.topics_covered[:10])}")

        msg.content = "\n".join(parts)
        await msg.update()

    except Exception as exc:
        logger.error(f"[LEARN] Manual cycle failed: {exc}")
        msg.content = f"Learning cycle failed: {exc}"
        await msg.update()


async def _show_facts():
    """Show learned semantic facts."""
    try:
        engine = cl.user_session.get("engine")
        if not engine:
            await cl.Message(content="Database not available.").send()
            return

        from chat_app.episodic_memory import get_relevant_facts
        facts = await get_relevant_facts(engine, min_confidence=0.3, limit=20)

        if not facts:
            await cl.Message(content="No semantic facts learned yet. Use `/learn run` to generate facts.").send()
            return

        parts = ["**Learned Semantic Facts**\n"]
        for fact in facts:
            conf = fact.get("confidence", 0)
            category = fact.get("category", "general")
            rule = fact.get("rule", "")
            parts.append(f"- [{category}] ({conf:.0%}) {rule}")

        await cl.Message(content="\n".join(parts)).send()

    except Exception as exc:
        logger.error(f"[LEARN] Facts display failed: {exc}")
        await cl.Message(content=f"Error: {exc}").send()


async def _show_insights():
    """Show proactive insights."""
    try:
        engine = cl.user_session.get("engine")
        if not engine:
            await cl.Message(content="Database not available.").send()
            return

        from chat_app.proactive_insights import (
            analyze_saved_searches_for_optimization,
            detect_incident_patterns,
        )

        optimization_insights = await analyze_saved_searches_for_optimization(engine)
        incident_insights = await detect_incident_patterns(engine)

        all_insights = optimization_insights + incident_insights

        if not all_insights:
            await cl.Message(content="No proactive insights available at this time. The system needs more interaction data.").send()
            return

        parts = ["**Proactive Insights**\n"]
        for insight in all_insights[:10]:
            icon = {"critical": "🔴", "warning": "🟡", "suggestion": "🔵", "info": "ℹ️"}.get(insight.severity, "ℹ️")
            parts.append(f"{icon} **{insight.title}**")
            parts.append(f"   {insight.description}")
            if insight.action_payload:
                parts.append(f"   ```spl\n   {insight.action_payload[:200]}\n   ```")

        await cl.Message(content="\n".join(parts)).send()

    except Exception as exc:
        logger.error(f"[LEARN] Insights display failed: {exc}")
        await cl.Message(content=f"Error: {exc}").send()
