"""
Dataclass for holding the context for the message handler.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Callable

@dataclass
class MessageHandlerContext:
    """
    Context for the message handler.
    """
    vector_store: Any
    engine: Any
    starter_options: List[Dict]
    search_roots: List[str]
    profiles_available: bool
    feedback_guardrails_available: bool
    system_prompt: str
    chain: Any
    llm: Any
    ensure_services_ready: Callable
    load_static_context: Callable
    map_source_to_url: Callable
    SPEC_STATIC_ROOT: str
    LOCAL_DOCS_ROOT: str
    SPEC_SRC_ROOT: str
    settings: Any
    mcp_tools: List[Any] = field(default_factory=list)
