"""
API Services Types — Data structures for the API Services layer.

Extracted from api_services.py to allow api_services_catalog.py to import
them without creating a circular import. Re-exported by api_services.py.
"""
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class ServiceCategory(str, Enum):
    SPL = "spl"
    SEARCH = "search"
    CONFIG = "config"
    MONITORING = "monitoring"
    INGESTION = "ingestion"
    SCRIPTING = "scripting"
    KNOWLEDGE = "knowledge"
    SYSTEM = "system"
    SPLUNKBASE = "splunkbase"


class ServiceAccess(str, Enum):
    PUBLIC = "public"        # No auth required (disabled by default)
    USER = "user"            # Any authenticated user
    ANALYST = "analyst"      # Analyst role or above
    ADMIN = "admin"          # Admin only


# ---------------------------------------------------------------------------
# ServiceDefinition
# ---------------------------------------------------------------------------

@dataclass
class ServiceDefinition:
    """Defines an API service with its handler, schema, and access control."""
    service_id: str
    name: str
    description: str
    category: ServiceCategory
    handler_key: str                   # Maps to skill_executor handler
    method: str = "POST"               # HTTP method
    access_level: ServiceAccess = ServiceAccess.USER
    enabled: bool = True               # Default: enabled (services require auth)
    rate_limit_per_minute: int = 30
    timeout_seconds: int = 60
    input_schema: Dict[str, Any] = field(default_factory=dict)   # JSON Schema
    output_schema: Dict[str, Any] = field(default_factory=dict)
    example_input: Dict[str, Any] = field(default_factory=dict)
    example_output: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "service_id": self.service_id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "method": self.method,
            "access_level": self.access_level.value,
            "enabled": self.enabled,
            "rate_limit_per_minute": self.rate_limit_per_minute,
            "timeout_seconds": self.timeout_seconds,
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "example_input": self.example_input,
            "example_output": self.example_output,
            "tags": self.tags,
            "endpoint": f"/api/v1/services/{self.service_id}",
        }


# ---------------------------------------------------------------------------
# Request/Response Models
# ---------------------------------------------------------------------------

class ServiceRequest(BaseModel):
    """Generic service request."""
    input: str = Field(default="", description="Primary input text (query, SPL, config, etc.)")
    params: Dict[str, Any] = Field(default_factory=dict, description="Additional parameters")


class ServiceResponse(BaseModel):
    """Generic service response."""
    success: bool
    service_id: str
    output: Any = None
    error: Optional[str] = None
    duration_ms: float = 0
    timestamp: str = ""
    usage: Optional[Dict[str, Any]] = None


class SplunkbaseCheckRequest(BaseModel):
    """Splunkbase app version check request."""
    apps: List[Dict[str, str]] = Field(
        description="List of apps with 'name' and optional 'version' fields",
        examples=[[{"name": "Splunk_TA_windows", "version": "8.5.0"}, {"name": "SplunkEnterpriseSecuritySuite"}]],
    )


class BulkSPLRequest(BaseModel):
    """Bulk SPL analysis request."""
    queries: List[str] = Field(description="List of SPL queries to analyze")
    action: str = Field(default="validate", description="Action: validate, optimize, explain, analyze")


# ---------------------------------------------------------------------------
# Rate Limiter
# ---------------------------------------------------------------------------

class _RateLimiter:
    """Simple in-memory rate limiter per caller."""

    def __init__(self):
        self._calls: Dict[str, List[float]] = defaultdict(list)

    def check(self, caller_id: str, limit: int, window_seconds: int = 60) -> bool:
        """Return True if within rate limit."""
        now = time.time()
        calls = self._calls[caller_id]
        # Prune old entries
        self._calls[caller_id] = [t for t in calls if now - t < window_seconds]
        if len(self._calls[caller_id]) >= limit:
            return False
        self._calls[caller_id].append(now)
        return True


_rate_limiter = _RateLimiter()
