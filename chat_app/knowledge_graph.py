"""
In-memory Knowledge Graph for SPL entity relationships.

Uses NetworkX to model structural relationships between SPL commands,
functions, fields, indexes, lookups, datamodels, arguments, operators,
and configuration stanzas. Provides graph-augmented context to the RAG
pipeline alongside vector similarity results.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Set


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Entity types & relationship types — defined in knowledge_graph_types.py,
# imported here and re-exported for backward compatibility.
# ---------------------------------------------------------------------------
from chat_app.knowledge_graph_types import (  # noqa: E402, F401
    ENTITY_TYPES,
    KNOWN_COMMANDS,
    KNOWN_FUNCTIONS,
    RELATIONSHIP_TYPES,
)

# I/O, dedup, visualization, stats, serialization mixin (extracted for size)
from chat_app.knowledge_graph_io import KnowledgeGraphIOMixin  # noqa: E402
# GraphRAG context generation mixin (extracted for size)
from chat_app.knowledge_graph_rag import KnowledgeGraphRAGMixin  # noqa: E402


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class KGEntity:
    """A node in the knowledge graph."""
    id: str
    entity_type: str
    name: str
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KGRelationship:
    """An edge in the knowledge graph."""
    source_id: str
    target_id: str
    rel_type: str
    weight: float = 1.0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core graph class
# ---------------------------------------------------------------------------

class SplunkKnowledgeGraph(KnowledgeGraphRAGMixin, KnowledgeGraphIOMixin):
    """In-memory knowledge graph backed by NetworkX.

    Index Strategy:
    - ``_graph``: NetworkX DiGraph — stores nodes (entities) and directed edges (relationships).
      Queried by: node ID lookup O(1), neighbor traversal O(degree), degree-sorted listing.
    - ``_entity_index``: Dict[entity_id, KGEntity] — O(1) entity lookup by ID.
      Used by: entity detail API, graph visualization, context generation.
    - ``_type_index``: Dict[entity_type, Set[entity_id]] — O(1) type filtering.
      Used by: "list all Commands", "count Fields", entity browser filtered by type.
    - ``_name_index``: Dict[lowercase_name, entity_id] — O(1) name-to-ID resolution.
      Used by: query_related() for fuzzy matching, search by name.
      Priority: Commands > Functions > Index > Lookup > Datamodel > Field
      (so "stats" resolves to the Command, not a Field named "stats").
    """

    def __init__(self):
        try:
            import networkx as nx
            self._nx = nx
        except ImportError:
            raise ImportError("networkx is required: pip install networkx>=3.1")

        # Core graph: nodes=entities, edges=relationships (directed)
        self._graph = nx.DiGraph()
        # Fast lookup indexes (maintained in add_entity/add_relationship)
        self._entity_index: Dict[str, KGEntity] = {}          # id -> entity
        self._type_index: Dict[str, Set[str]] = defaultdict(set)  # type -> {ids}
        self._name_index: Dict[str, str] = {}                 # lowercase name -> id
        self._build_timestamp: Optional[str] = None
        self._build_time_ms: float = 0

    # --- Graph building ---

    # Priority for name index: Commands > Functions > Index > Lookup > Datamodel > Field > others
    # When multiple entities share a name, higher priority type wins the name index slot.
    _NAME_PRIORITY = {
        "Command": 0, "Function": 1, "Index": 2, "Lookup": 3,
        "Datamodel": 4, "Operator": 5, "Argument": 6, "Field": 7,
        "ConfigStanza": 8,
    }

    def add_entity(self, entity: KGEntity) -> None:
        """Add an entity (node) to the graph."""
        if entity.id in self._entity_index:
            return
        self._entity_index[entity.id] = entity
        self._type_index[entity.entity_type].add(entity.id)
        # Name index: higher-priority types win (Command > Function > Field > ConfigStanza)
        name_lower = entity.name.lower()
        existing_id = self._name_index.get(name_lower)
        if existing_id:
            existing_entity = self._entity_index.get(existing_id)
            if existing_entity:
                existing_pri = self._NAME_PRIORITY.get(existing_entity.entity_type, 9)
                new_pri = self._NAME_PRIORITY.get(entity.entity_type, 9)
                if new_pri < existing_pri:
                    self._name_index[name_lower] = entity.id
            else:
                self._name_index[name_lower] = entity.id
        else:
            self._name_index[name_lower] = entity.id
        self._graph.add_node(entity.id, **asdict(entity))

    def add_relationship(self, rel: KGRelationship) -> None:
        """Add a relationship (edge) to the graph."""
        if rel.source_id not in self._entity_index:
            return
        if rel.target_id not in self._entity_index:
            return
        self._graph.add_edge(
            rel.source_id, rel.target_id,
            rel_type=rel.rel_type,
            weight=rel.weight,
            metadata=rel.metadata,
        )

    # --- Query methods ---

    def get_entity(self, entity_id: str) -> Optional[KGEntity]:
        """Get entity by ID."""
        return self._entity_index.get(entity_id)

    def resolve_entity(self, name: str) -> Optional[KGEntity]:
        """Resolve entity by name (case-insensitive)."""
        eid = self._name_index.get(name.lower())
        if eid:
            return self._entity_index.get(eid)
        return None

    def query_by_type(self, entity_type: str, limit: int = 50) -> List[KGEntity]:
        """Return entities of a given type."""
        ids = sorted(self._type_index.get(entity_type, set()))
        return [self._entity_index[eid] for eid in ids[:limit]]

    def search_entities(self, query: str, entity_types: Optional[List[str]] = None,
                        limit: int = 10) -> List[KGEntity]:
        """Search entities by name substring."""
        query_lower = query.lower()
        results = []
        for name_lower, eid in self._name_index.items():
            if query_lower in name_lower:
                entity = self._entity_index[eid]
                if entity_types and entity.entity_type not in entity_types:
                    continue
                results.append(entity)
                if len(results) >= limit:
                    break
        return results

    def get_neighbors(self, entity_id: str, direction: str = "both") -> List[Dict]:
        """Get all relationships for an entity."""
        if entity_id not in self._graph:
            return []
        results = []
        if direction in ("out", "both"):
            for _, target, data in self._graph.out_edges(entity_id, data=True):
                target_entity = self._entity_index.get(target)
                results.append({
                    "direction": "outgoing",
                    "rel_type": data.get("rel_type", ""),
                    "target_id": target,
                    "target_name": target_entity.name if target_entity else target,
                    "target_type": target_entity.entity_type if target_entity else "",
                    "weight": data.get("weight", 1.0),
                })
        if direction in ("in", "both"):
            for source, _, data in self._graph.in_edges(entity_id, data=True):
                source_entity = self._entity_index.get(source)
                results.append({
                    "direction": "incoming",
                    "rel_type": data.get("rel_type", ""),
                    "source_id": source,
                    "source_name": source_entity.name if source_entity else source,
                    "source_type": source_entity.entity_type if source_entity else "",
                    "weight": data.get("weight", 1.0),
                })
        return results

    def query_related(self, entity_name: str, rel_types: Optional[List[str]] = None,
                      max_depth: int = 2, max_results: int = 10) -> List[Dict]:
        """Query related entities starting from a named entity."""
        entity = self.resolve_entity(entity_name)
        # Fallback: try individual words, then substring search
        if not entity:
            for word in entity_name.split():
                entity = self.resolve_entity(word.strip())
                if entity:
                    break
        if not entity:
            # Try substring search and use the best match
            candidates = self.search_entities(entity_name, limit=1)
            if not candidates:
                for word in entity_name.split():
                    candidates = self.search_entities(word.strip(), limit=1)
                    if candidates:
                        break
            if candidates:
                entity = candidates[0]
        if not entity:
            return []

        visited = set()
        results: list[dict] = []
        queue = [(entity.id, 0)]

        while queue and len(results) < max_results:
            current_id, depth = queue.pop(0)
            if current_id in visited:
                continue
            visited.add(current_id)

            neighbors = self.get_neighbors(current_id, direction="out")
            for n in neighbors:
                if rel_types and n["rel_type"] not in rel_types:
                    continue
                if n["target_id"] not in visited:
                    results.append({
                        "from": self._entity_index[current_id].name,
                        "rel_type": n["rel_type"],
                        "to": n["target_name"],
                        "to_type": n["target_type"],
                        "depth": depth + 1,
                    })
                    if depth + 1 < max_depth:
                        queue.append((n["target_id"], depth + 1))

        return results[:max_results]

    def query_path(self, source_name: str, target_name: str,
                   max_depth: int = 3) -> List[Dict]:
        """Find shortest path between two named entities."""
        source = self.resolve_entity(source_name)
        target = self.resolve_entity(target_name)
        if not source or not target:
            return []
        try:
            path = self._nx.shortest_path(
                self._graph, source.id, target.id,
            )
        except (self._nx.NetworkXNoPath, self._nx.NodeNotFound):
            return []

        if len(path) - 1 > max_depth:
            return []

        result = []
        for i in range(len(path) - 1):
            edge_data = self._graph.edges[path[i], path[i + 1]]
            src_e = self._entity_index[path[i]]
            tgt_e = self._entity_index[path[i + 1]]
            result.append({
                "from": src_e.name,
                "from_type": src_e.entity_type,
                "rel_type": edge_data.get("rel_type", ""),
                "to": tgt_e.name,
                "to_type": tgt_e.entity_type,
            })
        return result

    def get_subgraph(self, entity_ids: List[str],
                     include_neighbors: bool = True) -> Dict:
        """Get a subgraph around specified entities."""
        node_ids = set(entity_ids)
        if include_neighbors:
            for eid in list(entity_ids):
                if eid in self._graph:
                    node_ids.update(self._graph.successors(eid))
                    node_ids.update(self._graph.predecessors(eid))

        nodes = []
        for nid in node_ids:
            e = self._entity_index.get(nid)
            if e:
                nodes.append({"id": e.id, "name": e.name, "type": e.entity_type})

        edges = []
        for u, v, data in self._graph.edges(data=True):
            if u in node_ids and v in node_ids:
                edges.append({
                    "source": u, "target": v,
                    "rel_type": data.get("rel_type", ""),
                })
        return {"nodes": nodes, "edges": edges}

    # RAG context generation, query expansion, entity mention extraction,
    # fuzzy matching, and edit distance are provided by KnowledgeGraphRAGMixin
    # (knowledge_graph_rag.py).
    # Dedup, tool entities, visualization, stats, serialization
    # are provided by KnowledgeGraphIOMixin (knowledge_graph_io.py).


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_KG_SINGLETON: Optional[SplunkKnowledgeGraph] = None


def get_knowledge_graph() -> Optional[SplunkKnowledgeGraph]:
    """Return the singleton KG instance, building it lazily on first access."""
    global _KG_SINGLETON
    if _KG_SINGLETON is not None:
        return _KG_SINGLETON

    try:
        from chat_app.settings import get_settings
        settings = get_settings()
    except Exception as _exc:  # broad catch — resilience against all failures
        return None

    if not settings.knowledge_graph.enabled:
        logger.info("[KG] Knowledge graph disabled in settings")
        return None

    try:
        _KG_SINGLETON = build_knowledge_graph(
            spl_docs_dir=settings.knowledge_graph.spl_docs_dir,
            metadata_dir=settings.knowledge_graph.metadata_dir,
            spec_dir=settings.knowledge_graph.spec_dir,
            cache_path=settings.knowledge_graph.cache_path,
            force_rebuild=settings.knowledge_graph.rebuild_on_startup,
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[KG] Failed to build knowledge graph: %s", exc)
        _KG_SINGLETON = None

    return _KG_SINGLETON


def rebuild_knowledge_graph() -> SplunkKnowledgeGraph:
    """Force rebuild (used by admin API)."""
    global _KG_SINGLETON

    try:
        from chat_app.settings import get_settings
        settings = get_settings()
        _KG_SINGLETON = build_knowledge_graph(
            spl_docs_dir=settings.knowledge_graph.spl_docs_dir,
            metadata_dir=settings.knowledge_graph.metadata_dir,
            spec_dir=settings.knowledge_graph.spec_dir,
            cache_path=settings.knowledge_graph.cache_path,
            force_rebuild=True,
        )
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning("[KG] Rebuild failed: %s", exc)
        _KG_SINGLETON = build_knowledge_graph(force_rebuild=True)

    return _KG_SINGLETON


# ---------------------------------------------------------------------------
# Entity extractors & build orchestrator — extracted to kg_builders.py
# Re-exported here for backward compatibility (must be after class definitions
# to avoid circular imports — kg_builders imports from this module).
# ---------------------------------------------------------------------------
try:
    from chat_app.kg_builders import (  # noqa: F401, E402 — re-export
        SPLQueryAnalyzer,
        build_knowledge_graph,
        extract_entities_from_indexes_conf,
        extract_entities_from_macros,
        extract_entities_from_org_config,
        extract_entities_from_props_transforms,
        extract_entities_from_rag_context,
        extract_entities_from_savedsearches,
        extract_entities_from_spl_doc,
        extract_entities_from_splunk_rules,
        extract_entities_from_spec_file,
    )
except ImportError:
    # Fallback: kg_builders not yet fully initialized (circular import during first load)
    # These will be resolved once the module system completes initialization.
    build_knowledge_graph = None  # type: ignore[assignment]
    SPLQueryAnalyzer = None  # type: ignore[assignment]
