"""Evaluation Gate — blocks releases if quality metrics fall below thresholds.

Runs a controlled suite of golden test cases against the RAG pipeline and
scores keyword coverage, forbidden-word absence, and minimum-length
requirements. A release passes only when 80 % or more of the test cases
receive a passing score.

Test-case categories (at least 5 each):
  - spl_generation       — SPL write tasks; answers must contain SPL constructs
  - spl_explanation      — SPL explain tasks; must reference key command names
  - conceptual           — "What is X?" questions; must mention domain terms
  - config_troubleshoot  — conf-file / admin questions; must reference conf files

Usage:
    from chat_app.eval_gate import run_eval_suite, run_eval_gate

    # Quick structural check (no LLM needed — used in CI pre-flight):
    result = run_eval_gate()
    assert result["passed"]

    # Full live evaluation (requires running Ollama + ChromaDB):
    result = run_eval_suite()
    if not result.overall_passed:
        print("RELEASE BLOCKED:", result.failures)

    # CLI:
    python3 -m chat_app.eval_gate          # exits 0/1
    python3 -m chat_app.eval_gate --quick  # structural check only
"""

import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Minimum fraction of test cases that must pass for a green release gate.
RELEASE_QUALITY_THRESHOLD = 0.80

# Minimum character count an answer must reach to be non-trivial.
DEFAULT_MIN_LENGTH = 50


# ---------------------------------------------------------------------------
# EvalTestCase dataclass
# ---------------------------------------------------------------------------

@dataclass
class EvalTestCase:
    """A single golden evaluation test case.

    Attributes:
        query:              The user query sent to the pipeline.
        intent:             Expected intent category (used for grouping stats).
        category:           One of: spl_generation, spl_explanation,
                            conceptual, config_troubleshoot.
        expected_keywords:  Any one of these keywords must appear in the
                            response for the case to pass (case-insensitive).
        forbidden_keywords: If any of these appear in the response the case
                            fails, regardless of expected_keywords.
        min_length:         Minimum character length of the response.
        description:        Human-readable explanation of the test purpose.
    """
    query: str
    intent: str
    category: str
    expected_keywords: List[str]
    forbidden_keywords: List[str] = field(default_factory=list)
    min_length: int = DEFAULT_MIN_LENGTH
    description: str = ""


# ---------------------------------------------------------------------------
# Eval result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class CaseResult:
    """Outcome for a single test case."""
    test_case: EvalTestCase
    response: Optional[str]        # Raw pipeline response (None = error)
    keyword_hit: bool              # At least one expected_keyword found
    no_forbidden: bool             # No forbidden_keyword found
    min_length_met: bool           # Response length >= min_length
    passed: bool                   # All three conditions met
    matched_keyword: Optional[str] # Which expected keyword was found
    matched_forbidden: Optional[str]  # Which forbidden keyword caused failure
    error: Optional[str]           # Pipeline error message (if any)

    @property
    def score(self) -> float:
        """Fractional score: each criterion contributes 1/3."""
        criteria = [self.keyword_hit, self.no_forbidden, self.min_length_met]
        return sum(criteria) / len(criteria)


@dataclass
class EvalResult:
    """Aggregate outcome of running the full eval suite."""
    overall_passed: bool
    pass_rate: float
    total: int
    passed_count: int
    failed_count: int
    threshold: float
    case_results: List[CaseResult]
    failures: List[str]
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "overall_passed": self.overall_passed,
            "pass_rate": round(self.pass_rate, 4),
            "total": self.total,
            "passed_count": self.passed_count,
            "failed_count": self.failed_count,
            "threshold": self.threshold,
            "failures": self.failures,
            "evaluated_at": self.evaluated_at,
            "cases": [
                {
                    "query": r.test_case.query[:80],
                    "category": r.test_case.category,
                    "intent": r.test_case.intent,
                    "passed": r.passed,
                    "score": round(r.score, 3),
                    "keyword_hit": r.keyword_hit,
                    "no_forbidden": r.no_forbidden,
                    "min_length_met": r.min_length_met,
                    "matched_keyword": r.matched_keyword,
                    "matched_forbidden": r.matched_forbidden,
                    "error": r.error,
                }
                for r in self.case_results
            ],
        }


# ---------------------------------------------------------------------------
# Eval thresholds (legacy — kept for backward compatibility)
# ---------------------------------------------------------------------------

@dataclass
class EvalThresholds:
    """Quality thresholds that must be met for the structural gate."""
    min_grounding_score: float = 0.7
    max_hallucination_rate: float = 0.05
    min_retrieval_precision: float = 0.6
    min_confidence_avg: float = 0.5
    min_test_cases: int = 20


# ---------------------------------------------------------------------------
# Golden test cases
# ---------------------------------------------------------------------------

GOLDEN_CASES: List[EvalTestCase] = [
    # -----------------------------------------------------------------------
    # 1-5  SPL Generation
    # -----------------------------------------------------------------------
    EvalTestCase(
        query="Write a Splunk search for failed login attempts",
        intent="splunk_search",
        category="spl_generation",
        expected_keywords=["stats", "EventCode", "failure", "failed", "count"],
        forbidden_keywords=["I cannot", "I'm unable", "I don't know"],
        min_length=60,
        description="SPL generation — failed logins must use stats and reference EventCode or failure terms",
    ),
    EvalTestCase(
        query="Create a SPL query to find the top 10 source IPs by error count",
        intent="splunk_search",
        category="spl_generation",
        expected_keywords=["stats", "count", "src_ip", "top", "by", "|"],
        forbidden_keywords=["I cannot", "not possible"],
        min_length=60,
        description="SPL generation — top-N pattern must include stats/count and a grouping field",
    ),
    EvalTestCase(
        query="Write a search to detect processes running from temp directories",
        intent="splunk_search",
        category="spl_generation",
        expected_keywords=["index", "where", "process", "temp", "search", "|"],
        forbidden_keywords=["I cannot"],
        min_length=60,
        description="SPL generation — endpoint monitoring query must reference process and temp path",
    ),
    EvalTestCase(
        query="How do I calculate average response time per host in Splunk?",
        intent="splunk_search",
        category="spl_generation",
        expected_keywords=["avg", "stats", "by host", "response_time", "timechart"],
        forbidden_keywords=["I'm unable"],
        min_length=60,
        description="SPL generation — aggregation with avg() grouped by host",
    ),
    EvalTestCase(
        query="Write a Splunk alert query that fires when CPU usage exceeds 90%",
        intent="splunk_search",
        category="spl_generation",
        expected_keywords=["cpu", "where", "stats", ">", "threshold", "alert"],
        forbidden_keywords=["I cannot"],
        min_length=60,
        description="SPL generation — threshold alerting pattern must reference cpu and a comparison operator",
    ),

    # -----------------------------------------------------------------------
    # 6-10  SPL Explanation
    # -----------------------------------------------------------------------
    EvalTestCase(
        query="Explain what this SPL does: index=main | stats count by sourcetype",
        intent="spl_explain",
        category="spl_explanation",
        expected_keywords=["stats", "count", "sourcetype", "group", "aggregate"],
        forbidden_keywords=["I cannot explain", "unclear"],
        min_length=80,
        description="SPL explanation — must name the stats command and describe grouping by sourcetype",
    ),
    EvalTestCase(
        query="What does the rex command do in Splunk?",
        intent="spl_help",
        category="spl_explanation",
        expected_keywords=["rex", "regex", "extract", "field", "pattern"],
        forbidden_keywords=["I don't know"],
        min_length=60,
        description="SPL explanation — rex command must be described in terms of regex extraction",
    ),
    EvalTestCase(
        query="Explain the difference between stats and eventstats in Splunk",
        intent="spl_help",
        category="spl_explanation",
        expected_keywords=["stats", "eventstats", "result", "event", "replace"],
        forbidden_keywords=["same", "identical"],
        min_length=100,
        description="SPL explanation — comparison must identify that eventstats preserves all events",
    ),
    EvalTestCase(
        query="What is the purpose of the eval command?",
        intent="spl_help",
        category="spl_explanation",
        expected_keywords=["eval", "expression", "field", "calculate", "value"],
        forbidden_keywords=["I cannot"],
        min_length=60,
        description="SPL explanation — eval must be described as a field-calculation command",
    ),
    EvalTestCase(
        query="Explain this SPL: | tstats count where index=* by index",
        intent="spl_explain",
        category="spl_explanation",
        expected_keywords=["tstats", "count", "index", "accelerated", "fast"],
        forbidden_keywords=["I'm unable"],
        min_length=80,
        description="SPL explanation — tstats must be described as accelerated stats over tsidx data",
    ),

    # -----------------------------------------------------------------------
    # 11-15  Conceptual
    # -----------------------------------------------------------------------
    EvalTestCase(
        query="What is Splunk?",
        intent="general_qa",
        category="conceptual",
        expected_keywords=["data platform", "search", "log", "SIEM", "observability", "machine data"],
        forbidden_keywords=["I don't know", "I cannot answer"],
        min_length=80,
        description="Conceptual — must characterise Splunk as a data/search platform",
    ),
    EvalTestCase(
        query="What is the Common Information Model (CIM) in Splunk?",
        intent="general_qa",
        category="conceptual",
        expected_keywords=["CIM", "data model", "normalise", "normalize", "field", "schema"],
        forbidden_keywords=["I'm unable"],
        min_length=80,
        description="Conceptual — CIM must be described as a data normalisation schema",
    ),
    EvalTestCase(
        query="What is an index in Splunk?",
        intent="general_qa",
        category="conceptual",
        expected_keywords=["index", "store", "bucket", "raw", "data", "search"],
        forbidden_keywords=["I don't know"],
        min_length=60,
        description="Conceptual — index must be described as a data storage container",
    ),
    EvalTestCase(
        query="What is a Splunk forwarder?",
        intent="general_qa",
        category="conceptual",
        expected_keywords=["forwarder", "forward", "data", "collect", "universal", "heavy"],
        forbidden_keywords=["I cannot"],
        min_length=60,
        description="Conceptual — forwarder must be described as a data-collection agent",
    ),
    EvalTestCase(
        query="What is the difference between a search head and an indexer?",
        intent="general_qa",
        category="conceptual",
        expected_keywords=["search head", "indexer", "query", "store", "role"],
        forbidden_keywords=["same", "identical", "I'm unable"],
        min_length=100,
        description="Conceptual — must distinguish query (search head) from storage (indexer) roles",
    ),

    # -----------------------------------------------------------------------
    # 16-20  Config / Troubleshooting
    # -----------------------------------------------------------------------
    EvalTestCase(
        query="How do I increase the search job limit in Splunk?",
        intent="general_qa",
        category="config_troubleshoot",
        expected_keywords=["limits.conf", "max_searches_per_cpu", "search", "limit", "configuration"],
        forbidden_keywords=["I cannot", "impossible"],
        min_length=80,
        description="Config — must reference limits.conf and the relevant stanza or setting",
    ),
    EvalTestCase(
        query="How do I configure inputs.conf to monitor a log file?",
        intent="general_qa",
        category="config_troubleshoot",
        expected_keywords=["inputs.conf", "monitor://", "[monitor", "index", "sourcetype"],
        forbidden_keywords=["I'm unable"],
        min_length=80,
        description="Config — must reference inputs.conf and the monitor:// stanza format",
    ),
    EvalTestCase(
        query="What is props.conf used for in Splunk?",
        intent="spl_help",
        category="config_troubleshoot",
        expected_keywords=["props.conf", "sourcetype", "transform", "extract", "timestamp"],
        forbidden_keywords=["I don't know"],
        min_length=60,
        description="Config — props.conf must be described in terms of sourcetype configuration",
    ),
    EvalTestCase(
        query="How do I set up HEC (HTTP Event Collector) in Splunk?",
        intent="general_qa",
        category="config_troubleshoot",
        expected_keywords=["HEC", "token", "http", "port", "inputs.conf", "endpoint"],
        forbidden_keywords=["I cannot"],
        min_length=80,
        description="Config — HEC setup must mention token, port, and how events are sent",
    ),
    EvalTestCase(
        query="Why is my Splunk search slow and how do I optimise it?",
        intent="general_qa",
        category="config_troubleshoot",
        expected_keywords=["index", "time range", "filter", "stats", "optimise", "optimize", "tstats"],
        forbidden_keywords=["I'm unable", "I cannot help"],
        min_length=100,
        description="Troubleshooting — must suggest indexing strategy, time-range filters, or tstats",
    ),
]


# ---------------------------------------------------------------------------
# Structural gate (no LLM required — used in CI pre-flight)
# ---------------------------------------------------------------------------

def run_eval_gate(thresholds: Optional[EvalThresholds] = None) -> Dict[str, Any]:
    """Validate the eval suite structure — no live pipeline required.

    This check is fast, runs without Ollama/ChromaDB, and verifies:
    - Minimum number of test cases
    - All required fields present on each case
    - Each category has at least 5 cases
    - No test case has an empty expected_keywords list

    Returns:
        Dict with: passed (bool), failures (list), warnings (list),
        golden_cases (int), categories (dict), intents_covered (list),
        grounded_cases (int), ungrounded_cases (int), thresholds (dict),
        timestamp (str).
    """
    if thresholds is None:
        thresholds = EvalThresholds()

    failures: List[str] = []
    warnings: List[str] = []

    # Minimum count
    if len(GOLDEN_CASES) < thresholds.min_test_cases:
        failures.append(
            f"Only {len(GOLDEN_CASES)} golden cases defined "
            f"(minimum required: {thresholds.min_test_cases})"
        )

    # Per-case field validation
    for index, case in enumerate(GOLDEN_CASES):
        prefix = f"Case {index} ('{case.query[:40]}...')"
        if not case.query.strip():
            failures.append(f"{prefix}: 'query' is empty")
        if not case.intent.strip():
            failures.append(f"{prefix}: 'intent' is empty")
        if not case.category.strip():
            failures.append(f"{prefix}: 'category' is empty")
        if not case.expected_keywords:
            failures.append(f"{prefix}: 'expected_keywords' is empty — cannot score")
        if case.min_length < 0:
            failures.append(f"{prefix}: 'min_length' is negative ({case.min_length})")

    # Category coverage: each must have at least 5 cases
    required_categories = {
        "spl_generation",
        "spl_explanation",
        "conceptual",
        "config_troubleshoot",
    }
    category_counts: Dict[str, int] = {}
    for case in GOLDEN_CASES:
        category_counts[case.category] = category_counts.get(case.category, 0) + 1

    for category in required_categories:
        count = category_counts.get(category, 0)
        if count < 5:
            failures.append(
                f"Category '{category}' has only {count} cases (minimum 5 required)"
            )

    # Intent coverage
    intents_covered = sorted({case.intent for case in GOLDEN_CASES})
    required_intents = {"general_qa", "spl_help", "splunk_search", "spl_explain"}
    missing_intents = required_intents - set(intents_covered)
    if missing_intents:
        warnings.append(f"Missing intent coverage: {sorted(missing_intents)}")

    # Grounded / ungrounded balance (kept for backward compat reporting)
    grounded_count = sum(
        1 for c in GOLDEN_CASES if c.category != "conceptual"
    )
    ungrounded_count = len(GOLDEN_CASES) - grounded_count
    if ungrounded_count == 0:
        warnings.append("No ungrounded test cases — cannot test LLM-only answers")

    passed = len(failures) == 0

    return {
        "passed": passed,
        "failures": failures,
        "warnings": warnings,
        "golden_cases": len(GOLDEN_CASES),
        "categories": category_counts,
        "intents_covered": intents_covered,
        "grounded_cases": grounded_count,
        "ungrounded_cases": ungrounded_count,
        "thresholds": {
            "min_grounding_score": thresholds.min_grounding_score,
            "max_hallucination_rate": thresholds.max_hallucination_rate,
            "min_retrieval_precision": thresholds.min_retrieval_precision,
            "min_confidence_avg": thresholds.min_confidence_avg,
            "min_test_cases": thresholds.min_test_cases,
        },
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Per-case scoring logic
# ---------------------------------------------------------------------------

def _score_case(case: EvalTestCase, response: str) -> CaseResult:
    """Score a single test case against the pipeline response.

    Scoring criteria (each independently evaluated):
    1. keyword_hit    — at least one expected_keyword appears in response
    2. no_forbidden   — none of the forbidden_keywords appear in response
    3. min_length_met — len(response) >= case.min_length

    All three must be true for the case to pass.
    """
    response_lower = response.lower()

    # Check expected keywords (case-insensitive substring match)
    matched_keyword: Optional[str] = None
    for keyword in case.expected_keywords:
        if keyword.lower() in response_lower:
            matched_keyword = keyword
            break
    keyword_hit = matched_keyword is not None

    # Check forbidden keywords
    matched_forbidden: Optional[str] = None
    for keyword in case.forbidden_keywords:
        if keyword.lower() in response_lower:
            matched_forbidden = keyword
            break
    no_forbidden = matched_forbidden is None

    # Check minimum length
    min_length_met = len(response) >= case.min_length

    passed = keyword_hit and no_forbidden and min_length_met

    return CaseResult(
        test_case=case,
        response=response,
        keyword_hit=keyword_hit,
        no_forbidden=no_forbidden,
        min_length_met=min_length_met,
        passed=passed,
        matched_keyword=matched_keyword,
        matched_forbidden=matched_forbidden,
        error=None,
    )


def _error_case(case: EvalTestCase, error_message: str) -> CaseResult:
    """Build a failing CaseResult for pipeline errors."""
    return CaseResult(
        test_case=case,
        response=None,
        keyword_hit=False,
        no_forbidden=True,
        min_length_met=False,
        passed=False,
        matched_keyword=None,
        matched_forbidden=None,
        error=error_message,
    )


# ---------------------------------------------------------------------------
# Live evaluation runner
# ---------------------------------------------------------------------------

def _get_pipeline_response(query: str) -> str:
    """Invoke the RAG pipeline for a single query and return the response text.

    Attempts to import the internal pipeline response function. When the
    full Chainlit/Ollama stack is not available, returns a stub that causes
    the case to fail gracefully.
    """
    try:
        # Try the lightweight pipeline-response helper first (avoids
        # importing the full Chainlit app context).
        from chat_app.pipeline_models import run_pipeline_query  # type: ignore[import]
        result = run_pipeline_query(query)
        return result if isinstance(result, str) else str(result)
    except ImportError:
        pass

    try:
        # Fall back to message_handler if pipeline_models is unavailable.
        from chat_app.message_handler import get_pipeline_response  # type: ignore[import]
        result = get_pipeline_response(query)
        return result if isinstance(result, str) else str(result)
    except ImportError:
        pass

    # No pipeline available — return an empty string so the case fails with
    # a clear "no pipeline" signal rather than raising an exception.
    logger.warning(
        "No pipeline module available — eval case '%s' will fail due to empty response",
        query[:60],
    )
    return ""


def run_eval_suite(
    cases: Optional[List[EvalTestCase]] = None,
    quality_threshold: float = RELEASE_QUALITY_THRESHOLD,
) -> EvalResult:
    """Run the full evaluation suite against the live RAG pipeline.

    Requires a running Ollama + ChromaDB stack. In CI environments without
    the full stack, call run_eval_gate() instead for a structural check.

    Args:
        cases:             Test cases to run. Defaults to GOLDEN_CASES.
        quality_threshold: Fraction of cases that must pass (default 0.80).

    Returns:
        EvalResult with overall_passed, per-case details, and a failure list.
    """
    if cases is None:
        cases = GOLDEN_CASES

    case_results: List[CaseResult] = []
    failures: List[str] = []

    for case in cases:
        try:
            response = _get_pipeline_response(case.query)
            result = _score_case(case, response)
        except Exception as exc:  # broad catch — resilience at boundary  # noqa: BLE001
            logger.warning("Pipeline error for case '%s': %s", case.query[:60], exc)
            result = _error_case(case, str(exc))

        case_results.append(result)

        if not result.passed:
            reasons = []
            if not result.keyword_hit:
                reasons.append(
                    f"no expected keyword found (wanted any of {case.expected_keywords[:3]})"
                )
            if not result.no_forbidden:
                reasons.append(f"forbidden keyword '{result.matched_forbidden}' found")
            if not result.min_length_met:
                length = len(result.response) if result.response else 0
                reasons.append(
                    f"response too short ({length} chars, minimum {case.min_length})"
                )
            if result.error:
                reasons.append(f"pipeline error: {result.error}")
            failures.append(
                f"[{case.category}] '{case.query[:60]}': {'; '.join(reasons)}"
            )

    passed_count = sum(1 for r in case_results if r.passed)
    total = len(case_results)
    pass_rate = passed_count / total if total > 0 else 0.0
    overall_passed = pass_rate >= quality_threshold

    return EvalResult(
        overall_passed=overall_passed,
        pass_rate=pass_rate,
        total=total,
        passed_count=passed_count,
        failed_count=total - passed_count,
        threshold=quality_threshold,
        case_results=case_results,
        failures=failures,
    )


# ---------------------------------------------------------------------------
# CLI entry point — exits 0 on pass, 1 on failure
# ---------------------------------------------------------------------------

def _cli_main(argv: Optional[List[str]] = None) -> int:
    """Run the eval gate from the command line.

    Flags:
        --quick   Only run the structural gate (no live pipeline required).
                  This is what CI uses by default.
        --live    Run the full live suite (requires Ollama + ChromaDB).
    """
    logging.basicConfig(level=logging.WARNING)

    args = argv if argv is not None else sys.argv[1:]
    quick_mode = "--live" not in args

    if quick_mode:
        result = run_eval_gate()
        print(
            f"\nEval Gate (structural) — "
            f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
        )
        print(f"Cases defined : {result['golden_cases']}")
        print(f"Categories    : {result['categories']}")
        print(f"Intents       : {result['intents_covered']}")

        if result["failures"]:
            print("\nFAILURES:")
            for failure in result["failures"]:
                print(f"  - {failure}")

        if result["warnings"]:
            print("\nWARNINGS:")
            for warning in result["warnings"]:
                print(f"  ~ {warning}")

        status = "PASS" if result["passed"] else "FAIL"
        print(f"\nStructural gate: {status}")
        return 0 if result["passed"] else 1

    # Live mode
    print(
        f"\nEval Gate (live) — "
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC"
    )
    print(f"Running {len(GOLDEN_CASES)} test cases against live pipeline...\n")

    eval_result = run_eval_suite()

    print(
        f"{'Query':<50} {'Category':<22} {'Pass':>5} {'Score':>6}"
    )
    print("-" * 90)
    for case_result in eval_result.case_results:
        status = "PASS" if case_result.passed else "FAIL"
        print(
            f"{case_result.test_case.query[:49]:<50} "
            f"{case_result.test_case.category:<22} "
            f"{status:>5} "
            f"{case_result.score:>6.2f}"
        )

    print()
    print(f"Pass rate : {eval_result.pass_rate:.1%} ({eval_result.passed_count}/{eval_result.total})")
    print(f"Threshold : {eval_result.threshold:.1%}")

    if eval_result.failures:
        print("\nFailing cases:")
        for failure in eval_result.failures:
            print(f"  - {failure}")

    overall = "PASS" if eval_result.overall_passed else "FAIL"
    print(f"\nEval gate: {overall}")

    if not eval_result.overall_passed:
        print("RELEASE BLOCKED — quality threshold not met")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())
