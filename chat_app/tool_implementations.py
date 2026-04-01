"""
Tool Implementations — Execution functions for all built-in tools.

Extracted from tool_definitions.py for size management.
tool_definitions.py imports from this module.

Provides:
- _tool_analyze_spl, _tool_optimize_spl, _tool_validate_spl, _tool_generate_spl
- _tool_run_splunk_search, _tool_list_saved_searches, _tool_check_splunk_health
- _tool_analyze_configs, _tool_lookup_config
- _tool_analyze_cribl_pipeline, _tool_generate_cribl_route, _tool_suggest_metrics_query
- _tool_search_kb, _tool_update_saved_search, _tool_create_knowledge_object
- Splunk admin tools: list_indexes, list_inputs, list_apps, list_users,
  get_server_info, list_deployment_clients, search_index_stats, list_lookups,
  list_macros, get_license_usage
"""
import logging

from chat_app.tool_registry import ToolResult

logger = logging.getLogger(__name__)

def _tool_analyze_spl(query: str, auto_fix: bool = True) -> ToolResult:
    """Analyze SPL for issues and optimization opportunities."""
    try:
        from shared.spl_robust_analyzer import analyze_spl
        result = analyze_spl(query, auto_fix=auto_fix)

        parts = []
        if result.issues:
            parts.append("**Issues Found:**")
            for issue in result.issues:
                severity = issue.severity.value.upper() if hasattr(issue.severity, 'value') else str(issue.severity)
                parts.append(f"- [{severity}] {issue.message}")

        if result.optimized_query and result.optimized_query != query:
            parts.append(f"\n**Optimized Query:**\n```spl\n{result.optimized_query}\n```")

        if hasattr(result, 'score') and result.score is not None:
            parts.append(f"\n**Quality Score:** {result.score}/100")

        output = "\n".join(parts) if parts else "No issues found. Query looks good."
        return ToolResult(
            success=True,
            output=output,
            data={"issues_count": len(result.issues) if result.issues else 0},
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Analysis failed: {exc}")


def _tool_optimize_spl(query: str) -> ToolResult:
    """Optimize SPL query."""
    try:
        from shared.spl_query_optimizer import SPLQueryOptimizer
        result = SPLQueryOptimizer.optimize(query)
        optimized = getattr(result, 'optimized', query)
        strategy = getattr(result, 'strategy', None)
        notes = getattr(result, 'performance_notes', []) or []

        if optimized.strip() == query.strip():
            return ToolResult(
                success=True,
                output="Query is already well-optimized. No changes needed.",
            )

        parts = [f"**Optimized Query:**\n```spl\n{optimized}\n```"]
        if strategy:
            strategy_str = strategy.value if hasattr(strategy, 'value') else str(strategy)
            parts.append(f"**Strategy:** {strategy_str}")
        if notes:
            parts.append("**Performance Notes:**")
            for note in notes[:5]:
                parts.append(f"- {note}")

        return ToolResult(success=True, output="\n".join(parts))
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Optimization failed: {exc}")


def _tool_validate_spl(query: str) -> ToolResult:
    """Validate SPL syntax."""
    try:
        from shared.spl_validator import SPLValidator, ValidationStatus
        result = SPLValidator.validate(query, block_dangerous=False)

        status_str = result.status.value if hasattr(result.status, 'value') else str(result.status)
        parts = [f"**Validation Status:** {status_str}"]

        if result.errors:
            parts.append("**Errors:**")
            for err in result.errors:
                parts.append(f"- {err}")
        if result.warnings:
            parts.append("**Warnings:**")
            for warn in result.warnings:
                parts.append(f"- {warn}")
        if result.status == ValidationStatus.VALID:
            parts.append("Query syntax is valid.")

        return ToolResult(success=True, output="\n".join(parts))
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Validation failed: {exc}")


async def _tool_generate_spl(description: str, index: str = None, sourcetype: str = None) -> ToolResult:
    """Generate SPL from natural language."""
    try:
        from shared.nlp_to_spl import generate_spl_query
        query = generate_spl_query(description, index=index, sourcetype=sourcetype)
        if query:
            return ToolResult(
                success=True,
                output=f"**Generated SPL:**\n```spl\n{query}\n```",
                data={"query": query},
            )
        return ToolResult(success=False, output="", error="Could not generate SPL from the description")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"SPL generation failed: {exc}")


async def _tool_run_splunk_search(query: str, earliest: str = "-15m", latest: str = "now") -> ToolResult:
    """Execute SPL against Splunk."""
    try:
        from splunk_client import SplunkClient
        client = SplunkClient()
        results = client.run_search(query, earliest_time=earliest, latest_time=latest)

        if not results:
            return ToolResult(success=True, output="Search completed with no results.")

        # Format as markdown table (limit rows)
        headers = list(results[0].keys())
        rows = results[:20]
        header_line = "| " + " | ".join(headers) + " |"
        sep_line = "| " + " | ".join(["---"] * len(headers)) + " |"
        row_lines = [
            "| " + " | ".join(str(r.get(h, ''))[:50] for h in headers) + " |"
            for r in rows
        ]
        table = "\n".join([header_line, sep_line] + row_lines)

        summary = f"Returned {len(results)} results"
        if len(results) > 20:
            summary += " (showing first 20)"

        return ToolResult(
            success=True,
            output=f"{summary}\n\n{table}",
            data={"total_results": len(results), "results": results[:20]},
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Search failed: {exc}")


async def _tool_list_saved_searches() -> ToolResult:
    """List saved searches from Splunk."""
    try:
        from splunk_client import SplunkClient
        client = SplunkClient()
        searches = client.get_saved_searches()
        if not searches:
            return ToolResult(success=True, output="No saved searches found.")

        parts = [f"Found **{len(searches)}** saved searches:\n"]
        for search in searches[:25]:
            parts.append(
                f"- **{search['name']}** (App: {search.get('app', 'N/A')}, Owner: {search.get('owner', 'N/A')})"
            )

        return ToolResult(success=True, output="\n".join(parts), data={"searches": searches})
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Failed to list saved searches: {exc}")


async def _tool_check_splunk_health() -> ToolResult:
    """Check Splunk instance health."""
    try:
        from splunk_client import SplunkClient
        client = SplunkClient()
        info = client.get_server_info()
        return ToolResult(
            success=True,
            output=(
                f"**Splunk Health:** Connected\n"
                f"- Version: {info.get('version', 'unknown')}\n"
                f"- Server: {info.get('serverName', 'unknown')}"
            ),
            data=info,
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Health check failed: {exc}")


def _tool_analyze_configs(config_path: str = None) -> ToolResult:
    """Run config health checks."""
    import os
    try:
        from shared.config_analyzer import ConfigAnalyzer
        path = config_path or os.getenv("ORG_REPO_ROOT", "/app/public/documents/repo")
        analyzer = ConfigAnalyzer(config_root=path)
        findings = analyzer.run_checks()

        if not findings:
            return ToolResult(success=True, output="No configuration issues found.")

        findings.sort(key=lambda item: ({"High": 0, "Medium": 1, "Low": 2}.get(item["severity"], 3)))
        parts = [f"Found **{len(findings)}** issues:\n"]
        for finding in findings[:15]:
            parts.append(
                f"- [{finding['severity']}] **{finding['title']}** in `{finding['file']}` "
                f"(line {finding['line']}): {finding['description']}"
            )

        return ToolResult(success=True, output="\n".join(parts), data={"findings": findings})
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Config analysis failed: {exc}")


def _tool_lookup_config(conf_file: str, stanza: str = None, parameter: str = None) -> ToolResult:
    """Look up specific config stanza/parameter."""
    try:
        from context_builder import find_local_spec_file, extract_spec_stanzas
        import os

        search_roots = [
            os.getenv("SPEC_STATIC_ROOT", "/app/public/documents/specs"),
            os.getenv("SPEC_SRC_ROOT", "/tmp/specs"),
            os.getenv("ORG_REPO_ROOT", "/app/public/documents/repo"),
        ]

        spec_file = find_local_spec_file(conf_file, search_roots)
        if not spec_file:
            return ToolResult(
                success=False, output="",
                error=f"Config file '{conf_file}' not found in knowledge base",
                suggestions=[f"Try ingesting {conf_file} with: read_url: https://docs.splunk.com/..."],
            )

        stanzas = extract_spec_stanzas(spec_file, stanza, limit=5)
        if not stanzas:
            return ToolResult(success=True, output=f"File '{conf_file}' found but no matching stanzas.")

        output = f"**{conf_file}** reference:\n\n" + "\n\n".join(stanzas[:3])
        return ToolResult(success=True, output=output)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Config lookup failed: {exc}")


def _tool_analyze_cribl_pipeline(pipeline_config: str) -> ToolResult:
    """Analyze Cribl pipeline configuration."""
    try:
        import yaml
        import json

        # Parse the config
        try:
            config = yaml.safe_load(pipeline_config)
        except Exception:  # broad catch — resilience at boundary
            try:
                config = json.loads(pipeline_config)
            except Exception:  # broad catch — resilience at boundary
                return ToolResult(
                    success=False, output="",
                    error="Could not parse pipeline config as YAML or JSON",
                )

        issues = []
        suggestions = []

        # Basic Cribl pipeline analysis
        if isinstance(config, dict):
            functions = config.get("functions", config.get("pipeline", {}).get("functions", []))
            if isinstance(functions, list):
                for idx, func in enumerate(functions):
                    func_id = func.get("id", f"function_{idx}")
                    func_type = func.get("conf", {}).get("type", func.get("type", "unknown"))

                    # Check for common issues
                    if func_type == "regex_extract" and not func.get("conf", {}).get("regex"):
                        issues.append(f"Function '{func_id}': regex_extract without regex pattern")
                    if func_type == "eval" and not func.get("conf", {}).get("add", []):
                        issues.append(f"Function '{func_id}': eval function with no expressions")
                    if not func.get("filter"):
                        suggestions.append(
                            f"Function '{func_id}': Consider adding a filter to reduce processing"
                        )

        parts = []
        if issues:
            parts.append("**Issues:**")
            for issue in issues:
                parts.append(f"- {issue}")
        if suggestions:
            parts.append("**Suggestions:**")
            for suggestion in suggestions:
                parts.append(f"- {suggestion}")
        if not issues and not suggestions:
            parts.append("Pipeline configuration looks good. No issues found.")

        return ToolResult(success=True, output="\n".join(parts))
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Pipeline analysis failed: {exc}")


def _tool_generate_cribl_route(
    description: str, source_type: str = None, destination: str = None
) -> ToolResult:
    """Generate a Cribl route configuration."""
    import json
    parts = ["**Suggested Cribl Route Configuration:**\n"]

    route_config = {
        "id": "auto_generated_route",
        "name": f"Route for: {description[:50]}",
        "filter": f"sourcetype=='{source_type}'" if source_type else "true",
        "pipeline": "main",
        "output": destination or "default",
        "final": False,
        "description": description,
    }

    parts.append(f"```yaml\n{json.dumps(route_config, indent=2)}\n```")
    parts.append("\n**Notes:**")
    parts.append("- Adjust the `filter` expression to match your data")
    parts.append("- Set `final: true` if no other routes should process matching events")
    parts.append("- Create a pipeline with appropriate functions for your use case")

    return ToolResult(success=True, output="\n".join(parts))


def _tool_suggest_metrics_query(metric_name: str, time_range: str = "-1h") -> ToolResult:
    """Suggest mstats/mcatalog queries for metrics."""
    queries = [
        {
            "name": "Discover metrics",
            "query": f'| mcatalog values(metric_name) WHERE metric_name="{metric_name}*"',
        },
        {
            "name": "Average over time",
            "query": f'| mstats avg("{metric_name}") WHERE index=* span=5m earliest={time_range}',
        },
        {
            "name": "By host",
            "query": f'| mstats avg("{metric_name}") WHERE index=* BY host span=5m earliest={time_range}',
        },
    ]

    parts = ["**Suggested Metrics Queries:**\n"]
    for query in queries:
        parts.append(f"**{query['name']}:**\n```spl\n{query['query']}\n```\n")

    return ToolResult(success=True, output="\n".join(parts))


async def _tool_search_kb(query: str, collection: str = None) -> ToolResult:
    """Search the knowledge base."""
    try:
        from vectorstore import ensure_vector_store, search_similar_chunks

        store = ensure_vector_store()
        if not store:
            return ToolResult(success=False, output="", error="Vector store not available")

        chunks = search_similar_chunks(store, query, k=5)
        if not chunks:
            return ToolResult(success=True, output="No relevant documents found.")

        parts = [f"Found **{len(chunks)}** relevant documents:\n"]
        for idx, chunk in enumerate(chunks[:5], 1):
            text = chunk.get("text", "")[:200]
            source = chunk.get("source", "unknown")
            parts.append(f"**{idx}.** [{source}] {text}...")

        return ToolResult(success=True, output="\n".join(parts))
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"KB search failed: {exc}")


def _tool_update_saved_search(
    name: str,
    search: str = None,
    description: str = None,
    cron_schedule: str = None,
    app: str = "search",
) -> ToolResult:
    """Update an existing saved search in Splunk."""
    try:
        from chat_app.splunk_client import SplunkClient

        splunk_client = SplunkClient()
        kwargs = {}
        if search is not None:
            kwargs["search"] = search
        if description is not None:
            kwargs["description"] = description
        if cron_schedule is not None:
            kwargs["cron_schedule"] = cron_schedule

        if not kwargs:
            return ToolResult(
                success=False, output="",
                error="No fields to update. Provide search, description, or cron_schedule.",
            )

        result = splunk_client.update_saved_search(name, app=app, **kwargs)
        changed = ", ".join(result["fields_changed"])
        output = (
            f"**Updated saved search `{name}`** (app={app})\n"
            f"Fields changed: {changed}\n"
        )
        if "search" in result["fields_changed"]:
            output += f"\nPrevious query:\n```spl\n{result['previous']['search']}\n```\n"
            output += f"\nNew query:\n```spl\n{result['updated']['search']}\n```"

        return ToolResult(success=True, output=output, data=result)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Update failed: {exc}")


def _tool_create_knowledge_object(
    object_type: str, name: str, definition: str, app: str = "search"
) -> ToolResult:
    """Create a Splunk knowledge object."""
    try:
        from chat_app.splunk_client import SplunkClient

        splunk_client = SplunkClient()
        result = splunk_client.create_knowledge_object(object_type, name, definition, app=app)
        output = (
            f"**Created {result['type']} `{name}`** (app={app})\n"
            f"Definition: `{definition[:200]}`"
        )
        return ToolResult(success=True, output=output, data=result)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Creation failed: {exc}")


def _tool_list_indexes() -> ToolResult:
    """List all Splunk indexes."""
    try:
        from chat_app.splunk_client import SplunkClient
        splunk_client = SplunkClient()
        indexes = splunk_client.list_indexes()
        if not indexes:
            return ToolResult(success=True, output="No indexes found.")

        parts = [f"Found **{len(indexes)}** indexes:\n"]
        for idx in sorted(indexes, key=lambda item: int(item.get("current_db_size_mb", 0)), reverse=True):
            disabled = " (disabled)" if idx.get("disabled") == "1" else ""
            parts.append(
                f"- **{idx['name']}** — {idx.get('total_event_count', 0)} events, "
                f"{idx.get('current_db_size_mb', 0)} MB, "
                f"type={idx.get('datatype', 'event')}{disabled}"
            )
        return ToolResult(success=True, output="\n".join(parts), data={"indexes": indexes})
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Failed to list indexes: {exc}")


def _tool_list_inputs(kind: str = "all") -> ToolResult:
    """List Splunk data inputs."""
    try:
        from chat_app.splunk_client import SplunkClient
        splunk_client = SplunkClient()
        inputs = splunk_client.list_inputs(kind=kind)
        if not inputs:
            return ToolResult(success=True, output=f"No data inputs found (kind={kind}).")

        parts = [f"Found **{len(inputs)}** data inputs:\n"]
        for inp in inputs:
            disabled = " (disabled)" if inp.get("disabled") == "1" else ""
            parts.append(
                f"- [{inp['type']}] **{inp['name']}** → index={inp.get('index', 'default')}, "
                f"sourcetype={inp.get('sourcetype', 'N/A')}{disabled}"
            )
        return ToolResult(success=True, output="\n".join(parts), data={"inputs": inputs})
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Failed to list inputs: {exc}")


def _tool_list_apps() -> ToolResult:
    """List installed Splunk apps."""
    try:
        from chat_app.splunk_client import SplunkClient
        splunk_client = SplunkClient()
        apps = splunk_client.list_apps()
        if not apps:
            return ToolResult(success=True, output="No apps found.")

        parts = [f"Found **{len(apps)}** installed apps:\n"]
        for app in apps:
            disabled = " (disabled)" if app.get("disabled") == "1" else ""
            visible = "" if app.get("visible") == "true" else " [hidden]"
            parts.append(
                f"- **{app.get('label', app['name'])}** v{app.get('version', '?')}{disabled}{visible}"
            )
        return ToolResult(success=True, output="\n".join(parts), data={"apps": apps})
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Failed to list apps: {exc}")


def _tool_list_users() -> ToolResult:
    """List Splunk users."""
    try:
        from chat_app.splunk_client import SplunkClient
        splunk_client = SplunkClient()
        users = splunk_client.list_users()
        if not users:
            return ToolResult(success=True, output="No users found.")

        parts = [f"Found **{len(users)}** users:\n"]
        for user in users:
            roles = ", ".join(user.get("roles", []))
            parts.append(f"- **{user['name']}** — roles: {roles}")
        return ToolResult(success=True, output="\n".join(parts), data={"users": users})
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Failed to list users: {exc}")


def _tool_get_server_info() -> ToolResult:
    """Get Splunk server info."""
    try:
        from chat_app.splunk_client import SplunkClient
        splunk_client = SplunkClient()
        info = splunk_client.get_server_info()

        roles = ", ".join(info.get("server_roles", []))
        output = (
            f"**Splunk Server Info**\n"
            f"- Server: {info.get('server_name', 'N/A')}\n"
            f"- Version: {info.get('version', 'N/A')} (build {info.get('build', 'N/A')})\n"
            f"- OS: {info.get('os_name', 'N/A')} {info.get('os_version', '')}\n"
            f"- CPU: {info.get('cpu_arch', 'N/A')}\n"
            f"- License: {info.get('license_state', 'N/A')}\n"
            f"- Mode: {info.get('mode', 'N/A')}\n"
            f"- Roles: {roles or 'none'}"
        )
        return ToolResult(success=True, output=output, data=info)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Failed to get server info: {exc}")


def _tool_list_deployment_clients() -> ToolResult:
    """List deployment server clients."""
    try:
        from chat_app.splunk_client import SplunkClient
        splunk_client = SplunkClient()
        clients = splunk_client.list_deployment_clients()
        if not clients:
            return ToolResult(
                success=True,
                output="No deployment clients found (deployment server may not be enabled).",
            )

        parts = [f"Found **{len(clients)}** deployment clients:\n"]
        for client in clients[:50]:
            parts.append(
                f"- **{client.get('clientName', client.get('hostname', 'N/A'))}** — "
                f"IP={client.get('ip', 'N/A')}, "
                f"version={client.get('splunkVersion', 'N/A')}, "
                f"last phone home={client.get('lastPhoneHomeTime', 'N/A')}"
            )
        return ToolResult(success=True, output="\n".join(parts), data={"clients": clients})
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Failed to list deployment clients: {exc}")


def _tool_search_index_stats() -> ToolResult:
    """Get per-index ingestion stats."""
    try:
        from chat_app.splunk_client import SplunkClient
        splunk_client = SplunkClient()
        stats = splunk_client.get_index_stats()
        if not stats:
            return ToolResult(success=True, output="No index statistics available.")

        parts = ["**Index Statistics:**\n"]
        parts.append("| Index | Size (MB) | Events | Type | Disabled |")
        parts.append("| --- | --- | --- | --- | --- |")
        for stat in sorted(stats, key=lambda item: float(item.get("currentDBSizeMB", 0)), reverse=True):
            parts.append(
                f"| {stat.get('title', 'N/A')} | {stat.get('currentDBSizeMB', 0)} | "
                f"{stat.get('totalEventCount', 0)} | {stat.get('datatype', 'event')} | "
                f"{stat.get('disabled', '0')} |"
            )
        return ToolResult(success=True, output="\n".join(parts), data={"stats": stats})
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Failed to get index stats: {exc}")


def _tool_list_lookups() -> ToolResult:
    """List Splunk lookup definitions."""
    try:
        from chat_app.splunk_client import SplunkClient
        splunk_client = SplunkClient()
        lookups = splunk_client.list_lookups()
        if not lookups:
            return ToolResult(success=True, output="No lookup definitions found.")

        parts = [f"Found **{len(lookups)}** lookup definitions:\n"]
        for lookup in lookups:
            disabled = " (disabled)" if lookup.get("disabled") else ""
            parts.append(
                f"- **{lookup['name']}** — type={lookup.get('type', 'file')}, "
                f"file={lookup.get('filename', 'N/A')}, app={lookup.get('app', 'N/A')}{disabled}"
            )
        return ToolResult(success=True, output="\n".join(parts), data={"lookups": lookups})
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Failed to list lookups: {exc}")


def _tool_list_macros() -> ToolResult:
    """List Splunk search macros."""
    try:
        from chat_app.splunk_client import SplunkClient
        splunk_client = SplunkClient()
        macros = splunk_client.list_macros()
        if not macros:
            return ToolResult(success=True, output="No search macros found.")

        parts = [f"Found **{len(macros)}** search macros:\n"]
        for macro in macros:
            definition = macro.get("definition", "")[:80]
            parts.append(
                f"- **{macro['name']}** — `{definition}`"
                + (f" (args: {macro['args']})" if macro.get("args") else "")
            )
        return ToolResult(success=True, output="\n".join(parts), data={"macros": macros})
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Failed to list macros: {exc}")


def _tool_get_license_usage() -> ToolResult:
    """Get Splunk license usage."""
    try:
        from chat_app.splunk_client import SplunkClient
        splunk_client = SplunkClient()
        usage = splunk_client.get_license_usage()
        if not usage:
            return ToolResult(success=True, output="License usage data not available.")

        output = (
            f"**Splunk License Usage**\n"
            f"- Quota: {usage.get('quota_gb', 'N/A')} GB/day\n"
            f"- Used: {usage.get('used_gb', 'N/A')} GB ({usage.get('usage_percent', 0)}%)\n"
            f"- Remaining: {round(usage.get('quota_gb', 0) - usage.get('used_gb', 0), 2)} GB"
        )
        return ToolResult(success=True, output=output, data=usage)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return ToolResult(success=False, output="", error=f"Failed to get license usage: {exc}")

