"""Skill handlers — SPL analysis, search, health, config, deployment, etc.

Extracted from skill_executor.py (batches 1-3) for modularity.
Each handler follows: def handler(user_input: str = "", **kwargs) -> str

Exports HANDLERS dict for auto-registration.
"""
import asyncio
import logging
import os

logger = logging.getLogger(__name__)


def _run_async(coro):
    """Run an async coroutine from sync context, safely handling running event loops."""
    import concurrent.futures
    try:
        asyncio.get_running_loop()
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result(timeout=30)
    except RuntimeError:
        return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Batch 1: Real-execution handlers
# ---------------------------------------------------------------------------

def _handler_explain_spl(user_input: str = "", spl: str = "", **kwargs) -> str:
    """Explain an SPL query step by step."""
    import re
    query = spl or user_input
    if not query:
        return "No SPL query provided to explain."

    pipes = [p.strip() for p in re.split(r'\|', query) if p.strip()]
    if not pipes:
        return "Could not parse SPL query."

    explanation = ["**SPL Query Breakdown:**\n"]
    for i, pipe in enumerate(pipes):
        cmd = pipe.split()[0] if pipe.split() else "unknown"
        if i == 0:
            explanation.append(f"**Step {i+1} (Base search):** `{pipe[:200]}`")
            explanation.append("  This is the initial search that retrieves events from the index.\n")
        else:
            explanation.append(f"**Step {i+1} ({cmd}):** `{pipe[:200]}`")
            explanation.append(f"  The `{cmd}` command processes results from the previous step.\n")
    explanation.append(f"\n*Total pipeline stages: {len(pipes)}*")

    kg_context = kwargs.get("kg_context", "")
    if kg_context:
        explanation.append(f"\n**Knowledge Graph Context:**\n{kg_context}")

    return "\n".join(explanation)


def _handler_annotate_spl(user_input: str = "", spl: str = "", **kwargs) -> str:
    """Annotate SPL with inline comments."""
    import re
    query = spl or user_input
    if not query:
        return "No SPL query provided."

    pipes = [p.strip() for p in re.split(r'\|', query) if p.strip()]
    annotated = []
    for i, pipe in enumerate(pipes):
        cmd = pipe.split()[0] if pipe.split() else "?"
        comment = {
            "search": "base search filter",
            "where": "filter results with eval expressions",
            "eval": "compute new fields or modify existing",
            "stats": "aggregate/summarize results",
            "eventstats": "aggregate without removing events",
            "streamstats": "running aggregate over streaming events",
            "table": "select and display specific fields",
            "sort": "order results by field values",
            "head": "limit to first N results",
            "tail": "limit to last N results",
            "dedup": "remove duplicate events",
            "rename": "rename fields",
            "fields": "include/exclude fields",
            "timechart": "time-series chart aggregation",
            "chart": "chart aggregation by split fields",
            "top": "most common values",
            "rare": "least common values",
            "rex": "regex field extraction",
            "lookup": "enrich with lookup table data",
            "tstats": "fast aggregation on indexed fields",
            "join": "join with subsearch results",
            "transaction": "group events into transactions",
            "fillnull": "replace null values",
            "convert": "convert field data types",
            "bin": "bucket numeric/time values",
        }.get(cmd, "process data")

        prefix = "" if i == 0 else "| "
        annotated.append(f"{prefix}{pipe}  ```{cmd}: {comment}```")

    return "```spl\n" + "\n".join(annotated) + "\n```"


def _handler_summarize(user_input: str = "", text: str = "", **kwargs) -> str:
    """Summarize text content concisely."""
    content = text or user_input
    if not content:
        return "No content to summarize."

    sentences = [s.strip() for s in content.replace('\n', '. ').split('.') if s.strip()]
    if len(sentences) <= 3:
        return content

    key_sentences = [sentences[0]]
    if len(sentences) > 2:
        middle = sentences[1:-1]
        middle.sort(key=len, reverse=True)
        key_sentences.append(middle[0])
    key_sentences.append(sentences[-1])
    return ". ".join(key_sentences) + "."


def _handler_conf_parser(user_input: str = "", filepath: str = "", **kwargs) -> str:
    """Parse a .conf file and return structured output."""
    import re
    from pathlib import Path

    if filepath:
        resolved = Path(filepath).resolve()
        _allowed = [Path("/app/shared/public/documents").resolve(),
                    Path("/app/data").resolve(),
                    Path("/app/ingest_specs").resolve()]
        if not any(str(resolved).startswith(str(r)) for r in _allowed):
            return "Error: File path not allowed. Only files in documents/data directories are accessible."
        if resolved.exists():
            content = resolved.read_text(encoding="utf-8", errors="ignore")
        else:
            content = user_input
    else:
        content = user_input

    if not content:
        return "No configuration content to parse."

    stanzas = re.findall(r'\[([^\]]+)\]\s*\n((?:[^[\n].*\n)*)', content)
    if not stanzas:
        return "No stanzas found in the configuration."

    result = [f"**Parsed {len(stanzas)} stanza(s):**\n"]
    for name, body in stanzas[:20]:
        settings = []
        for line in body.strip().split('\n'):
            kv = re.match(r'(\S+)\s*=\s*(.*)', line.strip())
            if kv:
                settings.append(f"  - `{kv.group(1)}` = `{kv.group(2).strip()[:100]}`")
        result.append(f"**[{name}]** ({len(settings)} settings)")
        result.extend(settings[:10])
        result.append("")
    return "\n".join(result)


def _handler_health_monitor(user_input: str = "", **kwargs) -> str:
    """Check system health status."""
    try:
        from chat_app.health_monitor import (
            check_postgres, check_ollama, check_chromadb, check_redis
        )

        async def _check():
            results = {}
            try:
                from chat_app.settings import get_settings
                s = get_settings()
                engine = None
                if hasattr(s, 'database') and hasattr(s.database, 'url') and s.database.url:
                    from sqlalchemy.ext.asyncio import create_async_engine
                    url = s.database.url.replace("postgresql://", "postgresql+asyncpg://")
                    engine = create_async_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=5)
                if engine:
                    h = await check_postgres(engine)
                    results["PostgreSQL"] = f"{'OK' if h.status == 'healthy' else h.status.upper()} ({h.latency_ms:.0f}ms)"
                    await engine.dispose()
                else:
                    results["PostgreSQL"] = "SKIP (no DB URL)"
            except Exception as e:
                results["PostgreSQL"] = f"ERROR: {e}"
            for name, checker in [
                ("Ollama", check_ollama),
                ("ChromaDB", check_chromadb),
                ("Redis", check_redis),
            ]:
                try:
                    h = await checker()
                    results[name] = f"{'OK' if h.status == 'healthy' else h.status.upper()} ({h.latency_ms:.0f}ms)"
                except Exception as e:
                    results[name] = f"ERROR: {e}"
            return results

        results = _run_async(_check())

        lines = ["**System Health Check:**\n"]
        for svc, status in results.items():
            lines.append(f"- **{svc}**: {status}")
        return "\n".join(lines)
    except Exception as e:
        return f"Health check failed: {e}"


def _handler_search_knowledge(user_input: str = "", query: str = "", k: int = 5, **kwargs) -> str:
    """Search the knowledge base across all collections."""
    search_query = query or user_input
    if not search_query:
        return "No search query provided."

    try:
        from chat_app.vectorstore import search_similar_chunks_parallel

        async def _search():
            return await search_similar_chunks_parallel(search_query, n_results=k)

        results = _run_async(_search())

        if not results:
            return "No relevant results found in the knowledge base."

        lines = [f"**Found {len(results)} relevant results:**\n"]
        for i, r in enumerate(results[:k], 1):
            text = r.get("text", "")[:200]
            source = r.get("source", "unknown")
            collection = r.get("collection", "")
            score = r.get("score", 0)
            lines.append(f"**{i}.** [{collection}] (score: {score:.2f}) `{source}`")
            lines.append(f"   {text}...\n")

        kg_context = kwargs.get("kg_context", "")
        if kg_context:
            lines.append(f"\n**Knowledge Graph Context:**\n{kg_context}")

        return "\n".join(lines)
    except Exception as e:
        return f"Knowledge base search failed: {e}"


def _handler_general_qa(user_input: str = "", **kwargs) -> str:
    """General Q&A — search knowledge base and provide contextual answer."""
    if not user_input:
        return "No question provided."

    context = _handler_search_knowledge(user_input=user_input, k=3, **kwargs)

    kg_context = kwargs.get("kg_context", "")
    if kg_context:
        return f"Based on knowledge base search:\n\n{context}\n\n**Structural Context:**\n{kg_context}"
    return f"Based on knowledge base search:\n\n{context}"


def _handler_create_alert(user_input: str = "", alert_name: str = "", spl: str = "",
                          cron: str = "*/5 * * * *", **kwargs) -> str:
    """Generate a Splunk alert/saved search configuration."""
    name = alert_name or "custom_alert"
    search = spl or user_input

    if not search:
        return "No SPL query provided for the alert."

    config = f"""[{name}]
search = {search}
cron_schedule = {cron}
dispatch.earliest_time = -15m
dispatch.latest_time = now
is_scheduled = 1
alert.severity = 3
alert.suppress = 1
alert.suppress.period = 1h
alert_type = number of events
alert_comparator = greater than
alert_threshold = 0
counttype = number of events
enableSched = 1
"""
    return f"**Generated savedsearches.conf entry:**\n```ini\n{config}```"


def _handler_config_generator(user_input: str = "", config_type: str = "", **kwargs) -> str:
    """Generate Splunk configuration stanzas."""
    query = user_input.lower()

    if "input" in query or "data input" in query or config_type == "inputs":
        return """**Sample inputs.conf:**
```ini
[monitor:///var/log/syslog]
disabled = false
index = os
sourcetype = syslog
# Follow log rotation
followTail = 0

[monitor:///var/log/messages]
disabled = false
index = os
sourcetype = linux_messages_syslog
```"""
    elif "props" in query or "field extraction" in query or config_type == "props":
        return """**Sample props.conf:**
```ini
[my_sourcetype]
TIME_FORMAT = %Y-%m-%d %H:%M:%S
TIME_PREFIX = timestamp=
MAX_TIMESTAMP_LOOKAHEAD = 25
SHOULD_LINEMERGE = false
LINE_BREAKER = ([\\r\\n]+)
TRANSFORMS-extract = my_field_extraction
```"""
    elif "transform" in query or config_type == "transforms":
        return """**Sample transforms.conf:**
```ini
[my_field_extraction]
REGEX = user=(?P<user>\\w+)\\s+action=(?P<action>\\w+)\\s+status=(?P<status>\\d+)
FORMAT = user::$1 action::$2 status::$3

[my_lookup]
filename = my_lookup.csv
max_matches = 1
```"""
    elif "saved" in query or "alert" in query or config_type == "savedsearches":
        return _handler_create_alert(user_input=user_input, **kwargs)
    elif "macro" in query or config_type == "macros":
        return """**Sample macros.conf:**
```ini
[my_base_search]
definition = index=main sourcetype=access_combined
iseval = 0

[my_filter(2)]
args = field, value
definition = search $field$="$value$"
iseval = 0
```"""
    else:
        result = """**Available config types:**
- `inputs.conf` — Data inputs (files, network, scripted)
- `props.conf` — Data parsing and field extraction
- `transforms.conf` — Field transformations and lookups
- `savedsearches.conf` — Saved searches and alerts
- `macros.conf` — Search macros
- `limits.conf` — System limits

Specify a config type for a detailed template."""

        kg_context = kwargs.get("kg_context", "")
        if kg_context:
            result += f"\n\n**Knowledge Graph Context:**\n{kg_context}"
        return result


def _handler_security_audit(user_input: str = "", **kwargs) -> str:
    """Run security audit: check system config + provide security queries."""
    import socket
    parts = ["**Security Audit Report:**\n"]

    try:
        from chat_app.settings import get_settings
        s = get_settings()
        auth_on = os.environ.get("ENABLE_AUTHENTICATION", "false").lower() == "true"
        ssl_on = os.environ.get("ENABLE_SSL", "false").lower() == "true"
        parts.append("**System Security Status:**")
        parts.append(f"- Authentication: {'ENABLED' if auth_on else 'DISABLED (WARNING)'}")
        parts.append(f"- SSL/TLS: {'ENABLED' if ssl_on else 'DISABLED (WARNING)'}")
        parts.append(f"- Rate limiting: {'ENABLED' if s.security.rate_limit_enabled else 'DISABLED'}" if hasattr(s.security, 'rate_limit_enabled') else "- Rate limiting: check nginx config")
        parts.append(f"- Auth secret: {'SET' if os.environ.get('CHAINLIT_AUTH_SECRET') else 'MISSING (CRITICAL)'}")
        if not auth_on:
            parts.append("\n**RECOMMENDATION:** Enable authentication for production use")
        if not ssl_on:
            parts.append("**RECOMMENDATION:** Enable SSL/TLS for encrypted communications")
    except Exception as e:
        parts.append(f"- System check failed: {e}")

    parts.append("\n**Service Exposure Check:**")
    exposed = []
    for name, port in [("PostgreSQL", 5432), ("ChromaDB", 8001), ("Redis", 6379), ("Ollama", 11430)]:
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            try:
                sock.connect(("localhost", port))
                exposed.append(f"{name} :{port}")
            finally:
                sock.close()
        except Exception as _exc:
            logger.debug("[SKILL] Optional operation failed: %s", _exc)
    parts.append(f"- Services accessible on localhost: {', '.join(exposed)}")

    parts.append("""
**Security Audit SPL Queries:**

1. **Failed Authentication:**
```spl
index=security EventCode=4625
| stats count by user, src_ip
| where count > 5
| sort -count
```

2. **Privilege Escalation:**
```spl
index=security EventCode=4672
| stats count values(Privileges) by user
| sort -count
```

3. **Unusual Login Hours:**
```spl
index=security EventCode=4624
| eval hour=strftime(_time, "%H")
| where hour < 6 OR hour > 22
| stats count by user, src_ip
```

4. **Data Exfiltration Indicators:**
```spl
| tstats sum(All_Traffic.bytes_out) from datamodel=Network_Traffic by All_Traffic.src
| sort -bytes_out | head 20
```""")

    return "\n".join(parts)


def _handler_nlp_to_spl(user_input: str = "", **kwargs) -> str:
    """Convert natural language to SPL using the template engine."""
    if not user_input:
        return "No natural language query provided."

    try:
        from shared.spl_template_engine import SPLTemplateEngine
        intent_result = SPLTemplateEngine.detect_intent(user_input)
        if intent_result and intent_result.intent_type != "unknown":
            query, explanation, _ = SPLTemplateEngine.generate_query(user_input)
            if query:
                result = f"**Generated SPL:**\n```spl\n{query}\n```"
                if explanation:
                    result += f"\n\n**Explanation:** {explanation}"
                return result
    except Exception as _exc:
        logger.debug("[SKILL] Optional operation failed: %s", _exc)

    return (
        "Could not auto-generate SPL from this query. "
        "Try rephrasing with specific SPL terms like 'stats', 'search', 'filter', etc."
    )


def _handler_cleanup(user_input: str = "", **kwargs) -> str:
    """Report on cleanup opportunities."""
    try:
        from pathlib import Path
        data_dir = Path("/app/data")
        if data_dir.exists():
            total_size = sum(f.stat().st_size for f in data_dir.rglob("*") if f.is_file())
            file_count = sum(1 for f in data_dir.rglob("*") if f.is_file())
            old_files = []
            import time as _t
            cutoff = _t.time() - 7 * 86400
            for f in data_dir.rglob("*"):
                if f.is_file() and f.stat().st_mtime < cutoff:
                    old_files.append(f.name)

            return (
                f"**Data Directory Audit:**\n"
                f"- Total files: {file_count}\n"
                f"- Total size: {total_size / 1024 / 1024:.1f} MB\n"
                f"- Files older than 7 days: {len(old_files)}\n"
                + (f"- Old files: {', '.join(old_files[:10])}" if old_files else "")
            )
        return "Data directory not found."
    except Exception as e:
        return f"Cleanup audit failed: {e}"


def _handler_deep_search(user_input: str = "", query: str = "", **kwargs) -> str:
    """Deep search across all collections with higher result count and reranking."""
    search_query = query or user_input
    if not search_query:
        return "No search query provided."

    try:
        from chat_app.vectorstore import search_similar_chunks_parallel

        async def _search():
            return await search_similar_chunks_parallel(search_query, n_results=20)

        results = _run_async(_search())

        if not results:
            return "No results found in deep search."

        seen_sources = set()
        unique_results = []
        for r in results:
            src = r.get("source", "")
            if src not in seen_sources:
                seen_sources.add(src)
                unique_results.append(r)

        lines = [f"**Deep Search: {len(unique_results)} unique results from {len(results)} total**\n"]
        for i, r in enumerate(unique_results[:15], 1):
            text = r.get("text", "")[:250]
            source = r.get("source", "unknown")
            collection = r.get("collection", "")
            score = r.get("score", 0)
            lines.append(f"**{i}.** [{collection}] (score: {score:.2f}) `{source}`")
            lines.append(f"   {text}...\n")

        kg_context = kwargs.get("kg_context", "")
        if kg_context:
            lines.append(f"\n**Knowledge Graph Context:**\n{kg_context}")

        return "\n".join(lines)
    except Exception as e:
        return f"Deep search failed: {e}"


def _handler_search_suggestion(user_input: str = "", **kwargs) -> str:
    """Suggest search improvements using rules and KG context."""
    if not user_input:
        return "No query to suggest improvements for."

    suggestions = []
    q = user_input.lower()

    if "index=*" in q:
        suggestions.append("Replace `index=*` with a specific index name")
    if "| search" in q and q.index("| search") > 0:
        suggestions.append("Move `| search` filters to the base search for better performance")
    if "| join" in q:
        suggestions.append("Consider using `lookup` instead of `join` for better performance")
    if "| regex" in q and "_raw" in q:
        suggestions.append("Move regex patterns to base search keywords instead of `| regex _raw`")
    if "earliest" not in q and "latest" not in q:
        suggestions.append("Add time bounds (earliest/latest) to limit the search scope")
    if "| stats" in q and "| tstats" not in q:
        suggestions.append("Consider using `| tstats` for indexed field aggregations (10-100x faster)")
    if not suggestions:
        suggestions.append("Query looks reasonable. Consider adding TERM() for exact token matching.")

    try:
        from chat_app.knowledge_graph import get_knowledge_graph, SPLQueryAnalyzer
        kg = get_knowledge_graph()
        if kg:
            analysis = SPLQueryAnalyzer.analyze(user_input)
            for cmd in analysis.get("commands", []):
                related = kg.query_related(cmd, rel_types=["pipes_to"], max_depth=1, max_results=3)
                if related:
                    alts = [r["entity_name"] for r in related if r["entity_name"] != cmd]
                    if alts:
                        suggestions.append(
                            f"Related commands to `{cmd}`: {', '.join(f'`{a}`' for a in alts[:3])}"
                        )
    except Exception as _exc:
        logger.debug("[SKILL] Optional operation failed: %s", _exc)

    return "**Search Optimization Suggestions:**\n" + "\n".join(f"- {s}" for s in suggestions)


def _handler_route_query(user_input: str = "", **kwargs) -> str:
    """Route a query to the best handler."""
    from chat_app.intent_classifier import IntentClassifier
    classifier = IntentClassifier()
    result = classifier.classify(user_input, len(user_input.split()))
    return (
        f"**Query Routing:**\n"
        f"- Intent: `{result.intent}`\n"
        f"- Confidence: {result.confidence:.2f}\n"
        f"- Suggested handler: `{result.intent}`"
    )


# ---------------------------------------------------------------------------
# Batch 2: Real-execution handlers
# ---------------------------------------------------------------------------

def _handler_analyze_spl(user_input: str = "", spl: str = "", **kwargs) -> str:
    """Analyze SPL query for complexity, commands used, and potential issues."""
    query = spl or user_input
    if not query:
        return "No SPL query provided to analyze."

    commands = []
    pipes = query.split("|")
    for p in pipes:
        cmd = p.strip().split()[0] if p.strip() else ""
        if cmd:
            commands.append(cmd)

    issues = []
    q = query.lower()
    if "index=*" in q:
        issues.append("Uses `index=*` — specify index for performance")
    if q.count("|") > 8:
        issues.append("Many pipe stages — consider simplifying")
    if "| join" in q:
        issues.append("`join` is resource-heavy — consider `lookup` or `stats`")
    if "| regex" in q:
        issues.append("Post-filter `regex` — move keywords to base search")
    if "| search" in q and q.index("| search") > 5:
        issues.append("Mid-pipeline `search` — move filters earlier")
    if "NOT" in query and "!" not in query:
        issues.append("Use `!=` instead of `NOT field=val` when possible")

    result = "**SPL Analysis:**\n"
    result += f"- Pipe stages: {len(pipes)}\n"
    result += f"- Commands used: {', '.join(f'`{c}`' for c in commands)}\n"
    result += f"- Estimated complexity: {'High' if len(pipes) > 6 else 'Medium' if len(pipes) > 3 else 'Low'}\n"
    if issues:
        result += "\n**Potential Issues:**\n" + "\n".join(f"- {i}" for i in issues)
    else:
        result += "\nNo obvious issues detected."
    return result


def _handler_validate_spl(user_input: str = "", spl: str = "", **kwargs) -> str:
    """Validate SPL syntax for common errors."""
    query = spl or user_input
    if not query:
        return "No SPL query provided to validate."

    errors = []
    warnings = []
    q = query.strip()

    if q.count('"') % 2 != 0:
        errors.append("Unbalanced double quotes")
    if q.count("'") % 2 != 0:
        warnings.append("Odd number of single quotes (may be intentional)")

    depth = 0
    for c in q:
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        if depth < 0:
            errors.append("Extra closing parenthesis")
            break
    if depth > 0:
        errors.append(f"Unclosed parenthesis ({depth} missing)")

    if q.count("[") != q.count("]"):
        errors.append("Unbalanced square brackets (subsearch)")

    if "| |" in q:
        errors.append("Empty pipe stage: `| |`")
    if q.endswith("|"):
        errors.append("Trailing pipe with no command")
    if "stats " in q and "by" not in q.split("stats")[1].split("|")[0]:
        warnings.append("`stats` without `by` clause — aggregates over all results")

    status = "VALID" if not errors else "ERRORS FOUND"
    result = f"**SPL Validation: {status}**\n"
    if errors:
        result += "\nErrors:\n" + "\n".join(f"- {e}" for e in errors)
    if warnings:
        result += "\nWarnings:\n" + "\n".join(f"- {w}" for w in warnings)
    if not errors and not warnings:
        result += "No syntax issues detected."
    return result


def _handler_generate_spl(user_input: str = "", **kwargs) -> str:
    """Generate SPL from natural language (extended version of nlp_to_spl)."""
    if not user_input:
        return "Describe what you want to search for."

    try:
        from shared.spl_template_engine import SPLTemplateEngine
        intent_result = SPLTemplateEngine.detect_intent(user_input)
        if intent_result and intent_result.intent_type != "unknown":
            query, explanation, _ = SPLTemplateEngine.generate_query(user_input)
            if query:
                result = f"**Generated SPL:**\n```spl\n{query}\n```"
                if explanation:
                    result += f"\n\n**Explanation:** {explanation}"
                return result
    except Exception as _exc:
        logger.debug("[SKILL] Optional operation failed: %s", _exc)

    q = user_input.lower()
    if any(w in q for w in ["error", "fail", "exception"]):
        return '**Suggested SPL:**\n```spl\nindex=main ("error" OR "fail" OR "exception")\n| stats count by source, sourcetype\n| sort -count\n```'
    if any(w in q for w in ["login", "auth", "password"]):
        return '**Suggested SPL:**\n```spl\nindex=security (login OR authentication OR password)\n| stats count by user, action, src_ip\n| sort -count\n```'
    if any(w in q for w in ["top", "most", "frequent"]):
        return '**Suggested SPL:**\n```spl\nindex=main\n| top limit=20 sourcetype\n```'
    return (
        "Could not auto-generate SPL. Try being more specific:\n"
        "- 'Show top 10 error sources in the last hour'\n"
        "- 'Find failed login attempts by user'\n"
        "- 'Count events by sourcetype over time'"
    )


def _handler_optimize_spl(user_input: str = "", spl: str = "", **kwargs) -> str:
    """Suggest SPL optimizations."""
    query = spl or user_input
    if not query:
        return "No SPL query provided to optimize."

    optimizations = []
    q = query.lower()

    if "index=*" in q:
        optimizations.append("**Specify index**: Replace `index=*` with specific index name(s)")
    if "| search" in q and q.index("| search") > 10:
        optimizations.append("**Move filters early**: Shift `| search` conditions to the base search")
    if "| join" in q:
        optimizations.append("**Replace join**: Use `| lookup` or `| stats` instead of `| join`")
    if "| regex" in q:
        optimizations.append("**Move regex to base**: Use search terms instead of `| regex`")
    if "| fields" not in q and "| table" not in q and q.count("|") > 2:
        optimizations.append("**Add `| fields`**: Limit fields early to reduce data volume")
    if "earliest" not in q and "latest" not in q:
        optimizations.append("**Add time range**: Always include `earliest=` and `latest=`")
    if "| stats" in q and "| tstats" not in q:
        optimizations.append("**Use tstats**: For indexed fields, `| tstats` is 10-100x faster")
    if "| eval" in q and q.count("| eval") > 3:
        optimizations.append("**Combine evals**: Merge multiple `| eval` into one with comma separation")
    if "| where" in q and "| search" in q:
        optimizations.append("**Pick one filter**: Use either `| where` or `| search`, not both")
    if "| sort" in q and "| head" not in q and "| tail" not in q:
        optimizations.append("**Add limit after sort**: `| sort -count | head 100` reduces memory")

    if not optimizations:
        return "**SPL looks well-optimized.** No immediate improvements detected."

    return "**Optimization Suggestions:**\n\n" + "\n\n".join(f"{i+1}. {o}" for i, o in enumerate(optimizations))


def _handler_extract(user_input: str = "", text: str = "", **kwargs) -> str:
    """Extract fields from sample text using regex patterns."""
    import re
    sample = text or user_input
    if not sample:
        return "Provide sample text to extract fields from."

    extractions = {}

    patterns = {
        "IP addresses": r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b',
        "Email addresses": r'[\w.+-]+@[\w-]+\.[\w.]+',
        "Key=Value pairs": r'(\w+)=("[^"]*"|[^\s,]+)',
        "Timestamps": r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}',
        "URLs": r'https?://[^\s<>"]+',
        "MAC addresses": r'(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}',
        "Port numbers": r'\bport[= ]+(\d+)\b',
    }

    for name, pat in patterns.items():
        matches = re.findall(pat, sample)
        if matches:
            if isinstance(matches[0], tuple):
                matches = [f"{m[0]}={m[1]}" for m in matches]
            extractions[name] = list(set(matches))[:10]

    if not extractions:
        return "No recognizable fields found in the text. Try providing structured log data."

    result = "**Extracted Fields:**\n"
    for field_name, values in extractions.items():
        result += f"\n**{field_name}:** {', '.join(f'`{v}`' for v in values)}"
    return result


def _handler_query_planner(user_input: str = "", **kwargs) -> str:
    """Plan a multi-step search strategy."""
    if not user_input:
        return "Describe your search goal to plan a strategy."

    q = user_input.lower()
    steps = []

    if any(w in q for w in ["investigate", "incident", "alert"]):
        steps = [
            "1. **Scope**: Identify time range, affected hosts, source IPs",
            "2. **Baseline**: Check normal activity for the time period",
            "3. **Search**: Run targeted searches for indicators",
            "4. **Correlate**: Join events across data sources",
            "5. **Timeline**: Build event timeline with `| transaction` or `| streamstats`",
            "6. **Report**: Summarize findings with `| stats` and `| table`",
        ]
    elif any(w in q for w in ["performance", "slow", "latency", "optimize"]):
        steps = [
            "1. **Identify**: Find the slow search or process",
            "2. **Measure**: Use `| rest /services/search/jobs` for job stats",
            "3. **Profile**: Check `dispatch.csv` or job inspector",
            "4. **Optimize**: Apply search optimization rules",
            "5. **Verify**: Re-run and compare execution time",
        ]
    elif any(w in q for w in ["dashboard", "report", "visualize"]):
        steps = [
            "1. **Define**: Identify key metrics and KPIs",
            "2. **Queries**: Write base searches for each panel",
            "3. **Layout**: Plan dashboard layout (time range, filters)",
            "4. **Build**: Create panels with chart/timechart/table",
            "5. **Schedule**: Set up scheduled report if needed",
        ]
    else:
        steps = [
            "1. **Understand**: Clarify the search objective",
            "2. **Identify sources**: Determine relevant indexes and sourcetypes",
            "3. **Base search**: Start with a broad time-bounded search",
            "4. **Filter**: Narrow down with specific field values",
            "5. **Aggregate**: Summarize with stats/chart/timechart",
            "6. **Refine**: Iterate on the query based on results",
        ]

    return "**Search Strategy Plan:**\n\n" + "\n".join(steps)


def _handler_check_system_health(user_input: str = "", **kwargs) -> str:
    """Check system health across all components."""
    return _handler_health_monitor(user_input=user_input, **kwargs)


def _handler_teach(user_input: str = "", **kwargs) -> str:
    """Teach a concept step by step."""
    if not user_input:
        return "What concept would you like to learn about?"

    q = user_input.lower()
    if "tstats" in q:
        return """**Learning: tstats Command**

`tstats` queries indexed metadata (tsidx files) for 10-100x faster results.

**Step 1 — Basic syntax:**
```spl
| tstats count WHERE index=main by sourcetype
```

**Step 2 — With data models:**
```spl
| tstats count from datamodel=Network_Traffic by All_Traffic.src
```

**Step 3 — Time-based:**
```spl
| tstats count WHERE index=main by _time span=1h
```

**Key rules:**
- Only works with indexed fields
- Must use `WHERE` (not `search`)
- Uses `from datamodel=X` for accelerated models
- Fields use `datamodel_name.field_name` format"""

    if "eval" in q:
        return """**Learning: eval Command**

`eval` creates calculated fields in your results.

**Step 1 — Basic calculation:**
```spl
| eval duration = end_time - start_time
```

**Step 2 — Conditional logic:**
```spl
| eval status = if(code >= 400, "error", "ok")
| eval severity = case(code>=500, "critical", code>=400, "warning", 1=1, "info")
```

**Step 3 — String functions:**
```spl
| eval domain = lower(split(email, "@", 2))
| eval short_msg = substr(message, 1, 50)
```

**Key functions:** `if()`, `case()`, `coalesce()`, `mvappend()`, `tonumber()`, `tostring()`, `now()`, `relative_time()`"""

    return _handler_search_knowledge(user_input=f"explain {user_input}", k=5)


def _handler_transform(user_input: str = "", **kwargs) -> str:
    """Generate SPL for data transformations."""
    if not user_input:
        return "Describe the data transformation you need."

    q = user_input.lower()
    if any(w in q for w in ["json", "spath", "parse"]):
        return """**JSON Data Transformation:**
```spl
| spath input=_raw
| spath input=_raw path=data.items{} output=items
| mvexpand items
| spath input=items
```"""
    if any(w in q for w in ["csv", "split", "delimit"]):
        return """**CSV/Delimited Transformation:**
```spl
| makemv delim="," field_name
| mvexpand field_name
| rex field=field_name "(?<key>[^=]+)=(?<value>.*)"
```"""
    if any(w in q for w in ["rename", "field"]):
        return """**Field Renaming:**
```spl
| rename old_field AS new_field, "Source IP" AS src_ip
| fieldformat bytes = tostring(bytes, "commas")
```"""
    return """**Common Transformations:**
- Parse JSON: `| spath`
- Split multivalue: `| makemv delim="," field`
- Extract regex: `| rex field=_raw "(?<name>pattern)"`
- Rename: `| rename old AS new`
- Calculate: `| eval new_field = expression`
- Format: `| fieldformat field = tostring(val, "commas")`"""


def _handler_aggregate(user_input: str = "", **kwargs) -> str:
    """Generate SPL for data aggregation."""
    return """**Aggregation Functions Reference:**

| Function | Example | Description |
|----------|---------|-------------|
| `count` | `stats count by src_ip` | Count events |
| `dc` | `stats dc(user) by dept` | Distinct count |
| `values` | `stats values(action) by user` | List unique values |
| `sum` | `stats sum(bytes) by host` | Sum numeric field |
| `avg` | `stats avg(duration) by service` | Average |
| `max/min` | `stats max(cpu) by host` | Max/min |
| `perc95` | `stats perc95(response_time)` | 95th percentile |
| `list` | `stats list(event) by session` | All values (ordered) |
| `earliest/latest` | `stats earliest(_time) by user` | First/last time |

**Over time:** Replace `stats` with `timechart span=1h` for time-series.
**Running totals:** Use `streamstats` for row-by-row aggregation."""


def _handler_filter(user_input: str = "", **kwargs) -> str:
    """Generate SPL filtering patterns."""
    return """**SPL Filtering Patterns:**

**Base search (fastest):**
```spl
index=main sourcetype=access_combined status>=400
```

**where clause (post-filter):**
```spl
| where len(user) > 0 AND cidrmatch("10.0.0.0/8", src_ip)
```

**search command (mid-pipeline):**
```spl
| search NOT [| inputlookup whitelist.csv | fields src_ip]
```

**regex (pattern match):**
```spl
| regex _raw="(?i)error|fail|exception"
```

**dedup (unique only):**
```spl
| dedup user, src_ip sortby -_time
```

**Performance tip:** Filter as early as possible. Base search > where > search > regex."""


def _handler_audit(user_input: str = "", **kwargs) -> str:
    """Generate audit trail queries."""
    return """**Splunk Audit Trail Queries:**

**Configuration Changes:**
```spl
index=_audit action=edit
| table _time, user, action, object, info
```

**Search Activity:**
```spl
index=_audit action=search
| stats count avg(total_run_time) by user
| sort -count
```

**Login/Access:**
```spl
index=_audit action=login
| stats count values(info) by user, clientip
```

**Knowledge Object Changes:**
```spl
index=_audit (action=create OR action=edit OR action=delete)
| stats count by user, action, object_type
```

**User Activity Summary:**
```spl
index=_audit
| stats dc(action) as actions, count as events, latest(_time) as last_seen by user
| sort -events
```"""


def _handler_analyze_metrics(user_input: str = "", **kwargs) -> str:
    """Analyze system metrics and performance."""
    try:
        with open("/proc/loadavg") as f:
            load = f.read().strip().split()
        with open("/proc/meminfo") as f:
            mem_lines = f.readlines()[:3]

        mem_info = {}
        for line in mem_lines:
            parts = line.split()
            mem_info[parts[0].rstrip(":")] = int(parts[1]) // 1024  # MB

        total = mem_info.get("MemTotal", 0)
        mem_info.get("MemFree", 0)
        avail = mem_info.get("MemAvailable", 0)
        used = total - avail

        result = f"""**System Metrics:**
- Load average: {load[0]} (1m), {load[1]} (5m), {load[2]} (15m)
- Memory: {used}MB used / {total}MB total ({used*100//total}% utilized)
- Available: {avail}MB
"""
        statvfs = os.statvfs("/app")
        disk_total = statvfs.f_blocks * statvfs.f_frsize // (1024 * 1024)
        disk_free = statvfs.f_bfree * statvfs.f_frsize // (1024 * 1024)
        result += f"- Disk: {disk_total - disk_free}MB used / {disk_total}MB total ({(disk_total - disk_free)*100//disk_total}% utilized)\n"

        if used * 100 // total > 90:
            result += "\n**WARNING:** Memory usage above 90%"
        if float(load[0]) > os.cpu_count():
            result += f"\n**WARNING:** Load average exceeds CPU count ({os.cpu_count()})"

        try:
            from chat_app.health_monitor import get_internal_metrics
            metrics = get_internal_metrics().get_all()
            counters = metrics.get("counters", {})
            active = {k: v for k, v in counters.items() if v > 0}
            if active:
                result += "\n**Application Counters:**\n"
                for k, v in active.items():
                    result += f"- {k}: {v}\n"
            gauges = metrics.get("gauges", {})
            if gauges.get("avg_response_latency_ms", 0) > 0:
                result += "\n**Performance:**\n"
                result += f"- Avg response latency: {gauges['avg_response_latency_ms']:.0f}ms\n"
                result += f"- Latency P50: {metrics.get('latency_p50', 0):.0f}ms\n"
                result += f"- Latency P95: {metrics.get('latency_p95', 0):.0f}ms\n"
                if gauges.get("avg_quality_score", 0) > 0:
                    result += f"- Avg quality: {gauges['avg_quality_score']:.2f}\n"
        except Exception as _exc:
            logger.debug("[SKILL] Optional operation failed: %s", _exc)

        return result
    except Exception as e:
        return f"Could not collect metrics: {e}"


def _handler_compare(user_input: str = "", **kwargs) -> str:
    """Compare Splunk configurations or commands."""
    if not user_input:
        return "Specify what to compare (e.g., 'stats vs eventstats', 'join vs lookup')."

    q = user_input.lower()
    if "stats" in q and "eventstats" in q:
        return """**stats vs eventstats:**

| Feature | stats | eventstats |
|---------|-------|------------|
| Output | Aggregated rows only | Original rows + aggregated fields |
| Row count | Reduced | Same as input |
| Use case | Summary tables | Enriching events with stats |

```spl
# stats: returns 1 row per group
| stats avg(bytes) as avg_bytes by src_ip

# eventstats: adds avg_bytes to EVERY event
| eventstats avg(bytes) as avg_bytes by src_ip
| where bytes > avg_bytes * 2
```"""

    if "join" in q and "lookup" in q:
        return """**join vs lookup:**

| Feature | join | lookup |
|---------|------|--------|
| Performance | Slow (memory-heavy) | Fast (disk-based) |
| Max rows | 50,000 default | Unlimited |
| Data source | Search results | CSV/KV store |
| Use case | Correlate searches | Enrich with reference data |

**Prefer lookup** when possible. Use join only for search-to-search correlation."""

    if "where" in q and "search" in q:
        return """**where vs search:**

| Feature | where | search |
|---------|-------|--------|
| Syntax | Expressions | Search language |
| Functions | Yes (len, cidrmatch) | No |
| Field types | Type-aware | String comparison |
| Performance | Same (post-filter) | Same (post-filter) |

```spl
| where status >= 400 AND len(user) > 0     # Expression syntax
| search status>=400 user=*                  # Search syntax
```"""

    return _handler_search_knowledge(user_input=f"compare {user_input}", k=5)


HANDLERS = {
    # Batch 1
    "explain_spl": _handler_explain_spl,
    "annotate_spl": _handler_annotate_spl,
    "summarize": _handler_summarize,
    "conf_parser": _handler_conf_parser,
    "health_monitor": _handler_health_monitor,
    "monitor_health": _handler_health_monitor,
    "search_knowledge": _handler_search_knowledge,
    "search_knowledge_base": _handler_search_knowledge,
    "general_qa": _handler_general_qa,
    "create_alert": _handler_create_alert,
    "config_generator": _handler_config_generator,
    "security_audit": _handler_security_audit,
    "nlp_to_spl": _handler_nlp_to_spl,
    "cleanup": _handler_cleanup,
    "deep_search": _handler_deep_search,
    "search_suggestion": _handler_search_suggestion,
    "route_query": _handler_route_query,
    # Batch 2
    "analyze_spl": _handler_analyze_spl,
    "validate_spl": _handler_validate_spl,
    "generate_spl": _handler_generate_spl,
    "optimize_spl": _handler_optimize_spl,
    "extract": _handler_extract,
    "query_planner": _handler_query_planner,
    "check_system_health": _handler_check_system_health,
    "teach": _handler_teach,
    "transform": _handler_transform,
    "aggregate": _handler_aggregate,
    "filter": _handler_filter,
    "audit": _handler_audit,
    "analyze_metrics": _handler_analyze_metrics,
    "compare": _handler_compare,
    # Batch 3
}
