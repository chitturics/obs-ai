"""
/analyze_searches command handler.
"""
import logging
import chainlit as cl
from search_opt_client import call_robust_analyzer
from splunk_client import SplunkClient

logger = logging.getLogger(__name__)


async def analyze_searches_command():
    """Analyze all saved searches for optimizations."""
    await cl.Message(content="Analyzing saved searches... This may take a moment.").send()
    try:
        splunk_client = SplunkClient()
        saved_searches = splunk_client.get_saved_searches()

        if not saved_searches:
            await cl.Message(content="Could not find any saved searches or failed to connect to Splunk. Please ensure the following environment variables are set correctly:\n- `SPLUNK_HOST`\n- `SPLUNK_PORT`\n- `SPLUNK_USERNAME`\n- `SPLUNK_PASSWORD` (or `SPLUNK_TOKEN`)").send()
            return

        analysis_results = []
        for search in saved_searches:
            analysis = await call_robust_analyzer(search["query"])
            if analysis and (analysis.get("issues") or analysis.get("optimization_potential") > 30):
                analysis_results.append({
                    "name": search["name"],
                    "app": search["app"],
                    "owner": search["owner"],
                    "query": search["query"],
                    "analysis": analysis,
                })

        if not analysis_results:
            await cl.Message(content="Found no issues or optimization opportunities in your saved searches.").send()
            return

        report = "## Saved Search Analysis Report\n\nI found the following opportunities for improvement:\n\n"
        for result in analysis_results:
            report += f"### {result['name']} (App: {result['app']}, Owner: {result['owner']})\n"
            report += f"**Query:**\n```spl\n{result['query']}\n```\n"
            if result['analysis'].get("issues"):
                report += "**Issues Found:**\n"
                for issue in result['analysis']["issues"]:
                    report += f"- {issue['message']}\n"
            if result['analysis'].get("optimization_potential") > 30:
                report += f"**Optimization Potential:** {result['analysis']['optimization_potential']}/100\n"
                if result['analysis'].get("suggestions"):
                    report += "**Suggestions:**\n"
                    for sugg in result['analysis']["suggestions"]:
                        report += f"- {sugg}\n"
            report += "\n---\n\n"

        await cl.Message(content=report).send()

    except Exception as e:
        logger.error(f"Error during saved search analysis: {e}")
        await cl.Message(content=f"An error occurred during saved search analysis: {e}").send()
