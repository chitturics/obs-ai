"""
API Services Layer — Expose ObsAI capabilities as REST API endpoints.

Allows external systems (Splunk custom commands, scripts, automation tools)
to consume ObsAI's analysis, generation, and knowledge capabilities via API.

Architecture:
    ServiceRegistry → ServiceDefinition → ServiceExecutor → Result
    ├── Role-based access control per service
    ├── Rate limiting per API key / role
    ├── Request/response validation via Pydantic
    ├── Usage tracking and audit logging
    └── Config-driven enable/disable (all disabled by default)

Usage from Splunk:
    | makeresults | eval apps=mvjoin(rest("/services/apps/local").title, ",")
    | eval result=httppost("https://obsai:8000/api/v1/services/splunkbase-check",
                           json_object("apps", apps))
"""
import time
from collections import defaultdict
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data structures and catalog — extracted to keep this file under 600 lines
# ---------------------------------------------------------------------------
from chat_app.api_services_types import (  # noqa: F401 — re-exported
    BulkSPLRequest,
    ServiceAccess,
    ServiceCategory,
    ServiceDefinition,
    ServiceRequest,
    ServiceResponse,
    SplunkbaseCheckRequest,
    _RateLimiter,
    _rate_limiter,
)
from chat_app.api_services_catalog import _build_service_catalog  # noqa: F401 — re-exported


# ---------------------------------------------------------------------------
# Service Executor
# ---------------------------------------------------------------------------

class ServiceExecutor:
    """Executes API service requests via the skill executor."""

    def __init__(self):
        self._services = _build_service_catalog()
        self._usage_log: List[Dict[str, Any]] = []
        self._config_overrides: Dict[str, bool] = {}  # service_id → enabled

    def get_service(self, service_id: str) -> Optional[ServiceDefinition]:
        svc = self._services.get(service_id)
        if svc and service_id in self._config_overrides:
            svc.enabled = self._config_overrides[service_id]
        return svc

    def get_catalog(self) -> List[Dict[str, Any]]:
        """Get the full service catalog."""
        result = []
        for svc in self._services.values():
            if svc.service_id in self._config_overrides:
                svc.enabled = self._config_overrides[svc.service_id]
            result.append(svc.to_dict())
        return sorted(result, key=lambda s: (s["category"], s["service_id"]))

    def enable_service(self, service_id: str) -> bool:
        if service_id in self._services:
            self._config_overrides[service_id] = True
            return True
        return False

    def disable_service(self, service_id: str) -> bool:
        if service_id in self._services:
            self._config_overrides[service_id] = False
            return True
        return False

    def get_enabled_services(self) -> List[str]:
        return [
            sid for sid, svc in self._services.items()
            if self._config_overrides.get(sid, svc.enabled)
        ]

    async def execute(
        self,
        service_id: str,
        request: ServiceRequest,
        caller_id: str = "anonymous",
        caller_role: str = "USER",
    ) -> ServiceResponse:
        """Execute a service request."""
        start = time.time()
        svc = self.get_service(service_id)

        if not svc:
            return ServiceResponse(
                success=False, service_id=service_id,
                error=f"Service '{service_id}' not found",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        # Check enabled
        is_enabled = self._config_overrides.get(service_id, svc.enabled)
        if not is_enabled:
            return ServiceResponse(
                success=False, service_id=service_id,
                error=f"Service '{service_id}' is disabled. Enable it in admin config.",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        # Check access level
        role_hierarchy = {"ADMIN": 4, "ANALYST": 3, "USER": 2, "VIEWER": 1}
        access_hierarchy = {"admin": 4, "analyst": 3, "user": 2, "public": 1}
        caller_level = role_hierarchy.get(caller_role.upper(), 1)
        required_level = access_hierarchy.get(svc.access_level.value, 2)
        if caller_level < required_level:
            return ServiceResponse(
                success=False, service_id=service_id,
                error=f"Access denied. Requires '{svc.access_level.value}' role.",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        # Rate limit
        if not _rate_limiter.check(f"{caller_id}:{service_id}", svc.rate_limit_per_minute):
            return ServiceResponse(
                success=False, service_id=service_id,
                error=f"Rate limit exceeded ({svc.rate_limit_per_minute}/min)",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

        # Execute via handler
        try:
            output = await self._dispatch(svc, request)
            duration_ms = (time.time() - start) * 1000

            self._log_usage(service_id, caller_id, caller_role, True, duration_ms)

            return ServiceResponse(
                success=True, service_id=service_id,
                output=output, duration_ms=round(duration_ms, 1),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        except asyncio.TimeoutError:
            duration_ms = (time.time() - start) * 1000
            self._log_usage(service_id, caller_id, caller_role, False, duration_ms)
            return ServiceResponse(
                success=False, service_id=service_id,
                error=f"Service timed out after {svc.timeout_seconds}s",
                duration_ms=round(duration_ms, 1),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            duration_ms = (time.time() - start) * 1000
            self._log_usage(service_id, caller_id, caller_role, False, duration_ms)
            return ServiceResponse(
                success=False, service_id=service_id,
                error=str(exc), duration_ms=round(duration_ms, 1),
                timestamp=datetime.now(timezone.utc).isoformat(),
            )

    async def _dispatch(self, svc: ServiceDefinition, request: ServiceRequest) -> Any:
        """Dispatch to the appropriate handler."""
        handler_key = svc.handler_key

        # Built-in custom handlers
        if handler_key == "_splunkbase_check":
            return await self._handle_splunkbase_check(request)
        elif handler_key == "_bulk_spl":
            return await self._handle_bulk_spl(request)
        elif handler_key == "_ingest_trigger":
            return await self._handle_ingest_trigger(request)
        elif handler_key == "_evolution_assess":
            return await self._handle_evolution_assess(request)

        # Delegate to skill executor
        try:
            from chat_app.skill_executor import get_skill_executor
            executor = get_skill_executor()

            # Determine which parameter key the handler expects
            # Tool registry tools use 'query'; internal handlers use 'user_input'
            source, _ = executor.resolve_handler(handler_key)
            params = {**request.params}

            if source == "tool_registry":
                # Tool registry tools have strict signatures — only pass 'query'
                params = {"query": request.input, **request.params}
            else:
                # Internal handlers accept user_input and other flexible params
                if request.input:
                    params["user_input"] = request.input
                    params["query"] = request.input
                    params["spl"] = request.input
                    params["input"] = request.input

            result = await asyncio.wait_for(
                executor.execute(handler_key=handler_key, params=params),
                timeout=svc.timeout_seconds,
            )

            if result.success:
                return result.output
            else:
                raise Exception(result.error or "Execution failed")
        except asyncio.TimeoutError:
            raise
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            raise Exception(f"Handler '{handler_key}' failed: {exc}")

    async def _handle_splunkbase_check(self, request: ServiceRequest) -> Dict[str, Any]:
        """Check Splunkbase for outdated apps."""
        apps = request.params.get("apps", [])
        if not apps:
            raise ValueError("No apps provided. Send {'params': {'apps': [{'name': '...', 'version': '...'}]}}")

        results = []
        for app in apps:
            app_name = app.get("name", "")
            installed_version = app.get("version", "unknown")
            # Try to check against our catalog
            try:
                from chat_app.splunkbase_catalog import get_splunkbase_catalog
                catalog = get_splunkbase_catalog()
                info = catalog.get_app_info(app_name) if hasattr(catalog, 'get_app_info') else None
                if info:
                    latest = info.get("latest_version", "unknown")
                    is_outdated = installed_version != "unknown" and latest != "unknown" and installed_version < latest
                    results.append({
                        "name": app_name,
                        "installed_version": installed_version,
                        "latest_version": latest,
                        "outdated": is_outdated,
                        "description": info.get("description", ""),
                    })
                else:
                    results.append({
                        "name": app_name,
                        "installed_version": installed_version,
                        "latest_version": "not_found",
                        "outdated": False,
                        "description": "App not found in Splunkbase catalog",
                    })
            except Exception as _exc:  # broad catch — resilience against all failures
                results.append({
                    "name": app_name,
                    "installed_version": installed_version,
                    "latest_version": "check_failed",
                    "outdated": False,
                })

        outdated_count = sum(1 for r in results if r.get("outdated"))
        return {
            "total_apps": len(results),
            "outdated": outdated_count,
            "up_to_date": len(results) - outdated_count,
            "results": results,
        }

    async def _handle_bulk_spl(self, request: ServiceRequest) -> Dict[str, Any]:
        """Handle bulk SPL analysis."""
        queries = request.params.get("queries", [])
        action = request.params.get("action", "validate")

        if not queries:
            raise ValueError("No queries provided")

        results = []
        for query in queries[:50]:  # Cap at 50
            try:
                from chat_app.skill_executor import get_skill_executor
                executor = get_skill_executor()
                handler_map = {"validate": "validate_spl", "optimize": "optimize_spl",
                              "explain": "explain_spl", "analyze": "analyze_spl"}
                handler_key = handler_map.get(action, "validate_spl")
                # Tool registry tools only accept 'query'
                source, _ = executor.resolve_handler(handler_key)
                if source == "tool_registry":
                    exec_params = {"query": query}
                else:
                    exec_params = {"user_input": query, "query": query, "spl": query}
                result = await executor.execute(
                    handler_key=handler_key,
                    params=exec_params,
                )
                results.append({
                    "query": query[:200],
                    "action": action,
                    "success": result.success,
                    "output": result.output if result.success else result.error,
                })
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                results.append({"query": query[:200], "action": action, "success": False, "output": str(exc)})

        return {"total": len(results), "successful": sum(1 for r in results if r["success"]), "results": results}

    async def _handle_ingest_trigger(self, request: ServiceRequest) -> Dict[str, Any]:
        """Trigger document ingestion (sandboxed to allowed directories)."""
        directory = request.params.get("directory")
        if directory:
            from pathlib import Path
            resolved = Path(directory).resolve()
            allowed = Path("/app/shared/public/documents").resolve()
            if not str(resolved).startswith(str(allowed)):
                return {"status": "failed", "error": f"Directory must be under {allowed}"}
        try:
            from chat_app.run_quick_ingest import run_ingestion
            result = await run_ingestion(directory=directory)
            return {"status": "completed", "result": str(result)}
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            return {"status": "failed", "error": str(exc)}

    async def _handle_evolution_assess(self, request: ServiceRequest) -> Dict[str, Any]:
        """Run evolution assessment."""
        from chat_app.evolution_engine import get_evolution_engine
        return await get_evolution_engine().run_assessment()

    def _log_usage(self, service_id: str, caller_id: str, role: str, success: bool, duration_ms: float):
        """Log API service usage."""
        self._usage_log.append({
            "service_id": service_id,
            "caller_id": caller_id,
            "role": role,
            "success": success,
            "duration_ms": round(duration_ms, 1),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        # Keep last 1000
        if len(self._usage_log) > 1000:
            self._usage_log = self._usage_log[-1000:]

    def get_usage_stats(self) -> Dict[str, Any]:
        """Get usage statistics."""
        if not self._usage_log:
            return {"total_calls": 0, "by_service": {}}

        by_service = defaultdict(lambda: {"calls": 0, "success": 0, "avg_ms": 0, "total_ms": 0})
        for entry in self._usage_log:
            sid = entry["service_id"]
            by_service[sid]["calls"] += 1
            if entry["success"]:
                by_service[sid]["success"] += 1
            by_service[sid]["total_ms"] += entry["duration_ms"]

        for sid, stats in by_service.items():
            stats["avg_ms"] = round(stats["total_ms"] / max(stats["calls"], 1), 1)
            stats["success_rate"] = round(stats["success"] / max(stats["calls"], 1), 3)
            del stats["total_ms"]

        return {
            "total_calls": len(self._usage_log),
            "unique_callers": len(set(e["caller_id"] for e in self._usage_log)),
            "by_service": dict(by_service),
            "recent": self._usage_log[-20:],
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_executor: Optional[ServiceExecutor] = None


def get_service_executor() -> ServiceExecutor:
    global _executor
    if _executor is None:
        _executor = ServiceExecutor()
    return _executor


# ---------------------------------------------------------------------------
# FastAPI Router
# ---------------------------------------------------------------------------

from chat_app.auth_dependencies import require_admin

services_router = APIRouter(
    prefix="/api/v1/services",
    tags=["API Services"],
    dependencies=[Depends(require_admin)],
)


@services_router.get("/catalog", summary="List all available API services")
async def get_service_catalog():
    """Get the complete catalog of available API services with schemas and examples."""
    executor = get_service_executor()
    catalog = executor.get_catalog()
    enabled = executor.get_enabled_services()
    return {
        "total_services": len(catalog),
        "enabled_count": len(enabled),
        "services": catalog,
    }


@services_router.get("/enabled", summary="List enabled services")
async def get_enabled_services():
    """Get only the currently enabled services."""
    executor = get_service_executor()
    enabled_ids = executor.get_enabled_services()
    catalog = executor.get_catalog()
    return {
        "enabled": [s for s in catalog if s["service_id"] in enabled_ids],
        "count": len(enabled_ids),
    }


@services_router.post("/manage/{service_id}", summary="Enable or disable a service")
async def manage_service(service_id: str, action: str = "enable"):
    """Enable or disable an API service. Requires ADMIN role."""
    executor = get_service_executor()
    if action == "enable":
        ok = executor.enable_service(service_id)
    elif action == "disable":
        ok = executor.disable_service(service_id)
    else:
        return {"error": f"Unknown action: {action}. Use 'enable' or 'disable'."}

    if not ok:
        return {"error": f"Service '{service_id}' not found"}

    return {
        "service_id": service_id,
        "action": action,
        "success": True,
        "enabled_services": executor.get_enabled_services(),
    }


@services_router.get("/usage", summary="API service usage statistics")
async def get_usage_stats():
    """Get usage statistics for all API services."""
    return get_service_executor().get_usage_stats()


@services_router.post("/{service_id}", summary="Execute an API service")
async def execute_service(service_id: str, request: ServiceRequest, req: Request):
    """
    Execute an API service by ID.

    Send the input and parameters matching the service's schema.
    Check /api/v1/services/catalog for available services and their schemas.
    """
    # Extract caller info from request
    caller_id = "anonymous"
    caller_role = "USER"  # Default to least privilege

    try:
        from chat_app.auth_dependencies import get_authenticated_user
        user = await get_authenticated_user(req)
        if user:
            caller_id = getattr(user, 'identifier', 'unknown')
            metadata = getattr(user, 'metadata', {}) or {}
            caller_role = metadata.get('role', 'USER')
    except Exception as _exc:  # broad catch — resilience against all failures
        pass  # Fall back to default

    executor = get_service_executor()
    response = await executor.execute(service_id, request, caller_id, caller_role)
    status_code = 200 if response.success else 400
    return JSONResponse(content=response.model_dump(), status_code=status_code)


@services_router.post("/{service_id}/test", summary="Test a service with example input")
async def test_service(service_id: str, req: Request):
    """Test a service using its built-in example input."""
    executor = get_service_executor()
    svc = executor.get_service(service_id)
    if not svc:
        return {"error": f"Service '{service_id}' not found"}

    # Use example input
    example = svc.example_input or {}
    request = ServiceRequest(
        input=example.get("input", ""),
        params=example.get("params", {}),
    )

    response = await executor.execute(service_id, request, "test_user", "ADMIN")
    return {
        "service_id": service_id,
        "test_input": example,
        "result": response.model_dump(),
    }
