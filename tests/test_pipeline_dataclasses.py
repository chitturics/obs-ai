"""Tests for pipeline dataclass models (RetrievalResult, LLMContextResult, BuildLLMContextRequest)."""

import pytest


class TestRetrievalResult:

    def test_default_construction(self):
        from chat_app.pipeline_models import RetrievalResult
        result = RetrievalResult()
        assert result.memory_chunks == []
        assert result.local_spec_content == []
        assert result.detected_profile is None
        assert result.has_conf_context is False

    def test_populated_construction(self):
        from chat_app.pipeline_models import RetrievalResult
        result = RetrievalResult(
            memory_chunks=["chunk1", "chunk2"],
            local_spec_content=["spec content"],
            local_spec_refs=["ref1"],
            detected_profile="splunk_admin",
            chroma_source="spl_docs",
            has_conf_context=True,
            conf_files=["inputs.conf"],
        )
        assert len(result.memory_chunks) == 2
        assert result.detected_profile == "splunk_admin"
        assert result.has_conf_context is True
        assert result.conf_files == ["inputs.conf"]


class TestLLMContextResult:

    def test_default_construction(self):
        from chat_app.pipeline_models import LLMContextResult
        result = LLMContextResult()
        assert result.formatted_context == ""
        assert result.system_prompt == ""
        assert result.feedback_match is None
        assert result.all_refs == []
        assert result.scored_chunks == []

    def test_populated_construction(self):
        from chat_app.pipeline_models import LLMContextResult
        result = LLMContextResult(
            formatted_context="Context here",
            system_prompt="You are a Splunk assistant",
            all_refs=["spl_docs:search.md"],
            scored_chunks=[{"text": "chunk", "score": 0.9}],
            doc_snippets=["snippet 1"],
        )
        assert result.formatted_context == "Context here"
        assert len(result.all_refs) == 1
        assert len(result.scored_chunks) == 1


class TestBuildLLMContextRequest:

    def test_default_construction(self):
        from chat_app.pipeline_models import BuildLLMContextRequest
        req = BuildLLMContextRequest(user_input="test query")
        assert req.user_input == "test query"
        assert req.memory_chunks == []
        assert req.username == ""
        assert req.profiles_available is False
        assert req.plan is None

    def test_full_construction(self):
        from chat_app.pipeline_models import BuildLLMContextRequest
        req = BuildLLMContextRequest(
            user_input="search for errors",
            memory_chunks=["chunk1"],
            user_settings={"model": "llama3"},
            username="admin",
            system_prompt="You are helpful",
            profiles_available=True,
            detected_profile="splunk_admin",
            feedback_guardrails_available=True,
        )
        assert req.user_input == "search for errors"
        assert req.username == "admin"
        assert req.profiles_available is True
        assert req.detected_profile == "splunk_admin"

    def test_request_is_dataclass(self):
        from chat_app.pipeline_models import BuildLLMContextRequest
        from dataclasses import fields
        field_names = [f.name for f in fields(BuildLLMContextRequest)]
        assert "user_input" in field_names
        assert "memory_chunks" in field_names
        assert "engine" in field_names
        assert len(field_names) == 15  # 15 parameters consolidated
