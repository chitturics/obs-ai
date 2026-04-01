"""
/version command handler.
"""
import platform
import sys

import chainlit as cl


async def version_command():
    """Show application version and environment info."""
    try:
        from chat_app.settings import get_settings
        cfg = get_settings()
        app_version = cfg.app.version
        environment = cfg.app.environment
        profile = cfg.app.active_profile
        llm_model = cfg.ollama.model
    except Exception:
        app_version = "3.5.0"
        environment = "unknown"
        profile = "unknown"
        llm_model = "unknown"

    # Collect service versions
    services = []
    try:
        import ollama as _ollama_mod
        services.append(f"- Ollama client: `{getattr(_ollama_mod, '__version__', 'installed')}`")
    except ImportError:
        pass
    try:
        import chromadb
        services.append(f"- ChromaDB: `{chromadb.__version__}`")
    except (ImportError, AttributeError):
        pass
    try:
        import chainlit as _cl
        services.append(f"- Chainlit: `{_cl.__version__}`")
    except (ImportError, AttributeError):
        pass

    services_text = "\n".join(services) if services else "- (unavailable)"

    await cl.Message(content=f"""**ObsAI - Observability AI Assistant**

| | |
|---|---|
| **Version** | `{app_version}` |
| **Environment** | `{environment}` |
| **Active Profile** | `{profile}` |
| **LLM Model** | `{llm_model}` |
| **Python** | `{sys.version.split()[0]}` |
| **Platform** | `{platform.system()} {platform.release()}` |

**Library Versions:**
{services_text}

**Links:** [Admin Console](/api/admin/v2/) | [Documentation](/api/admin/v2/)""").send()
