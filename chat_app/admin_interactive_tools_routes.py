"""Admin sub-router: Interactive tools (public, no auth required).

Handles these endpoint groups:
- POST /api/admin/tools/regex-test       — Test regex pattern
- POST /api/admin/tools/conf-simulate    — Simulate Splunk props/transforms
- POST /api/admin/tools/jsonpath         — Evaluate JSONPath expression
- POST /api/admin/tools/json-convert     — Convert between JSON/CSV/NDJSON
- POST /api/admin/tools/log-analyze      — Auto-detect fields in raw log
- POST /api/admin/tools/spl-performance  — SPL query performance estimator
- POST /api/admin/tools/conf-validate    — Validate Splunk conf syntax
- POST /api/admin/tools/cim-map          — Map log fields to CIM model
- POST /api/admin/execute-command        — Execute slash command programmatically
- GET  /api/admin/spec-files             — List .conf.spec files
- GET  /api/admin/spec-files/{name}      — Get parsed spec file content

Mount with:
    from chat_app.admin_interactive_tools_routes import interactive_tools_public_router, interactive_tools_router
"""

import asyncio
import logging
from datetime import datetime as _dt

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from chat_app.auth_dependencies import require_admin
from chat_app.admin_shared import (
    _csrf_check,
    _rate_limit,
    _track_audit_user,
)

logger = logging.getLogger(__name__)

# Interactive tools — require at least authenticated user (security hardening)
# Previously public; now gated behind require_any_authenticated to prevent abuse.
from chat_app.auth_dependencies import require_any_authenticated
interactive_tools_public_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-interactive-tools"],
    dependencies=[Depends(_rate_limit), Depends(require_any_authenticated), Depends(_csrf_check)],
)

# Authenticated endpoints
interactive_tools_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-interactive-tools"],
    dependencies=[Depends(_rate_limit), Depends(require_admin), Depends(_track_audit_user), Depends(_csrf_check)],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class RegexTestRequest(BaseModel):
    pattern: str = Field(..., min_length=1, max_length=500)
    test_text: str = Field(..., max_length=10000)
    flags: str = Field(default="", max_length=20)


class ConfSimulateRequest(BaseModel):
    props_conf: str = Field(..., min_length=1, max_length=20000)
    transforms_conf: str = Field(default="", max_length=20000)
    raw_data: str = Field(..., min_length=1, max_length=50000)
    stanza_name: str = Field(default="", max_length=200)


class JSONPathRequest(BaseModel):
    json_data: str = Field(..., min_length=1, max_length=100000)
    path: str = Field(..., min_length=1, max_length=500)


class JSONConvertRequest(BaseModel):
    data: str = Field(..., min_length=1, max_length=100000)
    from_format: str = Field(default="json", pattern=r"^(json|csv|ndjson)$")
    to_format: str = Field(default="csv", pattern=r"^(json|csv|ndjson)$")


class LogAnalyzeRequest(BaseModel):
    raw_log: str = Field(..., min_length=1, max_length=50000)


class SPLPerformanceRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=10000)


class ConfValidateRequest(BaseModel):
    conf_content: str = Field(..., min_length=1, max_length=50000)
    conf_type: str = Field(default="props", pattern=r"^(props|transforms|inputs|outputs)$")


class CIMMapRequest(BaseModel):
    sample_log: str = Field(..., min_length=1, max_length=10000)
    model: str = Field(default="", max_length=100)


# ---------------------------------------------------------------------------
# POST /tools/regex-test
# ---------------------------------------------------------------------------

@interactive_tools_public_router.post("/tools/regex-test", summary="Test regex pattern against text")
async def regex_test(body: RegexTestRequest):
    """Test a regex pattern against sample text, returning matches and performance."""
    import re as _re
    import time as _time

    if len(body.pattern) > 500:
        raise HTTPException(status_code=413, detail="Pattern too long (max 500 chars)")
    if len(body.test_text) > 10000:
        raise HTTPException(status_code=413, detail="Input text too large (max 10000 chars)")

    py_flags = 0
    if "i" in body.flags:
        py_flags |= _re.IGNORECASE
    if "m" in body.flags:
        py_flags |= _re.MULTILINE
    if "s" in body.flags:
        py_flags |= _re.DOTALL

    def _run_regex():
        test_text = body.test_text[:10000]
        start = _time.perf_counter()
        compiled = _re.compile(body.pattern, py_flags)
        matches = []
        for m in compiled.finditer(test_text):
            groups = {}
            for i, g in enumerate(m.groups(), 1):
                groups[f"group_{i}"] = g
            if m.groupdict():
                groups.update(m.groupdict())
            matches.append({
                "match": m.group(0),
                "start": m.start(),
                "end": m.end(),
                "groups": groups,
            })
            if len(matches) >= 500:
                break
        elapsed_us = int((_time.perf_counter() - start) * 1_000_000)
        return matches, elapsed_us

    try:
        try:
            matches, elapsed_us = await asyncio.wait_for(
                asyncio.to_thread(_run_regex), timeout=2.0,
            )
        except asyncio.TimeoutError:
            raise HTTPException(status_code=408, detail="Regex execution timed out (possible ReDoS)")

        cost = "low"
        if elapsed_us > 10000:
            cost = "high"
        elif elapsed_us > 1000:
            cost = "medium"

        warnings = []
        if _re.search(r"\.\*.*\.\*", body.pattern):
            warnings.append("Multiple .* can cause catastrophic backtracking")
        if _re.search(r"\(.*\+\).*\+", body.pattern):
            warnings.append("Nested quantifiers may cause exponential time")
        if _re.search(r"\(\.\*\)", body.pattern):
            warnings.append("Greedy .* in capture group — consider .*? (lazy)")

        return {
            "status": "ok",
            "matches": matches,
            "match_count": len(matches),
            "elapsed_us": elapsed_us,
            "cost": cost,
            "warnings": warnings,
        }
    except HTTPException:
        raise
    except _re.error as e:
        return {"status": "error", "message": f"Invalid regex: {e}"}


# ---------------------------------------------------------------------------
# POST /tools/conf-simulate
# ---------------------------------------------------------------------------

@interactive_tools_public_router.post("/tools/conf-simulate", summary="Simulate Splunk props/transforms on raw data")
async def conf_simulate(body: ConfSimulateRequest):
    """Simulate how Splunk would process raw data with given props.conf and transforms.conf."""
    import re as _re

    _field_colors = [
        "#6c8cff", "#34d399", "#fbbf24", "#f97316", "#a78bfa",
        "#06b6d4", "#ec4899", "#ef4444", "#84cc16", "#14b8a6",
        "#e879f9", "#fb923c", "#38bdf8", "#a3e635", "#c084fc",
    ]

    try:
        from shared.conf_parser import parse_conf_file_advanced
        props = parse_conf_file_advanced(body.props_conf, "props.conf")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "message": f"Failed to parse props.conf: {exc}"}

    transforms = {}
    if body.transforms_conf.strip():
        try:
            from shared.conf_parser import parse_conf_file_advanced as _parse
            transforms = _parse(body.transforms_conf, "transforms.conf")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("[%s] %%s", "admin_interactive_tools_routes.py", _exc)

    stanza_name = body.stanza_name.strip()
    if not stanza_name:
        for k in props:
            if k.lower() != "default":
                stanza_name = k
                break
        if not stanza_name and props:
            stanza_name = next(iter(props))

    if stanza_name not in props:
        return {"status": "error", "message": f"Stanza [{stanza_name}] not found in props.conf",
                "available_stanzas": list(props.keys())}

    stanza = props[stanza_name]
    stanza_clean = {k: v for k, v in stanza.items() if not k.startswith('__')}
    warnings = []

    # Event Breaking
    line_breaker = stanza_clean.get("LINE_BREAKER", r"([\r\n]+)")
    break_only_before = stanza_clean.get("BREAK_ONLY_BEFORE")
    raw = body.raw_data
    line_break_positions = []

    try:
        if break_only_before:
            parts = _re.split(f"(?={break_only_before})", raw)
            parts = [p for p in parts if p.strip()]
        else:
            parts = _re.split(line_breaker, raw)
            merged = []
            i = 0
            while i < len(parts):
                merged.append(parts[i])
                if i + 1 < len(parts):
                    line_break_positions.append({"separator": parts[i + 1]})
                i += 2
            parts = [p for p in merged if p.strip()]
    except _re.error as exc:
        warnings.append(f"LINE_BREAKER regex error: {exc}")
        parts = raw.split('\n')
        parts = [p for p in parts if p.strip()]

    time_format = stanza_clean.get("TIME_FORMAT", "")
    time_prefix = stanza_clean.get("TIME_PREFIX", "")

    extract_rules = {}
    for key, val in stanza_clean.items():
        if key.startswith("EXTRACT-"):
            rule_name = key.replace("EXTRACT-", "")
            extract_rules[rule_name] = val
        elif key.startswith("REPORT-"):
            rule_name = key.replace("REPORT-", "")
            transform_names = [t.strip() for t in val.split(",")]
            for tn in transform_names:
                if tn in transforms:
                    t_stanza = transforms[tn]
                    regex = t_stanza.get("REGEX", "")
                    if regex:
                        extract_rules[f"{rule_name}:{tn}"] = regex

    color_idx = 0
    field_color_map = {}
    events = []
    for idx, event_raw in enumerate(parts[:50]):
        event_data = {"raw": event_raw, "index": idx, "fields": {}, "time_parsed": None, "time_error": None}

        if time_format:
            try:
                search_text = event_raw
                if time_prefix:
                    tp_m = _re.search(time_prefix, event_raw)
                    if tp_m:
                        search_text = event_raw[tp_m.end():]
                py_fmt = time_format
                try:
                    parsed_time = _dt.strptime(search_text[:len(time_format) + 20].strip(), py_fmt)
                    if '%Y' not in py_fmt and '%y' not in py_fmt and parsed_time.year == 1900:
                        parsed_time = parsed_time.replace(year=_dt.now().year)
                    event_data["time_parsed"] = parsed_time.isoformat()
                except ValueError:
                    for trim_len in range(min(50, len(search_text)), 5, -1):
                        try:
                            parsed_time = _dt.strptime(search_text[:trim_len].strip(), py_fmt)
                            if '%Y' not in py_fmt and '%y' not in py_fmt and parsed_time.year == 1900:
                                parsed_time = parsed_time.replace(year=_dt.now().year)
                            event_data["time_parsed"] = parsed_time.isoformat()
                            break
                        except ValueError:
                            continue
                    if not event_data["time_parsed"]:
                        event_data["time_error"] = f"Could not parse with format: {time_format}"
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                event_data["time_error"] = str(exc)

        for rule_name, pattern in extract_rules.items():
            try:
                for m in _re.finditer(pattern, event_raw):
                    groups = m.groupdict()
                    if not groups:
                        for gi, gv in enumerate(m.groups(), 1):
                            if gv is not None:
                                fname = f"{rule_name}_field{gi}"
                                if fname not in field_color_map:
                                    field_color_map[fname] = _field_colors[color_idx % len(_field_colors)]
                                    color_idx += 1
                                event_data["fields"][fname] = {
                                    "value": gv, "start": m.start(gi), "end": m.end(gi),
                                    "color": field_color_map[fname], "rule": rule_name,
                                }
                    else:
                        for gname, gval in groups.items():
                            if gval is not None:
                                if gname not in field_color_map:
                                    field_color_map[gname] = _field_colors[color_idx % len(_field_colors)]
                                    color_idx += 1
                                event_data["fields"][gname] = {
                                    "value": gval, "start": m.start(gname), "end": m.end(gname),
                                    "color": field_color_map[gname], "rule": rule_name,
                                }
            except _re.error as exc:
                warnings.append(f"Regex error in {rule_name}: {exc}")

        events.append(event_data)

    return {
        "status": "ok",
        "stanza": stanza_name,
        "event_count": len(events),
        "events": events,
        "line_breaks": line_break_positions[:20],
        "settings": stanza_clean,
        "extract_rules": {k: v for k, v in extract_rules.items()},
        "field_colors": field_color_map,
        "warnings": warnings,
    }


# ---------------------------------------------------------------------------
# POST /tools/jsonpath
# ---------------------------------------------------------------------------

@interactive_tools_public_router.post("/tools/jsonpath", summary="Evaluate JSONPath expression")
async def jsonpath_evaluate(body: JSONPathRequest):
    """Parse JSON and evaluate a JSONPath-like expression."""
    import json as _json
    import re as _re

    try:
        data = _json.loads(body.json_data)
    except _json.JSONDecodeError as exc:
        return {"status": "error", "message": f"Invalid JSON: {exc}"}

    path = body.path.strip()
    if path.startswith('$'):
        path = path[1:]
    if path.startswith('.'):
        path = path[1:]

    def _navigate(obj, parts):
        if not parts:
            return [obj]
        part = parts[0]
        rest = parts[1:]

        if part == '[*]' or part == '*':
            if isinstance(obj, list):
                results = []
                for item in obj:
                    results.extend(_navigate(item, rest))
                return results
            elif isinstance(obj, dict):
                results = []
                for v in obj.values():
                    results.extend(_navigate(v, rest))
                return results
            return []

        idx_m = _re.match(r'^\[(\d+)\]$', part)
        if idx_m:
            idx = int(idx_m.group(1))
            if isinstance(obj, list) and 0 <= idx < len(obj):
                return _navigate(obj[idx], rest)
            return []

        if isinstance(obj, dict) and part in obj:
            return _navigate(obj[part], rest)

        return []

    parts = []
    for segment in _re.split(r'\.(?![^\[]*\])', path):
        if not segment:
            continue
        sub = _re.findall(r'([^\[\]]+|\[\d+\]|\[\*\])', segment)
        parts.extend(sub)

    try:
        matches = _navigate(data, parts)
        return {
            "status": "ok",
            "matches": matches[:100],
            "count": len(matches),
            "path": body.path,
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "message": f"Path evaluation error: {exc}"}


# ---------------------------------------------------------------------------
# POST /tools/json-convert
# ---------------------------------------------------------------------------

@interactive_tools_public_router.post("/tools/json-convert", summary="Convert between JSON, CSV, NDJSON")
async def json_convert(body: JSONConvertRequest):
    """Convert data between JSON, CSV, and NDJSON formats."""
    import json as _json
    import csv as _csv
    import io as _io

    records = []

    try:
        if body.from_format == "json":
            parsed = _json.loads(body.data)
            if isinstance(parsed, list):
                records = parsed
            elif isinstance(parsed, dict):
                records = [parsed]
            else:
                return {"status": "error", "message": "JSON must be an object or array of objects"}
        elif body.from_format == "csv":
            reader = _csv.DictReader(_io.StringIO(body.data))
            records = list(reader)
        elif body.from_format == "ndjson":
            for line in body.data.strip().split('\n'):
                line = line.strip()
                if line:
                    records.append(_json.loads(line))
    except (OSError, ValueError, KeyError, TypeError, _json.JSONDecodeError) as exc:
        return {"status": "error", "message": f"Parse error ({body.from_format}): {exc}"}

    if not records:
        return {"status": "error", "message": "No records found in input"}

    try:
        if body.to_format == "json":
            result = _json.dumps(records, indent=2, default=str)
        elif body.to_format == "csv":
            def _flatten(obj, prefix=""):
                flat = {}
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        key = f"{prefix}.{k}" if prefix else k
                        if isinstance(v, dict):
                            flat.update(_flatten(v, key))
                        elif isinstance(v, list):
                            if v and isinstance(v[0], dict):
                                for i, item in enumerate(v):
                                    flat.update(_flatten(item, f"{key}[{i}]"))
                            else:
                                flat[key] = "|".join(str(x) for x in v)
                        else:
                            flat[key] = v
                else:
                    flat[prefix or "value"] = obj
                return flat

            flat_records = [_flatten(r) if isinstance(r, dict) else {"value": r} for r in records]
            all_keys = []
            seen = set()
            for r in flat_records:
                if isinstance(r, dict):
                    for k in r.keys():
                        if k not in seen:
                            all_keys.append(k)
                            seen.add(k)
            output = _io.StringIO()
            writer = _csv.DictWriter(output, fieldnames=all_keys, extrasaction='ignore')
            writer.writeheader()
            for r in flat_records:
                if isinstance(r, dict):
                    writer.writerow({k: str(v) if v is not None else "" for k, v in r.items()})
            result = output.getvalue()
        elif body.to_format == "ndjson":
            lines = [_json.dumps(r, default=str) for r in records]
            result = '\n'.join(lines)
        else:
            return {"status": "error", "message": f"Unknown output format: {body.to_format}"}

        columns = []
        if records and isinstance(records[0], dict):
            columns = list(records[0].keys())

        return {
            "status": "ok",
            "result": result,
            "stats": {
                "rows": len(records),
                "columns": len(columns),
                "column_names": columns[:50],
            },
            "from_format": body.from_format,
            "to_format": body.to_format,
        }
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return {"status": "error", "message": f"Conversion error: {exc}"}



# ---------------------------------------------------------------------------
# Re-exports from admin_interactive_tools_data (log-analyze, spl-performance,
# conf-validate, cim-map, execute-command, spec-files) for backward compat.
# Importing this module triggers route registration on the shared routers.
# ---------------------------------------------------------------------------
import chat_app.admin_interactive_tools_data  # noqa: E402,F401 — side-effect: registers routes
from chat_app.admin_interactive_tools_data import (  # noqa: E402,F401
    log_analyze,
    spl_performance,
    conf_validate,
    cim_field_map,
    execute_command,
    list_spec_files,
    get_spec_file,
)
