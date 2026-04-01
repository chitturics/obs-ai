"""
SPL Knowledge Base - Deep understanding of Splunk SPL commands and patterns.

Provides expert-level knowledge about:
- SPL command syntax, options, and behavior
- Performance characteristics and costs
- Common patterns and anti-patterns
- Optimization opportunities
- Human-readable explanations

Usage:
    from spl_knowledge_base import SPLKnowledgeBase

    kb = SPLKnowledgeBase()
    info = kb.get_command_info("stats")
    explanation = kb.explain_command_usage("stats count by user")
    suggestions = kb.get_optimization_suggestions(query)
"""

import copy
import re
import json
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from pathlib import Path
from enum import Enum


class CommandCategory(Enum):
    """Categories of SPL commands by function."""
    SEARCH = "search"           # Base search, filtering
    AGGREGATION = "aggregation" # stats, timechart, chart
    TRANSFORM = "transform"     # eval, rex, lookup
    FILTERING = "filtering"     # where, search, dedup
    ORDERING = "ordering"       # sort, head, tail
    FORMATTING = "formatting"   # table, fields, rename
    JOINING = "joining"         # join, append, union
    REPORTING = "reporting"     # outputlookup, collect
    STREAMING = "streaming"     # eventstats, streamstats
    GENERATING = "generating"   # makeresults, inputlookup


class PerformanceCost(Enum):
    """Relative performance cost of commands."""
    VERY_LOW = 1    # tstats, metadata
    LOW = 2         # stats, timechart, table
    MEDIUM = 3      # eval, where, rex
    HIGH = 4        # join, transaction
    VERY_HIGH = 5   # append subsearch, map


@dataclass
class CommandInfo:
    """Detailed information about an SPL command."""
    name: str
    category: CommandCategory
    cost: PerformanceCost
    description: str
    syntax: str
    common_options: Dict[str, str]
    examples: List[str]
    optimization_notes: List[str]
    alternatives: List[str]
    streaming: bool = False  # Can be distributed/parallelized
    generates_events: bool = False
    transforms_events: bool = False
    distributable: bool = True  # Can run on indexers (distributed search)
    memory_intensity: str = "low"  # "low", "medium", "high", "very_high"
    cpu_intensity: str = "low"  # "low", "medium", "high"


# Comprehensive SPL command knowledge base
SPL_COMMANDS: Dict[str, CommandInfo] = {
    # === SEARCH COMMANDS ===
    "search": CommandInfo(
        name="search",
        category=CommandCategory.SEARCH,
        cost=PerformanceCost.MEDIUM,
        description="Filters events based on Boolean expressions. The implicit first command in most searches.",
        syntax="search <search-expression>",
        common_options={
            "index": "Specify which index to search",
            "sourcetype": "Filter by sourcetype",
            "earliest": "Start time for search",
            "latest": "End time for search",
        },
        examples=[
            "index=main error",
            "index=security sourcetype=WinEventLog EventCode=4625",
            "search status>=400",
        ],
        optimization_notes=[
            "Always specify index explicitly - never use index=*",
            "Add time constraints with earliest/latest",
            "Put most restrictive filters first",
            "Use TERM(literal) for exact token matching in bloom filters (e.g., TERM(error), TERM(action=denied))",
            "Use PREFIX(field=value) for prefix matching in tsidx (e.g., PREFIX(src_ip=10.1.))",
            "NEVER put wildcards inside TERM() — use PREFIX() instead of TERM(value*)",
        ],
        alternatives=["where (for post-search filtering)"],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "tstats": CommandInfo(
        name="tstats",
        category=CommandCategory.AGGREGATION,
        cost=PerformanceCost.VERY_LOW,
        description="Performs statistical queries on indexed fields (tsidx). 10-100x faster than stats for compatible queries.",
        syntax="| tstats <stats-func> from <datamodel> where <filter> by <fields>",
        common_options={
            "prestats": "Include pre-computed stats",
            "summariesonly": "Only use accelerated data",
            "allow_old_summaries": "Use older summaries if available",
            "append": "Append to existing results",
        },
        examples=[
            "| tstats count where index=firewall TERM(action=denied) by host",
            "| tstats count from datamodel=Network_Traffic by All_Traffic.src",
            "| tstats prestats=t count where index=main TERM(error) by _time span=1h",
            "| tstats count where index=main TERM(error) by PREFIX(action=) | rename \"action=*\" AS action | search action=error",
        ],
        optimization_notes=[
            "Best performance when using indexed fields only",
            "Use with CIM data models for accelerated searches",
            "Cannot use calculated fields or rex extractions",
            "Use TERM(field=value) for exact token matching in tsidx bloom filters",
            "Use PREFIX(field=) for prefix matching — e.g., PREFIX(src_ip=10.1.)",
            "NEVER put wildcards inside TERM() — use PREFIX() for prefix matching instead",
            "For search-time fields: use PREFIX(field=) in BY clause with rename/search for filtering",
        ],
        alternatives=["stats (slower but more flexible)"],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    # === AGGREGATION COMMANDS ===
    "stats": CommandInfo(
        name="stats",
        category=CommandCategory.AGGREGATION,
        cost=PerformanceCost.LOW,
        description="Calculates aggregate statistics over the result set. Most common aggregation command.",
        syntax="stats <stats-func>(<field>) [as <alias>] [by <field-list>]",
        common_options={
            "count": "Count events",
            "sum": "Sum numeric values",
            "avg": "Calculate average",
            "dc": "Distinct count",
            "values": "List unique values",
            "first/last": "First or last value",
            "max/min": "Maximum or minimum",
        },
        examples=[
            "| stats count by user",
            "| stats sum(bytes) as total_bytes by src_ip",
            "| stats dc(user) as unique_users, count as total_events by host",
            "| stats values(action) as actions by user",
        ],
        optimization_notes=[
            "Consider tstats for simple counts on indexed fields",
            "Use dc() carefully on high-cardinality fields",
            "Reduce BY field cardinality when possible",
            "stats is more efficient than eventstats for final aggregations",
        ],
        alternatives=["tstats (faster for indexed fields)", "eventstats (adds stats to events)"],
        transforms_events=True,
        distributable=True,
        memory_intensity="medium",
        cpu_intensity="low",
    ),

    "timechart": CommandInfo(
        name="timechart",
        category=CommandCategory.AGGREGATION,
        cost=PerformanceCost.LOW,
        description="Creates time-series data for charting. Groups results by time buckets.",
        syntax="timechart [span=<time>] <stats-func>(<field>) [by <split-field>]",
        common_options={
            "span": "Time bucket size (1h, 1d, etc.)",
            "bins": "Number of time buckets",
            "limit": "Limit number of series",
            "useother": "Include 'other' category",
        },
        examples=[
            "| timechart span=1h count",
            "| timechart span=5m avg(response_time) by status",
            "| timechart count by host limit=10",
        ],
        optimization_notes=[
            "Larger span = fewer buckets = faster",
            "limit=N reduces data for high-cardinality splits",
            "Consider tstats with span for indexed fields",
        ],
        alternatives=["chart (arbitrary X-axis)", "tstats prestats with span"],
        transforms_events=True,
    ),

    "eventstats": CommandInfo(
        name="eventstats",
        category=CommandCategory.STREAMING,
        cost=PerformanceCost.HIGH,
        description="Adds aggregated statistics as new fields to each event without removing events.",
        syntax="eventstats <stats-func>(<field>) [as <alias>] [by <field-list>]",
        common_options={
            "Same as stats": "count, sum, avg, dc, values, etc.",
        },
        examples=[
            "| eventstats count as total_count",
            "| eventstats avg(response_time) as avg_response by host",
            "| eventstats sum(bytes) as total_bytes by user | eval pct=bytes/total_bytes*100",
        ],
        optimization_notes=[
            "Memory-intensive for large datasets",
            "Consider stats + join as alternative for simple cases",
            "Use streamstats if processing order matters",
        ],
        alternatives=["stats (if you don't need original events)", "streamstats (for running totals)"],
        streaming=True,
        distributable=True,
        memory_intensity="high",
        cpu_intensity="medium",
    ),

    "streamstats": CommandInfo(
        name="streamstats",
        category=CommandCategory.STREAMING,
        cost=PerformanceCost.MEDIUM,
        description="Calculates running statistics for each event based on preceding events.",
        syntax="streamstats [window=<N>] <stats-func>(<field>) [as <alias>] [by <field-list>]",
        common_options={
            "window": "Number of preceding events to consider",
            "current": "Include current event in calculation",
            "global": "Calculate across all events",
            "reset_on_change": "Reset when BY field changes",
        },
        examples=[
            "| streamstats count as running_count",
            "| streamstats window=5 avg(value) as moving_avg",
            "| streamstats reset_on_change=true count by session_id",
        ],
        optimization_notes=[
            "Process-intensive for large window sizes",
            "Sort events first if order matters",
            "Consider trendline for simpler moving averages",
        ],
        alternatives=["trendline (simpler moving averages)", "eventstats (for group-level stats)"],
        streaming=True,
        distributable=False,
        memory_intensity="medium",
        cpu_intensity="medium",
    ),

    # === TRANSFORM COMMANDS ===
    "eval": CommandInfo(
        name="eval",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.MEDIUM,
        description="Creates or modifies fields using expressions. The most versatile field manipulation command.",
        syntax="eval <field>=<expression> [, <field2>=<expression2>]",
        common_options={
            "if()": "Conditional expressions",
            "case()": "Multi-condition expressions",
            "coalesce()": "First non-null value",
            "tonumber/tostring": "Type conversion",
            "strftime/strptime": "Time formatting",
            "mvjoin/split": "Multivalue operations",
        },
        examples=[
            "| eval status_text=if(status>=400, \"error\", \"ok\")",
            "| eval severity=case(level=\"ERROR\",3, level=\"WARN\",2, 1=1,1)",
            "| eval bytes_mb=bytes/1024/1024",
            "| eval full_name=first_name.\" \".last_name",
        ],
        optimization_notes=[
            "Combine multiple eval operations into one command",
            "Use case() instead of nested if() for clarity",
            "Avoid eval in subsearches when possible",
        ],
        alternatives=["rex (for regex extraction)", "lookup (for value mapping)"],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="medium",
    ),

    "rex": CommandInfo(
        name="rex",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.MEDIUM,
        description="Extracts fields using regular expressions or replaces text patterns.",
        syntax="rex [field=<field>] <regex-pattern> | rex mode=sed <sed-expression>",
        common_options={
            "field": "Field to apply regex to (default: _raw)",
            "mode": "sed for replacement mode",
            "max_match": "Maximum matches to extract",
            "offset_field": "Store match position",
        },
        examples=[
            '| rex field=message "user=(?<username>\\w+)"',
            '| rex "(?<ip>\\d+\\.\\d+\\.\\d+\\.\\d+)"',
            '| rex mode=sed "s/password=\\S+/password=REDACTED/g"',
        ],
        optimization_notes=[
            "Complex regex patterns are CPU-intensive",
            "Consider using indexed field extraction in props.conf instead",
            "Use TERM() if searching for literal strings",
        ],
        alternatives=["extract (automatic extraction)", "spath (for structured data)"],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="high",
    ),

    "lookup": CommandInfo(
        name="lookup",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.LOW,
        description="Enriches events with data from a lookup table (CSV or KV store).",
        syntax="lookup <lookup-name> <match-field> [as <local-field>] [OUTPUT <output-fields>]",
        common_options={
            "OUTPUT": "Specify which fields to add",
            "OUTPUTNEW": "Only add if field doesn't exist",
            "local": "Use local lookup table",
        },
        examples=[
            "| lookup users_lookup username OUTPUT department, manager",
            "| lookup geo_lookup ip as src_ip OUTPUT city, country",
            "| lookup threat_intel domain OUTPUTNEW threat_score, threat_type",
        ],
        optimization_notes=[
            "KV store lookups are faster for large datasets",
            "Use automatic lookups in transforms.conf when appropriate",
            "Limit OUTPUT fields to only what's needed",
        ],
        alternatives=["inputlookup (load entire lookup)", "join (for complex matching)"],
        streaming=True,
    ),

    # === FILTERING COMMANDS ===
    "where": CommandInfo(
        name="where",
        category=CommandCategory.FILTERING,
        cost=PerformanceCost.LOW,
        description="Filters results using Boolean expressions on calculated or extracted fields.",
        syntax="where <eval-expression>",
        common_options={
            "Operators": "=, !=, <, >, <=, >=, AND, OR, NOT",
            "Functions": "isnull(), isnotnull(), like(), match()",
        },
        examples=[
            "| where count > 100",
            "| where status >= 400 AND status < 500",
            "| where like(user, \"admin%\")",
            "| where isnotnull(error_message)",
        ],
        optimization_notes=[
            "Use search command for initial filtering when possible",
            "where is best for filtering on calculated fields",
            "Put most selective conditions first",
        ],
        alternatives=["search (for base filtering)", "dedup (for uniqueness)"],
        streaming=True,
    ),

    "dedup": CommandInfo(
        name="dedup",
        category=CommandCategory.FILTERING,
        cost=PerformanceCost.MEDIUM,
        description="Removes duplicate events based on specified fields.",
        syntax="dedup [<N>] <field-list> [sortby <sort-field>]",
        common_options={
            "N": "Keep first N duplicates (default: 1)",
            "sortby": "Sort order before deduplication",
            "keepevents": "Keep all events, mark duplicates",
            "consecutive": "Only dedupe consecutive duplicates",
        },
        examples=[
            "| dedup user",
            "| dedup 5 host sortby -_time",
            "| dedup src_ip, dest_ip, dest_port",
        ],
        optimization_notes=[
            "Memory-intensive for many unique combinations",
            "Consider stats for simple counting scenarios",
            "Use consecutive=true for streaming dedup",
        ],
        alternatives=["stats (for aggregation)", "uniq (after sort)"],
        streaming=False,
        distributable=False,
        memory_intensity="high",
        cpu_intensity="low",
    ),

    # === FORMATTING COMMANDS ===
    "table": CommandInfo(
        name="table",
        category=CommandCategory.FORMATTING,
        cost=PerformanceCost.LOW,
        description="Formats output as a table with specified fields in order.",
        syntax="table <field-list>",
        common_options={},
        examples=[
            "| table _time, user, action, status",
            "| table host, cpu_pct, memory_pct",
        ],
        optimization_notes=[
            "Use fields command to remove fields earlier in pipeline",
            "Table is applied at the end, after all processing",
        ],
        alternatives=["fields (to remove fields earlier)"],
        transforms_events=True,
    ),

    "fields": CommandInfo(
        name="fields",
        category=CommandCategory.FORMATTING,
        cost=PerformanceCost.VERY_LOW,
        description="Keeps or removes fields from events. Use early to reduce data volume.",
        syntax="fields [+|-] <field-list>",
        common_options={
            "+": "Keep only these fields (default)",
            "-": "Remove these fields",
        },
        examples=[
            "| fields user, action, _time",
            "| fields - _raw, _indextime",
            "| fields + src_ip, dest_ip, bytes",
        ],
        optimization_notes=[
            "Use early in pipeline to reduce memory usage",
            "fields - _raw can significantly reduce memory",
            "More efficient than table for field reduction",
        ],
        alternatives=["table (for final output formatting)"],
        streaming=True,
    ),

    "rename": CommandInfo(
        name="rename",
        category=CommandCategory.FORMATTING,
        cost=PerformanceCost.VERY_LOW,
        description="Renames fields in the results.",
        syntax="rename <old-field> as <new-field> [, ...]",
        common_options={},
        examples=[
            "| rename src_ip as source, dest_ip as destination",
            "| rename count as total_events",
        ],
        optimization_notes=[
            "Lightweight operation, minimal performance impact",
            "Can use wildcards: rename *_old as *_new",
        ],
        alternatives=["eval (for more complex renaming)"],
        streaming=True,
    ),

    # === JOINING COMMANDS ===
    "join": CommandInfo(
        name="join",
        category=CommandCategory.JOINING,
        cost=PerformanceCost.HIGH,
        description="Combines results from main search with subsearch results. Use sparingly.",
        syntax="join [type=<join-type>] <field-list> [<subsearch>]",
        common_options={
            "type": "inner (default), outer, left",
            "max": "Maximum matches (default: 1)",
            "overwrite": "Overwrite existing fields",
        },
        examples=[
            "index=web | join session_id [search index=auth | fields session_id, user]",
            "| join type=left user [inputlookup users.csv]",
        ],
        optimization_notes=[
            "VERY expensive - avoid in production searches",
            "Subsearch has 50,000 result limit",
            "Consider stats or lookup as alternatives",
            "Use append + stats for union-style operations",
        ],
        alternatives=["lookup (much faster for enrichment)", "stats (for aggregation-based joins)"],
        transforms_events=True,
        distributable=False,
        memory_intensity="very_high",
        cpu_intensity="medium",
    ),

    "append": CommandInfo(
        name="append",
        category=CommandCategory.JOINING,
        cost=PerformanceCost.HIGH,
        description="Appends subsearch results to main search results.",
        syntax="append [<subsearch>]",
        common_options={
            "maxtime": "Maximum time for subsearch",
            "timeout": "Subsearch timeout",
        },
        examples=[
            "index=errors | append [search index=warnings]",
            "| stats count by host | append [| makeresults | eval host=\"Total\"]",
        ],
        optimization_notes=[
            "Subsearch has result limits",
            "Consider union for combining multiple searches",
            "multisearch may be more efficient",
        ],
        alternatives=["union (for combining searches)", "multisearch (for parallel searches)"],
        generates_events=True,
    ),

    "transaction": CommandInfo(
        name="transaction",
        category=CommandCategory.JOINING,
        cost=PerformanceCost.VERY_HIGH,
        description="Groups events into transactions based on field values or time constraints.",
        syntax="transaction <field-list> [startswith=<expr>] [endswith=<expr>] [maxspan=<time>]",
        common_options={
            "startswith": "Expression marking transaction start",
            "endswith": "Expression marking transaction end",
            "maxspan": "Maximum transaction duration",
            "maxpause": "Maximum gap between events",
            "mvlist": "Create multivalue list of field values",
        },
        examples=[
            "| transaction session_id maxspan=30m",
            '| transaction host startswith="session start" endswith="session end"',
            "| transaction user maxpause=5m",
        ],
        optimization_notes=[
            "EXTREMELY expensive - avoid on large datasets",
            "Consider stats with earliest/latest instead",
            "Use maxspan/maxpause to limit scope",
            "Often can be replaced with streamstats + stats",
        ],
        alternatives=["stats (for simple duration calculations)", "streamstats (for session tracking)"],
        transforms_events=True,
        distributable=False,
        memory_intensity="very_high",
        cpu_intensity="high",
    ),

    # === ORDERING COMMANDS ===
    "sort": CommandInfo(
        name="sort",
        category=CommandCategory.ORDERING,
        cost=PerformanceCost.MEDIUM,
        description="Sorts results by specified fields. Use + for ascending (default), - for descending.",
        syntax="sort [<limit>] [+|-]<field> [, ...]",
        common_options={
            "+": "Ascending order (default)",
            "-": "Descending order",
            "limit": "Maximum results to return",
            "num()": "Sort as numbers",
            "str()": "Sort as strings",
            "ip()": "Sort as IP addresses",
        },
        examples=[
            "| sort -_time",
            "| sort 100 -count, +user",
            "| sort num(status), -bytes",
        ],
        optimization_notes=[
            "Limit results before sorting when possible",
            "Specify ascending/descending explicitly",
            "Memory-intensive for large result sets",
        ],
        alternatives=["head (after sort for top N)"],
        streaming=False,
        distributable=False,
        memory_intensity="high",
        cpu_intensity="medium",
    ),

    "head": CommandInfo(
        name="head",
        category=CommandCategory.ORDERING,
        cost=PerformanceCost.VERY_LOW,
        description="Returns the first N results.",
        syntax="head [<N>] [limit=<N>] [null=<bool>]",
        common_options={
            "limit": "Number of results (default: 10)",
            "null": "Include null values",
            "keeplast": "Keep last N instead of first",
        },
        examples=[
            "| head 100",
            "| head limit=50",
            "| sort -count | head 10",
        ],
        optimization_notes=[
            "Very efficient - stops processing early",
            "Use after sort for top N pattern",
        ],
        alternatives=["tail (for last N)"],
        streaming=True,
    ),

    "tail": CommandInfo(
        name="tail",
        category=CommandCategory.ORDERING,
        cost=PerformanceCost.LOW,
        description="Returns the last N results.",
        syntax="tail [<N>]",
        common_options={},
        examples=[
            "| tail 100",
            "| sort _time | tail 50",
        ],
        optimization_notes=[
            "Must process all events to find last N",
            "Less efficient than head for large datasets",
        ],
        alternatives=["head (for first N)", "sort with limit"],
        streaming=False,
    ),

    # === ADDITIONAL COMMON COMMANDS ===
    "chart": CommandInfo(
        name="chart",
        category=CommandCategory.AGGREGATION,
        cost=PerformanceCost.LOW,
        description="Creates a chart with arbitrary X and Y axes. More flexible than timechart.",
        syntax="chart <stats-func>(<field>) [over <x-field>] [by <split-field>]",
        common_options={
            "over": "Field for X-axis",
            "by": "Field to split series",
            "limit": "Maximum series",
            "useother": "Include 'other' category",
        },
        examples=[
            "| chart count over status",
            "| chart avg(response_time) over host by method",
            "| chart sum(bytes) by src_ip limit=10",
        ],
        optimization_notes=[
            "Use limit to reduce high-cardinality splits",
            "Consider timechart when X-axis is time",
        ],
        alternatives=["timechart (for time-series)", "stats (for table output)"],
        transforms_events=True,
    ),

    "fillnull": CommandInfo(
        name="fillnull",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.VERY_LOW,
        description="Replaces null values in fields with a specified value.",
        syntax="fillnull [value=<string>] [<field-list>]",
        common_options={
            "value": "Value to replace nulls with (default: 0)",
        },
        examples=[
            "| fillnull value=0",
            "| fillnull value=\"N/A\" user, department",
            "| timechart count by host | fillnull",
        ],
        optimization_notes=[
            "Lightweight operation",
            "Often used after timechart to fill gaps",
        ],
        alternatives=["eval with coalesce()"],
        streaming=True,
    ),

    "mvexpand": CommandInfo(
        name="mvexpand",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.MEDIUM,
        description="Expands multivalue fields into separate events.",
        syntax="mvexpand <field> [limit=<N>]",
        common_options={
            "limit": "Maximum values to expand",
        },
        examples=[
            "| mvexpand tags",
            "| mvexpand ip_addresses limit=100",
        ],
        optimization_notes=[
            "Can significantly increase event count",
            "Use limit to prevent runaway expansion",
            "Consider mvzip or mvfilter for alternatives",
        ],
        alternatives=["mvzip (combine)", "mvfilter (filter values)"],
        transforms_events=True,
        generates_events=True,
    ),

    "spath": CommandInfo(
        name="spath",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.MEDIUM,
        description="Extracts fields from structured data (JSON, XML).",
        syntax="spath [input=<field>] [output=<field>] [path=<path>]",
        common_options={
            "input": "Field containing structured data (default: _raw)",
            "output": "Field name for extracted value",
            "path": "Path expression for extraction",
        },
        examples=[
            "| spath",
            '| spath input=json_data path="user.name" output=username',
            "| spath path=items{}",
        ],
        optimization_notes=[
            "CPU-intensive for complex structures",
            "Consider indexed extraction in props.conf",
            "Use specific paths instead of extracting all",
        ],
        alternatives=["rex (for regex)", "extract (auto-extraction)"],
        streaming=True,
    ),

    "inputlookup": CommandInfo(
        name="inputlookup",
        category=CommandCategory.GENERATING,
        cost=PerformanceCost.LOW,
        description="Loads events from a lookup table file or KV store collection.",
        syntax="| inputlookup [append=<bool>] <lookup-name> [where <condition>]",
        common_options={
            "append": "Append to existing results",
            "where": "Filter condition (supports basic operations)",
            "max": "Maximum rows to return",
        },
        examples=[
            "| inputlookup users.csv",
            "| inputlookup assets_lookup where status=\"active\"",
            "| inputlookup geo_data max=1000",
        ],
        optimization_notes=[
            "Efficient for loading static data",
            "Use where clause to filter at source",
            "KV store lookups support more complex queries",
        ],
        alternatives=["lookup (for enrichment)"],
        generates_events=True,
    ),

    "outputlookup": CommandInfo(
        name="outputlookup",
        category=CommandCategory.REPORTING,
        cost=PerformanceCost.LOW,
        description="Writes results to a lookup table file or KV store collection.",
        syntax="| outputlookup [append=<bool>] [create_empty=<bool>] <lookup-name>",
        common_options={
            "append": "Append to existing data",
            "create_empty": "Create file even if no results",
            "createinapp": "Create in current app context",
        },
        examples=[
            "| outputlookup daily_stats.csv",
            "| outputlookup append=true alerts_history",
        ],
        optimization_notes=[
            "Check permissions before writing",
            "Consider KV store for large/complex data",
        ],
        alternatives=["collect (for summary indexes)"],
        transforms_events=True,
    ),

    "collect": CommandInfo(
        name="collect",
        category=CommandCategory.REPORTING,
        cost=PerformanceCost.MEDIUM,
        description="Writes results to a summary index for later searching.",
        syntax="| collect index=<index> [source=<source>] [sourcetype=<sourcetype>]",
        common_options={
            "index": "Target summary index",
            "source": "Source value for collected events",
            "sourcetype": "Sourcetype for collected events",
            "marker": "Add marker field",
        },
        examples=[
            "| collect index=summary",
            "| collect index=summary source=daily_report marker=\"report_type=daily\"",
        ],
        optimization_notes=[
            "Target index must exist and be writable",
            "Use for scheduled summary generation",
            "Consider report acceleration as alternative",
        ],
        alternatives=["outputlookup (for lookup tables)"],
        transforms_events=True,
    ),

    "makeresults": CommandInfo(
        name="makeresults",
        category=CommandCategory.GENERATING,
        cost=PerformanceCost.VERY_LOW,
        description="Generates a specified number of empty result rows.",
        syntax="| makeresults [count=<N>] [annotate=<bool>] [splunk_server=<server>]",
        common_options={
            "count": "Number of results to generate (default: 1)",
            "annotate": "Add _time and splunk_server fields",
        },
        examples=[
            "| makeresults",
            "| makeresults count=10 | eval id=random()",
            "| makeresults | eval status=\"Total\", count=0",
        ],
        optimization_notes=[
            "Very efficient for generating test data",
            "Useful for adding summary rows to results",
        ],
        alternatives=[],
        generates_events=True,
    ),

    "format": CommandInfo(
        name="format",
        category=CommandCategory.FORMATTING,
        cost=PerformanceCost.VERY_LOW,
        description="Formats subsearch results as a search string for use in main search.",
        syntax="| format [maxresults=<N>]",
        common_options={
            "maxresults": "Maximum results to include",
        },
        examples=[
            "[search index=blocklist | fields ip | format]",
            "| search [search index=users department=IT | fields user | format]",
        ],
        optimization_notes=[
            "Used automatically in subsearches",
            "Be aware of subsearch result limits",
        ],
        alternatives=[],
        streaming=True,
    ),

    "bin": CommandInfo(
        name="bin",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.VERY_LOW,
        description="Discretizes numeric values into bins (also known as bucket).",
        syntax="bin [span=<span>] [bins=<N>] <field> [as <newfield>]",
        common_options={
            "span": "Size of each bin",
            "bins": "Number of bins",
            "minspan": "Minimum span for auto-bins",
            "aligntime": "Align time bins to specific time",
        },
        examples=[
            "| bin span=1h _time",
            "| bin bins=10 response_time as response_bucket",
            "| bin span=log2 bytes",
        ],
        optimization_notes=[
            "Alias for 'bucket' command",
            "Use for time bucketing before stats",
        ],
        alternatives=["bucket (same command)"],
        streaming=True,
    ),

    "bucket": CommandInfo(
        name="bucket",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.VERY_LOW,
        description="Discretizes numeric values into bins (alias for bin).",
        syntax="bucket [span=<span>] [bins=<N>] <field> [as <newfield>]",
        common_options={
            "span": "Size of each bin",
            "bins": "Number of bins",
        },
        examples=[
            "| bucket span=5m _time",
            "| bucket bins=20 price as price_range",
        ],
        optimization_notes=[
            "Same as 'bin' command",
            "Essential for creating time-based aggregations",
        ],
        alternatives=["bin (same command)"],
        streaming=True,
    ),

    "addtotals": CommandInfo(
        name="addtotals",
        category=CommandCategory.AGGREGATION,
        cost=PerformanceCost.VERY_LOW,
        description="Adds row and column totals to results.",
        syntax="addtotals [row=<bool>] [col=<bool>] [labelfield=<field>] [label=<string>]",
        common_options={
            "row": "Add row totals",
            "col": "Add column totals",
            "fieldname": "Name for totals column",
            "label": "Label for totals row",
        },
        examples=[
            "| stats count by host, status | addtotals",
            "| timechart count by host | addtotals col=t row=f",
        ],
        optimization_notes=[
            "Lightweight for adding summary calculations",
        ],
        alternatives=["eventstats (for adding totals to each row)"],
        streaming=True,
    ),

    "return": CommandInfo(
        name="return",
        category=CommandCategory.FORMATTING,
        cost=PerformanceCost.VERY_LOW,
        description="Returns values from a subsearch to the main search.",
        syntax="return [<N>] [$<field> | <field>=<value>]",
        common_options={
            "$field": "Return field value as search term",
            "field=value": "Return specific field-value pair",
        },
        examples=[
            "[search index=users | return $user]",
            "[search sourcetype=auth failed | return 5 $src_ip]",
        ],
        optimization_notes=[
            "More efficient than format for simple value returns",
            "Useful for passing values between searches",
        ],
        alternatives=["format (for complex returns)"],
        streaming=True,
    ),

    "map": CommandInfo(
        name="map",
        category=CommandCategory.JOINING,
        cost=PerformanceCost.VERY_HIGH,
        description="Runs a search for each result from a previous search.",
        syntax="| map search=\"<search>\" [maxsearches=<N>]",
        common_options={
            "search": "Search to run for each row",
            "maxsearches": "Maximum iterations (default: 10)",
        },
        examples=[
            '| inputlookup servers | map search="search index=os_logs host=$host$ | head 1"',
        ],
        optimization_notes=[
            "VERY expensive - runs multiple searches",
            "Consider using join or lookup instead",
            "Default limit is 10 iterations",
        ],
        alternatives=["join (more efficient)", "lookup (for enrichment)"],
        transforms_events=True,
        distributable=False,
        memory_intensity="very_high",
        cpu_intensity="high",
    ),

    "multisearch": CommandInfo(
        name="multisearch",
        category=CommandCategory.JOINING,
        cost=PerformanceCost.MEDIUM,
        description="Runs multiple searches in parallel and combines results.",
        syntax="| multisearch [<search1>] [<search2>] ...",
        common_options={},
        examples=[
            "| multisearch [search index=web] [search index=app] [search index=db]",
        ],
        optimization_notes=[
            "More efficient than multiple append subsearches",
            "Searches run in parallel",
        ],
        alternatives=["append (sequential)", "union"],
        generates_events=True,
    ),

    "union": CommandInfo(
        name="union",
        category=CommandCategory.JOINING,
        cost=PerformanceCost.MEDIUM,
        description="Combines results from multiple datasets or saved searches.",
        syntax="| union [datamodel:<dm>] [savedsearch:<name>] [<subsearch>]",
        common_options={
            "datamodel": "Include datamodel results",
            "savedsearch": "Include saved search results",
        },
        examples=[
            "| union [search index=a] [search index=b]",
            "| union savedsearch:daily_errors",
        ],
        optimization_notes=[
            "Efficient for combining similar data",
            "Better than multiple append commands",
        ],
        alternatives=["append (for sequential)", "multisearch (for parallel)"],
        generates_events=True,
    ),

    "xmlkv": CommandInfo(
        name="xmlkv",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.MEDIUM,
        description="Extracts key-value pairs from XML-formatted data.",
        syntax="xmlkv [maxinputs=<N>]",
        common_options={
            "maxinputs": "Maximum elements to extract",
        },
        examples=[
            "| xmlkv",
        ],
        optimization_notes=[
            "Use spath for more control over XML parsing",
            "Consider indexed extraction for frequent use",
        ],
        alternatives=["spath (more flexible)"],
        streaming=True,
    ),

    # === METRIC & INFRASTRUCTURE COMMANDS ===

    "mstats": CommandInfo(
        name="mstats",
        category=CommandCategory.AGGREGATION,
        cost=PerformanceCost.VERY_LOW,
        description="Calculates statistics from metric indexes. Much faster than stats for metric data.",
        syntax="| mstats <stats-func>(<metric_name>) [prestats=t] WHERE <filter> [BY <fields>] [span=<time>]",
        common_options={
            "prestats": "Enable pre-stats for distributed search",
            "WHERE": "Filter metric data",
            "span": "Time bucket size",
            "fillnull_value": "Fill null values",
        },
        examples=[
            "| mstats avg(cpu.idle) WHERE index=metrics host=web* BY host span=5m",
            "| mstats max(mem.used) prestats=t WHERE metric_name=mem.* BY host span=1h",
        ],
        optimization_notes=[
            "Use instead of stats for metric indexes — reads metric store directly",
            "Requires metric index (not event index)",
            "Use prestats=t for distributed search optimization",
        ],
        alternatives=["stats (for event indexes)", "tstats (for accelerated event data)"],
        streaming=True,
        generates_events=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "mcatalog": CommandInfo(
        name="mcatalog",
        category=CommandCategory.GENERATING,
        cost=PerformanceCost.VERY_LOW,
        description="Lists available metrics, dimensions, and metric index metadata.",
        syntax="| mcatalog values(<field>) WHERE index=<metric_index> [BY <dimension>]",
        common_options={
            "values": "List unique values of metric_name or dimension",
            "WHERE": "Filter by index or dimension",
        },
        examples=[
            "| mcatalog values(metric_name) WHERE index=metrics",
            "| mcatalog values(host) WHERE index=metrics metric_name=cpu.*",
        ],
        optimization_notes=[
            "Very fast — reads metadata, not actual metric data",
            "Use to discover available metrics before writing mstats queries",
        ],
        alternatives=[],
        generates_events=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "rest": CommandInfo(
        name="rest",
        category=CommandCategory.GENERATING,
        cost=PerformanceCost.MEDIUM,
        description="Accesses Splunk REST API endpoints. Used for system introspection.",
        syntax="| rest <endpoint> [splunk_server=<server>] [count=<N>]",
        common_options={
            "splunk_server": "Target server (default: local)",
            "count": "Limit results",
            "timeout": "Request timeout",
        },
        examples=[
            "| rest /services/saved/searches",
            "| rest /services/data/indexes splunk_server=*",
        ],
        optimization_notes=[
            "Hits REST API — can be slow on large clusters",
            "splunk_server=* queries ALL servers (expensive)",
            "Cache results if querying frequently",
        ],
        alternatives=[],
        generates_events=True,
        distributable=False,
        memory_intensity="medium",
        cpu_intensity="low",
    ),

    "metadata": CommandInfo(
        name="metadata",
        category=CommandCategory.GENERATING,
        cost=PerformanceCost.VERY_LOW,
        description="Returns metadata about sources, sourcetypes, or hosts in an index.",
        syntax="| metadata type=<sources|sourcetypes|hosts> index=<index>",
        common_options={
            "type": "sources, sourcetypes, or hosts",
            "index": "Index to query",
        },
        examples=[
            "| metadata type=sourcetypes index=main",
            "| metadata type=hosts index=security | sort -recentTime",
        ],
        optimization_notes=[
            "Extremely fast — reads index metadata only",
            "Use instead of 'stats dc(sourcetype) by index' for metadata queries",
        ],
        alternatives=["rest (for more detailed index info)"],
        generates_events=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    # === DATA MODEL COMMANDS ===

    "from": CommandInfo(
        name="from",
        category=CommandCategory.GENERATING,
        cost=PerformanceCost.LOW,
        description="Retrieves data from data models, lookup tables, or saved searches.",
        syntax="| from datamodel:<name>.<dataset> | from lookup:<name> | from savedsearch:<name>",
        common_options={},
        examples=[
            "| from datamodel:Network_Traffic.All_Traffic",
            "| from lookup:assets_lookup",
            "| from savedsearch:daily_errors",
        ],
        optimization_notes=[
            "Efficient for accessing accelerated data models",
            "Uses acceleration summaries when available",
        ],
        alternatives=["tstats (for raw indexed data)", "inputlookup (for lookup tables)"],
        generates_events=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "datamodel": CommandInfo(
        name="datamodel",
        category=CommandCategory.GENERATING,
        cost=PerformanceCost.VERY_LOW,
        description="Returns information about data model objects or searches within them.",
        syntax="| datamodel <model_name> <dataset_name> search | ...",
        common_options={},
        examples=[
            "| datamodel Network_Traffic All_Traffic search | stats count by All_Traffic.src",
        ],
        optimization_notes=[
            "Uses data model acceleration for fast queries",
            "Preferred for CIM-compliant searches",
        ],
        alternatives=["from (simpler syntax)", "tstats from datamodel (faster)"],
        generates_events=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    # === ADDITIONAL AGGREGATION COMMANDS ===

    "top": CommandInfo(
        name="top",
        category=CommandCategory.AGGREGATION,
        cost=PerformanceCost.LOW,
        description="Returns the most frequent values for specified fields.",
        syntax="top [<N>] <field-list> [by <split-field>] [showperc=<bool>]",
        common_options={
            "limit": "Maximum results (default: 10)",
            "showperc": "Show percentage (default: true)",
            "countfield": "Name for count field",
        },
        examples=[
            "| top 20 user",
            "| top src_ip by host limit=10",
            "| top action showperc=f",
        ],
        optimization_notes=[
            "Distributable — runs efficiently on indexers",
            "More efficient than stats count by field | sort -count | head N",
        ],
        alternatives=["stats count by field | sort -count | head N (more flexible)"],
        transforms_events=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "rare": CommandInfo(
        name="rare",
        category=CommandCategory.AGGREGATION,
        cost=PerformanceCost.LOW,
        description="Returns the least frequent values for specified fields.",
        syntax="rare [<N>] <field-list> [by <split-field>]",
        common_options={
            "limit": "Maximum results (default: 10)",
            "showperc": "Show percentage",
        },
        examples=[
            "| rare 10 user",
            "| rare status_code by host",
        ],
        optimization_notes=[
            "Distributable — runs efficiently on indexers",
            "Useful for finding outliers or uncommon values",
        ],
        alternatives=["stats count by field | sort count | head N"],
        transforms_events=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "pivot": CommandInfo(
        name="pivot",
        category=CommandCategory.REPORTING,
        cost=PerformanceCost.MEDIUM,
        description="Generates pivot table reports from data models.",
        syntax="| pivot <datamodel> <dataset> <cell-value> <split-row> <split-col>",
        common_options={},
        examples=[
            "| pivot Network_Traffic All_Traffic count(All_Traffic) splitrow host splitcol action",
        ],
        optimization_notes=[
            "Works best with accelerated data models",
            "Use tstats for better performance on similar queries",
        ],
        alternatives=["tstats (faster for indexed data)", "chart (for manual pivots)"],
        transforms_events=True,
        distributable=True,
        memory_intensity="medium",
        cpu_intensity="medium",
    ),

    # === ADDITIONAL TRANSFORM COMMANDS ===

    "foreach": CommandInfo(
        name="foreach",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.MEDIUM,
        description="Runs an eval expression iteratively over a set of fields.",
        syntax='foreach <field-list> [<eval-expression>]',
        common_options={
            "<<FIELD>>": "Placeholder for current field name in eval",
        },
        examples=[
            '| foreach * [eval <<FIELD>>=if(<<FIELD>>="N/A",null(),<<FIELD>>)]',
            '| foreach cpu_* [eval <<FIELD>>=round(<<FIELD>>,2)]',
        ],
        optimization_notes=[
            "Efficient for applying same operation to many fields",
            "Better than multiple eval commands for column operations",
        ],
        alternatives=["eval (for individual fields)"],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="medium",
    ),

    "regex": CommandInfo(
        name="regex",
        category=CommandCategory.FILTERING,
        cost=PerformanceCost.MEDIUM,
        description="Filters events using regular expressions.",
        syntax='regex <field>=<regex> | regex <field>!="<regex>"',
        common_options={},
        examples=[
            '| regex _raw="error|fail|critical"',
            '| regex src_ip="^10\\.1\\..*"',
        ],
        optimization_notes=[
            "CPU-intensive — pre-filter with search/where when possible",
            "Consider TERM() or PREFIX() for literal string matching",
        ],
        alternatives=["where match() (more flexible)", "search (for simple patterns)"],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="high",
    ),

    "convert": CommandInfo(
        name="convert",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.VERY_LOW,
        description="Converts field values between formats (number, duration, time, etc.).",
        syntax="convert <function>(<field>) [as <alias>]",
        common_options={
            "dur2sec": "Duration to seconds",
            "num": "Convert to number",
            "ctime": "Epoch to readable time",
            "mktime": "Readable time to epoch",
            "memk": "Memory string to kilobytes",
        },
        examples=[
            "| convert dur2sec(duration) as duration_sec",
            "| convert ctime(_time) as readable_time",
        ],
        optimization_notes=[
            "Lightweight operation",
            "Often replaceable with eval for more flexibility",
        ],
        alternatives=["eval (more flexible type conversion)"],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "replace": CommandInfo(
        name="replace",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.VERY_LOW,
        description="Replaces field values using wildcards.",
        syntax='replace <old> WITH <new> [IN <field-list>]',
        common_options={},
        examples=[
            '| replace "ERROR" WITH "E", "WARNING" WITH "W" IN severity',
        ],
        optimization_notes=[
            "Lightweight string replacement",
        ],
        alternatives=["eval replace() (more flexible)"],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "multikv": CommandInfo(
        name="multikv",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.MEDIUM,
        description="Extracts key-value pairs from table-formatted text data.",
        syntax="multikv [forceheader=<N>] [filter <field-list>]",
        common_options={
            "forceheader": "Force specific line as header",
            "filter": "Only extract specific fields",
        },
        examples=[
            "| multikv forceheader=1 filter USER PID %CPU",
        ],
        optimization_notes=[
            "Useful for parsing CLI output (ps, df, netstat)",
            "Can be CPU-intensive on large volumes",
        ],
        alternatives=["rex (for more control)"],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="medium",
    ),

    "erex": CommandInfo(
        name="erex",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.HIGH,
        description="Automatically generates regex to extract fields based on examples.",
        syntax='erex <field> fromfield=<source_field> examples="<example1>,<example2>"',
        common_options={
            "fromfield": "Source field to extract from",
            "examples": "Example values to match",
        },
        examples=[
            '| erex ip_address fromfield=_raw examples="192.168.1.1,10.0.0.1"',
        ],
        optimization_notes=[
            "CPU-intensive — generates and tests regex patterns",
            "Use for prototyping, then convert to rex for production",
        ],
        alternatives=["rex (when regex pattern is known)"],
        streaming=True,
        distributable=True,
        memory_intensity="medium",
        cpu_intensity="high",
    ),

    # === STREAMING/ORDER-DEPENDENT COMMANDS ===

    "trendline": CommandInfo(
        name="trendline",
        category=CommandCategory.STREAMING,
        cost=PerformanceCost.MEDIUM,
        description="Calculates moving averages (SMA, EMA, WMA) for time-series data.",
        syntax="trendline <type><period>(<field>) [as <alias>]",
        common_options={
            "sma": "Simple moving average",
            "ema": "Exponential moving average",
            "wma": "Weighted moving average",
        },
        examples=[
            "| trendline sma5(count) as moving_avg",
            "| trendline ema10(response_time) as trend",
        ],
        optimization_notes=[
            "Non-distributable — runs on search head only",
            "Sort data by _time before using trendline",
        ],
        alternatives=["streamstats (more flexible windowed calculations)"],
        streaming=True,
        distributable=False,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "accum": CommandInfo(
        name="accum",
        category=CommandCategory.STREAMING,
        cost=PerformanceCost.LOW,
        description="Calculates a running total for a numeric field.",
        syntax="accum <field> [as <alias>]",
        common_options={},
        examples=[
            "| sort _time | accum bytes as running_total",
        ],
        optimization_notes=[
            "Non-distributable — order-dependent",
            "Sort data first for meaningful results",
        ],
        alternatives=["streamstats sum() (more flexible)"],
        streaming=True,
        distributable=False,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "autoregress": CommandInfo(
        name="autoregress",
        category=CommandCategory.STREAMING,
        cost=PerformanceCost.LOW,
        description="Sets up data dependency on previous events for time-series analysis.",
        syntax="autoregress <field> [as <alias>] [p=<N>]",
        common_options={
            "p": "Number of prior values to include",
        },
        examples=[
            "| sort _time | autoregress count as prev_count p=1",
        ],
        optimization_notes=[
            "Non-distributable — depends on event order",
            "Sort by _time before using",
        ],
        alternatives=["streamstats (more flexible)"],
        streaming=True,
        distributable=False,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "delta": CommandInfo(
        name="delta",
        category=CommandCategory.STREAMING,
        cost=PerformanceCost.LOW,
        description="Calculates the difference between consecutive values of a field.",
        syntax="delta <field> [as <alias>] [p=<N>]",
        common_options={
            "p": "Compare with Nth previous event",
        },
        examples=[
            "| sort _time | delta bytes as bytes_diff",
        ],
        optimization_notes=[
            "Non-distributable — depends on event order",
            "Sort by _time before using",
        ],
        alternatives=["streamstats (more flexible windowed calculations)"],
        streaming=True,
        distributable=False,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "concurrency": CommandInfo(
        name="concurrency",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.MEDIUM,
        description="Calculates concurrent events over time based on duration fields.",
        syntax="concurrency duration=<field>",
        common_options={
            "duration": "Field containing event duration",
        },
        examples=[
            "| concurrency duration=duration",
        ],
        optimization_notes=[
            "Non-distributable — needs all events in time order",
            "Useful for calculating concurrent sessions/requests",
        ],
        alternatives=["timechart with span for approximate concurrency"],
        streaming=False,
        distributable=False,
        memory_intensity="medium",
        cpu_intensity="medium",
    ),

    # === JOINING / COMBINING COMMANDS ===

    "appendcols": CommandInfo(
        name="appendcols",
        category=CommandCategory.JOINING,
        cost=PerformanceCost.HIGH,
        description="Appends the results of a subsearch as new columns.",
        syntax="appendcols [override=<bool>] [<subsearch>]",
        common_options={
            "override": "Override existing fields (default: false)",
        },
        examples=[
            "index=main | stats count | appendcols [search index=errors | stats count as error_count]",
        ],
        optimization_notes=[
            "Buffers both result sets in memory",
            "Joins by row number, not field values",
            "Consider stats or eval as alternatives",
        ],
        alternatives=["stats (for same-search aggregation)", "join (for field-based joining)"],
        transforms_events=True,
        distributable=False,
        memory_intensity="high",
        cpu_intensity="low",
    ),

    "appendpipe": CommandInfo(
        name="appendpipe",
        category=CommandCategory.JOINING,
        cost=PerformanceCost.MEDIUM,
        description="Appends the result of a pipeline applied to current results.",
        syntax="appendpipe [run_in_preview=<bool>] [<pipeline>]",
        common_options={},
        examples=[
            '| stats count by host | appendpipe [stats sum(count) as count | eval host="Total"]',
        ],
        optimization_notes=[
            "Useful for adding summary rows",
            "Runs the pipeline on a copy of current results",
        ],
        alternatives=["addtotals (for simple totals)"],
        transforms_events=True,
        memory_intensity="medium",
        cpu_intensity="low",
    ),

    # === ORDERING COMMANDS ===

    "reverse": CommandInfo(
        name="reverse",
        category=CommandCategory.ORDERING,
        cost=PerformanceCost.LOW,
        description="Reverses the order of results.",
        syntax="reverse",
        common_options={},
        examples=[
            "| sort _time | reverse",
        ],
        optimization_notes=[
            "Must collect all results before reversing",
            "Consider using sort with -/+ to avoid separate reverse",
        ],
        alternatives=["sort (with reversed direction)"],
        streaming=False,
        distributable=False,
        memory_intensity="medium",
        cpu_intensity="low",
    ),

    "uniq": CommandInfo(
        name="uniq",
        category=CommandCategory.FILTERING,
        cost=PerformanceCost.LOW,
        description="Removes consecutive duplicate events (must be sorted first).",
        syntax="uniq",
        common_options={},
        examples=[
            "| sort user, _time | uniq",
        ],
        optimization_notes=[
            "Only removes CONSECUTIVE duplicates — sort first",
            "dedup is usually more practical (doesn't require sorting)",
        ],
        alternatives=["dedup (for global dedup without sorting)"],
        streaming=False,
        distributable=False,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    # === ML / ANALYTICS COMMANDS ===

    "predict": CommandInfo(
        name="predict",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.HIGH,
        description="Predicts future values using machine learning algorithms.",
        syntax="predict <field> [algorithm=<name>] [future_timespan=<N>]",
        common_options={
            "algorithm": "LLP, LLP5, LLT, LLT5, BiLLP",
            "future_timespan": "Number of future periods to predict",
            "holdback": "Events to hold back for validation",
        },
        examples=[
            "| timechart count | predict count future_timespan=24",
        ],
        optimization_notes=[
            "Must see entire time series — non-distributable",
            "Sort by _time before using predict",
            "Memory usage scales with event count",
        ],
        alternatives=["trendline (for simple moving averages)"],
        transforms_events=True,
        distributable=False,
        memory_intensity="high",
        cpu_intensity="high",
    ),

    "anomalydetection": CommandInfo(
        name="anomalydetection",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.VERY_HIGH,
        description="Detects anomalies in data using machine learning.",
        syntax="anomalydetection [method=<name>] [<field-list>]",
        common_options={
            "method": "histogram, IQR",
            "pthresh": "P-value threshold",
            "action": "annotate, filter, summary",
        },
        examples=[
            "| anomalydetection method=histogram response_time",
        ],
        optimization_notes=[
            "Very expensive — requires full dataset in memory",
            "Pre-aggregate or sample data before running",
            "Consider threshold-based alerting for simple cases",
        ],
        alternatives=["outlier (simpler)", "predict (for time-series anomalies)"],
        transforms_events=True,
        distributable=False,
        memory_intensity="very_high",
        cpu_intensity="high",
    ),

    "cluster": CommandInfo(
        name="cluster",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.VERY_HIGH,
        description="Groups events into clusters based on similarity.",
        syntax="cluster [t=<threshold>] [showcount=<bool>] [labelonly=<bool>]",
        common_options={
            "t": "Similarity threshold (0-1, default: 0.8)",
            "showcount": "Show cluster sizes",
            "field": "Field to cluster on",
        },
        examples=[
            "| cluster t=0.9 showcount=t",
        ],
        optimization_notes=[
            "Extremely expensive — loads all events into memory",
            "Pre-filter to reduce event count before clustering",
            "Not suitable for large datasets (>100K events)",
        ],
        alternatives=["rex + stats (for pattern-based grouping)"],
        transforms_events=True,
        distributable=False,
        memory_intensity="very_high",
        cpu_intensity="high",
    ),

    "kmeans": CommandInfo(
        name="kmeans",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.VERY_HIGH,
        description="K-means clustering algorithm for numeric data.",
        syntax="kmeans k=<N> [<field-list>]",
        common_options={
            "k": "Number of clusters",
        },
        examples=[
            "| stats avg(response_time) avg(bytes) by host | kmeans k=3",
        ],
        optimization_notes=[
            "Requires ALL data in memory",
            "Pre-aggregate before clustering for performance",
            "Only works with numeric fields",
        ],
        alternatives=["cluster (for text-based grouping)"],
        transforms_events=True,
        distributable=False,
        memory_intensity="very_high",
        cpu_intensity="high",
    ),

    # === REPORTING / OUTPUT COMMANDS ===

    "delete": CommandInfo(
        name="delete",
        category=CommandCategory.REPORTING,
        cost=PerformanceCost.VERY_HIGH,
        description="Permanently deletes events from an index. DANGEROUS - cannot be undone.",
        syntax="| delete",
        common_options={},
        examples=[
            "index=test sourcetype=temp_data earliest=-30d | delete",
        ],
        optimization_notes=[
            "PERMANENTLY removes events — cannot be undone",
            "Requires 'delete_by_keyword' capability",
            "Actually masks events until bucket rolls",
        ],
        alternatives=["Archive or freeze buckets instead"],
        transforms_events=True,
        distributable=False,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "sendemail": CommandInfo(
        name="sendemail",
        category=CommandCategory.REPORTING,
        cost=PerformanceCost.LOW,
        description="Sends search results via email.",
        syntax='sendemail to=<email> subject=<text> [format=<csv|table|raw>]',
        common_options={
            "to": "Recipient email address(es)",
            "subject": "Email subject",
            "format": "Output format (csv, table, raw)",
        },
        examples=[
            '| sendemail to="admin@company.com" subject="Alert: High Error Rate"',
        ],
        optimization_notes=[
            "Typically used in saved searches / alerts",
            "Ensure email server is configured in server.conf",
        ],
        alternatives=[],
        transforms_events=True,
    ),

    # === FORMATTING / RESHAPING COMMANDS ===

    "xyseries": CommandInfo(
        name="xyseries",
        category=CommandCategory.FORMATTING,
        cost=PerformanceCost.LOW,
        description="Converts results into a table format with dynamic columns.",
        syntax="xyseries <x-field> <y-field> <data-field>",
        common_options={},
        examples=[
            "| stats count by host, status | xyseries host status count",
        ],
        optimization_notes=[
            "Memory usage depends on cardinality of y-field",
            "Creates one column per unique y-field value",
        ],
        alternatives=["chart (produces similar pivoted output directly)"],
        transforms_events=True,
    ),

    "untable": CommandInfo(
        name="untable",
        category=CommandCategory.FORMATTING,
        cost=PerformanceCost.LOW,
        description="Converts a table with multiple columns into rows (unpivot).",
        syntax="untable <x-field> <y-field> <data-field>",
        common_options={},
        examples=[
            "| untable host metric_name value",
        ],
        optimization_notes=[
            "Inverse of xyseries — converts columns back to rows",
            "Can significantly increase row count",
        ],
        alternatives=["mvexpand (for multivalue fields)"],
        transforms_events=True,
        generates_events=True,
    ),

    # === SUMMARY INDEXING COMMANDS ===

    "sistats": CommandInfo(
        name="sistats",
        category=CommandCategory.AGGREGATION,
        cost=PerformanceCost.LOW,
        description="Summary indexing variant of stats. Used in summary index scheduled searches.",
        syntax="sistats <stats-func>(<field>) [by <field-list>]",
        common_options={},
        examples=[
            "| sistats count by host",
        ],
        optimization_notes=[
            "Use with | collect for summary indexing",
            "Distributable — runs on indexers",
        ],
        alternatives=["stats (for normal aggregation)"],
        transforms_events=True,
        distributable=True,
        memory_intensity="medium",
        cpu_intensity="low",
    ),

    "sitimechart": CommandInfo(
        name="sitimechart",
        category=CommandCategory.AGGREGATION,
        cost=PerformanceCost.LOW,
        description="Summary indexing variant of timechart.",
        syntax="sitimechart [span=<time>] <stats-func>(<field>) [by <split-field>]",
        common_options={},
        examples=[
            "| sitimechart span=1h count by host",
        ],
        optimization_notes=[
            "Use with | collect for summary indexing",
            "Distributable — runs on indexers",
        ],
        alternatives=["timechart (for normal aggregation)"],
        transforms_events=True,
        distributable=True,
        memory_intensity="medium",
        cpu_intensity="low",
    ),

    # === MULTIVALUE OPERATIONS ===

    "mvcombine": CommandInfo(
        name="mvcombine",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.MEDIUM,
        description="Combines values of a field from multiple events into a single multivalue field.",
        syntax="mvcombine [delim=<string>] <field>",
        common_options={
            "delim": "Delimiter between values",
        },
        examples=[
            "| stats count by user, action | mvcombine action",
            "| mvcombine delim=\" \" tags",
        ],
        optimization_notes=[
            "Inverse of mvexpand — collapses rows into multivalue",
            "Memory-intensive with high-cardinality grouping",
        ],
        alternatives=["stats values() (similar grouping in one step)"],
        transforms_events=True,
        distributable=True,
        memory_intensity="medium",
        cpu_intensity="low",
    ),

    "mvfilter": CommandInfo(
        name="mvfilter",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.LOW,
        description="Filters values in a multivalue field using an expression.",
        syntax="mvfilter <eval-expression>",
        common_options={},
        examples=[
            '| mvfilter(match(ip, "^10\\."))',
            "| mvfilter(status >= 400)",
            '| eval errors=mvfilter(match(events, "error|fail"))',
        ],
        optimization_notes=[
            "Efficient inline multivalue filtering",
            "Evaluates expression against each value individually",
        ],
        alternatives=["mvexpand + where + mvcombine (more verbose equivalent)"],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "makemv": CommandInfo(
        name="makemv",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.LOW,
        description="Converts a single-value field to multivalue by splitting on a delimiter.",
        syntax='makemv [delim=<string>] [tokenizer=<regex>] <field>',
        common_options={
            "delim": "Delimiter character/string",
            "tokenizer": "Regex for splitting",
            "setsv": "Also set single-value representation",
        },
        examples=[
            '| makemv delim="," tags',
            '| makemv tokenizer="(\\w+)" message',
        ],
        optimization_notes=[
            "Lightweight operation",
            "Use delim for simple splits, tokenizer for complex patterns",
        ],
        alternatives=["eval split() (in eval context)"],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "nomv": CommandInfo(
        name="nomv",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.VERY_LOW,
        description="Converts a multivalue field to single-value (uses first value).",
        syntax="nomv <field>",
        common_options={},
        examples=[
            "| nomv tags",
        ],
        optimization_notes=[
            "Very lightweight — just takes first value",
        ],
        alternatives=["eval mvindex(field, 0) (explicit first value)"],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    # === GEOSPATIAL COMMANDS ===

    "iplocation": CommandInfo(
        name="iplocation",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.LOW,
        description="Adds geographic information (city, country, lat, lon) based on IP address.",
        syntax="iplocation [prefix=<string>] [allfields=<bool>] <ip-field>",
        common_options={
            "prefix": "Prefix for output field names",
            "allfields": "Include all geo fields (default: true)",
            "lang": "Language for place names",
        },
        examples=[
            "| iplocation src_ip",
            "| iplocation prefix=src_ allfields=true clientip",
        ],
        optimization_notes=[
            "Uses local MaxMind GeoIP database — fast lookup",
            "Place after filtering to reduce lookups",
            "Only works with public IP addresses (RFC 1918 addresses return no results)",
        ],
        alternatives=["lookup with custom geo table"],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "geostats": CommandInfo(
        name="geostats",
        category=CommandCategory.AGGREGATION,
        cost=PerformanceCost.MEDIUM,
        description="Generates statistics for geographic data visualization on cluster maps.",
        syntax="geostats [latfield=<field>] [longfield=<field>] <stats-func> [by <field>]",
        common_options={
            "latfield": "Latitude field",
            "longfield": "Longitude field",
            "globallimit": "Max clusters globally",
            "locallimit": "Max clusters per tile",
            "binspanlat": "Latitude bin span",
            "binspanlong": "Longitude bin span",
        },
        examples=[
            "| iplocation src_ip | geostats count by action",
            "| geostats latfield=lat longfield=lon sum(bytes) by host",
        ],
        optimization_notes=[
            "Use iplocation first to get lat/lon from IP addresses",
            "globallimit controls memory usage and rendering speed",
        ],
        alternatives=["stats with lat/lon grouping (manual approach)"],
        transforms_events=True,
        distributable=True,
        memory_intensity="medium",
        cpu_intensity="medium",
    ),

    "geom": CommandInfo(
        name="geom",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.LOW,
        description="Adds geographic boundary features for choropleth map visualization.",
        syntax="geom <featureCollection> [featureIdField=<field>]",
        common_options={
            "featureIdField": "Field to match with geographic features",
        },
        examples=[
            "| stats count by Country | geom geo_countries featureIdField=Country",
        ],
        optimization_notes=[
            "Requires geographic feature collections (KMZ/KML files)",
        ],
        alternatives=[],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    # === ANALYTICS / ML COMMANDS ===

    "outlier": CommandInfo(
        name="outlier",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.MEDIUM,
        description="Removes outliers from numeric fields based on standard deviation.",
        syntax="outlier [action=<remove|transform>] [param=<N>] [<field-list>]",
        common_options={
            "action": "remove (filter) or transform (mark) outliers",
            "param": "Number of standard deviations for threshold (default: 3)",
            "uselower": "Include lower bound outliers",
        },
        examples=[
            "| outlier action=remove param=2.5 response_time",
            "| outlier action=transform bytes",
        ],
        optimization_notes=[
            "Requires full dataset in memory to compute statistics",
            "Consider pre-aggregation to reduce data volume",
        ],
        alternatives=["anomalydetection (more sophisticated)", "where with stats (manual threshold)"],
        transforms_events=True,
        distributable=False,
        memory_intensity="medium",
        cpu_intensity="medium",
    ),

    "abstract": CommandInfo(
        name="abstract",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.MEDIUM,
        description="Produces a summary (abstract) of each event by extracting key sentences.",
        syntax="abstract [maxterms=<N>] [maxlines=<N>]",
        common_options={
            "maxterms": "Maximum terms in abstract",
            "maxlines": "Maximum lines in abstract",
        },
        examples=[
            "| abstract maxlines=3",
        ],
        optimization_notes=[
            "CPU-intensive text processing",
            "Use after filtering to reduce event count",
        ],
        alternatives=["rex (for specific field extraction)"],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="medium",
    ),

    "reltime": CommandInfo(
        name="reltime",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.VERY_LOW,
        description="Adds a reltime field showing relative time (e.g., '2 hours ago').",
        syntax="reltime",
        common_options={},
        examples=[
            "| reltime | table _time, reltime, message",
        ],
        optimization_notes=[
            "Very lightweight — simple time formatting",
        ],
        alternatives=["eval with strftime()"],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "transpose": CommandInfo(
        name="transpose",
        category=CommandCategory.FORMATTING,
        cost=PerformanceCost.LOW,
        description="Transposes rows and columns in results (pivot).",
        syntax="transpose [<N>] [column_name=<field>] [header_field=<field>]",
        common_options={
            "column_name": "Name for generated column",
            "header_field": "Field to use as column headers",
        },
        examples=[
            "| stats count by status | transpose",
            "| transpose 5 column_name=metric header_field=host",
        ],
        optimization_notes=[
            "Loads all results before transposing",
            "Row count becomes column count — beware high cardinality",
        ],
        alternatives=["xyseries (for pivoting with aggregation)"],
        transforms_events=True,
        memory_intensity="medium",
        cpu_intensity="low",
    ),

    "selfjoin": CommandInfo(
        name="selfjoin",
        category=CommandCategory.JOINING,
        cost=PerformanceCost.HIGH,
        description="Joins results with themselves on specified fields.",
        syntax="selfjoin <field-list> [max=<N>] [overwrite=<bool>]",
        common_options={
            "max": "Maximum matches per event",
            "overwrite": "Overwrite existing fields",
        },
        examples=[
            "| selfjoin session_id",
        ],
        optimization_notes=[
            "Buffers entire result set — very memory-intensive",
            "Consider stats or streamstats as alternatives",
        ],
        alternatives=["stats (for aggregation)", "streamstats (for sequential comparison)"],
        transforms_events=True,
        distributable=False,
        memory_intensity="very_high",
        cpu_intensity="medium",
    ),

    "set": CommandInfo(
        name="set",
        category=CommandCategory.JOINING,
        cost=PerformanceCost.MEDIUM,
        description="Performs set operations (union, intersect, diff) between subsearches.",
        syntax="| set <union|intersect|diff> [<subsearch1>] [<subsearch2>]",
        common_options={},
        examples=[
            "| set diff [search index=a | fields user] [search index=b | fields user]",
            "| set intersect [search index=auth | fields user] [search index=vpn | fields user]",
        ],
        optimization_notes=[
            "Buffers both result sets in memory",
            "Consider stats + eval as alternative for simple operations",
        ],
        alternatives=["stats with eval (for union/intersect logic)"],
        transforms_events=True,
        distributable=False,
        memory_intensity="high",
        cpu_intensity="low",
    ),

    "fieldsummary": CommandInfo(
        name="fieldsummary",
        category=CommandCategory.REPORTING,
        cost=PerformanceCost.MEDIUM,
        description="Generates summary statistics for all fields in the results.",
        syntax="fieldsummary [maxvals=<N>] [<field-list>]",
        common_options={
            "maxvals": "Max distinct values to show (default: 100)",
        },
        examples=[
            "| fieldsummary",
            "| fieldsummary maxvals=10 src_ip dest_ip user",
        ],
        optimization_notes=[
            "Scans all events to compute statistics",
            "Useful for data exploration and schema discovery",
        ],
        alternatives=["stats dc() + values() (for specific field analysis)"],
        transforms_events=True,
        memory_intensity="medium",
        cpu_intensity="medium",
    ),

    "gentimes": CommandInfo(
        name="gentimes",
        category=CommandCategory.GENERATING,
        cost=PerformanceCost.VERY_LOW,
        description="Generates time-based events for a range of dates.",
        syntax="| gentimes start=<time> end=<time> [increment=<span>]",
        common_options={
            "start": "Start time",
            "end": "End time",
            "increment": "Time between events",
        },
        examples=[
            '| gentimes start=1 end=30 increment=1d',
        ],
        optimization_notes=[
            "Very lightweight — just generates timestamps",
            "Useful for creating time-based scaffolding",
        ],
        alternatives=["makeresults with eval (more flexible)"],
        generates_events=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "loadjob": CommandInfo(
        name="loadjob",
        category=CommandCategory.GENERATING,
        cost=PerformanceCost.LOW,
        description="Loads results from a previously completed search job.",
        syntax="| loadjob <sid> [events=<bool>] [artifact_offset=<N>]",
        common_options={
            "events": "Load events vs results",
            "artifact_offset": "Start from specific offset",
        },
        examples=[
            "| loadjob 1234567890.123",
        ],
        optimization_notes=[
            "Reads from dispatch directory — fast for recent jobs",
            "Jobs expire based on dispatch TTL settings",
        ],
        alternatives=[],
        generates_events=True,
        distributable=False,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "filldown": CommandInfo(
        name="filldown",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.VERY_LOW,
        description="Fills null values in a field with the most recent non-null value.",
        syntax="filldown [<field-list>]",
        common_options={},
        examples=[
            "| filldown user session_id",
        ],
        optimization_notes=[
            "Very lightweight streaming operation",
            "Useful for sparse data after timechart",
        ],
        alternatives=["streamstats (for more complex fill logic)"],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),

    "rangemap": CommandInfo(
        name="rangemap",
        category=CommandCategory.TRANSFORM,
        cost=PerformanceCost.VERY_LOW,
        description="Maps numeric values to named ranges (low, elevated, severe).",
        syntax="rangemap field=<field> <range-name>=<min>-<max> [default=<name>]",
        common_options={
            "field": "Field to evaluate",
            "default": "Default range name when no range matches",
        },
        examples=[
            "| rangemap field=cpu_pct low=0-60 elevated=61-85 severe=86-100 default=unknown",
        ],
        optimization_notes=[
            "Very lightweight — simple range comparison",
            "Alternative to complex eval case() expressions for numeric ranges",
        ],
        alternatives=["eval case() (more flexible conditional logic)"],
        streaming=True,
        distributable=True,
        memory_intensity="low",
        cpu_intensity="low",
    ),
}


# Common anti-patterns and their fixes
ANTI_PATTERNS = [
    {
        "pattern": r"index\s*=\s*\*",
        "name": "Wildcard index",
        "severity": "high",
        "explanation": "Searching all indexes is extremely slow and resource-intensive.",
        "fix": "Specify the exact index(es) you need: index=main OR index=security",
    },
    {
        "pattern": r"^\s*\*\s*\|",
        "name": "No base search filter",
        "severity": "high",
        "explanation": "Starting with '* |' scans all events before filtering.",
        "fix": "Add specific index, sourcetype, or keyword filters before the first pipe.",
    },
    {
        "pattern": r"\|\s*join\b",
        "name": "Using join command",
        "severity": "medium",
        "explanation": "Join is expensive and has subsearch limits. Consider alternatives.",
        "fix": "Use lookup for enrichment, or stats for aggregation-based joins.",
    },
    {
        "pattern": r"\|\s*transaction\b",
        "name": "Using transaction command",
        "severity": "high",
        "explanation": "Transaction is one of the most expensive commands. It holds all events in memory.",
        "fix": "Use stats with earliest(_time), latest(_time), and duration calculation instead.",
    },
    {
        "pattern": r"\|\s*append\s*\[",
        "name": "Using append with subsearch",
        "severity": "medium",
        "explanation": "Subsearches have result limits and can be slow.",
        "fix": "Consider using union command or restructuring the search.",
    },
    {
        "pattern": r"NOT\s+\w+\s*=",
        "name": "NOT with field=value",
        "severity": "low",
        "explanation": "NOT conditions cannot use index optimization.",
        "fix": "If possible, filter positively instead of negatively.",
    },
    {
        "pattern": r"\beval\b.*\beval\b.*\beval\b",
        "name": "Multiple separate eval commands",
        "severity": "low",
        "explanation": "Multiple eval commands can be combined for efficiency.",
        "fix": "Combine into one eval: | eval field1=expr1, field2=expr2, field3=expr3",
    },
    {
        "pattern": r"\|\s*table\b.*\|\s*(?!$)",
        "name": "Table not at end of search",
        "severity": "low",
        "explanation": "Table should typically be the final command for display.",
        "fix": "Move table to the end, or use fields command for intermediate field selection.",
    },
    {
        "pattern": r"earliest\s*=\s*0",
        "name": "Unbounded earliest time",
        "severity": "high",
        "explanation": "earliest=0 searches all time, which is very expensive.",
        "fix": "Set a reasonable time range: earliest=-24h or earliest=-7d",
    },
    {
        "pattern": r"\|\s*eventstats\s+\w+\s*\([^)]*\)(?:\s+as\s+\w+)?\s*$",
        "name": "eventstats without BY clause",
        "severity": "high",
        "explanation": "eventstats without BY clause computes across ALL events, requiring entire result set in memory.",
        "fix": "Add a BY clause to limit scope, or use stats if you don't need the original events.",
    },
    {
        "pattern": r"\|\s*map\s+(?!.*maxsearches\s*=)",
        "name": "map without maxsearches",
        "severity": "high",
        "explanation": "map without explicit maxsearches= defaults to 10. Always set this explicitly.",
        "fix": "Add maxsearches=N for clarity and resource control: | map maxsearches=5 search=...",
    },
    {
        "pattern": r"\|\s*collect\s+(?!.*marker\s*=)",
        "name": "collect without marker",
        "severity": "medium",
        "explanation": "collect without marker= makes it hard to identify and filter summary data later.",
        "fix": 'Add marker="report_type=<name>" to tag collected events for easy retrieval.',
    },
    {
        "pattern": r"\|\s*rename\s+\S*\*\S*\s+as\b",
        "name": "Wildcard rename",
        "severity": "medium",
        "explanation": "Renaming with wildcards can have unintended effects on field names.",
        "fix": "Rename specific fields explicitly rather than using wildcard patterns.",
    },
    {
        "pattern": r"\|\s*sort\s+(?!\d)[^|]*$",
        "name": "sort without result limit",
        "severity": "medium",
        "explanation": "sort without a limit loads ALL results into memory for sorting.",
        "fix": "Add a limit: 'sort 10000 -field' to cap memory usage.",
    },
    {
        "pattern": r"\|\s*dedup\s+(?:\w+\s*,\s*){3,}",
        "name": "dedup on many fields",
        "severity": "medium",
        "explanation": "dedup on 4+ fields creates high cardinality hash table, consuming excessive memory.",
        "fix": "Reduce dedup fields, or use stats first(*) by field1, field2.",
    },
    {
        "pattern": r"\|\s*lookup\s+\w+\s+\w+(?:\s+(?:as|,)\s+\w+)*\s*(?:\||\s*$)(?!.*OUTPUT)(?!.*OUTPUTNEW)",
        "name": "Lookup without OUTPUT clause",
        "severity": "low",
        "explanation": "Lookup without OUTPUT/OUTPUTNEW returns ALL fields from the lookup table.",
        "fix": "Add OUTPUT field1, field2 to only return needed fields.",
    },
    {
        "pattern": r"\|\s*stats\s+count\s*\(\s*\*\s*\)",
        "name": "stats count(*) instead of count",
        "severity": "low",
        "explanation": "count(*) and count are equivalent in SPL, but count is simpler.",
        "fix": "Use 'stats count' instead of 'stats count(*)' — they produce identical results.",
    },
]


# Optimization rules with priorities
OPTIMIZATION_RULES = [
    {
        "name": "Convert stats to tstats",
        "condition": lambda q: "stats count" in q.lower() and "tstats" not in q.lower(),
        "priority": 10,
        "description": "Simple count operations can often use tstats for 10-100x speedup",
    },
    {
        "name": "Add TERM()/PREFIX() for indexed field matching",
        "condition": lambda q: re.search(r'"\w+\.\w+"', q) and "TERM(" not in q and "PREFIX(" not in q,
        "priority": 8,
        "description": "Use TERM(field=value) for exact tsidx token matching, or PREFIX(field=) for prefix matching. Never use wildcards inside TERM() — use PREFIX() for suffix wildcards instead.",
    },
    {
        "name": "Use fields early",
        "condition": lambda q: "| fields " not in q.lower() and "| table " in q.lower(),
        "priority": 5,
        "description": "Add 'fields' command early in pipeline to reduce memory usage",
    },
    {
        "name": "Combine multiple evals",
        "condition": lambda q: q.lower().count("| eval ") > 2,
        "priority": 3,
        "description": "Multiple eval commands can be combined: eval a=1, b=2, c=3",
    },
    {
        "name": "Replace transaction with stats",
        "condition": lambda q: "transaction" in q.lower() and "stats" not in q.lower(),
        "priority": 9,
        "description": "Transaction is very expensive. Replace with: stats min(_time) max(_time) values(*) by session_field",
    },
    {
        "name": "Use mstats for metric indexes",
        "condition": lambda q: re.search(r"index\s*=\s*\w*metric\w*", q, re.IGNORECASE) is not None and "mstats" not in q.lower(),
        "priority": 8,
        "description": "Metric indexes should use mstats instead of stats for much faster queries",
    },
    {
        "name": "Add limit to chart/timechart BY clause",
        "condition": lambda q: re.search(r"\|\s*(?:timechart|chart)\b.*\bby\b(?!.*limit)", q, re.IGNORECASE) is not None,
        "priority": 6,
        "description": "Add limit=N to timechart/chart BY clause to prevent high-cardinality explosions",
    },
    {
        "name": "Add window to streamstats",
        "condition": lambda q: "streamstats" in q.lower() and "window=" not in q.lower(),
        "priority": 5,
        "description": "Add window=N to streamstats to limit memory usage and define calculation scope",
    },
    {
        "name": "Replace join with lookup or stats",
        "condition": lambda q: "| join" in q.lower(),
        "priority": 8,
        "description": "Join is expensive and has subsearch limits. Use lookup for enrichment or stats for aggregation",
    },
]


class SPLKnowledgeBase:
    """
    Expert knowledge base for SPL commands and optimization.

    Combines hardcoded expert knowledge with official Splunk documentation
    loaded from documents/commands/ and documents/specs/.
    """

    def __init__(self, auto_enrich: bool = True):
        # Deep copy so _merge_command() mutations don't leak into module-level SPL_COMMANDS
        self.commands = copy.deepcopy(SPL_COMMANDS)
        self.anti_patterns = ANTI_PATTERNS
        self.optimization_rules = OPTIMIZATION_RULES
        self._docs = None
        self._enriched = False
        if auto_enrich:
            self._enrich_from_docs()

    def _enrich_from_docs(self):
        """Merge official Splunk documentation into the knowledge base.

        Failures here are non-fatal — the knowledge base still works with
        hardcoded data if docs can't be loaded or parsed.
        """
        if self._enriched:
            return
        self._enriched = True

        try:
            from shared.docs_loader import get_docs
        except ImportError:
            return

        try:
            docs = get_docs()
            self._docs = docs

            enriched_count = 0
            new_count = 0

            for cmd_name in docs.get_all_command_names():
                try:
                    cmd_doc = docs.get_command(cmd_name)
                    if not cmd_doc:
                        continue

                    existing = self.commands.get(cmd_name)
                    if existing:
                        self._merge_command(existing, cmd_doc)
                        enriched_count += 1
                    else:
                        new_info = self._create_from_doc(cmd_doc)
                        if new_info:
                            self.commands[cmd_name] = new_info
                            new_count += 1
                except Exception as cmd_err:
                    import logging
                    logging.getLogger(__name__).debug(
                        f"Skipping doc enrichment for '{cmd_name}': {cmd_err}"
                    )

            if enriched_count or new_count:
                import logging
                logging.getLogger(__name__).info(
                    f"Knowledge base enriched: {enriched_count} commands updated, "
                    f"{new_count} new commands from official docs"
                )
        except Exception as e:
            import logging
            logging.getLogger(__name__).warning(
                f"Docs enrichment failed (non-fatal): {e}"
            )

    def _merge_command(self, info: CommandInfo, doc) -> None:
        """Merge official doc into an existing CommandInfo (mutates deep-copied info)."""
        # Add official description as a supplement (keep our concise one primary)
        if doc.description and not hasattr(info, "_official_desc"):
            info._official_desc = doc.summary

        # Merge usage notes into optimization_notes (dedup, capped)
        existing_notes = set(n.lower() for n in info.optimization_notes)
        for note in (doc.usage_notes or []):
            if len(info.optimization_notes) >= 15:
                break  # Cap per-command notes
            if note.lower() not in existing_notes:
                info.optimization_notes.append(f"[Official] {note}")
                existing_notes.add(note.lower())

        # Merge limitations into optimization_notes
        for limit in (doc.limitations or []):
            if len(info.optimization_notes) >= 15:
                break
            if limit.lower() not in existing_notes:
                info.optimization_notes.append(f"[Limitation] {limit}")
                existing_notes.add(limit.lower())

        # Store source URL
        if doc.source_url:
            info._doc_url = doc.source_url

        # Store related commands
        if doc.related_commands:
            existing_alts = set(a.lower() for a in info.alternatives)
            for rel in doc.related_commands:
                if rel.lower() not in existing_alts:
                    info.alternatives.append(rel)

    def _create_from_doc(self, doc) -> Optional[CommandInfo]:
        """Create a CommandInfo from an official doc only (no hardcoded data)."""
        if not doc.name or not doc.description:
            return None

        # Determine command type from description keywords
        desc_lower = doc.description.lower()
        if any(w in desc_lower for w in ["aggregat", "statistic", "count", "sum"]):
            category = CommandCategory.AGGREGATION
        elif any(w in desc_lower for w in ["filter", "remove", "exclude"]):
            category = CommandCategory.FILTERING
        elif any(w in desc_lower for w in ["transform", "convert", "extract"]):
            category = CommandCategory.TRANSFORM
        elif any(w in desc_lower for w in ["join", "append", "combine", "union"]):
            category = CommandCategory.JOINING
        elif any(w in desc_lower for w in ["sort", "order", "head", "tail"]):
            category = CommandCategory.ORDERING
        elif any(w in desc_lower for w in ["table", "field", "rename", "format"]):
            category = CommandCategory.FORMATTING
        elif any(w in desc_lower for w in ["generat", "input", "make", "create"]):
            category = CommandCategory.GENERATING
        else:
            category = CommandCategory.TRANSFORM

        return CommandInfo(
            name=doc.name,
            category=category,
            cost=PerformanceCost.MEDIUM,  # conservative default
            description=doc.summary[:300],
            syntax="",  # official docs don't have clean syntax lines
            common_options={},
            examples=[f"[Example] {e}" for e in doc.examples[:3]],
            optimization_notes=doc.usage_notes[:5],
            alternatives=doc.related_commands[:5],
        )

    @property
    def docs(self):
        """Access the underlying SplunkDocsIndex for direct lookups."""
        return self._docs

    def get_command_info(self, command: str) -> Optional[CommandInfo]:
        """Get detailed information about a command."""
        return self.commands.get(command.lower())

    def explain_command_usage(self, command_text: str) -> str:
        """
        Generate a human-readable explanation of a command usage.
        """
        command_text = command_text.strip()
        if command_text.startswith("|"):
            command_text = command_text[1:].strip()

        # Extract command name
        match = re.match(r"(\w+)", command_text)
        if not match:
            return "Unable to parse command."

        cmd_name = match.group(1).lower()
        cmd_info = self.commands.get(cmd_name)

        if not cmd_info:
            return f"'{cmd_name}' is not in the knowledge base. It may be a custom command or macro."

        # Build explanation
        explanation = [f"**{cmd_name.upper()}**: {cmd_info.description}"]
        explanation.append("")

        # Parse specific usage
        usage_explanation = self._explain_specific_usage(cmd_name, command_text, cmd_info)
        if usage_explanation:
            explanation.append("**In this usage:**")
            explanation.append(usage_explanation)
            explanation.append("")

        # Add performance note
        cost_text = {
            PerformanceCost.VERY_LOW: "very fast",
            PerformanceCost.LOW: "fast",
            PerformanceCost.MEDIUM: "moderate",
            PerformanceCost.HIGH: "slow (use with caution)",
            PerformanceCost.VERY_HIGH: "very slow (avoid on large datasets)",
        }
        explanation.append(f"**Performance**: {cost_text[cmd_info.cost]}")

        # Add official doc URL if available
        doc_url = getattr(cmd_info, "_doc_url", None)
        if doc_url:
            explanation.append(f"\n**Reference**: {doc_url}")

        return "\n".join(explanation)

    def _explain_specific_usage(self, cmd: str, text: str, info: CommandInfo) -> str:
        """Generate usage-specific explanation."""
        text_lower = text.lower()

        if cmd == "stats":
            parts = []
            # Check for functions
            for func in ["count", "sum", "avg", "dc", "values", "min", "max"]:
                if func in text_lower:
                    if func == "count":
                        parts.append("counts events")
                    elif func == "dc":
                        match = re.search(r"dc\s*\(\s*(\w+)\s*\)", text_lower)
                        field = match.group(1) if match else "field"
                        parts.append(f"counts unique values of '{field}'")
                    elif func in ("sum", "avg", "min", "max"):
                        match = re.search(rf"{func}\s*\(\s*(\w+)\s*\)", text_lower)
                        field = match.group(1) if match else "field"
                        parts.append(f"calculates {func} of '{field}'")

            # Check for BY clause
            by_match = re.search(r"\bby\s+(.+?)(?:\s*\||\s*$)", text_lower)
            if by_match:
                by_fields = by_match.group(1).strip()
                parts.append(f"grouped by {by_fields}")

            return ", ".join(parts) if parts else None

        elif cmd == "eval":
            # Extract field assignment
            match = re.search(r"eval\s+(\w+)\s*=", text_lower)
            if match:
                field = match.group(1)
                return f"Creates or modifies the '{field}' field with a calculated value."

        elif cmd == "where":
            # Describe the filter
            match = re.search(r"where\s+(.+?)(?:\s*\||\s*$)", text_lower)
            if match:
                condition = match.group(1).strip()
                return f"Filters results where: {condition}"

        elif cmd == "table":
            match = re.search(r"table\s+(.+?)(?:\s*\||\s*$)", text_lower)
            if match:
                fields = match.group(1).strip()
                return f"Displays these fields in order: {fields}"

        elif cmd == "timechart":
            parts = []
            span_match = re.search(r"span\s*=\s*(\w+)", text_lower)
            if span_match:
                parts.append(f"groups data into {span_match.group(1)} time buckets")

            by_match = re.search(r"\bby\s+(\w+)", text_lower)
            if by_match:
                parts.append(f"split by '{by_match.group(1)}'")

            return ", ".join(parts) if parts else None

        return None

    def detect_anti_patterns(self, query: str) -> List[Dict[str, Any]]:
        """
        Detect anti-patterns in a query.
        """
        issues = []
        for pattern in self.anti_patterns:
            if re.search(pattern["pattern"], query, re.IGNORECASE):
                issues.append({
                    "name": pattern["name"],
                    "severity": pattern["severity"],
                    "explanation": pattern["explanation"],
                    "fix": pattern["fix"],
                })
        return issues

    def get_optimization_suggestions(self, query: str) -> List[Dict[str, Any]]:
        """
        Generate optimization suggestions for a query.
        """
        suggestions = []

        # Check optimization rules
        for rule in self.optimization_rules:
            if rule["condition"](query):
                suggestions.append({
                    "name": rule["name"],
                    "priority": rule["priority"],
                    "description": rule["description"],
                })

        # Check anti-patterns
        anti_patterns = self.detect_anti_patterns(query)
        for ap in anti_patterns:
            suggestions.append({
                "name": f"Fix: {ap['name']}",
                "priority": 9 if ap["severity"] == "high" else 5,
                "description": ap["fix"],
            })

        # Sort by priority
        suggestions.sort(key=lambda x: x["priority"], reverse=True)

        return suggestions

    def explain_pipeline(self, query: str) -> List[Dict[str, str]]:
        """
        Explain each stage of an SPL pipeline in human terms.
        """
        stages = []

        # Split pipeline
        parts = self._split_pipeline(query)

        for i, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue

            # Get command name
            match = re.match(r"(\w+)", part)
            cmd_name = match.group(1).lower() if match else "unknown"

            # Get command info
            cmd_info = self.commands.get(cmd_name)

            stage = {
                "stage": i + 1,
                "command": cmd_name,
                "raw": part,
                "explanation": "",
                "performance": "",
            }

            if cmd_info:
                stage["explanation"] = self.explain_command_usage(part)
                cost_text = {
                    PerformanceCost.VERY_LOW: "Very Fast",
                    PerformanceCost.LOW: "Fast",
                    PerformanceCost.MEDIUM: "Moderate",
                    PerformanceCost.HIGH: "Slow",
                    PerformanceCost.VERY_HIGH: "Very Slow",
                }
                stage["performance"] = cost_text[cmd_info.cost]
            else:
                # Base search or unknown command
                if i == 0:
                    stage["explanation"] = self._explain_base_search(part)
                    stage["performance"] = "Varies"
                else:
                    stage["explanation"] = f"Unknown command or macro: {cmd_name}"

            stages.append(stage)

        return stages

    def _explain_base_search(self, search: str) -> str:
        """Explain the base search portion."""
        parts = []

        # Index
        idx_match = re.search(r"index\s*=\s*(\S+)", search)
        if idx_match:
            idx = idx_match.group(1)
            if idx == "*":
                parts.append("searches ALL indexes (slow!)")
            else:
                parts.append(f"searches the '{idx}' index")

        # Sourcetype
        st_match = re.search(r"sourcetype\s*=\s*(\S+)", search)
        if st_match:
            parts.append(f"for '{st_match.group(1)}' data")

        # Time range
        earliest_match = re.search(r"earliest\s*=\s*(\S+)", search)
        latest_match = re.search(r"latest\s*=\s*(\S+)", search)
        if earliest_match:
            parts.append(f"from {earliest_match.group(1)}")
        if latest_match:
            parts.append(f"to {latest_match.group(1)}")

        # Keywords
        keywords = re.findall(r'\b(?!index|sourcetype|earliest|latest|host|source)\w+\b', search)
        keywords = [k for k in keywords if "=" not in k and not k.isupper()]
        if keywords[:5]:
            parts.append(f"filtering for: {', '.join(keywords[:5])}")

        return "Base search: " + ", ".join(parts) if parts else "Base search"

    def _split_pipeline(self, query: str) -> List[str]:
        """Split query into pipeline stages."""
        stages = []
        current = []
        depth = 0
        in_quote = False
        quote_char = None

        for i, char in enumerate(query):
            if char in '"\'`' and (i == 0 or query[i-1] != '\\'):
                if not in_quote:
                    in_quote = True
                    quote_char = char
                elif char == quote_char:
                    in_quote = False
                    quote_char = None

            if not in_quote:
                if char == '[':
                    depth += 1
                elif char == ']':
                    depth -= 1
                elif char == '|' and depth == 0:
                    stage = ''.join(current).strip()
                    if stage:
                        stages.append(stage)
                    current = []
                    continue

            current.append(char)

        stage = ''.join(current).strip()
        if stage:
            stages.append(stage)

        return stages

    def get_command_alternatives(self, command: str) -> List[str]:
        """Get alternative commands that might be more efficient."""
        cmd_info = self.commands.get(command.lower())
        if cmd_info:
            return cmd_info.alternatives
        return []

    def calculate_query_complexity(self, query: str) -> Dict[str, Any]:
        """
        Calculate overall query complexity score.
        """
        stages = self._split_pipeline(query)

        total_cost = 0
        high_cost_commands = []

        for stage in stages:
            match = re.match(r"(\w+)", stage.strip())
            if match:
                cmd = match.group(1).lower()
                cmd_info = self.commands.get(cmd)
                if cmd_info:
                    cost = cmd_info.cost.value
                    total_cost += cost
                    if cost >= 4:
                        high_cost_commands.append(cmd)

        # Calculate complexity level
        avg_cost = total_cost / len(stages) if stages else 0

        if avg_cost < 2:
            level = "simple"
        elif avg_cost < 3:
            level = "moderate"
        elif avg_cost < 4:
            level = "complex"
        else:
            level = "very complex"

        return {
            "level": level,
            "total_cost": total_cost,
            "stage_count": len(stages),
            "average_cost": round(avg_cost, 2),
            "high_cost_commands": high_cost_commands,
            "optimization_potential": "high" if high_cost_commands else "low",
        }


# Convenience singleton
_kb = None

def get_knowledge_base() -> SPLKnowledgeBase:
    """Get the singleton knowledge base instance."""
    global _kb
    if _kb is None:
        _kb = SPLKnowledgeBase()
    return _kb
