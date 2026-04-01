#!/usr/bin/env python3
"""
Training Data Constants and Helpers — Shared data for eval_training_export.py pipeline.

Contains: SYSTEM_PROMPT, template constants, COMMAND_FAMILIES, scenario lists,
          TrainingEntry dataclass, _parse_spl_doc(), _parse_spec_file().
Imported by both eval_training_export.py and eval_training_generators.py.
"""

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger("training_export")

OUTPUT_DIR = __import__("pathlib").Path("/app/data/training_data")

logger = logging.getLogger("training_export")

SYSTEM_PROMPT = (
    "You are a Splunk expert assistant with deep knowledge of SPL (Search Processing Language), "
    "Splunk configuration files (.conf/.spec), log analysis, troubleshooting, CIM data models, "
    "and observability best practices. You write correct, optimized SPL queries and explain "
    "Splunk concepts clearly. Never use index=* — always specify the correct index. "
    "Prefer tstats with CIM data models for performance. Use TERM() and PREFIX() for "
    "index-time tokenization optimization."
)

OUTPUT_DIR = Path("/app/data/training_data")

# ============================================================================
# SPL Command Documentation Templates
# ============================================================================

COMMAND_QA_TEMPLATES = [
    # Basic help
    ("What does the {cmd} command do?", "description"),
    ("Explain the {cmd} SPL command.", "description"),
    ("What is the purpose of {cmd} in Splunk?", "description"),
    # Syntax
    ("What is the syntax for {cmd}?", "syntax"),
    ("Show the {cmd} command syntax.", "syntax"),
    ("How do I write a {cmd} command?", "syntax"),
    # Examples
    ("Give me an example of {cmd}.", "examples"),
    ("Show a practical {cmd} example.", "examples"),
    ("How do I use {cmd} in a real search?", "examples"),
    # Arguments
    ("What arguments does {cmd} accept?", "arguments"),
    ("What are the options for {cmd}?", "arguments"),
    ("List the parameters for {cmd}.", "arguments"),
    # Usage context
    ("When should I use {cmd}?", "usage"),
    ("Is {cmd} a streaming or transforming command?", "type"),
    ("Can {cmd} be used in subsearches?", "usage"),
    # Performance
    ("Performance tips for {cmd}?", "performance"),
    ("How to optimize {cmd} usage?", "performance"),
    # Troubleshooting
    ("Common errors with {cmd}?", "troubleshoot"),
    ("Why is my {cmd} query not working?", "troubleshoot"),
    ("{cmd} returns unexpected results, how to fix?", "troubleshoot"),
]

CROSS_COMMAND_TEMPLATES = [
    "What is the difference between {cmd1} and {cmd2}?",
    "When should I use {cmd1} vs {cmd2}?",
    "Can I combine {cmd1} and {cmd2} in one query?",
    "Compare {cmd1} and {cmd2} for performance.",
]

COMMAND_FAMILIES = {
    "stats": ["stats", "eventstats", "streamstats", "sistats", "mstats", "rawstats", "geostats"],
    "chart": ["chart", "timechart", "sichart", "sitimechart"],
    "top": ["top", "rare", "sitop", "sirare"],
    "search": ["search", "where", "regex", "find", "metadata", "metasearch"],
    "join": ["join", "selfjoin", "append", "appendcols", "union", "multisearch"],
    "dedup": ["dedup", "uniq", "sort"],
    "eval": ["eval", "where", "fieldformat", "convert"],
    "output": ["outputcsv", "outputlookup", "collect", "tscollect", "mcollect"],
    "input": ["inputcsv", "inputlookup", "loadjob", "from"],
    "field": ["fields", "rename", "table", "transpose", "untable", "xyseries"],
    "mv": ["makemv", "mvexpand", "mvcombine", "nomv"],
    "time": ["timechart", "timewrap", "bin", "gentimes", "reltime"],
    "lookup": ["lookup", "inputlookup", "outputlookup"],
    "tstats": ["tstats", "mstats", "mcatalog", "datamodel"],
    "rex": ["rex", "erex", "regex", "extract", "kv", "xmlkv", "spath"],
}

# ============================================================================
# SPL Generation Training Templates
# ============================================================================

SPL_GENERATION_SCENARIOS = [
    # Basic searches
    {
        "q": "Find all failed login attempts in the last 24 hours",
        "a": '```spl\nindex=security sourcetype=WinEventLog:Security EventCode=4625 earliest=-24h\n| stats count by src_ip, user\n| sort -count\n```\nThis searches the security index for Windows EventCode 4625 (failed logon) in the last 24 hours, then aggregates by source IP and username.',
    },
    {
        "q": "Show me the top 10 error messages from application logs",
        "a": '```spl\nindex=main sourcetype=application level=ERROR\n| top limit=10 message\n```\nSearches application logs for ERROR level events and shows the top 10 most common error messages with count and percentage.',
    },
    {
        "q": "Create a timechart of events per hour by sourcetype",
        "a": '```spl\nindex=main earliest=-24h\n| timechart span=1h count by sourcetype\n```\nCreates an hourly timechart showing event counts broken down by sourcetype for the last 24 hours.',
    },
    {
        "q": "Find processes consuming more than 80% CPU",
        "a": '```spl\nindex=os sourcetype=Perfmon:Process\n| where PercentProcessorTime > 80\n| stats avg(PercentProcessorTime) as avg_cpu, max(PercentProcessorTime) as max_cpu by process_name\n| sort -avg_cpu\n```',
    },
    {
        "q": "Show network traffic by source and destination IP",
        "a": '```spl\n| tstats count from datamodel=Network_Traffic where * by All_Traffic.src, All_Traffic.dest\n| rename All_Traffic.* as *\n| sort -count\n| head 100\n```\nUses the CIM Network_Traffic data model with tstats for optimized performance.',
    },
    {
        "q": "Calculate the 95th percentile response time per API endpoint",
        "a": '```spl\nindex=web sourcetype=access_combined\n| rex field=uri_path "(?P<endpoint>/api/[^/]+)"\n| stats perc95(response_time) as p95_ms, avg(response_time) as avg_ms, count by endpoint\n| sort -p95_ms\n```',
    },
    {
        "q": "Detect brute force attacks (more than 5 failed logins from same IP in 10 minutes)",
        "a": '```spl\nindex=security sourcetype=WinEventLog:Security EventCode=4625\n| bin _time span=10m\n| stats count by _time, src_ip\n| where count > 5\n| sort -count\n```\nBins events into 10-minute windows and flags source IPs with more than 5 failed logins.',
    },
    {
        "q": "Find all configuration changes in Splunk",
        "a": '```spl\nindex=_audit action=edit* OR action=create* OR action=delete*\n| table _time, user, action, object, info\n| sort -_time\n```\nSearches the audit index for configuration change events.',
    },
    {
        "q": "Calculate disk usage trends over the past 30 days",
        "a": '```spl\nindex=os sourcetype=df\n| timechart span=1d avg(UsedPct) as avg_disk_pct by mount\n| where avg_disk_pct > 70\n```',
    },
    {
        "q": "Build a transaction of web session events",
        "a": '```spl\nindex=web sourcetype=access_combined\n| transaction session_id maxspan=30m maxpause=5m\n| stats avg(duration) as avg_session_sec, avg(eventcount) as avg_pages, count as total_sessions\n```\nGroups events by session_id with 30-minute max span and 5-minute max pause between events.',
    },
    {
        "q": "Search for lateral movement using Windows event logs",
        "a": '```spl\nindex=security sourcetype=WinEventLog:Security (EventCode=4624 Logon_Type=3 OR Logon_Type=10)\n| stats dc(dest) as unique_hosts, values(dest) as hosts by src_ip, user\n| where unique_hosts > 3\n| sort -unique_hosts\n```\nFinds accounts authenticating to multiple hosts via network logon (type 3) or RDP (type 10).',
    },
    {
        "q": "Monitor forwarder health and data gaps",
        "a": '```spl\nindex=_internal sourcetype=splunkd component=Metrics group=per_host_thruput\n| timechart span=5m sum(kb) as total_kb by series\n| untable _time host kb\n| where kb < 1\n```\nIdentifies forwarders with near-zero throughput, suggesting data gaps.',
    },
    {
        "q": "Create a dashboard panel showing error rate percentage",
        "a": '```spl\nindex=main sourcetype=application\n| timechart span=1h count(eval(level="ERROR")) as errors, count as total\n| eval error_rate=round(errors/total*100, 2)\n| fields _time, error_rate\n```',
    },
    {
        "q": "Find DNS queries to suspicious domains",
        "a": '```spl\n| tstats count from datamodel=Network_Resolution where * by All_DNS.query, All_DNS.src\n| rename All_DNS.* as *\n| lookup ut_domain_blacklist domain as query OUTPUT is_malicious\n| where is_malicious="true"\n```',
    },
    {
        "q": "Analyze license usage by index over time",
        "a": '```spl\nindex=_internal source=*license_usage.log type=Usage\n| timechart span=1d sum(b) as bytes by idx\n| eval GB=round(bytes/1024/1024/1024, 2)\n| fields _time, idx, GB\n```',
    },
    {
        "q": "Build a correlation search for multiple failed logins followed by a success",
        "a": '```spl\nindex=security sourcetype=WinEventLog:Security (EventCode=4625 OR EventCode=4624)\n| sort _time\n| transaction user maxspan=10m startswith=(EventCode=4625) endswith=(EventCode=4624)\n| where eventcount > 3\n| table _time, user, src_ip, eventcount, duration\n```',
    },
    {
        "q": "How do I find the most common user agents in web logs?",
        "a": '```spl\nindex=web sourcetype=access_combined\n| top limit=20 useragent\n| eval percent=round(percent, 2)\n```\nThe `top` command automatically adds count and percent fields. Limit=20 shows top 20 user agents.',
    },
    {
        "q": "Calculate moving average of response times",
        "a": '```spl\nindex=web sourcetype=access_combined\n| timechart span=1h avg(response_time) as avg_response\n| trendline sma5(avg_response) as moving_avg\n```\nUses `trendline` with a 5-point simple moving average (sma5).',
    },
    {
        "q": "Find events with specific field values using TERM()",
        "a": '```spl\nindex=main TERM(error_code=500)\n| stats count by sourcetype, host\n```\nTERM() forces exact token matching at index time, which is much faster than field extraction. Use it when searching for known indexed values.',
    },
    {
        "q": "Create a lookup table from search results",
        "a": '```spl\nindex=assets sourcetype=cmdb\n| stats latest(os) as os, latest(owner) as owner, latest(department) as dept by hostname\n| outputlookup assets_lookup.csv\n```\nCreates or updates a CSV lookup file with the latest asset information.',
    },
]

# More SPL generation scenarios (optimization focused)
SPL_OPTIMIZATION_SCENARIOS = [
    {
        "q": "How to optimize: index=* sourcetype=* | stats count by host",
        "a": "This query is inefficient because it uses `index=*` and `sourcetype=*` which searches everything.\n\nOptimized version:\n```spl\n| tstats count where index=main by host\n```\n\nImprovements:\n1. Use `tstats` instead of raw search + stats (10-100x faster)\n2. Specify the exact index instead of `index=*`\n3. Remove unnecessary `sourcetype=*`\n4. `tstats` operates on indexed metadata, not raw events",
    },
    {
        "q": "Optimize: index=web | regex _raw=\"(error|fail|exception)\" | stats count by host",
        "a": "Using `regex` on `_raw` forces full event scanning.\n\nOptimized:\n```spl\nindex=web (error OR fail OR exception)\n| stats count by host\n```\n\nImprovements:\n1. Move regex terms to the base search as keywords — they leverage the index\n2. Remove the `regex` command entirely — boolean OR in base search is faster\n3. Splunk's bloom filters can quickly eliminate non-matching buckets",
    },
    {
        "q": "Optimize: index=main | eval hour=strftime(_time,\"%H\") | search hour=14 | stats count",
        "a": "Using eval + search to filter by time is very slow.\n\nOptimized:\n```spl\nindex=main date_hour=14\n| stats count\n```\n\nOr with time range:\n```spl\nindex=main earliest=@d+14h latest=@d+15h\n| stats count\n```\n\n`date_hour` is an indexed field and is much faster than eval + search.",
    },
    {
        "q": "Optimize: index=security | join user [search index=hr_data | fields user, department]",
        "a": "The `join` command has a 50,000 row limit and is memory-intensive.\n\nOptimized:\n```spl\nindex=security\n| lookup hr_lookup user OUTPUT department\n```\n\nOr if you need a subsearch:\n```spl\nindex=security [search index=hr_data | fields user | format]\n| stats count by user\n```\n\nLookups are much more efficient than join for enrichment.",
    },
    {
        "q": "Optimize: index=main | search host=web* status>=400 | stats count by uri_path",
        "a": "The `| search` command after the base search adds an extra filtering step.\n\nOptimized:\n```spl\nindex=main host=web* status>=400\n| stats count by uri_path\n| sort -count\n```\n\nMove filter terms directly into the base search where they can leverage the index and bloom filters.",
    },
    {
        "q": "Optimize: ... | eval is_error=if(status>=400,1,0) | where is_error=1 | stats count",
        "a": "Creating a temporary field just to filter is unnecessary.\n\nOptimized:\n```spl\n... | where status >= 400 | stats count\n```\n\nOr even better, filter in the base search:\n```spl\nindex=web status>=400 | stats count\n```\n\nThe `where` command can handle the comparison directly.",
    },
    {
        "q": "Optimize: index=main | fields + _time, host, source, sourcetype, _raw | table _time, host",
        "a": "Including _raw in `fields` defeats the purpose of field extraction optimization.\n\nOptimized:\n```spl\nindex=main\n| fields _time, host\n| table _time, host\n```\n\n1. Remove `_raw` from fields — it prevents search optimization\n2. Remove `source` and `sourcetype` if not needed in the output\n3. `fields +` is redundant, `fields` defaults to include",
    },
    {
        "q": "Why is my search slow: index=main earliest=-30d | stats count by user | sort -count | head 10",
        "a": "A 30-day time range is very expensive.\n\nOptimized:\n```spl\n| tstats count where index=main earliest=-30d by user\n| sort -count\n| head 10\n```\n\nImprovements:\n1. Use `tstats` for metadata-level counting (orders of magnitude faster)\n2. Consider using accelerated data models if this is a repeated search\n3. If you don't need `user` as an indexed field, consider using `| tstats prestats=t count by user` with an accelerated data model",
    },
]

# ============================================================================
# Best Practice Training
# ============================================================================

BEST_PRACTICES = [
    {
        "q": "What are Splunk search optimization best practices?",
        "a": """Key Splunk search optimization practices:

1. **Be specific with index and sourcetype** — Never use `index=*`
2. **Use tstats** — For aggregations on indexed fields, `tstats` is 10-100x faster than `stats`
3. **Filter early** — Put filter terms in the base search, not after pipes
4. **Use TERM() and PREFIX()** — Force exact index-time token matching
5. **Avoid join** — Use lookups or subsearches instead
6. **Limit time range** — Shorter time ranges are faster; use `earliest`/`latest`
7. **Use fields command** — Reduce the data pipeline by selecting only needed fields
8. **Avoid regex on _raw** — Use base search keywords instead
9. **Use summary indexing or data models** for repeated expensive searches
10. **Use `stats` before `sort`** — Don't sort raw events, aggregate first""",
    },
    {
        "q": "What is the difference between tstats and stats?",
        "a": """`tstats` vs `stats`:

**tstats**:
- Operates on indexed metadata (tsidx files) — extremely fast
- Works with `_time`, indexed fields, and accelerated data models
- Cannot access non-indexed fields or _raw
- Syntax: `| tstats count where index=main by host`

**stats**:
- Operates on search results after field extraction — slower
- Can access any extracted field
- More flexible but requires full event processing
- Syntax: `index=main | stats count by host`

**When to use tstats**: Counting, aggregating by indexed fields, data model accelerations
**When to use stats**: When you need extracted/calculated fields""",
    },
    {
        "q": "How do I use CIM data models effectively?",
        "a": """CIM (Common Information Model) data models provide standardized field names across sourcetypes.

**Using CIM with tstats** (fastest):
```spl
| tstats count from datamodel=Authentication where Authentication.action=failure by Authentication.user, Authentication.src
| rename Authentication.* as *
```

**Key CIM data models**: Authentication, Network_Traffic, Endpoint, Web, Intrusion_Detection, Change, Malware, Alerts

**Steps to leverage CIM**:
1. Install the Splunk CIM Add-on
2. Map your sourcetypes to CIM data models via tags
3. Enable data model acceleration
4. Use `tstats` against accelerated models for fast searches
5. Reference fields with the model name prefix (e.g., `Authentication.user`)""",
    },
    {
        "q": "How do I troubleshoot slow Splunk searches?",
        "a": """Steps to troubleshoot slow searches:

1. **Check the Job Inspector** — Click the job inspector icon to see time breakdowns
2. **Look at scan count** — High scan count vs result count means poor filtering
3. **Review the search.log** — Shows per-command timing and warnings
4. **Check indexer parallelization** — Look for `| localop` or serialized commands
5. **Analyze the search pipeline**:
   - `search` phase: Time spent on bucket scanning
   - `filter` phase: Time on field extraction and filtering
   - `aggregate` phase: Time on stats/chart computations
6. **Common fixes**:
   - Add specific index/sourcetype
   - Move filters to base search
   - Replace `join` with `lookup`
   - Use `tstats` instead of raw searches
   - Add `TERM()` for exact token matching""",
    },
    {
        "q": "What are Splunk .conf file best practices?",
        "a": """Configuration file best practices:

1. **Never edit default files** — Always use local/ directory
2. **Precedence order**: system/local > app/local > app/default > system/default
3. **Use apps for organization** — Group related configs in custom apps
4. **inputs.conf**: Set `index=` explicitly, use `disabled=false` for active inputs
5. **props.conf**: Use TRANSFORMS for field extraction over EXTRACT when possible
6. **transforms.conf**: Define lookup definitions here
7. **limits.conf**: Tune `max_searches_per_cpu`, `max_mem_usage_mb` carefully
8. **server.conf**: Configure replication factor and search factor for clustering
9. **Validate changes**: Use `btool check` before restarting
10. **Version control**: Track all config changes in git""",
    },
    {
        "q": "How do I create an efficient dashboard in Splunk?",
        "a": """Dashboard efficiency tips:

1. **Use base searches** — Share a single search across multiple panels with `<search id="base">`
2. **Use tstats** — All dashboard searches should prefer tstats for speed
3. **Set time ranges** — Don't use All Time; default to last 24h or shorter
4. **Use summary indexing** — Pre-compute expensive metrics with `collect` or `mcollect`
5. **Limit drilldown data** — Use `| head 100` or `| top limit=20`
6. **Enable search caching** — Set `refresh` and `refreshType` appropriately
7. **Use Simple XML Dashboard Studio** for modern dashboards
8. **Avoid real-time searches** in dashboards — Use scheduled + cache instead
9. **Token filters** — Let users filter data to reduce search scope
10. **Post-process searches** — Use `<search base="">` for panel variations""",
    },
]

# ============================================================================
# Advanced SPL Scenarios (Security, IT Ops, DevOps, Data Analysis)
# ============================================================================

ADVANCED_SCENARIOS = [
    # Security Operations
    {"q": "How to detect PowerShell-based attacks in Splunk?",
     "a": '```spl\nindex=windows sourcetype=WinEventLog:Microsoft-Windows-PowerShell/Operational EventCode=4104\n| rex field=ScriptBlockText "(?P<suspicious>Invoke-Expression|IEX|Net.WebClient|DownloadString|Invoke-Mimikatz|Invoke-Shellcode)"\n| where isnotnull(suspicious)\n| stats count values(ScriptBlockText) as scripts by ComputerName, UserID\n| sort -count\n```\nMonitors PowerShell ScriptBlock logging (EventCode 4104) for known malicious patterns.'},
    {"q": "Create a data exfiltration alert based on unusual upload volume",
     "a": '```spl\n| tstats sum(All_Traffic.bytes_out) as bytes_out from datamodel=Network_Traffic where * by All_Traffic.src, _time span=1h\n| rename All_Traffic.src as src\n| eventstats avg(bytes_out) as avg_out, stdev(bytes_out) as stdev_out by src\n| where bytes_out > (avg_out + 3*stdev_out)\n| eval MB_out=round(bytes_out/1024/1024, 2)\n| table _time, src, MB_out, avg_out, stdev_out\n```\nDetects hosts sending significantly more data than their historical average (3 standard deviations).'},
    {"q": "Monitor for privilege escalation attempts",
     "a": '```spl\nindex=security sourcetype=WinEventLog:Security (EventCode=4672 OR EventCode=4673 OR EventCode=4674)\n| stats count dc(dest) as host_count values(Privileges) as privs by user\n| where count > 10 OR host_count > 3\n| sort -count\n```\nTracks special privilege assignment (4672), service operations (4673), and object access (4674).'},
    {"q": "Find lateral movement via Pass-the-Hash",
     "a": '```spl\nindex=security sourcetype=WinEventLog:Security EventCode=4624 Logon_Type=3 Authentication_Package=NTLM\n| stats dc(dest) as unique_hosts values(dest) as hosts by src_ip, user\n| where unique_hosts > 5\n| sort -unique_hosts\n```\nNTLM network logons (type 3) to many hosts from the same source suggest Pass-the-Hash.'},
    # IT Operations
    {"q": "Monitor disk space across all servers and alert on >90%",
     "a": '```spl\nindex=os sourcetype=df\n| dedup host, mount\n| where UsedPct > 90\n| table host, mount, Type, Size, Used, Avail, UsedPct\n| sort -UsedPct\n```\nShows all mounts above 90% utilization, sorted by most critical.'},
    {"q": "Track service restart patterns across infrastructure",
     "a": '```spl\nindex=os sourcetype=linux_service OR sourcetype=WinEventLog:System EventCode=7036\n| rex field=_raw "(?P<service>[\\w-]+).*(?:entered|started|stopped)"\n| stats count by host, service, _time span=1h\n| eventstats avg(count) as baseline by host, service\n| where count > baseline * 2\n| table _time, host, service, count, baseline\n```'},
    {"q": "Build a host inventory dashboard from Splunk data",
     "a": '```spl\nindex=os OR index=windows\n| stats latest(os) as os, latest(arch) as arch, latest(cpu_count) as cpus, latest(mem_total) as mem_gb, dc(sourcetype) as sourcetypes, max(_time) as last_seen by host\n| eval last_seen=strftime(last_seen, "%Y-%m-%d %H:%M"), mem_gb=round(mem_gb/1024/1024/1024,1)\n| sort host\n```'},
    {"q": "Create SLA monitoring for web application response times",
     "a": '```spl\nindex=web sourcetype=access_combined\n| eval sla_met=if(response_time < 2000, 1, 0)\n| timechart span=1h avg(response_time) as avg_ms, perc95(response_time) as p95_ms, avg(sla_met) as sla_pct\n| eval sla_pct=round(sla_pct*100, 2)\n| eval status=case(sla_pct>=99.9, "GREEN", sla_pct>=99, "YELLOW", 1=1, "RED")\n```'},
    # DevOps / CI-CD
    {"q": "Monitor deployment frequency and rollback rate",
     "a": '```spl\nindex=devops sourcetype=deployment_events\n| eval status=coalesce(status, "unknown")\n| timechart span=1d count as deployments, count(eval(status="rollback")) as rollbacks\n| eval rollback_rate=round(rollbacks/deployments*100, 1)\n```'},
    {"q": "Track mean time to recovery (MTTR) from incidents",
     "a": '```spl\nindex=itsm sourcetype=incident_tracker\n| transaction incident_id startswith=status="open" endswith=status="resolved"\n| eval mttr_hours=duration/3600\n| stats avg(mttr_hours) as avg_mttr, median(mttr_hours) as median_mttr, perc90(mttr_hours) as p90_mttr by priority\n| eval avg_mttr=round(avg_mttr,1), median_mttr=round(median_mttr,1)\n```'},
    # Data Analysis
    {"q": "Perform cohort analysis on user activity",
     "a": '```spl\nindex=app sourcetype=user_events action=login\n| stats min(_time) as first_login by user\n| eval cohort=strftime(first_login, "%Y-%m")\n| join user [search index=app sourcetype=user_events | stats dc(date_mday) as active_days by user]\n| stats count as users, avg(active_days) as avg_engagement by cohort\n| sort cohort\n```'},
    {"q": "Calculate customer churn rate month over month",
     "a": '```spl\nindex=app sourcetype=user_events\n| bin _time span=1mon\n| stats dc(user) as active_users by _time\n| autoregress active_users as prev_users p=1\n| eval churn_rate=round((prev_users-active_users)/prev_users*100, 2)\n| where isnotnull(churn_rate)\n```'},
    {"q": "Build a funnel analysis for e-commerce checkout",
     "a": '```spl\nindex=web sourcetype=clickstream\n| stats dc(session_id) as sessions by page\n| eval step=case(page="/products","1_browse", page="/cart","2_cart", page="/checkout","3_checkout", page="/confirm","4_confirm")\n| where isnotnull(step)\n| sort step\n| streamstats first(sessions) as total\n| eval conversion=round(sessions/total*100, 1)\n```'},
    # Splunk Administration
    {"q": "Check indexer cluster health and replication status",
     "a": '```spl\n| rest /services/cluster/master/peers\n| table title, status, is_searchable, replication_count, search_state, bucket_count\n| sort title\n```\nOr via the REST API:\n```spl\n| rest /services/cluster/master/generation\n| table generation_id, multisite, replication_factor, search_factor\n```'},
    {"q": "Find heavy forwarders that are behind on data forwarding",
     "a": '```spl\nindex=_internal sourcetype=splunkd component=Metrics group=queue\n| where name="tcpout_sendingqueue"\n| eval fill_pct=round(current_size/max_size*100, 1)\n| where fill_pct > 80\n| stats latest(fill_pct) as queue_pct by host\n| sort -queue_pct\n```'},
    {"q": "Audit user search activity in Splunk",
     "a": '```spl\nindex=_audit action=search info=completed\n| stats count sum(total_run_time) as total_time avg(total_run_time) as avg_time by user\n| eval avg_time=round(avg_time, 1), total_hours=round(total_time/3600, 1)\n| sort -count\n```'},
    {"q": "Monitor search concurrency and capacity",
     "a": '```spl\nindex=_internal sourcetype=scheduler status=completed OR status=skipped\n| timechart span=5m count by status\n| eval skip_rate=round(skipped/(completed+skipped)*100, 1)\n```'},
    # Machine Learning / Advanced Analytics
    {"q": "Detect anomalous login times for users",
     "a": '```spl\nindex=security sourcetype=WinEventLog:Security EventCode=4624\n| eval hour=tonumber(strftime(_time, "%H"))\n| eventstats avg(hour) as avg_hour, stdev(hour) as stdev_hour by user\n| where abs(hour - avg_hour) > 2*stdev_hour\n| table _time, user, src_ip, hour, avg_hour, stdev_hour\n```\nFlags login events occurring at unusual hours compared to each user\'s historical pattern.'},
    {"q": "Predict disk full date using linear regression",
     "a": '```spl\nindex=os sourcetype=df mount="/"\n| timechart span=1d latest(UsedPct) as disk_used\n| predict disk_used as predicted future_timespan=30\n| where predicted >= 95\n| head 1\n| eval full_date=strftime(_time, "%Y-%m-%d")\n```\nUses Splunk\'s `predict` command with linear regression to estimate when disk reaches 95%.'},
]

# Additional command-specific advanced templates
ADVANCED_COMMAND_TEMPLATES = [
    # Pipeline patterns
    ("How to chain {cmd} with stats?", "pipeline"),
    ("Show {cmd} used in a real-world pipeline.", "pipeline"),
    ("Combine {cmd} with eval for calculations.", "pipeline"),
    ("Use {cmd} with timechart for trending.", "pipeline"),
    # Error handling
    ("What happens if {cmd} gets null values?", "null_handling"),
    ("How does {cmd} handle multivalue fields?", "mv_handling"),
    # Advanced use cases
    ("Use {cmd} for security analysis.", "security_use"),
    ("Use {cmd} for performance monitoring.", "perf_use"),
    ("How does {cmd} work with subsearches?", "subsearch"),
    ("Can {cmd} be accelerated?", "acceleration"),
]

# ============================================================================
# Config/Spec Training Templates
# ============================================================================

SPEC_QA_TEMPLATES = [
    ("What settings are available in {conf}?", "stanza_list"),
    ("What is the default value for {setting} in {conf}?", "default"),
    ("How do I configure {setting} in {conf}?", "setting"),
    ("What does the [{stanza}] stanza do in {conf}?", "stanza"),
    ("Show me an example {conf} configuration.", "example"),
]

# ============================================================================
# Core Export Logic
# ============================================================================

@dataclass
class TrainingEntry:
    question: str
    answer: str
    source: str = ""
    topic: str = ""
    confidence: float = 0.9


def _parse_spl_doc(filepath: str) -> Dict[str, str]:
    """Extract sections from an SPL doc markdown file."""
    sections = {}
    try:
        content = Path(filepath).read_text(encoding="utf-8", errors="ignore")

        # Standard ## sections
        for section_name in ["Description", "Syntax", "Arguments", "Examples", "Usage", "See also"]:
            pattern = rf'##?\s*{section_name}\s*\n(.*?)(?=\n##?\s|\Z)'
            match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
            if match:
                sections[section_name.lower()] = match.group(1).strip()

        # Fallback: extract description from content after # heading (new doc format)
        if "description" not in sections:
            # Try to get first substantial paragraph after the title heading
            title_match = re.search(r'^#\s+\w+\s*\n\n(.+?)(?=\n#+\s|\n---|\Z)', content, re.DOTALL | re.MULTILINE)
            if title_match:
                desc = title_match.group(1).strip()
                if len(desc) > 20:
                    sections["description"] = desc[:800]

        # Fallback: extract from YAML frontmatter title + first paragraph
        if "description" not in sections:
            # After frontmatter, find first meaningful paragraph
            fm_end = content.find('---', 3)
            if fm_end > 0:
                after_fm = content[fm_end + 3:].strip()
                # Skip # heading
                heading_end = after_fm.find('\n')
                if heading_end > 0:
                    body = after_fm[heading_end:].strip()
                    # Get first paragraph
                    para_end = body.find('\n\n')
                    if para_end > 0:
                        desc = body[:para_end].strip()
                    else:
                        desc = body[:500].strip()
                    if len(desc) > 20:
                        sections["description"] = desc[:800]

        # Fallback: extract syntax from #### sections
        if "syntax" not in sections:
            syn_match = re.search(r'####?\s*(?:Required|Optional|Syntax)\s*.*?\n(.*?)(?=\n####?\s|\Z)',
                                  content, re.DOTALL | re.IGNORECASE)
            if syn_match:
                sections["syntax"] = syn_match.group(1).strip()[:600]

        # Fallback: extract arguments from #### sections
        if "arguments" not in sections:
            arg_match = re.search(r'####?\s*(?:Required|Optional)\s+arguments?\s*\n(.*?)(?=\n####?\s|\n##?\s|\Z)',
                                  content, re.DOTALL | re.IGNORECASE)
            if arg_match:
                sections["arguments"] = arg_match.group(1).strip()[:800]

        # Detect command type
        if re.search(r'streaming|distributable', content, re.IGNORECASE):
            sections["type"] = "streaming"
        elif re.search(r'transforming|aggregate', content, re.IGNORECASE):
            sections["type"] = "transforming"
        elif re.search(r'generating', content, re.IGNORECASE):
            sections["type"] = "generating"
        elif re.search(r'dataset', content, re.IGNORECASE):
            sections["type"] = "dataset"
        else:
            sections["type"] = "unknown"

        # Extract performance notes
        perf_match = re.search(r'(?:performance|optimization|tip|note).*?\n(.*?)(?=\n##?\s|\Z)',
                               content, re.DOTALL | re.IGNORECASE)
        if perf_match:
            sections["performance"] = perf_match.group(1).strip()

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass
    return sections


def _parse_spec_file(filepath: str) -> List[Dict]:
    """Parse a .spec or .conf file into stanzas."""
    stanzas = []
    try:
        content = Path(filepath).read_text(encoding="utf-8", errors="ignore")
        for match in re.finditer(r'\[([^\]]+)\]\s*\n((?:[^[\n].*\n)*)', content):
            name = match.group(1)
            body = match.group(2).strip()
            settings = {}
            for line in body.split('\n'):
                kv = re.match(r'(\w[\w.]*)\s*=\s*(.*)', line.strip())
                if kv:
                    settings[kv.group(1)] = kv.group(2).strip()
            stanzas.append({"name": name, "body": body, "settings": settings})
    except (OSError, ValueError, KeyError, TypeError) as _exc:
        logger.debug("%s", _exc)  # was: pass
    return stanzas


