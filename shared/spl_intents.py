"""
Splunk-specific intents for NLP-to-SPL generation.
"""
from enum import Enum

class SPLIntent(Enum):
    """Classification of what the user wants to do."""
    # Search & Retrieval
    SEARCH_EVENTS = "search_events"
    SEARCH_BY_FIELD = "search_by_field"
    SEARCH_PATTERN = "search_pattern"

    # Aggregation & Statistics
    COUNT_EVENTS = "count_events"
    TOP_VALUES = "top_values"
    RARE_EVENTS = "rare_events"
    TIMECHART = "timechart"
    STATS_BY_FIELD = "stats_by_field"

    # Security & Threat Detection
    FAILED_LOGINS = "failed_logins"
    BRUTE_FORCE_DETECTION = "brute_force_detection"
    ANOMALY_DETECTION = "anomaly_detection"
    DATA_EXFILTRATION = "data_exfiltration"
    PRIVILEGE_ESCALATION = "privilege_escalation"

    # Performance & Troubleshooting
    ERROR_ANALYSIS = "error_analysis"
    LATENCY_ANALYSIS = "latency_analysis"
    THROUGHPUT_METRICS = "throughput_metrics"

    # Compliance & Audit
    USER_ACTIVITY = "user_activity"
    ACCESS_AUDIT = "access_audit"
    CHANGE_TRACKING = "change_tracking"

    # Data Pipeline
    SOURCE_MONITORING = "source_monitoring"
    INDEXING_PERFORMANCE = "indexing_performance"
    FORWARDER_HEALTH = "forwarder_health"

    # Network & Infrastructure
    NETWORK_TRAFFIC = "network_traffic"
    FIREWALL_DENIES = "firewall_denies"
    VPN_CONNECTIONS = "vpn_connections"
    DNS_QUERIES = "dns_queries"

    # Application Performance
    APP_ERRORS = "app_errors"
    APP_TRANSACTIONS = "app_transactions"
    API_PERFORMANCE = "api_performance"

# Intent-specific query templates with intelligent defaults
INTENT_TEMPLATES = {
    SPLIntent.FAILED_LOGINS: {
        "template": (
            "index={index} sourcetype={sourcetype} {failed_login_patterns} "
            "earliest={time_start} latest={time_end} "
            "| stats count as failed_attempts by {user_field}, {source_field} "
            "| where failed_attempts > {threshold} "
            "| sort - failed_attempts"
        ),
        "default_params": {
            "index": "wineventlog",
            "sourcetype": "WinEventLog:Security",
            "failed_login_patterns": "EventCode=4625",
            "user_field": "user",
            "source_field": "src_ip",
            "threshold": 3,
            "time_start": "-1h",
            "time_end": "now",
        },
    },
    SPLIntent.BRUTE_FORCE_DETECTION: {
        "template": (
            "| tstats count WHERE index={index} TERM(EventCode=4625) "
            "earliest={time_start} latest={time_end} BY _time span=1m, user, src_ip "
            "| bin _time span=5m "
            "| stats count as attempts by _time, user, src_ip "
            "| where attempts > 5 "
            "| sort - attempts | head 100"
        ),
        "default_params": {
            "index": "wineventlog",
            "time_start": "-1h",
            "time_end": "now",
        },
    },
    SPLIntent.COUNT_EVENTS: {
        "template": (
            "index={index} earliest={time_start} latest={time_end} "
            "| stats count by {group_field}"
        ),
        "default_params": {
            "index": "main",
            "group_field": "host",
            "time_start": "-1h",
            "time_end": "now",
        },
    },
    SPLIntent.TOP_VALUES: {
        "template": (
            "index={index} earliest={time_start} latest={time_end} "
            "| top limit={limit} {field}"
        ),
        "default_params": {
            "index": "main",
            "field": "host",
            "limit": 10,
            "time_start": "-24h",
            "time_end": "now",
        },
    },
    SPLIntent.RARE_EVENTS: {
        "template": (
            "index={index} earliest={time_start} latest={time_end} "
            "| rare limit={limit} {field}"
        ),
        "default_params": {
            "index": "main",
            "field": "sourcetype",
            "limit": 20,
            "time_start": "-24h",
            "time_end": "now",
        },
    },
    SPLIntent.TIMECHART: {
        "template": (
            "index={index} earliest={time_start} latest={time_end} "
            "| timechart span={span} count by {split_field}"
        ),
        "default_params": {
            "index": "main",
            "span": "1h",
            "split_field": "sourcetype",
            "time_start": "-24h",
            "time_end": "now",
        },
    },
    SPLIntent.ERROR_ANALYSIS: {
        "template": (
            "index={index} TERM(error) OR TERM(ERROR) OR TERM(exception) "
            "earliest={time_start} latest={time_end} "
            "| stats count by sourcetype, host "
            "| sort - count"
        ),
        "default_params": {
            "index": "main",
            "time_start": "-4h",
            "time_end": "now",
        },
    },
    SPLIntent.NETWORK_TRAFFIC: {
        "template": (
            "| tstats summariesonly=t count from datamodel=Network_Traffic.All_Traffic "
            "where earliest={time_start} latest={time_end} "
            "by All_Traffic.src, All_Traffic.dest, All_Traffic.action "
            "| sort - count | head 50"
        ),
        "default_params": {
            "time_start": "-4h",
            "time_end": "now",
        },
    },
    SPLIntent.FIREWALL_DENIES: {
        "template": (
            "index={index} TERM(action=denied) OR TERM(action=blocked) "
            "earliest={time_start} latest={time_end} "
            "| stats count by src_ip, dest_ip, dest_port "
            "| sort - count | head 50"
        ),
        "default_params": {
            "index": "firewall",
            "time_start": "-4h",
            "time_end": "now",
        },
    },
    SPLIntent.DNS_QUERIES: {
        "template": (
            "index={index} earliest={time_start} latest={time_end} "
            "| stats count by query, query_type, src_ip "
            "| sort - count | head 50"
        ),
        "default_params": {
            "index": "dns",
            "time_start": "-1h",
            "time_end": "now",
        },
    },
    SPLIntent.VPN_CONNECTIONS: {
        "template": (
            "index={index} earliest={time_start} latest={time_end} "
            "| stats count by user, src_ip, action "
            "| sort - count"
        ),
        "default_params": {
            "index": "vpn",
            "time_start": "-24h",
            "time_end": "now",
        },
    },
    SPLIntent.PRIVILEGE_ESCALATION: {
        "template": (
            "index={index} (EventCode=4728 OR EventCode=4732 OR EventCode=4756) "
            "earliest={time_start} latest={time_end} "
            "| table _time, user, MemberName, Group_Name, EventCode "
            "| sort - _time"
        ),
        "default_params": {
            "index": "wineventlog",
            "time_start": "-24h",
            "time_end": "now",
        },
    },
    SPLIntent.USER_ACTIVITY: {
        "template": (
            "index={index} user={user} earliest={time_start} latest={time_end} "
            "| stats count by action, sourcetype, host "
            "| sort - count"
        ),
        "default_params": {
            "index": "main",
            "user": "*",
            "time_start": "-24h",
            "time_end": "now",
        },
    },
    SPLIntent.INDEXING_PERFORMANCE: {
        "template": (
            "index=_internal sourcetype=splunkd group=per_index_thruput "
            "earliest={time_start} latest={time_end} "
            "| stats sum(kb) as total_kb by series "
            "| sort - total_kb"
        ),
        "default_params": {
            "time_start": "-1h",
            "time_end": "now",
        },
    },
    SPLIntent.FORWARDER_HEALTH: {
        "template": (
            "index=_internal sourcetype=splunkd group=tcpin_connections "
            "earliest={time_start} latest={time_end} "
            "| stats latest(connectionType) as type, latest(version) as version, "
            "latest(fwdType) as fwdType, latest(ssl) as ssl by hostname "
            "| sort hostname"
        ),
        "default_params": {
            "time_start": "-15m",
            "time_end": "now",
        },
    },
    SPLIntent.SOURCE_MONITORING: {
        "template": (
            "| tstats count where index=* earliest={time_start} latest={time_end} "
            "by index, sourcetype, host "
            "| sort - count"
        ),
        "default_params": {
            "time_start": "-1h",
            "time_end": "now",
        },
    },
    SPLIntent.ANOMALY_DETECTION: {
        "template": (
            "index={index} earliest={time_start} latest={time_end} "
            "| timechart span=1h count by host "
            "| foreach * [eval <<FIELD>>_z = (<<FIELD>> - avg(<<FIELD>>)) / stdev(<<FIELD>>)] "
            "| where abs(count_z) > 2"
        ),
        "default_params": {
            "index": "main",
            "time_start": "-7d",
            "time_end": "now",
        },
    },
    SPLIntent.APP_ERRORS: {
        "template": (
            "index={index} (TERM(error) OR TERM(exception) OR TERM(fatal)) "
            "earliest={time_start} latest={time_end} "
            "| stats count by sourcetype, host, source "
            "| sort - count"
        ),
        "default_params": {
            "index": "main",
            "time_start": "-4h",
            "time_end": "now",
        },
    },
    SPLIntent.LATENCY_ANALYSIS: {
        "template": (
            "index={index} earliest={time_start} latest={time_end} "
            "| stats avg(response_time) as avg_ms, "
            "p95(response_time) as p95_ms, "
            "max(response_time) as max_ms by host "
            "| sort - avg_ms"
        ),
        "default_params": {
            "index": "main",
            "time_start": "-1h",
            "time_end": "now",
        },
    },
}
