"""
Unified Tool Registry — Single source of truth for ALL tools, skills, and MCP definitions.

Solves DEAD-03: Previously there were 4 separate registries that could drift:
- tool_registry.py — 15 built-in tools (ReAct loop)
- skill_catalog.py — 122 skills (agent dispatcher)
- skills_manager.py — manifest.json packages (dynamic loading)
- mcp_server_mode.py — 10 MCP tools (external MCP clients)

This module provides a unified READ-ONLY view over all four registries.
The existing registries continue to own their data and execution logic;
this module imports, normalises and deduplicates them into a single
queryable collection of ``ToolDefinition`` objects.

Usage::

    from chat_app.unified_registry import get_unified_registry
    reg = get_unified_registry()
    tools = reg.search("spl")
    mcp   = reg.get_mcp_tools()
    report = reg.get_capability_report()
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Role hierarchy for access checks
_ROLE_LEVELS = {"VIEWER": 0, "USER": 1, "ANALYST": 2, "ADMIN": 3}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. ToolDefinition — normalised data class
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class ToolDefinition:
    """Unified representation of any capability in the system."""

    id: str                                          # Unique tool ID
    name: str                                        # Human-readable name
    description: str                                 # Trigger description (max 1024 chars)
    category: str                                    # spl, config, cribl, system, utility, etc.
    handler_key: str                                 # Maps to execution handler

    # Access control
    min_role: str = "USER"                           # VIEWER, USER, ANALYST, ADMIN
    requires_approval: bool = False
    approval_type: str = ""                          # "confirm", "review", ""

    # Execution
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    timeout_seconds: int = 30
    supports_dry_run: bool = False
    idempotent: bool = False

    # Discovery
    tags: List[str] = field(default_factory=list)
    intents: List[str] = field(default_factory=list)
    department: str = ""

    # Exposure — which subsystems surface this tool
    expose_as_skill: bool = True
    expose_as_mcp: bool = False
    expose_as_api: bool = False

    # Provenance — which registry originally owns this tool
    source_registry: str = ""                        # tool_registry, skill_catalog, skills_manager, mcp_server

    # Metadata
    enabled: bool = True
    version: str = "1.0"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description[:1024],
            "category": self.category,
            "handler_key": self.handler_key,
            "min_role": self.min_role,
            "requires_approval": self.requires_approval,
            "approval_type": self.approval_type,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "timeout_seconds": self.timeout_seconds,
            "supports_dry_run": self.supports_dry_run,
            "idempotent": self.idempotent,
            "tags": self.tags,
            "intents": self.intents,
            "department": self.department,
            "expose_as_skill": self.expose_as_skill,
            "expose_as_mcp": self.expose_as_mcp,
            "expose_as_api": self.expose_as_api,
            "source_registry": self.source_registry,
            "enabled": self.enabled,
            "version": self.version,
        }

    def to_mcp_schema(self) -> Dict[str, Any]:
        """Return MCP-format tool schema for this tool."""
        return {
            "name": self.handler_key,
            "description": self.description[:1024],
            "inputSchema": self.input_schema or {"type": "object", "properties": {}},
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Import adapters — convert each registry's native format to ToolDefinition
# ═══════════════════════════════════════════════════════════════════════════════

def _import_tool_registry() -> List[ToolDefinition]:
    """Import entries from chat_app.tool_registry (15 built-in tools)."""
    defs: List[ToolDefinition] = []
    try:
        from chat_app.tool_registry import get_tool_registry
        reg = get_tool_registry()
        for tool in reg._tools.values():
            params_schema: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}
            for p in tool.parameters:
                params_schema["properties"][p.name] = {
                    "type": p.param_type if p.param_type != "bool" else "boolean",
                    "description": p.description,
                }
                if p.default is not None:
                    params_schema["properties"][p.name]["default"] = p.default
                if p.required:
                    params_schema["required"].append(p.name)

            td = ToolDefinition(
                id=f"tool:{tool.name}",
                name=tool.name,
                description=tool.description,
                category=tool.category.value if hasattr(tool.category, "value") else str(tool.category),
                handler_key=tool.name,
                input_schema=params_schema,
                timeout_seconds=tool.timeout_seconds,
                intents=list(tool.intents),
                tags=[tool.category.value] if hasattr(tool.category, "value") else [],
                expose_as_skill=False,
                expose_as_mcp=False,
                expose_as_api=False,
                source_registry="tool_registry",
            )
            defs.append(td)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[UNIFIED] Failed to import tool_registry: %s", exc)
    return defs


def _import_skill_catalog() -> List[ToolDefinition]:
    """Import entries from chat_app.skill_catalog (122 skills)."""
    defs: List[ToolDefinition] = []
    try:
        from chat_app.skill_catalog import get_skill_catalog, ApprovalGate
        catalog = get_skill_catalog()
        for skill in catalog._skills.values():
            needs_approval = skill.approval in (ApprovalGate.CONFIRM, ApprovalGate.REVIEW)
            td = ToolDefinition(
                id=f"skill:{skill.name}",
                name=skill.name,
                description=skill.description,
                category=skill.family.value if hasattr(skill.family, "value") else str(skill.family),
                handler_key=skill.handler_key or skill.name,
                min_role=skill.min_role,
                requires_approval=needs_approval,
                approval_type=skill.approval.value if needs_approval else "",
                intents=list(skill.intents),
                tags=list(skill.tags),
                expose_as_skill=True,
                expose_as_mcp=False,
                expose_as_api=False,
                enabled=skill.enabled,
                source_registry="skill_catalog",
            )
            defs.append(td)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[UNIFIED] Failed to import skill_catalog: %s", exc)
    return defs


def _import_skills_manager() -> List[ToolDefinition]:
    """Import entries from chat_app.skills_manager (manifest.json packages)."""
    defs: List[ToolDefinition] = []
    try:
        from chat_app.skills_manager import get_skills_manager
        mgr = get_skills_manager()
        for name, pkg in mgr._skills.items():
            status_val = getattr(pkg, "status", "active")
            if hasattr(status_val, "value"):
                status_val = status_val.value
            cat_val = getattr(pkg, "category", "custom")
            if hasattr(cat_val, "value"):
                cat_val = cat_val.value
            td = ToolDefinition(
                id=f"package:{name}",
                name=name,
                description=getattr(pkg, "description", "") or f"Skill package: {name}",
                category=str(cat_val),
                handler_key=name,
                min_role=getattr(pkg, "min_role", "USER"),
                tags=getattr(pkg, "tags", []) or [],
                expose_as_skill=True,
                expose_as_mcp=False,
                expose_as_api=False,
                enabled=status_val == "active",
                source_registry="skills_manager",
            )
            defs.append(td)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[UNIFIED] Failed to import skills_manager: %s", exc)
    return defs


def _import_mcp_tools() -> List[ToolDefinition]:
    """Import entries from chat_app.mcp_server_mode (10 MCP tools)."""
    defs: List[ToolDefinition] = []
    try:
        from chat_app.mcp_server_mode import MCP_TOOLS
        for mcp_tool in MCP_TOOLS:
            tool_name = mcp_tool["name"]
            schema = mcp_tool.get("inputSchema", {})
            has_dry_run = "dry_run" in schema.get("properties", {})

            td = ToolDefinition(
                id=f"mcp:{tool_name}",
                name=tool_name,
                description=mcp_tool.get("description", ""),
                category="mcp",
                handler_key=tool_name,
                min_role=mcp_tool.get("min_role", "USER"),
                input_schema=schema,
                supports_dry_run=has_dry_run,
                tags=["mcp"],
                expose_as_skill=False,
                expose_as_mcp=True,
                expose_as_api=False,
                source_registry="mcp_server",
            )
            defs.append(td)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[UNIFIED] Failed to import mcp_server_mode: %s", exc)
    return defs


# ═══════════════════════════════════════════════════════════════════════════════
# 3. UnifiedToolRegistry
# ═══════════════════════════════════════════════════════════════════════════════

class UnifiedToolRegistry:
    """Read-only unified view over all tool/skill/MCP registries.

    Does NOT replace any existing registry — they continue to own execution.
    This provides discovery, search, deduplication and capability reporting.
    """

    def __init__(self) -> None:
        self._tools: Dict[str, ToolDefinition] = {}
        self._intent_index: Dict[str, List[str]] = {}   # intent -> list of tool ids
        self._category_index: Dict[str, List[str]] = {}  # category -> list of tool ids
        self._loaded_at: Optional[str] = None
        self._dedup_log: List[str] = []

    # -------------------------------------------------------------------
    # Loading
    # -------------------------------------------------------------------

    def load(self) -> None:
        """Import all registries, deduplicate, and build indexes."""
        self._tools.clear()
        self._intent_index.clear()
        self._category_index.clear()
        self._dedup_log.clear()

        all_defs: List[ToolDefinition] = []
        all_defs.extend(_import_tool_registry())
        all_defs.extend(_import_skill_catalog())
        all_defs.extend(_import_skills_manager())
        all_defs.extend(_import_mcp_tools())

        # Deduplicate: if the same handler_key appears in multiple registries,
        # merge exposure flags into a single entry (prefer the richer definition).
        by_handler: Dict[str, List[ToolDefinition]] = {}
        for td in all_defs:
            key = td.handler_key or td.name
            by_handler.setdefault(key, []).append(td)

        for key, group in by_handler.items():
            if len(group) == 1:
                self._register(group[0])
            else:
                merged = self._merge_duplicates(group)
                self._register(merged)

        self._loaded_at = datetime.now(timezone.utc).isoformat()
        logger.info(
            "[UNIFIED] Loaded %d tools (%d deduplicated) from 4 registries",
            len(self._tools),
            len(self._dedup_log),
        )

    def _merge_duplicates(self, group: List[ToolDefinition]) -> ToolDefinition:
        """Merge multiple definitions of the same handler into one."""
        # Pick the definition with the longest description as the base
        base = max(group, key=lambda t: len(t.description))
        sources = [t.source_registry for t in group]
        self._dedup_log.append(f"{base.handler_key} merged from: {', '.join(sources)}")

        # Merge exposure flags
        for td in group:
            if td.expose_as_skill:
                base.expose_as_skill = True
            if td.expose_as_mcp:
                base.expose_as_mcp = True
            if td.expose_as_api:
                base.expose_as_api = True

        # Merge tags
        all_tags: Set[str] = set()
        for td in group:
            all_tags.update(td.tags)
        base.tags = sorted(all_tags)

        # Merge intents
        all_intents: Set[str] = set()
        for td in group:
            all_intents.update(td.intents)
        base.intents = sorted(all_intents)

        # Use the strictest role
        base.min_role = max(
            (td.min_role for td in group),
            key=lambda r: _ROLE_LEVELS.get(r, 0),
        )

        # Combine source registries
        base.source_registry = "+".join(sorted(set(sources)))
        # Use the merged ID format
        base.id = f"merged:{base.handler_key}"
        return base

    def _register(self, td: ToolDefinition) -> None:
        """Add a tool to all indexes."""
        self._tools[td.id] = td
        for intent in td.intents:
            self._intent_index.setdefault(intent, []).append(td.id)
        self._category_index.setdefault(td.category, []).append(td.id)

    # -------------------------------------------------------------------
    # Core queries
    # -------------------------------------------------------------------

    def get(self, tool_id: str) -> Optional[ToolDefinition]:
        """Get a tool by its unified ID."""
        return self._tools.get(tool_id)

    def get_by_handler(self, handler_key: str) -> Optional[ToolDefinition]:
        """Find a tool by handler_key (first match)."""
        for td in self._tools.values():
            if td.handler_key == handler_key:
                return td
        return None

    def get_all(self) -> List[ToolDefinition]:
        """Return all registered tools."""
        return list(self._tools.values())

    def search(self, query: str) -> List[ToolDefinition]:
        """Full-text search across name, description, tags, and intents."""
        q = query.lower()
        words = [w for w in q.split() if len(w) > 1]
        results: List[ToolDefinition] = []
        for td in self._tools.values():
            haystack = f"{td.name} {td.description} {' '.join(td.tags)} {' '.join(td.intents)}".lower()
            if q in haystack or any(w in haystack for w in words):
                results.append(td)
        return results

    def get_for_intent(self, intent: str) -> List[ToolDefinition]:
        """Get all tools that handle a given intent."""
        ids = self._intent_index.get(intent, [])
        return [self._tools[tid] for tid in ids if tid in self._tools]

    def get_by_category(self, category: str) -> List[ToolDefinition]:
        """Get all tools in a category."""
        ids = self._category_index.get(category, [])
        return [self._tools[tid] for tid in ids if tid in self._tools]

    # -------------------------------------------------------------------
    # Filtered views — exposure type
    # -------------------------------------------------------------------

    def get_mcp_tools(self) -> List[ToolDefinition]:
        """Tools exposed via Model Context Protocol."""
        return [t for t in self._tools.values() if t.expose_as_mcp]

    def get_api_services(self) -> List[ToolDefinition]:
        """Tools exposed as REST API endpoints."""
        return [t for t in self._tools.values() if t.expose_as_api]

    def get_skills(self) -> List[ToolDefinition]:
        """Tools exposed as agent skills."""
        return [t for t in self._tools.values() if t.expose_as_skill]

    def get_enabled(self) -> List[ToolDefinition]:
        """All enabled tools regardless of exposure."""
        return [t for t in self._tools.values() if t.enabled]

    # -------------------------------------------------------------------
    # Filtered views — access control
    # -------------------------------------------------------------------

    def get_for_role(self, role: str) -> List[ToolDefinition]:
        """Get all tools accessible to a given role."""
        level = _ROLE_LEVELS.get(role.upper(), 0)
        return [
            t for t in self._tools.values()
            if _ROLE_LEVELS.get(t.min_role, 0) <= level and t.enabled
        ]

    # -------------------------------------------------------------------
    # Schema generation
    # -------------------------------------------------------------------

    def to_mcp_schema(self) -> List[Dict[str, Any]]:
        """Generate MCP-format tool list for external MCP clients."""
        results: List[Dict[str, Any]] = []
        for td in self.get_mcp_tools():
            results.append({
                "name": td.handler_key,
                "description": td.description[:1024],
                "inputSchema": td.input_schema or {"type": "object", "properties": {}},
            })
        return results

    def to_openapi_paths(self) -> Dict[str, Any]:
        """Generate a minimal OpenAPI paths fragment for API-exposed tools."""
        paths: Dict[str, Any] = {}
        for td in self.get_api_services():
            path = f"/api/tools/{td.handler_key}"
            paths[path] = {
                "post": {
                    "summary": td.name,
                    "description": td.description[:1024],
                    "requestBody": {
                        "content": {
                            "application/json": {"schema": td.input_schema}
                        }
                    } if td.input_schema else {},
                    "responses": {"200": {"description": "Success"}},
                    "tags": [td.category],
                }
            }
        return paths

    # -------------------------------------------------------------------
    # Capability reporting
    # -------------------------------------------------------------------

    def _check_tool_availability(self, tool: ToolDefinition) -> Dict[str, Any]:
        """Check if a tool can actually execute right now.

        Returns a dict with 'status' ('available', 'unavailable', 'degraded')
        and 'reason' explaining why.
        """
        # Check 1: Is the tool enabled?
        if not tool.enabled:
            return {"status": "unavailable", "reason": "Disabled by admin"}

        # Check 2: Are required services running?
        try:
            from chat_app.settings import get_settings
            _settings = get_settings()

            if "splunk" in tool.tags or "splunk" in tool.category:
                if not _settings.splunk.is_configured:
                    return {"status": "unavailable", "reason": "Splunk not configured (set SPLUNK_HOST)"}

            if "cribl" in tool.tags or "cribl" in tool.category:
                if not _settings.cribl.is_configured:
                    return {"status": "unavailable", "reason": "Cribl not configured (set CRIBL_BASE_URL)"}
        except Exception as _exc:  # broad catch — resilience against all failures
            pass  # Settings unavailable -- skip service checks

        # Check 3: Does the handler exist in the source registry?
        if tool.source_registry == "tool_registry":
            try:
                from chat_app.tool_registry import get_tool_registry
                t = get_tool_registry().get_tool(tool.handler_key)
                if t is None:
                    return {"status": "unavailable", "reason": "Handler not found in tool_registry"}
                if t.execute_fn is None:
                    return {"status": "degraded", "reason": "No execution function attached"}
            except Exception as _exc:  # broad catch — resilience against all failures
                return {"status": "degraded", "reason": "tool_registry import failed"}

        # Check 4: Approval-gated tools are degraded (usable but require extra step)
        if tool.requires_approval:
            return {"status": "degraded", "reason": f"Requires {tool.approval_type or 'approval'} before execution"}

        return {"status": "available", "reason": ""}

    def get_capability_status(self, tool_id: str) -> Dict[str, Any]:
        """Explain why a tool is available or unavailable."""
        td = self._tools.get(tool_id) or self.get_by_handler(tool_id)
        if td is None:
            return {"tool_id": tool_id, "found": False, "reason": "Tool not found in any registry"}

        availability = self._check_tool_availability(td)
        issues: List[str] = []
        if availability["reason"]:
            issues.append(availability["reason"])

        reachable = availability["status"] != "unavailable"

        return {
            "tool_id": tool_id,
            "found": True,
            "enabled": td.enabled,
            "reachable": reachable,
            "status": availability["status"],
            "min_role": td.min_role,
            "source_registry": td.source_registry,
            "issues": issues,
            "available": availability["status"] == "available",
        }

    def get_capability_report(self) -> Dict[str, Any]:
        """Full capability report with availability, counts by source, category, exposure, role."""
        by_source: Dict[str, int] = {}
        by_category: Dict[str, int] = {}
        by_exposure: Dict[str, int] = {"skill": 0, "mcp": 0, "api": 0}
        by_role: Dict[str, int] = {"VIEWER": 0, "USER": 0, "ANALYST": 0, "ADMIN": 0}
        enabled_count = 0
        approval_count = 0

        available_tools: List[Dict[str, Any]] = []
        unavailable_tools: List[Dict[str, Any]] = []
        degraded_tools: List[Dict[str, Any]] = []

        for td in self._tools.values():
            # Source
            for src in td.source_registry.split("+"):
                by_source[src] = by_source.get(src, 0) + 1
            # Category
            by_category[td.category] = by_category.get(td.category, 0) + 1
            # Exposure
            if td.expose_as_skill:
                by_exposure["skill"] += 1
            if td.expose_as_mcp:
                by_exposure["mcp"] += 1
            if td.expose_as_api:
                by_exposure["api"] += 1
            # Role
            by_role[td.min_role] = by_role.get(td.min_role, 0) + 1
            if td.enabled:
                enabled_count += 1
            if td.requires_approval:
                approval_count += 1

            # Availability check
            availability = self._check_tool_availability(td)
            entry = {"id": td.id, "name": td.name, "reason": availability["reason"]}
            if availability["status"] == "available":
                available_tools.append(entry)
            elif availability["status"] == "unavailable":
                unavailable_tools.append(entry)
            else:
                degraded_tools.append(entry)

        return {
            "total_tools": len(self._tools),
            "enabled": enabled_count,
            "disabled": len(self._tools) - enabled_count,
            "requires_approval": approval_count,
            "available_count": len(available_tools),
            "unavailable_count": len(unavailable_tools),
            "degraded_count": len(degraded_tools),
            "available": available_tools,
            "unavailable": unavailable_tools,
            "degraded": degraded_tools,
            "by_source_registry": by_source,
            "by_category": dict(sorted(by_category.items())),
            "by_exposure": by_exposure,
            "by_min_role": by_role,
            "deduplicated": self._dedup_log,
            "loaded_at": self._loaded_at,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_mcp_capabilities(self) -> Dict[str, Any]:
        """Return capabilities for MCP discovery protocol.

        Lists all MCP-exposed tools with their schemas, plus any tools that
        are configured for MCP but currently unavailable (with reasons).
        """
        tools = self.get_mcp_tools()
        available_mcp: List[Dict[str, Any]] = []
        unavailable_mcp: List[Dict[str, Any]] = []

        for td in self._tools.values():
            if not td.expose_as_mcp:
                continue
            availability = self._check_tool_availability(td)
            if availability["status"] == "available":
                available_mcp.append(td.to_mcp_schema())
            else:
                unavailable_mcp.append({
                    "name": td.name,
                    "reason": availability["reason"],
                    "status": availability["status"],
                })

        return {
            "tools": available_mcp,
            "unavailable": unavailable_mcp,
            "total_mcp_tools": len(tools),
            "available_count": len(available_mcp),
            "unavailable_count": len(unavailable_mcp),
        }

    # -------------------------------------------------------------------
    # Intent coverage analysis
    # -------------------------------------------------------------------

    def get_intent_coverage(self) -> Dict[str, Any]:
        """Show which intents have tools and which do not."""
        covered: Dict[str, int] = {}
        for intent, ids in self._intent_index.items():
            covered[intent] = len(ids)

        # Try to detect uncovered intents from the Intent enum
        all_intents: List[str] = []
        try:
            from chat_app.registry import Intent
            all_intents = [i.value for i in Intent]
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass

        uncovered = [i for i in all_intents if i not in covered]
        return {
            "covered_intents": dict(sorted(covered.items())),
            "uncovered_intents": sorted(uncovered),
            "total_covered": len(covered),
            "total_uncovered": len(uncovered),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Singleton
# ═══════════════════════════════════════════════════════════════════════════════

_registry: Optional[UnifiedToolRegistry] = None


def get_unified_registry() -> UnifiedToolRegistry:
    """Get or create the singleton UnifiedToolRegistry."""
    global _registry
    if _registry is None:
        _registry = UnifiedToolRegistry()
        _registry.load()
    return _registry


def reload_unified_registry() -> UnifiedToolRegistry:
    """Force a full reload of the unified registry."""
    global _registry
    _registry = UnifiedToolRegistry()
    _registry.load()
    return _registry
