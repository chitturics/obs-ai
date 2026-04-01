"""Admin sub-router: SSL certificate and network connectivity endpoints.

Provides:
- GET  /api/admin/ssl/status            — SSL certificate info and current status
- POST /api/admin/ssl/upload-cert       — Upload a PEM certificate file
- POST /api/admin/ssl/generate-self-signed — Generate a self-signed certificate
- PATCH /api/admin/ssl/toggle           — Enable or disable SSL
- GET  /api/admin/ports                 — Configured and running port map
- PATCH /api/admin/ports                — Save port overrides to config.yaml
- GET  /api/admin/network/test          — Connectivity status for internal services
- POST /api/admin/network/test          — Run a targeted network diagnostic

Mount with:
    from chat_app.admin_network_routes import network_router
    app.include_router(network_router)
"""

import base64
import logging
import socket
import ssl as ssl_stdlib
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from chat_app.admin_shared import (
    _append_audit,
    _csrf_check,
    _now_iso,
    _rate_limit,
    _safe_error,
    _track_audit_user,
)
from chat_app.auth_dependencies import require_admin

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default certificate paths used by the nginx container.
_DEFAULT_CERT_PATH = "/app/certs/cert.pem"
_DEFAULT_KEY_PATH = "/app/certs/key.pem"

# Seconds before a socket probe is considered a timeout.
_PROBE_TIMEOUT_SECONDS = 3

# Services probed by the connectivity check.
_INTERNAL_SERVICES = {
    "ollama": ("llm_api_service", 11430),
    "chromadb": ("chat_chroma_db", 8001),
    "postgres": ("chat_db_app", 5432),
    "redis": ("chat_redis_app", 6379),
    "search_opt": ("chat_search_opt", 8004),
}

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

network_router = APIRouter(
    prefix="/api/admin",
    tags=["admin-network"],
    dependencies=[
        Depends(_rate_limit),
        Depends(require_admin),
        Depends(_track_audit_user),
        Depends(_csrf_check),
    ],
)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class CertUploadRequest(BaseModel):
    """Base64-encoded PEM certificate upload."""
    filename: str = Field(..., min_length=1, max_length=128, description="Target filename (cert.pem or key.pem)")
    content_base64: str = Field(..., min_length=1, description="Base64-encoded PEM file content")


class SSLToggleRequest(BaseModel):
    """Enable or disable SSL."""
    enabled: bool = Field(..., description="True to enable SSL, False to disable")


class PortSaveRequest(BaseModel):
    """Save port overrides to config.yaml."""
    ports: Dict[str, int] = Field(..., description="Port name → port number mapping to persist")


class NetworkDiagRequest(BaseModel):
    """Run a targeted network diagnostic."""
    tool: str = Field(..., pattern="^(dns|ping|port)$", description="Diagnostic tool: dns, ping, or port")
    target: str = Field(..., min_length=1, max_length=255, description="Hostname or IP address to probe")
    port: int = Field(default=0, ge=0, le=65535, description="Port number (required for port tool)")


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _probe_tcp(host: str, port: int, timeout: float = _PROBE_TIMEOUT_SECONDS) -> bool:
    """Return True if a TCP connection to host:port succeeds within timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, socket.timeout):
        return False


def _read_cert_info(cert_path: str) -> Dict[str, Optional[str]]:
    """Extract expiry, subject, and issuer from a PEM cert file. Returns empty strings on failure."""
    info: Dict[str, Optional[str]] = {"expiry": None, "subject": None, "issuer": None}
    try:
        context = ssl_stdlib.SSLContext(ssl_stdlib.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl_stdlib.CERT_NONE
        cert_bytes = Path(cert_path).read_bytes()
        # Parse with cryptography if available, otherwise use ssl.DER_cert_to_PEM_cert
        try:
            from cryptography import x509
            from cryptography.hazmat.backends import default_backend
            cert = x509.load_pem_x509_certificate(cert_bytes, default_backend())
            info["expiry"] = cert.not_valid_after_utc.isoformat()
            info["subject"] = cert.subject.rfc4514_string()
            info["issuer"] = cert.issuer.rfc4514_string()
        except ImportError:
            # Fallback: use ssl.PEM_cert_to_DER_cert and then ssl.DER_cert_to_PEM_cert
            der = ssl_stdlib.PEM_cert_to_DER_cert(cert_bytes.decode())
            cert_dict2 = ssl_stdlib.DER_cert_to_PEM_cert(der)  # noqa: F841 — validates round-trip
            # ssl stdlib cannot parse expiry directly; leave as None
    except Exception as exc:  # noqa:  # broad catch — resilience at boundary BLE001 — best-effort, must not raise
        logger.debug("[network_routes] cert parse failed: %s", exc)
    return info


def _get_ssl_settings() -> Any:
    """Return the ssl sub-section of settings."""
    from chat_app.settings import get_settings
    settings = get_settings()
    return getattr(settings, "ssl", None) or getattr(getattr(settings, "ui", None), "ssl", None)


def _get_configured_ports() -> Dict[str, int]:
    """Return the port map from settings/config.yaml."""
    try:
        from chat_app.settings import get_settings
        settings = get_settings()
        # Prefer an explicit ports section; fall back to individual service settings.
        if hasattr(settings, "ports"):
            return dict(settings.ports or {})
    except Exception as exc:  # noqa:  # broad catch — resilience at boundary BLE001
        logger.debug("[network_routes] ports setting read failed: %s", exc)

    # Build reasonable defaults from well-known settings fields.
    return {
        "app": 8090,
        "gateway": 8000,
        "gateway_ssl": 8443,
        "ollama": 11430,
        "chromadb": 8001,
        "postgres": 5432,
        "redis": 6379,
        "search_opt": 8004,
    }


# ---------------------------------------------------------------------------
# SSL Status
# ---------------------------------------------------------------------------

@network_router.get("/ssl/status", summary="SSL certificate status")
async def get_ssl_status() -> Dict[str, Any]:
    """Return SSL configuration and certificate metadata."""
    ssl_cfg = _get_ssl_settings()

    cert_path = getattr(ssl_cfg, "cert_file", "") or _DEFAULT_CERT_PATH
    key_path = getattr(ssl_cfg, "key_file", "") or _DEFAULT_KEY_PATH
    ssl_enabled = bool(getattr(ssl_cfg, "enabled", False))

    cert_exists = Path(cert_path).is_file()
    key_exists = Path(key_path).is_file()

    cert_info: Dict[str, Optional[str]] = {"expiry": None, "subject": None, "issuer": None}
    if cert_exists:
        cert_info = _read_cert_info(cert_path)

    return {
        "enabled": ssl_enabled,
        "cert_file": cert_path,
        "key_file": key_path,
        "cert_exists": cert_exists,
        "key_exists": key_exists,
        "expiry": cert_info["expiry"],
        "subject": cert_info["subject"],
        "issuer": cert_info["issuer"],
        "timestamp": _now_iso(),
    }


# ---------------------------------------------------------------------------
# Certificate Upload
# ---------------------------------------------------------------------------

@network_router.post("/ssl/upload-cert", summary="Upload SSL certificate or key")
async def upload_ssl_cert(body: CertUploadRequest) -> Dict[str, Any]:
    """Accept a base64-encoded PEM file and write it to /app/certs/."""
    allowed_names = {"cert.pem", "key.pem", "ca.pem"}
    if body.filename not in allowed_names:
        raise HTTPException(
            status_code=400,
            detail=f"filename must be one of: {', '.join(sorted(allowed_names))}",
        )

    try:
        content = base64.b64decode(body.content_base64)
    except Exception as exc:  # broad catch — resilience at boundary
        raise HTTPException(status_code=400, detail=f"Invalid base64 content: {exc}") from exc

    dest_dir = Path("/app/certs")
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / body.filename

    try:
        dest_path.write_bytes(content)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write certificate: {exc}") from exc

    _append_audit("ssl.upload-cert", {"filename": body.filename, "size": len(content)})
    logger.info("[network_routes] certificate uploaded: %s (%d bytes)", body.filename, len(content))

    return {
        "status": "ok",
        "file": str(dest_path),
        "size": len(content),
        "message": f"Certificate '{body.filename}' saved successfully.",
    }


# ---------------------------------------------------------------------------
# Generate Self-Signed Certificate
# ---------------------------------------------------------------------------

@network_router.post("/ssl/generate-self-signed", summary="Generate a self-signed SSL certificate")
async def generate_self_signed_cert() -> Dict[str, Any]:
    """Generate a 2048-bit self-signed certificate and key in /app/certs/."""
    dest_dir = Path("/app/certs")
    dest_dir.mkdir(parents=True, exist_ok=True)
    cert_path = dest_dir / "cert.pem"
    key_path = dest_dir / "key.pem"

    try:
        import subprocess
        result = subprocess.run(
            [
                "openssl", "req", "-x509", "-newkey", "rsa:2048",
                "-keyout", str(key_path),
                "-out", str(cert_path),
                "-days", "365",
                "-nodes",
                "-subj", "/CN=obsai-local/O=ObsAI/C=US",
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip())
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=500,
            detail="openssl binary not found in container. Install with: apk add openssl",
        ) from exc
    except Exception as exc:  # broad catch — resilience at boundary
        raise HTTPException(status_code=500, detail=_safe_error(exc, "generate-self-signed")) from exc

    _append_audit("ssl.generate-self-signed", {"cert": str(cert_path), "key": str(key_path)})
    logger.info("[network_routes] self-signed certificate generated at %s", cert_path)

    return {
        "status": "ok",
        "cert_file": str(cert_path),
        "key_file": str(key_path),
        "message": "Self-signed certificate valid for 365 days created successfully.",
    }


# ---------------------------------------------------------------------------
# Toggle SSL
# ---------------------------------------------------------------------------

@network_router.patch("/ssl/toggle", summary="Enable or disable SSL")
async def toggle_ssl(body: SSLToggleRequest) -> Dict[str, Any]:
    """Persist ssl.enabled in config.yaml and return restart requirement."""
    try:
        from chat_app.config_manager import get_config_manager
        config_mgr = get_config_manager()
        config_mgr.update_section("ssl", {"enabled": body.enabled})
    except Exception as exc:  # noqa:  # broad catch — resilience at boundary BLE001
        logger.warning("[network_routes] could not persist ssl.enabled: %s", exc)

    _append_audit("ssl.toggle", {"enabled": body.enabled})
    action = "enabled" if body.enabled else "disabled"
    logger.info("[network_routes] SSL %s via admin API", action)

    return {
        "status": "ok",
        "ssl_enabled": body.enabled,
        "restart_required": True,
        "message": f"SSL {action}. Restart nginx to apply.",
    }


# ---------------------------------------------------------------------------
# Port Configuration
# ---------------------------------------------------------------------------

@network_router.get("/ports", summary="Get configured port map")
async def get_ports() -> Dict[str, Any]:
    """Return configured and currently active port numbers for all services."""
    configured = _get_configured_ports()

    # Probe each service to determine if it is actually listening.
    running: Dict[str, int] = {}
    for service_name, (host, port) in _INTERNAL_SERVICES.items():
        if _probe_tcp(host, port):
            running[service_name] = port

    labels = {
        "app": "App (internal)",
        "gateway": "Gateway HTTP",
        "gateway_ssl": "Gateway HTTPS",
        "ollama": "Ollama LLM",
        "chromadb": "ChromaDB",
        "postgres": "PostgreSQL",
        "redis": "Redis",
        "search_opt": "Search Optimizer",
    }

    return {
        "configured": configured,
        "running": running,
        "labels": labels,
        "timestamp": _now_iso(),
    }


@network_router.patch("/ports", summary="Save port overrides")
async def save_ports(body: PortSaveRequest) -> Dict[str, Any]:
    """Persist port overrides to config.yaml."""
    if not body.ports:
        raise HTTPException(status_code=400, detail="ports map must not be empty")

    previous = _get_configured_ports()

    try:
        from chat_app.config_manager import get_config_manager
        config_mgr = get_config_manager()
        config_mgr.update_section("ports", body.ports)
    except Exception as exc:  # noqa:  # broad catch — resilience at boundary BLE001
        logger.warning("[network_routes] could not persist ports: %s", exc)

    _append_audit("ports.save", {"ports": body.ports})
    logger.info("[network_routes] ports updated: %s", body.ports)

    return {
        "status": "ok",
        "saved": body.ports,
        "previous": previous,
        "restart_required": True,
        "message": "Port configuration saved. Restart containers to apply.",
    }


# ---------------------------------------------------------------------------
# Network Connectivity Test
# ---------------------------------------------------------------------------

@network_router.get("/network/test", summary="Internal service connectivity overview")
async def get_network_status() -> Dict[str, Any]:
    """Probe all internal services and return their reachability."""
    results: Dict[str, Any] = {}
    for service_name, (host, port) in _INTERNAL_SERVICES.items():
        reachable = _probe_tcp(host, port)
        results[service_name] = {
            "host": host,
            "port": port,
            "reachable": reachable,
            "status": "up" if reachable else "unreachable",
        }

    total = len(results)
    reachable_count = sum(1 for r in results.values() if r["reachable"])

    return {
        "services": results,
        "summary": {
            "total": total,
            "reachable": reachable_count,
            "unreachable": total - reachable_count,
        },
        "timestamp": _now_iso(),
    }


@network_router.post("/network/test", summary="Run targeted network diagnostic")
async def run_network_diagnostic(body: NetworkDiagRequest) -> Dict[str, Any]:
    """Run a DNS lookup, ping, or TCP port check against an arbitrary target."""
    tool = body.tool
    target = body.target
    port = body.port
    result: Dict[str, Any] = {"tool": tool, "target": target, "timestamp": _now_iso()}

    try:
        if tool == "dns":
            addresses = socket.getaddrinfo(target, None)
            ips = list({addr[4][0] for addr in addresses})
            result.update({"success": True, "resolved_ips": ips})

        elif tool == "ping":
            # Use TCP probe to a well-known port as a ping proxy (ICMP ping requires root).
            probe_port = port if port > 0 else 80
            reachable = _probe_tcp(target, probe_port)
            result.update({
                "success": reachable,
                "note": f"TCP probe to port {probe_port} (ICMP requires elevated privileges)",
            })

        elif tool == "port":
            if port <= 0:
                raise HTTPException(status_code=400, detail="port must be > 0 for port tool")
            reachable = _probe_tcp(target, port)
            result.update({"success": reachable, "port": port})

        else:
            raise HTTPException(status_code=400, detail=f"Unknown tool: {tool}")

    except HTTPException:
        raise
    except (OSError, socket.gaierror, socket.timeout) as exc:
        result.update({"success": False, "error": str(exc)})
    except Exception as exc:  # noqa:  # broad catch — resilience at boundary BLE001
        result.update({"success": False, "error": _safe_error(exc, "network-diag")})

    return result
