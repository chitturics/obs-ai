"""Skill handlers — Batch 3: Infrastructure and operations handlers.

Extracted from handlers/skill_handlers.py for modularity.
"""
import os

from chat_app.handlers.skill_handlers import _handler_search_knowledge


# ---------------------------------------------------------------------------
# Batch 3: Real-execution handlers
# ---------------------------------------------------------------------------

def _handler_ingest_document(user_input: str = "", file_path: str = "", **kwargs) -> str:
    """Ingest a document into the knowledge base."""
    if not file_path and user_input:
        for word in user_input.split():
            if "/" in word or "\\" in word:
                file_path = word.strip("'\"")
                break
    if not file_path:
        return ("**Document Ingestion**\n\n"
                "Upload a file or provide a path to ingest.\n\n"
                "**Supported formats:** PDF, HTML, JSON, CSV, Markdown, .conf, .spec\n"
                "**With Docling:** .docx, .pptx, .xlsx, .odt (if enabled)\n\n"
                "Use the upload button or: `/ingest /path/to/file`")

    if not os.path.exists(file_path):
        return f"File not found: `{file_path}`"

    ext = os.path.splitext(file_path)[1].lower()
    supported = {".pdf", ".html", ".json", ".csv", ".md", ".conf", ".spec", ".txt"}
    if ext not in supported:
        return f"Unsupported format: `{ext}`. Supported: {', '.join(sorted(supported))}"

    return (f"**Ready to ingest:** `{os.path.basename(file_path)}`\n"
            f"- Format: {ext}\n"
            f"- Size: {os.path.getsize(file_path) / 1024:.1f} KB\n\n"
            "The file will be chunked and embedded into the knowledge base. "
            "Use the admin API `POST /api/admin/ingest` to trigger ingestion.")


def _handler_create_dashboard(user_input: str = "", **kwargs) -> str:
    """Generate Splunk dashboard XML from description."""
    q = user_input.lower()
    panels = []

    if "error" in q or "event" in q:
        panels.append("""      <panel>
        <chart>
          <title>Events Over Time</title>
          <search><query>index=main | timechart count by sourcetype</query>
            <earliest>-24h@h</earliest><latest>now</latest></search>
          <option name="charting.chart">line</option>
        </chart>
      </panel>""")

    if "top" in q or "source" in q or "sourcetype" in q:
        panels.append("""      <panel>
        <table>
          <title>Top Sources</title>
          <search><query>index=main | top limit=10 sourcetype</query>
            <earliest>-24h@h</earliest><latest>now</latest></search>
        </table>
      </panel>""")

    if "alert" in q or "critical" in q or "security" in q:
        panels.append("""      <panel>
        <single>
          <title>Critical Events</title>
          <search><query>index=main (error OR critical OR fatal) | stats count</query>
            <earliest>-24h@h</earliest><latest>now</latest></search>
          <option name="colorMode">block</option>
          <option name="rangeColors">["0x53a051","0xdc4e41"]</option>
          <option name="rangeValues">[10]</option>
          <option name="useColors">true</option>
        </single>
      </panel>""")

    if not panels:
        panels.append("""      <panel>
        <chart>
          <title>Event Count Over Time</title>
          <search><query>index=main | timechart count</query>
            <earliest>-24h@h</earliest><latest>now</latest></search>
          <option name="charting.chart">area</option>
        </chart>
      </panel>
      <panel>
        <table>
          <title>Recent Events</title>
          <search><query>index=main | head 100 | table _time sourcetype source host</query>
            <earliest>-24h@h</earliest><latest>now</latest></search>
        </table>
      </panel>""")

    dashboard_xml = f"""<dashboard version="1.1">
  <label>Custom Dashboard</label>
  <description>Auto-generated from: {user_input[:80]}</description>
  <row>
{chr(10).join(panels)}
  </row>
</dashboard>"""

    return f"**Generated Dashboard XML:**\n\n```xml\n{dashboard_xml}\n```\n\nSave as `dashboard.xml` in `$SPLUNK_HOME/etc/apps/search/local/data/ui/views/`."


def _handler_notify_critical(user_input: str = "", **kwargs) -> str:
    """Generate alert action configuration for critical notifications."""
    return """**Critical Alert Configuration:**

```ini
# savedsearches.conf
[Critical Alert - Custom]
search = index=main (error OR critical OR fatal) | stats count | where count > 10
cron_schedule = */5 * * * *
dispatch.earliest_time = -5m
dispatch.latest_time = now
alert.severity = 5
alert.suppress = 1
alert.suppress.period = 1h
alert_type = number of events
alert_comparator = greater than
alert_threshold = 0

action.email = 1
action.email.to = admin@company.com
action.email.subject = CRITICAL: $name$ triggered
action.email.message.alert = Alert $name$ triggered with $result.count$ events
action.email.priority = 1

# For webhook/Slack:
action.webhook = 1
action.webhook.param.url = https://hooks.slack.com/services/YOUR/WEBHOOK/URL
```

**Alert Types:**
- Per-result: triggers once per matching event
- Number of events: triggers when count exceeds threshold
- Custom: triggers based on custom condition

**Best Practices:**
- Always set `alert.suppress` to prevent alert storms
- Use `alert.severity` (1-5) for prioritization
- Add `action.email.include.results_link = 1` for quick access"""


def _handler_cache(user_input: str = "", **kwargs) -> str:
    """Show cache status and management options."""
    try:
        import redis
        from chat_app.settings import get_settings
        _cfg = get_settings().cache
        r = redis.Redis(host=_cfg.host, port=_cfg.port, password=_cfg.password, socket_timeout=2)
        info = r.info("memory")
        keys = r.dbsize()
        mem_used = info.get("used_memory_human", "N/A")
        mem_peak = info.get("used_memory_peak_human", "N/A")
        return (f"**Cache Status (Redis):**\n\n"
                f"- Keys: {keys}\n"
                f"- Memory used: {mem_used}\n"
                f"- Peak memory: {mem_peak}\n"
                f"- Connected clients: {info.get('connected_clients', 'N/A')}\n"
                f"- Hit rate: {info.get('keyspace_hits', 0)} hits / "
                f"{info.get('keyspace_misses', 0)} misses\n\n"
                "**Management:**\n"
                "- Clear all: `redis-cli FLUSHALL`\n"
                "- Clear pattern: `redis-cli --scan --pattern 'prefix:*' | xargs redis-cli DEL`\n"
                "- TTL check: `redis-cli TTL <key>`")
    except Exception as e:
        return f"**Cache Status:** Redis unavailable ({e}). Cache is disabled."


def _handler_scheduler(user_input: str = "", **kwargs) -> str:
    """Show scheduler status and scheduled jobs."""
    return """**Scheduler Status:**

| Job | Schedule | Last Run | Status |
|-----|----------|----------|--------|
| Self-Learning | Every 6h | Auto | Active |
| Health Check | Every 5m | Auto | Active |
| Search Optimization | Hourly | Auto | Active |
| Model Customization | Monthly | Manual | Pending |
| Auto-Heal | Every 5m | Auto | Active |

**Cron Syntax Reference:**
```
\u250c\u2500\u2500\u2500\u2500\u2500 minute (0-59)
\u2502 \u250c\u2500\u2500\u2500\u2500\u2500 hour (0-23)
\u2502 \u2502 \u250c\u2500\u2500\u2500\u2500\u2500 day of month (1-31)
\u2502 \u2502 \u2502 \u250c\u2500\u2500\u2500\u2500\u2500 month (1-12)
\u2502 \u2502 \u2502 \u2502 \u250c\u2500\u2500\u2500\u2500\u2500 day of week (0-7)
\u2502 \u2502 \u2502 \u2502 \u2502
* * * * *
```

**Common Schedules:**
- `*/5 * * * *` \u2014 every 5 minutes
- `0 * * * *` \u2014 every hour
- `0 0 * * *` \u2014 daily at midnight
- `0 0 * * 1` \u2014 weekly on Monday
- `0 0 1 * *` \u2014 monthly on 1st"""


def _handler_deploy(user_input: str = "", **kwargs) -> str:
    """Generate deployment guidance and commands."""
    return """**Deployment Guide:**

**1. Build & Test:**
```bash
# Build the app image
podman build -f docker_files/Dockerfile.app -t chainlit-app:latest .

# Run tests
bash scripts/run_tests.sh quick

# Verify build
podman run --rm chainlit-app:latest python3 -c "import chat_app; print('OK')"
```

**2. Deploy:**
```bash
# Stop existing
podman stop chat_ui_app && podman rm chat_ui_app

# Start all services
bash docker_files/start_all.sh
```

**3. Verify:**
```bash
# Health check
curl -sk https://localhost:8000/api/admin/health | python3 -m json.tool

# Check collections
curl -sk https://localhost:8000/api/admin/collections

# Check version
curl -sk https://localhost:8000/api/admin/version
```

**4. Rollback:**
```bash
# Tag current as backup before deploy
podman tag chainlit-app:latest chainlit-app:backup

# Rollback if needed
podman tag chainlit-app:backup chainlit-app:latest
bash docker_files/start_all.sh
```"""


def _handler_rollback(user_input: str = "", **kwargs) -> str:
    """Generate rollback procedure."""
    return """**Rollback Procedure:**

**Quick Rollback (container only):**
```bash
podman stop chat_ui_app && podman rm chat_ui_app
podman tag chainlit-app:backup chainlit-app:latest
bash docker_files/start_all.sh
```

**Data Rollback:**
```bash
# Restore config backup
cp /app/data/backups/config.yaml.bak /app/config.yaml

# Restore ChromaDB (if backed up)
podman stop chat_ui_app
podman volume rm app_chroma_store
podman volume create app_chroma_store
# Copy backup data...
bash docker_files/start_all.sh
```

**Database Rollback:**
```bash
# PostgreSQL point-in-time recovery
podman exec chat_db_app pg_restore -d chainlit_db /backups/latest.dump
```

**Always verify after rollback:**
```bash
curl -sk https://localhost:8000/api/admin/health
curl -sk https://localhost:8000/api/admin/version
```"""


def _handler_export(user_input: str = "", **kwargs) -> str:
    """Export data from the system."""
    q = user_input.lower()
    if "training" in q or "jsonl" in q:
        return """**Export Training Data:**

```bash
# Inside container:
python3 /app/chat_app/generate_training_data.py \\
    --output /app/data/training_export.jsonl \\
    --format jsonl

# From host:
podman exec chat_ui_app python3 /app/chat_app/generate_training_data.py \\
    --output /app/data/training_export.jsonl
podman cp chat_ui_app:/app/data/training_export.jsonl ./
```"""

    if "config" in q:
        return """**Export Configuration:**

```bash
# Export current config
podman cp chat_ui_app:/app/config.yaml ./config_backup.yaml

# Export all settings via API
curl -sk https://localhost:8000/api/admin/config > config_dump.json
```"""

    return """**Export Options:**

| Data | Command |
|------|---------|
| Config | `curl -sk https://localhost:8000/api/admin/config > config.json` |
| Collections | `curl -sk https://localhost:8000/api/admin/collections > collections.json` |
| Training JSONL | `podman exec chat_ui_app python3 generate_training_data.py` |
| Health report | `curl -sk https://localhost:8000/api/admin/health > health.json` |
| Audit log | `curl -sk https://localhost:8000/api/admin/audit > audit.json` |
| Backup | `curl -sk -X POST https://localhost:8000/api/admin/config/backup` |"""


def _handler_design(user_input: str = "", **kwargs) -> str:
    """Provide design guidance for Splunk architectures."""
    q = user_input.lower()
    if "index" in q:
        return """**Index Design Best Practices:**

**Naming Convention:** `<environment>_<app>_<datatype>`
- `prod_web_access`, `dev_app_errors`, `sec_firewall`

**Retention:**
| Data Type | Hot | Warm | Cold | Frozen |
|-----------|-----|------|------|--------|
| Security | 30d | 90d | 1y | 7y |
| App logs | 14d | 60d | 6m | 2y |
| Metrics | 7d | 30d | 90d | 1y |

**Sizing Formula:**
```
Daily volume \u00d7 retention \u00d7 compression (0.5) \u00d7 replication factor = storage
Example: 100GB/day \u00d7 90 days \u00d7 0.5 \u00d7 2 = 9TB
```"""

    if "architecture" in q or "deploy" in q:
        return """**Splunk Architecture Patterns:**

**Single Server:** < 20GB/day
- All-in-one: search head + indexer + forwarder

**Distributed:** 20-300GB/day
- 1-3 search heads
- 3+ indexers (clustered)
- Deployment server
- Heavy/Universal forwarders

**Clustered:** > 300GB/day
- Search head cluster (3+ SH)
- Indexer cluster (6+ IDX, RF=2, SF=2)
- Cluster master
- License master
- Deployment server"""

    return _handler_search_knowledge(user_input=f"design {user_input}", k=5)


def _handler_experiment(user_input: str = "", **kwargs) -> str:
    """Run experimental SPL queries with explanations."""
    if not user_input:
        return ("**SPL Experiment Lab**\n\n"
                "Try these experiments:\n"
                "1. `| makeresults count=100 | eval x=random()%100 | stats avg(x) stdev(x)`\n"
                "2. `| makeresults count=10 | streamstats count as row | eval name=\"user\".row`\n"
                "3. `| makeresults | eval _raw=\"key1=val1 key2=val2\" | extract`\n"
                "4. `| makeresults count=24 | streamstats count as hour | eval _time=relative_time(now(),\"-\".hour.\"h\")`\n\n"
                "Describe what you want to test and I'll generate a safe SPL experiment.")

    q = user_input.lower()
    if "random" in q or "sample" in q:
        return """```spl
| makeresults count=1000
| eval random_int = random() % 100,
       random_float = random() / 2147483647,
       category = case(random_int<33, "low", random_int<66, "medium", 1=1, "high")
| stats count avg(random_int) stdev(random_int) by category
```
This generates 1000 random samples and categorizes them."""

    if "time" in q or "timechart" in q:
        return """```spl
| makeresults count=168
| streamstats count as hour
| eval _time = relative_time(now(), "-".hour."h"),
       value = 50 + (random() % 50) + if(hour%24 > 8 AND hour%24 < 18, 30, 0)
| timechart span=1h avg(value) as metric
```
This simulates 7 days of hourly metrics with a business-hours pattern."""

    return (f"**Experiment for:** {user_input}\n\n"
            "```spl\n| makeresults count=100\n"
            "| streamstats count as row\n"
            f"| eval test_data = \"experiment: {user_input[:40]}\"\n"
            "| table row test_data\n```\n\n"
            "Modify the `eval` line to create your test data.")


def _handler_stabilize(user_input: str = "", **kwargs) -> str:
    """Provide system stabilization guidance."""
    return """**System Stabilization Checklist:**

**1. Resource Check:**
```bash
# CPU/Memory
cat /proc/loadavg
free -h
# Disk
df -h /app /app/chroma_store
```

**2. Service Health:**
```bash
curl -sk https://localhost:8000/api/admin/health
```

**3. Common Issues & Fixes:**

| Issue | Fix |
|-------|-----|
| High CPU (Ollama) | Restart: `podman restart llm_api_service` |
| ChromaDB slow | Check disk I/O: `iostat -x 1 5` |
| Redis OOM | Clear cache: `redis-cli FLUSHALL` |
| PostgreSQL connections | Check: `SELECT count(*) FROM pg_stat_activity` |
| App unresponsive | Restart: `podman restart chat_ui_app` |

**4. Performance Tuning:**
- Limit Ollama concurrent requests: `OLLAMA_NUM_PARALLEL=1`
- Reduce embedding batch size for low-memory systems
- Enable Redis caching for repeated queries
- Set `OLLAMA_KEEP_ALIVE=5m` to auto-unload idle models"""


def _handler_throttle(user_input: str = "", **kwargs) -> str:
    """Generate SPL throttling and rate-limiting patterns."""
    return """**SPL Throttling Patterns:**

**1. Dedup by time window:**
```spl
index=main sourcetype=auth action=failure
| bin _time span=5m
| stats count dc(src) values(src) by user _time
| where count > 5
```

**2. Rate limiting with streamstats:**
```spl
index=main sourcetype=access
| streamstats time_window=1m count as rate by src_ip
| where rate > 100
| dedup src_ip
```

**3. Alert throttling (savedsearches.conf):**
```ini
alert.suppress = 1
alert.suppress.period = 30m
alert.suppress.fields = src_ip, user
alert.suppress.group_name = brute_force_$src_ip$
```

**4. Search concurrency limits:**
```ini
# limits.conf
[search]
max_searches_per_cpu = 4
max_rt_search_multiplier = 1
max_searches_perc = 75
```"""


def _handler_warmup(user_input: str = "", **kwargs) -> str:
    """Warm up system components for optimal performance."""
    results = []

    try:
        import urllib.request
        from chat_app.settings import get_settings
        _ollama_url = get_settings().ollama.base_url.rstrip("/")
        req = urllib.request.Request(
            f"{_ollama_url}/api/embed",
            data=b'{"model":"mxbai-embed-large","input":"warmup test"}',
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        urllib.request.urlopen(req, timeout=60)
        results.append("- Ollama embed model: warmed up")
    except Exception as e:
        results.append(f"- Ollama embed model: {e}")

    try:
        import chromadb
        client = chromadb.PersistentClient(path="/app/chroma_store")
        cols = client.list_collections()
        total = sum(client.get_collection(c.name).count() for c in cols)
        results.append(f"- ChromaDB: {total} docs across {len(cols)} collections")
    except Exception as e:
        results.append(f"- ChromaDB: {e}")

    try:
        import redis
        from chat_app.settings import get_settings
        _rcfg = get_settings().cache
        r = redis.Redis(host=_rcfg.host, port=_rcfg.port, password=_rcfg.password, socket_timeout=2)
        r.ping()
        results.append(f"- Redis: connected ({r.dbsize()} keys)")
    except Exception as e:
        results.append(f"- Redis: {e}")

    return "**System Warmup Results:**\n\n" + "\n".join(results)


def _handler_organize(user_input: str = "", **kwargs) -> str:
    """Organize and structure Splunk data or configurations."""
    q = user_input.lower()
    if "index" in q or "data" in q:
        return """**Data Organization Strategy:**

**By Source Type:**
```
index=os_logs      \u2192 syslog, WinEventLog, linux_secure
index=web_logs     \u2192 access_combined, iis, nginx
index=app_logs     \u2192 log4j, json_app, custom_app
index=security     \u2192 firewall, ids, authentication
index=metrics      \u2192 perfmon, collectd, statsd
```

**By Environment:**
```
prod_*, dev_*, staging_*, qa_*
```

**By Retention:**
```
hot_30d, warm_90d, cold_1y, frozen_archive
```"""

    if "conf" in q or "config" in q:
        return """**Configuration Organization:**

```
$SPLUNK_HOME/etc/
\u251c\u2500\u2500 system/local/        # System-wide overrides
\u251c\u2500\u2500 apps/
\u2502   \u251c\u2500\u2500 search/local/    # Search app configs
\u2502   \u251c\u2500\u2500 my_app/
\u2502   \u2502   \u251c\u2500\u2500 default/     # App defaults (version controlled)
\u2502   \u2502   \u251c\u2500\u2500 local/       # Local overrides
\u2502   \u2502   \u251c\u2500\u2500 metadata/    # Permissions
\u2502   \u2502   \u251c\u2500\u2500 lookups/     # Reference data
\u2502   \u2502   \u2514\u2500\u2500 bin/         # Scripts
\u2502   \u2514\u2500\u2500 ...
\u2514\u2500\u2500 deployment-apps/     # Managed by deployment server
```

**Rules:**
- Never edit `default/` \u2014 use `local/` for overrides
- Use apps for logical grouping
- Version control `default/` directories"""

    return _handler_search_knowledge(user_input=f"organize {user_input}", k=5)


def _handler_guided_mode(user_input: str = "", **kwargs) -> str:
    """Provide step-by-step guided workflow."""
    q = user_input.lower()
    if "search" in q or "query" in q or "spl" in q:
        return """**Guided Search Builder:**

**Step 1 \u2014 Choose your data:**
What index and sourcetype? (e.g., `index=main sourcetype=syslog`)

**Step 2 \u2014 Filter:**
What are you looking for? Keywords, field values, time range?

**Step 3 \u2014 Transform:**
What analysis do you need?
- Count events \u2192 `| stats count`
- Group by field \u2192 `| stats count by fieldname`
- Over time \u2192 `| timechart count`
- Top values \u2192 `| top limit=10 fieldname`
- Unique values \u2192 `| stats dc(fieldname)`

**Step 4 \u2014 Format output:**
- Table \u2192 `| table field1 field2`
- Rename \u2192 `| rename old AS new`
- Sort \u2192 `| sort -count`

**Example complete query:**
```spl
index=main sourcetype=access_combined status>=400
| stats count by status uri_path
| sort -count
| head 20
```"""

    if "alert" in q:
        return """**Guided Alert Creation:**

**Step 1 \u2014 Define the search:**
```spl
index=main error | stats count | where count > 10
```

**Step 2 \u2014 Set schedule:**
- How often? `*/5 * * * *` (every 5 min)
- Time range? `-5m to now`

**Step 3 \u2014 Set trigger:**
- Number of results > 0? Or custom threshold?

**Step 4 \u2014 Choose action:**
- Email notification
- Webhook (Slack, PagerDuty)
- Script execution
- Log event

**Step 5 \u2014 Throttle:**
- Suppress for: 30 minutes
- Suppress on fields: src_ip, user"""

    return ("**Guided Mode**\n\n"
            "What would you like help with?\n"
            "- `search` \u2014 Build a search query step by step\n"
            "- `alert` \u2014 Create an alert step by step\n"
            "- `dashboard` \u2014 Design a dashboard step by step\n"
            "- `report` \u2014 Build a scheduled report\n"
            "- `config` \u2014 Configure a Splunk component")


def _handler_escalate(user_input: str = "", **kwargs) -> str:
    """Provide escalation procedures and templates."""
    return """**Escalation Procedures:**

**Severity Levels:**
| Level | Response Time | Examples |
|-------|--------------|---------|
| SEV-1 (Critical) | 15 min | Data loss, total outage |
| SEV-2 (High) | 1 hour | Partial outage, degraded |
| SEV-3 (Medium) | 4 hours | Performance issue, errors |
| SEV-4 (Low) | Next business day | Cosmetic, enhancement |

**Escalation Template:**
```
Subject: [SEV-X] Brief description
Time detected: YYYY-MM-DD HH:MM UTC
Impact: What's affected, how many users
Current status: Investigating / Mitigating / Resolved
Actions taken: What's been done so far
Next steps: What's planned
Owner: Who's handling it
```

**Splunk search for incident timeline:**
```spl
index=main (error OR exception OR fatal)
| timechart span=1m count by sourcetype
| addtotals
| where Total > baseline_threshold
```"""


def _handler_conflict_resolution(user_input: str = "", **kwargs) -> str:
    """Resolve Splunk configuration conflicts."""
    return """**Configuration Conflict Resolution:**

**Splunk Config Precedence (highest \u2192 lowest):**
1. `system/local/` \u2014 System local overrides
2. `apps/<app>/local/` \u2014 App local (most common)
3. `apps/<app>/default/` \u2014 App defaults
4. `system/default/` \u2014 System defaults

**Debugging:**
```spl
| rest /services/configs/conf-<filename> splunk_server=local
| table title value stanza eai:appName
```

```bash
# Show effective config
splunk btool <conf_name> list --debug
# Example:
splunk btool props list --debug | grep -A5 "sourcetype::syslog"
```

**Common Conflicts:**
- `props.conf` + `transforms.conf` \u2192 Check both files for same sourcetype
- Multiple apps defining same stanza \u2192 Higher-precedence app wins
- `inputs.conf` duplicates \u2192 First match wins, check all apps"""




# Handler registry for batch 3
HANDLERS = {
    "ingest_document": _handler_ingest_document,
    "create_dashboard": _handler_create_dashboard,
    "notify_critical": _handler_notify_critical,
    "cache": _handler_cache,
    "scheduler": _handler_scheduler,
    "deploy": _handler_deploy,
    "rollback": _handler_rollback,
    "export": _handler_export,
    "design": _handler_design,
    "experiment": _handler_experiment,
    "stabilize": _handler_stabilize,
    "throttle": _handler_throttle,
    "warmup": _handler_warmup,
    "organize": _handler_organize,
    "guided_mode": _handler_guided_mode,
    "escalate": _handler_escalate,
    "conflict_resolution": _handler_conflict_resolution,
}
