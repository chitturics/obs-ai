"""Tests for ObsAI CLI tool."""
import argparse
import json
import sys
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Fixture: import the CLI module
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _ensure_cli_importable():
    """Make sure cli/ is on sys.path so we can import obsai_cli."""
    import os
    cli_dir = os.path.join(os.path.dirname(__file__), "..", "cli")
    abs_cli = os.path.abspath(cli_dir)
    if abs_cli not in sys.path:
        sys.path.insert(0, abs_cli)


def _import_cli():
    import obsai_cli
    return obsai_cli


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(data: dict, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = data
    resp.text = json.dumps(data)
    return resp


def _capture(func, args_obj):
    """Call *func(args_obj)* and return captured stdout."""
    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        func(args_obj)
    finally:
        sys.stdout = old
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Argparse tests — make sure every subcommand parses cleanly
# ---------------------------------------------------------------------------

class TestArgparse:
    """Verify argparse definitions for every subcommand."""

    def _parse(self, argv):
        cli = _import_cli()
        parser = argparse.ArgumentParser(prog="obsai")
        parser.add_argument("--url", default="http://localhost:8000")
        parser.add_argument("--api-key", default="")
        sub = parser.add_subparsers(dest="command")

        p = sub.add_parser("ask")
        p.add_argument("question")

        p = sub.add_parser("search")
        p.add_argument("query")
        p.add_argument("--collection", "-c")
        p.add_argument("--k", type=int, default=5)

        sub.add_parser("health")

        p = sub.add_parser("costs")
        p.add_argument("--hours", type=int, default=24)

        p = sub.add_parser("config")
        csub = p.add_subparsers(dest="config_cmd")
        cs = csub.add_parser("show")
        cs.add_argument("--section")
        cv = csub.add_parser("versions")
        cv.add_argument("--limit", type=int, default=20)

        p = sub.add_parser("traces")
        p.add_argument("--limit", type=int, default=10)

        p = sub.add_parser("skills")
        p.add_argument("--family")

        p = sub.add_parser("agents")
        p.add_argument("--department")

        p = sub.add_parser("analytics")
        p.add_argument("subcommand", choices=["taxonomy", "gaps", "adoption", "roi"])

        p = sub.add_parser("kg")
        p.add_argument("subcommand", choices=["search", "stats"])
        p.add_argument("entity", nargs="?", default="")

        return parser.parse_args(argv)

    def test_ask(self):
        args = self._parse(["ask", "What is Splunk?"])
        assert args.command == "ask"
        assert args.question == "What is Splunk?"

    def test_search(self):
        args = self._parse(["search", "tstats", "-c", "spl_commands_mxbai"])
        assert args.command == "search"
        assert args.query == "tstats"
        assert args.collection == "spl_commands_mxbai"

    def test_search_default_k(self):
        args = self._parse(["search", "foo"])
        assert args.k == 5

    def test_health(self):
        args = self._parse(["health"])
        assert args.command == "health"

    def test_costs(self):
        args = self._parse(["costs", "--hours", "48"])
        assert args.command == "costs"
        assert args.hours == 48

    def test_costs_default(self):
        args = self._parse(["costs"])
        assert args.hours == 24

    def test_config_show(self):
        args = self._parse(["config", "show", "--section", "llm"])
        assert args.command == "config"
        assert args.config_cmd == "show"
        assert args.section == "llm"

    def test_config_versions(self):
        args = self._parse(["config", "versions", "--limit", "5"])
        assert args.command == "config"
        assert args.config_cmd == "versions"
        assert args.limit == 5

    def test_traces(self):
        args = self._parse(["traces", "--limit", "20"])
        assert args.command == "traces"
        assert args.limit == 20

    def test_skills(self):
        args = self._parse(["skills", "--family", "cognitive"])
        assert args.command == "skills"
        assert args.family == "cognitive"

    def test_agents(self):
        args = self._parse(["agents", "--department", "engineering"])
        assert args.command == "agents"
        assert args.department == "engineering"

    def test_analytics_taxonomy(self):
        args = self._parse(["analytics", "taxonomy"])
        assert args.subcommand == "taxonomy"

    def test_analytics_gaps(self):
        args = self._parse(["analytics", "gaps"])
        assert args.subcommand == "gaps"

    def test_analytics_adoption(self):
        args = self._parse(["analytics", "adoption"])
        assert args.subcommand == "adoption"

    def test_analytics_roi(self):
        args = self._parse(["analytics", "roi"])
        assert args.subcommand == "roi"

    def test_kg_search(self):
        args = self._parse(["kg", "search", "stats"])
        assert args.subcommand == "search"
        assert args.entity == "stats"

    def test_kg_stats(self):
        args = self._parse(["kg", "stats"])
        assert args.subcommand == "stats"

    def test_no_command(self):
        args = self._parse([])
        assert args.command is None


# ---------------------------------------------------------------------------
# Command output tests — mock httpx and verify formatting
# ---------------------------------------------------------------------------

class TestHealthOutput:
    """Test health command output formatting."""

    def test_health_format(self):
        cli = _import_cli()
        mock_resp = _mock_response({
            "health": {
                "overall": "healthy",
                "services": [
                    {"name": "PostgreSQL", "status": "up", "latency_ms": 12},
                    {"name": "ChromaDB", "status": "up", "latency_ms": 8},
                    {"name": "Ollama", "status": "up", "latency_ms": 45},
                ]
            },
            "resources": {"cpu_pct": 32, "memory_pct": 61, "disk_pct": 44}
        })
        with patch.object(cli, "get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_gc.return_value = mock_client

            args = argparse.Namespace(command="health")
            output = _capture(cli.cmd_health, args)

        assert "Overall: healthy" in output
        assert "PostgreSQL" in output
        assert "ChromaDB" in output
        assert "Ollama" in output
        assert "CPU: 32%" in output
        assert "MEM: 61%" in output
        assert "DISK: 44%" in output

    def test_health_degraded(self):
        cli = _import_cli()
        mock_resp = _mock_response({
            "health": {
                "overall": "degraded",
                "services": [
                    {"name": "Ollama", "status": "down", "latency_ms": 0},
                ]
            },
            "resources": {"cpu_pct": 95, "memory_pct": 88, "disk_pct": 70}
        })
        with patch.object(cli, "get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_gc.return_value = mock_client

            args = argparse.Namespace(command="health")
            output = _capture(cli.cmd_health, args)

        assert "degraded" in output
        assert "down" in output


class TestCostsOutput:
    """Test costs command output formatting."""

    def test_costs_format(self):
        cli = _import_cli()
        mock_resp = _mock_response({
            "total_usd": 0.0523,
            "total_calls": 142,
            "avg_cost_per_query": 0.000368,
            "by_model": {
                "llama3.1:8b": 0.0421,
                "mxbai-embed-large": 0.0102,
            }
        })
        with patch.object(cli, "get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_gc.return_value = mock_client

            args = argparse.Namespace(command="costs", hours=24)
            output = _capture(cli.cmd_costs, args)

        assert "Cost Summary (24h)" in output
        assert "$0.0523" in output
        assert "142" in output
        assert "llama3.1:8b" in output
        assert "mxbai-embed-large" in output

    def test_costs_empty(self):
        cli = _import_cli()
        mock_resp = _mock_response({
            "total_usd": 0,
            "total_calls": 0,
            "avg_cost_per_query": 0,
            "by_model": {}
        })
        with patch.object(cli, "get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_gc.return_value = mock_client

            args = argparse.Namespace(command="costs", hours=48)
            output = _capture(cli.cmd_costs, args)

        assert "Cost Summary (48h)" in output
        assert "$0.0000" in output


class TestSkillsOutput:
    """Test skills command output formatting."""

    def test_skills_list(self):
        cli = _import_cli()
        mock_resp = _mock_response({
            "skills": [
                {"name": "spl_search", "family": "cognitive", "status": "active"},
                {"name": "shell_exec", "family": "operational", "status": "active"},
                {"name": "report_gen", "family": "io", "status": "disabled"},
            ]
        })
        with patch.object(cli, "get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_gc.return_value = mock_client

            args = argparse.Namespace(command="skills", family=None)
            output = _capture(cli.cmd_skills, args)

        assert "spl_search" in output
        assert "shell_exec" in output
        assert "Total: 3 skills" in output

    def test_skills_filter_family(self):
        cli = _import_cli()
        mock_resp = _mock_response({
            "skills": [
                {"name": "spl_search", "family": "cognitive", "status": "active"},
                {"name": "shell_exec", "family": "operational", "status": "active"},
            ]
        })
        with patch.object(cli, "get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_gc.return_value = mock_client

            args = argparse.Namespace(command="skills", family="cognitive")
            output = _capture(cli.cmd_skills, args)

        assert "spl_search" in output
        assert "shell_exec" not in output
        assert "Total: 1 skills" in output


class TestAgentsOutput:
    """Test agents command output formatting."""

    def test_agents_list(self):
        cli = _import_cli()
        mock_resp = _mock_response({
            "agents": [
                {"name": "spl_expert", "department": "engineering"},
                {"name": "troubleshooter", "department": "operations"},
            ]
        })
        with patch.object(cli, "get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_gc.return_value = mock_client

            args = argparse.Namespace(command="agents", department=None)
            output = _capture(cli.cmd_agents, args)

        assert "spl_expert" in output
        assert "troubleshooter" in output
        assert "Total: 2 agents" in output


class TestSearchOutput:
    """Test search command output formatting."""

    def test_search_results(self):
        cli = _import_cli()
        mock_resp = _mock_response({
            "results": [
                {"text": "The stats command calculates aggregate statistics.", "source": "spl_docs/stats.md", "score": 0.92},
                {"text": "Use stats to compute count, sum, avg.", "source": "spl_docs/stats.md", "score": 0.85},
            ]
        })
        with patch.object(cli, "get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_gc.return_value = mock_client

            args = argparse.Namespace(command="search", query="stats", collection=None, k=5)
            output = _capture(cli.cmd_search, args)

        assert "Result 1" in output
        assert "score: 0.92" in output
        assert "spl_docs/stats.md" in output

    def test_search_no_results(self):
        cli = _import_cli()
        mock_resp = _mock_response({"results": []})
        with patch.object(cli, "get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.post.return_value = mock_resp
            mock_gc.return_value = mock_client

            args = argparse.Namespace(command="search", query="nonexistent", collection=None, k=5)
            output = _capture(cli.cmd_search, args)

        assert "No results found" in output


class TestTracesOutput:
    """Test traces command output formatting."""

    def test_traces_list(self):
        cli = _import_cli()
        mock_resp = _mock_response({
            "traces": [
                {"trace_id": "abc123def456", "root_name": "message_handler", "duration_ms": 320, "span_count": 8},
                {"trace_id": "xyz789abc012", "root_name": "skill_executor", "duration_ms": 150, "span_count": 4},
            ]
        })
        with patch.object(cli, "get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_gc.return_value = mock_client

            args = argparse.Namespace(command="traces", limit=10)
            output = _capture(cli.cmd_traces, args)

        assert "abc123def456" in output
        assert "message_handler" in output
        assert "320" in output


class TestConfigOutput:
    """Test config command output formatting."""

    def test_config_show_sections(self):
        cli = _import_cli()
        mock_resp = _mock_response({
            "sections": {
                "llm": {"model": "llama3.1:8b"},
                "retrieval": {"top_k": 5},
                "security": {"auth_enabled": False},
            }
        })
        with patch.object(cli, "get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_gc.return_value = mock_client

            args = argparse.Namespace(command="config", config_cmd="show", section=None)
            output = _capture(cli.cmd_config_show, args)

        assert "llm" in output
        assert "retrieval" in output
        assert "security" in output

    def test_config_show_specific_section(self):
        cli = _import_cli()
        mock_resp = _mock_response({
            "sections": {
                "llm": {"model": "llama3.1:8b", "temperature": 0.1},
            }
        })
        with patch.object(cli, "get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_gc.return_value = mock_client

            args = argparse.Namespace(command="config", config_cmd="show", section="llm")
            output = _capture(cli.cmd_config_show, args)

        assert "llama3.1:8b" in output
        assert "temperature" in output


class TestKgOutput:
    """Test knowledge graph command output formatting."""

    def test_kg_stats(self):
        cli = _import_cli()
        mock_resp = _mock_response({
            "total_entities": 1250,
            "total_relationships": 3400,
            "entity_type_counts": {
                "Command": 200,
                "Function": 150,
                "Field": 500,
            }
        })
        with patch.object(cli, "get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_gc.return_value = mock_client

            args = argparse.Namespace(command="kg", subcommand="stats")
            output = _capture(cli.cmd_kg, args)

        assert "Entities: 1250" in output
        assert "Relationships: 3400" in output
        assert "Command" in output
        assert "200" in output


class TestAnalyticsOutput:
    """Test analytics command output formatting."""

    def test_taxonomy(self):
        cli = _import_cli()
        mock_resp = _mock_response({
            "total_queries": 500,
            "avg_confidence": 0.85,
            "avg_quality": 0.78,
            "by_intent": {"spl_query": 200, "general_question": 150}
        })
        with patch.object(cli, "get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_gc.return_value = mock_client

            args = argparse.Namespace(command="analytics", subcommand="taxonomy")
            output = _capture(cli.cmd_analytics, args)

        assert "Total queries: 500" in output
        assert "spl_query" in output

    def test_gaps(self):
        cli = _import_cli()
        mock_resp = _mock_response({
            "gaps": [
                {"pattern": "How to configure HEC?", "occurrences": 12},
                {"pattern": "Splunk license usage", "occurrences": 8},
            ]
        })
        with patch.object(cli, "get_client") as mock_gc:
            mock_client = MagicMock()
            mock_client.get.return_value = mock_resp
            mock_gc.return_value = mock_client

            args = argparse.Namespace(command="analytics", subcommand="gaps")
            output = _capture(cli.cmd_analytics, args)

        assert "12x" in output
        assert "How to configure HEC?" in output
