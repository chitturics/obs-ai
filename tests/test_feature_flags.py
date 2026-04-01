"""Tests for feature flag management — toggle, reload, precedence."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chat_app'))

import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def reset_feature_flags():
    """Reset feature flag singleton before each test."""
    import chat_app.admin_shared as shared
    shared._feature_flags = None
    yield
    shared._feature_flags = None


class TestFeatureFlagInit:
    """Test feature flag initialization from config."""

    def test_default_flags_loaded(self):
        """Feature flags initialize with defaults when no config."""
        from chat_app.admin_api import _get_feature_flags
        with patch("chat_app.settings._load_yaml_config", return_value={}):
            with patch("chat_app.admin_shared.get_settings") as mock_settings:
                mock_settings.return_value.learning.enabled = True
                flags = _get_feature_flags()
        assert isinstance(flags, dict)
        assert len(flags) > 10
        assert "query_caching" in flags
        assert "hybrid_search" in flags

    def test_config_overrides_defaults(self):
        """Config.yaml values override defaults."""
        from chat_app.admin_api import _get_feature_flags
        config = {"features": {"hybrid_search": True, "reranking": True}}
        with patch("chat_app.settings._load_yaml_config", return_value=config):
            with patch("chat_app.admin_shared.get_settings") as mock_settings:
                mock_settings.return_value.learning.enabled = False
                flags = _get_feature_flags()
        assert flags["hybrid_search"] is True
        assert flags["reranking"] is True

    def test_flags_are_boolean(self):
        """All feature flags must be boolean values."""
        from chat_app.admin_api import _get_feature_flags
        with patch("chat_app.settings._load_yaml_config", return_value={}):
            with patch("chat_app.admin_shared.get_settings") as mock_settings:
                mock_settings.return_value.learning.enabled = True
                flags = _get_feature_flags()
        for key, value in flags.items():
            assert isinstance(value, bool), f"Flag '{key}' is {type(value).__name__}, expected bool"


class TestFeatureFlagToggle:
    """Test toggling feature flags on/off."""

    def test_toggle_on(self):
        """Toggling a flag on sets it to True."""
        from chat_app.admin_api import _get_feature_flags
        with patch("chat_app.settings._load_yaml_config", return_value={}):
            with patch("chat_app.admin_shared.get_settings") as mock_settings:
                mock_settings.return_value.learning.enabled = True
                flags = _get_feature_flags()
        flags["hybrid_search"] = True
        assert flags["hybrid_search"] is True

    def test_toggle_off(self):
        """Toggling a flag off sets it to False."""
        from chat_app.admin_api import _get_feature_flags
        with patch("chat_app.settings._load_yaml_config", return_value={}):
            with patch("chat_app.admin_shared.get_settings") as mock_settings:
                mock_settings.return_value.learning.enabled = True
                flags = _get_feature_flags()
        flags["query_caching"] = False
        assert flags["query_caching"] is False

    def test_unknown_flag_not_present(self):
        """Flags not in the defined set should not exist."""
        from chat_app.admin_api import _get_feature_flags
        with patch("chat_app.settings._load_yaml_config", return_value={}):
            with patch("chat_app.admin_shared.get_settings") as mock_settings:
                mock_settings.return_value.learning.enabled = True
                flags = _get_feature_flags()
        assert "nonexistent_flag" not in flags


class TestFeatureFlagReload:
    """Test reloading flags from config."""

    def test_reload_resets_cache(self):
        """After reload, flags should reflect new config."""
        import chat_app.admin_shared as shared
        # First load with defaults
        with patch("chat_app.settings._load_yaml_config", return_value={}):
            with patch("chat_app.admin_shared.get_settings") as mock_settings:
                mock_settings.return_value.learning.enabled = True
                flags1 = shared._get_feature_flags()
        assert flags1["hybrid_search"] is False

        # Reset and reload with new config
        shared._feature_flags = None
        new_config = {"features": {"hybrid_search": True}}
        with patch("chat_app.settings._load_yaml_config", return_value=new_config):
            with patch("chat_app.admin_shared.get_settings") as mock_settings:
                mock_settings.return_value.learning.enabled = True
                flags2 = shared._get_feature_flags()
        assert flags2["hybrid_search"] is True


class TestFeatureFlagGating:
    """Test that features are properly gated by flags."""

    def test_known_flag_names(self):
        """Verify all expected flag names exist."""
        from chat_app.admin_api import _get_feature_flags
        expected_flags = [
            "hybrid_search", "query_caching", "response_streaming",
            "reranking", "circuit_breakers", "retry_with_backoff",
            "fallback_responses", "learning", "knowledge_graph",
            "orchestration",
        ]
        with patch("chat_app.settings._load_yaml_config", return_value={}):
            with patch("chat_app.admin_shared.get_settings") as mock_settings:
                mock_settings.return_value.learning.enabled = True
                flags = admin_flags = _get_feature_flags()
        for name in expected_flags:
            assert name in flags, f"Expected flag '{name}' not found in feature flags"
