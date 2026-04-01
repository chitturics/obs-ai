"""
Director Graph — DAG-based orchestration with conditional routing.

Adapted from OpenMAIC's Director Graph pattern (LangGraph-inspired).
Provides:
- GraphNode: nodes of type director/agent/tool/gate
- GraphEdge: edges with optional conditions
- DirectorGraph: DAG definition with entry node
- DirectorGraphExecutor: walks graph, executing nodes via AgentDispatcher
- GRAPH_TEMPLATES: pre-built graph templates (director_loop, parallel_experts,
  deep_analysis, iterative_refinement)

Used by DirectorGraphStrategy in orchestration_strategies.py.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Terminal sentinel
END = "END"


# ---------------------------------------------------------------------------
# Graph data structures
# ---------------------------------------------------------------------------

@dataclass
class GraphNode:
    """A node in the director graph."""
    id: str
    node_type: str  # "director", "agent", "tool", "gate"
    handler: Optional[str] = None  # agent name, skill name, or None for director
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "type": self.node_type,
            "handler": self.handler,
            "config": self.config,
        }


@dataclass
class GraphEdge:
    """An edge with optional condition."""
    source: str
    target: str
    condition: Optional[str] = None  # e.g. "quality < 0.7", "needs_more_info"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "condition": self.condition,
        }


@dataclass
class DirectorGraph:
    """DAG of nodes with conditional edges."""
    nodes: Dict[str, GraphNode] = field(default_factory=dict)
    edges: List[GraphEdge] = field(default_factory=list)
    entry_node: str = "director"
    name: str = ""
    description: str = ""

    def get_next_nodes(self, current_id: str, state: Dict[str, Any]) -> List[str]:
        """Evaluate edges from current node, return matching target IDs."""
        candidates = [e for e in self.edges if e.source == current_id]
        if not candidates:
            return []

        # Evaluate conditions
        matching = []
        for edge in candidates:
            if edge.condition is None:
                matching.append(edge.target)
            elif self._evaluate_condition(edge.condition, state):
                matching.append(edge.target)

        # If no conditional match, take unconditional edges
        if not matching:
            matching = [e.target for e in candidates if e.condition is None]

        return matching

    @staticmethod
    def _evaluate_condition(condition: str, state: Dict[str, Any]) -> bool:
        """Safely evaluate a simple condition against state."""
        try:
            quality = state.get("quality", 0.5)
            iteration = state.get("iteration", 0)
            done = state.get("done", False)
            has_context = bool(state.get("context", ""))

            # Simple condition evaluation (no eval())
            cond = condition.strip()
            if cond == "done":
                return done
            if cond == "not_done":
                return not done
            if cond.startswith("quality"):
                # Parse "quality < 0.7", "quality >= 0.7", etc.
                for op, fn in [(">=", lambda a, b: a >= b), ("<=", lambda a, b: a <= b),
                               (">", lambda a, b: a > b), ("<", lambda a, b: a < b),
                               ("==", lambda a, b: a == b)]:
                    if op in cond:
                        threshold = float(cond.split(op)[1].strip())
                        return fn(quality, threshold)
            if cond == "needs_more_info":
                return not has_context or quality < 0.5
            if cond == "has_context":
                return has_context
            if cond.startswith("iteration"):
                for op, fn in [(">=", lambda a, b: a >= b), ("<", lambda a, b: a < b)]:
                    if op in cond:
                        threshold = int(cond.split(op)[1].strip())
                        return fn(iteration, threshold)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as _exc:
            logger.debug("%s", _exc)  # was: pass
        return False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "entry_node": self.entry_node,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "edges": [e.to_dict() for e in self.edges],
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
        }


# ---------------------------------------------------------------------------
# Graph executor
# ---------------------------------------------------------------------------

class DirectorGraphExecutor:
    """Executes a director graph by traversing nodes."""

    MAX_HOPS = 10  # Prevent infinite loops

    def __init__(self, max_hops: int = 10):
        self.MAX_HOPS = max_hops

    async def execute(
        self,
        graph: DirectorGraph,
        user_input: str,
        intent: str = "",
        context: Any = None,
    ) -> Dict[str, Any]:
        """Walk the graph from entry to terminal, executing each node."""
        state: Dict[str, Any] = {
            "user_input": user_input,
            "intent": intent,
            "context": "",
            "iteration": 0,
            "quality": 0.0,
            "done": False,
            "trace": [],
            "accumulated_outputs": [],
        }

        current = graph.entry_node
        start = time.monotonic()

        while state["iteration"] < self.MAX_HOPS and not state["done"]:
            node = graph.nodes.get(current)
            if node is None:
                logger.warning("[DIRECTOR_GRAPH] Node '%s' not found in graph", current)
                break

            node_start = time.monotonic()
            state = await self._execute_node(node, state, context)
            node_duration = (time.monotonic() - node_start) * 1000

            state["trace"].append({
                "node": current,
                "type": node.node_type,
                "handler": node.handler,
                "duration_ms": round(node_duration, 1),
                "iteration": state["iteration"],
            })

            # Get next nodes
            next_nodes = graph.get_next_nodes(current, state)
            if not next_nodes or next_nodes[0] == END:
                state["done"] = True
                break

            current = next_nodes[0]
            state["iteration"] += 1

        total_duration = (time.monotonic() - start) * 1000
        logger.info("[DIRECTOR_GRAPH] Completed: %d hops, quality=%.2f, %.0fms",
                    state["iteration"], state["quality"], total_duration)

        return {
            "context": state["context"],
            "trace": state["trace"],
            "iterations": state["iteration"] + 1,
            "quality": state["quality"],
            "duration_ms": total_duration,
            "done": state["done"],
        }

    async def _execute_node(
        self, node: GraphNode, state: Dict[str, Any], context: Any
    ) -> Dict[str, Any]:
        """Execute a single graph node based on its type."""
        if node.node_type == "director":
            return await self._execute_director(node, state)
        elif node.node_type == "agent":
            return await self._execute_agent(node, state, context)
        elif node.node_type == "gate":
            return self._execute_gate(node, state)
        elif node.node_type == "tool":
            return await self._execute_tool(node, state, context)
        return state

    async def _execute_director(
        self, node: GraphNode, state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Director node: decides how to proceed based on current state.

        Uses LLM to assess progress and decide next action.
        """
        user_input = state["user_input"]
        current_context = state.get("context", "")

        if not current_context:
            # First iteration — just pass through to workers
            return state

        # After first iteration, use LLM to assess if we need more work
        try:
            from chat_app.llm_utils import generate_text
            assessment_prompt = (
                f"Assess the quality of this analysis for the query: '{user_input}'\n\n"
                f"Current analysis:\n{current_context[:1500]}\n\n"
                "Rate the quality from 0.0 to 1.0. Reply with ONLY a number."
            )
            score_text = await generate_text(assessment_prompt, max_tokens=10)
            try:
                quality = float(score_text.strip())
                quality = max(0.0, min(1.0, quality))
            except (ValueError, TypeError):
                quality = 0.6
            state["quality"] = quality
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[DIRECTOR_GRAPH] Director assessment failed: %s", exc)
            state["quality"] = 0.6

        return state

    async def _execute_agent(
        self, node: GraphNode, state: Dict[str, Any], context: Any
    ) -> Dict[str, Any]:
        """Agent node: dispatch to a named or best-fit agent."""
        try:
            from chat_app.agent_dispatcher import get_agent_dispatcher
            dispatcher = get_agent_dispatcher()

            result = await dispatcher.dispatch(
                user_input=state["user_input"],
                intent=state.get("intent", "general_qa"),
            )

            if result.success and result.enriched_context:
                state["context"] = (
                    state.get("context", "") + "\n\n" + result.enriched_context
                ).strip()
                state["accumulated_outputs"].append({
                    "agent": result.agent_name,
                    "output": result.enriched_context[:500],
                })
                # Bump quality based on skill execution success
                success_ratio = (
                    len([r for r in result.skill_results if r.success])
                    / max(len(result.skill_results), 1)
                )
                state["quality"] = max(state["quality"], success_ratio)

        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[DIRECTOR_GRAPH] Agent node '%s' failed: %s", node.id, exc)

        return state

    def _execute_gate(self, node: GraphNode, state: Dict[str, Any]) -> Dict[str, Any]:
        """Gate node: quality check, sets done if threshold met."""
        threshold = node.config.get("threshold", 0.7)
        if state["quality"] >= threshold:
            state["done"] = True
        return state

    async def _execute_tool(
        self, node: GraphNode, state: Dict[str, Any], context: Any
    ) -> Dict[str, Any]:
        """Tool node: execute a specific skill."""
        if not node.handler:
            return state

        try:
            from chat_app.skill_executor import get_skill_executor
            executor = get_skill_executor()
            result = await executor.execute(
                skill_name=node.handler,
                params={"user_input": state["user_input"]},
            )
            if result.success and result.output:
                state["context"] = (
                    state.get("context", "") + "\n\n" + result.output
                ).strip()
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[DIRECTOR_GRAPH] Tool node '%s' failed: %s", node.id, exc)

        return state


# ---------------------------------------------------------------------------
# Built-in graph templates
# ---------------------------------------------------------------------------

GRAPH_TEMPLATES: Dict[str, DirectorGraph] = {
    "director_loop": DirectorGraph(
        name="director_loop",
        description="Director assesses, dispatches to worker, reviews, loops until quality threshold met.",
        nodes={
            "director": GraphNode("director", "director"),
            "worker": GraphNode("worker", "agent"),
            "reviewer": GraphNode("reviewer", "gate", config={"threshold": 0.7}),
        },
        edges=[
            GraphEdge("director", "worker"),
            GraphEdge("worker", "reviewer"),
            GraphEdge("reviewer", "director", condition="quality < 0.7"),
            GraphEdge("reviewer", END, condition="quality >= 0.7"),
        ],
        entry_node="director",
    ),

    "parallel_experts": DirectorGraph(
        name="parallel_experts",
        description="Director dispatches to two expert agents, results synthesized.",
        nodes={
            "director": GraphNode("director", "director"),
            "expert_a": GraphNode("expert_a", "agent"),
            "expert_b": GraphNode("expert_b", "agent"),
            "synthesizer": GraphNode("synthesizer", "agent"),
        },
        edges=[
            GraphEdge("director", "expert_a"),
            GraphEdge("director", "expert_b"),
            GraphEdge("expert_a", "synthesizer"),
            GraphEdge("expert_b", "synthesizer"),
        ],
        entry_node="director",
    ),

    "deep_analysis": DirectorGraph(
        name="deep_analysis",
        description="Three-stage pipeline: retrieve → analyze → validate with quality gate.",
        nodes={
            "retriever": GraphNode("retriever", "tool", handler="retrieve_chunks"),
            "analyzer": GraphNode("analyzer", "agent"),
            "validator": GraphNode("validator", "gate", config={"threshold": 0.6}),
            "refiner": GraphNode("refiner", "agent"),
        },
        edges=[
            GraphEdge("retriever", "analyzer"),
            GraphEdge("analyzer", "validator"),
            GraphEdge("validator", "refiner", condition="quality < 0.6"),
            GraphEdge("validator", END, condition="quality >= 0.6"),
            GraphEdge("refiner", "validator"),
        ],
        entry_node="retriever",
    ),

    "iterative_refinement": DirectorGraph(
        name="iterative_refinement",
        description="Agent generates, director reviews, loops up to 3 times for quality.",
        nodes={
            "director": GraphNode("director", "director"),
            "generator": GraphNode("generator", "agent"),
            "quality_gate": GraphNode("quality_gate", "gate", config={"threshold": 0.75}),
        },
        edges=[
            GraphEdge("director", "generator"),
            GraphEdge("generator", "quality_gate"),
            GraphEdge("quality_gate", "director", condition="quality < 0.75"),
            GraphEdge("quality_gate", END, condition="quality >= 0.75"),
        ],
        entry_node="director",
    ),
}


def get_template_names() -> List[str]:
    """Return list of available template names."""
    return list(GRAPH_TEMPLATES.keys())


def get_template(name: str) -> Optional[DirectorGraph]:
    """Get a graph template by name."""
    return GRAPH_TEMPLATES.get(name)


def get_templates_summary() -> Dict[str, Dict[str, Any]]:
    """Get summary of all templates for API."""
    return {
        name: {
            "description": g.description,
            "nodes": len(g.nodes),
            "edges": len(g.edges),
            "entry": g.entry_node,
            "node_types": [n.node_type for n in g.nodes.values()],
            "node_ids": list(g.nodes.keys()),
        }
        for name, g in GRAPH_TEMPLATES.items()
    }
