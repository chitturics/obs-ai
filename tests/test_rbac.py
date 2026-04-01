"""Tests for fine-grained RBAC permission system."""

import json
import os

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_rbac_state(tmp_path, monkeypatch):
    """Reset RBAC state between tests."""
    import chat_app.rbac as rbac_mod
    monkeypatch.setattr(rbac_mod, "_user_overrides", {})
    monkeypatch.setattr(rbac_mod, "_overrides_loaded", True)
    monkeypatch.setattr(rbac_mod, "_USER_OVERRIDES_PATH", tmp_path / "rbac_overrides.json")


def _make_user(username: str, role: str = "USER") -> dict:
    return {"identifier": username, "metadata": {"role": role}}


# ---------------------------------------------------------------------------
# Permission Matching Tests
# ---------------------------------------------------------------------------

class TestPermissionMatching:

    def test_exact_match(self):
        from chat_app.rbac import _permission_matches
        assert _permission_matches("tool:search:execute", "tool:search:execute")

    def test_wildcard_resource(self):
        from chat_app.rbac import _permission_matches
        assert _permission_matches("tool:*:execute", "tool:search:execute")

    def test_wildcard_action(self):
        from chat_app.rbac import _permission_matches
        assert _permission_matches("tool:search:*", "tool:search:execute")

    def test_wildcard_all(self):
        from chat_app.rbac import _permission_matches
        assert _permission_matches("*:*:*", "tool:search:execute")

    def test_no_match_different_type(self):
        from chat_app.rbac import _permission_matches
        assert not _permission_matches("collection:*:read", "tool:search:execute")

    def test_no_match_different_action(self):
        from chat_app.rbac import _permission_matches
        assert not _permission_matches("tool:search:read", "tool:search:execute")

    def test_partial_wildcard(self):
        from chat_app.rbac import _permission_matches
        assert _permission_matches("*:*:read", "collection:spl_docs:read")

    def test_short_permission_padded(self):
        from chat_app.rbac import _permission_matches
        assert _permission_matches("tool:search", "tool:search:*")


# ---------------------------------------------------------------------------
# Role Permission Tests
# ---------------------------------------------------------------------------

class TestRolePermissions:

    def test_admin_has_full_access(self):
        from chat_app.rbac import check_permission
        user = _make_user("admin", "ADMIN")
        assert check_permission(user, "tool", "dangerous_delete", "execute")
        assert check_permission(user, "config", "llm", "update")
        assert check_permission(user, "admin", "users", "manage")

    def test_viewer_read_only(self):
        from chat_app.rbac import check_permission
        user = _make_user("viewer", "VIEWER")
        assert check_permission(user, "dashboard", "main", "read")
        assert check_permission(user, "audit", "entries", "read")
        # Viewer can use utility tools
        assert check_permission(user, "tool", "base64_encode", "execute")
        # But not execute arbitrary tools
        assert not check_permission(user, "config", "llm", "update")

    def test_user_can_execute_tools(self):
        from chat_app.rbac import check_permission
        user = _make_user("user1", "USER")
        assert check_permission(user, "tool", "splunk_search", "execute")
        assert check_permission(user, "collection", "spl_docs", "search")
        assert check_permission(user, "chat", "main", "use")

    def test_analyst_can_create_collections(self):
        from chat_app.rbac import check_permission
        user = _make_user("analyst1", "ANALYST")
        assert check_permission(user, "collection", "custom", "create")
        assert check_permission(user, "collection", "custom", "reindex")
        assert check_permission(user, "workflow", "my_workflow", "create")

    def test_role_hierarchy_inheritance(self):
        """Higher roles should inherit lower role permissions."""
        from chat_app.rbac import _get_effective_permissions
        viewer_perms = _get_effective_permissions("VIEWER")
        user_perms = _get_effective_permissions("USER")
        analyst_perms = _get_effective_permissions("ANALYST")

        # USER inherits VIEWER permissions
        assert viewer_perms.issubset(user_perms)
        # ANALYST inherits USER (and VIEWER) permissions
        assert user_perms.issubset(analyst_perms)


# ---------------------------------------------------------------------------
# Per-User Override Tests
# ---------------------------------------------------------------------------

class TestUserOverrides:

    def test_grant_additional_permission(self):
        from chat_app.rbac import check_permission, set_user_overrides
        user = _make_user("limited_user", "VIEWER")

        # Viewer can't execute tools by default
        assert not check_permission(user, "tool", "splunk_search", "execute")

        # Grant specific tool access
        set_user_overrides("limited_user", grants=["tool:splunk_search:execute"])
        assert check_permission(user, "tool", "splunk_search", "execute")
        # Other tools still denied
        assert not check_permission(user, "tool", "delete_index", "execute")

    def test_deny_overrides_role(self):
        from chat_app.rbac import check_permission, set_user_overrides
        user = _make_user("restricted_admin", "ADMIN")

        # Admin has full access by default
        assert check_permission(user, "config", "database", "update")

        # Deny specific access
        set_user_overrides("restricted_admin", denials=["config:database:*"])
        assert not check_permission(user, "config", "database", "update")
        assert not check_permission(user, "config", "database", "delete")
        # Other config sections still accessible
        assert check_permission(user, "config", "llm", "update")

    def test_denial_takes_precedence(self):
        """Explicit denial should override both role and grant permissions."""
        from chat_app.rbac import check_permission, set_user_overrides
        user = _make_user("conflicted", "USER")

        set_user_overrides("conflicted",
                           grants=["tool:dangerous:execute"],
                           denials=["tool:dangerous:execute"])
        assert not check_permission(user, "tool", "dangerous", "execute")

    def test_delete_overrides(self):
        from chat_app.rbac import check_permission, set_user_overrides, delete_user_overrides
        user = _make_user("temp_user", "VIEWER")

        set_user_overrides("temp_user", grants=["tool:search:execute"])
        assert check_permission(user, "tool", "search", "execute")

        delete_user_overrides("temp_user")
        assert not check_permission(user, "tool", "search", "execute")

    def test_list_overrides(self):
        from chat_app.rbac import set_user_overrides, list_all_overrides
        set_user_overrides("user1", grants=["tool:*:execute"])
        set_user_overrides("user2", denials=["config:*:*"])

        overrides = list_all_overrides()
        assert "user1" in overrides
        assert "user2" in overrides

    def test_get_user_permissions_summary(self):
        from chat_app.rbac import get_user_permissions, set_user_overrides
        user = _make_user("analyst", "ANALYST")
        set_user_overrides("analyst", grants=["admin:users:read"])

        summary = get_user_permissions(user)
        assert summary["username"] == "analyst"
        assert summary["role"] == "ANALYST"
        assert summary["role_level"] == 2
        assert "admin:users:read" in summary["grants"]


# ---------------------------------------------------------------------------
# Default Permissions Tests
# ---------------------------------------------------------------------------

class TestDefaultPermissions:

    def test_get_defaults(self):
        from chat_app.rbac import get_default_permissions
        defaults = get_default_permissions()
        assert "VIEWER" in defaults
        assert "USER" in defaults
        assert "ANALYST" in defaults
        assert "ADMIN" in defaults
        assert "*:*:*" in defaults["ADMIN"]

    def test_viewer_has_read_all(self):
        from chat_app.rbac import get_default_permissions
        defaults = get_default_permissions()
        assert "*:*:read" in defaults["VIEWER"]
