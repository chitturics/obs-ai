"""
Utility functions: file I/O, caching, conf parsing, and low-level helpers.
"""
import csv
import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from shared.spl_validator import SPLValidator

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------
_SAVED_CACHE: Dict[str, Any] = {}
_MACROS_CACHE: Dict[str, str] = {}
_CUSTOM_COMMANDS_CACHE: Dict[str, Dict[str, Any]] = {}
_ANALYZED_CACHE: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Data root
# ---------------------------------------------------------------------------
def _resolve_data_root() -> Path:
    preferred = Path(os.getenv("SEARCH_OPT_DATA_DIR", "/app/data"))
    try:
        preferred.mkdir(parents=True, exist_ok=True)
        return preferred
    except Exception:
        for fallback in [Path("/tmp/search_opt_data"), Path.cwd() / "data"]:
            try:
                fallback.mkdir(parents=True, exist_ok=True)
                return fallback
            except Exception:
                continue
        return preferred


# ---------------------------------------------------------------------------
# Best-practices / history persistence
# ---------------------------------------------------------------------------
def _load_best_practices(path: Path) -> list:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def _save_best_practices(path: Path, practices: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(practices, indent=2), encoding="utf-8")


def _append_history(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _load_best_practices(path)
    existing.append(record)
    _save_best_practices(path, existing)


# ---------------------------------------------------------------------------
# Conf file parsing
# ---------------------------------------------------------------------------
def _parse_conf_file(conf_path: Path) -> list:
    """Robustly parse a Splunk .conf file into a list of stanza dicts."""
    stanzas: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None
    search_accum: List[str] = []

    try:
        with conf_path.open(encoding="utf-8", errors="ignore") as f:
            for raw in f:
                line = raw.rstrip("\n")
                if not line or line.strip().startswith("#"):
                    continue
                if line.startswith("[") and line.endswith("]"):
                    if current:
                        if search_accum:
                            current["search"] = "\n".join(search_accum).strip()
                            search_accum = []
                        stanzas.append(current)
                    current = {"name": line.strip("[]"), "fields": {}, "file": str(conf_path)}
                    continue
                if current is None:
                    continue
                if line.startswith(" ") or line.startswith("\t"):
                    if search_accum:
                        search_accum.append(line.strip())
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    key = key.strip()
                    val = val.strip()
                    if key == "search":
                        search_accum = [val]
                    else:
                        current["fields"][key] = val
        if current:
            if search_accum:
                current["search"] = "\n".join(search_accum).strip()
            stanzas.append(current)
    except Exception as e:
        logger.warning(f"Failed to parse {conf_path}: {e}")

    return stanzas


# ---------------------------------------------------------------------------
# Macros loading
# ---------------------------------------------------------------------------
def _load_macros(root: Path) -> Dict[str, str]:
    """Load macros as a flat name->definition dict."""
    macros = {}
    for path in root.rglob("macros.conf"):
        for stanza in _parse_conf_file(path):
            definition = stanza["fields"].get("definition")
            if definition:
                macros[stanza["name"]] = definition
    return macros


def _load_all_macros() -> Dict[str, str]:
    """Load macros from all configured repository roots. Cached after first load."""
    global _MACROS_CACHE
    if _MACROS_CACHE:
        return _MACROS_CACHE

    default_root = "/app/public/documents/repo"
    roots = os.getenv("SAVEDSEARCH_ROOTS", default_root).split(",")
    if all(not Path(r.strip()).exists() for r in roots):
        local_root = Path.cwd() / "documents" / "repo"
        roots = [str(local_root)]

    for root in roots:
        root_path = Path(root.strip())
        if root_path.exists():
            macros = _load_macros(root_path)
            _MACROS_CACHE.update(macros)

    out_path = _resolve_data_root() / "macros_cache.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(_MACROS_CACHE, indent=2), encoding="utf-8")

    return _MACROS_CACHE


def get_registered_macros() -> Dict[str, str]:
    """Get all registered macros."""
    return _load_all_macros()


# ---------------------------------------------------------------------------
# Custom commands loading
# ---------------------------------------------------------------------------
def _load_custom_commands(root: Path) -> Dict[str, Dict[str, Any]]:
    """Parse commands.conf files to discover custom SPL commands."""
    commands = {}
    for path in root.rglob("commands.conf"):
        for stanza in _parse_conf_file(path):
            name = stanza["name"]
            if name == "default":
                continue
            fields = stanza["fields"]
            commands[name] = {
                "file": stanza["file"],
                "type": fields.get("type", "python"),
                "filename": fields.get("filename", ""),
                "streaming": fields.get("streaming", "false").lower() == "true",
                "generating": fields.get("generating", "false").lower() == "true",
                "retainsevents": fields.get("retainsevents", "false").lower() == "true",
                "description": fields.get("description", ""),
            }
    return commands


def get_custom_commands() -> Dict[str, Dict[str, Any]]:
    """Get all custom commands from the repo directory. Cached after first load."""
    global _CUSTOM_COMMANDS_CACHE
    if _CUSTOM_COMMANDS_CACHE:
        return _CUSTOM_COMMANDS_CACHE

    default_root = "/app/public/documents/repo"
    roots = os.getenv("SAVEDSEARCH_ROOTS", default_root).split(",")
    if all(not Path(r.strip()).exists() for r in roots):
        local_root = Path.cwd() / "documents" / "repo"
        roots = [str(local_root)]

    for root in roots:
        root_path = Path(root.strip())
        if root_path.exists():
            commands = _load_custom_commands(root_path)
            _CUSTOM_COMMANDS_CACHE.update(commands)

    out_path = _resolve_data_root() / "custom_commands.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(_CUSTOM_COMMANDS_CACHE, indent=2), encoding="utf-8")

    return _CUSTOM_COMMANDS_CACHE


def get_custom_command_names() -> set:
    """Get just the names of custom commands for quick lookup."""
    return set(get_custom_commands().keys())


# ---------------------------------------------------------------------------
# Saved searches loading
# ---------------------------------------------------------------------------
def _expand_macros(search: str, macros: Dict[str, str]) -> Tuple[str, List[str]]:
    used = []
    pattern = re.compile(r"`([^`(]+)(?:\([^\)]*\))?`")

    def repl(match):
        name = match.group(1)
        used.append(name)
        return macros.get(name, match.group(0))

    expanded = pattern.sub(repl, search)
    return expanded, used


def _load_saved_searches() -> List[Dict[str, Any]]:
    global _SAVED_CACHE
    cache_key = "savedsearches"
    if _SAVED_CACHE.get(cache_key):
        return _SAVED_CACHE[cache_key]

    default_root = "/app/public/documents/repo"
    roots = os.getenv("SAVEDSEARCH_ROOTS", default_root).split(",")
    if all(not Path(r.strip()).exists() for r in roots):
        local_root = Path.cwd() / "documents" / "repo"
        roots = [str(local_root)]
    saved = []
    for root in roots:
        root_path = Path(root.strip())
        if not root_path.exists():
            continue
        macros = _load_macros(root_path)
        for path in root_path.rglob("savedsearches.conf"):
            for stanza in _parse_conf_file(path):
                search_text = stanza.get("search") or stanza["fields"].get("search")
                if not search_text:
                    continue
                expanded, used = _expand_macros(search_text, macros)
                saved.append(
                    {
                        "name": stanza["name"],
                        "file": stanza["file"],
                        "search_raw": search_text,
                        "search_expanded": expanded,
                        "macros_used": used,
                        "fields": stanza["fields"],
                    }
                )
    _SAVED_CACHE[cache_key] = saved
    out_path = _resolve_data_root() / "savedsearch_index.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(saved, indent=2), encoding="utf-8")
    return saved


def _find_matching_savedsearches(query: str, saved: List[Dict[str, Any]], limit: int = 3) -> List[Dict[str, Any]]:
    q_tokens = set(re.findall(r"[a-z0-9_]+", query.lower()))
    scored = []
    for item in saved:
        tokens = set(re.findall(r"[a-z0-9_]+", item.get("search_raw", "").lower()))
        score = len(q_tokens & tokens)
        if item.get("name") and item["name"].lower() in q_tokens:
            score += 5
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s[1] for s in scored[:limit]]


# ---------------------------------------------------------------------------
# Log hints
# ---------------------------------------------------------------------------
def _load_log_hints(path: Path) -> list:
    if not path.exists():
        fallback = Path.cwd() / "containers" / "search_opt" / "data" / "log_type_hints.csv"
        if fallback.exists():
            path = fallback
        else:
            return []
    rows = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append({k: (v or "").strip() for k, v in row.items()})
    return rows


def _find_hint(raw_query: str, hints: list) -> Dict[str, str]:
    ql = raw_query.lower()
    for hint in hints:
        if hint.get("type_of_log") and hint["type_of_log"].lower() in ql:
            return hint
    return {}


def _apply_hint_to_query(query: str, hint: Dict[str, str]) -> str:
    index = hint.get("index")
    sourcetype = hint.get("sourcetype")
    source = hint.get("source")
    add = hint.get("additional_search") or hint.get("additiional_search")

    def insert_term(base: str, term: str) -> str:
        if not term:
            return base
        m = re.search(r"\bearliest=|\blatest=", base)
        if m:
            return f"{base[:m.start()]}{term} {base[m.start():]}"
        if " |" in base:
            pre, post = base.split("|", 1)
            return f"{pre} {term} |{post}"
        return f"{base} {term}"

    if index and "index=" not in query:
        if query.startswith("| tstats") and " where " in query:
            query = query.replace(" where ", f" where index={index} ", 1)
        elif query.startswith("search "):
            query = query.replace("search ", f"search index={index} ", 1)
        else:
            query = insert_term(query, f"index={index}")

    if sourcetype and "sourcetype=" not in query:
        query = insert_term(query, f"sourcetype={sourcetype}")

    if source and "source=" not in query:
        query = insert_term(query, f"source={source}")

    if add:
        add_term = add
        if (" OR " in add or " AND " in add) and not add.strip().startswith("("):
            add_term = f"({add})"
        query = insert_term(query, add_term)

    return query


# ---------------------------------------------------------------------------
# SQL linting (optional)
# ---------------------------------------------------------------------------
def _sql_lint(query: str) -> Dict[str, Any]:
    """Run sqlfluff lint if available and the query looks like SQL."""
    if not re.search(r"\bselect\b.*\bfrom\b", query, re.IGNORECASE):
        return {"ran": False}
    try:
        import sqlfluff  # type: ignore

        lint_result = sqlfluff.lint(query, dialect="ansi")
        violations = [
            {
                "code": v["code"],
                "line": v["line_no"],
                "position": v["line_pos"],
                "description": v["description"],
            }
            for v in lint_result
        ]
        return {"ran": True, "violations": violations}
    except ImportError:
        return {"ran": False, "reason": "sqlfluff not installed"}
    except Exception as exc:
        return {"ran": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Review & best-practices extraction
# ---------------------------------------------------------------------------
def _extract_best_practices(query: str, validation) -> list:
    practices = []
    if "earliest" in query and "latest" in query:
        practices.append("Time-bounded search provided (earliest/latest).")
    if validation and validation.errors:
        practices.append("Avoid patterns flagged as errors: " + "; ".join(validation.errors))
    if validation and validation.warnings:
        practices.append("Consider warnings: " + "; ".join(validation.warnings))
    if validation and validation.parsed_components:
        indexes = validation.parsed_components.get("indexes") or []
        if indexes:
            practices.append("Indexes explicitly scoped: " + ", ".join(indexes))
        commands = validation.parsed_components.get("commands") or []
        if commands:
            practices.append("Pipeline uses commands: " + ", ".join(commands))
    return practices


def _review_query(query: str) -> Tuple[Dict[str, Any], Any]:
    validation = SPLValidator.validate(query, block_dangerous=False)
    return {
        "status": validation.status.value,
        "risk_score": validation.risk_score,
        "risk_level": validation.risk_level.value,
        "errors": validation.errors,
        "warnings": validation.warnings,
        "suggestions": validation.suggestions,
    }, validation


# ---------------------------------------------------------------------------
# Analyzed searches cache
# ---------------------------------------------------------------------------
def _get_analyzed_searches_path() -> Path:
    return _resolve_data_root() / "analyzed_savedsearches.json"


def _get_feedback_path() -> Path:
    return _resolve_data_root() / "search_feedback.json"


def _load_analyzed_searches() -> Dict[str, Any]:
    """Load previously analyzed saved searches."""
    global _ANALYZED_CACHE
    if _ANALYZED_CACHE:
        return _ANALYZED_CACHE

    path = _get_analyzed_searches_path()
    if path.exists():
        try:
            _ANALYZED_CACHE = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            _ANALYZED_CACHE = {}
    return _ANALYZED_CACHE


def _save_analyzed_searches(data: Dict[str, Any]) -> None:
    """Persist analyzed saved searches."""
    global _ANALYZED_CACHE
    _ANALYZED_CACHE = data
    path = _get_analyzed_searches_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
