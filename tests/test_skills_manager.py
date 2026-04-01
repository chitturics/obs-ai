"""Comprehensive unit tests for chat_app.skills_manager."""
import json
import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from chat_app.skills_manager import (
    ApprovalLevel,
    SkillAction,
    SkillCategory,
    SkillExecutionResult,
    SkillInstance,
    SkillManifest,
    SkillsManager,
    SkillStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manifest(name="test_skill", version="1.0.0", **kwargs):
    """Create a SkillManifest with sensible defaults."""
    return SkillManifest(
        name=name,
        version=version,
        description=kwargs.get("description", "A test skill"),
        author=kwargs.get("author", "Tester"),
        category=kwargs.get("category", SkillCategory.CUSTOM),
        actions=kwargs.get("actions", []),
        dependencies=kwargs.get("dependencies", []),
        tags=kwargs.get("tags", []),
    )


def _make_action(name="do_thing", approval_level=ApprovalLevel.NONE, handler=None, **kw):
    return SkillAction(
        name=name,
        description=kw.get("description", "does a thing"),
        handler=handler,
        approval_level=approval_level,
        intents=kw.get("intents", []),
        requires=kw.get("requires", set()),
    )


def _write_manifest(skills_dir: Path, skill_name: str, manifest_dict: dict):
    """Write a manifest.json inside skills_dir/skill_name/."""
    skill_path = skills_dir / skill_name
    skill_path.mkdir(parents=True, exist_ok=True)
    (skill_path / "manifest.json").write_text(json.dumps(manifest_dict), encoding="utf-8")
    return skill_path


# ---------------------------------------------------------------------------
# SkillManifest creation & validation
# ---------------------------------------------------------------------------

class TestSkillManifest:
    def test_create_minimal(self):
        m = SkillManifest(name="x", version="0.1", description="desc")
        assert m.name == "x"
        assert m.version == "0.1"
        assert m.author == "ObsAI Team"
        assert m.category == SkillCategory.CUSTOM
        assert m.actions == []
        assert m.license == "MIT"

    def test_create_with_all_fields(self):
        action = _make_action()
        m = _make_manifest(
            name="full",
            version="2.0.0",
            description="Full skill",
            author="Author",
            category=SkillCategory.SECURITY,
            actions=[action],
            dependencies=["base_skill"],
            tags=["tag1", "tag2"],
        )
        assert m.name == "full"
        assert m.category == SkillCategory.SECURITY
        assert len(m.actions) == 1
        assert m.dependencies == ["base_skill"]
        assert m.tags == ["tag1", "tag2"]

    def test_skill_category_values(self):
        assert SkillCategory.SPLUNK.value == "splunk"
        assert SkillCategory.CRIBL.value == "cribl"
        assert SkillCategory.OBSERVABILITY.value == "observability"
        assert SkillCategory.INTEGRATION.value == "integration"

    def test_approval_level_values(self):
        assert ApprovalLevel.NONE.value == "none"
        assert ApprovalLevel.INFORM.value == "inform"
        assert ApprovalLevel.CONFIRM.value == "confirm"
        assert ApprovalLevel.REVIEW.value == "review"


# ---------------------------------------------------------------------------
# SkillInstance state management
# ---------------------------------------------------------------------------

class TestSkillInstance:
    def test_default_state(self):
        m = _make_manifest()
        inst = SkillInstance(manifest=m)
        assert inst.status == SkillStatus.ACTIVE
        assert inst.execution_count == 0
        assert inst.error_count == 0
        assert inst.avg_latency_ms == 0.0
        assert inst.error_rate == 0.0
        assert inst.last_executed is None

    def test_record_execution_success(self):
        inst = SkillInstance(manifest=_make_manifest())
        inst.record_execution(latency_ms=120.0, success=True)
        assert inst.execution_count == 1
        assert inst.error_count == 0
        assert inst.avg_latency_ms == 120.0
        assert inst.error_rate == 0.0
        assert inst.last_executed is not None

    def test_record_execution_failure(self):
        inst = SkillInstance(manifest=_make_manifest())
        inst.record_execution(latency_ms=50.0, success=False)
        assert inst.execution_count == 1
        assert inst.error_count == 1
        assert inst.error_rate == 1.0

    def test_avg_latency_multiple(self):
        inst = SkillInstance(manifest=_make_manifest())
        inst.record_execution(100.0, True)
        inst.record_execution(200.0, True)
        inst.record_execution(300.0, False)
        assert inst.execution_count == 3
        assert inst.avg_latency_ms == pytest.approx(200.0)
        assert inst.error_rate == pytest.approx(1 / 3)

    def test_error_state(self):
        inst = SkillInstance(manifest=_make_manifest(), status=SkillStatus.ERROR, error="boom")
        assert inst.status == SkillStatus.ERROR
        assert inst.error == "boom"


# ---------------------------------------------------------------------------
# SkillsManager — discover_skills
# ---------------------------------------------------------------------------

class TestDiscoverSkills:
    def test_discover_empty_dir(self, tmp_path):
        mgr = SkillsManager(skills_dir=str(tmp_path))
        assert mgr.discover_skills() == []

    def test_discover_nonexistent_dir(self, tmp_path):
        mgr = SkillsManager(skills_dir=str(tmp_path / "nonexistent"))
        assert mgr.discover_skills() == []

    def test_discover_valid_manifest(self, tmp_path):
        _write_manifest(tmp_path, "skill_a", {
            "name": "skill_a",
            "version": "1.0.0",
            "description": "Skill A",
            "actions": [{"name": "act1", "description": "action one"}],
        })
        mgr = SkillsManager(skills_dir=str(tmp_path))
        manifests = mgr.discover_skills()
        assert len(manifests) == 1
        assert manifests[0].name == "skill_a"
        assert len(manifests[0].actions) == 1

    def test_discover_skips_files(self, tmp_path):
        """Files in skills_dir (not dirs) should be ignored."""
        (tmp_path / "readme.txt").write_text("hello")
        mgr = SkillsManager(skills_dir=str(tmp_path))
        assert mgr.discover_skills() == []

    def test_discover_skips_dir_without_manifest(self, tmp_path):
        (tmp_path / "no_manifest_skill").mkdir()
        mgr = SkillsManager(skills_dir=str(tmp_path))
        assert mgr.discover_skills() == []

    def test_discover_multiple_skills(self, tmp_path):
        for name in ("alpha", "beta", "gamma"):
            _write_manifest(tmp_path, name, {
                "name": name,
                "version": "0.1.0",
                "description": f"Skill {name}",
            })
        mgr = SkillsManager(skills_dir=str(tmp_path))
        manifests = mgr.discover_skills()
        assert len(manifests) == 3
        names = {m.name for m in manifests}
        assert names == {"alpha", "beta", "gamma"}


# ---------------------------------------------------------------------------
# SkillsManager — install / uninstall
# ---------------------------------------------------------------------------

class TestInstallUninstall:
    def test_install_from_manifest(self, tmp_path):
        _write_manifest(tmp_path, "my_skill", {
            "name": "my_skill",
            "version": "1.2.0",
            "description": "My Skill",
            "category": "security",
            "actions": [
                {"name": "scan", "description": "run scan", "approval_level": "confirm"},
            ],
        })
        mgr = SkillsManager(skills_dir=str(tmp_path))
        inst = mgr.install_skill("my_skill")
        assert inst.status == SkillStatus.ACTIVE
        assert inst.manifest.name == "my_skill"
        assert inst.manifest.category == SkillCategory.SECURITY
        assert len(inst.manifest.actions) == 1
        assert inst.manifest.actions[0].approval_level == ApprovalLevel.CONFIRM
        # Verify it is listed
        skills = mgr.list_skills()
        assert len(skills) == 1
        assert skills[0]["name"] == "my_skill"

    def test_install_not_found(self, tmp_path):
        mgr = SkillsManager(skills_dir=str(tmp_path))
        with pytest.raises(FileNotFoundError):
            mgr.install_skill("nonexistent")

    def test_install_with_module_load_error(self, tmp_path):
        _write_manifest(tmp_path, "bad", {
            "name": "bad",
            "version": "0.0.1",
            "description": "Bad skill",
        })
        # Write a skill.py that raises on import
        (tmp_path / "bad" / "skill.py").write_text("raise RuntimeError('broken')")
        mgr = SkillsManager(skills_dir=str(tmp_path))
        inst = mgr.install_skill("bad")
        assert inst.status == SkillStatus.ERROR
        assert "broken" in inst.error

    def test_uninstall_existing(self, tmp_path):
        _write_manifest(tmp_path, "removable", {
            "name": "removable",
            "version": "1.0.0",
            "description": "Removable",
            "actions": [{"name": "act1", "description": "a1"}],
        })
        mgr = SkillsManager(skills_dir=str(tmp_path))
        mgr.install_skill("removable")
        assert mgr.get_skill("removable") is not None
        result = mgr.uninstall_skill("removable")
        assert result is True
        assert mgr.get_skill("removable") is None
        # Action should be deregistered
        assert mgr.get_available_actions() == []

    def test_uninstall_nonexistent(self, tmp_path):
        mgr = SkillsManager(skills_dir=str(tmp_path))
        assert mgr.uninstall_skill("ghost") is False

    def test_uninstall_calls_cleanup(self, tmp_path):
        _write_manifest(tmp_path, "cleanable", {
            "name": "cleanable",
            "version": "1.0.0",
            "description": "Has cleanup",
        })
        mgr = SkillsManager(skills_dir=str(tmp_path))
        inst = mgr.install_skill("cleanable")
        mock_module = MagicMock()
        inst.module = mock_module
        mgr.uninstall_skill("cleanable")
        mock_module.cleanup.assert_called_once()


# ---------------------------------------------------------------------------
# SkillsManager — enable / disable
# ---------------------------------------------------------------------------

class TestEnableDisable:
    def test_disable_active_skill(self, tmp_path):
        _write_manifest(tmp_path, "s1", {"name": "s1", "version": "1.0", "description": "s1"})
        mgr = SkillsManager(skills_dir=str(tmp_path))
        mgr.install_skill("s1")
        assert mgr.disable_skill("s1") is True
        assert mgr.get_skill("s1").status == SkillStatus.DISABLED

    def test_enable_disabled_skill(self, tmp_path):
        _write_manifest(tmp_path, "s2", {"name": "s2", "version": "1.0", "description": "s2"})
        mgr = SkillsManager(skills_dir=str(tmp_path))
        mgr.install_skill("s2")
        mgr.disable_skill("s2")
        assert mgr.enable_skill("s2") is True
        assert mgr.get_skill("s2").status == SkillStatus.ACTIVE

    def test_enable_nonexistent(self, tmp_path):
        mgr = SkillsManager(skills_dir=str(tmp_path))
        assert mgr.enable_skill("nope") is False

    def test_disable_nonexistent(self, tmp_path):
        mgr = SkillsManager(skills_dir=str(tmp_path))
        assert mgr.disable_skill("nope") is False


# ---------------------------------------------------------------------------
# SkillsManager — execute_action with approval levels
# ---------------------------------------------------------------------------

class TestExecuteAction:
    @pytest.fixture
    def mgr_with_actions(self, tmp_path):
        _write_manifest(tmp_path, "tool", {
            "name": "tool",
            "version": "1.0",
            "description": "tool skill",
            "actions": [
                {"name": "auto_act", "description": "auto", "approval_level": "none"},
                {"name": "inform_act", "description": "inform", "approval_level": "inform"},
                {"name": "confirm_act", "description": "confirm", "approval_level": "confirm"},
                {"name": "review_act", "description": "review", "approval_level": "review"},
            ],
        })
        mgr = SkillsManager(skills_dir=str(tmp_path))
        inst = mgr.install_skill("tool")
        # Attach handlers
        for action in inst.manifest.actions:
            action.handler = lambda **kw: "ok"
        return mgr

    @pytest.mark.asyncio
    async def test_execute_none_approval(self, mgr_with_actions):
        result = await mgr_with_actions.execute_action("auto_act")
        assert result.success is True
        assert result.output == "ok"

    @pytest.mark.asyncio
    async def test_execute_inform_level(self, mgr_with_actions):
        result = await mgr_with_actions.execute_action("inform_act")
        assert result.success is True
        assert result.approval_required is False

    @pytest.mark.asyncio
    async def test_execute_confirm_requires_approval(self, mgr_with_actions):
        result = await mgr_with_actions.execute_action("confirm_act")
        assert result.success is False
        assert result.approval_required is True
        assert "confirmation" in result.approval_message

    @pytest.mark.asyncio
    async def test_execute_review_requires_approval(self, mgr_with_actions):
        result = await mgr_with_actions.execute_action("review_act")
        assert result.success is False
        assert result.approval_required is True
        assert "admin review" in result.approval_message

    @pytest.mark.asyncio
    async def test_execute_confirm_with_user_approved(self, mgr_with_actions):
        result = await mgr_with_actions.execute_action("confirm_act", user_approved=True)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_execute_action_not_found(self, mgr_with_actions):
        result = await mgr_with_actions.execute_action("nonexistent_action")
        assert result.success is False
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_execute_action_skill_disabled(self, mgr_with_actions):
        mgr_with_actions.disable_skill("tool")
        result = await mgr_with_actions.execute_action("auto_act")
        assert result.success is False
        assert "not active" in result.error

    @pytest.mark.asyncio
    async def test_execute_no_handler(self, tmp_path):
        _write_manifest(tmp_path, "nohandler", {
            "name": "nohandler",
            "version": "1.0",
            "description": "no handler",
            "actions": [{"name": "ghost_act", "description": "no handler"}],
        })
        mgr = SkillsManager(skills_dir=str(tmp_path))
        mgr.install_skill("nohandler")
        result = await mgr.execute_action("ghost_act")
        assert result.success is False
        assert "No handler" in result.error

    @pytest.mark.asyncio
    async def test_execute_handler_exception(self, tmp_path):
        _write_manifest(tmp_path, "failing", {
            "name": "failing",
            "version": "1.0",
            "description": "fails",
            "actions": [{"name": "fail_act", "description": "fails"}],
        })
        mgr = SkillsManager(skills_dir=str(tmp_path))
        inst = mgr.install_skill("failing")
        inst.manifest.actions[0].handler = lambda **kw: (_ for _ in ()).throw(ValueError("handler error"))
        result = await mgr.execute_action("fail_act")
        assert result.success is False
        assert "handler error" in result.error
        assert inst.error_count == 1


# ---------------------------------------------------------------------------
# SkillsManager — metrics and history
# ---------------------------------------------------------------------------

class TestMetricsAndHistory:
    @pytest.mark.asyncio
    async def test_get_skill_metrics(self, tmp_path):
        _write_manifest(tmp_path, "m1", {
            "name": "m1", "version": "1.0", "description": "m1",
            "actions": [{"name": "a1", "description": "a1"}],
        })
        mgr = SkillsManager(skills_dir=str(tmp_path))
        inst = mgr.install_skill("m1")
        inst.manifest.actions[0].handler = lambda **kw: "done"
        await mgr.execute_action("a1")
        metrics = mgr.get_skill_metrics()
        assert metrics["total_skills"] == 1
        assert metrics["active_skills"] == 1
        assert metrics["total_actions"] == 1
        assert metrics["total_executions"] == 1
        assert metrics["total_errors"] == 0

    @pytest.mark.asyncio
    async def test_execution_history(self, tmp_path):
        _write_manifest(tmp_path, "h1", {
            "name": "h1", "version": "1.0", "description": "h1",
            "actions": [{"name": "hist_act", "description": "h"}],
        })
        mgr = SkillsManager(skills_dir=str(tmp_path))
        inst = mgr.install_skill("h1")
        inst.manifest.actions[0].handler = lambda **kw: "result"
        await mgr.execute_action("hist_act")
        history = mgr.get_execution_history()
        assert len(history) == 1
        assert history[0]["action"] == "hist_act"
        assert history[0]["success"] is True

    @pytest.mark.asyncio
    async def test_execution_history_limit(self, tmp_path):
        _write_manifest(tmp_path, "lim", {
            "name": "lim", "version": "1.0", "description": "lim",
            "actions": [{"name": "lim_act", "description": "l"}],
        })
        mgr = SkillsManager(skills_dir=str(tmp_path))
        inst = mgr.install_skill("lim")
        inst.manifest.actions[0].handler = lambda **kw: "ok"
        for _ in range(10):
            await mgr.execute_action("lim_act")
        assert len(mgr.get_execution_history(limit=3)) == 3

    def test_get_skill_metrics_empty(self, tmp_path):
        mgr = SkillsManager(skills_dir=str(tmp_path))
        metrics = mgr.get_skill_metrics()
        assert metrics["total_skills"] == 0
        assert metrics["overall_error_rate"] == 0.0


# ---------------------------------------------------------------------------
# SkillsManager — pending approvals / approve / deny
# ---------------------------------------------------------------------------

class TestApprovals:
    @pytest.mark.asyncio
    async def test_pending_approvals_populated(self, tmp_path):
        _write_manifest(tmp_path, "ap", {
            "name": "ap", "version": "1.0", "description": "ap",
            "actions": [{"name": "needs_confirm", "description": "c", "approval_level": "confirm"}],
        })
        mgr = SkillsManager(skills_dir=str(tmp_path))
        inst = mgr.install_skill("ap")
        inst.manifest.actions[0].handler = lambda **kw: "yes"
        await mgr.execute_action("needs_confirm")
        pending = mgr.get_pending_approvals()
        assert len(pending) == 1
        assert pending[0]["action"] == "needs_confirm"

    @pytest.mark.asyncio
    async def test_approve_action_removes_pending(self, tmp_path):
        _write_manifest(tmp_path, "ap2", {
            "name": "ap2", "version": "1.0", "description": "ap2",
            "actions": [{"name": "conf2", "description": "c2", "approval_level": "confirm"}],
        })
        mgr = SkillsManager(skills_dir=str(tmp_path))
        inst = mgr.install_skill("ap2")
        inst.manifest.actions[0].handler = lambda **kw: "yes"
        await mgr.execute_action("conf2")
        pending = mgr.get_pending_approvals()
        approval_id = pending[0]["id"]
        assert mgr.approve_action(approval_id) is True
        assert mgr.get_pending_approvals() == []

    def test_approve_invalid_id(self, tmp_path):
        mgr = SkillsManager(skills_dir=str(tmp_path))
        assert mgr.approve_action("bogus_id") is False

    def test_list_skills_format(self, tmp_path):
        _write_manifest(tmp_path, "fmt", {
            "name": "fmt", "version": "2.0", "description": "formatted",
            "category": "splunk",
            "actions": [{"name": "fmt_act", "description": "f"}],
            "tags": ["spl"],
        })
        mgr = SkillsManager(skills_dir=str(tmp_path))
        mgr.install_skill("fmt")
        listing = mgr.list_skills()
        assert len(listing) == 1
        entry = listing[0]
        assert entry["name"] == "fmt"
        assert entry["version"] == "2.0"
        assert entry["category"] == "splunk"
        assert "metrics" in entry
        assert "execution_count" in entry["metrics"]

    def test_get_available_actions_filters_disabled(self, tmp_path):
        _write_manifest(tmp_path, "fil", {
            "name": "fil", "version": "1.0", "description": "fil",
            "actions": [{"name": "fil_act", "description": "f"}],
        })
        mgr = SkillsManager(skills_dir=str(tmp_path))
        mgr.install_skill("fil")
        assert len(mgr.get_available_actions()) == 1
        mgr.disable_skill("fil")
        assert len(mgr.get_available_actions()) == 0

    def test_load_all_skills(self, tmp_path):
        for name in ("s1", "s2"):
            _write_manifest(tmp_path, name, {
                "name": name, "version": "1.0", "description": name,
            })
        mgr = SkillsManager(skills_dir=str(tmp_path))
        mgr.load_all_skills()
        assert len(mgr.list_skills()) == 2
