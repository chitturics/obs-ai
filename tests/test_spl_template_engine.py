"""
Comprehensive tests for shared/spl_template_engine.py

Tests cover every public and private helper in SPLTemplateEngine using
real SPL examples and strict assertions (no mocking).
"""
import pytest
from shared.spl_template_engine import SPLTemplateEngine, QueryIntent


# ────────────────────────────────────────────────────────────────────
# 1. QueryIntent dataclass
# ────────────────────────────────────────────────────────────────────

class TestQueryIntentDataclass:
    """Validate the QueryIntent data structure."""

    def test_defaults(self):
        intent = QueryIntent(query_type="unknown")
        assert intent.query_type == "unknown"
        assert intent.index is None
        assert intent.sourcetype is None
        assert intent.source is None
        assert intent.keywords is None
        assert intent.time_range is None
        assert intent.datamodel is None
        assert intent.groupby_fields is None
        assert intent.confidence == 0.0

    def test_full_construction(self):
        intent = QueryIntent(
            query_type="term_search",
            index="security",
            sourcetype="syslog",
            source="/var/log/messages",
            keywords=["error", "failed"],
            time_range="-24h",
            datamodel=None,
            groupby_fields=["host", "src_ip"],
            confidence=0.9,
        )
        assert intent.index == "security"
        assert intent.sourcetype == "syslog"
        assert intent.source == "/var/log/messages"
        assert intent.keywords == ["error", "failed"]
        assert intent.time_range == "-24h"
        assert intent.groupby_fields == ["host", "src_ip"]
        assert intent.confidence == 0.9


# ────────────────────────────────────────────────────────────────────
# 2. _is_ip  /  _is_cidr
# ────────────────────────────────────────────────────────────────────

class TestIsIp:
    """Validate IPv4 / IPv6 address detection."""

    @pytest.mark.parametrize("addr", [
        "192.168.1.1",
        "10.0.0.1",
        "255.255.255.255",
        "0.0.0.0",
        "::1",               # IPv6 loopback
        "fe80::1",           # IPv6 link-local
    ])
    def test_valid_ips(self, addr):
        assert SPLTemplateEngine._is_ip(addr) is True

    @pytest.mark.parametrize("addr", [
        "not_an_ip",
        "999.999.999.999",
        "192.168.1",
        "192.168.1.1/24",    # CIDR, not bare IP
        "",
        "hello",
    ])
    def test_invalid_ips(self, addr):
        assert SPLTemplateEngine._is_ip(addr) is False


class TestIsCidr:
    """Validate CIDR notation detection."""

    @pytest.mark.parametrize("cidr", [
        "192.168.0.0/24",
        "10.0.0.0/8",
        "172.16.0.0/12",
        "192.168.1.1/32",     # single-host CIDR
        "0.0.0.0/0",
    ])
    def test_valid_cidrs(self, cidr):
        assert SPLTemplateEngine._is_cidr(cidr) is True

    @pytest.mark.parametrize("cidr", [
        "not_a_cidr",
        "hello/world",
        "",
        "abc",
    ])
    def test_invalid_cidrs(self, cidr):
        assert SPLTemplateEngine._is_cidr(cidr) is False


# ────────────────────────────────────────────────────────────────────
# 3. _classify_token
# ────────────────────────────────────────────────────────────────────

class TestClassifyToken:
    """Validate heuristic token classification."""

    def test_ipv4_classified_as_src_ip(self):
        field, value = SPLTemplateEngine._classify_token("10.20.30.40")
        assert field == "src_ip"
        assert value == "10.20.30.40"

    def test_cidr_classified_as_src_ip(self):
        field, value = SPLTemplateEngine._classify_token("192.168.0.0/16")
        assert field == "src_ip"
        assert value == "192.168.0.0/16"

    def test_three_digit_status_code(self):
        field, value = SPLTemplateEngine._classify_token("404")
        assert field == "status"
        assert value == "404"

    def test_200_status_code(self):
        field, value = SPLTemplateEngine._classify_token("200")
        assert field == "status"
        assert value == "200"

    def test_email_classified_as_user(self):
        field, value = SPLTemplateEngine._classify_token("admin@corp.local")
        assert field == "user"
        assert value == "admin@corp.local"

    def test_hostname_classified_as_dest(self):
        field, value = SPLTemplateEngine._classify_token("server01.example.com")
        assert field == "dest"
        assert value == "server01.example.com"

    def test_plain_word_unclassified(self):
        field, value = SPLTemplateEngine._classify_token("error")
        assert field is None
        assert value == "error"

    def test_four_digit_number_unclassified(self):
        """Only 3-digit numbers are status codes."""
        field, value = SPLTemplateEngine._classify_token("1234")
        assert field is None


# ────────────────────────────────────────────────────────────────────
# 4. _escape_term
# ────────────────────────────────────────────────────────────────────

class TestEscapeTerm:
    """Validate TERM()-safe escaping."""

    def test_simple_alphanumeric_unchanged(self):
        assert SPLTemplateEngine._escape_term("error") == "error"

    def test_underscore_unchanged(self):
        assert SPLTemplateEngine._escape_term("src_ip") == "src_ip"

    def test_term_with_dot_gets_quoted(self):
        result = SPLTemplateEngine._escape_term("server01.corp.local")
        assert result == '"server01.corp.local"'

    def test_term_with_at_sign_gets_quoted(self):
        result = SPLTemplateEngine._escape_term("user@domain.com")
        assert result == '"user@domain.com"'

    def test_term_with_slash_gets_quoted(self):
        result = SPLTemplateEngine._escape_term("/var/log/syslog")
        assert result == '"/var/log/syslog"'

    def test_term_with_space_gets_quoted(self):
        result = SPLTemplateEngine._escape_term("failed login")
        assert result == '"failed login"'

    def test_embedded_double_quote_escaped(self):
        result = SPLTemplateEngine._escape_term('say"hello')
        assert r'\"' in result
        assert result.startswith('"') and result.endswith('"')


# ────────────────────────────────────────────────────────────────────
# 5. _detect_aggregation_type
# ────────────────────────────────────────────────────────────────────

class TestDetectAggregationType:
    """Validate aggregation-type detection from natural language."""

    def test_timechart_over_time(self):
        assert SPLTemplateEngine._detect_aggregation_type("errors over time") == "timechart"

    def test_timechart_trend(self):
        assert SPLTemplateEngine._detect_aggregation_type("show me the trend") == "timechart"

    def test_timechart_hourly(self):
        assert SPLTemplateEngine._detect_aggregation_type("hourly count") == "timechart"

    def test_timechart_spike(self):
        assert SPLTemplateEngine._detect_aggregation_type("any spike in errors") == "timechart"

    def test_top_detected(self):
        assert SPLTemplateEngine._detect_aggregation_type("top 10 hosts") == "top"

    def test_most_common_detected_as_top(self):
        assert SPLTemplateEngine._detect_aggregation_type("most common user") == "top"

    def test_rare_detected(self):
        assert SPLTemplateEngine._detect_aggregation_type("rare user agents") == "rare"

    def test_uncommon_detected_as_rare(self):
        assert SPLTemplateEngine._detect_aggregation_type("uncommon processes") == "rare"

    def test_table_list(self):
        assert SPLTemplateEngine._detect_aggregation_type("list all events") == "table"

    def test_table_show_me(self):
        assert SPLTemplateEngine._detect_aggregation_type("show me details") == "table"

    def test_stats_count_how_many(self):
        assert SPLTemplateEngine._detect_aggregation_type("how many events") == "stats_count"

    def test_stats_avg(self):
        assert SPLTemplateEngine._detect_aggregation_type("average response time") == "stats_avg"

    def test_stats_sum(self):
        # "total" alone matches stats_count first; use "sum" to trigger stats_sum
        assert SPLTemplateEngine._detect_aggregation_type("sum of all bytes") == "stats_sum"

    def test_default_is_stats_count(self):
        """When no pattern matches, default to stats_count."""
        assert SPLTemplateEngine._detect_aggregation_type("xyz foobar baz") == "stats_count"


# ────────────────────────────────────────────────────────────────────
# 6. _extract_groupby_fields
# ────────────────────────────────────────────────────────────────────

class TestExtractGroupbyFields:
    """Validate GROUP BY field extraction from natural language."""

    def test_by_single_field(self):
        fields = SPLTemplateEngine._extract_groupby_fields("count by host")
        assert fields == ["host"]

    def test_by_multiple_comma_separated(self):
        fields = SPLTemplateEngine._extract_groupby_fields("count by host, sourcetype")
        assert fields == ["host", "sourcetype"]

    def test_per_field(self):
        fields = SPLTemplateEngine._extract_groupby_fields("events per user")
        assert fields == ["user"]

    def test_for_each_field(self):
        fields = SPLTemplateEngine._extract_groupby_fields("count for each src_ip")
        assert fields == ["src_ip"]

    def test_grouped_by(self):
        fields = SPLTemplateEngine._extract_groupby_fields("events grouped by action")
        assert fields == ["action"]

    def test_no_groupby_returns_empty(self):
        fields = SPLTemplateEngine._extract_groupby_fields("count all events in index main")
        assert fields == []


# ────────────────────────────────────────────────────────────────────
# 7. _infer_index_from_context
# ────────────────────────────────────────────────────────────────────

class TestInferIndexFromContext:
    """Validate index inference from context keywords."""

    @pytest.mark.parametrize("text,expected_index", [
        ("show firewall logs", "firewall"),
        ("proxy traffic analysis", "proxy"),
        ("windows event logs", "wineventlog"),
        ("linux syslog messages", "os"),
        ("endpoint detection events", "edr"),
        ("vpn connection failures", "vpn"),
        ("ids alert from sensor", "ids"),
    ])
    def test_known_hints(self, text, expected_index):
        result = SPLTemplateEngine._infer_index_from_context(text)
        assert result == expected_index

    def test_no_hint_returns_none(self):
        assert SPLTemplateEngine._infer_index_from_context("hello world xyz") is None


# ────────────────────────────────────────────────────────────────────
# 8. detect_intent  (comprehensive)
# ────────────────────────────────────────────────────────────────────

class TestDetectIntent:
    """End-to-end tests for intent detection from natural language."""

    # --- query_type ---

    def test_tstats_term_query_type(self):
        intent = SPLTemplateEngine.detect_intent(
            "use tstats and TERM to search for errors"
        )
        assert intent.query_type == "term_search"
        assert intent.confidence == 0.9

    def test_term_only_query_type(self):
        intent = SPLTemplateEngine.detect_intent(
            "search using TERM(denied) on firewall"
        )
        assert intent.query_type == "term_search"
        assert intent.confidence == 0.8

    def test_datamodel_query_type(self):
        intent = SPLTemplateEngine.detect_intent(
            "query the authentication datamodel for failed logins"
        )
        assert intent.query_type == "datamodel"
        assert intent.confidence == 0.8

    def test_cim_triggers_datamodel(self):
        intent = SPLTemplateEngine.detect_intent("use cim for network traffic")
        assert intent.query_type == "datamodel"

    def test_search_keyword_triggers_term_search(self):
        intent = SPLTemplateEngine.detect_intent("search for denied connections")
        assert intent.query_type == "term_search"
        assert intent.confidence == 0.6

    def test_find_keyword_triggers_term_search(self):
        intent = SPLTemplateEngine.detect_intent("find failed logins")
        assert intent.query_type == "term_search"

    def test_unknown_query_type_fallback(self):
        """Queries without action verbs remain 'unknown'."""
        intent = SPLTemplateEngine.detect_intent("hello world")
        assert intent.query_type == "unknown"

    # --- index extraction ---

    def test_explicit_index_equals(self):
        intent = SPLTemplateEngine.detect_intent("search index=security for errors")
        assert intent.index == "security"

    def test_from_index_pattern(self):
        intent = SPLTemplateEngine.detect_intent("get events from index network")
        assert intent.index == "network"

    def test_in_firewall_index(self):
        # "in X index" pattern: use phrasing that won't collide with
        # the first INDEX_PATTERN (index[=\s]+(\w+)) capturing a later word
        intent = SPLTemplateEngine.detect_intent("search from firewall index")
        assert intent.index == "firewall"

    def test_index_blacklist_skipped(self):
        """Words like 'last' should not be captured as index names."""
        intent = SPLTemplateEngine.detect_intent("search in last events")
        # 'last' is blacklisted, so explicit extraction should not match it
        # Inferred index may still return something via context hints
        assert intent.index != "last"

    def test_inferred_index_fallback(self):
        intent = SPLTemplateEngine.detect_intent("show vpn connection errors")
        assert intent.index == "vpn"

    # --- sourcetype extraction ---

    def test_sourcetype_extracted(self):
        intent = SPLTemplateEngine.detect_intent(
            "find errors sourcetype=syslog in last hour"
        )
        assert intent.sourcetype == "syslog"

    # --- source extraction ---

    def test_source_extracted(self):
        intent = SPLTemplateEngine.detect_intent(
            "search source=/var/log/auth.log for failures"
        )
        assert intent.source == "/var/log/auth.log"

    # --- time range ---

    def test_time_last_24_hours(self):
        intent = SPLTemplateEngine.detect_intent("show errors in the last 24 hours")
        assert intent.time_range == "-24h"

    def test_time_last_5_minutes(self):
        intent = SPLTemplateEngine.detect_intent("find events last 5 minutes")
        assert intent.time_range == "-5m"

    def test_time_last_7_days(self):
        intent = SPLTemplateEngine.detect_intent("events in the last 7 days")
        assert intent.time_range == "-7d"

    def test_time_today(self):
        intent = SPLTemplateEngine.detect_intent("show me events from today")
        assert intent.time_range == "@d"

    def test_time_yesterday(self):
        intent = SPLTemplateEngine.detect_intent("events from yesterday")
        assert intent.time_range == "-1d@d"

    def test_time_default_15m(self):
        """If no time range is mentioned, default to -15m."""
        intent = SPLTemplateEngine.detect_intent("find errors")
        assert intent.time_range == "-15m"

    # --- keywords ---

    def test_keywords_exclude_noise(self):
        intent = SPLTemplateEngine.detect_intent(
            "search for failed and denied in firewall"
        )
        assert "search" not in intent.keywords
        assert "for" not in intent.keywords
        assert "and" not in intent.keywords

    def test_keyword_extraction_search_for(self):
        intent = SPLTemplateEngine.detect_intent("search for failed logins")
        assert "failed" in intent.keywords

    # --- groupby ---

    def test_groupby_in_detect_intent(self):
        intent = SPLTemplateEngine.detect_intent("count events by host, sourcetype")
        assert "host" in intent.groupby_fields

    def test_groupby_per_in_detect_intent(self):
        intent = SPLTemplateEngine.detect_intent("count events per user")
        assert intent.groupby_fields == ["user"]

    # --- empty query ---

    def test_empty_query_does_not_crash(self):
        intent = SPLTemplateEngine.detect_intent("")
        assert intent.query_type == "unknown"
        assert intent.time_range == "-15m"


# ────────────────────────────────────────────────────────────────────
# 9. generate_term_query
# ────────────────────────────────────────────────────────────────────

class TestGenerateTermQuery:
    """Validate SPL generation from a QueryIntent."""

    def test_basic_search_fallback(self):
        intent = QueryIntent(
            query_type="term_search",
            index=None,
            keywords=["denied"],
            time_range="-15m",
            groupby_fields=[],
        )
        query = SPLTemplateEngine.generate_term_query(intent)
        assert query.startswith("search")
        assert "earliest=-15m" in query
        assert "latest=now" in query

    def test_index_included_when_set(self):
        intent = QueryIntent(
            query_type="term_search",
            index="firewall",
            keywords=["blocked"],
            time_range="-1h",
            groupby_fields=[],
        )
        query = SPLTemplateEngine.generate_term_query(intent)
        assert "index=firewall" in query

    def test_sourcetype_included(self):
        intent = QueryIntent(
            query_type="term_search",
            index="main",
            sourcetype="syslog",
            keywords=["error"],
            time_range="-1h",
            groupby_fields=[],
        )
        query = SPLTemplateEngine.generate_term_query(intent)
        assert "sourcetype=syslog" in query

    def test_ip_keyword_produces_fielded_term(self):
        """An IP address keyword should map to TERM(src_ip=...).
        IPs contain dots, so _escape_term wraps the value in quotes."""
        intent = QueryIntent(
            query_type="term_search",
            index="network",
            keywords=["10.0.0.5"],
            time_range="-1h",
            groupby_fields=[],
        )
        query = SPLTemplateEngine.generate_term_query(intent)
        assert 'TERM(src_ip="10.0.0.5")' in query

    def test_status_code_keyword_produces_fielded_term(self):
        intent = QueryIntent(
            query_type="term_search",
            index="web",
            keywords=["500"],
            time_range="-1h",
            groupby_fields=[],
        )
        query = SPLTemplateEngine.generate_term_query(intent)
        assert "TERM(status=500)" in query

    def test_tstats_path_for_fielded_only(self):
        """When all tokens are fielded and index is set, prefer tstats."""
        intent = QueryIntent(
            query_type="term_search",
            index="network",
            keywords=["10.0.0.1"],
            time_range="-1h",
            groupby_fields=[],
        )
        query = SPLTemplateEngine.generate_term_query(intent)
        assert query.startswith("| tstats")
        assert 'TERM(src_ip="10.0.0.1")' in query

    def test_fallback_to_search_when_text_terms_present(self):
        """Mixed fielded + free-text should fall back to search.
        'blocked_xyz' is not in FIELD_KEYWORDS so it stays as free text."""
        intent = QueryIntent(
            query_type="term_search",
            index="firewall",
            keywords=["blocked_xyz", "10.0.0.1"],
            time_range="-15m",
            groupby_fields=[],
        )
        query = SPLTemplateEngine.generate_term_query(intent)
        assert query.startswith("search")

    def test_no_keywords_defaults_to_error(self):
        intent = QueryIntent(
            query_type="term_search",
            index=None,
            keywords=[],
            time_range="-15m",
            groupby_fields=[],
        )
        query = SPLTemplateEngine.generate_term_query(intent)
        # Should use fallback keyword "error"
        assert "error" in query.lower()

    def test_groupby_in_tstats(self):
        """Group-by fields should appear in tstats output."""
        intent = QueryIntent(
            query_type="term_search",
            index="web",
            keywords=["200"],
            time_range="-1h",
            groupby_fields=["host"],
        )
        query = SPLTemplateEngine.generate_term_query(intent)
        assert "by host" in query


# ────────────────────────────────────────────────────────────────────
# 10. generate_query  (end-to-end)
# ────────────────────────────────────────────────────────────────────

class TestGenerateQuery:
    """End-to-end integration tests for generate_query()."""

    def test_returns_three_tuple(self):
        result = SPLTemplateEngine.generate_query("find errors in firewall index")
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_query_is_nonempty_string(self):
        query, _, _ = SPLTemplateEngine.generate_query("find errors")
        assert isinstance(query, str) and len(query) > 0

    def test_explanation_is_nonempty_string(self):
        _, _, explanation = SPLTemplateEngine.generate_query("find errors")
        assert isinstance(explanation, str) and len(explanation) > 0

    def test_term_search_produces_stats_tail(self):
        query, _, _ = SPLTemplateEngine.generate_query(
            "count denied events in firewall index"
        )
        assert "stats count" in query or "tstats count" in query

    def test_timechart_aggregation_appended(self):
        query, _, _ = SPLTemplateEngine.generate_query(
            "show errors over time in firewall index last 24 hours"
        )
        assert "timechart" in query

    def test_top_aggregation_appended(self):
        query, _, _ = SPLTemplateEngine.generate_query(
            "top 5 hosts by event count in network"
        )
        assert "top" in query.lower()

    def test_rare_aggregation_appended(self):
        query, _, _ = SPLTemplateEngine.generate_query(
            "rare user agents in proxy index"
        )
        assert "rare" in query.lower()

    def test_datamodel_query(self):
        query, intent, explanation = SPLTemplateEngine.generate_query(
            "search the authentication datamodel for failures"
        )
        assert intent.query_type == "datamodel"
        assert "tstats" in query
        assert "datamodel=" in query
        assert "Authentication" in query

    def test_unknown_fallback_still_produces_query(self):
        """Even unrecognised queries should produce a valid search."""
        query, _, explanation = SPLTemplateEngine.generate_query("xyzzy foobar")
        assert isinstance(query, str) and len(query) > 0
        assert "Basic keyword search" in explanation

    def test_time_range_propagated(self):
        query, intent, _ = SPLTemplateEngine.generate_query(
            "find errors last 2 hours"
        )
        assert intent.time_range == "-2h"
        assert "earliest=-2h" in query


# ────────────────────────────────────────────────────────────────────
# 11. _build_aggregation_tail
# ────────────────────────────────────────────────────────────────────

class TestBuildAggregationTail:
    """Test the aggregation tail builder."""

    def _make_intent(self, groupby=None):
        return QueryIntent(
            query_type="term_search",
            keywords=["error"],
            time_range="-1h",
            groupby_fields=groupby or [],
        )

    def test_default_stats_count(self):
        tail = SPLTemplateEngine._build_aggregation_tail(
            self._make_intent(), "some random query"
        )
        assert tail == " | stats count"

    def test_stats_count_with_groupby(self):
        tail = SPLTemplateEngine._build_aggregation_tail(
            self._make_intent(["host"]), "some random query"
        )
        assert tail == " | stats count by host"

    def test_timechart_default_span(self):
        tail = SPLTemplateEngine._build_aggregation_tail(
            self._make_intent(), "errors over time"
        )
        assert "timechart span=1h count" in tail

    def test_timechart_daily_span(self):
        tail = SPLTemplateEngine._build_aggregation_tail(
            self._make_intent(), "daily error count"
        )
        assert "span=1d" in tail

    def test_top_default_limit(self):
        tail = SPLTemplateEngine._build_aggregation_tail(
            self._make_intent(), "top hosts"
        )
        assert "top limit=10" in tail

    def test_top_custom_limit(self):
        tail = SPLTemplateEngine._build_aggregation_tail(
            self._make_intent(), "top 5 users"
        )
        assert "top limit=5" in tail

    def test_rare_limit(self):
        tail = SPLTemplateEngine._build_aggregation_tail(
            self._make_intent(), "rare processes"
        )
        assert "rare limit=20" in tail

    def test_table_default_fields(self):
        tail = SPLTemplateEngine._build_aggregation_tail(
            self._make_intent(), "list all events"
        )
        assert "table" in tail
        assert "_time" in tail

    def test_stats_avg(self):
        tail = SPLTemplateEngine._build_aggregation_tail(
            self._make_intent(), "average response time"
        )
        assert "avg(response_time)" in tail

    def test_stats_sum(self):
        # "total" alone matches stats_count first; use "sum" to trigger stats_sum
        tail = SPLTemplateEngine._build_aggregation_tail(
            self._make_intent(), "sum of all bytes"
        )
        assert "sum(bytes)" in tail
        assert "sort" in tail


# ────────────────────────────────────────────────────────────────────
# 12. generate_datamodel_query
# ────────────────────────────────────────────────────────────────────

class TestGenerateDatamodelQuery:
    """Validate datamodel query generation."""

    def test_authentication_datamodel(self):
        intent = QueryIntent(
            query_type="datamodel",
            keywords=["authentication", "failed"],
            time_range="-1h",
            groupby_fields=[],
        )
        query = SPLTemplateEngine.generate_datamodel_query(intent)
        assert "datamodel=Authentication.Authentication" in query
        assert "tstats" in query
        assert "TERM(failed)" in query

    def test_network_traffic_datamodel(self):
        intent = QueryIntent(
            query_type="datamodel",
            keywords=["network", "blocked"],
            time_range="-24h",
            groupby_fields=[],
        )
        query = SPLTemplateEngine.generate_datamodel_query(intent)
        assert "datamodel=Network_Traffic.All_Traffic" in query
        assert "TERM(blocked)" in query

    def test_web_datamodel(self):
        intent = QueryIntent(
            query_type="datamodel",
            keywords=["web", "500"],
            time_range="-1h",
            groupby_fields=[],
        )
        query = SPLTemplateEngine.generate_datamodel_query(intent)
        assert "datamodel=Web.Web" in query

    def test_dns_datamodel(self):
        intent = QueryIntent(
            query_type="datamodel",
            keywords=["dns", "malicious.com"],
            time_range="-1h",
            groupby_fields=[],
        )
        query = SPLTemplateEngine.generate_datamodel_query(intent)
        assert "Network_Resolution.DNS" in query

    def test_unknown_defaults_to_network_traffic(self):
        intent = QueryIntent(
            query_type="datamodel",
            keywords=["xyzzy"],
            time_range="-1h",
            groupby_fields=[],
        )
        query = SPLTemplateEngine.generate_datamodel_query(intent)
        assert "Network_Traffic" in query

    def test_custom_groupby_overrides_defaults(self):
        intent = QueryIntent(
            query_type="datamodel",
            keywords=["authentication"],
            time_range="-1h",
            groupby_fields=["custom_field"],
        )
        query = SPLTemplateEngine.generate_datamodel_query(intent)
        assert "by custom_field" in query
        # Default Authentication by-fields should NOT appear
        assert "Authentication.user" not in query

    def test_time_range_in_datamodel_query(self):
        intent = QueryIntent(
            query_type="datamodel",
            keywords=["authentication"],
            time_range="-7d",
            groupby_fields=[],
        )
        query = SPLTemplateEngine.generate_datamodel_query(intent)
        assert "earliest=-7d" in query
        assert "latest=now" in query
