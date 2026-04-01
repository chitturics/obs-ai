"""
SPL Analyzer - Comprehensive Splunk SPL Query Analysis System

Combines multiple capabilities:
1. Intent Classification - Detect what user wants (generate, optimize, explain, validate)
2. NLP to SPL - Convert natural language to SPL queries
3. Query Explanation - Step-by-step breakdown of SPL queries
4. Query Optimization - Convert to tstats/improve performance
5. Query Validation - Syntax checking and risk scoring
6. Query Ranking - Quality and efficiency scoring
7. Query Annotation - Add inline comments

Usage:
    from chat_app.spl_analyzer import SPLAnalyzer

    analyzer = SPLAnalyzer()

    # Auto-detect intent and process
    result = analyzer.analyze("show me failed logins in the last hour")

    # Or use specific functions
    result = analyzer.explain("index=auth action=failure | stats count by user")
    result = analyzer.optimize("index=auth action=failure | stats count by user")
    result = analyzer.validate("index=auth | stats count")
"""

import re
import json
from typing import Optional, List, Dict, Tuple, Any, Union
from dataclasses import dataclass, field, asdict
from enum import Enum
from datetime import datetime

# Import existing modules
from shared.spl_validator import SPLValidator, ValidationResult, ValidationStatus, RiskLevel
from shared.spl_query_optimizer import SPLQueryOptimizer, OptimizedQuery, ConversionStatus, OptimizationStrategy


class UserIntent(Enum):
    """Classification of what the user wants to do."""
    GENERATE = "generate"      # Natural language to SPL
    OPTIMIZE = "optimize"      # Make query faster
    EXPLAIN = "explain"        # Understand a query
    VALIDATE = "validate"      # Check for errors
    DEBUG = "debug"            # Fix a broken query
    COMPARE = "compare"        # Compare two queries
    ANNOTATE = "annotate"      # Add comments to query
    UNKNOWN = "unknown"


@dataclass
class QueryScore:
    """Quality and efficiency scoring for a query."""
    overall: int  # 0-100
    readability: int  # 0-100
    efficiency: int  # 0-100
    best_practices: int  # 0-100
    issues: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


@dataclass
class QueryExplanation:
    """Step-by-step explanation of a query."""
    query: str
    summary: str
    stages: List[Dict[str, str]]  # Each stage explained
    fields_used: List[str]
    data_flow: str
    purpose: str
    complexity: str  # simple, moderate, complex


@dataclass
class AnalysisResult:
    """Comprehensive result from SPL analysis."""
    intent: UserIntent
    original_input: str
    query: Optional[str] = None
    validation: Optional[ValidationResult] = None
    optimization: Optional[OptimizedQuery] = None
    explanation: Optional[QueryExplanation] = None
    score: Optional[QueryScore] = None
    suggestions: List[str] = field(default_factory=list)
    annotated_query: Optional[str] = None
    error: Optional[str] = None
    processing_time_ms: int = 0

    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        result = {
            "intent": self.intent.value,
            "original_input": self.original_input,
            "query": self.query,
            "suggestions": self.suggestions,
            "error": self.error,
            "processing_time_ms": self.processing_time_ms,
        }
        if self.validation:
            result["validation"] = {
                "status": self.validation.status.value,
                "risk_level": self.validation.risk_level.value,
                "risk_score": self.validation.risk_score,
                "errors": self.validation.errors,
                "warnings": self.validation.warnings,
            }
        if self.optimization:
            result["optimization"] = {
                "status": self.optimization.status.value,
                "strategy": self.optimization.strategy.value,
                "optimized": self.optimization.optimized,
                "explanation": self.optimization.explanation,
            }
        if self.explanation:
            result["explanation"] = asdict(self.explanation)
        if self.score:
            result["score"] = asdict(self.score)
        if self.annotated_query:
            result["annotated_query"] = self.annotated_query
        return result


class SPLAnalyzer:
    """
    Comprehensive SPL Query Analyzer.

    Provides unified interface for all SPL analysis operations.
    """

    # Configurable index mappings (overridden by org config via set_index_mappings)
    _index_mappings = {
        "network": "firewall",
        "authentication": "wineventlog",
        "web": "proxy",
        "dns": "dns",
        "windows": "wineventlog",
        "endpoint": "main",
    }

    @classmethod
    def set_index_mappings(cls, mappings: Dict[str, str]) -> None:
        """Override default index mappings with org-specific ones."""
        cls._index_mappings.update(mappings)

    # Intent detection patterns
    INTENT_PATTERNS = {
        UserIntent.GENERATE: [
            r'\b(show|find|get|list|search for|give me|display)\b',
            r'\b(how many|count of|number of)\b',
            r'\b(what are|which)\b.*\b(in|from|with)\b',
            r'\bfind\s+all\b',
            r'\b(failed|successful|blocked|denied)\s+(logins?|connections?|attempts?)\b',
        ],
        UserIntent.OPTIMIZE: [
            r'\b(optimize|speed up|make faster|improve performance|convert to tstats)\b',
            r'\b(slow|taking too long|inefficient)\b',
            r'\btstats\b.*\b(convert|use|change)\b',
        ],
        UserIntent.EXPLAIN: [
            r'\b(explain|what does|how does|understand|break down|analyze)\b',
            r'\b(what is|what\'s)\s+(this|the)\s+(query|search|spl)\b',
            r'\bwalk me through\b',
        ],
        UserIntent.VALIDATE: [
            r'\b(validate|check|verify|is this correct|syntax)\b',
            r'\b(valid|correct|right)\b.*\?',
            r'\bany (errors?|issues?|problems?)\b',
        ],
        UserIntent.DEBUG: [
            r'\b(fix|debug|not working|error|broken|wrong)\b',
            r'\bwhy (is|does|doesn\'t)\b',
            r'\bhelp with\b',
        ],
        UserIntent.ANNOTATE: [
            r'\b(annotate|add comments|document|comment)\b',
        ],
    }

    # NLP patterns for query generation
    NLP_PATTERNS = {
        # Time patterns
        r'\b(last|past)\s+(\d+)\s+(hour|minute|day|week|month)s?\b': 'earliest=-{1}{2[0]} latest=now',
        r'\b(yesterday)\b': 'earliest=-1d@d latest=@d',
        r'\b(today)\b': 'earliest=@d latest=now',
        r'\b(this week)\b': 'earliest=@w latest=now',

        # Data type patterns
        r'\b(firewall|network traffic|connections?)\b': 'index=firewall',
        r'\b(authentication|login|logon|auth)\b': 'index=wineventlog sourcetype=WinEventLog:Security',
        r'\b(web|http|proxy)\b': 'index=proxy',
        r'\b(dns)\b': 'index=dns',
        r'\b(windows|winevent)\b': 'index=wineventlog',

        # Action patterns
        r'\b(failed|failure|unsuccessful)\b': 'action=failure OR action=denied',
        r'\b(successful|success)\b': 'action=success OR action=allowed',
        r'\b(blocked|denied|rejected)\b': 'action=blocked OR action=denied',
        r'\b(allowed|permitted|accepted)\b': 'action=allowed',

        # Aggregation patterns
        r'\bhow many\b': 'stats count',
        r'\bcount\s*(of|by)?\b': 'stats count',
        r'\btop\s+(\d+)\b': 'top {0}',
        r'\b(by|per|for each)\s+(\w+)\b': 'by {1}',
        r'\bover time\b': 'timechart count',
        r'\btrend\b': 'timechart count',
    }

    # SPL command descriptions for explanation
    COMMAND_DESCRIPTIONS = {
        "search": "Filters events based on specified criteria",
        "stats": "Calculates aggregate statistics over the result set",
        "timechart": "Creates time-series data for charting",
        "chart": "Creates chart data with arbitrary X-axis",
        "table": "Formats results as a table with specified fields",
        "eval": "Calculates an expression and stores result in a field",
        "where": "Filters results based on a condition",
        "sort": "Sorts results by specified fields",
        "head": "Returns the first N results",
        "tail": "Returns the last N results",
        "dedup": "Removes duplicate events based on specified fields",
        "rename": "Renames fields in the result set",
        "rex": "Extracts fields using regular expressions",
        "lookup": "Enriches events with data from a lookup table",
        "join": "Combines results from subsearch with main results",
        "append": "Appends subsearch results to main results",
        "transaction": "Groups events into transactions",
        "tstats": "Fast statistical queries using indexed metadata",
        "eventstats": "Adds aggregated values to each event",
        "streamstats": "Calculates running statistics",
        "top": "Returns the most common values",
        "rare": "Returns the least common values",
        "fields": "Keeps or removes fields from results",
        "fillnull": "Replaces null values with specified value",
        "iplocation": "Adds geographic information based on IP",
        "inputlookup": "Loads data from a lookup table",
        "outputlookup": "Writes results to a lookup table",
        "collect": "Writes results to a summary index",
        "bucket": "Groups values into discrete buckets",
        "bin": "Alias for bucket command",
        "convert": "Converts field values between formats",
    }

    def __init__(self):
        """Initialize the SPL Analyzer."""
        self.validator = SPLValidator
        self.optimizer = SPLQueryOptimizer

    def analyze(self, input_text: str, force_intent: Optional[UserIntent] = None) -> AnalysisResult:
        """
        Analyze input and automatically detect what to do.

        Args:
            input_text: User input (query or natural language)
            force_intent: Optional intent to force specific processing

        Returns:
            AnalysisResult with all relevant analysis
        """
        start_time = datetime.now()

        result = AnalysisResult(
            intent=UserIntent.UNKNOWN,
            original_input=input_text,
        )

        try:
            # Detect intent
            if force_intent:
                result.intent = force_intent
            else:
                result.intent = self._detect_intent(input_text)

            # Check if input is already SPL
            is_spl = self._is_spl_query(input_text)

            if is_spl:
                result.query = input_text

            # Process based on intent
            if result.intent == UserIntent.GENERATE and not is_spl:
                result.query = self._generate_spl(input_text)
                result.suggestions.append("Generated SPL from natural language")

            if result.query:
                # Always validate
                result.validation = self.validator.validate(result.query)

                # Intent-specific processing
                if result.intent == UserIntent.OPTIMIZE:
                    result.optimization = self.optimizer.optimize(result.query)

                elif result.intent == UserIntent.EXPLAIN:
                    result.explanation = self._explain_query(result.query)

                elif result.intent == UserIntent.ANNOTATE:
                    result.annotated_query = self._annotate_query(result.query)

                # Always score
                result.score = self._score_query(result.query, result.validation)

                # Add optimization suggestion if relevant
                if (result.validation and
                    result.validation.suggestions and
                    result.intent != UserIntent.OPTIMIZE):
                    result.suggestions.extend(result.validation.suggestions)

        except Exception as e:
            result.error = str(e)

        result.processing_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        return result

    def explain(self, query: str) -> AnalysisResult:
        """Explain an SPL query step by step."""
        return self.analyze(query, force_intent=UserIntent.EXPLAIN)

    def optimize(self, query: str) -> AnalysisResult:
        """Optimize an SPL query for better performance."""
        return self.analyze(query, force_intent=UserIntent.OPTIMIZE)

    def validate(self, query: str) -> AnalysisResult:
        """Validate an SPL query for syntax and best practices."""
        return self.analyze(query, force_intent=UserIntent.VALIDATE)

    def generate(self, natural_language: str) -> AnalysisResult:
        """Generate SPL from natural language."""
        return self.analyze(natural_language, force_intent=UserIntent.GENERATE)

    def annotate(self, query: str) -> AnalysisResult:
        """Add inline comments to an SPL query."""
        return self.analyze(query, force_intent=UserIntent.ANNOTATE)

    def _detect_intent(self, input_text: str) -> UserIntent:
        """Detect user intent from input text."""
        input_lower = input_text.lower()

        # Check each intent pattern
        scores = {intent: 0 for intent in UserIntent}

        for intent, patterns in self.INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, input_lower):
                    scores[intent] += 1

        # If input looks like SPL, default to EXPLAIN
        if self._is_spl_query(input_text):
            if scores[UserIntent.OPTIMIZE] > 0:
                return UserIntent.OPTIMIZE
            elif scores[UserIntent.VALIDATE] > 0:
                return UserIntent.VALIDATE
            elif scores[UserIntent.ANNOTATE] > 0:
                return UserIntent.ANNOTATE
            else:
                return UserIntent.EXPLAIN

        # Find highest scoring intent
        max_score = max(scores.values())
        if max_score > 0:
            for intent, score in scores.items():
                if score == max_score:
                    return intent

        # Default to GENERATE for non-SPL input
        return UserIntent.GENERATE

    def _is_spl_query(self, text: str) -> bool:
        """Check if text appears to be an SPL query."""
        text = text.strip()

        # Clear indicators of SPL
        spl_indicators = [
            r'^\s*\|',  # Starts with pipe
            r'\bindex\s*=',  # index=
            r'\bsourcetype\s*=',  # sourcetype=
            r'\|\s*(stats|timechart|chart|table|eval|where|sort|head|tail)\b',
            r'\bearliest\s*=',
            r'\blatest\s*=',
            r'\bTERM\s*\(',
            r'\bPREFIX\s*\(',
        ]

        for pattern in spl_indicators:
            if re.search(pattern, text, re.IGNORECASE):
                return True

        return False

    def _generate_spl(self, natural_language: str) -> str:
        """Generate SPL query from natural language description."""
        nl_lower = natural_language.lower()

        # Start building the query
        parts = {
            "index": [],
            "filters": [],
            "time": [],
            "aggregation": [],
            "by_fields": [],
        }

        # Extract time range
        time_patterns = [
            (r'\b(last|past)\s+(\d+)\s+(hour)s?\b', '-{0}h'),
            (r'\b(last|past)\s+(\d+)\s+(minute)s?\b', '-{0}m'),
            (r'\b(last|past)\s+(\d+)\s+(day)s?\b', '-{0}d'),
            (r'\b(last|past)\s+(\d+)\s+(week)s?\b', '-{0}w'),
            (r'\b(yesterday)\b', '-1d@d'),
            (r'\b(today)\b', '@d'),
        ]

        for pattern, time_fmt in time_patterns:
            match = re.search(pattern, nl_lower)
            if match:
                if '{0}' in time_fmt:
                    parts["time"].append(f"earliest={time_fmt.format(match.group(2))}")
                else:
                    parts["time"].append(f"earliest={time_fmt}")
                break

        if not parts["time"]:
            parts["time"].append("earliest=-1h")
        parts["time"].append("latest=now")

        # Detect data type / index (using configurable mappings)
        idx = self._index_mappings
        if re.search(r'\b(firewall|network|traffic|connection)\b', nl_lower):
            parts["index"].append(f"index={idx.get('network', 'firewall')}")
        elif re.search(r'\b(login|logon|authentication|auth)\b', nl_lower):
            parts["index"].append(f"index={idx.get('authentication', 'wineventlog')}")
            parts["filters"].append("sourcetype=WinEventLog:Security")
        elif re.search(r'\b(web|http|proxy|url)\b', nl_lower):
            parts["index"].append(f"index={idx.get('web', 'proxy')}")
        elif re.search(r'\b(dns)\b', nl_lower):
            parts["index"].append(f"index={idx.get('dns', 'dns')}")
        elif re.search(r'\b(windows|winevent)\b', nl_lower):
            parts["index"].append(f"index={idx.get('windows', 'wineventlog')}")
        else:
            parts["index"].append("index=main")

        # Detect action filters
        if re.search(r'\b(failed|failure|unsuccessful|denied|blocked)\b', nl_lower):
            if 'login' in nl_lower or 'logon' in nl_lower or 'auth' in nl_lower:
                parts["filters"].append("EventCode=4625")
            else:
                parts["filters"].append("action=failure OR action=denied OR action=blocked")
        elif re.search(r'\b(success|successful|allowed)\b', nl_lower):
            if 'login' in nl_lower or 'logon' in nl_lower:
                parts["filters"].append("EventCode=4624")
            else:
                parts["filters"].append("action=success OR action=allowed")

        # Detect aggregation
        if re.search(r'\b(how many|count|number of)\b', nl_lower):
            parts["aggregation"].append("stats count")
        elif re.search(r'\btop\s+(\d+)\b', nl_lower):
            match = re.search(r'\btop\s+(\d+)\b', nl_lower)
            parts["aggregation"].append(f"top {match.group(1)}")
        elif re.search(r'\b(trend|over time|timeline)\b', nl_lower):
            parts["aggregation"].append("timechart count")

        # Detect BY fields
        by_match = re.search(r'\b(by|per|for each|group by)\s+(\w+)', nl_lower)
        if by_match:
            field = by_match.group(2)
            # Map common words to SPL fields
            field_map = {
                "user": "user",
                "users": "user",
                "ip": "src_ip",
                "source": "src_ip",
                "destination": "dest_ip",
                "host": "host",
                "computer": "host",
            }
            parts["by_fields"].append(field_map.get(field, field))

        # Build query
        query_parts = []
        query_parts.extend(parts["index"])
        query_parts.extend(parts["filters"])
        query_parts.extend(parts["time"])

        base_search = " ".join(query_parts)

        if parts["aggregation"]:
            agg = parts["aggregation"][0]
            if parts["by_fields"]:
                agg += " by " + ", ".join(parts["by_fields"])
            return f"{base_search} | {agg}"

        return base_search

    def _explain_query(self, query: str) -> QueryExplanation:
        """Generate detailed explanation of a query."""
        stages = []
        fields_used = set()

        # Split into pipeline stages
        pipeline = self._split_pipeline(query)

        for i, stage in enumerate(pipeline):
            stage = stage.strip()
            if not stage:
                continue

            stage_info = {
                "stage_num": i + 1,
                "raw": stage,
                "command": "",
                "description": "",
                "purpose": "",
            }

            # Extract command
            cmd_match = re.match(r'^(\w+)', stage)
            if cmd_match:
                cmd = cmd_match.group(1).lower()
                stage_info["command"] = cmd
                stage_info["description"] = self.COMMAND_DESCRIPTIONS.get(cmd, "Custom or unknown command")

                # Generate purpose based on content
                if cmd == "search" or i == 0:
                    stage_info["purpose"] = self._describe_search_stage(stage)
                elif cmd == "stats":
                    stage_info["purpose"] = self._describe_stats_stage(stage)
                elif cmd == "timechart":
                    stage_info["purpose"] = "Creates time-series data for visualization"
                elif cmd == "eval":
                    stage_info["purpose"] = self._describe_eval_stage(stage)
                elif cmd == "where":
                    stage_info["purpose"] = self._describe_where_stage(stage)
                elif cmd == "table":
                    stage_info["purpose"] = self._describe_table_stage(stage)
                elif cmd == "sort":
                    stage_info["purpose"] = self._describe_sort_stage(stage)
                elif cmd == "tstats":
                    stage_info["purpose"] = "Fast aggregation using indexed metadata (10-100x faster)"
                else:
                    stage_info["purpose"] = stage_info["description"]

            # Extract fields
            field_pattern = r'\b([a-zA-Z_][a-zA-Z0-9_]*)\s*='
            for match in re.finditer(field_pattern, stage):
                fields_used.add(match.group(1))

            stages.append(stage_info)

        # Determine complexity
        num_stages = len(stages)
        has_expensive = any(
            s.get("command") in {"transaction", "join", "eventstats", "streamstats"}
            for s in stages
        )

        if num_stages <= 2 and not has_expensive:
            complexity = "simple"
        elif num_stages <= 4 and not has_expensive:
            complexity = "moderate"
        else:
            complexity = "complex"

        # Generate summary
        summary = self._generate_summary(stages)

        # Generate data flow description
        data_flow = self._describe_data_flow(stages)

        # Determine overall purpose
        purpose = self._determine_purpose(stages, query)

        return QueryExplanation(
            query=query,
            summary=summary,
            stages=stages,
            fields_used=list(fields_used),
            data_flow=data_flow,
            purpose=purpose,
            complexity=complexity,
        )

    def _describe_search_stage(self, stage: str) -> str:
        """Describe what the base search does."""
        parts = []

        # Index
        idx_match = re.search(r'index\s*=\s*(\S+)', stage)
        if idx_match:
            parts.append(f"searches the '{idx_match.group(1)}' index")

        # Sourcetype
        st_match = re.search(r'sourcetype\s*=\s*(\S+)', stage)
        if st_match:
            parts.append(f"for '{st_match.group(1)}' data")

        # Time range
        time_match = re.search(r'earliest\s*=\s*(\S+)', stage)
        if time_match:
            parts.append(f"from {time_match.group(1)} to now")

        # Filters
        filters = re.findall(r'(\w+)\s*=\s*(\S+)', stage)
        filter_parts = []
        for field, value in filters:
            if field.lower() not in ('index', 'sourcetype', 'earliest', 'latest'):
                filter_parts.append(f"{field}={value}")
        if filter_parts:
            parts.append(f"filtering by {', '.join(filter_parts)}")

        return " ".join(parts) if parts else "Retrieves events"

    def _describe_stats_stage(self, stage: str) -> str:
        """Describe what the stats command does."""
        # Extract functions
        funcs = re.findall(r'(\w+)\s*\(([^)]*)\)', stage)
        func_desc = []
        for func, arg in funcs:
            if func.lower() == 'count':
                func_desc.append("counts events")
            elif func.lower() == 'sum':
                func_desc.append(f"sums {arg}")
            elif func.lower() == 'avg':
                func_desc.append(f"averages {arg}")
            elif func.lower() == 'dc':
                func_desc.append(f"counts distinct {arg}")

        # Extract BY fields
        by_match = re.search(r'\bby\s+(.+?)(?:\s*$|\s*\|)', stage, re.IGNORECASE)
        if by_match:
            by_fields = by_match.group(1).strip()
            func_desc.append(f"grouped by {by_fields}")

        return " and ".join(func_desc) if func_desc else "Aggregates data"

    def _describe_eval_stage(self, stage: str) -> str:
        """Describe what an eval command does."""
        # Extract field being created
        field_match = re.search(r'eval\s+(\w+)\s*=', stage)
        if field_match:
            return f"Creates calculated field '{field_match.group(1)}'"
        return "Calculates new field values"

    def _describe_where_stage(self, stage: str) -> str:
        """Describe what a where command does."""
        # Extract condition
        cond_match = re.search(r'where\s+(.+)', stage, re.IGNORECASE)
        if cond_match:
            return f"Filters results where {cond_match.group(1)}"
        return "Filters results based on condition"

    def _describe_table_stage(self, stage: str) -> str:
        """Describe what a table command does."""
        fields_match = re.search(r'table\s+(.+)', stage, re.IGNORECASE)
        if fields_match:
            return f"Displays fields: {fields_match.group(1)}"
        return "Formats output as a table"

    def _describe_sort_stage(self, stage: str) -> str:
        """Describe what a sort command does."""
        if '-' in stage:
            return "Sorts results in descending order"
        elif '+' in stage:
            return "Sorts results in ascending order"
        return "Sorts results"

    def _generate_summary(self, stages: List[Dict]) -> str:
        """Generate a natural language summary of the query."""
        if not stages:
            return "Empty query"

        parts = []

        for stage in stages:
            purpose = stage.get("purpose", "")
            if purpose:
                parts.append(purpose)

        if len(parts) == 1:
            return parts[0]
        elif len(parts) == 2:
            return f"{parts[0]}, then {parts[1]}"
        else:
            return f"{parts[0]}, " + ", then ".join(parts[1:])

    def _describe_data_flow(self, stages: List[Dict]) -> str:
        """Describe how data flows through the pipeline."""
        if not stages:
            return "No data flow"

        flow = "Events"
        for stage in stages:
            cmd = stage.get("command", "").lower()
            if cmd in ("search", "index") or not cmd:
                flow += " → Retrieved from index"
            elif cmd == "stats":
                flow += " → Aggregated into summary"
            elif cmd == "timechart":
                flow += " → Grouped by time"
            elif cmd == "where":
                flow += " → Filtered"
            elif cmd == "eval":
                flow += " → Enriched with calculations"
            elif cmd == "table":
                flow += " → Formatted"
            elif cmd == "sort":
                flow += " → Sorted"
            elif cmd == "tstats":
                flow += " → Fast-aggregated from index"

        return flow

    def _determine_purpose(self, stages: List[Dict], query: str) -> str:
        """Determine the overall purpose of the query."""
        query_lower = query.lower()

        # Check for common patterns
        if "4625" in query or ("failed" in query_lower and "login" in query_lower):
            return "Detect failed login attempts"
        elif "4624" in query or ("success" in query_lower and "login" in query_lower):
            return "Track successful logins"
        elif "denied" in query_lower or "blocked" in query_lower:
            return "Find blocked or denied actions"
        elif "error" in query_lower:
            return "Find error events"
        elif "timechart" in query_lower or "trend" in query_lower:
            return "Analyze trends over time"
        elif "top" in query_lower:
            return "Find most common values"
        elif "stats count" in query_lower:
            return "Count events"

        return "General search and analysis"

    def _score_query(self, query: str, validation: Optional[ValidationResult]) -> QueryScore:
        """Score a query for quality and efficiency."""
        issues = []
        recommendations = []

        # Readability score
        readability = 100

        # Long single-line query
        if len(query) > 200 and '\n' not in query:
            readability -= 20
            recommendations.append("Consider breaking long query into multiple lines for readability")

        # No comments
        if '```' not in query:
            readability -= 5

        # Efficiency score
        efficiency = 100

        if validation:
            efficiency -= validation.risk_score
            issues.extend(validation.errors)

            # Check for expensive patterns
            if 'transaction' in query.lower():
                efficiency -= 20
                issues.append("Transaction command is expensive")
            if 'join' in query.lower():
                efficiency -= 15
                issues.append("Join command can be slow")
            if not validation.parsed_components.get("has_time_constraint"):
                efficiency -= 25
                issues.append("No time constraint")

        # Check for tstats usage (bonus)
        if 'tstats' in query.lower():
            efficiency = min(100, efficiency + 20)

        # Best practices score
        best_practices = 100

        # Check for explicit index
        if 'index=' not in query.lower() and 'tstats' not in query.lower():
            best_practices -= 20
            recommendations.append("Specify an explicit index for better performance")

        # Check for time range
        if 'earliest' not in query.lower() and 'latest' not in query.lower():
            best_practices -= 20
            recommendations.append("Add explicit time range (earliest/latest)")

        # Check for wildcard index
        if 'index=*' in query.lower():
            best_practices -= 15
            recommendations.append("Avoid index=* - specify exact indexes")

        # Calculate overall
        overall = int((readability + efficiency + best_practices) / 3)

        return QueryScore(
            overall=max(0, min(100, overall)),
            readability=max(0, min(100, readability)),
            efficiency=max(0, min(100, efficiency)),
            best_practices=max(0, min(100, best_practices)),
            issues=issues,
            recommendations=recommendations,
        )

    def _annotate_query(self, query: str) -> str:
        """Add inline comments to a query."""
        lines = []
        pipeline = self._split_pipeline(query)

        for i, stage in enumerate(pipeline):
            stage = stage.strip()
            if not stage:
                continue

            # Generate comment
            comment = ""
            cmd_match = re.match(r'^(\w+)', stage)
            if cmd_match:
                cmd = cmd_match.group(1).lower()

                if i == 0 and cmd not in self.COMMAND_DESCRIPTIONS:
                    comment = "``` Base search: retrieves raw events"
                elif cmd == "stats":
                    comment = "``` Aggregation: calculate statistics"
                elif cmd == "timechart":
                    comment = "``` Time series: group by time for charting"
                elif cmd == "eval":
                    comment = "``` Calculation: create computed field"
                elif cmd == "where":
                    comment = "``` Filter: remove non-matching results"
                elif cmd == "table":
                    comment = "``` Format: display selected fields"
                elif cmd == "sort":
                    comment = "``` Order: arrange results"
                elif cmd == "tstats":
                    comment = "``` Fast stats: uses indexed metadata (10-100x faster)"
                elif cmd in self.COMMAND_DESCRIPTIONS:
                    comment = f"``` {self.COMMAND_DESCRIPTIONS[cmd]}"

            if i == 0:
                if comment:
                    lines.append(comment)
                lines.append(stage)
            else:
                if comment:
                    lines.append(comment)
                lines.append(f"| {stage}")

        return "\n".join(lines)

    def _split_pipeline(self, query: str) -> List[str]:
        """Split query into pipeline stages."""
        stages = []
        current = []
        depth = 0
        in_quote = False
        quote_char = None

        for i, char in enumerate(query):
            if char in '"\'`' and (i == 0 or query[i-1] != '\\'):
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
                    depth -= 1
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


# Convenience functions
def analyze_spl(input_text: str) -> AnalysisResult:
    """Analyze SPL query or generate from natural language."""
    return SPLAnalyzer().analyze(input_text)


def explain_spl(query: str) -> QueryExplanation:
    """Explain an SPL query step by step."""
    result = SPLAnalyzer().explain(query)
    return result.explanation


def generate_spl(natural_language: str) -> str:
    """Generate SPL from natural language."""
    result = SPLAnalyzer().generate(natural_language)
    return result.query


def score_spl(query: str) -> QueryScore:
    """Score an SPL query for quality."""
    result = SPLAnalyzer().validate(query)
    return result.score


# Example usage
if __name__ == "__main__":
    analyzer = SPLAnalyzer()

    print("=" * 80)
    print("SPL ANALYZER DEMO")
    print("=" * 80)

    # Test NLP to SPL
    print("\n1. Natural Language to SPL:")
    print("-" * 40)
    nl_queries = [
        "show me failed logins in the last hour",
        "count firewall blocked connections by source IP today",
        "top 10 users with failed authentication yesterday",
    ]
    for nl in nl_queries:
        result = analyzer.generate(nl)
        print(f"NL: {nl}")
        print(f"SPL: {result.query}")
        print()

    # Test Explanation
    print("\n2. Query Explanation:")
    print("-" * 40)
    query = "index=wineventlog EventCode=4625 earliest=-1h | stats count by user | where count > 10 | sort -count"
    result = analyzer.explain(query)
    print(f"Query: {query}")
    print(f"Summary: {result.explanation.summary}")
    print(f"Complexity: {result.explanation.complexity}")
    print(f"Purpose: {result.explanation.purpose}")
    print()

    # Test Optimization
    print("\n3. Query Optimization:")
    print("-" * 40)
    query = "index=firewall action=denied earliest=-1h latest=now | stats count by host"
    result = analyzer.optimize(query)
    print(f"Original: {query}")
    if result.optimization:
        print(f"Strategy: {result.optimization.strategy.value}")
        print(f"Optimized: {result.optimization.optimized}")
    print()

    # Test Scoring
    print("\n4. Query Scoring:")
    print("-" * 40)
    query = "index=* | stats count"
    result = analyzer.validate(query)
    print(f"Query: {query}")
    if result.score:
        print(f"Overall Score: {result.score.overall}/100")
        print(f"Efficiency: {result.score.efficiency}/100")
        print(f"Best Practices: {result.score.best_practices}/100")
        if result.score.recommendations:
            print(f"Recommendations: {result.score.recommendations}")
