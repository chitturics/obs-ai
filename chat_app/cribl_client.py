"""
Cribl Stream REST API client.

Provides async methods for:
- Authentication and health checks
- Pipeline CRUD and validation
- Route management
- Pack operations
- Worker group management and deployment
- Event breaker rules
- Source and destination management
- System info, metrics, and licenses

Uses httpx for async HTTP with retry logic, token refresh,
structured logging, and error classification.
"""
from __future__ import annotations

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Dict, List, Optional

import httpx

from chat_app.settings import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


class CriblErrorKind(str, Enum):
    """Classified API error types."""
    AUTH = "auth"
    NOT_FOUND = "not_found"
    VALIDATION = "validation"
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    UNKNOWN = "unknown"


class CriblAPIError(Exception):
    """Raised when a Cribl API call fails."""

    def __init__(self, message: str, kind: CriblErrorKind = CriblErrorKind.UNKNOWN,
                 status_code: int = 0, response_body: str = ""):
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.response_body = response_body


def _classify_error(status_code: int) -> CriblErrorKind:
    """Map HTTP status to error kind."""
    if status_code in (401, 403):
        return CriblErrorKind.AUTH
    if status_code == 404:
        return CriblErrorKind.NOT_FOUND
    if status_code in (400, 422):
        return CriblErrorKind.VALIDATION
    if status_code >= 500:
        return CriblErrorKind.SERVER_ERROR
    return CriblErrorKind.UNKNOWN


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class CriblClient:
    """Async client for the Cribl Stream REST API.

    Supports bearer-token auth and username/password login.
    All group-scoped endpoints default to the ``default`` worker group.
    """

    _MAX_RETRIES = 3
    _RETRY_BACKOFF = 1.0  # seconds, doubles each attempt
    _RETRYABLE_STATUSES = frozenset({502, 503, 504, 429})

    def __init__(
        self,
        base_url: str,
        auth_token: str = "",
        username: str = "",
        password: str = "",
        verify_ssl: bool = True,
        default_group: str = "default",
        timeout: float = 30.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._api = f"{self._base_url}/api/v1"
        self._token = auth_token
        self._username = username
        self._password = password
        self._default_group = default_group
        self._token_expires: float = 0.0
        self._session = httpx.AsyncClient(
            verify=verify_ssl,
            timeout=httpx.Timeout(timeout, connect=10.0),
            follow_redirects=True,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _headers(self) -> Dict[str, str]:
        headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def _ensure_token(self) -> None:
        """Authenticate if no token or token is near expiry."""
        if self._token and time.time() < self._token_expires - 60:
            return
        if self._username and self._password:
            await self.authenticate()
        elif not self._token:
            raise CriblAPIError("No auth credentials configured", CriblErrorKind.AUTH)

    async def _request(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        """Make an authenticated API request with retry logic.

        Returns the parsed JSON response body.  Raises ``CriblAPIError``
        on non-2xx responses after exhausting retries.
        """
        await self._ensure_token()
        url = f"{self._api}{path}"
        last_exc: Optional[Exception] = None

        for attempt in range(1, self._MAX_RETRIES + 1):
            try:
                resp = await self._session.request(
                    method, url, headers=self._headers(), **kwargs,
                )
                if resp.status_code < 300:
                    if resp.status_code == 204:
                        return {}
                    return resp.json()  # type: ignore[no-any-return]

                # Token expired — refresh once
                if resp.status_code in (401, 403) and attempt == 1 and self._username:
                    logger.info("Token rejected, refreshing")
                    await self.authenticate()
                    continue

                # Retry on transient failures
                if resp.status_code in self._RETRYABLE_STATUSES and attempt < self._MAX_RETRIES:
                    wait = self._RETRY_BACKOFF * (2 ** (attempt - 1))
                    logger.warning("Cribl API %s %s returned %s, retry %d in %.1fs",
                                   method, path, resp.status_code, attempt, wait)
                    await asyncio.sleep(wait)
                    continue

                kind = _classify_error(resp.status_code)
                body = resp.text[:500]
                raise CriblAPIError(
                    f"{method} {path} -> {resp.status_code}: {body}",
                    kind=kind, status_code=resp.status_code, response_body=body,
                )

            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt < self._MAX_RETRIES:
                    logger.warning("Timeout on %s %s (attempt %d)", method, path, attempt)
                    continue
                raise CriblAPIError(f"Timeout: {exc}", CriblErrorKind.TIMEOUT) from exc

            except httpx.ConnectError as exc:
                raise CriblAPIError(f"Connection failed: {exc}", CriblErrorKind.CONNECTION) from exc

            except CriblAPIError:
                raise

            except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as exc:
                last_exc = exc
                if attempt < self._MAX_RETRIES:
                    continue
                raise CriblAPIError(f"Unexpected: {exc}", CriblErrorKind.UNKNOWN) from exc

        raise CriblAPIError(f"Exhausted retries: {last_exc}", CriblErrorKind.UNKNOWN)

    # ------------------------------------------------------------------
    # Auth & health
    # ------------------------------------------------------------------

    async def authenticate(self) -> bool:
        """Authenticate via username/password and store bearer token."""
        if not self._username or not self._password:
            raise CriblAPIError("Username/password not configured", CriblErrorKind.AUTH)
        try:
            resp = await self._session.post(
                f"{self._api}/auth/login",
                json={"username": self._username, "password": self._password},
                headers={"Content-Type": "application/json"},
            )
            if resp.status_code >= 300:
                raise CriblAPIError(
                    f"Auth failed: {resp.status_code}", CriblErrorKind.AUTH,
                    status_code=resp.status_code,
                )
            data = resp.json()
            self._token = data.get("token", "")
            # Cribl tokens typically last 24h; assume 23h to be safe
            self._token_expires = time.time() + 23 * 3600
            logger.info("Authenticated to Cribl at %s", self._base_url)
            return True
        except CriblAPIError:
            raise
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            raise CriblAPIError(f"Auth request failed: {exc}", CriblErrorKind.CONNECTION) from exc

    async def health_check(self) -> Dict[str, Any]:
        """Check Cribl API health (unauthenticated)."""
        try:
            resp = await self._session.get(
                f"{self._api}/health", headers={"Accept": "application/json"},
            )
            return {"status": "healthy" if resp.status_code < 300 else "unhealthy",
                    "status_code": resp.status_code}
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            return {"status": "unreachable", "error": str(exc)}

    # ------------------------------------------------------------------
    # Pipelines
    # ------------------------------------------------------------------

    async def list_pipelines(self, group: str = "") -> List[Dict[str, Any]]:
        """List all pipelines in a worker group."""
        g = group or self._default_group
        data = await self._request("GET", f"/m/{g}/pipelines")
        return data.get("items", [])

    async def get_pipeline(self, pipeline_id: str, group: str = "") -> Dict[str, Any]:
        """Get pipeline configuration including functions."""
        g = group or self._default_group
        return await self._request("GET", f"/m/{g}/pipelines/{pipeline_id}")

    async def create_pipeline(self, pipeline_id: str, config: Dict[str, Any],
                              group: str = "") -> Dict[str, Any]:
        """Create a new pipeline."""
        g = group or self._default_group
        config.setdefault("id", pipeline_id)
        return await self._request("PUT", f"/m/{g}/pipelines/{pipeline_id}", json=config)

    async def update_pipeline(self, pipeline_id: str, config: Dict[str, Any],
                              group: str = "") -> Dict[str, Any]:
        """Update an existing pipeline configuration."""
        g = group or self._default_group
        return await self._request("PATCH", f"/m/{g}/pipelines/{pipeline_id}", json=config)

    async def delete_pipeline(self, pipeline_id: str, group: str = "") -> bool:
        """Delete a pipeline. Returns True on success."""
        g = group or self._default_group
        await self._request("DELETE", f"/m/{g}/pipelines/{pipeline_id}")
        return True

    async def validate_pipeline(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """Validate pipeline configuration without saving."""
        return await self._request("POST", "/pipelines/validate", json=config)

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    async def list_routes(self, group: str = "") -> List[Dict[str, Any]]:
        """List all routes in a worker group."""
        g = group or self._default_group
        data = await self._request("GET", f"/m/{g}/routes")
        return data.get("items", data.get("routes", []))

    async def get_route(self, route_id: str, group: str = "") -> Dict[str, Any]:
        """Get a specific route."""
        g = group or self._default_group
        return await self._request("GET", f"/m/{g}/routes/{route_id}")

    async def create_route(self, config: Dict[str, Any], group: str = "") -> Dict[str, Any]:
        """Create a new route."""
        g = group or self._default_group
        return await self._request("POST", f"/m/{g}/routes", json=config)

    async def update_route(self, route_id: str, config: Dict[str, Any],
                           group: str = "") -> Dict[str, Any]:
        """Update an existing route."""
        g = group or self._default_group
        return await self._request("PATCH", f"/m/{g}/routes/{route_id}", json=config)

    # ------------------------------------------------------------------
    # Packs
    # ------------------------------------------------------------------

    async def list_packs(self) -> List[Dict[str, Any]]:
        """List installed packs."""
        data = await self._request("GET", "/packs")
        return data.get("items", [])

    async def get_pack(self, pack_id: str) -> Dict[str, Any]:
        """Get details for a specific pack."""
        return await self._request("GET", f"/packs/{pack_id}")

    async def install_pack(self, pack_id: str, source: str) -> Dict[str, Any]:
        """Install a pack from a source (URL or registry reference)."""
        return await self._request("POST", "/packs", json={"id": pack_id, "source": source})

    # ------------------------------------------------------------------
    # Worker groups
    # ------------------------------------------------------------------

    async def list_groups(self) -> List[Dict[str, Any]]:
        """List all worker groups (leader-mode only)."""
        data = await self._request("GET", "/master/groups")
        return data.get("items", [])

    async def get_group(self, group_id: str) -> Dict[str, Any]:
        """Get worker group details."""
        return await self._request("GET", f"/master/groups/{group_id}")

    async def deploy(self, group: str = "") -> Dict[str, Any]:
        """Deploy current configuration to a worker group."""
        g = group or self._default_group
        return await self._request("PATCH", f"/master/groups/{g}/deploy")

    async def get_deploy_status(self, group: str = "") -> Dict[str, Any]:
        """Get deployment status for a worker group."""
        g = group or self._default_group
        return await self._request("GET", f"/master/groups/{g}/deployStatus")

    # ------------------------------------------------------------------
    # Event breaker rules
    # ------------------------------------------------------------------

    async def list_event_breaker_rules(self, group: str = "") -> List[Dict[str, Any]]:
        """List event breaker rulesets."""
        g = group or self._default_group
        data = await self._request("GET", f"/m/{g}/breakers")
        return data.get("items", [])

    async def get_event_breaker_rule(self, rule_id: str, group: str = "") -> Dict[str, Any]:
        """Get a specific event breaker ruleset."""
        g = group or self._default_group
        return await self._request("GET", f"/m/{g}/breakers/{rule_id}")

    async def create_event_breaker_rule(self, config: Dict[str, Any],
                                        group: str = "") -> Dict[str, Any]:
        """Create a new event breaker ruleset."""
        g = group or self._default_group
        return await self._request("POST", f"/m/{g}/breakers", json=config)

    # ------------------------------------------------------------------
    # Sources & destinations
    # ------------------------------------------------------------------

    async def list_sources(self, group: str = "") -> List[Dict[str, Any]]:
        """List all input sources."""
        g = group or self._default_group
        data = await self._request("GET", f"/m/{g}/inputs")
        return data.get("items", [])

    async def get_source(self, source_id: str, group: str = "") -> Dict[str, Any]:
        """Get a specific input source."""
        g = group or self._default_group
        return await self._request("GET", f"/m/{g}/inputs/{source_id}")

    async def list_destinations(self, group: str = "") -> List[Dict[str, Any]]:
        """List all output destinations."""
        g = group or self._default_group
        data = await self._request("GET", f"/m/{g}/outputs")
        return data.get("items", [])

    async def get_destination(self, dest_id: str, group: str = "") -> Dict[str, Any]:
        """Get a specific output destination."""
        g = group or self._default_group
        return await self._request("GET", f"/m/{g}/outputs/{dest_id}")

    # ------------------------------------------------------------------
    # System
    # ------------------------------------------------------------------

    async def get_system_info(self) -> Dict[str, Any]:
        """Get Cribl system information."""
        return await self._request("GET", "/system/info")

    async def get_metrics(self) -> Dict[str, Any]:
        """Get Cribl internal metrics summary."""
        return await self._request("GET", "/system/metrics")

    async def get_licenses(self) -> Dict[str, Any]:
        """Get license information."""
        return await self._request("GET", "/system/licenses")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        await self._session.aclose()

    async def __aenter__(self) -> "CriblClient":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_client: Optional[CriblClient] = None


def get_cribl_client() -> Optional[CriblClient]:
    """Return the Cribl client singleton, or ``None`` if not configured.

    Reads connection settings from ``get_settings().cribl``.
    """
    global _client
    if _client is not None:
        return _client

    cfg = get_settings().cribl
    if not cfg.base_url:
        return None

    _client = CriblClient(
        base_url=cfg.base_url,
        auth_token=cfg.auth_token,
        username=cfg.username,
        password=cfg.password,
        verify_ssl=cfg.verify_ssl,
        default_group=cfg.default_group,
    )
    logger.info("Initialized Cribl client for %s", cfg.base_url)
    return _client
