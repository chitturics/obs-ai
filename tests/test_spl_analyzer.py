"""
Comprehensive tests for shared/spl_robust_analyzer.py -- SPL query analysis,
validation, anti-pattern detection, best-practice checks, command ordering,
auto-fix generation, and recommendation quality.

Covers:
- _validate_syntax()          -- balanced parens/brackets/quotes, typo detection
- _parse_commands()           -- command pipeline extraction and classification
- _check_anti_patterns()      -- sort-before-stats, table-before-stats, join, transaction, etc.
- _check_best_practices()     -- filter early, aggregate late, tstats opportunity, time range
- _analyze_command_order()    -- suboptimal ordering detection
- _generate_optimized_query() -- auto-fix generation
- _generate_recommendations() -- recommendation quality and severity ordering
- analyze() entry point       -- end-to-end with real SPL queries

Target: ~30 pure-function tests using real SPL examples.

NOTE: Anti-pattern issues from shared/spl_rules.py carry a spl_rules.Severity enum,
which is a different class from spl_robust_analyzer.Severity despite identical values.
Severity comparisons in anti-pattern tests therefore use .value strings rather than
enum identity to avoid false negatives.
"""

import pytest

from shared.spl_robust_analyzer import (
    AnalysisResult,
    CommandInfo,
    Issue,
    IssueCategory,
    RobustSPLAnalyzer,
    Severity,
    analyze_spl,
    get_robust_analyzer,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _issues_with_message(result: AnalysisResult, substring: str) -> list[Issue]:
    """Return issues whose message contains the given substring (case-insensitive)."""
    return [i for i in result.issues if substring.lower() in i.message.lower()]


def _issues_in_category(result: AnalysisResult, cat: IssueCategory) -> list[Issue]:
    """Return issues in a given category."""
    return [i for i in result.issues if i.category == cat]


def _command_names(result: AnalysisResult) -> list[str]:
    """Extract command names from parsed commands."""
    return [c.name for c in result.commands]


def _severity_value(issue: Issue) -> str:
    """Get severity value string, safe across both Severity enum definitions.

    Anti-pattern issues use spl_rules.Severity; best-practice / syntax issues
    use spl_robust_analyzer.Severity. Comparing .value strings works for both.
    """
    return issue.severity.value


# =====================================================================
# _validate_syntax()
# =====================================================================


class TestValidateSyntax:
    """Tests for _validate_syntax() -- balanced delimiters and typo detection."""

    def setup_method(self):
        self.analyzer = RobustSPLAnalyzer()

    # -- Valid queries produce no CRITICAL syntax issues -----------------------

    def test_valid_simple_query_no_syntax_errors(self):
        result = self.analyzer.analyze("index=main | stats count by host")
        critical_syntax = [
            i for i in result.issues
            if i.category == IssueCategory.SYNTAX and i.severity == Severity.CRITICAL
        ]
        assert critical_syntax == [], (
            f"Valid query should have no critical syntax issues, got: "
            f"{[i.message for i in critical_syntax]}"
        )

    def test_valid_complex_query_no_syntax_errors(self):
        query = (
            'index=main sourcetype=access_combined status>=400 '
            '| eval hour=strftime(_time, "%H") '
            '| stats count by hour, status'
        )
        result = self.analyzer.analyze(query)
        critical_syntax = [
            i for i in result.issues
            if i.category == IssueCategory.SYNTAX and i.severity == Severity.CRITICAL
        ]
        assert critical_syntax == []

    # -- Unbalanced parentheses ------------------------------------------------

    def test_unbalanced_open_paren_detected(self):
        result = self.analyzer.analyze("index=main | where (count > 5")
        paren_issues = _issues_with_message(result, "parenthes")
        assert len(paren_issues) >= 1
        assert paren_issues[0].severity == Severity.CRITICAL
        assert result.is_valid is False

    def test_unbalanced_close_paren_detected(self):
        result = self.analyzer.analyze("index=main | where count > 5)")
        paren_issues = _issues_with_message(result, "parenthes")
        assert len(paren_issues) >= 1
        assert result.is_valid is False

    # -- Unbalanced brackets (subsearch) ---------------------------------------

    def test_unbalanced_open_bracket_detected(self):
        result = self.analyzer.analyze("index=main [search index=threat")
        bracket_issues = _issues_with_message(result, "bracket")
        assert len(bracket_issues) >= 1
        assert bracket_issues[0].severity == Severity.CRITICAL
        assert result.is_valid is False

    def test_unbalanced_close_bracket_detected(self):
        result = self.analyzer.analyze("index=main search index=threat]")
        bracket_issues = _issues_with_message(result, "bracket")
        assert len(bracket_issues) >= 1

    # -- Unbalanced quotes -----------------------------------------------------

    def test_unbalanced_double_quotes_detected(self):
        result = self.analyzer.analyze('index=main | search "unterminated')
        quote_issues = _issues_with_message(result, "quote")
        assert len(quote_issues) >= 1
        assert result.is_valid is False

    # -- Typo detection --------------------------------------------------------

    def test_typo_statss(self):
        result = self.analyzer.analyze("index=main | statss count by host")
        typo_issues = _issues_with_message(result, "typo")
        assert len(typo_issues) >= 1
        assert any("stats" in i.message for i in typo_issues)

    def test_typo_tabel(self):
        result = self.analyzer.analyze("index=main | tabel _time host")
        typo_issues = _issues_with_message(result, "typo")
        assert len(typo_issues) >= 1
        assert any("table" in i.message for i in typo_issues)

    def test_typo_wehre(self):
        result = self.analyzer.analyze("index=main | wehre status>400")
        typo_issues = _issues_with_message(result, "typo")
        assert len(typo_issues) >= 1
        assert any("where" in i.message for i in typo_issues)


# =====================================================================
# _parse_commands()
# =====================================================================


class TestParseCommands:
    """Tests for _parse_commands() -- extracting command pipeline."""

    def setup_method(self):
        self.analyzer = RobustSPLAnalyzer()

    def test_simple_pipeline_commands(self):
        result = self.analyzer.analyze("index=main | stats count by host")
        names = _command_names(result)
        assert "search" in names, "First stage should parse as 'search'"
        assert "stats" in names

    def test_multi_stage_pipeline(self):
        result = self.analyzer.analyze(
            "index=main | eval x=1 | where x>0 | table x"
        )
        names = _command_names(result)
        assert "eval" in names
        assert "where" in names
        assert "table" in names

    def test_four_stage_pipeline_count(self):
        result = self.analyzer.analyze(
            "index=main | stats count | sort -count | head 10"
        )
        assert len(result.commands) == 4, (
            f"Expected 4 commands, got {len(result.commands)}: {_command_names(result)}"
        )

    def test_single_stage_search(self):
        result = self.analyzer.analyze("index=main")
        assert len(result.commands) >= 1
        assert result.commands[0].name == "search"

    def test_streaming_flag_set(self):
        result = self.analyzer.analyze("index=main | eval x=1 | where x>0")
        eval_cmd = next(c for c in result.commands if c.name == "eval")
        assert eval_cmd.is_streaming is True
        where_cmd = next(c for c in result.commands if c.name == "where")
        assert where_cmd.is_streaming is True

    def test_transforming_flag_set(self):
        result = self.analyzer.analyze("index=main | stats count by host | sort -count")
        stats_cmd = next(c for c in result.commands if c.name == "stats")
        assert stats_cmd.is_transforming is True
        sort_cmd = next(c for c in result.commands if c.name == "sort")
        assert sort_cmd.is_transforming is True

    def test_command_positions_sequential(self):
        result = self.analyzer.analyze(
            "index=main | eval x=1 | stats count | sort -count"
        )
        positions = [c.position for c in result.commands]
        assert positions == sorted(positions), "Positions should be sequential"

    def test_cost_assigned_to_each_command(self):
        result = self.analyzer.analyze("index=main | stats count by host")
        for cmd in result.commands:
            assert isinstance(cmd.estimated_cost, int)
            assert cmd.estimated_cost >= 1


# =====================================================================
# _check_anti_patterns()
# =====================================================================


class TestCheckAntiPatterns:
    """Tests for _check_anti_patterns() -- detecting known bad patterns.

    Anti-pattern issues carry spl_rules.Severity (a different enum from
    spl_robust_analyzer.Severity), so severity comparisons use .value strings.
    """

    def setup_method(self):
        self.analyzer = RobustSPLAnalyzer()

    def test_index_star_flagged(self):
        result = self.analyzer.analyze("index=* | stats count by host")
        star_issues = _issues_with_message(result, "all indexes")
        assert len(star_issues) >= 1, (
            f"index=* should be flagged; issues: {[i.message for i in result.issues]}"
        )
        assert _severity_value(star_issues[0]) == "critical"

    def test_join_flagged_as_expensive(self):
        result = self.analyzer.analyze(
            'index=main | join src_ip [search index=threat]'
        )
        join_issues = _issues_with_message(result, "join")
        assert len(join_issues) >= 1, (
            f"JOIN should be flagged; issues: {[i.message for i in result.issues]}"
        )
        assert any(_severity_value(i) in ("high", "critical") for i in join_issues)

    def test_transaction_flagged(self):
        result = self.analyzer.analyze(
            "index=main | transaction session_id maxspan=30m"
        )
        txn_issues = _issues_with_message(result, "transaction")
        assert len(txn_issues) >= 1, (
            f"TRANSACTION should be flagged; issues: {[i.message for i in result.issues]}"
        )
        assert any(_severity_value(i) == "high" for i in txn_issues)

    def test_table_mid_pipeline_flagged(self):
        result = self.analyzer.analyze(
            "index=main sourcetype=access_combined | table _time host status | where status>400"
        )
        table_issues = _issues_with_message(result, "table")
        assert len(table_issues) >= 1, (
            f"TABLE mid-pipeline should be flagged; issues: {[i.message for i in result.issues]}"
        )
        assert any("mid-pipeline" in i.message.lower() or "end" in (i.suggestion or "").lower()
                    for i in table_issues)

    def test_search_after_pipe_flagged(self):
        result = self.analyzer.analyze(
            "index=main | search user=admin | stats count"
        )
        search_issues = _issues_with_message(result, "search")
        perf_search_issues = [
            i for i in search_issues
            if i.category == IssueCategory.PERFORMANCE and "where" in (i.suggestion or "").lower()
        ]
        assert len(perf_search_issues) >= 1, (
            f"'| search' should suggest WHERE; issues: {[i.message for i in result.issues]}"
        )

    def test_stats_count_by_raw_flagged(self):
        result = self.analyzer.analyze("index=main | stats count by _raw")
        raw_issues = _issues_with_message(result, "_raw")
        assert len(raw_issues) >= 1
        assert any(_severity_value(i) == "critical" for i in raw_issues)

    def test_clean_query_no_severe_anti_patterns(self):
        """A well-formed query should not trigger severe anti-pattern issues."""
        result = self.analyzer.analyze(
            "index=main sourcetype=syslog earliest=-1h | stats count by host"
        )
        perf_issues = _issues_in_category(result, IssueCategory.PERFORMANCE)
        severe_anti = [
            i for i in perf_issues
            if _severity_value(i) in ("high", "critical")
            and ("join" in i.message.lower() or "transaction" in i.message.lower()
                 or "all indexes" in i.message.lower() or "_raw" in i.message.lower())
        ]
        assert severe_anti == []


# =====================================================================
# _check_best_practices()
# =====================================================================


class TestCheckBestPractices:
    """Tests for _check_best_practices() -- optimization suggestions."""

    def setup_method(self):
        self.analyzer = RobustSPLAnalyzer()

    def test_missing_time_range_flagged(self):
        result = self.analyzer.analyze("index=main | stats count by host")
        time_issues = [i for i in result.issues
                       if "time" in i.message.lower() and "range" in i.message.lower()]
        assert len(time_issues) >= 1, (
            f"Missing time range should be flagged; issues: {[i.message for i in result.issues]}"
        )

    def test_time_range_present_no_flag(self):
        result = self.analyzer.analyze(
            "index=main earliest=-1h latest=now | stats count by host"
        )
        time_issues = [i for i in result.issues
                       if "time" in i.message.lower() and "range" in i.message.lower()
                       and "add" in i.message.lower()]
        assert time_issues == [], "Query with time range should not be flagged for missing time"

    def test_missing_index_flagged(self):
        result = self.analyzer.analyze("sourcetype=syslog | stats count")
        index_issues = _issues_with_message(result, "index")
        assert any("no index" in i.message.lower() for i in index_issues), (
            f"Missing index should be flagged; issues: {[i.message for i in result.issues]}"
        )

    def test_index_present_no_missing_index_flag(self):
        result = self.analyzer.analyze("index=main | stats count by host")
        index_issues = [i for i in result.issues
                        if "no index specified" in i.message.lower()]
        assert index_issues == []

    def test_tstats_opportunity_detected(self):
        """Simple search | stats should suggest tstats conversion."""
        result = self.analyzer.analyze("index=main | stats count by sourcetype")
        tstats_issues = _issues_with_message(result, "tstats")
        assert len(tstats_issues) >= 1, (
            f"Simple stats should suggest tstats; issues: {[i.message for i in result.issues]}"
        )
        # tstats opportunity comes from _check_best_practices which uses
        # spl_robust_analyzer.Severity natively
        assert any(i.severity == Severity.HIGH for i in tstats_issues)

    def test_no_tstats_suggestion_for_complex_query(self):
        """Query with eval/rex should NOT suggest tstats."""
        result = self.analyzer.analyze(
            'index=main | rex field=_raw "user=(?<username>\\w+)" | stats count by username'
        )
        tstats_issues = [i for i in result.issues
                         if "could be converted to tstats" in i.message.lower()]
        assert tstats_issues == [], "Complex query with rex should not suggest tstats"

    def test_no_tstats_suggestion_when_already_tstats(self):
        result = self.analyzer.analyze("| tstats count WHERE index=main by sourcetype")
        tstats_issues = [i for i in result.issues
                         if "could be converted to tstats" in i.message.lower()]
        assert tstats_issues == [], "tstats query should not suggest converting to tstats"

    def test_missing_fields_command_flagged_for_long_pipeline(self):
        result = self.analyzer.analyze(
            "index=main | eval x=1 | where x>0 | stats count by host"
        )
        fields_issues = [i for i in result.issues
                         if "fields" in i.message.lower() and "data transfer" in i.message.lower()]
        assert len(fields_issues) >= 1, (
            f"Long pipeline without fields should flag; issues: {[i.message for i in result.issues]}"
        )

    def test_subsearch_usage_flagged(self):
        result = self.analyzer.analyze(
            "index=main [search index=threat | fields src_ip] | stats count"
        )
        sub_issues = [i for i in result.issues
                      if "subsearch" in i.message.lower() or "lookup" in (i.suggestion or "").lower()]
        assert len(sub_issues) >= 1

    def test_broad_search_index_star_sourcetype_star_flagged(self):
        result = self.analyzer.analyze(
            "index=* sourcetype=* | stats count by host"
        )
        broad_issues = _issues_with_message(result, "broad")
        assert len(broad_issues) >= 1
        # This issue comes from _check_best_practices, using analyzer's Severity
        assert any(i.severity == Severity.CRITICAL for i in broad_issues)


# =====================================================================
# _analyze_command_order()
# =====================================================================


class TestAnalyzeCommandOrder:
    """Tests for _analyze_command_order() -- detect suboptimal ordering."""

    def setup_method(self):
        self.analyzer = RobustSPLAnalyzer()

    def test_sort_directly_before_stats_flagged(self):
        """Sort immediately followed by stats should be flagged as unnecessary."""
        result = self.analyzer.analyze(
            "index=main | sort _time | stats count by host"
        )
        sort_issues = [i for i in result.issues
                       if "sort" in i.message.lower() and "aggregat" in i.message.lower()]
        assert len(sort_issues) >= 1, (
            f"Sort directly before stats should be flagged; issues: "
            f"{[i.message for i in result.issues]}"
        )

    def test_sort_before_chart_flagged(self):
        result = self.analyzer.analyze(
            "index=main | sort _time | chart count by host"
        )
        sort_issues = [i for i in result.issues
                       if "sort" in i.message.lower() and "aggregat" in i.message.lower()]
        assert len(sort_issues) >= 1

    def test_sort_before_timechart_flagged(self):
        result = self.analyzer.analyze(
            "index=main | sort _time | timechart count"
        )
        sort_issues = [i for i in result.issues
                       if "sort" in i.message.lower() and "aggregat" in i.message.lower()]
        assert len(sort_issues) >= 1

    def test_streaming_after_transforming_flagged(self):
        """eval after stats is suboptimal -- should move before."""
        result = self.analyzer.analyze(
            "index=main | stats count by host | eval label=host"
        )
        order_issues = [i for i in result.issues
                        if "streaming" in i.message.lower() and "transforming" in i.message.lower()]
        assert len(order_issues) >= 1, (
            f"Streaming after transforming should be flagged; issues: "
            f"{[i.message for i in result.issues]}"
        )

    def test_single_command_no_order_issues(self):
        result = self.analyzer.analyze("index=main")
        order_issues = [i for i in result.issues
                        if "streaming" in i.message.lower() and "transforming" in i.message.lower()]
        assert order_issues == [], "Single command should not produce ordering issues"

    def test_sort_with_intervening_command_not_flagged_for_aggregation(self):
        """The sort-before-aggregation check only fires on immediately adjacent
        commands (commands[i+1]), so sort -> head -> stats does not trigger it."""
        result = self.analyzer.analyze(
            "index=_internal | sort _time | head 100 | stats count"
        )
        sort_agg_issues = [i for i in result.issues
                           if "sort" in i.message.lower()
                           and "aggregat" in i.message.lower()
                           and "unnecessary" in i.message.lower()]
        assert sort_agg_issues == [], (
            "Sort followed by head (not directly stats) should not trigger "
            "the sort-before-aggregation check"
        )


# =====================================================================
# _generate_optimized_query()
# =====================================================================


class TestGenerateOptimizedQuery:
    """Tests for _generate_optimized_query() -- auto-fix generation."""

    def setup_method(self):
        self.analyzer = RobustSPLAnalyzer()

    def test_search_replaced_with_where(self):
        result = self.analyzer.analyze(
            "index=main | search user=test | stats count", auto_fix=True
        )
        assert result.optimized_query is not None
        assert "| where" in result.optimized_query, (
            f"Expected '| where' in optimized query, got: {result.optimized_query}"
        )

    def test_unbalanced_parens_auto_fixed(self):
        result = self.analyzer.analyze(
            "index=main | where (count > 5", auto_fix=True
        )
        assert result.optimized_query is not None
        assert result.optimized_query.count('(') == result.optimized_query.count(')'), (
            f"Parentheses should be balanced in: {result.optimized_query}"
        )

    def test_balance_brackets_fix_method_directly(self):
        """Test the bracket balancing fix method in isolation."""
        analyzer = RobustSPLAnalyzer()
        fixed = analyzer._fix_balance_brackets("index=main [search index=threat")
        assert fixed.count('[') == fixed.count(']'), (
            f"Brackets should be balanced; got: {fixed}"
        )

    def test_balance_parentheses_fix_extra_open(self):
        """Direct test of parenthesis balancing with extra open parens."""
        analyzer = RobustSPLAnalyzer()
        fixed = analyzer._fix_balance_parentheses("index=main | where ((x > 5)")
        assert fixed.count('(') == fixed.count(')')

    def test_balance_parentheses_fix_extra_close(self):
        """Direct test of parenthesis balancing with extra close parens."""
        analyzer = RobustSPLAnalyzer()
        fixed = analyzer._fix_balance_parentheses("index=main | where (x > 5))")
        assert fixed.count('(') == fixed.count(')')

    def test_time_range_added_when_missing(self):
        result = self.analyzer.analyze(
            "index=main | stats count by host", auto_fix=True
        )
        assert result.optimized_query is not None
        assert "earliest" in result.optimized_query.lower(), (
            f"Time range should be added; got: {result.optimized_query}"
        )

    def test_add_time_range_inserts_after_index(self):
        """Direct test of _fix_add_time_range inserting after index=."""
        analyzer = RobustSPLAnalyzer()
        fixed = analyzer._fix_add_time_range("index=main | stats count")
        assert "earliest" in fixed.lower()
        assert "index=main" in fixed

    def test_auto_fix_disabled_no_optimized_query(self):
        result = self.analyzer.analyze(
            "index=main | stats count by host", auto_fix=False
        )
        assert result.optimized_query is None

    def test_original_query_preserved(self):
        original = "index=main | search user=admin | stats count"
        result = self.analyzer.analyze(original, auto_fix=True)
        assert result.original_query == original, "Original query must not be mutated"


# =====================================================================
# _generate_recommendations()
# =====================================================================


class TestGenerateRecommendations:
    """Tests for _generate_recommendations() -- suggestion quality and ordering."""

    def setup_method(self):
        self.analyzer = RobustSPLAnalyzer()

    def test_critical_syntax_issues_generate_critical_section(self):
        """Unbalanced parentheses produce analyzer-native CRITICAL issues
        that should appear in a CRITICAL recommendations section."""
        result = self.analyzer.analyze("index=main | where (count > 5")
        assert any("CRITICAL" in r for r in result.recommendations), (
            f"Syntax CRITICAL issues should produce CRITICAL section; "
            f"recs: {result.recommendations}"
        )

    def test_high_priority_section_present_for_tstats_opportunity(self):
        """tstats opportunity is a HIGH severity issue from _check_best_practices
        which uses the analyzer's own Severity, so it should appear in recommendations."""
        result = self.analyzer.analyze("index=main | stats count by host")
        high_recs = [r for r in result.recommendations if "HIGH PRIORITY" in r]
        assert len(high_recs) >= 1, (
            f"Should have HIGH PRIORITY section; recs: {result.recommendations}"
        )

    def test_recommendations_are_strings(self):
        result = self.analyzer.analyze("index=main | stats count by host")
        for rec in result.recommendations:
            assert isinstance(rec, str)

    def test_clean_query_minimal_recommendations(self):
        result = self.analyzer.analyze(
            "| tstats count WHERE index=main earliest=-1h latest=now by sourcetype"
        )
        critical_recs = [r for r in result.recommendations if "CRITICAL" in r]
        assert critical_recs == [], (
            f"Clean tstats query should have no CRITICAL recommendations; got: {critical_recs}"
        )

    def test_optimization_potential_positive_for_fixable_query(self):
        """A query with auto-fixable issues should have nonzero optimization potential."""
        result = self.analyzer.analyze(
            "index=main | search user=admin | stats count"
        )
        assert result.optimization_potential > 0, (
            f"Query with auto-fixable issues should have optimization potential > 0; "
            f"got: {result.optimization_potential}"
        )


# =====================================================================
# analyze() -- End-to-end with real SPL queries
# =====================================================================


class TestAnalyzeEndToEnd:
    """End-to-end tests for the analyze() entry point with real SPL queries."""

    def setup_method(self):
        self.analyzer = RobustSPLAnalyzer()

    def test_simple_stats_query(self):
        result = self.analyzer.analyze("index=main | stats count by host")
        assert result.is_valid is True
        assert len(result.commands) >= 2
        assert result.estimated_cost > 0
        assert isinstance(result.recommendations, list)

    def test_internal_sort_head_stats_pipeline(self):
        """A pipeline with sort, head, and stats should parse all 4 commands
        and detect at least some issues (missing time range, tstats opportunity, etc.)."""
        result = self.analyzer.analyze(
            "index=_internal | sort _time | head 100 | stats count"
        )
        assert result.is_valid is True
        assert len(result.commands) == 4
        names = _command_names(result)
        assert "sort" in names
        assert "head" in names
        assert "stats" in names
        assert len(result.issues) > 0

    def test_access_combined_table_before_where(self):
        result = self.analyzer.analyze(
            "index=main sourcetype=access_combined | table _time host status | where status>400"
        )
        assert result.is_valid is True
        table_issues = _issues_with_message(result, "table")
        assert len(table_issues) >= 1

    def test_tstats_query_is_valid(self):
        result = self.analyzer.analyze(
            "| tstats count WHERE index=main by sourcetype, host"
        )
        assert result.is_valid is True
        names = _command_names(result)
        assert "tstats" in names

    def test_complex_eval_pipeline(self):
        result = self.analyzer.analyze(
            'index=web | eval response_class=case(status<300,"2xx",status<400,"3xx",'
            'status<500,"4xx",1=1,"5xx") | stats count by response_class'
        )
        assert result.is_valid is True
        names = _command_names(result)
        assert "eval" in names
        assert "stats" in names

    def test_result_has_all_expected_fields(self):
        result = self.analyzer.analyze("index=main | stats count")
        assert hasattr(result, "original_query")
        assert hasattr(result, "is_valid")
        assert hasattr(result, "optimized_query")
        assert hasattr(result, "commands")
        assert hasattr(result, "issues")
        assert hasattr(result, "estimated_cost")
        assert hasattr(result, "optimization_potential")
        assert hasattr(result, "recommendations")

    def test_estimated_cost_within_bounds(self):
        result = self.analyzer.analyze("index=main | stats count by host")
        assert 0 <= result.estimated_cost <= 100

    def test_optimization_potential_within_bounds(self):
        result = self.analyzer.analyze("index=main | stats count by host")
        assert 0 <= result.optimization_potential <= 100


# =====================================================================
# Module-level helpers: analyze_spl() and get_robust_analyzer()
# =====================================================================


class TestModuleLevelHelpers:
    """Tests for analyze_spl() convenience function and singleton."""

    def test_analyze_spl_returns_analysis_result(self):
        result = analyze_spl("index=main | stats count")
        assert isinstance(result, AnalysisResult)
        assert result.original_query == "index=main | stats count"

    def test_get_robust_analyzer_returns_instance(self):
        analyzer = get_robust_analyzer()
        assert isinstance(analyzer, RobustSPLAnalyzer)

    def test_singleton_pattern(self):
        a1 = get_robust_analyzer()
        a2 = get_robust_analyzer()
        assert a1 is a2
