"""
Intent handler for the Splunk Assistant.

Handles tool-callable intents (run_search, create_alert, etc.)
with optional MCP tool-augmented LLM support.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import TYPE_CHECKING

import chainlit as cl
import splunklib.binding as binding
from chat_app.query_router_handler import QueryPlan
from chat_app.registry import Intent

if TYPE_CHECKING:
    from chat_app.message_context import MessageHandlerContext
from splunk_client import SplunkClient
from shared.config_analyzer import ConfigAnalyzer
from search_opt_client import call_robust_analyzer

try:
    from chat_app.tool_executor import should_use_tools, run_tool_augmented_query
    _TOOL_EXECUTOR_AVAILABLE = True
except ImportError:
    _TOOL_EXECUTOR_AVAILABLE = False

logger = logging.getLogger(__name__)


def _splunk_configured() -> bool:
    """Check if Splunk connection details are configured."""
    try:
        from chat_app.settings import get_settings
        cfg = get_settings().splunk
        return bool(cfg.host)
    except Exception as _exc:  # broad catch — resilience against all failures
        return False


async def _splunk_not_configured_msg(action_desc: str) -> None:
    """Send a user-friendly message when Splunk is not configured."""
    await cl.Message(
        content=(
            f"**Splunk is not configured** — cannot {action_desc}.\n\n"
            "To enable live Splunk features, set these environment variables:\n"
            "- `SPLUNK_HOST` (required)\n"
            "- `SPLUNK_PORT` (default: 8089)\n"
            "- `SPLUNK_TOKEN` or `SPLUNK_USERNAME` + `SPLUNK_PASSWORD`\n\n"
            "I can still help you with questions about saved searches, alerts, "
            "and configurations using the knowledge base. Just rephrase your "
            "question without asking me to run or create anything."
        )
    ).send()


async def handle_intent(plan: QueryPlan, user_input: str, context: "MessageHandlerContext") -> bool:
    """Handles the intent of the user's message. Returns True if handled."""
    if plan.intent == Intent.SAVED_SEARCH_ANALYSIS:
        if not _splunk_configured():
            await _splunk_not_configured_msg("analyze saved searches")
            return True
        await cl.Message(content="Analyzing saved searches... This may take a moment.").send()
        try:
            splunk_client = SplunkClient()
            saved_searches = splunk_client.get_saved_searches()

            if not saved_searches:
                await cl.Message(content="Could not find any saved searches or failed to connect to Splunk. Please ensure the following environment variables are set correctly:\n- `SPLUNK_HOST`\n- `SPLUNK_PORT`\n- `SPLUNK_USERNAME`\n- `SPLUNK_PASSWORD` (or `SPLUNK_TOKEN`)").send()
                return True

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
                return True

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
        except binding.AuthenticationError:
            await cl.Message(content="Splunk authentication failed. Please check your credentials in the environment variables.").send()
        except binding.HTTPError as e:
            await cl.Message(content=f"A Splunk HTTP error occurred: {e}").send()
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.error(f"Error during saved search analysis: {e}")
            await cl.Message(content=f"An error occurred during saved search analysis: {e}").send()
        return True

    if plan.intent == Intent.CONFIG_HEALTH_CHECK:
        org_repo_root = os.getenv("ORG_REPO_ROOT", "/app/public/documents/repo")
        await cl.Message(content=f"Running configuration health check on files in `{org_repo_root}`...").send()
        try:
            analyzer = ConfigAnalyzer(config_root=org_repo_root)
            findings = analyzer.run_checks()

            if not findings:
                await cl.Message(content="✅ No configuration issues found.").send()
                return True

            report = "## Configuration Health Check Report\n\nI found the following potential issues in your configuration files:\n\n"
            findings.sort(key=lambda x: ({"High": 0, "Medium": 1, "Low": 2}.get(x["severity"], 3), x["file"]))

            for finding in findings:
                report += f"### [{finding['severity']}] {finding['title']}\n"
                report += f"- **File:** `{finding['file']}` (Line: {finding['line']})\n"
                report += f"- **Finding:** {finding['description']}\n"
                report += f"- **Evidence:** `{finding['evidence']}`\n\n"

            await cl.Message(content=report).send()

        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.error(f"Error during config health check: {e}")
            await cl.Message(content=f"An error occurred during the configuration health check: {e}").send()
        return True

    if plan.intent == Intent.RUN_SEARCH:
        if not _splunk_configured():
            await _splunk_not_configured_msg("run searches")
            return True

        query = plan.extracted_query
        if not query:
            await cl.Message(content="I couldn't extract a valid SPL query from your message. Please try again, for example: `run index=_internal | head 5`").send()
            return True

        msg = await cl.Message(content=f"Running search...\n```spl\n{query}\n```").send()

        try:
            splunk_client = SplunkClient()
            results = splunk_client.run_search(query)

            if not results:
                await msg.remove()
                await cl.Message(content=f"Search ran successfully but returned no results.\n```spl\n{query}\n```").send()
                return True

            # Format results as a markdown table
            headers = results[0].keys()
            header_line = "| " + " | ".join(headers) + " |"
            separator_line = "| " + " | ".join(["---"] * len(headers)) + " |"

            rows = []
            for row in results[:20]: # Limit to 20 rows for display
                row_str = "| " + " | ".join(str(row.get(h, '')) for h in headers) + " |"
                rows.append(row_str)

            table = "\n".join([header_line, separator_line] + rows)

            summary = f"Search completed. Displaying {len(rows)} of {len(results)} results."
            if len(results) > len(rows):
                summary += f" (truncated from {len(results)})"

            final_report = f"### Search Results\n\n{summary}\n\n{table}"

            await msg.remove()
            await cl.Message(content=final_report).send()

        except binding.HTTPError as e:
            await msg.remove()
            error_message = f"An error occurred while running the search. This may be due to an invalid query. Please check your SPL.\n\n**Details:**\n`{e}`"
            await cl.Message(content=error_message).send()
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            await msg.remove()
            error_message = f"An unexpected error occurred while running the search:\n\n`{e}`"
            await cl.Message(content=error_message).send()
        return True

    if plan.intent == Intent.CREATE_ALERT:
        if not _splunk_configured():
            await _splunk_not_configured_msg("create alerts")
            return True

        from langchain_core.prompts import ChatPromptTemplate
        from langchain_core.output_parsers import StrOutputParser

        msg = await cl.Message(content="Analyzing your alert request...").send()

        # Define a prompt for the LLM to extract parameters
        extraction_prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert assistant that parses natural language requests for Splunk alerts and converts them into a structured JSON object.

The user wants to create an alert. Extract the following parameters from the user's request:
- "name": A unique and descriptive name for the alert.
- "query": The full SPL query for the alert.
- "cron_schedule": A cron schedule (e.g., "*/5 * * * *"). If the user says "every 10 minutes", convert it. Default to "*/5 * * * *" if not specified.
- "alert_type": The alert type. Usually "number of events".
- "alert_comparator": The comparison operator (e.g., "greater than", "less than").
- "alert_threshold": The threshold value (e.g., "100").
- "description": A brief description of the alert's purpose.

If a value is not specified, omit the key from the JSON. The "name" and "query" are required.

Respond ONLY with the JSON object, enclosed in ```json ... ```."""),
            ("human", "{user_request}")
        ])

        # Create a temporary chain for this task
        extraction_chain = extraction_prompt | context.llm | StrOutputParser()

        try:
            # Get the JSON response from the LLM
            raw_response = await extraction_chain.ainvoke({"user_request": user_input})

            # Extract JSON from the markdown block
            json_match = re.search(r'```json\n(.*?)\n```', raw_response, re.DOTALL)
            if not json_match:
                msg.content = f"I had trouble understanding the alert details. Could you please be more specific about the alert's name and query?\n\nLLM Response: {raw_response}"
                await msg.update()
                return True

            params_str = json_match.group(1)
            alert_params = json.loads(params_str)

            # Check for required parameters
            if "name" not in alert_params or "query" not in alert_params:
                msg.content = "I couldn't determine the **name** and **query** for the alert. Please provide them."
                await msg.update()
                return True

            msg.content = f"Preparing to create alert '{alert_params['name']}'..."
            await msg.update()

            # Call the splunk client
            splunk_client = SplunkClient()
            splunk_client.create_alert(**alert_params)

            final_message = f"✅ **Alert Created Successfully!**\n\n- **Name:** {alert_params.get('name')}\n- **Schedule:** {alert_params.get('cron_schedule', 'Default (every 5 mins)')}"
            msg.content = final_message
            await msg.update()

        except json.JSONDecodeError:
            msg.content = "I received an invalid format from the language model. Please try rephrasing your request."
            await msg.update()
        except binding.HTTPError as e:
            if e.status == 409:
                msg.content = f"An alert with the name '{alert_params.get('name')}' already exists. Please choose a different name."
                await msg.update()
            else:
                msg.content = f"A Splunk HTTP error occurred while creating the alert:\n\n`{e}`"
                await msg.update()
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            msg.content = f"An unexpected error occurred while creating the alert:\n\n`{e}`"
            await msg.update()
        return True

    # Fallback: if the intent is tool-callable and MCP tools are available,
    # try running a tool-augmented query
    mcp_tools = getattr(context, "mcp_tools", [])
    if _TOOL_EXECUTOR_AVAILABLE and mcp_tools and should_use_tools(plan.intent):
        try:
            result = await run_tool_augmented_query(
                user_input=user_input,
                llm=context.llm,
                tools=mcp_tools,
                system_prompt=context.system_prompt,
                max_tool_rounds=2,
            )
            if result:
                await cl.Message(content=result).send()
                return True
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning(f"[MCP] Tool-augmented query failed: {exc}")
