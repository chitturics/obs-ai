"""Tests for code intelligence — dependency graph, duplicates, health metrics."""

import pytest


@pytest.fixture
def intel():
    from chat_app.code_intelligence import CodeIntelligence
    return CodeIntelligence()


class TestDependencyGraph:

    def test_graph_has_nodes_and_edges(self, intel):
        graph = intel.get_dependency_graph()
        assert graph["node_count"] >= 100
        assert graph["edge_count"] >= 100
        assert len(graph["nodes"]) == graph["node_count"]
        assert len(graph["edges"]) == graph["edge_count"]

    def test_nodes_have_layer(self, intel):
        graph = intel.get_dependency_graph()
        for node in graph["nodes"][:10]:
            assert "layer" in node
            assert "lines" in node
            assert "fan_in" in node
            assert "fan_out" in node

    def test_layers_cover_architecture(self, intel):
        graph = intel.get_dependency_graph()
        layers = graph["layers"]
        assert "pipeline" in layers
        assert "execution" in layers
        assert "security" in layers
        assert "observability" in layers
        assert "admin" in layers


class TestModuleInfo:

    def test_get_known_module(self, intel):
        mod = intel.get_module("settings")
        assert mod is not None
        assert mod["name"] == "settings"
        assert mod["lines"] > 100
        assert "layer" in mod

    def test_get_unknown_module(self, intel):
        assert intel.get_module("nonexistent_xyz") is None

    def test_all_modules(self, intel):
        modules = intel.get_all_modules()
        assert len(modules) >= 100
        names = [m["name"] for m in modules]
        assert "settings" in names
        assert "skill_executor" in names
        assert "audit_log" in names


class TestDuplicateDetection:

    def test_finds_duplicates(self, intel):
        dupes = intel.find_duplicates()
        assert isinstance(dupes, list)
        # There should be some duplicates from the route extraction
        for d in dupes:
            assert "name" in d
            assert "locations" in d
            assert d["count"] >= 2


class TestLayerMap:

    def test_layer_map_has_all_layers(self, intel):
        layers = intel.get_layer_map()
        assert "pipeline" in layers
        assert "security" in layers
        assert "observability" in layers

    def test_security_layer_modules(self, intel):
        layers = intel.get_layer_map()
        security_names = [m["name"] for m in layers.get("security", [])]
        assert "audit_log" in security_names
        assert "rbac" in security_names
        assert "mfa" in security_names


class TestHealthMetrics:

    def test_health_metrics_structure(self, intel):
        health = intel.get_health_metrics()
        assert health["total_modules"] >= 100
        assert health["total_lines"] > 50000
        assert "avg_fan_out" in health
        assert "god_files" in health
        assert "layers" in health

    def test_god_files_reduced(self, intel):
        health = intel.get_health_metrics()
        # After splitting, should have very few god files (>2000 lines)
        assert len(health["god_files"]) <= 3, f"Too many god files: {health['god_files']}"


class TestCrossLayerDependencies:

    def test_finds_cross_layer_deps(self, intel):
        violations = intel.get_cross_layer_dependencies()
        assert isinstance(violations, list)
        # Should have some cross-layer deps (admin importing security, etc.)
        assert len(violations) >= 10
        for v in violations[:5]:
            assert "from_module" in v
            assert "from_layer" in v
            assert "to_module" in v
            assert "to_layer" in v
            assert v["from_layer"] != v["to_layer"]
