"""
Meta commands handler for ObsAI - Observability AI Assistant.
"""
import chainlit as cl

async def handle_meta_commands(message: cl.Message, vector_store, engine, starter_options):
    """Handles slash commands and starter messages."""
    user_input = (message.content or "").strip()

    # Handle commands
    command = getattr(message, "command", None)
    if command:
        from slash_commands import handle_slash_command
        await handle_slash_command(f"/{command} {user_input}".strip(),
                                   vector_store=vector_store, engine=engine)
        return True
    if user_input.startswith('/'):
        from slash_commands import handle_slash_command
        await handle_slash_command(user_input, vector_store=vector_store, engine=engine)
        return True

    # Handle starters
    starter_messages = [opt["message"] for opt in starter_options]
    if user_input in starter_messages:
        await cl.Message(content=(
            f"{user_input}\n\nPlease select one of the example prompts above or create your own specific question."
        )).send()
        return True

    # Handle meta-questions
    user_lower = user_input.lower()
    if any(p in user_lower for p in ["who are you", "what are you", "introduce yourself"]):
        try:
            from chat_app.settings import get_settings
            _ver = get_settings().app.version
        except Exception as _exc:  # broad catch — resilience against all failures
            _ver = "3.1.0"
        await cl.Message(content=(
            f"I'm **ObsAI - Observability AI Assistant** `v{_ver}`\n\n"
            "An AI assistant specialized in Splunk configurations, queries, and best practices. "
            "I have access to Splunk spec files, local documentation, SPL query generation, "
            "and configuration examples.\n\n"
            "Type `/version` for full system info or `/help` for all commands."
        )).send()
        return True
    if any(p in user_lower for p in ["what can you do", "how can you help", "your capabilities"]):
        await cl.Message(content=(
            "**My Capabilities:**\n\n"
            "- **Search & Query Help** - Generate optimized tstats queries, create SPL searches, validate queries\n"
            "- **Configuration Assistance** - Explain .conf settings, provide examples for inputs/props/transforms\n"
            "- **Documentation Lookup** - Search spec files, reference local docs, best practices\n\n"
            "Just ask me specific questions about Splunk!"
        )).send()
        return True

    return False
