"""
/create_alert command handler.
"""
import chainlit as cl

async def create_alert_command():
    """Guide the user on how to create an alert."""
    await cl.Message(
        content="""To create an alert, please describe it in a single message. I will parse the details.

**Example:**
`create an alert named 'High Error Rate' for the query 'index=main sourcetype=error_logs | stats count' that runs every 15 minutes and triggers if the count is greater than 50.`
"""
    ).send()
