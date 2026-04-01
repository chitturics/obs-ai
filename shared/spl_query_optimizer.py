"""
SPL Query Optimizer - Sophisticated tstats Conversion Engine

Parses Splunk SPL queries and converts them to optimized tstats queries
when possible, using TERM() and PREFIX() for maximum performance.

This module provides:
1. Query parsing and decomposition
2. Field classification (index-time vs search-time)
3. CIM data model mapping
4. tstats query generation with TERM()/PREFIX()
5. Macro detection and expansion support
6. Comment stripping (triple backticks)
"""

import re
import logging
from typing import Optional, List, Dict, Tuple, Set, Any
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class ConversionStatus(Enum):
    """Status of tstats conversion attempt."""
    FULL = "full"           # Entire query converted to tstats
    PARTIAL = "partial"     # Initial search converted, post-processing kept
    IMPOSSIBLE = "impossible"  # Cannot convert to tstats


class OptimizationStrategy(Enum):
    """Strategy used for optimization."""
    PURE_TSTATS = "Pure tstats"              # All BY fields are tstats-safe
    TWO_PHASE = "Two-phase"                  # tstats prefilter + original aggregation
    DATAMODEL = "Datamodel tstats"           # Using CIM datamodel summaries
    REFUSED = "Refused"                      # Cannot convert safely


@dataclass
class SearchTerm:
    """Represents a single search term."""
    raw: str                    # Original text
    field: Optional[str]        # Field name if key=value
    value: str                  # Value or keyword
    operator: str = "="         # Comparison operator: =, !=, >, <, >=, <=
    is_negated: bool = False    # NOT or !=
    has_wildcard: bool = False  # Contains * or ?
    wildcard_position: str = "" # "prefix", "suffix", "middle", "none"
    is_or_group: bool = False   # Part of OR condition
    or_group_id: int = 0        # ID for grouping OR terms
    is_comparison: bool = False # True if operator is >, <, >=, <=

    def to_tstats_filter(self) -> Optional[str]:
        """Convert to tstats TERM() or PREFIX() filter."""
        # Middle wildcards (*value*) require raw event scanning
        if self.wildcard_position == "middle":
            return None

        # Prefix wildcards (*value) cannot use TERM() or PREFIX() - require raw scanning
        if self.wildcard_position == "prefix":
            return None

        # Comparison operators (>, <, >=, <=) cannot be converted to tstats TERM/PREFIX
        if self.is_comparison:
            return None

        # Negated terms cannot be converted to tstats filters
        if self.is_negated:
            return None

        # Free-text keywords (no field) → TERM(keyword)
        # Example: "error" → TERM(error)
        if not self.field:
            if self.has_wildcard and self.wildcard_position == "suffix":
                # error* → PREFIX(error)
                clean_value = self.value.rstrip("*")
                return f"PREFIX({clean_value})"
            # Exact keyword → TERM(keyword)
            return f"TERM({self.value})"

        # Suffix wildcards (value*) → can use PREFIX()
        if self.has_wildcard and self.wildcard_position == "suffix":
            # src_ip=10.1.* → PREFIX(src_ip=10.1.)
            clean_value = self.value.rstrip("*")
            return f"PREFIX({self.field}={clean_value})"

        # Exact match (no wildcards) → TERM()
        return f"TERM({self.field}={self.value})"


@dataclass
class MacroReference:
    """Represents a macro reference in SPL."""
    name: str           # Macro name (without backticks)
    raw: str            # Original text including backticks
    args: List[str] = field(default_factory=list)  # Arguments if parametrized
    expanded: Optional[str] = None  # Expanded definition (if available)


@dataclass
class ParsedQuery:
    """Fully parsed SPL query structure."""
    # Initial search (before first pipe)
    indexes: List[str] = field(default_factory=list)
    sourcetypes: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
    hosts: List[str] = field(default_factory=list)

    # Organization-specific indexed fields
    unit_ids: List[str] = field(default_factory=list)
    circuits: List[str] = field(default_factory=list)

    # Time range
    earliest: str = "-15m"
    latest: str = "now"

    # Search terms (key=value and free text)
    search_terms: List[SearchTerm] = field(default_factory=list)

    # Pipeline commands
    commands: List[Dict] = field(default_factory=list)

    # Aggregation info
    aggregation_cmd: Optional[str] = None  # stats, timechart, chart, etc.
    aggregation_funcs: List[str] = field(default_factory=list)  # count, sum, avg, etc.
    by_fields: List[str] = field(default_factory=list)  # fields in BY clause
    time_span: Optional[str] = None  # span=1h, span=5m, etc.

    # Fields referenced throughout
    all_fields: Set[str] = field(default_factory=set)

    # Conversion blockers
    blockers: List[str] = field(default_factory=list)

    # Macros detected in query
    macros: List[MacroReference] = field(default_factory=list)

    # Comments stripped from query
    comments: List[str] = field(default_factory=list)

    # Whether query was already tstats
    is_tstats: bool = False


@dataclass
class OptimizedQuery:
    """Result of query optimization."""
    status: ConversionStatus
    strategy: OptimizationStrategy
    original: str
    optimized: str
    explanation: str
    blockers: List[str] = field(default_factory=list)
    performance_notes: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)


class SPLQueryOptimizer:
    """Sophisticated SPL query optimizer with tstats conversion."""

    # Index-time fields (always available for tstats)
    INDEX_TIME_FIELDS = {
        "index", "source", "sourcetype", "host", "_time",
        "splunk_server", "splunk_server_group", "linecount",
        # Organization-specific indexed fields
        "unit_id", "circuit"
    }

    # Macro definitions cache (can be loaded from macros.conf)
    _macro_definitions: Dict[str, Dict[str, Any]] = {}

    @classmethod
    def register_macros(cls, macros: Dict[str, Dict[str, Any]]) -> None:
        """
        Register macro definitions for expansion.

        Args:
            macros: Dict mapping macro name to its full definition dict
                    from conf_loader.
        """
        cls._macro_definitions.update(macros)
        logger.debug(f"Registered {len(macros)} macros")

    @classmethod
    def strip_comments(cls, query: str) -> Tuple[str, List[str]]:
        """
        Strip triple-backtick comments from SPL query.

        In SPL, triple backticks (```) denote multi-line comments.

        Args:
            query: Raw SPL query

        Returns:
            Tuple of (cleaned_query, list_of_comments)
        """
        comments = []
        # Match ``` ... ``` comment blocks (can span multiple lines)
        pattern = r'```(.*?)```'

        def capture_comment(match):
            comment = match.group(1).strip()
            if comment:
                comments.append(comment)
            return ''  # Remove the comment

        cleaned = re.sub(pattern, capture_comment, query, flags=re.DOTALL)

        if comments:
            logger.debug(f"Stripped {len(comments)} comments from query")

        return cleaned.strip(), comments

    @classmethod
    def detect_macros(cls, query: str) -> List[MacroReference]:
        """
        Detect macro references in SPL query.

        Macros are denoted by backticks: `macroname` or `macroname(arg1,arg2)`

        Args:
            query: SPL query

        Returns:
            List of MacroReference objects
        """
        macros = []

        # Pattern for macros: `name` or `name(args)`
        # Must NOT be triple backticks (comments)
        pattern = r'(?<!`)(?<!``)`([^`]+)`(?!`)(?!``)'

        for match in re.finditer(pattern, query):
            raw = match.group(0)
            content = match.group(1)

            # Check if it's a parametrized macro: name(arg1, arg2)
            param_match = re.match(r'(\w+)\(([^)]*)\)', content)
            if param_match:
                name = param_match.group(1)
                args_str = param_match.group(2)
                args = [a.strip() for a in args_str.split(',')] if args_str else []
            else:
                name = content.strip()
                args = []

            # Try to get expansion from registered macros
            expanded = None
            macro_def = cls._macro_definitions.get(name)
            if macro_def:
                expanded = macro_def.get("definition")
                # Substitute arguments if present
                if args and expanded:
                    defined_args = macro_def.get("args", [])
                    # Prefer named argument substitution if available
                    if defined_args and len(defined_args) == len(args):
                        arg_map = {key: value for key, value in zip(defined_args, args)}
                        for arg_name, arg_value in arg_map.items():
                            expanded = expanded.replace(f'${arg_name}$', arg_value)
                    else:
                        # Fallback to positional substitution
                        for i, arg in enumerate(args):
                            expanded = expanded.replace(f'${i+1}$', arg)

            macros.append(MacroReference(
                name=name,
                raw=raw,
                args=args,
                expanded=expanded
            ))

        return macros

    @classmethod
    def expand_macros(cls, query: str, macros: List[MacroReference] = None) -> str:
        """
        Expand macros in query if definitions are available.

        Args:
            query: SPL query with macros
            macros: Optional pre-detected macros (will detect if not provided)

        Returns:
            Query with macros expanded (where definitions available)
        """
        if macros is None:
            macros = cls.detect_macros(query)

        result = query
        for macro in macros:
            if macro.expanded:
                result = result.replace(macro.raw, macro.expanded)
                logger.debug(f"Expanded macro `{macro.name}` -> {macro.expanded[:50]}...")

        return result

    @classmethod
    def check_macro_index_risk(cls, macros: List[MacroReference]) -> List[str]:
        """
        Check if any macros might contain index definitions.

        Args:
            macros: List of detected macros

        Returns:
            List of warning messages
        """
        warnings = []
        # Common macro naming patterns that often contain index definitions
        index_macro_patterns = [
            r'.*base.*',        # base_search, my_base, etc.
            r'.*index.*',       # index_filter, etc.
            r'.*search.*',      # common_search, etc.
            r'.*filter.*',      # common_filter, etc.
            r'.*source.*',      # data_source, etc.
        ]

        for macro in macros:
            name_lower = macro.name.lower()

            # Check if macro expansion contains index
            if macro.expanded:
                if 'index=' in macro.expanded.lower():
                    warnings.append(
                        f"Macro `{macro.name}` contains index definition: "
                        f"{macro.expanded[:100]}..."
                    )
                continue

            # No expansion available - warn if name suggests it might have index
            for pattern in index_macro_patterns:
                if re.match(pattern, name_lower):
                    warnings.append(
                        f"Macro `{macro.name}` may contain index definition "
                        f"(cannot verify - definition not loaded)"
                    )
                    break
            else:
                # Generic warning for any unexpanded macro
                warnings.append(
                    f"Macro `{macro.name}` was not expanded - index analysis may be incomplete"
                )

        return warnings

    # CIM Data Models and their field mappings
    CIM_MODELS = {
        "Network_Traffic": {
            "indicators": ["firewall", "pan", "asa", "network", "traffic", "connection"],
            "dataset": "All_Traffic",
            "fields": {
                "src_ip": "Network_Traffic.All_Traffic.src",
                "dest_ip": "Network_Traffic.All_Traffic.dest",
                "src": "Network_Traffic.All_Traffic.src",
                "dest": "Network_Traffic.All_Traffic.dest",
                "src_port": "Network_Traffic.All_Traffic.src_port",
                "dest_port": "Network_Traffic.All_Traffic.dest_port",
                "action": "Network_Traffic.All_Traffic.action",
                "protocol": "Network_Traffic.All_Traffic.transport",
                "bytes": "Network_Traffic.All_Traffic.bytes",
                "packets": "Network_Traffic.All_Traffic.packets",
            }
        },
        "Authentication": {
            "indicators": ["auth", "login", "logon", "4624", "4625", "4634", "wineventlog"],
            "dataset": "Authentication",
            "fields": {
                "user": "Authentication.Authentication.user",
                "src": "Authentication.Authentication.src",
                "dest": "Authentication.Authentication.dest",
                "action": "Authentication.Authentication.action",
                "app": "Authentication.Authentication.app",
            }
        },
        "Web": {
            "indicators": ["proxy", "web", "http", "url", "uri"],
            "dataset": "Web",
            "fields": {
                "url": "Web.Web.url",
                "uri_path": "Web.Web.uri_path",
                "status": "Web.Web.status",
                "http_method": "Web.Web.http_method",
                "src": "Web.Web.src",
                "dest": "Web.Web.dest",
            }
        },
        "Endpoint": {
            "indicators": ["process", "endpoint", "sysmon", "edr"],
            "dataset": "Processes",
            "fields": {
                "process_name": "Endpoint.Processes.process_name",
                "process_path": "Endpoint.Processes.process_path",
                "user": "Endpoint.Processes.user",
                "dest": "Endpoint.Processes.dest",
                "parent_process": "Endpoint.Processes.parent_process_name",
            }
        },
        "Change": {
            "indicators": ["change", "config", "audit"],
            "dataset": "All_Changes",
            "fields": {
                "user": "Change.All_Changes.user",
                "object": "Change.All_Changes.object",
                "action": "Change.All_Changes.action",
            }
        }
    }

    @classmethod
    def register_cim_models(cls, models: Dict[str, Dict]) -> None:
        """
        Register additional CIM data models from org config.

        Args:
            models: Dict mapping model name to model definition.
                    Each definition must have: indicators, dataset, fields.
        """
        for name, model_def in models.items():
            cls.CIM_MODELS[name] = model_def
        logger.debug(f"Registered {len(models)} additional CIM models: {list(models.keys())}")

    # Commands that BLOCK tstats conversion
    BLOCKING_COMMANDS = {
        "streamstats",  # Per-event running calculations
        "eventstats",   # Per-event aggregation (adds to each event)
        "transaction",  # Groups events into transactions
        "rex",          # Search-time field extraction
        "spath",        # JSON/XML extraction
        "mvexpand",     # Multivalue expansion
        "accum",        # Running totals
    }

    # Aggregation commands that CAN be converted
    AGGREGATION_COMMANDS = {"stats", "timechart", "chart", "top", "rare", "sistats", "sitimechart"}

    # tstats-supported aggregation functions
    TSTATS_FUNCTIONS = {"count", "sum", "avg", "min", "max", "dc", "values", "list", "earliest", "latest"}

    @classmethod
    def parse_query(cls, query: str, expand_macros: bool = True) -> ParsedQuery:
        """
        Parse a SPL query into its structural components.

        Args:
            query: Raw SPL query string
            expand_macros: Whether to expand macros if definitions are available

        Returns:
            ParsedQuery object with all components extracted
        """
        parsed = ParsedQuery()
        query = query.strip()

        # Step 1: Strip triple-backtick comments
        query, parsed.comments = cls.strip_comments(query)
        if parsed.comments:
            logger.debug(f"Stripped {len(parsed.comments)} comments")

        # Step 2: Detect macros (single backticks)
        parsed.macros = cls.detect_macros(query)
        if parsed.macros:
            logger.debug(f"Found {len(parsed.macros)} macros: {[m.name for m in parsed.macros]}")

            # Add warnings about macros that might contain index definitions
            macro_warnings = cls.check_macro_index_risk(parsed.macros)
            for warning in macro_warnings:
                parsed.blockers.append(warning)

        # Step 3: Expand macros if definitions are available
        if expand_macros and parsed.macros:
            query = cls.expand_macros(query, parsed.macros)

        # Step 4: Check if query is already tstats
        query_lower = query.lower().strip()
        if query_lower.startswith('| tstats') or query_lower.startswith('tstats'):
            parsed.is_tstats = True
            logger.debug("Query is already tstats")

        # Split into pipeline stages
        # Handle continuation lines and quoted strings
        stages = cls._split_pipeline(query)

        if not stages:
            return parsed

        # Parse initial search (first stage)
        initial_search = stages[0]
        cls._parse_initial_search(initial_search, parsed)

        # Parse pipeline commands
        for stage in stages[1:]:
            cmd_info = cls._parse_command(stage)
            if cmd_info:
                parsed.commands.append(cmd_info)

                # Track aggregation info
                cmd_name = cmd_info.get("command", "").lower()
                if cmd_name in cls.AGGREGATION_COMMANDS:
                    parsed.aggregation_cmd = cmd_name
                    parsed.aggregation_funcs = cmd_info.get("functions", [])
                    parsed.by_fields = cmd_info.get("by_fields", [])
                    parsed.time_span = cmd_info.get("span")

                # Track blockers
                if cmd_name in cls.BLOCKING_COMMANDS:
                    parsed.blockers.append(f"Uses {cmd_name} (requires per-event processing)")

                # Track all fields
                parsed.all_fields.update(cmd_info.get("fields", []))

        return parsed

    @classmethod
    def _split_pipeline(cls, query: str) -> List[str]:
        """Split query into pipeline stages, respecting quotes and brackets."""
        stages = []
        current = []
        depth = 0  # Track bracket depth for subsearches
        in_quote = False
        quote_char = None

        i = 0
        while i < len(query):
            char = query[i]

            # Handle quotes
            if char in '"\'`' and (i == 0 or query[i-1] != '\\'):
                if not in_quote:
                    in_quote = True
                    quote_char = char
                elif char == quote_char:
                    in_quote = False
                    quote_char = None

            # Handle brackets (subsearches)
            if not in_quote:
                if char == '[':
                    depth += 1
                elif char == ']':
                    depth -= 1
                elif char == '|' and depth == 0:
                    # Pipeline separator
                    stage = ''.join(current).strip()
                    if stage:
                        stages.append(stage)
                    current = []
                    i += 1
                    continue

            current.append(char)
            i += 1

        # Add final stage
        stage = ''.join(current).strip()
        if stage:
            stages.append(stage)

        return stages

    @classmethod
    def _parse_initial_search(cls, search: str, parsed: ParsedQuery):
        """Parse the initial search stage (before first pipe)."""
        # Remove leading 'search' command if present
        search = re.sub(r'^\s*search\s+', '', search, flags=re.IGNORECASE)

        # Extract index
        for match in re.finditer(r'index\s*=\s*["\']?([^\s"\']+)["\']?', search, re.IGNORECASE):
            parsed.indexes.append(match.group(1))

        # Extract sourcetype
        for match in re.finditer(r'sourcetype\s*=\s*["\']?([^\s"\']+)["\']?', search, re.IGNORECASE):
            parsed.sourcetypes.append(match.group(1))

        # Extract source
        for match in re.finditer(r'(?<!source)source\s*=\s*["\']?([^\s"\']+)["\']?', search, re.IGNORECASE):
            parsed.sources.append(match.group(1))

        # Extract host
        for match in re.finditer(r'host\s*=\s*["\']?([^\s"\']+)["\']?', search, re.IGNORECASE):
            parsed.hosts.append(match.group(1))

        # Extract unit_id (organization-specific)
        for match in re.finditer(r'unit_id\s*=\s*["\']?([^\s"\']+)["\']?', search, re.IGNORECASE):
            parsed.unit_ids.append(match.group(1))

        # Extract circuit (organization-specific)
        for match in re.finditer(r'circuit\s*=\s*["\']?([^\s"\']+)["\']?', search, re.IGNORECASE):
            parsed.circuits.append(match.group(1))

        # Extract time range
        earliest_match = re.search(r'earliest\s*=\s*([^\s]+)', search, re.IGNORECASE)
        if earliest_match:
            parsed.earliest = earliest_match.group(1)

        latest_match = re.search(r'latest\s*=\s*([^\s]+)', search, re.IGNORECASE)
        if latest_match:
            parsed.latest = latest_match.group(1)

        # Extract other search terms (key=value and free text)
        cls._extract_search_terms(search, parsed)

    @classmethod
    def _extract_search_terms(cls, search: str, parsed: ParsedQuery):
        """Extract search terms (key=value pairs and free text keywords)."""
        # Remove already-parsed fields
        cleaned = search
        for pattern in [
            r'index\s*=\s*["\']?[^\s"\']+["\']?',
            r'sourcetype\s*=\s*["\']?[^\s"\']+["\']?',
            r'(?<!source)source\s*=\s*["\']?[^\s"\']+["\']?',
            r'host\s*=\s*["\']?[^\s"\']+["\']?',
            r'unit_id\s*=\s*["\']?[^\s"\']+["\']?',
            r'circuit\s*=\s*["\']?[^\s"\']+["\']?',
            r'earliest\s*=\s*[^\s]+',
            r'latest\s*=\s*[^\s]+',
        ]:
            cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

        # Detect NOT conditions - these are blockers for tstats TERM filtering
        not_patterns = [
            r'\bNOT\s+\w+\s*=',  # NOT field=value
            r'\bNOT\s+\w+',      # NOT keyword
        ]
        for pattern in not_patterns:
            if re.search(pattern, cleaned, re.IGNORECASE):
                parsed.blockers.append("NOT conditions cannot be negated with TERM() in tstats")
                break

        # Detect OR conditions for grouping
        or_group_id = 0
        or_matches = list(re.finditer(r'(\w+\s*=\s*[^\s]+)\s+OR\s+(\w+\s*=\s*[^\s]+)', cleaned, re.IGNORECASE))

        # Extract key=value pairs
        for match in re.finditer(r'(\w+)\s*([!=<>]+)\s*["\']?([^\s"\']+)["\']?', cleaned):
            field_name = match.group(1)
            operator = match.group(2)
            value = match.group(3)

            # Skip if it's an index-time field we already parsed
            if field_name.lower() in {'index', 'sourcetype', 'source', 'host', 'unit_id', 'circuit', 'earliest', 'latest'}:
                continue

            # Check if this term is part of an OR group
            is_or_term = False
            current_or_group = 0
            for i, or_match in enumerate(or_matches):
                if match.group(0) in or_match.group(0):
                    is_or_term = True
                    current_or_group = i + 1
                    break

            # Detect comparison operators (>, <, >=, <=) vs equality (=, !=)
            is_comparison = operator in ['>', '<', '>=', '<=']

            term = SearchTerm(
                raw=match.group(0),
                field=field_name,
                value=value,
                operator=operator,
                is_negated=(operator in ['!=', 'NOT']),
                has_wildcard=('*' in value or '?' in value),
                is_or_group=is_or_term,
                or_group_id=current_or_group,
                is_comparison=is_comparison,
            )

            # Determine wildcard position
            if term.has_wildcard:
                if value.startswith('*') and value.endswith('*'):
                    term.wildcard_position = "middle"
                elif value.endswith('*'):
                    term.wildcard_position = "suffix"
                elif value.startswith('*'):
                    term.wildcard_position = "prefix"

            # Comparison operators are blockers for tstats
            if is_comparison:
                parsed.blockers.append(f"Comparison '{term.raw}' cannot be converted to tstats TERM/PREFIX")
            # Negated terms are blockers
            elif term.is_negated:
                parsed.blockers.append(f"Negated term '{term.raw}' cannot be converted to tstats")

            parsed.search_terms.append(term)
            parsed.all_fields.add(field_name)

        # Extract free text keywords (quoted strings and single words)
        # Remove the key=value pairs first
        text_only = re.sub(r'\w+\s*[!=<>]+\s*["\']?[^\s"\']+["\']?', '', cleaned)

        # Find quoted strings
        for match in re.finditer(r'"([^"]+)"', text_only):
            term = SearchTerm(raw=match.group(0), field=None, value=match.group(1))
            parsed.search_terms.append(term)

        # Find remaining keywords (excluding common SPL operators)
        text_only = re.sub(r'"[^"]+"', '', text_only)  # Remove quoted strings
        skip_words = {'and', 'or', 'not', 'in', 'by', 'as', 'over', 'where'}
        for word in text_only.split():
            word = word.strip('()[]')
            if word and word.lower() not in skip_words and not word.startswith('`'):
                if '*' in word:
                    term = SearchTerm(raw=word, field=None, value=word, has_wildcard=True)
                    if word.startswith('*') and word.endswith('*'):
                        term.wildcard_position = "middle"
                    elif word.endswith('*'):
                        term.wildcard_position = "suffix"
                    elif word.startswith('*'):
                        term.wildcard_position = "prefix"
                else:
                    term = SearchTerm(raw=word, field=None, value=word)
                parsed.search_terms.append(term)

    @classmethod
    def _parse_command(cls, stage: str) -> Optional[Dict]:
        """Parse a pipeline command stage."""
        stage = stage.strip()
        if not stage:
            return None

        # Extract command name
        match = re.match(r'(\w+)', stage)
        if not match:
            return None

        cmd_name = match.group(1).lower()
        result = {"command": cmd_name, "raw": stage, "fields": [], "functions": []}

        # Parse stats/timechart/chart commands
        if cmd_name in cls.AGGREGATION_COMMANDS:
            # Extract functions (count, sum, avg, etc.)
            for func_match in re.finditer(r'(\w+)\s*\(([^)]*)\)', stage):
                func_name = func_match.group(1).lower()
                func_arg = func_match.group(2).strip()
                if func_name in cls.TSTATS_FUNCTIONS or func_name in {'count', 'dc', 'sum', 'avg', 'min', 'max'}:
                    result["functions"].append(func_name)
                    if func_arg and func_arg != '*':
                        result["fields"].append(func_arg)

            # Extract BY fields
            by_match = re.search(r'\bby\s+(.+?)(?:\s*$|\s*\|)', stage, re.IGNORECASE)
            if by_match:
                by_clause = by_match.group(1)
                by_fields = [f.strip() for f in re.split(r'[,\s]+', by_clause) if f.strip()]
                result["by_fields"] = by_fields
                result["fields"].extend(by_fields)

            # Extract span for timechart
            span_match = re.search(r'span\s*=\s*(\d+[smhd])', stage, re.IGNORECASE)
            if span_match:
                result["span"] = span_match.group(1)

        # Parse eval commands for field references
        elif cmd_name == 'eval':
            # Extract field names from eval expressions
            for field_match in re.finditer(r'\b([a-zA-Z_]\w*)\s*=', stage):
                result["fields"].append(field_match.group(1))

        # Parse where commands
        elif cmd_name == 'where':
            for field_match in re.finditer(r'\b([a-zA-Z_]\w*)\s*[<>=!]', stage):
                field_name = field_match.group(1)
                if field_name not in {'and', 'or', 'not', 'in', 'like'}:
                    result["fields"].append(field_name)

        return result

    @classmethod
    def detect_data_model(cls, parsed: ParsedQuery) -> Optional[str]:
        """Detect appropriate CIM data model based on query content."""
        # Build indicator string from query components
        # NOTE: Don't include index names - they're arbitrary and could false-match
        # (e.g., "index=web" doesn't mean Web data model)
        indicators = []
        indicators.extend(parsed.sourcetypes)  # sourcetypes are strong indicators
        indicators.extend([t.value.lower() for t in parsed.search_terms])
        indicators.extend([f.lower() for f in parsed.all_fields])

        indicator_text = ' '.join(indicators).lower()

        # Score each data model
        best_model = None
        best_score = 0

        for model_name, model_info in cls.CIM_MODELS.items():
            score = sum(1 for ind in model_info["indicators"] if ind in indicator_text)
            # Bonus for field matches
            score += sum(0.5 for f in parsed.all_fields if f in model_info["fields"])

            if score > best_score:
                best_score = score
                best_model = model_name

        # Require at least 2 indicators to use a data model (avoid false matches)
        return best_model if best_score >= 2 else None

    # Functions supported by raw tstats (without data model)
    RAW_TSTATS_FUNCTIONS = {"count", "sum", "dc"}

    # Functions supported by tstats with data model (summariesonly=t)
    DATAMODEL_TSTATS_FUNCTIONS = {"count", "sum", "dc", "avg", "min", "max", "values", "list", "earliest", "latest"}

    @classmethod
    def optimize(cls, query: str, use_datamodel: bool = True, expand_macros: bool = True) -> OptimizedQuery:
        """
        Optimize a SPL query by converting to tstats where possible.

        Args:
            query: Original SPL query
            use_datamodel: Whether to use CIM data models (default True)
            expand_macros: Whether to expand macros if definitions available

        Returns:
            OptimizedQuery with status, optimized query, and explanation
        """
        # Parse the query (this now handles comments and macros)
        parsed = cls.parse_query(query, expand_macros=expand_macros)

        # If query is already tstats, return as-is
        if parsed.is_tstats:
            return OptimizedQuery(
                status=ConversionStatus.FULL,
                strategy=OptimizationStrategy.PURE_TSTATS,
                original=query,
                optimized=query,
                explanation="Query is already using tstats - no optimization needed.",
                performance_notes=["Query already uses tstats for efficient aggregation."],
            )

        # Check for unexpanded macros - these are warnings, not hard blockers
        macro_warnings = []
        unexpanded_macros = [m for m in parsed.macros if m.expanded is None]
        if unexpanded_macros:
            macro_names = ', '.join(f'`{m.name}`' for m in unexpanded_macros)
            macro_warnings.append(
                f"Query contains unexpanded macros: {macro_names}. "
                f"Optimization may be incomplete if macros contain index/sourcetype definitions."
            )

        # Note: Fieldless/free-text terms CAN be converted to TERM(keyword) in tstats
        # Example: "error" → TERM(error)
        # Only block if there are fieldless terms with unsupported patterns (middle/prefix wildcards)
        blocked_fieldless = [
            t.raw for t in parsed.search_terms
            if not t.field and t.wildcard_position in ("middle", "prefix")
        ]
        if blocked_fieldless:
            return OptimizedQuery(
                status=ConversionStatus.IMPOSSIBLE,
                strategy=OptimizationStrategy.REFUSED,
                original=query,
                optimized=query,
                explanation="Query contains wildcard terms that require raw event scanning: "
                            + "; ".join(blocked_fieldless),
                blockers=["Middle/prefix wildcards in free-text terms require raw event scanning"]
            )

        # Check for hard blockers (exclude macro warnings which are soft warnings)
        hard_blockers = [b for b in parsed.blockers if 'Macro' not in b and 'macro' not in b]
        if hard_blockers:
            return OptimizedQuery(
                status=ConversionStatus.IMPOSSIBLE,
                strategy=OptimizationStrategy.REFUSED,
                original=query,
                optimized=query,
                explanation="Query cannot be converted to tstats due to: " + "; ".join(hard_blockers),
                blockers=hard_blockers
            )

        # Check if query has aggregation
        if not parsed.aggregation_cmd:
            return OptimizedQuery(
                status=ConversionStatus.IMPOSSIBLE,
                strategy=OptimizationStrategy.REFUSED,
                original=query,
                optimized=query,
                explanation="Query does not contain aggregation (stats/timechart/chart). tstats is only for aggregation queries.",
                blockers=["No aggregation command found"]
            )

        # Check for wildcards that cannot be converted to tstats
        # - Middle wildcards (*value*): Cannot use TERM() or PREFIX()
        # - Prefix wildcards (*value): Cannot use TERM() or PREFIX()
        # - Suffix wildcards (value*): OK - can use PREFIX()
        unconvertible_wildcards = [
            t for t in parsed.search_terms
            if t.wildcard_position in ("middle", "prefix")
        ]
        if unconvertible_wildcards:
            wildcard_details = [f"{t.raw} ({t.wildcard_position} wildcard)" for t in unconvertible_wildcards]
            return OptimizedQuery(
                status=ConversionStatus.IMPOSSIBLE,
                strategy=OptimizationStrategy.REFUSED,
                original=query,
                optimized=query,
                explanation=f"Query contains wildcards that require raw event scanning: {wildcard_details}. "
                           f"Only suffix wildcards (value*) can use tstats PREFIX().",
                blockers=["Middle/prefix wildcards require raw event scanning - tstats cannot be used"]
            )

        # Check if a data model would be needed for the aggregation functions
        data_model = cls.detect_data_model(parsed) if use_datamodel else None

        # Validate aggregation functions
        if parsed.aggregation_funcs:
            for func in parsed.aggregation_funcs:
                func_name = func.split("(")[0].strip().lower()
                if data_model:
                    if func_name not in cls.DATAMODEL_TSTATS_FUNCTIONS:
                        return OptimizedQuery(
                            status=ConversionStatus.IMPOSSIBLE,
                            strategy=OptimizationStrategy.REFUSED,
                            original=query,
                            optimized=query,
                            explanation=f"Aggregation function '{func_name}' is not supported by tstats. "
                                        f"Supported: {', '.join(sorted(cls.DATAMODEL_TSTATS_FUNCTIONS))}",
                            blockers=[f"'{func_name}' not available in tstats"]
                        )
                else:
                    # Without data model, only count/sum/dc are supported
                    if func_name not in cls.RAW_TSTATS_FUNCTIONS:
                        return OptimizedQuery(
                            status=ConversionStatus.IMPOSSIBLE,
                            strategy=OptimizationStrategy.REFUSED,
                            original=query,
                            optimized=query,
                            explanation=f"Aggregation function '{func_name}' requires raw event access. "
                                        f"Raw tstats only supports: {', '.join(sorted(cls.RAW_TSTATS_FUNCTIONS))}",
                            blockers=[f"'{func_name}' not available in raw tstats (no data model)"]
                        )

        # Build the tstats query
        tstats_parts = ["| tstats"]
        performance_notes = []
        assumptions = []

        # Determine strategy based on BY fields
        # TSTATS-safe metadata fields
        METADATA_FIELDS = {"host", "source", "sourcetype", "index", "_time", "splunk_server"}

        # data_model was already determined during function validation above

        # Classify BY fields
        by_fields_metadata = []  # Can use directly
        by_fields_unsafe = []    # Cannot use in tstats

        for field in parsed.by_fields:
            field_lower = field.lower()
            if field_lower in METADATA_FIELDS:
                by_fields_metadata.append(field)
            elif data_model and field in cls.CIM_MODELS.get(data_model, {}).get("fields", {}):
                by_fields_metadata.append(field)  # Datamodel field
            else:
                by_fields_unsafe.append(field)
                assumptions.append(f"Leaving '{field}' to post-aggregation (not metadata or datamodel field)")

        # If BY contains non-metadata fields, refuse conversion to avoid invalid tstats output
        if by_fields_unsafe:
            return OptimizedQuery(
                status=ConversionStatus.IMPOSSIBLE,
                strategy=OptimizationStrategy.REFUSED,
                original=query,
                optimized=query,
                explanation="BY clause has non-metadata fields that tstats cannot group without losing data: "
                            + ", ".join(by_fields_unsafe),
                blockers=["Non-metadata BY fields require raw search aggregation"]
            )

        # Determine strategy
        if data_model:
            strategy = OptimizationStrategy.DATAMODEL
        else:
            strategy = OptimizationStrategy.PURE_TSTATS

        # Build query based on strategy
        if data_model:
            model_info = cls.CIM_MODELS[data_model]
            tstats_parts.append("summariesonly=t")
            performance_notes.append(f"Using CIM data model {data_model} for pre-computed summaries")

            # Add aggregation functions
            funcs = parsed.aggregation_funcs or ["count"]
            tstats_parts.append(funcs[0] if len(funcs) == 1 else ', '.join(funcs))

            # Add data model
            tstats_parts.append(f"from datamodel={data_model}.{model_info['dataset']}")
            tstats_parts.append("where")
        else:
            # Raw index tstats
            funcs = parsed.aggregation_funcs or ["count"]
            tstats_parts.append(funcs[0] if len(funcs) == 1 else ', '.join(funcs))
            tstats_parts.append("where")

            # Add index filters
            if parsed.indexes:
                if len(parsed.indexes) == 1:
                    tstats_parts.append(f"index={parsed.indexes[0]}")
                else:
                    tstats_parts.append(f"index IN ({', '.join(parsed.indexes)})")

            if parsed.sourcetypes:
                if len(parsed.sourcetypes) == 1:
                    tstats_parts.append(f"sourcetype={parsed.sourcetypes[0]}")

        # Add TERM() and PREFIX() filters, handling OR groups
        or_groups: Dict[int, List[str]] = {}  # group_id -> list of filters
        regular_filters: List[str] = []

        for term in parsed.search_terms:
            # Skip negated terms (already flagged as blockers)
            if term.is_negated:
                continue

            filter_str = term.to_tstats_filter()
            if filter_str:
                if term.is_or_group and term.or_group_id > 0:
                    # Collect OR group terms
                    if term.or_group_id not in or_groups:
                        or_groups[term.or_group_id] = []
                    or_groups[term.or_group_id].append(filter_str)
                else:
                    regular_filters.append(filter_str)

                if "PREFIX" in filter_str:
                    performance_notes.append(f"Using PREFIX() for prefix matching: {term.raw}")
                else:
                    performance_notes.append(f"Using TERM() for exact matching: {term.raw}")

        # Add regular filters
        for f in regular_filters:
            tstats_parts.append(f)

        # Add OR group filters with parentheses
        for group_id, filters in or_groups.items():
            if len(filters) > 1:
                or_clause = f"({' OR '.join(filters)})"
                tstats_parts.append(or_clause)
                performance_notes.append(f"OR condition preserved with parentheses: {or_clause}")
            elif filters:
                tstats_parts.append(filters[0])

        # Add unit_id filter (organization-specific)
        if parsed.unit_ids:
            if len(parsed.unit_ids) == 1:
                tstats_parts.append(f"TERM(unit_id={parsed.unit_ids[0]})")
            else:
                for uid in parsed.unit_ids:
                    tstats_parts.append(f"TERM(unit_id={uid})")

        # Add time range
        tstats_parts.append(f"earliest={parsed.earliest} latest={parsed.latest}")

        # Build BY clause based on strategy
        if parsed.by_fields:
            by_clause_parts = []

            if data_model:
                # Map fields to data model
                model_info = cls.CIM_MODELS[data_model]
                for f in parsed.by_fields:
                    if f == "_time":
                        by_clause_parts.append("_time")
                    elif f in model_info["fields"]:
                        by_clause_parts.append(model_info["fields"][f])
                    else:
                        by_clause_parts.append(f)
            elif strategy == OptimizationStrategy.TWO_PHASE:
                # Keep only tstats-safe metadata in pre-aggregation; rest handled later
                by_clause_parts = [f for f in by_fields_metadata]
                if by_fields_unsafe:
                    performance_notes.append(
                        "Left non-metadata BY fields for post-aggregation to avoid invalid tstats BY"
                    )
            else:
                # Pure tstats - use fields directly
                by_clause_parts = parsed.by_fields.copy()

            # Add time span if present
            if parsed.time_span:
                # Find _time and add span
                for i, f in enumerate(by_clause_parts):
                    if f == "_time" or f.startswith("_time"):
                        by_clause_parts[i] = f"_time span={parsed.time_span}"
                        break
                else:
                    # No _time found but we have span (timechart)
                    if parsed.aggregation_cmd == "timechart":
                        by_clause_parts.insert(0, f"_time span={parsed.time_span}")
            elif parsed.aggregation_cmd == "timechart":
                # timechart implies _time grouping
                span = parsed.time_span or "1m"
                by_clause_parts.insert(0, f"_time span={span}")

            if by_clause_parts:
                tstats_parts.append("BY " + ", ".join(by_clause_parts))

        # Build final query
        optimized_query = " ".join(tstats_parts)

        # Add post-aggregation commands that couldn't be converted
        post_commands = []
        for cmd in parsed.commands:
            cmd_name = cmd.get("command", "").lower()
            if cmd_name not in cls.AGGREGATION_COMMANDS:
                post_commands.append("| " + cmd["raw"])
            elif strategy == OptimizationStrategy.TWO_PHASE and cmd_name in cls.AGGREGATION_COMMANDS:
                # Re-apply original aggregation to restore BY fields dropped from tstats
                post_commands.append("| " + cmd["raw"])

        if post_commands:
            optimized_query += "\n" + "\n".join(post_commands)

        # Add macro warnings to performance notes
        if macro_warnings:
            performance_notes.extend(macro_warnings)

        return OptimizedQuery(
            status=ConversionStatus.FULL if not post_commands else ConversionStatus.PARTIAL,
            strategy=strategy,
            original=query,
            optimized=optimized_query,
            explanation=f"Converted using {strategy.value}" + (f" with {data_model}" if data_model else ""),
            performance_notes=performance_notes,
            assumptions=assumptions
        )

    @classmethod
    def explain_optimization(cls, result: OptimizedQuery) -> str:
        """Generate a human-readable explanation of the optimization."""
        lines = []

        lines.append("## Query Optimization Analysis")
        lines.append("")
        lines.append(f"**Status:** {result.status.value.title()}")
        lines.append(f"**Strategy:** {result.strategy.value}")
        lines.append("")

        if result.blockers:
            lines.append("### ⚠️ Conversion Blockers:")
            for blocker in result.blockers:
                lines.append(f"- {blocker}")
            lines.append("")

        if result.assumptions:
            lines.append("### Assumptions:")
            for assumption in result.assumptions:
                lines.append(f"- {assumption}")
            lines.append("")

        if result.status != ConversionStatus.IMPOSSIBLE:
            lines.append("### Original Query:")
            lines.append("```spl")
            lines.append(result.original)
            lines.append("```")
            lines.append("")

            lines.append("### Optimized Query:")
            lines.append("```spl")
            lines.append(result.optimized)
            lines.append("```")
            lines.append("")

            if result.performance_notes:
                lines.append("### Performance Improvements:")
                for note in result.performance_notes:
                    lines.append(f"- {note}")
                lines.append("")

            lines.append("### Why This is Faster:")
            lines.append("- **tstats** reads pre-computed index summaries instead of scanning raw events")
            lines.append("- **TERM()** filters at the tsidx (index) level — 10-100x faster than wildcards")
            lines.append("- **PREFIX()** enables efficient prefix matching at index level")
            if result.strategy == OptimizationStrategy.DATAMODEL:
                lines.append("- **summariesonly=t** uses pre-accelerated data model summaries")

        lines.append("")
        lines.append("### Quick Reference:")
        lines.append("```")
        lines.append("TERM(x)      = exact match on indexed token")
        lines.append("TERM(k=v)    = exact match on indexed k=v token")
        lines.append("PREFIX(k=v)  = matches tokens starting with k=v")
        lines.append("BY PREFIX(k=) -> needs | rename \"*=\" AS \"*\"")
        lines.append("```")

        return "\n".join(lines)


# Example usage and testing
if __name__ == "__main__":
    test_queries = [
        # Simple stats → tstats
        "index=firewall action=denied earliest=-4h latest=now | stats count by src_ip, dest_ip",

        # Timechart conversion
        "index=wineventlog EventCode=4625 earliest=-24h latest=now | timechart span=1h count by user",

        # IP prefix matching
        "index=network src_ip=10.1.* dest_ip=192.168.* earliest=-1h latest=now | stats count by src_ip",

        # Cannot convert (streamstats)
        "index=network earliest=-1h latest=now | sort _time | streamstats count as running by src_ip",

        # Partial conversion (post-processing)
        "index=firewall action=denied earliest=-4h | stats count by src_ip | where count > 100 | eval risk=if(count>1000,\"critical\",\"high\")",
    ]

    print("=" * 80)
    print("SPL QUERY OPTIMIZER TEST")
    print("=" * 80)

    for query in test_queries:
        print(f"\n{'─' * 80}")
        print(f"Input: {query[:70]}...")
        print()

        result = SPLQueryOptimizer.optimize(query)
        print(SPLQueryOptimizer.explain_optimization(result))
