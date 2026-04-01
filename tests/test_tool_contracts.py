"""Contract tests for the unified tool registry.

Validates structural invariants across ALL tools/skills/MCP definitions:
- Input/output schema validity
- Description requirements
- Handler key existence
- MCP-specific constraints
- Role hierarchy correctness
- Capability discovery accuracy
"""
import pytest
from unittest.mock import patch, MagicMock

from chat_app.unified_registry import (
    get_unified_registry,
    reload_unified_registry,
    ToolDefinition,
    UnifiedToolRegistry,
    _ROLE_LEVELS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def registry():
    """Return the singleton unified registry (loads all 4 source registries)."""
    return get_unified_registry()


@pytest.fixture
def fresh_registry():
    """Force a full reload so tests see the latest catalog state."""
    return reload_unified_registry()


@pytest.fixture
def all_tools(registry):
    """All registered tool definitions."""
    return registry.get_all()


@pytest.fixture
def mcp_tools(registry):
    """Only MCP-exposed tools."""
    return registry.get_mcp_tools()


@pytest.fixture
def skill_tools(registry):
    """Only skill-exposed tools."""
    return registry.get_skills()


@pytest.fixture
def sample_tool():
    """A minimal valid ToolDefinition for unit-level tests."""
    return ToolDefinition(
        id="test:sample",
        name="sample_tool",
        description="A sample tool for contract testing purposes",
        category="test",
        handler_key="sample_handler",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
        output_schema={
            "type": "object",
            "properties": {
                "result": {"type": "string"},
            },
        },
        tags=["test", "sample"],
        intents=["general_qa"],
        min_role="USER",
        enabled=True,
        expose_as_mcp=True,
        source_registry="test",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Contract Tests — structural invariants that every tool MUST satisfy
# ═══════════════════════════════════════════════════════════════════════════════

class TestToolDescriptions:
    """Every tool must have a meaningful description."""

    def test_all_tools_have_descriptions(self, all_tools):
        """Every tool description must be longer than 10 characters."""
        for tool in all_tools:
            assert len(tool.description) > 10, (
                f"Tool {tool.id} has short description ({len(tool.description)} chars): "
                f"'{tool.description}'"
            )

    def test_descriptions_are_strings(self, all_tools):
        """Descriptions must be plain strings, not None or other types."""
        for tool in all_tools:
            assert isinstance(tool.description, str), (
                f"Tool {tool.id} description is {type(tool.description).__name__}, not str"
            )

    def test_descriptions_not_placeholder(self, all_tools):
        """Descriptions must not be generic placeholders."""
        placeholders = {"todo", "fixme", "tbd", "placeholder", "n/a", "none"}
        for tool in all_tools:
            assert tool.description.lower().strip() not in placeholders, (
                f"Tool {tool.id} has placeholder description: '{tool.description}'"
            )


class TestToolHandlers:
    """Every tool must have a valid handler_key."""

    def test_all_tools_have_handler_key(self, all_tools):
        """handler_key must be a non-empty string."""
        for tool in all_tools:
            assert tool.handler_key, (
                f"Tool {tool.id} has no handler_key"
            )

    def test_handler_keys_are_strings(self, all_tools):
        """handler_key must be a string."""
        for tool in all_tools:
            assert isinstance(tool.handler_key, str), (
                f"Tool {tool.id} handler_key is {type(tool.handler_key).__name__}"
            )

    def test_handler_keys_are_identifiers(self, all_tools):
        """handler_key should be a valid Python-ish identifier (alphanumeric + underscores + hyphens)."""
        import re
        pattern = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_\-]*$")
        for tool in all_tools:
            if tool.handler_key:
                assert pattern.match(tool.handler_key), (
                    f"Tool {tool.id} handler_key '{tool.handler_key}' is not a valid identifier"
                )


class TestToolInputSchemas:
    """Input schemas must be valid JSON Schema objects when present."""

    def test_input_schema_is_dict_when_present(self, all_tools):
        """If input_schema is set, it must be a dict."""
        for tool in all_tools:
            if tool.input_schema:
                assert isinstance(tool.input_schema, dict), (
                    f"Tool {tool.id} input_schema is {type(tool.input_schema).__name__}, not dict"
                )

    def test_input_schema_has_type_field(self, all_tools):
        """Non-empty input schemas must have a 'type' field."""
        for tool in all_tools:
            if tool.input_schema:
                assert "type" in tool.input_schema, (
                    f"Tool {tool.id} input_schema missing 'type' field"
                )

    def test_input_schema_type_is_object(self, all_tools):
        """Input schemas should declare type=object (tools accept named params)."""
        for tool in all_tools:
            if tool.input_schema and "type" in tool.input_schema:
                assert tool.input_schema["type"] == "object", (
                    f"Tool {tool.id} input_schema type is '{tool.input_schema['type']}', expected 'object'"
                )

    def test_input_schema_properties_are_dicts(self, all_tools):
        """If properties key exists, its value must be a dict of dicts."""
        for tool in all_tools:
            if tool.input_schema and "properties" in tool.input_schema:
                props = tool.input_schema["properties"]
                assert isinstance(props, dict), (
                    f"Tool {tool.id} input_schema.properties is {type(props).__name__}"
                )
                for pname, pdef in props.items():
                    assert isinstance(pdef, dict), (
                        f"Tool {tool.id} input_schema.properties.{pname} is "
                        f"{type(pdef).__name__}, expected dict"
                    )

    def test_required_fields_are_lists(self, all_tools):
        """If 'required' is specified, it must be a list of strings."""
        for tool in all_tools:
            if tool.input_schema and "required" in tool.input_schema:
                req = tool.input_schema["required"]
                assert isinstance(req, list), (
                    f"Tool {tool.id} input_schema.required is {type(req).__name__}"
                )
                for item in req:
                    assert isinstance(item, str), (
                        f"Tool {tool.id} input_schema.required contains non-string: {item!r}"
                    )

    def test_required_fields_exist_in_properties(self, all_tools):
        """Every field listed in 'required' must exist in 'properties'."""
        for tool in all_tools:
            schema = tool.input_schema
            if schema and "required" in schema and "properties" in schema:
                props = set(schema["properties"].keys())
                for req_field in schema["required"]:
                    assert req_field in props, (
                        f"Tool {tool.id}: required field '{req_field}' not in properties {props}"
                    )


class TestToolOutputSchemas:
    """Output schemas must be valid JSON Schema objects when present."""

    def test_output_schema_is_dict_when_present(self, all_tools):
        """If output_schema is set, it must be a dict."""
        for tool in all_tools:
            if tool.output_schema:
                assert isinstance(tool.output_schema, dict), (
                    f"Tool {tool.id} output_schema is {type(tool.output_schema).__name__}"
                )

    def test_output_schema_has_type_when_present(self, all_tools):
        """Non-empty output schemas must have a 'type' field."""
        for tool in all_tools:
            if tool.output_schema:
                assert "type" in tool.output_schema, (
                    f"Tool {tool.id} output_schema missing 'type' field"
                )


class TestMCPToolContracts:
    """MCP-exposed tools have stricter requirements."""

    def test_all_mcp_tools_have_input_schemas(self, mcp_tools):
        """Every MCP tool MUST have an input_schema (MCP protocol requirement)."""
        for tool in mcp_tools:
            assert tool.input_schema, (
                f"MCP tool {tool.id} must have input_schema (MCP protocol requires it)"
            )

    def test_mcp_schemas_have_type_object(self, mcp_tools):
        """MCP input schemas must be type=object."""
        for tool in mcp_tools:
            if tool.input_schema:
                assert tool.input_schema.get("type") == "object", (
                    f"MCP tool {tool.id} input_schema.type must be 'object'"
                )

    def test_mcp_tools_have_mcp_tag(self, mcp_tools):
        """MCP tools should be tagged with 'mcp'."""
        for tool in mcp_tools:
            assert "mcp" in tool.tags, (
                f"MCP tool {tool.id} missing 'mcp' tag"
            )

    def test_mcp_tool_names_are_lowercase(self, mcp_tools):
        """MCP tool names should be lowercase with underscores (convention)."""
        import re
        pattern = re.compile(r"^[a-z][a-z0-9_]*$")
        for tool in mcp_tools:
            assert pattern.match(tool.handler_key), (
                f"MCP tool {tool.id} handler_key '{tool.handler_key}' not lowercase_underscore"
            )

    def test_mcp_to_mcp_schema_format(self, mcp_tools):
        """to_mcp_schema() must return name, description, inputSchema."""
        for tool in mcp_tools:
            schema = tool.to_mcp_schema()
            assert "name" in schema, f"MCP tool {tool.id} to_mcp_schema() missing 'name'"
            assert "description" in schema, f"MCP tool {tool.id} to_mcp_schema() missing 'description'"
            assert "inputSchema" in schema, f"MCP tool {tool.id} to_mcp_schema() missing 'inputSchema'"
            assert isinstance(schema["inputSchema"], dict), (
                f"MCP tool {tool.id} inputSchema is not a dict"
            )


class TestToolRoles:
    """Access control roles must be valid."""

    VALID_ROLES = {"VIEWER", "USER", "ANALYST", "ADMIN"}

    def test_all_tools_have_valid_min_role(self, all_tools):
        """min_role must be one of the 4 valid roles."""
        for tool in all_tools:
            assert tool.min_role in self.VALID_ROLES, (
                f"Tool {tool.id} has invalid min_role '{tool.min_role}'. "
                f"Valid roles: {self.VALID_ROLES}"
            )

    def test_role_hierarchy_levels_complete(self):
        """The _ROLE_LEVELS dict must have all 4 roles."""
        for role in self.VALID_ROLES:
            assert role in _ROLE_LEVELS, f"Role '{role}' missing from _ROLE_LEVELS"

    def test_role_levels_are_ordered(self):
        """VIEWER < USER < ANALYST < ADMIN."""
        assert _ROLE_LEVELS["VIEWER"] < _ROLE_LEVELS["USER"]
        assert _ROLE_LEVELS["USER"] < _ROLE_LEVELS["ANALYST"]
        assert _ROLE_LEVELS["ANALYST"] < _ROLE_LEVELS["ADMIN"]


class TestToolCategories:
    """Category metadata must be consistent."""

    def test_all_tools_have_category(self, all_tools):
        """Every tool must have a non-empty category."""
        for tool in all_tools:
            assert tool.category, (
                f"Tool {tool.id} has empty category"
            )

    def test_categories_are_strings(self, all_tools):
        """Categories must be plain strings."""
        for tool in all_tools:
            assert isinstance(tool.category, str), (
                f"Tool {tool.id} category is {type(tool.category).__name__}"
            )


class TestToolIDs:
    """Tool IDs must be unique and well-formed."""

    def test_ids_are_unique(self, all_tools):
        """No two tools may share the same ID."""
        seen = {}
        for tool in all_tools:
            assert tool.id not in seen, (
                f"Duplicate tool ID '{tool.id}': first registered as "
                f"'{seen[tool.id]}', duplicate is '{tool.name}'"
            )
            seen[tool.id] = tool.name

    def test_ids_have_prefix(self, all_tools):
        """IDs should follow the prefix:name convention."""
        for tool in all_tools:
            assert ":" in tool.id, (
                f"Tool ID '{tool.id}' missing prefix:name format"
            )

    def test_ids_are_non_empty(self, all_tools):
        """IDs must not be empty."""
        for tool in all_tools:
            assert tool.id, f"Found tool with empty ID: name={tool.name}"


class TestToolMetadata:
    """General metadata consistency checks."""

    def test_all_tools_have_names(self, all_tools):
        """Every tool must have a non-empty name."""
        for tool in all_tools:
            assert tool.name, f"Tool {tool.id} has empty name"

    def test_all_tools_have_source_registry(self, all_tools):
        """Every tool must declare which registry it came from."""
        for tool in all_tools:
            assert tool.source_registry, (
                f"Tool {tool.id} has empty source_registry"
            )

    def test_tags_are_lists_of_strings(self, all_tools):
        """tags must be a list of strings."""
        for tool in all_tools:
            assert isinstance(tool.tags, list), (
                f"Tool {tool.id} tags is {type(tool.tags).__name__}"
            )
            for tag in tool.tags:
                assert isinstance(tag, str), (
                    f"Tool {tool.id} has non-string tag: {tag!r}"
                )

    def test_intents_are_lists_of_strings(self, all_tools):
        """intents must be a list of strings."""
        for tool in all_tools:
            assert isinstance(tool.intents, list), (
                f"Tool {tool.id} intents is {type(tool.intents).__name__}"
            )
            for intent in tool.intents:
                assert isinstance(intent, str), (
                    f"Tool {tool.id} has non-string intent: {intent!r}"
                )

    def test_enabled_is_bool(self, all_tools):
        """enabled must be a boolean."""
        for tool in all_tools:
            assert isinstance(tool.enabled, bool), (
                f"Tool {tool.id} enabled is {type(tool.enabled).__name__}"
            )

    def test_timeout_is_positive(self, all_tools):
        """timeout_seconds must be positive."""
        for tool in all_tools:
            assert tool.timeout_seconds > 0, (
                f"Tool {tool.id} has non-positive timeout: {tool.timeout_seconds}"
            )


class TestToolSerialization:
    """to_dict() and to_mcp_schema() must produce well-formed output."""

    def test_to_dict_returns_dict(self, all_tools):
        """to_dict() must return a plain dict."""
        for tool in all_tools:
            d = tool.to_dict()
            assert isinstance(d, dict), f"Tool {tool.id} to_dict() returned {type(d).__name__}"

    def test_to_dict_has_required_keys(self, all_tools):
        """to_dict() must include all essential keys."""
        required_keys = {"id", "name", "description", "category", "handler_key", "min_role", "enabled"}
        for tool in all_tools:
            d = tool.to_dict()
            missing = required_keys - set(d.keys())
            assert not missing, (
                f"Tool {tool.id} to_dict() missing keys: {missing}"
            )

    def test_to_dict_roundtrip_id(self, all_tools):
        """to_dict()['id'] must match the tool's actual ID."""
        for tool in all_tools:
            assert tool.to_dict()["id"] == tool.id

    def test_to_mcp_schema_on_sample(self, sample_tool):
        """to_mcp_schema() returns well-formed MCP tool definition."""
        schema = sample_tool.to_mcp_schema()
        assert schema["name"] == "sample_handler"
        assert schema["description"] == sample_tool.description
        assert schema["inputSchema"] == sample_tool.input_schema


# ═══════════════════════════════════════════════════════════════════════════════
# Capability Discovery Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestCapabilityDiscovery:
    """Tests for the availability checking and capability report system."""

    def test_check_availability_enabled_tool(self, sample_tool):
        """An enabled tool with no service deps should be 'available'."""
        reg = UnifiedToolRegistry()
        reg._tools[sample_tool.id] = sample_tool
        result = reg._check_tool_availability(sample_tool)
        assert result["status"] == "available"
        assert result["reason"] == ""

    def test_check_availability_disabled_tool(self, sample_tool):
        """A disabled tool should be 'unavailable'."""
        sample_tool.enabled = False
        reg = UnifiedToolRegistry()
        reg._tools[sample_tool.id] = sample_tool
        result = reg._check_tool_availability(sample_tool)
        assert result["status"] == "unavailable"
        assert "Disabled" in result["reason"]

    def test_check_availability_approval_gated(self, sample_tool):
        """A tool requiring approval should be 'degraded'."""
        sample_tool.requires_approval = True
        sample_tool.approval_type = "confirm"
        reg = UnifiedToolRegistry()
        reg._tools[sample_tool.id] = sample_tool
        result = reg._check_tool_availability(sample_tool)
        assert result["status"] == "degraded"
        assert "confirm" in result["reason"].lower() or "approval" in result["reason"].lower()

    def test_check_availability_splunk_unconfigured(self):
        """A splunk-tagged tool should be unavailable when Splunk is not configured."""
        tool = ToolDefinition(
            id="test:splunk_tool",
            name="splunk_test",
            description="A test tool that requires Splunk connectivity",
            category="splunk",
            handler_key="splunk_test_handler",
            tags=["splunk"],
            enabled=True,
            source_registry="test",
        )
        reg = UnifiedToolRegistry()
        reg._tools[tool.id] = tool
        # Default settings have splunk unconfigured (no host set)
        result = reg._check_tool_availability(tool)
        assert result["status"] == "unavailable"
        assert "Splunk" in result["reason"]

    def test_check_availability_cribl_unconfigured(self):
        """A cribl-tagged tool should be unavailable when Cribl is not configured."""
        tool = ToolDefinition(
            id="test:cribl_tool",
            name="cribl_test",
            description="A test tool that requires Cribl connectivity",
            category="cribl",
            handler_key="cribl_test_handler",
            tags=["cribl"],
            enabled=True,
            source_registry="test",
        )
        reg = UnifiedToolRegistry()
        reg._tools[tool.id] = tool
        result = reg._check_tool_availability(tool)
        assert result["status"] == "unavailable"
        assert "Cribl" in result["reason"]

    def test_capability_status_unknown_tool(self, registry):
        """Querying a non-existent tool ID returns found=False."""
        result = registry.get_capability_status("nonexistent:tool")
        assert result["found"] is False
        assert "not found" in result["reason"].lower()

    def test_capability_report_structure(self, registry):
        """get_capability_report() returns all expected keys."""
        report = registry.get_capability_report()
        required_keys = {
            "total_tools", "enabled", "disabled", "requires_approval",
            "available_count", "unavailable_count", "degraded_count",
            "available", "unavailable", "degraded",
            "by_source_registry", "by_category", "by_exposure", "by_min_role",
            "deduplicated", "loaded_at", "timestamp",
        }
        missing = required_keys - set(report.keys())
        assert not missing, f"Capability report missing keys: {missing}"

    def test_capability_report_counts_consistent(self, registry):
        """available + unavailable + degraded should equal total_tools."""
        report = registry.get_capability_report()
        assert (
            report["available_count"] + report["unavailable_count"] + report["degraded_count"]
            == report["total_tools"]
        ), "Availability counts do not sum to total_tools"

    def test_capability_report_enabled_disabled_sum(self, registry):
        """enabled + disabled should equal total_tools."""
        report = registry.get_capability_report()
        assert report["enabled"] + report["disabled"] == report["total_tools"]

    def test_mcp_capabilities_structure(self, registry):
        """get_mcp_capabilities() returns expected keys."""
        caps = registry.get_mcp_capabilities()
        assert "tools" in caps
        assert "unavailable" in caps
        assert "total_mcp_tools" in caps
        assert "available_count" in caps
        assert "unavailable_count" in caps

    def test_mcp_capabilities_tools_have_schemas(self, registry):
        """Each available MCP tool in the capabilities response has a schema."""
        caps = registry.get_mcp_capabilities()
        for tool_schema in caps["tools"]:
            assert "name" in tool_schema
            assert "description" in tool_schema
            assert "inputSchema" in tool_schema

    def test_mcp_capabilities_unavailable_have_reasons(self, registry):
        """Each unavailable MCP tool has a reason string."""
        caps = registry.get_mcp_capabilities()
        for entry in caps["unavailable"]:
            assert "name" in entry
            assert "reason" in entry
            assert isinstance(entry["reason"], str)

    def test_mcp_capabilities_count_matches(self, registry):
        """available + unavailable should equal total_mcp_tools."""
        caps = registry.get_mcp_capabilities()
        assert caps["available_count"] + caps["unavailable_count"] == caps["total_mcp_tools"]


class TestRegistryQueries:
    """Test the query and filtering methods on the registry."""

    def test_get_all_returns_list(self, registry):
        """get_all() must return a list."""
        tools = registry.get_all()
        assert isinstance(tools, list)

    def test_registry_has_tools(self, registry):
        """Registry should have loaded at least some tools."""
        assert len(registry.get_all()) > 0, "Registry is empty -- no tools loaded"

    def test_get_for_role_viewer_subset_of_admin(self, registry):
        """VIEWER tools should be a subset of ADMIN tools."""
        viewer_ids = {t.id for t in registry.get_for_role("VIEWER")}
        admin_ids = {t.id for t in registry.get_for_role("ADMIN")}
        assert viewer_ids.issubset(admin_ids), (
            f"VIEWER has tools not available to ADMIN: {viewer_ids - admin_ids}"
        )

    def test_get_for_role_user_subset_of_analyst(self, registry):
        """USER tools should be a subset of ANALYST tools."""
        user_ids = {t.id for t in registry.get_for_role("USER")}
        analyst_ids = {t.id for t in registry.get_for_role("ANALYST")}
        assert user_ids.issubset(analyst_ids), (
            f"USER has tools not available to ANALYST: {user_ids - analyst_ids}"
        )

    def test_search_returns_matches(self, registry):
        """search() should find tools matching query text."""
        results = registry.search("spl")
        # There should be at least one SPL-related tool
        assert len(results) > 0, "No tools found for 'spl' search"

    def test_get_by_handler_returns_tool(self, registry):
        """get_by_handler() should find tools by handler_key."""
        all_tools = registry.get_all()
        if all_tools:
            first = all_tools[0]
            found = registry.get_by_handler(first.handler_key)
            assert found is not None
            assert found.handler_key == first.handler_key

    def test_intent_coverage_structure(self, registry):
        """get_intent_coverage() returns expected keys."""
        coverage = registry.get_intent_coverage()
        assert "covered_intents" in coverage
        assert "uncovered_intents" in coverage
        assert "total_covered" in coverage
        assert "total_uncovered" in coverage

    def test_category_index_matches_tools(self, registry):
        """Each category in the index should have tools that actually belong to it."""
        for tool in registry.get_all():
            cat_tools = registry.get_by_category(tool.category)
            tool_ids = {t.id for t in cat_tools}
            assert tool.id in tool_ids, (
                f"Tool {tool.id} not found in its own category '{tool.category}'"
            )


class TestToolDefinitionUnit:
    """Unit tests for ToolDefinition methods and defaults."""

    def test_default_values(self):
        """ToolDefinition defaults should be sensible."""
        td = ToolDefinition(
            id="test:defaults",
            name="defaults",
            description="Test default values",
            category="test",
            handler_key="defaults",
        )
        assert td.min_role == "USER"
        assert td.enabled is True
        assert td.requires_approval is False
        assert td.timeout_seconds == 30
        assert td.tags == []
        assert td.intents == []
        assert td.input_schema == {}
        assert td.output_schema == {}
        assert td.version == "1.0"

    def test_to_dict_includes_output_schema(self):
        """to_dict() should include output_schema."""
        td = ToolDefinition(
            id="test:out",
            name="out_test",
            description="Test output schema serialization",
            category="test",
            handler_key="out_test",
            output_schema={"type": "object", "properties": {"ok": {"type": "boolean"}}},
        )
        d = td.to_dict()
        assert "output_schema" in d
        assert d["output_schema"]["type"] == "object"

    def test_to_mcp_schema_defaults_empty_input(self):
        """to_mcp_schema() should provide a default empty-object schema if none set."""
        td = ToolDefinition(
            id="test:noinput",
            name="no_input",
            description="Tool with no input schema defined",
            category="test",
            handler_key="no_input",
        )
        schema = td.to_mcp_schema()
        assert schema["inputSchema"] == {"type": "object", "properties": {}}

    def test_to_mcp_schema_truncates_description(self):
        """to_mcp_schema() should truncate description to 1024 chars."""
        td = ToolDefinition(
            id="test:long",
            name="long_desc",
            description="A" * 2000,
            category="test",
            handler_key="long_desc",
        )
        schema = td.to_mcp_schema()
        assert len(schema["description"]) == 1024
