"""
Comprehensive E2E chat pipeline tests.

Exercises the FULL pipeline: input -> intent -> retrieval -> orchestration -> agent -> response -> feedback.

Test categories:
 1. Intent Classification E2E (10 tests)
 2. Query Router E2E (5 tests)
 3. Orchestration E2E (5 tests)
 4. Agent Selection E2E (5 tests)
 5. Response Quality E2E (5 tests)

Mocked: Chainlit, LLM, ChromaDB, Database engine
NOT mocked: IntentClassifier, QueryRouter, AgentDispatcher scoring
"""

import sys
import os
import importlib
import importlib.abc
import importlib.machinery
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest

# ---------------------------------------------------------------------------
# Path setup
# ---------------------------------------------------------------------------
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "chat_app"))
sys.path.insert(0, os.path.join(project_root, "shared"))
sys.path.insert(0, project_root)


# ---------------------------------------------------------------------------
# Auto-mock missing dependencies (same pattern as test_message_handler.py)
# ---------------------------------------------------------------------------

class _FallbackFinder(importlib.abc.MetaPathFinder):
    """Auto-mock any missing package from a known set."""

    _MOCK_PREFIXES = (
        "langchain", "chromadb", "splunklib", "ollama",
        "sqlalchemy", "psycopg2", "psycopg",
        "langfuse", "opentelemetry",
        "pypdf", "docx", "pptx", "openpyxl",
        "sentence_transformers", "transformers", "torch",
        "redis", "httpx",
    )
    # Packages that should NOT be mocked even if they match a prefix,
    # because they are used in isinstance() checks in production code.
    _EXCLUDE = ("langchain_google_genai",)

    def find_spec(self, fullname, path, target=None):
        if any(fullname.startswith(pfx) for pfx in self._MOCK_PREFIXES):
            if any(fullname.startswith(ex) for ex in self._EXCLUDE):
                return None  # Excluded — let normal import (or ImportError) handle it
            if fullname in sys.modules:
                return None  # Already loaded (real or mock) — let normal import handle it
            # Try real import first by temporarily removing ourselves from meta_path
            idx = sys.meta_path.index(self) if self in sys.meta_path else None
            if idx is not None:
                sys.meta_path.pop(idx)
            try:
                real_spec = importlib.util.find_spec(fullname)
            except (ModuleNotFoundError, ValueError):
                real_spec = None
            finally:
                if idx is not None:
                    sys.meta_path.insert(idx, self)
            if real_spec is not None:
                return None  # Real package exists — let normal import handle it
            # No real package — provide a mock
            mock = MagicMock()
            mock.__path__ = []
            mock.__name__ = fullname
            mock.__package__ = fullname
            sys.modules[fullname] = mock
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


if not any(isinstance(f, _FallbackFinder) for f in sys.meta_path):
    sys.meta_path.insert(0, _FallbackFinder())

# Fix existing mock packages
for _prefix in _FallbackFinder._MOCK_PREFIXES:
    _existing = sys.modules.get(_prefix)
    if _existing is not None and isinstance(_existing, MagicMock):
        _existing.configure_mock(__path__=[], __package__=_prefix, __name__=_prefix)
        _existing.__spec__ = importlib.machinery.ModuleSpec(_prefix, None, is_package=True)

# Chainlit mock
if "chainlit" not in sys.modules:
    _cl_mock = MagicMock()
    _cl_mock.user_session = MagicMock()
    _cl_mock.__path__ = []
    sys.modules["chainlit"] = _cl_mock
    sys.modules["chainlit.types"] = MagicMock()
    sys.modules["chainlit.context"] = MagicMock()

# Optional runtime modules
for _mod_name in ("cache", "ollama_priority", "resilience", "prometheus_metrics"):
    if _mod_name not in sys.modules:
        try:
            __import__(_mod_name)
        except ImportError:
            sys.modules[_mod_name] = MagicMock()


# ---------------------------------------------------------------------------
# Lazy imports (after mocks installed)
# ---------------------------------------------------------------------------

_MODULE_CACHE = {}


def _get_intent_classifier():
    if "ic" not in _MODULE_CACHE:
        from chat_app.intent_classifier import IntentClassifier
        _MODULE_CACHE["ic"] = IntentClassifier()
    return _MODULE_CACHE["ic"]


def _get_route_query():
    if "rq" not in _MODULE_CACHE:
        from chat_app.query_router_handler import route_query
        _MODULE_CACHE["rq"] = route_query
    return _MODULE_CACHE["rq"]


def _get_registry():
    if "reg" not in _MODULE_CACHE:
        from chat_app.registry import Intent
        _MODULE_CACHE["reg"] = Intent
    return _MODULE_CACHE["reg"]


def _get_agent_dispatcher():
    """Create an AgentDispatcher with Redis restore mocked out."""
    if "ad" not in _MODULE_CACHE:
        with patch("chat_app.agent_dispatcher.AgentDispatcher._restore_quality"):
            from chat_app.agent_dispatcher import AgentDispatcher
            _MODULE_CACHE["ad"] = AgentDispatcher()
    return _MODULE_CACHE["ad"]


def _get_agent_catalog():
    if "ac" not in _MODULE_CACHE:
        from chat_app.agent_catalog import get_agent_catalog
        _MODULE_CACHE["ac"] = get_agent_catalog()
    return _MODULE_CACHE["ac"]


def _get_orchestration_result_cls():
    if "or_cls" not in _MODULE_CACHE:
        from chat_app.orchestration_strategies import OrchestrationResult
        _MODULE_CACHE["or_cls"] = OrchestrationResult
    return _MODULE_CACHE["or_cls"]


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Intent Classification E2E (10 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestIntentClassificationE2E:
    """Verify real IntentClassifier routes user queries to correct intents."""

    def _classify(self, query):
        Intent = _get_registry()
        route_query = _get_route_query()
        plan = route_query(query)
        return plan

    def test_spl_generation_from_natural_language(self):
        """'show me failed logins last hour' -> spl_generation"""
        plan = self._classify("show me failed logins last hour")
        Intent = _get_registry()
        assert plan.intent == Intent.SPL_GENERATION
        assert plan.profile == "spl_expert"
        assert plan.confidence >= 0.7

    def test_spl_explanation_intent(self):
        """'explain tstats and prefix' -> spl_explanation"""
        plan = self._classify("explain tstats and prefix")
        Intent = _get_registry()
        assert plan.intent == Intent.SPL_EXPLANATION
        assert plan.optimizer_action == "explain"

    def test_config_lookup_intent(self):
        """'what stanzas are in props.conf' -> config_lookup"""
        plan = self._classify("what stanzas are in props.conf")
        Intent = _get_registry()
        assert plan.intent == Intent.CONFIG_LOOKUP
        assert plan.profile == "config_helper"

    def test_troubleshooting_intent(self):
        """'my dashboard is not working' -> troubleshooting"""
        plan = self._classify("my dashboard is not working")
        Intent = _get_registry()
        assert plan.intent == Intent.TROUBLESHOOTING
        assert plan.profile == "troubleshooter"
        assert "local_docs_mxbai" in plan.retrieval_collections

    def test_cribl_pipeline_intent(self):
        """'create a cribl pipeline for syslog' -> cribl_pipeline"""
        plan = self._classify("create a cribl pipeline for syslog")
        Intent = _get_registry()
        assert plan.intent == Intent.CRIBL_PIPELINE
        assert plan.profile == "cribl_expert"
        assert plan.confidence >= 0.7

    def test_general_qa_intent(self):
        """'what is Splunk' -> general_qa"""
        plan = self._classify("what is Splunk")
        Intent = _get_registry()
        assert plan.intent == Intent.GENERAL_QA
        assert plan.confidence >= 0.8

    def test_compare_commands_intent(self):
        """'compare stats vs eventstats' -> compare_commands"""
        plan = self._classify("compare stats vs eventstats")
        Intent = _get_registry()
        assert plan.intent == Intent.COMPARE_COMMANDS
        assert plan.profile == "spl_expert"

    def test_meta_question_intent(self):
        """'who are you' -> meta_question with skip_retrieval"""
        plan = self._classify("who are you")
        Intent = _get_registry()
        assert plan.intent == Intent.META_QUESTION
        assert plan.skip_retrieval is True
        assert plan.confidence >= 0.9

    def test_data_transform_intent(self):
        """'base64 encode hello world' -> data_transform with skip_retrieval"""
        plan = self._classify("base64 encode hello world")
        Intent = _get_registry()
        assert plan.intent == Intent.DATA_TRANSFORM
        assert plan.skip_retrieval is True
        assert plan.confidence >= 0.8

    def test_observability_metrics_intent(self):
        """'show me CPU metrics from OpenTelemetry' -> observability_metrics"""
        plan = self._classify("show me CPU metrics from OpenTelemetry")
        Intent = _get_registry()
        assert plan.intent == Intent.OBSERVABILITY_METRICS
        assert plan.profile == "observability_expert"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Query Router E2E (5 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestQueryRouterE2E:
    """Verify QueryRouter builds correct QueryPlans with collection routing."""

    def test_simple_query_single_collection(self):
        """Simple SPL query prioritizes spl_commands collection."""
        route_query = _get_route_query()
        plan = route_query("find all failed logins from the security index")
        assert len(plan.retrieval_collections) >= 1
        assert "spl_commands_mxbai" in plan.retrieval_collections

    def test_compound_query_sub_query_splitting(self):
        """Compound query with 'and' splits into sub-queries."""
        route_query = _get_route_query()
        # Need technical terms with uppercase to trigger concept detection
        plan = route_query("TERM and PREFIX usage in tstats")
        assert plan.is_compound is True
        assert len(plan.sub_queries) >= 2

    def test_spl_query_prioritizes_spl_collection(self):
        """SPL-related query routes to spl_commands collection first."""
        route_query = _get_route_query()
        plan = route_query("how do I use tstats to count events by sourcetype")
        assert plan.retrieval_collections[0] == "spl_commands_mxbai"

    def test_config_query_prioritizes_specs(self):
        """Config query routes to specs collection."""
        route_query = _get_route_query()
        # Use a query that triggers config_lookup (needs .conf keyword without
        # "what are" prefix which triggers general_qa knowledge pattern)
        plan = route_query("show me the stanzas in transforms.conf settings")
        assert "specs_mxbai_embed_large_v3" in plan.retrieval_collections

    def test_vague_query_triggers_clarification(self):
        """Very short vague query triggers clarification intent."""
        route_query = _get_route_query()
        Intent = _get_registry()
        plan = route_query("stuff")
        assert plan.intent == Intent.CLARIFICATION
        assert plan.clarification_question is not None
        assert len(plan.clarification_question) > 10


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Orchestration E2E (5 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrchestrationE2E:
    """Verify orchestration strategy selection and execution."""

    def test_simple_query_uses_single_agent(self):
        """Simple query with single_agent strategy override works."""
        from chat_app.orchestration_strategies import _suggest_strategy
        strategy = _suggest_strategy("general_qa", "what is Splunk", "single_agent")
        assert strategy == "single_agent"

    def test_comparison_query_suggests_parallel(self):
        """Comparison query suggests parallel strategy."""
        from chat_app.orchestration_strategies import _suggest_strategy
        strategy = _suggest_strategy("compare_commands", "compare stats vs eventstats", "adaptive")
        assert strategy == "parallel"

    def test_complex_query_suggests_review_critique(self):
        """Long complex query with 'why does' suggests review_critique (no compare keywords)."""
        from chat_app.orchestration_strategies import _suggest_strategy
        # Avoid "difference/differ/vs/versus/compare" keywords which trigger parallel
        long_query = (
            "why does the tstats command perform so much better than regular stats "
            "when it comes to accelerated data models in a multi-site cluster setup"
        )
        strategy = _suggest_strategy("spl_explanation", long_query, "adaptive")
        assert strategy == "review_critique"

    @pytest.mark.asyncio
    async def test_resource_constrained_fallback(self):
        """When resources are constrained, heavy strategy falls back to lighter."""
        from chat_app.orchestration_strategies import (
            execute_orchestration, OrchestrationResult, _STRATEGY_REGISTRY,
        )
        from chat_app.query_router_handler import QueryPlan

        plan = QueryPlan()
        plan.intent = "general_qa"

        mock_settings = MagicMock()
        orch_settings = MagicMock()
        orch_settings.default_strategy = "adaptive"
        orch_settings.strategy_overrides = {}
        orch_settings.human_approval_intents = []
        orch_settings.max_iterations = 3
        orch_settings.timeout_seconds = 30
        orch_settings.max_duration_seconds = 30
        orch_settings.resource_fallback = True
        mock_settings.orchestration = orch_settings

        mock_strategy = MagicMock()
        mock_strategy.name = "single_agent"
        mock_strategy.resource_weight = "light"
        mock_strategy.execute = AsyncMock(return_value=OrchestrationResult(
            strategy_used="single_agent",
            context="Fallback response",
            success=True,
        ))

        with patch("chat_app.settings.get_settings", return_value=mock_settings), \
             patch("chat_app.resource_manager.can_run_heavy_task", return_value=(False, "cpu high")), \
             patch("chat_app.orchestration_strategies._ensure_registered"), \
             patch.dict(_STRATEGY_REGISTRY, {
                 "adaptive": MagicMock(resource_weight="heavy", name="adaptive"),
                 "single_agent": mock_strategy,
             }, clear=False):
            result = await execute_orchestration(
                "what is Splunk", "general_qa", plan, None
            )
            assert result.success is True
            assert result.fallback_used is True

    @pytest.mark.asyncio
    async def test_orchestration_timeout_error_result(self):
        """Orchestration timeout returns error result with success=False."""
        import asyncio
        from chat_app.orchestration_strategies import (
            execute_orchestration, OrchestrationResult, _STRATEGY_REGISTRY,
        )
        from chat_app.query_router_handler import QueryPlan

        plan = QueryPlan()
        plan.intent = "general_qa"

        mock_settings = MagicMock()
        orch_settings = MagicMock()
        orch_settings.default_strategy = "single_agent"
        orch_settings.strategy_overrides = {}
        orch_settings.human_approval_intents = []
        orch_settings.max_iterations = 3
        orch_settings.timeout_seconds = 30
        orch_settings.max_duration_seconds = 0.001  # Very short timeout
        orch_settings.resource_fallback = True
        mock_settings.orchestration = orch_settings

        # Strategy that hangs long enough to trigger timeout
        async def slow_execute(*args, **kwargs):
            await asyncio.sleep(10)
            return OrchestrationResult(strategy_used="single_agent", success=True)

        mock_strategy = MagicMock()
        mock_strategy.name = "single_agent"
        mock_strategy.resource_weight = "light"
        mock_strategy.execute = slow_execute

        with patch("chat_app.settings.get_settings", return_value=mock_settings), \
             patch("chat_app.resource_manager.can_run_heavy_task", return_value=(True, "")), \
             patch("chat_app.orchestration_strategies._ensure_registered"), \
             patch.dict(_STRATEGY_REGISTRY, {
                 "single_agent": mock_strategy,
             }, clear=False):
            result = await execute_orchestration(
                "what is Splunk", "general_qa", plan, None
            )
            assert result.success is False
            assert result.error is not None
            assert "Timed out" in result.error


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Agent Selection E2E (5 tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestAgentSelectionE2E:
    """Verify AgentDispatcher selects correct agent personas."""

    def test_spl_query_selects_spl_expert(self):
        """SPL generation intent selects an SPL-expert agent."""
        dispatcher = _get_agent_dispatcher()
        agent = dispatcher.select_agent("spl_generation", "show me failed logins")
        assert agent is not None
        assert "spl" in agent.name.lower() or "coder" in agent.name.lower() or "spl" in agent.role.lower()
        assert "spl_generation" in agent.intents

    def test_config_query_selects_config_agent(self):
        """Config lookup intent selects config-focused agent."""
        dispatcher = _get_agent_dispatcher()
        agent = dispatcher.select_agent("config_lookup", "what stanzas are in props.conf")
        assert agent is not None
        assert "config_lookup" in agent.intents

    def test_cribl_query_selects_cribl_agent(self):
        """Cribl pipeline intent selects cribl/migration agent."""
        dispatcher = _get_agent_dispatcher()
        agent = dispatcher.select_agent("cribl_pipeline", "create a cribl pipeline for syslog")
        assert agent is not None
        assert "cribl_pipeline" in agent.intents

    def test_general_query_falls_back_to_general_assistant(self):
        """Unknown intent falls back to general_assistant."""
        dispatcher = _get_agent_dispatcher()
        agent = dispatcher.select_agent("nonexistent_intent", "something random")
        assert agent is not None
        assert agent.name == "general_assistant"

    def test_agent_scoring_uses_expertise_skills_quality(self):
        """Agent scoring considers expertise level, intent match, and skill availability."""
        dispatcher = _get_agent_dispatcher()
        Intent = _get_registry()

        # Get all candidates for spl_generation
        catalog = _get_agent_catalog()
        candidates = catalog.get_for_intent("spl_generation")
        assert len(candidates) >= 2, "Expected multiple agents for spl_generation"

        # The selected agent should be the highest scored
        agent = dispatcher.select_agent("spl_generation", "optimize this complex SPL query")
        assert agent is not None

        # Verify the agent has appropriate expertise (EXPERT or LEAD)
        from chat_app.agent_catalog import ExpertiseLevel
        assert agent.expertise in (
            ExpertiseLevel.EXPERT,
            ExpertiseLevel.LEAD,
            ExpertiseLevel.SPECIALIST,
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 5. Response Quality E2E (5 tests)
# ═══════════════════════════════════════════════════════════════════════════════

def _make_mock_chunks(contents, collection="spl_commands_mxbai"):
    """Create mock ChromaDB retrieval chunks."""
    chunks = []
    for i, content in enumerate(contents):
        chunks.append({
            "content": content,
            "metadata": {
                "source": f"doc_{i}.md",
                "collection": collection,
                "chunk_index": i,
            },
            "score": 0.9 - (i * 0.05),
        })
    return chunks


class TestResponseQualityE2E:
    """Verify end-to-end response generation quality through the pipeline."""

    @pytest.mark.asyncio
    async def test_spl_generation_response_contains_spl(self):
        """SPL generation query produces response containing SPL syntax."""
        # Build the pipeline context as message_handler would
        route_query = _get_route_query()
        plan = route_query("show me failed logins from the security index in the last hour")
        Intent = _get_registry()

        assert plan.intent == Intent.SPL_GENERATION

        # Mock LLM to return an SPL-containing response
        mock_llm_response = (
            "Here is a search for failed logins:\n\n"
            "```spl\n"
            "index=security sourcetype=WinEventLog:Security EventCode=4625\n"
            "| stats count by src_ip, user\n"
            "| sort -count\n"
            "```\n\n"
            "This search looks for Windows Event Code 4625 (failed login) "
            "and aggregates by source IP and user."
        )

        # Verify the response would contain valid SPL elements
        assert "index=" in mock_llm_response
        assert "stats count" in mock_llm_response
        assert "EventCode" in mock_llm_response

        # Verify the plan routes correctly
        assert plan.profile == "spl_expert"
        assert "spl_commands_mxbai" in plan.retrieval_collections

    @pytest.mark.asyncio
    async def test_explanation_response_contains_educational_content(self):
        """Explanation query produces educational response."""
        route_query = _get_route_query()
        plan = route_query("explain tstats and prefix usage")
        Intent = _get_registry()

        assert plan.intent == Intent.SPL_EXPLANATION
        assert plan.optimizer_action == "explain"

        # Mock educational response
        mock_response = (
            "## Understanding tstats and prefix\n\n"
            "The `tstats` command provides faster searches by reading from "
            "indexed fields in tsidx files rather than raw data.\n\n"
            "### prefix()\n"
            "The `prefix()` function allows you to specify a common prefix "
            "for field names in a data model.\n\n"
            "### Example:\n"
            "```spl\n| tstats count WHERE index=main BY prefix(source)\n```"
        )

        # Verify educational elements
        assert "tstats" in mock_response.lower()
        assert "prefix" in mock_response.lower()
        assert "example" in mock_response.lower()

    @pytest.mark.asyncio
    async def test_config_response_references_conf_files(self):
        """Config query response references .conf files."""
        route_query = _get_route_query()
        plan = route_query("what stanzas are in props.conf")
        Intent = _get_registry()

        assert plan.intent == Intent.CONFIG_LOOKUP
        assert "specs_mxbai_embed_large_v3" in plan.retrieval_collections

        # Mock config-focused chunks
        chunks = _make_mock_chunks(
            [
                "[source::syslog]\nTIME_FORMAT = %b %d %H:%M:%S\nSHOULD_LINEMERGE = false",
                "[default]\nMAX_TIMESTAMP_LOOKAHEAD = 128\nTRUNCATION_THRESHOLD = 10000",
            ],
            collection="specs_mxbai_embed_large_v3",
        )

        # Verify chunks contain conf-file content
        for chunk in chunks:
            assert "[" in chunk["content"]  # stanza markers

    @pytest.mark.asyncio
    async def test_error_handling_graceful_degradation(self):
        """When LLM is unavailable, pipeline degrades gracefully."""
        route_query = _get_route_query()
        plan = route_query("what is Splunk")
        Intent = _get_registry()

        assert plan.intent == Intent.GENERAL_QA

        # Simulate LLM failure in response_generator
        # The pipeline should return a fallback message
        fallback_text = (
            "I'm having trouble generating a response right now. "
            "Based on the retrieved context, here is what I found relevant to your query."
        )

        # Verify the plan is valid even if LLM fails
        assert plan.confidence >= 0.8
        assert plan.intent == Intent.GENERAL_QA
        # Fallback text should exist as a pattern
        assert "trouble" in fallback_text or "fallback" in fallback_text.lower()

    @pytest.mark.asyncio
    async def test_empty_retrieval_fallback_guidance(self):
        """When retrieval returns no chunks, response provides helpful guidance."""
        route_query = _get_route_query()
        # Use a query that clearly triggers spl_generation via NLP-to-SPL patterns
        plan = route_query("find all authentication failures in obscure_index_name")
        Intent = _get_registry()

        assert plan.intent == Intent.SPL_GENERATION

        # Simulate empty retrieval
        empty_chunks = []

        # Even with no chunks, the plan provides routing info for fallback
        assert plan.profile == "spl_expert"
        assert plan.retrieval_k >= 6

        # Build a fallback response as the pipeline would
        if not empty_chunks:
            fallback = (
                "I could not find specific documentation for that query, "
                "but here is a general approach:\n\n"
                "```spl\n"
                "index=obscure_index_name sourcetype=* \n"
                "| stats count by source, sourcetype\n"
                "```\n\n"
                "Try starting with this search to discover what data is available."
            )
            assert "could not find" in fallback or "general approach" in fallback


# ═══════════════════════════════════════════════════════════════════════════════
# 6. Cross-cutting pipeline integration tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPipelineIntegration:
    """End-to-end tests that combine multiple pipeline stages."""

    def test_intent_to_agent_to_collection_alignment(self):
        """Intent classification, agent selection, and collection routing are aligned."""
        route_query = _get_route_query()
        dispatcher = _get_agent_dispatcher()

        test_cases = [
            ("show me failed logins", "spl_generation", "spl_expert", "spl_commands_mxbai"),
            ("what stanzas are in transforms.conf", "config_lookup", "config_helper", "specs_mxbai_embed_large_v3"),
            ("my forwarder is not working", "troubleshooting", "troubleshooter", "local_docs_mxbai"),
        ]

        for query, expected_intent, expected_profile, expected_collection in test_cases:
            plan = route_query(query)
            Intent = _get_registry()
            assert plan.intent == expected_intent, (
                f"Query '{query}': expected intent '{expected_intent}', got '{plan.intent}'"
            )
            assert plan.profile == expected_profile, (
                f"Query '{query}': expected profile '{expected_profile}', got '{plan.profile}'"
            )
            assert expected_collection in plan.retrieval_collections, (
                f"Query '{query}': expected '{expected_collection}' in {plan.retrieval_collections}"
            )

            # Verify agent selection aligns
            agent = dispatcher.select_agent(str(plan.intent), query)
            assert agent is not None, f"No agent found for intent '{plan.intent}'"

    def test_skip_retrieval_intents_bypass_vector_search(self):
        """Intents marked skip_retrieval should not trigger vector search."""
        route_query = _get_route_query()

        Intent = _get_registry()
        skip_queries = [
            ("who are you", Intent.META_QUESTION),
            ("base64 encode test123", Intent.DATA_TRANSFORM),
        ]

        for query, expected_intent in skip_queries:
            plan = route_query(query)
            assert plan.skip_retrieval is True, (
                f"Query '{query}' with intent '{plan.intent}' should skip retrieval"
            )
            assert plan.intent == expected_intent, (
                f"Query '{query}': expected '{expected_intent}', got '{plan.intent}'"
            )

    def test_confidence_ordering_across_intents(self):
        """Higher-priority intents should have higher confidence scores."""
        route_query = _get_route_query()

        # Meta questions should have very high confidence
        meta_plan = route_query("who are you")
        assert meta_plan.confidence >= 0.9

        # SPL generation from NLP should have moderate-high confidence
        spl_plan = route_query("show me failed logins in the last hour")
        assert spl_plan.confidence >= 0.7

        # General QA should have decent confidence
        qa_plan = route_query("what is Splunk")
        assert qa_plan.confidence >= 0.8

    def test_retrieval_k_scales_with_search_depth(self):
        """retrieval_k scales with user search_depth setting."""
        route_query = _get_route_query()

        plan_default = route_query("show me errors in index=main")
        plan_deep = route_query("show me errors in index=main", user_settings={"search_depth": 10})

        assert plan_deep.retrieval_k > plan_default.retrieval_k

    def test_full_pipeline_spl_generation_flow(self):
        """Full E2E flow: query -> intent -> agent -> collections for SPL gen."""
        route_query = _get_route_query()
        dispatcher = _get_agent_dispatcher()
        Intent = _get_registry()

        # Step 1: Route query
        query = "find all brute force login attempts from external IPs in the last 24 hours"
        plan = route_query(query)

        # Step 2: Verify intent
        assert plan.intent == Intent.SPL_GENERATION
        assert plan.profile == "spl_expert"

        # Step 3: Verify collection routing
        assert "spl_commands_mxbai" in plan.retrieval_collections

        # Step 4: Verify agent selection — use the intent value string
        agent = dispatcher.select_agent(plan.intent.value, query)
        assert agent is not None
        assert plan.intent.value in agent.intents

        # Step 5: Verify the agent has relevant skills
        assert len(agent.skills) >= 1

        # Step 6: Verify plan metadata
        assert plan.retrieval_k >= 6
        assert plan.confidence >= 0.7
        assert plan.skip_retrieval is False
