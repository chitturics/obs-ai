"""
Robust SPL Analyzer - Comprehensive query validation, analysis, and optimization.

Implements Splunk best practices for:
- Syntax validation (using Splunk REST API /services/search/parser)
- Performance analysis and cost estimation
- Optimization suggestions with auto-fix capability
- Command ordering analysis
- Anti-pattern detection

Sources:
- https://lantern.splunk.com/Platform_Data_Management/Transform_Data/Optimizing_search
- https://docs.splunk.com/Documentation/SplunkCloud/latest/Search/Quicktipsforoptimization
- https://community.splunk.com/t5/Splunk-Dev/Splunk-REST-API-Validate-SPL/m-p/582098
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple

from shared.constants import (
    COMMAND_COSTS,
    GENERATING_COMMANDS,
    KNOWN_COMMANDS,
    STREAMING_COMMANDS,
    TRANSFORMING_COMMANDS,
)
from shared.query_cost_estimator import QueryCostEstimator
from shared.spl_rules import ANTI_PATTERNS, BEST_PRACTICES
from shared.utils import split_pipeline

logger = logging.getLogger(__name__)


class Severity(Enum):
    """Severity levels for issues."""
    CRITICAL = "critical"   # Query won't work or is very slow
    HIGH = "high"          # Significant performance impact
    MEDIUM = "medium"      # Moderate impact
    LOW = "low"           # Minor improvement possible
    INFO = "info"         # Informational


class IssueCategory(Enum):
    """Categories of issues."""
    SYNTAX = "syntax"
    PERFORMANCE = "performance"
    SECURITY = "security"
    BEST_PRACTICE = "best_practice"
    DATA_MODEL = "data_model"


@dataclass
class Issue:
    """A detected issue in the query."""
    category: IssueCategory
    severity: Severity
    message: str
    location: Optional[str] = None  # Where in the query
    suggestion: Optional[str] = None  # How to fix
    auto_fixable: bool = False
    fix_function: Optional[str] = None  # Name of function to auto-fix


@dataclass
class CommandInfo:
    """Information about a parsed command."""
    name: str
    args: str
    position: int
    is_streaming: bool
    is_transforming: bool
    is_generating: bool
    estimated_cost: int  # 1-10, higher = more expensive


@dataclass
class AnalysisResult:
    """Complete analysis result."""
    original_query: str
    is_valid: bool
    normalized_query: Optional[str] = None
    optimized_query: Optional[str] = None
    commands: List[CommandInfo] = field(default_factory=list)
    issues: List[Issue] = field(default_factory=list)
    estimated_cost: int = 0  # 1-100
    optimization_potential: int = 0  # 0-100, higher = more room for improvement
    recommendations: List[str] = field(default_factory=list)
    splunk_validation: Optional[Dict] = None
    parsed_components: Dict[str, Any] = field(default_factory=dict)


class RobustSPLAnalyzer:
    """
    Comprehensive SPL analyzer with validation and optimization.
    """

    # Use centralized constants from shared.constants

    def __init__(self, splunk_host: str = None, splunk_port: int = None,
                 splunk_user: str = None, splunk_pass: str = None):
        """Initialize the analyzer with optional Splunk connection."""
        self.splunk_host = splunk_host or os.getenv("SPLUNK_VALIDATOR_HOST")
        self.splunk_port = splunk_port or int(os.getenv("SPLUNK_VALIDATOR_PORT", "8089"))
        self.splunk_user = splunk_user or os.getenv("SPLUNK_VALIDATOR_USER", "admin")
        self.splunk_pass = splunk_pass or os.getenv("SPLUNK_VALIDATOR_PASS")
        self._splunk_available = None

    def analyze(self, query: str, auto_fix: bool = True) -> AnalysisResult:
        """
        Perform comprehensive analysis of an SPL query.

        Args:
            query: The SPL query to analyze
            auto_fix: Whether to auto-fix detected issues

        Returns:
            AnalysisResult with all findings
        """
        result = AnalysisResult(original_query=query, is_valid=True)

        # Step 1: Basic syntax validation
        self._validate_syntax(query, result)

        # Step 2: Parse commands
        self._parse_commands(query, result)

        # Step 3: Check anti-patterns
        self._check_anti_patterns(query, result)

        # Step 4: Check best practices
        self._check_best_practices(query, result)

        # Step 5: Analyze command ordering
        self._analyze_command_order(result)

        # Step 6: Estimate cost
        self._estimate_cost(result)

        # Step 7: Validate with Splunk REST API if available
        if self.splunk_host and self.splunk_pass:
            self._validate_with_splunk(query, result)

        # Step 8: Generate optimized query if requested
        if auto_fix and result.issues:
            self._generate_optimized_query(result)

        # Step 9: Generate recommendations
        self._generate_recommendations(result)

        return result

    def _validate_syntax(self, query: str, result: AnalysisResult) -> None:
        """Basic syntax validation."""
        # Check balanced parentheses
        if query.count('(') != query.count(')'):
            result.issues.append(Issue(
                category=IssueCategory.SYNTAX,
                severity=Severity.CRITICAL,
                message="Unbalanced parentheses",
                auto_fixable=True,
                fix_function="balance_parentheses",
            ))
            result.is_valid = False

        # Check balanced brackets
        if query.count('[') != query.count(']'):
            result.issues.append(Issue(
                category=IssueCategory.SYNTAX,
                severity=Severity.CRITICAL,
                message="Unbalanced brackets (subsearch)",
                auto_fixable=True,
                fix_function="balance_brackets",
            ))
            result.is_valid = False

        # Check balanced quotes
        if query.count('"') % 2 != 0:
            result.issues.append(Issue(
                category=IssueCategory.SYNTAX,
                severity=Severity.CRITICAL,
                message="Unbalanced double quotes",
                suggestion="Manually correct the query to ensure all double quotes are properly paired.",
                auto_fixable=False,
                fix_function=None,
            ))
            result.is_valid = False

        # Check for common typos
        typos = [
            (r'\bstatss\b', 'stats'),
            (r'\btabel\b', 'table'),
            (r'\bfilds\b', 'fields'),
            (r'\btstas\b', 'tstats'),
            (r'\bwehre\b', 'where'),
            (r'\brenamae\b', 'rename'),
        ]
        for pattern, correct in typos:
            if re.search(pattern, query, re.IGNORECASE):
                result.issues.append(Issue(
                    category=IssueCategory.SYNTAX,
                    severity=Severity.CRITICAL,
                    message=f"Possible typo: did you mean '{correct}'?",
                    auto_fixable=True,
                ))


    def _parse_commands(self, query: str, result: AnalysisResult) -> None:
        """Parse the query into individual commands."""
        parts = split_pipeline(query)

        for i, part in enumerate(parts):
            part = part.strip()
            if not part:
                continue

            cmd_match = re.match(r'^(\w+)', part)
            if cmd_match:
                candidate = cmd_match.group(1).lower()
                cmd_name = candidate if candidate in KNOWN_COMMANDS else 'search'
            elif part.startswith('['):
                cmd_name = 'subsearch'
            else:
                cmd_name = 'search'

            is_streaming = cmd_name in STREAMING_COMMANDS
            is_transforming = cmd_name in TRANSFORMING_COMMANDS
            is_generating = cmd_name in GENERATING_COMMANDS
            cost = COMMAND_COSTS.get(cmd_name, 5)

            result.commands.append(CommandInfo(
                name=cmd_name,
                args=part[len(cmd_name):].strip() if cmd_match else part,
                position=i,
                is_streaming=is_streaming,
                is_transforming=is_transforming,
                is_generating=is_generating,
                estimated_cost=cost,
            ))

    def _check_anti_patterns(self, query: str, result: AnalysisResult) -> None:
        """Check for known anti-patterns."""
        for ap in ANTI_PATTERNS:
            if re.search(ap["pattern"], query, re.IGNORECASE):
                result.issues.append(Issue(
                    category=IssueCategory.PERFORMANCE,
                    severity=ap["severity"],
                    message=ap["message"],
                    suggestion=ap["suggestion"],
                    auto_fixable=ap.get("auto_fixable", False),
                    fix_function=ap.get("fix_function"),
                ))

    def _check_best_practices(self, query: str, result: AnalysisResult) -> None:
        """Check best practice compliance."""
        query_lower = query.lower()

        # Check for time range
        if "earliest" not in query_lower and "latest" not in query_lower:
            # Check if it's a generating command that doesn't need time
            first_cmd = result.commands[0].name if result.commands else ""
            if first_cmd not in ("makeresults", "inputlookup", "rest", "metadata"):
                result.issues.append(Issue(
                    category=IssueCategory.BEST_PRACTICE,
                    severity=Severity.INFO,
                    message="Consider adding a time range to your query to improve performance and avoid accidentally searching all time.",
                    suggestion="Add earliest=-1h latest=now (or an appropriate time range) to your search.",
                    auto_fixable=True,
                    fix_function="add_time_range",
                ))

        # Check for index
        if "index=" not in query_lower and "index " not in query_lower:
            first_cmd = result.commands[0].name if result.commands else ""
            if first_cmd not in ("tstats", "mstats", "makeresults", "inputlookup", "rest", "metadata"):
                result.issues.append(Issue(
                    category=IssueCategory.BEST_PRACTICE,
                    severity=Severity.MEDIUM,
                    message="No index specified",
                    suggestion="Add index=<name> to limit search scope",
                ))

        # Check for fields command
        has_fields = any(cmd.name == "fields" for cmd in result.commands)
        if not has_fields and len(result.commands) > 2:
            result.issues.append(Issue(
                category=IssueCategory.BEST_PRACTICE,
                severity=Severity.LOW,
                message="No FIELDS command to reduce data transfer",
                suggestion="Add | fields <needed_fields> early in pipeline",
            ))

        # Check for bare free text keywords that should use TERM()
        # Extract base search (before first pipe)
        base_search = query.split("|")[0] if "|" in query else query
        # Remove known structured parts: index=, sourcetype=, host=, earliest=, latest=, field=value, TERM(), PREFIX()
        stripped = re.sub(r'(?:index|sourcetype|source|host|earliest|latest)\s*=\s*[^\s]+', '', base_search, flags=re.IGNORECASE)
        stripped = re.sub(r'\w+\s*[!=<>]+\s*["\']?[^\s"\']+["\']?', '', stripped)
        stripped = re.sub(r'(?:TERM|PREFIX)\s*\([^)]*\)', '', stripped)
        stripped = re.sub(r'"[^"]+"', '', stripped)  # Remove quoted strings (already specific)
        # Find remaining bare keywords
        skip_words = {'and', 'or', 'not', 'in', 'by', 'as', 'over', 'where', 'search'}
        bare_keywords = [w.strip('()[]') for w in stripped.split()
                         if w.strip('()[]') and w.strip('()[]').lower() not in skip_words
                         and not w.startswith('`') and w.strip('()[]').isalpha()]
        if bare_keywords:
            result.issues.append(Issue(
                category=IssueCategory.PERFORMANCE,
                severity=Severity.MEDIUM,
                message=f"Bare free text keyword(s) in search: {', '.join(bare_keywords)}. These bypass bloom filter optimization.",
                suggestion=f"Wrap with TERM() for bloom filter lookup: {', '.join(f'TERM({kw})' for kw in bare_keywords)}. For field=value pairs, use TERM(field=value) instead of bare text.",
            ))

        # Check for wildcard usage
        if "*" in query_lower:
            result.issues.append(Issue(
                category=IssueCategory.PERFORMANCE,
                severity=Severity.MEDIUM,
                message="Usage of wildcard `*` can be slow. Consider using more specific terms or TERM() for exact matches.",
                suggestion="Replace `*` with more specific terms or use TERM() for exact matches.",
            ))

        # Check for tstats opportunity
        if self._is_tstats_candidate(result):
            result.issues.append(Issue(
                category=IssueCategory.PERFORMANCE,
                severity=Severity.HIGH,
                message="This query could be converted to tstats for 10-100x speedup",
                suggestion="Use: | tstats count where index=... TERM(field=value) by host. For prefix matching use PREFIX(field=prefix). Never use wildcards inside TERM().",
                auto_fixable=True,
                fix_function="convert_to_tstats",
            ))

        # Check for subsearch usage
        if "[search" in query_lower:
            result.issues.append(Issue(
                category=IssueCategory.PERFORMANCE,
                severity=Severity.HIGH,
                message="Usage of subsearch can be slow. Consider using a lookup instead.",
                suggestion="Replace the subsearch with a lookup.",
                auto_fixable=True,
                fix_function="replace_subsearch_with_lookup",
            ))

        # Check for broad search
        if "index=*" in query_lower and "sourcetype=*" in query_lower:
            result.issues.append(Issue(
                category=IssueCategory.PERFORMANCE,
                severity=Severity.CRITICAL,
                message="Very broad search (index=* and sourcetype=*) can cause hallucinations and poor performance.",
                suggestion="Specify a concrete index and sourcetype to narrow down the search.",
            ))

    def _is_tstats_candidate(self, result: AnalysisResult) -> bool:
        """Check if query is a candidate for tstats conversion."""
        if not result.commands:
            return False

        # Must start with search (not already tstats)
        if result.commands[0].name == "tstats":
            return False

        # Look for simple aggregation pattern: search | stats
        has_stats = any(cmd.name == "stats" for cmd in result.commands)
        has_complex = any(cmd.name in ("eval", "rex", "lookup", "join") for cmd in result.commands)

        # Simple pattern: search with only stats/table/fields
        simple_commands = {"search", "stats", "table", "fields", "sort", "head", "where"}
        all_simple = all(cmd.name in simple_commands for cmd in result.commands)

        return has_stats and not has_complex and all_simple

    def _analyze_command_order(self, result: AnalysisResult) -> None:
        """Analyze command ordering for efficiency."""
        commands = result.commands
        if len(commands) < 2:
            return

        # Check for non-streaming before transforming
        saw_transforming = False
        for cmd in commands:
            if cmd.is_transforming:
                saw_transforming = True
            elif saw_transforming and cmd.is_streaming:
                result.issues.append(Issue(
                    category=IssueCategory.PERFORMANCE,
                    severity=Severity.MEDIUM,
                    message=f"Streaming command '{cmd.name}' after transforming command",
                    suggestion="Move streaming commands (eval, where) before stats/chart",
                ))

        # Check for sort before stats
        for i, cmd in enumerate(commands[:-1]):
            if cmd.name == "sort":
                next_cmd = commands[i + 1]
                if next_cmd.name in ("stats", "chart", "timechart"):
                    result.issues.append(Issue(
                        category=IssueCategory.PERFORMANCE,
                        severity=Severity.LOW,
                        message="SORT before aggregation is usually unnecessary",
                        suggestion="Stats/chart don't need sorted input",
                    ))

    def _estimate_cost(self, result: AnalysisResult) -> None:
        """Estimate query cost and optimization potential."""
        cost_estimator = QueryCostEstimator()
        cost_estimation = cost_estimator.estimate(result)
        result.estimated_cost = cost_estimation["total_cost"]

        # Optimization potential based on auto-fixable issues
        fixable = sum(1 for i in result.issues if i.auto_fixable)
        high_issues = sum(1 for i in result.issues if i.severity == Severity.HIGH)
        result.optimization_potential = min(100, fixable * 15 + high_issues * 10)

    def _validate_with_splunk(self, query: str, result: AnalysisResult) -> None:
        """Validate query using Splunk REST API."""
        try:
            import requests
            from urllib3.exceptions import InsecureRequestWarning
            # WARNING: Disabling SSL warnings is not recommended for production.
            # Consider using a proper CA bundle.
            requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

            url = f"https://{self.splunk_host}:{self.splunk_port}/services/search/parser"
            try:
                from chat_app.settings import get_settings
                _ssl_verify = get_settings().splunk.get_ssl_verify()
            except Exception:
                _ssl_verify = os.getenv("SPLUNK_VERIFY_SSL", "true").lower() != "false"
                _ca = os.getenv("SPLUNK_CA_BUNDLE", "")
                if _ca:
                    _ssl_verify = _ca
            response = requests.post(
                url,
                auth=(self.splunk_user, self.splunk_pass),
                data={"q": query, "output_mode": "json"},
                verify=_ssl_verify,
                timeout=10, # Prevent indefinite hangs
            )

            if response.status_code == 200:
                data = response.json()
                result.splunk_validation = data

                # Check for errors
                if "messages" in data:
                    for msg in data["messages"]:
                        if msg.get("type") == "FATAL":
                            result.is_valid = False
                            result.issues.append(Issue(
                                category=IssueCategory.SYNTAX,
                                severity=Severity.CRITICAL,
                                message=f"Splunk parser: {msg.get('text', 'Unknown error')}",
                            ))

                # Get normalized query
                if "dict" in data and "remoteSearch" in data["dict"]:
                    result.normalized_query = data["dict"]["remoteSearch"]

        except requests.exceptions.RequestException as e:
            logger.warning(f"Splunk validation failed due to a network error: {e}")
        except Exception as e:
            logger.error(f"An unexpected error occurred during Splunk validation: {e}")

    def _generate_optimized_query(self, result: AnalysisResult) -> None:
        """Generate optimized version of the query."""
        optimized = result.original_query

        for issue in result.issues:
            if issue.auto_fixable and issue.fix_function:
                fix_method = getattr(self, f"_fix_{issue.fix_function}", None)
                if fix_method:
                    optimized = fix_method(optimized)

        result.optimized_query = optimized

    def _generate_recommendations(self, result: AnalysisResult) -> None:
        """Generate human-readable recommendations."""
        recommendations = []

        # Priority order by severity
        critical = [i for i in result.issues if i.severity == Severity.CRITICAL]
        high = [i for i in result.issues if i.severity == Severity.HIGH]

        if critical:
            recommendations.append("CRITICAL: Fix these issues first:")
            for issue in critical:
                recommendations.append(f"  - {issue.message}")
                if issue.suggestion:
                    recommendations.append(f"    Fix: {issue.suggestion}")

        if high:
            recommendations.append("HIGH PRIORITY: Performance improvements:")
            for issue in high:
                recommendations.append(f"  - {issue.message}")
                if issue.suggestion:
                    recommendations.append(f"    Fix: {issue.suggestion}")

        if result.optimization_potential > 50:
            recommendations.append(f"This query has {result.optimization_potential}% optimization potential")

        if result.estimated_cost > 70:
            recommendations.append(f"WARNING: High estimated cost ({result.estimated_cost}/100)")

        result.recommendations = recommendations

    # Auto-fix methods
    def _fix_balance_parentheses(self, query: str) -> str:
        """Fix unbalanced parentheses."""
        open_count = query.count('(')
        close_count = query.count(')')
        if open_count > close_count:
            query += ')' * (open_count - close_count)
        elif close_count > open_count:
            query = '(' * (close_count - open_count) + query
        return query

    def _fix_balance_brackets(self, query: str) -> str:
        """Fix unbalanced brackets."""
        open_count = query.count('[')
        close_count = query.count(']')
        if open_count > close_count:
            query += ']' * (open_count - close_count)
        elif close_count > open_count:
            query = '[' * (close_count - open_count) + query
        return query

    def _fix_balance_quotes(self, query: str) -> str:
        """Fix unbalanced quotes by removing them."""
        if query.count('"') % 2 != 0:
            # Find and remove the unpaired quote
            return query.replace('"', '', 1)
        return query

    def _fix_add_time_range(self, query: str) -> str:
        """Add default time range if missing."""
        if "earliest" not in query.lower():
            # Add after index= if present
            if "index=" in query.lower():
                query = re.sub(
                    r'(index\s*=\s*\S+)',
                    r'\1 earliest=-1h latest=now',
                    query,
                    count=1,
                    flags=re.IGNORECASE
                )
            else:
                # Add at the beginning
                if query.strip().startswith('|'):
                    # It's a generating command, add to where clause if tstats
                    if 'tstats' in query.lower():
                        query = re.sub(
                            r'(where\s+)',
                            r'\1earliest=-1h latest=now ',
                            query,
                            count=1,
                            flags=re.IGNORECASE
                        )
                else:
                    query = f"earliest=-1h latest=now {query}"
        return query

    def _fix_combine_eval_commands(self, query: str) -> str:
        """Combine multiple consecutive eval commands."""
        # Match consecutive eval commands
        pattern = r'\|\s*eval\s+(\w+\s*=\s*[^|]+)\|\s*eval\s+'
        while re.search(pattern, query):
            query = re.sub(pattern, r'| eval \1, ', query)
        return query

    def _fix_move_table_to_end(self, query: str) -> str:
        """Move table command to end of query."""
        # Extract table command
        table_match = re.search(r'\|\s*table\s+([^|]+)', query)
        if table_match:
            table_cmd = f"| table {table_match.group(1).strip()}"
            # Remove from current position
            query = re.sub(r'\|\s*table\s+[^|]+\|', '|', query)
            # Add to end
            query = query.rstrip() + " " + table_cmd
        return query

    def _fix_replace_search_with_where(self, query: str) -> str:
        """Replace mid-pipeline '| search field=value' with '| where field=value'."""
        # Match: | search field_name=value (but not the initial search command)
        pattern = r'\|\s*search\s+(\w+)\s*=\s*("[^"]*"|\S+)'
        return re.sub(pattern, r'| where \1=\2', query, flags=re.IGNORECASE)

    def _fix_convert_to_tstats(self, query: str) -> str:
        """Convert simple stats query to tstats using SPLQueryOptimizer."""
        try:
            from shared.spl_query_optimizer import SPLQueryOptimizer, ConversionStatus
            result = SPLQueryOptimizer.optimize(query)
            if result.status != ConversionStatus.IMPOSSIBLE:
                return result.optimized
        except Exception:
            pass
        return query

    def _fix_replace_subsearch_with_lookup(self, query: str) -> str:
        """Replace subsearch with lookup."""
        # This is a simplified implementation. A real implementation would need to
        # parse the subsearch and create a lookup table.
        return query.replace("[search", "| lookup")


# Singleton instance
_analyzer: Optional[RobustSPLAnalyzer] = None


def get_robust_analyzer() -> RobustSPLAnalyzer:
    """Get or create the robust analyzer singleton."""
    global _analyzer
    if _analyzer is None:
        _analyzer = RobustSPLAnalyzer()
    return _analyzer


def analyze_spl(query: str, auto_fix: bool = True) -> AnalysisResult:
    """Convenience function to analyze SPL query."""
    analyzer = get_robust_analyzer()
    return analyzer.analyze(query, auto_fix)


def suggest_search(user_request: str) -> str:
    """
    Suggest a Splunk search query based on the user's request.
    """
    from langchain_google_genai import ChatGoogleGenerativeAI
    from langchain_core.prompts import ChatPromptTemplate
    from langchain_core.output_parsers import StrOutputParser

    llm = ChatGoogleGenerativeAI(model="gemini-pro", convert_system_message_to_human=True)
    prompt = ChatPromptTemplate.from_template("You are a Splunk expert. Suggest a Splunk search query for the following user request: {user_request}")
    chain = prompt | llm | StrOutputParser()
    return chain.invoke({"user_request": user_request})


def validate_and_optimize(query: str) -> Dict[str, Any]:
    """
    Full validation and optimization pipeline.

    Returns dict with:
    - valid: bool
    - original: str
    - optimized: str (if valid)
    - issues: list of issues
    - cost: int (0-100)
    - recommendations: list of strings
    """
    result = analyze_spl(query)

    return {
        "valid": result.is_valid,
        "original": result.original_query,
        "optimized": result.optimized_query,
        "normalized": result.normalized_query,
        "issues": [
            {
                "severity": i.severity.value,
                "category": i.category.value,
                "message": i.message,
                "suggestion": i.suggestion,
                "auto_fixable": i.auto_fixable,
            }
            for i in result.issues
        ],
        "cost": result.estimated_cost,
        "optimization_potential": result.optimization_potential,
        "recommendations": result.recommendations,
        "commands": [
            {
                "name": c.name,
                "position": c.position,
                "cost": c.estimated_cost,
                "streaming": c.is_streaming,
            }
            for c in result.commands
        ],
    }
