"""
SPL Query Validator - Validates and analyzes Splunk SPL queries.

Provides:
1. Local syntax validation (no Splunk connection required)
2. Risk scoring based on query patterns (inspired by Splunk MCP Server guardrails)
3. Performance analysis and recommendations
4. Optional Splunk REST API validation (requires connection)

References:
- Splunk MCP Server guardrails: https://github.com/splunk/splunk-mcp-server2
- Splunk REST API /services/search/parser endpoint
- Splunk SDK for Python: https://github.com/splunk/splunk-sdk-python
"""

from __future__ import annotations

import os
import logging
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from shared.constants import (
    DANGEROUS_COMMANDS,
    EXPENSIVE_COMMAND_RISKS,
    INVALID_PATTERNS,
    KNOWN_COMMANDS,
    TSTATS_BLOCKERS,
    TSTATS_OPPORTUNITY_COMMANDS,
    TIME_UNITS,
)
from shared.utils import (
    extract_earliest_latest,
    extract_indexes,
    extract_sourcetypes,
    parse_relative_time,
    split_pipeline,
)

logger = logging.getLogger(__name__)


class RiskLevel(Enum):
    """Risk level classification."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ValidationStatus(Enum):
    """Validation result status."""
    VALID = "valid"
    WARNING = "warning"
    ERROR = "error"
    BLOCKED = "blocked"


@dataclass
class ValidationResult:
    """Result of SPL query validation."""
    status: ValidationStatus
    risk_level: RiskLevel
    risk_score: int  # 0-100
    query: str
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    parsed_components: Dict = field(default_factory=dict)


class SPLValidator:
    """
    Validates SPL queries for syntax, risk, and performance.

    Can work offline (local validation) or with Splunk connection (API validation).
    """

    # Registered custom commands from commands.conf (set externally)
    _custom_commands: set = set()

    # Safe time range threshold (in seconds) — default 7 days
    SAFE_TIME_RANGE = int(os.getenv("SPL_SAFE_TIME_RANGE", 7 * 86400))

    # Risk score threshold for blocking
    BLOCK_THRESHOLD = int(os.getenv("SPL_BLOCK_THRESHOLD", 80))

    @classmethod
    def register_custom_commands(cls, commands: set) -> None:
        """Register custom commands from commands.conf files."""
        cls._custom_commands = commands

    @classmethod
    def is_known_command(cls, cmd: str) -> bool:
        """Check if a command is known (built-in or custom)."""
        return cmd in KNOWN_COMMANDS or cmd in cls._custom_commands

    @classmethod
    def validate(cls, query: str, block_dangerous: bool = True) -> ValidationResult:
        """
        Validate an SPL query for syntax, risk, and performance.

        Args:
            query: SPL query string
            block_dangerous: If True, block queries exceeding risk threshold

        Returns:
            ValidationResult with status, risk score, and recommendations
        """
        query = query.strip()
        result = ValidationResult(
            status=ValidationStatus.VALID,
            risk_level=RiskLevel.LOW,
            risk_score=0,
            query=query
        )

        if not query:
            result.status = ValidationStatus.ERROR
            result.errors.append("Empty query")
            return result

        # Parse the query
        components = cls._parse_query(query)
        result.parsed_components = components

        # Run all validation checks
        cls._check_syntax(query, components, result)
        cls._check_time_range(components, result)
        cls._check_index_usage(components, result)
        cls._check_expensive_commands(components, result)
        cls._check_dangerous_commands(components, result)
        cls._check_tstats_syntax(query, components, result)
        cls._check_optimization_opportunities(components, result)

        # Calculate final risk level
        if result.risk_score >= 80:
            result.risk_level = RiskLevel.CRITICAL
        elif result.risk_score >= 50:
            result.risk_level = RiskLevel.HIGH
        elif result.risk_score >= 25:
            result.risk_level = RiskLevel.MEDIUM
        else:
            result.risk_level = RiskLevel.LOW

        # Determine final status
        if result.errors:
            result.status = ValidationStatus.ERROR
        elif block_dangerous and result.risk_score >= cls.BLOCK_THRESHOLD:
            result.status = ValidationStatus.BLOCKED
            result.errors.append(f"Query blocked: risk score {result.risk_score} exceeds threshold {cls.BLOCK_THRESHOLD}")
        elif result.warnings:
            result.status = ValidationStatus.WARNING

        return result

    @classmethod
    def validate_simple(cls, query: str) -> Tuple[bool, List[str]]:
        """
        Simple validation returning (is_valid, errors) tuple.

        Backward compatible with old API.

        Args:
            query: SPL query string to validate

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        result = cls.validate(query, block_dangerous=False)
        errors = result.errors + [f"Warning: {w}" for w in result.warnings]
        return result.status != ValidationStatus.ERROR, errors

    @classmethod
    def _parse_query(cls, query: str) -> Dict:
        """Parse query into components using shared utilities."""
        indexes, has_wildcard = extract_indexes(query)
        sourcetypes = extract_sourcetypes(query)
        earliest, latest = extract_earliest_latest(query)

        components = {
            "raw": query,
            "commands": [],
            "indexes": indexes,
            "sourcetypes": sourcetypes,
            "time_earliest": earliest,
            "time_latest": latest,
            "has_index_wildcard": has_wildcard,
            "has_time_constraint": earliest is not None,
            "uses_tstats": False,
            "uses_datamodel": False,
            "starts_with_pipe": query.lstrip().startswith('|'),
        }

        stages = split_pipeline(query)
        is_first_stage = True
        for stage in stages:
            stage = stage.strip()
            if not stage:
                continue

            match = re.match(r'^\s*(\w+)', stage)
            if match:
                cmd = match.group(1).lower()

                # First stage without leading pipe is a base search, not a command
                if is_first_stage and not components["starts_with_pipe"]:
                    if cmd in ('index', 'sourcetype', 'source', 'host', 'earliest', 'latest'):
                        is_first_stage = False
                        continue
                    if re.match(r'^\w+\s*=', stage):
                        is_first_stage = False
                        continue

                is_first_stage = False

                components["commands"].append({
                    "name": cmd,
                    "raw": stage,
                    "known": cls.is_known_command(cmd),
                    "is_custom": cmd in cls._custom_commands,
                })

                if cmd == "tstats":
                    components["uses_tstats"] = True
                if "datamodel" in stage.lower():
                    components["uses_datamodel"] = True

        return components

    @classmethod
    def _check_syntax(cls, query: str, components: Dict, result: ValidationResult):
        """Check for syntax errors."""
        for pattern, error_msg in INVALID_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                result.errors.append(error_msg)

        # Check for unknown commands
        for cmd_info in components["commands"]:
            if not cmd_info["known"]:
                cmd = cmd_info["name"]
                result.warnings.append(f"Unknown command '{cmd}' - may be custom command or typo")

        # Unbalanced quotes
        for quote in ['"', "'"]:
            if query.count(quote) % 2 != 0:
                result.errors.append(f"Unbalanced {quote} quotes")

        # Unbalanced brackets
        if query.count('[') != query.count(']'):
            result.errors.append("Unbalanced brackets [ ]")
        if query.count('(') != query.count(')'):
            result.errors.append("Unbalanced parentheses ( )")

        # Common mistakes
        if re.search(r'index\s*=\s*\|', query):
            result.errors.append("Invalid syntax: 'index= |' - missing index value")

        if re.search(r'\|\s*\|', query):
            result.errors.append("Invalid syntax: empty pipe stage '| |'")

    @classmethod
    def _check_tstats_syntax(cls, query: str, components: Dict, result: ValidationResult):
        """Check tstats-specific syntax."""
        if not components["uses_tstats"]:
            return

        # tstats is a GENERATING command - it must be the first command in the pipeline.
        # It cannot receive piped input from any search or other command.
        # Valid:   | tstats count where index=network ...
        # Invalid: index=network | tstats count
        # Invalid: index=network | stats count | tstats count
        ql = query.lower().strip()
        tstats_pos = ql.find('tstats')
        if tstats_pos > 0:
            before = ql[:tstats_pos].rstrip()
            # The only valid form is "| tstats" at the very start (optionally with whitespace)
            # If there's anything before "|" that isn't just whitespace, it's an error
            if before != '|':
                # There's content before tstats that isn't just "| "
                # Check if it's a pipe at the end of a base search
                if '|' in before:
                    # Something like "index=network | tstats" or "search | eval | tstats"
                    result.errors.append(
                        "tstats is a generating command - it cannot receive piped input. "
                        "Use '| tstats count where index=... TERM(keyword)' instead"
                    )
                elif before and before != '|':
                    result.errors.append(
                        "tstats must start with '| tstats'. "
                        "Example: | tstats count where index=network TERM(error)"
                    )

        # Check for TERM in BY clause (invalid)
        if re.search(r'\bby\s+.*TERM\s*\(', query, re.IGNORECASE):
            result.errors.append("TERM() is a filter, not a field - cannot use in BY clause")

        # Check for _raw in tstats (invalid)
        if re.search(r'tstats.*\b_raw\b', query, re.IGNORECASE):
            result.errors.append("_raw field is not available in tstats")

        # Check for PREFIX in BY without rename
        if re.search(r'\bby\s+.*PREFIX\s*\([^)]+\)', query, re.IGNORECASE):
            if 'rename' not in query.lower():
                result.warnings.append("PREFIX() in BY clause returns field=value - consider adding '| rename \"*=\" AS \"*\"'")

    @classmethod
    def _check_time_range(cls, components: Dict, result: ValidationResult):
        """Check time range for performance risks."""
        if not components["has_time_constraint"]:
            # Time range is often set via the UI time picker, not in the query itself.
            result.risk_score += 5
            return

        earliest = components["time_earliest"]
        if earliest:
            seconds = parse_relative_time(earliest)
            if seconds is None:
                pass  # Absolute time or unparseable
            elif seconds == 0:
                result.risk_score += 40
                result.warnings.append("'earliest=0' scans all time - very expensive")
            elif abs(seconds) > cls.SAFE_TIME_RANGE:
                days = abs(seconds) / 86400
                result.risk_score += min(30, int(days / 7) * 5)
                result.warnings.append(f"Time range ({days:.1f} days) exceeds safe threshold")

    @classmethod
    def _check_index_usage(cls, components: Dict, result: ValidationResult):
        """Check index usage patterns."""
        if components["has_index_wildcard"]:
            if not components["sourcetypes"]:
                result.risk_score += 25
                result.warnings.append("Using index=* without sourcetype filter - very broad search")
            else:
                result.risk_score += 10
                result.warnings.append("Using index=* - consider specifying exact index")

        if not components["indexes"] and not components["uses_tstats"]:
            result.risk_score += 15
            result.warnings.append("No index specified - will search all allowed indexes")

    @classmethod
    def _check_expensive_commands(cls, components: Dict, result: ValidationResult):
        """Check for expensive commands."""
        for cmd_info in components["commands"]:
            cmd = cmd_info["name"]
            if cmd in EXPENSIVE_COMMAND_RISKS:
                risk_add = EXPENSIVE_COMMAND_RISKS[cmd]
                result.risk_score += risk_add
                result.warnings.append(f"Expensive command '{cmd}' (+{risk_add} risk)")

    @classmethod
    def _check_dangerous_commands(cls, components: Dict, result: ValidationResult):
        """Check for dangerous/modifying commands."""
        for cmd_info in components["commands"]:
            cmd = cmd_info["name"]
            if cmd in DANGEROUS_COMMANDS:
                risk_add = DANGEROUS_COMMANDS[cmd]
                result.risk_score += risk_add
                result.warnings.append(f"Dangerous command '{cmd}' (+{risk_add} risk) — modifies data or executes code")

        raw = components["raw"]
        if re.search(r'outputlookup\s+.*override\s*=\s*true', raw, re.IGNORECASE):
            result.risk_score += 15
            result.warnings.append("outputlookup with override=true can overwrite existing data")

        if re.search(r'collect\s+.*override\s*=\s*true', raw, re.IGNORECASE):
            result.risk_score += 15
            result.warnings.append("collect with override=true can overwrite existing data")

    @classmethod
    def _check_optimization_opportunities(cls, components: Dict, result: ValidationResult):
        """Suggest optimization opportunities."""
        has_aggregation = any(
            cmd["name"] in TSTATS_OPPORTUNITY_COMMANDS
            for cmd in components["commands"]
        )

        if has_aggregation and not components["uses_tstats"]:
            has_blockers = any(
                cmd["name"] in TSTATS_BLOCKERS
                for cmd in components["commands"]
            )

            if not has_blockers:
                result.suggestions.append(
                    "This query may be optimizable with tstats. "
                    "Consider using '| tstats count WHERE ... BY ...' for faster aggregation."
                )

        if components["uses_tstats"]:
            raw = components["raw"]
            if re.search(r'where\s+\w+=\w+', raw, re.IGNORECASE):
                if 'TERM(' not in raw and 'PREFIX(' not in raw:
                    result.suggestions.append(
                        "Consider using TERM(field=value) for exact matching or PREFIX(field=prefix) for prefix matching in tstats WHERE clause. Never use wildcards inside TERM()."
                    )

    @classmethod
    def validate_with_splunk(cls, query: str, host: str, port: int = 8089,
                              username: str = None, password: str = None,
                              token: str = None) -> ValidationResult:
        """
        Validate query using Splunk's REST API /services/search/parser endpoint.

        Args:
            query: SPL query to validate
            host: Splunk server hostname
            port: Splunk management port (default 8089)
            username: Splunk username (or use token)
            password: Splunk password (or use token)
            token: Splunk auth token (alternative to username/password)

        Returns:
            ValidationResult with Splunk's validation response
        """
        result = cls.validate(query, block_dangerous=False)

        try:
            import splunklib.client as client

            if token:
                service = client.connect(host=host, port=port, token=token)
            else:
                service = client.connect(host=host, port=port, username=username, password=password)

            response = service.parse(query, parse_only=True)

            if response and hasattr(response, 'messages'):
                for msg in response.messages:
                    if msg.get('type') == 'ERROR':
                        result.errors.append(f"Splunk: {msg.get('text', 'Unknown error')}")
                        result.status = ValidationStatus.ERROR
                    elif msg.get('type') == 'WARN':
                        result.warnings.append(f"Splunk: {msg.get('text', 'Warning')}")

            result.parsed_components["splunk_validated"] = True
            logger.info("[SPL_VALIDATOR] Splunk validation successful")

        except ImportError:
            result.warnings.append("splunk-sdk not installed - using local validation only")
        except Exception as e:
            result.warnings.append(f"Splunk validation failed: {str(e)} - using local validation only")

        return result

    @classmethod
    def get_corrected_query(cls, query: str) -> str:
        """Attempt to auto-correct common mistakes."""
        corrected = query.strip()

        # Fix missing pipe before tstats
        if re.match(r'^tstats\s+', corrected, re.IGNORECASE):
            corrected = f"| {corrected}"

        # Remove leading "splunk |"
        corrected = re.sub(r'^splunk\s+\|', '|', corrected, flags=re.IGNORECASE)

        # Fix "index network" -> "index=network" (missing = sign)
        corrected = re.sub(
            r'(?<!\w)index\s+(?!=)(\w+)',
            r'index=\1',
            corrected,
            flags=re.IGNORECASE
        )

        # Fix piping into tstats from base search:
        # "index=network error | tstats count ..." -> "| tstats count where index=network TERM(error) ..."
        # This is a fundamentally broken pattern - try to reconstruct as proper tstats
        pipe_tstats_match = re.match(
            r'(.*?)\|\s*tstats\s+(.*)',
            corrected,
            re.IGNORECASE | re.DOTALL,
        )
        if pipe_tstats_match:
            base_search = pipe_tstats_match.group(1).strip()
            tstats_rest = pipe_tstats_match.group(2).strip()
            # Only fix if there's a real base search before the pipe
            if base_search and not base_search.startswith('|'):
                # Try to use the local optimizer to fix it properly
                try:
                    from shared.spl_query_optimizer import SPLQueryOptimizer, ConversionStatus
                    # Reconstruct as search | stats count and optimize
                    reconstructed = base_search
                    if '| stats' not in reconstructed.lower():
                        reconstructed += ' | stats count'
                    opt_result = SPLQueryOptimizer.optimize(reconstructed)
                    if opt_result.status != ConversionStatus.IMPOSSIBLE:
                        corrected = opt_result.optimized
                except Exception:
                    # Fallback: just prefix with pipe
                    corrected = f"| tstats {tstats_rest}"

        return corrected

    @classmethod
    def explain(cls, result: ValidationResult) -> str:
        """Generate human-readable explanation of validation result."""
        lines = []

        status_icons = {
            ValidationStatus.VALID: "OK",
            ValidationStatus.WARNING: "!",
            ValidationStatus.ERROR: "X",
            ValidationStatus.BLOCKED: "BLOCKED",
        }
        icon = status_icons.get(result.status, "?")
        lines.append(f"## SPL Validation: [{icon}] {result.status.value.upper()}")
        lines.append("")

        risk_icons = {
            RiskLevel.LOW: "[LOW]",
            RiskLevel.MEDIUM: "[MEDIUM]",
            RiskLevel.HIGH: "[HIGH]",
            RiskLevel.CRITICAL: "[CRITICAL]",
        }
        risk_icon = risk_icons.get(result.risk_level, "")
        lines.append(f"**Risk Score:** {result.risk_score}/100 {risk_icon}")
        lines.append("")

        if result.errors:
            lines.append("### Errors")
            for err in result.errors:
                lines.append(f"- X {err}")
            lines.append("")

        if result.warnings:
            lines.append("### Warnings")
            for warn in result.warnings:
                lines.append(f"- ! {warn}")
            lines.append("")

        if result.suggestions:
            lines.append("### Optimization Suggestions")
            for sug in result.suggestions:
                lines.append(f"- > {sug}")
            lines.append("")

        if result.parsed_components:
            lines.append("### Query Analysis")
            comp = result.parsed_components
            if comp.get("indexes"):
                lines.append(f"- **Indexes:** {', '.join(comp['indexes'])}")
            if comp.get("sourcetypes"):
                lines.append(f"- **Sourcetypes:** {', '.join(comp['sourcetypes'])}")
            if comp.get("time_earliest"):
                lines.append(f"- **Time Range:** {comp.get('time_earliest')} to {comp.get('time_latest', 'now')}")
            if comp.get("commands"):
                cmd_names = [c["name"] for c in comp["commands"]]
                lines.append(f"- **Commands:** {' | '.join(cmd_names)}")
            if comp.get("uses_tstats"):
                lines.append("- **Uses tstats:** Yes")
            if comp.get("uses_datamodel"):
                lines.append("- **Uses datamodel:** Yes")

        return "\n".join(lines)


# Convenience functions
def validate_spl(query: str) -> ValidationResult:
    """Validate an SPL query."""
    return SPLValidator.validate(query)


def is_valid_spl(query: str) -> bool:
    """Quick check if SPL query is valid."""
    result = SPLValidator.validate(query, block_dangerous=False)
    return result.status != ValidationStatus.ERROR


def get_risk_score(query: str) -> int:
    """Get risk score for an SPL query (0-100)."""
    result = SPLValidator.validate(query, block_dangerous=False)
    return result.risk_score


def validate_spl_response(response: str) -> Tuple[bool, str, List[str]]:
    """
    Validate SPL query from LLM response.

    Args:
        response: Full LLM response text

    Returns:
        Tuple of (is_valid, extracted_query, list_of_errors)
    """
    code_block_match = re.search(r'```(?:spl)?\s*\n(.*?)\n```', response, re.DOTALL)

    if code_block_match:
        query = code_block_match.group(1).strip()
    else:
        lines = response.split('\n')
        query_lines = [line for line in lines if line.strip().startswith('|') or 'index=' in line.lower()]
        query = '\n'.join(query_lines) if query_lines else response

    is_valid, errors = SPLValidator.validate_simple(query)
    return is_valid, query, errors

