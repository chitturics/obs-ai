"""Tests for the deterministic error taxonomy."""

import pytest
from fastapi import HTTPException


class TestErrorCodes:

    def test_all_codes_have_catalog_entry(self):
        from chat_app.error_taxonomy import ErrorCode, _ERROR_CATALOG
        for code in ErrorCode:
            assert code in _ERROR_CATALOG, f"Missing catalog entry for {code.value}"

    def test_all_entries_have_required_fields(self):
        from chat_app.error_taxonomy import _ERROR_CATALOG
        required_fields = {"status", "message", "remediation", "retry"}
        for code, entry in _ERROR_CATALOG.items():
            for field in required_fields:
                assert field in entry, f"Missing '{field}' in {code.value}"

    def test_status_codes_valid(self):
        from chat_app.error_taxonomy import _ERROR_CATALOG
        valid_statuses = {200, 202, 400, 401, 403, 404, 409, 410, 413, 422, 423, 429, 500, 501, 502, 503, 504}
        for code, entry in _ERROR_CATALOG.items():
            assert entry["status"] in valid_statuses, f"Invalid status {entry['status']} for {code.value}"


class TestRaiseError:

    def test_raise_basic_error(self):
        from chat_app.error_taxonomy import raise_error, ErrorCode
        with pytest.raises(HTTPException) as exc_info:
            raise_error(ErrorCode.AUTH_REQUIRED)
        assert exc_info.value.status_code == 401
        body = exc_info.value.detail
        assert body["error"]["code"] == "AUTH_REQUIRED"

    def test_raise_with_template_vars(self):
        from chat_app.error_taxonomy import raise_error, ErrorCode
        with pytest.raises(HTTPException) as exc_info:
            raise_error(ErrorCode.RESOURCE_NOT_FOUND, resource="collection", identifier="spl_docs")
        body = exc_info.value.detail
        assert "spl_docs" in body["error"]["message"]
        assert body["error"]["details"]["resource"] == "collection"

    def test_raise_with_headers(self):
        from chat_app.error_taxonomy import raise_error, ErrorCode
        with pytest.raises(HTTPException) as exc_info:
            raise_error(ErrorCode.RATE_LIMITED, headers={"Retry-After": "30"}, retry_after="30")
        assert exc_info.value.headers == {"Retry-After": "30"}

    def test_permission_denied_error(self):
        from chat_app.error_taxonomy import raise_error, ErrorCode
        with pytest.raises(HTTPException) as exc_info:
            raise_error(ErrorCode.PERMISSION_DENIED, resource_type="tool", resource_id="delete", action="execute")
        body = exc_info.value.detail
        assert exc_info.value.status_code == 403
        assert "tool" in body["error"]["message"]
        assert body["error"]["retry"] is False

    def test_tool_timeout_retryable(self):
        from chat_app.error_taxonomy import raise_error, ErrorCode
        with pytest.raises(HTTPException) as exc_info:
            raise_error(ErrorCode.TOOL_TIMEOUT, tool_name="splunk_search", timeout="30")
        body = exc_info.value.detail
        assert body["error"]["retry"] is True

    def test_error_body_structure(self):
        from chat_app.error_taxonomy import raise_error, ErrorCode
        with pytest.raises(HTTPException) as exc_info:
            raise_error(ErrorCode.INTERNAL_ERROR, context="test operation")
        body = exc_info.value.detail
        assert "error" in body
        assert "code" in body["error"]
        assert "message" in body["error"]
        assert "remediation" in body["error"]
        assert "retry" in body["error"]


class TestErrorCatalog:

    def test_get_catalog(self):
        from chat_app.error_taxonomy import get_error_catalog
        catalog = get_error_catalog()
        assert len(catalog) > 30
        assert "AUTH_REQUIRED" in catalog
        assert "RESOURCE_NOT_FOUND" in catalog

    def test_catalog_has_categories(self):
        from chat_app.error_taxonomy import get_error_catalog
        catalog = get_error_catalog()
        categories = set(v["category"] for v in catalog.values())
        assert "AUTH" in categories
        assert "VALIDATION" in categories
        assert "RESOURCE" in categories
        assert "TOOL" in categories
        assert "INTERNAL" in categories
