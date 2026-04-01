"""
/explain command — Explain an SPL query in plain language.

Usage: /explain <SPL query>
Example: /explain index=main sourcetype=access_combined | stats count by status | sort -count
"""
import logging
import chainlit as cl

logger = logging.getLogger(__name__)


async def explain_command(args: str):
    """Explain an SPL query in plain language."""
    if not args.strip():
        await cl.Message(content=(
            "**Usage:** `/explain <SPL query>`\n\n"
            "**Example:** `/explain index=main sourcetype=access_combined | stats count by status`\n\n"
            "This will break down the query into plain-language steps and highlight performance considerations."
        )).send()
        return

    try:
        from chat_app.proactive_insights import explain_spl

        explanation = explain_spl(args.strip())

        parts = [f"**SPL Explanation** (Complexity: {explanation.complexity})\n"]
        parts.append(f"```spl\n{explanation.original_spl}\n```\n")
        parts.append(f"**Summary:** {explanation.summary}\n")

        if explanation.steps:
            parts.append("**Step-by-step breakdown:**")
            for i, step in enumerate(explanation.steps, 1):
                parts.append(f"{i}. {step.replace('Step: ', '')}")

        if explanation.performance_notes:
            parts.append("\n**Performance considerations:**")
            for note in explanation.performance_notes:
                parts.append(f"- {note.replace('Performance: ', '')}")

        # Add KG entity decomposition
        try:
            from chat_app.knowledge_graph import SPLQueryAnalyzer
            analysis = SPLQueryAnalyzer.analyze(args.strip())
            kg_parts = []
            if analysis.get("commands"):
                kg_parts.append(f"**Commands:** {', '.join(f'`{c}`' for c in analysis['commands'])}")
            if analysis.get("functions"):
                kg_parts.append(f"**Functions:** {', '.join(f'`{f}`' for f in analysis['functions'])}")
            if analysis.get("indexes"):
                kg_parts.append(f"**Indexes:** {', '.join(f'`{i}`' for i in analysis['indexes'])}")
            if analysis.get("fields"):
                kg_parts.append(f"**Fields:** {', '.join(f'`{f}`' for f in analysis['fields'])}")
            if analysis.get("sourcetypes"):
                kg_parts.append(f"**Sourcetypes:** {', '.join(f'`{s}`' for s in analysis['sourcetypes'])}")
            if analysis.get("macros"):
                kg_parts.append(f"**Macros:** {', '.join(f'`{m}`' for m in analysis['macros'])}")
            if analysis.get("lookups"):
                kg_parts.append(f"**Lookups:** {', '.join(f'`{l}`' for l in analysis['lookups'])}")
            if analysis.get("has_tstats"):
                kg_parts.append("**Accelerated:** Uses tstats (fast indexed search)")
            if kg_parts:
                parts.append("\n**Entity Decomposition:**")
                parts.extend(kg_parts)
        except Exception:
            pass

        await cl.Message(content="\n".join(parts)).send()

    except Exception as exc:
        logger.error(f"[EXPLAIN] Command failed: {exc}")
        await cl.Message(content=f"Error explaining SPL: {exc}").send()
