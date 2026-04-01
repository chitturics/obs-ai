"""Agent Communication Protocol — message passing, blackboard, and clarification.

Defines how agents communicate with each other and with users:
- **Blackboard**: Shared context visible to all agents in a workflow run
- **Messages**: Typed inter-agent messages (request, response, delegate, clarify)
- **Clarification**: Structured protocol for asking users questions

Usage:
    from chat_app.agent_protocol import get_comm_bus, MessageType

    bus = get_comm_bus()
    board = bus.create_blackboard(run_id="abc", user_query="search errors", intent="splunk_search")

    # Agent posts to blackboard
    board.contribute("spl_expert", "Found 42 errors in index=main")

    # Agent requests clarification from user
    board.request_clarification("spl_expert", "Which time range should I search?")

    # Agent delegates to another agent
    bus.send(AgentMessage(
        message_type=MessageType.DELEGATE,
        sender_agent="spl_expert",
        recipient_agent="security_guard",
        content="Please check if these errors indicate a security incident",
    ))
"""

import logging
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    REQUEST = "request"
    RESPONSE = "response"
    INFORM = "inform"
    DELEGATE = "delegate"
    CLARIFY = "clarify"
    ESCALATE = "escalate"


@dataclass
class AgentMessage:
    """A typed message between agents or between agent and user."""
    message_id: str = ""
    message_type: MessageType = MessageType.INFORM
    sender_agent: str = ""
    recipient: str = ""  # Agent name, "user", or "broadcast"
    content: str = ""
    structured_data: Dict[str, Any] = field(default_factory=dict)
    parent_message_id: str = ""
    workflow_run_id: str = ""
    timestamp: str = ""
    requires_response: bool = False

    def __post_init__(self):
        if not self.message_id:
            self.message_id = uuid.uuid4().hex[:12]
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.message_id,
            "type": self.message_type.value,
            "sender": self.sender_agent,
            "recipient": self.recipient,
            "content": self.content[:500],
            "timestamp": self.timestamp,
            "requires_response": self.requires_response,
        }


@dataclass
class Blackboard:
    """Shared context visible to all agents in a single workflow run."""
    run_id: str
    user_query: str
    intent: str
    shared_context: Dict[str, Any] = field(default_factory=dict)
    messages: List[AgentMessage] = field(default_factory=list)
    agent_contributions: Dict[str, str] = field(default_factory=dict)
    pending_clarifications: List[AgentMessage] = field(default_factory=list)
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()

    def contribute(self, agent_name: str, content: str) -> None:
        """Agent posts its output to the shared blackboard."""
        self.agent_contributions[agent_name] = content
        self.messages.append(AgentMessage(
            message_type=MessageType.INFORM,
            sender_agent=agent_name,
            recipient="blackboard",
            content=content[:1000],
            workflow_run_id=self.run_id,
        ))

    def request_clarification(self, agent_name: str, question: str) -> AgentMessage:
        """Agent asks the user a clarifying question."""
        msg = AgentMessage(
            message_type=MessageType.CLARIFY,
            sender_agent=agent_name,
            recipient="user",
            content=question,
            workflow_run_id=self.run_id,
            requires_response=True,
        )
        self.pending_clarifications.append(msg)
        self.messages.append(msg)
        return msg

    def get_context_for_agent(self, agent_name: str) -> str:
        """Get all blackboard context relevant to an agent."""
        parts = [f"User Query: {self.user_query}", f"Intent: {self.intent}"]
        for name, contribution in self.agent_contributions.items():
            if name != agent_name:
                parts.append(f"[{name}]: {contribution[:300]}")
        if self.shared_context:
            parts.append(f"Shared Context: {str(self.shared_context)[:500]}")
        return "\n".join(parts)

    @property
    def has_pending_clarifications(self) -> bool:
        return len(self.pending_clarifications) > 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "user_query": self.user_query[:200],
            "intent": self.intent,
            "agent_contributions": {k: v[:200] for k, v in self.agent_contributions.items()},
            "message_count": len(self.messages),
            "pending_clarifications": len(self.pending_clarifications),
            "messages": [m.to_dict() for m in self.messages[-20:]],
        }


class AgentCommunicationBus:
    """Central message bus for inter-agent communication."""

    def __init__(self):
        self._blackboards: Dict[str, Blackboard] = {}
        self._message_log: Deque[AgentMessage] = deque(maxlen=2000)
        self._lock = threading.Lock()

    def create_blackboard(self, run_id: str, user_query: str, intent: str) -> Blackboard:
        board = Blackboard(run_id=run_id, user_query=user_query, intent=intent)
        with self._lock:
            self._blackboards[run_id] = board
            # Cleanup old boards
            if len(self._blackboards) > 200:
                oldest = sorted(self._blackboards.keys())[:50]
                for k in oldest:
                    del self._blackboards[k]
        return board

    def get_blackboard(self, run_id: str) -> Optional[Blackboard]:
        return self._blackboards.get(run_id)

    def send(self, message: AgentMessage) -> None:
        """Route a message between agents."""
        with self._lock:
            self._message_log.append(message)
        board = self._blackboards.get(message.workflow_run_id)
        if board:
            board.messages.append(message)
        logger.debug("[AGENT_COMM] %s → %s: %s (%s)",
                     message.sender_agent, message.recipient,
                     message.message_type.value, message.content[:80])

    def get_stats(self) -> Dict[str, Any]:
        return {
            "active_blackboards": len(self._blackboards),
            "total_messages": len(self._message_log),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


_bus_instance: Optional[AgentCommunicationBus] = None
_bus_lock = threading.Lock()


def get_comm_bus() -> AgentCommunicationBus:
    global _bus_instance
    if _bus_instance is None:
        with _bus_lock:
            if _bus_instance is None:
                _bus_instance = AgentCommunicationBus()
    return _bus_instance


# ═══════════════════════════════════════════════════════════════════════════════
# AgentScope-Inspired Extensions: AgentBase + Pipelines
# ═══════════════════════════════════════════════════════════════════════════════

import asyncio
import time


class AgentBase:
    """Base class for agents with lifecycle hooks (AgentScope pattern).

    Lifecycle:
        1. __init__() — setup agent with name, config, tools
        2. observe(msg) — receive and process an incoming message
        3. reply(msg) -> AgentMessage — generate a response
        4. step() — called each pipeline iteration (optional)

    Subclass and override reply() to create a custom agent.
    """

    def __init__(
        self,
        name: str,
        department: str = "",
        description: str = "",
        skills: Optional[List[str]] = None,
    ):
        self.name = name
        self.department = department
        self.description = description
        self.skills = skills or []
        self._history: List[AgentMessage] = []
        self._metrics: Dict[str, float] = {}

    def observe(self, msg: AgentMessage) -> None:
        """Receive a message. Called before reply()."""
        self._history.append(msg)
        if len(self._history) > 50:
            self._history = self._history[-50:]

    async def reply(self, msg: AgentMessage) -> AgentMessage:
        """Generate a response. Override in subclasses."""
        return AgentMessage(
            message_type=MessageType.RESPONSE,
            sender_agent=self.name,
            recipient=msg.sender_agent,
            content=f"[{self.name}] Acknowledged: {msg.content[:100]}",
            parent_message_id=msg.message_id,
        )

    async def step(self) -> Optional[AgentMessage]:
        """Called each pipeline iteration. Override for proactive behavior."""
        return None

    def reset(self) -> None:
        """Reset agent state for a new conversation."""
        self._history.clear()
        self._metrics.clear()

    def record_metric(self, key: str, value: float) -> None:
        self._metrics[key] = value

    def get_state(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "department": self.department,
            "history_length": len(self._history),
            "metrics": dict(self._metrics),
        }


class SequentialPipeline:
    """Execute agents in sequence. Each agent's output feeds the next."""

    def __init__(self, agents: List[AgentBase]):
        self.agents = agents

    async def run(self, msg: AgentMessage) -> AgentMessage:
        current = msg
        for agent in self.agents:
            agent.observe(current)
            start = time.time()
            current = await agent.reply(current)
            elapsed_ms = (time.time() - start) * 1000
            agent.record_metric("last_duration_ms", elapsed_ms)
            logger.debug("[PIPELINE] %s → %.1fms", agent.name, elapsed_ms)
        return current


class ParallelPipeline:
    """Execute agents in parallel, select best response."""

    def __init__(self, agents: List[AgentBase], select: str = "first"):
        self.agents = agents
        self.select = select  # "first", "longest", "merge"

    async def run(self, msg: AgentMessage) -> AgentMessage:
        tasks = []
        for agent in self.agents:
            agent.observe(msg)
            tasks.append(agent.reply(msg))

        results = await asyncio.gather(*tasks, return_exceptions=True)
        responses = [r for r in results if isinstance(r, AgentMessage)]

        if not responses:
            return AgentMessage(
                message_type=MessageType.RESPONSE,
                sender_agent="pipeline",
                content="All agents failed",
            )

        if self.select == "merge":
            merged = "\n\n".join(f"**{r.sender_agent}:** {r.content}" for r in responses)
            return AgentMessage(
                message_type=MessageType.RESPONSE,
                sender_agent="parallel_pipeline",
                content=merged,
            )

        if self.select == "longest":
            responses.sort(key=lambda m: len(m.content), reverse=True)

        return responses[0]


class ConditionalPipeline:
    """Route to different agents based on a condition."""

    def __init__(self, condition, if_true, if_false):
        self.condition = condition
        self.if_true = if_true
        self.if_false = if_false

    async def run(self, msg: AgentMessage) -> AgentMessage:
        branch = self.if_true if self.condition(msg) else self.if_false
        if isinstance(branch, (SequentialPipeline, ParallelPipeline, ConditionalPipeline, LoopPipeline)):
            return await branch.run(msg)
        branch.observe(msg)
        return await branch.reply(msg)


class LoopPipeline:
    """Repeatedly run an agent until stop condition or max iterations."""

    def __init__(self, agent: AgentBase, stop_condition, max_iterations: int = 5):
        self.agent = agent
        self.stop_condition = stop_condition
        self.max_iterations = max_iterations

    async def run(self, msg: AgentMessage) -> AgentMessage:
        current = msg
        for i in range(self.max_iterations):
            self.agent.observe(current)
            current = await self.agent.reply(current)
            current.structured_data["loop_iteration"] = i + 1
            if self.stop_condition(current):
                break
        return current


class ReviewPipeline:
    """Generator produces, reviewer critiques, generator refines."""

    def __init__(self, generator: AgentBase, reviewer: AgentBase, max_rounds: int = 2):
        self.generator = generator
        self.reviewer = reviewer
        self.max_rounds = max_rounds

    async def run(self, msg: AgentMessage) -> AgentMessage:
        self.generator.observe(msg)
        draft = await self.generator.reply(msg)

        for _round in range(self.max_rounds):
            self.reviewer.observe(draft)
            review = await self.reviewer.reply(draft)

            # If reviewer approves (quality > 0.8 or contains "approved")
            if "approved" in review.content.lower() or "looks good" in review.content.lower():
                draft.structured_data["approved"] = True
                draft.structured_data["review_rounds"] = _round + 1
                break

            # Refine
            feedback = AgentMessage(
                message_type=MessageType.REQUEST,
                sender_agent="reviewer",
                content=f"Feedback: {review.content}\n\nOriginal: {draft.content}",
                parent_message_id=review.message_id,
            )
            self.generator.observe(feedback)
            draft = await self.generator.reply(feedback)

        return draft


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Registry
# ═══════════════════════════════════════════════════════════════════════════════

_agent_registry: Dict[str, AgentBase] = {}


def register_agent(agent: AgentBase) -> None:
    """Register an agent instance."""
    _agent_registry[agent.name] = agent


def get_agent(name: str) -> Optional[AgentBase]:
    """Get a registered agent by name."""
    return _agent_registry.get(name)


def list_registered_agents() -> List[str]:
    """List all registered agent names."""
    return list(_agent_registry.keys())


def get_protocol_stats() -> Dict[str, Any]:
    """Get protocol statistics for admin API."""
    bus = get_comm_bus()
    bus_stats = bus.get_stats()
    return {
        "registered_agents": len(_agent_registry),
        "agent_names": list(_agent_registry.keys()),
        "communication_bus": bus_stats,
        "pipeline_types": ["Sequential", "Parallel", "Conditional", "Loop", "Review"],
    }
