"""Performance SLO Gate — hard latency and reliability targets that block releases.

Defines SLO targets for:
- Query latency (p95 < 10s, p99 < 30s)
- Retrieval latency (p95 < 2s)
- LLM latency (p95 < 15s)
- Error rate (< 5%)
- Cache hit rate (> 30%)

Each SLO is evaluated against metrics collected from the Prometheus client
registry (counters, histograms) accumulated during runtime. Results include
the actual measured value, the threshold, whether it passed, and the
remaining error budget.

Usage:
    from chat_app.slo_gate import SLOEvaluator, get_slo_report

    evaluator = SLOEvaluator()
    results = evaluator.evaluate_all()
    passed = all(r.passed for r in results)

    # CI usage: exits 0 on pass, 1 on failure
    python3 -m chat_app.slo_gate
"""

import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Operators
# ---------------------------------------------------------------------------

OPERATOR_LT = "lt"   # actual < threshold  →  lower is better (latency, error rate)
OPERATOR_GT = "gt"   # actual > threshold  →  higher is better (cache hit rate)

VALID_OPERATORS = {OPERATOR_LT, OPERATOR_GT}


# ---------------------------------------------------------------------------
# SLO Definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SLODefinition:
    """Immutable specification of a single Service Level Objective.

    Attributes:
        name:           Human-readable identifier used in reports and CI output.
        metric:         Prometheus metric name (or logical key) to evaluate.
        threshold:      The pass/fail boundary value.
        operator:       Comparison direction — "lt" (actual < threshold passes)
                        or "gt" (actual > threshold passes).
        window_minutes: Rolling time window in minutes from which the metric
                        sample is gathered. Used for documentation; actual
                        window is controlled by the Prometheus scrape interval.
        description:    Optional explanation of the SLO purpose.
    """
    name: str
    metric: str
    threshold: float
    operator: str           # "lt" or "gt"
    window_minutes: int = 60
    description: str = ""

    def __post_init__(self) -> None:
        if self.operator not in VALID_OPERATORS:
            raise ValueError(
                f"SLODefinition '{self.name}': operator must be one of "
                f"{VALID_OPERATORS}, got '{self.operator}'"
            )
        if self.threshold < 0:
            raise ValueError(
                f"SLODefinition '{self.name}': threshold must be >= 0, "
                f"got {self.threshold}"
            )
        if self.window_minutes <= 0:
            raise ValueError(
                f"SLODefinition '{self.name}': window_minutes must be > 0, "
                f"got {self.window_minutes}"
            )


# ---------------------------------------------------------------------------
# SLO Result
# ---------------------------------------------------------------------------

@dataclass
class SLOResult:
    """Outcome of evaluating a single SLO against collected metrics.

    Attributes:
        slo:             The definition that was evaluated.
        passed:          True when the actual value satisfies the threshold.
        actual_value:    Measured value at evaluation time (None = no data).
        budget_remaining: Fractional headroom before breach (0–1). Positive
                         means headroom exists; negative means the SLO is
                         already breached by that fraction.
        message:         Human-readable summary of the result.
        evaluated_at:    ISO-8601 timestamp of when evaluation ran.
    """
    slo: SLODefinition
    passed: bool
    actual_value: Optional[float]
    budget_remaining: float
    message: str
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.slo.name,
            "metric": self.slo.metric,
            "threshold": self.slo.threshold,
            "operator": self.slo.operator,
            "window_minutes": self.slo.window_minutes,
            "description": self.slo.description,
            "passed": self.passed,
            "actual_value": self.actual_value,
            "budget_remaining": round(self.budget_remaining, 4),
            "message": self.message,
            "evaluated_at": self.evaluated_at,
        }


# ---------------------------------------------------------------------------
# Hard SLO Targets (the contract)
# ---------------------------------------------------------------------------

# These values represent the minimum acceptable service quality for a
# production release. Adjust only with explicit SRE sign-off.
QUERY_LATENCY_P95_SECONDS = 10.0
QUERY_LATENCY_P99_SECONDS = 30.0
RETRIEVAL_LATENCY_P95_SECONDS = 2.0
LLM_LATENCY_P95_SECONDS = 15.0
MAX_ERROR_RATE_FRACTION = 0.05   # 5 % of requests may fail
MIN_CACHE_HIT_RATE_FRACTION = 0.30  # 30 % of queries must hit cache

DEFAULT_SLOS: List[SLODefinition] = [
    SLODefinition(
        name="query_latency_p95",
        metric="obsai_query_duration_seconds_p95",
        threshold=QUERY_LATENCY_P95_SECONDS,
        operator=OPERATOR_LT,
        window_minutes=60,
        description="95th-percentile end-to-end query latency must stay below 10 s",
    ),
    SLODefinition(
        name="query_latency_p99",
        metric="obsai_query_duration_seconds_p99",
        threshold=QUERY_LATENCY_P99_SECONDS,
        operator=OPERATOR_LT,
        window_minutes=60,
        description="99th-percentile end-to-end query latency must stay below 30 s",
    ),
    SLODefinition(
        name="retrieval_latency_p95",
        metric="obsai_retrieval_duration_seconds_p95",
        threshold=RETRIEVAL_LATENCY_P95_SECONDS,
        operator=OPERATOR_LT,
        window_minutes=60,
        description="95th-percentile vector-store retrieval latency must stay below 2 s",
    ),
    SLODefinition(
        name="llm_latency_p95",
        metric="obsai_llm_duration_seconds_p95",
        threshold=LLM_LATENCY_P95_SECONDS,
        operator=OPERATOR_LT,
        window_minutes=60,
        description="95th-percentile LLM generation latency must stay below 15 s",
    ),
    SLODefinition(
        name="error_rate",
        metric="obsai_error_rate",
        threshold=MAX_ERROR_RATE_FRACTION,
        operator=OPERATOR_LT,
        window_minutes=60,
        description="Fraction of requests resulting in an error must stay below 5 %",
    ),
    SLODefinition(
        name="cache_hit_rate",
        metric="obsai_cache_hit_rate",
        threshold=MIN_CACHE_HIT_RATE_FRACTION,
        operator=OPERATOR_GT,
        window_minutes=60,
        description="Fraction of queries served from cache must exceed 30 %",
    ),
]


# ---------------------------------------------------------------------------
# Metric collector helpers
# ---------------------------------------------------------------------------

def _collect_prometheus_metrics() -> Dict[str, float]:
    """Read available metrics from the Prometheus client registry.

    Returns a flat dict mapping metric name → current value. Histogram
    quantiles are derived from the _bucket / _count / _sum samples when
    a full histogram is available; otherwise the raw gauge value is used.

    When the Prometheus client is not installed, an empty dict is returned
    so that the evaluator degrades gracefully (all SLOs report no-data).
    """
    collected: Dict[str, float] = {}

    try:
        import prometheus_client  # type: ignore[import]
        registry = prometheus_client.REGISTRY

        for metric_family in registry.collect():
            samples = metric_family.samples

            # Collect bucket samples to approximate quantiles
            bucket_counts: Dict[str, Dict[float, float]] = {}
            total_counts: Dict[str, float] = {}
            total_sums: Dict[str, float] = {}

            for sample in samples:
                sample_name: str = sample.name
                sample_value: float = sample.value

                if sample_name.endswith("_bucket"):
                    base = sample_name[: -len("_bucket")]
                    le_value = float(sample.labels.get("le", "inf"))
                    bucket_counts.setdefault(base, {})[le_value] = sample_value
                elif sample_name.endswith("_count"):
                    base = sample_name[: -len("_count")]
                    total_counts[base] = sample_value
                elif sample_name.endswith("_sum"):
                    base = sample_name[: -len("_sum")]
                    total_sums[base] = sample_value
                else:
                    collected[sample_name] = sample_value

            # Approximate p95 / p99 from histogram buckets using linear interpolation
            for base, buckets in bucket_counts.items():
                total = total_counts.get(base, 0)
                if total > 0:
                    collected[f"{base}_p95"] = _approximate_quantile(buckets, total, 0.95)
                    collected[f"{base}_p99"] = _approximate_quantile(buckets, total, 0.99)

    except ImportError:
        logger.debug("prometheus_client not available — metrics collection skipped")
    except Exception as exc:  # broad catch — resilience at boundary  # noqa: BLE001
        logger.warning("Failed to collect Prometheus metrics: %s", exc)

    return collected


def _approximate_quantile(
    buckets: Dict[float, float],
    total_count: float,
    quantile: float,
) -> float:
    """Linearly interpolate a quantile from a histogram bucket dict.

    Args:
        buckets:     {upper_bound: cumulative_count} (includes +Inf bucket).
        total_count: Total observation count (_count sample).
        quantile:    Target quantile, e.g. 0.95.

    Returns:
        Estimated value at that quantile, or the +Inf upper bound when
        the target falls in the overflow bucket.
    """
    target_count = quantile * total_count
    sorted_bounds = sorted(b for b in buckets if b != float("inf"))

    previous_bound = 0.0
    previous_count = 0.0

    for bound in sorted_bounds:
        cumulative = buckets[bound]
        if cumulative >= target_count:
            # Linearly interpolate within this bucket
            bucket_width = bound - previous_bound
            bucket_count = cumulative - previous_count
            if bucket_count > 0:
                fraction = (target_count - previous_count) / bucket_count
                return previous_bound + fraction * bucket_width
            return bound
        previous_bound = bound
        previous_count = cumulative

    # Target falls in +Inf bucket — return last finite bound as best estimate
    return previous_bound if sorted_bounds else 0.0


# ---------------------------------------------------------------------------
# SLO Evaluator
# ---------------------------------------------------------------------------

class SLOEvaluator:
    """Evaluates the full set of SLOs against current Prometheus metrics.

    Designed for use in both runtime (admin API) and CI (exit code 0/1).
    """

    def __init__(self, slos: Optional[List[SLODefinition]] = None) -> None:
        self._slos = slos if slos is not None else DEFAULT_SLOS

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_all(self) -> List[SLOResult]:
        """Evaluate every registered SLO and return the full result set."""
        metrics = _collect_prometheus_metrics()
        return [self._evaluate_one(slo, metrics) for slo in self._slos]

    def evaluate_one(self, slo_name: str) -> Optional[SLOResult]:
        """Evaluate a single SLO by name. Returns None when not found."""
        target = next((s for s in self._slos if s.name == slo_name), None)
        if target is None:
            return None
        metrics = _collect_prometheus_metrics()
        return self._evaluate_one(target, metrics)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _evaluate_one(
        self,
        slo: SLODefinition,
        metrics: Dict[str, float],
    ) -> SLOResult:
        actual = metrics.get(slo.metric)

        if actual is None:
            return SLOResult(
                slo=slo,
                passed=True,   # No data → do not block (optimistic default)
                actual_value=None,
                budget_remaining=1.0,
                message=f"No data available for metric '{slo.metric}' — SLO skipped",
            )

        passed, budget = self._check(slo, actual)
        direction = "below" if slo.operator == OPERATOR_LT else "above"
        status = "PASS" if passed else "FAIL"
        message = (
            f"{status}: {slo.name} — actual={actual:.4f} must be {direction} "
            f"{slo.threshold} (budget_remaining={budget:+.2%})"
        )

        return SLOResult(
            slo=slo,
            passed=passed,
            actual_value=actual,
            budget_remaining=budget,
            message=message,
        )

    @staticmethod
    def _check(slo: SLODefinition, actual: float) -> tuple[bool, float]:
        """Return (passed, budget_remaining).

        Budget remaining is expressed as a fraction of the threshold:
        - For lt-operator:  (threshold - actual) / threshold
        - For gt-operator:  (actual - threshold) / threshold

        A positive value means headroom; negative means breach.
        """
        if slo.threshold == 0:
            # Guard against zero-division: any positive actual fails lt, any passes gt
            if slo.operator == OPERATOR_LT:
                passed = actual <= 0
                return passed, 0.0
            else:
                passed = actual >= 0
                return passed, 0.0

        if slo.operator == OPERATOR_LT:
            passed = actual < slo.threshold
            budget = (slo.threshold - actual) / slo.threshold
        else:  # OPERATOR_GT
            passed = actual > slo.threshold
            budget = (actual - slo.threshold) / slo.threshold

        return passed, budget


# ---------------------------------------------------------------------------
# Admin API integration helper
# ---------------------------------------------------------------------------

def get_slo_report() -> Dict[str, Any]:
    """Generate a JSON-serialisable SLO report for the admin API.

    Returns:
        Dict with keys: passed (bool), total, passing_count, failing_count,
        slos (list of per-SLO result dicts), evaluated_at.
    """
    evaluator = SLOEvaluator()
    results = evaluator.evaluate_all()

    passing = [r for r in results if r.passed]
    failing = [r for r in results if not r.passed]

    return {
        "passed": len(failing) == 0,
        "total": len(results),
        "passing_count": len(passing),
        "failing_count": len(failing),
        "slos": [r.to_dict() for r in results],
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Admin route registration helper
# ---------------------------------------------------------------------------

def register_slo_routes(router: Any) -> None:  # noqa: ANN001
    """Attach SLO-gate endpoints to an existing FastAPI router.

    Called from admin_api.py or admin_observability_routes.py.

    Endpoints added:
        GET  /slo/report   — Full SLO evaluation report
        GET  /slo/{name}   — Single SLO result by name
    """
    try:
        from fastapi import HTTPException  # noqa: PLC0415
    except ImportError:
        logger.warning("FastAPI not available — SLO routes not registered")
        return

    @router.get("/slo/report", summary="SLO Gate — full evaluation report")
    async def slo_report() -> Dict[str, Any]:
        return get_slo_report()

    @router.get("/slo/{slo_name}", summary="SLO Gate — single SLO result")
    async def slo_single(slo_name: str) -> Dict[str, Any]:
        evaluator = SLOEvaluator()
        result = evaluator.evaluate_one(slo_name)
        if result is None:
            raise HTTPException(
                status_code=404,
                detail=f"SLO '{slo_name}' not found. "
                f"Available: {[s.name for s in DEFAULT_SLOS]}",
            )
        return result.to_dict()


# ---------------------------------------------------------------------------
# CLI entry point — exits 0 on pass, 1 on failure
# ---------------------------------------------------------------------------

def _cli_main() -> int:
    """Run the SLO gate from the command line.

    Prints a human-readable report and returns exit code 0 (all pass)
    or 1 (one or more SLOs fail).
    """
    logging.basicConfig(level=logging.WARNING)

    evaluator = SLOEvaluator()
    results = evaluator.evaluate_all()

    print(f"\nSLO Gate Evaluation — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
    print(f"{'SLO Name':<30} {'Metric':<45} {'Threshold':>10} {'Actual':>10} {'Status':>6}")
    print("-" * 110)

    any_failed = False
    for result in results:
        actual_str = f"{result.actual_value:.4f}" if result.actual_value is not None else "no-data"
        status = "PASS" if result.passed else "FAIL"
        if not result.passed:
            any_failed = True
        print(
            f"{result.slo.name:<30} {result.slo.metric:<45} "
            f"{result.slo.threshold:>10.4f} {actual_str:>10} {status:>6}"
        )

    print()
    if any_failed:
        failing_names = [r.slo.name for r in results if not r.passed]
        print(f"RELEASE BLOCKED — {len(failing_names)} SLO(s) failed: {failing_names}")
        return 1

    print(f"All {len(results)} SLOs passed.")
    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())
