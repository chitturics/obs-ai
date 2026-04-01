"""
/kg command — Query the knowledge graph from chat.

Usage:
    /kg                    → show graph stats
    /kg search <term>      → find entities by name
    /kg analyze <SPL>      → decompose SPL into entities
    /kg related <entity>   → show relationships for an entity
"""
import logging
import chainlit as cl

logger = logging.getLogger(__name__)


async def kg_command(args: str):
    """Query the knowledge graph."""
    args = args.strip()

    # /kg → show stats
    if not args:
        return await _kg_stats()

    lower = args.lower()

    if lower.startswith("search "):
        return await _kg_search(args[7:].strip())

    if lower.startswith("analyze "):
        return await _kg_analyze(args[8:].strip())

    if lower.startswith("related "):
        return await _kg_related(args[8:].strip())

    # Default: treat as search
    return await _kg_search(args)


async def _kg_stats():
    """Show knowledge graph statistics."""
    try:
        from chat_app.knowledge_graph import get_knowledge_graph
        kg = get_knowledge_graph()
    except Exception as exc:
        await cl.Message(content=f"Knowledge graph unavailable: {exc}").send()
        return

    if not kg:
        await cl.Message(content="Knowledge graph is not initialized.").send()
        return

    stats = kg.get_stats()
    lines = ["### Knowledge Graph Stats\n"]
    lines.append(f"- **Entities:** {stats['total_entities']}")
    lines.append(f"- **Relationships:** {stats['total_relationships']}")
    lines.append(f"- **Build time:** {stats.get('build_time_ms', 0):.0f}ms")

    # Entity type breakdown
    type_counts = stats.get("entity_type_counts", {})
    if type_counts:
        lines.append("\n**Entity Types:**")
        for etype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            lines.append(f"- {etype}: {count}")

    # Relationship type breakdown (top 10)
    rel_counts = stats.get("relationship_type_counts", {})
    if rel_counts:
        lines.append("\n**Relationship Types (top 10):**")
        for rtype, count in sorted(rel_counts.items(), key=lambda x: -x[1])[:10]:
            lines.append(f"- {rtype}: {count}")

    lines.append("\n**Usage:** `/kg search <term>` | `/kg analyze <SPL>` | `/kg related <entity>`")
    await cl.Message(content="\n".join(lines)).send()


async def _kg_search(term: str):
    """Search for entities by name."""
    if not term:
        await cl.Message(content="**Usage:** `/kg search <term>`").send()
        return

    try:
        from chat_app.knowledge_graph import get_knowledge_graph
        kg = get_knowledge_graph()
        if not kg:
            await cl.Message(content="Knowledge graph is not initialized.").send()
            return
        results = kg.search_entities(term, limit=15)
    except Exception as exc:
        await cl.Message(content=f"Search failed: {exc}").send()
        return

    if not results:
        await cl.Message(content=f"No entities matching **{term}**.").send()
        return

    lines = [f"### Entities matching \"{term}\" ({len(results)} found)\n"]
    for entity in results:
        desc = f" — {entity.description[:80]}" if entity.description else ""
        lines.append(f"- **{entity.name}** (`{entity.entity_type}`){desc}")

    lines.append("\n_Use `/kg related <name>` to explore relationships._")
    await cl.Message(content="\n".join(lines)).send()


async def _kg_analyze(spl: str):
    """Decompose an SPL query into knowledge graph entities."""
    if not spl:
        await cl.Message(content="**Usage:** `/kg analyze <SPL query>`").send()
        return

    try:
        from chat_app.knowledge_graph import SPLQueryAnalyzer
        analysis = SPLQueryAnalyzer.analyze(spl)
    except Exception as exc:
        await cl.Message(content=f"Analysis failed: {exc}").send()
        return

    lines = ["### SPL Query Analysis\n"]
    lines.append(f"```spl\n{spl}\n```\n")

    if analysis.get("commands"):
        lines.append(f"**Commands:** {', '.join(f'`{c}`' for c in analysis['commands'])}")
    if analysis.get("functions"):
        lines.append(f"**Functions:** {', '.join(f'`{f}`' for f in analysis['functions'])}")
    if analysis.get("fields"):
        lines.append(f"**Fields:** {', '.join(f'`{f}`' for f in analysis['fields'])}")
    if analysis.get("indexes"):
        lines.append(f"**Indexes:** {', '.join(f'`{i}`' for i in analysis['indexes'])}")
    if analysis.get("sourcetypes"):
        lines.append(f"**Sourcetypes:** {', '.join(f'`{s}`' for s in analysis['sourcetypes'])}")
    if analysis.get("sources"):
        lines.append(f"**Sources:** {', '.join(f'`{s}`' for s in analysis['sources'])}")
    if analysis.get("macros"):
        lines.append(f"**Macros:** {', '.join(f'`{m}`' for m in analysis['macros'])}")
    if analysis.get("lookups"):
        lines.append(f"**Lookups:** {', '.join(f'`{l}`' for l in analysis['lookups'])}")
    if analysis.get("datamodels"):
        lines.append(f"**Data Models:** {', '.join(f'`{d}`' for d in analysis['datamodels'])}")
    if analysis.get("filters"):
        lines.append(f"**Filters:** {', '.join(f'`{f}`' for f in analysis['filters'])}")
    if analysis.get("has_tstats"):
        lines.append("**Uses tstats:** Yes (accelerated search)")
    if analysis.get("has_summarization"):
        lines.append("**Has summarization:** Yes")

    total = sum(
        len(analysis.get(k, []))
        for k in ("commands", "functions", "fields", "indexes", "sourcetypes",
                   "sources", "macros", "lookups", "datamodels", "filters")
    )
    lines.append(f"\n_Total entities identified: {total}_")
    await cl.Message(content="\n".join(lines)).send()


async def _kg_related(entity_name: str):
    """Show relationships for a named entity."""
    if not entity_name:
        await cl.Message(content="**Usage:** `/kg related <entity name>`").send()
        return

    try:
        from chat_app.knowledge_graph import get_knowledge_graph
        kg = get_knowledge_graph()
        if not kg:
            await cl.Message(content="Knowledge graph is not initialized.").send()
            return

        entity = kg.resolve_entity(entity_name)
        if not entity:
            await cl.Message(
                content=f"Entity **{entity_name}** not found. Try `/kg search {entity_name}`."
            ).send()
            return

        neighbors = kg.get_neighbors(entity.id)
    except Exception as exc:
        await cl.Message(content=f"Lookup failed: {exc}").send()
        return

    lines = [f"### Relationships for {entity.name} (`{entity.entity_type}`)\n"]
    if entity.description:
        lines.append(f"_{entity.description[:120]}_\n")

    outgoing = [n for n in neighbors if n["direction"] == "outgoing"]
    incoming = [n for n in neighbors if n["direction"] == "incoming"]

    if outgoing:
        lines.append(f"**Outgoing ({len(outgoing)}):**")
        for n in outgoing[:15]:
            lines.append(f"- —[`{n['rel_type']}`]→ **{n['target_name']}** (`{n['target_type']}`)")

    if incoming:
        lines.append(f"\n**Incoming ({len(incoming)}):**")
        for n in incoming[:15]:
            lines.append(f"- ←[`{n['rel_type']}`]— **{n['source_name']}** (`{n['source_type']}`)")

    if not outgoing and not incoming:
        lines.append("_No relationships found for this entity._")
    else:
        total = len(outgoing) + len(incoming)
        shown = min(len(outgoing), 15) + min(len(incoming), 15)
        if shown < total:
            lines.append(f"\n_Showing {shown} of {total} relationships._")

    await cl.Message(content="\n".join(lines)).send()
