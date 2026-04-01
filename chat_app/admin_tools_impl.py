"""Large endpoint implementations for admin_tools.py.

Registers routes onto tools_router (defined in admin_tools.py).
Kept separate to stay under 600 lines per file.

Endpoints:
- POST /tools/network-test
- POST /tools/syslog-test
- POST /tools/regex-ai
- POST /tools/regex-generate
- POST /tools/fs-monitor
- POST /tools/ai-chat
- POST /tools/transform-ai
"""

import asyncio
import logging
import os
import socket

from chat_app.admin_shared import _human_size
from chat_app.admin_tools import (
    tools_router,
    NetworkTestRequest,
    SyslogTestRequest,
    RegexAIRequest,
    RegexGenerateRequest,
    FSMonitorRequest,
    ToolsAIChatRequest,
    TransformAIRequest,
)
from chat_app.settings import get_settings

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# POST /api/admin/tools/network-test
# ---------------------------------------------------------------------------

@tools_router.post("/tools/network-test", summary="Run network diagnostic")
async def network_test(body: NetworkTestRequest):
    """Run DNS lookup, ping, or port check using Python-native tools."""
    import time as _time
    import re as _re

    if not _re.match(r'^[a-zA-Z0-9._:\-\[\]]+$', body.target):
        return {"status": "error", "message": "Invalid target -- only hostname/IP allowed"}

    try:
        if body.tool == "dns":
            start = _time.perf_counter()
            try:
                results = socket.getaddrinfo(body.target, None)
                elapsed = int((_time.perf_counter() - start) * 1000)
                ips = list({r[4][0] for r in results})
                families = list({("IPv4" if r[0] == socket.AF_INET else "IPv6") for r in results})
                reverse = []
                for ip in ips[:3]:
                    try:
                        hostname = socket.gethostbyaddr(ip)[0]
                        reverse.append(f"{ip} -> {hostname}")
                    except socket.herror:
                        reverse.append(f"{ip} -> (no reverse DNS)")
                output = f"DNS Lookup: {body.target}\nResolved in {elapsed}ms\n\n"
                output += "Addresses:\n" + "\n".join(f"  {ip} ({'/'.join(families)})" for ip in ips) + "\n\n"
                output += "Reverse DNS:\n" + "\n".join(f"  {r}" for r in reverse)
                return {"status": "ok", "tool": "dns", "target": body.target,
                        "output": output, "ips": ips, "elapsed_ms": elapsed}
            except socket.gaierror as e:
                return {"status": "error", "tool": "dns", "target": body.target,
                        "output": f"DNS lookup failed: {e}", "ips": [], "message": str(e)}

        elif body.tool == "ping":
            output = f"TCP Ping: {body.target} (3 attempts)\n\n"
            ports_to_try = [80, 443, 8089, 8000, 22]
            latencies = []
            for i in range(3):
                for port in ports_to_try:
                    try:
                        start = _time.perf_counter()
                        s = socket.create_connection((body.target, port), timeout=2)
                        elapsed = (_time.perf_counter() - start) * 1000
                        s.close()
                        latencies.append(elapsed)
                        output += f"  Attempt {i+1}: Connected to port {port} in {elapsed:.1f}ms\n"
                        break
                    except (socket.timeout, ConnectionRefusedError, OSError):
                        continue
                else:
                    output += f"  Attempt {i+1}: No open port found (tried {ports_to_try})\n"
            if latencies:
                avg = sum(latencies) / len(latencies)
                output += f"\nAverage: {avg:.1f}ms, Min: {min(latencies):.1f}ms, Max: {max(latencies):.1f}ms"
            else:
                output += "\nHost unreachable -- no open TCP ports detected"
            return {"status": "ok", "tool": "ping", "target": body.target,
                    "output": output, "latencies": [round(l, 1) for l in latencies]}

        elif body.tool == "port":
            if body.port <= 0:
                return {"status": "error", "message": "Port required for port check"}
            start = _time.perf_counter()
            try:
                s = socket.create_connection((body.target, body.port), timeout=3)
                elapsed = (_time.perf_counter() - start) * 1000
                s.close()
                output = f"Port {body.port} on {body.target}: OPEN\nConnected in {elapsed:.1f}ms"
                return {"status": "ok", "tool": "port", "target": body.target,
                        "port": body.port, "reachable": True, "output": output,
                        "elapsed_ms": round(elapsed, 1)}
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                elapsed = (_time.perf_counter() - start) * 1000
                output = f"Port {body.port} on {body.target}: CLOSED/FILTERED\n{type(e).__name__}: {e}"
                return {"status": "ok", "tool": "port", "target": body.target,
                        "port": body.port, "reachable": False, "output": output,
                        "elapsed_ms": round(elapsed, 1)}

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "message": str(exc)[:500]}


# ---------------------------------------------------------------------------
# POST /api/admin/tools/syslog-test
# ---------------------------------------------------------------------------

@tools_router.post("/tools/syslog-test", summary="Compose and optionally send syslog events")
async def syslog_test(body: SyslogTestRequest):
    """Compose syslog events in RFC 3164/5424/HEC format and optionally send them."""
    import time as _time
    import json as _json
    import re as _re
    from datetime import datetime

    pri = body.facility * 8 + body.severity
    pid = body.pid or os.getpid()
    now = datetime.now()

    if body.format == "rfc3164":
        timestamp = now.strftime("%b %d %H:%M:%S")
        event = f"<{pri}>{timestamp} {body.hostname} {body.app_name}[{pid}]: {body.message}"
    elif body.format == "rfc5424":
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        event = f"<{pri}>1 {timestamp} {body.hostname} {body.app_name} {pid} - - {body.message}"
    else:  # hec
        event = _json.dumps({
            "event": body.message, "host": body.hostname,
            "source": body.app_name, "sourcetype": "syslog", "time": _time.time()
        })

    result = {"status": "ok", "format": body.format, "event": event,
              "priority": pri, "facility": body.facility, "severity": body.severity, "sent": False}

    if body.send and body.target:
        if not _re.match(r'^[a-zA-Z0-9._:\-\[\]]+$', body.target):
            return {"status": "error", "message": "Invalid target hostname"}

        def _send_syslog_sync(target, port, protocol, event_bytes):
            if protocol == "udp":
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(3)
                sock.sendto(event_bytes, (target, port))
                sock.close()
            else:
                sock = socket.create_connection((target, port), timeout=3)
                sock.sendall(event_bytes + b'\n')
                sock.close()

        try:
            await asyncio.to_thread(_send_syslog_sync, body.target, body.port, body.protocol, event.encode('utf-8'))
            result["sent"] = True
            result["send_target"] = f"{body.target}:{body.port}/{body.protocol}"
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            result["send_error"] = str(exc)[:300]

    return result


# ---------------------------------------------------------------------------
# POST /api/admin/tools/regex-ai
# ---------------------------------------------------------------------------

@tools_router.post("/tools/regex-ai", summary="AI-powered regex assessment and suggestions")
async def regex_ai(body: RegexAIRequest):
    """Use LLM to assess regex pattern quality and suggest improvements."""
    import re as _re

    suggestions = []
    warnings = []
    pattern = body.pattern

    if _re.search(r'\.\*.*\.\*', pattern):
        warnings.append("Multiple .* can cause catastrophic backtracking -- consider more specific patterns")
    if _re.search(r'\(.*\+\).*\+', pattern):
        warnings.append("Nested quantifiers detected -- potential exponential time complexity")
    if _re.search(r'\(\.\*\)', pattern):
        suggestions.append("Consider using (.*?) (lazy) instead of (.*) (greedy) for more precise captures")
    if _re.search(r'\\d\+', pattern) and not _re.search(r'\\d\{', pattern):
        suggestions.append("Consider using \\d{1,5} instead of \\d+ to set explicit bounds")
    if pattern.startswith('.*'):
        suggestions.append("Leading .* is unnecessary in findall/search -- regex engine already scans the string")
    if '(?:' not in pattern and pattern.count('(') > 3:
        suggestions.append("Consider using (?:...) for non-capturing groups to improve performance")
    if _re.search(r'\[[^\]]*[a-z]-[A-Z]|[A-Z]-[a-z]', pattern):
        warnings.append("Mixed-case range in character class -- verify intended range")
    if len(pattern) > 200:
        suggestions.append("Very long pattern -- consider breaking into named sub-patterns for readability")

    try:
        compiled = _re.compile(pattern)
        groups = compiled.groupindex
        num_groups = compiled.groups
    except _re.error as e:
        return {"status": "error", "message": f"Invalid regex: {e}"}

    optimized = None
    if '.*' in pattern and '.*?' not in pattern:
        optimized = pattern.replace('.*', '.*?')
        suggestions.append(f"Lazy version: {optimized}")

    splunk_suggestions = []
    if '\\d+\\.\\d+\\.\\d+\\.\\d+' in pattern:
        splunk_suggestions.append("Splunk rex: | rex field=_raw \"(?P<ip>\\d+\\.\\d+\\.\\d+\\.\\d+)\"")
    if '(?P<' in pattern:
        groups_list = list(compiled.groupindex.keys())
        if groups_list:
            field_refs = " ".join(groups_list)
            splunk_suggestions.append(f"Use captured fields in SPL: | table {field_refs}")

    ai_assessment = None
    try:
        _s = get_settings()
        import httpx as _httpx
        prompt = f"Assess this regex pattern briefly (3-5 bullets):\nPattern: {pattern}\n"
        if body.description:
            prompt += f"Intent: {body.description}\n"
        if body.sample_text:
            prompt += f"Sample: {body.sample_text[:500]}\n"
        prompt += (
            "Provide:\n1. What it matches (one line)\n2. Performance assessment (backtracking risk?)\n"
            "3. One optimized alternative if possible\n4. Splunk rex/regex usage example\nKeep it concise."
        )
        async with _httpx.AsyncClient(timeout=_httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)) as _hc:
            _resp = await _hc.post(
                f"{_s.ollama.base_url}/api/generate",
                json={"model": _s.ollama.model, "prompt": prompt, "stream": False,
                      "options": {"temperature": 0.1, "num_predict": 300}},
            )
            ai_assessment = _resp.json().get("response", "")
    except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
        logger.warning("[TOOLS] AI regex assessment unavailable: %s: %s", type(exc).__name__, exc)

    return {
        "status": "ok", "pattern": pattern, "valid": True, "num_groups": num_groups,
        "named_groups": list(groups.keys()) if groups else [], "suggestions": suggestions,
        "warnings": warnings, "splunk_suggestions": splunk_suggestions,
        "optimized": optimized, "ai_assessment": ai_assessment,
    }


# ---------------------------------------------------------------------------
# POST /api/admin/tools/regex-generate
# ---------------------------------------------------------------------------

@tools_router.post("/tools/regex-generate", summary="Generate regex from selected text using AI")
async def regex_generate(body: RegexGenerateRequest):
    """Given highlighted text and context, generate a regex pattern that matches it."""
    import re as _re

    selected = body.selected_text.strip()
    if not selected:
        return {"status": "error", "message": "No text selected"}

    full = body.full_text or ""
    sel_idx = full.find(selected)
    before_ctx = full[max(0, sel_idx - 60):sel_idx] if sel_idx >= 0 else ""

    if _re.match(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$', selected):
        val_pat = r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}'
    elif _re.match(r'^\d+$', selected):
        val_pat = r'\d+'
    elif _re.match(r'^\d+\.\d+$', selected):
        val_pat = r'\d+\.\d+'
    else:
        val_pat = r'\S+'

    kv_m = _re.search(r'(\w[\w.-]*)[\s]*=[\s]*"?$', before_ctx)
    colon_m = _re.search(r'(\w[\w.-]*)[\s]*:[\s]+$', before_ctx)
    if kv_m:
        key = kv_m.group(1)
        literal_pattern = f'{key}=(?P<{key}>{val_pat})'
    elif colon_m:
        key = colon_m.group(1)
        literal_pattern = f'{key}:\\s+(?P<{key}>{val_pat})'
    elif before_ctx.rstrip().endswith((',', '|', '\t')):
        literal_pattern = f'(?P<value>{val_pat})'
    else:
        literal_pattern = f'(?<=\\s)(?P<value>{val_pat})(?=\\s|$)'

    ai_pattern = None
    ai_explanation = None
    try:
        _s = get_settings()
        import httpx as _httpx
        context_snippet = body.full_text[:1000] if body.full_text else ""
        prompt = f"Generate an ANCHORED Python regex pattern that captures text like this:\nSelected text: \"{selected}\"\n"
        if context_snippet:
            prompt += f"Full log context:\n{context_snippet}\n"
        if body.description:
            prompt += f"User hint: {body.description}\n"
        prompt += (
            "\nCritical requirements:\n"
            "- The regex MUST be anchored to surrounding context (key=, prefix, delimiter, start of line)\n"
            "- NEVER match a bare literal string -- always include what comes before/after as anchor\n"
            "- Look at what precedes the selected text: is it key=value, key: value, after a comma, at line start?\n"
            "- Use named capture groups (?P<name>...) for the captured value\n"
            "- Name the group after the key/field if one exists (e.g., src_ip=... -> (?P<src_ip>...))\n"
            "- Pattern should generalize to match similar values, not just the exact literal\n"
            "- Return ONLY the regex pattern on the first line\n"
            "- Then one line explaining the anchor and what it captures\n"
        )
        async with _httpx.AsyncClient(timeout=_httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)) as _hc:
            _resp = await _hc.post(
                f"{_s.ollama.base_url}/api/generate",
                json={"model": _s.ollama.model, "prompt": prompt, "stream": False,
                      "options": {"temperature": 0.1, "num_predict": 200}},
            )
            answer = _resp.json().get("response", "")
        lines = answer.strip().split('\n')
        for line in lines:
            line = line.strip().strip('`').strip()
            if line and not line.startswith('#') and not line.lower().startswith('explanation'):
                try:
                    _re.compile(line)
                    ai_pattern = line
                    ai_explanation = '\n'.join(l for l in lines if l.strip() != line).strip()
                    break
                except _re.error:
                    continue
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[TOOLS] AI regex generation unavailable: %s", exc)

    pattern = ai_pattern or literal_pattern
    group_idx = [0]

    def _to_named(m):
        group_idx[0] += 1
        return f'(?P<field{group_idx[0]}>'

    rex_pattern = _re.sub(r'\((?!\?)', lambda m: _to_named(m), pattern)
    rex_command = f'| rex field=_raw "{rex_pattern}"'

    return {
        "status": "ok", "pattern": pattern, "literal_pattern": literal_pattern,
        "ai_generated": ai_pattern is not None,
        "explanation": ai_explanation or f"Matches: {selected}",
        "rex_command": rex_command,
    }


# ---------------------------------------------------------------------------
# POST /api/admin/tools/fs-monitor
# ---------------------------------------------------------------------------

@tools_router.post("/tools/fs-monitor", summary="Monitor filesystem paths")
async def fs_monitor(body: FSMonitorRequest):
    """List files matching a path/pattern with metadata, optionally generate inputs.conf."""
    import glob as _glob
    import stat
    from datetime import datetime

    if body.pattern.startswith('/') or '..' in body.pattern:
        return {"status": "error", "message": "Invalid pattern -- no absolute paths or '..' allowed"}

    clean_path = os.path.normpath(body.path)
    if '..' in clean_path or not os.path.isabs(clean_path):
        return {"status": "error", "message": "Path must be absolute with no '..' traversal"}

    search_path = os.path.join(clean_path, body.pattern)
    if not os.path.normpath(search_path).startswith(clean_path):
        return {"status": "error", "message": "Pattern resolves outside base path"}

    def _scan_files_sync(search_path_, max_files_):
        matched = sorted(_glob.glob(search_path_, recursive=True))[:max_files_]
        files_ = []
        total_ = 0
        for fpath in matched:
            try:
                st = os.stat(fpath)
                is_dir = stat.S_ISDIR(st.st_mode)
                size = st.st_size if not is_dir else 0
                total_ += size
                files_.append({
                    "path": fpath, "name": os.path.basename(fpath), "size": size,
                    "size_human": _human_size(size),
                    "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                    "is_dir": is_dir, "permissions": stat.filemode(st.st_mode),
                })
            except (OSError, PermissionError) as e:
                files_.append({"path": fpath, "name": os.path.basename(fpath), "error": str(e)})
        return files_, total_

    try:
        files, total_size = await asyncio.to_thread(_scan_files_sync, search_path, body.max_files)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        return {"status": "error", "message": f"Glob error: {e}"}

    result = {
        "status": "ok", "path": clean_path, "pattern": body.pattern,
        "file_count": len(files), "total_size": total_size,
        "total_size_human": _human_size(total_size), "files": files,
    }

    if body.generate_inputs_conf:
        stanzas = []
        dirs_seen = set()
        for f in files:
            if f.get("is_dir"):
                continue
            d = os.path.dirname(f["path"])
            if d in dirs_seen:
                continue
            dirs_seen.add(d)
            ext = os.path.splitext(f["path"])[1].lstrip('.')
            st_map = {'log': 'syslog', 'json': '_json', 'csv': 'csv', 'xml': 'XmlWinEventLog', 'conf': 'splunk_conf'}
            sourcetype = st_map.get(ext, 'auto')
            stanza = f"[monitor://{d}]\ndisabled = false\nsourcetype = {sourcetype}\nindex = main\n"
            if body.pattern != "*":
                stanza += f"whitelist = {body.pattern}\n"
            stanzas.append(stanza)
        result["inputs_conf"] = "\n".join(stanzas)

    return result


# ---------------------------------------------------------------------------
# POST /api/admin/tools/ai-chat
# ---------------------------------------------------------------------------

@tools_router.post("/tools/ai-chat", summary="AI assistant for tools pages")
async def tools_ai_chat(body: ToolsAIChatRequest):
    """Context-aware AI assistant for any tools page."""
    page_prompts = {
        "network": (
            "You are helping with Splunk network diagnostics. "
            "Topics: DNS lookup, port checking, connectivity testing, "
            "firewall rules, network troubleshooting, Splunk forwarder connectivity."
        ),
        "syslog": (
            "You are helping with syslog and event testing for Splunk. "
            "Topics: syslog format (RFC 3164/5424), UDP/TCP syslog forwarding, "
            "event generation, HEC (HTTP Event Collector), props.conf/transforms.conf."
        ),
        "monitor": (
            "You are helping with Splunk file monitoring configuration. "
            "Topics: inputs.conf monitor stanzas, file rotation, whitelists/blacklists, "
            "recursive monitoring, sourcetype assignment, index routing."
        ),
        "spl": (
            "You are a Splunk SPL expert helping with search queries. "
            "Topics: SPL syntax, command reference, optimization, data models, "
            "tstats, eval functions, stats aggregations, subsearches, macros."
        ),
        "regex": (
            "You are helping with regex patterns for Splunk. "
            "Topics: rex command, regex field extraction, named groups, "
            "props.conf EXTRACT, transforms.conf REGEX, performance optimization."
        ),
        "slash": (
            "You are helping with ObsAI slash commands and features. "
            "Topics: available commands (/help, /search, /config, /health, /spec, etc.), "
            "configuration, profiles, admin console."
        ),
        "transform": (
            "You are helping with data transformation operations (CyberChef-like). "
            "Topics: encoding/decoding (base64, URL, hex), hashing, JSON/CSV parsing, "
            "text manipulation, chained operations, Splunk field extraction."
        ),
        "confsim": (
            "You are helping with Splunk props.conf and transforms.conf configuration. "
            "Topics: LINE_BREAKER, BREAK_ONLY_BEFORE, TIME_FORMAT, TIME_PREFIX, "
            "EXTRACT-, REPORT-, TRANSFORMS, field extraction, event breaking, sourcetype config."
        ),
        "json": (
            "You are helping with JSON data manipulation and conversion. "
            "Topics: JSON formatting, JSONPath queries, CSV/JSON/NDJSON conversion, "
            "JSON validation, flattening/unflattening, data transformation."
        ),
        "ansible": (
            "You are an Ansible automation expert. "
            "Topics: playbook writing, YAML syntax, modules (copy, template, service, apt, yum, "
            "docker_container, user, cron, etc.), roles, handlers, variables, Jinja2 templates, "
            "inventory management, best practices, idempotency, error handling."
        ),
        "shell": (
            "You are a shell scripting expert (Bash/POSIX). "
            "Topics: script structure, set -euo pipefail, error handling, traps, getopts, "
            "parameter expansion, process substitution, quoting rules, awk/sed, "
            "cron jobs, service scripts, deployment automation."
        ),
        "python": (
            "You are a Python development expert. "
            "Topics: script structure, argparse, logging, type hints, dataclasses, "
            "async/await, FastAPI, pytest, pathlib, context managers, decorators, "
            "packaging, virtual environments, best practices."
        ),
    }

    system_prompt = (
        "You are a Splunk expert assistant embedded in the ObsAI tools page. "
        + page_prompts.get(body.page, "Answer concisely about Splunk administration.")
        + " Keep responses concise and practical. Use code blocks for SPL or config examples."
    )

    try:
        _s = get_settings()
        import httpx
        prompt = body.question
        if body.context:
            prompt = f"Context from the page:\n{body.context[:2000]}\n\nUser question: {body.question}"

        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)) as client:
            resp = await client.post(
                f"{_s.ollama.base_url}/api/chat",
                json={
                    "model": _s.ollama.model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.3, "num_predict": 500},
                },
            )
            data = resp.json()
            answer = data.get("message", {}).get("content", data.get("response", "No response"))

        return {"status": "ok", "answer": answer, "page": body.page}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[TOOLS] AI chat error: %s: %s", type(exc).__name__, exc)
        return {"status": "error", "answer": f"AI unavailable: {type(exc).__name__}: {exc}", "page": body.page}


# ---------------------------------------------------------------------------
# POST /api/admin/tools/transform-ai
# ---------------------------------------------------------------------------

@tools_router.post("/tools/transform-ai", summary="AI suggest data transformation chain")
async def transform_ai_suggest(body: TransformAIRequest):
    """Given raw data and optional goal, suggest a chain of transform operations."""
    try:
        _s = get_settings()
        import httpx
        prompt = (
            f"Analyze this data and suggest a chain of transformation operations.\n"
            f"Data (first 500 chars): {body.data[:500]}\n"
        )
        if body.goal:
            prompt += f"Goal: {body.goal}\n"
        prompt += (
            "\nAvailable operations: base64_encode, base64_decode, url_encode, url_decode, "
            "hex_encode, hex_decode, html_encode, html_decode, md5, sha1, sha256, "
            "json_parse, json_prettify, json_minify, csv_parse, kv_parse, xml_parse, "
            "upper, lower, reverse, trim, line_sort, unique_lines, remove_empty, "
            "rex_extract, spl_escape, quote_values\n\n"
            "Return a JSON array of operation names in order, then a brief explanation.\n"
            "Format:\n[\"op1\", \"op2\", ...]\nExplanation text here"
        )
        async with httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)) as client:
            resp = await client.post(
                f"{_s.ollama.base_url}/api/generate",
                json={"model": _s.ollama.model, "prompt": prompt, "stream": False,
                      "options": {"temperature": 0.2, "num_predict": 300}},
            )
            data = resp.json()
            answer = data.get("response", "")
        import json as _json
        lines = answer.strip().split('\n')
        ops = []
        explanation = answer
        for line in lines:
            line = line.strip()
            if line.startswith('['):
                try:
                    ops = _json.loads(line)
                    explanation = '\n'.join(l for l in lines if l.strip() != line).strip()
                    break
                except _json.JSONDecodeError:
                    pass
        return {"status": "ok", "operations": ops, "explanation": explanation}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[TOOLS] Transform AI error: %s: %s", type(exc).__name__, exc)
        return {"status": "error", "operations": [], "explanation": f"AI unavailable: {type(exc).__name__}: {exc}"}
