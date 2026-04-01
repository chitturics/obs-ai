"""
Agentic Tool Registry — Declarative tool system for the Splunk/Cribl/Observability Assistant.

Each tool declares:
- name, description, parameter schema
- required capabilities (e.g., splunk_connected, mcp_available)
- execution function
- result formatting

The registry is queried by the ReAct loop to decide which tools are
available for a given query/intent.
"""
import asyncio
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class ToolCategory(str, Enum):
    SPLUNK = "splunk"
    CRIBL = "cribl"
    OBSERVABILITY = "observability"
    KNOWLEDGE = "knowledge"
    ANALYSIS = "analysis"
    GENERATION = "generation"
    ADMIN = "admin"


@dataclass
class ToolParameter:
    """A single parameter for a tool."""
    name: str
    description: str
    param_type: str = "string"  # string, int, float, bool, list
    required: bool = False
    default: Any = None


@dataclass
class ToolResult:
    """Standardized result from a tool execution."""
    success: bool
    output: str
    data: Any = None
    error: Optional[str] = None
    suggestions: List[str] = field(default_factory=list)

    def format_for_context(self) -> str:
        """Format this result for injection into the LLM context."""
        if not self.success:
            return f"[Tool Error] {self.error or 'Unknown error'}"
        return self.output


@dataclass
class Tool:
    """A registered agentic tool."""
    name: str
    description: str
    category: ToolCategory
    parameters: List[ToolParameter] = field(default_factory=list)
    requires: Set[str] = field(default_factory=set)  # e.g. {"splunk_connected"}
    intents: List[str] = field(default_factory=list)  # Intents this tool handles
    execute_fn: Optional[Callable] = None
    max_retries: int = 1
    timeout_seconds: int = 30

    @property
    def param_names(self) -> List[str]:
        return [p.name for p in self.parameters]


class ToolRegistry:
    """Central registry of all available agentic tools."""

    def __init__(self):
        self._tools: Dict[str, Tool] = {}
        self._intent_map: Dict[str, List[str]] = {}  # intent -> tool names
        self._capabilities: Set[str] = set()

    def register(self, tool: Tool):
        """Register a tool."""
        self._tools[tool.name] = tool
        for intent in tool.intents:
            self._intent_map.setdefault(intent, []).append(tool.name)
        logger.debug(f"[TOOLS] Registered: {tool.name} ({tool.category.value})")

    def set_capabilities(self, capabilities: Set[str]):
        """Update the current system capabilities (e.g., splunk_connected)."""
        self._capabilities = capabilities

    def add_capability(self, capability: str):
        self._capabilities.add(capability)

    def remove_capability(self, capability: str):
        self._capabilities.discard(capability)

    def get_tool(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def get_tools_for_intent(self, intent: str) -> List[Tool]:
        """Get all available tools for a given intent."""
        tool_names = self._intent_map.get(intent, [])
        available = []
        for name in tool_names:
            tool = self._tools[name]
            if tool.requires.issubset(self._capabilities):
                available.append(tool)
        return available

    def get_available_tools(self) -> List[Tool]:
        """Get all currently available tools (capabilities satisfied)."""
        return [
            t for t in self._tools.values()
            if t.requires.issubset(self._capabilities)
        ]

    def list_tools_summary(self) -> str:
        """Generate a summary of available tools for the LLM context."""
        available = self.get_available_tools()
        if not available:
            return "No tools currently available."

        lines = ["Available tools:"]
        for tool in sorted(available, key=lambda t: t.category.value):
            params = ", ".join(
                f"{p.name}: {p.param_type}" + (" (required)" if p.required else "")
                for p in tool.parameters
            )
            lines.append(
                f"- **{tool.name}** [{tool.category.value}]: {tool.description}"
                + (f" | Params: {params}" if params else "")
            )
        return "\n".join(lines)

    def validate_params(self, tool: Tool, kwargs: Dict[str, Any]) -> Optional[str]:
        """Validate parameters against the tool's parameter spec.

        Returns None if valid, or an error message string.
        """
        _type_map = {
            "string": str, "str": str,
            "int": int, "integer": int,
            "float": float, "number": float,
            "bool": bool, "boolean": bool,
            "list": list,
        }

        for param in tool.parameters:
            if param.required and param.name not in kwargs:
                return f"Missing required parameter: '{param.name}'"

            if param.name in kwargs:
                value = kwargs[param.name]
                expected_type = _type_map.get(param.param_type)
                if expected_type and value is not None and not isinstance(value, expected_type):
                    # Try coercion for basic types
                    try:
                        if expected_type == int:
                            kwargs[param.name] = int(value)
                        elif expected_type == float:
                            kwargs[param.name] = float(value)
                        elif expected_type == bool:
                            kwargs[param.name] = str(value).lower() in ("true", "1", "yes")
                        elif expected_type == str:
                            kwargs[param.name] = str(value)
                    except (ValueError, TypeError):
                        return (
                            f"Parameter '{param.name}' expected {param.param_type}, "
                            f"got {type(value).__name__}"
                        )

        return None

    async def execute(self, tool_name: str, **kwargs) -> ToolResult:
        """Execute a tool by name with the given arguments."""
        tool = self._tools.get(tool_name)
        if not tool:
            return ToolResult(success=False, output="", error=f"Unknown tool: {tool_name}")

        if not tool.requires.issubset(self._capabilities):
            missing = tool.requires - self._capabilities
            return ToolResult(
                success=False, output="",
                error=f"Tool '{tool_name}' requires: {', '.join(missing)}",
            )

        if not tool.execute_fn:
            return ToolResult(success=False, output="", error=f"Tool '{tool_name}' has no execute function")

        # Validate parameters
        if tool.parameters:
            validation_error = self.validate_params(tool, kwargs)
            if validation_error:
                return ToolResult(
                    success=False, output="",
                    error=f"Parameter validation failed for '{tool_name}': {validation_error}",
                )

        for attempt in range(tool.max_retries):
            try:
                if asyncio.iscoroutinefunction(tool.execute_fn):
                    result = await asyncio.wait_for(
                        tool.execute_fn(**kwargs),
                        timeout=tool.timeout_seconds,
                    )
                else:
                    result = await asyncio.wait_for(
                        asyncio.to_thread(tool.execute_fn, **kwargs),
                        timeout=tool.timeout_seconds,
                    )

                if isinstance(result, ToolResult):
                    return result
                return ToolResult(success=True, output=str(result))

            except asyncio.TimeoutError:
                if attempt < tool.max_retries - 1:
                    logger.warning(f"[TOOLS] {tool_name} timed out, retrying ({attempt + 1}/{tool.max_retries})")
                    continue
                return ToolResult(success=False, output="", error=f"Tool '{tool_name}' timed out after {tool.timeout_seconds}s")
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                if attempt < tool.max_retries - 1:
                    logger.warning(f"[TOOLS] {tool_name} failed, retrying: {exc}")
                    continue
                return ToolResult(success=False, output="", error=f"Tool '{tool_name}' failed: {exc}")

        return ToolResult(success=False, output="", error=f"Tool '{tool_name}' exhausted retries")


# ---------------------------------------------------------------------------
# Singleton registry
# ---------------------------------------------------------------------------
_registry = ToolRegistry()


def get_tool_registry() -> ToolRegistry:
    return _registry


# ---------------------------------------------------------------------------
# Built-in tool registration (implementations in tool_definitions.py)
# ---------------------------------------------------------------------------

from chat_app.tool_definitions import register_builtin_tools  # noqa: F401
register_builtin_tools()

# Backward-compatible re-exports (moved to tool_definitions / tool_implementations)
from chat_app.tool_definitions import register_builtin_tools as _register_builtin_tools  # noqa: F401
from chat_app.tool_implementations import (  # noqa: F401
    _tool_analyze_configs,
    _tool_analyze_cribl_pipeline,
    _tool_analyze_spl,
    _tool_check_splunk_health,
    _tool_create_knowledge_object,
    _tool_generate_cribl_route,
    _tool_generate_spl,
    _tool_get_license_usage,
    _tool_get_server_info,
    _tool_list_apps,
    _tool_list_deployment_clients,
    _tool_list_indexes,
    _tool_list_inputs,
    _tool_list_lookups,
    _tool_list_macros,
    _tool_list_saved_searches,
    _tool_list_users,
    _tool_lookup_config,
    _tool_optimize_spl,
    _tool_run_splunk_search,
    _tool_search_index_stats,
    _tool_search_kb,
    _tool_suggest_metrics_query,
    _tool_update_saved_search,
    _tool_validate_spl,
)
