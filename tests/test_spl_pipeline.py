"""
Comprehensive test suite for SPL generation pipeline improvements.

Tests:
1. NLP-to-SPL direct match patterns
2. NLP-to-SPL intent detection
3. NLP-to-SPL time extraction
4. NLP-to-SPL builtin examples coverage
5. Template engine intent detection
6. Template engine aggregation variety
7. Template engine groupby detection
8. Template engine index hint inference
9. Template engine noise word filtering
10. Template engine datamodel query generation
11. Query router — clarification trap fix
12. Query router — NLP-to-SPL pattern expansion
13. Query router — SPL extraction
14. NLP-to-SPL suggestions quality
15. Robust analyzer checks
"""
import sys
import os

import pytest

# Add shared and chat_app to path to handle imports
_PROJECT_ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "shared"))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "chat_app"))
sys.path.insert(0, _PROJECT_ROOT)

_IMPORT_ERROR = ""
try:
    from nlp_to_spl import NLPtoSPL, SPLGenerationResult  # noqa: F401
    from spl_template_engine import SPLTemplateEngine, QueryIntent  # noqa: F401
    from spl_robust_analyzer import analyze_spl
    from chat_app.query_router_handler import route_query, extract_spl_from_input
    _IMPORTS_AVAILABLE = True
except (ImportError, TypeError, Exception) as exc:
    _IMPORTS_AVAILABLE = False
    _IMPORT_ERROR = str(exc)

pytestmark = pytest.mark.skipif(
    not _IMPORTS_AVAILABLE,
    reason=f"SPL pipeline dependencies not available: {_IMPORT_ERROR}",
)


# ═══════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def nlp_generator():
    """Shared NLPtoSPL instance for all tests in this module."""
    return NLPtoSPL()


# ═══════════════════════════════════════════════════════════
# 1. NLP-to-SPL: Direct Match Patterns
# ═══════════════════════════════════════════════════════════

DIRECT_MATCH_CASES = [
    ("failed logins in the last hour", "EventCode=4625", "failed_logins"),
    ("successful login last 24 hours", "EventCode=4624", "successful_login"),
    ("brute force detection", "where attempts > 5", "brute_force"),
    ("account lockout events", "stats count by host", "account_lockout"),
    ("password change", "EventCode=4719", "password_change"),
    ("privilege escalation", "EventCode=4728", "privilege_escalation"),
    ("firewall denied connections", "TERM(action=denied)", "firewall_denied"),
    ("firewall allowed traffic", "index=firewall", "firewall_allowed"),
    ("dns queries last hour", "index=dns", "dns_queries"),
    ("nxdomain failures", "index=dns", "dns_nxdomain"),
    ("http errors", "TERM(error)", "http_errors"),
    ("slow response time", "response_time", "slow_response"),
    ("powershell activity", "PowerShell", "powershell"),
    ("process execution events", "process_name", "process_exec"),
    ("error count", "stats count by host", "error_count"),
    ("error trend over time", "timechart", "error_trend"),
    ("top users", "top limit=10 user", "top_users"),
    ("top sourcetypes", "top limit=10 sourcetype", "top_sourcetypes"),
    ("aws cloudtrail errors", "TERM(error)", "aws_cloudtrail"),
    ("azure signin failures", "ResultType", "azure_signin"),
    ("login trend over time", "timechart", "login_trend"),
    ("vpn connections", "index=vpn", "vpn"),
]


@pytest.mark.parametrize("query_text,expected_fragment,label", DIRECT_MATCH_CASES, ids=[c[2] for c in DIRECT_MATCH_CASES])
def test_direct_match_patterns(nlp_generator, query_text, expected_fragment, label):
    result = nlp_generator.generate(query_text)
    assert expected_fragment in result.query, f"Expected '{expected_fragment}' in: {result.query}"


# ═══════════════════════════════════════════════════════════
# 2. NLP-to-SPL: Intent Detection
# ═══════════════════════════════════════════════════════════

INTENT_CASES = [
    ("count of events by host", "count_events"),
    ("error trend over time", "timechart"),
    ("failed login attempts", "failed_logins"),
    ("firewall denied traffic", "firewall_denies"),
    ("malware detection alert", "search_events"),
    ("dns query lookup", "dns_queries"),
    ("http status code 404", "search_events"),
    ("process execution sysmon", "search_events"),
    ("rare events today", "rare_events"),
]


@pytest.mark.parametrize("query_text,expected_intent", INTENT_CASES)
def test_intent_detection(nlp_generator, query_text, expected_intent):
    detected = nlp_generator._detect_intent(query_text)
    # _detect_intent may return SPLIntent enum; compare against .value
    detected_value = detected.value if hasattr(detected, "value") else detected
    assert detected_value == expected_intent, f"Expected {expected_intent}, got {detected}"


# ═══════════════════════════════════════════════════════════
# 3. NLP-to-SPL: Time Extraction
# ═══════════════════════════════════════════════════════════

TIME_CASES = [
    ("last 15 minutes", "earliest=-15m"),
    ("last 4 hours", "earliest=-4h"),
    ("last 7 days", "earliest=-7d"),
    ("last 24 hours", "earliest=-24h"),
    ("past day", "earliest=-24h"),
    ("last week", "earliest=-7d"),
    ("last month", "earliest=-30d"),
    ("today", "earliest=@d"),
    ("all time", "earliest=0"),
    ("no time mentioned", "earliest=-1h"),
]


@pytest.mark.parametrize("query_text,expected_fragment", TIME_CASES)
def test_time_extraction(nlp_generator, query_text, expected_fragment):
    result = nlp_generator._extract_time_range(query_text.lower())
    assert expected_fragment in result, f"Expected '{expected_fragment}' in: {result}"


# ═══════════════════════════════════════════════════════════
# 4. NLP-to-SPL: Builtin Examples Coverage
# ═══════════════════════════════════════════════════════════

def test_builtin_examples_count(nlp_generator):
    stats = nlp_generator.get_stats()
    assert stats["total_examples"] >= 20, f"Expected >= 20 examples, got {stats['total_examples']}"


REQUIRED_INTENTS = ["aggregation", "authentication", "network", "timechart", "security", "dns", "web", "endpoint"]


@pytest.mark.parametrize("intent_name", REQUIRED_INTENTS)
def test_builtin_examples_intent_diversity(nlp_generator, intent_name):
    stats = nlp_generator.get_stats()
    intents_present = set(stats["by_intent"].keys())
    assert intent_name in intents_present, f"Intent '{intent_name}' missing. Present: {intents_present}"


# ═══════════════════════════════════════════════════════════
# 5. Template Engine: Intent Detection
# ═══════════════════════════════════════════════════════════

TE_INTENT_CASES = [
    ("search for errors in firewall index last 5 minutes", "term_search", "firewall"),
    ("find denied events in network index", "term_search", "network"),
    ("use datamodel for authentication", "datamodel", None),
    ("show me events from proxy index", "term_search", "proxy"),
    ("count errors by host", "term_search", None),
    ("list all VPN connections", "term_search", "vpn"),
]


@pytest.mark.parametrize("query_text,expected_type,expected_index", TE_INTENT_CASES)
def test_template_engine_intent(query_text, expected_type, expected_index):
    intent = SPLTemplateEngine.detect_intent(query_text)
    assert intent.query_type == expected_type, f"Expected type {expected_type}, got {intent.query_type}"
    if expected_index:
        assert intent.index == expected_index, f"Expected index {expected_index}, got {intent.index}"


# ═══════════════════════════════════════════════════════════
# 6. Template Engine: Aggregation Variety
# ═══════════════════════════════════════════════════════════

AGG_CASES = [
    ("show me error trend over time in main index", "timechart"),
    ("top 5 users in main index", "top"),
    ("rare sourcetypes in main index", "rare"),
    ("list events from firewall index", "table"),
    ("count errors by host in main index", "stats count"),
]


@pytest.mark.parametrize("query_text,expected_agg", AGG_CASES)
def test_template_engine_aggregation(query_text, expected_agg):
    query, intent, explanation = SPLTemplateEngine.generate_query(query_text)
    normalized_query = query.replace(" ", "").lower()
    normalized_agg = expected_agg.replace(" ", "")
    assert normalized_agg in normalized_query or expected_agg.split("_")[0] in query.lower(), \
        f"Expected '{expected_agg}' in query: {query}"


# ═══════════════════════════════════════════════════════════
# 7. Template Engine: Groupby Detection
# ═══════════════════════════════════════════════════════════

GROUPBY_CASES = [
    ("count events by user in main index", ["user"]),
    ("count by host, sourcetype in main index", ["host", "sourcetype"]),
    ("errors per host in network index", ["host"]),
]


@pytest.mark.parametrize("query_text,expected_fields", GROUPBY_CASES)
def test_template_engine_groupby(query_text, expected_fields):
    intent = SPLTemplateEngine.detect_intent(query_text)
    assert intent.groupby_fields == expected_fields, f"Expected {expected_fields}, got {intent.groupby_fields}"


# ═══════════════════════════════════════════════════════════
# 8. Template Engine: Index Hint Inference
# ═══════════════════════════════════════════════════════════

HINT_CASES = [
    ("search for errors in firewall logs", "firewall"),
    ("find windows events", "wineventlog"),
    ("show endpoint data", "edr"),
    ("get vpn connections", "vpn"),
    ("linux log errors", "os"),
]


@pytest.mark.parametrize("query_text,expected_index", HINT_CASES)
def test_template_engine_index_hint(query_text, expected_index):
    intent = SPLTemplateEngine.detect_intent(query_text)
    assert intent.index == expected_index, f"Expected index={expected_index}, got {intent.index}"


# ═══════════════════════════════════════════════════════════
# 9. Template Engine: Noise Word Filtering
# ═══════════════════════════════════════════════════════════

NOISE_CASES = [
    ("search for errors in firewall index", ["errors"]),
    ("show me denied events", ["denied"]),
    ("find failed logins", ["failed"]),
]


@pytest.mark.parametrize("query_text,should_contain", NOISE_CASES)
def test_template_engine_noise_filtering(query_text, should_contain):
    intent = SPLTemplateEngine.detect_intent(query_text)
    for keyword in should_contain:
        assert keyword in intent.keywords, f"Expected '{keyword}' in keywords: {intent.keywords}"


# ═══════════════════════════════════════════════════════════
# 10. Template Engine: Datamodel Queries
# ═══════════════════════════════════════════════════════════

DATAMODEL_CASES = [
    ("use datamodel for authentication", "Authentication"),
    ("cim network traffic", "Network_Traffic"),
    ("datamodel web proxy", "Web"),
    ("cim dns queries", "Network_Resolution"),
    ("datamodel endpoint processes", "Endpoint"),
    ("cim email events", "Email"),
]


@pytest.mark.parametrize("query_text,expected_dm", DATAMODEL_CASES)
def test_template_engine_datamodel(query_text, expected_dm):
    query, intent, explanation = SPLTemplateEngine.generate_query(query_text)
    assert expected_dm in query, f"Expected '{expected_dm}' in query: {query}"


# ═══════════════════════════════════════════════════════════
# 11. Query Router: Clarification Trap Fix
# ═══════════════════════════════════════════════════════════

SHOULD_NOT_CLARIFY = [
    "show me this error in the firewall",
    "what is that sourcetype",
    "find those denied events in firewall",
    "count by host in main index",
    "show me failed logins in the last hour",
    "find firewall errors in the last day",
    "show top users by event count",
]


@pytest.mark.parametrize("query_text", SHOULD_NOT_CLARIFY)
def test_no_false_clarification(query_text):
    plan = route_query(query_text)
    assert plan.intent != "clarification", f"Unexpected clarification for: '{query_text}' (intent={plan.intent})"


SHOULD_CLARIFY = [
    "x",
]


@pytest.mark.parametrize("query_text", SHOULD_CLARIFY)
def test_triggers_clarification(query_text):
    plan = route_query(query_text)
    assert plan.intent == "clarification", f"Expected clarification for '{query_text}', got {plan.intent}"


# ═══════════════════════════════════════════════════════════
# 12. Query Router: NLP-to-SPL Pattern Routing
# ═══════════════════════════════════════════════════════════

NLP_ROUTE_CASES = [
    ("show me failed logins", "spl_generation"),
    ("find all denied connections in firewall", "spl_generation"),
    ("how many errors today", "spl_generation"),
    ("top 10 users by event count", "spl_generation"),
    ("rare sourcetypes in main index", "spl_generation"),
    ("detect brute force attacks", "spl_generation"),
    ("dns query activity", "spl_generation"),
    ("what is denied in the firewall", "general_qa"),
    ("show blocked events", "spl_generation"),
    ("authentication events search", "spl_generation"),
]


@pytest.mark.parametrize("query_text,expected_intent", NLP_ROUTE_CASES)
def test_nlp_to_spl_routing(query_text, expected_intent):
    plan = route_query(query_text)
    assert plan.intent == expected_intent, f"Expected {expected_intent}, got {plan.intent} (profile={plan.profile})"


# ═══════════════════════════════════════════════════════════
# 13. Query Router: SPL Extraction
# ═══════════════════════════════════════════════════════════

EXTRACTION_CASES = [
    ("optimize this spl: index=main | stats count", "index=main | stats count"),
    ("explain: | tstats count where index=main by host", "| tstats count where index=main by host"),
    ("index=firewall | stats count by src_ip", "index=firewall | stats count by src_ip"),
]


@pytest.mark.parametrize("user_input,expected_spl", EXTRACTION_CASES)
def test_spl_extraction(user_input, expected_spl):
    extracted = extract_spl_from_input(user_input)
    assert extracted is not None, f"Extraction returned None for: '{user_input}'"
    assert expected_spl in extracted, f"Expected '{expected_spl}' in: {extracted}"


# ═══════════════════════════════════════════════════════════
# 14. NLP-to-SPL: Suggestions Quality
# ═══════════════════════════════════════════════════════════

SUGGESTION_CASES = [
    ("index=* | stats count", "index=*"),
    ("index=main | join", "join"),
    ("index=main | transaction", "transaction"),
]


@pytest.mark.parametrize("query,expected_keyword", SUGGESTION_CASES)
def test_suggestions_quality(nlp_generator, query, expected_keyword):
    suggestions = nlp_generator._get_suggestions(query)
    has_relevant = any(expected_keyword.lower() in s.lower() for s in suggestions)
    assert has_relevant, f"No suggestion mentioning '{expected_keyword}'. Got: {suggestions}"


# ═══════════════════════════════════════════════════════════
# 15. Robust Analyzer: Anti-Pattern Detection
# ═══════════════════════════════════════════════════════════

ANTI_PATTERN_CASES = [
    ("index=* | stats count", "Searching all indexes"),
    ("index=main | join user [| inputlookup users]", "JOIN command"),
    ("index=main | transaction user", "TRANSACTION is memory-intensive"),
    ("index=main | table user | stats count", "TABLE command mid-pipeline"),
    ("index=main | search user=admin | stats count", "Using SEARCH after pipe"),
]


@pytest.mark.parametrize("query,expected_msg", ANTI_PATTERN_CASES)
def test_anti_pattern_detection(query, expected_msg):
    result = analyze_spl(query, auto_fix=False)
    messages = [issue.message for issue in result.issues]
    has_issue = any(expected_msg in msg for msg in messages)
    assert has_issue, f"Expected '{expected_msg}' in issues: {messages}"


def test_tstats_opportunity_detection():
    result = analyze_spl("index=ep_intel | stats count by host")
    messages = [issue.message for issue in result.issues]
    has_tstats = any("could be converted to tstats" in msg for msg in messages)
    assert has_tstats, f"Expected tstats opportunity. Issues: {messages}"


def test_auto_fix_search_to_where():
    result = analyze_spl("index=main | search user=test | stats count", auto_fix=True)
    assert "| where user=test" in result.optimized_query, f"Expected auto-fix. Got: {result.optimized_query}"
