"""
Skill Catalog — Comprehensive mapping of human actions to system capabilities.

Every human action (eat, sleep, think, run, walk, cry, act, play, jump, etc.)
maps to a concrete system skill that the ObsAI assistant can perform.

Skills are organized into action families:
- Cognitive: think, reason, analyze, evaluate, plan, decide, learn, remember, focus
- Physical/IO: eat (ingest), run (search), walk (browse), jump (escalate), swim (deep-dive)
- Communication: speak, listen, write, read, explain, teach, ask, answer, translate
- Emotional/Alerting: cry (alert), laugh (celebrate), worry (warn), calm (stabilize)
- Creative: play (experiment), build, create, design, compose, improvise
- Social: collaborate, delegate, lead, follow, mentor, negotiate
- Maintenance: sleep (rest), heal (recover), clean (purge), protect (guard), organize

Each skill has:
- action: Human-readable verb (the metaphor)
- name: System identifier
- description: What it does in the system
- category: Grouping for UI/routing
- handler_key: Maps to tool_registry or skills_manager action
- approval_level: HITL approval gate
- capabilities_required: System capabilities needed

Implementation is split for maintainability:
    skill_catalog_types.py — SkillFamily, ApprovalGate, Skill dataclass
    skill_catalog_a.py     — Catalog data group A (Cognitive … Social)
    skill_catalog_b.py     — Catalog data group B (Maintenance … Utility)
All types and SKILL_CATALOG are re-exported here for backward compat.
"""
import logging
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Type definitions — re-exported for backward-compatible imports
# ---------------------------------------------------------------------------
from chat_app.skill_catalog_types import (  # noqa: F401
    SkillFamily,
    ApprovalGate,
    Skill,
)

# ---------------------------------------------------------------------------
# Catalog data — combined from split modules
# ---------------------------------------------------------------------------
from chat_app.skill_catalog_a import SKILL_CATALOG_A
from chat_app.skill_catalog_b import SKILL_CATALOG_B

SKILL_CATALOG: List[Skill] = SKILL_CATALOG_A + SKILL_CATALOG_B

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Skill Registry
# ---------------------------------------------------------------------------

class SkillCatalog:
    """Registry and dispatcher for all system skills."""

    def __init__(self):
        self._skills: Dict[str, Skill] = {}
        self._by_action: Dict[str, Skill] = {}
        self._by_family: Dict[SkillFamily, List[Skill]] = {}
        self._by_tag: Dict[str, List[Skill]] = {}
        self._register_all()

    def _register_all(self):
        """Register all skills from the catalog."""
        for skill in SKILL_CATALOG:
            self._skills[skill.name] = skill
            self._by_action[skill.action.lower()] = skill
            self._by_family.setdefault(skill.family, []).append(skill)
            for tag in skill.tags:
                self._by_tag.setdefault(tag.lower(), []).append(skill)

    def get(self, name: str) -> Optional[Skill]:
        """Get a skill by system name."""
        return self._skills.get(name)

    def get_by_action(self, action: str) -> Optional[Skill]:
        """Get a skill by human action verb (e.g., 'think', 'eat', 'run')."""
        return self._by_action.get(action.lower())

    def get_family(self, family: SkillFamily) -> List[Skill]:
        """Get all skills in a family."""
        return self._by_family.get(family, [])

    def get_by_tag(self, tag: str) -> List[Skill]:
        """Get all skills with a specific tag."""
        return self._by_tag.get(tag.lower(), [])

    def get_for_intent(self, intent: str) -> List[Skill]:
        """Get all skills that handle a specific intent."""
        return [s for s in self._skills.values() if intent in s.intents]

    def get_enabled(self) -> List[Skill]:
        """Get all enabled skills."""
        return [s for s in self._skills.values() if s.enabled]

    def get_requiring_approval(self) -> List[Skill]:
        """Get skills that require user approval before execution."""
        return [
            s for s in self._skills.values()
            if s.approval in (ApprovalGate.CONFIRM, ApprovalGate.REVIEW)
        ]

    def search(self, query: str) -> List[Skill]:
        """Search skills by name, action, description, or tags. Supports multi-word queries."""
        query_lower = query.lower()
        words = [w for w in query_lower.split() if len(w) > 1]
        matches = []
        for skill in self._skills.values():
            searchable = f"{skill.name} {skill.action} {skill.description} {' '.join(skill.tags)}".lower()
            # Match full query or any individual word
            if query_lower in searchable or any(w in searchable for w in words):
                matches.append(skill)
        return matches

    def list_all(self) -> List[Dict[str, Any]]:
        """List all skills as dicts for API responses."""
        return [s.to_dict() for s in self._skills.values()]

    def list_actions(self) -> List[str]:
        """List all human action verbs."""
        return sorted(self._by_action.keys())

    def summary(self) -> Dict[str, Any]:
        """Get a summary of the skill catalog."""
        return {
            "total_skills": len(self._skills),
            "families": {
                f.value: len(skills)
                for f, skills in self._by_family.items()
            },
            "approval_required": len(self.get_requiring_approval()),
            "enabled": len(self.get_enabled()),
            "actions": self.list_actions(),
        }

    @property
    def count(self) -> int:
        return len(self._skills)


# ---------------------------------------------------------------------------
# Human-readable "thinking" messages for UI progress indicators
# ---------------------------------------------------------------------------

SKILL_THINKING_MESSAGES: Dict[str, str] = {
    # Cognitive
    "reason": "Thinking through the problem...",
    "analyze_spl": "Analyzing the SPL query...",
    "evaluate_quality": "Evaluating response quality...",
    "plan_actions": "Planning my approach...",
    "classify_intent": "Understanding your intent...",
    "self_learn": "Learning from this interaction...",
    "recall_context": "Let me check my memory...",
    "compress_context": "Focusing on the most relevant details...",
    "score_confidence": "Gauging my confidence...",
    "diagnose_failure": "Diagnosing the issue...",
    "validate_spl": "Validating the SPL syntax...",
    "compare_configs": "Comparing configurations...",
    # IO
    "ingest_data": "Ingesting data into the knowledge base...",
    "execute_search": "Running the search...",
    "browse_knowledge": "Browsing the knowledge base...",
    "deep_dive_analysis": "Taking a deep dive into this...",
    "retrieve_chunks": "Fetching relevant documentation...",
    "extract_fields": "Extracting key information...",
    "search_deep": "Searching deeply across multiple sources...",
    # Communication
    "generate_response": "Composing a response...",
    "generate_spl": "Writing the SPL query...",
    "explain_spl": "Preparing an explanation...",
    "answer_question": "Looking up the answer...",
    "summarize": "Summarizing the findings...",
    # Creative
    "experiment": "Experimenting with approaches...",
    "build_pipeline": "Building the pipeline...",
    "compose_query": "Composing the query...",
    "craft_config": "Crafting the configuration...",
    # Operational
    "optimize_spl": "Optimizing the query for performance...",
    "monitor_health": "Checking system health...",
    # Migration
    "analyze_splunk_confs": "Analyzing Splunk configuration files...",
    "compare_splunk_cribl": "Comparing Splunk and Cribl configurations...",
    "generate_cribl_pipeline": "Generating Cribl pipeline configuration...",
}


def get_thinking_message(skill_name: str) -> str:
    """Get a human-readable thinking message for a skill."""
    return SKILL_THINKING_MESSAGES.get(skill_name, "Working on it...")


# Singleton
_catalog: Optional[SkillCatalog] = None


def get_skill_catalog() -> SkillCatalog:
    """Get or create the singleton SkillCatalog."""
    global _catalog
    if _catalog is None:
        _catalog = SkillCatalog()
    return _catalog
