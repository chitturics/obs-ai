"""
Tests for SkillCatalog — human-action-to-system-capability mapping.

Tests all skills, families, lookup methods, and API endpoints.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from chat_app.skill_catalog import (
    Skill,
    SkillCatalog,
    SkillFamily,
    ApprovalGate,
    SKILL_CATALOG,
    get_skill_catalog,
)


@pytest.fixture
def catalog():
    return SkillCatalog()


# ---------------------------------------------------------------------------
# Skill dataclass
# ---------------------------------------------------------------------------

class TestSkillDataclass:
    def test_defaults(self):
        s = Skill(action="test", name="test_skill", description="test", family=SkillFamily.COGNITIVE)
        assert s.enabled is True
        assert s.approval == ApprovalGate.AUTO
        assert s.requires == set()
        assert s.intents == []
        assert s.tags == []

    def test_display_name_with_emoji(self):
        s = Skill(action="think", name="reason", description="", family=SkillFamily.COGNITIVE, emoji="🧠")
        assert s.display_name == "🧠 Think"

    def test_display_name_without_emoji(self):
        s = Skill(action="think", name="reason", description="", family=SkillFamily.COGNITIVE)
        assert s.display_name == "Think"

    def test_to_dict(self):
        s = Skill(
            action="eat", name="ingest_data", description="Ingest data",
            family=SkillFamily.IO, emoji="🍽️",
            handler_key="ingest", tags=["data"],
        )
        d = s.to_dict()
        assert d["action"] == "eat"
        assert d["name"] == "ingest_data"
        assert d["family"] == "io"
        assert d["emoji"] == "🍽️"
        assert "data" in d["tags"]


# ---------------------------------------------------------------------------
# SkillFamily enum
# ---------------------------------------------------------------------------

class TestSkillFamily:
    def test_all_families_exist(self):
        families = {f.value for f in SkillFamily}
        expected = {"cognitive", "io", "communication", "alerting", "creative", "social", "maintenance", "operational"}
        assert families == expected

    def test_string_enum(self):
        assert isinstance(SkillFamily.COGNITIVE, str)
        assert SkillFamily.COGNITIVE == "cognitive"


# ---------------------------------------------------------------------------
# ApprovalGate enum
# ---------------------------------------------------------------------------

class TestApprovalGate:
    def test_all_gates(self):
        gates = {g.value for g in ApprovalGate}
        assert gates == {"auto", "inform", "confirm", "review"}


# ---------------------------------------------------------------------------
# SKILL_CATALOG contents
# ---------------------------------------------------------------------------

class TestCatalogContents:
    def test_catalog_not_empty(self):
        assert len(SKILL_CATALOG) > 50

    def test_all_have_required_fields(self):
        for skill in SKILL_CATALOG:
            assert skill.action, f"Skill {skill.name} missing action"
            assert skill.name, f"Skill {skill.action} missing name"
            assert skill.description, f"Skill {skill.name} missing description"
            assert isinstance(skill.family, SkillFamily)

    def test_unique_names(self):
        names = [s.name for s in SKILL_CATALOG]
        assert len(names) == len(set(names)), f"Duplicate names: {[n for n in names if names.count(n) > 1]}"

    def test_unique_actions(self):
        actions = [s.action for s in SKILL_CATALOG]
        assert len(actions) == len(set(actions)), f"Duplicate actions: {[a for a in actions if actions.count(a) > 1]}"

    def test_all_families_represented(self):
        families = {s.family for s in SKILL_CATALOG}
        for f in SkillFamily:
            assert f in families, f"Family {f.value} has no skills"

    def test_key_human_actions_present(self):
        """The user explicitly asked for eat, sleep, think, run, walk, cry, act, play, jump."""
        actions = {s.action for s in SKILL_CATALOG}
        for action in ["eat", "sleep", "think", "run", "walk", "cry", "play", "jump"]:
            assert action in actions, f"Missing human action: {action}"

    def test_approval_gated_skills_exist(self):
        gated = [s for s in SKILL_CATALOG if s.approval != ApprovalGate.AUTO]
        assert len(gated) >= 5, "Should have multiple approval-gated skills"

    def test_skills_with_requirements(self):
        required = [s for s in SKILL_CATALOG if s.requires]
        assert len(required) >= 2, "Should have skills with capability requirements"


# ---------------------------------------------------------------------------
# SkillCatalog methods
# ---------------------------------------------------------------------------

class TestSkillCatalogLookup:
    def test_get_by_name(self, catalog):
        s = catalog.get("reason")
        assert s is not None
        assert s.action == "think"

    def test_get_unknown_name(self, catalog):
        assert catalog.get("nonexistent") is None

    def test_get_by_action(self, catalog):
        s = catalog.get_by_action("eat")
        assert s is not None
        assert s.name == "ingest_data"

    def test_get_by_action_case_insensitive(self, catalog):
        s = catalog.get_by_action("EAT")
        assert s is not None

    def test_get_by_action_unknown(self, catalog):
        assert catalog.get_by_action("teleport") is None

    def test_get_family(self, catalog):
        cognitive = catalog.get_family(SkillFamily.COGNITIVE)
        assert len(cognitive) >= 5
        assert all(s.family == SkillFamily.COGNITIVE for s in cognitive)

    def test_get_by_tag(self, catalog):
        spl_skills = catalog.get_by_tag("spl")
        assert len(spl_skills) >= 3

    def test_get_for_intent(self, catalog):
        spl_skills = catalog.get_for_intent("spl_generation")
        assert len(spl_skills) >= 3

    def test_get_enabled(self, catalog):
        enabled = catalog.get_enabled()
        assert len(enabled) == catalog.count

    def test_get_requiring_approval(self, catalog):
        gated = catalog.get_requiring_approval()
        assert len(gated) >= 5
        for s in gated:
            assert s.approval in (ApprovalGate.CONFIRM, ApprovalGate.REVIEW)

    def test_search(self, catalog):
        results = catalog.search("spl")
        assert len(results) >= 3

    def test_search_by_action(self, catalog):
        results = catalog.search("eat")
        assert any(s.action == "eat" for s in results)

    def test_list_all(self, catalog):
        all_skills = catalog.list_all()
        assert len(all_skills) == catalog.count
        assert all(isinstance(s, dict) for s in all_skills)

    def test_list_actions(self, catalog):
        actions = catalog.list_actions()
        assert "think" in actions
        assert "eat" in actions
        assert "run" in actions
        assert actions == sorted(actions)

    def test_summary(self, catalog):
        s = catalog.summary()
        assert s["total_skills"] == catalog.count
        assert "families" in s
        assert "actions" in s
        assert s["enabled"] == catalog.count

    def test_count(self, catalog):
        assert catalog.count > 50


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_singleton_returns_same(self):
        a = get_skill_catalog()
        b = get_skill_catalog()
        assert a is b


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

class TestSkillCatalogAPI:
    @pytest.fixture
    def app(self):
        from fastapi import FastAPI
        from chat_app.admin_api import (
            router, public_router,
            config_router, settings_router, tools_router, users_router,
            security_router, observability_router, skills_router,
            collections_router, learning_router, operations_router,
            dashboard_router, pages_router, pages_public_router,
            interactive_tools_public_router, interactive_tools_router,
        )
        from chat_app.auth_dependencies import get_authenticated_user, require_admin
        from chat_app.admin_shared import _rate_limit, _csrf_check, _track_audit_user

        async def _fake_user():
            return {
                "identifier": "test_admin",
                "metadata": {"role": "ADMIN", "provider": "test"},
            }

        app = FastAPI()
        app.include_router(router)
        app.include_router(public_router)
        for _sub in [config_router, settings_router, tools_router, users_router,
                     security_router, observability_router, skills_router,
                     collections_router, learning_router, operations_router,
                     dashboard_router, pages_router, pages_public_router,
                     interactive_tools_public_router, interactive_tools_router]:
            app.include_router(_sub)
        app.dependency_overrides[get_authenticated_user] = _fake_user
        app.dependency_overrides[require_admin] = lambda: None
        app.dependency_overrides[_rate_limit] = lambda: None
        app.dependency_overrides[_csrf_check] = lambda: None
        app.dependency_overrides[_track_audit_user] = lambda: None
        return app

    @pytest.fixture
    def client(self, app):
        from fastapi.testclient import TestClient
        return TestClient(app)

    def test_get_full_catalog(self, client):
        resp = client.get("/api/admin/skill-catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert len(data["skills"]) > 50

    def test_list_actions(self, client):
        resp = client.get("/api/admin/skill-catalog/actions")
        assert resp.status_code == 200
        assert "think" in resp.json()["actions"]

    def test_get_by_action(self, client):
        resp = client.get("/api/admin/skill-catalog/action/think")
        assert resp.status_code == 200
        assert resp.json()["name"] == "reason"

    def test_get_by_action_not_found(self, client):
        resp = client.get("/api/admin/skill-catalog/action/teleport")
        assert resp.status_code == 404

    def test_get_by_family(self, client):
        resp = client.get("/api/admin/skill-catalog/family/cognitive")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 5

    def test_get_by_family_invalid(self, client):
        resp = client.get("/api/admin/skill-catalog/family/invalid")
        assert resp.status_code == 400

    def test_search_skills(self, client):
        resp = client.get("/api/admin/skill-catalog/search?q=spl")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 3

    def test_get_for_intent(self, client):
        resp = client.get("/api/admin/skill-catalog/intent/spl_generation")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 3

    def test_approval_required(self, client):
        resp = client.get("/api/admin/skill-catalog/approval-required")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 5
