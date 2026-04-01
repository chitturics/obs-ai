"""
App Routes — Route mounting and middleware setup for the Chainlit FastAPI app.

Extracted from app.py to keep that file under 600 lines.
Called once at app.py module-import time via mount_all_routes().
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


def mount_all_routes(settings: Any) -> None:
    """
    Mount all routes on the Chainlit FastAPI app.

    Inserts health routes, admin API, and API Services router at the BEGINNING
    of the route list so Chainlit's SPA catch-all does not intercept them.

    Args:
        settings: The loaded AppSettings instance.
    """
    try:
        from chainlit.server import app as _fastapi_app

        _mount_security_middleware(_fastapi_app, settings)
        _mount_cors_middleware(_fastapi_app, settings)
        _mount_health_routes(_fastapi_app)
        _mount_admin_routes(_fastapi_app)

    except ImportError as _exc:
        logger.info("Health routes not available (optional): %s", _exc)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
        logger.warning("Health routes mount warning (non-fatal): %s", _exc)


def _mount_security_middleware(fastapi_app: Any, settings: Any) -> None:
    """Add credential-in-query-string guard middleware."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from starlette.responses import JSONResponse

    class _CredentialQueryGuard(BaseHTTPMiddleware):
        """Reject requests that pass credentials (username/password) via URL query parameters.

        Credentials in URIs are a security risk: they appear in browser history,
        server access logs, proxy logs, and referrer headers.
        """

        _SENSITIVE_PARAMS = {"password", "passwd", "secret", "api_key", "apikey"}
        _CREDENTIAL_COMBOS = {"username", "user", "login"}  # block if paired with password

        async def dispatch(self, request, call_next):
            if request.query_params:
                params_lower = {k.lower() for k in request.query_params.keys()}
                # Block any password/secret in query string (any method)
                leaked = params_lower & self._SENSITIVE_PARAMS
                # Also block username-like params if password is also present
                if not leaked and (params_lower & self._CREDENTIAL_COMBOS) and (params_lower & {"password", "passwd"}):
                    leaked = params_lower & (self._CREDENTIAL_COMBOS | {"password", "passwd"})
                if leaked:
                    logger.warning(
                        "Blocked credentials in URI: %s %s (params: %s)",
                        request.method, request.url.path, ", ".join(leaked),
                    )
                    return JSONResponse(
                        status_code=400,
                        content={
                            "detail": "Credentials must not be sent in URL query parameters. "
                                      "Use POST with form/JSON body instead."
                        },
                    )
            return await call_next(request)

    fastapi_app.add_middleware(_CredentialQueryGuard)
    logger.info("Security middleware: credential query-string guard enabled")


def _mount_cors_middleware(fastapi_app: Any, settings: Any) -> None:
    """Add CORS middleware if enabled in settings."""
    if not (hasattr(settings, 'security') and getattr(settings.security, 'cors_enabled', False)):
        return

    from starlette.middleware.cors import CORSMiddleware
    cors_origins = getattr(settings.security, 'cors_allowed_origins', [
        "https://localhost:8000", "https://127.0.0.1:8000",
    ])
    # Safety check: warn if wildcard origin is used
    if "*" in cors_origins:
        logger.warning(
            "CORS wildcard origin '*' detected — this is insecure and should NOT be used in production. "
            "Set explicit origins in config.yaml security.cors.allowed_origins"
        )
        if settings.app.environment.lower() == "production":
            logger.warning("Stripping wildcard '*' from CORS origins in production environment")
            cors_origins = [o for o in cors_origins if o != "*"]
            if not cors_origins:
                cors_origins = ["https://localhost:8000", "https://127.0.0.1:8000"]
    fastapi_app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", "Accept"],
    )
    logger.info("CORS middleware enabled: origins=%s", cors_origins)


def _mount_health_routes(fastapi_app: Any) -> None:
    """Mount health check routes early to beat SPA catch-all."""
    from health_routes import router as _health_router
    _health_router_routes = list(_health_router.routes)
    for _route in reversed(_health_router_routes):
        fastapi_app.router.routes.insert(0, _route)
    logger.info("Health check routes mounted: /live, /ready, /metrics")


def _mount_admin_routes(fastapi_app: Any) -> None:
    """Mount admin API and API Services routes."""
    try:
        from chat_app.admin_api import (
            router as _admin_router,
            public_router as _admin_public_router,
            wellknown_router as _wellknown_router,
            config_router as _config_router,
            settings_router as _settings_router,
            tools_router as _tools_router,
            users_router as _users_router,
            security_router as _security_router,
            dashboard_router as _dashboard_router,
            pages_router as _pages_router,
            pages_public_router as _pages_public_router,
            interactive_tools_public_router as _itools_pub_router,
            interactive_tools_router as _itools_router,
            observability_router as _obs_router,
            skills_router as _skills_router,
            collections_router as _collections_router,
            learning_router as _learning_router,
            operations_router as _operations_router,
        )
        from chat_app.admin_config_helpers import config_ext_router as _config_ext_router
        from chat_app.admin_tools_routes_ext import tools_ext_router as _tools_ext_router
        from chat_app.admin_tools_routes_ext2 import tools_ext2_router as _tools_ext2_router
        from chat_app.admin_security_audit_routes import security_ext_router as _security_ext_router
        from chat_app.admin_security_infra_routes import security_infra_router as _security_infra_router
        from chat_app.admin_skills_orchestration_routes import skills_orch_router as _skills_orch_router
        from chat_app.admin_skills_workflow_routes import workflow_templates_router as _wf_templates_router
        from chat_app.admin_learning_ext_routes import learning_ext_router as _learning_ext_router
        from chat_app.admin_network_routes import network_router as _network_router
        from chat_app.admin_upgrade_routes import upgrade_router as _upgrade_router
        from chat_app.admin_upgrade_platform_routes import upgrade_platform_router as _upgrade_platform_router
        from chat_app.admin_data_sources_routes import data_sources_router as _data_sources_router

        _admin_routes = list(_admin_router.routes)
        _public_routes = list(_admin_public_router.routes)
        _wellknown_routes = list(_wellknown_router.routes)
        _sub_routes = (
            list(_config_router.routes) + list(_config_ext_router.routes) +
            list(_settings_router.routes) +
            list(_tools_router.routes) + list(_tools_ext_router.routes) +
            list(_tools_ext2_router.routes) + list(_users_router.routes) +
            list(_security_router.routes) + list(_security_ext_router.routes) +
            list(_security_infra_router.routes) + list(_dashboard_router.routes) +
            list(_operations_router.routes) +
            list(_itools_pub_router.routes) + list(_itools_router.routes) +
            list(_obs_router.routes) + list(_skills_router.routes) +
            list(_skills_orch_router.routes) + list(_wf_templates_router.routes) +
            list(_collections_router.routes) + list(_learning_router.routes) +
            list(_learning_ext_router.routes) +
            list(_network_router.routes) + list(_upgrade_router.routes) +
            list(_upgrade_platform_router.routes) +
            list(_data_sources_router.routes) +
            list(_pages_router.routes) + list(_pages_public_router.routes)
        )
        for _route in reversed(_admin_routes + _public_routes + _wellknown_routes + _sub_routes):
            fastapi_app.router.routes.insert(0, _route)
        logger.info(
            "Admin API routes mounted: /api/admin/* (%d routes, %d public, %d wellknown, %d sub-router)",
            len(_admin_routes), len(_public_routes), len(_wellknown_routes), len(_sub_routes),
        )

        # Mount API Services router for external consumers
        try:
            from chat_app.api_services import services_router as _svc_router
            _svc_routes = list(_svc_router.routes)
            for _route in reversed(_svc_routes):
                fastapi_app.router.routes.insert(0, _route)
            logger.info("API Services routes mounted: /api/v1/services/* (%d routes)", len(_svc_routes))
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _svc_exc:
            logger.debug("API Services mount skipped: %s", _svc_exc)

    except ImportError as _admin_exc:
        logger.info("Admin API not available (optional): %s", _admin_exc)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _admin_exc:
        logger.warning("Admin API mount warning (non-fatal): %s", _admin_exc)
