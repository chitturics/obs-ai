"""Tests for tenant isolation — scoping, context, export/import."""

import pytest
import json


@pytest.fixture
def mgr(tmp_path, monkeypatch):
    """Create a fresh TenantManager with temp storage."""
    import chat_app.tenant_isolation as mod
    monkeypatch.setattr(mod, "_TENANTS_FILE", tmp_path / "tenants.json")
    # Reset singleton
    monkeypatch.setattr(mod, "_instance", None)
    from chat_app.tenant_isolation import TenantManager
    return TenantManager()


class TestTenantCRUD:

    def test_default_tenant_exists(self, mgr):
        tenant = mgr.get_tenant("default")
        assert tenant is not None
        assert tenant.enabled is True

    def test_create_tenant(self, mgr):
        tenant = mgr.create_tenant("acme_corp", display_name="Acme Corporation")
        assert tenant.tenant_id == "acme_corp"
        assert tenant.display_name == "Acme Corporation"

    def test_create_duplicate_raises(self, mgr):
        mgr.create_tenant("test_tenant")
        with pytest.raises(ValueError):
            mgr.create_tenant("test_tenant")

    def test_list_tenants(self, mgr):
        mgr.create_tenant("tenant_a")
        mgr.create_tenant("tenant_b")
        tenants = mgr.list_tenants()
        ids = [t.tenant_id for t in tenants]
        assert "default" in ids
        assert "tenant_a" in ids
        assert "tenant_b" in ids

    def test_update_tenant(self, mgr):
        mgr.create_tenant("test_tenant")
        updated = mgr.update_tenant("test_tenant", display_name="Updated Name")
        assert updated.display_name == "Updated Name"

    def test_disable_tenant(self, mgr):
        mgr.create_tenant("test_tenant")
        assert mgr.disable_tenant("test_tenant") is True
        tenant = mgr.get_tenant("test_tenant")
        assert tenant.enabled is False

    def test_delete_tenant(self, mgr):
        mgr.create_tenant("test_tenant")
        assert mgr.delete_tenant("test_tenant") is True
        assert mgr.get_tenant("test_tenant") is None

    def test_cannot_delete_default(self, mgr):
        assert mgr.delete_tenant("default") is False


class TestCollectionScoping:

    def test_scope_default_tenant(self, mgr):
        scoped = mgr.scope_collection("default", "spl_docs")
        assert scoped == "spl_docs"  # Default tenant = no prefix

    def test_scope_named_tenant(self, mgr):
        mgr.create_tenant("acme")
        scoped = mgr.scope_collection("acme", "spl_docs")
        assert scoped == "acme__spl_docs"

    def test_unscope_collection(self, mgr):
        tenant_id, base = mgr.unscope_collection("acme__spl_docs")
        assert tenant_id == "acme"
        assert base == "spl_docs"

    def test_unscope_default(self, mgr):
        tenant_id, base = mgr.unscope_collection("spl_docs")
        assert tenant_id == "default"
        assert base == "spl_docs"


class TestTenantContext:

    def test_get_context(self, mgr):
        mgr.create_tenant("acme")
        ctx = mgr.get_context("acme")
        assert ctx is not None
        assert ctx.tenant_id == "acme"
        assert ctx.collection_prefix == "acme"

    def test_context_scope_collection(self, mgr):
        mgr.create_tenant("acme")
        ctx = mgr.get_context("acme")
        assert ctx.scope_collection("spl_docs") == "acme__spl_docs"

    def test_context_unscope_collection(self, mgr):
        mgr.create_tenant("acme")
        ctx = mgr.get_context("acme")
        assert ctx.unscope_collection("acme__spl_docs") == "spl_docs"

    def test_disabled_tenant_no_context(self, mgr):
        mgr.create_tenant("acme")
        mgr.disable_tenant("acme")
        ctx = mgr.get_context("acme")
        assert ctx is None

    def test_nonexistent_tenant_no_context(self, mgr):
        ctx = mgr.get_context("nonexistent")
        assert ctx is None

    def test_default_context_no_prefix(self, mgr):
        ctx = mgr.get_context("default")
        assert ctx.collection_prefix == ""
        assert ctx.scope_collection("spl_docs") == "spl_docs"


class TestExportImport:

    def test_export_tenant(self, mgr):
        mgr.create_tenant("acme", config_overrides={"llm": {"model": "llama3"}})
        export = mgr.export_tenant("acme")
        assert export is not None
        assert export.tenant_id == "acme"
        assert export.config == {"llm": {"model": "llama3"}}

    def test_export_nonexistent(self, mgr):
        assert mgr.export_tenant("nonexistent") is None

    def test_import_tenant(self, mgr):
        export_data = {
            "tenant_id": "imported_corp",
            "metadata": {"display_name": "Imported Corp"},
            "config": {"retrieval": {"top_k": 5}},
        }
        tenant = mgr.import_tenant(export_data)
        assert tenant.tenant_id == "imported_corp"
        assert tenant.display_name == "Imported Corp"


class TestPersistence:

    def test_tenants_persisted(self, mgr, tmp_path, monkeypatch):
        import chat_app.tenant_isolation as mod
        mgr.create_tenant("persist_test")

        # Create new instance (simulating restart)
        from chat_app.tenant_isolation import TenantManager
        mgr2 = TenantManager()
        tenant = mgr2.get_tenant("persist_test")
        assert tenant is not None


class TestStats:

    def test_stats_structure(self, mgr):
        mgr.create_tenant("acme")
        mgr.create_tenant("beta")
        stats = mgr.get_stats()
        assert stats["total_tenants"] >= 3  # default + acme + beta
        assert stats["enabled"] >= 3
        assert "timestamp" in stats
