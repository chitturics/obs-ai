"""A2A Protocol — Agent-to-Agent interoperability via JSON-RPC 2.0."""
import logging
from typing import Dict, List, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class AgentCard:
    """A2A Agent Card for discovery."""
    name: str
    description: str
    url: str
    capabilities: List[str]
    supported_modalities: List[str] = field(default_factory=lambda: ["text"])
    authentication: Dict[str, Any] = field(default_factory=lambda: {"type": "api_key"})
    long_running_tasks: bool = True
    protocols: List[str] = field(default_factory=lambda: ["a2a/0.3", "mcp/2.0"])


def get_agent_cards() -> List[Dict]:
    """Generate A2A Agent Cards for all ObsAI agents."""
    try:
        from chat_app.agent_catalog import AGENT_CATALOG
        cards = []
        for agent in AGENT_CATALOG[:10]:  # Top 10 agents
            cards.append({
                "name": f"obsai-{agent.name}",
                "description": agent.description,
                "url": f"/a2a/agents/{agent.name}",
                "capabilities": [s for s in agent.skills[:5]],
                "supported_modalities": ["text"],
                "authentication": {"type": "api_key", "header": "X-API-Key"},
                "long_running_tasks": True,
            })
        return cards
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.warning("[A2A] Failed to generate agent cards: %s", e)
        return []


def get_well_known_agent_json() -> Dict:
    """Return the /.well-known/agent.json discovery document."""
    return {
        "name": "obsai",
        "description": "ObsAI — AI-powered Splunk & Observability Assistant",
        "version": "3.5.0",
        "url": "/a2a",
        "agents": get_agent_cards(),
        "protocols": ["a2a/0.3"],
        "authentication": {
            "type": "api_key",
            "header": "X-API-Key",
        },
    }


async def handle_a2a_task(task: Dict) -> Dict:
    """Handle incoming A2A task."""
    task_type = task.get("type", "query")
    task.get("agent", "")
    input_data = task.get("input", {})

    if task_type == "query":
        # Route to agent dispatch
        try:
            from chat_app.agent_dispatcher import get_agent_dispatcher
            dispatcher = get_agent_dispatcher()
            result = await dispatcher.dispatch(input_data.get("query", ""), "general_qa")
            return {
                "status": "completed",
                "output": {
                    "response": result.enriched_context if result.enriched_context else "No response generated",
                    "agent_used": result.agent_name,
                    "confidence": getattr(result, "quality_score", None),
                },
            }
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            return {"status": "failed", "error": str(e)}

    return {"status": "unsupported", "error": f"Unknown task type: {task_type}"}
