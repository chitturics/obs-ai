"""
Startup configuration validation.
Verifies settings and service connectivity using centralized config.
"""
import logging
import re
from typing import List, Tuple

from chat_app.settings import get_settings

logger = logging.getLogger(__name__)


def validate_config() -> Tuple[bool, List[str], List[str]]:
    """
    Validate application configuration on startup.

    Uses centralized settings (env var > config.yaml > defaults).

    Returns:
        Tuple of (is_valid, errors, warnings)
    """
    errors: List[str] = []
    warnings: List[str] = []
    cfg = get_settings()

    # Database URL is required
    if not cfg.database.url:
        errors.append("Missing required: DATABASE_URL (or CHAINLIT_DB_CONNINFO)")
    elif not cfg.database.url.startswith(("postgresql", "postgres")):
        errors.append(f"DATABASE_URL must be a PostgreSQL URL, got: {cfg.database.url[:20]}...")

    # LLM defaults — warn if still on defaults (user may not have configured)
    if cfg.ollama.base_url == "http://127.0.0.1:11430":
        warnings.append("OLLAMA_BASE_URL using default (http://127.0.0.1:11430)")
    if cfg.ollama.model == "qwen2.5:3b":
        warnings.append("OLLAMA_MODEL using default (qwen2.5:3b)")

    # Optional feature notes (info-level, not warnings)
    if not cfg.search_optimizer.enabled:
        logger.info("Optional: Search optimizer disabled")
    if not cfg.cache.enabled:
        logger.info("Optional: Redis caching disabled (in-memory fallback used)")
    if not cfg.auth.enabled:
        logger.info("Optional: Authentication disabled (anonymous access)")

    return len(errors) == 0, errors, warnings


def _is_valid_port(value: str) -> Tuple[bool, str]:
    """Check if a value is a valid port number."""
    try:
        port = int(value)
        if 1 <= port <= 65535:
            return True, ""
        return False, "Port must be between 1 and 65535."
    except ValueError:
        return False, "Port must be a number."


def _is_valid_path(value: str) -> Tuple[bool, str]:
    """Check if a value looks like a valid file/directory path."""
    if not value or not value.strip():
        return False, "Path cannot be empty."
    # Block obvious injection attempts
    if any(c in value for c in [";", "&", "|", "`", "$("]):
        return False, "Path contains invalid characters."
    return True, ""


def _is_valid_interval(value: str) -> Tuple[bool, str]:
    """Check if a value is a valid time interval (positive integer)."""
    try:
        interval = int(value)
        if interval > 0:
            return True, ""
        return False, "Interval must be a positive number."
    except ValueError:
        return False, "Interval must be a number (seconds)."


def _is_valid_sourcetype(value: str) -> Tuple[bool, str]:
    """Check if a value is a valid Splunk sourcetype name."""
    if not value or not value.strip():
        return False, "Sourcetype name cannot be empty."
    if not re.match(r'^[a-zA-Z0-9_:.-]+$', value):
        return False, "Sourcetype name can only contain letters, numbers, underscores, colons, dots, and hyphens."
    return True, ""


def _is_valid_stanza_name(value: str) -> Tuple[bool, str]:
    """Check if a value is a valid stanza name."""
    if not value or not value.strip():
        return False, "Stanza name cannot be empty."
    if any(c in value for c in ["[", "]", "\n", "\r"]):
        return False, "Stanza name cannot contain brackets or newlines."
    return True, ""


def validate_user_input(value: str, expected_type: str) -> Tuple[bool, str]:
    """
    Validate user input based on the expected field type.

    Args:
        value: The user's input.
        expected_type: The field name (e.g., 'port', 'path', 'interval').

    Returns:
        A tuple of (is_valid, error_message).
    """
    if expected_type == "port":
        return _is_valid_port(value)
    if expected_type in ("path", "script_path"):
        return _is_valid_path(value)
    if expected_type == "interval":
        return _is_valid_interval(value)
    if expected_type == "sourcetype_name":
        return _is_valid_sourcetype(value)
    if expected_type in ("stanza_name", "filename"):
        return _is_valid_stanza_name(value)
    # Default: accept non-empty input
    if not value or not value.strip():
        return False, f"{expected_type} cannot be empty."
    return True, ""


def log_startup_config():
    """Log current configuration state for debugging."""
    is_valid, errors, warnings = validate_config()
    cfg = get_settings()

    logger.info("=" * 60)
    logger.info("STARTUP CONFIGURATION VALIDATION")
    logger.info("=" * 60)

    if errors:
        for err in errors:
            logger.error("  CONFIG ERROR: %s", err)

    if warnings:
        for warn in warnings:
            logger.warning("  CONFIG WARNING: %s", warn)

    if is_valid:
        logger.info("  Configuration: VALID")
    else:
        logger.error("  Configuration: INVALID - application may not function correctly")

    # Log active features from centralized settings
    features = {
        "Authentication": cfg.auth.enabled,
        "Redis Cache": cfg.cache.enabled,
        "Search Optimizer": cfg.search_optimizer.enabled,
        "Splunk Integration": cfg.splunk.is_configured,
    }

    logger.info("  Active Features:")
    for feature, enabled in features.items():
        status = "ENABLED" if enabled else "disabled"
        logger.info("    %s: %s", feature, status)

    logger.info("  Model: %s @ %s", cfg.ollama.model, cfg.ollama.base_url)
    logger.info("  Profile: %s", cfg.app.active_profile)
    logger.info("=" * 60)

    return is_valid
