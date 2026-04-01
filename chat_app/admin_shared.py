"""Shared helpers for admin API sub-routers.

This module extracts common utilities used across admin_api.py and its
sub-routers so they can be imported without circular dependencies.

Provides:
- _arun() — async subprocess execution
- _safe_error() — standardised error logging/response
- _now_iso() — UTC ISO-8601 timestamp
- _append_audit() — audit trail helper
- _validate_password_complexity() — password validation
- Container runtime helpers (_container_cmd, _compose_cmd, _compose_dir)
- Rate limiter and CSRF middleware
- In-memory stores (audit trail, feature flags, activity tracking)
- Pydantic request models shared across sub-routers
"""

import asyncio
import contextvars
import logging
import os
import shutil
import subprocess
import time
import uuid

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from chat_app.settings import get_settings
from chat_app.auth_dependencies import get_authenticated_user

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Async subprocess runner
# ---------------------------------------------------------------------------

async def _arun(cmd, **kwargs):
    """Run subprocess asynchronously to avoid blocking the event loop."""
    return await asyncio.to_thread(subprocess.run, cmd, **kwargs)


# ---------------------------------------------------------------------------
# Safe error logging
# ---------------------------------------------------------------------------

def _safe_error(exc: Exception, context: str = "operation") -> str:
    """Return a generic error message for HTTP responses, log the real error server-side."""
    logger.error("[ADMIN] %s failed: %s", context, exc, exc_info=True)
    return f"Internal error during {context}. Check server logs for details."


def _error_response(
    code: str,
    message: str,
    status_code: int = 500,
    details: Optional[Dict[str, Any]] = None,
) -> None:
    """Raise an HTTPException with standardized error body.

    Response format:
        {"error": {"code": "ERROR_CODE", "message": "...", "details": {...}}}

    Usage:
        _error_response("VALIDATION_ERROR", "Field 'name' is required", 422, {"field": "name"})
    """
    error_body: Dict[str, Any] = {"code": code, "message": message}
    if details:
        error_body["details"] = details
    raise HTTPException(status_code=status_code, detail={"error": error_body})


# ---------------------------------------------------------------------------
# Timestamp helper
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Password validation
# ---------------------------------------------------------------------------

def _validate_password_complexity(password: str) -> None:
    """Validate password meets complexity requirements. Raises HTTPException on failure."""
    import re as _pwd_re

    if len(password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")
    if not _pwd_re.search(r'[A-Z]', password):
        raise HTTPException(status_code=400, detail="Password must contain at least one uppercase letter")
    if not _pwd_re.search(r'[a-z]', password):
        raise HTTPException(status_code=400, detail="Password must contain at least one lowercase letter")
    if not _pwd_re.search(r'[0-9]', password):
        raise HTTPException(status_code=400, detail="Password must contain at least one digit")


# ---------------------------------------------------------------------------
# Audit trail context variable
# ---------------------------------------------------------------------------

_current_audit_user: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "_current_audit_user", default=None
)


async def _track_audit_user(request: Request):
    """Set the current user in context for audit trail entries."""
    try:
        user = await get_authenticated_user(request)
        _current_audit_user.set(user.get("identifier"))
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[AUDIT] Could not resolve audit user: %s: %s", type(exc).__name__, exc)


# ---------------------------------------------------------------------------
# In-memory rate limiter (sliding window, per-IP, no external dependencies)
# ---------------------------------------------------------------------------

_RATE_LIMIT_MAX_REQUESTS = 300  # max requests per window (admin UI loads multiple API calls per page)
_RATE_LIMIT_WINDOW_SECONDS = 60  # sliding window size

# In-memory fallback store (used when Redis is unavailable)
_rate_limit_store: Dict[str, List[float]] = {}

# Redis client for distributed rate limiting (initialized lazily)
_redis_rate_limiter = None
_redis_rate_limit_checked = False


def _get_redis_for_rate_limit():
    """Get Redis client for rate limiting. Returns None if unavailable."""
    global _redis_rate_limiter, _redis_rate_limit_checked
    if _redis_rate_limit_checked:
        return _redis_rate_limiter
    _redis_rate_limit_checked = True
    try:
        from chat_app.settings import get_settings
        cache_settings = get_settings().cache
        if cache_settings.enabled:
            import redis
            _redis_rate_limiter = redis.Redis(
                host=cache_settings.host,
                port=cache_settings.port,
                password=cache_settings.password or None,
                db=1,  # Separate DB from main cache
                decode_responses=True,
                socket_connect_timeout=2,
            )
            _redis_rate_limiter.ping()
            return _redis_rate_limiter
    except Exception as _exc:  # broad catch — resilience against all failures
        _redis_rate_limiter = None
    return None


def _get_client_ip(request: Request) -> str:
    """Extract client IP from request, respecting X-Forwarded-For behind proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


async def _rate_limit(request: Request):
    """Enforce per-IP rate limiting (sliding window, 60 req/min).

    Uses Redis when available (distributed, survives restarts).
    Falls back to in-memory dict (single instance only).
    Returns Retry-After header on 429.
    """
    client_ip = _get_client_ip(request)
    rate_limit_key = f"rl:{client_ip}"

    # --- Redis path (distributed, production-ready) ---
    redis_client = _get_redis_for_rate_limit()
    if redis_client is not None:
        try:
            pipe = redis_client.pipeline()
            now_ms = int(time.time() * 1000)
            window_start_ms = now_ms - (_RATE_LIMIT_WINDOW_SECONDS * 1000)

            # Sorted set: score=timestamp_ms, member=timestamp_ms (unique per request)
            pipe.zremrangebyscore(rate_limit_key, 0, window_start_ms)
            pipe.zcard(rate_limit_key)
            pipe.zadd(rate_limit_key, {str(now_ms): now_ms})
            pipe.expire(rate_limit_key, _RATE_LIMIT_WINDOW_SECONDS + 1)
            results = pipe.execute()

            request_count = results[1]  # zcard result
            if request_count >= _RATE_LIMIT_MAX_REQUESTS:
                # Get oldest entry to calculate retry-after
                oldest = redis_client.zrange(rate_limit_key, 0, 0, withscores=True)
                retry_after = 1
                if oldest:
                    oldest_ms = int(oldest[0][1])
                    retry_after = max(1, int((oldest_ms + _RATE_LIMIT_WINDOW_SECONDS * 1000 - now_ms) / 1000) + 1)
                raise HTTPException(
                    status_code=429,
                    detail="Rate limit exceeded. Try again later.",
                    headers={"Retry-After": str(retry_after)},
                )
            return  # Allowed
        except HTTPException:
            raise
        except Exception as _exc:  # broad catch — resilience against all failures
            pass  # Redis failed, fall through to in-memory

    # --- In-memory fallback (single instance) ---
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW_SECONDS

    timestamps = _rate_limit_store.get(client_ip)
    if timestamps is None:
        timestamps = []
        _rate_limit_store[client_ip] = timestamps

    while timestamps and timestamps[0] <= window_start:
        timestamps.pop(0)

    if len(timestamps) >= _RATE_LIMIT_MAX_REQUESTS:
        retry_after = int(timestamps[0] - window_start) + 1
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    timestamps.append(now)

    # Housekeeping: purge stale IPs when store grows large
    # Runs on every 50th unique IP or when store exceeds 500 entries (hard cap)
    store_size = len(_rate_limit_store)
    if (len(timestamps) == 1 and store_size > 100) or store_size > 500:
        stale_ips = [
            ip for ip, ts in _rate_limit_store.items()
            if not ts or ts[-1] <= window_start
        ]
        for ip in stale_ips:
            del _rate_limit_store[ip]


# ---------------------------------------------------------------------------
# CSRF protection
# ---------------------------------------------------------------------------

async def _csrf_check(request: Request):
    """Reject cross-origin mutating requests (CSRF protection).

    Allows same-origin and localhost requests.  Compares hostnames only
    (ignoring port) because nginx reverse-proxy changes the port between
    the public gateway (e.g. 8000) and the internal app (8090).
    """
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    origin = request.headers.get("origin", "")
    referer = request.headers.get("referer", "")
    host = request.headers.get("host", "")
    # Allow non-browser clients (curl, API tools, internal services)
    if not origin and not referer:
        return
    # Allow requests with API key header (authenticated programmatic access)
    if request.headers.get("x-api-key"):
        return

    _LOCALHOST = ("localhost", "127.0.0.1", "::1", "[::1]")

    def _extract_hostname(url_or_host: str) -> str:
        """Extract hostname without port from a URL or host:port string."""
        from urllib.parse import urlparse
        if "://" in url_or_host:
            parsed = urlparse(url_or_host)
            return (parsed.hostname or "").lower()
        # host:port format
        h = url_or_host.rsplit(":", 1)[0] if ":" in url_or_host and not url_or_host.startswith("[") else url_or_host
        return h.strip("[]").lower()

    host_name = _extract_hostname(host)

    source = origin or referer
    source_name = _extract_hostname(source)

    # Same hostname (ignoring port — nginx proxies change ports)
    if source_name == host_name:
        return
    # Both are localhost variants (covers 127.0.0.1 vs localhost vs ::1)
    if source_name in _LOCALHOST and host_name in _LOCALHOST:
        return
    # Source is localhost, host is empty (direct container access without Host header)
    if source_name in _LOCALHOST and not host_name:
        return

    raise HTTPException(status_code=403, detail=f"CSRF check failed: origin '{source_name}' does not match host '{host_name}'")


# ---------------------------------------------------------------------------
# In-memory stores
# ---------------------------------------------------------------------------

# Audit trail of configuration changes (list of dicts, most recent last).
_config_audit_trail: List[Dict[str, Any]] = []

# Feature flags with runtime overrides.  Initialised lazily from config.yaml
# the first time the flags endpoint is hit, then mutated in-memory.
_feature_flags: Optional[Dict[str, bool]] = None

# Activity tracking: recent queries and intent distribution.
_recent_queries: List[Dict[str, Any]] = []
_intent_counts: Dict[str, int] = {}
_query_volume: List[Dict[str, Any]] = []  # [{timestamp, count}] per-minute buckets
_collection_hit_counts: Dict[str, int] = {}  # per-collection usage tracking

# In-memory feature requests
_feature_requests: List[Dict[str, Any]] = []

# Maximum items retained in memory.
_MAX_AUDIT_ENTRIES = 500
_MAX_RECENT_QUERIES = 200
_MAX_VOLUME_BUCKETS = 1440  # 24 hours of per-minute buckets


def _compute_diff(old: Dict[str, Any], new: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Compute structured diff between old and new config values.

    Returns a list of per-key change records:
        [{"key": "model", "old": "llama2", "new": "llama3", "action": "modified"}, ...]
    """
    diffs: List[Dict[str, Any]] = []
    all_keys = set(list(old.keys()) + list(new.keys()))
    for key in sorted(all_keys):
        old_val = old.get(key)
        new_val = new.get(key)
        if old_val != new_val:
            if key in old and key in new:
                diff_action = "modified"
            elif key not in old:
                diff_action = "added"
            else:
                diff_action = "removed"
            diffs.append({
                "key": key,
                "old": old_val,
                "new": new_val,
                "action": diff_action,
            })
    return diffs


def _append_audit(
    section: str,
    action: str,
    changes: Dict[str, Any],
    previous: Optional[Dict[str, Any]] = None,
    user: Optional[str] = None,
) -> Dict[str, Any]:
    """Append an entry to the configuration audit trail and return it.

    When *previous* is provided, a structured diff is computed automatically
    so consumers can inspect exactly which keys changed and how.

    Entries are written to both:
    - In-memory deque (fast query, capped at _MAX_AUDIT_ENTRIES)
    - Immutable audit log (file-persisted, hash-chained, tamper-evident)
    """
    if user is None:
        user = _current_audit_user.get(None)
    diff = _compute_diff(previous, changes) if previous else None
    entry = {
        "id": str(uuid.uuid4()),
        "timestamp": _now_iso(),
        "section": section,
        "action": action,
        "changes": changes,
        "previous": previous,
        "user": user,
        "diff": diff,
    }
    _config_audit_trail.append(entry)
    # Trim oldest entries to keep memory bounded.
    if len(_config_audit_trail) > _MAX_AUDIT_ENTRIES:
        del _config_audit_trail[: len(_config_audit_trail) - _MAX_AUDIT_ENTRIES]

    # Record to immutable audit log (hash-chained, file-persisted)
    try:
        from chat_app.audit_log import get_audit_log
        get_audit_log().append(
            event_type="config_change",
            actor=user or "system",
            action=action,
            target=section,
            details={"diff": diff} if diff else {"changes": changes},
            severity="medium" if action in ("update", "delete") else "low",
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[AUDIT] Immutable log write failed: %s", exc)

    # Record to unified activity timeline
    try:
        from chat_app.activity_timeline import get_timeline
        get_timeline().record(
            event_type="config_change",
            actor=user or "system",
            action=action,
            target=section,
            details={"diff": diff} if diff else {"changes": changes},
            status="ok",
        )
    except Exception as _exc:  # broad catch — resilience against all failures
        pass  # Timeline is best-effort; never break audit

    return entry


# ---------------------------------------------------------------------------
# Container runtime helpers
# ---------------------------------------------------------------------------

_PROJECT_ROOT_ADMIN = Path(__file__).resolve().parent.parent


_CACHED_CONTAINER_CMD: Optional[str] = None
_CONTAINER_CMD_CHECKED = False


def _container_cmd() -> Optional[str]:
    """Auto-detect a *working* container runtime: prefer podman, fall back to docker.
    Returns None if neither CLI is available or neither daemon is reachable.
    Result is cached after first successful check. Retries on failure
    (socket may not be ready at startup)."""
    global _CACHED_CONTAINER_CMD, _CONTAINER_CMD_CHECKED
    # If we found a runtime, return it (permanent cache)
    if _CACHED_CONTAINER_CMD is not None:
        return _CACHED_CONTAINER_CMD
    # If we already checked and found nothing, retry up to 3 times total
    # (docker socket might mount after app starts)
    if _CONTAINER_CMD_CHECKED:
        # Allow retry by not returning immediately
        pass
    _CONTAINER_CMD_CHECKED = True
    for cmd in ("docker", "podman"):
        if not shutil.which(cmd):
            continue
        try:
            r = subprocess.run(
                [cmd, "ps", "--format", "{{.Names}}"],
                capture_output=True, timeout=3,
            )
            if r.returncode == 0:
                _CACHED_CONTAINER_CMD = cmd
                logger.info("[ADMIN] Container runtime detected: %s", cmd)
                return cmd
        except Exception as _exc:  # broad catch — resilience against all failures
            continue
    return None  # no working runtime available


def _compose_cmd() -> List[str]:
    """Return the compose command prefix (e.g. ['podman', 'compose'] or ['docker', 'compose'])."""
    runtime = _container_cmd()
    if runtime is None:
        return ["docker", "compose"]  # will fail clearly with FileNotFoundError
    return [runtime, "compose"]


def _compose_dir() -> str:
    """Return the docker-compose project directory."""
    for candidate in ["/app/project", "/app", str(_PROJECT_ROOT_ADMIN)]:
        compose_file = os.path.join(candidate, "docker-compose.yml")
        if os.path.isfile(compose_file):
            return candidate
    return str(_PROJECT_ROOT_ADMIN)


# ---------------------------------------------------------------------------
# Human-readable file size
# ---------------------------------------------------------------------------

def _human_size(nbytes) -> str:
    """Convert bytes to human-readable size string."""
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if abs(nbytes) < 1024.0:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024.0
    return f"{nbytes:.1f} PB"


# ---------------------------------------------------------------------------
# Allowed container services (for validation)
# ---------------------------------------------------------------------------

_ALLOWED_CONTAINER_SERVICES = frozenset({
    "chat_ui_app", "chat_db_app", "llm_api_service", "chat_chroma_db",
    "redis_cache", "search_opt_service", "prometheus_monitoring",
    "grafana_monitoring", "nginx_gateway", "docling_converter",
})

# Service -> (port, probe_type) mapping for TCP/HTTP health probes
_SERVICE_PROBES: dict[str, tuple[int, str]] = {
    "chat_ui_app":          (8090, "http"),
    "chat_db_app":          (5432, "tcp"),
    "llm_api_service":      (11430, "http"),
    "chat_chroma_db":       (8001, "http"),
    "redis_cache":          (6379, "tcp"),
    "search_opt_service":   (9005, "http"),
    "prometheus_monitoring": (9090, "tcp"),
    "grafana_monitoring":   (3100, "tcp"),
}


# ---------------------------------------------------------------------------
# Utility operations allowlist
# ---------------------------------------------------------------------------

_UTILITY_OPS = frozenset({
    "base64_encode", "base64_decode", "url_encode", "url_decode",
    "hex_encode", "hex_decode", "html_encode", "html_decode",
    "md5", "sha1", "sha256", "sha512",
    "json_prettify", "json_minify", "csv_to_json", "json_to_csv",
    "kv_parse", "xml_to_json", "json_parse", "csv_parse",
    "text_upper", "text_lower", "text_reverse", "text_trim",
    "line_sort", "unique_lines", "remove_empty_lines",
    "spl_escape", "quote_values", "rex_extract",
    "timestamp_convert", "uuid_generate", "regex_test",
    "conf_validate", "cim_validate",
})


# ---------------------------------------------------------------------------
# Shared Pydantic models used by multiple sub-routers
# ---------------------------------------------------------------------------

class ContainerActionRequest(BaseModel):
    """Request to perform an action on a container/service."""
    service: str = Field(..., description="Service name")
    action: str = Field(..., description="Action: restart, stop, start, up, logs, rebuild")


class ContainerBuildRequest(BaseModel):
    """Request to build specific container images."""
    services: List[str] = Field(default_factory=list, description="Service names to build (empty = all)")
    no_cache: bool = Field(default=False, description="Build without cache")


class FeatureToggleRequest(BaseModel):
    """Request body to toggle a feature flag."""
    enabled: bool


class ApprovalDecision(BaseModel):
    """Optional body for approve/deny actions."""
    reason: Optional[str] = Field(
        default=None,
        description="Optional reason for the approval or denial.",
    )


class PromptUpdateRequest(BaseModel):
    """Update a prompt template."""
    content: str = Field(..., min_length=10, description="New prompt content")


# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------

def _get_feature_flags() -> Dict[str, bool]:
    """Return the current feature flags, initialising from config.yaml on first call."""
    global _feature_flags
    if _feature_flags is None:
        cfg = {}
        try:
            from chat_app.settings import _load_yaml_config
            cfg = _load_yaml_config()
            raw = cfg.get("features", {})
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug(f"[ADMIN] Feature flags load failed: {exc}")
            raw = {}
        _feature_flags = {
            "hybrid_search": raw.get("hybrid_search", False),
            "query_caching": raw.get("query_caching", True),
            "response_streaming": raw.get("response_streaming", False),
            "auto_feedback_collection": raw.get("auto_feedback_collection", True),
            "reranking": raw.get("reranking", False),
            "query_expansion": raw.get("query_expansion", True),
            "compound_query_detection": raw.get("compound_query_detection", True),
            "prometheus_metrics": raw.get("prometheus_metrics", False),
            "health_checks": raw.get("health_checks", True),
            "circuit_breakers": raw.get("circuit_breakers", True),
            "retry_with_backoff": raw.get("retry_with_backoff", True),
            "fallback_responses": raw.get("fallback_responses", True),
            # Settings-driven flags
            "learning": get_settings().learning.enabled,
            "streaming": raw.get("response_streaming", False),
            "knowledge_graph": cfg.get("knowledge_graph", {}).get("enabled", True),
            "orchestration": cfg.get("orchestration", {}).get("default_strategy", "adaptive") != "disabled",
            "docling_processing": cfg.get("docling", {}).get("enabled", False),
            "splunkbase_catalog": cfg.get("splunkbase_catalog", {}).get("enabled", False),
        }
    return _feature_flags


# ---------------------------------------------------------------------------
# Activity tracking
# ---------------------------------------------------------------------------

def record_query(
    query: str,
    intent: Optional[str] = None,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    collections_searched: Optional[List[str]] = None,
    chunks_found: int = 0,
    confidence: float = 0.0,
    duration_ms: int = 0,
    profile: Optional[str] = None,
) -> None:
    """Record a user query for activity tracking.

    Call this from the message handler pipeline to feed the admin dashboard.
    """
    now = _now_iso()
    _recent_queries.append({
        "query": query[:500],  # truncate long queries
        "intent": intent,
        "user_id": user_id,
        "session_id": session_id,
        "timestamp": now,
        "collections_searched": collections_searched or [],
        "chunks_found": chunks_found,
        "confidence": round(confidence, 3),
        "duration_ms": duration_ms,
        "profile": profile,
    })
    # Track per-collection usage
    for col_name in (collections_searched or []):
        _collection_hit_counts[col_name] = _collection_hit_counts.get(col_name, 0) + 1
    # Trim to bounded size.
    if len(_recent_queries) > _MAX_RECENT_QUERIES:
        del _recent_queries[: len(_recent_queries) - _MAX_RECENT_QUERIES]

    # Update intent distribution.
    if intent:
        _intent_counts[intent] = _intent_counts.get(intent, 0) + 1

    # Update per-minute volume bucket.
    minute_key = now[:16]  # "YYYY-MM-DDTHH:MM"
    if _query_volume and _query_volume[-1].get("minute") == minute_key:
        _query_volume[-1]["count"] += 1
    else:
        _query_volume.append({"minute": minute_key, "count": 1})
    if len(_query_volume) > _MAX_VOLUME_BUCKETS:
        del _query_volume[: len(_query_volume) - _MAX_VOLUME_BUCKETS]
