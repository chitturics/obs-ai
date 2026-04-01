"""
/run command handler.
"""
import logging
from typing import List, Dict

import chainlit as cl
from splunk_client import SplunkClient

logger = logging.getLogger(__name__)


def _format_results_as_table(results: List[Dict]) -> str:
    """Formats a list of dictionaries into a Markdown table."""
    if not results:
        return ""

    headers = results[0].keys()
    header_line = "| " + " | ".join(headers) + " |"
    separator_line = "| " + " | ".join(["---"] * len(headers)) + " |"

    rows = []
    for row in results[:20]: # Limit to 20 rows for display
        row_str = "| " + " | ".join(str(row.get(h, '')) for h in headers) + " |"
        rows.append(row_str)

    return "\n".join([header_line, separator_line] + rows)


async def run_command(query: str):
    """Execute a Splunk search query."""
    if not query:
        await cl.Message(content="Missing query.\n\n**Usage:** `/run <query>`").send()
        return

    msg = await cl.Message(content=f"Running search...\n```spl\n{query}\n```").send()

    try:
        splunk_client = SplunkClient()
        results = splunk_client.run_search(query)

        if not results:
            await msg.remove()
            await cl.Message(content=f"Search ran successfully but returned no results.\n```spl\n{query}\n```").send()
            return

        table = _format_results_as_table(results)

        summary = f"Search completed. Displaying {len(results[:20])} of {len(results)} results."
        if len(results) > 20:
            summary += " (truncated)"

        final_report = f"### Search Results\n\n{summary}\n\n{table}"

        await msg.remove()
        await cl.Message(content=final_report).send()

    except Exception as e:
        await msg.remove()
        error_message = f"An error occurred while running the search:\n\n`{e}`"
        await cl.Message(content=error_message).send()
