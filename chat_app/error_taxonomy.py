"""Deterministic Error Taxonomy — consistent error codes across all endpoints.

Every error in the system maps to a well-defined code with:
- HTTP status code
- Human-readable message template
- Remediation hint
- Retry policy (should the caller retry?)

Usage:
    from chat_app.error_taxonomy import raise_error, ErrorCode

    # Raise a standardized error
    raise_error(ErrorCode.RESOURCE_NOT_FOUND, resource="collection", identifier="spl_docs")

    # Or use the helper directly
    raise_error(ErrorCode.PERMISSION_DENIED, required="ADMIN", current="USER")

Response format:
    {
        "error": {
            "code": "RESOURCE_NOT_FOUND",
            "message": "Resource not found: collection 'spl_docs'",
            "details": {"resource": "collection", "identifier": "spl_docs"},
            "remediation": "Verify the resource exists and you have access to it.",
            "retry": false
        }
    }
"""

import logging
from enum import Enum
from typing import Any, Dict, Optional

from fastapi import HTTPException

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Error Code Definitions
# ---------------------------------------------------------------------------

class ErrorCode(str, Enum):
    """Canonical error codes for the entire application.

    Grouped by category prefix:
    - AUTH_*: Authentication and authorization
    - VALIDATION_*: Input validation
    - RESOURCE_*: Resource lifecycle
    - RATE_*: Rate limiting
    - TOOL_*: Tool and skill execution
    - CONFIG_*: Configuration management
    - WORKFLOW_*: Workflow and orchestration
    - INTERNAL_*: Server-side errors
    """

    # --- Authentication & Authorization ---
    AUTH_REQUIRED = "AUTH_REQUIRED"
    AUTH_INVALID_TOKEN = "AUTH_INVALID_TOKEN"
    AUTH_EXPIRED_TOKEN = "AUTH_EXPIRED_TOKEN"
    AUTH_INVALID_API_KEY = "AUTH_INVALID_API_KEY"
    AUTH_INVALID_SERVICE_KEY = "AUTH_INVALID_SERVICE_KEY"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    ROLE_INSUFFICIENT = "ROLE_INSUFFICIENT"
    CSRF_REJECTED = "CSRF_REJECTED"

    # --- Input Validation ---
    VALIDATION_ERROR = "VALIDATION_ERROR"
    VALIDATION_FIELD_REQUIRED = "VALIDATION_FIELD_REQUIRED"
    VALIDATION_FIELD_INVALID = "VALIDATION_FIELD_INVALID"
    VALIDATION_PAYLOAD_TOO_LARGE = "VALIDATION_PAYLOAD_TOO_LARGE"
    VALIDATION_PASSWORD_WEAK = "VALIDATION_PASSWORD_WEAK"

    # --- Resource Lifecycle ---
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_ALREADY_EXISTS = "RESOURCE_ALREADY_EXISTS"
    RESOURCE_LOCKED = "RESOURCE_LOCKED"
    RESOURCE_DELETED = "RESOURCE_DELETED"

    # --- Rate Limiting ---
    RATE_LIMITED = "RATE_LIMITED"
    QUOTA_EXCEEDED = "QUOTA_EXCEEDED"

    # --- Tool & Skill Execution ---
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    TOOL_EXECUTION_FAILED = "TOOL_EXECUTION_FAILED"
    TOOL_TIMEOUT = "TOOL_TIMEOUT"
    TOOL_DISABLED = "TOOL_DISABLED"
    TOOL_APPROVAL_REQUIRED = "TOOL_APPROVAL_REQUIRED"
    TOOL_DRY_RUN = "TOOL_DRY_RUN"
    SKILL_NOT_FOUND = "SKILL_NOT_FOUND"
    SKILL_EXECUTION_FAILED = "SKILL_EXECUTION_FAILED"

    # --- Configuration ---
    CONFIG_SECTION_NOT_FOUND = "CONFIG_SECTION_NOT_FOUND"
    CONFIG_VALIDATION_FAILED = "CONFIG_VALIDATION_FAILED"
    CONFIG_RESTART_REQUIRED = "CONFIG_RESTART_REQUIRED"
    CONFIG_BACKUP_FAILED = "CONFIG_BACKUP_FAILED"

    # --- Workflow & Orchestration ---
    WORKFLOW_NOT_FOUND = "WORKFLOW_NOT_FOUND"
    WORKFLOW_EXECUTION_FAILED = "WORKFLOW_EXECUTION_FAILED"
    WORKFLOW_STEP_FAILED = "WORKFLOW_STEP_FAILED"
    WORKFLOW_APPROVAL_PENDING = "WORKFLOW_APPROVAL_PENDING"
    STRATEGY_NOT_FOUND = "STRATEGY_NOT_FOUND"
    AGENT_NOT_FOUND = "AGENT_NOT_FOUND"

    # --- Container & Infrastructure ---
    CONTAINER_NOT_FOUND = "CONTAINER_NOT_FOUND"
    CONTAINER_ACTION_FAILED = "CONTAINER_ACTION_FAILED"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    DEPENDENCY_UNHEALTHY = "DEPENDENCY_UNHEALTHY"

    # --- Internal ---
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"


# ---------------------------------------------------------------------------
# Error metadata catalog
# ---------------------------------------------------------------------------

_ERROR_CATALOG: Dict[ErrorCode, Dict[str, Any]] = {
    # Auth
    ErrorCode.AUTH_REQUIRED: {
        "status": 401,
        "message": "Authentication required",
        "remediation": "Provide a valid access_token cookie, Bearer token, or X-API-Key header.",
        "retry": False,
    },
    ErrorCode.AUTH_INVALID_TOKEN: {
        "status": 401,
        "message": "Invalid authentication token",
        "remediation": "Check that your token is valid and correctly formatted.",
        "retry": False,
    },
    ErrorCode.AUTH_EXPIRED_TOKEN: {
        "status": 401,
        "message": "Authentication token has expired",
        "remediation": "Obtain a new token by logging in again.",
        "retry": False,
    },
    ErrorCode.AUTH_INVALID_API_KEY: {
        "status": 401,
        "message": "Invalid API key",
        "remediation": "Verify your API key or generate a new one via POST /api/admin/tokens.",
        "retry": False,
    },
    ErrorCode.AUTH_INVALID_SERVICE_KEY: {
        "status": 401,
        "message": "Invalid service key",
        "remediation": "Check the SERVICE_API_KEY environment variable.",
        "retry": False,
    },
    ErrorCode.PERMISSION_DENIED: {
        "status": 403,
        "message": "Permission denied: {resource_type}:{resource_id}:{action}",
        "remediation": "Contact an administrator to request the required permission.",
        "retry": False,
    },
    ErrorCode.ROLE_INSUFFICIENT: {
        "status": 403,
        "message": "Insufficient role. Required: {required}. Your role: {current}",
        "remediation": "Contact an administrator to upgrade your role.",
        "retry": False,
    },
    ErrorCode.CSRF_REJECTED: {
        "status": 403,
        "message": "Cross-origin request rejected (CSRF protection)",
        "remediation": "Ensure requests originate from the same origin or use an API key.",
        "retry": False,
    },

    # Validation
    ErrorCode.VALIDATION_ERROR: {
        "status": 422,
        "message": "Validation error: {message}",
        "remediation": "Check the request body against the API schema.",
        "retry": False,
    },
    ErrorCode.VALIDATION_FIELD_REQUIRED: {
        "status": 422,
        "message": "Required field missing: {field}",
        "remediation": "Include the '{field}' field in your request.",
        "retry": False,
    },
    ErrorCode.VALIDATION_FIELD_INVALID: {
        "status": 422,
        "message": "Invalid value for field '{field}': {reason}",
        "remediation": "Check the expected format for '{field}'.",
        "retry": False,
    },
    ErrorCode.VALIDATION_PAYLOAD_TOO_LARGE: {
        "status": 413,
        "message": "Request payload too large (max {max_size})",
        "remediation": "Reduce the request size or use pagination.",
        "retry": False,
    },
    ErrorCode.VALIDATION_PASSWORD_WEAK: {
        "status": 400,
        "message": "Password does not meet complexity requirements: {reason}",
        "remediation": "Use at least 8 characters with uppercase, lowercase, and digits.",
        "retry": False,
    },

    # Resource
    ErrorCode.RESOURCE_NOT_FOUND: {
        "status": 404,
        "message": "Resource not found: {resource} '{identifier}'",
        "remediation": "Verify the resource exists and you have access to it.",
        "retry": False,
    },
    ErrorCode.RESOURCE_ALREADY_EXISTS: {
        "status": 409,
        "message": "Resource already exists: {resource} '{identifier}'",
        "remediation": "Use a different name or update the existing resource.",
        "retry": False,
    },
    ErrorCode.RESOURCE_LOCKED: {
        "status": 423,
        "message": "Resource is locked: {resource} '{identifier}'",
        "remediation": "Wait for the current operation to complete or contact an admin.",
        "retry": True,
    },
    ErrorCode.RESOURCE_DELETED: {
        "status": 410,
        "message": "Resource has been deleted: {resource} '{identifier}'",
        "remediation": "The resource no longer exists. Check backups if recovery is needed.",
        "retry": False,
    },

    # Rate limiting
    ErrorCode.RATE_LIMITED: {
        "status": 429,
        "message": "Rate limit exceeded. Try again in {retry_after} seconds.",
        "remediation": "Reduce request frequency or wait for the rate limit window to reset.",
        "retry": True,
    },
    ErrorCode.QUOTA_EXCEEDED: {
        "status": 429,
        "message": "Quota exceeded: {quota_type}",
        "remediation": "Contact an administrator to increase your quota.",
        "retry": False,
    },

    # Tool execution
    ErrorCode.TOOL_NOT_FOUND: {
        "status": 404,
        "message": "Tool not found: '{tool_name}'",
        "remediation": "Check available tools via GET /api/admin/api-catalog.",
        "retry": False,
    },
    ErrorCode.TOOL_EXECUTION_FAILED: {
        "status": 500,
        "message": "Tool execution failed: {tool_name} — {reason}",
        "remediation": "Check tool dependencies and configuration.",
        "retry": True,
    },
    ErrorCode.TOOL_TIMEOUT: {
        "status": 504,
        "message": "Tool execution timed out: {tool_name} (limit: {timeout}s)",
        "remediation": "Try again or increase the tool timeout in configuration.",
        "retry": True,
    },
    ErrorCode.TOOL_DISABLED: {
        "status": 403,
        "message": "Tool is disabled: '{tool_name}'",
        "remediation": "Enable the tool via configuration or contact an admin.",
        "retry": False,
    },
    ErrorCode.TOOL_APPROVAL_REQUIRED: {
        "status": 202,
        "message": "Approval required for tool: '{tool_name}'",
        "remediation": "Submit an approval request via POST /api/admin/approvals.",
        "retry": False,
    },
    ErrorCode.TOOL_DRY_RUN: {
        "status": 200,
        "message": "Dry run completed for tool: '{tool_name}'",
        "remediation": "Review the dry run output and submit again with dry_run=false.",
        "retry": False,
    },
    ErrorCode.SKILL_NOT_FOUND: {
        "status": 404,
        "message": "Skill not found: '{skill_name}'",
        "remediation": "Check available skills via GET /api/admin/skill-catalog.",
        "retry": False,
    },
    ErrorCode.SKILL_EXECUTION_FAILED: {
        "status": 500,
        "message": "Skill execution failed: {skill_name} — {reason}",
        "remediation": "Check skill configuration and dependencies.",
        "retry": True,
    },

    # Config
    ErrorCode.CONFIG_SECTION_NOT_FOUND: {
        "status": 404,
        "message": "Configuration section not found: '{section}'",
        "remediation": "Valid sections: llm, retrieval, ingestion, security, features, etc.",
        "retry": False,
    },
    ErrorCode.CONFIG_VALIDATION_FAILED: {
        "status": 422,
        "message": "Configuration validation failed: {reason}",
        "remediation": "Check the configuration values against the schema.",
        "retry": False,
    },
    ErrorCode.CONFIG_RESTART_REQUIRED: {
        "status": 200,
        "message": "Configuration updated. Restart required for section: '{section}'",
        "remediation": "Restart the affected service to apply changes.",
        "retry": False,
    },
    ErrorCode.CONFIG_BACKUP_FAILED: {
        "status": 500,
        "message": "Configuration backup failed: {reason}",
        "remediation": "Check disk space and file permissions.",
        "retry": True,
    },

    # Workflow
    ErrorCode.WORKFLOW_NOT_FOUND: {
        "status": 404,
        "message": "Workflow not found: '{workflow_id}'",
        "remediation": "Check workflow history via GET /api/admin/workflows/history.",
        "retry": False,
    },
    ErrorCode.WORKFLOW_EXECUTION_FAILED: {
        "status": 500,
        "message": "Workflow execution failed: {reason}",
        "remediation": "Check the workflow definition and agent availability.",
        "retry": True,
    },
    ErrorCode.WORKFLOW_STEP_FAILED: {
        "status": 500,
        "message": "Workflow step '{step}' failed: {reason}",
        "remediation": "Review the step configuration and dependencies.",
        "retry": True,
    },
    ErrorCode.WORKFLOW_APPROVAL_PENDING: {
        "status": 202,
        "message": "Workflow step requires approval: '{step}'",
        "remediation": "Approve or deny via the approvals endpoint.",
        "retry": False,
    },
    ErrorCode.STRATEGY_NOT_FOUND: {
        "status": 404,
        "message": "Orchestration strategy not found: '{strategy}'",
        "remediation": "Check available strategies via GET /api/admin/orchestration/strategies.",
        "retry": False,
    },
    ErrorCode.AGENT_NOT_FOUND: {
        "status": 404,
        "message": "Agent not found: '{agent_name}'",
        "remediation": "Check the agent catalog via GET /api/admin/agent-catalog.",
        "retry": False,
    },

    # Container
    ErrorCode.CONTAINER_NOT_FOUND: {
        "status": 404,
        "message": "Container not found: '{container}'",
        "remediation": "Check running containers via GET /api/admin/containers.",
        "retry": False,
    },
    ErrorCode.CONTAINER_ACTION_FAILED: {
        "status": 500,
        "message": "Container action failed: {action} on '{container}' — {reason}",
        "remediation": "Check container logs and runtime status.",
        "retry": True,
    },
    ErrorCode.SERVICE_UNAVAILABLE: {
        "status": 503,
        "message": "Service unavailable: '{service}'",
        "remediation": "The service may be starting up or unhealthy. Try again shortly.",
        "retry": True,
    },
    ErrorCode.DEPENDENCY_UNHEALTHY: {
        "status": 503,
        "message": "Required dependency is unhealthy: '{dependency}'",
        "remediation": "Check the health of '{dependency}' and restart if needed.",
        "retry": True,
    },

    # Internal
    ErrorCode.INTERNAL_ERROR: {
        "status": 500,
        "message": "Internal server error: {context}",
        "remediation": "Check server logs for details. If the issue persists, contact support.",
        "retry": True,
    },
    ErrorCode.NOT_IMPLEMENTED: {
        "status": 501,
        "message": "Feature not implemented: {feature}",
        "remediation": "This feature is planned for a future release.",
        "retry": False,
    },
    ErrorCode.UPSTREAM_ERROR: {
        "status": 502,
        "message": "Upstream service error: {service} — {reason}",
        "remediation": "The upstream service returned an error. Try again or check its status.",
        "retry": True,
    },
}


# ---------------------------------------------------------------------------
# Error raising helper
# ---------------------------------------------------------------------------

def raise_error(
    code: ErrorCode,
    headers: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> None:
    """Raise an HTTPException with a standardized error body.

    Args:
        code: The error code from ErrorCode enum.
        headers: Optional HTTP headers (e.g., Retry-After for 429).
        **kwargs: Template variables for the message and details.

    Raises:
        HTTPException with structured error body.
    """
    catalog_entry = _ERROR_CATALOG.get(code, {
        "status": 500,
        "message": str(code.value),
        "remediation": "Check server logs.",
        "retry": False,
    })

    status_code = catalog_entry["status"]
    message_template = catalog_entry["message"]
    remediation = catalog_entry["remediation"]
    retry = catalog_entry["retry"]

    # Format message and remediation with kwargs
    try:
        message = message_template.format(**kwargs)
    except (KeyError, IndexError):
        message = message_template

    try:
        remediation = remediation.format(**kwargs)
    except (KeyError, IndexError) as _exc:
        logger.debug("Remediation template format failed for code %r: %s", code, _exc)

    error_body: Dict[str, Any] = {
        "code": code.value,
        "message": message,
        "remediation": remediation,
        "retry": retry,
    }
    if kwargs:
        error_body["details"] = {k: str(v) for k, v in kwargs.items()}

    logger.warning(
        "[ERROR] %s (HTTP %d): %s — details=%s",
        code.value, status_code, message, kwargs,
    )

    raise HTTPException(
        status_code=status_code,
        detail={"error": error_body},
        headers=headers,
    )


def get_error_catalog() -> Dict[str, Dict[str, Any]]:
    """Return the full error catalog for documentation/UI display."""
    catalog = {}
    for code, meta in _ERROR_CATALOG.items():
        catalog[code.value] = {
            "status": meta["status"],
            "message_template": meta["message"],
            "remediation": meta["remediation"],
            "retry": meta["retry"],
            "category": code.value.split("_")[0],
        }
    return catalog
