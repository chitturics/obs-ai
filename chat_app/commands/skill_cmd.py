"""
/skill command — Execute or browse skills from chat.

Usage:
    /skill              → list executable skills by family
    /skill search <q>   → search skill catalog
    /skill <name>       → execute a skill
    /skill <name> <arg> → execute with input
"""
import logging
import chainlit as cl

logger = logging.getLogger(__name__)


async def skill_command(args: str):
    """Execute or browse skills from chat."""
    args = args.strip()

    # /skill → list executable skills
    if not args:
        return await _list_skills()

    # /skill search <term>
    if args.lower().startswith("search "):
        term = args[7:].strip()
        return await _search_skills(term)

    # /skill <name> [params]
    parts = args.split(maxsplit=1)
    skill_name = parts[0]
    input_text = parts[1] if len(parts) > 1 else ""
    return await _execute_skill(skill_name, input_text)


async def _list_skills():
    """List all executable skills grouped by family."""
    try:
        from chat_app.skill_executor import get_skill_executor
        executor = get_skill_executor()
        available = executor.get_available_skills()
    except Exception as exc:
        await cl.Message(content=f"Could not load skills: {exc}").send()
        return

    if not available:
        await cl.Message(content="No executable skills available.").send()
        return

    # Group by family
    by_family: dict = {}
    for s in available:
        family = s.get("family", "other")
        by_family.setdefault(family, []).append(s)

    lines = [f"### Executable Skills ({len(available)} available)\n"]
    for family in sorted(by_family):
        lines.append(f"**{family.title()}**")
        for s in sorted(by_family[family], key=lambda x: x["name"]):
            source_tag = f"`{s['source']}`"
            lines.append(f"- `{s['name']}` ({s['action']}) — {source_tag}")
        lines.append("")

    lines.append("**Usage:** `/skill <name> [input]` or `/skill search <term>`")
    await cl.Message(content="\n".join(lines)).send()


async def _search_skills(term: str):
    """Search the skill catalog by name, action, or tag."""
    if not term:
        await cl.Message(content="**Usage:** `/skill search <term>`").send()
        return

    try:
        from chat_app.skill_catalog import get_skill_catalog
        catalog = get_skill_catalog()
        results = catalog.search(term)
    except Exception as exc:
        await cl.Message(content=f"Search failed: {exc}").send()
        return

    if not results:
        await cl.Message(content=f"No skills matching **{term}**.").send()
        return

    lines = [f"### Skills matching \"{term}\" ({len(results)} found)\n"]
    for skill in results[:15]:
        handler = f"`{skill.handler_key}`" if skill.handler_key else "_no handler_"
        lines.append(
            f"- **{skill.display_name}** (`{skill.name}`) — {skill.description[:80]}  "
            f"  Handler: {handler}"
        )

    await cl.Message(content="\n".join(lines)).send()


async def _execute_skill(skill_name: str, input_text: str):
    """Execute a skill by name."""
    try:
        from chat_app.skill_executor import get_skill_executor
        executor = get_skill_executor()
    except Exception as exc:
        await cl.Message(content=f"Skill executor unavailable: {exc}").send()
        return

    msg = cl.Message(content=f"Executing skill `{skill_name}`...")
    await msg.send()

    params = {"input": input_text, "user_input": input_text}
    result = await executor.execute(skill_name=skill_name, params=params)

    if result.approval_required:
        msg.content = f"Skill `{skill_name}` requires approval: {result.approval_message}"
        await msg.update()
        return

    if not result.success:
        msg.content = (
            f"**Skill Failed:** `{skill_name}`\n\n"
            f"Error: {result.error}\n"
            f"Duration: {result.duration_ms:.0f}ms"
        )
        await msg.update()
        return

    msg.content = (
        f"**Skill Result:** `{skill_name}` ({result.source})\n\n"
        f"{result.output}\n\n"
        f"_Duration: {result.duration_ms:.0f}ms_"
    )
    await msg.update()
