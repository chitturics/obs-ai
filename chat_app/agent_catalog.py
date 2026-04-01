"""
Agent Catalog — Comprehensive mapping of human roles to system agent personas.

Every human role (listener, parser, writer, coder, reader, watcher, developer,
tester, learner, ops guy, storage guy, network guy, project manager, director,
orchestrator, monitor, observer, database guy, UI guy, etc.) maps to a
specialized agent persona that handles specific types of tasks.

Agents are organized into departments:
- Engineering: coder, developer, tester, breaker, builder, architect
- Operations: ops_guy, deployer, monitor, observer, scheduler
- Data: storage_guy, database_guy, data_engineer, data_analyst
- Infrastructure: network_guy, platform_engineer, cloud_engineer
- Management: project_manager, director, owner, orchestrator, coordinator
- Knowledge: reader, writer, learner, teacher, documenter, researcher
- Security: security_guard, auditor, compliance_officer
- UI/UX: ui_guy, ux_designer, frontend_engineer
- Support: troubleshooter, helper, advisor, mentor

Each agent has:
- role: Human-readable role name
- name: System identifier
- description: What this agent specializes in
- department: Organizational grouping
- skills: List of skill names this agent can perform
- personality: Brief personality descriptor for LLM context
- expertise_level: How specialized this agent is

Types and constants are in agent_catalog_types.py.
The BUILT_IN_AGENTS list is in agent_catalog_data.py.
"""
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Re-export all types for backward compatibility
# ---------------------------------------------------------------------------
from chat_app.agent_catalog_types import (  # noqa: F401 — re-exported
    AGENT_PERSONA_DOC_MAP,
    DEPT_DIRECTIVES,
    EXPERTISE_STYLES,
    AgentCapabilities,
    AgentDataSources,
    AgentGuardrails,
    AgentPersona,
    Department,
    ExpertiseLevel,
    get_persona_doc_for_agent,
)

# ---------------------------------------------------------------------------
# Re-export the built-in agents list for backward compatibility
# ---------------------------------------------------------------------------
from chat_app.agent_catalog_data import AGENT_CATALOG  # noqa: F401 — re-exported


# ---------------------------------------------------------------------------
# Agent Registry
# ---------------------------------------------------------------------------

class AgentCatalog:
    """Registry and dispatcher for all agent personas."""

    def __init__(self):
        self._agents: Dict[str, AgentPersona] = {}
        self._by_role: Dict[str, AgentPersona] = {}
        self._by_department: Dict[Department, List[AgentPersona]] = {}
        self._by_intent: Dict[str, List[AgentPersona]] = {}
        self._register_all()

    def _register_all(self):
        """Register all agents from the catalog."""
        for agent in AGENT_CATALOG:
            self._agents[agent.name] = agent
            self._by_role[agent.role.lower()] = agent
            self._by_department.setdefault(agent.department, []).append(agent)
            for intent in agent.intents:
                self._by_intent.setdefault(intent, []).append(agent)

    def get(self, name: str) -> Optional[AgentPersona]:
        """Get an agent by system name."""
        return self._agents.get(name)

    def get_by_role(self, role: str) -> Optional[AgentPersona]:
        """Get an agent by human role (e.g., 'coder', 'ops guy')."""
        return self._by_role.get(role.lower())

    def get_department(self, department: Department) -> List[AgentPersona]:
        """Get all agents in a department."""
        return self._by_department.get(department, [])

    def get_for_intent(self, intent: str) -> List[AgentPersona]:
        """Get all agents that handle a specific intent."""
        return self._by_intent.get(intent, [])

    def get_best_agent(self, intent: str) -> Optional[AgentPersona]:
        """Get the best agent for a given intent (highest expertise)."""
        agents = self.get_for_intent(intent)
        if not agents:
            return None
        expertise_order = {
            ExpertiseLevel.LEAD: 4,
            ExpertiseLevel.EXPERT: 3,
            ExpertiseLevel.SPECIALIST: 2,
            ExpertiseLevel.GENERALIST: 1,
        }
        return max(agents, key=lambda a: expertise_order.get(a.expertise, 0))

    def get_active(self) -> List[AgentPersona]:
        """Get all active agents."""
        return [a for a in self._agents.values() if a.active]

    def search(self, query: str) -> List[AgentPersona]:
        """Search agents by name, role, description, or tags."""
        query_lower = query.lower()
        matches = []
        for agent in self._agents.values():
            if (query_lower in agent.name.lower()
                    or query_lower in agent.role.lower()
                    or query_lower in agent.description.lower()
                    or any(query_lower in t for t in agent.tags)):
                matches.append(agent)
        return matches

    def list_all(self) -> List[Dict[str, Any]]:
        """List all agents as dicts for API responses."""
        return [a.to_dict() for a in self._agents.values()]

    def list_roles(self) -> List[str]:
        """List all human role names."""
        return sorted(self._by_role.keys())

    def summary(self) -> Dict[str, Any]:
        """Get a summary of the agent catalog."""
        return {
            "total_agents": len(self._agents),
            "departments": {
                d.value: len(agents)
                for d, agents in self._by_department.items()
            },
            "active": len(self.get_active()),
            "expertise_breakdown": {
                level.value: sum(
                    1 for a in self._agents.values() if a.expertise == level
                )
                for level in ExpertiseLevel
            },
            "roles": self.list_roles(),
        }

    @property
    def count(self) -> int:
        return len(self._agents)


# Singleton
_catalog: Optional[AgentCatalog] = None


def get_agent_catalog() -> AgentCatalog:
    """Get or create the singleton AgentCatalog."""
    global _catalog
    if _catalog is None:
        _catalog = AgentCatalog()
    return _catalog
