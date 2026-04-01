"""Tests for least-privilege credential scoping."""

import os
import pytest


@pytest.fixture
def mgr(monkeypatch):
    """Create a fresh CredentialManager with some env vars set."""
    # Simulate some credentials being set
    monkeypatch.setenv("SPLUNK_READ_TOKEN", "test_read_token")
    monkeypatch.setenv("SPLUNK_PASSWORD", "test_admin_pass")
    monkeypatch.setenv("SPLUNK_HEC_TOKEN", "test_hec_token")

    from chat_app.credential_scoping import CredentialManager
    return CredentialManager()


class TestCredentialSelection:

    def test_read_action_gets_read_credential(self, mgr):
        cred = mgr.get_credential("splunk", "splunk_search")
        assert cred is not None
        assert cred.scope.value == "read"
        assert cred.name == "splunk_read"

    def test_write_action_falls_back_to_higher_scope(self, mgr):
        """Write token not set, so falls back to superadmin (SPLUNK_PASSWORD)."""
        cred = mgr.get_credential("splunk", "update_saved_search")
        assert cred is not None
        # Should use the fallback since SPLUNK_WRITE_TOKEN is not set
        assert cred.scope.value in ("write", "superadmin")

    def test_hec_action_uses_hec_token(self, mgr):
        cred = mgr.get_credential("splunk", "send_hec_event")
        assert cred is not None
        assert "hec" in cred.name.lower() or cred.scope.value in ("write", "superadmin")

    def test_no_credential_for_unknown_service(self, mgr):
        cred = mgr.get_credential("unknown_service", "some_action")
        assert cred is None

    def test_credential_use_tracking(self, mgr):
        cred = mgr.get_credential("splunk", "splunk_search")
        assert cred.use_count >= 1
        assert cred.last_used is not None

    def test_multiple_uses_increment_count(self, mgr):
        mgr.get_credential("splunk", "splunk_search")
        mgr.get_credential("splunk", "list_indexes")
        cred = mgr.get_credential("splunk", "list_apps")
        # All three use the same read credential
        assert cred.use_count >= 3


class TestScopeMapping:

    def test_scope_for_search(self, mgr):
        scope = mgr.get_scope_for_action("splunk", "splunk_search")
        assert scope == "read"

    def test_scope_for_delete(self, mgr):
        scope = mgr.get_scope_for_action("splunk", "delete_index")
        assert scope == "admin"

    def test_scope_for_deploy(self, mgr):
        scope = mgr.get_scope_for_action("cribl", "deploy_pipeline")
        assert scope == "write"

    def test_scope_for_unknown_defaults_to_read(self, mgr):
        scope = mgr.get_scope_for_action("splunk", "unknown_action")
        assert scope == "read"

    def test_get_all_scopes(self, mgr):
        scopes = mgr.get_all_scopes()
        assert "splunk" in scopes
        assert "cribl" in scopes
        assert "splunk_search" in scopes["splunk"]


class TestConnectorHealth:

    def test_health_report(self, mgr):
        health = mgr.get_connector_health()
        assert "connectors" in health
        assert "splunk" in health["connectors"]
        assert health["total_credentials"] >= 8
        assert health["set_count"] >= 3  # We set 3 env vars

    def test_service_scopes_available(self, mgr):
        health = mgr.get_connector_health()
        splunk = health["connectors"]["splunk"]
        assert splunk["any_set"] is True
        assert "read" in splunk["scopes_available"]


class TestCredentialSerialization:

    def test_to_dict(self, mgr):
        creds = mgr.get_all_credentials()
        assert len(creds) >= 8
        d = creds[0].to_dict()
        assert "name" in d
        assert "service" in d
        assert "scope" in d
        assert "is_set" in d

    def test_get_for_service(self, mgr):
        splunk_creds = mgr.get_for_service("splunk")
        assert len(splunk_creds) >= 4
        cribl_creds = mgr.get_for_service("cribl")
        assert len(cribl_creds) >= 3
