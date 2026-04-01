"""Tests for the configurable UI framework feature."""
import os
import sys
import pytest

# Add paths
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(project_root, "chat_app"))
sys.path.insert(0, os.path.join(project_root, "shared"))
sys.path.insert(0, project_root)


class TestSessionStore:
    """Test the framework-agnostic session store."""

    def test_create_and_get(self):
        from session_store import SessionStore
        store = SessionStore()
        store.create_session("t1")
        store.set("t1", "key", "value")
        assert store.get("t1", "key") == "value"

    def test_default_value(self):
        from session_store import SessionStore
        store = SessionStore()
        assert store.get("nonexistent", "key") is None
        assert store.get("nonexistent", "key", "default") == "default"

    def test_auto_create_on_set(self):
        from session_store import SessionStore
        store = SessionStore()
        store.set("t2", "auto", True)
        assert store.get("t2", "auto") is True

    def test_delete_session(self):
        from session_store import SessionStore
        store = SessionStore()
        store.set("t3", "data", 123)
        store.delete_session("t3")
        assert store.get("t3", "data") is None

    def test_cleanup_expired(self):
        from session_store import SessionStore
        store = SessionStore(ttl=0)  # Expire immediately
        store.set("t4", "key", "val")
        removed = store.cleanup_expired()
        assert removed == 1
        assert store.get("t4", "key") is None

    def test_cleanup_keeps_fresh(self):
        from session_store import SessionStore
        store = SessionStore(ttl=9999)
        store.set("t5", "key", "val")
        removed = store.cleanup_expired()
        assert removed == 0
        assert store.get("t5", "key") == "val"

    def test_multiple_keys_per_session(self):
        from session_store import SessionStore
        store = SessionStore()
        store.set("t6", "a", 1)
        store.set("t6", "b", 2)
        store.set("t6", "c", 3)
        assert store.get("t6", "a") == 1
        assert store.get("t6", "b") == 2
        assert store.get("t6", "c") == 3

    def test_multiple_sessions_isolated(self):
        from session_store import SessionStore
        store = SessionStore()
        store.set("s1", "name", "Alice")
        store.set("s2", "name", "Bob")
        assert store.get("s1", "name") == "Alice"
        assert store.get("s2", "name") == "Bob"

    def test_overwrite_value(self):
        from session_store import SessionStore
        store = SessionStore()
        store.set("t7", "key", "old")
        store.set("t7", "key", "new")
        assert store.get("t7", "key") == "new"


class TestUISettings:
    """Test the UI framework configuration in settings.py."""

    def setup_method(self):
        """Clear settings cache before each test."""
        from chat_app.settings import get_settings
        get_settings.cache_clear()

    def test_default_framework_is_chainlit(self):
        # Remove env var if set
        old = os.environ.pop("UI_FRAMEWORK", None)
        try:
            from chat_app.settings import get_settings
            get_settings.cache_clear()
            s = get_settings()
            assert s.ui.framework == "chainlit"
        finally:
            if old is not None:
                os.environ["UI_FRAMEWORK"] = old

    def test_env_override_to_open_webui(self):
        os.environ["UI_FRAMEWORK"] = "open-webui"
        try:
            from chat_app.settings import get_settings
            get_settings.cache_clear()
            s = get_settings()
            assert s.ui.framework == "open-webui"
        finally:
            os.environ.pop("UI_FRAMEWORK", None)

    def test_ui_settings_model(self):
        from chat_app.settings import UISettings
        ui = UISettings(framework="open-webui")
        assert ui.framework == "open-webui"

    def test_ui_settings_default(self):
        from chat_app.settings import UISettings
        ui = UISettings()
        assert ui.framework == "chainlit"


class TestOpenAICompat:
    """Test the OpenAI-compatible API module structure."""

    def test_module_imports(self):
        from chat_app.openai_compat import router, configure, list_models, chat_completions
        assert router is not None

    def test_chat_message_model(self):
        from chat_app.openai_compat import ChatMessage
        msg = ChatMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"

    def test_chat_completion_request_model(self):
        from chat_app.openai_compat import ChatCompletionRequest
        req = ChatCompletionRequest(
            model="test",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )
        assert req.model == "test"
        assert req.stream is True
        assert len(req.messages) == 1

    def test_format_completion(self):
        from chat_app.openai_compat import _format_completion
        result = _format_completion("Hello world", "test-model")
        assert result["object"] == "chat.completion"
        assert result["model"] == "test-model"
        assert result["choices"][0]["message"]["content"] == "Hello world"
        assert result["choices"][0]["finish_reason"] == "stop"
