"""Unit tests for query_router.py - intent classification and routing."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chat_app'))

from chat_app.query_router_handler import route_query, extract_spl_from_input, QueryPlan


class TestRouteQuery:
    """Test intent classification."""

    def test_meta_question_who_are_you(self):
        plan = route_query("who are you")
        assert plan.intent == "meta_question"
        assert plan.skip_retrieval is True

    def test_meta_question_capabilities(self):
        plan = route_query("what can you do")
        assert plan.intent == "meta_question"
        assert plan.skip_retrieval is True

    def test_spl_optimize(self):
        plan = route_query("optimize this spl: index=main | stats count by host")
        assert plan.intent == "spl_optimization"
        assert plan.optimizer_action == "optimize"
        assert plan.profile == "spl_expert"

    def test_spl_explain(self):
        plan = route_query("explain this query: index=main | stats count by host")
        assert plan.intent == "spl_explanation"
        assert plan.optimizer_action == "explain"

    def test_spl_review(self):
        plan = route_query("review this spl: index=main error")
        assert plan.intent == "spl_validation"
        assert plan.optimizer_action == "review"

    def test_raw_spl_detection(self):
        plan = route_query("index=network sourcetype=firewall | stats count by src_ip")
        assert plan.intent == "spl_generation"
        # Raw SPL without natural language context → auto-explain mode
        assert plan.optimizer_action == "explain"
        assert plan.auto_explain is True
        assert plan.optimizer_type == "spl"

    def test_nlp_to_spl(self):
        plan = route_query("find all failed logins in the last hour")
        assert plan.intent == "spl_generation"
        assert plan.optimizer_type == "nlp"

    def test_config_lookup(self):
        plan = route_query("show me inputs.conf settings")
        assert plan.intent == "config_lookup"
        assert plan.profile == "config_helper"

    def test_troubleshooting(self):
        plan = route_query("my forwarder is not working and shows errors")
        assert plan.intent == "troubleshooting"
        assert plan.profile == "troubleshooter"

    def test_repo_query(self):
        plan = route_query("show our app setup details")
        assert plan.intent == "repo_query"
        assert plan.profile == "org_expert"

    def test_general_qa(self):
        plan = route_query("what is the difference between heavy and universal forwarder")
        assert plan.intent == "general_qa"

    def test_run_search(self):
        plan = route_query("run this search: index=main | head 10")
        assert plan.intent == "run_search"
        assert plan.extracted_query is not None

    def test_create_alert(self):
        plan = route_query("create an alert for failed logins")
        assert plan.intent == "create_alert"

    def test_clarification_vague(self):
        plan = route_query("stuff")
        assert plan.intent == "clarification"
        assert plan.clarification_question is not None

    def test_saved_search_analysis(self):
        plan = route_query("analyze saved searches for optimization opportunities")
        assert plan.intent == "saved_search_analysis"

    def test_retrieval_k_scales_with_search_depth(self):
        plan_low = route_query("what is splunk", {"search_depth": 1})
        plan_high = route_query("what is splunk", {"search_depth": 10})
        assert plan_high.retrieval_k >= plan_low.retrieval_k


class TestExtractSplFromInput:
    """Test SPL extraction from user messages."""

    def test_extract_with_optimize_prefix(self):
        result = extract_spl_from_input("optimize this spl: index=main | stats count by host")
        assert result is not None
        assert "index=main" in result

    def test_extract_with_explain_prefix(self):
        result = extract_spl_from_input("explain: | tstats count where index=main by host")
        assert result is not None
        assert "tstats" in result

    def test_extract_raw_spl(self):
        result = extract_spl_from_input("index=firewall sourcetype=pan | stats count by src_ip")
        assert result is not None
        assert "index=firewall" in result

    def test_no_spl_detected(self):
        result = extract_spl_from_input("tell me about Splunk")
        assert result is None

    def test_extract_with_review_prefix(self):
        result = extract_spl_from_input("review this query: index=web | timechart count")
        assert result is not None
        assert "timechart" in result
