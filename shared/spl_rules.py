"""
SPL Rules for the Splunk Assistant.
"""

from enum import Enum


class Severity(Enum):
    """Severity levels for issues."""
    CRITICAL = "critical"   # Query won't work or is very slow
    HIGH = "high"          # Significant performance impact
    MEDIUM = "medium"      # Moderate impact
    LOW = "low"           # Minor improvement possible
    INFO = "info"         # Informational


# Anti-patterns to detect
ANTI_PATTERNS = [
    {
        "pattern": r"index\s*=\s*\*",
        "message": "Searching all indexes (index=*) is extremely slow",
        "severity": Severity.CRITICAL,
        "suggestion": "Specify exact index names: index=main or index IN (idx1, idx2)",
        "auto_fixable": False,
    },
    {
        "pattern": r"(?<![a-z_])NOT\s+\w+\s*=",
        "message": "NOT expressions consume more resources than positive matches",
        "severity": Severity.MEDIUM,
        "suggestion": "Use positive matching where possible instead of NOT",
        "auto_fixable": False,
    },
    {
        "pattern": r"\|\s*join\s+",
        "message": "JOIN command makes multiple indexer trips, very expensive",
        "severity": Severity.HIGH,
        "suggestion": "Consider using stats with eval/where or lookup instead",
        "auto_fixable": False,
    },
    {
        "pattern": r"\|\s*append\s+\[",
        "message": "APPEND with subsearch makes multiple indexer trips",
        "severity": Severity.HIGH,
        "suggestion": "Consider combining searches with OR, or use stats",
        "auto_fixable": False,
    },
    {
        "pattern": r"\|\s*transaction\s+",
        "message": "TRANSACTION is memory-intensive; consider stats with range(_time)",
        "severity": Severity.HIGH,
        "suggestion": "Replace with: stats min(_time) as start, max(_time) as end, values(*) by transaction_field",
        "auto_fixable": False,
    },
    {
        "pattern": r"(?<!\|)\s*\*[\w\-]+\*",
        "message": "Middle wildcards (*term*) are slow - cannot use bloom filters",
        "severity": Severity.HIGH,
        "suggestion": "Use suffix wildcards (term*), PREFIX(term) for prefix matching, or TERM(exact_value) for exact token matching. Never put wildcards inside TERM().",
        "auto_fixable": False,
    },
    {
        "pattern": r"\|\s*table\s+.+\|\s*(?!$)",
        "message": "TABLE command mid-pipeline forces data to search head early",
        "severity": Severity.MEDIUM,
        "suggestion": "Move TABLE to the end of the query",
        "auto_fixable": True,
        "fix_function": "move_table_to_end",
    },
    {
        "pattern": r"\|\s*search\s+.+\|\s*stats",
        "message": "Using SEARCH after pipe for filtering is less efficient than WHERE",
        "severity": Severity.LOW,
        "suggestion": "Consider using WHERE command instead of | search",
        "auto_fixable": True,
        "fix_function": "replace_search_with_where",
    },
    {
        "pattern": r"(\|\s*eval\s+\w+\s*=.+){3,}",
        "message": "Multiple EVAL commands can be combined into one",
        "severity": Severity.LOW,
        "suggestion": "Combine: | eval field1=val1, field2=val2, field3=val3",
        "auto_fixable": True,
        "fix_function": "combine_eval_commands",
    },
    {
        "pattern": r"\|\s*stats\s+count\s+by\s+_raw",
        "message": "Aggregating by _raw is extremely inefficient",
        "severity": Severity.CRITICAL,
        "suggestion": "Instead of `by _raw`, use fields that identify unique events, like `by host, source, sourcetype`",
        "auto_fixable": False,
    },
    {
        "pattern": r"\[\s*search\b",
        "message": "Subsearch has 60-second timeout and 50K result limit by default",
        "severity": Severity.MEDIUM,
        "suggestion": "Consider lookup tables for large datasets, or add maxout/maxtime explicitly",
        "auto_fixable": False,
    },
    {
        "pattern": r"\|\s*map\s+",
        "message": "MAP command runs a separate search per row — very expensive",
        "severity": Severity.HIGH,
        "suggestion": "Use join or lookup instead. If map is necessary, set maxsearches explicitly",
        "auto_fixable": False,
    },
    {
        "pattern": r"\|\s*sort\s+(?![\d-])[^|]*$",
        "message": "SORT without numeric limit — loads all results into memory",
        "severity": Severity.MEDIUM,
        "suggestion": "Add a limit: | sort 10000 -field_name",
        "auto_fixable": False,
    },
    {
        "pattern": r"\|\s*eventstats\s+\w+\s*\([^)]*\)(?:\s+as\s+\w+)?\s*$",
        "message": "EVENTSTATS without BY clause buffers entire result set",
        "severity": Severity.HIGH,
        "suggestion": "Add BY clause to limit scope, or use stats if original events aren't needed",
        "auto_fixable": False,
    },
    {
        "pattern": r"\|\s*delete\b",
        "message": "DELETE permanently removes events — cannot be undone",
        "severity": Severity.CRITICAL,
        "suggestion": "Verify index and time range carefully. Consider archiving instead of deleting",
        "auto_fixable": False,
    },
]

# Best practice checks
BEST_PRACTICES = [
    {
        "check": "has_time_range",
        "message": "Ensure search runs with an appropriate time window (via UI picker or earliest/latest)",
        "severity": Severity.INFO,
        "suggestion": "Time range is typically set via the Splunk UI time picker. Add earliest/latest in the query only when needed for scheduled searches or subsearches.",
    },
    {
        "check": "has_index",
        "message": "No index specified - query will search default indexes",
        "severity": Severity.MEDIUM,
        "suggestion": "Specify index=<name> to limit scope",
    },
    {
        "check": "fields_early",
        "message": "No FIELDS command - consider adding to reduce data transfer",
        "severity": Severity.LOW,
        "suggestion": "Add | fields <needed_fields> early in the pipeline",
    },
    {
        "check": "tstats_opportunity",
        "message": "Simple aggregation could use TSTATS for 10-100x speedup",
        "severity": Severity.HIGH,
        "suggestion": "Convert to: | tstats count where index=... by field",
    },
    {
        "check": "subsearch_limits",
        "message": "Subsearch without explicit maxout/maxtime — defaults may truncate results",
        "severity": Severity.MEDIUM,
        "suggestion": "Add maxout=50000 maxtime=120 to subsearches for explicit resource control",
    },
    {
        "check": "sort_limit",
        "message": "Sort without limit may consume excessive memory on large result sets",
        "severity": Severity.LOW,
        "suggestion": "Add a numeric limit: | sort 10000 -count",
    },
    {
        "check": "chart_limit",
        "message": "chart/timechart with BY clause should include limit= to cap series count",
        "severity": Severity.MEDIUM,
        "suggestion": "Add limit=10 to prevent excessive series with high-cardinality BY fields",
    },
    {
        "check": "streamstats_window",
        "message": "streamstats without window= accumulates over entire result set",
        "severity": Severity.LOW,
        "suggestion": "Add window=N to control memory usage and define calculation scope",
    },
    {
        "check": "metric_index",
        "message": "Query targets metric-like data — consider using mstats for metric indexes",
        "severity": Severity.HIGH,
        "suggestion": "Use | mstats for metric indexes instead of | stats — reads metric store directly",
    },
]
