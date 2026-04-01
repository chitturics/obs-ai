"""
Comprehensive MCP integration tests.

Tests the full MCP pipeline: registry, tool loading, tool execution,
tool-augmented queries, and message handler integration.
"""
import json
import os
import sys
import asyncio
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure chat_app is importable
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "chat_app"))
sys.path.insert(0, project_root)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_config_yaml(tmp_path):
    """Create a temporary config.yaml with MCP gateway config."""
    config = tmp_path / "config.yaml"
    config.write_text(
        """
mcp_gateway:
  enabled: true
  connection_timeout: 10
  max_retries: 1
  servers:
    - name: test-splunk
      client_type: sse
      endpoint: http://localhost:9999
      auth_scheme: bearer
      auth_hints:
        header: Authorization
        prefix: "Bearer "
      enabled: true
      description: Test Splunk MCP
    - name: test-github
      client_type: streamable-http
      endpoint: http://localhost:9998
      auth_scheme: bearer
      enabled: true
    - name: test-disabled
      client_type: sse
      endpoint: http://localhost:9997
      enabled: false
    - name: test-stdio
      client_type: stdio
      command: echo hello
      enabled: true
""",
        encoding="utf-8",
    )
    return config


@pytest.fixture
def empty_config_yaml(tmp_path):
    """Config with empty MCP section."""
    config = tmp_path / "config.yaml"
    config.write_text("mcp_gateway:\n  enabled: true\n", encoding="utf-8")
    return config


@pytest.fixture
def disabled_config_yaml(tmp_path):
    """Config with MCP disabled."""
    config = tmp_path / "config.yaml"
    config.write_text("mcp_gateway:\n  enabled: false\n", encoding="utf-8")
    return config


# ---------------------------------------------------------------------------
# 1. MCP Registry Tests
# ---------------------------------------------------------------------------

class TestMCPRegistry:
    """Test mcp_registry.py functions."""

    def test_load_registry_with_servers(self, sample_config_yaml):
        from mcp_registry import load_registry
        reg = load_registry(sample_config_yaml)
        assert reg["enabled"] is True
        assert len(reg["servers"]) == 4  # All servers, including disabled

    def test_load_registry_enabled_default_true(self, empty_config_yaml):
        """When mcp_gateway exists but has no 'enabled' key, default to True."""
        from mcp_registry import load_registry
        reg = load_registry(empty_config_yaml)
        assert reg["enabled"] is True

    def test_load_registry_disabled(self, disabled_config_yaml):
        from mcp_registry import load_registry
        reg = load_registry(disabled_config_yaml)
        assert reg["enabled"] is False

    def test_load_registry_missing_file(self, tmp_path):
        from mcp_registry import load_registry
        reg = load_registry(tmp_path / "nonexistent.yaml")
        # Falls back to builtin servers
        assert reg["enabled"] is True
        assert len(reg["servers"]) >= 1
        assert reg["servers"][0]["name"] == "splunk-mcp"

    def test_list_servers_filters_disabled(self, sample_config_yaml):
        from mcp_registry import load_registry, list_servers
        with patch("mcp_registry.DEFAULT_CONFIG_PATH", sample_config_yaml):
            servers = list_servers()
            names = [s["name"] for s in servers]
            assert "test-splunk" in names
            assert "test-github" in names
            assert "test-disabled" not in names

    def test_list_servers_include_disabled(self, sample_config_yaml):
        from mcp_registry import list_servers
        with patch("mcp_registry.DEFAULT_CONFIG_PATH", sample_config_yaml):
            servers = list_servers(include_disabled=True)
            names = [s["name"] for s in servers]
            assert "test-disabled" in names

    def test_list_servers_when_gateway_disabled(self, disabled_config_yaml):
        from mcp_registry import list_servers
        with patch("mcp_registry.DEFAULT_CONFIG_PATH", disabled_config_yaml):
            servers = list_servers()
            assert servers == []

    def test_get_server(self, sample_config_yaml):
        from mcp_registry import get_server
        with patch("mcp_registry.DEFAULT_CONFIG_PATH", sample_config_yaml):
            s = get_server("test-splunk")
            assert s is not None
            assert s["endpoint"] == "http://localhost:9999"

    def test_get_server_not_found(self, sample_config_yaml):
        from mcp_registry import get_server
        with patch("mcp_registry.DEFAULT_CONFIG_PATH", sample_config_yaml):
            assert get_server("nonexistent") is None

    def test_normalize_server_aliases(self):
        """Server entries with 'type' and 'url' aliases are normalized."""
        from mcp_registry import _normalize_server
        entry = {
            "name": "alias-test",
            "type": "streamable-http",
            "url": "http://example.com",
            "auth_scheme": "api_key",
        }
        result = _normalize_server(entry)
        assert result["client_type"] == "streamable-http"
        assert result["endpoint"] == "http://example.com"
        assert result["auth_scheme"] == "api_key"

    def test_normalize_server_empty(self):
        from mcp_registry import _normalize_server
        assert _normalize_server({}) is None
        assert _normalize_server(None) is None

    def test_normalize_server_no_name(self):
        from mcp_registry import _normalize_server
        assert _normalize_server({"endpoint": "http://x"}) is None


# ---------------------------------------------------------------------------
# 2. MCPTool Tests
# ---------------------------------------------------------------------------

class TestMCPTool:
    """Test the MCPTool wrapper class."""

    def test_tool_creation(self):
        from mcp_utils import MCPTool
        tool = MCPTool(
            name="search",
            description="Run a Splunk search",
            server_name="test-splunk",
            endpoint="http://localhost:9999",
        )
        assert tool.name == "search"
        assert tool.description == "Run a Splunk search"
        assert tool.server_name == "test-splunk"

    def test_tool_repr(self):
        from mcp_utils import MCPTool
        tool = MCPTool(name="search", server_name="splunk")
        assert "search" in repr(tool)
        assert "splunk" in repr(tool)

    @pytest.mark.asyncio
    async def test_tool_ainvoke_success(self):
        from mcp_utils import MCPTool
        tool = MCPTool(
            name="test_tool",
            endpoint="http://localhost:9999",
            timeout=5,
        )

        mock_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "content": [
                    {"type": "text", "text": "Search returned 42 results."}
                ]
            },
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.json.return_value = mock_response
            mock_resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tool.ainvoke({"query": "index=main"})
            assert "42 results" in result

    @pytest.mark.asyncio
    async def test_tool_ainvoke_http_error(self):
        from mcp_utils import MCPTool
        tool = MCPTool(name="err_tool", endpoint="http://localhost:9999", timeout=2)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            mock_resp.raise_for_status.side_effect = RuntimeError("HTTP 500")
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tool.ainvoke({})
            assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_tool_ainvoke_connection_error(self):
        from mcp_utils import MCPTool
        import httpx
        tool = MCPTool(name="conn_err", endpoint="http://localhost:1", timeout=1)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("Connection refused"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await tool.ainvoke({})
            assert "error" in result.lower()


# ---------------------------------------------------------------------------
# 3. Auth Header Tests
# ---------------------------------------------------------------------------

class TestAuthHeaders:
    """Test _build_auth_headers."""

    def test_bearer_auth(self):
        from mcp_utils import _build_auth_headers
        server = {
            "auth_scheme": "bearer",
            "auth_hints": {"header": "Authorization", "prefix": "Bearer "},
        }
        headers = _build_auth_headers(server, "mytoken123")
        assert headers == {"Authorization": "Bearer mytoken123"}

    def test_api_key_auth(self):
        from mcp_utils import _build_auth_headers
        server = {
            "auth_scheme": "api_key",
            "auth_hints": {"header": "X-API-Key"},
        }
        headers = _build_auth_headers(server, "key456")
        assert headers == {"X-API-Key": "key456"}

    def test_no_auth(self):
        from mcp_utils import _build_auth_headers
        server = {"auth_scheme": "none"}
        headers = _build_auth_headers(server, None)
        assert headers == {}

    def test_bearer_no_token(self):
        from mcp_utils import _build_auth_headers
        server = {"auth_scheme": "bearer"}
        headers = _build_auth_headers(server, None)
        assert headers == {}

    def test_default_bearer_hints(self):
        from mcp_utils import _build_auth_headers
        server = {"auth_scheme": "bearer", "auth_hints": {}}
        headers = _build_auth_headers(server, "tok")
        assert headers == {"Authorization": "Bearer tok"}


# ---------------------------------------------------------------------------
# 4. Tool Discovery Tests
# ---------------------------------------------------------------------------

class TestToolDiscovery:
    """Test _discover_tools."""

    @pytest.mark.asyncio
    async def test_discover_tools_success(self):
        from mcp_utils import _discover_tools

        server = {"name": "test", "endpoint": "http://localhost:9999"}
        mock_tools = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": "search", "description": "Run search", "inputSchema": {"type": "object"}},
                    {"name": "list_indexes", "description": "List indexes"},
                ]
            },
        }

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = mock_tools
            mock_resp.raise_for_status = MagicMock()
            mock_client.post = AsyncMock(return_value=mock_resp)
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            tools = await _discover_tools(server, {}, timeout=5, max_retries=0)
            assert len(tools) == 2
            assert tools[0]["name"] == "search"

    @pytest.mark.asyncio
    async def test_discover_tools_no_endpoint(self):
        from mcp_utils import _discover_tools
        tools = await _discover_tools({"name": "empty", "endpoint": ""}, {})
        assert tools == []

    @pytest.mark.asyncio
    async def test_discover_tools_server_down(self):
        from mcp_utils import _discover_tools
        import httpx

        server = {"name": "down", "endpoint": "http://localhost:1"}

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))
            mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

            tools = await _discover_tools(server, {}, timeout=2, max_retries=1)
            assert tools == []


# ---------------------------------------------------------------------------
# 5. load_mcp_tools_from_registry Tests
# ---------------------------------------------------------------------------

class TestLoadFromRegistry:
    """Test load_mcp_tools_from_registry."""

    @pytest.mark.asyncio
    async def test_load_tools_from_registry(self, sample_config_yaml):
        from mcp_utils import load_mcp_tools_from_registry

        mock_tools_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "tools": [
                    {"name": "search", "description": "Run Splunk search"},
                ]
            },
        }

        with patch("mcp_registry.DEFAULT_CONFIG_PATH", sample_config_yaml):
            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_resp.json.return_value = mock_tools_response
                mock_resp.raise_for_status = MagicMock()
                mock_client.post = AsyncMock(return_value=mock_resp)
                mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                tools = await load_mcp_tools_from_registry()
                # test-splunk + test-github (not disabled, not stdio)
                assert len(tools) >= 1
                assert any(t.name == "search" for t in tools)

    @pytest.mark.asyncio
    async def test_load_tools_skips_stdio(self, sample_config_yaml):
        """Stdio servers are skipped in HTTP-only mode."""
        from mcp_utils import load_mcp_tools_from_registry

        with patch("mcp_registry.DEFAULT_CONFIG_PATH", sample_config_yaml):
            with patch("mcp_utils._discover_tools", new_callable=AsyncMock) as mock_discover:
                mock_discover.return_value = []
                await load_mcp_tools_from_registry()
                # Should not be called for stdio server
                called_servers = [c.args[0]["name"] for c in mock_discover.call_args_list]
                assert "test-stdio" not in called_servers

    @pytest.mark.asyncio
    async def test_load_tools_empty_registry(self, disabled_config_yaml):
        from mcp_utils import load_mcp_tools_from_registry
        with patch("mcp_registry.DEFAULT_CONFIG_PATH", disabled_config_yaml):
            tools = await load_mcp_tools_from_registry()
            assert tools == []

    @pytest.mark.asyncio
    async def test_load_tools_with_user_tokens(self, sample_config_yaml):
        from mcp_utils import load_mcp_tools_from_registry

        with patch("mcp_registry.DEFAULT_CONFIG_PATH", sample_config_yaml):
            with patch("mcp_utils._discover_tools", new_callable=AsyncMock) as mock_discover:
                mock_discover.return_value = [{"name": "t1", "description": "d1"}]
                tools = await load_mcp_tools_from_registry(
                    user_tokens={"test-splunk": "my-secret-token"}
                )
                # Verify auth headers were passed
                for call in mock_discover.call_args_list:
                    server = call.args[0]
                    headers = call.args[1]
                    if server["name"] == "test-splunk":
                        assert "Authorization" in headers
                        assert "my-secret-token" in headers["Authorization"]


# ---------------------------------------------------------------------------
# 6. Tool Executor Tests
# ---------------------------------------------------------------------------

class TestToolExecutor:
    """Test tool_executor.py functions."""

    @pytest.mark.asyncio
    async def test_execute_tool_call_with_mcp_tool(self):
        from mcp_utils import MCPTool
        from tool_executor import execute_tool_call

        tool = MCPTool(name="my_tool", endpoint="http://localhost:9999")
        tool.ainvoke = AsyncMock(return_value="result data")

        result = await execute_tool_call(
            {"name": "my_tool", "args": {"q": "test"}},
            [tool],
        )
        assert result == "result data"
        tool.ainvoke.assert_called_once_with({"q": "test"})

    @pytest.mark.asyncio
    async def test_execute_tool_call_not_found(self):
        from tool_executor import execute_tool_call
        result = await execute_tool_call(
            {"name": "missing", "args": {}},
            [],
        )
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_execute_tool_call_exception(self):
        from mcp_utils import MCPTool
        from tool_executor import execute_tool_call

        tool = MCPTool(name="err_tool", endpoint="http://localhost:9999")
        tool.ainvoke = AsyncMock(side_effect=RuntimeError("boom"))

        result = await execute_tool_call(
            {"name": "err_tool", "args": {}},
            [tool],
        )
        assert "failed" in result.lower()

    def test_should_use_tools(self):
        from tool_executor import should_use_tools
        assert should_use_tools("run_search") is True
        assert should_use_tools("create_alert") is True
        assert should_use_tools("saved_search_analysis") is True
        assert should_use_tools("config_health_check") is True
        assert should_use_tools("general_qa") is False
        assert should_use_tools("spl_generation") is False


# ---------------------------------------------------------------------------
# 7. Prompt-based tool calling Tests
# ---------------------------------------------------------------------------

class TestPromptBasedToolCalling:
    """Test the prompt-based fallback tool calling."""

    def test_build_tool_descriptions(self):
        from mcp_utils import MCPTool
        from tool_executor import _build_tool_descriptions

        tools = [
            MCPTool(
                name="search",
                description="Run a Splunk search query",
                input_schema={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "SPL query"},
                    },
                },
            ),
            MCPTool(name="list_indexes", description="List available indexes"),
        ]
        desc = _build_tool_descriptions(tools)
        assert "search" in desc
        assert "list_indexes" in desc
        assert "SPL query" in desc
        assert "tool_name" in desc

    def test_parse_tool_call_json_block(self):
        from tool_executor import _parse_tool_call

        text = 'I need to search.\n```json\n{"tool": "search", "args": {"query": "index=main"}}\n```'
        result = _parse_tool_call(text)
        assert result is not None
        assert result["name"] == "search"
        assert result["args"]["query"] == "index=main"

    def test_parse_tool_call_bare_json(self):
        from tool_executor import _parse_tool_call
        text = '{"tool": "list_indexes", "args": {}}\n\nSome follow up text.'
        result = _parse_tool_call(text)
        assert result is not None
        assert result["name"] == "list_indexes"

    def test_parse_tool_call_no_tool(self):
        from tool_executor import _parse_tool_call
        text = "Here is a normal text response without any tool calls."
        assert _parse_tool_call(text) is None

    def test_parse_tool_call_invalid_json(self):
        from tool_executor import _parse_tool_call
        text = '```json\n{invalid json}\n```'
        assert _parse_tool_call(text) is None

    @pytest.mark.asyncio
    async def test_prompt_tool_loop(self):
        from mcp_utils import MCPTool
        from tool_executor import _run_prompt_tool_loop

        tool = MCPTool(name="search", description="Run search", endpoint="http://x")
        tool.ainvoke = AsyncMock(return_value="42 results found")

        mock_llm = MagicMock()
        # First call: LLM returns tool call
        # Second call: LLM returns final answer
        call_count = 0

        async def fake_ainvoke(prompt):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MagicMock(content='```json\n{"tool": "search", "args": {"query": "index=main"}}\n```')
            return MagicMock(content="The search returned 42 results from the main index.")

        mock_llm.ainvoke = fake_ainvoke

        result = await _run_prompt_tool_loop(
            "How many events in main index?",
            mock_llm,
            [tool],
            system_prompt="You are a Splunk assistant.",
        )
        assert result is not None
        assert "42 results" in result


# ---------------------------------------------------------------------------
# 8. run_tool_augmented_query integration
# ---------------------------------------------------------------------------

class TestRunToolAugmented:
    """Test the public run_tool_augmented_query entry point."""

    @pytest.mark.asyncio
    async def test_returns_none_with_no_tools(self):
        from tool_executor import run_tool_augmented_query
        result = await run_tool_augmented_query("test", MagicMock(), [])
        assert result is None

    @pytest.mark.asyncio
    async def test_falls_back_to_prompt_based(self):
        """When native tool calling is unavailable, falls back to prompt-based."""
        from mcp_utils import MCPTool
        from tool_executor import run_tool_augmented_query

        tool = MCPTool(name="search", description="Run search", endpoint="http://x")
        tool.ainvoke = AsyncMock(return_value="search results")

        mock_llm = MagicMock()
        mock_llm.ainvoke = AsyncMock(return_value=MagicMock(content="Final answer based on search results"))

        with patch("tool_executor._TOOL_CALLING_AVAILABLE", False):
            result = await run_tool_augmented_query(
                "search for errors",
                mock_llm,
                [tool],
            )
            assert result is not None


# ---------------------------------------------------------------------------
# 9. Backward-compatible load_splunk_mcp_tools
# ---------------------------------------------------------------------------

class TestBackwardCompat:
    """Test the legacy load_splunk_mcp_tools function."""

    def test_load_splunk_mcp_tools_returns_list(self):
        from mcp_utils import load_splunk_mcp_tools
        with patch("mcp_utils.load_mcp_tools_from_registry") as mock_load:
            mock_load.side_effect = RuntimeError("no servers")
            tools = load_splunk_mcp_tools()
            assert isinstance(tools, list)

    def test_load_splunk_mcp_tools_ignores_params(self):
        """URI and client_name params are ignored (config-driven now)."""
        from mcp_utils import load_splunk_mcp_tools
        with patch("mcp_utils.load_mcp_tools_from_registry") as mock_load:
            mock_load.side_effect = RuntimeError("test")
            tools = load_splunk_mcp_tools(uri="ws://custom:1234", client_name="custom")
            assert isinstance(tools, list)


# ---------------------------------------------------------------------------
# 10. MCP Handler Tests
# ---------------------------------------------------------------------------

class TestMCPHandler:
    """Test mcp_handler.py exports."""

    def test_handler_exports(self):
        import mcp_handler
        assert hasattr(mcp_handler, "__all__")
        assert "on_mcp_connect" in mcp_handler.__all__
        assert "on_mcp_disconnect" in mcp_handler.__all__

    def test_handler_functions_are_callable(self):
        import mcp_handler
        assert callable(mcp_handler.on_mcp_connect)
        assert callable(mcp_handler.on_mcp_disconnect)
