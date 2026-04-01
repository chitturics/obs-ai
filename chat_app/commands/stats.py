"""
/stats command handler.
"""
import chainlit as cl


async def stats_command():
    """Show user statistics and metrics."""
    try:
        from chat_app.metrics import get_stats_report
        report = get_stats_report()
        await cl.Message(content=report).send()
    except ImportError:
        # Fallback: try without package prefix (running from chat_app dir)
        try:
            from metrics import get_stats_report
            report = get_stats_report()
            await cl.Message(content=report).send()
        except ImportError:
            await cl.Message(
                content="**Statistics**\n\n"
                "Metrics module not available. Stats are collected during active sessions.\n\n"
                "Try `/health` for service health checks or check the admin console "
                "at [Admin Console](/api/admin/v2/) for full dashboard metrics."
            ).send()
