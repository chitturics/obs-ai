"""Comprehensive unit tests for chat_app.llm_utils."""
import socket
from unittest.mock import MagicMock, patch, call

import pytest

from chat_app.settings import get_settings

get_settings.cache_clear()


# ---------------------------------------------------------------------------
# _probe_ollama_url
# ---------------------------------------------------------------------------

class TestProbeOllamaUrl:
    @patch("chat_app.llm_utils.socket.create_connection")
    def test_configured_url_reachable(self, mock_conn):
        from chat_app.llm_utils import _probe_ollama_url
        mock_sock = MagicMock()
        mock_conn.return_value = mock_sock
        result = _probe_ollama_url("http://localhost:11434")
        assert result == "http://localhost:11434"
        mock_sock.close.assert_called_once()

    @patch("chat_app.llm_utils.socket.create_connection")
    def test_ipv6_fallback_for_localhost(self, mock_conn):
        from chat_app.llm_utils import _probe_ollama_url
        # First call (IPv4 localhost) fails, second call (::1) succeeds
        mock_sock = MagicMock()
        mock_conn.side_effect = [
            ConnectionRefusedError("IPv4 refused"),
            mock_sock,
        ]
        result = _probe_ollama_url("http://localhost:11434")
        assert result == "http://[::1]:11434"
        assert mock_conn.call_count == 2

    @patch("chat_app.llm_utils.socket.create_connection")
    def test_ipv6_fallback_for_127_0_0_1(self, mock_conn):
        from chat_app.llm_utils import _probe_ollama_url
        mock_sock = MagicMock()
        mock_conn.side_effect = [
            ConnectionRefusedError("IPv4 refused"),
            mock_sock,
        ]
        result = _probe_ollama_url("http://127.0.0.1:11434")
        assert result == "http://[::1]:11434"

    @patch("chat_app.llm_utils.socket.create_connection")
    def test_docker_host_fallback(self, mock_conn):
        from chat_app.llm_utils import _probe_ollama_url
        mock_sock = MagicMock()
        # configured URL fails, IPv6 fails, localhost fails,
        # host.containers.internal succeeds
        mock_conn.side_effect = [
            ConnectionRefusedError(),  # configured
            ConnectionRefusedError(),  # ::1
            ConnectionRefusedError(),  # localhost
            mock_sock,                 # host.containers.internal
        ]
        result = _probe_ollama_url("http://localhost:11434")
        assert "host.containers.internal" in result

    @patch("chat_app.llm_utils.socket.create_connection")
    def test_all_fail_returns_original(self, mock_conn):
        from chat_app.llm_utils import _probe_ollama_url
        mock_conn.side_effect = ConnectionRefusedError("all refused")
        result = _probe_ollama_url("http://localhost:11434")
        assert result == "http://localhost:11434"

    @patch("chat_app.llm_utils.socket.create_connection")
    def test_timeout_treated_as_failure(self, mock_conn):
        from chat_app.llm_utils import _probe_ollama_url
        mock_conn.side_effect = socket.timeout("timed out")
        result = _probe_ollama_url("http://localhost:11434")
        # Falls through all attempts and returns original
        assert result == "http://localhost:11434"

    @patch("chat_app.llm_utils.socket.create_connection")
    def test_os_error_treated_as_failure(self, mock_conn):
        from chat_app.llm_utils import _probe_ollama_url
        mock_conn.side_effect = OSError("network unreachable")
        result = _probe_ollama_url("http://localhost:11434")
        assert result == "http://localhost:11434"

    @patch("chat_app.llm_utils.socket.create_connection")
    def test_custom_port_preserved(self, mock_conn):
        from chat_app.llm_utils import _probe_ollama_url
        mock_sock = MagicMock()
        mock_conn.return_value = mock_sock
        result = _probe_ollama_url("http://ollama-server:9999")
        assert result == "http://ollama-server:9999"
        mock_conn.assert_called_once_with(("ollama-server", 9999), timeout=3)

    @patch("chat_app.llm_utils.socket.create_connection")
    def test_non_localhost_skips_ipv6(self, mock_conn):
        """For non-localhost hosts, IPv6 ::1 fallback should be skipped."""
        from chat_app.llm_utils import _probe_ollama_url
        mock_sock = MagicMock()
        # First call (configured) fails, then fallbacks
        calls = []

        def track_calls(addr, timeout=None):
            calls.append(addr)
            if addr[0] == "host.docker.internal":
                return mock_sock
            raise ConnectionRefusedError()

        mock_conn.side_effect = track_calls
        result = _probe_ollama_url("http://custom-host:11434")
        # Should not try ::1 since host is not localhost/127.0.0.1
        ipv6_tried = any(c[0] == "::1" for c in calls)
        assert not ipv6_tried

    @patch("chat_app.llm_utils.socket.create_connection")
    def test_default_port_when_missing(self, mock_conn):
        from chat_app.llm_utils import _probe_ollama_url
        mock_sock = MagicMock()
        mock_conn.return_value = mock_sock
        result = _probe_ollama_url("http://localhost")
        # Port defaults to 11430 in the code
        mock_conn.assert_called_once_with(("localhost", 11430), timeout=3)

    @patch("chat_app.llm_utils.socket.create_connection")
    def test_gaierror_in_fallback(self, mock_conn):
        """socket.gaierror should be caught in fallback loop."""
        from chat_app.llm_utils import _probe_ollama_url
        mock_conn.side_effect = socket.gaierror("name resolution failed")
        result = _probe_ollama_url("http://localhost:11434")
        assert result == "http://localhost:11434"


# ---------------------------------------------------------------------------
# _create_llm
# ---------------------------------------------------------------------------

class TestCreateLlm:
    def _patch_chat_ollama(self):
        """Helper to patch ChatOllama via the langchain_ollama mock module."""
        import sys
        mock_cls = MagicMock()
        if "langchain_ollama" not in sys.modules or sys.modules["langchain_ollama"] is None:
            sys.modules["langchain_ollama"] = MagicMock()
        sys.modules["langchain_ollama"].ChatOllama = mock_cls
        return mock_cls

    @patch("chat_app.llm_utils._probe_ollama_url", return_value="http://localhost:11434")
    def test_creates_llm_with_settings(self, mock_probe):
        from chat_app.llm_utils import _create_llm
        mock_cls = self._patch_chat_ollama()
        mock_cls.return_value = MagicMock()
        cfg = get_settings().ollama
        result = _create_llm()
        assert result is not None
        mock_cls.assert_called_once()
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["model"] == cfg.model
        assert call_kwargs["temperature"] == cfg.temperature
        assert call_kwargs["num_ctx"] == cfg.num_ctx
        assert call_kwargs["streaming"] is True

    @patch("chat_app.llm_utils._probe_ollama_url", return_value="http://[::1]:11434")
    def test_uses_probed_url(self, mock_probe):
        from chat_app.llm_utils import _create_llm
        mock_cls = self._patch_chat_ollama()
        mock_cls.return_value = MagicMock()
        _create_llm()
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["base_url"] == "http://[::1]:11434"

    @patch("chat_app.llm_utils._probe_ollama_url", return_value="http://localhost:11434")
    def test_returns_none_on_error(self, mock_probe):
        from chat_app.llm_utils import _create_llm
        mock_cls = self._patch_chat_ollama()
        mock_cls.side_effect = RuntimeError("connection failed")
        result = _create_llm()
        assert result is None

    def test_returns_none_when_langchain_missing(self):
        """When langchain_ollama cannot be imported, returns None."""
        import sys
        from chat_app.llm_utils import _create_llm
        saved = sys.modules.get("langchain_ollama")
        try:
            sys.modules["langchain_ollama"] = None  # Force ImportError
            result = _create_llm()
            assert result is None
        finally:
            if saved is not None:
                sys.modules["langchain_ollama"] = saved

    @patch("chat_app.llm_utils._probe_ollama_url", return_value="http://localhost:11434")
    def test_num_predict_passed(self, mock_probe):
        from chat_app.llm_utils import _create_llm
        mock_cls = self._patch_chat_ollama()
        mock_cls.return_value = MagicMock()
        cfg = get_settings().ollama
        _create_llm()
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs["num_predict"] == cfg.num_predict

    @patch("chat_app.llm_utils._probe_ollama_url", return_value="http://localhost:11434")
    def test_num_ctx_passed(self, mock_probe):
        from chat_app.llm_utils import _create_llm
        mock_cls = self._patch_chat_ollama()
        mock_cls.return_value = MagicMock()
        _create_llm()
        call_kwargs = mock_cls.call_args[1]
        assert "num_ctx" in call_kwargs


# ---------------------------------------------------------------------------
# Module-level LLM singleton
# ---------------------------------------------------------------------------

class TestLlmSingleton:
    def test_llm_module_attribute_exists(self):
        """The module should expose an LLM attribute (may be None in test env)."""
        import chat_app.llm_utils as mod
        assert hasattr(mod, "LLM")

    def test_llm_is_created_at_import(self):
        """_create_llm is called at module level to set LLM."""
        # This is a design observation: LLM = _create_llm()
        import chat_app.llm_utils as mod
        # LLM is set (could be None if ChatOllama fails, or a mock)
        assert "LLM" in dir(mod)


# ---------------------------------------------------------------------------
# URL parsing edge cases
# ---------------------------------------------------------------------------

class TestUrlParsing:
    @patch("chat_app.llm_utils.socket.create_connection")
    def test_https_scheme_preserved(self, mock_conn):
        from chat_app.llm_utils import _probe_ollama_url
        mock_sock = MagicMock()
        mock_conn.side_effect = [
            ConnectionRefusedError(),
            mock_sock,
        ]
        result = _probe_ollama_url("https://localhost:11434")
        # IPv6 fallback should use https scheme
        assert result == "https://[::1]:11434"

    @patch("chat_app.llm_utils.socket.create_connection")
    def test_url_with_path(self, mock_conn):
        from chat_app.llm_utils import _probe_ollama_url
        mock_sock = MagicMock()
        mock_conn.return_value = mock_sock
        result = _probe_ollama_url("http://localhost:11434/v1")
        assert result == "http://localhost:11434/v1"


# ---------------------------------------------------------------------------
# Settings integration
# ---------------------------------------------------------------------------

class TestSettingsIntegration:
    def test_settings_ollama_section_has_required_fields(self):
        cfg = get_settings().ollama
        assert hasattr(cfg, "model")
        assert hasattr(cfg, "base_url")
        assert hasattr(cfg, "temperature")
        assert hasattr(cfg, "num_ctx")
        assert hasattr(cfg, "num_predict")
        assert hasattr(cfg, "embed_model")

    def test_temperature_is_float(self):
        cfg = get_settings().ollama
        assert isinstance(cfg.temperature, (int, float))
        assert 0.0 <= cfg.temperature <= 2.0

    def test_num_ctx_is_positive(self):
        cfg = get_settings().ollama
        assert isinstance(cfg.num_ctx, int)
        assert cfg.num_ctx > 0
