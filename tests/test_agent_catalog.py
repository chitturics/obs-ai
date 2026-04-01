"""
Tests for AgentCatalog — human-role-to-system-agent mapping.

Tests all agent personas, departments, lookup methods, and API endpoints.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from chat_app.agent_catalog import (
    AgentPersona,
    AgentCatalog,
    Department,
    ExpertiseLevel,
    AGENT_CATALOG,
    get_agent_catalog,
)


@pytest.fixture
def catalog():
    return AgentCatalog()


# ---------------------------------------------------------------------------
# AgentPersona dataclass
# ---------------------------------------------------------------------------

class TestAgentPersona:
    def test_defaults(self):
        a = AgentPersona(
            role="test", name="test_agent",
            description="test agent", department=Department.ENGINEERING,
        )
        assert a.active is True
        assert a.expertise == ExpertiseLevel.SPECIALIST
        assert a.skills == []
        assert a.intents == []

    def test_display_name_with_emoji(self):
        a = AgentPersona(
            role="coder", name="spl_coder", description="",
            department=Department.ENGINEERING, emoji="💻",
        )
        assert a.display_name == "💻 Coder"

    def test_display_name_without_emoji(self):
        a = AgentPersona(
            role="coder", name="spl_coder", description="",
            department=Department.ENGINEERING,
        )
        assert a.display_name == "Coder"

    def test_system_prompt_fragment(self):
        a = AgentPersona(
            role="coder", name="spl_coder",
            description="Writes SPL", department=Department.ENGINEERING,
            skills=["generate_spl", "optimize_spl"],
            personality="Precise and methodical.",
        )
        prompt = a.get_system_prompt_fragment()
        assert "Coder" in prompt  # role in title
        assert "Writes SPL" in prompt  # description included
        assert "Precise and methodical" in prompt
        assert "generate_spl" in prompt
        assert "Engineering" in prompt  # department directive
        assert "Expertise Level" in prompt  # expertise style

    def test_to_dict(self):
        a = AgentPersona(
            role="ops guy", name="ops_engineer", description="Handles ops",
            department=Department.OPERATIONS, emoji="⚙️",
            skills=["monitor_health"], tags=["operations"],
        )
        d = a.to_dict()
        assert d["role"] == "ops guy"
        assert d["name"] == "ops_engineer"
        assert d["department"] == "operations"
        assert "monitor_health" in d["skills"]


# ---------------------------------------------------------------------------
# Department enum
# ---------------------------------------------------------------------------

class TestDepartment:
    def test_all_departments(self):
        depts = {d.value for d in Department}
        expected = {
            "engineering", "operations", "data", "infrastructure",
            "management", "knowledge", "security", "ui_ux",
            "support", "creative",
        }
        assert depts == expected

    def test_string_enum(self):
        assert isinstance(Department.ENGINEERING, str)


# ---------------------------------------------------------------------------
# ExpertiseLevel enum
# ---------------------------------------------------------------------------

class TestExpertiseLevel:
    def test_all_levels(self):
        levels = {e.value for e in ExpertiseLevel}
        assert levels == {"generalist", "specialist", "expert", "lead"}


# ---------------------------------------------------------------------------
# AGENT_CATALOG contents
# ---------------------------------------------------------------------------

class TestCatalogContents:
    def test_catalog_not_empty(self):
        assert len(AGENT_CATALOG) > 30

    def test_all_have_required_fields(self):
        for agent in AGENT_CATALOG:
            assert agent.role, f"Agent {agent.name} missing role"
            assert agent.name, f"Agent {agent.role} missing name"
            assert agent.description, f"Agent {agent.name} missing description"
            assert isinstance(agent.department, Department)

    def test_unique_names(self):
        names = [a.name for a in AGENT_CATALOG]
        assert len(names) == len(set(names)), f"Duplicate names found"

    def test_all_departments_represented(self):
        departments = {a.department for a in AGENT_CATALOG}
        for d in Department:
            assert d in departments, f"Department {d.value} has no agents"

    def test_key_human_roles_present(self):
        """The user asked for: listener, parser, writer, coder, reader, watcher,
        breaker, developer, tester, learner, ops guy, storage guy, network guy,
        project manager, director, owner, orchestrator, monitor, observer,
        database guy, UI guy."""
        roles = {a.role.lower() for a in AGENT_CATALOG}
        for role in [
            "listener", "parser", "writer", "coder", "reader", "watcher",
            "breaker", "developer", "tester", "learner", "ops guy",
            "storage guy", "network guy", "project manager", "director",
            "owner", "orchestrator", "monitor", "observer", "database guy",
            "ui guy",
        ]:
            assert role in roles, f"Missing human role: {role}"

    def test_all_agents_have_skills(self):
        for agent in AGENT_CATALOG:
            assert len(agent.skills) >= 1, f"Agent {agent.name} has no skills"

    def test_all_agents_have_personality(self):
        for agent in AGENT_CATALOG:
            assert agent.personality, f"Agent {agent.name} has no personality"

    def test_expertise_variety(self):
        levels = {a.expertise for a in AGENT_CATALOG}
        assert len(levels) >= 3, "Should have variety in expertise levels"


# ---------------------------------------------------------------------------
# AgentCatalog methods
# ---------------------------------------------------------------------------

class TestAgentCatalogLookup:
    def test_get_by_name(self, catalog):
        a = catalog.get("spl_coder")
        assert a is not None
        assert a.role == "coder"

    def test_get_unknown_name(self, catalog):
        assert catalog.get("nonexistent") is None

    def test_get_by_role(self, catalog):
        a = catalog.get_by_role("coder")
        assert a is not None
        assert a.name == "spl_coder"

    def test_get_by_role_case_insensitive(self, catalog):
        a = catalog.get_by_role("CODER")
        assert a is not None

    def test_get_by_role_with_spaces(self, catalog):
        a = catalog.get_by_role("ops guy")
        assert a is not None
        assert a.name == "ops_engineer"

    def test_get_by_role_unknown(self, catalog):
        assert catalog.get_by_role("astronaut") is None

    def test_get_department(self, catalog):
        eng = catalog.get_department(Department.ENGINEERING)
        assert len(eng) >= 5
        assert all(a.department == Department.ENGINEERING for a in eng)

    def test_get_for_intent(self, catalog):
        spl_agents = catalog.get_for_intent("spl_generation")
        assert len(spl_agents) >= 2

    def test_get_best_agent(self, catalog):
        best = catalog.get_best_agent("spl_generation")
        assert best is not None
        assert best.expertise in (ExpertiseLevel.EXPERT, ExpertiseLevel.LEAD)

    def test_get_best_agent_unknown_intent(self, catalog):
        assert catalog.get_best_agent("nonexistent_intent") is None

    def test_get_active(self, catalog):
        active = catalog.get_active()
        assert len(active) == catalog.count

    def test_search(self, catalog):
        results = catalog.search("spl")
        assert len(results) >= 2

    def test_search_by_role(self, catalog):
        results = catalog.search("coder")
        assert any(a.role == "coder" for a in results)

    def test_search_by_tag(self, catalog):
        results = catalog.search("security")
        assert len(results) >= 2

    def test_list_all(self, catalog):
        all_agents = catalog.list_all()
        assert len(all_agents) == catalog.count
        assert all(isinstance(a, dict) for a in all_agents)

    def test_list_roles(self, catalog):
        roles = catalog.list_roles()
        assert "coder" in roles
        assert "ops guy" in roles
        assert roles == sorted(roles)

    def test_summary(self, catalog):
        s = catalog.summary()
        assert s["total_agents"] == catalog.count
        assert "departments" in s
        assert "expertise_breakdown" in s
        assert "roles" in s

    def test_count(self, catalog):
        assert catalog.count > 30


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

class TestSingleton:
    def test_singleton_returns_same(self):
        a = get_agent_catalog()
        b = get_agent_catalog()
        assert a is b


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

class TestAgentCatalogAPI:
    @pytest.fixture
    def app(self):
        from fastapi import FastAPI
        from chat_app.admin_api import router, public_router, skills_router
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
        app.include_router(skills_router)
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
        resp = client.get("/api/admin/agent-catalog")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert len(data["agents"]) > 30

    def test_list_roles(self, client):
        resp = client.get("/api/admin/agent-catalog/roles")
        assert resp.status_code == 200
        assert "coder" in resp.json()["roles"]

    def test_get_by_role(self, client):
        resp = client.get("/api/admin/agent-catalog/role/coder")
        assert resp.status_code == 200
        assert resp.json()["name"] == "spl_coder"

    def test_get_by_role_not_found(self, client):
        resp = client.get("/api/admin/agent-catalog/role/astronaut")
        assert resp.status_code == 404

    def test_get_by_department(self, client):
        resp = client.get("/api/admin/agent-catalog/department/engineering")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 5

    def test_get_by_department_invalid(self, client):
        resp = client.get("/api/admin/agent-catalog/department/invalid")
        assert resp.status_code == 400

    def test_search_agents(self, client):
        resp = client.get("/api/admin/agent-catalog/search?q=security")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 2

    def test_get_for_intent(self, client):
        resp = client.get("/api/admin/agent-catalog/intent/spl_generation")
        assert resp.status_code == 200
        assert resp.json()["count"] >= 2

    def test_get_best_agent(self, client):
        resp = client.get("/api/admin/agent-catalog/best/spl_generation")
        assert resp.status_code == 200
        assert resp.json()["expertise"] in ("expert", "lead")

    def test_get_best_agent_not_found(self, client):
        resp = client.get("/api/admin/agent-catalog/best/nonexistent")
        assert resp.status_code == 404
