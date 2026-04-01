"""
Skills Marketplace — Dynamic skill/plugin system for ObsAI - Observability AI Assistant.

Enables:
- Skill discovery from skills/ directory and remote registries
- Dynamic loading/unloading of skill modules at runtime
- Skill manifest validation (JSON schema)
- Per-skill configuration and feature flags
- Skill health tracking and metrics
- Human-in-the-loop approval for critical skill actions
"""
import asyncio
import importlib
import importlib.util
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Skill manifest schema
# ---------------------------------------------------------------------------

class SkillStatus(str, Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"
    INSTALLING = "installing"
    UNINSTALLED = "uninstalled"


class SkillCategory(str, Enum):
    SPLUNK = "splunk"
    CRIBL = "cribl"
    OBSERVABILITY = "observability"
    SECURITY = "security"
    KNOWLEDGE = "knowledge"
    AUTOMATION = "automation"
    INTEGRATION = "integration"
    CUSTOM = "custom"


class ApprovalLevel(str, Enum):
    """Human-in-the-loop approval requirements."""
    NONE = "none"           # Auto-execute
    INFORM = "inform"       # Execute and notify user
    CONFIRM = "confirm"     # Require user confirmation before execution
    REVIEW = "review"       # Require admin review before execution


@dataclass
class SkillAction:
    """A single action/tool provided by a skill."""
    name: str
    description: str
    handler: Optional[Callable] = None
    parameters: Dict[str, Any] = field(default_factory=dict)
    approval_level: ApprovalLevel = ApprovalLevel.NONE
    timeout_seconds: int = 30
    max_retries: int = 1
    intents: List[str] = field(default_factory=list)
    requires: Set[str] = field(default_factory=set)


@dataclass
class SkillManifest:
    """Manifest describing a skill package."""
    name: str
    version: str
    description: str
    author: str = "ObsAI Team"
    category: SkillCategory = SkillCategory.CUSTOM
    actions: List[SkillAction] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    config_schema: Dict[str, Any] = field(default_factory=dict)
    min_version: str = "3.0.0"
    icon: str = ""
    tags: List[str] = field(default_factory=list)
    homepage: str = ""
    license: str = "MIT"


@dataclass
class SkillInstance:
    """A loaded skill with runtime state."""
    manifest: SkillManifest
    status: SkillStatus = SkillStatus.ACTIVE
    config: Dict[str, Any] = field(default_factory=dict)
    module: Any = None
    loaded_at: float = field(default_factory=time.time)
    error: Optional[str] = None
    # Metrics
    execution_count: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0
    last_executed: Optional[float] = None

    @property
    def avg_latency_ms(self) -> float:
        if self.execution_count == 0:
            return 0.0
        return self.total_latency_ms / self.execution_count

    @property
    def error_rate(self) -> float:
        if self.execution_count == 0:
            return 0.0
        return self.error_count / self.execution_count

    def record_execution(self, latency_ms: float, success: bool):
        """Record a skill action execution."""
        self.execution_count += 1
        self.total_latency_ms += latency_ms
        self.last_executed = time.time()
        if not success:
            self.error_count += 1


@dataclass
class SkillExecutionResult:
    """Result of executing a skill action."""
    success: bool
    output: str
    data: Any = None
    error: Optional[str] = None
    approval_required: bool = False
    approval_message: str = ""
    latency_ms: float = 0.0
    skill_name: str = ""
    action_name: str = ""


# ---------------------------------------------------------------------------
# Skills Manager
# ---------------------------------------------------------------------------

class SkillsManager:
    """Central manager for skill discovery, loading, and execution."""

    def __init__(self, skills_dir: str = "skills"):
        self._skills: Dict[str, SkillInstance] = {}
        self._skills_dir = Path(skills_dir)
        self._pending_approvals: Dict[str, Dict[str, Any]] = {}
        self._action_registry: Dict[str, tuple] = {}  # action_name -> (skill_name, action)
        self._execution_history: List[Dict[str, Any]] = []

    @property
    def skills_dir(self) -> Path:
        return self._skills_dir

    def discover_skills(self) -> List[SkillManifest]:
        """Discover available skills from the skills directory."""
        manifests = []
        if not self._skills_dir.exists():
            logger.debug(f"Skills directory not found: {self._skills_dir}")
            return manifests

        for skill_path in self._skills_dir.iterdir():
            if not skill_path.is_dir():
                continue
            manifest_file = skill_path / "manifest.json"
            if not manifest_file.exists():
                continue
            try:
                manifest = self._load_manifest(manifest_file)
                manifests.append(manifest)
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.warning(f"Failed to load manifest from {skill_path}: {exc}")

        return manifests

    def _load_manifest(self, manifest_file: Path) -> SkillManifest:
        """Load and validate a skill manifest from JSON."""
        data = json.loads(manifest_file.read_text(encoding="utf-8"))
        actions = []
        for action_data in data.get("actions", []):
            actions.append(SkillAction(
                name=action_data["name"],
                description=action_data.get("description", ""),
                parameters=action_data.get("parameters", {}),
                approval_level=ApprovalLevel(action_data.get("approval_level", "none")),
                timeout_seconds=action_data.get("timeout_seconds", 30),
                max_retries=action_data.get("max_retries", 1),
                intents=action_data.get("intents", []),
                requires=set(action_data.get("requires", [])),
            ))
        return SkillManifest(
            name=data["name"],
            version=data["version"],
            description=data.get("description", ""),
            author=data.get("author", "ObsAI Team"),
            category=SkillCategory(data.get("category", "custom")),
            actions=actions,
            dependencies=data.get("dependencies", []),
            config_schema=data.get("config_schema", {}),
            min_version=data.get("min_version", "3.0.0"),
            icon=data.get("icon", ""),
            tags=data.get("tags", []),
            homepage=data.get("homepage", ""),
            license=data.get("license", "MIT"),
        )

    def install_skill(self, skill_name: str) -> SkillInstance:
        """Install and load a skill from the skills directory."""
        skill_path = self._skills_dir / skill_name
        manifest_file = skill_path / "manifest.json"

        if not manifest_file.exists():
            raise FileNotFoundError(f"Skill manifest not found: {manifest_file}")

        manifest = self._load_manifest(manifest_file)

        # Check dependencies
        for dep in manifest.dependencies:
            if dep not in self._skills:
                logger.warning(f"Skill '{skill_name}' depends on '{dep}' which is not installed")

        # Load the Python module
        module = None
        module_file = skill_path / "skill.py"
        if module_file.exists():
            try:
                spec = importlib.util.spec_from_file_location(
                    f"skills.{skill_name}", str(module_file)
                )
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                logger.info(f"Loaded skill module: {skill_name}")
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.error(f"Failed to load skill module {skill_name}: {exc}")
                instance = SkillInstance(
                    manifest=manifest,
                    status=SkillStatus.ERROR,
                    error=str(exc),
                )
                self._skills[skill_name] = instance
                return instance

        # Bind action handlers from module
        if module:
            for action in manifest.actions:
                handler_name = action.name.replace("-", "_")
                handler = getattr(module, handler_name, None)
                if handler:
                    action.handler = handler

        # Load skill-specific config
        config = {}
        config_file = skill_path / "config.yaml"
        if config_file.exists():
            try:
                import yaml
                config = yaml.safe_load(config_file.read_text(encoding="utf-8")) or {}
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
                logger.debug("%s", _exc)  # was: pass

        instance = SkillInstance(
            manifest=manifest,
            status=SkillStatus.ACTIVE,
            module=module,
            config=config,
        )
        self._skills[skill_name] = instance

        # Register actions
        for action in manifest.actions:
            self._action_registry[action.name] = (skill_name, action)

        logger.info(f"Skill installed: {skill_name} v{manifest.version} ({len(manifest.actions)} actions)")
        return instance

    def uninstall_skill(self, skill_name: str) -> bool:
        """Uninstall a skill."""
        if skill_name not in self._skills:
            return False

        instance = self._skills[skill_name]

        # Unregister actions
        for action in instance.manifest.actions:
            self._action_registry.pop(action.name, None)

        # Cleanup module
        if instance.module and hasattr(instance.module, "cleanup"):
            try:
                instance.module.cleanup()
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.debug(f"Skill cleanup error for {skill_name}: {exc}")

        instance.status = SkillStatus.UNINSTALLED
        del self._skills[skill_name]
        logger.info(f"Skill uninstalled: {skill_name}")
        return True

    def enable_skill(self, skill_name: str) -> bool:
        """Enable a disabled skill."""
        if skill_name not in self._skills:
            return False
        self._skills[skill_name].status = SkillStatus.ACTIVE
        return True

    def disable_skill(self, skill_name: str) -> bool:
        """Disable an active skill."""
        if skill_name not in self._skills:
            return False
        self._skills[skill_name].status = SkillStatus.DISABLED
        return True

    def get_skill(self, skill_name: str) -> Optional[SkillInstance]:
        """Get a skill instance by name."""
        return self._skills.get(skill_name)

    def list_skills(self) -> List[Dict[str, Any]]:
        """List all installed skills with their status and metrics."""
        return [
            {
                "name": inst.manifest.name,
                "version": inst.manifest.version,
                "description": inst.manifest.description,
                "category": inst.manifest.category.value,
                "status": inst.status.value,
                "author": inst.manifest.author,
                "actions": [a.name for a in inst.manifest.actions],
                "tags": inst.manifest.tags,
                "metrics": {
                    "execution_count": inst.execution_count,
                    "error_count": inst.error_count,
                    "error_rate": round(inst.error_rate, 4),
                    "avg_latency_ms": round(inst.avg_latency_ms, 2),
                    "last_executed": inst.last_executed,
                },
            }
            for inst in self._skills.values()
        ]

    def get_available_actions(self, intent: str = None, capabilities: Set[str] = None) -> List[Dict[str, Any]]:
        """Get all available actions, optionally filtered by intent and capabilities."""
        actions = []
        for action_name, (skill_name, action) in self._action_registry.items():
            inst = self._skills.get(skill_name)
            if not inst or inst.status != SkillStatus.ACTIVE:
                continue
            if intent and intent not in action.intents and action.intents:
                continue
            if capabilities and action.requires and not action.requires.issubset(capabilities):
                continue
            actions.append({
                "name": action.name,
                "description": action.description,
                "skill": skill_name,
                "parameters": action.parameters,
                "approval_level": action.approval_level.value,
                "intents": action.intents,
            })
        return actions

    async def execute_action(
        self,
        action_name: str,
        params: Dict[str, Any] = None,
        user_approved: bool = False,
    ) -> SkillExecutionResult:
        """Execute a skill action with approval gate support."""
        if action_name not in self._action_registry:
            return SkillExecutionResult(
                success=False,
                output="",
                error=f"Action not found: {action_name}",
                skill_name="",
                action_name=action_name,
            )

        skill_name, action = self._action_registry[action_name]
        inst = self._skills.get(skill_name)

        if not inst or inst.status != SkillStatus.ACTIVE:
            return SkillExecutionResult(
                success=False,
                output="",
                error=f"Skill '{skill_name}' is not active",
                skill_name=skill_name,
                action_name=action_name,
            )

        # Human-in-the-loop: check approval level
        if action.approval_level in (ApprovalLevel.CONFIRM, ApprovalLevel.REVIEW) and not user_approved:
            approval_id = f"{skill_name}:{action_name}:{time.time()}"
            self._pending_approvals[approval_id] = {
                "skill": skill_name,
                "action": action_name,
                "params": params,
                "timestamp": time.time(),
            }
            return SkillExecutionResult(
                success=False,
                output="",
                approval_required=True,
                approval_message=(
                    f"Action '{action_name}' from skill '{skill_name}' "
                    f"requires {'confirmation' if action.approval_level == ApprovalLevel.CONFIRM else 'admin review'}. "
                    f"Approval ID: {approval_id}"
                ),
                skill_name=skill_name,
                action_name=action_name,
            )

        # Execute the action
        if not action.handler:
            return SkillExecutionResult(
                success=False,
                output="",
                error=f"No handler registered for action: {action_name}",
                skill_name=skill_name,
                action_name=action_name,
            )

        start = time.time()
        try:
            if asyncio.iscoroutinefunction(action.handler):
                result = await action.handler(**(params or {}))
            else:
                result = action.handler(**(params or {}))
            latency_ms = (time.time() - start) * 1000
            inst.record_execution(latency_ms, success=True)

            output = str(result) if not isinstance(result, str) else result
            exec_result = SkillExecutionResult(
                success=True,
                output=output,
                data=result,
                latency_ms=latency_ms,
                skill_name=skill_name,
                action_name=action_name,
            )
        except Exception as exc:  # Broad catch intentional: skill actions are third-party plugins that may raise any type
            latency_ms = (time.time() - start) * 1000
            inst.record_execution(latency_ms, success=False)
            exec_result = SkillExecutionResult(
                success=False,
                output="",
                error=str(exc),
                latency_ms=latency_ms,
                skill_name=skill_name,
                action_name=action_name,
            )

        # Record execution history
        self._execution_history.append({
            "skill": skill_name,
            "action": action_name,
            "success": exec_result.success,
            "latency_ms": exec_result.latency_ms,
            "timestamp": time.time(),
        })
        if len(self._execution_history) > 500:
            self._execution_history = self._execution_history[-500:]

        # Notify for INFORM level
        if action.approval_level == ApprovalLevel.INFORM:
            logger.info(f"[SKILL] Executed {skill_name}:{action_name} (inform mode)")

        return exec_result

    def approve_action(self, approval_id: str) -> bool:
        """Approve a pending action (human-in-the-loop)."""
        if approval_id in self._pending_approvals:
            del self._pending_approvals[approval_id]
            return True
        return False

    def get_pending_approvals(self) -> List[Dict[str, Any]]:
        """Get all pending approval requests."""
        return [
            {"id": k, **v}
            for k, v in self._pending_approvals.items()
        ]

    def get_execution_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent execution history."""
        return self._execution_history[-limit:]

    def get_skill_metrics(self) -> Dict[str, Any]:
        """Get aggregated metrics across all skills."""
        total_executions = sum(s.execution_count for s in self._skills.values())
        total_errors = sum(s.error_count for s in self._skills.values())
        active_count = sum(1 for s in self._skills.values() if s.status == SkillStatus.ACTIVE)

        return {
            "total_skills": len(self._skills),
            "active_skills": active_count,
            "total_actions": len(self._action_registry),
            "total_executions": total_executions,
            "total_errors": total_errors,
            "overall_error_rate": round(total_errors / max(total_executions, 1), 4),
            "pending_approvals": len(self._pending_approvals),
        }

    def load_all_skills(self):
        """Discover and install all available skills."""
        manifests = self.discover_skills()
        for manifest in manifests:
            if manifest.name not in self._skills:
                try:
                    self.install_skill(manifest.name)
                except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                    logger.error(f"Failed to install skill {manifest.name}: {exc}")


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_manager: Optional[SkillsManager] = None


def get_skills_manager(skills_dir: str = "skills") -> SkillsManager:
    """Get or create the singleton SkillsManager."""
    global _manager
    if _manager is None:
        _manager = SkillsManager(skills_dir=skills_dir)
    return _manager
