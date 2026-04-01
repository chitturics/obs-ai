"""
SPL Deep Analysis - Next-Level Query Intelligence

Goes beyond basic optimization to provide:
1. Cardinality analysis for BY/dedup fields
2. Memory estimation for stats/join/transaction/eventstats
3. Regex complexity scoring (backtracking risk, catastrophic patterns)
4. Bucket/span optimization (bin/bucket sizing)
5. Lookup table analysis (size, placement)
6. Nested subsearch depth detection
7. Metric index / mstats detection
8. Distributed vs non-distributed command analysis
9. Query fingerprinting (structural dedup)
10. Search profiling (stage-by-stage bottleneck identification)
11. Pipeline reorder suggestions
12. Resource risk matrix (memory, CPU, disk I/O, network)

Usage:
    from shared.spl_deep_analysis import SPLDeepAnalyzer, deep_analyze

    report = deep_analyze("index=firewall | stats count by src_ip")
    print(report.summary)
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from shared.constants import (
    CPU_WEIGHTS,
    DISTRIBUTABLE_COMMANDS,
    MEMORY_WEIGHTS,
    METRIC_FIELD_PATTERNS,
    METRIC_INDEX_PATTERNS,
    NON_DISTRIBUTABLE_COMMANDS,
)
from shared.utils import (
    estimate_cardinality,
    extract_command,
    extract_time_range_seconds,
    seconds_to_human,
    split_pipeline,
)


# ---------------------------------------------------------------------------
# Enums & Data Classes
# ---------------------------------------------------------------------------

class RiskLevel(Enum):
    """Resource risk levels."""
    NONE = "none"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


class ResourceType(Enum):
    """Types of resources a query consumes."""
    MEMORY = "memory"
    CPU = "cpu"
    DISK_IO = "disk_io"
    NETWORK = "network"
    CONCURRENCY = "concurrency"


@dataclass
class CardinalityWarning:
    """Warning about high-cardinality fields in BY/dedup clauses."""
    field_name: str
    command: str
    estimated_cardinality: str  # "low", "medium", "high", "very_high"
    risk: RiskLevel
    message: str
    suggestion: str


@dataclass
class MemoryEstimate:
    """Memory footprint estimate for a command."""
    command: str
    stage: int
    estimated_mb: str  # e.g. "10-50 MB", "500+ MB"
    risk: RiskLevel
    factors: List[str]
    suggestion: Optional[str] = None


@dataclass
class RegexRisk:
    """Risk assessment for a regex pattern."""
    pattern: str
    command: str
    stage: int
    complexity_score: int  # 0-100
    risk: RiskLevel
    issues: List[str]
    suggestion: Optional[str] = None


@dataclass
class SpanSuggestion:
    """Suggestion for bucket/span optimization."""
    command: str
    stage: int
    current_span: Optional[str]
    suggested_span: Optional[str]
    time_range: Optional[str]
    message: str
    risk: RiskLevel


@dataclass
class LookupWarning:
    """Warning about lookup usage."""
    lookup_name: str
    command: str  # "lookup" or "inputlookup"
    stage: int
    message: str
    risk: RiskLevel
    suggestion: Optional[str] = None


@dataclass
class SubsearchReport:
    """Analysis of subsearch nesting."""
    max_depth: int
    total_subsearches: int
    risk: RiskLevel
    locations: List[str]
    message: str
    suggestion: Optional[str] = None


@dataclass
class MetricSuggestion:
    """Suggestion to use mstats for metric indexes."""
    detected_metric_patterns: List[str]
    current_command: str
    suggested_command: str
    message: str


@dataclass
class DistributionIssue:
    """Command that breaks search distribution."""
    command: str
    stage: int
    is_distributable: bool
    breaks_distribution: bool
    message: str
    suggestion: Optional[str] = None


@dataclass
class ResourceRisk:
    """Resource consumption risk for the entire query."""
    memory: RiskLevel
    cpu: RiskLevel
    disk_io: RiskLevel
    network: RiskLevel
    overall: RiskLevel
    memory_estimate: str
    bottlenecks: List[str]
    details: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PipelineReorderSuggestion:
    """Suggestion to reorder pipeline commands."""
    current_order: List[str]
    suggested_order: List[str]
    improvement: str
    reason: str


@dataclass
class SearchProfile:
    """Stage-by-stage profiling of a search."""
    stages: List[Dict[str, Any]]
    bottleneck_stage: Optional[int]
    bottleneck_reason: str
    total_estimated_cost: int
    optimization_score: int  # 0-100, higher = more optimized


@dataclass
class DeepAnalysisResult:
    """Complete deep analysis report."""
    query: str
    fingerprint: str

    # Gap checks (1-8)
    cardinality_warnings: List[CardinalityWarning]
    memory_estimates: List[MemoryEstimate]
    regex_risks: List[RegexRisk]
    span_suggestions: List[SpanSuggestion]
    lookup_warnings: List[LookupWarning]
    subsearch_report: SubsearchReport
    metric_suggestions: List[MetricSuggestion]
    distribution_issues: List[DistributionIssue]

    # Next-level (9-12)
    resource_risk: ResourceRisk
    profile: SearchProfile
    reorder_suggestions: List[PipelineReorderSuggestion]

    # Summary
    total_issues: int = 0
    critical_issues: int = 0
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict for API response."""
        return {
            "query": self.query,
            "fingerprint": self.fingerprint,
            "total_issues": self.total_issues,
            "critical_issues": self.critical_issues,
            "summary": self.summary,
            "cardinality_warnings": [
                {"field": w.field_name, "command": w.command,
                 "cardinality": w.estimated_cardinality, "risk": w.risk.value,
                 "message": w.message, "suggestion": w.suggestion}
                for w in self.cardinality_warnings
            ],
            "memory_estimates": [
                {"command": m.command, "stage": m.stage, "estimated_mb": m.estimated_mb,
                 "risk": m.risk.value, "factors": m.factors, "suggestion": m.suggestion}
                for m in self.memory_estimates
            ],
            "regex_risks": [
                {"pattern": r.pattern, "command": r.command, "stage": r.stage,
                 "complexity": r.complexity_score, "risk": r.risk.value,
                 "issues": r.issues, "suggestion": r.suggestion}
                for r in self.regex_risks
            ],
            "span_suggestions": [
                {"command": s.command, "stage": s.stage, "current_span": s.current_span,
                 "suggested_span": s.suggested_span, "message": s.message, "risk": s.risk.value}
                for s in self.span_suggestions
            ],
            "lookup_warnings": [
                {"lookup_name": l.lookup_name, "command": l.command, "stage": l.stage,
                 "message": l.message, "risk": l.risk.value, "suggestion": l.suggestion}
                for l in self.lookup_warnings
            ],
            "subsearch_report": {
                "max_depth": self.subsearch_report.max_depth,
                "total_subsearches": self.subsearch_report.total_subsearches,
                "risk": self.subsearch_report.risk.value,
                "message": self.subsearch_report.message,
                "suggestion": self.subsearch_report.suggestion,
            },
            "metric_suggestions": [
                {"patterns": m.detected_metric_patterns, "current": m.current_command,
                 "suggested": m.suggested_command, "message": m.message}
                for m in self.metric_suggestions
            ],
            "distribution_issues": [
                {"command": d.command, "stage": d.stage, "distributable": d.is_distributable,
                 "breaks_distribution": d.breaks_distribution, "message": d.message,
                 "suggestion": d.suggestion}
                for d in self.distribution_issues
            ],
            "resource_risk": {
                "memory": self.resource_risk.memory.value,
                "cpu": self.resource_risk.cpu.value,
                "disk_io": self.resource_risk.disk_io.value,
                "network": self.resource_risk.network.value,
                "overall": self.resource_risk.overall.value,
                "memory_estimate": self.resource_risk.memory_estimate,
                "bottlenecks": self.resource_risk.bottlenecks,
            },
            "profile": {
                "stages": self.profile.stages,
                "bottleneck_stage": self.profile.bottleneck_stage,
                "bottleneck_reason": self.profile.bottleneck_reason,
                "total_cost": self.profile.total_estimated_cost,
                "optimization_score": self.profile.optimization_score,
            },
            "reorder_suggestions": [
                {"current": r.current_order, "suggested": r.suggested_order,
                 "improvement": r.improvement, "reason": r.reason}
                for r in self.reorder_suggestions
            ],
        }




# ---------------------------------------------------------------------------
# SPL Deep Analyzer
# ---------------------------------------------------------------------------

class SPLDeepAnalyzer:
    """
    Next-level SPL query analysis engine.

    Goes beyond basic validation/optimization to provide deep intelligence
    about resource consumption, performance risks, and architectural issues.
    """

    # -------------------------------------------------------------------
    # 1. Cardinality Analysis
    # -------------------------------------------------------------------
    def analyze_cardinality(self, query: str) -> List[CardinalityWarning]:
        """Analyze fields in BY/dedup clauses for high cardinality risks."""
        warnings = []
        stages = split_pipeline(query)

        for i, stage in enumerate(stages):
            stage_stripped = stage.strip()
            cmd = extract_command(stage_stripped)

            # Extract BY fields from stats/timechart/chart/eventstats/streamstats/top/rare
            if cmd in ("stats", "timechart", "chart", "eventstats", "streamstats",
                        "top", "rare", "sistats", "sitimechart", "sichart"):
                by_match = re.search(r"\bby\s+(.+?)(?:\s*$|\s*\|)", stage_stripped, re.IGNORECASE)
                if by_match:
                    by_fields = [f.strip().split("=")[0].strip()
                                 for f in re.split(r"[,\s]+", by_match.group(1))
                                 if f.strip() and not f.startswith("span=")]
                    for fld in by_fields:
                        if fld.startswith("_time"):
                            continue
                        warning = self._assess_field_cardinality(fld, cmd)
                        if warning:
                            warnings.append(warning)

            # Extract fields from dedup
            elif cmd == "dedup":
                field_match = re.match(r"dedup\s+(?:\d+\s+)?(.+?)(?:\s+sortby|\s*$|\s*\|)",
                                        stage_stripped, re.IGNORECASE)
                if field_match:
                    dedup_fields = [f.strip() for f in re.split(r"[,\s]+", field_match.group(1))
                                    if f.strip()]
                    for fld in dedup_fields:
                        warning = self._assess_field_cardinality(fld, cmd)
                        if warning:
                            warnings.append(warning)

            # dc() function in stats
            if cmd in ("stats", "eventstats", "streamstats"):
                for dc_match in re.finditer(r"dc\s*\(\s*(\w+)\s*\)", stage_stripped):
                    fld = dc_match.group(1)
                    card = estimate_cardinality(fld)
                    if card in ("high", "very_high"):
                        warnings.append(CardinalityWarning(
                            field_name=fld,
                            command=f"dc({fld})",
                            estimated_cardinality=card,
                            risk=RiskLevel.HIGH if card == "very_high" else RiskLevel.MODERATE,
                            message=f"dc({fld}) on {card}-cardinality field is memory-intensive",
                            suggestion=f"Consider using estdc({fld}) for approximate distinct count (much faster)",
                        ))

        return warnings

    def _assess_field_cardinality(self, field_name: str, command: str) -> Optional[CardinalityWarning]:
        """Assess cardinality risk for a single field."""
        card = estimate_cardinality(field_name)
        if card == "very_high":
            return CardinalityWarning(
                field_name=field_name,
                command=command,
                estimated_cardinality=card,
                risk=RiskLevel.CRITICAL,
                message=f"'{field_name}' in '{command} by' has very high cardinality — "
                        f"will create millions of buckets consuming excessive memory",
                suggestion=f"Add '| where count > N' after aggregation, use 'top 100 {field_name}', "
                           f"or pre-filter with a more selective base search",
            )
        elif card == "high":
            return CardinalityWarning(
                field_name=field_name,
                command=command,
                estimated_cardinality=card,
                risk=RiskLevel.HIGH,
                message=f"'{field_name}' in '{command} by' has high cardinality — "
                        f"may create hundreds of thousands of buckets",
                suggestion=f"Consider adding 'limit=100' or filtering results after aggregation",
            )
        return None

    # -------------------------------------------------------------------
    # 2. Memory Estimation
    # -------------------------------------------------------------------
    def estimate_memory(self, query: str) -> List[MemoryEstimate]:
        """Estimate memory footprint per pipeline stage."""
        estimates = []
        stages = split_pipeline(query)

        for i, stage in enumerate(stages):
            stage_stripped = stage.strip()
            cmd = extract_command(stage_stripped)
            if cmd == "unknown":
                continue
            weight = MEMORY_WEIGHTS.get(cmd, 1.0)

            if weight < 2.0:
                continue  # Skip low-memory commands

            factors = []
            risk = RiskLevel.LOW
            estimate = "< 10 MB"
            suggestion = None

            if cmd == "transaction":
                factors.append("Holds ALL matching events in memory until transaction boundaries are found")
                factors.append("Memory grows linearly with event count between start/end markers")
                by_match = re.search(r"transaction\s+(\w+)", stage_stripped)
                if by_match:
                    card = estimate_cardinality(by_match.group(1))
                    if card in ("high", "very_high"):
                        factors.append(f"Grouping by high-cardinality field '{by_match.group(1)}'")
                        estimate = "500+ MB (potential OOM)"
                        risk = RiskLevel.CRITICAL
                    else:
                        estimate = "100-500 MB"
                        risk = RiskLevel.HIGH
                else:
                    estimate = "100-500 MB"
                    risk = RiskLevel.HIGH
                suggestion = "Replace with: stats min(_time) as start, max(_time) as end, values(*) as events by session_field"

            elif cmd == "join":
                factors.append("Subsearch results buffered in memory (50K row limit)")
                factors.append("Hash table built for join keys")
                estimate = "50-200 MB"
                risk = RiskLevel.HIGH
                suggestion = "Use 'lookup' for enrichment or 'stats' for aggregation-based joins"

            elif cmd == "eventstats":
                factors.append("Buffers entire result set to add aggregated fields back to each event")
                by_match = re.search(r"\bby\s+(.+?)(?:\s*$|\s*\|)", stage_stripped, re.IGNORECASE)
                if by_match:
                    fields = [f.strip() for f in re.split(r"[,\s]+", by_match.group(1)) if f.strip()]
                    has_high_card = any(estimate_cardinality(f) in ("high", "very_high") for f in fields)
                    if has_high_card:
                        estimate = "200-500 MB"
                        risk = RiskLevel.HIGH
                        factors.append("High-cardinality BY fields increase memory")
                    else:
                        estimate = "50-200 MB"
                        risk = RiskLevel.MODERATE
                else:
                    estimate = "100-300 MB"
                    risk = RiskLevel.MODERATE
                suggestion = "If you only need aggregated values, use 'stats' instead"

            elif cmd == "streamstats":
                window_match = re.search(r"window\s*=\s*(\d+)", stage_stripped)
                if window_match:
                    window = int(window_match.group(1))
                    if window > 10000:
                        estimate = "100-500 MB"
                        risk = RiskLevel.HIGH
                        factors.append(f"Large window size ({window}) keeps many events in memory")
                    elif window > 1000:
                        estimate = "10-50 MB"
                        risk = RiskLevel.MODERATE
                        factors.append(f"Window size {window}")
                    else:
                        estimate = "< 10 MB"
                        risk = RiskLevel.LOW
                        factors.append(f"Small window size ({window})")
                else:
                    estimate = "50-200 MB"
                    risk = RiskLevel.MODERATE
                    factors.append("No window limit — accumulates over entire result set")
                    suggestion = "Add window=N to limit memory usage"

            elif cmd == "sort":
                factors.append("Must load all results into memory for sorting")
                limit_match = re.search(r"sort\s+(\d+)", stage_stripped)
                if limit_match:
                    limit = int(limit_match.group(1))
                    if limit <= 1000:
                        estimate = "< 10 MB"
                        risk = RiskLevel.LOW
                        factors.append(f"Limited to {limit} results")
                    else:
                        estimate = "10-100 MB"
                        risk = RiskLevel.MODERATE
                else:
                    estimate = "50-500 MB"
                    risk = RiskLevel.HIGH
                    factors.append("No limit — sorts ALL results")
                    suggestion = "Add a limit: 'sort 1000 -count' or use 'head' after sort"

            elif cmd in ("stats", "timechart", "chart"):
                by_match = re.search(r"\bby\s+(.+?)(?:\s*$|\s*\|)", stage_stripped, re.IGNORECASE)
                if by_match:
                    fields = [f.strip() for f in re.split(r"[,\s]+", by_match.group(1))
                              if f.strip() and not f.startswith("span=")]
                    high_card_fields = [f for f in fields
                                         if estimate_cardinality(f) in ("high", "very_high")]
                    if high_card_fields:
                        estimate = "100-500 MB"
                        risk = RiskLevel.HIGH
                        factors.append(f"High-cardinality BY field(s): {', '.join(high_card_fields)}")
                        suggestion = f"Add 'limit=100' or filter before aggregation"
                    elif len(fields) >= 3:
                        estimate = "50-200 MB"
                        risk = RiskLevel.MODERATE
                        factors.append(f"Multiple BY fields ({len(fields)}) multiply bucket count")
                    else:
                        estimate = "10-50 MB"
                        risk = RiskLevel.LOW
                        factors.append("Low-cardinality grouping")
                else:
                    estimate = "< 10 MB"
                    risk = RiskLevel.NONE
                    factors.append("No BY clause — single aggregation bucket")
                    continue  # Skip adding this one

            elif cmd == "dedup":
                field_match = re.match(r"dedup\s+(?:\d+\s+)?(.+?)(?:\s+sortby|\s*$|\s*\|)",
                                        stage_stripped, re.IGNORECASE)
                if field_match:
                    fields = [f.strip() for f in re.split(r"[,\s]+", field_match.group(1)) if f.strip()]
                    high_card = [f for f in fields if estimate_cardinality(f) in ("high", "very_high")]
                    if high_card:
                        estimate = "200-500 MB"
                        risk = RiskLevel.HIGH
                        factors.append(f"Dedup on high-cardinality field(s): {', '.join(high_card)}")
                        suggestion = "Consider 'stats latest(*) by field' or add a time filter"

            elif cmd in ("cluster", "kmeans"):
                estimate = "200-1000 MB"
                risk = RiskLevel.CRITICAL
                factors.append("ML algorithms require full dataset in memory")
                suggestion = "Pre-aggregate or sample data before clustering"

            elif cmd == "mvexpand":
                factors.append("Can multiply event count by multivalue field size")
                estimate = "10-100 MB"
                risk = RiskLevel.MODERATE
                limit_match = re.search(r"limit\s*=\s*(\d+)", stage_stripped)
                if limit_match:
                    factors.append(f"Limited to {limit_match.group(1)} expansions")
                    risk = RiskLevel.LOW
                else:
                    suggestion = "Add limit=N to prevent runaway expansion"

            else:
                estimate = "10-50 MB"
                risk = RiskLevel.LOW
                factors.append(f"'{cmd}' has moderate memory usage")

            estimates.append(MemoryEstimate(
                command=cmd, stage=i, estimated_mb=estimate,
                risk=risk, factors=factors, suggestion=suggestion,
            ))

        return estimates

    # -------------------------------------------------------------------
    # 3. Regex Complexity Analysis
    # -------------------------------------------------------------------
    def analyze_regex_complexity(self, query: str) -> List[RegexRisk]:
        """Score regex patterns for complexity and backtracking risk."""
        risks = []
        stages = split_pipeline(query)

        for i, stage in enumerate(stages):
            stage_stripped = stage.strip()
            cmd = extract_command(stage_stripped)
            if cmd == "unknown":
                continue

            if cmd not in ("rex", "regex"):
                continue

            # Extract regex pattern
            patterns = re.findall(r'"((?:[^"\\]|\\.)*)"', stage_stripped)
            if not patterns:
                patterns = re.findall(r"'((?:[^'\\]|\\.)*)'", stage_stripped)

            for pattern in patterns:
                # Skip sed mode replacement strings
                if pattern.startswith("s/"):
                    # Extract the actual regex from sed expression
                    parts = pattern.split("/")
                    if len(parts) >= 3:
                        pattern = parts[1]

                score, issues = self._score_regex(pattern)
                if score > 20:  # Only report non-trivial complexity
                    risk = RiskLevel.LOW
                    if score >= 80:
                        risk = RiskLevel.CRITICAL
                    elif score >= 60:
                        risk = RiskLevel.HIGH
                    elif score >= 40:
                        risk = RiskLevel.MODERATE

                    suggestion = None
                    if score >= 60:
                        suggestion = ("Consider pre-filtering events before regex extraction, "
                                      "or use indexed field extraction in props.conf for frequently used patterns")
                    elif "backtrack" in " ".join(issues).lower():
                        suggestion = "Use atomic groups or possessive quantifiers to prevent backtracking"

                    risks.append(RegexRisk(
                        pattern=pattern, command=cmd, stage=i,
                        complexity_score=score, risk=risk,
                        issues=issues, suggestion=suggestion,
                    ))

        return risks

    def _score_regex(self, pattern: str) -> Tuple[int, List[str]]:
        """Score a regex pattern for complexity. Returns (score 0-100, issues)."""
        score = 0
        issues = []

        # Nested quantifiers (catastrophic backtracking risk): (a+)+, (a*)*
        if re.search(r"\([^)]*[+*][^)]*\)[+*]", pattern):
            score += 40
            issues.append("Nested quantifiers detected — catastrophic backtracking risk")

        # Alternation with overlapping patterns: (a|ab|abc)
        alternations = re.findall(r"\(([^)]+\|[^)]+)\)", pattern)
        for alt in alternations:
            branches = alt.split("|")
            if len(branches) > 5:
                score += 15
                issues.append(f"Complex alternation with {len(branches)} branches")
            # Check for overlapping prefixes
            for j, b1 in enumerate(branches):
                for b2 in branches[j+1:]:
                    if b1.startswith(b2[:2]) or b2.startswith(b1[:2]):
                        score += 10
                        issues.append("Alternation branches may overlap — causes backtracking")
                        break

        # Unbounded repetition on _raw (very expensive)
        if re.search(r"\.\*.*\.\*", pattern):
            score += 20
            issues.append("Multiple .* (greedy any-match) — scans entire field for each event")

        # Named capture groups (performance is fine, but adds complexity)
        captures = re.findall(r"\(\?P?<(\w+)>", pattern)
        if len(captures) > 5:
            score += 10
            issues.append(f"{len(captures)} capture groups — consider extracting fewer fields")

        # Lookahead/lookbehind (CPU-intensive)
        if re.search(r"\(\?[=!<]", pattern):
            score += 15
            issues.append("Lookahead/lookbehind assertions add CPU overhead")

        # Backreferences
        if re.search(r"\\[1-9]", pattern):
            score += 15
            issues.append("Backreferences prevent regex engine optimizations")

        # Very long pattern
        if len(pattern) > 200:
            score += 10
            issues.append(f"Very long pattern ({len(pattern)} chars) — hard to maintain and optimize")

        # Character classes with negation on large fields
        if re.search(r"\[\^[^\]]{10,}\]", pattern):
            score += 5
            issues.append("Large negated character class")

        # Simple quantifier count
        quantifier_count = len(re.findall(r"[+*?]|\{\d+", pattern))
        if quantifier_count > 8:
            score += min(15, quantifier_count * 2)
            issues.append(f"High quantifier density ({quantifier_count} quantifiers)")

        return min(100, score), issues

    # -------------------------------------------------------------------
    # 4. Bucket/Span Optimization
    # -------------------------------------------------------------------
    def analyze_bucket_span(self, query: str) -> List[SpanSuggestion]:
        """Analyze bin/bucket/timechart span for optimization."""
        suggestions = []
        stages = split_pipeline(query)

        # Extract time range from query
        time_range_seconds = extract_time_range_seconds(query)

        for i, stage in enumerate(stages):
            stage_stripped = stage.strip()
            cmd = extract_command(stage_stripped)
            if cmd == "unknown":
                continue

            if cmd not in ("bin", "bucket", "timechart"):
                continue

            current_span = None
            span_match = re.search(r"span\s*=\s*(\d+[smhdw]|auto)", stage_stripped, re.IGNORECASE)
            if span_match:
                current_span = span_match.group(1)

            if cmd == "timechart":
                if not current_span and time_range_seconds:
                    # No span specified — Splunk auto-selects, but we can suggest
                    suggested = self._suggest_span_for_range(time_range_seconds)
                    if suggested:
                        suggestions.append(SpanSuggestion(
                            command=cmd, stage=i, current_span=None,
                            suggested_span=suggested,
                            time_range=seconds_to_human(time_range_seconds),
                            message=f"No explicit span — Splunk will auto-select. "
                                    f"For a {seconds_to_human(time_range_seconds)} range, "
                                    f"span={suggested} gives good granularity without too many buckets",
                            risk=RiskLevel.LOW,
                        ))
                elif current_span and time_range_seconds:
                    span_seconds = self._parse_span_to_seconds(current_span)
                    if span_seconds and time_range_seconds:
                        bucket_count = time_range_seconds / span_seconds
                        if bucket_count > 10000:
                            suggested = self._suggest_span_for_range(time_range_seconds)
                            suggestions.append(SpanSuggestion(
                                command=cmd, stage=i, current_span=current_span,
                                suggested_span=suggested,
                                time_range=seconds_to_human(time_range_seconds),
                                message=f"span={current_span} creates ~{int(bucket_count)} buckets "
                                        f"for a {seconds_to_human(time_range_seconds)} range — "
                                        f"excessive granularity hurts performance",
                                risk=RiskLevel.HIGH,
                            ))
                        elif bucket_count < 3:
                            suggested = self._suggest_span_for_range(time_range_seconds)
                            suggestions.append(SpanSuggestion(
                                command=cmd, stage=i, current_span=current_span,
                                suggested_span=suggested,
                                time_range=seconds_to_human(time_range_seconds),
                                message=f"span={current_span} creates only ~{int(bucket_count)} buckets "
                                        f"for a {seconds_to_human(time_range_seconds)} range — "
                                        f"too coarse to see trends",
                                risk=RiskLevel.LOW,
                            ))

            elif cmd in ("bin", "bucket"):
                # Check if _time is being binned
                if "_time" in stage_stripped and current_span and time_range_seconds:
                    span_seconds = self._parse_span_to_seconds(current_span)
                    if span_seconds:
                        bucket_count = time_range_seconds / span_seconds
                        if bucket_count > 10000:
                            suggested = self._suggest_span_for_range(time_range_seconds)
                            suggestions.append(SpanSuggestion(
                                command=cmd, stage=i, current_span=current_span,
                                suggested_span=suggested,
                                time_range=seconds_to_human(time_range_seconds),
                                message=f"bin _time span={current_span} creates ~{int(bucket_count)} "
                                        f"time buckets — consider larger span",
                                risk=RiskLevel.HIGH,
                            ))

        return suggestions

    def _suggest_span_for_range(self, seconds: int) -> str:
        """Suggest optimal span for a given time range (targeting 100-500 buckets)."""
        target_buckets = 200
        ideal_span = seconds / target_buckets
        if ideal_span <= 10:
            return "10s"
        elif ideal_span <= 60:
            return "1m"
        elif ideal_span <= 300:
            return "5m"
        elif ideal_span <= 900:
            return "15m"
        elif ideal_span <= 3600:
            return "1h"
        elif ideal_span <= 14400:
            return "4h"
        elif ideal_span <= 43200:
            return "12h"
        else:
            return "1d"

    def _parse_span_to_seconds(self, span: str) -> Optional[int]:
        """Parse a span like '5m' to seconds."""
        if span == "auto":
            return None
        match = re.match(r"(\d+)([smhdw])", span, re.IGNORECASE)
        if match:
            value = int(match.group(1))
            unit = match.group(2).lower()
            multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
            return value * multipliers.get(unit, 0)
        return None

    # -------------------------------------------------------------------
    # 5. Lookup Analysis
    # -------------------------------------------------------------------
    def analyze_lookups(self, query: str) -> List[LookupWarning]:
        """Analyze lookup usage for performance concerns."""
        warnings = []
        stages = split_pipeline(query)

        lookup_count = 0
        for i, stage in enumerate(stages):
            stage_stripped = stage.strip()
            cmd = extract_command(stage_stripped)
            if cmd == "unknown":
                continue

            if cmd == "lookup":
                lookup_count += 1
                name_match = re.search(r"lookup\s+(\w+)", stage_stripped)
                lookup_name = name_match.group(1) if name_match else "unknown"

                # Check if OUTPUT is specified (best practice)
                if "OUTPUT" not in stage_stripped and "OUTPUTNEW" not in stage_stripped:
                    warnings.append(LookupWarning(
                        lookup_name=lookup_name, command="lookup", stage=i,
                        message=f"Lookup '{lookup_name}' without OUTPUT clause — "
                                f"returns ALL fields from lookup table",
                        risk=RiskLevel.MODERATE,
                        suggestion=f"Add OUTPUT field1, field2 to only retrieve needed fields",
                    ))

                # Check placement — lookups after aggregation are wasted
                has_prior_agg = any(
                    re.match(r"\s*(stats|timechart|chart|top|rare)\b", stages[j], re.IGNORECASE)
                    for j in range(i)
                )
                if not has_prior_agg and i > 0:
                    # Lookup before aggregation is fine
                    pass
                elif has_prior_agg:
                    # Lookup after aggregation — check if it's enrichment (ok) or wasteful
                    warnings.append(LookupWarning(
                        lookup_name=lookup_name, command="lookup", stage=i,
                        message=f"Lookup '{lookup_name}' after aggregation — "
                                f"ensure this is intentional enrichment and not redundant",
                        risk=RiskLevel.LOW,
                    ))

            elif cmd == "inputlookup":
                lookup_count += 1
                name_match = re.search(r"inputlookup\s+(\w+)", stage_stripped)
                lookup_name = name_match.group(1) if name_match else "unknown"

                # Check for where clause (best practice)
                if "where" not in stage_stripped.lower():
                    warnings.append(LookupWarning(
                        lookup_name=lookup_name, command="inputlookup", stage=i,
                        message=f"inputlookup '{lookup_name}' without WHERE clause — "
                                f"loads entire lookup table into memory",
                        risk=RiskLevel.MODERATE,
                        suggestion="Add a WHERE clause to filter at source: "
                                   f"| inputlookup {lookup_name} where status=\"active\"",
                    ))

        if lookup_count > 3:
            warnings.append(LookupWarning(
                lookup_name="(multiple)", command="lookup", stage=0,
                message=f"Query uses {lookup_count} lookups — each adds I/O and memory overhead",
                risk=RiskLevel.HIGH,
                suggestion="Consider combining lookups or pre-joining data",
            ))

        return warnings

    # -------------------------------------------------------------------
    # 6. Subsearch Depth Detection
    # -------------------------------------------------------------------
    def analyze_subsearch_depth(self, query: str) -> SubsearchReport:
        """Detect nested subsearch depth and total count."""
        max_depth = 0
        current_depth = 0
        total_subsearches = 0
        locations = []
        in_quote = False
        quote_char = None

        for i, char in enumerate(query):
            if char in ('"', "'") and (i == 0 or query[i-1] != '\\'):
                if not in_quote:
                    in_quote = True
                    quote_char = char
                elif char == quote_char:
                    in_quote = False
                    quote_char = None
            if in_quote:
                continue

            if char == '[':
                # Heuristic: subsearches start with [search, [|, or [inputlookup etc.
                # Skip regex character classes like [^\d] or [a-z]
                rest = query[i+1:i+20].lstrip()
                if rest and (rest[0] == '^' or (len(rest) >= 2 and rest[1] == '-')):
                    continue  # Likely regex character class, not subsearch
                current_depth += 1
                total_subsearches += 1
                max_depth = max(max_depth, current_depth)
                # Get context around the subsearch
                start = max(0, i - 20)
                end = min(len(query), i + 40)
                locations.append(f"...{query[start:end]}...")
            elif char == ']':
                current_depth = max(0, current_depth - 1)

        risk = RiskLevel.NONE
        message = "No subsearches detected"
        suggestion = None

        if max_depth >= 3:
            risk = RiskLevel.CRITICAL
            message = (f"Deeply nested subsearches (depth {max_depth}, {total_subsearches} total) — "
                       f"each level adds latency and has 50K result limit")
            suggestion = ("Flatten nested subsearches using intermediate lookups or "
                         "break into multiple scheduled searches")
        elif max_depth == 2:
            risk = RiskLevel.HIGH
            message = (f"Two levels of nested subsearches ({total_subsearches} total) — "
                       f"inner subsearches have 50K result limits")
            suggestion = "Consider flattening with lookup tables"
        elif max_depth == 1:
            if total_subsearches > 2:
                risk = RiskLevel.MODERATE
                message = f"{total_subsearches} subsearches at depth 1 — each adds overhead"
                suggestion = "Consider using multisearch or union for parallel execution"
            else:
                risk = RiskLevel.LOW
                message = f"{total_subsearches} subsearch(es) at depth 1"

        return SubsearchReport(
            max_depth=max_depth, total_subsearches=total_subsearches,
            risk=risk, locations=locations[:5], message=message, suggestion=suggestion,
        )

    # -------------------------------------------------------------------
    # 7. Metric Index / mstats Detection
    # -------------------------------------------------------------------
    def detect_metric_index(self, query: str) -> List[MetricSuggestion]:
        """Detect queries that should use mstats for metric indexes."""
        suggestions = []
        ql = query.lower()

        # Skip if already using mstats/mcatalog
        if "mstats" in ql or "mcatalog" in ql:
            return suggestions

        # Check for metric index patterns
        metric_index_detected = False
        detected_patterns = []
        for pattern in METRIC_INDEX_PATTERNS:
            match = re.search(pattern, query, re.IGNORECASE)
            if match:
                metric_index_detected = True
                detected_patterns.append(match.group(0))

        # Check for metric field patterns
        metric_fields_detected = []
        for pattern in METRIC_FIELD_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                metric_fields_detected.append(pattern.replace(r"\b", "").replace("(?:", ""))

        # If we detect metric patterns and the query uses stats/timechart
        if metric_index_detected and any(cmd in ql for cmd in ("stats", "timechart", "chart")):
            current_cmd = "stats" if "stats" in ql else "timechart" if "timechart" in ql else "chart"
            suggestions.append(MetricSuggestion(
                detected_metric_patterns=detected_patterns,
                current_command=current_cmd,
                suggested_command="mstats",
                message=(f"Query targets what appears to be a metric index ({', '.join(detected_patterns)}). "
                         f"Consider using '| mstats' instead of '| {current_cmd}' for metric data — "
                         f"mstats reads from metric store directly, which is much faster than event search."),
            ))

        # If we see metric field patterns without explicit metric index
        if metric_fields_detected and not metric_index_detected:
            if any(cmd in ql for cmd in ("stats", "timechart")) and "avg(" in ql or "max(" in ql or "min(" in ql:
                suggestions.append(MetricSuggestion(
                    detected_metric_patterns=metric_fields_detected[:3],
                    current_command="stats/timechart",
                    suggested_command="mstats",
                    message=("Query aggregates metric-like fields (cpu, memory, latency, etc.). "
                             "If this data is in a metric index, use '| mstats' for dramatically faster queries. "
                             "Check with: | mcatalog values(metric_name) where index=<your_index>"),
                ))

        return suggestions

    # -------------------------------------------------------------------
    # 8. Distribution Analysis
    # -------------------------------------------------------------------
    def analyze_distribution(self, query: str) -> List[DistributionIssue]:
        """Analyze which commands break distributed search execution."""
        issues = []
        stages = split_pipeline(query)
        distribution_broken_at = None

        for i, stage in enumerate(stages):
            stage_stripped = stage.strip()
            cmd = extract_command(stage_stripped)
            if cmd == "unknown":
                continue

            is_distributable = cmd in DISTRIBUTABLE_COMMANDS
            breaks_distribution = cmd in NON_DISTRIBUTABLE_COMMANDS

            if breaks_distribution and distribution_broken_at is None:
                distribution_broken_at = i

                suggestion = None
                if cmd == "sort":
                    suggestion = "Add a limit to sort: 'sort 1000 -field' to reduce data before centralized sorting"
                elif cmd == "transaction":
                    suggestion = "Replace with distributable stats: 'stats min(_time) max(_time) values(*) by field'"
                elif cmd == "streamstats":
                    suggestion = "Consider if eventstats (distributable for simple aggregations) could work instead"
                elif cmd == "dedup":
                    suggestion = "Consider 'stats first(*) by field' as a distributable alternative"
                elif cmd in ("head", "tail"):
                    suggestion = f"'{cmd}' forces all results to search head. If possible, aggregate before limiting"

                issues.append(DistributionIssue(
                    command=cmd, stage=i,
                    is_distributable=False, breaks_distribution=True,
                    message=(f"'{cmd}' at stage {i+1} forces all subsequent processing to the search head. "
                             f"All prior stages run on indexers, but from here everything is centralized."),
                    suggestion=suggestion,
                ))

            elif not is_distributable and distribution_broken_at is None:
                # Unknown command — might break distribution
                issues.append(DistributionIssue(
                    command=cmd, stage=i,
                    is_distributable=False, breaks_distribution=False,
                    message=f"'{cmd}' is not in the known distributable commands list — may break distribution",
                ))

        # If no distribution-breaking commands found, that's good
        if not issues:
            pass  # All clean

        return issues

    # -------------------------------------------------------------------
    # 9. Query Fingerprinting
    # -------------------------------------------------------------------
    def fingerprint_query(self, query: str) -> str:
        """
        Generate a structural fingerprint for a query.

        Normalizes the query structure so that semantically identical queries
        with different literal values produce the same fingerprint.
        This enables dedup of similar queries in optimization caches.
        """
        normalized = query.strip()

        # Normalize whitespace
        normalized = re.sub(r"\s+", " ", normalized)

        # Replace literal values with placeholders
        # index=anything → index=?
        normalized = re.sub(r"index\s*=\s*[^\s|]+", "index=?", normalized, flags=re.IGNORECASE)
        # sourcetype=anything → sourcetype=?
        normalized = re.sub(r"sourcetype\s*=\s*[^\s|]+", "sourcetype=?", normalized, flags=re.IGNORECASE)
        # field=value → field=?
        normalized = re.sub(r"(\w+)\s*=\s*\"[^\"]+\"", r"\1=?", normalized)
        normalized = re.sub(r"(\w+)\s*=\s*'[^']+'", r"\1=?", normalized)
        normalized = re.sub(r"(\w+)\s*=\s*[^\s|,)]+", r"\1=?", normalized)
        # Numbers → #
        normalized = re.sub(r"\b\d+\b", "#", normalized)
        # TERM(anything) → TERM(?)
        normalized = re.sub(r"TERM\([^)]+\)", "TERM(?)", normalized, flags=re.IGNORECASE)
        # PREFIX(anything) → PREFIX(?)
        normalized = re.sub(r"PREFIX\([^)]+\)", "PREFIX(?)", normalized, flags=re.IGNORECASE)
        # Quoted strings → "?"
        normalized = re.sub(r'"[^"]*"', '"?"', normalized)

        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    # -------------------------------------------------------------------
    # 10. Search Profiling
    # -------------------------------------------------------------------
    def profile_search(self, query: str) -> SearchProfile:
        """Generate stage-by-stage profiling with bottleneck identification."""
        stages_info = []
        stages = split_pipeline(query)
        max_cost = 0
        max_cost_stage = None
        max_cost_reason = ""
        total_cost = 0

        for i, stage in enumerate(stages):
            stage_stripped = stage.strip()
            cmd = extract_command(stage_stripped)

            # Base cost from command type
            if cmd in MEMORY_WEIGHTS:
                mem_cost = MEMORY_WEIGHTS[cmd]
            else:
                mem_cost = 1.0

            if cmd in CPU_WEIGHTS:
                cpu_cost = CPU_WEIGHTS[cmd]
            else:
                cpu_cost = 1.0

            # Check for amplifying factors
            amplifiers = []
            stage_cost = max(mem_cost, cpu_cost) * 10  # Scale to 0-100

            # High cardinality BY fields amplify cost
            by_match = re.search(r"\bby\s+(.+?)(?:\s*$|\s*\|)", stage_stripped, re.IGNORECASE)
            if by_match:
                fields = [f.strip() for f in re.split(r"[,\s]+", by_match.group(1))
                          if f.strip() and not f.startswith("span=")]
                for f in fields:
                    card = estimate_cardinality(f)
                    if card == "very_high":
                        stage_cost *= 2.0
                        amplifiers.append(f"high-cardinality BY field '{f}'")
                    elif card == "high":
                        stage_cost *= 1.5
                        amplifiers.append(f"medium-cardinality BY field '{f}'")

            # Subsearch amplifies cost
            if "[" in stage_stripped:
                stage_cost *= 1.5
                amplifiers.append("contains subsearch")

            # Note: Time range is often set via UI time picker, not in the query.
            # We don't penalize missing earliest/latest.

            # Wildcard index
            if "index=*" in stage_stripped.lower():
                stage_cost *= 2.0
                amplifiers.append("wildcard index scan")

            stage_cost = min(100, int(stage_cost))
            total_cost += stage_cost

            if stage_cost > max_cost:
                max_cost = stage_cost
                max_cost_stage = i
                max_cost_reason = f"'{cmd}' command" + (f" (amplified by: {', '.join(amplifiers)})" if amplifiers else "")

            stages_info.append({
                "stage": i + 1,
                "command": cmd,
                "raw": stage_stripped[:100],
                "cost": stage_cost,
                "memory_weight": mem_cost,
                "cpu_weight": cpu_cost,
                "amplifiers": amplifiers,
                "distributable": cmd in DISTRIBUTABLE_COMMANDS,
            })

        # Calculate optimization score (inverted: lower cost = higher score)
        num_stages = len(stages_info)
        avg_cost = total_cost / num_stages if num_stages else 0
        optimization_score = max(0, min(100, 100 - int(avg_cost)))

        return SearchProfile(
            stages=stages_info,
            bottleneck_stage=max_cost_stage,
            bottleneck_reason=max_cost_reason,
            total_estimated_cost=min(100, total_cost),
            optimization_score=optimization_score,
        )

    # -------------------------------------------------------------------
    # 11. Pipeline Reorder Suggestions
    # -------------------------------------------------------------------
    def suggest_pipeline_reorder(self, query: str) -> List[PipelineReorderSuggestion]:
        """Suggest optimal command ordering for the pipeline."""
        suggestions = []
        stages = split_pipeline(query)
        commands = []

        for stage in stages:
            cmd = extract_command(stage)
            if cmd != "unknown":
                commands.append(cmd)

        if len(commands) < 3:
            return suggestions

        # Rule 1: fields should come early (right after search)
        if "fields" in commands:
            fields_idx = commands.index("fields")
            if fields_idx > 2:  # Allow it at position 0, 1, or 2
                before = commands[:fields_idx]
                after = commands[fields_idx+1:]
                suggested = [commands[0], "fields"] + [c for c in before[1:] if c != "fields"] + after
                suggestions.append(PipelineReorderSuggestion(
                    current_order=commands,
                    suggested_order=suggested,
                    improvement="Move 'fields' earlier to reduce data volume through pipeline",
                    reason="'fields' reduces data transfer and memory usage for all subsequent commands",
                ))

        # Rule 2: where/search should come before expensive commands
        for i, cmd in enumerate(commands):
            if cmd in ("where", "search") and i > 1:
                # Check if there are expensive commands before this filter
                expensive_before = [c for c in commands[:i] if c in ("eval", "rex", "lookup", "spath")]
                if expensive_before:
                    suggestions.append(PipelineReorderSuggestion(
                        current_order=commands,
                        suggested_order=commands,  # Complex to compute exact reorder
                        improvement=f"Move '{cmd}' before {', '.join(expensive_before)} to filter early",
                        reason="Filtering before expensive operations reduces the number of events processed",
                    ))

        # Rule 3: sort before head (not sort after head)
        if "head" in commands and "sort" in commands:
            sort_idx = commands.index("sort")
            head_idx = commands.index("head")
            if head_idx < sort_idx:
                suggestions.append(PipelineReorderSuggestion(
                    current_order=commands,
                    suggested_order=commands[:head_idx] + ["sort"] + [commands[head_idx]],
                    improvement="Move 'sort' before 'head' — head then sort may give wrong results",
                    reason="'head' limits results first, then 'sort' only sorts the limited set",
                ))

        # Rule 4: table should always be last
        if "table" in commands:
            table_idx = commands.index("table")
            if table_idx < len(commands) - 1:
                remaining_after = commands[table_idx+1:]
                if any(c not in ("sort", "head", "rename") for c in remaining_after):
                    suggestions.append(PipelineReorderSuggestion(
                        current_order=commands,
                        suggested_order=[c for c in commands if c != "table"] + ["table"],
                        improvement="Move 'table' to the end of the pipeline",
                        reason="'table' discards fields — placing it before processing commands loses data",
                    ))

        # Rule 5: eval before stats (if eval creates a field used in stats by)
        if "eval" in commands and "stats" in commands:
            eval_idx = commands.index("eval")
            stats_idx = commands.index("stats")
            if eval_idx > stats_idx:
                suggestions.append(PipelineReorderSuggestion(
                    current_order=commands,
                    suggested_order=commands,
                    improvement="Move 'eval' before 'stats' if the eval creates fields used in aggregation",
                    reason="Fields created by eval after stats are not available for the BY clause",
                ))

        return suggestions

    # -------------------------------------------------------------------
    # 12. Resource Risk Matrix
    # -------------------------------------------------------------------
    def assess_resource_risk(self, query: str,
                              memory_estimates: List[MemoryEstimate] = None,
                              regex_risks: List[RegexRisk] = None,
                              distribution_issues: List[DistributionIssue] = None,
                              ) -> ResourceRisk:
        """Assess overall resource consumption risk."""
        mem_risk = RiskLevel.NONE
        cpu_risk = RiskLevel.NONE
        disk_risk = RiskLevel.NONE
        net_risk = RiskLevel.NONE
        bottlenecks = []

        # Memory risk from estimates
        if memory_estimates:
            max_mem_risk = max((m.risk for m in memory_estimates), default=RiskLevel.NONE,
                               key=lambda r: list(RiskLevel).index(r))
            mem_risk = max_mem_risk
            critical_mem = [m for m in memory_estimates if m.risk in (RiskLevel.HIGH, RiskLevel.CRITICAL)]
            for m in critical_mem:
                bottlenecks.append(f"Memory: '{m.command}' — {m.estimated_mb}")

        # CPU risk from regex
        if regex_risks:
            max_regex_risk = max((r.risk for r in regex_risks), default=RiskLevel.NONE,
                                  key=lambda r: list(RiskLevel).index(r))
            cpu_risk = max(cpu_risk, max_regex_risk, key=lambda r: list(RiskLevel).index(r))
            for r in regex_risks:
                if r.risk in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                    bottlenecks.append(f"CPU: regex in '{r.command}' (complexity {r.complexity_score}/100)")

        # CPU from expensive commands
        stages = split_pipeline(query)
        for stage in stages:
            cmd = extract_command(stage)
            if cmd in CPU_WEIGHTS and cmd != "unknown":
                if CPU_WEIGHTS[cmd] >= 5:
                    cpu_risk = max(cpu_risk, RiskLevel.MODERATE,
                                   key=lambda r: list(RiskLevel).index(r))

        # Disk I/O risk
        ql = query.lower()
        if "index=*" in ql:
            disk_risk = RiskLevel.CRITICAL
            bottlenecks.append("Disk I/O: index=* scans all indexes")
        elif "earliest=" not in ql and "latest=" not in ql:
            # Time range is often set via UI time picker, not in query text.
            # Don't flag as high risk — just note it as informational.
            disk_risk = RiskLevel.LOW
        else:
            time_seconds = extract_time_range_seconds(query)
            if time_seconds and time_seconds > 30 * 86400:  # > 30 days
                disk_risk = RiskLevel.HIGH
                bottlenecks.append(f"Disk I/O: large time range ({seconds_to_human(time_seconds)})")

        # Network risk from non-distributable commands
        if distribution_issues:
            breaking = [d for d in distribution_issues if d.breaks_distribution]
            if breaking:
                net_risk = RiskLevel.MODERATE
                if any(d.command in ("transaction", "sort") for d in breaking):
                    net_risk = RiskLevel.HIGH
                bottlenecks.append(
                    f"Network: {', '.join(d.command for d in breaking)} forces centralized processing"
                )

        # Overall risk = worst of all
        all_risks = [mem_risk, cpu_risk, disk_risk, net_risk]
        overall = max(all_risks, key=lambda r: list(RiskLevel).index(r))

        # Memory estimate string
        if memory_estimates:
            worst = max(memory_estimates, key=lambda m: list(RiskLevel).index(m.risk))
            mem_estimate_str = worst.estimated_mb
        else:
            mem_estimate_str = "< 10 MB"

        return ResourceRisk(
            memory=mem_risk, cpu=cpu_risk, disk_io=disk_risk, network=net_risk,
            overall=overall, memory_estimate=mem_estimate_str,
            bottlenecks=bottlenecks,
        )

    # -------------------------------------------------------------------
    # Full Deep Analysis
    # -------------------------------------------------------------------
    def deep_analyze(self, query: str) -> DeepAnalysisResult:
        """Run all deep analysis checks and return comprehensive report."""
        fingerprint = self.fingerprint_query(query)
        cardinality = self.analyze_cardinality(query)
        memory = self.estimate_memory(query)
        regex = self.analyze_regex_complexity(query)
        spans = self.analyze_bucket_span(query)
        lookups = self.analyze_lookups(query)
        subsearch = self.analyze_subsearch_depth(query)
        metrics = self.detect_metric_index(query)
        distribution = self.analyze_distribution(query)
        resource = self.assess_resource_risk(query, memory, regex, distribution)
        profile = self.profile_search(query)
        reorder = self.suggest_pipeline_reorder(query)

        # Count issues
        total = (len(cardinality) + len(memory) + len(regex) + len(spans)
                 + len(lookups) + len(metrics) + len(distribution) + len(reorder))
        if subsearch.risk != RiskLevel.NONE:
            total += 1
        if resource.overall in (RiskLevel.HIGH, RiskLevel.CRITICAL):
            total += 1

        critical = sum(1 for w in cardinality if w.risk == RiskLevel.CRITICAL)
        critical += sum(1 for m in memory if m.risk == RiskLevel.CRITICAL)
        critical += sum(1 for r in regex if r.risk == RiskLevel.CRITICAL)
        critical += sum(1 for s in spans if s.risk == RiskLevel.HIGH)
        if subsearch.risk == RiskLevel.CRITICAL:
            critical += 1
        if resource.overall == RiskLevel.CRITICAL:
            critical += 1

        # Generate summary
        summary_parts = []
        if critical > 0:
            summary_parts.append(f"{critical} critical issue(s)")
        if resource.overall != RiskLevel.NONE:
            summary_parts.append(f"resource risk: {resource.overall.value}")
        if profile.bottleneck_stage is not None:
            summary_parts.append(f"bottleneck at stage {profile.bottleneck_stage + 1}: {profile.bottleneck_reason}")
        if metrics:
            summary_parts.append("metric index opportunity detected")
        if not summary_parts:
            summary_parts.append("query looks well-optimized")

        summary = "Deep Analysis: " + "; ".join(summary_parts)

        return DeepAnalysisResult(
            query=query,
            fingerprint=fingerprint,
            cardinality_warnings=cardinality,
            memory_estimates=memory,
            regex_risks=regex,
            span_suggestions=spans,
            lookup_warnings=lookups,
            subsearch_report=subsearch,
            metric_suggestions=metrics,
            distribution_issues=distribution,
            resource_risk=resource,
            profile=profile,
            reorder_suggestions=reorder,
            total_issues=total,
            critical_issues=critical,
            summary=summary,
        )



# ---------------------------------------------------------------------------
# Convenience singleton & function
# ---------------------------------------------------------------------------

_deep_analyzer: Optional[SPLDeepAnalyzer] = None


def get_deep_analyzer() -> SPLDeepAnalyzer:
    """Get or create the singleton deep analyzer."""
    global _deep_analyzer
    if _deep_analyzer is None:
        _deep_analyzer = SPLDeepAnalyzer()
    return _deep_analyzer


def deep_analyze(query: str) -> DeepAnalysisResult:
    """Run full deep analysis on an SPL query."""
    return get_deep_analyzer().deep_analyze(query)
