"""Tests for chat_app/prompts.py — Prompt templates, loading, and caching."""
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from chat_app.prompts import (
    _apply_org_name,
    _get_org_names,
    _load_template,
    _template_cache,
    invalidate_template_cache,
    system_prompt,
    query_generation_prompt,
    query_analysis_prompt,
    config_guidance_prompt,
    conceptual_prompt,
    search_optimization_prompt,
    query_optimizer_prompt,
)


# ---------------------------------------------------------------------------
# Module-level prompt constants
# ---------------------------------------------------------------------------

class TestPromptConstants:
    """Tests that all prompt constants are loaded and non-empty."""

    def test_system_prompt_loaded(self):
        assert isinstance(system_prompt, str)
        assert len(system_prompt) > 100

    def test_query_generation_prompt_loaded(self):
        assert isinstance(query_generation_prompt, str)
        assert len(query_generation_prompt) > 100

    def test_query_analysis_prompt_loaded(self):
        assert isinstance(query_analysis_prompt, str)
        assert len(query_analysis_prompt) > 100

    def test_config_guidance_prompt_loaded(self):
        assert isinstance(config_guidance_prompt, str)
        assert len(config_guidance_prompt) > 100

    def test_conceptual_prompt_loaded(self):
        assert isinstance(conceptual_prompt, str)
        assert len(conceptual_prompt) > 100

    def test_search_optimization_prompt_loaded(self):
        assert isinstance(search_optimization_prompt, str)
        assert len(search_optimization_prompt) > 100

    def test_query_optimizer_prompt_loaded(self):
        assert isinstance(query_optimizer_prompt, str)
        assert len(query_optimizer_prompt) > 100


# ---------------------------------------------------------------------------
# _get_org_names
# ---------------------------------------------------------------------------

class TestGetOrgNames:
    """Tests for organization name resolution."""

    @patch("chat_app.settings.get_settings")
    def test_from_settings(self, mock_gs):
        mock_gs.return_value.app.org_name = "ACME"
        mock_gs.return_value.app.org_full_name = "Acme Corporation"
        org, org_full = _get_org_names()
        assert org == "ACME"
        assert org_full == "Acme Corporation"

    @patch("chat_app.settings.get_settings", side_effect=RuntimeError("no settings"))
    def test_fallback_to_env(self, mock_gs):
        with patch.dict(os.environ, {"ORG_NAME": "ENV_ORG", "ORG_FULL_NAME": "Env Org Full"}):
            org, org_full = _get_org_names()
            assert org == "ENV_ORG"
            assert org_full == "Env Org Full"

    @patch("chat_app.settings.get_settings", side_effect=RuntimeError("no settings"))
    def test_fallback_defaults(self, mock_gs):
        with patch.dict(os.environ, {}, clear=True):
            # Remove the env vars if present
            os.environ.pop("ORG_NAME", None)
            os.environ.pop("ORG_FULL_NAME", None)
            org, org_full = _get_org_names()
            assert org == "MY_ORG"
            assert org_full == "My Organization"


# ---------------------------------------------------------------------------
# _apply_org_name
# ---------------------------------------------------------------------------

class TestApplyOrgName:
    """Tests for org name placeholder substitution."""

    @patch("chat_app.prompts._get_org_names", return_value=("TESTORG", "Test Organization"))
    def test_replaces_org_name(self, mock_names):
        result = _apply_org_name("Welcome to {ORG_NAME}'s system")
        assert "TESTORG" in result
        assert "{ORG_NAME}" not in result

    @patch("chat_app.prompts._get_org_names", return_value=("TESTORG", "Test Organization"))
    def test_replaces_org_full_name(self, mock_names):
        result = _apply_org_name("Full name is {ORG_FULL_NAME}")
        assert "Test Organization" in result
        assert "{ORG_FULL_NAME}" not in result

    @patch("chat_app.prompts._get_org_names", return_value=("X", "Y"))
    def test_replaces_both_placeholders(self, mock_names):
        result = _apply_org_name("{ORG_NAME} aka {ORG_FULL_NAME}")
        assert result == "X aka Y"

    @patch("chat_app.prompts._get_org_names", return_value=("ORG", "Org"))
    def test_no_placeholders_unchanged(self, mock_names):
        text = "No placeholders here"
        assert _apply_org_name(text) == text

    @patch("chat_app.prompts._get_org_names", return_value=("ORG", "Org"))
    def test_empty_string(self, mock_names):
        assert _apply_org_name("") == ""


# ---------------------------------------------------------------------------
# _load_template
# ---------------------------------------------------------------------------

class TestLoadTemplate:
    """Tests for template file loading with caching."""

    def test_fallback_when_file_missing(self, tmp_path):
        """When template file does not exist, use inline fallback."""
        # Point to a non-existent path by patching _TEMPLATE_DIR
        with patch("chat_app.prompts._TEMPLATE_DIR", tmp_path):
            result = _load_template("nonexistent", "fallback content")
            assert "fallback content" in result

    def test_loads_from_file(self, tmp_path):
        """When template file exists, load from it."""
        template_file = tmp_path / "test_tmpl.md"
        template_file.write_text("File template content")

        with patch("chat_app.prompts._TEMPLATE_DIR", tmp_path):
            result = _load_template("test_tmpl", "fallback")
            assert "File template content" in result

    def test_caching_by_mtime(self, tmp_path):
        """Second load should use cache if mtime unchanged."""
        template_file = tmp_path / "cached.md"
        template_file.write_text("Cached content")

        with patch("chat_app.prompts._TEMPLATE_DIR", tmp_path):
            # Clear relevant cache entry
            _template_cache.pop("cached", None)

            result1 = _load_template("cached", "fallback")
            result2 = _load_template("cached", "fallback")
            assert result1 == result2
            assert "cached" in _template_cache

    def test_cache_invalidated_on_mtime_change(self, tmp_path):
        """If file mtime changes, cache should refresh."""
        template_file = tmp_path / "changing.md"
        template_file.write_text("Version 1")

        with patch("chat_app.prompts._TEMPLATE_DIR", tmp_path):
            _template_cache.pop("changing", None)
            result1 = _load_template("changing", "fallback")
            assert "Version 1" in result1

            # Update file
            template_file.write_text("Version 2")
            # Force different mtime
            import time
            time.sleep(0.05)
            template_file.touch()

            result2 = _load_template("changing", "fallback")
            assert "Version 2" in result2

    def test_org_name_applied_in_file_templates(self, tmp_path):
        """Org name placeholders in file templates should be replaced."""
        template_file = tmp_path / "org_tmpl.md"
        template_file.write_text("Welcome to {ORG_NAME}")

        with patch("chat_app.prompts._TEMPLATE_DIR", tmp_path):
            _template_cache.pop("org_tmpl", None)
            result = _load_template("org_tmpl", "fallback")
            assert "{ORG_NAME}" not in result

    def test_org_name_applied_in_fallback(self):
        """Org name placeholders in fallback text should be replaced."""
        with patch("chat_app.prompts._TEMPLATE_DIR", Path("/nonexistent")):
            result = _load_template("missing", "Hello {ORG_NAME}")
            assert "{ORG_NAME}" not in result


# ---------------------------------------------------------------------------
# invalidate_template_cache
# ---------------------------------------------------------------------------

class TestInvalidateTemplateCache:
    """Tests for cache invalidation."""

    def test_clears_cache_returns_count(self):
        _template_cache["test_entry"] = (0.0, "content")
        _template_cache["test_entry2"] = (0.0, "content2")
        count = invalidate_template_cache()
        assert count >= 2
        assert len(_template_cache) == 0

    def test_empty_cache_returns_zero(self):
        _template_cache.clear()
        assert invalidate_template_cache() == 0


# ---------------------------------------------------------------------------
# System prompt content verification
# ---------------------------------------------------------------------------

class TestSystemPromptContent:
    """Tests verifying system prompt contains expected sections."""

    def test_contains_identity_or_role(self):
        # Template file may use different wording than inline default
        lower = system_prompt.lower()
        assert "splunk" in lower or "obsai" in lower

    def test_contains_knowledge_section(self):
        assert "What You Know" in system_prompt or "Knowledge" in system_prompt

    def test_contains_spl_references(self):
        assert "tstats" in system_prompt

    def test_contains_collection_or_repo_priority(self):
        assert "org_repo" in system_prompt or "REPO" in system_prompt or "repo" in system_prompt.lower()

    def test_contains_response_guidelines(self):
        assert "Be specific" in system_prompt or "concise" in system_prompt.lower()

    def test_no_unresolved_org_placeholder(self):
        assert "{ORG_NAME}" not in system_prompt
        assert "{ORG_FULL_NAME}" not in system_prompt


# ---------------------------------------------------------------------------
# Query generation prompt content
# ---------------------------------------------------------------------------

class TestQueryGenerationPromptContent:
    """Tests verifying query generation prompt structure."""

    def test_contains_variable_placeholders(self):
        # These should remain as {question}, {content}, {examples} for runtime filling
        assert "{question}" in query_generation_prompt
        assert "{content}" in query_generation_prompt

    def test_contains_spl_examples(self):
        assert "```spl" in query_generation_prompt or "```" in query_generation_prompt

    def test_no_unresolved_org_placeholder(self):
        assert "{ORG_NAME}" not in query_generation_prompt


# ---------------------------------------------------------------------------
# Query analysis prompt content
# ---------------------------------------------------------------------------

class TestQueryAnalysisPromptContent:
    """Tests verifying query analysis prompt structure."""

    def test_contains_result_placeholders(self):
        assert "{splunkQuery}" in query_analysis_prompt or "{question}" in query_analysis_prompt

    def test_contains_analysis_framework(self):
        lower = query_analysis_prompt.lower()
        assert "analysis" in lower or "interpret" in lower


# ---------------------------------------------------------------------------
# Special character handling
# ---------------------------------------------------------------------------

class TestSpecialCharacters:
    """Tests for special character handling in prompts."""

    @patch("chat_app.prompts._get_org_names", return_value=("O'Reilly", "O'Reilly & Co."))
    def test_apostrophe_in_org_name(self, mock_names):
        result = _apply_org_name("{ORG_NAME} system")
        assert "O'Reilly" in result

    @patch("chat_app.prompts._get_org_names", return_value=("Test<Corp>", "Test&Corp"))
    def test_html_chars_in_org_name(self, mock_names):
        result = _apply_org_name("{ORG_NAME} and {ORG_FULL_NAME}")
        assert "Test<Corp>" in result
        assert "Test&Corp" in result

    @patch("chat_app.prompts._get_org_names", return_value=("", ""))
    def test_empty_org_name(self, mock_names):
        result = _apply_org_name("{ORG_NAME} system")
        assert result == " system"


# ---------------------------------------------------------------------------
# Prompt aliases
# ---------------------------------------------------------------------------

class TestPromptAliases:
    """Tests that backward-compatible aliases are set."""

    def test_agent_system_prompt_alias(self):
        from chat_app.prompts import agent_system_prompt
        assert agent_system_prompt == system_prompt

    def test_splunk_query_generation_alias(self):
        from chat_app.prompts import splunk_query_generation_prompt
        assert splunk_query_generation_prompt == query_generation_prompt

    def test_splunk_query_analysis_alias(self):
        from chat_app.prompts import splunk_query_analysis_prompt
        assert splunk_query_analysis_prompt == query_analysis_prompt

    def test_text_analysis_alias(self):
        from chat_app.prompts import text_analysis_prompt
        assert text_analysis_prompt == conceptual_prompt
