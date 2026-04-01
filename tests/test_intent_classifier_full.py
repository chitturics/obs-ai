"""Tests for intent classification — Full intent coverage via route_query."""
import pytest
from chat_app.query_router_handler import route_query, extract_spl_from_input, QueryPlan
from chat_app.intent_classifier import RAW_SPL_PATTERNS
import re


class TestIntentClassifierAllIntents:
    """Test that every intent type is correctly classified via route_query."""

    def test_meta_who_are_you(self):
        plan = route_query("who are you?")
        assert plan.intent == "meta_question"
        assert plan.skip_retrieval is True

    def test_meta_capabilities(self):
        plan = route_query("what can you do?")
        assert plan.intent == "meta_question"

    def test_spl_optimize(self):
        plan = route_query("optimize this search: index=main | stats count")
        assert plan.intent in ("spl_generation", "spl_optimization")
        assert plan.optimizer_action == "optimize"

    def test_spl_explain(self):
        plan = route_query("explain this query: index=main | stats count by host")
        assert plan.intent in ("spl_generation", "spl_explanation")

    def test_spl_review(self):
        plan = route_query("review this search: index=main | stats count")
        assert plan.intent in ("spl_generation", "spl_validation")

    def test_raw_spl_with_index(self):
        plan = route_query("index=main sourcetype=syslog | stats count by host")
        assert plan.intent == "spl_generation"

    def test_raw_spl_with_pipe(self):
        plan = route_query("| tstats count WHERE index=main by sourcetype")
        assert plan.intent == "spl_generation"

    def test_config_lookup_props(self):
        plan = route_query("show me props.conf settings for syslog")
        assert plan.intent == "config_lookup"

    def test_config_lookup_savedsearch(self):
        plan = route_query("what are our saved searches?")
        assert plan.intent in ("config_lookup", "saved_search_analysis")

    def test_troubleshoot_error(self):
        plan = route_query("my search is not working, it gives an error")
        assert plan.intent == "troubleshooting"

    def test_general_qa_stats(self):
        plan = route_query("how does the stats command work?")
        assert plan.intent in ("general_qa", "spl_generation")

    def test_general_qa_concept(self):
        plan = route_query("what is the difference between stats and eventstats?")
        assert plan.intent in ("general_qa", "spl_generation", "spl_explanation")

    def test_nlp_to_spl_generation(self):
        plan = route_query("show me failed login attempts in the last 24 hours")
        assert plan.intent == "spl_generation"

    def test_clarification_for_vague(self):
        plan = route_query("help")
        assert plan.intent in ("clarification", "meta_question", "general_qa")

    def test_saved_search_analysis(self):
        plan = route_query("analyze my saved searches")
        assert plan.intent in ("saved_search_analysis", "general_qa")

    def test_improve_spl(self):
        plan = route_query("improve this: index=main | table host | sort host")
        assert plan.intent == "spl_generation"

    def test_spl_generation_has_optimizer_action(self):
        plan = route_query("optimize this: index=main | stats count by host")
        assert plan.intent == "spl_generation"
        assert plan.optimizer_action in ("optimize", "review", "explain")

    def test_spl_generation_for_raw_sets_auto_explain(self):
        plan = route_query("index=main | stats count by host")
        assert plan.intent == "spl_generation"


class TestQueryPlanStructure:
    """Test that QueryPlan fields are populated correctly."""

    def test_plan_has_intent(self):
        plan = route_query("index=main | stats count")
        assert hasattr(plan, "intent")
        assert plan.intent is not None
        assert isinstance(plan.intent, str)

    def test_plan_has_profile(self):
        plan = route_query("show me props.conf settings")
        assert hasattr(plan, "profile")
        assert plan.profile is not None

    def test_plan_has_retrieval_k(self):
        plan = route_query("what is Splunk?")
        assert hasattr(plan, "retrieval_k")
        assert plan.retrieval_k > 0

    def test_plan_has_skip_retrieval(self):
        plan = route_query("who are you")
        assert hasattr(plan, "skip_retrieval")
        assert isinstance(plan.skip_retrieval, bool)

    def test_optimizer_action_set_for_optimize(self):
        plan = route_query("optimize this search: index=main | sort _time | stats count")
        assert plan.optimizer_action == "optimize"

    def test_extracted_query_for_spl_action(self):
        plan = route_query("explain: index=main | stats count by host")
        assert plan.extracted_query is not None
        assert "index=main" in plan.extracted_query

    def test_retrieval_k_scales(self):
        plan_default = route_query("what is Splunk?")
        plan_deep = route_query("what is Splunk?", user_settings={"search_depth": 10})
        assert plan_deep.retrieval_k >= plan_default.retrieval_k


class TestRawSplPatterns:
    """Test RAW_SPL_PATTERNS list for completeness."""

    def test_patterns_list_nonempty(self):
        assert len(RAW_SPL_PATTERNS) >= 15

    def test_index_pattern_matches(self):
        assert any(re.search(p, "index=main", re.IGNORECASE) for p in RAW_SPL_PATTERNS)

    def test_pipe_stats_matches(self):
        assert any(re.search(p, "| stats count by host", re.IGNORECASE) for p in RAW_SPL_PATTERNS)

    def test_earliest_matches(self):
        assert any(re.search(p, "earliest=-24h", re.IGNORECASE) for p in RAW_SPL_PATTERNS)

    def test_pipe_eval_matches(self):
        assert any(re.search(p, "| eval x=1", re.IGNORECASE) for p in RAW_SPL_PATTERNS)

    def test_natural_language_not_matched(self):
        assert not any(re.search(p, "how do I count events?", re.IGNORECASE) for p in RAW_SPL_PATTERNS)

    def test_greeting_not_matched(self):
        assert not any(re.search(p, "hello, how are you?", re.IGNORECASE) for p in RAW_SPL_PATTERNS)


class TestExtractSplFromInput:
    """Test SPL extraction from user messages."""

    def test_extract_with_optimize_prefix(self):
        spl = extract_spl_from_input("optimize this: index=main | stats count")
        assert spl is not None
        assert "index=main" in spl

    def test_extract_with_explain_prefix(self):
        spl = extract_spl_from_input("explain: | tstats count WHERE index=main by src_ip")
        assert spl is not None
        assert "tstats" in spl

    def test_extract_raw_spl(self):
        spl = extract_spl_from_input("index=main | stats count by host")
        assert spl is not None

    def test_no_spl_in_natural_language(self):
        spl = extract_spl_from_input("what is the stats command?")
        assert spl is None

    def test_extract_preserves_full_query(self):
        spl = extract_spl_from_input("review: index=main | eval x=1 | where x>0 | table x")
        assert spl is not None
        assert "eval" in spl
        assert "table" in spl
