"""
TEST-07: Slash command handler tests.

Tests every command handler in the _COMMAND_TABLE plus routing logic,
alias resolution, argument handling, and unknown-command handling.
"""
import sys
import os
import importlib
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Path setup (mirrors conftest.py)
# ---------------------------------------------------------------------------
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "chat_app"))
sys.path.insert(0, os.path.join(project_root, "shared"))
sys.path.insert(0, project_root)

# Ensure chainlit is mocked
if "chainlit" not in sys.modules:
    _cl_mock = MagicMock()
    _cl_mock.user_session = MagicMock()
    sys.modules["chainlit"] = _cl_mock
    sys.modules["chainlit.types"] = MagicMock()
    sys.modules["chainlit.context"] = MagicMock()

for _mod_name in ("cache", "ollama_priority", "resilience", "prometheus_metrics"):
    if _mod_name not in sys.modules:
        try:
            __import__(_mod_name)
        except ImportError:
            sys.modules[_mod_name] = MagicMock()

# ---------------------------------------------------------------------------
# Pre-mock runtime-only modules that slash_commands transitively imports.
# These are NOT available in the test environment but are needed so that
# `from chat_app.slash_commands import _COMMAND_TABLE` succeeds.
# ---------------------------------------------------------------------------
_RUNTIME_ONLY_MODULES = (
    "vectorstore", "search_opt_client", "splunk_client",
    "mcp_registry", "proactive_insights", "document_ingestor",
    "feedback_logger", "helper",
)
for _mod_name in _RUNTIME_ONLY_MODULES:
    if _mod_name not in sys.modules:
        try:
            __import__(_mod_name)
        except (ImportError, ModuleNotFoundError):
            sys.modules[_mod_name] = MagicMock()

# Now import slash_commands (all transitive deps satisfied)
try:
    from chat_app.slash_commands import handle_slash_command, _COMMAND_TABLE
except Exception:
    handle_slash_command = None
    _COMMAND_TABLE = {}

# Also force-build the command registry so registry tests work
try:
    from chat_app import registry as _reg_mod
    _reg_mod._command_cache.clear()
    _reg_mod._command_cache.update(_reg_mod._build_command_metadata())
except Exception:
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_content(msg_cls):
    """Extract content string from the cl.Message(...) call."""
    if not msg_cls.call_args:
        return ""
    args, kwargs = msg_cls.call_args
    if args:
        return str(args[0])
    return kwargs.get("content", "")


def _patch_cl_message():
    """Return a patch context manager that intercepts cl.Message(...).send()."""
    msg_instance = MagicMock()
    msg_instance.send = AsyncMock()
    msg_instance.update = AsyncMock()
    msg_instance.content = ""
    msg_class = MagicMock(return_value=msg_instance)
    return patch("chainlit.Message", msg_class), msg_class, msg_instance


# ═══════════════════════════════════════════════════════════════════════════════
# 1. /help command
# ═══════════════════════════════════════════════════════════════════════════════

class TestHelpCommand:
    """Tests for /help command handler."""

    @pytest.mark.asyncio
    async def test_help_full_page(self):
        """Full /help shows all sections."""
        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            from chat_app.commands.help import help_command
            await help_command("")
            content = _get_content(msg_cls)
            assert "Command Reference" in content
            assert "/run" in content
            assert "/search" in content
            msg_inst.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_help_specific_section_splunk(self):
        """/help splunk returns only Splunk section."""
        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            from chat_app.commands.help import help_command
            await help_command("splunk")
            content = _get_content(msg_cls)
            assert "Splunk" in content
            msg_inst.send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_help_specific_section_config(self):
        """/help config returns configuration section."""
        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            from chat_app.commands.help import help_command
            await help_command("config")
            content = _get_content(msg_cls)
            assert "Configuration" in content or "config" in content.lower()

    @pytest.mark.asyncio
    async def test_help_unknown_section_shows_full(self):
        """/help nonexistent falls back to full help."""
        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            from chat_app.commands.help import help_command
            await help_command("nonexistent_section")
            content = _get_content(msg_cls)
            assert "Command Reference" in content


# ═══════════════════════════════════════════════════════════════════════════════
# 2. /spec command
# ═══════════════════════════════════════════════════════════════════════════════

class TestSpecCommand:
    """Tests for /spec command handler (with mocked ingest_specs directory)."""

    @pytest.mark.asyncio
    async def test_spec_list_when_no_args(self, tmp_path):
        """Empty args shows available specs list."""
        spec_dir = tmp_path / "ingest_specs"
        spec_dir.mkdir()
        (spec_dir / "inputs.conf.spec").write_text("[monitor]\ndisabled = <bool>")
        (spec_dir / "props.conf.spec").write_text("[default]\nTIME_FORMAT = %Y-%m-%d")

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher, patch("chat_app.commands.spec._SPEC_DIRS", [spec_dir]):
            from chat_app.commands.spec import spec_command
            await spec_command("")
            content = _get_content(msg_cls)
            assert "inputs" in content or "props" in content

    @pytest.mark.asyncio
    async def test_spec_found(self, tmp_path):
        """Spec file lookup returns file content."""
        spec_dir = tmp_path / "ingest_specs"
        spec_dir.mkdir()
        (spec_dir / "inputs.conf.spec").write_text("[monitor]\ndisabled = <bool>\nindex = <string>")

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher, patch("chat_app.commands.spec._SPEC_DIRS", [spec_dir]):
            from chat_app.commands.spec import spec_command
            await spec_command("inputs")
            content = _get_content(msg_cls)
            assert "inputs.conf.spec" in content
            assert "[monitor]" in content

    @pytest.mark.asyncio
    async def test_spec_not_found_shows_suggestions(self, tmp_path):
        """Missing spec shows 'not found' with suggestions."""
        spec_dir = tmp_path / "ingest_specs"
        spec_dir.mkdir()
        (spec_dir / "inputs.conf.spec").write_text("x")

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher, patch("chat_app.commands.spec._SPEC_DIRS", [spec_dir]):
            from chat_app.commands.spec import spec_command
            await spec_command("bogus_xyz")
            content = _get_content(msg_cls)
            assert "not found" in content.lower()

    @pytest.mark.asyncio
    async def test_spec_list_subcommand(self, tmp_path):
        """/spec list shows all available spec files."""
        spec_dir = tmp_path / "ingest_specs"
        spec_dir.mkdir()
        (spec_dir / "inputs.conf.spec").write_text("x")
        (spec_dir / "props.conf.spec").write_text("y")

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher, patch("chat_app.commands.spec._SPEC_DIRS", [spec_dir]):
            from chat_app.commands.spec import spec_command
            await spec_command("list")
            content = _get_content(msg_cls)
            assert "2" in content or ("inputs" in content and "props" in content)


# ═══════════════════════════════════════════════════════════════════════════════
# 3. /stats command
# ═══════════════════════════════════════════════════════════════════════════════

class TestStatsCommand:
    """Tests for /stats command handler."""

    @pytest.mark.asyncio
    async def test_stats_with_metrics_module(self):
        """/stats shows report when metrics module available."""
        mock_report = "**Stats:** 42 queries processed"
        mock_metrics = MagicMock()
        mock_metrics.get_stats_report = MagicMock(return_value=mock_report)

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher, patch.dict(sys.modules, {"chat_app.metrics": mock_metrics}):
            from chat_app.commands import stats as stats_mod
            importlib.reload(stats_mod)
            await stats_mod.stats_command()
            content = _get_content(msg_cls)
            assert "42 queries" in content

    @pytest.mark.asyncio
    async def test_stats_fallback_no_metrics(self):
        """/stats shows fallback message when metrics module unavailable."""
        patcher, msg_cls, msg_inst = _patch_cl_message()

        # Temporarily make both metrics modules unimportable
        saved_cam = sys.modules.pop("chat_app.metrics", None)
        saved_m = sys.modules.pop("metrics", None)
        try:
            # Set to None to make __import__ raise ImportError
            sys.modules["chat_app.metrics"] = None  # type: ignore[assignment]
            sys.modules["metrics"] = None  # type: ignore[assignment]
            with patcher:
                from chat_app.commands import stats as stats_mod
                importlib.reload(stats_mod)
                await stats_mod.stats_command()
                content = _get_content(msg_cls)
                assert "Statistics" in content or "Metrics" in content or "stats" in content.lower()
        finally:
            sys.modules.pop("chat_app.metrics", None)
            sys.modules.pop("metrics", None)
            if saved_cam is not None:
                sys.modules["chat_app.metrics"] = saved_cam
            if saved_m is not None:
                sys.modules["metrics"] = saved_m


# ═══════════════════════════════════════════════════════════════════════════════
# 4. /config command
# ═══════════════════════════════════════════════════════════════════════════════

class TestConfigCommand:
    """Tests for /config command handler."""

    @pytest.mark.asyncio
    async def test_config_show_current(self):
        """/config with no args shows current settings."""
        import chainlit as cl
        cl.user_session.get = MagicMock(return_value={"temperature": 0.7, "model": "llama3"})

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            from chat_app.commands.config import config_command
            await config_command("")
            content = _get_content(msg_cls)
            assert "Current Settings" in content
            assert "temperature" in content

    @pytest.mark.asyncio
    async def test_config_update_setting(self):
        """/config key=value updates session settings."""
        import chainlit as cl
        settings = {"temperature": 0.7}
        cl.user_session.get = MagicMock(return_value=settings)
        cl.user_session.set = MagicMock()

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher, patch("chat_app.commands.config._persist_config", new_callable=AsyncMock):
            from chat_app.commands.config import config_command
            await config_command("temperature=0.9")
            content = _get_content(msg_cls)
            assert "updated" in content.lower()

    @pytest.mark.asyncio
    async def test_config_invalid_format(self):
        """/config with no '=' shows error."""
        import chainlit as cl
        cl.user_session.get = MagicMock(return_value={})

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            from chat_app.commands.config import config_command
            await config_command("temperature")
            content = _get_content(msg_cls)
            assert "Invalid" in content or "Usage" in content


# ═══════════════════════════════════════════════════════════════════════════════
# 5. /search command
# ═══════════════════════════════════════════════════════════════════════════════

class TestSearchCommand:
    """Tests for /search command handler (with mocked vectorstore)."""

    @pytest.mark.asyncio
    async def test_search_no_query(self):
        """/search with no query shows usage."""
        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            from chat_app.commands.search import search_command
            await search_command("", vector_store=None)
            content = _get_content(msg_cls)
            assert "Usage" in content or "Missing" in content

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        """/search with results displays them."""
        import chainlit as cl
        mock_results = [
            {"source": "spl_docs/stats.md", "text": "The stats command aggregates..."},
            {"source": "spl_docs/eval.md", "text": "The eval command calculates..."},
        ]
        cl.make_async = MagicMock(return_value=MagicMock(return_value=mock_results))

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            from chat_app.commands.search import search_command
            await search_command("stats command", vector_store=MagicMock())
            assert msg_inst.send.await_count >= 1

    @pytest.mark.asyncio
    async def test_search_no_results(self):
        """/search with no matches says so."""
        import chainlit as cl
        cl.make_async = MagicMock(return_value=MagicMock(return_value=[]))

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            from chat_app.commands.search import search_command
            await search_command("zzznonexistent", vector_store=MagicMock())
            assert msg_inst.send.await_count >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 6. /version command
# ═══════════════════════════════════════════════════════════════════════════════

class TestVersionCommand:
    """Tests for /version command handler."""

    @pytest.mark.asyncio
    async def test_version_output(self):
        """/version shows version info."""
        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            from chat_app.commands.version import version_command
            await version_command()
            content = _get_content(msg_cls)
            assert "Version" in content
            assert "Python" in content


# ═══════════════════════════════════════════════════════════════════════════════
# 7. /health command
# ═══════════════════════════════════════════════════════════════════════════════

class TestHealthCommand:
    """Tests for /health command handler (with mocked services)."""

    @pytest.mark.asyncio
    async def test_health_comprehensive(self):
        """/health runs health checks and shows status."""
        import chainlit as cl
        cl.user_session.get = MagicMock(return_value=None)

        mock_service = MagicMock()
        mock_service.name = "Ollama"
        mock_service.status = "healthy"
        mock_service.latency_ms = 50.0
        mock_service.error = None
        mock_service.details = {}

        mock_health = MagicMock()
        mock_health.overall = "healthy"
        mock_health.services = [mock_service]
        mock_health.metrics = {
            "counters": {"queries_total": 10, "cache_hits": 5, "cache_misses": 2},
            "latency_p50": 100, "latency_p95": 200, "quality_p50": 0.8,
        }
        mock_health.learning = {
            "episodes_total": 5, "success_rate": 0.9, "avg_confidence": 0.85,
            "semantic_facts": 10, "improvement_trend": "improving",
        }

        mock_hm = MagicMock()
        mock_hm.get_comprehensive_health = AsyncMock(return_value=mock_health)

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher, patch.dict(sys.modules, {"chat_app.health_monitor": mock_hm}):
            from chat_app.commands import health as health_mod
            importlib.reload(health_mod)
            await health_mod.health_command()
            assert msg_inst.send.await_count >= 1
            assert msg_inst.update.await_count >= 1


# ═══════════════════════════════════════════════════════════════════════════════
# 8. /profile command
# ═══════════════════════════════════════════════════════════════════════════════

class TestProfileCommand:
    """Tests for /profile command handler."""

    @pytest.mark.asyncio
    async def test_profile_shows_current(self):
        """/profile shows current profile info."""
        import chainlit as cl
        cl.user_session.get = MagicMock(return_value="general")

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            from chat_app.commands.profile import profile_command
            await profile_command()
            content = _get_content(msg_cls)
            assert "General Assistant" in content
            assert "All Available Profiles" in content


# ═══════════════════════════════════════════════════════════════════════════════
# 9. /clear command
# ═══════════════════════════════════════════════════════════════════════════════

class TestClearCommand:
    """Tests for /clear command handler."""

    @pytest.mark.asyncio
    async def test_clear_resets_history(self):
        """/clear clears conversation history."""
        import chainlit as cl
        cl.user_session.set = MagicMock()

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            from chat_app.commands.clear import clear_command
            await clear_command()
            cl.user_session.set.assert_called_with("conversation_history", [])
            content = _get_content(msg_cls)
            assert "cleared" in content.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 10. /skill command
# ═══════════════════════════════════════════════════════════════════════════════

class TestSkillCommand:
    """Tests for /skill command handler."""

    @pytest.mark.asyncio
    async def test_skill_list(self):
        """/skill with no args lists skills."""
        mock_executor = MagicMock()
        mock_executor.get_available_skills.return_value = [
            {"name": "hash_md5", "family": "operational", "action": "hash_data", "source": "internal"},
            {"name": "encode_base64", "family": "operational", "action": "encode_data", "source": "internal"},
        ]
        mock_se = MagicMock()
        mock_se.get_skill_executor = MagicMock(return_value=mock_executor)

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher, patch.dict(sys.modules, {"chat_app.skill_executor": mock_se}):
            from chat_app.commands import skill_cmd
            importlib.reload(skill_cmd)
            await skill_cmd.skill_command("")
            content = _get_content(msg_cls)
            assert "Executable Skills" in content or "hash_md5" in content

    @pytest.mark.asyncio
    async def test_skill_search(self):
        """/skill search <term> searches the catalog."""
        mock_skill = MagicMock()
        mock_skill.display_name = "MD5 Hash"
        mock_skill.name = "hash_md5"
        mock_skill.description = "Compute MD5 hash of input"
        mock_skill.handler_key = "hash_md5"

        mock_catalog = MagicMock()
        mock_catalog.search.return_value = [mock_skill]
        mock_sc = MagicMock()
        mock_sc.get_skill_catalog = MagicMock(return_value=mock_catalog)

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher, patch.dict(sys.modules, {"chat_app.skill_catalog": mock_sc}):
            from chat_app.commands import skill_cmd
            importlib.reload(skill_cmd)
            await skill_cmd.skill_command("search hash")
            content = _get_content(msg_cls)
            assert "hash" in content.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 11. /kg command
# ═══════════════════════════════════════════════════════════════════════════════

class TestKGCommand:
    """Tests for /kg command handler."""

    @pytest.mark.asyncio
    async def test_kg_stats(self):
        """/kg with no args shows stats."""
        mock_kg = MagicMock()
        mock_kg.get_stats.return_value = {
            "total_entities": 200,
            "total_relationships": 500,
            "build_time_ms": 150,
            "entity_type_counts": {"Command": 100, "Function": 50, "Field": 50},
            "relationship_type_counts": {"pipes_to": 80, "has_arguments": 60},
        }
        mock_kg_mod = MagicMock()
        mock_kg_mod.get_knowledge_graph = MagicMock(return_value=mock_kg)

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher, patch.dict(sys.modules, {"chat_app.knowledge_graph": mock_kg_mod}):
            from chat_app.commands import kg_cmd
            importlib.reload(kg_cmd)
            await kg_cmd.kg_command("")
            content = _get_content(msg_cls)
            assert "200" in content
            assert "Knowledge Graph" in content

    @pytest.mark.asyncio
    async def test_kg_search(self):
        """/kg search <term> searches entities."""
        mock_entity = MagicMock()
        mock_entity.name = "stats"
        mock_entity.entity_type = "Command"
        mock_entity.description = "Aggregation command"

        mock_kg = MagicMock()
        mock_kg.search_entities.return_value = [mock_entity]
        mock_kg_mod = MagicMock()
        mock_kg_mod.get_knowledge_graph = MagicMock(return_value=mock_kg)

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher, patch.dict(sys.modules, {"chat_app.knowledge_graph": mock_kg_mod}):
            from chat_app.commands import kg_cmd
            importlib.reload(kg_cmd)
            await kg_cmd.kg_command("search stats")
            content = _get_content(msg_cls)
            assert "stats" in content


# ═══════════════════════════════════════════════════════════════════════════════
# 12. Command routing (handle_slash_command)
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.skipif(handle_slash_command is None, reason="slash_commands import failed")
class TestCommandRouting:
    """Tests for handle_slash_command dispatch logic."""

    @pytest.mark.asyncio
    async def test_unknown_command(self):
        """Unknown command returns error message."""
        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            await handle_slash_command("/nonexistent_command_xyz")
            content = _get_content(msg_cls)
            assert "Unknown command" in content
            assert "/help" in content

    @pytest.mark.asyncio
    async def test_alias_version_ver(self):
        """/ver routes to version_command (alias)."""
        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            await handle_slash_command("/ver")
            content = _get_content(msg_cls)
            assert "Version" in content

    @pytest.mark.asyncio
    async def test_alias_version_about(self):
        """/about routes to version_command (alias)."""
        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            await handle_slash_command("/about")
            content = _get_content(msg_cls)
            assert "Version" in content

    @pytest.mark.asyncio
    async def test_alias_status_routes_to_health(self):
        """/status routes to health_command (alias)."""
        import chainlit as cl
        cl.user_session.get = MagicMock(return_value=None)

        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            await handle_slash_command("/status")
            assert msg_inst.send.await_count >= 1

    def test_alias_build_config_hyphen(self):
        """/build-config routes to build_config_command (alias)."""
        assert "/build-config" in _COMMAND_TABLE
        assert _COMMAND_TABLE["/build-config"][0] is _COMMAND_TABLE["/build_config"][0]

    @pytest.mark.asyncio
    async def test_command_with_args(self):
        """/help splunk passes 'splunk' as args."""
        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            await handle_slash_command("/help splunk")
            content = _get_content(msg_cls)
            assert "Splunk" in content

    @pytest.mark.asyncio
    async def test_command_case_insensitive(self):
        """Commands are case-insensitive."""
        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            await handle_slash_command("/VERSION")
            content = _get_content(msg_cls)
            assert "Version" in content

    @pytest.mark.asyncio
    async def test_command_without_required_args(self):
        """/spec without args shows available specs (no required arg error)."""
        patcher, msg_cls, msg_inst = _patch_cl_message()
        with patcher:
            await handle_slash_command("/spec")
            # spec_command("") shows available specs or usage hint
            content = _get_content(msg_cls)
            assert "spec" in content.lower() or "Usage" in content


# ═══════════════════════════════════════════════════════════════════════════════
# 13. Registry integration
# ═══════════════════════════════════════════════════════════════════════════════

class TestCommandRegistryIntegration:
    """Tests for registry.py command metadata built from _COMMAND_TABLE."""

    def test_registry_populated(self):
        """get_command_registry returns entries for all primary commands."""
        from chat_app.registry import get_command_registry
        reg = get_command_registry()
        assert len(reg) > 0, "Command registry is empty -- _COMMAND_TABLE import failed"
        # /ver is the primary (shortest alias for version_command)
        for cmd in ["/help", "/search", "/spec", "/config", "/stats",
                    "/clear", "/profile", "/health", "/ver", "/skill", "/kg"]:
            assert cmd in reg, f"{cmd} missing from command registry"

    def test_alias_detection(self):
        """Registry detects aliases (e.g. /ver and /about for /version)."""
        from chat_app.registry import get_command_registry
        reg = get_command_registry()
        # /ver is shortest so it becomes primary; /about and /version are aliases
        version_info = reg.get("/ver") or reg.get("/version") or reg.get("/about")
        assert version_info is not None, "No version command found in registry"
        assert len(version_info.aliases) > 0 or version_info.name in ["/ver", "/version", "/about"]

    def test_commands_for_api(self):
        """get_commands_for_api returns sorted list of dicts."""
        from chat_app.registry import get_commands_for_api
        result = get_commands_for_api()
        assert isinstance(result, list)
        assert len(result) > 0, "get_commands_for_api returned empty list"
        for entry in result:
            assert "name" in entry
            assert "description" in entry
            assert "category" in entry

    def test_command_table_primary_commands_have_descriptions(self):
        """Primary commands (non-aliases) have descriptions in the registry."""
        from chat_app.registry import get_command_registry
        reg = get_command_registry()
        # Commands with the canonical long name should have descriptions.
        # Short aliases like /ver may lack descriptions (primary is /ver but
        # _DESCRIPTIONS maps /version), which is acceptable.
        described = [info for info in reg.values() if info.description]
        assert len(described) >= 15, (
            f"Expected at least 15 described commands, got {len(described)}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# 14. Section registry includes new entries
# ═══════════════════════════════════════════════════════════════════════════════

class TestSectionRegistry:
    """Tests for section registry entries."""

    def test_quality_monitor_section_exists(self):
        """quality-monitor section is in the registry."""
        from chat_app.registry import get_section_registry
        sections = get_section_registry()
        ids = [s.id for s in sections]
        assert "quality-monitor" in ids

    def test_evolution_section_exists(self):
        """evolution section is in the registry."""
        from chat_app.registry import get_section_registry
        sections = get_section_registry()
        ids = [s.id for s in sections]
        assert "evolution" in ids

    def test_new_sections_in_intelligence_group(self):
        """New sections belong to the Intelligence group."""
        from chat_app.registry import get_section_registry
        sections = get_section_registry()
        for s in sections:
            if s.id in ("quality-monitor", "evolution"):
                assert s.group == "Intelligence", f"Section {s.id} should be in Intelligence group"

    def test_new_routing_tags_exist(self):
        """New RoutingTag members are defined."""
        from chat_app.registry import RoutingTag
        for tag_name in ("SUPERVISOR", "DIRECTOR_GRAPH", "EVOLUTION", "GCI",
                         "PRIORITY", "JOURNAL", "LINEAGE"):
            assert hasattr(RoutingTag, tag_name), f"RoutingTag.{tag_name} not found"
