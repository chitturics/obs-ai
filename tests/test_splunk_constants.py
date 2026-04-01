"""Tests for chat_app/splunk_constants.py — SPL command and .conf file allowlists."""
import pytest
from chat_app.splunk_constants import (
    is_allowed_command,
    is_allowed_conf_file,
    get_command_type,
    get_conf_file_type,
    format_allowed_commands_for_prompt,
    format_allowed_conf_files_for_prompt,
    ALLOWED_SEARCH_COMMANDS,
    ALLOWED_CONF_FILES,
)


class TestIsAllowedCommand:
    """Test SPL command allowlist validation."""

    def test_common_commands_allowed(self):
        for cmd in ["stats", "eval", "where", "table", "fields", "search", "tstats", "rex", "join"]:
            assert is_allowed_command(cmd), f"{cmd} should be allowed"

    def test_unknown_command_rejected(self):
        assert not is_allowed_command("superquery")
        assert not is_allowed_command("fakecommand")
        assert not is_allowed_command("")

    def test_all_173_commands_in_set(self):
        assert len(ALLOWED_SEARCH_COMMANDS) >= 170

    def test_generating_commands_present(self):
        for cmd in ["makeresults", "inputlookup", "rest", "metadata", "tstats"]:
            assert is_allowed_command(cmd)

    def test_streaming_commands_present(self):
        for cmd in ["eval", "where", "rex", "rename", "fields"]:
            assert is_allowed_command(cmd)


class TestIsAllowedConfFile:
    """Test .conf file allowlist validation."""

    def test_common_conf_files_allowed(self):
        for f in ["inputs.conf", "outputs.conf", "props.conf", "transforms.conf", "indexes.conf"]:
            assert is_allowed_conf_file(f), f"{f} should be allowed"

    def test_spec_suffix_stripped(self):
        assert is_allowed_conf_file("inputs.conf.spec")
        assert is_allowed_conf_file("props.conf.spec")

    def test_unknown_conf_rejected(self):
        assert not is_allowed_conf_file("my_custom.conf")
        assert not is_allowed_conf_file("")

    def test_all_70_conf_files_in_set(self):
        assert len(ALLOWED_CONF_FILES) >= 65


class TestGetCommandType:
    """Test command type classification."""

    def test_builtin_command(self):
        assert get_command_type("stats") == "built-in"
        assert get_command_type("eval") == "built-in"

    def test_unknown_command(self):
        result = get_command_type("nonexistent")
        assert result in ("custom", "unknown")


class TestGetConfFileType:
    """Test .conf file type classification."""

    def test_builtin_conf(self):
        assert get_conf_file_type("props.conf") == "built-in"
        assert get_conf_file_type("indexes.conf") == "built-in"

    def test_unknown_conf(self):
        result = get_conf_file_type("random.conf")
        assert result in ("custom", "unknown")


class TestFormatForPrompt:
    """Test prompt formatting functions."""

    def test_commands_formatted_as_string(self):
        result = format_allowed_commands_for_prompt()
        assert isinstance(result, str)
        assert len(result) > 100
        assert "stats" in result
        assert "eval" in result

    def test_conf_files_formatted_as_string(self):
        result = format_allowed_conf_files_for_prompt()
        assert isinstance(result, str)
        assert len(result) > 50
        assert "props.conf" in result
        assert "inputs.conf" in result
