"""Tests for Splunk writer tools (update_saved_search, create_knowledge_object)."""
import pytest
import sys
from unittest.mock import MagicMock, patch


# splunklib is not installed in test env, so mock it for SplunkClient tests
splunklib_mock = MagicMock()
sys.modules.setdefault("splunklib", splunklib_mock)
sys.modules.setdefault("splunklib.client", splunklib_mock.client)
sys.modules.setdefault("splunklib.results", splunklib_mock.results)


class TestSplunkClientWriterMethods:
    """Test SplunkClient write methods without live Splunk."""

    def test_update_saved_search_not_found(self):
        """update_saved_search raises ValueError for missing search."""
        from chat_app.splunk_client import SplunkClient
        sc = SplunkClient.__new__(SplunkClient)
        sc.service = MagicMock()
        sc.service.saved_searches.__getitem__ = MagicMock(side_effect=KeyError("not_found"))
        with pytest.raises(ValueError, match="not found"):
            sc.update_saved_search("not_found")

    def test_create_knowledge_object_invalid_type(self):
        """create_knowledge_object rejects unsupported object types."""
        from chat_app.splunk_client import SplunkClient
        sc = SplunkClient.__new__(SplunkClient)
        sc.service = MagicMock()
        with pytest.raises(ValueError, match="Unsupported object_type"):
            sc.create_knowledge_object("invalid_type", "test", "definition")

    def test_create_knowledge_object_macro(self):
        from chat_app.splunk_client import SplunkClient
        sc = SplunkClient.__new__(SplunkClient)
        sc.service = MagicMock()
        result = sc.create_knowledge_object("macro", "test_macro", "index=main | stats count")
        assert result["type"] == "macro"
        assert result["name"] == "test_macro"

    def test_create_knowledge_object_eventtype(self):
        from chat_app.splunk_client import SplunkClient
        sc = SplunkClient.__new__(SplunkClient)
        sc.service = MagicMock()
        result = sc.create_knowledge_object("eventtypes", "test_et", "index=main error")
        assert result["type"] == "eventtype"

    def test_create_knowledge_object_tag(self):
        from chat_app.splunk_client import SplunkClient
        sc = SplunkClient.__new__(SplunkClient)
        sc.service = MagicMock()
        result = sc.create_knowledge_object("tags", "test_tag", "host=web01")
        assert result["type"] == "tag"

    def test_create_knowledge_object_saved_search(self):
        from chat_app.splunk_client import SplunkClient
        sc = SplunkClient.__new__(SplunkClient)
        sc.service = MagicMock()
        sc.service.saved_searches.create = MagicMock()
        result = sc.create_knowledge_object("saved_search", "test_ss", "index=main | head 10")
        assert result["type"] == "saved_search"

    def test_update_saved_search_success(self):
        from chat_app.splunk_client import SplunkClient
        sc = SplunkClient.__new__(SplunkClient)
        sc.service = MagicMock()
        mock_saved = MagicMock()
        mock_saved.name = "my_search"
        mock_saved.__getitem__ = lambda self, key: "old query" if key == "search" else ""
        mock_saved.content = {"description": "old desc", "cron_schedule": "*/5 * * * *", "disabled": "0"}
        mock_saved.update.return_value = mock_saved
        mock_saved.refresh.return_value = None
        sc.service.saved_searches.__getitem__ = MagicMock(return_value=mock_saved)

        result = sc.update_saved_search("my_search", search="new query")
        assert "fields_changed" in result
        assert "search" in result["fields_changed"]


class TestWriterToolFunctions:
    """Test tool_registry writer tool functions."""

    def test_update_saved_search_no_fields(self):
        """update tool returns error if no fields provided."""
        from chat_app.tool_registry import _tool_update_saved_search
        result = _tool_update_saved_search(name="test")
        assert not result.success
        assert "No fields" in result.error

    def test_update_saved_search_with_mock(self):
        """update tool calls client with correct kwargs."""
        from chat_app.tool_registry import _tool_update_saved_search
        with patch("chat_app.splunk_client.SplunkClient") as MockClient:
            mock_sc = MagicMock()
            mock_sc.update_saved_search.return_value = {
                "previous": {"search": "old query"},
                "updated": {"search": "new query"},
                "fields_changed": ["search"],
            }
            MockClient.return_value = mock_sc
            result = _tool_update_saved_search(name="my_search", search="new query")
            assert result.success
            assert "Updated saved search" in result.output

    def test_create_knowledge_object_with_mock(self):
        from chat_app.tool_registry import _tool_create_knowledge_object
        with patch("chat_app.splunk_client.SplunkClient") as MockClient:
            mock_sc = MagicMock()
            mock_sc.create_knowledge_object.return_value = {
                "type": "macro", "name": "my_macro",
                "definition": "index=main", "app": "search",
            }
            MockClient.return_value = mock_sc
            result = _tool_create_knowledge_object(
                object_type="macro", name="my_macro", definition="index=main",
            )
            assert result.success
            assert "Created macro" in result.output

    def test_create_knowledge_object_invalid_type(self):
        from chat_app.tool_registry import _tool_create_knowledge_object
        with patch("chat_app.splunk_client.SplunkClient") as MockClient:
            mock_sc = MagicMock()
            mock_sc.create_knowledge_object.side_effect = ValueError("Unsupported")
            MockClient.return_value = mock_sc
            result = _tool_create_knowledge_object(
                object_type="invalid", name="test", definition="test",
            )
            assert not result.success


class TestWriterSkillHandlers:
    """Test skill_executor writer handlers."""

    def test_handler_update_saved_search_no_name(self):
        from chat_app.handlers.meta_handlers import _handler_update_saved_search
        result = _handler_update_saved_search()
        assert "required" in result.lower() or "error" in result.lower()

    def test_handler_update_saved_search_no_fields(self):
        from chat_app.handlers.meta_handlers import _handler_update_saved_search
        result = _handler_update_saved_search(user_input="test_search", name="test_search")
        assert "no fields" in result.lower() or "error" in result.lower()

    def test_handler_create_knowledge_object_missing_params(self):
        from chat_app.handlers.meta_handlers import _handler_create_knowledge_object
        result = _handler_create_knowledge_object()
        assert "required" in result.lower() or "error" in result.lower()


class TestWriterSkillCatalog:
    """Verify writer skills are properly registered."""

    def test_update_saved_search_skill_exists(self):
        from chat_app.skill_catalog import get_skill_catalog
        cat = get_skill_catalog()
        skill = cat.get("update_saved_search")
        assert skill is not None
        assert skill.handler_key == "update_saved_search"

    def test_create_knowledge_object_skill_exists(self):
        from chat_app.skill_catalog import get_skill_catalog
        cat = get_skill_catalog()
        skill = cat.get("create_knowledge_object")
        assert skill is not None
        assert skill.handler_key == "create_knowledge_object"

    def test_writer_skills_require_review_approval(self):
        from chat_app.skill_catalog import get_skill_catalog, ApprovalGate
        cat = get_skill_catalog()
        for name in ("update_saved_search", "create_knowledge_object"):
            skill = cat.get(name)
            assert skill is not None
            assert skill.approval == ApprovalGate.REVIEW, f"{name} should require REVIEW approval"

    def test_writer_skills_require_splunk_connected(self):
        from chat_app.skill_catalog import get_skill_catalog
        cat = get_skill_catalog()
        for name in ("update_saved_search", "create_knowledge_object"):
            skill = cat.get(name)
            assert "splunk_connected" in skill.requires


class TestWriterToolRegistry:
    """Verify writer tools are registered in tool_registry."""

    def test_update_saved_search_tool_registered(self):
        from chat_app.tool_registry import get_tool_registry
        reg = get_tool_registry()
        tool = reg.get_tool("update_saved_search")
        assert tool is not None
        assert "splunk_connected" in tool.requires

    def test_create_knowledge_object_tool_registered(self):
        from chat_app.tool_registry import get_tool_registry
        reg = get_tool_registry()
        tool = reg.get_tool("create_knowledge_object")
        assert tool is not None
        assert "splunk_connected" in tool.requires
