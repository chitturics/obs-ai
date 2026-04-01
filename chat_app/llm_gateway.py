"""Multi-LLM Gateway with automatic fallback across providers.

Supports: Ollama (local), OpenAI, Anthropic, Google Gemini, Azure OpenAI,
and MCP-as-LLM (route inference through any MCP server that exposes a
generate/complete tool).

Provider selection:
  1. Explicit provider= kwarg per call
  2. Fallback chain (cloud providers first if API keys present, Ollama last)
  3. Task-type recommendations via recommend_model()

Configuration:
  - Provider API keys via environment variables (see _ENV_KEYS)
  - Model defaults via config/llm.yaml → providers section
  - MCP-as-LLM via config/llm.yaml → mcp_llm section
"""

import json
import logging
import os
import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, AsyncIterator, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response dataclass
# ---------------------------------------------------------------------------

@dataclass
class LLMResponse:
    """Standardised response envelope from any provider."""

    text: str
    model: str
    provider: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0
    cost_usd: float = 0.0
    finish_reason: str = "stop"


# ---------------------------------------------------------------------------
# Base provider
# ---------------------------------------------------------------------------

class _BaseProvider:
    """Common interface every provider must implement."""

    provider_name: str = ""

    def is_available(self) -> bool:
        raise NotImplementedError

    async def generate(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: int = 256,
    ) -> LLMResponse:
        raise NotImplementedError

    async def stream(
        self,
        prompt: str,
        system: str = "",
        temperature: float = 0.1,
        max_tokens: int = 256,
    ) -> AsyncIterator[str]:
        """Default: yield the full response at once."""
        yield (await self.generate(prompt, system, temperature, max_tokens)).text


# ---------------------------------------------------------------------------
# Ollama (local)
# ---------------------------------------------------------------------------

class OllamaProvider(_BaseProvider):
    provider_name = "ollama"

    def __init__(self, base_url: str = "", model: str = "qwen2.5:3b"):
        self.base_url = base_url or os.getenv("OLLAMA_BASE_URL", "http://localhost:11430")
        self.model = model

    async def generate(self, prompt, system="", temperature=0.1, max_tokens=256):
        import httpx

        start = time.monotonic()
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "system": system,
                    "stream": False,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
            )
            data = resp.json()
        return LLMResponse(
            text=data.get("response", ""),
            model=self.model,
            provider="ollama",
            input_tokens=data.get("prompt_eval_count", 0),
            output_tokens=data.get("eval_count", 0),
            latency_ms=int((time.monotonic() - start) * 1000),
        )

    async def stream(self, prompt, system="", temperature=0.1, max_tokens=256):
        import httpx

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "system": system,
                    "stream": True,
                    "options": {"temperature": temperature, "num_predict": max_tokens},
                },
            ) as resp:
                async for line in resp.aiter_lines():
                    if line and "response" in (d := json.loads(line)):
                        yield d["response"]

    def is_available(self) -> bool:
        try:
            import httpx

            return httpx.get(f"{self.base_url}/api/tags", timeout=5.0).status_code == 200
        except Exception:
            return False


# ---------------------------------------------------------------------------
# Cloud providers — share API-key pattern
# ---------------------------------------------------------------------------

class _CloudProvider(_BaseProvider):
    """Base for API-key cloud providers."""

    provider_name = ""
    _env_key = ""

    def __init__(self, api_key: str = "", model: str = ""):
        self.api_key = api_key or os.getenv(self._env_key, "")
        self.model = model

    def is_available(self) -> bool:
        return bool(self.api_key)

    async def stream(self, prompt, system="", temperature=0.1, max_tokens=256):
        yield (await self.generate(prompt, system, temperature, max_tokens)).text


class OpenAIProvider(_CloudProvider):
    provider_name = "openai"
    _env_key = "OPENAI_API_KEY"

    def __init__(self, api_key="", model="gpt-4o-mini", base_url: str = ""):
        super().__init__(api_key, model)
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com")

    async def generate(self, prompt, system="", temperature=0.1, max_tokens=256):
        import httpx

        messages = (
            [{"role": "system", "content": system}] if system else []
        ) + [{"role": "user", "content": prompt}]
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=60.0) as client:
            data = (
                await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                )
            ).json()
        choice = data.get("choices", [{}])[0]
        usage = data.get("usage", {})
        return LLMResponse(
            text=choice.get("message", {}).get("content", ""),
            model=self.model,
            provider="openai",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=int((time.monotonic() - start) * 1000),
            finish_reason=choice.get("finish_reason", "stop"),
        )


class AnthropicProvider(_CloudProvider):
    """Anthropic Claude API (messages endpoint)."""

    provider_name = "anthropic"
    _env_key = "ANTHROPIC_API_KEY"

    def __init__(self, api_key="", model="claude-sonnet-4-20250514"):
        super().__init__(api_key, model)

    async def generate(self, prompt, system="", temperature=0.1, max_tokens=256):
        import httpx

        start = time.monotonic()
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system
        async with httpx.AsyncClient(timeout=60.0) as client:
            data = (
                await client.post(
                    "https://api.anthropic.com/v1/messages",
                    headers={
                        "x-api-key": self.api_key,
                        "anthropic-version": "2023-06-01",
                        "content-type": "application/json",
                    },
                    json=payload,
                )
            ).json()
        usage = data.get("usage", {})
        content_blocks = data.get("content", [])
        text = content_blocks[0].get("text", "") if content_blocks else ""
        return LLMResponse(
            text=text,
            model=self.model,
            provider="anthropic",
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
            latency_ms=int((time.monotonic() - start) * 1000),
            finish_reason=data.get("stop_reason", "end_turn"),
        )


class GoogleProvider(_CloudProvider):
    """Google Gemini API."""

    provider_name = "google"
    _env_key = "GOOGLE_API_KEY"

    def __init__(self, api_key="", model="gemini-2.0-flash"):
        super().__init__(api_key, model)

    async def generate(self, prompt, system="", temperature=0.1, max_tokens=256):
        import httpx

        contents = []
        if system:
            contents += [
                {"role": "user", "parts": [{"text": system}]},
                {"role": "model", "parts": [{"text": "Understood."}]},
            ]
        contents.append({"role": "user", "parts": [{"text": prompt}]})
        start = time.monotonic()
        async with httpx.AsyncClient(timeout=60.0) as client:
            data = (
                await client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent?key={self.api_key}",
                    json={
                        "contents": contents,
                        "generationConfig": {
                            "temperature": temperature,
                            "maxOutputTokens": max_tokens,
                        },
                    },
                )
            ).json()
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        usage = data.get("usageMetadata", {})
        return LLMResponse(
            text=parts[0].get("text", "") if parts else "",
            model=self.model,
            provider="google",
            input_tokens=usage.get("promptTokenCount", 0),
            output_tokens=usage.get("candidatesTokenCount", 0),
            latency_ms=int((time.monotonic() - start) * 1000),
        )


class AzureOpenAIProvider(_CloudProvider):
    """Azure-hosted OpenAI models."""

    provider_name = "azure_openai"
    _env_key = "AZURE_OPENAI_API_KEY"

    def __init__(self, api_key="", model="gpt-4o-mini", endpoint: str = "", api_version: str = ""):
        super().__init__(api_key, model)
        self.endpoint = endpoint or os.getenv("AZURE_OPENAI_ENDPOINT", "")
        self.api_version = api_version or os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01")

    def is_available(self) -> bool:
        return bool(self.api_key) and bool(self.endpoint)

    async def generate(self, prompt, system="", temperature=0.1, max_tokens=256):
        import httpx

        messages = (
            [{"role": "system", "content": system}] if system else []
        ) + [{"role": "user", "content": prompt}]
        start = time.monotonic()
        url = f"{self.endpoint}/openai/deployments/{self.model}/chat/completions?api-version={self.api_version}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            data = (
                await client.post(
                    url,
                    headers={"api-key": self.api_key},
                    json={
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                )
            ).json()
        choice = data.get("choices", [{}])[0]
        usage = data.get("usage", {})
        return LLMResponse(
            text=choice.get("message", {}).get("content", ""),
            model=self.model,
            provider="azure_openai",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=int((time.monotonic() - start) * 1000),
            finish_reason=choice.get("finish_reason", "stop"),
        )


# ---------------------------------------------------------------------------
# MCP-as-LLM — route inference through an MCP server
# ---------------------------------------------------------------------------

class MCPLLMProvider(_BaseProvider):
    """Use any MCP server that exposes a text-generation tool as an LLM.

    The MCP server must expose a tool matching ``tool_name`` (default:
    ``generate``) that accepts ``{"prompt": str, "system": str,
    "temperature": float, "max_tokens": int}`` and returns
    ``{"text": str}``.

    Configuration via environment or config/llm.yaml → mcp_llm:
        MCP_LLM_ENDPOINT  — MCP server URL (SSE or HTTP)
        MCP_LLM_TOOL_NAME — tool name to invoke (default: "generate")
        MCP_LLM_API_KEY   — optional bearer token
    """

    provider_name = "mcp_llm"

    def __init__(
        self,
        endpoint: str = "",
        tool_name: str = "",
        api_key: str = "",
        model_label: str = "mcp-llm",
    ):
        self.endpoint = endpoint or os.getenv("MCP_LLM_ENDPOINT", "")
        self.tool_name = tool_name or os.getenv("MCP_LLM_TOOL_NAME", "generate")
        self.api_key = api_key or os.getenv("MCP_LLM_API_KEY", "")
        self.model = model_label

    def is_available(self) -> bool:
        return bool(self.endpoint)

    async def generate(self, prompt, system="", temperature=0.1, max_tokens=256):
        import httpx

        start = time.monotonic()
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # MCP tool call payload — wraps prompt in the tool's expected arguments
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": self.tool_name,
                "arguments": {
                    "prompt": prompt,
                    "system": system,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
            },
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(self.endpoint, headers=headers, json=payload)
            data = resp.json()

        # Extract text from MCP tool result
        result = data.get("result", {})
        # MCP tools return content as list of content blocks
        content_blocks = result.get("content", [])
        text = ""
        if isinstance(content_blocks, list) and content_blocks:
            text = content_blocks[0].get("text", "")
        elif isinstance(result, dict):
            text = result.get("text", str(result))

        return LLMResponse(
            text=text,
            model=self.model,
            provider="mcp_llm",
            latency_ms=int((time.monotonic() - start) * 1000),
        )


# ---------------------------------------------------------------------------
# OpenAI-compatible provider — works with vLLM, LMStudio, LocalAI, etc.
# ---------------------------------------------------------------------------

class OpenAICompatibleProvider(_CloudProvider):
    """Any server that implements the OpenAI chat completions API."""

    provider_name = "openai_compatible"
    _env_key = "OPENAI_COMPATIBLE_API_KEY"

    def __init__(self, api_key="", model="", base_url: str = ""):
        super().__init__(api_key or "not-needed", model)
        self.base_url = base_url or os.getenv("OPENAI_COMPATIBLE_BASE_URL", "")

    def is_available(self) -> bool:
        return bool(self.base_url)

    async def generate(self, prompt, system="", temperature=0.1, max_tokens=256):
        import httpx

        messages = (
            [{"role": "system", "content": system}] if system else []
        ) + [{"role": "user", "content": prompt}]
        start = time.monotonic()
        headers = {"Content-Type": "application/json"}
        if self.api_key and self.api_key != "not-needed":
            headers["Authorization"] = f"Bearer {self.api_key}"
        async with httpx.AsyncClient(timeout=120.0) as client:
            data = (
                await client.post(
                    f"{self.base_url}/v1/chat/completions",
                    headers=headers,
                    json={
                        "model": self.model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                )
            ).json()
        choice = data.get("choices", [{}])[0]
        usage = data.get("usage", {})
        return LLMResponse(
            text=choice.get("message", {}).get("content", ""),
            model=self.model,
            provider="openai_compatible",
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
            latency_ms=int((time.monotonic() - start) * 1000),
            finish_reason=choice.get("finish_reason", "stop"),
        )


# ---------------------------------------------------------------------------
# Task-type recommendations
# ---------------------------------------------------------------------------

_RECOMMENDATIONS = {
    "general": {"model": "qwen2.5:3b", "provider": "ollama", "reason": "Fast local inference for general queries"},
    "code": {"model": "qwen2.5:7b", "provider": "ollama", "reason": "Better code understanding with larger model"},
    "complex": {"model": "claude-sonnet-4-20250514", "provider": "anthropic", "reason": "Deep reasoning for complex analysis"},
    "creative": {"model": "gpt-4o", "provider": "openai", "reason": "Creative generation and nuanced writing"},
    "spl": {"model": "qwen2.5:7b", "provider": "ollama", "reason": "SPL generation benefits from local fine-tuned context"},
    "summarization": {"model": "gemini-2.0-flash", "provider": "google", "reason": "Fast summarization with large context window"},
}


# ---------------------------------------------------------------------------
# Provider registry — maps name → class + env key
# ---------------------------------------------------------------------------

_PROVIDER_REGISTRY: Dict[str, type] = {
    "ollama": OllamaProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "azure_openai": AzureOpenAIProvider,
    "mcp_llm": MCPLLMProvider,
    "openai_compatible": OpenAICompatibleProvider,
}

_ENV_KEYS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "azure_openai": "AZURE_OPENAI_API_KEY",
    "mcp_llm": "MCP_LLM_ENDPOINT",
    "openai_compatible": "OPENAI_COMPATIBLE_BASE_URL",
}


# ---------------------------------------------------------------------------
# Gateway
# ---------------------------------------------------------------------------

class LLMGateway:
    """Unified gateway across all configured LLM providers."""

    def __init__(self, provider_config: Optional[Dict[str, Dict]] = None):
        self._providers: Dict[str, _BaseProvider] = {}
        self._fallback_chain: List[str] = []
        self._call_stats: Dict[str, Dict[str, int]] = {}
        self._init_providers(provider_config or {})

    def _init_providers(self, provider_config: Dict[str, Dict]):
        """Initialise providers from config dict + environment variables."""

        # Ollama is always registered (local, no key needed)
        ollama_cfg = provider_config.get("ollama", {})
        self._providers["ollama"] = OllamaProvider(
            base_url=ollama_cfg.get("base_url", ""),
            model=ollama_cfg.get("model", "qwen2.5:3b"),
        )
        self._fallback_chain.append("ollama")

        # Cloud / remote providers — register if API key or endpoint is present
        for name, cls in _PROVIDER_REGISTRY.items():
            if name == "ollama":
                continue
            cfg = provider_config.get(name, {})
            env_key = _ENV_KEYS.get(name, "")

            # Determine if this provider should be registered
            has_env = bool(os.getenv(env_key)) if env_key else False
            has_config = bool(cfg.get("api_key") or cfg.get("endpoint") or cfg.get("base_url"))

            if has_env or has_config:
                try:
                    instance = cls(**cfg) if cfg else cls()
                    self._providers[name] = instance
                    # Cloud providers go first in fallback chain
                    self._fallback_chain.insert(-1, name)
                except Exception as exc:
                    logger.warning("[LLM-GW] Failed to init provider %s: %s", name, exc)

        logger.info(
            "[LLM-GW] Providers: %s, fallback chain: %s",
            list(self._providers),
            self._fallback_chain,
        )

    async def generate(
        self,
        prompt: str,
        system: str = "",
        provider: str = "",
        **kwargs,
    ) -> LLMResponse:
        """Generate a response, falling back through the provider chain."""
        chain = [provider] if provider in self._providers else self._fallback_chain
        last_error = None
        for name in chain:
            prov = self._providers.get(name)
            if not prov or not prov.is_available():
                continue
            try:
                result = await prov.generate(prompt, system, **kwargs)
                self._call_stats.setdefault(name, {"success": 0, "failure": 0})["success"] += 1
                try:
                    from chat_app.cost_tracker import record_llm_cost

                    record_llm_cost(
                        result.model,
                        "generation",
                        result.input_tokens,
                        result.output_tokens,
                        latency_ms=result.latency_ms,
                    )
                except (ImportError, RuntimeError):
                    pass
                return result
            except Exception as exc:
                last_error = exc
                self._call_stats.setdefault(name, {"success": 0, "failure": 0})["failure"] += 1
                logger.warning("[LLM-GW] %s failed: %s", name, exc)
        raise RuntimeError(f"All LLM providers failed. Last error: {last_error}")

    def get_provider(self, name: str) -> Optional[_BaseProvider]:
        """Get a specific provider by name."""
        return self._providers.get(name)

    def get_providers(self) -> List[Dict]:
        """List all registered providers with status."""
        return [
            {
                "name": name,
                "provider": prov.provider_name,
                "available": prov.is_available(),
                "model": getattr(prov, "model", "unknown"),
                **self._call_stats.get(name, {"success": 0, "failure": 0}),
            }
            for name, prov in self._providers.items()
        ]

    def get_fallback_chain(self) -> List[str]:
        return list(self._fallback_chain)

    def recommend_model(self, task_type: str = "general") -> Dict:
        rec = _RECOMMENDATIONS.get(task_type, _RECOMMENDATIONS["general"])
        pname = rec["provider"]
        if pname in self._providers and self._providers[pname].is_available():
            return rec
        return {
            "model": "qwen2.5:3b",
            "provider": "ollama",
            "reason": f"Fallback — {pname} not available",
        }


@lru_cache(maxsize=1)
def get_llm_gateway() -> LLMGateway:
    """Singleton gateway instance. Reads provider config from llm.yaml if available."""
    provider_config: Dict[str, Dict] = {}
    try:
        from chat_app.settings import get_settings

        settings = get_settings()
        # If llm.yaml has a providers section, use it
        if hasattr(settings, "llm_providers"):
            provider_config = settings.llm_providers or {}
    except Exception:
        pass
    return LLMGateway(provider_config)
