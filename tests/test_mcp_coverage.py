"""Tests for MCP tool coverage — verify all tools are registered, handlers exist, schemas valid."""

import pytest


class TestMCPToolRegistration:
    """Verify all MCP tools have matching handlers."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from chat_app.mcp_server_mode import MCP_TOOLS, _HANDLERS
        self.tools = MCP_TOOLS
        self.handlers = _HANDLERS

    def test_all_tools_have_handlers(self):
        """Every MCP tool must have a registered handler."""
        tool_names = {t["name"] for t in self.tools}
        handler_names = set(self.handlers.keys())
        missing = tool_names - handler_names
        assert not missing, f"Tools without handlers: {missing}"

    def test_all_handlers_have_tools(self):
        """Every handler must correspond to a defined tool."""
        tool_names = {t["name"] for t in self.tools}
        handler_names = set(self.handlers.keys())
        orphan = handler_names - tool_names
        assert not orphan, f"Handlers without tools: {orphan}"

    def test_tool_count_minimum(self):
        """Should have at least 30 MCP tools."""
        assert len(self.tools) >= 30, f"Only {len(self.tools)} tools registered"

    def test_handler_count_matches(self):
        """Tool count and handler count must match."""
        assert len(self.tools) == len(self.handlers)


class TestMCPToolSchemas:
    """Verify all MCP tool schemas are well-formed."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from chat_app.mcp_server_mode import MCP_TOOLS
        self.tools = MCP_TOOLS

    def test_all_tools_have_required_fields(self):
        for tool in self.tools:
            assert "name" in tool, f"Tool missing 'name': {tool}"
            assert "description" in tool, f"Tool {tool.get('name', '?')} missing 'description'"
            assert "inputSchema" in tool, f"Tool {tool['name']} missing 'inputSchema'"
            assert "min_role" in tool, f"Tool {tool['name']} missing 'min_role'"

    def test_all_schemas_are_objects(self):
        for tool in self.tools:
            schema = tool["inputSchema"]
            assert schema.get("type") == "object", f"Tool {tool['name']} schema type is not 'object'"

    def test_required_params_in_properties(self):
        """All required params must be defined in properties."""
        for tool in self.tools:
            schema = tool["inputSchema"]
            required = set(schema.get("required", []))
            properties = set(schema.get("properties", {}).keys())
            missing = required - properties
            assert not missing, f"Tool {tool['name']}: required params not in properties: {missing}"

    def test_tool_names_are_prefixed(self):
        """All tool names should start with 'obsai_'."""
        for tool in self.tools:
            assert tool["name"].startswith("obsai_"), f"Tool name not prefixed: {tool['name']}"

    def test_min_roles_are_valid(self):
        valid_roles = {"VIEWER", "USER", "ANALYST", "ADMIN"}
        for tool in self.tools:
            assert tool["min_role"] in valid_roles, f"Tool {tool['name']} has invalid min_role: {tool['min_role']}"


class TestMCPToolCategories:
    """Verify good coverage across tool categories."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from chat_app.mcp_server_mode import MCP_TOOLS
        self.tool_names = [t["name"] for t in MCP_TOOLS]

    def test_has_spl_tools(self):
        spl_tools = [n for n in self.tool_names if "spl" in n.lower() or "search" in n.lower() or "explain" in n.lower()]
        assert len(spl_tools) >= 5, f"Only {len(spl_tools)} SPL tools"

    def test_has_scripting_tools(self):
        script_tools = [n for n in self.tool_names if "ansible" in n or "shell" in n or "python" in n]
        assert len(script_tools) >= 3, f"Only {len(script_tools)} scripting tools"

    def test_has_utility_tools(self):
        util_tools = [n for n in self.tool_names if any(x in n for x in ["encode", "hash", "transform", "text", "validate"])]
        assert len(util_tools) >= 5, f"Only {len(util_tools)} utility tools"

    def test_has_admin_tools(self):
        admin_tools = [n for n in self.tool_names if any(x in n for x in ["config", "container", "health", "security", "collection"])]
        assert len(admin_tools) >= 5, f"Only {len(admin_tools)} admin tools"

    def test_has_orchestration_tools(self):
        orch_tools = [n for n in self.tool_names if any(x in n for x in ["orchestrate", "agent", "reason"])]
        assert len(orch_tools) >= 2, f"Only {len(orch_tools)} orchestration tools"


class TestMCPHandlerResolution:
    """Verify handlers can be resolved (function exists in module)."""

    def test_all_handlers_resolvable(self):
        from chat_app.mcp_server_mode import _HANDLERS

        for tool_name, handler_value in _HANDLERS.items():
            # _HANDLERS maps tool names to callables (post-split) or strings (legacy)
            if callable(handler_value):
                assert callable(handler_value), f"Handler for tool '{tool_name}' is not callable"
            else:
                # Legacy string-based handler name — look up in module
                import chat_app.mcp_server_mode as mod
                handler_fn = getattr(mod, handler_value, None)
                assert handler_fn is not None, f"Handler function '{handler_value}' not found for tool '{tool_name}'"
                assert callable(handler_fn), f"Handler '{handler_value}' is not callable"


class TestMCPToolAccessControl:
    """Verify access control works."""

    def test_check_tool_access(self):
        from chat_app.mcp_server_mode import check_tool_access
        # ADMIN tools should require ADMIN
        assert check_tool_access("obsai_config_update", "ADMIN") is True
        assert check_tool_access("obsai_config_update", "USER") is False
        # VIEWER tools accessible to all
        assert check_tool_access("obsai_health", "VIEWER") is True
        assert check_tool_access("obsai_health", "USER") is True

    def test_viewer_tools(self):
        from chat_app.mcp_server_mode import MCP_TOOLS
        viewer_tools = [t["name"] for t in MCP_TOOLS if t["min_role"] == "VIEWER"]
        assert len(viewer_tools) >= 5, "Not enough VIEWER-accessible tools"

    def test_user_tools(self):
        from chat_app.mcp_server_mode import MCP_TOOLS
        user_tools = [t["name"] for t in MCP_TOOLS if t["min_role"] in ("VIEWER", "USER")]
        assert len(user_tools) >= 15, "Not enough USER-accessible tools"


class TestSlashCommandMCPParity:
    """Verify key slash commands have MCP equivalents."""

    @pytest.fixture(autouse=True)
    def setup(self):
        from chat_app.mcp_server_mode import MCP_TOOLS
        self.tool_names = {t["name"] for t in MCP_TOOLS}

    @pytest.mark.parametrize("command,expected_tool", [
        ("/search", "obsai_search"),
        ("/explain", "obsai_explain_spl"),
        ("/run", "obsai_run_search"),
        ("/health", "obsai_health"),
        ("/kg", "obsai_kg_query"),
        ("/doc", "obsai_generate_docs"),
        ("/spec", "obsai_spec_lookup"),
        ("/build_config", "obsai_build_config"),
        ("/create_alert", "obsai_create_alert"),
        ("/skill", "obsai_orchestrate"),
    ])
    def test_command_has_mcp_tool(self, command, expected_tool):
        assert expected_tool in self.tool_names, f"Command {command} has no MCP tool {expected_tool}"
