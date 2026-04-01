"""Tests for IntentClassifier — verifies correct intent routing for all query types."""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chat_app'))

import pytest
from chat_app.intent_classifier import IntentClassifier


@pytest.fixture
def classifier():
    return IntentClassifier()


# ---------------------------------------------------------------------------
# Meta Questions (self-referential — no RAG context needed)
# ---------------------------------------------------------------------------

class TestMetaQuestions:
    def test_who_are_you(self, classifier):
        plan = classifier.classify("who are you?", 3)
        assert plan.intent == "meta_question"
        assert plan.skip_retrieval is True

    def test_what_can_you_do(self, classifier):
        plan = classifier.classify("what can you do?", 4)
        assert plan.intent == "meta_question"

    def test_your_capabilities(self, classifier):
        plan = classifier.classify("tell me about your capabilities", 5)
        assert plan.intent == "meta_question"

    def test_what_is_splunk(self, classifier):
        """'what is splunk' is a knowledge question — benefits from RAG context."""
        plan = classifier.classify("what is splunk", 3)
        assert plan.intent == "general_qa"

    def test_how_does_splunk_work(self, classifier):
        """'how does splunk work' is a knowledge question — benefits from RAG context."""
        plan = classifier.classify("how does splunk work?", 4)
        assert plan.intent == "general_qa"


# ---------------------------------------------------------------------------
# Run Search
# ---------------------------------------------------------------------------

class TestRunSearch:
    def test_run_search(self, classifier):
        plan = classifier.classify("run this search: index=main | head 10", 8)
        assert plan.intent == "run_search"

    def test_execute_search(self, classifier):
        plan = classifier.classify("execute this search: index=main | head 10", 8)
        assert plan.intent == "run_search"


# ---------------------------------------------------------------------------
# Create Alert
# ---------------------------------------------------------------------------

class TestCreateAlert:
    def test_create_alert(self, classifier):
        plan = classifier.classify("create an alert for failed logins", 6)
        assert plan.intent == "create_alert"

    def test_alert_me_when(self, classifier):
        plan = classifier.classify("alert me when error count exceeds 100", 7)
        assert plan.intent == "create_alert"

    def test_schedule_report(self, classifier):
        plan = classifier.classify("schedule a report for daily event counts", 7)
        assert plan.intent == "create_alert"


# ---------------------------------------------------------------------------
# SPL Actions (explain, optimize, review, score, annotate)
# Now route to specific intents for better downstream handling
# ---------------------------------------------------------------------------

class TestSPLExplain:
    def test_explain_spl(self, classifier):
        plan = classifier.classify("explain this SPL query for me", 6)
        assert plan.intent == "spl_explanation"
        assert plan.optimizer_action == "explain"

    def test_what_does_tstats_do(self, classifier):
        """'what does tstats mean' has SPL context — routes to SPL explain pipeline."""
        plan = classifier.classify("what does tstats mean and how does it work?", 8)
        assert plan.intent == "spl_explanation"
        assert plan.optimizer_action == "explain"

    def test_how_to_use_eval(self, classifier):
        plan = classifier.classify("how to use eval in SPL?", 6)
        assert plan.intent == "spl_explanation"
        assert plan.optimizer_action == "explain"

    def test_step_by_step(self, classifier):
        plan = classifier.classify("break down this query step by step", 6)
        assert plan.intent == "spl_explanation"
        assert plan.optimizer_action == "explain"

    def test_teach_me_prefix(self, classifier):
        plan = classifier.classify("teach me about prefix and term in SPL", 8)
        assert plan.intent == "spl_explanation"
        assert plan.optimizer_action == "explain"

    def test_help_with_tstats(self, classifier):
        """The key fix — 'help me with tstats and prefix' should explain, not generate."""
        plan = classifier.classify("help me with tstats and prefix", 6)
        assert plan.intent == "spl_explanation"
        assert plan.optimizer_action == "explain"
        assert plan.confidence >= 0.8

    def test_show_me_tstats_examples(self, classifier):
        plan = classifier.classify("show me tstats prefix examples", 4)
        assert plan.intent == "spl_explanation"
        assert plan.optimizer_action == "explain"

    def test_tstats_examples(self, classifier):
        plan = classifier.classify("tstats examples with prefix", 4)
        assert plan.intent == "spl_explanation"
        assert plan.optimizer_action == "explain"


class TestSPLOptimize:
    def test_optimize_spl(self, classifier):
        plan = classifier.classify("optimize this SPL query for performance", 6)
        assert plan.intent == "spl_optimization"
        assert plan.optimizer_action == "optimize"

    def test_make_faster(self, classifier):
        plan = classifier.classify("make this search faster and more efficient", 7)
        assert plan.intent == "spl_optimization"
        assert plan.optimizer_action == "optimize"

    def test_convert_to_tstats(self, classifier):
        plan = classifier.classify("convert to tstats for better performance", 6)
        assert plan.intent == "spl_optimization"
        assert plan.optimizer_action == "optimize"


class TestSPLReview:
    def test_review_spl(self, classifier):
        plan = classifier.classify("review this SPL query for issues", 6)
        assert plan.intent == "spl_validation"
        assert plan.optimizer_action == "review"

    def test_validate_search(self, classifier):
        plan = classifier.classify("validate this search query", 4)
        assert plan.intent == "spl_validation"
        assert plan.optimizer_action == "review"

    def test_is_this_correct(self, classifier):
        plan = classifier.classify("is this spl query correct?", 5)
        assert plan.intent == "spl_validation"
        assert plan.optimizer_action == "review"


class TestSPLScore:
    def test_score_query(self, classifier):
        plan = classifier.classify("score this SPL query for quality", 6)
        assert plan.intent == "spl_validation"
        assert plan.optimizer_action == "score"

    def test_how_good_is_search(self, classifier):
        plan = classifier.classify("how good is this search query?", 6)
        assert plan.intent == "spl_validation"
        assert plan.optimizer_action == "score"


class TestSPLAnnotate:
    def test_annotate_spl(self, classifier):
        plan = classifier.classify("annotate this SPL query with comments", 6)
        assert plan.intent == "spl_explanation"
        assert plan.optimizer_action == "annotate"


# ---------------------------------------------------------------------------
# Raw SPL Detection
# ---------------------------------------------------------------------------

class TestRawSPL:
    def test_index_equals(self, classifier):
        plan = classifier.classify("index=main sourcetype=access_combined | stats count by host", 8)
        assert plan.intent == "spl_generation"

    def test_pipe_stats(self, classifier):
        plan = classifier.classify("| stats count by host", 5)
        assert plan.intent == "spl_generation"

    def test_tstats(self, classifier):
        plan = classifier.classify("| tstats count from datamodel=Web by Web.src", 8)
        assert plan.intent == "spl_generation"


# ---------------------------------------------------------------------------
# NLP to SPL (natural language → query generation)
# ---------------------------------------------------------------------------

class TestNLPToSPL:
    def test_generate_query(self, classifier):
        plan = classifier.classify("write a query to find failed logins in the last hour", 10)
        assert plan.intent == "spl_generation"

    def test_show_me_events(self, classifier):
        plan = classifier.classify("show me failed login events from yesterday", 7)
        assert plan.intent == "spl_generation"

    def test_find_errors(self, classifier):
        plan = classifier.classify("find all errors in the web index last 24 hours", 9)
        assert plan.intent == "spl_generation"

    def test_count_by(self, classifier):
        plan = classifier.classify("count events by sourcetype", 4)
        assert plan.intent == "spl_generation"


# ---------------------------------------------------------------------------
# Config Lookup
# ---------------------------------------------------------------------------

class TestConfigLookup:
    def test_props_conf(self, classifier):
        plan = classifier.classify("how do I configure props.conf for JSON extraction?", 8)
        assert plan.intent == "config_lookup"

    def test_savedsearch(self, classifier):
        plan = classifier.classify("what stanzas are in savedsearches.conf?", 6)
        assert plan.intent == "config_lookup"


# ---------------------------------------------------------------------------
# Troubleshooting
# ---------------------------------------------------------------------------

class TestTroubleshooting:
    def test_error(self, classifier):
        plan = classifier.classify("I'm getting an error when running my search", 8)
        assert plan.intent == "troubleshooting"

    def test_not_working(self, classifier):
        plan = classifier.classify("my dashboard is not working properly", 6)
        assert plan.intent == "troubleshooting"


# ---------------------------------------------------------------------------
# Compare Commands
# ---------------------------------------------------------------------------

class TestCompareCommands:
    def test_compare(self, classifier):
        plan = classifier.classify("compare stats vs eventstats command", 5)
        assert plan.intent == "compare_commands"

    def test_difference(self, classifier):
        plan = classifier.classify("what's the difference between join and lookup commands", 8)
        assert plan.intent == "compare_commands"


# ---------------------------------------------------------------------------
# General QA (catch-all)
# ---------------------------------------------------------------------------

class TestGeneralQA:
    def test_general(self, classifier):
        plan = classifier.classify("tell me about data onboarding best practices", 6)
        assert plan.intent == "general_qa"

    def test_explain_concept(self, classifier):
        """Educational 'explain X' without SPL context uses general QA."""
        plan = classifier.classify("explain Splunk forwarders and indexers", 5)
        # "forwarders and indexers" has no SPL context words, routes to general QA
        assert plan.intent == "general_qa"
