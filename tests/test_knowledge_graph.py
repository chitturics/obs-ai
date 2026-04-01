"""Tests for chat_app.knowledge_graph — entity extraction, graph ops, context gen."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from chat_app.knowledge_graph import (
    KGEntity,
    KGRelationship,
    SplunkKnowledgeGraph,
    SPLQueryAnalyzer,
    extract_entities_from_spl_doc,
    extract_entities_from_rag_context,
    extract_entities_from_splunk_rules,
    extract_entities_from_spec_file,
    extract_entities_from_org_config,
    extract_entities_from_savedsearches,
    extract_entities_from_macros,
    extract_entities_from_indexes_conf,
    extract_entities_from_props_transforms,
    build_knowledge_graph,
    KNOWN_COMMANDS,
    KNOWN_FUNCTIONS,
)


# ---------------------------------------------------------------------------
# Data model tests
# ---------------------------------------------------------------------------

class TestKGEntity:
    """Test entity dataclass."""

    def test_create_entity(self):
        e = KGEntity(id="cmd:stats", entity_type="Command", name="stats")
        assert e.id == "cmd:stats"
        assert e.entity_type == "Command"
        assert e.name == "stats"
        assert e.description == ""
        assert e.metadata == {}

    def test_entity_with_metadata(self):
        e = KGEntity(
            id="cmd:eval", entity_type="Command", name="eval",
            description="Evaluate expressions",
            metadata={"source_url": "http://example.com"},
        )
        assert e.description == "Evaluate expressions"
        assert e.metadata["source_url"] == "http://example.com"


class TestKGRelationship:
    """Test relationship dataclass."""

    def test_create_relationship(self):
        r = KGRelationship(
            source_id="cmd:stats", target_id="fn:count",
            rel_type="uses_functions",
        )
        assert r.source_id == "cmd:stats"
        assert r.target_id == "fn:count"
        assert r.rel_type == "uses_functions"
        assert r.weight == 1.0

    def test_relationship_with_weight(self):
        r = KGRelationship(
            source_id="cmd:stats", target_id="cmd:sort",
            rel_type="pipes_to", weight=3.0,
        )
        assert r.weight == 3.0


# ---------------------------------------------------------------------------
# Core graph operations
# ---------------------------------------------------------------------------

class TestSplunkKnowledgeGraph:
    """Test core graph operations."""

    def _make_graph(self):
        """Helper to create a small test graph."""
        kg = SplunkKnowledgeGraph()
        kg.add_entity(KGEntity(id="cmd:stats", entity_type="Command", name="stats", description="Aggregate statistics"))
        kg.add_entity(KGEntity(id="cmd:sort", entity_type="Command", name="sort", description="Sort results"))
        kg.add_entity(KGEntity(id="cmd:head", entity_type="Command", name="head", description="First N results"))
        kg.add_entity(KGEntity(id="fn:count", entity_type="Function", name="count", description="Count function"))
        kg.add_entity(KGEntity(id="fn:avg", entity_type="Function", name="avg", description="Average function"))
        kg.add_entity(KGEntity(id="idx:main", entity_type="Index", name="main", description="Main index"))

        kg.add_relationship(KGRelationship(source_id="cmd:stats", target_id="fn:count", rel_type="uses_functions"))
        kg.add_relationship(KGRelationship(source_id="cmd:stats", target_id="fn:avg", rel_type="uses_functions"))
        kg.add_relationship(KGRelationship(source_id="cmd:stats", target_id="cmd:sort", rel_type="pipes_to"))
        kg.add_relationship(KGRelationship(source_id="cmd:sort", target_id="cmd:head", rel_type="pipes_to"))
        return kg

    def test_add_entity(self):
        kg = SplunkKnowledgeGraph()
        kg.add_entity(KGEntity(id="cmd:stats", entity_type="Command", name="stats"))
        assert kg.get_entity("cmd:stats") is not None
        assert kg.get_entity("cmd:stats").name == "stats"

    def test_add_duplicate_entity(self):
        kg = SplunkKnowledgeGraph()
        kg.add_entity(KGEntity(id="cmd:stats", entity_type="Command", name="stats"))
        kg.add_entity(KGEntity(id="cmd:stats", entity_type="Command", name="stats_v2"))
        # First one wins
        assert kg.get_entity("cmd:stats").name == "stats"

    def test_add_relationship(self):
        kg = self._make_graph()
        neighbors = kg.get_neighbors("cmd:stats", direction="out")
        assert len(neighbors) == 3  # count, avg, sort

    def test_relationship_missing_entity(self):
        kg = SplunkKnowledgeGraph()
        kg.add_entity(KGEntity(id="cmd:stats", entity_type="Command", name="stats"))
        # target doesn't exist
        kg.add_relationship(KGRelationship(
            source_id="cmd:stats", target_id="cmd:missing",
            rel_type="pipes_to",
        ))
        neighbors = kg.get_neighbors("cmd:stats", direction="out")
        assert len(neighbors) == 0

    def test_get_entity_not_found(self):
        kg = SplunkKnowledgeGraph()
        assert kg.get_entity("cmd:nonexistent") is None

    def test_resolve_entity(self):
        kg = self._make_graph()
        e = kg.resolve_entity("stats")
        assert e is not None
        assert e.id == "cmd:stats"

    def test_resolve_entity_case_insensitive(self):
        kg = self._make_graph()
        e = kg.resolve_entity("STATS")
        assert e is not None
        assert e.name == "stats"

    def test_resolve_entity_not_found(self):
        kg = self._make_graph()
        assert kg.resolve_entity("nonexistent") is None

    def test_query_by_type(self):
        kg = self._make_graph()
        cmds = kg.query_by_type("Command")
        assert len(cmds) == 3
        fns = kg.query_by_type("Function")
        assert len(fns) == 2

    def test_query_by_type_with_limit(self):
        kg = self._make_graph()
        cmds = kg.query_by_type("Command", limit=2)
        assert len(cmds) == 2

    def test_search_entities(self):
        kg = self._make_graph()
        results = kg.search_entities("stat")
        assert len(results) >= 1
        assert any(e.name == "stats" for e in results)

    def test_search_entities_with_type_filter(self):
        kg = self._make_graph()
        results = kg.search_entities("count", entity_types=["Function"])
        assert len(results) == 1
        assert results[0].name == "count"

    def test_get_neighbors_outgoing(self):
        kg = self._make_graph()
        neighbors = kg.get_neighbors("cmd:stats", direction="out")
        rel_types = {n["rel_type"] for n in neighbors}
        assert "uses_functions" in rel_types
        assert "pipes_to" in rel_types

    def test_get_neighbors_incoming(self):
        kg = self._make_graph()
        neighbors = kg.get_neighbors("fn:count", direction="in")
        assert len(neighbors) == 1
        assert neighbors[0]["source_name"] == "stats"

    def test_get_neighbors_both(self):
        kg = self._make_graph()
        neighbors = kg.get_neighbors("cmd:sort", direction="both")
        assert len(neighbors) == 2  # incoming from stats, outgoing to head

    def test_get_neighbors_unknown_entity(self):
        kg = self._make_graph()
        assert kg.get_neighbors("cmd:unknown") == []

    def test_query_related(self):
        kg = self._make_graph()
        results = kg.query_related("stats")
        assert len(results) >= 2
        names = {r["to"] for r in results}
        assert "count" in names or "sort" in names

    def test_query_related_with_rel_filter(self):
        kg = self._make_graph()
        results = kg.query_related("stats", rel_types=["pipes_to"])
        assert all(r["rel_type"] == "pipes_to" for r in results)

    def test_query_related_with_depth(self):
        kg = self._make_graph()
        results = kg.query_related("stats", max_depth=2)
        names = {r["to"] for r in results}
        assert "head" in names  # stats -> sort -> head

    def test_query_related_unknown_entity(self):
        kg = self._make_graph()
        results = kg.query_related("nonexistent")
        assert results == []

    def test_query_path(self):
        kg = self._make_graph()
        path = kg.query_path("stats", "head")
        assert len(path) == 2  # stats -> sort -> head
        assert path[0]["from"] == "stats"
        assert path[0]["to"] == "sort"
        assert path[1]["from"] == "sort"
        assert path[1]["to"] == "head"

    def test_query_path_no_path(self):
        kg = self._make_graph()
        path = kg.query_path("head", "stats")  # no reverse path
        assert path == []

    def test_query_path_unknown_entity(self):
        kg = self._make_graph()
        assert kg.query_path("stats", "nonexistent") == []

    def test_get_subgraph(self):
        kg = self._make_graph()
        sub = kg.get_subgraph(["cmd:stats"], include_neighbors=True)
        assert len(sub["nodes"]) >= 3  # stats + count + avg + sort
        assert len(sub["edges"]) >= 2

    def test_get_subgraph_no_neighbors(self):
        kg = self._make_graph()
        sub = kg.get_subgraph(["cmd:stats"], include_neighbors=False)
        assert len(sub["nodes"]) == 1

    def test_get_stats(self):
        kg = self._make_graph()
        stats = kg.get_stats()
        assert stats["total_entities"] == 6
        assert stats["total_relationships"] == 4
        assert "Command" in stats["entity_type_counts"]
        assert stats["entity_type_counts"]["Command"] == 3

    def test_empty_graph_stats(self):
        kg = SplunkKnowledgeGraph()
        stats = kg.get_stats()
        assert stats["total_entities"] == 0
        assert stats["total_relationships"] == 0


# ---------------------------------------------------------------------------
# Context generation
# ---------------------------------------------------------------------------

class TestContextGeneration:
    """Test RAG context generation."""

    def _make_graph(self):
        kg = SplunkKnowledgeGraph()
        kg.add_entity(KGEntity(id="cmd:stats", entity_type="Command", name="stats", description="Aggregate statistics"))
        kg.add_entity(KGEntity(id="fn:dc", entity_type="Function", name="dc", description="Distinct count"))
        kg.add_entity(KGEntity(id="fn:count", entity_type="Function", name="count", description="Count function"))
        kg.add_entity(KGEntity(id="cmd:sort", entity_type="Command", name="sort", description="Sort results"))
        kg.add_entity(KGEntity(id="cmd:table", entity_type="Command", name="table", description="Display as table"))

        kg.add_relationship(KGRelationship(source_id="cmd:stats", target_id="fn:dc", rel_type="uses_functions"))
        kg.add_relationship(KGRelationship(source_id="cmd:stats", target_id="fn:count", rel_type="uses_functions"))
        kg.add_relationship(KGRelationship(source_id="cmd:stats", target_id="cmd:sort", rel_type="pipes_to"))
        kg.add_relationship(KGRelationship(source_id="cmd:stats", target_id="cmd:table", rel_type="pipes_to"))
        return kg

    def test_generates_context_for_known_entity(self):
        kg = self._make_graph()
        ctx = kg.generate_context_for_query("how do I use stats", "spl_generation")
        assert ctx is not None
        assert "Knowledge Graph Context" in ctx
        assert "stats" in ctx

    def test_returns_none_for_no_entities(self):
        kg = self._make_graph()
        ctx = kg.generate_context_for_query("hello world greetings", "general_qa")
        assert ctx is None

    def test_context_includes_relationships(self):
        kg = self._make_graph()
        ctx = kg.generate_context_for_query("use stats command", "spl_generation")
        assert ctx is not None
        # Should mention functions or pipes_to
        assert "dc" in ctx or "count" in ctx or "sort" in ctx

    def test_intent_affects_priority(self):
        kg = self._make_graph()
        ctx_spl = kg.generate_context_for_query("use stats", "spl_generation")
        ctx_config = kg.generate_context_for_query("use stats", "config_lookup")
        # Both should generate context for stats but with different ordering
        assert ctx_spl is not None

    def test_max_facts_limit(self):
        kg = self._make_graph()
        ctx = kg.generate_context_for_query("stats sort", "spl_generation", max_facts=1)
        assert ctx is not None
        # Should be limited in content


# ---------------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------------

class TestSerialization:
    """Test graph save/load."""

    def test_save_and_load(self, tmp_path):
        kg = SplunkKnowledgeGraph()
        kg.add_entity(KGEntity(id="cmd:stats", entity_type="Command", name="stats"))
        kg.add_entity(KGEntity(id="fn:count", entity_type="Function", name="count"))
        kg.add_relationship(KGRelationship(
            source_id="cmd:stats", target_id="fn:count",
            rel_type="uses_functions", weight=2.0,
        ))
        kg._build_timestamp = "2024-01-01T00:00:00Z"
        kg._build_time_ms = 100.0

        path = str(tmp_path / "test_kg.json")
        kg.save_to_json(path)

        # Load into fresh graph
        kg2 = SplunkKnowledgeGraph()
        assert kg2.load_from_json(path) is True
        assert kg2.get_stats()["total_entities"] == 2
        assert kg2.get_stats()["total_relationships"] == 1
        assert kg2._build_timestamp == "2024-01-01T00:00:00Z"

    def test_load_nonexistent(self, tmp_path):
        kg = SplunkKnowledgeGraph()
        assert kg.load_from_json(str(tmp_path / "nope.json")) is False

    def test_round_trip_preserves_data(self, tmp_path):
        kg = SplunkKnowledgeGraph()
        kg.add_entity(KGEntity(
            id="cmd:eval", entity_type="Command", name="eval",
            description="Evaluate", metadata={"k": "v"},
        ))
        kg.add_entity(KGEntity(id="fn:if", entity_type="Function", name="if"))
        kg.add_relationship(KGRelationship(
            source_id="cmd:eval", target_id="fn:if",
            rel_type="uses_functions",
        ))

        path = str(tmp_path / "rt.json")
        kg.save_to_json(path)

        kg2 = SplunkKnowledgeGraph()
        kg2.load_from_json(path)

        e = kg2.get_entity("cmd:eval")
        assert e.description == "Evaluate"
        assert e.metadata == {"k": "v"}

        neighbors = kg2.get_neighbors("cmd:eval", direction="out")
        assert len(neighbors) == 1
        assert neighbors[0]["target_name"] == "if"


# ---------------------------------------------------------------------------
# Entity extraction from real files
# ---------------------------------------------------------------------------

class TestEntityExtraction:
    """Test extractors against real project files."""

    def test_extract_from_spl_doc_stats(self, spl_docs_dir):
        doc = spl_docs_dir / "spl_cmd_stats.md"
        if not doc.exists():
            pytest.skip("spl_docs not available")
        entities, rels = extract_entities_from_spl_doc(doc)
        # Should have at least the Command entity
        cmd_ents = [e for e in entities if e.entity_type == "Command" and e.name == "stats"]
        assert len(cmd_ents) >= 1
        # Should find some functions
        fn_ents = [e for e in entities if e.entity_type == "Function"]
        assert len(fn_ents) >= 1

    def test_extract_from_spl_doc_eval(self, spl_docs_dir):
        doc = spl_docs_dir / "spl_cmd_eval.md"
        if not doc.exists():
            pytest.skip("spl_docs not available")
        entities, rels = extract_entities_from_spl_doc(doc)
        cmd_ents = [e for e in entities if e.entity_type == "Command" and e.name == "eval"]
        assert len(cmd_ents) >= 1

    def test_extract_from_spl_doc_where(self, spl_docs_dir):
        doc = spl_docs_dir / "spl_cmd_where.md"
        if not doc.exists():
            pytest.skip("spl_docs not available")
        entities, rels = extract_entities_from_spl_doc(doc)
        cmd_ents = [e for e in entities if e.entity_type == "Command" and e.name == "where"]
        assert len(cmd_ents) >= 1

    def test_extract_from_rag_context(self, project_root_dir):
        md = project_root_dir / "metadata" / "rag_context.md"
        if not md.exists():
            pytest.skip("rag_context.md not available")
        entities, rels = extract_entities_from_rag_context(md)
        idx_ents = [e for e in entities if e.entity_type == "Index"]
        field_ents = [e for e in entities if e.entity_type == "Field"]
        assert len(idx_ents) >= 5  # snow, idc_asa, pan_logs, network, wineventlog, ...
        assert len(field_ents) >= 3

    def test_extract_from_rag_context_lookups(self, project_root_dir):
        md = project_root_dir / "metadata" / "rag_context.md"
        if not md.exists():
            pytest.skip("rag_context.md not available")
        entities, rels = extract_entities_from_rag_context(md)
        lookup_ents = [e for e in entities if e.entity_type == "Lookup"]
        assert len(lookup_ents) >= 1  # infoblox_networks_lite, unit_id_list
        # Should have references/enriches relationships
        ref_rels = [r for r in rels if r.rel_type in ("references", "enriches")]
        assert len(ref_rels) >= 1

    def test_extract_from_splunk_rules(self, project_root_dir):
        rules = project_root_dir / "metadata" / "splunk_rules.md"
        if not rules.exists():
            pytest.skip("splunk_rules.md not available")
        entities, rels = extract_entities_from_splunk_rules(rules)
        dm_ents = [e for e in entities if e.entity_type == "Datamodel"]
        assert len(dm_ents) >= 1  # Authentication, Web

    def test_extract_from_spec_file(self, project_root_dir):
        spec = project_root_dir / "ingest_specs" / "app.conf.spec"
        if not spec.exists():
            pytest.skip("app.conf.spec not available")
        entities, rels = extract_entities_from_spec_file(spec)
        stanza_ents = [e for e in entities if e.entity_type == "ConfigStanza"]
        assert len(stanza_ents) >= 1
        # Should have defines relationships
        def_rels = [r for r in rels if r.rel_type == "defines"]
        assert len(def_rels) >= 1

    def test_extract_from_org_config(self):
        cfg = {
            "organization": {
                "index_mappings": {
                    "authentication": "wineventlog",
                    "network": "firewall",
                },
                "field_mappings": {
                    "user": "user",
                    "source_ip": "src_ip",
                },
                "additional_cim_models": {
                    "Email": {
                        "indicators": ["email", "smtp"],
                        "dataset": "All_Email",
                        "fields": {"sender": "Email.All_Email.src_user"},
                    },
                },
            }
        }
        entities, rels = extract_entities_from_org_config(cfg)
        idx_ents = [e for e in entities if e.entity_type == "Index"]
        assert len(idx_ents) == 2
        dm_ents = [e for e in entities if e.entity_type == "Datamodel"]
        assert len(dm_ents) == 1
        assert dm_ents[0].name == "Email"

    def test_extract_nonexistent_file(self):
        entities, rels = extract_entities_from_spl_doc(Path("/nonexistent/file.md"))
        assert entities == []
        assert rels == []


# ---------------------------------------------------------------------------
# Build knowledge graph
# ---------------------------------------------------------------------------

class TestBuildKnowledgeGraph:
    """Test full graph construction."""

    def test_build_from_real_docs(self, spl_docs_dir, project_root_dir):
        if not (spl_docs_dir / "spl_cmd_stats.md").exists():
            pytest.skip("spl_docs not available")
        kg = build_knowledge_graph(
            spl_docs_dir=str(spl_docs_dir),
            metadata_dir=str(project_root_dir / "metadata"),
            spec_dir=str(project_root_dir / "ingest_specs"),
            cache_path="",  # Skip cache
            force_rebuild=True,
        )
        stats = kg.get_stats()
        # Should have a good number of entities
        assert stats["total_entities"] >= 100
        assert stats["total_relationships"] >= 50
        assert "Command" in stats["entity_type_counts"]
        assert stats["entity_type_counts"]["Command"] >= 100  # 174 spl docs

    def test_build_entity_type_diversity(self, spl_docs_dir, project_root_dir):
        if not (spl_docs_dir / "spl_cmd_stats.md").exists():
            pytest.skip("spl_docs not available")
        kg = build_knowledge_graph(
            spl_docs_dir=str(spl_docs_dir),
            metadata_dir=str(project_root_dir / "metadata"),
            spec_dir=str(project_root_dir / "ingest_specs"),
            cache_path="",
            force_rebuild=True,
        )
        stats = kg.get_stats()
        # Should have multiple entity types
        assert len(stats["entity_type_counts"]) >= 5

    def test_json_round_trip(self, tmp_path, spl_docs_dir, project_root_dir):
        if not (spl_docs_dir / "spl_cmd_stats.md").exists():
            pytest.skip("spl_docs not available")

        cache_path = str(tmp_path / "kg_cache.json")
        kg1 = build_knowledge_graph(
            spl_docs_dir=str(spl_docs_dir),
            metadata_dir=str(project_root_dir / "metadata"),
            spec_dir=str(project_root_dir / "ingest_specs"),
            cache_path=cache_path,
            force_rebuild=True,
        )
        stats1 = kg1.get_stats()

        # Load from cache
        kg2 = build_knowledge_graph(
            spl_docs_dir=str(spl_docs_dir),
            metadata_dir=str(project_root_dir / "metadata"),
            spec_dir=str(project_root_dir / "ingest_specs"),
            cache_path=cache_path,
            force_rebuild=False,
        )
        stats2 = kg2.get_stats()

        assert stats1["total_entities"] == stats2["total_entities"]
        assert stats1["total_relationships"] == stats2["total_relationships"]

    def test_build_with_missing_dirs(self, tmp_path):
        kg = build_knowledge_graph(
            spl_docs_dir=str(tmp_path / "no_spl"),
            metadata_dir=str(tmp_path / "no_meta"),
            spec_dir=str(tmp_path / "no_spec"),
            cache_path="",
            force_rebuild=True,
        )
        stats = kg.get_stats()
        # Should still have operators
        assert stats["total_entities"] >= 10  # operators


# ---------------------------------------------------------------------------
# Known constants
# ---------------------------------------------------------------------------

class TestKnownConstants:
    """Test that known command/function sets are reasonable."""

    def test_known_commands_has_common(self):
        assert "stats" in KNOWN_COMMANDS
        assert "eval" in KNOWN_COMMANDS
        assert "where" in KNOWN_COMMANDS
        assert "table" in KNOWN_COMMANDS
        assert "search" in KNOWN_COMMANDS

    def test_known_functions_has_common(self):
        assert "count" in KNOWN_FUNCTIONS
        assert "avg" in KNOWN_FUNCTIONS
        assert "sum" in KNOWN_FUNCTIONS
        assert "dc" in KNOWN_FUNCTIONS
        assert "values" in KNOWN_FUNCTIONS


# ---------------------------------------------------------------------------
# Singleton / feature flag
# ---------------------------------------------------------------------------

class TestSingleton:
    """Test get_knowledge_graph singleton behavior."""

    def test_disabled_returns_none(self):
        """When KG is disabled in settings, get_knowledge_graph returns None."""
        import chat_app.knowledge_graph as kg_mod

        # Save and reset singleton
        old = kg_mod._KG_SINGLETON
        kg_mod._KG_SINGLETON = None

        mock_settings = MagicMock()
        mock_settings.knowledge_graph.enabled = False

        with patch("chat_app.settings.get_settings", return_value=mock_settings):
            result = kg_mod.get_knowledge_graph()
            assert result is None

        kg_mod._KG_SINGLETON = old


# ---------------------------------------------------------------------------
# SPLQueryAnalyzer tests
# ---------------------------------------------------------------------------

class TestSPLQueryAnalyzer:
    """Test SPL query decomposition."""

    def test_analyze_basic_search(self):
        spl = 'index=main sourcetype=syslog | stats count(severity) by severity'
        result = SPLQueryAnalyzer.analyze(spl)
        assert "main" in result["indexes"]
        assert "syslog" in result["sourcetypes"]
        assert "stats" in result["commands"]
        assert "count" in result["functions"]
        assert "severity" in result["fields"]

    def test_analyze_complex_pipeline(self):
        spl = 'index=security sourcetype=cisco:asa | stats count by src_ip, dest_ip | sort -count | head 10'
        result = SPLQueryAnalyzer.analyze(spl)
        assert "security" in result["indexes"]
        assert "cisco:asa" in result["sourcetypes"]
        assert "stats" in result["commands"]
        assert "sort" in result["commands"]
        assert "head" in result["commands"]
        assert "src_ip" in result["fields"]
        assert "dest_ip" in result["fields"]

    def test_analyze_tstats(self):
        spl = '| tstats count from datamodel=Authentication by user'
        result = SPLQueryAnalyzer.analyze(spl)
        assert result["has_tstats"] is True
        assert result["has_summarization"] is True
        assert "Authentication" in result["datamodels"]
        assert "tstats" in result["commands"]

    def test_analyze_macros(self):
        spl = 'index=main `security_filter` | stats count'
        result = SPLQueryAnalyzer.analyze(spl)
        assert "security_filter" in result["macros"]

    def test_analyze_lookup(self):
        spl = 'index=main | lookup asset_lookup ip | table ip, asset_owner'
        result = SPLQueryAnalyzer.analyze(spl)
        assert "asset_lookup" in result["lookups"]

    def test_analyze_empty_input(self):
        result = SPLQueryAnalyzer.analyze("")
        assert result["commands"] == []
        assert result["indexes"] == []

    def test_analyze_filters(self):
        spl = 'index=main unit_id=12345 circuit="ABC-001" | stats count'
        result = SPLQueryAnalyzer.analyze(spl)
        filter_fields = [f["field"] for f in result["filters"]]
        assert "unit_id" in filter_fields
        assert "circuit" in filter_fields

    def test_to_entities_basic(self):
        spl = 'index=main | stats count by host'
        ents, rels = SPLQueryAnalyzer.to_entities_and_relationships(spl, "test_search")
        entity_types = {e.entity_type for e in ents}
        assert "SavedSearch" in entity_types
        assert "Index" in entity_types
        assert "Command" in entity_types
        rel_types = {r.rel_type for r in rels}
        assert "uses_index" in rel_types
        assert "uses_command" in rel_types

    def test_to_entities_with_summarization(self):
        spl = '| tstats count from datamodel=Network_Traffic by src'
        ents, rels = SPLQueryAnalyzer.to_entities_and_relationships(spl, "net_search")
        entity_types = {e.entity_type for e in ents}
        assert "Summarization" in entity_types
        rel_types = {r.rel_type for r in rels}
        assert "accelerated_by" in rel_types


# ---------------------------------------------------------------------------
# Saved search / macro / index / props extractor tests
# ---------------------------------------------------------------------------

class TestConfExtractors:
    """Test .conf file entity extraction."""

    def test_extract_savedsearches(self, tmp_path):
        conf = tmp_path / "savedsearches.conf"
        conf.write_text(
            "[My Alert]\n"
            "search = index=security sourcetype=firewall action=blocked | stats count by src_ip\n"
            "cron_schedule = */5 * * * *\n"
            "is_scheduled = 1\n"
            "\n"
            "[Daily Report]\n"
            "search = index=main | timechart count by host\n"
        )
        ents, rels = extract_entities_from_savedsearches(conf)
        entity_names = {e.name for e in ents}
        assert "My Alert" in entity_names
        assert "Daily Report" in entity_names
        entity_types = {e.entity_type for e in ents}
        assert "SavedSearch" in entity_types
        assert "Index" in entity_types
        assert "Sourcetype" in entity_types

    def test_extract_macros(self, tmp_path):
        conf = tmp_path / "macros.conf"
        conf.write_text(
            "[security_filter]\n"
            "definition = index=security sourcetype=firewall\n"
            "\n"
            "[time_range(2)]\n"
            "definition = earliest=$start$ latest=$end$\n"
            "args = start,end\n"
        )
        ents, rels = extract_entities_from_macros(conf)
        entity_names = {e.name for e in ents}
        assert "security_filter" in entity_names
        assert "time_range" in entity_names
        entity_types = {e.entity_type for e in ents}
        assert "Macro" in entity_types
        # security_filter references index=security
        rel_types = {r.rel_type for r in rels}
        assert "uses_index" in rel_types

    def test_extract_indexes_conf(self, tmp_path):
        conf = tmp_path / "indexes.conf"
        conf.write_text(
            "[main]\n"
            "homePath = $SPLUNK_DB/main/db\n"
            "frozenTimePeriodInSecs = 7776000\n"
            "\n"
            "[security]\n"
            "homePath = $SPLUNK_DB/security/db\n"
            "maxDataSizeMB = 50000\n"
        )
        ents, rels = extract_entities_from_indexes_conf(conf)
        entity_names = {e.name for e in ents}
        assert "main" in entity_names
        assert "security" in entity_names
        for e in ents:
            assert e.entity_type == "Index"

    def test_extract_props_transforms(self, tmp_path):
        props = tmp_path / "props.conf"
        props.write_text(
            "[cisco:asa]\n"
            "EXTRACT-src = src_ip=(?P<src_ip>\\d+\\.\\d+\\.\\d+\\.\\d+)\n"
            "\n"
            "[source::/var/log/syslog]\n"
            "TIME_FORMAT = %b %d %H:%M:%S\n"
        )
        transforms = tmp_path / "transforms.conf"
        transforms.write_text(
            "[extract_user]\n"
            "REGEX = user=(?P<extracted_user>\\w+)\n"
        )
        ents, rels = extract_entities_from_props_transforms(props, transforms)
        entity_types = {e.entity_type for e in ents}
        assert "Sourcetype" in entity_types
        assert "Source" in entity_types
        assert "IndexTimeField" in entity_types
        # Check extracted fields
        entity_names = {e.name for e in ents}
        assert "src_ip" in entity_names
        assert "extracted_user" in entity_names

    def test_extract_nonexistent_conf(self, tmp_path):
        ents, rels = extract_entities_from_savedsearches(tmp_path / "nonexistent.conf")
        assert ents == []
        assert rels == []


# ---------------------------------------------------------------------------
# Multi-context & inline SPL tests
# ---------------------------------------------------------------------------

class TestMultiContext:
    """Test multi-context query understanding."""

    def test_inline_spl_analysis(self):
        kg = SplunkKnowledgeGraph()
        # Add a command so _extract_entity_mentions finds something
        kg.add_entity(KGEntity(id="cmd:stats", entity_type="Command", name="stats"))
        kg.add_entity(KGEntity(id="cmd:eval", entity_type="Command", name="eval"))
        kg.add_relationship(KGRelationship(
            source_id="cmd:stats", target_id="cmd:eval", rel_type="compatible_with"))

        text = "Optimize: index=main sourcetype=syslog | stats count by host"
        context = kg.generate_context_for_query(text, "optimization")
        assert context is not None
        assert "Knowledge Graph" in context

    def test_spl_analyzer_integration(self):
        kg = SplunkKnowledgeGraph()
        count = kg.inject_spl_entities(
            "index=security | stats count by src_ip | sort -count",
            "audit_search"
        )
        assert count > 0
        # Verify entities were added
        entity = kg.resolve_entity("audit_search")
        assert entity is not None
        assert entity.entity_type == "SavedSearch"

    def test_analyze_spl_public_api(self):
        kg = SplunkKnowledgeGraph()
        result = kg.analyze_spl_query("index=main | stats count by host")
        assert "main" in result["indexes"]
        assert "stats" in result["commands"]

    def test_entity_mentions_finds_new_types(self):
        kg = SplunkKnowledgeGraph()
        kg.add_entity(KGEntity(id="macro:sec_filter", entity_type="Macro", name="sec_filter"))
        kg.add_entity(KGEntity(id="st:syslog", entity_type="Sourcetype", name="syslog"))
        kg.add_entity(KGEntity(id="search:my_alert", entity_type="SavedSearch", name="my_alert"))

        found = kg._extract_entity_mentions("what does sec_filter macro do with syslog data?")
        names = {e.name for e in found}
        assert "sec_filter" in names
        assert "syslog" in names
