"""Security Startup Checks — block insecure defaults in production.

Runs at application startup to verify that:
1. No default/empty credentials in production
2. Authentication is enabled in production
3. Critical secrets are set
4. JWT/auth secrets have sufficient entropy

If any check fails in production, the app logs CRITICAL errors.
In development, warnings are logged instead.

Usage:
    from chat_app.security_startup import run_security_checks
    issues = run_security_checks()
    if issues["blockers"]:
        # Production should not start with blockers
"""

import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_DEFAULT_PASSWORDS = frozenset({
    "chainlit", "admin", "password", "changeme", "default", "secret",
    "postgres", "redis", "grafana", "12345", "test", "",
})

_MIN_SECRET_LENGTH = 16  # Minimum entropy for secrets


def run_security_checks() -> Dict[str, Any]:
    """Run all startup security checks. Returns blockers and warnings."""
    env = os.getenv("DEPLOYMENT_ENV", os.getenv("APP_ENVIRONMENT", "development"))
    is_prod = env in ("production", "staging")

    blockers: List[str] = []
    warnings: List[str] = []

    # 1. Check authentication is enabled in production
    auth_enabled = os.getenv("ENABLE_AUTHENTICATION", "true").lower() not in ("false", "0", "no")
    if is_prod and not auth_enabled:
        blockers.append("ENABLE_AUTHENTICATION is disabled in production")

    # 2. Check for default database password
    db_url = os.getenv("DATABASE_URL", "")
    for default_pw in _DEFAULT_PASSWORDS:
        if default_pw and f":{default_pw}@" in db_url:
            msg = f"DATABASE_URL contains default password '{default_pw}'"
            (blockers if is_prod else warnings).append(msg)
            break

    # 3. Check JWT/auth secrets
    for secret_name in ("CHAINLIT_AUTH_SECRET", "JWT_SECRET"):
        val = os.getenv(secret_name, "")
        if not val:
            msg = f"{secret_name} is not set"
            (blockers if is_prod else warnings).append(msg)
        elif len(val) < _MIN_SECRET_LENGTH:
            msg = f"{secret_name} is too short ({len(val)} chars, need {_MIN_SECRET_LENGTH}+)"
            (blockers if is_prod else warnings).append(msg)

    # 4. Check service API key
    svc_key = os.getenv("SERVICE_API_KEY", "")
    if not svc_key and is_prod:
        warnings.append("SERVICE_API_KEY not set — service-to-service auth disabled")

    # 5. Check default admin password
    admin_pw = os.getenv("ADMIN_PASSWORD", "")
    if admin_pw.lower() in _DEFAULT_PASSWORDS:
        msg = "ADMIN_PASSWORD is a default/weak value"
        (blockers if is_prod else warnings).append(msg)

    # 6. Check Redis password
    redis_pw = os.getenv("REDIS_PASSWORD", "")
    if not redis_pw and is_prod:
        warnings.append("REDIS_PASSWORD not set — Redis is unprotected")

    # 7. Check Grafana password
    grafana_pw = os.getenv("GF_SECURITY_ADMIN_PASSWORD", "admin")
    if grafana_pw.lower() in _DEFAULT_PASSWORDS:
        msg = "GF_SECURITY_ADMIN_PASSWORD is default"
        (blockers if is_prod else warnings).append(msg)

    # Log results
    for b in blockers:
        logger.critical("[SECURITY] BLOCKER: %s", b)
    for w in warnings:
        logger.warning("[SECURITY] WARNING: %s", w)

    if not blockers and not warnings:
        logger.info("[SECURITY] All startup security checks passed (%s)", env)

    return {
        "environment": env,
        "blockers": blockers,
        "warnings": warnings,
        "passed": len(blockers) == 0,
        "total_checks": 7,
    }
