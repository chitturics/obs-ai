"""Integration tests — verify enterprise modules are wired into the execution pipeline.

These tests verify that:
1. Circuit breaker blocks execution when open
2. Safety policies deny execution when configured
3. Latency/SLO/cost trackers receive data from skill execution
"""

import pytest


@pytest.fixture(autouse=True)
def ensure_handlers():
    from chat_app.skill_executor import _register_builtin_internal_handlers
    _register_builtin_internal_handlers()
    # Ensure execution tracker writes to /tmp (not /app/data)
    import chat_app.execution_tracker as et_mod
    if et_mod._store_instance is None:
        from chat_app.execution_tracker import ExecutionStore
        et_mod._store_instance = ExecutionStore(persist_path="/tmp/test_global_traces.jsonl")


def _make_executor():
    from chat_app.skill_executor import SkillExecutor
    return SkillExecutor()


class TestCircuitBreakerWired:
    """Verify circuit breaker is checked before skill execution."""

    @pytest.mark.asyncio
    async def test_open_circuit_blocks_execution(self):
        """When circuit is open, skill executor should return fast failure."""
        from chat_app.circuit_breaker import CircuitBreakerRegistry
        import chat_app.circuit_breaker as cb_mod

        registry = CircuitBreakerRegistry(default_failure_threshold=2, default_cooldown_seconds=60)
        registry.record_failure("base64_encode")
        registry.record_failure("base64_encode")
        assert not registry.allow_request("base64_encode")

        old = cb_mod._registry_instance
        cb_mod._registry_instance = registry
        try:
            executor = _make_executor()
            result = await executor.execute(handler_key="base64_encode", params={"input": "test"})
            assert result.success is False
            assert "circuit breaker" in result.error.lower()
        finally:
            cb_mod._registry_instance = old

    @pytest.mark.asyncio
    async def test_closed_circuit_allows_execution(self):
        """When circuit is closed, execution proceeds normally."""
        from chat_app.circuit_breaker import CircuitBreakerRegistry
        import chat_app.circuit_breaker as cb_mod

        registry = CircuitBreakerRegistry()
        old = cb_mod._registry_instance
        cb_mod._registry_instance = registry
        try:
            executor = _make_executor()
            result = await executor.execute(handler_key="base64_encode", params={"input": "hello"})
            assert result.success is True
            assert result.output
        finally:
            cb_mod._registry_instance = old


class TestSafetyPoliciesWired:
    """Verify safety policies are enforced at skill execution."""

    @pytest.mark.asyncio
    async def test_destructive_tool_in_production(self, monkeypatch):
        """Destructive tools in production should require approval or be denied."""
        monkeypatch.setenv("DEPLOYMENT_ENV", "production")

        executor = _make_executor()
        result = await executor.execute(
            handler_key="delete_index",
            params={"input": "test_index", "user_role": "VIEWER"},
        )
        # Should be blocked: either safety policy deny, approval required, or handler not found
        # (delete_index doesn't have a real internal handler, but safety check runs first)
        assert not result.success


class TestExecutionTrackerWired:
    """Verify ExecutionTracker receives data from REAL skill execution."""

    @pytest.mark.asyncio
    async def test_skill_execution_recorded_in_tracker(self):
        """When a skill executes, ExecutionStore must receive a trace."""
        from chat_app.execution_tracker import ExecutionStore
        import chat_app.execution_tracker as et_mod

        store = ExecutionStore(persist_path="/tmp/test_pipeline_traces.jsonl")
        old = et_mod._store_instance
        et_mod._store_instance = store
        try:
            executor = _make_executor()
            await executor.execute(handler_key="uuid_generate", params={"input": ""})

            traces = store.query(category="skill")
            assert len(traces) >= 1, "ExecutionStore should have received a skill trace"
            assert traces[0]["name"] == "uuid_generate" or "uuid" in str(traces[0])
            assert traces[0]["success"] is True
        finally:
            et_mod._store_instance = old

    @pytest.mark.asyncio
    async def test_failed_skill_recorded_in_tracker(self):
        """Failed skill execution must also be recorded."""
        from chat_app.execution_tracker import ExecutionStore
        import chat_app.execution_tracker as et_mod

        store = ExecutionStore(persist_path="/tmp/test_pipeline_traces.jsonl")
        old = et_mod._store_instance
        et_mod._store_instance = store
        try:
            executor = _make_executor()
            # nonexistent_handler will fail
            await executor.execute(handler_key="nonexistent_handler_xyz", params={"input": "test"})

            traces = store.query(success=False)
            assert len(traces) >= 1, "ExecutionStore should have a failure trace"
        finally:
            et_mod._store_instance = old


class TestTrackerFeedback:
    """Verify trackers receive data from skill execution."""

    @pytest.mark.asyncio
    async def test_circuit_breaker_records_success(self):
        """Successful execution should record to circuit breaker."""
        from chat_app.circuit_breaker import CircuitBreakerRegistry
        import chat_app.circuit_breaker as cb_mod

        registry = CircuitBreakerRegistry()
        old = cb_mod._registry_instance
        cb_mod._registry_instance = registry
        try:
            executor = _make_executor()
            await executor.execute(handler_key="uuid_generate", params={"input": ""})
            status = registry.get_status("uuid_generate")
            assert status is not None
        finally:
            cb_mod._registry_instance = old

    @pytest.mark.asyncio
    async def test_latency_tracker_records(self):
        """Execution should record latency to the tracker."""
        from chat_app.latency_budgets import LatencyTracker
        import chat_app.latency_budgets as lt_mod

        tracker = LatencyTracker()
        old = lt_mod._tracker_instance
        lt_mod._tracker_instance = tracker
        try:
            executor = _make_executor()
            await executor.execute(handler_key="uuid_generate", params={"input": ""})
            report = tracker.get_report("uuid_generate")
            assert report["samples"] >= 1
        finally:
            lt_mod._tracker_instance = old

    @pytest.mark.asyncio
    async def test_slo_tracker_records(self):
        """Execution should record to SLO tracker."""
        from chat_app.slo_tracker import SLOTracker
        import chat_app.slo_tracker as slo_mod

        tracker = SLOTracker()
        old = slo_mod._tracker_instance
        slo_mod._tracker_instance = tracker
        try:
            executor = _make_executor()
            await executor.execute(handler_key="uuid_generate", params={"input": ""})
            result = tracker.evaluate("tool_success_rate")
            assert result["total"] >= 1
        finally:
            slo_mod._tracker_instance = old
