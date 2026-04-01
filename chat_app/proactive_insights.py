"""
Proactive Insights Engine — Don't wait to be asked.

Provides proactive recommendations and insights:
1. Query Optimization Suggestions (analyze saved searches for performance issues)
2. Knowledge Gap Alerts (flag topics with consistently poor results)
3. Environment Health Recommendations (based on Splunk/Cribl status)
4. SPL Explain Mode (reverse-direction: SPL → plain language)
5. Runbook Correlation (match errors to organizational runbooks)
6. Incident Pattern Detection (correlate related failures)
"""
import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class Insight:
    """A proactive insight or recommendation."""
    category: str  # optimization, gap, health, pattern, runbook
    severity: str  # info, suggestion, warning, critical
    title: str
    description: str
    action_label: Optional[str] = None
    action_payload: Optional[str] = None  # e.g., an SPL query to try
    confidence: float = 0.7


@dataclass
class SPLExplanation:
    """Plain-language explanation of an SPL query."""
    original_spl: str
    summary: str = ""
    steps: List[str] = field(default_factory=list)
    performance_notes: List[str] = field(default_factory=list)
    complexity: str = "moderate"  # simple, moderate, complex


# ---------------------------------------------------------------------------
# SPL Explain Mode
# ---------------------------------------------------------------------------

def explain_spl(spl_query: str) -> SPLExplanation:
    """
    Explain an SPL query in plain language.

    Breaks down the query into steps, explains each command,
    and provides performance notes.
    """
    explanation = SPLExplanation(original_spl=spl_query)
    commands = _parse_spl_pipeline(spl_query)

    if not commands:
        explanation.summary = "This doesn't appear to be a valid SPL query."
        return explanation

    steps = []
    perf_notes = []
    complexity_score = 0

    for i, (cmd, args) in enumerate(commands):
        step = _explain_command(cmd, args, i == 0)
        if step:
            steps.append(step)

        # Performance analysis
        perf = _analyze_command_performance(cmd, args, i, commands)
        if perf:
            perf_notes.extend(perf)

        # Complexity scoring
        if cmd in ('tstats', 'datamodel', 'pivot', 'map', 'appendpipe', 'multisearch'):
            complexity_score += 2
        elif cmd in ('stats', 'eventstats', 'streamstats', 'join', 'transaction'):
            complexity_score += 1

    explanation.steps = steps
    explanation.performance_notes = perf_notes

    if complexity_score >= 5:
        explanation.complexity = "complex"
    elif complexity_score <= 1:
        explanation.complexity = "simple"

    # Generate summary
    first_cmd = commands[0][0] if commands else ""
    last_cmd = commands[-1][0] if commands else ""
    explanation.summary = (
        f"This SPL query with {len(commands)} command(s) "
        f"{'starts by searching' if first_cmd in ('search', 'index') else f'starts with {first_cmd}'} "
        f"and {'presents results as a table' if last_cmd == 'table' else f'ends with {last_cmd}'}. "
        f"Complexity: {explanation.complexity}."
    )

    return explanation


def _parse_spl_pipeline(spl: str) -> List[tuple]:
    """Parse SPL into a list of (command, args) tuples."""
    # Split on pipe, handling quoted strings
    parts = re.split(r'\s*\|\s*', spl.strip())
    commands = []

    for part in parts:
        part = part.strip()
        if not part:
            continue
        # First word is the command (or implicit 'search')
        match = re.match(r'(\w+)\s*(.*)', part, re.DOTALL)
        if match:
            cmd = match.group(1).lower()
            args = match.group(2).strip()
            commands.append((cmd, args))
        else:
            commands.append(("search", part))

    return commands


_COMMAND_EXPLANATIONS = {
    "search": "Search for events matching: {args}",
    "index": "Search in index: {args}",
    "stats": "Calculate statistics: {args}",
    "eval": "Compute a new field: {args}",
    "where": "Filter results where: {args}",
    "table": "Display columns: {args}",
    "fields": "Keep/remove fields: {args}",
    "sort": "Sort results by: {args}",
    "head": "Keep the first {args} results",
    "tail": "Keep the last {args} results",
    "dedup": "Remove duplicate values of: {args}",
    "rename": "Rename fields: {args}",
    "rex": "Extract fields using regex: {args}",
    "spath": "Extract fields from JSON/XML: {args}",
    "timechart": "Create a time-series chart: {args}",
    "chart": "Create a chart: {args}",
    "top": "Find the most common values of: {args}",
    "rare": "Find the least common values of: {args}",
    "tstats": "Fast indexed-field aggregation: {args}",
    "lookup": "Enrich with lookup data: {args}",
    "join": "Join with another dataset: {args}",
    "transaction": "Group events into transactions: {args}",
    "eventstats": "Add statistics as new fields: {args}",
    "streamstats": "Running/cumulative statistics: {args}",
    "fillnull": "Replace null values: {args}",
    "replace": "Replace values: {args}",
    "convert": "Convert field types: {args}",
    "bin": "Bucket numeric values: {args}",
    "makemv": "Split a field into multiple values: {args}",
    "mvexpand": "Expand multivalue field into rows: {args}",
    "append": "Append results from a subsearch",
    "appendcols": "Append columns from a subsearch",
    "collect": "Write results to a summary index: {args}",
    "outputlookup": "Write results to a lookup file: {args}",
    "inputlookup": "Read from a lookup file: {args}",
    "multisearch": "Run multiple searches in parallel",
    "map": "Run a search for each result",
    "foreach": "Apply operation to multiple fields: {args}",
    "predict": "Forecast future values: {args}",
    "anomalydetection": "Detect anomalies: {args}",
    "cluster": "Cluster similar events",
    "geostats": "Calculate geographic statistics: {args}",
    "iplocation": "Resolve IP to geographic location: {args}",
    "datamodel": "Search a data model: {args}",
    "pivot": "Create a pivot table: {args}",
    "mstats": "Search metric store: {args}",
    "mcatalog": "Explore metric catalog: {args}",
    "regex": "Filter with regex: {args}",
    "format": "Format subsearch results",
    "return": "Return values from subsearch: {args}",
    "abstract": "Summarize events",
    "addinfo": "Add search metadata fields",
    "addtotals": "Add row/column totals: {args}",
    "trendline": "Calculate moving averages: {args}",
    "untable": "Convert columns to rows: {args}",
    "xyseries": "Convert rows to columns: {args}",
    "transpose": "Swap rows and columns",
}


def _explain_command(cmd: str, args: str, is_first: bool) -> str:
    """Explain a single SPL command in plain language."""
    # Handle implicit search (first command without explicit 'search')
    if is_first and cmd not in _COMMAND_EXPLANATIONS and ('=' in cmd + args or '*' in cmd + args):
        return f"Search for events where {cmd} {args}".strip()

    template = _COMMAND_EXPLANATIONS.get(cmd, f"Run the '{cmd}' command: {{args}}")
    step = template.format(args=args if args else "(default)")
    return f"Step: {step}"


def _analyze_command_performance(cmd: str, args: str, position: int, all_commands: list) -> List[str]:
    """Analyze performance implications of a command."""
    notes = []

    # stats before filtering
    if cmd == "stats" and position == 0:
        notes.append("Performance: Running stats on raw events — consider filtering first with 'where' or time range")

    # join vs stats
    if cmd == "join":
        notes.append("Performance: 'join' is resource-intensive — consider using 'stats' or 'lookup' instead")

    # sort before stats
    if cmd == "sort" and position < len(all_commands) - 1:
        next_cmd = all_commands[position + 1][0]
        if next_cmd in ("stats", "chart", "timechart"):
            notes.append(f"Performance: 'sort' before '{next_cmd}' is unnecessary — {next_cmd} handles its own ordering")

    # stats instead of tstats
    if cmd == "stats" and any("index=" in a for _, a in all_commands[:1]):
        notes.append("Performance: Consider using 'tstats' for indexed-field aggregations (10-100x faster)")

    # table before stats
    if cmd == "table" and position < len(all_commands) - 1:
        next_cmd = all_commands[position + 1][0]
        if next_cmd == "stats":
            notes.append("Performance: 'table' before 'stats' drops fields — use 'fields' instead or remove")

    return notes


# ---------------------------------------------------------------------------
# Proactive Optimization Suggestions
# ---------------------------------------------------------------------------

async def analyze_saved_searches_for_optimization(engine) -> List[Insight]:
    """
    Analyze saved searches from the database and suggest optimizations.
    """
    insights = []
    try:
        from sqlalchemy import text

        async with engine.begin() as conn:
            # Get recent queries that had long latencies
            result = await conn.execute(text("""
                SELECT question, response, created_at
                FROM assistant_interactions
                WHERE created_at > NOW() - INTERVAL '7 days'
                ORDER BY created_at DESC
                LIMIT 50
            """))
            interactions = result.fetchall()

            for row in interactions:
                question = row[0] or ""
                response = row[1] or ""

                # Check for SPL in questions or responses
                spl_blocks = re.findall(r'```(?:spl)?\n(.+?)\n```', response, re.DOTALL)
                spl_in_question = re.findall(r'(index\s*=\s*\S+.*?\|.*)', question)
                all_spl = spl_blocks + spl_in_question

                for spl in all_spl:
                    optimization = _quick_spl_review(spl.strip())
                    if optimization:
                        insights.append(optimization)

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[PROACTIVE] Saved search analysis failed: {exc}")

    # Deduplicate insights
    seen = set()
    unique = []
    for insight in insights:
        key = insight.title
        if key not in seen:
            seen.add(key)
            unique.append(insight)

    return unique[:10]  # Top 10 insights


def _quick_spl_review(spl: str) -> Optional[Insight]:
    """Quick review of an SPL query for common performance issues."""
    lower = spl.lower()

    # Check: stats on all events without time filter
    if 'stats' in lower and 'earliest=' not in lower and 'latest=' not in lower:
        if 'index=' in lower:
            return Insight(
                category="optimization",
                severity="suggestion",
                title="SPL query missing time range",
                description="This query searches without a time range, which can be very slow. Add earliest= and latest= to constrain the search.",
                action_payload=spl,
            )

    # Check: join usage
    if '| join' in lower:
        return Insight(
            category="optimization",
            severity="suggestion",
            title="SPL uses join — consider alternatives",
            description="The 'join' command is resource-intensive. Consider using 'stats' with 'by' clause or 'lookup' for better performance.",
            action_payload=spl,
        )

    # Check: stats where tstats could be used
    if '| stats' in lower and 'index=' in lower and '| tstats' not in lower:
        if re.search(r'\bcount\b|\bsum\b|\bavg\b', lower):
            return Insight(
                category="optimization",
                severity="suggestion",
                title="Consider tstats for indexed-field aggregation",
                description="This query uses 'stats' on indexed data. Using 'tstats' with a data model could be 10-100x faster.",
                action_payload=spl,
            )

    # Check: wildcard sourcetype
    if 'sourcetype=*' in lower:
        return Insight(
            category="optimization",
            severity="warning",
            title="Wildcard sourcetype detected",
            description="Using sourcetype=* scans all sourcetypes. Specify the exact sourcetype for better performance.",
            action_payload=spl,
        )

    return None


# ---------------------------------------------------------------------------
# Runbook Correlation
# ---------------------------------------------------------------------------

async def find_matching_runbook(
    error_message: str,
    engine,
    vector_store=None,
    search_func=None,
) -> Optional[Dict[str, Any]]:
    """
    Match an error message or alert to a relevant runbook.

    Searches the knowledge base for runbook/procedure content
    that matches the error pattern.
    """
    if not vector_store or not search_func:
        return None

    try:
        # Search for runbook-type content
        runbook_query = f"runbook procedure troubleshoot: {error_message}"
        chunks = await asyncio.to_thread(
            search_func, vector_store, runbook_query, k=5
        )

        # Filter for runbook-like content
        runbook_chunks = []
        for chunk in chunks:
            text = chunk.get("text", "").lower()
            if any(kw in text for kw in ["runbook", "procedure", "troubleshoot", "resolution", "remediation", "step 1", "step 2"]):
                runbook_chunks.append(chunk)

        if runbook_chunks:
            best = runbook_chunks[0]
            return {
                "title": best.get("metadata", {}).get("title", "Runbook"),
                "source": best.get("metadata", {}).get("source", ""),
                "content": best.get("text", "")[:1000],
                "relevance": best.get("score", 0),
            }

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[PROACTIVE] Runbook search failed: {exc}")

    return None


# ---------------------------------------------------------------------------
# Incident Pattern Detection
# ---------------------------------------------------------------------------

async def detect_incident_patterns(engine, window_hours: int = 24) -> List[Insight]:
    """
    Detect patterns in recent failures that might indicate a systemic issue.

    Looks for:
    - Multiple failures with the same root cause
    - Correlated timing of failures
    - Cascading failure patterns
    """
    insights = []

    try:
        from sqlalchemy import text

        async with engine.begin() as conn:
            # Find clustered failures (same failure type in short window)
            result = await conn.execute(text("""
                SELECT
                    failure_reason,
                    intent,
                    COUNT(*) as failure_count,
                    MIN(created_at) as first_seen,
                    MAX(created_at) as last_seen
                FROM assistant_episodes
                WHERE success = 0
                  AND created_at > NOW() - INTERVAL ':hours hours'
                  AND failure_reason IS NOT NULL
                  AND failure_reason != ''
                GROUP BY failure_reason, intent
                HAVING COUNT(*) >= 3
                ORDER BY failure_count DESC
            """.replace(":hours", str(window_hours))))
            clusters = result.fetchall()

            for row in clusters:
                reason = row[0]
                intent = row[1]
                count = row[2]

                severity = "critical" if count >= 10 else "warning" if count >= 5 else "info"
                insights.append(Insight(
                    category="pattern",
                    severity=severity,
                    title=f"Recurring failure pattern: {intent}",
                    description=f"'{reason}' has occurred {count} times in the last {window_hours}h for intent '{intent}'.",
                    confidence=min(0.9, 0.5 + count * 0.05),
                ))

            # Check for service degradation pattern
            result = await conn.execute(text("""
                SELECT
                    AVG(duration_ms) as avg_latency,
                    AVG(CASE WHEN success = 1 THEN 1.0 ELSE 0.0 END) as success_rate
                FROM assistant_episodes
                WHERE created_at > NOW() - INTERVAL '1 hour'
            """))
            recent = result.fetchone()
            if recent and recent[0]:
                avg_latency = float(recent[0])
                success_rate = float(recent[1] or 0)

                if avg_latency > 30000:  # >30 seconds
                    insights.append(Insight(
                        category="health",
                        severity="warning",
                        title="High response latency detected",
                        description=f"Average response latency is {avg_latency/1000:.1f}s (normal is <10s). LLM service may be overloaded.",
                        confidence=0.8,
                    ))

                if success_rate < 0.5 and success_rate > 0:
                    insights.append(Insight(
                        category="health",
                        severity="critical",
                        title="Low success rate in the last hour",
                        description=f"Only {success_rate:.0%} of queries succeeded in the last hour. Check service health.",
                        confidence=0.9,
                    ))

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[PROACTIVE] Pattern detection failed: {exc}")

    return insights


# ---------------------------------------------------------------------------
# Environment-Aware Personalization
# ---------------------------------------------------------------------------

def inject_org_context(user_input: str, org_config: Dict[str, Any]) -> str:
    """
    Inject organization-specific context into the prompt.

    Maps generic terms to org-specific indexes, fields, and data models.
    """
    index_mappings = org_config.get("index_mappings", {})
    field_mappings = org_config.get("field_mappings", {})

    context_parts = []

    lower = user_input.lower()

    # Match intent keywords to actual indexes
    matched_indexes = []
    for keyword, index in index_mappings.items():
        if keyword in lower:
            matched_indexes.append(f"'{keyword}' data → index={index}")

    if matched_indexes:
        context_parts.append(
            "**Organization Index Mappings:**\n" +
            "\n".join(f"- {m}" for m in matched_indexes)
        )

    # Include field mappings if user mentions field names
    matched_fields = []
    for generic, actual in field_mappings.items():
        if generic in lower:
            matched_fields.append(f"{generic} → {actual}")

    if matched_fields:
        context_parts.append(
            "**Organization Field Mappings:**\n" +
            "\n".join(f"- {m}" for m in matched_fields)
        )

    return "\n\n".join(context_parts) if context_parts else ""


# ---------------------------------------------------------------------------
# Reasoning Transparency
# ---------------------------------------------------------------------------

def format_reasoning_trace(
    intent: str,
    profile: str,
    chunks_found: int,
    collections_searched: List[str],
    confidence_score: float,
    tools_used: List[str] = None,
    latency_ms: float = 0,
) -> str:
    """
    Format a reasoning trace for display to the user.

    Shows how the assistant arrived at its answer.
    """
    parts = ["\n---\n**How I arrived at this answer:**\n"]

    parts.append(f"- Intent detected: `{intent}`")
    parts.append(f"- Profile used: `{profile}`")
    parts.append(f"- Knowledge sources searched: `{', '.join(collections_searched) if collections_searched else 'default'}`")
    parts.append(f"- Relevant chunks found: {chunks_found}")
    parts.append(f"- Confidence score: {confidence_score:.0%}")

    if tools_used:
        parts.append(f"- Tools used: {', '.join(tools_used)}")

    if latency_ms:
        parts.append(f"- Processing time: {latency_ms/1000:.1f}s")

    return "\n".join(parts)
