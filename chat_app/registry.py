"""
Unified registry for ObsAI application.

Single source of truth for:
- Intent enum (22 classifier + 5 phantom = 27 total)
- RoutingTag enum (~45 extended routing tags)
- Slash-command metadata (introspected from _COMMAND_TABLE)
- Admin sidebar section definitions (36 sections, 6 groups)
- Cross-catalog validation (skill refs, intent strings, strategy overrides)

All imports of external modules (skill_catalog, agent_catalog, slash_commands,
settings) are LAZY -- performed inside functions -- to avoid circular imports.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, FrozenSet, List, Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════════
# 1. Intent Enum
# ═══════════════════════════════════════════════════════════════════════════════

class Intent(str, Enum):
    """All known intent values.

    The first 22 are *classifier intents* -- values produced by
    ``IntentClassifier.classify()`` via ``plan.intent = "..."``.

    The last 5 are *phantom intents* -- referenced in config strategy_overrides
    or handler checks but never produced by the classifier.
    """

    # -- Classifier intents (22) -------------------------------------------
    ANSIBLE = "ansible"
    CLARIFICATION = "clarification"
    COMPARE_COMMANDS = "compare_commands"
    CONFIG_HEALTH_CHECK = "config_health_check"
    CONFIG_LOOKUP = "config_lookup"
    CREATE_ALERT = "create_alert"
    CRIBL_CONFIG = "cribl_config"
    CRIBL_PIPELINE = "cribl_pipeline"
    DATA_TRANSFORM = "data_transform"
    GENERAL_QA = "general_qa"
    INGESTION = "ingestion"
    META_QUESTION = "meta_question"
    OBSERVABILITY_INFRA = "observability_infra"
    OBSERVABILITY_METRICS = "observability_metrics"
    PYTHON_SCRIPT = "python_script"
    REPO_QUERY = "repo_query"
    RUN_SEARCH = "run_search"
    SAVED_SEARCH_ANALYSIS = "saved_search_analysis"
    SEARCH_SUGGESTION = "search_suggestion"
    SHELL_SCRIPT = "shell_script"
    SPL_GENERATION = "spl_generation"
    TROUBLESHOOTING = "troubleshooting"

    # -- Phantom intents (5) -----------------------------------------------
    SPL_OPTIMIZATION = "spl_optimization"
    SPL_EXPLANATION = "spl_explanation"
    SPL_VALIDATION = "spl_validation"
    GREETING = "greeting"
    COMMAND_HELP = "command_help"


# ═══════════════════════════════════════════════════════════════════════════════
# 2. RoutingTag Enum
# ═══════════════════════════════════════════════════════════════════════════════

class RoutingTag(str, Enum):
    """Extended routing tags used in skill.intents / agent.intents lists.

    These are NOT produced by the classifier; they exist only in the catalog
    metadata for skill/agent matching.
    """

    ALERTING = "alerting"
    ANALYSIS = "analysis"
    APPROVAL = "approval"
    ARCHITECTURE = "architecture"
    AUTOMATION = "automation"
    COMPLEX_TASK = "complex_task"
    COMPLIANCE = "compliance"
    CRITICAL = "critical"
    DEPLOYMENT = "deployment"
    DEVELOPMENT = "development"
    DOCUMENTATION = "documentation"
    ESCALATION = "escalation"
    EXPORT = "export"
    EXTRACTION = "extraction"
    HEALTH = "health"
    IMPROVEMENT = "improvement"
    INFRASTRUCTURE = "infrastructure"
    INGEST = "ingest"
    INITIALIZATION = "initialization"
    INVESTIGATION = "investigation"
    KNOWLEDGE = "knowledge"
    LEARN = "learn"
    LEARNING = "learning"
    LOOKUP = "lookup"
    MAINTENANCE = "maintenance"
    MONITORING = "monitoring"
    NLP_TO_SPL = "nlp_to_spl"
    ONBOARDING = "onboarding"
    OPERATIONS = "operations"
    OPTIMIZATION = "optimization"
    ORGANIZATION = "organization"
    PARSING = "parsing"
    PIPELINE = "pipeline"
    PLANNING = "planning"
    QUALITY = "quality"
    RECOVERY = "recovery"
    REPORTING = "reporting"
    RESPONSE = "response"
    RETRIEVAL = "retrieval"
    ROUTING = "routing"
    SCRIPTING = "scripting"
    SEARCH = "search"
    SECURITY = "security"
    TEACHING = "teaching"
    TRANSFORMATION = "transformation"
    TWO_STAGE = "two_stage"
    UPLOAD = "upload"

    # OpenMAIC-inspired tags
    ACTION_PLAN = "action_plan"
    DIRECTOR = "director"
    FEEDBACK = "feedback"
    MULTI_TURN = "multi_turn"

    # Governance & pipeline tags
    SUPERVISOR = "supervisor"
    DIRECTOR_GRAPH = "director_graph"
    EVOLUTION = "evolution"
    GCI = "gci"
    PRIORITY = "priority"
    JOURNAL = "journal"
    LINEAGE = "lineage"


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Helper
# ═══════════════════════════════════════════════════════════════════════════════

# Pre-compute lookup sets for fast membership testing.
_INTENT_VALUES: FrozenSet[str] = frozenset(i.value for i in Intent)
_TAG_VALUES: FrozenSet[str] = frozenset(t.value for t in RoutingTag)


def is_valid_intent_or_tag(value: str) -> bool:
    """Check if a string is a known Intent or RoutingTag."""
    return value in _INTENT_VALUES or value in _TAG_VALUES


# ═══════════════════════════════════════════════════════════════════════════════
# 4. CLASSIFIER_INTENTS frozenset
# ═══════════════════════════════════════════════════════════════════════════════

CLASSIFIER_INTENTS: FrozenSet[Intent] = frozenset([
    Intent.ANSIBLE,
    Intent.CLARIFICATION,
    Intent.COMPARE_COMMANDS,
    Intent.CONFIG_HEALTH_CHECK,
    Intent.CONFIG_LOOKUP,
    Intent.CREATE_ALERT,
    Intent.CRIBL_CONFIG,
    Intent.CRIBL_PIPELINE,
    Intent.DATA_TRANSFORM,
    Intent.GENERAL_QA,
    Intent.INGESTION,
    Intent.META_QUESTION,
    Intent.OBSERVABILITY_INFRA,
    Intent.OBSERVABILITY_METRICS,
    Intent.PYTHON_SCRIPT,
    Intent.REPO_QUERY,
    Intent.RUN_SEARCH,
    Intent.SAVED_SEARCH_ANALYSIS,
    Intent.SEARCH_SUGGESTION,
    Intent.SHELL_SCRIPT,
    Intent.SPL_GENERATION,
    Intent.TROUBLESHOOTING,
])


# ═══════════════════════════════════════════════════════════════════════════════
# 5. CommandInfo and command registry
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class CommandInfo:
    """Metadata for a single slash command."""
    name: str
    description: str
    category: str
    needs_args: bool = False
    aliases: List[str] = field(default_factory=list)


# Canonical description for every primary command.  This is the ONLY place
# command descriptions are defined.
_DESCRIPTIONS: Dict[str, str] = {
    "/help": "Show categorized help with all available commands",
    "/search": "Search the knowledge base (specs, docs, configs)",
    "/spec": "Look up .conf.spec reference files",
    "/config": "Show or update session configuration",
    "/stats": "Show usage statistics and cache metrics",
    "/clear": "Clear chat conversation history",
    "/profile": "Show current chat profile name and settings",
    "/analyze_searches": "Analyze saved searches for optimization opportunities",
    "/check_configs": "Validate .conf files in the org repository",
    "/run": "Execute a Splunk search and display results",
    "/create_alert": "Step-by-step alert creation wizard",
    "/mcp": "MCP gateway management commands",
    "/build_config": "Interactive .conf stanza builder (inputs/props/transforms)",
    "/health": "Comprehensive health checks with learning stats",
    "/splunk": "Splunk admin commands (search jobs, config, indexes)",
    "/explain": "Explain SPL query syntax and behavior",
    "/learn": "Trigger self-learning cycles, export training data",
    "/ingest": "Ingest documents/PDFs/URLs into vector store",
    "/tutorial": "Interactive tutorials (basics, spl, config, ingestion, admin)",
    "/version": "Display system version and build info",
    "/admin": "Admin console links and configuration guide",
    "/skill": "Explore skills, agents, and orchestration catalog",
    "/kg": "Knowledge graph queries and entity browser",
    "/doc": "Generate documentation from text, directory, or zip file (format=markdown|sharepoint)",
    "/upgrade": "Check Splunk app/TA/ES/ITSI/UF upgrade readiness",
}

# Category hints keyed on the handler function name (or a recognizable stem).
_CATEGORY_HINTS: Dict[str, str] = {
    "help": "communication",
    "search": "search",
    "spec": "search",
    "config": "configuration",
    "stats": "system",
    "clear": "system",
    "profile": "configuration",
    "analyze_searches": "analysis",
    "check_configs": "analysis",
    "run": "analysis",
    "create_alert": "communication",
    "mcp": "system",
    "build_config": "configuration",
    "health": "system",
    "splunk_admin": "analysis",
    "explain": "search",
    "learn": "learning",
    "ingest": "learning",
    "tutorial": "learning",
    "version": "system",
    "admin": "communication",
    "skill_cmd": "system",
    "kg_cmd": "search",
    "doc": "communication",
    "upgrade": "analysis",
}

# Module-level cache; populated once by ``get_command_registry()``.
_command_cache: Dict[str, CommandInfo] = {}


def _infer_category(handler_func: Any) -> str:
    """Derive a category from the handler function's name."""
    fname = getattr(handler_func, "__name__", "")
    # Strip common suffixes so "help_command" -> "help"
    stem = fname.replace("_command", "").replace("_cmd", "")
    return _CATEGORY_HINTS.get(stem, "general")


# Static fallback command list for environments where chainlit is not available
# (e.g., tests, CI). Must be kept in sync with slash_commands._COMMAND_TABLE.
_STATIC_COMMAND_FALLBACK: Dict[str, CommandInfo] = {
    "/help":             CommandInfo("/help", _DESCRIPTIONS.get("/help", "Show help"), "communication", True, []),
    "/search":           CommandInfo("/search", _DESCRIPTIONS.get("/search", "Search Splunk"), "search", True, []),
    "/spec":             CommandInfo("/spec", _DESCRIPTIONS.get("/spec", "Look up spec"), "search", True, []),
    "/config":           CommandInfo("/config", _DESCRIPTIONS.get("/config", "Configuration"), "configuration", True, []),
    "/stats":            CommandInfo("/stats", _DESCRIPTIONS.get("/stats", "Show stats"), "system", False, []),
    "/clear":            CommandInfo("/clear", _DESCRIPTIONS.get("/clear", "Clear conversation"), "system", False, []),
    "/profile":          CommandInfo("/profile", _DESCRIPTIONS.get("/profile", "Show profile"), "configuration", False, []),
    "/analyze_searches": CommandInfo("/analyze_searches", _DESCRIPTIONS.get("/analyze_searches", "Analyze searches"), "analysis", False, []),
    "/check_configs":    CommandInfo("/check_configs", _DESCRIPTIONS.get("/check_configs", "Check configs"), "analysis", False, []),
    "/run":              CommandInfo("/run", _DESCRIPTIONS.get("/run", "Run SPL query"), "analysis", True, []),
    "/create_alert":     CommandInfo("/create_alert", _DESCRIPTIONS.get("/create_alert", "Create alert"), "communication", False, []),
    "/mcp":              CommandInfo("/mcp", _DESCRIPTIONS.get("/mcp", "MCP tools"), "system", True, []),
    "/build-config":     CommandInfo("/build-config", _DESCRIPTIONS.get("/build-config", "Build config"), "configuration", True, ["/build_config"]),
    "/health":           CommandInfo("/health", _DESCRIPTIONS.get("/health", "Health check"), "system", False, ["/status"]),
    "/splunk":           CommandInfo("/splunk", _DESCRIPTIONS.get("/splunk", "Splunk admin"), "analysis", True, []),
    "/explain":          CommandInfo("/explain", _DESCRIPTIONS.get("/explain", "Explain SPL"), "search", True, []),
    "/learn":            CommandInfo("/learn", _DESCRIPTIONS.get("/learn", "Learn from feedback"), "learning", True, []),
    "/ingest":           CommandInfo("/ingest", _DESCRIPTIONS.get("/ingest", "Ingest documents"), "learning", True, []),
    "/tutorial":         CommandInfo("/tutorial", _DESCRIPTIONS.get("/tutorial", "Start tutorial"), "learning", True, []),
    "/version":          CommandInfo("/version", _DESCRIPTIONS.get("/version", "Show version"), "system", False, ["/ver", "/about"]),
    "/admin":            CommandInfo("/admin", _DESCRIPTIONS.get("/admin", "Admin panel"), "communication", True, []),
    "/skill":            CommandInfo("/skill", _DESCRIPTIONS.get("/skill", "Run skill"), "system", True, []),
    "/kg":               CommandInfo("/kg", _DESCRIPTIONS.get("/kg", "Knowledge graph"), "search", True, []),
    "/doc":              CommandInfo("/doc", _DESCRIPTIONS.get("/doc", "Documentation"), "communication", True, []),
    "/upgrade":          CommandInfo("/upgrade", _DESCRIPTIONS.get("/upgrade", "Check upgrade readiness"), "analysis", True, []),
}


def _build_command_metadata() -> Dict[str, CommandInfo]:
    """Introspect ``slash_commands._COMMAND_TABLE`` and build registry entries.

    Detects aliases (multiple command names pointing to the same handler
    function via ``id()``), picks the shortest name as the primary, and
    records the rest as aliases.
    """
    _COMMAND_TABLE: Dict[str, Any] = {}
    try:
        from chat_app.slash_commands import _COMMAND_TABLE as _ct1  # noqa: WPS433
        _COMMAND_TABLE = _ct1
    except ImportError:
        try:
            from slash_commands import _COMMAND_TABLE as _ct2  # noqa: WPS433
            _COMMAND_TABLE = _ct2
        except ImportError:
            logger.warning("slash_commands._COMMAND_TABLE not available; using static command fallback")
            return _STATIC_COMMAND_FALLBACK

    # Group command names by handler identity.
    handler_groups: Dict[int, List[str]] = {}
    handler_map: Dict[int, Any] = {}
    needs_args_map: Dict[int, bool] = {}

    for cmd_name, entry in _COMMAND_TABLE.items():
        handler_func = entry[0]
        needs_args = entry[1] if len(entry) > 1 else False
        hid = id(handler_func)
        handler_groups.setdefault(hid, []).append(cmd_name)
        handler_map[hid] = handler_func
        needs_args_map[hid] = needs_args

    registry: Dict[str, CommandInfo] = {}

    for hid, names in handler_groups.items():
        # Shortest name is the primary; rest are aliases.
        names_sorted = sorted(names, key=len)
        primary = names_sorted[0]
        aliases = names_sorted[1:]

        handler_func = handler_map[hid]
        description = _DESCRIPTIONS.get(primary, "")
        category = _infer_category(handler_func)

        registry[primary] = CommandInfo(
            name=primary,
            description=description,
            category=category,
            needs_args=needs_args_map[hid],
            aliases=aliases,
        )

    return registry


def get_command_registry() -> Dict[str, CommandInfo]:
    """Return the command registry, building it on first call."""
    global _command_cache  # noqa: WPS420
    if not _command_cache:
        _command_cache.update(_build_command_metadata())
    return _command_cache


def get_commands_for_api() -> List[Dict[str, Any]]:
    """Return a sorted list of command dicts suitable for the /commands-data API."""
    reg = get_command_registry()
    result = []
    for cmd_info in sorted(reg.values(), key=lambda c: c.name):
        result.append({
            "name": cmd_info.name,
            "description": cmd_info.description,
            "category": cmd_info.category,
            "needs_args": cmd_info.needs_args,
            "aliases": cmd_info.aliases,
        })
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 6. SectionInfo and section registry
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SectionInfo:
    """Metadata for a single admin sidebar section."""
    id: str
    label: str
    icon: str
    group: str
    path: str
    api_endpoint: Optional[str] = None
    external: bool = False


_SECTION_REGISTRY: List[SectionInfo] = [
    # ── Overview ──────────────────────────────────────────────────────────
    SectionInfo("dashboard", "Dashboard", "LayoutDashboard", "Overview",
                "/dashboard", "/api/admin/dashboard"),

    # ── AI & Retrieval ────────────────────────────────────────────────────
    SectionInfo("profiles", "Profiles", "UserCog", "AI & Retrieval",
                "/profiles", "/api/admin/settings"),
    SectionInfo("llm", "LLM", "Brain", "AI & Retrieval",
                "/llm", "/api/admin/llm"),
    SectionInfo("retrieval", "Retrieval", "Search", "AI & Retrieval",
                "/retrieval", "/api/admin/settings"),
    SectionInfo("prompts", "Prompts", "MessageSquare", "AI & Retrieval",
                "/prompts", "/api/admin/prompts"),
    SectionInfo("ingestion", "Ingestion", "Upload", "AI & Retrieval",
                "/ingestion", "/api/admin/uploads"),
    SectionInfo("chunking", "Chunking", "Layers", "AI & Retrieval",
                "/settings/chunking", "/api/admin/settings"),

    # ── Intelligence ──────────────────────────────────────────────────────
    SectionInfo("skills", "Skills & Agents", "Zap", "Intelligence",
                "/skills", "/api/admin/skills"),
    SectionInfo("orchestration", "Orchestration", "Workflow", "Intelligence",
                "/orchestration", "/api/admin/orchestration/strategies"),
    SectionInfo("workflow-designer", "Workflow Designer", "GitBranch", "Intelligence",
                "/workflow-designer", "/api/admin/workflows/history"),
    SectionInfo("mcp", "MCP Gateway", "Plug", "Intelligence",
                "/mcp", "/api/admin/settings"),
    SectionInfo("api-services", "API Services", "Globe", "Intelligence",
                "/api-services"),
    SectionInfo("action-engine", "Action Engine", "Cog", "Intelligence",
                "/action-engine", "/api/admin/action-engine/status"),
    SectionInfo("features", "Feature Flags", "ToggleRight", "Intelligence",
                "/features", "/api/admin/features"),
    SectionInfo("knowledge-graph", "Knowledge Graph", "Share2", "Intelligence",
                "/knowledge-graph", "/api/admin/knowledge-graph/stats"),
    SectionInfo("script-builder", "Script Builder", "Code", "Intelligence",
                "/script-builder"),
    SectionInfo("learning", "Self-Learning", "GraduationCap", "Intelligence",
                "/settings/learning", "/api/admin/learning/dashboard"),
    SectionInfo("prompt-templates", "Prompt Templates", "FileText", "Intelligence",
                "/prompt-templates", "/api/admin/prompt-templates"),
    SectionInfo("quality-monitor", "Quality Monitor", "ShieldCheck", "Intelligence",
                "/quality-monitor", "/api/admin/gci/status"),
    SectionInfo("evolution", "Evolution Engine", "Dna", "Intelligence",
                "/evolution", "/api/admin/evolution/status"),

    # ── Infrastructure ────────────────────────────────────────────────────
    SectionInfo("ssl", "Network & SSL", "Network", "Infrastructure",
                "/ssl", "/api/admin/settings"),
    SectionInfo("database", "Database", "Database", "Infrastructure",
                "/settings/database", "/api/admin/settings"),
    SectionInfo("cache", "Cache", "HardDrive", "Infrastructure",
                "/cache", "/api/admin/settings"),
    SectionInfo("security", "Security", "Shield", "Infrastructure",
                "/settings/security", "/api/admin/settings"),
    SectionInfo("users", "Users & Roles", "Users", "Infrastructure",
                "/users", "/api/admin/settings"),
    SectionInfo("paths", "Paths", "FolderTree", "Infrastructure",
                "/settings/paths", "/api/admin/settings"),
    SectionInfo("ui-settings", "UI Settings", "Palette", "Infrastructure",
                "/settings/ui", "/api/admin/settings"),

    # ── Integrations ──────────────────────────────────────────────────────
    SectionInfo("splunk", "Splunk", "Server", "Integrations",
                "/settings/splunk", "/api/admin/settings"),
    SectionInfo("github", "GitHub", "Github", "Integrations",
                "/settings/github", "/api/admin/settings"),
    SectionInfo("organization", "Organization", "Building2", "Integrations",
                "/organization", "/api/admin/settings"),

    # ── Operations ────────────────────────────────────────────────────────
    SectionInfo("containers", "Containers", "Container", "Operations",
                "/containers", "/api/admin/containers"),
    SectionInfo("observability", "Observability", "Activity", "Operations",
                "/observability", "/api/admin/observability"),
    SectionInfo("traces", "OTel Traces", "Scan", "Operations",
                "/traces", "/api/admin/otel/traces"),
    SectionInfo("langfuse", "LLM Traces", "Eye", "Operations",
                "/traces", "/api/admin/otel/traces"),
    SectionInfo("collections", "Collections", "Library", "Operations",
                "/collections", "/api/admin/collections"),
    SectionInfo("config-editor", "Config Editor", "FileCode", "Operations",
                "/config-editor", "/api/admin/settings"),
    SectionInfo("learning-center", "Learning Center", "BookOpen", "Operations",
                "/learning-center"),
    SectionInfo("interactive-tools", "Interactive Tools", "Wrench", "Operations",
                "/api/admin/commands", external=True),
    SectionInfo("commands", "ObsAI Commands", "Terminal", "Operations",
                "/commands"),
    SectionInfo("docs", "Documentation", "BookOpen", "Operations",
                "/docs"),
    SectionInfo("module-docs", "Module Reference", "FileCode", "Operations",
                "/module-docs"),
    SectionInfo("artifacts", "Artifacts", "Blocks", "Operations",
                "/artifacts", "/api/admin/monitoring/pipeline-traces"),
    SectionInfo("analytics", "Analytics & BI", "BarChart3", "Operations",
                "/analytics", "/api/admin/analytics/taxonomy"),
    SectionInfo("guardrails", "Guardrails", "Shield", "Operations",
                "/guardrails", "/api/admin/guardrails/stats"),
    SectionInfo("config-versions", "Config Versions", "GitBranch", "Operations",
                "/config-versions", "/api/admin/config/versions"),
    SectionInfo("audit", "Audit Log", "ClipboardList", "Operations",
                "/audit", "/api/admin/settings/history"),
    SectionInfo("backup", "Backup", "Save", "Operations",
                "/backup", "/api/admin/config/backup"),
    SectionInfo("version", "Version", "Info", "Operations",
                "/version"),
]

# Ordered group labels (used by ``get_sections_for_api``).
_GROUP_ORDER = [
    "Overview",
    "AI & Retrieval",
    "Intelligence",
    "Infrastructure",
    "Integrations",
    "Operations",
]


def get_section_registry() -> List[SectionInfo]:
    """Return the full flat list of section definitions."""
    return list(_SECTION_REGISTRY)


def get_sections_for_api() -> List[Dict[str, Any]]:
    """Return sections grouped by sidebar group for the admin API.

    Format::

        [
            {"label": "Overview", "items": [{"id": ..., "label": ..., ...}]},
            ...
        ]
    """
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for sec in _SECTION_REGISTRY:
        item: Dict[str, Any] = {
            "id": sec.id,
            "label": sec.label,
            "icon": sec.icon,
            "path": sec.path,
        }
        if sec.api_endpoint:
            item["api_endpoint"] = sec.api_endpoint
        if sec.external:
            item["external"] = True
        grouped.setdefault(sec.group, []).append(item)

    return [{"label": g, "items": grouped.get(g, [])} for g in _GROUP_ORDER]


# ═══════════════════════════════════════════════════════════════════════════════
# 7. Validation functions
# ═══════════════════════════════════════════════════════════════════════════════

def validate_agent_skill_refs() -> List[str]:
    """Verify all agent skill references resolve to known skills.

    Returns a list of human-readable error strings (empty == all OK).
    """
    errors: List[str] = []
    try:
        from chat_app.skill_catalog import SKILL_CATALOG  # noqa: WPS433
        from chat_app.agent_catalog import AGENT_CATALOG  # noqa: WPS433
    except ImportError as exc:
        return [f"Cannot import catalogs: {exc}"]

    skill_names = {s.name for s in SKILL_CATALOG}

    for agent in AGENT_CATALOG:
        for skill_ref in agent.skills:
            if skill_ref not in skill_names:
                errors.append(
                    f"Agent '{agent.name}' references unknown skill '{skill_ref}'"
                )
    return errors


def validate_skill_intents() -> List[str]:
    """Verify all skill intent strings are known Intent or RoutingTag values."""
    errors: List[str] = []
    try:
        from chat_app.skill_catalog import SKILL_CATALOG  # noqa: WPS433
    except ImportError as exc:
        return [f"Cannot import skill_catalog: {exc}"]

    for skill in SKILL_CATALOG:
        for intent_str in skill.intents:
            if not is_valid_intent_or_tag(intent_str):
                errors.append(
                    f"Skill '{skill.name}' has unknown intent '{intent_str}'"
                )
    return errors


def validate_agent_intents() -> List[str]:
    """Verify all agent intent strings are known Intent or RoutingTag values."""
    errors: List[str] = []
    try:
        from chat_app.agent_catalog import AGENT_CATALOG  # noqa: WPS433
    except ImportError as exc:
        return [f"Cannot import agent_catalog: {exc}"]

    for agent in AGENT_CATALOG:
        for intent_str in agent.intents:
            if not is_valid_intent_or_tag(intent_str):
                errors.append(
                    f"Agent '{agent.name}' has unknown intent '{intent_str}'"
                )
    return errors


def validate_strategy_overrides() -> List[str]:
    """Verify all strategy_overrides keys are known intents."""
    errors: List[str] = []
    try:
        from chat_app.settings import get_settings  # noqa: WPS433
        _settings = get_settings()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        return [f"Cannot load settings: {exc}"]

    overrides = getattr(
        getattr(_settings, "orchestration", None),
        "strategy_overrides",
        {},
    ) or {}

    for key in overrides:
        if key not in _INTENT_VALUES:
            errors.append(
                f"strategy_overrides key '{key}' is not a known Intent value"
            )
    return errors


def validate_all() -> Dict[str, List[str]]:
    """Run all validation checks.

    Returns ``{check_name: [errors]}``.  Empty lists mean the check passed.
    Logs warnings for any errors found.
    """
    results: Dict[str, List[str]] = {
        "agent_skill_refs": validate_agent_skill_refs(),
        "skill_intents": validate_skill_intents(),
        "agent_intents": validate_agent_intents(),
        "strategy_overrides": validate_strategy_overrides(),
    }

    for check, errs in results.items():
        for err in errs:
            logger.warning("registry validation [%s]: %s", check, err)

    return results


# ═══════════════════════════════════════════════════════════════════════════════
# 8. LLM capabilities context (injected into system prompt at query time)
# ═══════════════════════════════════════════════════════════════════════════════

_capabilities_context_cache: Optional[str] = None


def build_capabilities_context() -> str:
    """Build a concise capabilities summary for LLM context injection.

    Returns a compact text block describing available commands, skills,
    and agents so the multi-agent framework can reference them when
    answering user queries.  Cached after first *complete* build
    (i.e., only if skills and agents loaded successfully).
    """
    global _capabilities_context_cache
    if _capabilities_context_cache is not None:
        return _capabilities_context_cache

    lines: list[str] = ["### Available Capabilities"]
    _sections_loaded = 0  # track how many sections loaded

    # -- Slash commands (compact)
    cmds = get_command_registry()
    if cmds:
        cmd_lines = []
        for name, info in sorted(cmds.items()):
            desc = info.description[:80] if info.description else ""
            alias_str = f" (aliases: {', '.join(info.aliases)})" if info.aliases else ""
            cmd_lines.append(f"- `{name}` — {desc}{alias_str}")
        lines.append("\n**Slash Commands** (use these to invoke specific tools):")
        lines.extend(cmd_lines)
        _sections_loaded += 1

    # -- Skill families (grouped summary)
    try:
        from chat_app.skill_catalog import get_skill_catalog
        catalog_obj = get_skill_catalog()
        all_skills = catalog_obj.list_all() if hasattr(catalog_obj, "list_all") else []
        family_skills: dict[str, list[str]] = {}
        for s in all_skills:
            # list_all() returns dicts, not Skill objects
            fam = s.get("family", "unknown") if isinstance(s, dict) else (
                s.family.value if hasattr(s.family, "value") else str(s.family)
            )
            name = s.get("name", "?") if isinstance(s, dict) else s.name
            family_skills.setdefault(fam, []).append(name)

        if family_skills:
            lines.append(f"\n**Skills** ({len(all_skills)} total across {len(family_skills)} families):")
            for fam, names in sorted(family_skills.items()):
                sample = ", ".join(names[:8])
                extra = f" (+{len(names) - 8} more)" if len(names) > 8 else ""
                lines.append(f"- **{fam}**: {sample}{extra}")
            _sections_loaded += 1
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # -- Agent departments (compact summary)
    try:
        from chat_app.agent_catalog import get_agent_catalog
        agent_obj = get_agent_catalog()
        all_agents = agent_obj.list_all() if hasattr(agent_obj, "list_all") else []
        dept_agents: dict[str, list[str]] = {}
        for a in all_agents:
            # list_all() returns dicts, not Agent objects
            dept = a.get("department", "unknown") if isinstance(a, dict) else (
                a.department.value if hasattr(a.department, "value") else str(a.department)
            )
            name = a.get("name", "?") if isinstance(a, dict) else a.name
            dept_agents.setdefault(dept, []).append(name)

        if dept_agents:
            lines.append(f"\n**Agents** ({len(all_agents)} specialists across {len(dept_agents)} departments):")
            for dept, names in sorted(dept_agents.items()):
                lines.append(f"- **{dept}**: {', '.join(names)}")
            _sections_loaded += 1
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    # -- Orchestration strategies (one-liner)
    try:
        from chat_app.orchestration_strategies import _STRATEGY_REGISTRY
        strat_names = sorted(_STRATEGY_REGISTRY.keys())
        lines.append(f"\n**Orchestration Strategies** ({len(strat_names)}): {', '.join(strat_names)}")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.debug("%s", _exc)  # was: pass

    result = "\n".join(lines)
    # Only cache if all major sections loaded (commands + skills + agents)
    if _sections_loaded >= 3:
        _capabilities_context_cache = result
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 9. Registry dump (for /api/admin/registry endpoint)
# ═══════════════════════════════════════════════════════════════════════════════

def get_registry_dump() -> Dict[str, Any]:
    """Return full registry data for ``/api/admin/registry`` endpoint."""
    classifier_list = [
        {"name": i.name, "value": i.value}
        for i in Intent
        if i in CLASSIFIER_INTENTS
    ]
    extended_list = [
        {"name": i.name, "value": i.value}
        for i in Intent
        if i not in CLASSIFIER_INTENTS
    ]

    return {
        "intents": {
            "classifier": classifier_list,
            "extended": extended_list,
            "total": len(Intent),
        },
        "routing_tags": {
            "tags": [{"name": t.name, "value": t.value} for t in RoutingTag],
            "total": len(RoutingTag),
        },
        "commands": {
            "commands": get_commands_for_api(),
            "total": len(get_command_registry()),
        },
        "sections": {
            "groups": get_sections_for_api(),
            "total": len(_SECTION_REGISTRY),
        },
        "validation": validate_all(),
    }
