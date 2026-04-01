"""Admin Interactive Tools Extended — Log analysis, SPL performance, conf-validate, CIM map, commands, spec files.

Extracted from admin_interactive_tools_routes.py to keep file sizes manageable.
Contains: log-analyze, spl-performance, conf-validate, cim-map, execute-command, spec-files.
All public names are re-exported from the parent module for backward compatibility.
"""

import logging

from fastapi import HTTPException, Query, Request

from pydantic import BaseModel

from chat_app.admin_interactive_tools_routes import (
    interactive_tools_public_router,
    interactive_tools_router,
    LogAnalyzeRequest,
    SPLPerformanceRequest,
    ConfValidateRequest,
    CIMMapRequest,
)


class UpgradeCheckRequest(BaseModel):
    app_name: str
    cluster: str = "prod-search"

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# POST /tools/log-analyze
# ---------------------------------------------------------------------------

@interactive_tools_public_router.post("/tools/log-analyze", summary="Auto-detect fields in raw log lines")
async def log_analyze(body: LogAnalyzeRequest):
    """Analyze raw log text, detect fields (IP, timestamp, hostname, etc.), suggest extractions."""
    import re as _re

    lines = body.raw_log.strip().split('\n')
    sample = lines[0] if lines else ""

    _patterns = [
        ("ip_address", r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b',
         r'(?P<ip_address>\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'),
        ("mac_address", r'\b([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})\b',
         r'(?P<mac_address>[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})'),
        ("timestamp_iso", r'(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)',
         r'(?P<timestamp>\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)'),
        ("timestamp_syslog", r'([A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})',
         r'(?P<timestamp>[A-Z][a-z]{2}\s+\d{1,2}\s+\d{2}:\d{2}:\d{2})'),
        ("epoch", r'\b(1[6-7]\d{8})\b', r'(?P<epoch>1[6-7]\d{8})'),
        ("email", r'\b([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})\b',
         r'(?P<email>[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})'),
        ("url", r'(https?://[^\s"\'<>]+)', r'(?P<url>https?://[^\s"\'<>]+)'),
        ("port", r':(\d{2,5})\b', r':(?P<port>\d{2,5})'),
        ("http_method", r'\b(GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)\b',
         r'(?P<http_method>GET|POST|PUT|DELETE|PATCH|HEAD|OPTIONS)'),
        ("http_status", r'\b([1-5]\d{2})\b', r'(?P<http_status>[1-5]\d{2})'),
        ("severity", r'\b(DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|CRITICAL|NOTICE|ALERT|EMERG)\b',
         r'(?P<severity>DEBUG|INFO|WARN(?:ING)?|ERROR|FATAL|CRITICAL|NOTICE|ALERT|EMERG)'),
        ("hostname", r'\b([a-zA-Z][a-zA-Z0-9-]{1,62}(?:\.[a-zA-Z0-9-]+)*)\b', None),
        ("user", r'(?:user[= ]+|uid[= ]+)([a-zA-Z0-9._-]+)',
         r'(?:user[= ]+|uid[= ]+)(?P<user>[a-zA-Z0-9._-]+)'),
        ("pid", r'(?:\[(\d+)\]|pid[= ]+(\d+))', r'(?:\[(?P<pid>\d+)\]|pid[= ]+(?P<pid2>\d+))'),
        ("key_value", r'(\w[\w.-]*)=("[^"]*"|\S+)',
         r'(?P<key>\w[\w.-]*)=(?:"(?P<value_q>[^"]*)"|(?P<value>\S+))'),
        ("json_object", r'(\{[^{}]+\})', None),
        ("file_path", r'(/(?:[a-zA-Z0-9._-]+/)*[a-zA-Z0-9._-]+)',
         r'(?P<file_path>/(?:[a-zA-Z0-9._-]+/)*[a-zA-Z0-9._-]+)'),
    ]

    detected_fields = []
    rex_suggestions = []
    field_values = {}

    for name, pattern, rex_pat in _patterns:
        matches = _re.findall(pattern, sample, _re.IGNORECASE if name == "severity" else 0)
        if matches:
            vals = []
            for m in matches[:5]:
                if isinstance(m, tuple):
                    vals.extend([v for v in m if v])
                else:
                    vals.append(m)
            if vals:
                detected_fields.append({"field": name, "values": vals[:5], "count": len(matches)})
                field_values[name] = vals[0]
                if rex_pat:
                    rex_suggestions.append({
                        "field": name,
                        "rex": f'| rex field=_raw "{rex_pat}"',
                        "regex": rex_pat,
                    })

    parsed = {}
    for d in detected_fields:
        if d["field"] == "key_value":
            kv_pairs = _re.findall(r'(\w[\w.-]*)=(?:"([^"]*)"|(\S+))', sample)
            for k, v1, v2 in kv_pairs:
                parsed[k] = v1 or v2
        elif len(d["values"]) == 1:
            parsed[d["field"]] = d["values"][0]
        else:
            parsed[d["field"]] = d["values"]

    log_format = "unknown"
    if _re.match(r'^\d+\.\d+\.\d+\.\d+ .+ \[', sample):
        log_format = "apache_combined"
    elif _re.match(r'^[A-Z][a-z]{2}\s+\d', sample):
        log_format = "syslog"
    elif sample.strip().startswith('{'):
        log_format = "json"
    elif _re.match(r'^\d{4}-\d{2}-\d{2}', sample):
        log_format = "iso_timestamp"
    elif '<Event' in sample:
        log_format = "windows_xml"

    spath_suggestion = None
    if log_format == "json":
        spath_suggestion = '| spath | table *'

    return {
        "status": "ok",
        "line_count": len(lines),
        "log_format": log_format,
        "detected_fields": detected_fields,
        "parsed": parsed,
        "rex_suggestions": rex_suggestions,
        "spath_suggestion": spath_suggestion,
    }


# ---------------------------------------------------------------------------
# POST /tools/spl-performance
# ---------------------------------------------------------------------------

@interactive_tools_public_router.post("/tools/spl-performance", summary="Estimate SPL query performance")
async def spl_performance(body: SPLPerformanceRequest):
    """Analyze SPL query for performance issues and suggest optimizations."""
    import re as _re

    query = body.query.strip()
    issues = []
    suggestions = []
    score = 100

    commands = [c.strip() for c in _re.split(r'\|', query) if c.strip()]

    _expensive = {
        'join': ('join is expensive — O(n*m) complexity', 'Use stats/tstats with BY clause, or subsearch with format', 30),
        'transaction': ('transaction is memory-intensive', 'Use stats with earliest/latest and values() instead', 25),
        'append': ('append runs a separate search', 'Use multisearch or OR conditions when possible', 15),
        'map': ('map runs subsearch per result — very slow', 'Pre-compute values and use lookup or stats', 35),
        'multikv': ('multikv is CPU-intensive for table extraction', 'Use rex with specific patterns instead', 10),
        'diff': ('diff loads full result sets into memory', 'Limit results with head/where before diff', 15),
    }

    for cmd in commands:
        cmd_name = cmd.split()[0].lower() if cmd.split() else ""
        if cmd_name in _expensive:
            desc, fix, penalty = _expensive[cmd_name]
            issues.append({"severity": "high", "command": cmd_name, "issue": desc, "fix": fix})
            score -= penalty

    if _re.search(r'(?:^|\|)\s*search\s+\*(?:\s|$)', query, _re.IGNORECASE):
        issues.append({"severity": "high", "command": "search", "issue": "Searching all data with wildcard (*) — scans entire index", "fix": "Add index=, sourcetype=, or specific field filters"})
        score -= 25

    index_match = _re.search(r'index\s*=\s*(\S+)', query, _re.IGNORECASE)
    if not index_match:
        issues.append({"severity": "high", "command": "search", "issue": "No index= specified — may scan ALL indexes", "fix": "Always specify index= to limit scope. Use index::main (bloom filter, fastest) or index IN (main, security)"})
        score -= 20
    else:
        idx_val = index_match.group(1).strip('"').strip("'")
        if idx_val == '*':
            issues.append({"severity": "high", "command": "index", "issue": "index=* scans ALL indexes — extremely expensive", "fix": "Specify exact index names: index=main or index IN (main, security). Use index::main for bloom filter acceleration"})
            score -= 25
        elif '*' in idx_val:
            issues.append({"severity": "medium", "command": "index", "issue": f"Wildcard in index name (index={idx_val}) — scans multiple indexes", "fix": f"Use explicit index names: index IN (main, security) or index::{idx_val.replace('*', 'main')}"})
            score -= 15
        elif '::' in query[:query.index('|')] if '|' in query else '::' in query:
            suggestions.append({"type": "good", "message": "Using index:: prefix (bloom filter) — fastest index access"})
        first_cmd = commands[0] if commands else ""
        has_idx_time_filter = _re.search(r'(sourcetype|source|host)\s*=', first_cmd, _re.IGNORECASE)
        if not has_idx_time_filter:
            issues.append({"severity": "low", "command": "search", "issue": "No sourcetype/source/host in initial filter — index-time fields narrow search faster", "fix": "Add sourcetype= to initial search for faster filtering (index-time field)"})
            score -= 5

    subsearch_count = query.count('[')
    if subsearch_count > 0:
        if subsearch_count > 2:
            issues.append({"severity": "high", "command": "subsearch", "issue": f"{subsearch_count} nested subsearches — exponential complexity", "fix": "Reduce subsearch depth, use lookup tables or stats"})
            score -= 20
        else:
            issues.append({"severity": "low", "command": "subsearch", "issue": "Subsearch found — limited to 10K results / 60s by default", "fix": "Ensure subsearch returns minimal results"})
            score -= 5

    eval_rex = _re.findall(r'eval\s+\w+\s*=\s*(?:match|replace|if\s*\(\s*match)', query, _re.IGNORECASE)
    if eval_rex:
        issues.append({"severity": "low", "command": "eval", "issue": "Regex in eval — slower than rex command", "fix": "Use | rex for field extraction instead of eval+match"})
        score -= 5

    if _re.search(r'\|\s*fields\s+', query, _re.IGNORECASE):
        suggestions.append({"type": "good", "message": "Using fields command to limit data transfer"})

    if _re.search(r'\|\s*dedup\s+', query) and not _re.search(r'sortby', query):
        issues.append({"severity": "low", "command": "dedup", "issue": "dedup without sortby — results may be non-deterministic", "fix": "Add sortby parameter to dedup, or use | sort | dedup"})
        score -= 3

    if _re.search(r'\|\s*head\s+', query, _re.IGNORECASE):
        suggestions.append({"type": "good", "message": "Using head to limit results — reduces processing"})

    if 'datamodel' in query.lower() and 'tstats' not in query.lower():
        suggestions.append({"type": "optimization", "message": "Consider using | tstats for accelerated data model searches"})

    has_time = bool(_re.search(r'earliest|latest|_time', query, _re.IGNORECASE))
    if not has_time:
        issues.append({"severity": "medium", "command": "time", "issue": "No explicit time range — may use default (24h or All Time)", "fix": "Add earliest= and latest= or use the time picker"})
        score -= 5

    cmd_count = len(commands)
    if cmd_count > 10:
        issues.append({"severity": "low", "command": "pipeline", "issue": f"Long pipeline ({cmd_count} commands) — complex queries are harder to optimize", "fix": "Consider breaking into multiple searches or using summary indexes"})
        score -= 5

    score = max(0, min(100, score))
    rating = "excellent" if score >= 90 else "good" if score >= 70 else "fair" if score >= 50 else "poor" if score >= 30 else "critical"

    return {
        "status": "ok",
        "score": score,
        "rating": rating,
        "command_count": cmd_count,
        "issues": issues,
        "suggestions": suggestions,
    }


# ---------------------------------------------------------------------------
# POST /tools/conf-validate
# ---------------------------------------------------------------------------

@interactive_tools_public_router.post("/tools/conf-validate", summary="Validate Splunk conf file syntax")
async def conf_validate(body: ConfValidateRequest):
    """Validate a Splunk .conf file for syntax errors, regex validity, and conflicts."""
    import re as _re

    try:
        from shared.conf_parser import parse_conf_file_advanced
        parsed = parse_conf_file_advanced(body.conf_content, f"{body.conf_type}.conf")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "message": f"Parse error: {exc}"}

    errors = []
    warnings = []
    info = []
    stanza_count = len(parsed)

    _regex_keys = {
        "props": ["LINE_BREAKER", "BREAK_ONLY_BEFORE", "MUST_BREAK_AFTER", "TIME_PREFIX", "SEDCMD-"],
        "transforms": ["REGEX", "DELIMS", "MV_ADD"],
    }

    for stanza_name, settings in parsed.items():
        keys = {k: v for k, v in settings.items() if not k.startswith('__')}

        if not keys:
            warnings.append({"stanza": stanza_name, "key": "", "message": "Empty stanza — no settings defined"})
            continue

        for key, value in keys.items():
            regex_prefixes = _regex_keys.get(body.conf_type, [])
            is_regex_key = any(key == rk or key.startswith(rk) for rk in regex_prefixes)
            if is_regex_key and value:
                try:
                    _re.compile(value)
                except _re.error as exc:
                    errors.append({
                        "stanza": stanza_name, "key": key,
                        "message": f"Invalid regex: {exc}",
                        "value": value[:100],
                    })

            if body.conf_type == "props" and key.startswith("EXTRACT-"):
                try:
                    compiled = _re.compile(value)
                    groups = compiled.groupindex
                    if not groups:
                        warnings.append({
                            "stanza": stanza_name, "key": key,
                            "message": "EXTRACT regex has no named groups — use (?P<name>...) for field extraction",
                        })
                except _re.error as _exc:
                    logger.debug("Invalid regex in EXTRACT stanza %r key %r: %s", stanza_name, key, _exc)

            if body.conf_type == "props" and key.startswith("REPORT-"):
                transform_refs = [t.strip() for t in value.split(",")]
                for tr in transform_refs:
                    info.append({
                        "stanza": stanza_name, "key": key,
                        "message": f"References transform: [{tr}] — ensure it exists in transforms.conf",
                    })

            if key == "SHOULD_LINEMERGE" and value.lower() not in ("true", "false", "0", "1", "yes", "no"):
                errors.append({"stanza": stanza_name, "key": key, "message": f"Invalid boolean value: '{value}'"})

            if key == "TIME_FORMAT" and value:
                if '%s' in value and len(value) > 2:
                    warnings.append({"stanza": stanza_name, "key": key, "message": "%s (epoch) should typically be used alone, not mixed with other tokens"})

            if key == "KV_MODE" and value not in ("auto", "json", "xml", "none", "multi"):
                warnings.append({"stanza": stanza_name, "key": key, "message": f"Unknown KV_MODE: '{value}'. Valid: auto, json, xml, none, multi"})

            if key == "TRUNCATE":
                try:
                    trunc = int(value)
                    if trunc > 1000000:
                        warnings.append({"stanza": stanza_name, "key": key, "message": f"Very large TRUNCATE ({trunc}) — may cause memory issues"})
                except ValueError:
                    errors.append({"stanza": stanza_name, "key": key, "message": f"TRUNCATE must be an integer, got: '{value}'"})

    # Field name collision detection
    field_sources = {}
    for stanza_name, settings in parsed.items():
        for key, value in settings.items():
            if key.startswith('__'):
                continue
            if key.startswith("EXTRACT-"):
                try:
                    groups = list(_re.compile(value).groupindex.keys())
                    for g in groups:
                        if g in field_sources:
                            if field_sources[g] != stanza_name:
                                warnings.append({
                                    "stanza": stanza_name, "key": key,
                                    "message": f"Field '{g}' also extracted in [{field_sources[g]}] — potential collision",
                                })
                        else:
                            field_sources[g] = stanza_name
                except _re.error as _exc:
                    logger.debug("Invalid regex in cross-stanza check for stanza %r key %r: %s", stanza_name, key, _exc)

    return {
        "status": "ok",
        "stanza_count": stanza_count,
        "stanzas": list(parsed.keys()),
        "errors": errors,
        "warnings": warnings,
        "info": info,
        "valid": len(errors) == 0,
    }


# ---------------------------------------------------------------------------
# POST /tools/cim-map
# ---------------------------------------------------------------------------

@interactive_tools_public_router.post("/tools/cim-map", summary="Map log fields to CIM data model")
async def cim_field_map(body: CIMMapRequest):
    """Analyze a sample log and suggest CIM field mappings."""
    import re as _re
    import json as _json

    _field_map = {
        r'(?:src_?ip|source_?ip|client_?ip|clientip|remote_?addr)': 'src',
        r'(?:dst_?ip|dest_?ip|destination_?ip|server_?ip)': 'dest',
        r'(?:src_?port|source_?port|sport)': 'src_port',
        r'(?:dst_?port|dest_?port|destination_?port|dport|dpt)': 'dest_port',
        r'(?:user_?name|username|uid|login|account_?name|TargetUserName)': 'user',
        r'(?:src_?user|source_?user|SubjectUserName)': 'src_user',
        r'(?:http_?method|method|verb|cs-method)': 'http_method',
        r'(?:http_?status|status_?code|response_?code|sc-status|status)': 'status',
        r'(?:url|uri|request_?uri|cs-uri-stem|path)': 'url',
        r'(?:user_?agent|http_?user_?agent|cs-User-Agent)': 'http_user_agent',
        r'(?:bytes|bytes_?in|sc-bytes|content_?length|size)': 'bytes',
        r'(?:duration|elapsed|response_?time|duration_?ms|time_?taken)': 'duration',
        r'(?:action|event_?action|Activity|EventType)': 'action',
        r'(?:severity|level|priority|sev)': 'severity',
        r'(?:hostname|host|computer|Computer|dvc)': 'dvc',
        r'(?:process|process_?name|exe|Image|CommandLine)': 'process',
        r'(?:process_?id|pid|ProcessId)': 'process_id',
        r'(?:app|application|service|sourcetype)': 'app',
        r'(?:category|event_?category|Category)': 'category',
        r'(?:message|msg|description|Description)': 'body',
        r'(?:signature|rule|signature_?id|EventID|EventCode)': 'signature',
        r'(?:protocol|proto|transport)': 'transport',
    }

    sample = body.sample_log.strip()

    kv_pairs = _re.findall(r'(\w[\w.-]*)=(?:"([^"]*)"|(\S+))', sample)
    found_fields = {}
    for k, v1, v2 in kv_pairs:
        found_fields[k] = v1 or v2

    try:
        parsed_json = _json.loads(sample)
        if isinstance(parsed_json, dict):
            found_fields.update(parsed_json)
    except _json.JSONDecodeError as _exc:
        logger.debug("Sample does not parse as JSON (non-fatal): %s", _exc)

    ips = _re.findall(r'\b(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b', sample)
    if ips and 'src' not in found_fields:
        found_fields['_detected_ip_1'] = ips[0]
    if len(ips) > 1 and 'dest' not in found_fields:
        found_fields['_detected_ip_2'] = ips[1]

    mappings = []
    mapped_cim = set()
    for field_name, field_value in found_fields.items():
        best_cim = None
        best_score = 0
        for pattern, cim_field in _field_map.items():
            if _re.search(pattern, field_name, _re.IGNORECASE):
                score = len(pattern)
                if score > best_score:
                    best_score = score
                    best_cim = cim_field
        if best_cim and best_cim not in mapped_cim:
            mappings.append({
                "source_field": field_name,
                "cim_field": best_cim,
                "sample_value": str(field_value)[:100],
                "confidence": "high" if best_score > 20 else "medium",
            })
            mapped_cim.add(best_cim)

    alias_lines = []
    for m in mappings:
        if m["source_field"] != m["cim_field"]:
            alias_lines.append(f'FIELDALIAS-{m["cim_field"]} = {m["source_field"]} AS {m["cim_field"]}')

    return {
        "status": "ok",
        "detected_fields": list(found_fields.keys())[:50],
        "mappings": mappings,
        "fieldalias_conf": "\n".join(alias_lines) if alias_lines else "# No aliases needed — fields already match CIM names",
        "model": body.model,
    }


# ---------------------------------------------------------------------------
# Execute slash commands programmatically
# ---------------------------------------------------------------------------

@interactive_tools_router.post("/execute-command", summary="Execute a slash command programmatically")
async def execute_command(request: Request):
    """Execute a slash command from the admin API.

    Body: {"command": "health", "args": ""}
    """
    try:
        body = await request.json()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[ADMIN] Failed to parse request JSON body: %s", exc)
        return {"status": "error", "error": "Invalid JSON body"}

    command = body.get("command", "").strip()
    args = body.get("args", "").strip()
    if not command:
        return {"status": "error", "error": "Missing 'command' field"}

    cmd_str = f"/{command}"
    if args:
        cmd_str = f"{cmd_str} {args}"

    from chat_app.slash_commands import _COMMAND_TABLE

    entry = _COMMAND_TABLE.get(cmd_str.split()[0])
    if entry is None:
        available = sorted(k.lstrip("/") for k in _COMMAND_TABLE)
        return {
            "status": "error",
            "error": f"Unknown command: /{command}",
            "available_commands": available,
        }

    handler, needs_args, needs_kwargs = entry

    try:
        if needs_args and needs_kwargs:
            result = await handler(args, vector_store=None, engine=None)
        elif needs_args:
            result = await handler(args)
        else:
            result = await handler()

        return {
            "status": "ok",
            "command": command,
            "args": args,
            "result": str(result) if result else "Command executed (output sent to chat)",
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[ADMIN] Command execution failed: /%s %s — %s", command, args, exc)
        raise HTTPException(status_code=500, detail=f"Command /{command} failed: {exc}")


# ---------------------------------------------------------------------------
# Spec File Browser
# ---------------------------------------------------------------------------

@interactive_tools_public_router.get("/spec-files", summary="List available .conf.spec files")
async def list_spec_files(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """Return list of available Splunk .conf.spec reference files."""
    import pathlib
    spec_dirs = [pathlib.Path("/app/shared/public/documents/specs"), pathlib.Path("ingest_specs")]
    specs = []
    for d in spec_dirs:
        if d.exists():
            for f in sorted(d.glob("*.conf.spec")):
                name = f.name.replace(".conf.spec", ".conf")
                specs.append({"name": name, "file": f.name, "size": f.stat().st_size})
            break
    total = len(specs)
    page = specs[offset:offset + limit]
    return {"specs": page, "total": total, "count": len(page)}


@interactive_tools_public_router.get("/spec-files/{spec_name}", summary="Get parsed spec file content")
async def get_spec_file(spec_name: str):
    """Return parsed content of a .conf.spec file with stanzas and options."""
    import pathlib
    import re
    safe = re.sub(r'[^a-zA-Z0-9_.\-]', '', spec_name)
    if not safe.endswith('.conf.spec'):
        safe = safe.replace('.conf', '') + '.conf.spec'
    spec_dirs = [pathlib.Path("/app/shared/public/documents/specs"), pathlib.Path("ingest_specs")]
    spec_path = None
    for d in spec_dirs:
        candidate = d / safe
        if candidate.exists():
            spec_path = candidate
            break
    if not spec_path:
        raise HTTPException(status_code=404, detail=f"Spec file '{safe}' not found")
    try:
        text = spec_path.read_text(encoding='utf-8', errors='replace')
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read spec file: {exc}")

    stanzas = []
    current_stanza = {"name": "[default]", "description": "", "options": []}
    header_comment = []
    in_header = True
    current_option = None
    for line in text.split('\n'):
        stripped = line.strip()
        if stripped.startswith('[') and ']' in stripped:
            if in_header:
                current_stanza["description"] = '\n'.join(header_comment[-10:]) if header_comment else ""
                in_header = False
            if current_option:
                current_stanza["options"].append(current_option)
                current_option = None
            if current_stanza["options"] or current_stanza["name"] != "[default]":
                stanzas.append(current_stanza)
            current_stanza = {"name": stripped, "description": "", "options": []}
            continue
        if stripped.startswith('#'):
            comment = stripped.lstrip('#').strip()
            if in_header:
                header_comment.append(comment)
            elif current_option:
                current_option["description"] += ' ' + comment if current_option["description"] else comment
            else:
                current_stanza["description"] += (' ' + comment) if current_stanza["description"] else comment
            continue
        m = re.match(r'^([a-zA-Z_][a-zA-Z0-9_.\-<>]*)\s*=\s*(.*)', stripped)
        if m:
            if current_option:
                current_stanza["options"].append(current_option)
            current_option = {"key": m.group(1), "default": m.group(2).strip(), "description": ""}
            in_header = False
            continue
        if stripped and current_option:
            current_option["description"] += ' ' + stripped if current_option["description"] else stripped
    if current_option:
        current_stanza["options"].append(current_option)
    if current_stanza["options"] or current_stanza["name"] != "[default]":
        stanzas.append(current_stanza)
    conf_name = safe.replace('.spec', '')
    return {"name": conf_name, "stanzas": stanzas, "total_options": sum(len(s["options"]) for s in stanzas)}


# ---------------------------------------------------------------------------
# POST /tools/upgrade-check
# ---------------------------------------------------------------------------

@interactive_tools_public_router.post("/tools/upgrade-check", summary="Quick upgrade readiness check")
async def tool_upgrade_check(body: UpgradeCheckRequest):
    """Check if a Splunk app can be safely upgraded.

    Runs static analysis: conf diffs, CIM compliance, dependency impact.
    Uses the upgrade_readiness package's real analysis engine.
    """
    try:
        from chat_app.upgrade_readiness.baseline_builder import scan_app_directory
        from chat_app.upgrade_readiness.conf_differ import three_way_diff
        from chat_app.upgrade_readiness.impact_scorer import score_findings, build_impact_report
        from chat_app.upgrade_readiness.upgrade_advisor import lookup_app, get_type_info
        from chat_app.upgrade_readiness.es_analyzer import detect_upgrade_type
        import os

        # Look up app in Splunkbase catalog
        app_data = lookup_app(body.app_name)
        upgrade_type = detect_upgrade_type(body.app_name).value
        type_info = get_type_info(upgrade_type)

        # Try to find app in org repo
        repo_base = "documents/repo/splunk"
        app_dirs = []
        if os.path.exists(repo_base):
            for root, dirs, files in os.walk(repo_base):
                for d in dirs:
                    if d.lower() == body.app_name.lower():
                        full = os.path.join(root, d)
                        if os.path.exists(os.path.join(full, "default")):
                            app_dirs.append(full)

        findings = []
        installed_version = ""

        if app_dirs:
            # Scan the first found app directory
            old_baseline = scan_app_directory(app_dirs[0])
            installed_version = old_baseline.version.version if old_baseline.version else ""

            # If we have a new version to compare against (from upgrade test data)
            new_dir = f"/tmp/upgrade_test/{body.app_name}"
            if not os.path.exists(new_dir):
                # No new version available — report what we found
                local_count = sum(len(stanzas) for stanzas in old_baseline.local_confs.values())
                return {
                    "status": "ok",
                    "app_name": body.app_name,
                    "cluster": body.cluster,
                    "upgrade_type": upgrade_type,
                    "installed_version": installed_version,
                    "latest_version": app_data.get("latest_version", "unknown") if app_data else "unknown",
                    "risk_level": "info",
                    "finding_count": 0,
                    "local_customizations": local_count,
                    "repo_locations": app_dirs,
                    "recommendation": (
                        f"Found {body.app_name} v{installed_version} with {local_count} local customizations. "
                        f"Latest available: v{app_data.get('latest_version', '?') if app_data else '?'}. "
                        f"Upload or download the new version to run a full diff analysis."
                    ),
                    "type_info": {
                        "label": type_info.get("label", ""),
                        "what_we_check": type_info.get("what_we_check", [])[:5],
                    },
                }

            # We have both versions — run full diff
            new_baseline = scan_app_directory(new_dir)
            for conf_type in set(list(old_baseline.default_confs.keys()) + list(new_baseline.default_confs.keys())):
                if conf_type == "app":
                    continue
                conf_findings = three_way_diff(
                    old_baseline.default_confs.get(conf_type, {}),
                    new_baseline.default_confs.get(conf_type, {}),
                    old_baseline.local_confs.get(conf_type, {}),
                    conf_type=conf_type,
                )
                findings.extend(conf_findings)

            scored = score_findings(findings)
            target_ver = new_baseline.version.version if new_baseline.version else "unknown"
            report = build_impact_report(
                scored, app_id=body.app_name,
                from_version=installed_version,
                to_version=target_ver,
                cluster=body.cluster,
            )

            # Run config auditor against the merged conf files
            audit_report = None
            readiness_score = None
            try:
                from chat_app.upgrade_readiness.config_auditor import ConfigAuditor
                from chat_app.upgrade_readiness.readiness_scorer import ReadinessScorer

                merged_confs = {}
                for conf_type, stanzas in old_baseline.default_confs.items():
                    merged = dict(stanzas)
                    local = old_baseline.local_confs.get(conf_type, {})
                    for stanza, keys in local.items():
                        merged.setdefault(stanza, {}).update(keys)
                    merged_confs[conf_type] = merged

                auditor = ConfigAuditor()
                audit_report = auditor.audit(
                    conf_files=merged_confs,
                    from_version=installed_version or "9.0.0",
                    to_version=target_ver,
                )

                scorer = ReadinessScorer()
                readiness_score = scorer.calculate_score(
                    config_audit=audit_report,
                    conf_diff_findings=findings,
                )
            except (ImportError, Exception) as audit_exc:
                logger.debug("[TOOLS] Config audit skipped: %s", audit_exc)

            risk_map = {"CRITICAL": "critical", "HIGH": "high", "MEDIUM": "medium", "LOW": "low", "INFO": "safe"}
            risk_level = risk_map.get(report.overall_risk.value, "unknown")

            response: dict = {
                "status": "ok",
                "app_name": body.app_name,
                "cluster": body.cluster,
                "upgrade_type": upgrade_type,
                "installed_version": installed_version,
                "target_version": target_ver,
                "latest_version": app_data.get("latest_version", "unknown") if app_data else "unknown",
                "risk_level": risk_level,
                "finding_count": len(report.findings),
                "recommendation": report.recommendation,
                "findings": [
                    {
                        "risk": f.risk.value,
                        "category": f.category.value,
                        "stanza": f.stanza,
                        "conf_type": f.conf_type,
                        "description": f.description,
                        "recommendation": f.recommendation,
                    }
                    for f in report.findings[:30]
                ],
            }

            # Attach readiness score and config audit findings when available
            if readiness_score is not None:
                response["readiness_score"] = readiness_score.to_dict()
                response["blockers"] = readiness_score.blocker_count
            if audit_report is not None:
                response["config_audit_findings"] = [
                    f.to_dict() for f in audit_report.findings[:20]
                ]

            return response
        else:
            # App not found in repo — return catalog info
            return {
                "status": "ok",
                "app_name": body.app_name,
                "cluster": body.cluster,
                "upgrade_type": upgrade_type,
                "installed_version": "not found in repo",
                "latest_version": app_data.get("latest_version", "unknown") if app_data else "unknown",
                "risk_level": "info",
                "finding_count": 0,
                "recommendation": (
                    f"{body.app_name} not found in org repo at {repo_base}. "
                    f"Add the app's default/ and local/ dirs to the repo to enable full analysis. "
                    f"Latest on Splunkbase: v{app_data.get('latest_version', '?') if app_data else '?'}"
                ),
                "type_info": {
                    "label": type_info.get("label", ""),
                    "what_we_check": type_info.get("what_we_check", [])[:5],
                },
            }

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[TOOLS] upgrade-check error for %s on %s: %s", body.app_name, body.cluster, exc)
        return {
            "status": "error",
            "app_name": body.app_name,
            "cluster": body.cluster,
            "risk_level": "unknown",
            "finding_count": 0,
            "recommendation": f"Analysis error: {type(exc).__name__}: {str(exc)[:200]}",
        }
