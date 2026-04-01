"""
Shared SPL Utilities — Common Functions Used Across Modules

Provides single, canonical implementations of frequently needed
operations so that every module in shared/ uses the same logic:

- split_pipeline()       — Split SPL into pipe-delimited stages
- parse_relative_time()  — Parse Splunk relative-time strings to seconds
- extract_time_range()   — Pull earliest/latest from a query
- seconds_to_human()     — Human-readable duration
- estimate_cardinality() — Heuristic field cardinality classification
- extract_command()      — Extract command name from a pipeline stage
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from shared.constants import (
    HIGH_CARDINALITY_FIELDS,
    HIGH_CARD_KEYWORDS,
    LOW_CARD_KEYWORDS,
    LOW_CARDINALITY_FIELDS,
    MEDIUM_CARD_KEYWORDS,
    MEDIUM_CARDINALITY_FIELDS,
    TIME_UNITS,
)

# ---------------------------------------------------------------------------
# Compiled regex patterns (compiled once at import time)
# ---------------------------------------------------------------------------

_RE_SNAP_TO = re.compile(r"@[a-z0-9]*$")
_RE_RELATIVE_TIME = re.compile(r"^(-?\d+)([a-z]+)$")
_RE_EARLIEST = re.compile(r"earliest\s*=\s*(-?\d+)([a-z@]+)", re.IGNORECASE)
_RE_EARLIEST_ZERO = re.compile(r"earliest\s*=\s*0\b", re.IGNORECASE)
_RE_EARLIEST_STR = re.compile(r"earliest\s*=\s*([^\s]+)", re.IGNORECASE)
_RE_LATEST_STR = re.compile(r"latest\s*=\s*([^\s]+)", re.IGNORECASE)
_RE_INDEX = re.compile(r'index\s*=\s*["\']?([^\s"\']+)["\']?', re.IGNORECASE)
_RE_SOURCETYPE = re.compile(r'sourcetype\s*=\s*["\']?([^\s"\']+)["\']?', re.IGNORECASE)
_RE_CMD = re.compile(r"^\s*(\w+)")
_RE_BY_FIELDS = re.compile(r"\bby\s+(.+?)(?:\s*$|\s*\|)", re.IGNORECASE)
_RE_SPAN = re.compile(r"span\s*=\s*(\d+[smhdw]|auto)", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Pipeline Splitting
# ---------------------------------------------------------------------------

def split_pipeline(query: str) -> List[str]:
    """
    Split an SPL query into pipeline stages on unquoted, unbracketed pipes.

    Correctly handles:
    - Quoted strings (single, double, backtick)
    - Subsearch brackets  [search ...]
    - Escaped quotes

    Returns a list of stage strings (without the leading pipe character).
    """
    stages: list[str] = []
    current: list[str] = []
    in_quote = False
    quote_char: Optional[str] = None
    depth = 0

    for i, char in enumerate(query):
        # Track quotes (skip escaped quotes)
        if char in '"\'`' and (i == 0 or query[i - 1] != '\\'):
            if not in_quote:
                in_quote = True
                quote_char = char
            elif char == quote_char:
                in_quote = False
                quote_char = None

        if not in_quote:
            if char == '[':
                depth += 1
            elif char == ']':
                depth = max(0, depth - 1)
            elif char == '|' and depth == 0:
                stage = ''.join(current).strip()
                if stage:
                    stages.append(stage)
                current = []
                continue

        current.append(char)

    stage = ''.join(current).strip()
    if stage:
        stages.append(stage)

    return stages


# ---------------------------------------------------------------------------
# Time Parsing
# ---------------------------------------------------------------------------

def parse_relative_time(time_str: str) -> Optional[int]:
    """
    Parse a Splunk relative-time string to seconds.

    Handles all common formats:
    - Simple:   -7d, -24h, -30m, -1y
    - Snap-to:  -7d@d, -1h@h, -1w@w0
    - Long:     -30minutes, -7days, -1month
    - Special:  0, now

    Returns seconds (negative for past times) or None if unparseable.
    """
    if not time_str:
        return None

    time_str = time_str.strip().lower()

    if time_str == "now":
        return 0
    if time_str == "0":
        return 0

    # Strip snap-to suffix (@d, @h, @w0, etc.)
    base = _RE_SNAP_TO.sub("", time_str)
    if not base:
        return None

    match = _RE_RELATIVE_TIME.match(base)
    if match:
        value = int(match.group(1))
        unit = match.group(2)
        multiplier = TIME_UNITS.get(unit)
        if multiplier:
            return value * multiplier

    return None


def extract_time_range_seconds(query: str) -> Optional[int]:
    """
    Extract the approximate time range from a query's earliest= parameter.

    Returns the range in seconds, or None if no earliest= found.
    """
    match = _RE_EARLIEST.search(query)
    if match:
        value = abs(int(match.group(1)))
        raw_unit = match.group(2).lower()
        # Strip snap-to suffix: "d@d" → "d"
        unit = _RE_SNAP_TO.sub("", raw_unit)
        if not unit:
            unit = raw_unit[0]  # Fallback to first char
        multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400,
                       "w": 604800, "mon": 2592000, "y": 31536000}
        return value * multipliers.get(unit, 3600)

    # earliest=0 means all time
    if _RE_EARLIEST_ZERO.search(query):
        return 365 * 86400  # Treat as 1 year

    return None


def seconds_to_human(seconds: int) -> str:
    """Convert seconds to a compact human-readable duration."""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds // 60}m"
    elif seconds < 86400:
        return f"{seconds // 3600}h"
    elif seconds < 604800:
        return f"{seconds // 86400}d"
    elif seconds < 2592000:
        return f"{seconds // 604800}w"
    else:
        return f"{seconds // 86400}d"


# ---------------------------------------------------------------------------
# Cardinality Estimation
# ---------------------------------------------------------------------------

def estimate_cardinality(field_name: str) -> str:
    """
    Estimate the cardinality of a field based on its name.

    Returns one of: "very_high", "high", "medium", "low"
    """
    fld = field_name.lower()

    if fld in HIGH_CARDINALITY_FIELDS:
        return "very_high"
    if fld in MEDIUM_CARDINALITY_FIELDS:
        return "high"
    if fld in LOW_CARDINALITY_FIELDS:
        return "low"

    # Keyword heuristics for unknown fields
    if any(kw in fld for kw in HIGH_CARD_KEYWORDS):
        return "very_high"
    if any(kw in fld for kw in MEDIUM_CARD_KEYWORDS):
        return "high"
    if any(kw in fld for kw in LOW_CARD_KEYWORDS):
        return "low"

    return "medium"


# ---------------------------------------------------------------------------
# Command Extraction
# ---------------------------------------------------------------------------

def extract_command(stage: str) -> str:
    """Extract the command name from a pipeline stage string."""
    match = _RE_CMD.match(stage.strip())
    return match.group(1).lower() if match else "unknown"


def extract_by_fields(stage: str) -> List[str]:
    """Extract field names from a BY clause in a pipeline stage."""
    match = _RE_BY_FIELDS.search(stage)
    if not match:
        return []
    return [
        f.strip()
        for f in re.split(r"[,\s]+", match.group(1))
        if f.strip() and not f.startswith("span=")
    ]


# ---------------------------------------------------------------------------
# Query Component Extraction
# ---------------------------------------------------------------------------

def extract_indexes(query: str) -> Tuple[List[str], bool]:
    """
    Extract index names from a query.

    Returns (list_of_indexes, has_wildcard).
    """
    indexes = []
    has_wildcard = False
    for match in _RE_INDEX.finditer(query):
        idx = match.group(1)
        indexes.append(idx)
        if idx == "*" or idx.startswith("*"):
            has_wildcard = True
    return indexes, has_wildcard


def extract_sourcetypes(query: str) -> List[str]:
    """Extract sourcetype names from a query."""
    return [m.group(1) for m in _RE_SOURCETYPE.finditer(query)]


def extract_earliest_latest(query: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract earliest and latest values from a query."""
    earliest = None
    latest = None
    m = _RE_EARLIEST_STR.search(query)
    if m:
        earliest = m.group(1)
    m = _RE_LATEST_STR.search(query)
    if m:
        latest = m.group(1)
    return earliest, latest


# ---------------------------------------------------------------------------
# SPL Extraction from Free Text
# ---------------------------------------------------------------------------

def extract_spl_from_text(user_input: str) -> Optional[str]:
    """
    Extract an SPL query from free-form user input.

    Checks for:
    1. SPL in markdown code blocks (```spl ... ``` or ``` ... ```)
    2. Inline SPL (lines containing index= or pipe commands)

    Returns the extracted SPL string, or None if no SPL is found.
    """
    if not user_input:
        return None

    # Check for code block
    match = re.search(r'```(?:spl)?\n(.+?)\n```', user_input, re.DOTALL)
    if match:
        return match.group(1).strip()

    # Check for inline SPL
    match = re.search(
        r'((?:index\s*=\s*\S+|(?:\|\s*\w+\s+))\S.*?)(?:\n|$)',
        user_input, re.DOTALL
    )
    if match:
        candidate = match.group(1).strip()
        if '|' in candidate or 'index=' in candidate.lower():
            return candidate

    return None
