"""User-facing AI personas that customize the assistant's behavior.

Each persona modifies the system prompt, response style, verbosity, and
follow-up behavior to tailor the assistant to a specific use-case or
audience.  Built-in personas are always available; custom personas are
persisted to a JSON file so they survive restarts.
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

_CUSTOM_PERSONAS_PATH = os.environ.get(
    "CUSTOM_PERSONAS_FILE",
    os.path.join(os.path.dirname(__file__), "..", "data", "custom_personas.json"),
)


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class UserPersona:
    """A user-facing AI persona that shapes how the assistant responds."""

    id: str
    name: str
    description: str
    system_prompt_modifier: str  # Appended to system prompt
    response_style: str          # "technical", "executive", "tutorial", "debug"
    verbosity: str               # "concise", "normal", "detailed"
    expertise_level: str         # "beginner", "intermediate", "expert"
    follow_up_style: str         # "none", "suggestions", "interactive"
    icon: str = ""
    builtin: bool = True
    # Persona-driven skill priorities and approval overrides
    skill_priority_tags: List[str] = field(default_factory=list)  # Boost skills with these tags
    approval_bypass_intents: List[str] = field(default_factory=list)  # Auto-approve these intents
    version: int = 1

    def to_dict(self) -> Dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Built-in personas
# ---------------------------------------------------------------------------

BUILT_IN_PERSONAS: List[UserPersona] = [
    UserPersona(
        id="technical_expert",
        name="Technical Expert",
        description=(
            "Deep technical answers with code examples, regex patterns, and "
            "architecture details. Assumes strong Splunk/Cribl background."
        ),
        system_prompt_modifier=(
            "Provide deep technical answers. Include code examples, regex "
            "patterns, and configuration snippets. Assume the user is an "
            "experienced Splunk/Cribl administrator."
        ),
        response_style="technical",
        verbosity="detailed",
        expertise_level="expert",
        follow_up_style="suggestions",
        skill_priority_tags=["cognitive", "io", "maintenance"],
    ),
    UserPersona(
        id="executive_summary",
        name="Executive Summary",
        description=(
            "High-level answers focused on business impact, risk, and "
            "recommendations. No code unless specifically asked."
        ),
        system_prompt_modifier=(
            "Provide concise, high-level answers focused on business impact "
            "and recommendations. Avoid code unless specifically requested. "
            "Use bullet points."
        ),
        response_style="executive",
        verbosity="concise",
        expertise_level="intermediate",
        follow_up_style="none",
        skill_priority_tags=["communication", "alerting"],
    ),
    UserPersona(
        id="tutorial_mode",
        name="Tutorial Mode",
        description=(
            "Step-by-step explanations with examples. Explains concepts "
            "before using them. Good for learning."
        ),
        system_prompt_modifier=(
            "Explain everything step by step. Define terms before using them. "
            "Include examples for every concept. Use a teaching tone."
        ),
        response_style="tutorial",
        verbosity="detailed",
        expertise_level="beginner",
        follow_up_style="interactive",
        skill_priority_tags=["social", "creative"],
    ),
    UserPersona(
        id="debug_mode",
        name="Debug Mode",
        description=(
            "Focused on troubleshooting. Shows reasoning process, checks "
            "assumptions, suggests diagnostic steps."
        ),
        system_prompt_modifier=(
            "Focus on troubleshooting and diagnosis. Show your reasoning "
            "process. Check assumptions explicitly. Suggest specific "
            "diagnostic steps and commands."
        ),
        response_style="debug",
        verbosity="normal",
        expertise_level="expert",
        follow_up_style="suggestions",
        skill_priority_tags=["cognitive", "maintenance", "operational"],
    ),
    UserPersona(
        id="security_analyst",
        name="Security Analyst",
        description=(
            "Security-focused. Emphasizes threat detection, compliance, "
            "MITRE ATT&CK mapping, and security best practices."
        ),
        system_prompt_modifier=(
            "Focus on security aspects. Reference MITRE ATT&CK where "
            "relevant. Emphasize threat detection, compliance requirements, "
            "and security best practices. Flag potential security risks."
        ),
        response_style="technical",
        verbosity="normal",
        expertise_level="expert",
        follow_up_style="suggestions",
        skill_priority_tags=["cognitive", "maintenance", "operational"],
        approval_bypass_intents=["security", "config_health_check"],
    ),
]


# ---------------------------------------------------------------------------
# In-memory registry (built-in + custom)
# ---------------------------------------------------------------------------

_personas: Dict[str, UserPersona] = {}
_loaded = False


def _ensure_loaded() -> None:
    """Populate the registry on first access."""
    global _loaded
    if _loaded:
        return
    # Built-in personas first
    for p in BUILT_IN_PERSONAS:
        _personas[p.id] = p
    # Then custom (may override built-in ids, though not recommended)
    _load_custom_personas()
    _loaded = True


def _load_custom_personas() -> None:
    """Load custom personas from the JSON persistence file."""
    path = Path(_CUSTOM_PERSONAS_PATH)
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        for entry in data:
            entry["builtin"] = False
            persona = UserPersona(**entry)
            _personas[persona.id] = persona
        logger.info("[PERSONA] Loaded %d custom personas from %s", len(data), path)
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("[PERSONA] Failed to load custom personas: %s", exc)


def _save_custom_personas() -> None:
    """Persist all custom personas to the JSON file."""
    path = Path(_CUSTOM_PERSONAS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    custom = [p.to_dict() for p in _personas.values() if not p.builtin]
    path.write_text(json.dumps(custom, indent=2), encoding="utf-8")
    logger.info("[PERSONA] Saved %d custom personas to %s", len(custom), path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_persona(persona_id: str) -> Optional[UserPersona]:
    """Return a persona by ID, or ``None`` if not found."""
    _ensure_loaded()
    return _personas.get(persona_id)


def list_personas() -> List[UserPersona]:
    """Return all registered personas (built-in + custom)."""
    _ensure_loaded()
    return list(_personas.values())


def get_persona_prompt_modifier(persona_id: str) -> str:
    """Return the system-prompt modifier for a persona, or empty string."""
    persona = get_persona(persona_id)
    if persona is None:
        return ""
    return persona.system_prompt_modifier


def save_custom_persona(persona: UserPersona) -> UserPersona:
    """Add or update a custom persona and persist to disk.

    The ``builtin`` flag is forced to ``False`` so callers cannot overwrite
    built-in personas through this function.
    """
    _ensure_loaded()
    persona.builtin = False
    _personas[persona.id] = persona
    _save_custom_personas()
    return persona


def delete_custom_persona(persona_id: str) -> bool:
    """Remove a custom persona.  Returns ``True`` if deleted, ``False`` if
    the persona was built-in or did not exist."""
    _ensure_loaded()
    persona = _personas.get(persona_id)
    if persona is None or persona.builtin:
        return False
    del _personas[persona_id]
    _save_custom_personas()
    return True


def get_skill_priority_tags(persona_id: str) -> List[str]:
    """Return skill priority tags for a persona (used by agent dispatcher)."""
    persona = get_persona(persona_id)
    return persona.skill_priority_tags if persona else []


def get_approval_bypass_intents(persona_id: str) -> List[str]:
    """Return intents that can bypass approval for a persona."""
    persona = get_persona(persona_id)
    return persona.approval_bypass_intents if persona else []


def bump_persona_version(persona_id: str) -> Optional[int]:
    """Increment the version number of a persona (for change tracking)."""
    _ensure_loaded()
    persona = _personas.get(persona_id)
    if persona is None:
        return None
    persona.version += 1
    if not persona.builtin:
        _save_custom_personas()
    return persona.version
