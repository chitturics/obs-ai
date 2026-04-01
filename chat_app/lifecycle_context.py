"""
Dataclass for holding the context for the chat lifecycle handlers.
"""
from dataclasses import dataclass
from typing import Callable

@dataclass
class ChatLifecycleContext:
    """
    Context for the chat lifecycle handlers.
    """
    ensure_services_ready: Callable
    bootstrap_mcp_session: Callable
    initialize_org_data: Callable
