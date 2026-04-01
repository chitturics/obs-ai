"""
Skill type definitions — SkillFamily, ApprovalGate, and Skill dataclass.

Extracted from skill_catalog.py to break the circular import that would
arise if skill_catalog_a.py and skill_catalog_b.py (data modules) imported
directly from skill_catalog.py (which imports from them).

Re-exported from skill_catalog.py for backward-compatible imports.

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
"""
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Set

logger = logging.getLogger(__name__)


class SkillFamily(str, Enum):
    """Families of skills grouped by human action type."""
    COGNITIVE = "cognitive"
    IO = "io"
    COMMUNICATION = "communication"
    ALERTING = "alerting"
    CREATIVE = "creative"
    SOCIAL = "social"
    MAINTENANCE = "maintenance"
    OPERATIONAL = "operational"


class ApprovalGate(str, Enum):
    AUTO = "auto"           # No approval needed
    INFORM = "inform"       # Execute and notify
    CONFIRM = "confirm"     # Ask before executing
    REVIEW = "review"       # Admin review required


@dataclass
class Skill:
    """A single skill mapping a human action to a system capability."""
    action: str                 # Human verb: "eat", "think", "run"
    name: str                   # System name: "ingest_data", "reason", "search"
    description: str            # What it does
    family: SkillFamily         # Grouping
    emoji: str = ""             # Visual identifier
    handler_key: str = ""       # Maps to tool_registry or skill action
    approval: ApprovalGate = ApprovalGate.AUTO
    requires: Set[str] = field(default_factory=set)
    intents: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    min_role: str = "USER"      # Minimum role: VIEWER, USER, ANALYST, ADMIN
    cooldown_seconds: int = 0   # Minimum time between invocations
    priority: int = 2           # 0=CRITICAL, 1=HIGH, 2=NORMAL, 3=LOW, 4=BACKGROUND
    enabled: bool = True

    @property
    def display_name(self) -> str:
        return f"{self.emoji} {self.action.title()}" if self.emoji else self.action.title()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "name": self.name,
            "description": self.description,
            "family": self.family.value,
            "emoji": self.emoji,
            "handler_key": self.handler_key,
            "approval": self.approval.value,
            "requires": list(self.requires),
            "intents": self.intents,
            "tags": self.tags,
            "min_role": self.min_role,
            "priority": self.priority,
            "enabled": self.enabled,
        }

