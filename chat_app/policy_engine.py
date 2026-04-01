"""Policy-as-Code Engine — OPA-style rules for RBAC, approvals, and environment constraints.

Defines declarative policies that govern tool execution:
- **RBAC rules**: Who can do what (checked before execution)
- **Approval rules**: Which actions need approval and from whom
- **Environment rules**: What's allowed in dev/staging/production
- **Change window rules**: Time-based restrictions (e.g., no deploys during business hours)
- **Rate rules**: Per-user/per-tool execution limits

Policies are evaluated as a chain: all must pass for execution to proceed.

Usage:
    from chat_app.policy_engine import get_policy_engine, PolicyContext

    engine = get_policy_engine()
    ctx = PolicyContext(
        tool="deploy_pipeline",
        actor="analyst@example.com",
        role="ANALYST",
        environment="production",
    )
    result = engine.evaluate(ctx)
    if not result.allowed:
        print(f"Denied: {result.denial_reasons}")
"""

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Policy Context — input to policy evaluation
# ---------------------------------------------------------------------------

@dataclass
class PolicyContext:
    """Input context for policy evaluation."""
    tool: str
    actor: str
    role: str = "USER"
    environment: str = "development"
    target_resource: str = ""
    action: str = "execute"
    is_dry_run: bool = False
    is_approved: bool = False
    approval_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Policy Result
# ---------------------------------------------------------------------------

@dataclass
class PolicyResult:
    """Result of evaluating all policies against a context."""
    allowed: bool
    denial_reasons: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    requires_approval: bool = False
    approval_level: str = ""  # ADMIN, ANALYST, etc.
    applied_policies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "allowed": self.allowed,
            "denial_reasons": self.denial_reasons,
            "warnings": self.warnings,
            "requires_approval": self.requires_approval,
            "approval_level": self.approval_level,
            "applied_policies": self.applied_policies,
        }


# ---------------------------------------------------------------------------
# Policy Rule
# ---------------------------------------------------------------------------

class PolicyType(str, Enum):
    RBAC = "rbac"
    APPROVAL = "approval"
    ENVIRONMENT = "environment"
    CHANGE_WINDOW = "change_window"
    RATE = "rate"
    CUSTOM = "custom"


@dataclass
class PolicyRule:
    """A single declarative policy rule."""
    name: str
    description: str
    policy_type: PolicyType
    enabled: bool = True
    priority: int = 100  # Lower = evaluated first
    condition: Optional[Callable[[PolicyContext], bool]] = None
    effect: str = "deny"  # deny, require_approval, warn
    approval_level: str = ""
    tools: Set[str] = field(default_factory=set)  # Empty = all tools
    environments: Set[str] = field(default_factory=set)  # Empty = all environments
    roles: Set[str] = field(default_factory=set)  # Roles this rule applies TO (empty = all)

    def applies_to(self, ctx: PolicyContext) -> bool:
        """Check if this rule applies to the given context."""
        if not self.enabled:
            return False
        if self.tools and ctx.tool not in self.tools:
            return False
        if self.environments and ctx.environment not in self.environments:
            return False
        if self.roles and ctx.role not in self.roles:
            return False
        return True

    def evaluate(self, ctx: PolicyContext) -> Optional[str]:
        """Evaluate the rule. Returns denial reason, or None if passed."""
        if self.condition and not self.condition(ctx):
            return None  # Condition not met — rule doesn't trigger
        if self.condition is None:
            return None  # No condition = always passes
        return f"Policy '{self.name}': {self.description}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "type": self.policy_type.value,
            "enabled": self.enabled,
            "priority": self.priority,
            "effect": self.effect,
            "approval_level": self.approval_level,
            "tools": sorted(self.tools) if self.tools else ["*"],
            "environments": sorted(self.environments) if self.environments else ["*"],
            "roles": sorted(self.roles) if self.roles else ["*"],
        }


# ---------------------------------------------------------------------------
# Built-in policies
# ---------------------------------------------------------------------------

def _is_destructive(ctx: PolicyContext) -> bool:
    from chat_app.safety_policies import get_tool_safety_level, ToolSafetyLevel
    return get_tool_safety_level(ctx.tool) == ToolSafetyLevel.DESTRUCTIVE


def _is_external_write(ctx: PolicyContext) -> bool:
    from chat_app.safety_policies import get_tool_safety_level, ToolSafetyLevel
    return get_tool_safety_level(ctx.tool) == ToolSafetyLevel.EXTERNAL_WRITE


def _is_weekend(ctx: PolicyContext) -> bool:
    now = datetime.now(timezone.utc)
    return now.weekday() >= 5  # Saturday=5, Sunday=6


def _is_business_hours(ctx: PolicyContext) -> bool:
    now = datetime.now(timezone.utc)
    return 14 <= now.hour <= 23  # 9am-6pm EST in UTC


_BUILTIN_POLICIES: List[PolicyRule] = [
    # Destructive actions in production require admin approval
    PolicyRule(
        name="prod_destructive_approval",
        description="Destructive actions in production require ADMIN approval",
        policy_type=PolicyType.APPROVAL,
        condition=_is_destructive,
        effect="require_approval",
        approval_level="ADMIN",
        environments={"production"},
        priority=10,
    ),
    # External writes in production require approval
    PolicyRule(
        name="prod_external_write_approval",
        description="External system writes in production require ADMIN approval",
        policy_type=PolicyType.APPROVAL,
        condition=_is_external_write,
        effect="require_approval",
        approval_level="ADMIN",
        environments={"production"},
        priority=20,
    ),
    # No destructive actions on weekends (production)
    PolicyRule(
        name="weekend_freeze",
        description="Destructive actions blocked during weekends in production",
        policy_type=PolicyType.CHANGE_WINDOW,
        condition=lambda ctx: _is_destructive(ctx) and _is_weekend(ctx),
        effect="deny",
        environments={"production"},
        priority=5,
    ),
    # Viewer role cannot execute write tools
    PolicyRule(
        name="viewer_no_writes",
        description="VIEWER role cannot execute write or destructive tools",
        policy_type=PolicyType.RBAC,
        condition=lambda ctx: (
            not ctx.is_dry_run and
            get_tool_safety_level_safe(ctx.tool) in ("write", "external_write", "destructive")
        ),
        effect="deny",
        roles={"VIEWER"},
        priority=1,
    ),
    # Warn on staging destructive actions
    PolicyRule(
        name="staging_destructive_warn",
        description="Destructive actions in staging generate a warning",
        policy_type=PolicyType.ENVIRONMENT,
        condition=_is_destructive,
        effect="warn",
        environments={"staging"},
        priority=50,
    ),
]


def get_tool_safety_level_safe(tool: str) -> str:
    """Safe wrapper to get tool safety level without import errors."""
    try:
        from chat_app.safety_policies import get_tool_safety_level
        return get_tool_safety_level(tool).value
    except Exception as _exc:  # broad catch — resilience against all failures
        return "write"


# ---------------------------------------------------------------------------
# Policy Engine
# ---------------------------------------------------------------------------

class PolicyEngine:
    """Evaluates declarative policies against execution contexts."""

    def __init__(self):
        self._rules: List[PolicyRule] = list(_BUILTIN_POLICIES)
        self._lock = threading.Lock()
        self._evaluation_count = 0
        self._denial_count = 0

    def evaluate(self, ctx: PolicyContext) -> PolicyResult:
        """Evaluate all applicable policies for a context.

        Returns a PolicyResult with allowed/denied status and reasons.
        Dry-run requests always pass (no side effects).
        Pre-approved requests skip approval rules.
        """
        self._evaluation_count += 1

        # Dry runs always pass
        if ctx.is_dry_run:
            return PolicyResult(
                allowed=True,
                applied_policies=["dry_run_bypass"],
            )

        result = PolicyResult(allowed=True)

        # Sort by priority (lower first)
        sorted_rules = sorted(self._rules, key=lambda r: r.priority)

        for rule in sorted_rules:
            if not rule.applies_to(ctx):
                continue

            # Evaluate condition
            if rule.condition and rule.condition(ctx):
                result.applied_policies.append(rule.name)

                if rule.effect == "deny":
                    if not ctx.is_approved:
                        result.allowed = False
                        result.denial_reasons.append(
                            f"[{rule.name}] {rule.description}"
                        )
                elif rule.effect == "require_approval":
                    if not ctx.is_approved:
                        result.requires_approval = True
                        result.approval_level = rule.approval_level or "ADMIN"
                        result.warnings.append(
                            f"[{rule.name}] Approval required: {rule.description}"
                        )
                elif rule.effect == "warn":
                    result.warnings.append(
                        f"[{rule.name}] Warning: {rule.description}"
                    )

        if not result.allowed:
            self._denial_count += 1

        return result

    def add_rule(self, rule: PolicyRule) -> None:
        """Add a custom policy rule."""
        with self._lock:
            self._rules.append(rule)
        logger.info("[POLICY] Added rule: %s (type=%s, effect=%s)", rule.name, rule.policy_type.value, rule.effect)

    def remove_rule(self, name: str) -> bool:
        """Remove a policy rule by name."""
        with self._lock:
            before = len(self._rules)
            self._rules = [r for r in self._rules if r.name != name]
            removed = len(self._rules) < before
        if removed:
            logger.info("[POLICY] Removed rule: %s", name)
        return removed

    def enable_rule(self, name: str) -> bool:
        """Enable a policy rule."""
        for rule in self._rules:
            if rule.name == name:
                rule.enabled = True
                return True
        return False

    def disable_rule(self, name: str) -> bool:
        """Disable a policy rule."""
        for rule in self._rules:
            if rule.name == name:
                rule.enabled = False
                return True
        return False

    def get_all_rules(self) -> List[Dict[str, Any]]:
        """Get all policy rules."""
        return [r.to_dict() for r in sorted(self._rules, key=lambda r: r.priority)]

    def get_stats(self) -> Dict[str, Any]:
        """Get policy engine statistics."""
        enabled = sum(1 for r in self._rules if r.enabled)
        by_type: Dict[str, int] = {}
        for r in self._rules:
            by_type[r.policy_type.value] = by_type.get(r.policy_type.value, 0) + 1
        return {
            "total_rules": len(self._rules),
            "enabled_rules": enabled,
            "disabled_rules": len(self._rules) - enabled,
            "by_type": by_type,
            "total_evaluations": self._evaluation_count,
            "total_denials": self._denial_count,
            "denial_rate": round(self._denial_count / max(self._evaluation_count, 1), 3),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[PolicyEngine] = None
_engine_lock = threading.Lock()


def get_policy_engine() -> PolicyEngine:
    """Get the global PolicyEngine singleton."""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = PolicyEngine()
    return _engine_instance
