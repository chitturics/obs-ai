"""
Centralized SPL Constants — Single Source of Truth

All command classifications, cost weights, cardinality heuristics, and
time-parsing data live here. Every other module in shared/ imports from
this file instead of defining its own copy.

Organized into sections:
1. Command taxonomy (known, streaming, transforming, generating)
2. Cost & risk weights (command costs, memory, CPU, dangerous)
3. Distribution classification (distributable vs non-distributable)
4. Cardinality heuristics (field cardinality estimation)
5. Time parsing (unit multipliers, snap-to support)
6. Metric detection patterns
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 1. Command Taxonomy
# ---------------------------------------------------------------------------

# All 173 known built-in SPL commands
KNOWN_COMMANDS: frozenset[str] = frozenset({
    "abstract", "accum", "addcoltotals", "addinfo", "addtotals", "analyzefields",
    "anomalies", "anomalousvalue", "anomalydetection", "append", "appendcols",
    "appendpipe", "arules", "associate", "autoregress", "bin", "bucket", "bucketdir",
    "chart", "cluster", "cofilter", "collapse", "collect", "concurrency", "contingency",
    "convert", "copyresults", "correlate", "createrss", "datamodel", "dbinspect",
    "debug", "dedup", "delete", "delta", "diff", "dispatch", "dump", "editinfo",
    "erex", "eval", "eventcount", "eventstats", "extract", "fieldformat", "fields",
    "fieldsummary", "filldown", "fillnull", "findkeywords", "findtypes", "folderize",
    "foreach", "format", "from", "fromjson", "gauge", "gentimes", "geom", "geomfilter",
    "geostats", "head", "highlight", "history", "iconify", "ingestpreview", "input",
    "inputcsv", "inputlookup", "iplocation", "join", "kmeans", "kv", "kvform",
    "loadjob", "localize", "localop", "lookup", "makecontinuous", "makemv",
    "makeresults", "map", "mcatalog", "mcollect", "metadata", "metasearch",
    "meventcollect", "mpreview", "mrollup", "mstats", "multikv", "multisearch",
    "mvcombine", "mvexpand", "nokv", "nomv", "outlier", "outputcsv", "outputlookup",
    "outputraw", "outputtext", "overlap", "pivot", "predict", "preview", "prjob",
    "rangemap", "rare", "rawstats", "redistribute", "regex", "reltime", "rename",
    "replace", "require", "rest", "return", "reverse", "rex", "rtorder",
    "runshellscript", "savedsearch", "script", "scrub", "search", "searchtxn",
    "selfjoin", "sendalert", "sendemail", "set", "setfields", "showargs", "sichart",
    "sirare", "sistats", "sitimechart", "sitop", "sort", "spath", "stats", "strcat",
    "streamstats", "surrounding", "table", "tags", "tail", "timechart", "timewrap",
    "tojson", "top", "transaction", "transpose", "trendline", "tscollect", "tstats",
    "typeahead", "typelearner", "typer", "union", "uniq", "untable", "walklex",
    "where", "x11", "xmlkv", "xmlunescape", "xpath", "xyseries",
})

# Streaming commands — process events one at a time, no buffering
STREAMING_COMMANDS: frozenset[str] = frozenset({
    "eval", "where", "search", "rex", "fields", "rename", "replace",
    "convert", "lookup", "spath", "xmlkv", "kvform", "multikv",
    "regex", "reltime", "setfields", "strcat", "tags", "typer",
    "fillnull", "filldown", "makemv", "nomv", "mvfilter",
    "iplocation", "addinfo", "rangemap",
})

# Transforming commands — aggregate or reorder events
TRANSFORMING_COMMANDS: frozenset[str] = frozenset({
    "stats", "chart", "timechart", "top", "rare", "eventstats",
    "streamstats", "transaction", "dedup", "sort", "head", "tail",
    "cluster", "kmeans", "anomalydetection", "predict",
    "mvcombine", "transpose", "xyseries", "untable",
})

# Generating commands — produce events from scratch
GENERATING_COMMANDS: frozenset[str] = frozenset({
    "search", "tstats", "mstats", "inputlookup", "makeresults",
    "rest", "metadata", "datamodel", "from", "loadjob",
    "mcatalog", "gentimes", "inputcsv", "multisearch", "union",
})


# ---------------------------------------------------------------------------
# 2. Cost & Risk Weights
# ---------------------------------------------------------------------------

# Per-command cost (1-10 scale, used by QueryCostEstimator)
COMMAND_COSTS: dict[str, int] = {
    # Very fast (1-2) — streaming, minimal overhead
    "tstats": 1, "mstats": 1, "metadata": 1, "mcatalog": 1,
    "fields": 1, "rename": 1, "head": 1, "tail": 1,
    "table": 2, "fillnull": 1, "filldown": 1, "addtotals": 1,
    "return": 1, "bin": 1, "bucket": 1, "format": 1,
    "reltime": 1, "rangemap": 1, "nomv": 1, "makemv": 1,
    "addinfo": 1, "convert": 2, "replace": 1, "tags": 1,
    "makeresults": 1, "gentimes": 1, "accum": 2, "delta": 2,
    "autoregress": 2, "reverse": 2, "uniq": 2,
    # Fast (2-3) — lightweight processing
    "eval": 2, "where": 2, "search": 2, "lookup": 2,
    "stats": 3, "timechart": 3, "chart": 3,
    "top": 3, "rare": 3, "inputlookup": 2,
    "mvfilter": 2, "mvcombine": 3, "mvexpand": 4,
    "trendline": 3, "from": 2, "datamodel": 2,
    "sistats": 3, "sitimechart": 3, "xyseries": 3, "untable": 3,
    "iplocation": 2, "geom": 2, "loadjob": 2,
    "rest": 3, "sendemail": 2,
    # Medium (4-6) — requires buffering or CPU
    "rex": 5, "regex": 5, "spath": 4, "xmlkv": 4, "multikv": 4,
    "dedup": 5, "sort": 5, "foreach": 4, "erex": 6,
    "eventstats": 6, "streamstats": 5, "concurrency": 5,
    "outlier": 5, "fieldsummary": 5, "abstract": 4,
    "geostats": 4, "pivot": 4, "transpose": 4,
    "outputlookup": 4, "collect": 5,
    # Expensive (7-9) — multiple passes or heavy memory
    "join": 8, "append": 7, "appendcols": 7, "appendpipe": 6,
    "transaction": 9, "map": 9, "selfjoin": 8, "set": 6,
    "multisearch": 5, "union": 5,
    # Very expensive (9-10) — ML, multiple searches, admin
    "cluster": 8, "kmeans": 9, "anomalydetection": 9, "predict": 8,
    "delete": 10,
}

# Risk score additions for expensive commands (used by SPLValidator)
EXPENSIVE_COMMAND_RISKS: dict[str, int] = {
    "transaction": 30,
    "join": 25,
    "map": 25,
    "multisearch": 20,
    "append": 15,
    "appendcols": 15,
    "eventstats": 10,
    "streamstats": 10,
    "cluster": 20,
    "kmeans": 20,
    "associate": 15,
    "correlate": 15,
    "anomalydetection": 15,
    "selfjoin": 15,
}

# Risk score additions for dangerous/modifying commands
DANGEROUS_COMMANDS: dict[str, int] = {
    "delete": 50,
    "collect": 30,
    "outputlookup": 25,
    "mcollect": 30,
    "sendemail": 20,
    "sendalert": 20,
    "runshellscript": 50,
    "script": 40,
}

# Memory weight per command (relative units, used by deep analysis)
MEMORY_WEIGHTS: dict[str, float] = {
    "transaction": 10.0,
    "join": 8.0,
    "eventstats": 7.0,
    "appendcols": 7.0,
    "append": 5.0,
    "appendpipe": 4.0,
    "streamstats": 3.0,
    "dedup": 4.0,
    "sort": 5.0,
    "stats": 3.0,
    "timechart": 3.0,
    "chart": 3.0,
    "top": 2.0,
    "rare": 2.0,
    "cluster": 6.0,
    "kmeans": 8.0,
    "anomalydetection": 8.0,
    "predict": 5.0,
    "mvexpand": 3.0,
    "map": 8.0,
    "rest": 3.0,
    "xyseries": 3.0,
    "untable": 3.0,
    "concurrency": 4.0,
    "reverse": 3.0,
    "inputlookup": 2.0,
    "mvcombine": 2.0,
    "geostats": 4.0,
    "outlier": 5.0,
    "selfjoin": 6.0,
}

# CPU weight per command (relative units, used by deep analysis)
CPU_WEIGHTS: dict[str, float] = {
    "rex": 5.0,
    "regex": 5.0,
    "spath": 4.0,
    "xmlkv": 4.0,
    "multikv": 3.0,
    "eval": 2.0,
    "foreach": 3.0,
    "cluster": 7.0,
    "kmeans": 8.0,
    "anomalydetection": 8.0,
    "predict": 6.0,
    "erex": 6.0,
    "transaction": 5.0,
    "map": 3.0,
    "concurrency": 3.0,
}


# ---------------------------------------------------------------------------
# 3. Distribution Classification
# ---------------------------------------------------------------------------

# Commands that can run on indexers (distributed search)
DISTRIBUTABLE_COMMANDS: frozenset[str] = frozenset({
    # Filtering & search
    "search", "where", "eval", "rex", "regex", "fields", "rename",
    # Enrichment & extraction
    "lookup", "spath", "xmlkv", "convert", "fillnull",
    "replace", "multikv", "kvform", "tags",
    # Aggregations (indexers compute partial results)
    "stats", "timechart", "chart", "top", "rare", "eventstats",
    # Summary indexing variants
    "sistats", "sitimechart", "sichart", "sitop", "sirare",
    # Generating commands
    "tstats", "mstats", "mcatalog", "metadata",
    # Field transforms
    "bin", "bucket", "foreach",
    # Lightweight
    "head", "addtotals", "addinfo",
    # Field extraction
    "erex",
    # Subsearch formatting
    "format", "return",
    # Lookup I/O (inputlookup is distributable; outputlookup is not)
    "inputlookup",
    # Data model commands
    "from", "datamodel", "pivot",
    # Generating
    "makeresults",
    # Combining (parallel execution)
    "multisearch", "union",
    # Reshaping & formatting
    "xyseries", "untable", "table",
    # Multivalue operations (streaming)
    "mvexpand", "mvcombine", "mvfilter", "makemv", "nomv",
    # Type/geo operations
    "iplocation", "geostats",
})

# Commands that force all processing to the search head
NON_DISTRIBUTABLE_COMMANDS: frozenset[str] = frozenset({
    "transaction",      # Must see all events for grouping
    "streamstats",      # Order-dependent running calculations
    "sort",             # Must collect all results to sort
    "dedup",            # Must see all events for dedup
    "tail",             # Must see all events
    "reverse",          # Must collect all results
    "uniq",             # Must see all events
    "cluster",          # ML — must see all events
    "kmeans",           # ML — must see all events
    "anomalydetection", # ML — must see all events
    "predict",          # ML — must see all events
    "trendline",        # Order-dependent
    "accum",            # Running accumulation
    "autoregress",      # Depends on prior events
    "delta",            # Depends on prior events
    "concurrency",      # Must see all events in time order
    "rest",             # API calls from search head only
    "appendcols",       # Buffers both result sets
    "delete",           # Admin command — search head only
    "sendemail",        # Search head action
    "outputlookup",     # Writes to search head filesystem
    "collect",          # Writes to summary index from search head
    "outputcsv",        # Writes to search head filesystem
})

# Commands that suggest tstats optimization opportunity
TSTATS_OPPORTUNITY_COMMANDS: frozenset[str] = frozenset({
    "stats", "timechart", "chart", "top", "rare",
})

# Commands that block tstats conversion
TSTATS_BLOCKERS: frozenset[str] = frozenset({
    "streamstats", "eventstats", "transaction", "rex", "spath",
})


# ---------------------------------------------------------------------------
# 4. Cardinality Heuristics
# ---------------------------------------------------------------------------

# Fields with very high cardinality (millions of unique values)
HIGH_CARDINALITY_FIELDS: frozenset[str] = frozenset({
    "_raw", "_time", "message", "raw_message", "msg",
    "uri", "url", "uri_path", "request_uri", "referer",
    "session_id", "transaction_id", "request_id", "trace_id", "span_id",
    "md5", "sha256", "sha1", "hash", "checksum",
    "email", "email_address",
})

# Fields with medium cardinality (thousands — hundreds of thousands)
MEDIUM_CARDINALITY_FIELDS: frozenset[str] = frozenset({
    "src_ip", "dest_ip", "src", "dest", "ip", "client_ip", "server_ip",
    "user", "user_name", "username", "account_name",
    "process_name", "process_path", "parent_process",
    "file_name", "file_path", "registry_path",
    "domain", "dns_query", "query",
    "src_port", "dest_port",
})

# Fields with low cardinality (tens — hundreds)
LOW_CARDINALITY_FIELDS: frozenset[str] = frozenset({
    "host", "hostname", "source", "sourcetype", "index",
    "action", "status", "severity", "level", "priority",
    "protocol", "transport", "app", "vendor", "product",
    "EventCode", "EventID", "event_id", "category", "subcategory",
    "http_method", "http_status", "status_code",
    "direction", "interface", "zone",
    "os", "os_version", "arch",
    "tag", "type",
})

# Keyword heuristics for unknown fields
HIGH_CARD_KEYWORDS = ("id", "uuid", "guid", "hash", "token", "key", "path", "uri", "url")
MEDIUM_CARD_KEYWORDS = ("ip", "addr", "address", "user", "name", "email", "process", "file")
LOW_CARD_KEYWORDS = ("status", "action", "type", "category", "level", "severity", "code")


# ---------------------------------------------------------------------------
# 5. Time Parsing
# ---------------------------------------------------------------------------

# Comprehensive time unit → seconds mapping
TIME_UNITS: dict[str, int] = {
    "s": 1, "sec": 1, "secs": 1, "second": 1, "seconds": 1,
    "m": 60, "min": 60, "mins": 60, "minute": 60, "minutes": 60,
    "h": 3600, "hr": 3600, "hrs": 3600, "hour": 3600, "hours": 3600,
    "d": 86400, "day": 86400, "days": 86400,
    "w": 604800, "week": 604800, "weeks": 604800,
    "mon": 2592000, "month": 2592000, "months": 2592000,
    "y": 31536000, "year": 31536000, "years": 31536000,
}

# Short-form only (for compact lookups)
TIME_MULTIPLIERS: dict[str, int] = {
    "s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800,
    "mon": 2592000, "y": 31536000,
}


# ---------------------------------------------------------------------------
# 6. Metric Detection Patterns
# ---------------------------------------------------------------------------

# Metric index name indicators
METRIC_INDEX_PATTERNS: list[str] = [
    r"\bindex\s*=\s*[\w_]*metric[\w_]*",
    r"\bsourcetype\s*=\s*[\w_]*metric[\w_]*",
    r"\bindex\s*=\s*[\w_]*perf[\w_]*",
    r"\bindex\s*=\s*[\w_]*monitor[\w_]*",
    r"\bindex\s*=\s*[\w_]*telemetry[\w_]*",
    r"\bindex\s*=\s*[\w_]*statsd[\w_]*",
    r"\bindex\s*=\s*[\w_]*collectd[\w_]*",
    r"\bindex\s*=\s*[\w_]*prometheus[\w_]*",
    r"\bindex\s*=\s*[\w_]*graphite[\w_]*",
]

# Metric field name patterns
METRIC_FIELD_PATTERNS: list[str] = [
    r"\bcpu[_.]?(?:pct|percent|usage|idle|util)",
    r"\bmem(?:ory)?[_.]?(?:pct|percent|usage|free|used|total)",
    r"\bdisk[_.]?(?:pct|percent|usage|free|used|io|read|write)",
    r"\bnetwork[_.]?(?:bytes|packets|in|out|errors)",
    r"\blatency|response_time|duration|elapsed",
    r"\bthroughput|requests_per_sec|ops_per_sec",
    r"\bqueue[_.]?(?:depth|size|length|wait)",
    r"\b(?:avg|min|max|p\d+|percentile)\b.*\b(?:time|latency|duration)\b",
]


# ---------------------------------------------------------------------------
# 7. Validation Patterns
# ---------------------------------------------------------------------------

# Patterns that indicate a definitely invalid query
INVALID_PATTERNS: list[tuple[str, str]] = [
    (r'.+\|\s*tstats\b',
     "Cannot pipe into tstats — tstats is a generating command that must start the pipeline"),
    (r'^tstats\s+',
     "tstats must start with pipe: | tstats"),
    (r'(?<!\w)index\s+(?!IN\b)(\w+)\s+(?!where\b)',
     "Malformed 'index' — use 'index=<name>' not 'index <name>'"),
    (r'tstats\s+count\s+by\s+_raw',
     "Cannot use tstats with _raw field"),
    (r'tstats\s+count\s+by\s+TERM\(',
     "TERM() is not a field, cannot group by it"),
    (r'splunk\s+\|',
     "Query should not start with 'splunk'"),
    (r'\|\s+event\s+host=',
     "Invalid syntax — 'event' is not a Splunk command"),
    (r'TERM\([^)]*\*[^)]*\)',
     "TERM() does not support wildcards — use PREFIX() for prefix matching"),
    (r'PREFIX\([^)]*\*[^)]*\)',
     "PREFIX() does not support wildcards inside parentheses"),
]
