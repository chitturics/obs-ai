"""
SPL Expert Skill — Generate, optimize, explain, and analyze SPL queries.

Each function is a standalone action handler invoked by the SkillsManager.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Graceful imports from the existing codebase
# ---------------------------------------------------------------------------
try:
    from shared.spl_robust_analyzer import RobustSPLAnalyzer, analyze_spl, AnalysisResult
    _ROBUST_ANALYZER_AVAILABLE = True
except ImportError:
    _ROBUST_ANALYZER_AVAILABLE = False
    logger.debug("shared.spl_robust_analyzer not available — analysis features limited")

try:
    from shared.spl_template_engine import SPLTemplateEngine
    _TEMPLATE_ENGINE_AVAILABLE = True
except ImportError:
    _TEMPLATE_ENGINE_AVAILABLE = False
    logger.debug("shared.spl_template_engine not available — template generation disabled")

try:
    from shared.spl_query_optimizer import SPLQueryOptimizer
    _QUERY_OPTIMIZER_AVAILABLE = True
except ImportError:
    _QUERY_OPTIMIZER_AVAILABLE = False
    logger.debug("shared.spl_query_optimizer not available — tstats optimization disabled")

try:
    from shared.spl_knowledge_base import SPLKnowledgeBase, SPL_COMMANDS
    _KNOWLEDGE_BASE_AVAILABLE = True
except ImportError:
    _KNOWLEDGE_BASE_AVAILABLE = False
    logger.debug("shared.spl_knowledge_base not available — command explanations limited")

try:
    from shared.spl_deep_analysis import deep_analyze
    _DEEP_ANALYSIS_AVAILABLE = True
except ImportError:
    _DEEP_ANALYSIS_AVAILABLE = False
    logger.debug("shared.spl_deep_analysis not available — deep analysis disabled")

try:
    from shared.nlp_to_spl import NLPtoSPL
    _NLP_TO_SPL_AVAILABLE = True
except ImportError:
    _NLP_TO_SPL_AVAILABLE = False
    logger.debug("shared.nlp_to_spl not available — NLP generation uses fallback")

try:
    from shared.utils import split_pipeline
    _UTILS_AVAILABLE = True
except ImportError:
    _UTILS_AVAILABLE = False
    logger.debug("shared.utils not available — using built-in pipeline splitter")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Well-known anti-patterns with descriptions and fixes
_ANTI_PATTERNS = [
    {
        "pattern": r"\bindex\s*=\s*\*",
        "name": "Wildcard index",
        "severity": "critical",
        "description": "Searches all indexes, causing excessive resource consumption",
        "fix": "Specify explicit index names: index=myindex",
    },
    {
        "pattern": r"\|\s*join\b",
        "name": "Join command",
        "severity": "high",
        "description": "join is memory-intensive and has a 50K row default limit. Results can be non-deterministic.",
        "fix": "Replace with stats/lookup where possible. Use '| stats values(field) as field by common_key'",
    },
    {
        "pattern": r"\|\s*transaction\b",
        "name": "Transaction command",
        "severity": "high",
        "description": "transaction is very memory-intensive and CPU-heavy. Does not scale well.",
        "fix": "Replace with '| stats min(_time) as start max(_time) as end values(*) as * by transaction_id'",
    },
    {
        "pattern": r"\|\s*append\b\s*\[",
        "name": "Append subsearch",
        "severity": "medium",
        "description": "append with subsearch runs a separate search that is limited to 10K results by default",
        "fix": "Consider using multisearch or union command instead",
    },
    {
        "pattern": r"\|\s*map\b",
        "name": "Map command",
        "severity": "high",
        "description": "map runs a new search for each input row — extremely expensive at scale",
        "fix": "Restructure to use lookup, join, or stats instead of iterating over rows",
    },
    {
        "pattern": r"\bNOT\s+\bindex\s*=",
        "name": "NOT index filter",
        "severity": "medium",
        "description": "Negated index filter does not restrict the search as expected in Splunk",
        "fix": "List the specific indexes you want to search instead of excluding",
    },
    {
        "pattern": r"\|\s*search\b.*\|\s*search\b",
        "name": "Redundant search commands",
        "severity": "low",
        "description": "Multiple search commands can often be combined into one",
        "fix": "Combine conditions into a single initial search or where clause",
    },
    {
        "pattern": r"\|\s*table\b.*\|\s*(?:stats|chart|timechart)\b",
        "name": "Table before aggregation",
        "severity": "medium",
        "description": "table before stats/chart discards fields that might be needed and adds unnecessary processing",
        "fix": "Move the table command after the aggregation or use fields to limit columns",
    },
    {
        "pattern": r"\|\s*sort\s+\d+\s+",
        "name": "Sort with limit",
        "severity": "low",
        "description": "Using sort with a numeric limit may miss events; consider using head after sort",
        "fix": "Use '| sort 0 field | head N' for deterministic results",
    },
    {
        "pattern": r"\|\s*stats\s+count\s+by\b[^|]*\bby\b",
        "name": "Duplicate BY clause",
        "severity": "medium",
        "description": "Multiple BY keywords in stats — likely a typo causing incorrect grouping",
        "fix": "Use a single BY clause with all group-by fields",
    },
    {
        "pattern": r"\*\s*\|\s*(?:stats|table|chart)",
        "name": "Unbounded base search",
        "severity": "high",
        "description": "Base search of '*' with no index or sourcetype scans all data",
        "fix": "Add index, sourcetype, or source filters to the base search",
    },
    {
        "pattern": r"\|\s*rex\b.*\|\s*rex\b.*\|\s*rex\b",
        "name": "Excessive regex extractions",
        "severity": "medium",
        "description": "Multiple sequential rex commands are CPU-intensive; consider combining them",
        "fix": "Combine regex patterns or use EXTRACT- in props.conf for indexed extractions",
    },
]


def _split_pipeline_fallback(query: str) -> List[str]:
    """Simple pipeline splitter when shared.utils is unavailable."""
    # Avoid splitting inside brackets (subsearches)
    depth = 0
    parts = []
    current = []
    for char in query:
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
        elif char == "|" and depth == 0:
            parts.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    parts.append("".join(current).strip())
    return [p for p in parts if p]


def _split(query: str) -> List[str]:
    """Split SPL pipeline into stages."""
    if _UTILS_AVAILABLE:
        return split_pipeline(query)
    return _split_pipeline_fallback(query)


def _extract_command_name(stage: str) -> str:
    """Extract the command name from a pipeline stage."""
    stage = stage.strip()
    match = re.match(r"^(\w+)\b", stage)
    return match.group(1).lower() if match else ""


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def generate_spl(description: str) -> str:
    """
    Generate an SPL query from a natural language description.

    Uses the template engine for pattern-based generation, falling back
    to NLP-to-SPL translation when available.

    Args:
        description: Natural language description of the desired search.

    Returns:
        JSON string with the generated query and metadata.
    """
    if not description or not description.strip():
        return json.dumps({
            "status": "error",
            "error": "Description cannot be empty",
        })

    result: Dict[str, Any] = {
        "status": "ok",
        "description": description,
        "query": "",
        "confidence": 0.0,
        "method": "",
        "explanation": "",
        "suggestions": [],
    }

    # Try template engine first (deterministic, no LLM)
    if _TEMPLATE_ENGINE_AVAILABLE:
        try:
            engine = SPLTemplateEngine()
            intent = engine.detect_intent(description)
            if intent and intent.confidence > 0.3:
                query = engine.generate(description)
                if query:
                    result["query"] = query
                    result["confidence"] = round(intent.confidence, 2)
                    result["method"] = "template_engine"
                    result["explanation"] = f"Generated from template with intent: {intent.query_type}"
                    result["intent"] = intent.query_type

                    # Validate the generated query
                    if _ROBUST_ANALYZER_AVAILABLE:
                        analysis = analyze_spl(query, auto_fix=True)
                        if analysis.optimized_query and analysis.optimized_query != query:
                            result["optimized_query"] = analysis.optimized_query
                        result["suggestions"] = analysis.recommendations[:5]

                    return json.dumps(result, indent=2)
        except Exception as exc:
            logger.debug(f"Template engine generation failed: {exc}")

    # Try NLP-to-SPL (uses examples + LLM context)
    if _NLP_TO_SPL_AVAILABLE:
        try:
            generator = NLPtoSPL()
            gen_result = generator.generate(description)
            result["query"] = gen_result.query
            result["confidence"] = round(gen_result.confidence, 2)
            result["method"] = "nlp_to_spl"
            result["explanation"] = gen_result.explanation
            result["suggestions"] = gen_result.suggestions[:5]
            return json.dumps(result, indent=2)
        except Exception as exc:
            logger.debug(f"NLP-to-SPL generation failed: {exc}")

    # Fallback: basic keyword-based generation
    desc_lower = description.lower()

    # Detect common patterns
    query_parts = []
    if "error" in desc_lower or "fail" in desc_lower:
        query_parts.append('index=* (error OR fail* OR exception)')
    elif "login" in desc_lower or "auth" in desc_lower:
        query_parts.append('index=* (login OR auth* OR "authentication")')
    elif "network" in desc_lower or "firewall" in desc_lower:
        query_parts.append("index=* sourcetype=*firewall*")
    else:
        # Extract potential keywords
        words = re.findall(r"\b[a-z]{3,}\b", desc_lower)
        stop_words = {"the", "and", "for", "from", "with", "that", "this", "show", "find",
                       "give", "get", "list", "all", "how", "many", "what", "where", "which"}
        keywords = [w for w in words if w not in stop_words][:5]
        if keywords:
            query_parts.append(f'index=* ({" OR ".join(keywords)})')
        else:
            query_parts.append("index=*")

    # Detect aggregation requests
    if any(word in desc_lower for word in ["count", "how many", "total", "number of"]):
        query_parts.append("| stats count")
    if any(word in desc_lower for word in ["top", "most common", "most frequent"]):
        query_parts.append("| top limit=10")
    if any(word in desc_lower for word in ["over time", "trend", "timeline", "chart"]):
        query_parts.append("| timechart count")

    result["query"] = " ".join(query_parts)
    result["confidence"] = 0.2
    result["method"] = "fallback_keyword"
    result["explanation"] = "Generated from keyword extraction — review and refine the query"
    result["suggestions"] = [
        "Specify an explicit index name instead of index=*",
        "Add a time range filter (earliest=-1h latest=now)",
        "Consider adding sourcetype or source filters",
    ]

    return json.dumps(result, indent=2)


def optimize_query(query: str) -> str:
    """
    Optimize an existing SPL query for better performance.

    Analyzes command ordering, suggests tstats conversion, detects expensive
    operations, and returns an improved version.

    Args:
        query: The SPL query to optimize.

    Returns:
        JSON string with original query, optimized query, and recommendations.
    """
    if not query or not query.strip():
        return json.dumps({
            "status": "error",
            "error": "Query cannot be empty",
        })

    result: Dict[str, Any] = {
        "status": "ok",
        "original_query": query,
        "optimized_query": None,
        "improvements": [],
        "estimated_cost_before": 0,
        "estimated_cost_after": 0,
        "tstats_conversion": None,
    }

    # Run robust analysis
    if _ROBUST_ANALYZER_AVAILABLE:
        try:
            analysis = analyze_spl(query, auto_fix=True)
            result["estimated_cost_before"] = analysis.estimated_cost
            if analysis.optimized_query and analysis.optimized_query != query:
                result["optimized_query"] = analysis.optimized_query
                # Re-analyze optimized query to get new cost
                opt_analysis = analyze_spl(analysis.optimized_query, auto_fix=False)
                result["estimated_cost_after"] = opt_analysis.estimated_cost

            for issue in analysis.issues:
                result["improvements"].append({
                    "category": issue.category.value,
                    "severity": issue.severity.value,
                    "issue": issue.message,
                    "suggestion": issue.suggestion or "",
                    "auto_fixable": issue.auto_fixable,
                })
            result["recommendations"] = analysis.recommendations[:10]
        except Exception as exc:
            logger.warning(f"Robust analysis failed: {exc}")

    # Try tstats conversion
    if _QUERY_OPTIMIZER_AVAILABLE:
        try:
            optimizer = SPLQueryOptimizer()
            conversion = optimizer.convert(query)
            if conversion and conversion.status.value != "impossible":
                result["tstats_conversion"] = {
                    "status": conversion.status.value,
                    "strategy": conversion.strategy.value,
                    "tstats_query": conversion.tstats_query,
                    "explanation": conversion.explanation,
                }
                if not result["optimized_query"]:
                    result["optimized_query"] = conversion.tstats_query
        except Exception as exc:
            logger.debug(f"tstats conversion failed: {exc}")

    # Deep analysis for additional insights
    if _DEEP_ANALYSIS_AVAILABLE:
        try:
            deep = deep_analyze(query)
            result["deep_analysis"] = {
                "memory_risk": deep.memory_risk.value if hasattr(deep, "memory_risk") else "unknown",
                "cpu_risk": deep.cpu_risk.value if hasattr(deep, "cpu_risk") else "unknown",
                "fingerprint": deep.fingerprint if hasattr(deep, "fingerprint") else "",
            }
        except Exception as exc:
            logger.debug(f"Deep analysis failed: {exc}")

    # Fallback manual optimizations if no analyzer available
    if not result["improvements"]:
        stages = _split(query)

        # Check command order
        has_early_sort = False
        has_late_filter = False
        for i, stage in enumerate(stages):
            cmd = _extract_command_name(stage)
            if cmd == "sort" and i < len(stages) // 2:
                has_early_sort = True
            if cmd in ("where", "search") and i > 0 and i > len(stages) // 2:
                has_late_filter = True

        if has_early_sort:
            result["improvements"].append({
                "category": "performance",
                "severity": "medium",
                "issue": "sort appears early in the pipeline before data reduction",
                "suggestion": "Move sort after aggregation/filtering to reduce the number of events sorted",
                "auto_fixable": False,
            })
        if has_late_filter:
            result["improvements"].append({
                "category": "performance",
                "severity": "medium",
                "issue": "Filtering commands appear late in the pipeline",
                "suggestion": "Move where/search filters earlier to reduce data flowing through the pipeline",
                "auto_fixable": False,
            })

    if not result["optimized_query"]:
        result["optimized_query"] = query  # No changes

    return json.dumps(result, indent=2)


def explain_query(query: str) -> str:
    """
    Explain what an SPL query does in plain English.

    Breaks down each pipeline stage, identifies the data flow, and
    describes the output format.

    Args:
        query: The SPL query to explain.

    Returns:
        JSON string with stage-by-stage explanation.
    """
    if not query or not query.strip():
        return json.dumps({
            "status": "error",
            "error": "Query cannot be empty",
        })

    stages = _split(query)
    explanations: List[Dict[str, Any]] = []

    # Command descriptions for fallback
    cmd_descriptions = {
        "search": "Filters events matching the given criteria",
        "where": "Filters events using an eval expression",
        "stats": "Calculates aggregate statistics",
        "table": "Formats output as a table with specified columns",
        "fields": "Includes or excludes fields from the results",
        "eval": "Creates or modifies fields using expressions",
        "rex": "Extracts fields using regular expressions",
        "rename": "Renames fields in the results",
        "sort": "Sorts results by the specified fields",
        "head": "Returns the first N results",
        "tail": "Returns the last N results",
        "dedup": "Removes duplicate events based on field values",
        "top": "Returns the most common values of a field",
        "rare": "Returns the least common values of a field",
        "timechart": "Creates a time-series chart with aggregated values",
        "chart": "Creates a chart with aggregated values",
        "lookup": "Enriches events with data from a lookup table",
        "join": "Joins results from a subsearch with the main search",
        "append": "Appends results from a subsearch to the main results",
        "transaction": "Groups events into transactions based on shared fields",
        "eventstats": "Adds aggregate statistics to each event without reducing results",
        "streamstats": "Adds running aggregate statistics to each event",
        "tstats": "Searches indexed metadata for fast statistical queries",
        "inputlookup": "Loads a lookup table as the search results",
        "outputlookup": "Writes results to a lookup table",
        "collect": "Writes results to a summary index",
        "fillnull": "Replaces null values with a specified value",
        "makemv": "Converts a single-value field to a multi-value field",
        "mvexpand": "Expands multi-value fields into separate events",
        "bin": "Discretizes numeric or time values into buckets",
        "bucket": "Discretizes numeric or time values into buckets",
        "regex": "Filters events where a field matches a regular expression",
        "replace": "Replaces field values with specified values",
        "spath": "Extracts fields from structured data (JSON/XML)",
        "xmlkv": "Extracts key-value pairs from XML data",
        "multisearch": "Runs multiple searches simultaneously and combines results",
        "union": "Combines results from multiple datasets",
        "map": "Runs a search for each result row",
        "foreach": "Runs an eval expression for each field matching a pattern",
        "makeresults": "Generates result rows from scratch",
        "addtotals": "Adds a total of numeric fields to each event",
        "mstats": "Searches metrics index data",
    }

    for i, stage in enumerate(stages):
        cmd = _extract_command_name(stage)
        stage_info: Dict[str, Any] = {
            "stage": i + 1,
            "command": cmd,
            "raw": stage.strip(),
            "description": "",
        }

        # Use knowledge base for rich descriptions if available
        if _KNOWLEDGE_BASE_AVAILABLE and cmd in SPL_COMMANDS:
            cmd_info = SPL_COMMANDS[cmd]
            stage_info["description"] = cmd_info.description
            stage_info["category"] = cmd_info.category.value
            stage_info["performance_cost"] = cmd_info.cost.value
        elif cmd in cmd_descriptions:
            stage_info["description"] = cmd_descriptions[cmd]
        else:
            stage_info["description"] = f"Executes the '{cmd}' command"

        # Add context about what this specific stage does
        if i == 0:
            # First stage: identify data source
            index_match = re.search(r"index\s*=\s*(\S+)", stage, re.IGNORECASE)
            st_match = re.search(r"sourcetype\s*=\s*(\S+)", stage, re.IGNORECASE)
            context_parts = ["Retrieves events"]
            if index_match:
                context_parts.append(f"from index '{index_match.group(1)}'")
            if st_match:
                context_parts.append(f"with sourcetype '{st_match.group(1)}'")
            stage_info["context"] = " ".join(context_parts)
        elif cmd == "stats":
            funcs = re.findall(r"\b(count|sum|avg|min|max|dc|values|list|first|last|stdev)\b", stage, re.IGNORECASE)
            by_fields = re.findall(r"\bby\s+(.+?)(?:\||$)", stage, re.IGNORECASE)
            context_parts = []
            if funcs:
                context_parts.append(f"Calculates {', '.join(set(funcs))}")
            if by_fields:
                context_parts.append(f"grouped by {by_fields[0].strip()}")
            stage_info["context"] = " ".join(context_parts) if context_parts else ""
        elif cmd == "eval":
            assignments = re.findall(r"(\w+)\s*=", stage)
            if assignments:
                stage_info["context"] = f"Creates/modifies field(s): {', '.join(assignments[:5])}"
        elif cmd == "table":
            fields = stage.replace("table", "", 1).strip()
            stage_info["context"] = f"Displays columns: {fields}"
        elif cmd == "sort":
            stage_info["context"] = f"Sorts by: {stage.replace('sort', '', 1).strip()}"

        explanations.append(stage_info)

    # Build overall summary
    if explanations:
        first_cmd = explanations[0]["command"]
        last_cmd = explanations[-1]["command"]
        summary = f"This query has {len(explanations)} stage(s). "
        summary += f"It starts with '{first_cmd}' and ends with '{last_cmd}'."
    else:
        summary = "Empty or unparseable query."

    return json.dumps({
        "status": "ok",
        "query": query,
        "summary": summary,
        "stage_count": len(explanations),
        "stages": explanations,
    }, indent=2)


def detect_anti_patterns(query: str) -> str:
    """
    Detect performance anti-patterns in an SPL query.

    Checks for known bad practices such as wildcard indexes, expensive
    commands, poor command ordering, and resource-intensive patterns.

    Args:
        query: The SPL query to check.

    Returns:
        JSON string with detected anti-patterns and recommendations.
    """
    if not query or not query.strip():
        return json.dumps({
            "status": "error",
            "error": "Query cannot be empty",
        })

    detected: List[Dict[str, Any]] = []

    # Check built-in anti-patterns
    for ap in _ANTI_PATTERNS:
        if re.search(ap["pattern"], query, re.IGNORECASE):
            detected.append({
                "name": ap["name"],
                "severity": ap["severity"],
                "description": ap["description"],
                "fix": ap["fix"],
            })

    # Use robust analyzer for additional anti-patterns
    if _ROBUST_ANALYZER_AVAILABLE:
        try:
            analysis = analyze_spl(query, auto_fix=False)
            for issue in analysis.issues:
                if issue.category.value in ("performance", "best_practice"):
                    # Avoid duplicates with our built-in checks
                    if not any(d["description"] == issue.message for d in detected):
                        detected.append({
                            "name": issue.category.value,
                            "severity": issue.severity.value,
                            "description": issue.message,
                            "fix": issue.suggestion or "Review the query for optimization opportunities",
                        })
        except Exception as exc:
            logger.debug(f"Robust analyzer anti-pattern check failed: {exc}")

    # Use deep analysis for resource risk assessment
    resource_risks: Dict[str, Any] = {}
    if _DEEP_ANALYSIS_AVAILABLE:
        try:
            deep = deep_analyze(query)
            resource_risks = {
                "memory_risk": deep.memory_risk.value if hasattr(deep, "memory_risk") else "unknown",
                "cpu_risk": deep.cpu_risk.value if hasattr(deep, "cpu_risk") else "unknown",
                "io_risk": deep.io_risk.value if hasattr(deep, "io_risk") else "unknown",
            }
        except Exception:
            pass

    # Determine overall severity
    if any(d["severity"] == "critical" for d in detected):
        overall_severity = "critical"
    elif any(d["severity"] == "high" for d in detected):
        overall_severity = "high"
    elif any(d["severity"] == "medium" for d in detected):
        overall_severity = "medium"
    elif detected:
        overall_severity = "low"
    else:
        overall_severity = "none"

    return json.dumps({
        "status": "ok",
        "query": query,
        "anti_patterns_found": len(detected),
        "overall_severity": overall_severity,
        "anti_patterns": detected,
        "resource_risks": resource_risks,
    }, indent=2)


# ---------------------------------------------------------------------------
# Cleanup hook
# ---------------------------------------------------------------------------

def cleanup():
    """Release any resources held by this skill."""
    logger.debug("spl_expert skill cleaned up")
