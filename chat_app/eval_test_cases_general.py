"""
General/config/org test case data and generators for RAG evaluation.

Contains:
- Configuration file data (CONF_FILES, CONF_TEMPLATES, CONF_SCENARIOS)
- Troubleshooting queries (TROUBLESHOOTING_QUERIES)
- Best practice queries (BEST_PRACTICE_QUERIES)
- Organization-specific queries (ORG_QUERIES)
- Cribl queries (CRIBL_QUERIES)
- Compound/multi-step queries (COMPOUND_QUERIES)
- Generator functions for general test cases

Imported by eval_test_cases.py which combines all cases.
"""

from typing import List

from chat_app.eval_test_cases_base import TestCase


# ============================================================================
# Config / Spec file questions
# ============================================================================

CONF_FILES = [
    "inputs.conf", "outputs.conf", "props.conf", "transforms.conf", "indexes.conf",
    "server.conf", "web.conf", "limits.conf", "authorize.conf", "authentication.conf",
    "alert_actions.conf", "commands.conf", "deploymentclient.conf", "distsearch.conf",
    "eventtypes.conf", "fields.conf", "macros.conf", "savedsearches.conf",
    "serverclass.conf", "tags.conf", "times.conf", "transactiontypes.conf",
    "app.conf", "collections.conf", "restmap.conf", "workflow_actions.conf",
]

CONF_TEMPLATES = [
    "What are the settings in {conf}?",
    "How do I configure {conf}?",
    "Show me the stanzas for {conf}",
    "What is the default {conf} configuration?",
    "How to set up {conf} for {scenario}?",
    "What does the {setting} setting do in {conf}?",
    "How to troubleshoot {conf} issues?",
    "Best practices for {conf}",
    "What stanzas are available in {conf}?",
    "How to restart after changing {conf}?",
    "Where is {conf} located in a Splunk app?",
    "Precedence order for {conf} files",
    "Can I override {conf} at the app level?",
    "Example of a complete {conf} file",
    "What is the spec file for {conf}?",
    "How to validate {conf} settings?",
    "Common mistakes in {conf}",
    "Default vs local {conf} differences",
]

CONF_SCENARIOS = {
    "inputs.conf": ["monitor a log file", "listen on TCP port 514", "set up a scripted input", "monitor a directory", "UDP syslog input"],
    "outputs.conf": ["forward to indexers", "load balance across indexers", "set up SSL forwarding", "configure indexer acknowledgment", "syslog output"],
    "props.conf": ["set a custom sourcetype", "configure line breaking", "set time format", "field extraction at index time", "configure truncation"],
    "transforms.conf": ["create a field extraction", "set up a lookup", "route data to an index", "mask sensitive data", "create a field alias"],
    "indexes.conf": ["create a new index", "set retention policy", "configure frozen path", "set max data size", "enable tsidx reduction"],
    "server.conf": ["configure SSL", "set replication factor", "configure search factor", "set up clustering", "configure KV store"],
    "limits.conf": ["increase max results", "set search time limit", "configure concurrent searches", "increase dispatch buckets", "set real-time search limit"],
    "authorize.conf": ["create a custom role", "set search filter", "grant index access", "set search time window", "configure capabilities"],
    "savedsearches.conf": ["schedule a saved search", "set alert conditions", "configure email notification", "set up summary indexing", "schedule report"],
}


# ============================================================================
# Troubleshooting queries
# ============================================================================

TROUBLESHOOTING_QUERIES = [
    # Search issues
    ("My search is returning no results", "search", ["index", "sourcetype", "time range", "permissions"]),
    ("Search is taking too long", "performance", ["tstats", "fields", "filter early", "time range"]),
    ("Getting 'max results' warning", "limits", ["limits.conf", "max_count", "maxresultrows"]),
    ("Search head is running out of memory", "performance", ["limits.conf", "search_process_memory", "dispatch"]),
    ("Real-time search is not updating", "realtime", ["real-time", "indexer", "latest"]),
    ("Subsearch is not returning results", "subsearch", ["return", "format", "maxresultrows"]),
    # Data issues
    ("Data is not being indexed", "indexing", ["inputs.conf", "monitor", "sourcetype", "permissions"]),
    ("Events have wrong timestamps", "timestamp", ["props.conf", "TIME_FORMAT", "TIME_PREFIX", "MAX_TIMESTAMP_LOOKAHEAD"]),
    ("Line breaking is incorrect", "parsing", ["props.conf", "LINE_BREAKER", "SHOULD_LINEMERGE", "TRUNCATE"]),
    ("Field extractions are not working", "extraction", ["props.conf", "transforms.conf", "EXTRACT", "REPORT"]),
    ("Sourcetype is not being recognized", "sourcetype", ["props.conf", "sourcetype", "default"]),
    ("Data is going to the wrong index", "routing", ["transforms.conf", "DEST_KEY", "REGEX", "FORMAT"]),
    ("Events are being truncated", "truncation", ["props.conf", "TRUNCATE", "MAX_EVENTS"]),
    ("Lookup is not enriching events", "lookup", ["transforms.conf", "props.conf", "automatic_lookup"]),
    # Cluster issues
    ("Search head cluster captain election failing", "clustering", ["server.conf", "shcluster", "captain"]),
    ("Indexer cluster replication not working", "clustering", ["server.conf", "replication_factor", "cluster_master"]),
    ("License warning or violation", "license", ["license", "volume", "daily"]),
    ("Deployment server not pushing apps", "deployment", ["serverclass.conf", "deploymentclient.conf", "clientName"]),
    # Forwarder issues
    ("Universal forwarder not sending data", "forwarder", ["outputs.conf", "server", "tcpout", "defaultGroup"]),
    ("Forwarder queue is blocked", "forwarder", ["outputs.conf", "maxQueueSize", "tcpout"]),
    ("Forwarder SSL certificate error", "forwarder", ["outputs.conf", "sslCertPath", "sslRootCAPath"]),
    ("Heavy forwarder parsing issues", "forwarder", ["props.conf", "transforms.conf", "INDEXED_EXTRACTIONS"]),
]


# ============================================================================
# Best practices and architecture
# ============================================================================

BEST_PRACTICE_QUERIES = [
    # Search optimization
    ("What are SPL search optimization best practices?", "optimization", ["tstats", "fields", "time range"]),
    ("How to write efficient Splunk searches?", "optimization", ["filter early", "stats", "tstats"]),
    ("When should I use tstats vs stats?", "optimization", ["tstats", "stats", "indexed fields", "data model"]),
    ("How to reduce search runtime?", "optimization", ["time range", "index", "sourcetype", "fields"]),
    ("What makes a search slow?", "optimization", ["wildcards", "join", "subsearch", "NOT"]),
    ("How to use summary indexing?", "optimization", ["collect", "summary", "scheduled"]),
    ("Accelerated data models best practices", "optimization", ["datamodel", "acceleration", "tstats"]),
    ("How to optimize timechart queries?", "optimization", ["timechart", "span", "limit"]),
    ("Best practices for using eval", "optimization", ["eval", "where", "case", "if"]),
    ("How to avoid expensive searches?", "optimization", ["join", "subsearch", "wildcards", "NOT"]),
    # Architecture
    ("What is the Splunk architecture?", "architecture", ["indexer", "search head", "forwarder"]),
    ("How does search head clustering work?", "architecture", ["captain", "replication", "deployer"]),
    ("What is the indexer cluster?", "architecture", ["cluster_master", "peer", "replication_factor"]),
    ("How to size a Splunk deployment?", "architecture", ["daily volume", "retention", "hardware"]),
    ("What is the deployment server?", "architecture", ["serverclass", "deployment", "apps"]),
    # Data management
    ("How to manage data retention?", "data_mgmt", ["indexes.conf", "frozenTimePeriodInSecs", "maxTotalDataSizeMB"]),
    ("How to set up data archiving?", "data_mgmt", ["frozen", "coldToFrozenDir", "archive"]),
    ("Index-time vs search-time extraction?", "data_mgmt", ["props.conf", "INDEXED_EXTRACTIONS", "EXTRACT"]),
    ("How to use CIM for data normalization?", "data_mgmt", ["CIM", "data model", "field alias", "tag"]),
    ("How to onboard a new data source?", "data_mgmt", ["inputs.conf", "props.conf", "transforms.conf"]),
]


# ============================================================================
# Organization/repo specific queries
# ============================================================================

ORG_QUERIES = [
    # Index-specific
    ("What data is in the network index?", "org", ["network", "index"]),
    ("What sourcetypes are in the snow index?", "org", ["snow", "sourcetype"]),
    ("Show me the pan_logs index fields", "org", ["pan_logs", "fields"]),
    ("What lookups are available?", "org", ["lookup", "inputlookup"]),
    ("What saved searches exist for network monitoring?", "org", ["savedsearch", "network"]),
    ("What macros are defined?", "org", ["macros.conf", "definition"]),
    ("Show me the custom field extractions", "org", ["props.conf", "transforms.conf", "EXTRACT"]),
    # Business context
    ("How to find events for a specific business unit?", "org", ["u_business_unit", "unit_id"]),
    ("What is the circuit field used for?", "org", ["circuit", "network"]),
    ("How to correlate network events with ServiceNow?", "org", ["join", "snow", "network"]),
    ("What is the infoblox_networks_lite lookup?", "org", ["lookup", "infoblox", "network"]),
    ("How to find events by unit_id?", "org", ["unit_id", "index=network"]),
]


# ============================================================================
# Cribl queries
# ============================================================================

CRIBL_QUERIES = [
    ("What is Cribl Stream?", "cribl", ["Cribl", "Stream", "pipeline"]),
    ("How to set up a Cribl pipeline?", "cribl", ["pipeline", "route", "function"]),
    ("How to filter events in Cribl?", "cribl", ["filter", "drop", "suppress"]),
    ("How to route data in Cribl?", "cribl", ["route", "pipeline", "destination"]),
    ("How to mask sensitive data in Cribl?", "cribl", ["mask", "regex", "replace"]),
    ("How to reduce data volume with Cribl?", "cribl", ["sampling", "aggregation", "suppress"]),
    ("Cribl vs Splunk HEC for data ingestion?", "cribl", ["HEC", "Cribl", "ingestion"]),
    ("How to set up Cribl sources?", "cribl", ["source", "input", "Cribl"]),
    ("How to send data from Cribl to Splunk?", "cribl", ["destination", "Splunk", "HEC"]),
    ("Cribl processing functions", "cribl", ["function", "eval", "regex", "lookup"]),
    ("How to parse data in Cribl?", "cribl", ["parser", "function", "pipeline"]),
    ("Cribl Edge vs Cribl Stream", "cribl", ["Edge", "Stream", "agent"]),
]


# ============================================================================
# Compound / multi-step queries
# ============================================================================

COMPOUND_QUERIES = [
    ("Show me network errors, then group by source IP and show the trend", "compound",
     ["index=network", "error", "stats", "timechart", "src_ip"]),
    ("Find failed logins, lookup the user details, and alert if more than 10", "compound",
     ["index=", "failure", "lookup", "where count", "sendalert"]),
    ("Get firewall blocks, enrich with geo data, show on a map", "compound",
     ["index=firewall", "blocked", "iplocation", "geostats"]),
    ("Compare CPU usage between this week and last week", "compound",
     ["index=os", "cpu", "timechart", "timewrap", "compare"]),
    ("Find the top talkers, exclude internal IPs, show their activity", "compound",
     ["index=network", "NOT 10.", "NOT 192.168.", "stats", "top"]),
    ("Get incidents, calculate resolution time, show average by priority", "compound",
     ["index=snow", "eval", "duration", "stats avg", "priority"]),
    ("Monitor API errors, correlate with deployments, send alert", "compound",
     ["index=api", "status>=500", "transaction", "alert"]),
    ("Find anomalous network behavior and create a notable event", "compound",
     ["index=network", "anomalydetection", "collect", "notable"]),
]


# ============================================================================
# Generator functions
# ============================================================================

def _generate_config_cases() -> List[TestCase]:
    """Generate configuration file questions."""
    cases = []
    for conf in CONF_FILES:
        for template in CONF_TEMPLATES:
            if "{scenario}" in template:
                scenarios = CONF_SCENARIOS.get(conf, ["default settings"])
                for scenario in scenarios:
                    q = template.format(conf=conf, scenario=scenario, setting="[default]")
                    cases.append(TestCase(
                        query=q,
                        category="config",
                        expected_collection="specs_mxbai_embed_large_v3",
                        expected_keywords=[conf.replace(".conf", "")],
                        difficulty="medium",
                        expected_type="config",
                    ))
            elif "{setting}" in template:
                settings_map = {
                    "inputs.conf": ["index", "sourcetype", "disabled", "interval"],
                    "outputs.conf": ["server", "defaultGroup", "sslCertPath"],
                    "props.conf": ["TIME_FORMAT", "LINE_BREAKER", "TRUNCATE"],
                    "transforms.conf": ["REGEX", "FORMAT", "DEST_KEY"],
                    "indexes.conf": ["homePath", "coldPath", "maxTotalDataSizeMB"],
                    "server.conf": ["sslKeysfile", "pass4SymmKey", "replication_factor"],
                    "limits.conf": ["max_count", "maxresultrows", "max_searches_per_cpu"],
                }
                for setting in settings_map.get(conf, ["default"]):
                    q = template.format(conf=conf, setting=setting)
                    cases.append(TestCase(
                        query=q,
                        category="config",
                        expected_collection="specs_mxbai_embed_large_v3",
                        expected_keywords=[conf.replace(".conf", ""), setting],
                        difficulty="medium",
                        expected_type="config",
                    ))
            else:
                q = template.format(conf=conf)
                cases.append(TestCase(
                    query=q,
                    category="config",
                    expected_collection="specs_mxbai_embed_large_v3",
                    expected_keywords=[conf.replace(".conf", "")],
                    difficulty="easy",
                    expected_type="config",
                ))
    return cases


def _generate_troubleshooting_cases() -> List[TestCase]:
    """Generate troubleshooting questions."""
    cases = []
    for query, cat, keywords in TROUBLESHOOTING_QUERIES:
        cases.append(TestCase(
            query=query,
            category=f"troubleshoot_{cat}",
            expected_collection="specs_mxbai_embed_large_v3",
            expected_keywords=keywords,
            difficulty="hard",
            expected_type="troubleshoot",
        ))
        # Variations
        for prefix in ["How to fix: ", "Troubleshoot: ", "Help with: "]:
            cases.append(TestCase(
                query=prefix + query.lower(),
                category=f"troubleshoot_{cat}",
                expected_collection="specs_mxbai_embed_large_v3",
                expected_keywords=keywords,
                difficulty="hard",
                expected_type="troubleshoot",
            ))
    return cases


def _generate_best_practice_cases() -> List[TestCase]:
    """Generate best practice questions."""
    cases = []
    for query, cat, keywords in BEST_PRACTICE_QUERIES:
        cases.append(TestCase(
            query=query,
            category=f"best_practice_{cat}",
            expected_collection="spl_commands_mxbai",
            expected_keywords=keywords,
            difficulty="medium",
            expected_type="optimization",
        ))
    return cases


def _generate_org_cases() -> List[TestCase]:
    """Generate organization-specific questions."""
    cases = []
    for query, cat, keywords in ORG_QUERIES:
        cases.append(TestCase(
            query=query,
            category="org_specific",
            expected_collection="org_repo_mxbai",
            expected_keywords=keywords,
            difficulty="medium",
            expected_type="config",
        ))
    return cases


def _generate_cribl_cases() -> List[TestCase]:
    """Generate Cribl questions."""
    cases = []
    for query, cat, keywords in CRIBL_QUERIES:
        cases.append(TestCase(
            query=query,
            category="cribl",
            expected_collection="cribl_docs_mxbai",
            expected_keywords=keywords,
            difficulty="medium",
            expected_type="command_help",
        ))
    return cases


def _generate_compound_cases() -> List[TestCase]:
    """Generate compound/multi-step questions."""
    cases = []
    for query, cat, keywords in COMPOUND_QUERIES:
        cases.append(TestCase(
            query=query,
            category="compound",
            expected_collection="spl_commands_mxbai",
            expected_keywords=keywords,
            difficulty="hard",
            expected_type="generation",
        ))
    return cases


def generate_general_test_cases() -> List[TestCase]:
    """Generate all general/config test cases."""
    cases = []
    cases.extend(_generate_config_cases())
    cases.extend(_generate_troubleshooting_cases())
    cases.extend(_generate_best_practice_cases())
    cases.extend(_generate_org_cases())
    cases.extend(_generate_cribl_cases())
    cases.extend(_generate_compound_cases())
    return cases
