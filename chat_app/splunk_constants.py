"""
Splunk Constants - Allowed Commands and Configuration Files

This module defines the canonical lists of built-in Splunk search commands
and configuration files. These are used for:
1. Validation during ingestion (only allowed files are indexed)
2. Hallucination prevention (LLM can only reference these + org-specific)
3. Reference generation (only allowed files get public URLs)

NOTE: Any command or conf file NOT in these lists is considered:
- Custom (from Splunk App or Technology Add-on)
- Organization-specific (from org_repo collection)
- Should ONLY be referenced if explicitly found in context chunks
"""

# =============================================================================
# ALLOWED SPLUNK SEARCH COMMANDS
# =============================================================================
# Source: Official Splunk 9.x documentation
# Last updated: 2026-01-04
# These are the ONLY built-in SPL commands the LLM should reference confidently
# Any other command mentioned must be qualified as "custom" or "app-specific"

ALLOWED_SEARCH_COMMANDS = {
    "abstract",
    "accum",
    "addcoltotals",
    "addinfo",
    "addtotals",
    "analyzefields",
    "anomalies",
    "anomalousvalue",
    "anomalydetection",
    "append",
    "appendcols",
    "appendpipe",
    "arules",
    "associate",
    "autoregress",
    "bin",
    "bucket",
    "bucketdir",
    "chart",
    "chart-arguments",
    "cluster",
    "cofilter",
    "collapse",
    "collect",
    "concurrency",
    "contingency",
    "convert",
    "copyresults",
    "correlate",
    "createrss",
    "datamodel",
    "dbinspect",
    "debug",
    "dedup",
    "delete",
    "delta",
    "diff",
    "dispatch",
    "dump",
    "editinfo",
    "erex",
    "eval",
    "eventcount",
    "eventstats",
    "extract",
    "fieldformat",
    "fields",
    "fieldsummary",
    "filldown",
    "fillnull",
    "findkeywords",
    "findtypes",
    "folderize",
    "foreach",
    "format",
    "from",
    "fromjson",
    "gauge",
    "gentimes",
    "geom",
    "geomfilter",
    "geostats",
    "head",
    "highlight",
    "history",
    "iconify",
    "ingestpreview",
    "input",
    "inputcsv",
    "inputlookup",
    "iplocation",
    "join",
    "kmeans",
    "kv",
    "kvform",
    "loadjob",
    "localize",
    "localop",
    "lookup",
    "makecontinuous",
    "makemv",
    "makeresults",
    "map",
    "mcatalog",
    "mcollect",
    "metadata",
    "metasearch",
    "meventcollect",
    "mpreview",
    "mrollup",
    "mstats",
    "multikv",
    "multisearch",
    "mvcombine",
    "mvexpand",
    "nokv",
    "nomv",
    "oldreturn",
    "outlier",
    "outputcsv",
    "outputlookup",
    "outputraw",
    "outputtext",
    "overlap",
    "pivot",
    "predict",
    "preview",
    "prjob",
    "rangemap",
    "rare",
    "rawstats",
    "redistribute",
    "regex",
    "reltime",
    "rename",
    "replace",
    "require",
    "rest",
    "return",
    "reverse",
    "rex",
    "rtorder",
    "runshellscript",
    "savedsearch",
    "script",
    "scrub",
    "search",
    "searchtxn",
    "selfjoin",
    "sendalert",
    "sendemail",
    "set",
    "setfields",
    "showargs",
    "sichart",
    "sirare",
    "sistats",
    "sitimechart",
    "sitop",
    "sort",
    "spath",
    "stats",
    "stats-arguments",
    "strcat",
    "streamstats",
    "surrounding",
    "table",
    "tags",
    "tail",
    "timechart",
    "timechart-arguments",
    "timewrap",
    "tojson",
    "tojson-arguments",
    "top",
    "top-arguments",
    "transaction",
    "transpose",
    "trendline",
    "tscollect",
    "tstats",
    "typeahead",
    "typelearner",
    "typer",
    "union",
    "uniq",
    "untable",
    "walklex",
    "where",
    "x11",
    "xmlkv",
    "xmlunescape",
    "xpath",
    "xyseries",
}

# =============================================================================
# ALLOWED CONFIGURATION FILES
# =============================================================================
# Source: Official Splunk 9.x documentation - Configuration File Reference
# Last updated: 2026-01-04
# These are the ONLY built-in .conf files the LLM should reference confidently
# Any other .conf file mentioned must be qualified as "custom" or "app-specific"

ALLOWED_CONF_FILES = {
    "alert_actions.conf",
    "app.conf",
    "audit.conf",
    "authentication.conf",
    "authorize.conf",
    "bookmarks.conf",
    "checklist.conf",
    "collections.conf",
    "commands.conf",
    "conf.conf",
    "datamodels.conf",
    "datatypesbnf.conf",
    "default-mode.conf",
    "deployment.conf",
    "deploymentclient.conf",
    "distsearch.conf",
    "event_renderers.conf",
    "eventdiscoverer.conf",
    "eventtypes.conf",
    "federated.conf",
    "field_filters.conf",
    "fields.conf",
    "global-banner.conf",
    "health.conf",
    "indexes.conf",
    "inputs.conf",
    "instance.cfg",
    "limits.conf",
    "literals.conf",
    "livetail.conf",
    "macros.conf",
    "messages.conf",
    "metric_alerts.conf",
    "metric_rollups.conf",
    "migration.conf",
    "multikv.conf",
    "outputs.conf",
    "passwords.conf",
    "procmon-filters.conf",
    "props.conf",
    "pubsub.conf",
    "restmap.conf",
    "savedsearches.conf",
    "searchbnf.conf",
    "segmenters.conf",
    "server.conf",
    "serverclass.conf",
    "serverclass.seed.xml",
    "setup.xml",
    "source-classifier.conf",
    "sourcetypes.conf",
    "splunk-launch.conf",
    "tags.conf",
    "telemetry.conf",
    "times.conf",
    "transactiontypes.conf",
    "transforms.conf",
    "ui-prefs.conf",
    "ui-tour.conf",
    "user-prefs.conf",
    "user-seed.conf",
    "viewstates.conf",
    "visualizations.conf",
    "web-features.conf",
    "web.conf",
    "wmi.conf",
    "workflow_actions.conf",
    "workload_policy.conf",
    "workload_pools.conf",
    "workload_rules.conf",
}

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def is_allowed_command(command: str) -> bool:
    """Check if a command is in the allowed list (case-insensitive)."""
    return command.lower() in ALLOWED_SEARCH_COMMANDS


def is_allowed_conf_file(filename: str) -> bool:
    """Check if a conf file is in the allowed list.

    Args:
        filename: Name like "inputs.conf" or "inputs.conf.spec"

    Returns:
        True if the base conf file is allowed
    """
    # Remove .spec suffix if present
    base_name = filename.replace(".spec", "")
    return base_name in ALLOWED_CONF_FILES


def get_command_type(command: str) -> str:
    """Classify command as built-in, custom, or unknown.

    Returns:
        "built-in", "custom", or "unknown"
    """
    if is_allowed_command(command):
        return "built-in"
    # If command contains app-specific patterns
    if any(pattern in command.lower() for pattern in ["app_", "ta_", "addon_"]):
        return "custom"
    return "unknown"


def get_conf_file_type(filename: str) -> str:
    """Classify conf file as built-in, custom, or unknown.

    Returns:
        "built-in", "custom", or "unknown"
    """
    if is_allowed_conf_file(filename):
        return "built-in"
    # App-specific conf files often have app prefix
    if any(pattern in filename.lower() for pattern in ["app_", "ta_", "addon_", "local/"]):
        return "custom"
    return "unknown"


def format_allowed_commands_for_prompt() -> str:
    """Format allowed commands as a compact string for prompt injection."""
    return ", ".join(sorted(ALLOWED_SEARCH_COMMANDS))


def format_allowed_conf_files_for_prompt() -> str:
    """Format allowed conf files as a compact string for prompt injection."""
    return ", ".join(sorted(ALLOWED_CONF_FILES))


# =============================================================================
# VALIDATION STATS (for logging/debugging)
# =============================================================================

TOTAL_ALLOWED_COMMANDS = len(ALLOWED_SEARCH_COMMANDS)
TOTAL_ALLOWED_CONF_FILES = len(ALLOWED_CONF_FILES)

if __name__ == "__main__":
    print(f"Total allowed SPL commands: {TOTAL_ALLOWED_COMMANDS}")
    print(f"Total allowed .conf files: {TOTAL_ALLOWED_CONF_FILES}")
    print(f"\nSample commands: {list(ALLOWED_SEARCH_COMMANDS)[:10]}")
    print(f"\nSample conf files: {list(ALLOWED_CONF_FILES)[:10]}")
