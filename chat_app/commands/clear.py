"""
/clear command handler.
"""
import chainlit as cl

async def clear_command():
    """Clear chat history."""
    cl.user_session.set("conversation_history", [])
    await cl.Message(content="**Chat history cleared!**").send()
