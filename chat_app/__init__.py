import logging as _logging

_init_logger = _logging.getLogger(__name__)

try:
    from .message_handler import on_message
except ImportError:
    # Chainlit not available (e.g., Open WebUI API mode or local testing)
    on_message = None

# Startup security warnings for unconfigured secrets
try:
    from .settings import settings as _settings
    if not _settings.splunk.validator_pass:
        _init_logger.warning("SPLUNK_VALIDATOR_PASS not set — Splunk SPL validation disabled")
    if not _settings.auth.admin_password:
        _init_logger.warning("ADMIN_PASSWORD not set — using default authentication")
except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
    _init_logger.debug("Settings init skipped: %s", _exc)

# Lazy-loaded catalogs (available for API and admin UI)
from .skill_catalog import get_skill_catalog  # noqa: F401
from .agent_catalog import get_agent_catalog  # noqa: F401

# Agentic execution layer
from .skill_executor import get_skill_executor  # noqa: F401
from .agent_dispatcher import get_agent_dispatcher  # noqa: F401
from .workflow_orchestrator import get_workflow_orchestrator  # noqa: F401
