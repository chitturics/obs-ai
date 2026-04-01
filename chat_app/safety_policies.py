"""Safety Policies — per-tool execution policies for write-action protection.

Defines and enforces safety rules for tool execution:
- **read-only tools**: No restrictions
- **write tools**: Require explicit user approval before execution
- **destructive tools**: Require admin approval + confirmation
- **environment-aware**: Different policies for dev/staging/production

Policy evaluation flow:
    1. Look up tool's safety classification
    2. Check environment constraints
    3. Check if action requires approval
    4. Check dry_run preference
    5. Return policy decision (allow, require_approval, deny)

Usage:
    from chat_app.safety_policies import evaluate_policy, ToolSafetyLevel

    decision = evaluate_policy("delete_index", user_role="ANALYST", environment="production")
    if decision.action == "require_approval":
        # Route to approval workflow
    elif decision.action == "deny":
        # Block execution
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Safety levels
# ---------------------------------------------------------------------------

class ToolSafetyLevel(str, Enum):
    """Safety classification for tools."""
    READ_ONLY = "read_only"        # No side effects — always safe
    WRITE = "write"                # Modifies internal state — needs confirmation
    EXTERNAL_WRITE = "external_write"  # Modifies external systems (Splunk, Cribl)
    DESTRUCTIVE = "destructive"    # Irreversible — needs admin approval


class PolicyAction(str, Enum):
    """Result of a policy evaluation."""
    ALLOW = "allow"                    # Execute immediately
    REQUIRE_CONFIRMATION = "require_confirmation"  # User must confirm
    REQUIRE_APPROVAL = "require_approval"        # Admin must approve
    DENY = "deny"                      # Not allowed in this context
    DRY_RUN_ONLY = "dry_run_only"      # Only dry run allowed


class Environment(str, Enum):
    """Deployment environments with different safety policies."""
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


# ---------------------------------------------------------------------------
# Policy decision
# ---------------------------------------------------------------------------

@dataclass
class PolicyDecision:
    """Result of evaluating a safety policy."""
    action: PolicyAction
    tool_name: str
    safety_level: ToolSafetyLevel
    reason: str
    requires_dry_run: bool = False
    approval_role: Optional[str] = None
    environment: str = "development"


# ---------------------------------------------------------------------------
# Tool safety classifications
# ---------------------------------------------------------------------------

# Tools are classified by their safety level.
# Unknown tools default to WRITE level.

_TOOL_SAFETY_MAP: Dict[str, ToolSafetyLevel] = {
    # Read-only tools
    "search": ToolSafetyLevel.READ_ONLY,
    "splunk_search": ToolSafetyLevel.READ_ONLY,
    "list_saved_searches": ToolSafetyLevel.READ_ONLY,
    "get_splunk_health": ToolSafetyLevel.READ_ONLY,
    "list_indexes": ToolSafetyLevel.READ_ONLY,
    "list_inputs": ToolSafetyLevel.READ_ONLY,
    "list_apps": ToolSafetyLevel.READ_ONLY,
    "list_users": ToolSafetyLevel.READ_ONLY,
    "get_license_info": ToolSafetyLevel.READ_ONLY,
    "get_cluster_health": ToolSafetyLevel.READ_ONLY,
    "list_deployment_apps": ToolSafetyLevel.READ_ONLY,
    "get_pipeline_status": ToolSafetyLevel.READ_ONLY,
    "validate_spl": ToolSafetyLevel.READ_ONLY,
    "explain_spl": ToolSafetyLevel.READ_ONLY,
    "knowledge_graph_query": ToolSafetyLevel.READ_ONLY,
    "collection_stats": ToolSafetyLevel.READ_ONLY,
    "health_check": ToolSafetyLevel.READ_ONLY,

    # Utility tools (side-effect-free transforms)
    "base64_encode": ToolSafetyLevel.READ_ONLY,
    "base64_decode": ToolSafetyLevel.READ_ONLY,
    "url_encode": ToolSafetyLevel.READ_ONLY,
    "url_decode": ToolSafetyLevel.READ_ONLY,
    "json_prettify": ToolSafetyLevel.READ_ONLY,
    "json_minify": ToolSafetyLevel.READ_ONLY,
    "timestamp_convert": ToolSafetyLevel.READ_ONLY,
    "uuid_generate": ToolSafetyLevel.READ_ONLY,
    "regex_test": ToolSafetyLevel.READ_ONLY,
    "md5": ToolSafetyLevel.READ_ONLY,
    "sha256": ToolSafetyLevel.READ_ONLY,

    # Internal write tools
    "update_config": ToolSafetyLevel.WRITE,
    "update_settings": ToolSafetyLevel.WRITE,
    "toggle_feature": ToolSafetyLevel.WRITE,
    "create_collection": ToolSafetyLevel.WRITE,
    "reindex_collection": ToolSafetyLevel.WRITE,
    "ingest_document": ToolSafetyLevel.WRITE,
    "create_backup": ToolSafetyLevel.WRITE,
    "update_prompt": ToolSafetyLevel.WRITE,

    # External write tools (Splunk/Cribl)
    "update_saved_search": ToolSafetyLevel.EXTERNAL_WRITE,
    "create_saved_search": ToolSafetyLevel.EXTERNAL_WRITE,
    "deploy_pipeline": ToolSafetyLevel.EXTERNAL_WRITE,
    "update_pipeline": ToolSafetyLevel.EXTERNAL_WRITE,
    "create_input": ToolSafetyLevel.EXTERNAL_WRITE,
    "update_input": ToolSafetyLevel.EXTERNAL_WRITE,
    "send_hec_event": ToolSafetyLevel.EXTERNAL_WRITE,

    # Destructive tools
    "delete_collection": ToolSafetyLevel.DESTRUCTIVE,
    "delete_index": ToolSafetyLevel.DESTRUCTIVE,
    "delete_saved_search": ToolSafetyLevel.DESTRUCTIVE,
    "delete_pipeline": ToolSafetyLevel.DESTRUCTIVE,
    "restart_container": ToolSafetyLevel.DESTRUCTIVE,
    "stop_container": ToolSafetyLevel.DESTRUCTIVE,
    "clear_cache": ToolSafetyLevel.DESTRUCTIVE,
    "rebuild_knowledge_graph": ToolSafetyLevel.DESTRUCTIVE,
    "delete_user": ToolSafetyLevel.DESTRUCTIVE,
    "restore_backup": ToolSafetyLevel.DESTRUCTIVE,
}


# ---------------------------------------------------------------------------
# Environment policies
# ---------------------------------------------------------------------------

# Per-environment rules: which safety levels require what action
_ENVIRONMENT_POLICIES: Dict[str, Dict[ToolSafetyLevel, PolicyAction]] = {
    "development": {
        ToolSafetyLevel.READ_ONLY: PolicyAction.ALLOW,
        ToolSafetyLevel.WRITE: PolicyAction.ALLOW,
        ToolSafetyLevel.EXTERNAL_WRITE: PolicyAction.REQUIRE_CONFIRMATION,
        ToolSafetyLevel.DESTRUCTIVE: PolicyAction.REQUIRE_CONFIRMATION,
    },
    "staging": {
        ToolSafetyLevel.READ_ONLY: PolicyAction.ALLOW,
        ToolSafetyLevel.WRITE: PolicyAction.ALLOW,
        ToolSafetyLevel.EXTERNAL_WRITE: PolicyAction.REQUIRE_CONFIRMATION,
        ToolSafetyLevel.DESTRUCTIVE: PolicyAction.REQUIRE_APPROVAL,
    },
    "production": {
        ToolSafetyLevel.READ_ONLY: PolicyAction.ALLOW,
        ToolSafetyLevel.WRITE: PolicyAction.REQUIRE_CONFIRMATION,
        ToolSafetyLevel.EXTERNAL_WRITE: PolicyAction.REQUIRE_APPROVAL,
        ToolSafetyLevel.DESTRUCTIVE: PolicyAction.REQUIRE_APPROVAL,
    },
}

# Role-based overrides: minimum role to bypass confirmation
_ROLE_BYPASS: Dict[ToolSafetyLevel, str] = {
    ToolSafetyLevel.READ_ONLY: "VIEWER",
    ToolSafetyLevel.WRITE: "ANALYST",
    ToolSafetyLevel.EXTERNAL_WRITE: "ADMIN",
    ToolSafetyLevel.DESTRUCTIVE: "ADMIN",  # Never auto-bypassed
}

_ROLE_HIERARCHY = {"VIEWER": 0, "USER": 1, "ANALYST": 2, "ADMIN": 3}


# ---------------------------------------------------------------------------
# Policy evaluation
# ---------------------------------------------------------------------------

def get_tool_safety_level(tool_name: str) -> ToolSafetyLevel:
    """Get the safety classification for a tool. Unknown tools default to WRITE."""
    return _TOOL_SAFETY_MAP.get(tool_name, ToolSafetyLevel.WRITE)


def evaluate_policy(
    tool_name: str,
    user_role: str = "USER",
    environment: str = "development",
    is_approved: bool = False,
    is_dry_run: bool = False,
) -> PolicyDecision:
    """Evaluate the safety policy for a tool execution.

    Args:
        tool_name: The tool to execute.
        user_role: The user's role (VIEWER, USER, ANALYST, ADMIN).
        environment: Deployment environment (development, staging, production).
        is_approved: Whether the action has been pre-approved.
        is_dry_run: Whether this is a dry-run request.

    Returns:
        PolicyDecision with the action to take.
    """
    safety_level = get_tool_safety_level(tool_name)

    # Dry run is always allowed
    if is_dry_run:
        return PolicyDecision(
            action=PolicyAction.ALLOW,
            tool_name=tool_name,
            safety_level=safety_level,
            reason="Dry run — no side effects",
            requires_dry_run=True,
            environment=environment,
        )

    # Pre-approved actions are allowed
    if is_approved:
        return PolicyDecision(
            action=PolicyAction.ALLOW,
            tool_name=tool_name,
            safety_level=safety_level,
            reason="Pre-approved by user/admin",
            environment=environment,
        )

    # Look up environment policy
    env_policy = _ENVIRONMENT_POLICIES.get(environment, _ENVIRONMENT_POLICIES["development"])
    base_action = env_policy.get(safety_level, PolicyAction.REQUIRE_CONFIRMATION)

    # Check if user's role allows bypassing confirmation
    if base_action == PolicyAction.REQUIRE_CONFIRMATION:
        bypass_role = _ROLE_BYPASS.get(safety_level, "ADMIN")
        user_level = _ROLE_HIERARCHY.get(user_role, 0)
        bypass_level = _ROLE_HIERARCHY.get(bypass_role, 3)
        if user_level >= bypass_level:
            base_action = PolicyAction.ALLOW

    # Destructive actions in production always require approval regardless of role
    if safety_level == ToolSafetyLevel.DESTRUCTIVE and environment == "production":
        base_action = PolicyAction.REQUIRE_APPROVAL

    reason_map = {
        PolicyAction.ALLOW: f"Allowed — {safety_level.value} tool in {environment}",
        PolicyAction.REQUIRE_CONFIRMATION: f"Confirmation required — {safety_level.value} tool in {environment}",
        PolicyAction.REQUIRE_APPROVAL: f"Admin approval required — {safety_level.value} tool in {environment}",
        PolicyAction.DENY: f"Denied — {safety_level.value} tool not allowed in {environment}",
    }

    return PolicyDecision(
        action=base_action,
        tool_name=tool_name,
        safety_level=safety_level,
        reason=reason_map.get(base_action, "Unknown"),
        requires_dry_run=(safety_level in (ToolSafetyLevel.EXTERNAL_WRITE, ToolSafetyLevel.DESTRUCTIVE)
                          and environment == "production"),
        approval_role="ADMIN" if base_action == PolicyAction.REQUIRE_APPROVAL else None,
        environment=environment,
    )


def classify_tool(tool_name: str, safety_level: ToolSafetyLevel) -> None:
    """Register or update a tool's safety classification."""
    _TOOL_SAFETY_MAP[tool_name] = safety_level
    logger.info("[SAFETY] Tool '%s' classified as %s", tool_name, safety_level.value)


def get_all_classifications() -> Dict[str, str]:
    """Return all tool safety classifications."""
    return {name: level.value for name, level in sorted(_TOOL_SAFETY_MAP.items())}


def get_environment_policies() -> Dict[str, Dict[str, str]]:
    """Return environment policies for documentation."""
    result = {}
    for env, policies in _ENVIRONMENT_POLICIES.items():
        result[env] = {level.value: action.value for level, action in policies.items()}
    return result
