"""Admin Tools Extended Routes — Network, Syslog, Regex, FS, and AI tool endpoints.

Extracted from admin_tools_routes.py to keep file sizes manageable.
Contains: network-test, syslog-test, regex-ai, regex-generate,
fs-monitor, ai-chat, transform-ai endpoints.
"""

import asyncio
import logging
import os
import re as _re_module
import socket

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from chat_app.auth_dependencies import require_admin
from chat_app.settings import get_settings
from chat_app.admin_shared import (
    _csrf_check,
    _human_size,
    _rate_limit,
    _track_audit_user,
)

logger = logging.getLogger(__name__)

tools_ext_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-tools"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class NetworkTestRequest(BaseModel):
    tool: str = Field(..., pattern="^(dns|ping|port)$")
    target: str = Field(..., min_length=1, max_length=255)
    port: int = Field(default=0, ge=0, le=65535)


class SyslogTestRequest(BaseModel):
    format: str = Field(default="rfc3164", pattern="^(rfc3164|rfc5424|hec)$")
    facility: int = Field(default=16, ge=0, le=23)
    severity: int = Field(default=6, ge=0, le=7)
    hostname: str = Field(default="testhost", max_length=255)
    app_name: str = Field(default="myapp", max_length=128)
    pid: int = Field(default=0, ge=0, le=99999)
    message: str = Field(..., min_length=1, max_length=10000)
    target: str = Field(default="", max_length=255)
    port: int = Field(default=514, ge=1, le=65535)
    protocol: str = Field(default="udp", pattern="^(udp|tcp)$")
    send: bool = Field(default=False)


class RegexAIRequest(BaseModel):
    pattern: str = Field(..., min_length=1, max_length=2000)
    description: str = Field(default="", max_length=500)
    sample_text: str = Field(default="", max_length=10000)


class RegexGenerateRequest(BaseModel):
    selected_text: str = Field(..., min_length=1, max_length=5000)
    full_text: str = Field(default="", max_length=50000)
    description: str = Field(default="", max_length=500)


class FSMonitorRequest(BaseModel):
    path: str = Field(default="/var/log", max_length=500)
    pattern: str = Field(default="*", max_length=200)
    max_files: int = Field(default=100, ge=1, le=500)
    generate_inputs_conf: bool = Field(default=False)


class ToolsAIChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000)
    context: str = Field(default="", max_length=5000)
    page: str = Field(default="general", max_length=50)


class TransformAIRequest(BaseModel):
    data: str = Field(..., min_length=1, max_length=10000)
    goal: str = Field(default="", max_length=500)


# ---------------------------------------------------------------------------
# Network / Syslog / Regex / FS / AI Tools
# ---------------------------------------------------------------------------

@tools_ext_router.post("/tools/network-test", summary="Run network diagnostic")
async def network_test(body: NetworkTestRequest):
    """Run DNS lookup, ping, or port check using Python-native tools."""
    import time as _time

    if not _re_module.match(r'^[a-zA-Z0-9._:\-\[\]]+$', body.target):
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
                output = f"DNS Lookup: {body.target}\nResolved in {elapsed}ms\n\nAddresses:\n" + "\n".join(f"  {ip} ({'/'.join(families)})" for ip in ips) + "\n\nReverse DNS:\n" + "\n".join(f"  {r}" for r in reverse)
                return {"status": "ok", "tool": "dns", "target": body.target, "output": output, "ips": ips, "elapsed_ms": elapsed}
            except socket.gaierror as e:
                return {"status": "error", "tool": "dns", "target": body.target, "output": f"DNS lookup failed: {e}", "ips": [], "message": str(e)}

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
            return {"status": "ok", "tool": "ping", "target": body.target, "output": output, "latencies": [round(l, 1) for l in latencies]}

        elif body.tool == "port":
            if body.port <= 0:
                return {"status": "error", "message": "Port required for port check"}
            start = _time.perf_counter()
            try:
                s = socket.create_connection((body.target, body.port), timeout=3)
                elapsed = (_time.perf_counter() - start) * 1000
                s.close()
                output = f"Port {body.port} on {body.target}: OPEN\nConnected in {elapsed:.1f}ms"
                return {"status": "ok", "tool": "port", "target": body.target, "port": body.port, "reachable": True, "output": output, "elapsed_ms": round(elapsed, 1)}
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
                elapsed = (_time.perf_counter() - start) * 1000
                output = f"Port {body.port} on {body.target}: CLOSED/FILTERED\n{type(e).__name__}: {e}"
                return {"status": "ok", "tool": "port", "target": body.target, "port": body.port, "reachable": False, "output": output, "elapsed_ms": round(elapsed, 1)}

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "message": str(exc)[:500]}


@tools_ext_router.post("/tools/syslog-test", summary="Compose and optionally send syslog events")
async def syslog_test(body: SyslogTestRequest):
    """Compose syslog events in RFC3164/5424/HEC format, optionally send."""
    import json as _json
    import time as _time

    pri = body.facility * 8 + body.severity
    pid = body.pid or os.getpid()
    now = datetime.now()

    if body.format == "rfc3164":
        timestamp = now.strftime("%b %d %H:%M:%S")
        event = f"<{pri}>{timestamp} {body.hostname} {body.app_name}[{pid}]: {body.message}"
    elif body.format == "rfc5424":
        timestamp = now.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        event = f"<{pri}>1 {timestamp} {body.hostname} {body.app_name} {pid} - - {body.message}"
    else:
        event = _json.dumps({
            "event": body.message, "host": body.hostname,
            "source": body.app_name, "sourcetype": "syslog", "time": _time.time()
        })

    result = {"status": "ok", "format": body.format, "event": event, "priority": pri, "facility": body.facility, "severity": body.severity, "sent": False}

    if body.send and body.target:
        if not _re_module.match(r'^[a-zA-Z0-9._:\-\[\]]+$', body.target):
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


@tools_ext_router.post("/tools/regex-ai", summary="AI-powered regex assessment and suggestions")
async def regex_ai(body: RegexAIRequest):
    """Use LLM to assess regex pattern quality and suggest improvements."""
    import re as _re
    suggestions = []
    warnings = []
    pattern = body.pattern

    if _re.search(r'\.\*.*\.\*', pattern):
        warnings.append("Multiple .* can cause catastrophic backtracking")
    if _re.search(r'\(.*\+\).*\+', pattern):
        warnings.append("Nested quantifiers detected -- potential exponential time complexity")
    if _re.search(r'\(\.\*\)', pattern):
        suggestions.append("Consider using (.*?) (lazy) instead of (.*) (greedy)")
    if _re.search(r'\\d\+', pattern) and not _re.search(r'\\d\{', pattern):
        suggestions.append("Consider using \\d{1,5} instead of \\d+ to set explicit bounds")
    if pattern.startswith('.*'):
        suggestions.append("Leading .* is unnecessary in findall/search")
    if '(?:' not in pattern and pattern.count('(') > 3:
        suggestions.append("Consider using (?:...) for non-capturing groups")
    if _re.search(r'\[[^\]]*[a-z]-[A-Z]|[A-Z]-[a-z]', pattern):
        warnings.append("Mixed-case range in character class")
    if len(pattern) > 200:
        suggestions.append("Very long pattern -- consider breaking into named sub-patterns")

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
        prompt += "Provide:\n1. What it matches\n2. Performance assessment\n3. One optimized alternative\n4. Splunk rex usage example\nKeep it concise."
        async with _httpx.AsyncClient(timeout=_httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)) as _hc:
            _resp = await _hc.post(
                f"{_s.ollama.base_url}/api/generate",
                json={"model": _s.ollama.model, "prompt": prompt, "stream": False, "options": {"temperature": 0.1, "num_predict": 300}},
            )
            ai_assessment = _resp.json().get("response", "")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[TOOLS] AI regex assessment unavailable: {type(exc).__name__}: {exc}")

    return {
        "status": "ok", "pattern": pattern, "valid": True,
        "num_groups": num_groups, "named_groups": list(groups.keys()) if groups else [],
        "suggestions": suggestions, "warnings": warnings,
        "splunk_suggestions": splunk_suggestions,
        "optimized": optimized, "ai_assessment": ai_assessment,
    }


@tools_ext_router.post("/tools/regex-generate", summary="Generate regex from selected text using AI")
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
        prompt += "\nCritical requirements:\n- MUST be anchored to surrounding context\n- Use named capture groups (?P<name>...)\n- Return ONLY the regex pattern on the first line\n- Then one line explaining\n"
        async with _httpx.AsyncClient(timeout=_httpx.Timeout(connect=10.0, read=300.0, write=10.0, pool=10.0)) as _hc:
            _resp = await _hc.post(
                f"{_s.ollama.base_url}/api/generate",
                json={"model": _s.ollama.model, "prompt": prompt, "stream": False, "options": {"temperature": 0.1, "num_predict": 200}},
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
        logger.debug(f"[TOOLS] AI regex generation unavailable: {exc}")

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


@tools_ext_router.post("/tools/fs-monitor", summary="Monitor filesystem paths")
async def fs_monitor(body: FSMonitorRequest):
    """List files matching a path/pattern with metadata, optionally generate inputs.conf."""
    import glob as _glob
    import stat

    if body.pattern.startswith('/') or '..' in body.pattern:
        return {"status": "error", "message": "Invalid pattern"}

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
                    "path": fpath, "name": os.path.basename(fpath),
                    "size": size, "size_human": _human_size(size),
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


@tools_ext_router.post("/tools/ai-chat", summary="AI assistant for tools pages")
async def tools_ai_chat(body: ToolsAIChatRequest):
    """Context-aware AI assistant for any tools page."""
    page_prompts = {
        "network": "You are helping with Splunk network diagnostics.",
        "syslog": "You are helping with syslog and event testing for Splunk.",
        "monitor": "You are helping with Splunk file monitoring configuration.",
        "spl": "You are a Splunk SPL expert helping with search queries.",
        "regex": "You are helping with regex patterns for Splunk.",
        "slash": "You are helping with ObsAI slash commands and features.",
        "transform": "You are helping with data transformation operations.",
        "confsim": "You are helping with Splunk props.conf and transforms.conf configuration.",
        "json": "You are helping with JSON data manipulation and conversion.",
        "ansible": "You are an Ansible automation expert.",
        "shell": "You are a shell scripting expert (Bash/POSIX).",
        "python": "You are a Python development expert.",
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
                    "options": {"temperature": 0.2, "num_predict": 150},
                },
            )
            data = resp.json()
            answer = data.get("message", {}).get("content", "")
            if not answer:
                answer = str(data)

        return {"status": "ok", "answer": answer, "page": body.page}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[TOOLS] AI chat error: {type(exc).__name__}: {exc}")
        return {"status": "error", "answer": f"AI assistant unavailable: {type(exc).__name__}: {exc}",
                "message": f"AI assistant unavailable: {type(exc).__name__}: {exc}", "page": body.page}


