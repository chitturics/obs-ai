"""
Knowledge Graph — Type Constants.

Defines the vocabulary of entity types, relationship types, and known SPL
commands and functions used by the SplunkKnowledgeGraph.

Extracted from knowledge_graph.py for size management.
All names are re-exported from knowledge_graph.py for backward compatibility.
"""

# ---------------------------------------------------------------------------
# Entity types & relationship types
# ---------------------------------------------------------------------------

ENTITY_TYPES = {
    "Command", "Function", "Field", "Index", "Lookup",
    "Datamodel", "Argument", "Operator", "ConfigStanza",
    # Expanded types for deep SPL understanding
    "SavedSearch", "Macro", "Source", "Sourcetype",
    "SearchFilter", "Summarization", "IndexTimeField",
    # Tool/Skill cross-referencing
    "Tool", "Skill",
}

RELATIONSHIP_TYPES = {
    "has_arguments", "uses_functions", "pipes_to", "operates_on",
    "belongs_to", "references", "maps_to_cim", "alternative_to",
    "compatible_with", "suggests", "defines", "requires",
    "outputs", "aggregates", "filters", "enriches",
    "part_of", "transforms", "groups_by", "sorts_by",
    # Expanded relationships for deep SPL understanding
    "uses_index", "uses_field", "uses_sourcetype", "uses_macro",
    "uses_lookup", "uses_command", "accelerated_by", "filters_by",
    "summarizes", "writes_to", "reads_from", "schedules",
    "extracts_field", "has_source", "has_sourcetype",
    # Config cross-linking relationships (density improvement)
    "configures", "configured_by", "reads_config", "related_stanza",
    "targets_index",
}

# Well-known SPL stats/eval functions
KNOWN_FUNCTIONS = {
    "avg", "count", "dc", "distinct_count", "estdc", "estdc_error",
    "exactperc", "first", "last", "list", "max", "mean", "median",
    "min", "mode", "p", "perc", "percentile", "range", "rate",
    "stdev", "stdevp", "sum", "sumsq", "upperperc", "var", "varp",
    "values", "earliest", "earliest_time", "latest", "latest_time",
    "per_day", "per_hour", "per_minute", "per_second",
    # eval functions
    "abs", "case", "ceil", "ceiling", "cidrmatch", "coalesce",
    "commands", "exact", "exp", "floor", "if", "ifnull", "in",
    "isbool", "isint", "isnotnull", "isnull", "isnum", "isstr",
    "len", "like", "ln", "log", "lower", "ltrim", "match", "md5",
    "mvappend", "mvcount", "mvdedup", "mvfilter", "mvfind",
    "mvindex", "mvjoin", "mvrange", "mvsort", "mvzip",
    "now", "null", "nullif", "pi", "pow", "printf", "random",
    "relative_time", "replace", "round", "rtrim", "searchmatch",
    "sha1", "sha256", "sha512", "sigfig", "spath", "split",
    "sqrt", "strftime", "strptime", "substr", "time", "tonumber",
    "tostring", "trim", "typeof", "upper", "urldecode", "validate",
}

# Well-known SPL commands (used for pipes_to extraction)
KNOWN_COMMANDS = {
    "abstract", "accum", "addcoltotals", "addinfo", "addtotals",
    "analyzefields", "anomalies", "anomalousvalue", "anomalydetection",
    "append", "appendcols", "appendpipe", "arules", "associate",
    "autoregress", "bin", "bucket", "bucketdir", "chart", "cluster",
    "cofilter", "collect", "concurrency", "contingency", "convert",
    "correlate", "datamodel", "dbinspect", "dedup", "delete", "delta",
    "diff", "erex", "eval", "eventcount", "eventstats", "extract",
    "fieldformat", "fields", "fieldsummary", "filldown", "fillnull",
    "findtypes", "foreach", "format", "from", "gentimes", "geom",
    "geostats", "head", "highlight", "history", "iconify", "inputcsv",
    "inputlookup", "iplocation", "join", "kmeans", "kvform",
    "loadjob", "localize", "localop", "lookup", "makecontinuous",
    "makemv", "makeresults", "map", "mcatalog", "mcollect",
    "metadata", "metasearch", "meventcollect", "mpreview", "mstats",
    "multikv", "multisearch", "mvcombine", "mvexpand", "nomv",
    "outlier", "outputcsv", "outputlookup", "overlap", "pivot",
    "predict", "rangemap", "rare", "regex", "reltime", "rename",
    "replace", "rest", "return", "reverse", "rex", "rtorder",
    "savedsearch", "search", "selfjoin", "sendalert", "sendemail",
    "set", "setfields", "sichart", "sirare", "sistats", "sitimechart",
    "sitop", "sort", "spath", "stats", "strcat", "streamstats",
    "table", "tags", "tail", "timechart", "timewrap", "tojson",
    "top", "transaction", "transpose", "trendline", "tscollect",
    "tstats", "typeahead", "typelearner", "typer", "union", "uniq",
    "untable", "where", "x11", "xmlkv", "xmlunescape", "xpath",
    "xyseries",
}
