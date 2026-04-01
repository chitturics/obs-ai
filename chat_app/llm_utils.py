"""LLM instance creation for ObsAI.

Creates the primary LLM using centralized settings.
Supports multiple providers: Ollama (local), OpenAI, Anthropic, Google,
Azure OpenAI, MCP-as-LLM, and any OpenAI-compatible endpoint.

Provider selection is controlled by the LLM_PROVIDER environment variable
or the ``provider`` field in config/llm.yaml. Defaults to "ollama".
"""

import logging
import os
import socket
from urllib.parse import urlparse

from chat_app.settings import get_settings

logger = logging.getLogger(__name__)

# Supported provider → LangChain class mapping
_LANGCHAIN_PROVIDERS = {
    "ollama": "langchain_ollama.ChatOllama",
    "openai": "langchain_openai.ChatOpenAI",
    "anthropic": "langchain_anthropic.ChatAnthropic",
    "google": "langchain_google_genai.ChatGoogleGenerativeAI",
    "azure_openai": "langchain_openai.AzureChatOpenAI",
}


def _probe_ollama_url(base_url: str) -> str:
    """Verify Ollama is reachable at the configured URL.

    On podman with rootless networking, localhost may resolve to 127.0.0.1
    but Ollama is only reachable via [::1]. Detects that and returns a
    working URL.
    """
    parsed = urlparse(base_url)
    host = parsed.hostname or "localhost"
    port = parsed.port or 11430

    try:
        sock = socket.create_connection((host, port), timeout=3)
        sock.close()
        logger.info("Ollama reachable at configured URL: %s", base_url)
        return base_url
    except (ConnectionRefusedError, OSError, socket.timeout):
        logger.warning("Ollama not reachable at %s:%d, trying alternatives...", host, port)

    if host in ("localhost", "127.0.0.1"):
        try:
            sock = socket.create_connection(("::1", port), timeout=3)
            sock.close()
            alt_url = f"{parsed.scheme}://[::1]:{port}"
            logger.info("Ollama reachable via IPv6 at %s", alt_url)
            return alt_url
        except (ConnectionRefusedError, OSError, socket.timeout):
            pass

    for alt_host in ("localhost", "host.containers.internal", "host.docker.internal"):
        try:
            sock = socket.create_connection((alt_host, port), timeout=2)
            sock.close()
            alt_url = f"{parsed.scheme}://{alt_host}:{port}"
            logger.info("Ollama reachable at fallback: %s", alt_url)
            return alt_url
        except (ConnectionRefusedError, OSError, socket.timeout, socket.gaierror):
            continue

    logger.warning("Ollama not reachable at any known address. Using configured: %s", base_url)
    return base_url


def _import_class(dotted_path: str):
    """Dynamically import a class from a dotted module.class path."""
    module_path, class_name = dotted_path.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


def _create_ollama_llm(cfg):
    """Create a ChatOllama LLM instance."""
    try:
        from langchain_ollama import ChatOllama
    except ImportError:
        logger.error("langchain-ollama not installed — run: pip install langchain-ollama")
        return None

    working_url = _probe_ollama_url(cfg.base_url)
    llm = ChatOllama(
        model=cfg.model,
        base_url=working_url,
        temperature=cfg.temperature,
        num_ctx=cfg.num_ctx,
        num_predict=cfg.num_predict,
        streaming=True,
    )
    logger.info(
        "LLM created [ollama]: model=%s, url=%s, temp=%s, ctx=%s",
        cfg.model, working_url, cfg.temperature, cfg.num_ctx,
    )
    return llm


def _create_openai_llm(cfg):
    """Create a ChatOpenAI LLM instance."""
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        logger.error("langchain-openai not installed — run: pip install langchain-openai")
        return None

    api_key = os.getenv("OPENAI_API_KEY", "")
    base_url = os.getenv("OPENAI_BASE_URL", None)
    model = os.getenv("OPENAI_MODEL", cfg.model)

    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=cfg.temperature,
        max_tokens=cfg.num_predict,
        streaming=True,
    )
    logger.info("LLM created [openai]: model=%s, temp=%s", model, cfg.temperature)
    return llm


def _create_anthropic_llm(cfg):
    """Create a ChatAnthropic LLM instance."""
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError:
        logger.error("langchain-anthropic not installed — run: pip install langchain-anthropic")
        return None

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    model = os.getenv("ANTHROPIC_MODEL", cfg.model)

    llm = ChatAnthropic(
        model=model,
        api_key=api_key,
        temperature=cfg.temperature,
        max_tokens=cfg.num_predict,
        streaming=True,
    )
    logger.info("LLM created [anthropic]: model=%s, temp=%s", model, cfg.temperature)
    return llm


def _create_google_llm(cfg):
    """Create a ChatGoogleGenerativeAI LLM instance."""
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
    except ImportError:
        logger.error("langchain-google-genai not installed — run: pip install langchain-google-genai")
        return None

    api_key = os.getenv("GOOGLE_API_KEY", "")
    model = os.getenv("GOOGLE_MODEL", cfg.model)

    llm = ChatGoogleGenerativeAI(
        model=model,
        google_api_key=api_key,
        temperature=cfg.temperature,
        max_output_tokens=cfg.num_predict,
    )
    logger.info("LLM created [google]: model=%s, temp=%s", model, cfg.temperature)
    return llm


def _create_azure_openai_llm(cfg):
    """Create an AzureChatOpenAI LLM instance."""
    try:
        from langchain_openai import AzureChatOpenAI
    except ImportError:
        logger.error("langchain-openai not installed — run: pip install langchain-openai")
        return None

    llm = AzureChatOpenAI(
        azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", cfg.model),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT", ""),
        api_key=os.getenv("AZURE_OPENAI_API_KEY", ""),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-06-01"),
        temperature=cfg.temperature,
        max_tokens=cfg.num_predict,
        streaming=True,
    )
    logger.info("LLM created [azure_openai]: deployment=%s", cfg.model)
    return llm


def _create_openai_compatible_llm(cfg):
    """Create a ChatOpenAI instance pointing at a custom OpenAI-compatible server.

    Works with vLLM, LMStudio, LocalAI, text-generation-inference, etc.
    """
    try:
        from langchain_openai import ChatOpenAI
    except ImportError:
        logger.error("langchain-openai not installed — run: pip install langchain-openai")
        return None

    base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL", "")
    api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY", "not-needed")
    model = os.getenv("OPENAI_COMPATIBLE_MODEL", cfg.model)

    llm = ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        temperature=cfg.temperature,
        max_tokens=cfg.num_predict,
        streaming=True,
    )
    logger.info("LLM created [openai_compatible]: model=%s, url=%s", model, base_url)
    return llm


# Provider factory map
_PROVIDER_FACTORIES = {
    "ollama": _create_ollama_llm,
    "openai": _create_openai_llm,
    "anthropic": _create_anthropic_llm,
    "google": _create_google_llm,
    "azure_openai": _create_azure_openai_llm,
    "openai_compatible": _create_openai_compatible_llm,
}


def _create_llm():
    """Create the primary LLM instance based on provider configuration.

    Provider selection priority:
      1. LLM_PROVIDER environment variable
      2. config/llm.yaml → provider field
      3. Default: "ollama"
    """
    cfg = get_settings().ollama
    provider = os.getenv("LLM_PROVIDER", "").lower() or "ollama"

    factory = _PROVIDER_FACTORIES.get(provider)
    if not factory:
        logger.error("Unknown LLM provider: %s. Supported: %s", provider, list(_PROVIDER_FACTORIES.keys()))
        return None

    try:
        return factory(cfg)
    except Exception as exc:
        logger.error("Failed to create LLM (provider=%s): %s", provider, exc)
        # Fallback to Ollama if cloud provider fails
        if provider != "ollama":
            logger.info("Falling back to Ollama...")
            try:
                return _create_ollama_llm(cfg)
            except Exception as fallback_exc:
                logger.error("Ollama fallback also failed: %s", fallback_exc)
        return None


LLM = _create_llm()
