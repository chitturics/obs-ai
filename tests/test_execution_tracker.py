"""Tests for the universal execution tracker."""

import pytest


@pytest.fixture
def store(tmp_path):
    from chat_app.execution_tracker import ExecutionStore
    return ExecutionStore(persist_path=str(tmp_path / "traces.jsonl"))


@pytest.fixture
def trace():
    from chat_app.execution_tracker import _create_trace
    return _create_trace("skill", "splunk_search", actor="admin")


class TestWorkflowTrace:

    def test_create_trace(self, trace):
        assert trace.trace_id
        assert trace.category == "skill"
        assert trace.name == "splunk_search"
        assert trace.actor == "admin"

    def test_set_result(self, trace):
        trace.set_result(success=True, output="42 results", tokens=150, chunks=5)
        assert trace.success is True
        assert trace.completion_tokens == 150
        assert trace.chunks_retrieved == 5

    def test_finish(self, trace):
        import time
        time.sleep(0.01)
        trace.finish()
        assert trace.latency_ms > 0
        assert trace.finished_at

    def test_to_dict(self, trace):
        trace.finish()
        trace.success = True
        d = trace.to_dict()
        assert d["category"] == "skill"
        assert d["name"] == "splunk_search"
        assert "latency_ms" in d

    def test_children(self, trace):
        from chat_app.execution_tracker import _create_trace
        child = _create_trace("skill", "explain_spl", parent_id=trace.trace_id)
        child.finish()
        child.success = True
        trace.children.append(child)
        d = trace.to_dict()
        assert "children" in d
        assert len(d["children"]) == 1


class TestExecutionStore:

    def test_record_and_query(self, store, trace):
        trace.finish()
        trace.success = True
        store.record(trace)
        results = store.query(category="skill")
        assert len(results) >= 1

    def test_query_by_name(self, store):
        from chat_app.execution_tracker import _create_trace
        t1 = _create_trace("skill", "search"); t1.finish(); t1.success = True
        t2 = _create_trace("skill", "explain"); t2.finish(); t2.success = True
        store.record(t1)
        store.record(t2)
        results = store.query(name="search")
        assert len(results) == 1

    def test_query_by_success(self, store):
        from chat_app.execution_tracker import _create_trace
        t1 = _create_trace("skill", "a"); t1.finish(); t1.success = True
        t2 = _create_trace("skill", "b"); t2.finish(); t2.success = False; t2.error = "fail"
        store.record(t1)
        store.record(t2)
        failures = store.query(success=False)
        assert len(failures) == 1

    def test_stats(self, store):
        from chat_app.execution_tracker import _create_trace
        for i in range(5):
            t = _create_trace("command", f"/cmd{i}")
            t.finish(); t.success = True
            store.record(t)
        for i in range(3):
            t = _create_trace("agent", f"agent{i}")
            t.finish(); t.success = True
            store.record(t)
        stats = store.get_stats()
        assert stats["total_traces"] == 8
        assert stats["by_category"]["command"] == 5
        assert stats["by_category"]["agent"] == 3

    def test_dashboard(self, store):
        from chat_app.execution_tracker import _create_trace
        for i in range(10):
            t = _create_trace("skill", "search")
            t.finish(); t.success = i < 8  # 80% success
            store.record(t)
        dashboard = store.get_dashboard()
        assert dashboard["recent_count"] == 10
        assert dashboard["success_rate"] == 0.8


class TestTrackExecution:

    @pytest.mark.asyncio
    async def test_context_manager(self):
        from chat_app.execution_tracker import track_execution_ctx, get_execution_store
        import chat_app.execution_tracker as mod
        store = ExecutionStore(persist_path="/tmp/test_traces.jsonl")
        old = mod._store_instance
        mod._store_instance = store
        try:
            async with track_execution_ctx("command", "/test") as trace:
                trace.success = True
            assert store.query(category="command")
        finally:
            mod._store_instance = old

    @pytest.mark.asyncio
    async def test_decorator(self):
        from chat_app.execution_tracker import track_execution, get_execution_store, ExecutionStore
        import chat_app.execution_tracker as mod
        store = ExecutionStore(persist_path="/tmp/test_traces.jsonl")
        old = mod._store_instance
        mod._store_instance = store
        try:
            @track_execution(category="command", name="/decorated")
            async def my_command():
                return "done"

            await my_command()
            results = store.query(category="command")
            assert len(results) >= 1
            assert results[0]["name"] == "/decorated"
        finally:
            mod._store_instance = old

    @pytest.mark.asyncio
    async def test_error_tracking(self):
        from chat_app.execution_tracker import track_execution_ctx, ExecutionStore
        import chat_app.execution_tracker as mod
        store = ExecutionStore(persist_path="/tmp/test_traces.jsonl")
        old = mod._store_instance
        mod._store_instance = store
        try:
            with pytest.raises(ValueError):
                async with track_execution_ctx("skill", "broken") as trace:
                    raise ValueError("test error")
            results = store.query(success=False)
            assert len(results) >= 1
            assert "test error" in results[0]["error"]
        finally:
            mod._store_instance = old


# Need this import for the store fixture
from chat_app.execution_tracker import ExecutionStore
