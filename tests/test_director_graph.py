"""Tests for chat_app.director_graph — DAG-based orchestration."""

import asyncio
import pytest

from chat_app.director_graph import (
    GraphNode,
    GraphEdge,
    DirectorGraph,
    DirectorGraphExecutor,
    GRAPH_TEMPLATES,
    END,
    get_template_names,
    get_template,
    get_templates_summary,
)


# ---------------------------------------------------------------------------
# Graph data structure tests
# ---------------------------------------------------------------------------

class TestGraphNode:
    def test_basic(self):
        node = GraphNode("test", "agent", handler="spl_expert")
        assert node.id == "test"
        assert node.node_type == "agent"
        assert node.handler == "spl_expert"

    def test_to_dict(self):
        node = GraphNode("n1", "director")
        d = node.to_dict()
        assert d["id"] == "n1"
        assert d["type"] == "director"


class TestGraphEdge:
    def test_basic(self):
        edge = GraphEdge("a", "b", condition="quality < 0.7")
        assert edge.source == "a"
        assert edge.target == "b"
        assert edge.condition == "quality < 0.7"

    def test_to_dict(self):
        edge = GraphEdge("a", "b")
        d = edge.to_dict()
        assert d["source"] == "a"
        assert d["target"] == "b"
        assert d["condition"] is None


# ---------------------------------------------------------------------------
# DirectorGraph tests
# ---------------------------------------------------------------------------

class TestDirectorGraph:
    def test_get_next_unconditional(self):
        graph = DirectorGraph(
            nodes={"a": GraphNode("a", "director"), "b": GraphNode("b", "agent")},
            edges=[GraphEdge("a", "b")],
        )
        nexts = graph.get_next_nodes("a", {})
        assert nexts == ["b"]

    def test_get_next_conditional_match(self):
        graph = DirectorGraph(
            nodes={"a": GraphNode("a", "gate"), "b": GraphNode("b", "agent")},
            edges=[
                GraphEdge("a", "b", condition="quality < 0.7"),
                GraphEdge("a", END, condition="quality >= 0.7"),
            ],
        )
        # Low quality → should go to "b"
        nexts = graph.get_next_nodes("a", {"quality": 0.3})
        assert "b" in nexts

    def test_get_next_conditional_end(self):
        graph = DirectorGraph(
            nodes={"a": GraphNode("a", "gate")},
            edges=[
                GraphEdge("a", "b", condition="quality < 0.7"),
                GraphEdge("a", END, condition="quality >= 0.7"),
            ],
        )
        # High quality → should go to END
        nexts = graph.get_next_nodes("a", {"quality": 0.9})
        assert END in nexts

    def test_get_next_no_edges(self):
        graph = DirectorGraph(
            nodes={"a": GraphNode("a", "agent")},
            edges=[],
        )
        assert graph.get_next_nodes("a", {}) == []

    def test_evaluate_condition_done(self):
        assert DirectorGraph._evaluate_condition("done", {"done": True})
        assert not DirectorGraph._evaluate_condition("done", {"done": False})

    def test_evaluate_condition_not_done(self):
        assert DirectorGraph._evaluate_condition("not_done", {"done": False})

    def test_evaluate_condition_needs_more_info(self):
        assert DirectorGraph._evaluate_condition("needs_more_info", {"context": "", "quality": 0.3})
        assert not DirectorGraph._evaluate_condition("needs_more_info", {"context": "some info", "quality": 0.8})

    def test_to_dict(self):
        graph = DirectorGraph(
            name="test",
            description="A test graph",
            nodes={"a": GraphNode("a", "director")},
            edges=[GraphEdge("a", END)],
        )
        d = graph.to_dict()
        assert d["name"] == "test"
        assert d["node_count"] == 1
        assert d["edge_count"] == 1


# ---------------------------------------------------------------------------
# Template tests
# ---------------------------------------------------------------------------

class TestGraphTemplates:
    def test_templates_exist(self):
        assert len(GRAPH_TEMPLATES) >= 4

    def test_director_loop_structure(self):
        g = GRAPH_TEMPLATES["director_loop"]
        assert "director" in g.nodes
        assert "worker" in g.nodes
        assert "reviewer" in g.nodes
        assert len(g.edges) >= 3
        assert g.entry_node == "director"

    def test_parallel_experts_structure(self):
        g = GRAPH_TEMPLATES["parallel_experts"]
        assert "director" in g.nodes
        assert "expert_a" in g.nodes
        assert "synthesizer" in g.nodes

    def test_deep_analysis_structure(self):
        g = GRAPH_TEMPLATES["deep_analysis"]
        assert "retriever" in g.nodes
        assert g.entry_node == "retriever"

    def test_iterative_refinement_structure(self):
        g = GRAPH_TEMPLATES["iterative_refinement"]
        assert "quality_gate" in g.nodes

    def test_get_template_names(self):
        names = get_template_names()
        assert "director_loop" in names
        assert "parallel_experts" in names

    def test_get_template(self):
        t = get_template("director_loop")
        assert t is not None
        assert t.name == "director_loop"

    def test_get_template_missing(self):
        assert get_template("nonexistent") is None

    def test_get_templates_summary(self):
        summary = get_templates_summary()
        assert len(summary) >= 4
        for name, info in summary.items():
            assert "nodes" in info
            assert "edges" in info
            assert "entry" in info


# ---------------------------------------------------------------------------
# DirectorGraphExecutor tests
# ---------------------------------------------------------------------------

class TestDirectorGraphExecutor:
    def test_max_hops_protection(self):
        """Executor should stop after max_hops even in a loop."""
        graph = DirectorGraph(
            nodes={
                "a": GraphNode("a", "agent"),
                "b": GraphNode("b", "agent"),
            },
            edges=[
                GraphEdge("a", "b"),
                GraphEdge("b", "a"),  # Infinite loop
            ],
            entry_node="a",
        )
        executor = DirectorGraphExecutor(max_hops=5)
        result = asyncio.new_event_loop().run_until_complete(
            executor.execute(graph, "test query")
        )
        assert result["iterations"] <= 6  # max_hops + 1

    def test_execute_terminates_at_end(self):
        """Executor should stop when reaching END sentinel."""
        graph = DirectorGraph(
            nodes={"start": GraphNode("start", "agent")},
            edges=[GraphEdge("start", END)],
            entry_node="start",
        )
        executor = DirectorGraphExecutor()
        result = asyncio.new_event_loop().run_until_complete(
            executor.execute(graph, "test")
        )
        assert result["done"]

    def test_execute_missing_node(self):
        """Executor should handle missing nodes gracefully."""
        graph = DirectorGraph(
            nodes={"start": GraphNode("start", "agent")},
            edges=[GraphEdge("start", "missing_node")],
            entry_node="start",
        )
        executor = DirectorGraphExecutor()
        result = asyncio.new_event_loop().run_until_complete(
            executor.execute(graph, "test")
        )
        # Should have trace with at least the start node
        assert len(result["trace"]) >= 1
