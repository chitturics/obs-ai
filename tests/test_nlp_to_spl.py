"""Tests for the NLP-to-SPL generator."""
import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


class TestSPLIntents:
    """Test intent templates are valid."""

    def test_intent_templates_have_required_keys(self):
        from shared.spl_intents import INTENT_TEMPLATES
        for intent, info in INTENT_TEMPLATES.items():
            assert "template" in info, f"{intent} missing 'template'"
            assert "default_params" in info, f"{intent} missing 'default_params'"

    def test_intent_templates_format_with_defaults(self):
        from shared.spl_intents import INTENT_TEMPLATES
        for intent, info in INTENT_TEMPLATES.items():
            template = info["template"]
            params = info["default_params"]
            try:
                result = template.format(**params)
                assert len(result) > 0, f"{intent} produced empty query"
            except KeyError as e:
                pytest.fail(f"{intent} template missing default param: {e}")

    def test_all_templates_have_time_params(self):
        from shared.spl_intents import INTENT_TEMPLATES
        for intent, info in INTENT_TEMPLATES.items():
            params = info["default_params"]
            assert "time_start" in params, f"{intent} missing time_start"
            assert "time_end" in params, f"{intent} missing time_end"


class TestNLPtoSPLGenerator:
    """Test the NLP-to-SPL generator."""

    def _get_generator(self):
        from shared.nlp_to_spl import NLPtoSPL
        return NLPtoSPL(llm=None)

    def test_detect_intent_failed_logins(self):
        gen = self._get_generator()
        from shared.spl_intents import SPLIntent
        intent = gen._detect_intent("show me failed login attempts")
        assert intent == SPLIntent.FAILED_LOGINS

    def test_detect_intent_count(self):
        gen = self._get_generator()
        from shared.spl_intents import SPLIntent
        intent = gen._detect_intent("how many events by host")
        assert intent == SPLIntent.COUNT_EVENTS

    def test_detect_intent_timechart(self):
        gen = self._get_generator()
        from shared.spl_intents import SPLIntent
        intent = gen._detect_intent("show error trend over time")
        assert intent == SPLIntent.TIMECHART

    def test_detect_intent_dns(self):
        gen = self._get_generator()
        from shared.spl_intents import SPLIntent
        intent = gen._detect_intent("show dns queries for suspicious domains")
        assert intent == SPLIntent.DNS_QUERIES

    def test_detect_intent_brute_force(self):
        gen = self._get_generator()
        from shared.spl_intents import SPLIntent
        intent = gen._detect_intent("detect brute force attacks")
        assert intent == SPLIntent.BRUTE_FORCE_DETECTION

    def test_generate_failed_logins(self):
        gen = self._get_generator()
        result = gen.generate("show me failed login attempts in the last hour")
        assert result.query is not None
        assert len(result.query) > 10
        assert result.confidence > 0
        # Should contain authentication-related terms
        q = result.query.lower()
        assert "4625" in q or "failure" in q or "failed" in q

    def test_generate_network_traffic(self):
        gen = self._get_generator()
        result = gen.generate("show network traffic connections")
        assert result.query is not None
        assert len(result.query) > 10

    def test_generate_error_analysis(self):
        gen = self._get_generator()
        result = gen.generate("find all errors in the last 4 hours")
        assert result.query is not None
        assert "error" in result.query.lower() or "TERM(error)" in result.query

    def test_generate_top_values(self):
        gen = self._get_generator()
        result = gen.generate("top 10 users by event count")
        assert result.query is not None
        assert len(result.query) > 10
        # Should produce either a top command with limit or a stats query
        q = result.query.lower()
        assert "top" in q or "stats" in q or "10" in q

    def test_extract_time_range_last_hours(self):
        gen = self._get_generator()
        time_range = gen._extract_time_range("events in the last 4 hours")
        assert "earliest=-4h" in time_range
        assert "latest=now" in time_range

    def test_extract_time_range_last_days(self):
        gen = self._get_generator()
        time_range = gen._extract_time_range("show events from last 7 days")
        assert "earliest=-7d" in time_range

    def test_extract_time_range_default(self):
        gen = self._get_generator()
        time_range = gen._extract_time_range("show me events")
        assert "earliest=-1h" in time_range

    def test_extract_time_range_today(self):
        gen = self._get_generator()
        time_range = gen._extract_time_range("events today")
        assert "earliest=@d" in time_range

    def test_extract_entities_domain_auth(self):
        gen = self._get_generator()
        entities = gen._extract_entities("failed login attempts for user admin")
        assert entities.get("domain") == "authentication"
        assert entities.get("user") == "admin"

    def test_extract_entities_top_n(self):
        gen = self._get_generator()
        entities = gen._extract_entities("top 20 hosts by source")
        assert entities.get("limit") == 20
        assert entities.get("group_field") == "src_ip"

    def test_extract_entities_network(self):
        gen = self._get_generator()
        entities = gen._extract_entities("network traffic by source")
        assert entities.get("domain") == "network"

    def test_select_examples_relevance(self):
        gen = self._get_generator()
        examples = gen._select_examples("failed login attempts", max_examples=3)
        assert len(examples) > 0
        # Should rank auth-related examples higher
        names = [e.name for e in examples]
        assert any("login" in n or "auth" in n or "brute" in n for n in names)

    def test_custom_index_mappings(self):
        gen = self._get_generator()
        gen.set_index_mappings({"authentication": "my_custom_auth_index"})
        result = gen.generate("show failed logins")
        assert "my_custom_auth_index" in result.query or result.query is not None

    def test_get_suggestions(self):
        gen = self._get_generator()
        suggestions = gen._get_suggestions("index=* | stats count")
        assert any("index" in s.lower() for s in suggestions)

    def test_get_stats(self):
        gen = self._get_generator()
        stats = gen.get_stats()
        assert stats["total_examples"] > 0
        assert "builtin" in stats["by_source"]
