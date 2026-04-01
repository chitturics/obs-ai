# =====================================================================
# ObsAI – PROMPT DEFINITIONS  (coordinator module)
# Observability AI Assistant with Human-in-the-Loop
# Loads from prompt_templates/*.md files, falls back to inline defaults.
#
# Actual prompt data lives in sub-modules for maintainability:
#   prompts_system.py     — core system prompt (ObsAI identity + rules)
#   prompts_query_gen.py  — query generation prompt
#   prompts_analysis.py   — query analysis, config, conceptual, search opt
#
# This file owns the infrastructure (template loading, cache, org-name
# substitution) and re-exports everything for backward-compatible imports.
# =====================================================================
import logging
import os
from pathlib import Path

_TEMPLATE_DIR = Path(__file__).resolve().parent / "prompt_templates"
_prompt_logger = logging.getLogger(__name__)

# In-memory template cache: {name: (mtime, content)}
_template_cache: dict[str, tuple[float, str]] = {}


def _get_org_names() -> tuple:
    """Return (org_name, org_full_name) from settings, with safe fallback."""
    try:
        from chat_app.settings import get_settings
        s = get_settings()
        return s.app.org_name, s.app.org_full_name
    except Exception as _exc:  # broad catch — resilience against all failures
        return os.getenv("ORG_NAME", "MY_ORG"), os.getenv("ORG_FULL_NAME", "My Organization")


def _apply_org_name(text: str) -> str:
    """Replace {ORG_NAME} and {ORG_FULL_NAME} placeholders with configured org name."""
    org, org_full = _get_org_names()
    text = text.replace("{ORG_NAME}", org).replace("{ORG_FULL_NAME}", org_full)
    return text


def _load_template(name: str, fallback: str) -> str:
    """Load prompt template from file with mtime-based caching."""
    path = _TEMPLATE_DIR / f"{name}.md"
    if path.is_file():
        try:
            mtime = path.stat().st_mtime
            cached = _template_cache.get(name)
            if cached and cached[0] == mtime:
                return cached[1]
            content = _apply_org_name(path.read_text(encoding="utf-8").strip())
            _template_cache[name] = (mtime, content)
            return content
        except (OSError, ValueError, KeyError, TypeError) as exc:
            _prompt_logger.warning(f"Failed to load prompt template {path}: {exc}")
    return _apply_org_name(fallback.strip())


def invalidate_template_cache() -> int:
    """Clear in-memory template cache. Returns count of cleared entries."""
    count = len(_template_cache)
    _template_cache.clear()
    _prompt_logger.info("Template cache cleared (%d entries)", count)
    return count


# ---------------------------------------------------------------------------
# Prompt data (imported from sub-modules)
# Sub-modules import _load_template and _apply_org_name from prompts_infra.py
# which mirrors the infrastructure defined above.  The infrastructure here is
# the canonical version; tests patch this module's _get_org_names.
# ---------------------------------------------------------------------------

from chat_app.prompts_system import (  # noqa: F401
    _system_prompt_inline,
    system_prompt,
)

from chat_app.prompts_query_gen import (  # noqa: F401
    _query_generation_inline,
    query_generation_prompt,
)

from chat_app.prompts_analysis import (  # noqa: F401
    _query_analysis_inline,
    query_analysis_prompt,
    _config_guidance_inline,
    config_guidance_prompt,
    _conceptual_inline,
    conceptual_prompt,
    _search_optimization_inline,
    search_optimization_prompt,
    _query_optimizer_inline,
    query_optimizer_prompt,
    routing_guide,
)

# ---------------------------------------------------------------------------
# Backward-compatible aliases (kept for all existing consumers)
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = system_prompt
agent_system_prompt = system_prompt
splunk_query_generation_prompt = query_generation_prompt
splunk_query_analysis_prompt = query_analysis_prompt
splunk_search_optimization_prompt = search_optimization_prompt
splunk_query_optimizer_prompt = query_optimizer_prompt
text_analysis_prompt = conceptual_prompt


# =====================================================================
# AGENT RESPONSE TEMPLATES — Per-department response structure guidance
# =====================================================================

AGENT_RESPONSE_TEMPLATES = {
    "engineering": (
        "Structure your response as:\n"
        "1. **Solution** — Working code or configuration with comments\n"
        "2. **How It Works** — Brief technical explanation\n"
        "3. **Edge Cases** — Important caveats or limitations\n"
        "4. **Testing** — How to verify the solution works"
    ),
    "operations": (
        "Structure your response as:\n"
        "1. **Assessment** — Current state and impact analysis\n"
        "2. **Action Plan** — Step-by-step remediation with commands\n"
        "3. **Rollback Plan** — How to revert if needed\n"
        "4. **Monitoring** — What to watch after making changes"
    ),
    "data": (
        "Structure your response as:\n"
        "1. **Query/Pipeline** — Optimized SPL or data pipeline code\n"
        "2. **Performance Notes** — Expected execution characteristics\n"
        "3. **Data Quality** — Assumptions about input data\n"
        "4. **Alternatives** — Other approaches for different scale/needs"
    ),
    "infrastructure": (
        "Structure your response as:\n"
        "1. **Architecture** — Component layout and connections\n"
        "2. **Configuration** — Specific settings with explanations\n"
        "3. **Scaling** — How this handles growth\n"
        "4. **Resilience** — Failure modes and mitigation"
    ),
    "knowledge": (
        "Structure your response as:\n"
        "1. **Concept** — Clear explanation with context\n"
        "2. **Examples** — Concrete illustrations\n"
        "3. **Related Topics** — Connected concepts to explore\n"
        "4. **Resources** — Where to learn more"
    ),
    "security": (
        "Structure your response as:\n"
        "1. **Finding** — Security issue or recommendation\n"
        "2. **Risk Level** — Severity and potential impact\n"
        "3. **Remediation** — Specific fix with verification steps\n"
        "4. **Compliance** — Relevant standards (CIS, NIST, etc.)"
    ),
    "support": (
        "Structure your response as:\n"
        "1. **Understanding** — Acknowledge the issue clearly\n"
        "2. **Solution** — Step-by-step with verification at each step\n"
        "3. **Prevention** — How to avoid this in the future\n"
        "4. **Escalation** — When to seek additional help"
    ),
    "management": (
        "Structure your response as:\n"
        "1. **Summary** — Key findings in 2-3 sentences\n"
        "2. **Recommendations** — Prioritized action items\n"
        "3. **Dependencies** — What needs to happen first\n"
        "4. **Timeline** — Suggested sequence of work"
    ),
}
