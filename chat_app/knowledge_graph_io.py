"""
Knowledge Graph — I/O, Visualization, Deduplication, and Tool Cross-referencing.

Mixin class extracted from knowledge_graph.py for size management.
SplunkKnowledgeGraph inherits from KnowledgeGraphIOMixin.

Provides:
- Entity deduplication (deduplicate_entities, _merge_entity_into, _normalize_entity_name)
- Tool/Skill cross-referencing (add_tool_entities)
- Graph visualization data (get_visualization_data)
- Statistics (get_stats)
- Serialization (save_to_json, load_from_json)
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class KnowledgeGraphIOMixin:
    """
    Mixin providing I/O, visualization, dedup, and tool cross-referencing
    for SplunkKnowledgeGraph.

    Requires the host class to have these attributes:
        _graph, _entity_index, _type_index, _name_index,
        _build_timestamp, _build_time_ms,
        add_entity(), add_relationship()
    """

    # --- Entity deduplication ---

    def deduplicate_entities(self) -> int:
        """Merge entities that refer to the same concept.

        Rules:
        - Same name + same type: merge (keep the one with more relationships)
        - Same name + different type: keep separate (e.g., "stats" Command vs "stats" Function)
        - Normalize common variations: underscores/hyphens, singular/plural

        Returns the number of entities merged.
        """
        merged_count = 0

        # Group entities by (normalized_name, entity_type)
        groups: Dict[Tuple[str, str], List[str]] = defaultdict(list)
        for eid, entity in self._entity_index.items():
            norm_name = self._normalize_entity_name(entity.name)
            groups[(norm_name, entity.entity_type)].append(eid)

        for (norm_name, etype), eids in groups.items():
            if len(eids) < 2:
                continue

            # Sort by relationship count (most connected first)
            eids.sort(
                key=lambda eid: self._graph.degree(eid) if eid in self._graph else 0,
                reverse=True,
            )

            # Keep the first (most connected), merge others into it
            primary_id = eids[0]
            for duplicate_id in eids[1:]:
                self._merge_entity_into(duplicate_id, primary_id)
                merged_count += 1

        if merged_count:
            logger.info("[KG] Deduplicated %d entities", merged_count)
        return merged_count

    @staticmethod
    def _normalize_entity_name(name: str) -> str:
        """Normalize entity name for dedup comparison."""
        n = name.lower().strip()
        # Normalize separators
        n = n.replace("-", "_").replace(" ", "_")
        # Remove trailing 's' for simple plural normalization
        # but not for short names (e.g., "stats" should stay "stats")
        if len(n) > 5 and n.endswith("s") and not n.endswith("ss"):
            n = n[:-1]
        return n

    def _merge_entity_into(self, source_id: str, target_id: str) -> None:
        """Merge source entity into target, transferring all relationships."""
        if source_id not in self._entity_index or target_id not in self._entity_index:
            return

        source_entity = self._entity_index[source_id]
        target_entity = self._entity_index[target_id]

        # Transfer description if target lacks one
        if not target_entity.description and source_entity.description:
            target_entity.description = source_entity.description

        # Merge metadata
        for k, v in source_entity.metadata.items():
            if k not in target_entity.metadata:
                target_entity.metadata[k] = v

        # Re-wire outgoing edges
        if source_id in self._graph:
            for _, neighbor, data in list(self._graph.out_edges(source_id, data=True)):
                if neighbor != target_id:  # Avoid self-loops
                    self._graph.add_edge(target_id, neighbor, **data)

            # Re-wire incoming edges
            for neighbor, _, data in list(self._graph.in_edges(source_id, data=True)):
                if neighbor != target_id:
                    self._graph.add_edge(neighbor, target_id, **data)

            # Remove source node from graph
            self._graph.remove_node(source_id)

        # Remove from indexes
        del self._entity_index[source_id]
        self._type_index[source_entity.entity_type].discard(source_id)

        # Update name index if it pointed to the removed entity
        name_lower = source_entity.name.lower()
        if self._name_index.get(name_lower) == source_id:
            self._name_index[name_lower] = target_id

    # --- Tool/Skill cross-referencing ---

    def add_tool_entities(self) -> int:
        """Add tool registry and skill catalog entries as KG entities.

        Creates Tool/Skill nodes and connects them to related SPL commands
        and concepts based on their intents and tags.

        Returns the number of entities added.
        """
        from chat_app.knowledge_graph_types import KNOWN_COMMANDS
        from chat_app.knowledge_graph import KGEntity, KGRelationship

        added = 0

        # Try importing skill catalog
        try:
            from chat_app.skill_catalog import SkillCatalog
            catalog = SkillCatalog()
            for skill in catalog.all_skills():
                skill_id = f"skill:{skill.name}"
                if skill_id in self._entity_index:
                    continue

                self.add_entity(KGEntity(
                    id=skill_id,
                    entity_type="Skill",
                    name=skill.name,
                    description=skill.description[:200] if skill.description else "",
                    metadata={
                        "family": skill.family.value if hasattr(skill.family, "value") else str(skill.family),
                        "handler_key": skill.handler_key,
                        "tags": skill.tags,
                        "intents": skill.intents,
                    },
                ))
                added += 1

                # Connect skill to SPL commands it mentions
                for intent_name in skill.intents:
                    # Check if intent maps to a known command
                    cmd_name = intent_name.lower().replace("spl_", "").replace("_", "")
                    cmd_id = f"cmd:{cmd_name}"
                    if cmd_id in self._entity_index:
                        self.add_relationship(KGRelationship(
                            source_id=skill_id, target_id=cmd_id,
                            rel_type="uses_command", weight=0.6,
                        ))

                # Connect via tags
                for tag in skill.tags:
                    tag_lower = tag.lower()
                    # Check if tag matches a known entity
                    eid = self._name_index.get(tag_lower)
                    if eid:
                        self.add_relationship(KGRelationship(
                            source_id=skill_id, target_id=eid,
                            rel_type="references", weight=0.5,
                        ))

        except (ImportError, Exception) as exc:
            logger.debug("[KG] Could not load skill catalog: %s", exc)

        # Try importing tool registry
        try:
            from chat_app.tool_registry import ToolRegistry
            registry = ToolRegistry()
            for tool_name, tool_meta in registry.all_tools().items():
                tool_id = f"tool:{tool_name}"
                if tool_id in self._entity_index:
                    continue

                desc = ""
                if isinstance(tool_meta, dict):
                    desc = tool_meta.get("description", "")[:200]
                elif hasattr(tool_meta, "description"):
                    desc = (tool_meta.description or "")[:200]

                self.add_entity(KGEntity(
                    id=tool_id,
                    entity_type="Tool",
                    name=tool_name,
                    description=desc,
                ))
                added += 1

                # Connect tools to SPL commands they wrap
                for cmd_name in KNOWN_COMMANDS:
                    if cmd_name in tool_name.lower():
                        cmd_id = f"cmd:{cmd_name}"
                        if cmd_id in self._entity_index:
                            self.add_relationship(KGRelationship(
                                source_id=tool_id, target_id=cmd_id,
                                rel_type="references", weight=0.7,
                            ))
                            break

        except (ImportError, Exception) as exc:
            logger.debug("[KG] Could not load tool registry: %s", exc)

        if added:
            logger.info("[KG] Added %d tool/skill entities", added)
        return added

    # --- Graph visualization data (enhanced) ---

    def get_visualization_data(
        self,
        limit: int = 200,
        offset: int = 0,
        entity_types: Optional[List[str]] = None,
        min_connections: int = 0,
    ) -> Dict[str, Any]:
        """Return rich visualization data with filtering and grouping.

        Returns nodes with full metadata (relationship_count, entity_type,
        description) and edges with relationship type labels. Supports
        filtering by entity type and minimum connection count.
        """
        G = self._graph

        # Filter nodes by criteria
        candidate_nodes = []
        for nid in G.nodes():
            entity = self._entity_index.get(nid)
            if not entity:
                continue
            degree = G.degree(nid)

            # Apply filters
            if entity_types and entity.entity_type not in entity_types:
                continue
            if degree < min_connections:
                continue

            candidate_nodes.append((nid, entity, degree))

        # Sort by degree (most connected first)
        candidate_nodes.sort(key=lambda x: -x[2])
        total = len(candidate_nodes)

        # Paginate
        page = candidate_nodes[offset:offset + limit]
        node_set = {nid for nid, _, _ in page}

        # Build node data with grouping by type
        type_groups: Dict[str, List[Dict]] = defaultdict(list)
        nodes = []
        for nid, entity, degree in page:
            node_data = {
                "id": nid,
                "name": entity.name,
                "entity_type": entity.entity_type,
                "description": entity.description[:200] if entity.description else "",
                "relationship_count": degree,
                "in_degree": G.in_degree(nid),
                "out_degree": G.out_degree(nid),
                "metadata": entity.metadata,
            }
            nodes.append(node_data)
            type_groups[entity.entity_type].append({"id": nid, "name": entity.name})

        # Build edges with relationship type labels
        edges = []
        for u, v, edata in G.edges(data=True):
            if u in node_set and v in node_set:
                edges.append({
                    "source": u,
                    "target": v,
                    "rel_type": edata.get("rel_type", ""),
                    "label": edata.get("rel_type", "").replace("_", " "),
                    "weight": edata.get("weight", 1.0),
                })

        return {
            "nodes": nodes,
            "edges": edges,
            "total": total,
            "type_groups": {k: len(v) for k, v in type_groups.items()},
            "available_types": sorted(type_groups.keys()),
        }

    # --- Stats ---

    def get_stats(self) -> Dict[str, Any]:
        """Return graph statistics."""
        type_counts = {t: len(ids) for t, ids in self._type_index.items()}
        rel_type_counts: Dict[str, int] = defaultdict(int)
        for _, _, data in self._graph.edges(data=True):
            rel_type_counts[data.get("rel_type", "unknown")] += 1

        return {
            "total_entities": len(self._entity_index),
            "total_relationships": self._graph.number_of_edges(),
            "entity_type_counts": dict(type_counts),
            "relationship_type_counts": dict(rel_type_counts),
            "build_timestamp": self._build_timestamp,
            "build_time_ms": self._build_time_ms,
        }

    # --- Serialization ---

    def save_to_json(self, path: str) -> None:
        """Serialize graph to JSON file."""
        from dataclasses import asdict
        relationships: List[Dict[str, Any]] = []
        for source, target, edge_data in self._graph.edges(data=True):
            relationships.append({
                "source_id": source,
                "target_id": target,
                "rel_type": edge_data.get("rel_type", ""),
                "weight": edge_data.get("weight", 1.0),
                "metadata": edge_data.get("metadata", {}),
            })
        data: Dict[str, Any] = {
            "build_timestamp": self._build_timestamp,
            "build_time_ms": self._build_time_ms,
            "entities": [asdict(e) for e in self._entity_index.values()],
            "relationships": relationships,
        }

        filepath = Path(path)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, default=str)
        logger.info("[KG] Saved graph to %s (%d entities, %d relationships)",
                    path, len(data["entities"]), len(relationships))

    def load_from_json(self, path: str) -> bool:
        """Load graph from JSON file. Returns True if successful."""
        from chat_app.knowledge_graph import KGEntity, KGRelationship
        filepath = Path(path)
        if not filepath.exists():
            return False
        try:
            with open(filepath, encoding="utf-8") as f:
                data = json.load(f)

            self._build_timestamp = data.get("build_timestamp")
            self._build_time_ms = data.get("build_time_ms", 0)

            for e_data in data.get("entities", []):
                entity = KGEntity(
                    id=e_data["id"],
                    entity_type=e_data["entity_type"],
                    name=e_data["name"],
                    description=e_data.get("description", ""),
                    metadata=e_data.get("metadata", {}),
                )
                self.add_entity(entity)

            for r_data in data.get("relationships", []):
                rel = KGRelationship(
                    source_id=r_data["source_id"],
                    target_id=r_data["target_id"],
                    rel_type=r_data["rel_type"],
                    weight=r_data.get("weight", 1.0),
                    metadata=r_data.get("metadata", {}),
                )
                self.add_relationship(rel)

            logger.info("[KG] Loaded graph from %s (%d entities, %d rels)",
                        path, len(self._entity_index), self._graph.number_of_edges())
            return True
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[KG] Failed to load graph from %s: %s", path, exc)
            return False
