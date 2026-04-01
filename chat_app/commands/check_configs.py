"""
/check_configs command handler.

Validates .conf files in the organization's repository directory
and reports common configuration issues sorted by severity.
"""
import logging

import chainlit as cl
from shared.config_analyzer import ConfigAnalyzer
from chat_app.settings import get_settings

logger = logging.getLogger(__name__)


async def check_configs_command():
    """Run a health check on local .conf files.

    Scans the org repo root directory for Splunk .conf files and reports
    issues such as deprecated settings, missing required fields, and
    potential misconfigurations.
    """
    org_repo_root = get_settings().paths.org_repo_root
    await cl.Message(
        content=f"Running configuration health check on files in `{org_repo_root}`..."
    ).send()

    try:
        analyzer = ConfigAnalyzer(config_root=org_repo_root)
        findings = analyzer.run_checks()

        if not findings:
            await cl.Message(content="No configuration issues found.").send()
            return

        # Sort findings: High > Medium > Low, then by file
        severity_order = {"High": 0, "Medium": 1, "Low": 2}
        findings.sort(key=lambda x: (severity_order.get(x["severity"], 3), x["file"]))

        report = "## Configuration Health Check Report\n\n"
        report += f"Found **{len(findings)}** potential issues:\n\n"

        for finding in findings:
            report += f"### [{finding['severity']}] {finding['title']}\n"
            report += f"- **File:** `{finding['file']}` (Line: {finding['line']})\n"
            report += f"- **Finding:** {finding['description']}\n"
            report += f"- **Evidence:** `{finding['evidence']}`\n\n"

        await cl.Message(content=report).send()

    except Exception as e:
        logger.error("Config health check failed: %s", e)
        await cl.Message(
            content=f"An error occurred during the configuration health check: {e}"
        ).send()
