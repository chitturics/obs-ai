# Splunk Troubleshooting Guide

## Search Issues

### My search is returning no results
**Common causes and fixes:**
1. **Wrong index or sourcetype** — Verify with: `| eventcount summarize=false index=* | sort -count`
2. **Time range too narrow** — Expand to "All Time" first, then narrow down
3. **Permissions** — Check role has `srchIndexesAllowed` for the target index in authorize.conf
4. **Data not indexed yet** — Check ingestion pipeline: `index=_internal source=*metrics.log group=per_sourcetype_thruput`
5. **Typos in field names** — Use `| fieldsummary` to see actual field names
6. **Search syntax error** — Validate quotes, parentheses, and pipe positions

### Search is taking too long / slow search performance
**Steps to troubleshoot slow searches:**
1. **Check Job Inspector** — Click inspector icon; look at scan count vs result count
2. **Add specific index and sourcetype** — Never use `index=*`
3. **Move filters to base search** — `index=main error` is faster than `index=main | search error`
4. **Use tstats** — `| tstats count from datamodel=Web by Web.status` is 10-100x faster
5. **Add fields early** — `| fields + needed_field1, needed_field2` reduces data transfer
6. **Replace join with lookup** — Lookups are faster and use less memory
7. **Use TERM() for exact matches** — `index=main TERM(error_code=404)` uses index-time tokens
8. **Check search.log** — `index=_audit action=search info=completed | sort -total_run_time`

### Getting 'max results' warning
**Fix in limits.conf:**
```ini
# limits.conf
[restapi]
maxresultrows = 50000

[searchresults]
max_count = 50000
maxresultrows = 50000
```
Or use `| head 10000` in your search to explicitly limit. Default is 50000.

### Search head running out of memory
**Fixes:**
- `limits.conf`: Set `search_process_memory_usage_threshold = 0.5`
- Avoid `| join` on large datasets (50K row limit)
- Use `| stats` instead of `| transaction` when possible
- Reduce dispatch.buckets with `dispatch.max_count`
- Schedule heavy reports during off-hours

### Subsearch not returning results
**Common issues:**
- Subsearch default limit is 10000 results and 60 seconds
- Use `| return 10000` or `| format` to pass results correctly
- Check `maxresultrows` in limits.conf under `[subsearch]`
- Subsearch runs first, then feeds results to outer search

## Data Issues

### Data is not being indexed
**Troubleshooting checklist:**
1. Check `inputs.conf` — Is the input enabled? `disabled = false`
2. Check permissions — Does the splunk user have read access to the monitored file?
3. Check `internal logs` — `index=_internal source=*splunkd.log component=TailingProcessor`
4. Check `fishbucket` — `| inputlookup fishbucket_dir | search source=*your_file*`
5. Verify network — For forwarded data: `index=_internal source=*metrics.log group=tcpin_connections`
6. Check `outputs.conf` — Is the forwarder pointing to the correct indexer?

### Events have wrong timestamps
**Fix with props.conf:**
```ini
[my_sourcetype]
TIME_FORMAT = %Y-%m-%d %H:%M:%S
TIME_PREFIX = ^
MAX_TIMESTAMP_LOOKAHEAD = 25
TZ = UTC
```
Use `| eval _time=strptime(your_field, "%Y-%m-%d %H:%M:%S")` for post-processing fixes.

### Line breaking is incorrect
**Fix with props.conf:**
```ini
[my_sourcetype]
SHOULD_LINEMERGE = false
LINE_BREAKER = ([\r\n]+)
TRUNCATE = 10000
```
For multi-line events (like Java stack traces):
```ini
SHOULD_LINEMERGE = true
BREAK_ONLY_BEFORE_DATE = true
LINE_BREAKER = ([\r\n]+)\d{4}-\d{2}-\d{2}
```

### Field extractions not working
**Debugging steps:**
1. Check `props.conf` for correct sourcetype mapping
2. Verify extraction with: `| makeresults | eval _raw="your sample event" | extract`
3. Use `| rex` for inline testing: `| rex field=_raw "(?P<myfield>pattern)"`
4. Check transforms.conf REGEX syntax with regex101.com
5. Verify the stanza name matches the sourcetype exactly

### Sourcetype not being recognized
**Fix:**
1. Check `props.conf` for matching stanza name
2. Force sourcetype in inputs.conf: `sourcetype = my_type`
3. Check automatic sourcetype detection: `index=_internal source=*splunkd.log component=LearnedSourcetypes`
4. Clear learned types if needed: `$SPLUNK_HOME/var/lib/splunk/learnedtypes.conf`

### Data going to wrong index
**Fix with transforms.conf routing:**
```ini
# transforms.conf
[route_to_security]
REGEX = (attack|malware|threat)
DEST_KEY = _MetaData:Index
FORMAT = security

# props.conf
[my_sourcetype]
TRANSFORMS-routing = route_to_security
```
Or set index explicitly in inputs.conf: `index = security`

## Forwarder Issues

### Splunk forwarder not sending data
**Troubleshooting:**
1. Check forwarder status: `./splunk list forward-server`
2. Check outputs.conf for correct server and port
3. Check internal logs: `index=_internal host=forwarder_host source=*splunkd.log`
4. Test connectivity: `telnet indexer_ip 9997`
5. Check certificate issues for SSL: `index=_internal source=*splunkd.log ssl error`
6. Restart forwarder: `./splunk restart`

### Heavy Forwarder vs Universal Forwarder
| Feature | Universal (UF) | Heavy (HF) |
|---------|---------------|------------|
| Parsing | No | Yes |
| Routing | Basic | Full |
| Size | ~100MB | Full install |
| CPU/Memory | Low | High |
| Field extraction | No | Yes |
| Use case | Simple forwarding | Parse, filter, route |

## Cluster Issues

### Indexer cluster not replicating
**Checks:**
1. Cluster status: `| rest /services/cluster/master/peers`
2. Replication factor: Check server.conf `replication_factor`
3. Search factor: Check server.conf `search_factor`
4. Bucket fixup: `| rest /services/cluster/master/fixup`
5. Network connectivity between peers on replication port (8080 default)

### Search head cluster issues
**Debugging:**
1. Captain status: `| rest /services/shcluster/captain/info`
2. Member status: `| rest /services/shcluster/member/info`
3. Artifacts replication: Check `shcluster/` in server.conf
4. Rolling restart: `./splunk rolling-restart shcluster-members`

## Knowledge Object Issues

### Lookup not working
**Common fixes:**
1. Verify lookup file exists: `$SPLUNK_HOME/etc/apps/search/lookups/`
2. Check transforms.conf definition matches field names exactly
3. Verify field names in lookup CSV match search field names
4. Check permissions: `metadata/local.meta` for sharing
5. Test manually: `| inputlookup my_lookup.csv | head 5`

### Alert not triggering
**Debugging:**
1. Run the search manually — does it return results?
2. Check schedule: `cron_schedule` in savedsearches.conf
3. Check trigger conditions: `alert_type`, `alert_comparator`, `alert_threshold`
4. Check alert suppress settings
5. Review: `index=_internal source=*scheduler.log savedsearch_name="your_alert"`
6. Verify actions: email settings, webhook URLs, script permissions

### Dashboard not loading
**Fixes:**
1. Check for XML errors: validate in Dashboard Editor
2. Check search permissions for the dashboard owner role
3. Check for deprecated Simple XML features
4. Verify time tokens are properly set
5. Check panel dependencies and base searches
6. Review: `index=_internal source=*web_access.log uri=*dashboard*`

## Performance Tuning

### Splunk indexer is slow
**Optimizations:**
1. Review `indexes.conf` settings: `maxHotBuckets`, `maxDataSize`
2. Check disk I/O: Splunk needs fast storage for hot/warm buckets
3. Review `limits.conf`: `max_searches_per_cpu`, `base_max_searches`
4. Check license usage: `| rest /services/licenser/usage`
5. Monitor: `index=_internal source=*metrics.log group=pipeline`

### Splunk search head is slow
**Optimizations:**
1. Reduce concurrent searches: `limits.conf` `max_searches_per_cpu`
2. Enable search affinity for clustered search heads
3. Use summary indexing for common heavy searches
4. Move reports to scheduled rather than ad-hoc
5. Check: `index=_audit action=search info=completed | sort -total_run_time | head 20`

## Common SPL Errors

### "Error in search expression"
- Check balanced quotes (single and double)
- Check balanced parentheses
- Check pipe positions — no empty pipes `| |`
- Verify command names are valid

### "Field not found"
- Use `| fieldsummary` to see available fields
- Check field name case sensitivity
- Verify field is extracted at search time
- Check if field requires `spath` for JSON data

### "Memory limit reached"
- Add `| head N` or `| tail N` to limit results
- Use `| stats` instead of raw events for aggregation
- Reduce time range
- Add more filters to base search
- Check `limits.conf` `max_mem_usage_mb`
