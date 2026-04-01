"""
/config command handler — view/update settings with optional persistence.
"""
import asyncio
import logging
import chainlit as cl

logger = logging.getLogger(__name__)

# Map common config keys to admin API sections
_KEY_TO_SECTION = {
    "temperature": "llm",
    "model": "llm",
    "system_prompt": "prompts",
    "k_multiplier": "retrieval",
    "strategy": "retrieval",
    "search_depth": "retrieval",
    "chunk_tokens": "chunking",
    "overlap_tokens": "chunking",
}


async def config_command(setting: str):
    """View or update configuration."""
    settings = cl.user_session.get("settings", {})

    if not setting:
        config_text = "**Current Settings:**\n\n"
        for key, value in settings.items():
            config_text += f"- `{key}`: **{value}**\n"
        config_text += "\n**Usage:** `/config <key>=<value>`"
        await cl.Message(content=config_text).send()
        return

    if '=' not in setting:
        await cl.Message(
            content="**Invalid format**\n\n**Usage:** `/config <key>=<value>`"
        ).send()
        return

    key, value = setting.split('=', 1)
    key = key.strip()
    value = value.strip()

    # Parse value type
    if value.lower() in ['true', 'false']:
        value = value.lower() == 'true'
    elif value.replace('.', '', 1).isdigit():
        value = float(value) if '.' in value else int(value)

    settings[key] = value
    cl.user_session.set("settings", settings)

    # Persist to config.yaml via admin API (background, best-effort)
    persist_msg = ""
    section = _KEY_TO_SECTION.get(key)
    if section:
        asyncio.create_task(_persist_config(section, key, value))
        persist_msg = f"\n_Persisting to `{section}.{key}` in config.yaml..._"

    await cl.Message(
        content=f"**Setting updated!**\n\n`{key}` = **{value}**{persist_msg}"
    ).send()


async def _persist_config(section: str, key: str, value):
    """Best-effort persistence via admin API."""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.patch(
                f"https://localhost:8000/api/admin/config/section/{section}",
                json={"values": {key: value}},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status == 200:
                    logger.info("[CONFIG] Persisted %s.%s=%s", section, key, value)
                else:
                    logger.warning("[CONFIG] Persist failed (%d) for %s.%s",
                                   resp.status, section, key)
    except Exception as exc:
        logger.debug("[CONFIG] Persist best-effort failed: %s", exc)
