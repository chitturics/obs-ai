"""Comprehensive tests for chat_app/query_planner.py."""
import sys
import asyncio
import types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chat_app.query_planner import (
    QueryStep,
    QueryPlanResult,
    detect_sequential_query,
    _split_into_steps,
    _extract_key_terms,
    execute_sequential_retrieval,
)


# ---------------------------------------------------------------------------
# 1. QueryStep dataclass
# ---------------------------------------------------------------------------
class TestQueryStep:
    """Tests for the QueryStep dataclass."""

    def test_defaults(self):
        step = QueryStep(description="find errors")
        assert step.description == "find errors"
        assert step.depends_on_previous is False
        assert step.retrieval_query == ""

    def test_depends_on_previous(self):
        step = QueryStep(description="correlate with hosts", depends_on_previous=True)
        assert step.depends_on_previous is True

    def test_retrieval_query(self):
        step = QueryStep(
            description="get top sourcetypes",
            retrieval_query="index=main | top sourcetype",
        )
        assert step.retrieval_query == "index=main | top sourcetype"


# ---------------------------------------------------------------------------
# 2. QueryPlanResult dataclass
# ---------------------------------------------------------------------------
class TestQueryPlanResult:
    """Tests for the QueryPlanResult dataclass."""

    def test_defaults(self):
        result = QueryPlanResult()
        assert result.is_sequential is False
        assert result.steps == []
        assert result.original_query == ""

    def test_populated_result(self):
        steps = [
            QueryStep(description="step1"),
            QueryStep(description="step2", depends_on_previous=True),
        ]
        result = QueryPlanResult(is_sequential=True, steps=steps, original_query="do A then B")
        assert result.is_sequential is True
        assert len(result.steps) == 2
        assert result.original_query == "do A then B"

    def test_single_step_non_sequential(self):
        step = QueryStep(description="show errors", retrieval_query="show errors")
        result = QueryPlanResult(
            is_sequential=False,
            steps=[step],
            original_query="show errors",
        )
        assert result.is_sequential is False
        assert len(result.steps) == 1


# ---------------------------------------------------------------------------
# 3. detect_sequential_query()
# ---------------------------------------------------------------------------
class TestDetectSequentialQuery:
    """Tests for detect_sequential_query."""

    # -- Non-sequential queries --
    def test_non_sequential_returns_false(self):
        result = detect_sequential_query("show me all errors")
        assert result.is_sequential is False
        assert len(result.steps) == 1

    def test_simple_query_single_step(self):
        result = detect_sequential_query("show me errors")
        assert result.is_sequential is False
        assert len(result.steps) == 1
        assert result.steps[0].description == "show me errors"

    def test_simple_spl_query_single_step(self):
        result = detect_sequential_query("index=main sourcetype=syslog | head 10")
        assert result.is_sequential is False
        assert len(result.steps) == 1

    # -- "first X then Y" --
    def test_first_then_detected(self):
        result = detect_sequential_query(
            "first find all errors then correlate with deployment events"
        )
        assert result.is_sequential is True
        assert len(result.steps) == 2

    def test_first_get_top_sourcetypes_then_show_event_counts(self):
        query = "first get the top sourcetypes, then show event counts"
        result = detect_sequential_query(query)
        assert result.is_sequential is True
        assert len(result.steps) == 2
        assert "sourcetypes" in result.steps[0].description.lower()
        assert "event counts" in result.steps[1].description.lower()

    # -- "X and then Y" --
    def test_and_then_detected(self):
        result = detect_sequential_query(
            "find failed logins and then check successful logins"
        )
        assert result.is_sequential is True
        assert len(result.steps) == 2

    def test_find_failed_logins_and_then_check(self):
        query = "find failed logins and then check successful logins"
        result = detect_sequential_query(query)
        assert result.is_sequential is True
        assert "failed logins" in result.steps[0].description.lower()
        assert "successful logins" in result.steps[1].description.lower()

    # -- "X, after that Y" --
    def test_after_that_detected(self):
        result = detect_sequential_query(
            "get the error count, after that break down by host"
        )
        assert result.is_sequential is True
        assert len(result.steps) == 2

    # -- "X, next Y" --
    def test_next_detected(self):
        result = detect_sequential_query(
            "list the indexes, next show their sizes"
        )
        assert result.is_sequential is True
        assert len(result.steps) == 2

    # -- "X followed by Y" --
    def test_followed_by_detected(self):
        result = detect_sequential_query(
            "show errors followed by a timeline of deployments"
        )
        assert result.is_sequential is True
        assert len(result.steps) == 2

    # -- "once you get X, then Y" --
    def test_once_you_get_detected(self):
        result = detect_sequential_query(
            "once you get the top users, then show their activity"
        )
        assert result.is_sequential is True
        assert len(result.steps) == 2

    # -- "step 1 X step 2 Y" --
    def test_step_numbers_detected(self):
        # "step 1" triggers the _SEQUENTIAL_PATTERNS match, but the
        # text also needs to be splittable. Add "then" to ensure a split.
        result = detect_sequential_query(
            "step 1 find errors then step 2 correlate with hosts"
        )
        assert result.is_sequential is True
        assert len(result.steps) >= 2

    # -- "correlate X with Y" --
    def test_correlate_with_detected(self):
        result = detect_sequential_query(
            "correlate errors with deployment events"
        )
        # "correlate X with Y" matches _SEQUENTIAL_PATTERNS but there is no
        # splitter that can separate it into 2 steps, so it falls back to
        # is_sequential=False (single step).
        # The key point: pattern IS detected, but splitting fails -> False
        assert result.is_sequential is False
        assert len(result.steps) == 1

    # -- "compare X with Y" --
    def test_compare_with_detected(self):
        result = detect_sequential_query(
            "compare login failures with successful logins"
        )
        # Same as correlate: pattern detected, but no splitter matches
        assert result.is_sequential is False
        assert len(result.steps) == 1

    # -- "check if X also Y" --
    def test_check_if_also_detected(self):
        result = detect_sequential_query(
            "check if failed login users also had successful logins"
        )
        assert result.is_sequential is False
        assert len(result.steps) == 1

    # -- "based on the results" --
    def test_based_on_results_detected(self):
        result = detect_sequential_query(
            "find errors, then based on the results show the hosts"
        )
        assert result.is_sequential is True
        assert len(result.steps) >= 2

    # -- "from those results" --
    def test_from_those_results_detected(self):
        result = detect_sequential_query(
            "search for failed logins, then from those results get usernames"
        )
        assert result.is_sequential is True
        assert len(result.steps) >= 2

    # -- "using those results" --
    def test_using_those_results_detected(self):
        result = detect_sequential_query(
            "get top sourcetypes, then using those results show volumes"
        )
        assert result.is_sequential is True
        assert len(result.steps) >= 2

    # -- semicolons as splitters --
    def test_semicolons_as_splitters(self):
        result = detect_sequential_query(
            "find errors; then correlate with deployments"
        )
        assert result.is_sequential is True
        assert len(result.steps) >= 2

    # -- dependency flags --
    def test_step1_no_dependency_step2_has_dependency(self):
        result = detect_sequential_query(
            "first find errors, then correlate with hosts"
        )
        assert result.is_sequential is True
        assert result.steps[0].depends_on_previous is False
        assert result.steps[1].depends_on_previous is True

    # -- original query preserved --
    def test_original_query_preserved(self):
        query = "first find errors, then correlate with hosts"
        result = detect_sequential_query(query)
        assert result.original_query == query

    def test_original_query_preserved_non_sequential(self):
        query = "show me errors"
        result = detect_sequential_query(query)
        assert result.original_query == query

    # -- correlate ... with ... when also a splitter is present --
    def test_correlate_with_then_splitter(self):
        result = detect_sequential_query(
            "find errors, then correlate them with deployment events"
        )
        assert result.is_sequential is True
        assert len(result.steps) >= 2

    # -- edge cases --
    def test_empty_string(self):
        result = detect_sequential_query("")
        assert result.is_sequential is False


# ---------------------------------------------------------------------------
# 4. _split_into_steps()
# ---------------------------------------------------------------------------
class TestSplitIntoSteps:
    """Tests for _split_into_steps (internal helper)."""

    def test_first_x_then_y(self):
        steps = _split_into_steps("first find errors, then check the hosts")
        assert len(steps) == 2
        assert "find errors" in steps[0].description.lower()
        assert "check the hosts" in steps[1].description.lower()

    def test_x_and_then_y(self):
        steps = _split_into_steps("find errors and then check the hosts")
        assert len(steps) == 2

    def test_semicolons_three_parts(self):
        steps = _split_into_steps("find errors; check hosts; review logs")
        assert len(steps) == 3

    def test_first_step_no_dependency(self):
        steps = _split_into_steps("first get data, then filter it")
        assert steps[0].depends_on_previous is False

    def test_subsequent_steps_have_dependency(self):
        steps = _split_into_steps("first get data, then filter it")
        assert steps[1].depends_on_previous is True

    def test_single_clause_returns_single_step(self):
        steps = _split_into_steps("show me all errors")
        assert len(steps) == 1
        assert steps[0].depends_on_previous is False

    def test_multiple_then_splits_into_three(self):
        steps = _split_into_steps(
            "find errors then check hosts then review logs"
        )
        assert len(steps) == 3
        assert steps[0].depends_on_previous is False
        assert steps[1].depends_on_previous is True
        assert steps[2].depends_on_previous is True

    def test_after_that_split(self):
        steps = _split_into_steps("get errors, after that show hosts")
        assert len(steps) == 2

    def test_followed_by_split(self):
        steps = _split_into_steps("get errors followed by host breakdown")
        assert len(steps) == 2

    def test_retrieval_query_matches_description(self):
        steps = _split_into_steps("first find errors, then check hosts")
        for step in steps:
            assert step.retrieval_query == step.description


# ---------------------------------------------------------------------------
# 5. _extract_key_terms()
# ---------------------------------------------------------------------------
class TestExtractKeyTerms:
    """Tests for _extract_key_terms."""

    def test_extracts_field_value_patterns(self):
        chunks = [{"text": "sourcetype=syslog host=web01"}]
        result = _extract_key_terms(chunks)
        assert "sourcetype=syslog" in result or "sourcetype =syslog" in result
        assert "host=web01" in result or "host =web01" in result

    def test_extracts_pipe_command_names(self):
        chunks = [{"text": "| stats count by host | timechart span=1h count"}]
        result = _extract_key_terms(chunks)
        assert "stats" in result
        assert "timechart" in result

    def test_respects_max_terms_limit(self):
        chunks = [
            {
                "text": (
                    "a=1 b=2 c=3 d=4 e=5 f=6 g=7 h=8 i=9 j=10 "
                    "k=11 l=12 m=13 n=14 o=15"
                )
            }
        ]
        result = _extract_key_terms(chunks, max_terms=3)
        terms = result.split()
        assert len(terms) <= 3

    def test_empty_chunks_returns_empty_string(self):
        result = _extract_key_terms([])
        assert result == ""

    def test_chunks_without_spl_patterns(self):
        chunks = [{"text": "This is just plain English with no special patterns."}]
        result = _extract_key_terms(chunks)
        assert result == ""

    def test_multiple_chunks_combine_terms(self):
        chunks = [
            {"text": "sourcetype=syslog"},
            {"text": "| stats count"},
        ]
        result = _extract_key_terms(chunks)
        # Should contain terms from both chunks
        assert "sourcetype=syslog" in result or "sourcetype =syslog" in result
        assert "stats" in result

    def test_chunks_with_missing_text_key(self):
        chunks = [{"other_key": "no text here"}]
        result = _extract_key_terms(chunks)
        assert result == ""

    def test_default_max_terms_is_ten(self):
        # Build text that generates more than 10 unique terms
        fields = " ".join(f"f{i}=v{i}" for i in range(20))
        chunks = [{"text": fields}]
        result = _extract_key_terms(chunks)
        terms = result.split()
        assert len(terms) <= 10


# ---------------------------------------------------------------------------
# 6. execute_sequential_retrieval() (async, requires chainlit mock)
# ---------------------------------------------------------------------------
class TestExecuteSequentialRetrieval:
    """Tests for execute_sequential_retrieval (async)."""

    @pytest.fixture(autouse=True)
    def _mock_chainlit(self, monkeypatch):
        """Inject a fake chainlit module so the import inside
        execute_sequential_retrieval succeeds without a running server."""
        fake_cl = types.ModuleType("chainlit")

        # cl.make_async(fn) should just return fn as a coroutine wrapper
        def _make_async(fn):
            async def _wrapper(*args, **kwargs):
                return fn(*args, **kwargs)
            return _wrapper

        fake_cl.make_async = _make_async
        monkeypatch.setitem(sys.modules, "chainlit", fake_cl)

    @pytest.mark.asyncio
    async def test_single_step(self):
        def search_func(store, query, k=10, profile=None,
                        weight_map_override=None, user_settings=None):
            return [{"text": "result1"}]

        steps = [QueryStep(description="find errors", retrieval_query="find errors")]
        chunks, summaries = await execute_sequential_retrieval(
            steps, search_func, store=None, k=30,
        )
        assert len(chunks) == 1
        assert len(summaries) == 1
        assert "Step 1" in summaries[0]

    @pytest.mark.asyncio
    async def test_two_steps_with_dependency(self):
        call_queries = []

        def search_func(store, query, k=10, profile=None,
                        weight_map_override=None, user_settings=None):
            call_queries.append(query)
            return [{"text": f"result for {query[:20]}"}]

        steps = [
            QueryStep(description="find errors", depends_on_previous=False,
                      retrieval_query="find errors"),
            QueryStep(description="correlate with hosts", depends_on_previous=True,
                      retrieval_query="correlate with hosts"),
        ]
        chunks, summaries = await execute_sequential_retrieval(
            steps, search_func, store=None, k=30,
        )
        assert len(summaries) == 2
        # Second call should have been enriched with terms from first call's results
        # (if any key terms were extractable). Regardless, two calls must have happened.
        assert len(call_queries) == 2

    @pytest.mark.asyncio
    async def test_enrichment_adds_terms(self):
        """When step 2 depends on previous and step 1 returns field=value
        patterns, the second query should be enriched."""
        call_queries = []

        def search_func(store, query, k=10, profile=None,
                        weight_map_override=None, user_settings=None):
            call_queries.append(query)
            if len(call_queries) == 1:
                return [{"text": "sourcetype=syslog host=web01"}]
            return [{"text": "result2"}]

        steps = [
            QueryStep(description="find errors", depends_on_previous=False,
                      retrieval_query="find errors"),
            QueryStep(description="check hosts", depends_on_previous=True,
                      retrieval_query="check hosts"),
        ]
        await execute_sequential_retrieval(steps, search_func, store=None, k=30)
        # The second query should be longer (enriched)
        assert len(call_queries[1]) > len("check hosts")

    @pytest.mark.asyncio
    async def test_deduplication(self):
        def search_func(store, query, k=10, profile=None,
                        weight_map_override=None, user_settings=None):
            return [{"text": "duplicate result"}]

        steps = [
            QueryStep(description="step 1", depends_on_previous=False,
                      retrieval_query="step 1"),
            QueryStep(description="step 2", depends_on_previous=False,
                      retrieval_query="step 2"),
        ]
        chunks, _ = await execute_sequential_retrieval(
            steps, search_func, store=None, k=30,
        )
        # Both steps return the same text -> should be deduped to 1
        assert len(chunks) == 1

    @pytest.mark.asyncio
    async def test_k_limits_total_results(self):
        def search_func(store, query, k=10, profile=None,
                        weight_map_override=None, user_settings=None):
            return [{"text": f"chunk-{i}-{query[:5]}"} for i in range(k)]

        steps = [
            QueryStep(description="step 1", depends_on_previous=False,
                      retrieval_query="step 1"),
            QueryStep(description="step 2", depends_on_previous=False,
                      retrieval_query="step 2"),
        ]
        k = 5
        chunks, _ = await execute_sequential_retrieval(
            steps, search_func, store=None, k=k,
        )
        assert len(chunks) <= k

    @pytest.mark.asyncio
    async def test_step_summaries_generated(self):
        def search_func(store, query, k=10, profile=None,
                        weight_map_override=None, user_settings=None):
            return [{"text": "data"}]

        steps = [
            QueryStep(description="find errors", depends_on_previous=False,
                      retrieval_query="find errors"),
            QueryStep(description="check hosts", depends_on_previous=True,
                      retrieval_query="check hosts"),
        ]
        _, summaries = await execute_sequential_retrieval(
            steps, search_func, store=None, k=30,
        )
        assert len(summaries) == 2
        assert "Step 1" in summaries[0]
        assert "Step 2" in summaries[1]
        assert "1 chunks" in summaries[0]

    @pytest.mark.asyncio
    async def test_failed_step_records_failure(self):
        def search_func(store, query, k=10, profile=None,
                        weight_map_override=None, user_settings=None):
            raise RuntimeError("search broke")

        steps = [
            QueryStep(description="will fail", depends_on_previous=False,
                      retrieval_query="will fail"),
        ]
        chunks, summaries = await execute_sequential_retrieval(
            steps, search_func, store=None, k=30,
        )
        assert len(chunks) == 0
        assert "failed" in summaries[0].lower()

    @pytest.mark.asyncio
    async def test_k_divided_among_steps(self):
        """Each step should receive k // len(steps) as its individual k."""
        received_k = []

        def search_func(store, query, k=10, profile=None,
                        weight_map_override=None, user_settings=None):
            received_k.append(k)
            return []

        steps = [
            QueryStep(description="s1", depends_on_previous=False,
                      retrieval_query="s1"),
            QueryStep(description="s2", depends_on_previous=True,
                      retrieval_query="s2"),
        ]
        await execute_sequential_retrieval(steps, search_func, store=None, k=20)
        assert received_k[0] == 10  # 20 // 2
        assert received_k[1] == 10
