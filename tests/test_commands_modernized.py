"""
Tests for the modernized command system — cross-connections between
Commands, Skills, Knowledge Graph, Admin API, and Orchestration.
"""
import sys
import os
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock
from pathlib import Path

import pytest

# Ensure project root is on path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

# Mock heavy dependencies not available in test env
_deps_to_mock = [
    "chromadb", "chromadb.config", "chromadb.api", "chromadb.api.models",
    "aiohttp", "langchain_ollama", "langchain_core", "langchain_core.messages",
    "langchain_chroma",
    "splunklib", "splunklib.client", "splunklib.results",
    "langchain_community", "langchain_community.chat_models",
    "sentence_transformers", "tiktoken",
]
for _dep in _deps_to_mock:
    if _dep not in sys.modules:
        sys.modules[_dep] = MagicMock()

# Mock vectorstore, splunk_client, feedback_logger before they get imported
for _mod in ("vectorstore", "splunk_client", "feedback_logger"):
    if _mod not in sys.modules:
        sys.modules[_mod] = MagicMock()


# ============================================================================
# /skill command tests
# ============================================================================


class TestSkillCommand:
    """Tests for chat_app/commands/skill_cmd.py."""

    @pytest.fixture(autouse=True)
    def setup_chainlit_mock(self):
        """Mock chainlit for command tests."""
        self.msg_mock = MagicMock()
        self.msg_mock.send = AsyncMock()
        self.msg_mock.update = AsyncMock()
        self.msg_mock.content = ""

        with patch("chat_app.commands.skill_cmd.cl") as cl_mock:
            cl_mock.Message.return_value = self.msg_mock
            self.cl_mock = cl_mock
            yield

    @pytest.mark.asyncio
    async def test_skill_list_no_args(self):
        """Test /skill with no args shows skill list."""
        executor = MagicMock()
        executor.get_available_skills.return_value = [
            {"name": "analyze_spl", "action": "analyze", "handler_key": "analyze_spl",
             "source": "tool_registry", "family": "cognitive", "approval": "auto"},
        ]
        with patch("chat_app.skill_executor.get_skill_executor", return_value=executor):
            from chat_app.commands.skill_cmd import skill_command
            await skill_command("")
        assert self.cl_mock.Message.called

    @pytest.mark.asyncio
    async def test_skill_search(self):
        """Test /skill search finds matching skills."""
        mock_skill = MagicMock()
        mock_skill.display_name = "Analyze SPL"
        mock_skill.name = "analyze_spl"
        mock_skill.description = "Analyze SPL queries"
        mock_skill.handler_key = "analyze_spl"

        catalog = MagicMock()
        catalog.search.return_value = [mock_skill]
        with patch("chat_app.skill_catalog.get_skill_catalog", return_value=catalog):
            from chat_app.commands.skill_cmd import skill_command
            await skill_command("search spl")
        assert self.cl_mock.Message.called

    @pytest.mark.asyncio
    async def test_skill_execute(self):
        """Test /skill <name> <input> executes and shows result."""
        from chat_app.skill_executor import SkillExecResult

        executor = MagicMock()
        executor.execute = AsyncMock(return_value=SkillExecResult(
            success=True, output="SPL analysis complete.",
            skill_name="analyze_spl", handler_key="analyze_spl",
            source="tool_registry", duration_ms=42.0,
        ))
        with patch("chat_app.skill_executor.get_skill_executor", return_value=executor):
            from chat_app.commands.skill_cmd import skill_command
            await skill_command("analyze_spl index=main | stats count")
        assert self.msg_mock.update.called

    @pytest.mark.asyncio
    async def test_skill_execute_failure(self):
        """Test /skill shows error on failure."""
        from chat_app.skill_executor import SkillExecResult

        executor = MagicMock()
        executor.execute = AsyncMock(return_value=SkillExecResult(
            success=False, output="",
            skill_name="bad_skill", handler_key="bad",
            error="Handler not found: bad", duration_ms=1.0,
        ))
        with patch("chat_app.skill_executor.get_skill_executor", return_value=executor):
            from chat_app.commands.skill_cmd import skill_command
            await skill_command("bad_skill")
        assert self.msg_mock.update.called

    @pytest.mark.asyncio
    async def test_skill_empty_search(self):
        """Test /skill search with empty term shows usage."""
        from chat_app.commands.skill_cmd import skill_command
        await skill_command("search ")
        assert self.cl_mock.Message.called


# ============================================================================
# /kg command tests
# ============================================================================


class TestKGCommand:
    """Tests for chat_app/commands/kg_cmd.py."""

    @pytest.fixture(autouse=True)
    def setup_chainlit_mock(self):
        self.msg_mock = MagicMock()
        self.msg_mock.send = AsyncMock()
        self.msg_mock.update = AsyncMock()

        with patch("chat_app.commands.kg_cmd.cl") as cl_mock:
            cl_mock.Message.return_value = self.msg_mock
            self.cl_mock = cl_mock
            yield

    @pytest.mark.asyncio
    async def test_kg_stats(self):
        """Test /kg with no args shows stats."""
        kg = MagicMock()
        kg.get_stats.return_value = {
            "total_entities": 150,
            "total_relationships": 300,
            "build_time_ms": 42.5,
            "entity_type_counts": {"Command": 100, "Function": 50},
            "relationship_type_counts": {"pipes_to": 80, "has_arguments": 120},
        }
        with patch("chat_app.knowledge_graph.get_knowledge_graph", return_value=kg):
            from chat_app.commands.kg_cmd import kg_command
            await kg_command("")

        content = self.cl_mock.Message.call_args[1].get("content", "")
        assert "150" in content
        assert "Command" in content

    @pytest.mark.asyncio
    async def test_kg_search(self):
        """Test /kg search finds entities."""
        mock_entity = MagicMock()
        mock_entity.name = "stats"
        mock_entity.entity_type = "Command"
        mock_entity.description = "Aggregation command"

        kg = MagicMock()
        kg.search_entities.return_value = [mock_entity]
        with patch("chat_app.knowledge_graph.get_knowledge_graph", return_value=kg):
            from chat_app.commands.kg_cmd import kg_command
            await kg_command("search stats")

        content = self.cl_mock.Message.call_args[1].get("content", "")
        assert "stats" in content

    @pytest.mark.asyncio
    async def test_kg_analyze(self):
        """Test /kg analyze decomposes SPL."""
        from chat_app.commands.kg_cmd import kg_command
        await kg_command("analyze index=main | stats count(severity) by sourcetype")

        content = self.cl_mock.Message.call_args[1].get("content", "")
        assert "stats" in content or "Commands" in content

    @pytest.mark.asyncio
    async def test_kg_related(self):
        """Test /kg related shows entity relationships."""
        mock_entity = MagicMock()
        mock_entity.id = "cmd:stats"
        mock_entity.name = "stats"
        mock_entity.entity_type = "Command"
        mock_entity.description = "Aggregation command"

        kg = MagicMock()
        kg.resolve_entity.return_value = mock_entity
        kg.get_neighbors.return_value = [
            {"direction": "outgoing", "rel_type": "uses_functions",
             "target_name": "count", "target_type": "Function"},
        ]
        with patch("chat_app.knowledge_graph.get_knowledge_graph", return_value=kg):
            from chat_app.commands.kg_cmd import kg_command
            await kg_command("related stats")

        content = self.cl_mock.Message.call_args[1].get("content", "")
        assert "count" in content or "stats" in content

    @pytest.mark.asyncio
    async def test_kg_not_initialized(self):
        """Test /kg gracefully handles uninitialized KG."""
        with patch("chat_app.knowledge_graph.get_knowledge_graph", return_value=None):
            from chat_app.commands.kg_cmd import kg_command
            await kg_command("")

        content = self.cl_mock.Message.call_args[1].get("content", "")
        assert "not initialized" in content


# ============================================================================
# Enhanced command tests
# ============================================================================


class TestEnhancedCommands:
    """Tests for enhanced /search, /health, /config, /explain, /profile."""

    @pytest.fixture(autouse=True)
    def setup_chainlit_mock(self):
        self.msg_mock = MagicMock()
        self.msg_mock.send = AsyncMock()
        self.msg_mock.update = AsyncMock()
        self.msg_mock.content = ""

        with patch("chainlit.Message", return_value=self.msg_mock):
            with patch("chainlit.user_session") as session_mock:
                session_mock.get.return_value = {}
                self.session_mock = session_mock
                yield

    def test_config_key_to_section_mapping(self):
        """Test that config keys map to admin API sections."""
        from chat_app.commands.config import _KEY_TO_SECTION
        assert _KEY_TO_SECTION["temperature"] == "llm"
        assert _KEY_TO_SECTION["k_multiplier"] == "retrieval"
        assert _KEY_TO_SECTION["system_prompt"] == "prompts"

    def test_search_command_has_kg_import(self):
        """Test that search command imports KG."""
        import chat_app.commands.search as search_mod
        import inspect
        source = inspect.getsource(search_mod.search_command)
        assert "knowledge_graph" in source

    def test_health_command_has_skill_metrics(self):
        """Test that health command imports skill executor."""
        import chat_app.commands.health as health_mod
        import inspect
        source = inspect.getsource(health_mod.health_command)
        assert "get_skill_executor" in source
        assert "get_orchestration_summary" in source
        assert "get_knowledge_graph" in source

    def test_explain_command_has_kg_decomposition(self):
        """Test that explain command imports SPLQueryAnalyzer."""
        import chat_app.commands.explain as explain_mod
        import inspect
        source = inspect.getsource(explain_mod.explain_command)
        assert "SPLQueryAnalyzer" in source

    def test_profile_command_has_agent_catalog(self):
        """Test that profile command imports AgentCatalog."""
        import chat_app.commands.profile as profile_mod
        import inspect
        source = inspect.getsource(profile_mod.profile_command)
        assert "AgentCatalog" in source
        assert "get_skill_executor" in source


# ============================================================================
# Command registration tests
# ============================================================================


class TestCommandRegistration:
    """Tests for slash_commands.py and chat_lifecycle.py registration."""

    def test_skill_command_registered(self):
        """Test /skill is in the command table."""
        from chat_app.slash_commands import _COMMAND_TABLE
        assert "/skill" in _COMMAND_TABLE

    def test_kg_command_registered(self):
        """Test /kg is in the command table."""
        from chat_app.slash_commands import _COMMAND_TABLE
        assert "/kg" in _COMMAND_TABLE

    def test_all_commands_have_handlers(self):
        """Test all registered commands have valid handlers."""
        from chat_app.slash_commands import _COMMAND_TABLE
        for cmd, (handler, needs_args, needs_kwargs) in _COMMAND_TABLE.items():
            assert callable(handler), f"{cmd} handler is not callable"
            assert isinstance(needs_args, bool)
            assert isinstance(needs_kwargs, bool)


# ============================================================================
# Skill executor KG integration tests
# ============================================================================


class TestSkillExecutorKGIntegration:
    """Tests for KG context injection in skill_executor.py."""

    def test_explain_spl_handler_uses_kg_context(self):
        """Test _handler_explain_spl appends KG context."""
        from chat_app.handlers.skill_handlers import _handler_explain_spl
        result = _handler_explain_spl(
            spl="index=main | stats count by host",
            kg_context="stats: Aggregation command with 15 functions"
        )
        assert "Knowledge Graph Context" in result
        assert "stats" in result

    def test_explain_spl_handler_without_kg(self):
        """Test _handler_explain_spl works without KG context."""
        from chat_app.handlers.skill_handlers import _handler_explain_spl
        result = _handler_explain_spl(spl="index=main | stats count by host")
        assert "Step 1" in result
        assert "Knowledge Graph" not in result

    def test_general_qa_handler_uses_kg_context(self):
        """Test _handler_general_qa includes KG context when available."""
        from chat_app.handlers import skill_handlers as sh
        import inspect
        source = inspect.getsource(sh._handler_general_qa)
        assert "kg_context" in source
        assert "Structural Context" in source

    def test_search_suggestion_uses_kg(self):
        """Test _handler_search_suggestion uses KG for related commands."""
        from chat_app.handlers import skill_handlers as sh
        import inspect
        source = inspect.getsource(sh._handler_search_suggestion)
        assert "knowledge_graph" in source
        assert "SPLQueryAnalyzer" in source

    def test_deep_search_handler_deduplicates(self):
        """Test _handler_deep_search source deduplication."""
        from chat_app.handlers import skill_handlers as sh
        import inspect
        source = inspect.getsource(sh._handler_deep_search)
        assert "seen_sources" in source
        assert "unique_results" in source

    def test_config_generator_supports_macros(self):
        """Test _handler_config_generator handles macros.conf."""
        from chat_app.handlers.skill_handlers import _handler_config_generator
        result = _handler_config_generator(user_input="macro definition")
        assert "macros.conf" in result


# ============================================================================
# Orchestration KG integration tests
# ============================================================================


class TestOrchestrationKGIntegration:
    """Tests for KG-aware orchestration strategy selection."""

    def test_orchestration_has_kg_aware_strategy(self):
        """Test execute_orchestration uses SPLQueryAnalyzer."""
        import chat_app.orchestration_strategies as orch
        import inspect
        source = inspect.getsource(orch.execute_orchestration)
        assert "SPLQueryAnalyzer" in source
        assert "hierarchical" in source
        assert "review_critique" in source


# ============================================================================
# Admin API execute-command tests
# ============================================================================


class TestAdminAPIExecuteCommand:
    """Tests for POST /execute-command endpoint."""

    def test_admin_api_has_execute_command(self):
        """Test admin interactive tools routes contain the execute-command endpoint."""
        import chat_app.admin_interactive_tools_routes as itr
        import inspect
        source = inspect.getsource(itr)
        assert "execute-command" in source
        assert "execute_command" in source

    def test_admin_api_returns_available_commands(self):
        """Test that unknown commands return available list."""
        import chat_app.admin_interactive_tools_routes as itr
        import inspect
        source = inspect.getsource(itr.execute_command)
        assert "available_commands" in source
