"""
Agent Catalog Types — Dataclasses, enums, and style constants for agent personas.

Extracted from agent_catalog.py to keep that file under 600 lines.
All types are re-exported by agent_catalog.py for backward compatibility.
"""
import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Department directives — injected into agent system prompts
# ---------------------------------------------------------------------------
DEPT_DIRECTIVES: Dict[str, str] = {
    "engineering": (
        "Focus on code quality, efficiency, and correctness. "
        "Provide working examples with proper error handling. "
        "Consider edge cases and performance implications."
    ),
    "operations": (
        "Prioritize stability, reliability, and recoverability. "
        "Always suggest rollback plans and monitoring checks. "
        "Consider impact on running systems before recommending changes."
    ),
    "data": (
        "Think in data flows and pipelines. Optimize query performance. "
        "Consider data volume, cardinality, and retention. "
        "Validate data quality and suggest schema improvements."
    ),
    "infrastructure": (
        "Focus on scalability, redundancy, and resource efficiency. "
        "Consider network topology, DNS, load balancing, and failover. "
        "Suggest infrastructure-as-code approaches when appropriate."
    ),
    "management": (
        "Provide clear summaries and actionable recommendations. "
        "Consider resource constraints, timelines, and dependencies. "
        "Prioritize by impact and urgency."
    ),
    "knowledge": (
        "Be thorough and educational. Provide context and background. "
        "Link related concepts together. Use examples to illustrate. "
        "Build understanding progressively from basics to advanced."
    ),
    "security": (
        "Apply defense-in-depth thinking. Flag potential security issues proactively. "
        "Reference compliance frameworks (CIS, NIST, OWASP) when relevant. "
        "Consider least privilege, encryption, and audit trails."
    ),
    "ui_ux": (
        "Focus on user experience, accessibility, and visual clarity. "
        "Consider responsive design and cross-browser compatibility. "
        "Suggest usability improvements and consistent design patterns."
    ),
    "support": (
        "Be empathetic and patient. Start from the user's knowledge level. "
        "Provide step-by-step guidance with verification points. "
        "Offer multiple approaches ranked by simplicity."
    ),
    "creative": (
        "Think innovatively. Suggest novel approaches and combinations. "
        "Balance creativity with practicality. Prototype quickly."
    ),
}

# ---------------------------------------------------------------------------
# Expertise style modifiers — shape response depth and framing
# ---------------------------------------------------------------------------
EXPERTISE_STYLES: Dict[str, str] = {
    "lead": (
        "Take an architectural perspective. Consider system-wide trade-offs, "
        "long-term maintainability, and team scalability. Guide rather than dictate."
    ),
    "expert": (
        "Be precise and technically deep. Include edge cases, caveats, and "
        "performance characteristics. Provide production-ready solutions."
    ),
    "specialist": (
        "Focus tightly on your domain. Be direct and practical. "
        "Provide domain-specific best practices and proven patterns."
    ),
    "generalist": (
        "Give a broad overview covering multiple angles. "
        "Suggest domain specialists for deep dives. Connect concepts across areas."
    ),
}


# ---------------------------------------------------------------------------
# Agent persona documents — rich markdown governance/style docs loaded from
# chat_app/agent_personas/*.md and injected into agent system prompts.
# ---------------------------------------------------------------------------
_PERSONA_DOCS_DIR = Path(os.path.dirname(__file__)) / "agent_personas"

# Mapping from agent *name* to persona doc filename (without .md).
# Only agents with a dedicated persona doc need an entry here.
AGENT_PERSONA_DOC_MAP: Dict[str, str] = {
    "spl_coder": "spl_expert",
    "spl_analyst": "spl_expert",
    "config_builder": "config_helper",
    "migration_engineer": "migration_engineer",
    "general_assistant": "general_assistant",
}

_persona_doc_cache: Dict[str, str] = {}


def _load_persona_doc(doc_name: str) -> str:
    """Load and cache a persona markdown document by its base name."""
    if doc_name in _persona_doc_cache:
        return _persona_doc_cache[doc_name]
    path = _PERSONA_DOCS_DIR / f"{doc_name}.md"
    if path.exists():
        try:
            content = path.read_text(encoding="utf-8").strip()
            _persona_doc_cache[doc_name] = content
            logger.debug("[AGENT_CATALOG] Loaded persona doc: %s", path.name)
            return content
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.warning("[AGENT_CATALOG] Failed to load persona doc %s: %s", path, exc)
    return ""


def get_persona_doc_for_agent(agent_name: str) -> str:
    """Return the persona document content for an agent, or empty string."""
    doc_name = AGENT_PERSONA_DOC_MAP.get(agent_name, "")
    if not doc_name:
        return ""
    return _load_persona_doc(doc_name)


class Department(str, Enum):
    """Organizational departments for agent grouping."""
    ENGINEERING = "engineering"
    OPERATIONS = "operations"
    DATA = "data"
    INFRASTRUCTURE = "infrastructure"
    MANAGEMENT = "management"
    KNOWLEDGE = "knowledge"
    SECURITY = "security"
    UI_UX = "ui_ux"
    SUPPORT = "support"
    CREATIVE = "creative"


class ExpertiseLevel(str, Enum):
    """How specialized the agent is."""
    GENERALIST = "generalist"
    SPECIALIST = "specialist"
    EXPERT = "expert"
    LEAD = "lead"


@dataclass
class AgentCapabilities:
    """What an agent CAN do — explicit capability boundaries."""
    max_concurrent_skills: int = 3
    can_delegate: bool = False          # Can hand off to other agents
    can_escalate: bool = False          # Can escalate to human
    can_ask_clarification: bool = True  # Can ask user for more info
    can_write: bool = False             # Can trigger write/modify operations
    supported_output_formats: List[str] = field(default_factory=lambda: ["text", "markdown"])
    max_context_tokens: int = 4096


@dataclass
class AgentGuardrails:
    """What an agent CANNOT do — hard safety boundaries."""
    forbidden_skills: List[str] = field(default_factory=list)
    requires_approval_for: List[str] = field(default_factory=list)
    max_execution_time_seconds: float = 30.0
    read_only: bool = False
    pii_handling: str = "redact"        # "redact", "mask", "allow"
    scope: str = ""                     # Human-readable scope description
    max_retries: int = 2


@dataclass
class AgentDataSources:
    """What knowledge sources an agent has access to."""
    collections: List[str] = field(default_factory=lambda: ["spl_docs", "org_configs", "ingest_specs"])
    feedback_access: bool = False
    internet_access: bool = False
    mcp_tools: List[str] = field(default_factory=list)
    knowledge_graph: bool = True
    document_paths: List[str] = field(default_factory=list)


@dataclass
class AgentPersona:
    """A specialized agent persona with skills, capabilities, guardrails, and data sources."""
    role: str                    # Human role: "coder", "ops guy", "tester"
    name: str                    # System name: "spl_coder", "ops_engineer"
    description: str             # What this agent does
    department: Department       # Organizational grouping
    skills: List[str] = field(default_factory=list)      # Skill names from SkillCatalog
    personality: str = ""        # Brief personality for LLM system prompt
    expertise: ExpertiseLevel = ExpertiseLevel.SPECIALIST
    emoji: str = ""              # Visual identifier
    intents: List[str] = field(default_factory=list)      # Intents this agent handles
    tags: List[str] = field(default_factory=list)
    active: bool = True
    # Enterprise: capabilities, guardrails, data sources
    capabilities: AgentCapabilities = field(default_factory=AgentCapabilities)
    guardrails: AgentGuardrails = field(default_factory=AgentGuardrails)
    data_sources: AgentDataSources = field(default_factory=AgentDataSources)

    @property
    def display_name(self) -> str:
        return f"{self.emoji} {self.role.title()}" if self.emoji else self.role.title()

    def get_system_prompt_fragment(self) -> str:
        """Generate a rich, multi-section system prompt fragment for this agent."""
        sections = []

        # Role identity
        sections.append(
            f"## Agent Role: {self.role.replace('_', ' ').title()}\n"
            f"{self.description}"
        )

        # Department directive
        dept_directive = DEPT_DIRECTIVES.get(self.department.value, "")
        if dept_directive:
            sections.append(f"## Department Directive ({self.department.value.title()})\n{dept_directive}")

        # Expertise style
        expertise_style = EXPERTISE_STYLES.get(self.expertise.value, "")
        if expertise_style:
            sections.append(f"## Expertise Level: {self.expertise.value.title()}\n{expertise_style}")

        # Personality and approach
        if self.personality:
            sections.append(f"## Personality & Approach\n{self.personality}")

        # Core skills
        if self.skills:
            skill_list = ", ".join(self.skills[:8])
            sections.append(f"## Core Skills\n{skill_list}")

        # Capabilities and guardrails
        if self.guardrails.scope:
            sections.append(f"## Scope & Boundaries\n{self.guardrails.scope}")
        if self.guardrails.read_only:
            sections.append("**IMPORTANT: You are READ-ONLY. Do NOT suggest or execute write operations.**")
        if self.capabilities.can_ask_clarification:
            sections.append(
                "## Clarification Protocol\n"
                "If you are uncertain about the user's intent or lack sufficient information, "
                "ASK a specific clarifying question before proceeding. "
                "It is better to ask than to guess incorrectly."
            )
        if self.data_sources.collections:
            sections.append(f"## Available Knowledge Sources\nCollections: {', '.join(self.data_sources.collections)}")
        if self.capabilities.can_delegate:
            sections.append("You may delegate sub-tasks to other agents when the task crosses department boundaries.")

        # Persona document (governance, communication style, quality criteria)
        persona_doc = get_persona_doc_for_agent(self.name)
        if persona_doc:
            sections.append(f"## Agent Persona Guidelines\n{persona_doc}")

        return "\n\n".join(sections)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "name": self.name,
            "description": self.description,
            "department": self.department.value,
            "skills": self.skills,
            "personality": self.personality,
            "expertise": self.expertise.value,
            "emoji": self.emoji,
            "intents": self.intents,
            "tags": self.tags,
            "active": self.active,
            "capabilities": {
                "max_concurrent_skills": self.capabilities.max_concurrent_skills,
                "can_delegate": self.capabilities.can_delegate,
                "can_escalate": self.capabilities.can_escalate,
                "can_ask_clarification": self.capabilities.can_ask_clarification,
                "can_write": self.capabilities.can_write,
            },
            "guardrails": {
                "forbidden_skills": self.guardrails.forbidden_skills,
                "requires_approval_for": self.guardrails.requires_approval_for,
                "read_only": self.guardrails.read_only,
                "scope": self.guardrails.scope,
                "max_retries": self.guardrails.max_retries,
            },
            "data_sources": {
                "collections": self.data_sources.collections,
                "feedback_access": self.data_sources.feedback_access,
                "internet_access": self.data_sources.internet_access,
                "mcp_tools": self.data_sources.mcp_tools,
                "knowledge_graph": self.data_sources.knowledge_graph,
            },
        }
