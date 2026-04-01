"""
Troubleshooter Skill — Systematic diagnosis of Splunk issues, fix suggestions,
connectivity checks, and internal log analysis.

Each function is a standalone action handler invoked by the SkillsManager.
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Decision tree for diagnosis
# ---------------------------------------------------------------------------

_DIAGNOSIS_TREE: Dict[str, Dict[str, Any]] = {
    "search_slow": {
        "keywords": ["slow search", "search takes long", "search performance", "search timeout",
                      "long running search", "search hung"],
        "category": "search_performance",
        "diagnosis": "Slow search performance detected",
        "checks": [
            "Check if the search uses wildcard index (index=*)",
            "Look for expensive commands early in the pipeline (join, transaction, map)",
            "Verify the time range is not excessively broad",
            "Check for dense search patterns in the scheduler",
            "Review dispatch directory for search artifacts",
        ],
        "spl_diagnostic": (
            'index=_internal sourcetype=splunkd component=SearchScheduler '
            '| stats avg(run_time) max(run_time) count by savedsearch_name '
            '| where avg(run_time) > 60 | sort -avg(run_time)'
        ),
    },
    "indexing_lag": {
        "keywords": ["indexing lag", "data delay", "events not showing", "missing data",
                      "ingestion lag", "queue full", "blocked queue"],
        "category": "indexing",
        "diagnosis": "Data indexing lag or queue congestion",
        "checks": [
            "Check the indexing pipeline queues (parsing, merging, typing)",
            "Verify disk I/O performance on indexers",
            "Check for license violations that may block indexing",
            "Review props.conf for excessive index-time extractions",
            "Verify forwarder connections to indexers",
        ],
        "spl_diagnostic": (
            'index=_internal sourcetype=splunkd component=Metrics group=queue '
            '| eval fill_pct=round((current_size/max_size)*100, 2) '
            '| stats avg(fill_pct) max(fill_pct) by name '
            '| where max(fill_pct) > 80'
        ),
    },
    "forwarder_issue": {
        "keywords": ["forwarder", "uf", "universal forwarder", "not forwarding",
                      "forwarder down", "no data from forwarder"],
        "category": "forwarder",
        "diagnosis": "Forwarder connectivity or data flow issue",
        "checks": [
            "Verify the forwarder process is running",
            "Check outputs.conf for correct indexer addresses",
            "Review inputs.conf for correct monitor paths",
            "Check for firewall rules blocking port 9997",
            "Verify certificate validity for SSL connections",
        ],
        "spl_diagnostic": (
            'index=_internal sourcetype=splunkd component=TcpOutputProc '
            '| stats latest(_time) as last_seen count by host '
            '| eval minutes_ago=round((now()-last_seen)/60,1) '
            '| where minutes_ago > 15 | sort -minutes_ago'
        ),
    },
    "license_issue": {
        "keywords": ["license", "license violation", "license exceeded", "license pool",
                      "license warning", "daily volume"],
        "category": "licensing",
        "diagnosis": "License-related issue detected",
        "checks": [
            "Check current daily indexed volume vs. license limit",
            "Identify top sourcetypes contributing to license usage",
            "Look for unexpected data sources or duplicated data",
            "Verify license pool assignments",
            "Check for license slave connectivity to master",
        ],
        "spl_diagnostic": (
            'index=_internal sourcetype=splunkd component=LicenseUsage type=Usage '
            '| eval gb=b/1073741824 '
            '| stats sum(gb) as total_gb by pool, idx '
            '| sort -total_gb'
        ),
    },
    "auth_failure": {
        "keywords": ["authentication", "login failed", "access denied", "permission",
                      "unauthorized", "403", "401", "ldap", "saml"],
        "category": "authentication",
        "diagnosis": "Authentication or authorization failure",
        "checks": [
            "Verify user account status and role assignments",
            "Check LDAP/AD connectivity if using external auth",
            "Review authentication.conf for correct settings",
            "Check for expired SAML certificates",
            "Verify capability assignments for the user role",
        ],
        "spl_diagnostic": (
            'index=_audit action=login* '
            '| stats count by user, info, src '
            '| sort -count'
        ),
    },
    "crash_restart": {
        "keywords": ["crash", "restart", "segfault", "core dump", "out of memory",
                      "oom", "killed", "splunkd not running"],
        "category": "stability",
        "diagnosis": "Splunk service crash or unexpected restart",
        "checks": [
            "Check splunkd.log for crash stack traces",
            "Review system memory usage at time of crash",
            "Check for disk space issues",
            "Look for large lookup files or KV store issues",
            "Review ulimit settings for the splunk user",
        ],
        "spl_diagnostic": (
            'index=_internal sourcetype=splunkd (log_level=ERROR OR log_level=FATAL) '
            '| stats count by component, message '
            '| sort -count | head 20'
        ),
    },
    "replication_issue": {
        "keywords": ["replication", "cluster", "bucket", "peer", "captain",
                      "search factor", "replication factor"],
        "category": "clustering",
        "diagnosis": "Cluster replication or peer issue",
        "checks": [
            "Check cluster master/manager status",
            "Verify search factor and replication factor settings",
            "Look for peers in detention or down state",
            "Check for bucket fixup activities",
            "Review network connectivity between cluster peers",
        ],
        "spl_diagnostic": (
            'index=_internal sourcetype=splunkd component=CMPeer OR component=CMBucketFix '
            '| stats count by component, log_level, message '
            '| where log_level="ERROR" OR log_level="WARN" | sort -count'
        ),
    },
}

# ---------------------------------------------------------------------------
# Common error patterns and fixes
# ---------------------------------------------------------------------------

_ERROR_FIXES: Dict[str, Dict[str, Any]] = {
    "dispatch_dir_full": {
        "patterns": ["dispatch directory", "too many searches", "dispatch dir"],
        "description": "Dispatch directory has too many search artifacts",
        "fix": "Clean up dispatch directory: $SPLUNK_HOME/var/run/splunk/dispatch. "
               "Reduce concurrent searches or adjust limits.conf [search] max_searches_per_cpu.",
        "config": "limits.conf: [search]\nmax_searches_per_cpu = 2\ndispatch_dir_warning_size = 1000",
    },
    "kv_store_error": {
        "patterns": ["kvstore", "kv store", "mongodb", "collection"],
        "description": "KV Store / MongoDB error",
        "fix": "Check KV Store status: splunk show kvstore-status. If corrupted, "
               "run: splunk clean kvstore --local. Ensure mongod port 8191 is not blocked.",
        "config": "server.conf: [kvstore]\nport = 8191\n# storageEngine = wiredTiger",
    },
    "ssl_certificate": {
        "patterns": ["ssl", "certificate", "handshake", "tls", "cert expired"],
        "description": "SSL/TLS certificate error",
        "fix": "Check certificate expiry with: openssl x509 -enddate -noout -in server.pem. "
               "Regenerate certificates or update certificate chain.",
        "config": "server.conf: [sslConfig]\nenableSplunkdSSL = true\nsslVersions = tls1.2\n"
                  "serverCert = $SPLUNK_HOME/etc/auth/server.pem",
    },
    "memory_exceeded": {
        "patterns": ["out of memory", "oom", "memory limit", "cannot allocate"],
        "description": "Memory limit exceeded",
        "fix": "Increase memory limits or optimize searches. Check for memory-intensive commands "
               "(join, transaction, stats with high cardinality). Review limits.conf search_process_memory_usage_threshold.",
        "config": "limits.conf: [search]\nsearch_process_memory_usage_threshold = 0.25",
    },
    "bucket_corruption": {
        "patterns": ["bucket", "corrupt", "tsidx", "rawdata"],
        "description": "Index bucket corruption",
        "fix": "Rebuild bucket: splunk rebuild <bucket_path>. For severely corrupted buckets, "
               "remove the bucket and let replication restore from peers (clustered environment).",
        "config": "# Run: splunk rebuild /opt/splunk/var/lib/splunk/<index>/db/<bucket>",
    },
    "too_many_results": {
        "patterns": ["max result", "result limit", "too many results", "maxresults"],
        "description": "Search result limit exceeded",
        "fix": "Increase maxresultrows in limits.conf or add filtering to reduce result count. "
               "Default is 50000. Consider using summary indexing for large result sets.",
        "config": "limits.conf: [restapi]\nmaxresultrows = 50000\n\n[search]\nmax_count = 500000",
    },
    "lookup_error": {
        "patterns": ["lookup", "csv lookup", "lookup table", "automatic lookup"],
        "description": "Lookup table error",
        "fix": "Verify the lookup file exists in $SPLUNK_HOME/etc/apps/<app>/lookups/. "
               "Check file permissions. For large lookups (>100MB), consider using KV Store instead.",
        "config": "transforms.conf: [my_lookup]\nfilename = my_lookup.csv\nmax_matches = 1",
    },
}

# ---------------------------------------------------------------------------
# Connectivity check queries
# ---------------------------------------------------------------------------

_CONNECTIVITY_CHECKS: Dict[str, List[Dict[str, str]]] = {
    "forwarder": [
        {
            "name": "Active forwarders",
            "spl": ('index=_internal sourcetype=splunkd component=Metrics group=tcpin_connections '
                    '| stats dc(hostname) as forwarder_count latest(_time) as last_seen by sourceIp '
                    '| sort -last_seen'),
        },
        {
            "name": "Forwarders not seen recently",
            "spl": ('| rest /services/deployment/server/clients '
                    '| eval last_phone_home=strftime(lastPhoneHomeTime, "%Y-%m-%d %H:%M:%S") '
                    '| where lastPhoneHomeTime < relative_time(now(), "-1h") '
                    '| table clientName, ip, last_phone_home'),
        },
        {
            "name": "Forwarder data throughput",
            "spl": ('index=_internal sourcetype=splunkd component=Metrics group=tcpin_connections '
                    '| eval mb=kb/1024 | stats sum(mb) as total_mb by hostname | sort -total_mb'),
        },
    ],
    "indexer": [
        {
            "name": "Indexer pipeline health",
            "spl": ('index=_internal sourcetype=splunkd component=Metrics group=queue '
                    '| eval fill_pct=round((current_size/max_size)*100,2) '
                    '| stats latest(fill_pct) as fill_pct by host, name | sort -fill_pct'),
        },
        {
            "name": "Indexer disk usage",
            "spl": ('| rest /services/server/status/partitions-space '
                    '| eval free_pct=round((free/capacity)*100,1) '
                    '| table splunk_server, mount_point, capacity, free, free_pct | sort free_pct'),
        },
    ],
    "search_head": [
        {
            "name": "Search head cluster status",
            "spl": ('| rest /services/shcluster/status '
                    '| table label, status, last_heartbeat, replication_count'),
        },
        {
            "name": "Active searches",
            "spl": ('| rest /services/search/jobs '
                    '| stats count by dispatchState | sort -count'),
        },
        {
            "name": "Search concurrency",
            "spl": ('index=_internal sourcetype=splunkd component=SearchScheduler '
                    '| timechart span=5m count by status'),
        },
    ],
    "deployment_server": [
        {
            "name": "Deployment server client status",
            "spl": ('| rest /services/deployment/server/clients '
                    '| stats count by serverClassName '
                    '| sort -count'),
        },
        {
            "name": "Recent deployment activity",
            "spl": ('index=_internal sourcetype=splunkd component=DeploymentServer '
                    '| stats count by log_level, message | sort -count | head 20'),
        },
    ],
}

# ---------------------------------------------------------------------------
# Internal log analysis queries
# ---------------------------------------------------------------------------

_LOG_ANALYSIS: Dict[str, Dict[str, Any]] = {
    "indexing": {
        "description": "Analyze indexing performance and issues",
        "queries": [
            {"name": "Indexing throughput", "spl": (
                'index=_internal sourcetype=splunkd component=Metrics group=per_index_thruput '
                '| eval mb=kb/1024 | timechart span=5m sum(mb) as mb_indexed by series')},
            {"name": "Indexing errors", "spl": (
                'index=_internal sourcetype=splunkd component=IndexProcessor log_level=ERROR '
                '| stats count by message | sort -count | head 20')},
        ],
    },
    "search": {
        "description": "Analyze search performance and scheduling",
        "queries": [
            {"name": "Slowest searches", "spl": (
                'index=_audit action=search info=completed '
                '| stats avg(total_run_time) max(total_run_time) count by savedsearch_name, user '
                '| where avg(total_run_time) > 30 | sort -avg(total_run_time)')},
            {"name": "Skipped searches", "spl": (
                'index=_internal sourcetype=scheduler status=skipped '
                '| stats count by savedsearch_name, reason | sort -count')},
        ],
    },
    "forwarder": {
        "description": "Analyze forwarder connectivity and throughput",
        "queries": [
            {"name": "Forwarder throughput by host", "spl": (
                'index=_internal sourcetype=splunkd component=Metrics group=tcpin_connections '
                '| eval mb=kb/1024 | stats sum(mb) as total_mb by hostname | sort -total_mb | head 20')},
            {"name": "Forwarder errors", "spl": (
                'index=_internal sourcetype=splunkd component=TcpOutputProc log_level=ERROR '
                '| stats count by host, message | sort -count')},
        ],
    },
    "license": {
        "description": "Analyze license usage and violations",
        "queries": [
            {"name": "License usage by sourcetype", "spl": (
                'index=_internal sourcetype=splunkd component=LicenseUsage type=Usage '
                '| eval gb=b/1073741824 | stats sum(gb) as total_gb by st | sort -total_gb | head 20')},
            {"name": "License violation warnings", "spl": (
                'index=_internal sourcetype=splunkd component=LicenseUsage type=RolloverSummary '
                '| table _time, slaves_usage_bytes, stacksz')},
        ],
    },
    "auth": {
        "description": "Analyze authentication events and failures",
        "queries": [
            {"name": "Login attempts", "spl": (
                'index=_audit action=login* | stats count by user, info, src | sort -count')},
            {"name": "Failed auth by source", "spl": (
                'index=_audit action=login info=failed '
                '| stats count by user, src | where count > 3 | sort -count')},
        ],
    },
    "general": {
        "description": "General health and error analysis",
        "queries": [
            {"name": "Error summary by component", "spl": (
                'index=_internal sourcetype=splunkd log_level=ERROR '
                '| stats count by component | sort -count | head 20')},
            {"name": "Warning trends", "spl": (
                'index=_internal sourcetype=splunkd log_level=WARN '
                '| timechart span=1h count by component')},
        ],
    },
}

# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def diagnose_issue(symptoms: str) -> str:
    """
    Systematically diagnose a Splunk issue using a decision tree.

    Args:
        symptoms: Description of the issue or error message.

    Returns:
        JSON string with diagnosis and recommended actions.
    """
    if not symptoms or not symptoms.strip():
        return json.dumps({"status": "error", "error": "Symptoms description cannot be empty"})

    sym_lower = symptoms.lower()
    matches = []

    for issue_key, issue_data in _DIAGNOSIS_TREE.items():
        score = 0
        for keyword in issue_data["keywords"]:
            if keyword in sym_lower:
                score += 1
        if score > 0:
            matches.append((score, issue_key, issue_data))

    # Sort by match score descending
    matches.sort(key=lambda x: x[0], reverse=True)

    if not matches:
        return json.dumps({
            "status": "ok",
            "diagnosis": "Unable to match symptoms to a known issue pattern",
            "suggestion": "Provide more detail about the error messages or symptoms",
            "general_diagnostic_spl": (
                'index=_internal sourcetype=splunkd log_level=ERROR OR log_level=FATAL '
                '| stats count by component, message | sort -count | head 20'
            ),
            "available_categories": list(_DIAGNOSIS_TREE.keys()),
        })

    top_match = matches[0]
    issue_data = top_match[2]

    related = []
    for score, key, data in matches[1:3]:
        related.append({"issue": key, "category": data["category"], "match_score": score})

    return json.dumps({
        "status": "ok",
        "diagnosis": issue_data["diagnosis"],
        "category": issue_data["category"],
        "match_confidence": min(top_match[0] / len(issue_data["keywords"]), 1.0),
        "checks": issue_data["checks"],
        "diagnostic_spl": issue_data["spl_diagnostic"],
        "related_issues": related,
    }, indent=2)


def suggest_fix(error: str) -> str:
    """
    Suggest fixes for common Splunk errors.

    Args:
        error: The error message or error code.

    Returns:
        JSON string with suggested fixes.
    """
    if not error or not error.strip():
        return json.dumps({"status": "error", "error": "Error message cannot be empty"})

    err_lower = error.lower()
    matches = []

    for fix_key, fix_data in _ERROR_FIXES.items():
        for pattern in fix_data["patterns"]:
            if pattern in err_lower:
                matches.append(fix_data)
                break

    if not matches:
        return json.dumps({
            "status": "ok",
            "message": "No specific fix found for this error",
            "general_advice": [
                "Check splunkd.log for additional context",
                "Search Splunk Answers (community.splunk.com) for the error message",
                "Review recent configuration changes",
                "Try restarting the affected Splunk component",
            ],
            "diagnostic_spl": (
                f'index=_internal sourcetype=splunkd "{error[:50]}" '
                '| stats count by component, log_level | sort -count'
            ),
        })

    fixes = []
    for match in matches:
        fixes.append({
            "description": match["description"],
            "fix": match["fix"],
            "config_example": match["config"],
        })

    return json.dumps({
        "status": "ok",
        "fixes": fixes,
        "fix_count": len(fixes),
    }, indent=2)


def check_connectivity(component: str) -> str:
    """
    Generate connectivity check queries for Splunk components.

    Args:
        component: Component to check.

    Returns:
        JSON string with connectivity check queries.
    """
    if not component or not component.strip():
        return json.dumps({"status": "error", "error": "Component name cannot be empty"})

    comp = component.strip().lower()

    if comp == "all":
        all_checks = {}
        for comp_name, checks in _CONNECTIVITY_CHECKS.items():
            all_checks[comp_name] = checks
        return json.dumps({
            "status": "ok",
            "component": "all",
            "checks": all_checks,
        }, indent=2)

    checks = _CONNECTIVITY_CHECKS.get(comp)
    if not checks:
        return json.dumps({
            "status": "error",
            "error": f"Unknown component: {component}",
            "available_components": list(_CONNECTIVITY_CHECKS.keys()) + ["all"],
        })

    return json.dumps({
        "status": "ok",
        "component": comp,
        "checks": checks,
    }, indent=2)


def analyze_logs(area: str) -> str:
    """
    Generate SPL queries for analyzing internal Splunk logs.

    Args:
        area: Area to analyze.

    Returns:
        JSON string with analysis queries.
    """
    if not area or not area.strip():
        return json.dumps({"status": "error", "error": "Analysis area cannot be empty"})

    area_key = area.strip().lower()
    analysis = _LOG_ANALYSIS.get(area_key)

    if not analysis:
        return json.dumps({
            "status": "error",
            "error": f"Unknown analysis area: {area}",
            "available_areas": list(_LOG_ANALYSIS.keys()),
        })

    return json.dumps({
        "status": "ok",
        "area": area_key,
        "description": analysis["description"],
        "queries": analysis["queries"],
        "tips": [
            "Adjust time ranges to focus on the period of interest",
            "Add host filters to narrow to specific servers",
            "Export results to CSV for offline analysis",
        ],
    }, indent=2)


# ---------------------------------------------------------------------------
# Cleanup hook
# ---------------------------------------------------------------------------

def cleanup():
    """Release any resources held by this skill."""
    logger.debug("troubleshooter skill cleaned up")
