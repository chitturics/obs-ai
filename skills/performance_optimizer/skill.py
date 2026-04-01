"""
Performance Optimizer Skill — Profile searches, suggest tstats conversions,
optimize lookups, and tune limits.conf.

Each function is a standalone action handler invoked by the SkillsManager.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Command performance profiles
# ---------------------------------------------------------------------------

_COMMAND_COSTS: Dict[str, Dict[str, Any]] = {
    "search": {"cpu": "low", "memory": "low", "io": "high", "stage": "generating"},
    "where": {"cpu": "low", "memory": "low", "io": "none", "stage": "filtering"},
    "eval": {"cpu": "low", "memory": "low", "io": "none", "stage": "processing"},
    "stats": {"cpu": "medium", "memory": "high", "io": "none", "stage": "aggregation"},
    "eventstats": {"cpu": "medium", "memory": "high", "io": "none", "stage": "aggregation"},
    "streamstats": {"cpu": "medium", "memory": "medium", "io": "none", "stage": "aggregation"},
    "table": {"cpu": "low", "memory": "low", "io": "none", "stage": "formatting"},
    "fields": {"cpu": "low", "memory": "low", "io": "none", "stage": "filtering"},
    "rex": {"cpu": "high", "memory": "low", "io": "none", "stage": "processing"},
    "regex": {"cpu": "high", "memory": "low", "io": "none", "stage": "filtering"},
    "rename": {"cpu": "low", "memory": "low", "io": "none", "stage": "processing"},
    "sort": {"cpu": "medium", "memory": "high", "io": "none", "stage": "ordering"},
    "head": {"cpu": "low", "memory": "low", "io": "none", "stage": "filtering"},
    "tail": {"cpu": "low", "memory": "medium", "io": "none", "stage": "filtering"},
    "dedup": {"cpu": "medium", "memory": "high", "io": "none", "stage": "filtering"},
    "top": {"cpu": "medium", "memory": "medium", "io": "none", "stage": "aggregation"},
    "rare": {"cpu": "medium", "memory": "medium", "io": "none", "stage": "aggregation"},
    "timechart": {"cpu": "medium", "memory": "medium", "io": "none", "stage": "aggregation"},
    "chart": {"cpu": "medium", "memory": "medium", "io": "none", "stage": "aggregation"},
    "join": {"cpu": "high", "memory": "very_high", "io": "medium", "stage": "combining"},
    "append": {"cpu": "medium", "memory": "medium", "io": "medium", "stage": "combining"},
    "transaction": {"cpu": "very_high", "memory": "very_high", "io": "none", "stage": "combining"},
    "map": {"cpu": "very_high", "memory": "high", "io": "high", "stage": "generating"},
    "lookup": {"cpu": "low", "memory": "medium", "io": "medium", "stage": "enrichment"},
    "inputlookup": {"cpu": "low", "memory": "medium", "io": "medium", "stage": "generating"},
    "tstats": {"cpu": "low", "memory": "low", "io": "low", "stage": "generating"},
    "mstats": {"cpu": "low", "memory": "low", "io": "low", "stage": "generating"},
    "collect": {"cpu": "low", "memory": "medium", "io": "high", "stage": "output"},
    "outputlookup": {"cpu": "low", "memory": "medium", "io": "medium", "stage": "output"},
    "mvexpand": {"cpu": "medium", "memory": "high", "io": "none", "stage": "processing"},
    "spath": {"cpu": "high", "memory": "medium", "io": "none", "stage": "processing"},
    "xmlkv": {"cpu": "high", "memory": "medium", "io": "none", "stage": "processing"},
    "multisearch": {"cpu": "medium", "memory": "medium", "io": "high", "stage": "generating"},
    "union": {"cpu": "medium", "memory": "medium", "io": "medium", "stage": "combining"},
    "foreach": {"cpu": "medium", "memory": "low", "io": "none", "stage": "processing"},
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _split_pipeline(query: str) -> List[str]:
    """Split SPL pipeline into stages, respecting subsearch brackets."""
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


def _extract_command(stage: str) -> str:
    """Extract command name from a pipeline stage."""
    match = re.match(r"^\s*(\w+)\b", stage.strip())
    return match.group(1).lower() if match else ""


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def profile_search(query: str) -> str:
    """
    Profile an SPL query for performance bottlenecks.

    Args:
        query: The SPL query to profile.

    Returns:
        JSON string with performance profile and recommendations.
    """
    if not query or not query.strip():
        return json.dumps({"status": "error", "error": "Query cannot be empty"})

    stages = _split_pipeline(query)
    profile = []
    bottlenecks = []
    total_cost_score = 0
    cost_values = {"low": 1, "medium": 2, "high": 3, "very_high": 4, "none": 0}

    for i, stage in enumerate(stages):
        cmd = _extract_command(stage)
        cmd_info = _COMMAND_COSTS.get(cmd, {"cpu": "unknown", "memory": "unknown",
                                             "io": "unknown", "stage": "unknown"})
        cpu_score = cost_values.get(cmd_info["cpu"], 1)
        mem_score = cost_values.get(cmd_info["memory"], 1)
        io_score = cost_values.get(cmd_info["io"], 0)
        stage_score = cpu_score + mem_score + io_score

        profile.append({
            "stage": i + 1,
            "command": cmd,
            "raw": stage.strip()[:100],
            "cpu": cmd_info["cpu"],
            "memory": cmd_info["memory"],
            "io": cmd_info["io"],
            "pipeline_stage": cmd_info["stage"],
            "cost_score": stage_score,
        })

        total_cost_score += stage_score

        if stage_score >= 6:
            bottlenecks.append({
                "stage": i + 1,
                "command": cmd,
                "reason": f"High resource usage: CPU={cmd_info['cpu']}, Memory={cmd_info['memory']}, IO={cmd_info['io']}",
            })

    # Check for optimization opportunities
    recommendations = []

    # Check for wildcard index
    if re.search(r"index\s*=\s*\*", query, re.IGNORECASE):
        recommendations.append({
            "type": "scope",
            "severity": "critical",
            "message": "Replace index=* with specific index names to reduce scan scope",
        })

    # Check for late filtering
    commands = [_extract_command(s) for s in stages]
    filter_cmds = {"where", "search", "regex", "head", "dedup"}
    for i, cmd in enumerate(commands):
        if cmd in filter_cmds and i > len(commands) // 2 and len(commands) > 3:
            recommendations.append({
                "type": "reorder",
                "severity": "medium",
                "message": f"Move '{cmd}' (stage {i+1}) earlier in the pipeline to reduce data volume sooner",
            })

    # Check for join/transaction alternatives
    if "join" in commands:
        recommendations.append({
            "type": "alternative",
            "severity": "high",
            "message": "Replace 'join' with stats/lookup where possible for better scalability",
        })
    if "transaction" in commands:
        recommendations.append({
            "type": "alternative",
            "severity": "high",
            "message": "Replace 'transaction' with 'stats' using min/max(_time) and values() for better performance",
        })

    # Check for missing fields command
    if len(stages) > 3 and "fields" not in commands[:3]:
        recommendations.append({
            "type": "optimization",
            "severity": "low",
            "message": "Add '| fields field1, field2, ...' early to reduce data transferred between stages",
        })

    # Overall assessment
    if total_cost_score > 20:
        assessment = "expensive"
    elif total_cost_score > 10:
        assessment = "moderate"
    else:
        assessment = "efficient"

    return json.dumps({
        "status": "ok",
        "assessment": assessment,
        "total_cost_score": total_cost_score,
        "stage_count": len(stages),
        "stages": profile,
        "bottlenecks": bottlenecks,
        "recommendations": recommendations,
    }, indent=2)


def suggest_tstats(query: str) -> str:
    """
    Analyze a query for possible tstats conversion.

    Args:
        query: The SPL query to analyze.

    Returns:
        JSON string with tstats conversion suggestions.
    """
    if not query or not query.strip():
        return json.dumps({"status": "error", "error": "Query cannot be empty"})

    stages = _split_pipeline(query)
    commands = [_extract_command(s) for s in stages]

    convertible = True
    blockers = []
    reasons = []

    # Check if the query pattern is tstats-convertible
    # Pattern: search | stats ... by ...
    if commands[0] not in ("search", ""):
        if commands[0] != "tstats":
            blockers.append(f"First command is '{commands[0]}', not 'search' — tstats requires indexed data access")
            convertible = False

    # Check for non-tstats-compatible commands
    non_compat = {"rex", "eval", "lookup", "join", "transaction", "map", "spath", "xmlkv", "mvexpand"}
    before_stats = True
    for cmd in commands:
        if cmd in ("stats", "timechart", "chart"):
            before_stats = False
        if before_stats and cmd in non_compat:
            blockers.append(f"'{cmd}' before aggregation is not compatible with tstats")
            convertible = False

    # Check for stats-like aggregation
    has_aggregation = any(cmd in ("stats", "timechart", "chart", "top", "rare") for cmd in commands)
    if not has_aggregation:
        blockers.append("No aggregation command found — tstats requires stats-style aggregation")
        convertible = False

    # Extract index and sourcetype for tstats query
    index_match = re.search(r"index\s*=\s*(\S+)", query, re.IGNORECASE)
    st_match = re.search(r"sourcetype\s*=\s*(\S+)", query, re.IGNORECASE)
    index_name = index_match.group(1) if index_match else "my_index"
    sourcetype = st_match.group(1) if st_match else None

    # Extract stats functions and fields
    stats_match = re.search(r"\|\s*stats\s+(.+?)(?:\||$)", query, re.IGNORECASE)
    tstats_query = None

    if convertible and stats_match:
        stats_clause = stats_match.group(1).strip()
        where_clause = f'index={index_name}'
        if sourcetype:
            where_clause += f' sourcetype={sourcetype}'

        tstats_query = f'| tstats {stats_clause} where {where_clause}'

        reasons.append("Query pattern is compatible with tstats conversion")
        reasons.append("tstats searches indexed metadata (tsidx) which is much faster")
        reasons.append("Requires data model acceleration or indexed fields")

    elif commands[0] == "tstats":
        return json.dumps({
            "status": "ok",
            "convertible": False,
            "message": "Query already uses tstats",
        })

    return json.dumps({
        "status": "ok",
        "convertible": convertible,
        "original_query": query,
        "tstats_query": tstats_query,
        "blockers": blockers,
        "notes": reasons,
        "prerequisites": [
            "Ensure the relevant data model is accelerated",
            "Or ensure the fields used are indexed (INDEXED_EXTRACTIONS)",
            "Test tstats query output matches original query output",
        ] if convertible else [],
    }, indent=2)


def optimize_lookups(query: str) -> str:
    """
    Suggest lookup optimization strategies.

    Args:
        query: SPL query containing lookup commands.

    Returns:
        JSON string with lookup optimization recommendations.
    """
    if not query or not query.strip():
        return json.dumps({"status": "error", "error": "Query cannot be empty"})

    # Find lookup usages
    lookup_matches = re.findall(
        r"\|\s*lookup\s+(\S+)\s+(.+?)(?:OUTPUT|OUTPUTNEW|AS|\||$)",
        query, re.IGNORECASE
    )
    inputlookup_matches = re.findall(
        r"\|\s*inputlookup\s+(\S+)",
        query, re.IGNORECASE
    )

    if not lookup_matches and not inputlookup_matches:
        return json.dumps({
            "status": "ok",
            "message": "No lookup commands found in the query",
            "recommendation": "If you need enrichment, consider using automatic lookups in transforms.conf",
        })

    recommendations = []
    lookups_found = []

    for lookup_name, fields in lookup_matches:
        lookups_found.append({"name": lookup_name, "type": "lookup", "fields": fields.strip()})
        recommendations.append({
            "lookup": lookup_name,
            "optimization": "automatic_lookup",
            "description": f"Convert '{lookup_name}' to an automatic lookup in transforms.conf to avoid explicit lookup command",
            "config": (f"transforms.conf:\n[{lookup_name}]\nfilename = {lookup_name}.csv\n\n"
                       f"props.conf:\n[my_sourcetype]\nLOOKUP-{lookup_name} = {lookup_name} {fields.strip()}")
        })

    for lookup_name in inputlookup_matches:
        lookups_found.append({"name": lookup_name, "type": "inputlookup"})
        recommendations.append({
            "lookup": lookup_name,
            "optimization": "kvstore",
            "description": f"Consider migrating '{lookup_name}' to KV Store for better performance with large datasets",
        })

    # General optimization tips
    general_tips = []
    if len(lookup_matches) > 2:
        general_tips.append("Multiple lookups detected — consider combining into a single enrichment lookup")
    if any("inputlookup" in s for s in _split_pipeline(query)):
        general_tips.append("inputlookup loads entire CSV into memory — use 'where' clause to filter early")
    general_tips.extend([
        "Keep lookup files under 100MB for CSV lookups",
        "Use KV Store for lookups that need frequent updates",
        "Enable lookup table replication in distributed environments",
        "Set max_matches=1 in transforms.conf if only one match is needed",
    ])

    return json.dumps({
        "status": "ok",
        "lookups_found": lookups_found,
        "lookup_count": len(lookups_found),
        "recommendations": recommendations,
        "general_tips": general_tips,
    }, indent=2)


def tune_limits(workload: str) -> str:
    """
    Suggest limits.conf tuning based on workload characteristics.

    Args:
        workload: Description of the workload type.

    Returns:
        JSON string with limits.conf recommendations.
    """
    if not workload or not workload.strip():
        return json.dumps({"status": "error", "error": "Workload description cannot be empty"})

    wl = workload.strip().lower()

    tuning_profiles: Dict[str, Dict[str, Any]] = {
        "heavy_search": {
            "description": "Optimized for complex, long-running searches",
            "settings": {
                "[search]": {
                    "max_searches_per_cpu": 2,
                    "base_max_searches": 8,
                    "search_process_memory_usage_threshold": 0.30,
                    "max_mem_usage_mb": 4096,
                    "max_rawsize_perchunk": 200000000,
                },
                "[scheduler]": {
                    "max_searches_perc": 50,
                    "auto_summary_perc": 50,
                },
                "[results]": {
                    "maxresultrows": 100000,
                    "max_count": 500000,
                },
            },
        },
        "high_concurrency": {
            "description": "Optimized for many concurrent users and searches",
            "settings": {
                "[search]": {
                    "max_searches_per_cpu": 4,
                    "base_max_searches": 16,
                    "search_process_memory_usage_threshold": 0.20,
                    "max_mem_usage_mb": 2048,
                },
                "[scheduler]": {
                    "max_searches_perc": 75,
                    "auto_summary_perc": 25,
                },
                "[realtime]": {
                    "indexed_realtime_maximum_span": 300,
                },
            },
        },
        "large_lookups": {
            "description": "Optimized for large lookup table operations",
            "settings": {
                "[lookup]": {
                    "max_memtable_bytes": 524288000,
                    "max_matches": 1000,
                    "max_reverse_matches": 50,
                    "batch_index_query": True,
                },
                "[search]": {
                    "max_mem_usage_mb": 4096,
                },
                "[kvstore]": {
                    "max_documents_per_batch_save": 1000,
                    "max_size_per_batch_save_mb": 50,
                },
            },
        },
        "real_time": {
            "description": "Optimized for real-time search workloads",
            "settings": {
                "[realtime]": {
                    "indexed_realtime_maximum_span": 60,
                    "indexed_realtime_disk_sync_delay": 10,
                    "indexed_realtime_use_by_default": True,
                },
                "[search]": {
                    "max_searches_per_cpu": 3,
                    "max_rt_search_multiplier": 3,
                },
            },
        },
        "summary_indexing": {
            "description": "Optimized for summary indexing and report acceleration",
            "settings": {
                "[auto_summarizer]": {
                    "max_concurrent": 4,
                    "max_time": 3600,
                    "max_disabled_buckets": 2,
                },
                "[scheduler]": {
                    "auto_summary_perc": 75,
                    "max_searches_perc": 50,
                },
                "[search]": {
                    "max_mem_usage_mb": 4096,
                },
            },
        },
    }

    # Match workload
    matched = tuning_profiles.get(wl)
    if not matched:
        # Try fuzzy match
        for key, profile in tuning_profiles.items():
            if any(word in wl for word in key.split("_")):
                matched = profile
                wl = key
                break

    if not matched:
        return json.dumps({
            "status": "error",
            "error": f"Unknown workload type: {workload}",
            "available_workloads": list(tuning_profiles.keys()),
        })

    # Generate limits.conf content
    conf_lines = []
    for stanza, settings in matched["settings"].items():
        conf_lines.append(stanza)
        for key, value in settings.items():
            if isinstance(value, bool):
                conf_lines.append(f"{key} = {'true' if value else 'false'}")
            else:
                conf_lines.append(f"{key} = {value}")
        conf_lines.append("")

    return json.dumps({
        "status": "ok",
        "workload": wl,
        "description": matched["description"],
        "settings": matched["settings"],
        "limits_conf": "\n".join(conf_lines),
        "notes": [
            "Apply changes to $SPLUNK_HOME/etc/system/local/limits.conf",
            "Restart Splunk after making changes",
            "Monitor search.log and metrics.log after tuning",
            "Adjust values incrementally based on observed performance",
        ],
    }, indent=2)


# ---------------------------------------------------------------------------
# Cleanup hook
# ---------------------------------------------------------------------------

def cleanup():
    """Release any resources held by this skill."""
    logger.debug("performance_optimizer skill cleaned up")
