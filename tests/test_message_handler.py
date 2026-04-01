"""
Comprehensive tests for chat_app/message_handler.py — the core pipeline.

Covers:
 1. Helper functions (_is_pronoun_heavy, _simplify_query_for_retrieval, _run_local_optimizer)
 2. retrieve_context (ChromaDB retrieval, caching, fallback strategies)
 3. build_llm_context (context assembly, optimizer, knowledge graph injection)
 4. generate_llm_response (LLM call, optimizer bypass, fallback text)
 5. build_final_response (confidence, sources, references, follow-ups)
 6. _handle_direct_intent (search_suggestion, meta_question, clarification)
 7. on_message (full pipeline integration, error recovery, edge cases)
 8. Edge cases (empty input, very long input, special characters, unicode)
"""

import sys
import os
import hashlib
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Lazy import helper
# ---------------------------------------------------------------------------

_MODULE_CACHE = {}


import importlib
import importlib.abc
import importlib.machinery


class _FallbackFinder(importlib.abc.MetaPathFinder):
    """Meta path finder that auto-mocks any missing package from a known set.

    Uses the modern find_spec API (Python 3.4+).  Also handles the case
    where a parent package is already a MagicMock in sys.modules (e.g.
    ``splunklib``) and a submodule import like ``splunklib.binding``
    fails because MagicMock is "not a package".
    """

    _MOCK_PREFIXES = (
        "langchain", "chromadb", "splunklib", "ollama",
        "sqlalchemy", "psycopg2", "psycopg",
        "langfuse", "opentelemetry",
        "pypdf", "docx", "pptx", "openpyxl",
        "sentence_transformers", "transformers", "torch",
        "redis",
        # NOTE: httpx intentionally excluded — starlette.testclient inherits from
        # httpx.Response and mocking httpx causes metaclass conflicts when both
        # test_message_handler and test files using TestClient run in the same session.
    )
    # Packages that should NOT be mocked even if they match a prefix,
    # because they are used in isinstance() checks in production code,
    # or are installed and needed by other test modules.
    _EXCLUDE = (
        "langchain_google_genai",
        "opentelemetry",  # Installed; mocking breaks otel_tracing tests run in same session
    )

    def find_spec(self, fullname, path, target=None):
        if any(fullname.startswith(pfx) for pfx in self._MOCK_PREFIXES):
            if any(fullname.startswith(ex) for ex in self._EXCLUDE):
                return None  # Excluded — let normal import (or ImportError) handle it
            # Pre-register as mock so submodule imports also resolve
            if fullname not in sys.modules:
                mock = MagicMock()
                mock.__path__ = []
                mock.__name__ = fullname
                mock.__package__ = fullname
                sys.modules[fullname] = mock
                # Wire up parent -> child attribute
                if "." in fullname:
                    parent, child = fullname.rsplit(".", 1)
                    if parent in sys.modules:
                        setattr(sys.modules[parent], child, mock)
            return importlib.machinery.ModuleSpec(fullname, _FallbackLoader())
        return None


class _FallbackLoader(importlib.abc.Loader):
    def create_module(self, spec):
        mock = MagicMock()
        mock.__path__ = []
        mock.__name__ = spec.name
        mock.__spec__ = spec
        return mock

    def exec_module(self, module):
        pass


# Install auto-mocker BEFORE any message_handler import
if not any(isinstance(f, _FallbackFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _FallbackFinder())

# Ensure any MagicMock packages already in sys.modules have __path__ as a
# real list so Python's import machinery treats them as packages (allowing
# submodule imports like ``splunklib.binding``).  MagicMock dunder attrs
# need configure_mock() to be set properly.
for _prefix in _FallbackFinder._MOCK_PREFIXES:
    _existing = sys.modules.get(_prefix)
    if _existing is not None and isinstance(_existing, MagicMock):
        _existing.configure_mock(__path__=[], __package__=_prefix, __name__=_prefix)
        _existing.__spec__ = importlib.machinery.ModuleSpec(_prefix, None, is_package=True)

# Also pre-set chainlit mock if not already present
if "chainlit" not in sys.modules:
    _cl_mock = MagicMock()
    _cl_mock.user_session = MagicMock()
    _cl_mock.__path__ = []
    sys.modules["chainlit"] = _cl_mock


def _get_handler():
    """Import message_handler lazily."""
    if "handler" in _MODULE_CACHE:
        return _MODULE_CACHE["handler"]
    import chat_app.message_handler as mh
    _MODULE_CACHE["handler"] = mh
    return mh


# ---------------------------------------------------------------------------
# Helpers for creating well-configured mocks
# ---------------------------------------------------------------------------

def _make_cl_mock():
    """Create a properly configured chainlit mock with async support."""
    mock_cl = MagicMock()
    mock_cl.user_session = MagicMock()
    mock_cl.context = MagicMock()
    mock_cl.context.current_step = MagicMock()
    mock_cl.TaskList = MagicMock
    mock_cl.Task = MagicMock
    mock_cl.TaskStatus = MagicMock()
    mock_cl.make_async = lambda func: AsyncMock(return_value=[])

    def make_message(**kwargs):
        msg = MagicMock()
        msg.content = kwargs.get("content", "")
        msg.send = AsyncMock()
        msg.update = AsyncMock()
        msg.stream_token = AsyncMock()
        msg.id = "msg-mock-id"
        msg.actions = []
        return msg
    mock_cl.Message = MagicMock(side_effect=make_message)
    mock_cl.Action = MagicMock()
    return mock_cl


def _make_logging_utils_mock():
    m = MagicMock()
    m.set_request_context.return_value = "req-123"
    m.clear_request_context = MagicMock()
    lt = MagicMock()
    lt.start = MagicMock()
    lt.stop = MagicMock(return_value=50.0)
    lt.summary = MagicMock(return_value="r=50ms")
    m.LatencyTracker.return_value = lt
    return m


def _make_conv_mem_mock(resolve_side_effect=None):
    m = MagicMock()
    m.resolve_references = MagicMock(side_effect=resolve_side_effect or (lambda x: x))
    m.get_conversation_context = MagicMock(return_value=None)
    m.store_conversation_turn = MagicMock()
    return m


def _on_message_patches(mock_cl, mock_lu, mock_cm, extras=None):
    """Return an ExitStack with all common on_message patches applied.

    Use `extras` dict to override specific patches.
    ``extras`` maps mock target string -> mock value.
    """
    stack = ExitStack()
    stack.enter_context(patch("chat_app.message_handler.cl", mock_cl))
    # Also patch helpers module — prepare_request / route_and_track live there
    # and reference cl directly from their own module namespace.
    stack.enter_context(patch("chat_app.message_handler_helpers.cl", mock_cl))
    # current_username / current_thread_id are lazily imported from helper inside
    # prepare_request / route_and_track, so patch at the source module.
    stack.enter_context(patch("chat_app.message_handler.current_username", return_value="testuser"))
    stack.enter_context(patch("chat_app.message_handler.current_thread_id", return_value="t1"))
    stack.enter_context(patch("helper.current_username", return_value="testuser"))
    stack.enter_context(patch("helper.current_thread_id", return_value="t1"))
    stack.enter_context(patch.dict("sys.modules", {
        "chat_app.logging_utils": mock_lu,
        "chat_app.conversation_memory": mock_cm,
    }))
    stack.enter_context(patch("chat_app.message_handler.get_metrics", return_value=MagicMock()))

    # Apply extras (override defaults or add new patches)
    applied = {}
    if extras:
        for target, value in extras.items():
            if isinstance(value, dict) and "side_effect" in value:
                m = stack.enter_context(patch(target, new_callable=AsyncMock, side_effect=value["side_effect"]))
            elif isinstance(value, dict) and "return_value" in value:
                m = stack.enter_context(patch(target, new_callable=AsyncMock, return_value=value["return_value"]))
            elif callable(value) and not isinstance(value, MagicMock):
                m = stack.enter_context(patch(target, value))
            else:
                m = stack.enter_context(patch(target, value))
            applied[target] = m
    return stack, applied


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _reset_mh_state():
    """Reset settings cache to avoid cross-test pollution."""
    from chat_app.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def mh():
    return _get_handler()


@pytest.fixture
def mock_settings():
    s = MagicMock()
    s.retrieval.k_multiplier = 3
    s.knowledge_graph.max_context_facts = 8
    return s


@pytest.fixture
def mock_context(mock_settings):
    ctx = MagicMock()
    ctx.vector_store = MagicMock()
    ctx.engine = AsyncMock()
    ctx.starter_options = [{"message": "Help"}]
    ctx.search_roots = ["/app/documents"]
    ctx.profiles_available = False
    ctx.feedback_guardrails_available = False
    ctx.system_prompt = "You are a helpful Splunk assistant."
    ctx.chain = MagicMock()
    ctx.chain.astream = AsyncMock()
    ctx.llm = MagicMock()
    ctx.llm.ainvoke = AsyncMock(return_value=MagicMock(content="LLM response"))
    ctx.ensure_services_ready = AsyncMock()
    ctx.load_static_context = MagicMock(return_value=["Env: test"])
    ctx.map_source_to_url = MagicMock(return_value="http://e.com/d")
    ctx.SPEC_STATIC_ROOT = "/app/specs"
    ctx.LOCAL_DOCS_ROOT = "/app/docs"
    ctx.SPEC_SRC_ROOT = "/app/spec_src"
    ctx.settings = mock_settings
    ctx.mcp_tools = []
    return ctx


@pytest.fixture
def sample_memory_chunks():
    return [
        {"page_content": "stats agg", "metadata": {"source": "f://s.md", "collection": "spl"},
         "collection": "spl", "text": "stats agg"},
        {"page_content": "count by host", "metadata": {"source": "f://s.md", "collection": "spl"},
         "collection": "spl", "text": "count by host"},
        {"page_content": "tstats fast", "metadata": {"source": "f://t.md", "collection": "spl"},
         "collection": "spl", "text": "tstats fast"},
    ]


@pytest.fixture
def sample_scored_chunks():
    return [
        (0.95, "http://d/s.md", "stats", "f://s.md", {"collection": "spl", "text": "stats"}),
        (0.85, "http://d/t.md", "tstats", "f://t.md", {"collection": "spl", "text": "tstats"}),
    ]


# =========================================================================
# 1. _is_pronoun_heavy
# =========================================================================

class TestIsPronounHeavy:
    def test_optimize_that(self, mh):
        assert mh._is_pronoun_heavy("optimize that") is True

    def test_optimize_it(self, mh):
        assert mh._is_pronoun_heavy("Optimize it") is True

    def test_explain_this(self, mh):
        assert mh._is_pronoun_heavy("explain this") is True

    def test_review_the_query(self, mh):
        assert mh._is_pronoun_heavy("review the query") is True

    def test_what_about_prefix(self, mh):
        assert mh._is_pronoun_heavy("what about auth?") is True

    def test_and_also_prefix(self, mh):
        assert mh._is_pronoun_heavy("and also this") is True

    def test_do_that_again(self, mh):
        assert mh._is_pronoun_heavy("do that again") is True

    def test_same_but_for(self, mh):
        assert mh._is_pronoun_heavy("same but for prod") is True

    def test_normal_query(self, mh):
        assert mh._is_pronoun_heavy("how does stats work?") is False

    def test_spl_query(self, mh):
        assert mh._is_pronoun_heavy("index=main | stats count") is False

    def test_empty(self, mh):
        assert mh._is_pronoun_heavy("") is False

    def test_actual_content(self, mh):
        assert mh._is_pronoun_heavy("optimize index=main | stats count by host") is False

    def test_case_insensitive(self, mh):
        assert mh._is_pronoun_heavy("OPTIMIZE THAT") is True

    def test_whitespace(self, mh):
        assert mh._is_pronoun_heavy("   \t\n  ") is False


# =========================================================================
# 2. _simplify_query_for_retrieval
# =========================================================================

class TestSimplifyQuery:
    def test_strips_spl(self, mh):
        r = mh._simplify_query_for_retrieval("optimize index=main sourcetype=a | stats count by s")
        assert "index=" not in r
        assert "|" not in r

    def test_strips_fields(self, mh):
        r = mh._simplify_query_for_retrieval("index=sec host=w EventCode=4625")
        assert "index=sec" not in r

    def test_preserves_terms(self, mh):
        r = mh._simplify_query_for_retrieval("optimize index=main sourcetype=syslog | stats count")
        assert "optimize" in r.lower()

    def test_short_returns_original(self, mh):
        assert mh._simplify_query_for_retrieval("x") == "x"

    def test_plain_text(self, mh):
        r = mh._simplify_query_for_retrieval("how does stats command work")
        assert "stats" in r

    def test_empty(self, mh):
        assert mh._simplify_query_for_retrieval("") == ""

    def test_brackets(self, mh):
        r = mh._simplify_query_for_retrieval('[search index=main "error"]')
        assert "[" not in r

    def test_unicode(self, mh):
        assert isinstance(mh._simplify_query_for_retrieval("search 日本語"), str)

    def test_long_input(self, mh):
        r = mh._simplify_query_for_retrieval("index=main | stats count " * 100)
        assert len(r) > 0

    def test_injection(self, mh):
        assert isinstance(mh._simplify_query_for_retrieval("'; DROP TABLE x; --"), str)


# =========================================================================
# 3. _run_local_optimizer
# =========================================================================

class TestRunLocalOptimizer:
    # _run_local_optimizer now lives in message_handler_helpers; patch SPLQueryOptimizer there.
    @patch("chat_app.message_handler_helpers.SPLQueryOptimizer")
    def test_returns_result(self, mock_cls, mh):
        mock_cls.optimize.return_value = MagicMock(optimized_query="opt")
        assert mh._run_local_optimizer("q").optimized_query == "opt"

    @patch("chat_app.message_handler_helpers.SPLQueryOptimizer")
    def test_returns_none(self, mock_cls, mh):
        mock_cls.optimize.return_value = None
        assert mh._run_local_optimizer("q") is None


# =========================================================================
# 4. retrieve_context
# =========================================================================

class TestRetrieveContext:
    # retrieve_context now lives in pipeline_retrieval; patch dependencies there.
    @pytest.mark.asyncio
    @patch("chat_app.pipeline_retrieval.detect_config_context", return_value=([], None))
    @patch("chat_app.pipeline_retrieval.route_query")
    @patch("chat_app.pipeline_retrieval.get_cached_vector_results", new_callable=AsyncMock)
    @patch("chat_app.pipeline_retrieval.record_cache_hit")
    @patch("chat_app.pipeline_retrieval.cl")
    async def test_cache_hit(self, mock_cl, mock_rh, mock_gc, mock_rq, mock_dc,
                              mock_context, sample_memory_chunks, mh):
        mock_gc.return_value = sample_memory_chunks
        mock_rq.return_value = MagicMock(is_compound=False, sub_queries=[], intent="general_qa")
        mock_cl.make_async = lambda f: AsyncMock(return_value=sample_memory_chunks)

        _, _, _, _, source, _, _ = await mh.retrieve_context(
            "q", mock_context, {"search_depth": "5"}, False, "general",
            mock_context.map_source_to_url, "/s", "/d", "/ss",
        )
        assert source == "cache"
        mock_rh.assert_called_once()

    @pytest.mark.asyncio
    @patch("chat_app.pipeline_retrieval.detect_config_context", return_value=([], None))
    @patch("chat_app.pipeline_retrieval.route_query")
    @patch("chat_app.pipeline_retrieval.get_cached_vector_results", new_callable=AsyncMock, return_value=None)
    @patch("chat_app.pipeline_retrieval.record_cache_miss")
    @patch("chat_app.pipeline_retrieval.cache_vector_results", new_callable=AsyncMock)
    @patch("chat_app.pipeline_retrieval.cl")
    async def test_cache_miss(self, mock_cl, mock_cv, mock_rm, mock_gc,
                               mock_rq, mock_dc, mock_context, mh):
        mock_rq.return_value = MagicMock(is_compound=False, sub_queries=[], intent="general_qa")
        mock_cl.make_async = lambda f: AsyncMock(return_value=[])
        await mh.retrieve_context(
            "q", mock_context, {"search_depth": "5"}, False, "general",
            mock_context.map_source_to_url, "/s", "/d", "/ss",
        )
        assert mock_rm.called

    @pytest.mark.asyncio
    @patch("chat_app.pipeline_retrieval.detect_config_context", return_value=(["props.conf"], "syslog"))
    @patch("chat_app.pipeline_retrieval.route_query")
    @patch("chat_app.pipeline_retrieval.get_cached_vector_results", new_callable=AsyncMock, return_value=None)
    @patch("chat_app.pipeline_retrieval.record_cache_miss")
    @patch("chat_app.pipeline_retrieval.find_local_spec_file", return_value="/s/props.conf.spec")
    @patch("chat_app.pipeline_retrieval.extract_spec_stanzas", return_value=["[syslog]\nTF=%b"])
    @patch("chat_app.pipeline_retrieval.cache_vector_results", new_callable=AsyncMock)
    @patch("chat_app.pipeline_retrieval.cl")
    async def test_config_context(self, mock_cl, mock_cv, mock_es, mock_fs,
                                   mock_rm, mock_gc, mock_rq, mock_dc,
                                   mock_context, mh):
        mock_rq.return_value = MagicMock(is_compound=False, sub_queries=[], intent="config")
        mock_cl.make_async = lambda f: AsyncMock(return_value=[])
        _, spec, *_ = await mh.retrieve_context(
            "props.conf syslog", mock_context, {"search_depth": "5"}, False, "general",
            mock_context.map_source_to_url, "/s", "/d", "/ss",
        )
        assert len(spec) > 0


# =========================================================================
# 5. build_llm_context
# =========================================================================

class TestBuildLlmContext:
    # build_llm_context now lives in pipeline_response; patch dependencies there.
    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.score_and_filter_chunks", return_value=[])
    @patch("chat_app.pipeline_response.scrub_lines", side_effect=lambda x: x)
    @patch("chat_app.pipeline_response.filter_references", side_effect=lambda r, _: r)
    @patch("chat_app.pipeline_response.get_recent_global_notes_raw", new_callable=AsyncMock, return_value=[])
    @patch("chat_app.pipeline_response.get_recent_query_preferences", new_callable=AsyncMock, return_value=[])
    @patch("chat_app.pipeline_response.get_recent_interactions", new_callable=AsyncMock, return_value=[])
    async def test_no_context_fallback(self, mock_ri, mock_rp, mock_rn,
                                          mock_fr, mock_sl, mock_sf, mh):
        plan = MagicMock(intent="general_qa", optimizer_action=None)
        ctx, *_ = await mh.build_llm_context(
            "q", [], [], [], {}, AsyncMock(), "u", "sys",
            False, None, False, lambda x: None, lambda: [],
            plan=plan, conf_files=[],
        )
        # With registry capabilities injection, fallback always has context
        assert "Available Capabilities" in ctx or "No specific context" in ctx

    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.score_and_filter_chunks")
    @patch("chat_app.pipeline_response.format_chunk_with_metadata", return_value="fc")
    @patch("chat_app.pipeline_response.scrub_lines", side_effect=lambda x: x)
    @patch("chat_app.pipeline_response.filter_references", side_effect=lambda r, _: r)
    @patch("chat_app.pipeline_response.get_recent_global_notes_raw", new_callable=AsyncMock, return_value=[])
    @patch("chat_app.pipeline_response.get_recent_query_preferences", new_callable=AsyncMock, return_value=[])
    @patch("chat_app.pipeline_response.get_recent_interactions", new_callable=AsyncMock, return_value=[])
    async def test_kb_section(self, mock_h, mock_l, mock_f, mock_fr, mock_s,
                               mock_fmt, mock_sc, sample_memory_chunks,
                               sample_scored_chunks, mh):
        mock_sc.return_value = sample_scored_chunks
        plan = MagicMock(intent="general_qa", optimizer_action=None)
        ctx, *_ = await mh.build_llm_context(
            "stats", sample_memory_chunks, [], [], {}, AsyncMock(), "u", "sys",
            False, None, False, lambda x: None, lambda: [],
            plan=plan, conf_files=[],
        )
        assert "Knowledge Base" in ctx

    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.score_and_filter_chunks", return_value=[])
    @patch("chat_app.pipeline_response.scrub_lines", side_effect=lambda x: x)
    @patch("chat_app.pipeline_response.filter_references", side_effect=lambda r, _: r)
    @patch("chat_app.pipeline_response.get_recent_global_notes_raw", new_callable=AsyncMock, return_value=[])
    @patch("chat_app.pipeline_response.get_recent_query_preferences", new_callable=AsyncMock, return_value=[])
    @patch("chat_app.pipeline_response.get_recent_interactions", new_callable=AsyncMock, return_value=[])
    async def test_spl_expertise_fallback(self, mock_ri, mock_rp, mock_rn,
                                             mock_fr, mock_sl, mock_sf, mh):
        plan = MagicMock(intent="spl_generation", optimizer_action=None)
        ctx, *_ = await mh.build_llm_context(
            "write stats query", [], [], [], {}, AsyncMock(), "u", "sys",
            False, None, False, lambda x: None, lambda: [],
            plan=plan, conf_files=[],
        )
        # SPL fallback now coexists with capabilities context
        assert "deep expertise in SPL" in ctx or "Available Capabilities" in ctx


# =========================================================================
# 6. generate_llm_response
# =========================================================================

class TestGenerateLlmResponse:
    # generate_llm_response now lives in pipeline_response; patch dependencies there.
    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.get_metrics")
    @patch("chat_app.pipeline_response.generate_response", new_callable=AsyncMock, return_value="answer")
    async def test_normal_path(self, mock_gen, mock_gm, mh):
        m = MagicMock()
        m.timer.return_value.__enter__ = MagicMock()
        m.timer.return_value.__exit__ = MagicMock()
        mock_gm.return_value = m
        plan = MagicMock(optimizer_action=None)
        r = await mh.generate_llm_response("q", "c", MagicMock(), MagicMock(), {}, "p", "p", None, None, None, plan)
        assert r == "answer"

    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.get_metrics")
    @patch("chat_app.pipeline_response._format_optimizer_bypass_response")
    async def test_optimizer_bypass(self, mock_fb, mock_gm, mh):
        mock_fb.return_value = "Optimized: TERM"
        mock_gm.return_value = MagicMock()
        plan = MagicMock(optimizer_action="optimize", extracted_query="q")
        r = await mh.generate_llm_response("opt", "c", MagicMock(), MagicMock(), {}, "p", "p", None, None, MagicMock(), plan)
        assert "Optimized" in r

    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.get_metrics")
    @patch("chat_app.pipeline_response.generate_response", new_callable=AsyncMock, return_value=None)
    async def test_none_fallback(self, mock_gen, mock_gm, mh):
        m = MagicMock()
        m.timer.return_value.__enter__ = MagicMock()
        m.timer.return_value.__exit__ = MagicMock()
        mock_gm.return_value = m
        plan = MagicMock(optimizer_action=None)
        r = await mh.generate_llm_response("q", "c", MagicMock(), MagicMock(), {}, "p", "p", None, None, None, plan)
        assert "unavailable" in r.lower()

    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.get_metrics")
    @patch("chat_app.pipeline_response.generate_response", new_callable=AsyncMock, return_value="")
    async def test_empty_fallback(self, mock_gen, mock_gm, mh):
        m = MagicMock()
        m.timer.return_value.__enter__ = MagicMock()
        m.timer.return_value.__exit__ = MagicMock()
        mock_gm.return_value = m
        plan = MagicMock(optimizer_action=None)
        r = await mh.generate_llm_response("q", "c", MagicMock(), MagicMock(), {}, "p", "p", None, None, None, plan)
        assert "unavailable" in r.lower()

    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.get_metrics")
    @patch("chat_app.pipeline_response._format_optimizer_bypass_response", return_value=None)
    @patch("chat_app.pipeline_response.generate_response", new_callable=AsyncMock, return_value="LLM")
    async def test_bypass_none_falls_to_llm(self, mock_gen, mock_fb, mock_gm, mh):
        m = MagicMock()
        m.timer.return_value.__enter__ = MagicMock()
        m.timer.return_value.__exit__ = MagicMock()
        mock_gm.return_value = m
        plan = MagicMock(optimizer_action="optimize", extracted_query="q")
        r = await mh.generate_llm_response("q", "c", MagicMock(), MagicMock(), {}, "p", "p", None, None, MagicMock(), plan)
        assert r == "LLM"


# =========================================================================
# 7. build_final_response
# =========================================================================

class TestBuildFinalResponse:
    # build_final_response now lives in pipeline_response; patch dependencies there.
    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.compute_confidence", return_value="HIGH")
    @patch("chat_app.pipeline_response.build_sources_section", return_value="")
    @patch("chat_app.pipeline_response.classify_references", return_value=[])
    @patch("chat_app.pipeline_response.generate_followups", new_callable=AsyncMock, return_value=[])
    @patch("chat_app.pipeline_response.cl")
    async def test_confidence(self, cl, fu, cr, bs, cc, sample_scored_chunks, sample_memory_chunks, mh):
        cl.Action = MagicMock()
        r, _ = await mh.build_final_response("a", [], ["r"], sample_scored_chunks, sample_memory_chunks, "chromadb", {}, "q", False)
        assert "HIGH" in r

    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.compute_confidence", return_value="MED")
    @patch("chat_app.pipeline_response.build_sources_section", return_value="Sources")
    @patch("chat_app.pipeline_response.classify_references", return_value=[])
    @patch("chat_app.pipeline_response.generate_followups", new_callable=AsyncMock, return_value=["Follow?"])
    @patch("chat_app.pipeline_response.cl")
    async def test_followups(self, cl, fu, cr, bs, cc, sample_scored_chunks, sample_memory_chunks, mh):
        cl.Action = MagicMock()
        _, actions = await mh.build_final_response("a", [], [], sample_scored_chunks, sample_memory_chunks, "chromadb", {}, "q", False)
        cl.Action.assert_called()

    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.compute_confidence", return_value="LOW")
    @patch("chat_app.pipeline_response.build_sources_section", return_value="")
    @patch("chat_app.pipeline_response.classify_references", return_value=[("doc", "http://f.pdf", "f.pdf")])
    @patch("chat_app.pipeline_response.generate_followups", new_callable=AsyncMock, return_value=[])
    @patch("chat_app.pipeline_response.cl")
    async def test_references(self, cl, fu, cr, bs, cc, mh):
        cl.Action = MagicMock()
        r, _ = await mh.build_final_response("a", [], ["http://f.pdf"], [], [], "chromadb", {"show_sources": True}, "q", False)
        assert "References" in r

    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.compute_confidence", return_value="C")
    @patch("chat_app.pipeline_response.build_sources_section", return_value="")
    @patch("chat_app.pipeline_response.classify_references", return_value=[])
    @patch("chat_app.pipeline_response.generate_followups", new_callable=AsyncMock, return_value=[])
    @patch("chat_app.pipeline_response.cl")
    async def test_cached_label(self, cl, fu, cr, bs, cc, mh):
        cl.Action = MagicMock()
        r, _ = await mh.build_final_response("a", [], [], [], [], "cache", {}, "q", False)
        assert "Cached" in r

    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.compute_confidence", return_value="H")
    @patch("chat_app.pipeline_response.build_sources_section", return_value="")
    @patch("chat_app.pipeline_response.classify_references", return_value=[])
    @patch("chat_app.pipeline_response.generate_followups", new_callable=AsyncMock, return_value=[])
    @patch("chat_app.pipeline_response.cl")
    async def test_chunk_count(self, cl, fu, cr, bs, cc, sample_memory_chunks, mh):
        cl.Action = MagicMock()
        r, _ = await mh.build_final_response("a", [], [], [], sample_memory_chunks, "chromadb", {}, "q", False)
        assert "ChromaDB: 3 chunks" in r


# =========================================================================
# 8. _handle_direct_intent
# =========================================================================

class TestHandleDirectIntent:
    # Note: _handle_direct_intent now lives in message_handler_helpers.
    # handle_intent is lazily imported from chat_app.intent_handler inside the
    # function body, so patch that module directly.
    # cl is a module-level import in message_handler_helpers, so patch there.
    @pytest.mark.asyncio
    @patch("chat_app.intent_handler.handle_intent", new_callable=AsyncMock, return_value=False)
    @patch("chat_app.message_handler_helpers.cl")
    async def test_search_suggestion(self, cl, hi, mock_context, mh):
        cl.Message.return_value = MagicMock(send=AsyncMock())
        plan = MagicMock(intent="search_suggestion")
        with patch("shared.spl_robust_analyzer.suggest_search", return_value="| stats count"):
            assert await mh._handle_direct_intent(plan, "suggest", mock_context, "general") is True

    @pytest.mark.asyncio
    @patch("chat_app.intent_handler.handle_intent", new_callable=AsyncMock, return_value=True)
    async def test_intent_handler_catches(self, hi, mock_context, mh):
        assert await mh._handle_direct_intent(MagicMock(intent="chk"), "c", mock_context, "general") is True

    @pytest.mark.asyncio
    @patch("chat_app.intent_handler.handle_intent", new_callable=AsyncMock, return_value=False)
    @patch("chat_app.message_handler_helpers.record_query")
    @patch("chat_app.message_handler_helpers.cl")
    async def test_meta_question(self, cl, rq, hi, mock_context, mh):
        plan = MagicMock(intent="meta_question", skip_retrieval=True, clarification_question=None)
        async def astream(d):
            for t in ["H", "i"]:
                yield t
        mock_context.chain.astream = astream
        cl.Message.return_value = MagicMock(send=AsyncMock(), stream_token=AsyncMock(), update=AsyncMock(), content="")
        cl.user_session = MagicMock()
        assert await mh._handle_direct_intent(plan, "who?", mock_context, "general") is True

    @pytest.mark.asyncio
    @patch("chat_app.intent_handler.handle_intent", new_callable=AsyncMock, return_value=False)
    @patch("chat_app.message_handler_helpers.record_query")
    @patch("chat_app.message_handler_helpers.cl")
    async def test_clarification(self, cl, rq, hi, mock_context, mh):
        plan = MagicMock(intent="clarification", skip_retrieval=False, clarification_question="Which?")
        cl.Message.return_value = MagicMock(send=AsyncMock())
        assert await mh._handle_direct_intent(plan, "it", mock_context, "general") is True

    @pytest.mark.asyncio
    @patch("chat_app.intent_handler.handle_intent", new_callable=AsyncMock, return_value=False)
    async def test_general_qa_falls_through(self, hi, mock_context, mh):
        plan = MagicMock(intent="general_qa", skip_retrieval=False, clarification_question=None)
        assert await mh._handle_direct_intent(plan, "what?", mock_context, "general") is False

    @pytest.mark.asyncio
    @patch("chat_app.intent_handler.handle_intent", new_callable=AsyncMock, return_value=False)
    async def test_clarification_no_question(self, hi, mock_context, mh):
        plan = MagicMock(intent="clarification", skip_retrieval=False, clarification_question=None)
        assert await mh._handle_direct_intent(plan, "vague", mock_context, "general") is False

    @pytest.mark.asyncio
    @patch("chat_app.intent_handler.handle_intent", new_callable=AsyncMock, return_value=False)
    async def test_meta_no_skip(self, hi, mock_context, mh):
        plan = MagicMock(intent="meta_question", skip_retrieval=False, clarification_question=None)
        assert await mh._handle_direct_intent(plan, "what?", mock_context, "general") is False


# =========================================================================
# 9. on_message integration
# =========================================================================

class TestOnMessage:
    @pytest.mark.asyncio
    async def test_meta_command_short_circuits(self, mock_context, mh):
        cl, lu, cm = _make_cl_mock(), _make_logging_utils_mock(), _make_conv_mem_mock()
        cl.user_session.get.side_effect = lambda k, d=None: {"chat_profile": "g", "settings": {}}.get(k, d)
        msg = MagicMock(content="/help")
        extras = {"chat_app.message_handler.handle_meta_commands": {"return_value": True}}
        stack, applied = _on_message_patches(cl, lu, cm, extras)
        with stack:
            await mh.on_message(msg, mock_context)
            applied["chat_app.message_handler.handle_meta_commands"].assert_called_once()

    @pytest.mark.asyncio
    async def test_direct_intent_short_circuits(self, mock_context, mh):
        cl, lu, cm = _make_cl_mock(), _make_logging_utils_mock(), _make_conv_mem_mock()
        cl.user_session.get.side_effect = lambda k, d=None: {"chat_profile": "g", "settings": {}}.get(k, d)
        msg = MagicMock(content="who are you?")
        plan = MagicMock(intent="meta_question", skip_retrieval=True, is_compound=False,
                         sub_queries=[], optimizer_action=None)
        extras = {
            "chat_app.message_handler.handle_meta_commands": {"return_value": False},
            "chat_app.message_handler.extract_message_metadata": MagicMock(return_value=([], {})),
            "chat_app.message_handler.route_query": MagicMock(return_value=plan),
            "chat_app.message_handler._handle_direct_intent": {"return_value": True},
        }
        stack, applied = _on_message_patches(cl, lu, cm, extras)
        with stack:
            await mh.on_message(msg, mock_context)
            applied["chat_app.message_handler._handle_direct_intent"].assert_called_once()

    @pytest.mark.asyncio
    async def test_pronoun_heavy(self, mock_context, mh):
        cl, lu, cm = _make_cl_mock(), _make_logging_utils_mock(), _make_conv_mem_mock()
        cl.user_session.get.side_effect = lambda k, d=None: {"chat_profile": "g", "settings": {}}.get(k, d)
        msg = MagicMock(content="optimize that")
        stack, _ = _on_message_patches(cl, lu, cm)
        with stack:
            await mh.on_message(msg, mock_context)
        assert cl.Message.called

    @pytest.mark.asyncio
    async def test_empty_message(self, mock_context, mh):
        cl, lu, cm = _make_cl_mock(), _make_logging_utils_mock(), _make_conv_mem_mock()
        cl.user_session.get.side_effect = lambda k, d=None: {"chat_profile": "g", "settings": {}}.get(k, d)
        msg = MagicMock(content="")
        plan = MagicMock(intent="general_qa", is_compound=False, sub_queries=[], optimizer_action=None)
        extras = {
            "chat_app.message_handler.handle_meta_commands": {"return_value": False},
            "chat_app.message_handler.extract_message_metadata": MagicMock(return_value=([], {})),
            "chat_app.message_handler.route_query": MagicMock(return_value=plan),
            "chat_app.message_handler._handle_direct_intent": {"return_value": True},
        }
        stack, _ = _on_message_patches(cl, lu, cm, extras)
        with stack:
            await mh.on_message(msg, mock_context)

    @pytest.mark.asyncio
    async def test_none_message(self, mock_context, mh):
        cl, lu, cm = _make_cl_mock(), _make_logging_utils_mock(), _make_conv_mem_mock()
        cl.user_session.get.side_effect = lambda k, d=None: {"chat_profile": "g", "settings": {}}.get(k, d)
        msg = MagicMock(content=None)
        plan = MagicMock(intent="general_qa", is_compound=False, sub_queries=[], optimizer_action=None)
        extras = {
            "chat_app.message_handler.handle_meta_commands": {"return_value": False},
            "chat_app.message_handler.extract_message_metadata": MagicMock(return_value=([], {})),
            "chat_app.message_handler.route_query": MagicMock(return_value=plan),
            "chat_app.message_handler._handle_direct_intent": {"return_value": True},
        }
        stack, _ = _on_message_patches(cl, lu, cm, extras)
        with stack:
            await mh.on_message(msg, mock_context)

    @pytest.mark.asyncio
    async def test_orchestration_clarification_hard_pause(self, mock_context, mh):
        """Regression: when orch_result.clarification_needed is True the pipeline must
        send the clarification message and return immediately — build_llm_context and
        generate_llm_response must NOT be called (HARD PAUSE)."""
        from chat_app.orchestration_strategies import OrchestrationResult

        cl, lu, cm = _make_cl_mock(), _make_logging_utils_mock(), _make_conv_mem_mock()
        cl.user_session.get.side_effect = lambda k, d=None: {"chat_profile": "g", "settings": {}}.get(k, d)
        msg = MagicMock(content="show me errors")

        plan = MagicMock(
            intent="spl_generation",
            is_compound=False,
            sub_queries=[],
            optimizer_action=None,
            skip_retrieval=False,
            clarification_question=None,
            confidence=0.5,  # must be a float — adaptive_rag uses numeric comparison
        )

        # Orchestration result requesting clarification — 7-tuple from retrieve_context
        # (memory_chunks, local_spec_content, local_spec_refs, detected_profile,
        #  chroma_source, has_conf_context, conf_files)
        retrieve_return = ([], [], [], "general", "chromadb", False, [])

        clarification_orch_result = OrchestrationResult(
            strategy_used="adaptive",
            clarification_needed=True,
            clarification_questions=["Which index?", "What time range?"],
            clarification_agent="spl_engineer",
        )

        extras = {
            "chat_app.message_handler.handle_meta_commands": {"return_value": False},
            "chat_app.message_handler.extract_message_metadata": MagicMock(return_value=([], {})),
            "chat_app.message_handler.route_query": MagicMock(return_value=plan),
            "chat_app.message_handler._handle_direct_intent": {"return_value": False},
            "chat_app.message_handler.retrieve_context": {"return_value": retrieve_return},
        }
        stack, _ = _on_message_patches(cl, lu, cm, extras)
        with stack:
            # execute_orchestration is imported inline — patch at source module level
            with patch(
                "chat_app.orchestration_strategies.execute_orchestration",
                new_callable=AsyncMock,
                return_value=clarification_orch_result,
            ), patch(
                "chat_app.message_handler.build_llm_context",
                new_callable=AsyncMock,
            ) as patched_build_ctx, patch(
                "chat_app.message_handler.generate_llm_response",
                new_callable=AsyncMock,
            ) as patched_gen_llm:
                await mh.on_message(msg, mock_context)

                # Clarification message must have been sent to the user
                assert cl.Message.called, "Expected cl.Message() to be called with clarification text"
                # Retrieve the content kwarg from the most recent cl.Message() call
                last_call = cl.Message.call_args
                sent_content = (
                    last_call[1].get("content", "")
                    if last_call[1]
                    else (last_call[0][0] if last_call[0] else "")
                )
                assert (
                    "clarif" in sent_content.lower()
                    or "information" in sent_content.lower()
                    or "Which index" in sent_content
                ), f"Clarification message not sent to user. Got: {sent_content!r}"

                # HARD PAUSE guarantee: neither context building nor LLM generation must run
                patched_build_ctx.assert_not_called()
                patched_gen_llm.assert_not_called()


# =========================================================================
# 10. Context hash
# =========================================================================

class TestContextHash:
    # generate_llm_response now lives in pipeline_response; patch dependencies there.
    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.get_metrics")
    @patch("chat_app.pipeline_response.generate_response", new_callable=AsyncMock, return_value="a")
    async def test_hash_computed(self, mg, gm, mh):
        m = MagicMock()
        m.timer.return_value.__enter__ = MagicMock()
        m.timer.return_value.__exit__ = MagicMock()
        gm.return_value = m
        plan = MagicMock(optimizer_action=None)
        ctx = "some context"
        await mh.generate_llm_response("q", ctx, MagicMock(), MagicMock(), {}, "p", "p", None, None, None, plan)
        assert mg.call_args.args[4] == hashlib.sha256(ctx.encode()).hexdigest()

    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.get_metrics")
    @patch("chat_app.pipeline_response.generate_response", new_callable=AsyncMock, return_value="a")
    async def test_different_hashes(self, mg, gm, mh):
        m = MagicMock()
        m.timer.return_value.__enter__ = MagicMock()
        m.timer.return_value.__exit__ = MagicMock()
        gm.return_value = m
        plan = MagicMock(optimizer_action=None)
        await mh.generate_llm_response("q", "A", MagicMock(), MagicMock(), {}, "p", "p", None, None, None, plan)
        h1 = mg.call_args.args[4]
        await mh.generate_llm_response("q", "B", MagicMock(), MagicMock(), {}, "p", "p", None, None, None, plan)
        h2 = mg.call_args.args[4]
        assert h1 != h2


# =========================================================================
# 11. Edge cases for build_final_response
# =========================================================================

class TestBuildFinalEdgeCases:
    # build_final_response now lives in pipeline_response; patch dependencies there.
    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.compute_confidence", return_value="M")
    @patch("chat_app.pipeline_response.build_sources_section", return_value="")
    @patch("chat_app.pipeline_response.classify_references", return_value=[])
    @patch("chat_app.pipeline_response.generate_followups", new_callable=AsyncMock, return_value=[])
    @patch("chat_app.pipeline_response.cl")
    async def test_empty_text(self, cl, fu, cr, bs, cc, mh):
        cl.Action = MagicMock()
        r, _ = await mh.build_final_response("", [], [], [], [], "chromadb", {}, "", False)
        assert "Confidence" in r

    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.compute_confidence", return_value="H")
    @patch("chat_app.pipeline_response.build_sources_section", return_value="")
    @patch("chat_app.pipeline_response.classify_references", return_value=[])
    @patch("chat_app.pipeline_response.generate_followups", new_callable=AsyncMock, return_value=[])
    @patch("chat_app.pipeline_response.cl")
    async def test_unicode(self, cl, fu, cr, bs, cc, mh):
        cl.Action = MagicMock()
        r, _ = await mh.build_final_response("日本語テスト", [], [], [], [], "chromadb", {}, "日", False)
        assert "日本語" in r

    @pytest.mark.asyncio
    @patch("chat_app.pipeline_response.compute_confidence", return_value="M")
    @patch("chat_app.pipeline_response.build_sources_section", return_value="")
    @patch("chat_app.pipeline_response.classify_references", return_value=[])
    @patch("chat_app.pipeline_response.generate_followups", new_callable=AsyncMock, return_value=[])
    @patch("chat_app.pipeline_response.cl")
    async def test_very_long(self, cl, fu, cr, bs, cc, mh):
        cl.Action = MagicMock()
        r, _ = await mh.build_final_response("w " * 10000, [], [], [], [], "chromadb", {}, "q", False)
        assert len(r) > 10000


# =========================================================================
# 12. Pronoun resolution
# =========================================================================

class TestPronounResolution:
    @pytest.mark.asyncio
    async def test_resolved_query(self, mock_context, mh):
        cl, lu, cm = _make_cl_mock(), _make_logging_utils_mock(), _make_conv_mem_mock(lambda x: "explain stats")
        cl.user_session.get.side_effect = lambda k, d=None: {"chat_profile": "g", "settings": {}}.get(k, d)
        msg = MagicMock(content="explain it")
        extras = {"chat_app.message_handler.handle_meta_commands": {"return_value": True}}
        stack, applied = _on_message_patches(cl, lu, cm, extras)
        with stack:
            await mh.on_message(msg, mock_context)
            applied["chat_app.message_handler.handle_meta_commands"].assert_called_once()

    @pytest.mark.asyncio
    async def test_resolution_failure(self, mock_context, mh):
        cl, lu, cm = _make_cl_mock(), _make_logging_utils_mock(), _make_conv_mem_mock()
        cm.resolve_references = MagicMock(side_effect=RuntimeError("fail"))
        cl.user_session.get.side_effect = lambda k, d=None: {"chat_profile": "g", "settings": {}}.get(k, d)
        msg = MagicMock(content="how does stats work?")
        extras = {"chat_app.message_handler.handle_meta_commands": {"return_value": True}}
        stack, _ = _on_message_patches(cl, lu, cm, extras)
        with stack:
            await mh.on_message(msg, mock_context)
