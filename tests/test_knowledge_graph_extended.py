"""Extended tests for chat_app/knowledge_graph.py — entity management, queries, and context generation."""
import pytest
from unittest.mock import patch, MagicMock

from chat_app.knowledge_graph import (
    SplunkKnowledgeGraph,
    KGEntity,
    KGRelationship,
    ENTITY_TYPES,
    RELATIONSHIP_TYPES,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def kg():
    """Fresh knowledge graph instance."""
    return SplunkKnowledgeGraph()


@pytest.fixture
def populated_kg(kg):
    """Knowledge graph pre-loaded with sample entities and relationships."""
    # Commands
    kg.add_entity(KGEntity(id="cmd_stats", entity_type="Command", name="stats",
                           description="Aggregate statistics over results"))
    kg.add_entity(KGEntity(id="cmd_eval", entity_type="Command", name="eval",
                           description="Calculate an expression and store result in a field"))
    kg.add_entity(KGEntity(id="cmd_where", entity_type="Command", name="where",
                           description="Filter results using eval expressions"))
    kg.add_entity(KGEntity(id="cmd_table", entity_type="Command", name="table",
                           description="Display selected fields in tabular format"))

    # Functions
    kg.add_entity(KGEntity(id="fn_count", entity_type="Function", name="count",
                           description="Returns the count of events"))
    kg.add_entity(KGEntity(id="fn_avg", entity_type="Function", name="avg",
                           description="Returns the average of a field"))

    # Fields
    kg.add_entity(KGEntity(id="field_host", entity_type="Field", name="host",
                           description="The hostname of the event source"))
    kg.add_entity(KGEntity(id="field_source", entity_type="Field", name="source",
                           description="The source of the event"))

    # Indexes
    kg.add_entity(KGEntity(id="idx_main", entity_type="Index", name="main",
                           description="Default index for events"))

    # Lookup
    kg.add_entity(KGEntity(id="lkp_geo", entity_type="Lookup", name="geo_lookup",
                           description="IP geolocation lookup"))

    # ConfigStanza
    kg.add_entity(KGEntity(id="cfg_syslog", entity_type="ConfigStanza", name="syslog",
                           description="Props config for syslog sourcetype"))

    # Relationships
    kg.add_relationship(KGRelationship(source_id="cmd_stats", target_id="fn_count",
                                       rel_type="uses_functions"))
    kg.add_relationship(KGRelationship(source_id="cmd_stats", target_id="fn_avg",
                                       rel_type="uses_functions"))
    kg.add_relationship(KGRelationship(source_id="cmd_stats", target_id="field_host",
                                       rel_type="operates_on"))
    kg.add_relationship(KGRelationship(source_id="cmd_eval", target_id="cmd_where",
                                       rel_type="pipes_to"))
    kg.add_relationship(KGRelationship(source_id="cmd_where", target_id="cmd_table",
                                       rel_type="pipes_to"))
    kg.add_relationship(KGRelationship(source_id="cmd_stats", target_id="idx_main",
                                       rel_type="uses_index"))
    kg.add_relationship(KGRelationship(source_id="cfg_syslog", target_id="idx_main",
                                       rel_type="targets_index"))
    return kg


# ---------------------------------------------------------------------------
# Test add_entity
# ---------------------------------------------------------------------------

class TestAddEntity:
    def test_add_single_entity(self, kg):
        entity = KGEntity(id="cmd_search", entity_type="Command", name="search",
                          description="Search for events")
        kg.add_entity(entity)
        assert kg.get_entity("cmd_search") is not None
        assert kg.get_entity("cmd_search").name == "search"

    def test_add_duplicate_entity_ignored(self, kg):
        e1 = KGEntity(id="cmd_stats", entity_type="Command", name="stats", description="v1")
        e2 = KGEntity(id="cmd_stats", entity_type="Command", name="stats", description="v2")
        kg.add_entity(e1)
        kg.add_entity(e2)
        # First one wins
        assert kg.get_entity("cmd_stats").description == "v1"

    def test_entity_indexed_by_type(self, kg):
        kg.add_entity(KGEntity(id="cmd_a", entity_type="Command", name="a"))
        kg.add_entity(KGEntity(id="fn_b", entity_type="Function", name="b"))
        commands = kg.query_by_type("Command")
        assert any(e.id == "cmd_a" for e in commands)
        functions = kg.query_by_type("Function")
        assert any(e.id == "fn_b" for e in functions)

    def test_entity_indexed_by_name(self, kg):
        kg.add_entity(KGEntity(id="cmd_stats", entity_type="Command", name="stats"))
        resolved = kg.resolve_entity("stats")
        assert resolved is not None
        assert resolved.id == "cmd_stats"

    def test_entity_name_case_insensitive(self, kg):
        kg.add_entity(KGEntity(id="cmd_stats", entity_type="Command", name="Stats"))
        assert kg.resolve_entity("stats") is not None
        assert kg.resolve_entity("STATS") is not None


# ---------------------------------------------------------------------------
# Test add_relationship
# ---------------------------------------------------------------------------

class TestAddRelationship:
    def test_add_valid_relationship(self, populated_kg):
        neighbors = populated_kg.get_neighbors("cmd_stats", direction="out")
        rel_types = {n["rel_type"] for n in neighbors}
        assert "uses_functions" in rel_types
        assert "operates_on" in rel_types

    def test_add_relationship_missing_source(self, kg):
        kg.add_entity(KGEntity(id="target", entity_type="Field", name="host"))
        # Source does not exist -- relationship should be silently ignored
        kg.add_relationship(KGRelationship(
            source_id="nonexistent", target_id="target", rel_type="operates_on"))
        neighbors = kg.get_neighbors("target")
        assert len(neighbors) == 0

    def test_add_relationship_missing_target(self, kg):
        kg.add_entity(KGEntity(id="source", entity_type="Command", name="stats"))
        kg.add_relationship(KGRelationship(
            source_id="source", target_id="nonexistent", rel_type="operates_on"))
        neighbors = kg.get_neighbors("source", direction="out")
        assert len(neighbors) == 0


# ---------------------------------------------------------------------------
# Test query_by_type
# ---------------------------------------------------------------------------

class TestQueryByType:
    def test_returns_correct_type(self, populated_kg):
        commands = populated_kg.query_by_type("Command")
        assert len(commands) == 4  # stats, eval, where, table
        for e in commands:
            assert e.entity_type == "Command"

    def test_returns_empty_for_unknown_type(self, populated_kg):
        result = populated_kg.query_by_type("NonexistentType")
        assert result == []

    def test_respects_limit(self, populated_kg):
        result = populated_kg.query_by_type("Command", limit=2)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# Test query_related
# ---------------------------------------------------------------------------

class TestQueryRelated:
    def test_query_related_entities(self, populated_kg):
        related = populated_kg.query_related("stats")
        assert len(related) > 0
        # stats -> count via uses_functions
        target_names = {r["to"] for r in related}
        assert "count" in target_names or "avg" in target_names

    def test_query_related_with_rel_filter(self, populated_kg):
        related = populated_kg.query_related("stats", rel_types=["uses_functions"])
        target_names = {r["to"] for r in related}
        assert "count" in target_names
        assert "avg" in target_names
        # Should not include operates_on relationships
        assert "host" not in target_names

    def test_query_related_nonexistent(self, populated_kg):
        related = populated_kg.query_related("nonexistent_entity_xyz")
        assert related == []

    def test_query_related_depth(self, populated_kg):
        # eval -> where -> table (depth 2)
        related = populated_kg.query_related("eval", max_depth=2)
        target_names = {r["to"] for r in related}
        assert "where" in target_names
        # table should be reachable at depth 2
        assert "table" in target_names

    def test_query_related_max_results(self, populated_kg):
        related = populated_kg.query_related("stats", max_results=1)
        assert len(related) <= 1


# ---------------------------------------------------------------------------
# Test generate_context_for_query
# ---------------------------------------------------------------------------

class TestGenerateContextForQuery:
    def test_generates_context_for_known_entity(self, populated_kg):
        context = populated_kg.generate_context_for_query(
            "How do I use the stats command?", "spl_generation"
        )
        assert context is not None
        assert "stats" in context.lower()

    def test_returns_none_for_unrelated_query(self, kg):
        context = kg.generate_context_for_query(
            "What is the weather like today?", "general_qa"
        )
        assert context is None

    def test_context_includes_relationships(self, populated_kg):
        context = populated_kg.generate_context_for_query(
            "How does stats use functions?", "spl_generation"
        )
        if context:
            # Should mention at least one related entity
            assert any(name in context.lower()
                       for name in ["count", "avg", "host", "main"])


# ---------------------------------------------------------------------------
# Test entity name resolution priority
# ---------------------------------------------------------------------------

class TestNameResolutionPriority:
    def test_command_wins_over_field(self, kg):
        """When a Command and Field share the same name, Command should win."""
        kg.add_entity(KGEntity(id="field_stats", entity_type="Field", name="stats",
                               description="A field named stats"))
        kg.add_entity(KGEntity(id="cmd_stats", entity_type="Command", name="stats",
                               description="The stats command"))
        resolved = kg.resolve_entity("stats")
        assert resolved.entity_type == "Command"
        assert resolved.id == "cmd_stats"

    def test_command_wins_over_function(self, kg):
        """Command has higher priority than Function in name index."""
        kg.add_entity(KGEntity(id="fn_eval", entity_type="Function", name="eval"))
        kg.add_entity(KGEntity(id="cmd_eval", entity_type="Command", name="eval"))
        resolved = kg.resolve_entity("eval")
        assert resolved.entity_type == "Command"

    def test_function_wins_over_field(self, kg):
        """Function has higher priority than Field."""
        kg.add_entity(KGEntity(id="field_count", entity_type="Field", name="count"))
        kg.add_entity(KGEntity(id="fn_count", entity_type="Function", name="count"))
        resolved = kg.resolve_entity("count")
        assert resolved.entity_type == "Function"

    def test_first_entity_of_same_type_wins(self, kg):
        """When two entities of the same type share a name, first one wins."""
        kg.add_entity(KGEntity(id="cmd_a", entity_type="Command", name="mycommand", description="first"))
        kg.add_entity(KGEntity(id="cmd_b", entity_type="Command", name="mycommand", description="second"))
        resolved = kg.resolve_entity("mycommand")
        assert resolved.id == "cmd_a"

    def test_index_wins_over_lookup(self, kg):
        """Index (priority 2) should win over Lookup (priority 3)."""
        kg.add_entity(KGEntity(id="lkp_main", entity_type="Lookup", name="main"))
        kg.add_entity(KGEntity(id="idx_main", entity_type="Index", name="main"))
        resolved = kg.resolve_entity("main")
        assert resolved.entity_type == "Index"


# ---------------------------------------------------------------------------
# Test search_entities
# ---------------------------------------------------------------------------

class TestSearchEntities:
    def test_substring_search(self, populated_kg):
        results = populated_kg.search_entities("stat")
        names = [e.name for e in results]
        assert "stats" in names

    def test_search_with_type_filter(self, populated_kg):
        results = populated_kg.search_entities("a", entity_types=["Function"])
        for e in results:
            assert e.entity_type == "Function"

    def test_search_empty_query(self, populated_kg):
        # Empty string matches everything (substring match)
        results = populated_kg.search_entities("", limit=5)
        assert len(results) <= 5


# ---------------------------------------------------------------------------
# Test graph statistics
# ---------------------------------------------------------------------------

class TestGraphStats:
    def test_entity_count(self, populated_kg):
        # We added 11 entities in the fixture
        assert len(populated_kg._entity_index) == 11

    def test_type_index_counts(self, populated_kg):
        assert len(populated_kg._type_index["Command"]) == 4
        assert len(populated_kg._type_index["Function"]) == 2
        assert len(populated_kg._type_index["Field"]) == 2
        assert len(populated_kg._type_index["Index"]) == 1
        assert len(populated_kg._type_index["Lookup"]) == 1
        assert len(populated_kg._type_index["ConfigStanza"]) == 1

    def test_edge_count(self, populated_kg):
        assert populated_kg._graph.number_of_edges() == 7
