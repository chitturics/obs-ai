"""Code Intelligence — dependency graph, function map, duplication detection.

Builds a complete map of the codebase:
- **Module dependency graph**: who imports whom
- **Function registry**: every public function with signature, location, callers
- **Duplication detector**: finds duplicate function names across modules
- **Layer map**: which architectural layer each module belongs to
- **Health metrics**: coupling, cohesion, dependency depth

Usage:
    from chat_app.code_intelligence import get_code_intel

    intel = get_code_intel()
    graph = intel.get_dependency_graph()
    dupes = intel.find_duplicates()
    layers = intel.get_layer_map()
    health = intel.get_health_metrics()
"""

import ast
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_CHAT_APP_DIR = Path(__file__).parent


# ---------------------------------------------------------------------------
# Architectural layers
# ---------------------------------------------------------------------------

_LAYER_MAP: Dict[str, str] = {
    # Core Pipeline
    "message_handler": "pipeline", "intent_classifier": "pipeline", "response_generator": "pipeline",
    "context_builder": "pipeline", "prompts": "pipeline", "query_router": "pipeline",
    "query_router_handler": "pipeline", "confidence_scorer": "pipeline",
    # Retrieval
    "vectorstore_search": "retrieval", "reranker": "retrieval", "self_adaptive_rag": "retrieval",
    "knowledge_graph": "retrieval", "context_compressor": "retrieval",
    # Execution
    "skill_executor": "execution", "skill_catalog": "execution", "agent_catalog": "execution",
    "agent_dispatcher": "execution", "workflow_orchestrator": "execution",
    "orchestration_strategies": "execution", "tool_registry": "execution",
    # Enterprise Security
    "audit_log": "security", "rbac": "security", "mfa": "security", "policy_engine": "security",
    "safety_policies": "security", "approval_workflows": "security", "secrets_manager": "security",
    "auth_dependencies": "security", "auth_providers": "security", "scim": "security",
    "data_governance": "security", "credential_scoping": "security", "guardrails": "security",
    # Observability
    "execution_tracker": "observability", "slo_tracker": "observability",
    "circuit_breaker": "observability", "latency_budgets": "observability",
    "cost_tracker": "observability", "health_monitor": "observability",
    "activity_timeline": "observability", "otel_tracing": "observability",
    "prometheus_metrics": "observability", "runbooks": "observability",
    # Configuration
    "settings": "config", "config_manager": "config", "registry": "config",
    "sidebar_config": "config", "user_persona": "config",
    # Admin API
    "admin_api": "admin", "admin_shared": "admin",
    "admin_config_routes": "admin", "admin_settings_routes": "admin",
    "admin_tools_routes": "admin", "admin_users_routes": "admin",
    "admin_security_routes": "admin", "admin_collections_routes": "admin",
    "admin_learning_routes": "admin", "admin_operations_routes": "admin",
    "admin_observability_routes": "admin", "admin_skills_routes": "admin",
    "admin_containers": "admin",
    # Intelligence
    "self_learning": "intelligence", "self_evaluation": "intelligence",
    "toolformer": "intelligence", "agent_self_assessment": "intelligence",
    "agent_protocol": "intelligence", "persona_orchestration": "intelligence",
    "evolution_engine": "intelligence", "gci_agent": "intelligence",
    # Infrastructure
    "splunk_client": "infrastructure", "cribl_client": "infrastructure",
    "mcp_server_mode": "infrastructure", "mcp_handler": "infrastructure",
    "idle_worker": "infrastructure", "resource_manager": "infrastructure",
    "document_ingestor": "infrastructure", "tenant_isolation": "infrastructure",
    "tenant_quotas": "infrastructure",
    # Utilities
    "doc_generator": "utility", "idempotency": "utility", "error_taxonomy": "utility",
    "workflow_engine": "utility", "project_dictionary": "utility",
    "pipeline_models": "utility", "code_intelligence": "utility",
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class ModuleInfo:
    """Information about a single Python module."""
    name: str
    path: str
    lines: int = 0
    layer: str = "unknown"
    imports_from: List[str] = field(default_factory=list)  # Modules this imports
    imported_by: List[str] = field(default_factory=list)   # Modules that import this
    functions: List[str] = field(default_factory=list)
    classes: List[str] = field(default_factory=list)
    docstring: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "path": self.path, "lines": self.lines,
            "layer": self.layer,
            "imports_from": self.imports_from, "imported_by": self.imported_by,
            "functions": self.functions[:20], "classes": self.classes,
            "docstring": self.docstring[:200],
            "fan_in": len(self.imported_by), "fan_out": len(self.imports_from),
        }


@dataclass
class DuplicateFunction:
    """A function name that exists in multiple modules."""
    name: str
    locations: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "locations": self.locations, "count": len(self.locations)}


# ---------------------------------------------------------------------------
# Code Intelligence Engine
# ---------------------------------------------------------------------------

class CodeIntelligence:
    """Analyzes the codebase structure, dependencies, and health."""

    def __init__(self):
        self._modules: Dict[str, ModuleInfo] = {}
        self._built = False

    def _build(self) -> None:
        """Scan all modules and build the dependency graph."""
        if self._built:
            return
        self._built = True

        for py_file in sorted(_CHAT_APP_DIR.glob("*.py")):
            if py_file.name.startswith("__"):
                continue
            name = py_file.stem
            try:
                content = py_file.read_text(encoding="utf-8", errors="ignore")
                lines = content.split("\n")
                mod = ModuleInfo(
                    name=name,
                    path=f"chat_app/{py_file.name}",
                    lines=len(lines),
                    layer=_LAYER_MAP.get(name, "other"),
                )

                # Parse AST for functions, classes, docstring
                try:
                    tree = ast.parse(content)
                    mod.docstring = (ast.get_docstring(tree) or "")[:200]
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            if not node.name.startswith("_") or node.name.startswith("__"):
                                continue
                            mod.functions.append(node.name)
                        elif isinstance(node, ast.ClassDef):
                            mod.classes.append(node.name)
                except SyntaxError as _exc:
                    logger.debug("AST parse failed for module analysis: %s", _exc)

                # Also get public functions
                for match in re.finditer(r'^(?:async\s+)?def\s+(\w+)', content, re.MULTILINE):
                    fn = match.group(1)
                    if not fn.startswith("_") and fn not in mod.functions:
                        mod.functions.append(fn)

                # Extract imports
                for match in re.finditer(r'from\s+chat_app\.(\w+)\s+import|from\s+chat_app\s+import\s+(\w+)', content):
                    imported = match.group(1) or match.group(2)
                    if imported and imported != name:
                        mod.imports_from.append(imported)
                # Also check: import chat_app.X
                for match in re.finditer(r'import\s+chat_app\.(\w+)', content):
                    imported = match.group(1)
                    if imported and imported != name:
                        mod.imports_from.append(imported)

                mod.imports_from = sorted(set(mod.imports_from))
                self._modules[name] = mod

            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.debug("[CODE_INTEL] Failed to parse %s: %s", py_file, exc)

        # Build reverse dependency (imported_by)
        for name, mod in self._modules.items():
            for dep in mod.imports_from:
                if dep in self._modules:
                    self._modules[dep].imported_by.append(name)
        for mod in self._modules.values():
            mod.imported_by = sorted(set(mod.imported_by))

    # ----- Public API -----

    def get_dependency_graph(self) -> Dict[str, Any]:
        """Get the full module dependency graph."""
        self._build()
        nodes = []
        edges = []
        for name, mod in self._modules.items():
            nodes.append({
                "id": name, "layer": mod.layer, "lines": mod.lines,
                "fan_in": len(mod.imported_by), "fan_out": len(mod.imports_from),
            })
            for dep in mod.imports_from:
                edges.append({"from": name, "to": dep})
        return {
            "nodes": nodes, "edges": edges,
            "node_count": len(nodes), "edge_count": len(edges),
            "layers": self._get_layer_summary(),
        }

    def get_module(self, name: str) -> Optional[Dict[str, Any]]:
        """Get detailed info about a single module."""
        self._build()
        mod = self._modules.get(name)
        return mod.to_dict() if mod else None

    def get_all_modules(self) -> List[Dict[str, Any]]:
        """Get info for all modules."""
        self._build()
        return [m.to_dict() for m in sorted(self._modules.values(), key=lambda m: m.name)]

    def find_duplicates(self) -> List[Dict[str, Any]]:
        """Find function names that exist in multiple modules."""
        self._build()
        func_locations: Dict[str, List[str]] = defaultdict(list)
        for name, mod in self._modules.items():
            for fn in mod.functions:
                func_locations[fn].append(name)
        dupes = [
            DuplicateFunction(name=fn, locations=locs).to_dict()
            for fn, locs in sorted(func_locations.items())
            if len(locs) > 1
        ]
        return dupes

    def get_layer_map(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get modules organized by architectural layer."""
        self._build()
        layers: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for mod in self._modules.values():
            layers[mod.layer].append({
                "name": mod.name, "lines": mod.lines,
                "fan_in": len(mod.imported_by), "fan_out": len(mod.imports_from),
            })
        for layer in layers.values():
            layer.sort(key=lambda m: m["name"])
        return dict(layers)

    def get_health_metrics(self) -> Dict[str, Any]:
        """Get codebase health metrics — coupling, size, structure."""
        self._build()
        total_lines = sum(m.lines for m in self._modules.values())
        total_edges = sum(len(m.imports_from) for m in self._modules.values())
        avg_fan_out = total_edges / max(len(self._modules), 1)
        god_files = [m.name for m in self._modules.values() if m.lines > 2000]
        orphans = [m.name for m in self._modules.values() if not m.imported_by and not m.imports_from]
        high_coupling = [
            {"name": m.name, "fan_in": len(m.imported_by), "fan_out": len(m.imports_from)}
            for m in self._modules.values()
            if len(m.imported_by) + len(m.imports_from) > 15
        ]

        return {
            "total_modules": len(self._modules),
            "total_lines": total_lines,
            "avg_lines_per_module": round(total_lines / max(len(self._modules), 1)),
            "total_dependencies": total_edges,
            "avg_fan_out": round(avg_fan_out, 1),
            "god_files": god_files,
            "orphan_modules": orphans,
            "high_coupling_modules": sorted(high_coupling, key=lambda x: -(x["fan_in"] + x["fan_out"])),
            "layers": self._get_layer_summary(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_cross_layer_dependencies(self) -> List[Dict[str, Any]]:
        """Find dependencies that cross architectural layers (potential violations)."""
        self._build()
        violations = []
        for mod in self._modules.values():
            for dep_name in mod.imports_from:
                dep = self._modules.get(dep_name)
                if dep and dep.layer != mod.layer:
                    violations.append({
                        "from_module": mod.name, "from_layer": mod.layer,
                        "to_module": dep.name, "to_layer": dep.layer,
                    })
        return violations

    def _get_layer_summary(self) -> Dict[str, int]:
        """Count modules per layer."""
        counts: Dict[str, int] = defaultdict(int)
        for mod in self._modules.values():
            counts[mod.layer] += 1
        return dict(sorted(counts.items()))


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[CodeIntelligence] = None


def get_code_intel() -> CodeIntelligence:
    global _instance
    if _instance is None:
        _instance = CodeIntelligence()
    return _instance
