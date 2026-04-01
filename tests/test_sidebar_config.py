"""Tests for sidebar configuration — CMS++ layout management."""

import json
import pytest


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "sidebar_config.json"
    import chat_app.sidebar_config as mod
    monkeypatch.setattr(mod, "_CONFIG_PATH", path)
    return path


class TestSidebarConfig:

    def test_default_config_has_groups(self, config_path):
        from chat_app.sidebar_config import get_sidebar_config
        config = get_sidebar_config()
        assert "groups" in config
        assert len(config["groups"]) >= 7
        labels = [g["label"] for g in config["groups"]]
        assert "Overview" in labels
        assert "Intelligence" in labels
        assert "Infrastructure" in labels
        assert "Operations" in labels
        assert "Developer Tools" in labels

    def test_default_groups_have_items(self, config_path):
        from chat_app.sidebar_config import get_sidebar_config
        config = get_sidebar_config()
        for group in config["groups"]:
            assert "items" in group
            assert "label" in group
            assert "order" in group
            assert "visible" in group
            for item in group["items"]:
                assert "id" in item
                assert "label" in item
                assert "visible" in item
                assert "order" in item

    def test_save_and_load(self, config_path):
        from chat_app.sidebar_config import get_sidebar_config, save_sidebar_config
        config = get_sidebar_config()
        config["groups"][0]["visible"] = False  # Hide Overview
        save_sidebar_config(config, actor="test_user")

        loaded = get_sidebar_config()
        assert loaded["groups"][0]["visible"] is False
        assert loaded["updated_by"] == "test_user"
        assert loaded["updated_at"] is not None

    def test_reorder_groups(self, config_path):
        from chat_app.sidebar_config import get_sidebar_config, save_sidebar_config
        config = get_sidebar_config()
        # Move Operations to top
        for g in config["groups"]:
            if g["label"] == "Operations":
                g["order"] = -1
        save_sidebar_config(config)

        loaded = get_sidebar_config()
        ops = next(g for g in loaded["groups"] if g["label"] == "Operations")
        assert ops["order"] == -1

    def test_hide_item(self, config_path):
        from chat_app.sidebar_config import get_sidebar_config, save_sidebar_config
        config = get_sidebar_config()
        # Hide dashboard
        for group in config["groups"]:
            for item in group["items"]:
                if item["id"] == "dashboard":
                    item["visible"] = False
        save_sidebar_config(config)

        loaded = get_sidebar_config()
        dashboard = None
        for group in loaded["groups"]:
            for item in group["items"]:
                if item["id"] == "dashboard":
                    dashboard = item
        assert dashboard is not None
        assert dashboard["visible"] is False

    def test_reset_config(self, config_path):
        from chat_app.sidebar_config import get_sidebar_config, save_sidebar_config, reset_sidebar_config
        config = get_sidebar_config()
        config["groups"][0]["visible"] = False
        save_sidebar_config(config)

        reset = reset_sidebar_config()
        assert reset["groups"][0]["visible"] is True
        # File should be deleted (defaults used)
        assert reset["updated_at"] is None

    def test_persists_to_file(self, config_path):
        from chat_app.sidebar_config import save_sidebar_config
        save_sidebar_config({"groups": [{"label": "Test", "order": 0, "visible": True, "items": []}]})
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert data["groups"][0]["label"] == "Test"
