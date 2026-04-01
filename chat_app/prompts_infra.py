# =====================================================================
# ObsAI – PROMPT INFRASTRUCTURE
# Template loading, caching, and org-name substitution utilities.
# Used by all prompts_*.py modules.
# =====================================================================
import logging
import os
from pathlib import Path

_TEMPLATE_DIR = Path(__file__).resolve().parent / "prompt_templates"
_prompt_logger = logging.getLogger(__name__)

# In-memory template cache: {name: (mtime, content)}
_template_cache: dict[str, tuple[float, str]] = {}


def _get_org_names() -> tuple:
    """Return (org_name, org_full_name) from settings, with safe fallback.

    Defers to chat_app.prompts._get_org_names when available so that test
    patches on chat_app.prompts._get_org_names are honoured here too.
    """
    try:
        # Use the canonical version from prompts.py if already loaded,
        # so that @patch("chat_app.prompts._get_org_names") works from tests.
        import sys
        _prompts_mod = sys.modules.get("chat_app.prompts")
        if _prompts_mod is not None and hasattr(_prompts_mod, "_get_org_names"):
            return _prompts_mod._get_org_names()
    except Exception:  # broad catch — resilience at boundary
        pass
    # Fallback: resolve directly (used during prompts.py module load before
    # the sys.modules entry is established)
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
