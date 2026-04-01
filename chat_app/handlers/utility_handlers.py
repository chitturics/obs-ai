"""Utility handlers — encoding, hashing, data transform, text, validation, documentation.

Extracted from skill_executor.py for modularity. Each handler follows:
    def handler(user_input: str = "", **kwargs) -> str

Exports HANDLERS dict for auto-registration.
"""
# ── Batch 7: Utility handlers — encoding, hashing, data transform, text, validation ──

def _handler_base64_encode(user_input: str = "", **kwargs) -> str:
    import base64
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided. Usage: provide text to encode."
    return f"Base64 encoded:\n```\n{base64.b64encode(text.encode()).decode()}\n```"

def _handler_base64_decode(user_input: str = "", **kwargs) -> str:
    import base64
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided. Usage: provide base64 string to decode."
    try:
        return f"Decoded:\n```\n{base64.b64decode(text).decode()}\n```"
    except Exception as e:
        return f"Error decoding base64: {e}"

def _handler_url_encode(user_input: str = "", **kwargs) -> str:
    from urllib.parse import quote
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    return f"URL encoded:\n```\n{quote(text, safe='')}\n```"

def _handler_url_decode(user_input: str = "", **kwargs) -> str:
    from urllib.parse import unquote
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    return f"URL decoded:\n```\n{unquote(text)}\n```"

def _handler_hex_encode(user_input: str = "", **kwargs) -> str:
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    return f"Hex encoded:\n```\n{text.encode().hex()}\n```"

def _handler_hex_decode(user_input: str = "", **kwargs) -> str:
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    try:
        return f"Hex decoded:\n```\n{bytes.fromhex(text).decode()}\n```"
    except Exception as e:
        return f"Error decoding hex: {e}"

def _handler_html_encode(user_input: str = "", **kwargs) -> str:
    import html
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    return f"HTML encoded:\n```\n{html.escape(text)}\n```"

def _handler_html_decode(user_input: str = "", **kwargs) -> str:
    import html
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    return f"HTML decoded:\n```\n{html.unescape(text)}\n```"

def _handler_md5(user_input: str = "", **kwargs) -> str:
    import hashlib
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    return f"MD5 hash:\n```\n{hashlib.md5(text.encode()).hexdigest()}\n```"

def _handler_sha1(user_input: str = "", **kwargs) -> str:
    import hashlib
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    return f"SHA1 hash:\n```\n{hashlib.sha1(text.encode()).hexdigest()}\n```"

def _handler_sha256(user_input: str = "", **kwargs) -> str:
    import hashlib
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    return f"SHA256 hash:\n```\n{hashlib.sha256(text.encode()).hexdigest()}\n```"

def _handler_sha512(user_input: str = "", **kwargs) -> str:
    import hashlib
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    return f"SHA512 hash:\n```\n{hashlib.sha512(text.encode()).hexdigest()}\n```"

def _handler_json_prettify(user_input: str = "", **kwargs) -> str:
    import json
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No JSON input provided."
    try:
        data = json.loads(text)
        return f"Prettified JSON:\n```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```"
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON — {e}"

def _handler_json_minify(user_input: str = "", **kwargs) -> str:
    import json
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No JSON input provided."
    try:
        data = json.loads(text)
        return f"Minified JSON:\n```\n{json.dumps(data, separators=(',', ':'), ensure_ascii=False)}\n```"
    except json.JSONDecodeError as e:
        return f"Error: Invalid JSON — {e}"

def _handler_csv_to_json(user_input: str = "", **kwargs) -> str:
    import csv
    import json
    import io
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No CSV input provided."
    try:
        reader = csv.DictReader(io.StringIO(text))
        rows = list(reader)
        return f"JSON ({len(rows)} rows):\n```json\n{json.dumps(rows, indent=2, ensure_ascii=False)}\n```"
    except Exception as e:
        return f"Error parsing CSV: {e}"

def _handler_json_to_csv(user_input: str = "", **kwargs) -> str:
    import csv
    import json
    import io
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No JSON input provided."
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list) or not data:
            return "Error: JSON must be an array of objects."
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=data[0].keys())
        writer.writeheader()
        writer.writerows(data)
        return f"CSV ({len(data)} rows):\n```\n{output.getvalue()}\n```"
    except Exception as e:
        return f"Error converting to CSV: {e}"

def _handler_kv_parse(user_input: str = "", **kwargs) -> str:
    import json
    import re
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    pairs = re.findall(r'(\w+)\s*=\s*"([^"]*)"|\b(\w+)\s*=\s*(\S+)', text)
    result = {}
    for m in pairs:
        key = m[0] or m[2]
        val = m[1] or m[3]
        result[key] = val
    if not result:
        return "No key=value pairs found. Expected format: key1=value1 key2=\"value 2\""
    return f"Parsed key-value pairs:\n```json\n{json.dumps(result, indent=2)}\n```"

def _handler_xml_to_json(user_input: str = "", **kwargs) -> str:
    import json
    from xml.etree import ElementTree as ET
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No XML input provided."
    def _xml_to_dict(elem):
        result = {}
        if elem.attrib:
            result["@attributes"] = dict(elem.attrib)
        children = list(elem)
        if children:
            for child in children:
                child_data = _xml_to_dict(child)
                if child.tag in result:
                    if not isinstance(result[child.tag], list):
                        result[child.tag] = [result[child.tag]]
                    result[child.tag].append(child_data)
                else:
                    result[child.tag] = child_data
        elif elem.text and elem.text.strip():
            if result:
                result["#text"] = elem.text.strip()
            else:
                return elem.text.strip()
        return result
    try:
        root = ET.fromstring(text)
        data = {root.tag: _xml_to_dict(root)}
        return f"JSON from XML:\n```json\n{json.dumps(data, indent=2, ensure_ascii=False)}\n```"
    except ET.ParseError as e:
        return f"Error parsing XML: {e}"

def _handler_json_parse(user_input: str = "", **kwargs) -> str:
    import json
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    try:
        data = json.loads(text)
        type_name = type(data).__name__
        size = len(data) if isinstance(data, (list, dict)) else "N/A"
        pretty = json.dumps(data, indent=2, ensure_ascii=False)
        return f"Valid JSON ({type_name}, {size} items):\n```json\n{pretty}\n```"
    except json.JSONDecodeError as e:
        return f"Invalid JSON at line {e.lineno}, col {e.colno}: {e.msg}"

def _handler_csv_parse(user_input: str = "", **kwargs) -> str:
    import csv
    import io
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No CSV input provided."
    try:
        reader = csv.reader(io.StringIO(text))
        rows = list(reader)
        if not rows: return "Empty CSV."
        headers = rows[0]
        data_rows = rows[1:]
        lines = [f"Headers ({len(headers)}): {', '.join(headers)}",
                 f"Data rows: {len(data_rows)}"]
        for i, row in enumerate(data_rows[:5]):
            lines.append(f"  Row {i+1}: {dict(zip(headers, row))}")
        if len(data_rows) > 5:
            lines.append(f"  ... and {len(data_rows) - 5} more rows")
        return "CSV Structure:\n```\n" + "\n".join(lines) + "\n```"
    except Exception as e:
        return f"Error parsing CSV: {e}"

def _handler_text_upper(user_input: str = "", **kwargs) -> str:
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    return f"Uppercase:\n```\n{text.upper()}\n```"

def _handler_text_lower(user_input: str = "", **kwargs) -> str:
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    return f"Lowercase:\n```\n{text.lower()}\n```"

def _handler_text_reverse(user_input: str = "", **kwargs) -> str:
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    return f"Reversed:\n```\n{text[::-1]}\n```"

def _handler_text_trim(user_input: str = "", **kwargs) -> str:
    text = kwargs.get("input", user_input)
    if not text: return "Error: No input provided."
    lines = [line.strip() for line in text.splitlines()]
    return "Trimmed:\n```\n" + "\n".join(lines) + "\n```"

def _handler_line_sort(user_input: str = "", **kwargs) -> str:
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    lines = sorted(text.splitlines())
    return f"Sorted ({len(lines)} lines):\n```\n" + "\n".join(lines) + "\n```"

def _handler_unique_lines(user_input: str = "", **kwargs) -> str:
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    seen = set()
    unique = []
    for line in text.splitlines():
        if line not in seen:
            seen.add(line)
            unique.append(line)
    removed = len(text.splitlines()) - len(unique)
    return f"Unique lines ({removed} duplicates removed):\n```\n" + "\n".join(unique) + "\n```"

def _handler_remove_empty_lines(user_input: str = "", **kwargs) -> str:
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    lines = [l for l in text.splitlines() if l.strip()]
    removed = len(text.splitlines()) - len(lines)
    return f"Cleaned ({removed} empty lines removed):\n```\n" + "\n".join(lines) + "\n```"

def _handler_spl_escape(user_input: str = "", **kwargs) -> str:
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    escaped = text.replace('\\', '\\\\').replace('"', '\\"').replace("'", "\\'")
    for ch in ['|', '[', ']', '(', ')', '=', '!', '<', '>', '*', '?']:
        escaped = escaped.replace(ch, f'\\{ch}')
    return f"SPL escaped:\n```\n{escaped}\n```"

def _handler_quote_values(user_input: str = "", **kwargs) -> str:
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    import re
    def _quote(match):
        val = match.group(2)
        if not (val.startswith('"') and val.endswith('"')):
            val = f'"{val}"'
        return f'{match.group(1)}={val}'
    result = re.sub(r'(\w+)\s*=\s*([^\s,]+)', _quote, text)
    return f"Quoted values:\n```\n{result}\n```"

def _handler_rex_extract(user_input: str = "", **kwargs) -> str:
    import re
    pattern = kwargs.get("pattern", "")
    text = kwargs.get("input", user_input).strip()
    if not pattern:
        parts = text.split("|||", 1)
        if len(parts) == 2:
            pattern, text = parts[0].strip(), parts[1].strip()
        else:
            return "Error: Provide pattern and text. Format: pattern ||| text"
    if not text: return "Error: No text to search."
    try:
        re.findall(pattern, text)
        groups = re.finditer(pattern, text)
        results = []
        for m in groups:
            if m.groupdict():
                results.append(str(m.groupdict()))
            elif m.groups():
                results.append(str(m.groups()))
            else:
                results.append(m.group(0))
        if not results:
            return f"No matches for pattern `{pattern}`"
        return f"Regex matches ({len(results)}):\n```\n" + "\n".join(results) + "\n```"
    except re.error as e:
        return f"Invalid regex pattern: {e}"

def _handler_timestamp_convert(user_input: str = "", **kwargs) -> str:
    from datetime import datetime, timezone
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No input provided."
    results = []
    try:
        epoch = float(text)
        if epoch > 1e12: epoch /= 1000  # milliseconds
        dt = datetime.fromtimestamp(epoch, tz=timezone.utc)
        results.append(f"Epoch {text} =")
        results.append(f"  UTC:   {dt.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        results.append(f"  ISO:   {dt.isoformat()}")
        results.append(f"  Human: {dt.strftime('%B %d, %Y at %I:%M:%S %p UTC')}")
    except (ValueError, OverflowError):
        for fmt in ["%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S",
                     "%Y-%m-%d", "%m/%d/%Y %H:%M:%S", "%m/%d/%Y", "%d-%b-%Y %H:%M:%S"]:
            try:
                dt = datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
                results.append(f"Parsed: {text}")
                results.append(f"  Epoch (s):  {int(dt.timestamp())}")
                results.append(f"  Epoch (ms): {int(dt.timestamp() * 1000)}")
                results.append(f"  ISO:        {dt.isoformat()}")
                break
            except ValueError:
                continue
    if not results:
        now = datetime.now(tz=timezone.utc)
        results.append(f"Could not parse '{text}'. Current time:")
        results.append(f"  Epoch: {int(now.timestamp())}")
        results.append(f"  UTC:   {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        results.append(f"  ISO:   {now.isoformat()}")
    return "Timestamp conversion:\n```\n" + "\n".join(results) + "\n```"

def _handler_uuid_generate(user_input: str = "", **kwargs) -> str:
    import uuid
    count = 1
    try:
        count = int(kwargs.get("count", user_input.strip() or "1"))
    except ValueError:
        count = 1
    count = min(max(count, 1), 10)
    uuids = [str(uuid.uuid4()) for _ in range(count)]
    return "Generated UUID(s):\n```\n" + "\n".join(uuids) + "\n```"

def _handler_regex_test(user_input: str = "", **kwargs) -> str:
    import re
    pattern = kwargs.get("pattern", "")
    text = kwargs.get("input", user_input).strip()
    if not pattern:
        parts = text.split("|||", 1)
        if len(parts) == 2:
            pattern, text = parts[0].strip(), parts[1].strip()
        else:
            return "Error: Provide pattern and text. Format: pattern ||| text"
    if not text: return "Error: No text to test."
    try:
        compiled = re.compile(pattern)
        matches = list(compiled.finditer(text))
        groups = compiled.groups
        named = list(compiled.groupindex.keys())
        lines = [f"Pattern: {pattern}", f"Groups: {groups}", f"Named groups: {named or 'none'}",
                 f"Matches: {len(matches)}"]
        for i, m in enumerate(matches[:10]):
            lines.append(f"  Match {i+1}: '{m.group(0)}' at pos {m.start()}-{m.end()}")
            if m.groupdict():
                lines.append(f"    Named: {m.groupdict()}")
            elif m.groups():
                lines.append(f"    Groups: {m.groups()}")
        if len(matches) > 10:
            lines.append(f"  ... and {len(matches) - 10} more matches")
        return "Regex test results:\n```\n" + "\n".join(lines) + "\n```"
    except re.error as e:
        return f"Invalid regex: {e}"

def _handler_conf_validate(user_input: str = "", **kwargs) -> str:
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No .conf content provided."
    issues = []
    lines = text.splitlines()
    current_stanza = None
    stanza_count = 0
    kv_count = 0
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if stripped.startswith('[') and stripped.endswith(']'):
            current_stanza = stripped[1:-1]
            stanza_count += 1
            if not current_stanza:
                issues.append(f"  Line {i}: Empty stanza name []")
        elif '=' in stripped:
            key, _, val = stripped.partition('=')
            key = key.strip()
            if not key:
                issues.append(f"  Line {i}: Empty key before '='")
            if not current_stanza and stanza_count == 0:
                issues.append(f"  Line {i}: Key '{key}' outside any stanza")
            kv_count += 1
        elif stripped.startswith('['):
            issues.append(f"  Line {i}: Malformed stanza (missing closing ']')")
        else:
            if current_stanza:
                pass  # continuation value
            else:
                issues.append(f"  Line {i}: Orphan text outside stanza: '{stripped[:40]}'")
    result = [f"Conf validation: {stanza_count} stanzas, {kv_count} settings"]
    if issues:
        result.append(f"\nIssues ({len(issues)}):")
        result.extend(issues[:20])
        if len(issues) > 20:
            result.append(f"  ... and {len(issues) - 20} more issues")
    else:
        result.append("No issues found.")
    return "\n".join(result)

def _handler_cim_validate(user_input: str = "", **kwargs) -> str:
    text = kwargs.get("input", user_input).strip()
    if not text: return "Error: No fields provided. Provide comma-separated field names."
    CIM_MODELS = {
        "Authentication": ["action", "app", "authentication_method", "dest", "src", "src_user", "user", "signature", "tag"],
        "Change": ["action", "change_type", "command", "dest", "object", "object_category", "result", "src", "status", "user"],
        "Endpoint": ["action", "dest", "dest_nt_domain", "direction", "os", "process", "process_id", "service", "signature", "user"],
        "Network_Traffic": ["action", "app", "bytes", "bytes_in", "bytes_out", "dest", "dest_ip", "dest_port", "direction", "duration", "protocol", "src", "src_ip", "src_port", "transport", "user"],
        "Web": ["action", "app", "bytes", "bytes_in", "bytes_out", "category", "dest", "http_content_type", "http_method", "http_referrer", "http_user_agent", "site", "src", "status", "uri_path", "uri_query", "url", "user"],
        "Malware": ["action", "dest", "file_hash", "file_name", "file_path", "signature", "src", "user", "vendor_product"],
        "Intrusion_Detection": ["action", "category", "dest", "dvc", "ids_type", "severity", "signature", "src", "transport", "vendor_product"],
        "Alerts": ["app", "body", "description", "dest", "severity", "signature", "src", "subject", "type", "user"],
    }
    fields = [f.strip() for f in text.replace('\n', ',').split(',') if f.strip()]
    results = []
    for model, expected in CIM_MODELS.items():
        matched = [f for f in fields if f in expected]
        missing = [f for f in expected if f not in fields]
        if matched:
            pct = len(matched) / len(expected) * 100
            results.append(f"  {model}: {len(matched)}/{len(expected)} fields ({pct:.0f}%)")
            if missing and pct > 30:
                results.append(f"    Missing: {', '.join(missing[:8])}")
    unmapped = [f for f in fields if not any(f in v for v in CIM_MODELS.values())]
    summary = [f"CIM Validation for {len(fields)} fields:"]
    if results:
        summary.append("\nMatching data models:")
        summary.extend(results)
    else:
        summary.append("\nNo CIM data model matches found.")
    if unmapped:
        summary.append(f"\nUnmapped fields ({len(unmapped)}): {', '.join(unmapped[:15])}")
    return "\n".join(summary)


def _handler_doc_generator(user_input: str = "", **kwargs) -> str:
    """Generate documentation from text, directory, or zip file."""
    from chat_app.doc_generator import get_doc_generator
    from pathlib import Path as _DocPath

    text = kwargs.get("input", user_input).strip()
    if not text:
        return ("**Documentation Generator**\n\n"
                "Usage:\n"
                "- Provide text/snippets to generate formatted documentation\n"
                "- Provide a directory path to scan and document all files\n"
                "- Provide a zip file path to extract and document\n\n"
                "Options: format=markdown|sharepoint, style=technical|user-friendly|api-reference")

    gen = get_doc_generator()
    fmt = kwargs.get("format", "markdown")
    style = kwargs.get("style", "technical")
    title = kwargs.get("title", "Documentation")

    # Auto-detect mode from input
    target = _DocPath(text)
    if target.is_dir():
        result = gen.from_directory(text, title=title, format=fmt)
    elif target.exists() and text.endswith(".zip"):
        result = gen.from_zip(text, title=title, format=fmt)
    else:
        # Treat as text snippet(s)
        snippets = text.split("\n---\n") if "\n---\n" in text else [text]
        result = gen.from_snippets(snippets, title=title, format=fmt, style=style)

    warnings = ""
    if result.warnings:
        warnings = f"\n\n**Warnings**: {', '.join(result.warnings)}"

    meta = result.metadata
    stats_line = ""
    if "files_analyzed" in meta:
        stats_line = f"\n\n*Analyzed {meta['files_analyzed']} files, {meta.get('total_lines', 0):,} lines*"

    return f"{result.content}{stats_line}{warnings}"



# ---------------------------------------------------------------------------
# Handler registry — maps handler_key to function for auto-registration
# ---------------------------------------------------------------------------

HANDLERS = {
    # Encoding/decoding (8)
    "base64_encode": _handler_base64_encode,
    "base64_decode": _handler_base64_decode,
    "url_encode": _handler_url_encode,
    "url_decode": _handler_url_decode,
    "hex_encode": _handler_hex_encode,
    "hex_decode": _handler_hex_decode,
    "html_encode": _handler_html_encode,
    "html_decode": _handler_html_decode,
    # Hashing (4)
    "md5": _handler_md5,
    "sha1": _handler_sha1,
    "sha256": _handler_sha256,
    "sha512": _handler_sha512,
    # Data transform (8)
    "json_prettify": _handler_json_prettify,
    "json_minify": _handler_json_minify,
    "csv_to_json": _handler_csv_to_json,
    "json_to_csv": _handler_json_to_csv,
    "kv_parse": _handler_kv_parse,
    "xml_to_json": _handler_xml_to_json,
    "json_parse": _handler_json_parse,
    "csv_parse": _handler_csv_parse,
    # Text manipulation (7)
    "text_upper": _handler_text_upper,
    "text_lower": _handler_text_lower,
    "text_reverse": _handler_text_reverse,
    "text_trim": _handler_text_trim,
    "line_sort": _handler_line_sort,
    "unique_lines": _handler_unique_lines,
    "remove_empty_lines": _handler_remove_empty_lines,
    # SPL utilities (3)
    "spl_escape": _handler_spl_escape,
    "quote_values": _handler_quote_values,
    "rex_extract": _handler_rex_extract,
    # General utilities (3)
    "timestamp_convert": _handler_timestamp_convert,
    "uuid_generate": _handler_uuid_generate,
    "regex_test": _handler_regex_test,
    # Validation (2)
    "conf_validate": _handler_conf_validate,
    "cim_validate": _handler_cim_validate,
    # Documentation
    "doc_generator": _handler_doc_generator,
}
