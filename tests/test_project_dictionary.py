"""Tests for project dictionary — comprehensive resource catalog."""

import pytest


class TestProjectDictionary:

    @pytest.fixture(autouse=True)
    def setup(self):
        from chat_app.project_dictionary import ProjectDictionary
        self.d = ProjectDictionary()

    def test_build_manifest(self):
        manifest = self.d.build_manifest()
        assert "meta" in manifest
        assert manifest["meta"]["project"] == "ObsAI"

    def test_environment_variables_cataloged(self):
        manifest = self.d.build_manifest()
        env_vars = manifest["environment_variables"]
        assert len(env_vars) >= 30
        names = [v["name"] for v in env_vars]
        assert "GATEWAY_PORT" in names
        assert "DATABASE_URL" in names
        assert "ENABLE_AUTHENTICATION" in names
        assert "MFA_POLICY" in names
        assert "AUDIT_LOG_DIR" in names

    def test_env_vars_have_required_fields(self):
        manifest = self.d.build_manifest()
        for var in manifest["environment_variables"]:
            assert "name" in var
            assert "default" in var
            assert "description" in var
            assert "category" in var

    def test_collections_cataloged(self):
        manifest = self.d.build_manifest()
        collections = manifest["collections"]
        assert len(collections) >= 10
        names = [c["name"] for c in collections]
        assert "spl_docs" in names
        assert "self_learned_qa" in names

    def test_service_endpoints_cataloged(self):
        manifest = self.d.build_manifest()
        services = manifest["service_endpoints"]
        assert len(services) >= 9
        names = [s["name"] for s in services]
        assert any("PostgreSQL" in n for n in names)
        assert any("Ollama" in n for n in names)
        assert any("Nginx" in n for n in names)

    def test_modules_cataloged(self):
        manifest = self.d.build_manifest()
        modules = manifest["modules"]
        assert len(modules) >= 40  # Should have many modules
        names = [m["name"] for m in modules]
        assert "audit_log" in names
        assert "rbac" in names
        assert "settings" in names

    def test_modules_have_descriptions(self):
        manifest = self.d.build_manifest()
        modules_with_docs = [m for m in manifest["modules"] if m.get("description")]
        assert len(modules_with_docs) >= 20

    def test_config_sections_cataloged(self):
        manifest = self.d.build_manifest()
        sections = manifest["config_sections"]
        assert len(sections) >= 5

    def test_error_codes_cataloged(self):
        manifest = self.d.build_manifest()
        codes = manifest["error_codes"]
        assert len(codes) >= 37
        assert "AUTH_REQUIRED" in codes
        assert "RESOURCE_NOT_FOUND" in codes

    def test_safety_levels_cataloged(self):
        manifest = self.d.build_manifest()
        levels = manifest["safety_levels"]
        assert "read_only" in levels
        assert "destructive" in levels

    def test_slo_definitions_cataloged(self):
        manifest = self.d.build_manifest()
        slos = manifest["slo_definitions"]
        assert len(slos) >= 8
        assert "system_availability" in slos
        assert "tool_success_rate" in slos

    def test_get_by_category(self):
        env_vars = self.d.get("environment_variables")
        assert env_vars is not None
        assert len(env_vars) >= 30

    def test_manifest_cached(self):
        m1 = self.d.build_manifest()
        m2 = self.d.build_manifest()
        assert m1 is m2  # Same object (cached)

    def test_manifest_force_rebuild(self):
        m1 = self.d.build_manifest()
        m2 = self.d.build_manifest(force=True)
        assert m1 is not m2  # Different object (rebuilt)


class TestEnvironmentVariableCategories:

    def test_categories_are_meaningful(self):
        from chat_app.project_dictionary import ENVIRONMENT_VARIABLES
        categories = set(v["category"] for v in ENVIRONMENT_VARIABLES)
        assert "security" in categories
        assert "database" in categories
        assert "llm" in categories
        assert "networking" in categories

    def test_security_vars_identified(self):
        from chat_app.project_dictionary import ENVIRONMENT_VARIABLES
        security_vars = [v for v in ENVIRONMENT_VARIABLES if v["category"] == "security"]
        assert len(security_vars) >= 8
        names = [v["name"] for v in security_vars]
        assert "ENABLE_AUTHENTICATION" in names
        assert "MFA_POLICY" in names
        assert "SCIM_BEARER_TOKEN" in names
