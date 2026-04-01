"""
Cross-app dependency graph builder and impact tracer for the Splunk Upgrade
Readiness Testing System.

Builds a directed graph where nodes are (app_name, entity_type, entity_name)
and edges represent "A uses B" relationships found in conf files.

Supported dependency rules:
- props.conf TRANSFORMS-* → transforms.conf stanza
- savedsearches.conf search = ... | lookup X → transforms.conf lookup stanza
- savedsearches.conf search = `macro_name` → macros.conf stanza
- eventtypes.conf search = sourcetype=X → props.conf stanza
- tags.conf [eventtype=X] → eventtypes.conf stanza
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from chat_app.upgrade_readiness.models import ClusterInventory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Node and edge types
# ---------------------------------------------------------------------------

# Entity types stored as graph node "type" attribute
ENTITY_PROPS_STANZA = "props_stanza"
ENTITY_TRANSFORMS_STANZA = "transforms_stanza"
ENTITY_SAVEDSEARCH = "savedsearch"
ENTITY_MACRO = "macro"
ENTITY_EVENTTYPE = "eventtype"
ENTITY_TAG_STANZA = "tag_stanza"
ENTITY_LOOKUP = "lookup"

# Edge relationship labels
EDGE_TRANSFORMS_REFERENCE = "transforms_reference"
EDGE_LOOKUP_REFERENCE = "lookup_reference"
EDGE_MACRO_USAGE = "macro_usage"
EDGE_SOURCETYPE_FEEDS = "sourcetype_feeds"
EDGE_EVENTTYPE_TAGGED_BY = "eventtype_tagged_by"


# ---------------------------------------------------------------------------
# Graph data structures (pure Python, no NetworkX dependency)
# ---------------------------------------------------------------------------


@dataclass
class GraphNode:
    """
    A node in the dependency graph.

    Attributes:
        node_id: Unique string identifier, format "<app>::<type>::<name>".
        app_name: App that defines this entity.
        entity_type: One of the ENTITY_* constants.
        entity_name: Name within the app (stanza name, search name, etc.).
    """

    node_id: str
    app_name: str
    entity_type: str
    entity_name: str


@dataclass
class GraphEdge:
    """
    A directed edge representing a dependency relationship.

    Attributes:
        source_id: node_id of the depending entity (the consumer).
        target_id: node_id of the depended-on entity (the provider).
        relationship: One of the EDGE_* constants.
        conf_file: Source conf file where the dependency was found.
    """

    source_id: str
    target_id: str
    relationship: str
    conf_file: str = ""


@dataclass
class DependencyGraph:
    """
    Lightweight directed graph of Splunk configuration dependencies.

    Attributes:
        nodes: All nodes keyed by node_id.
        edges: All directed edges as a list.
        adjacency: node_id → set of target node_ids (outbound edges).
        reverse_adjacency: node_id → set of source node_ids (inbound edges).
    """

    nodes: Dict[str, GraphNode] = field(default_factory=dict)
    edges: List[GraphEdge] = field(default_factory=list)
    adjacency: Dict[str, Set[str]] = field(default_factory=dict)
    reverse_adjacency: Dict[str, Set[str]] = field(default_factory=dict)

    def add_node(self, node: GraphNode) -> None:
        """Add a node, ignoring duplicates by node_id."""
        if node.node_id not in self.nodes:
            self.nodes[node.node_id] = node
            self.adjacency[node.node_id] = set()
            self.reverse_adjacency[node.node_id] = set()

    def add_edge(self, edge: GraphEdge) -> None:
        """Add a directed edge, ensuring both endpoints exist in the graph."""
        self.edges.append(edge)
        self.adjacency.setdefault(edge.source_id, set()).add(edge.target_id)
        self.reverse_adjacency.setdefault(edge.target_id, set()).add(edge.source_id)


@dataclass
class ImpactPath:
    """
    A chain of dependencies from a changed entity to a downstream consumer.

    Attributes:
        changed_entity_id: The node_id of the entity that changed.
        impacted_entity_id: The node_id of the downstream consumer.
        path: Ordered list of node_ids from changed_entity_id to impacted_entity_id.
        hop_count: Number of dependency hops (len(path) - 1).
        relationship_chain: Edge relationship labels along the path.
    """

    changed_entity_id: str
    impacted_entity_id: str
    path: List[str]
    hop_count: int
    relationship_chain: List[str]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _make_node_id(app_name: str, entity_type: str, entity_name: str) -> str:
    """Build a canonical node_id string."""
    return f"{app_name}::{entity_type}::{entity_name}"


def _get_or_create_node(
    graph: DependencyGraph,
    app_name: str,
    entity_type: str,
    entity_name: str,
) -> GraphNode:
    """Return existing node or create and register it."""
    node_id = _make_node_id(app_name, entity_type, entity_name)
    if node_id not in graph.nodes:
        node = GraphNode(
            node_id=node_id,
            app_name=app_name,
            entity_type=entity_type,
            entity_name=entity_name,
        )
        graph.add_node(node)
    return graph.nodes[node_id]


def _extract_lookup_names(search_string: str) -> List[str]:
    """
    Extract lookup table names referenced in a SPL search string.

    Matches patterns like:
        | lookup lookup_name ...
        [| lookup lookup_name ...]

    Args:
        search_string: Raw SPL search string.

    Returns:
        List of lookup names found.
    """
    pattern = r'\|\s*lookup\s+(\S+)'
    return re.findall(pattern, search_string, re.IGNORECASE)


def _extract_macro_names(search_string: str) -> List[str]:
    """
    Extract macro names referenced in a SPL search string.

    Matches backtick invocations: `macro_name` or `macro_name(arg1,arg2)`

    Args:
        search_string: Raw SPL search string.

    Returns:
        List of macro names found (without backticks or arguments).
    """
    # Match `macro_name` or `macro_name(...)` — exclude $variable$ references
    pattern = r'`([a-zA-Z_][\w]*)(?:\([^`]*\))?`'
    return re.findall(pattern, search_string)


def _extract_sourcetypes_from_search(search_string: str) -> List[str]:
    """
    Parse sourcetype= references from a search string.

    Args:
        search_string: Raw SPL or eventtype search string.

    Returns:
        List of sourcetype names.
    """
    pattern = r'sourcetype\s*=\s*"?([^"\s\)]+)"?'
    return re.findall(pattern, search_string, re.IGNORECASE)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------


def _add_props_transforms_edges(
    graph: DependencyGraph,
    app_name: str,
    props_stanzas: Dict[str, Dict[str, str]],
    transforms_stanzas: Dict[str, Dict[str, str]],
    all_apps_transforms: Dict[str, Dict[str, Dict[str, str]]],
) -> None:
    """
    Add edges from props.conf TRANSFORMS-* references to transforms.conf stanzas.

    For every props stanza key matching TRANSFORMS-*, the value is one or more
    comma-separated transform stanza names.  Each referenced stanza becomes a
    target node; if it lives in another app, that app's node is used.
    """
    for props_stanza_name, keys in props_stanzas.items():
        source_node = _get_or_create_node(
            graph, app_name, ENTITY_PROPS_STANZA, props_stanza_name
        )
        for key, value in keys.items():
            if key == "__lines__":
                continue
            if not (key.upper().startswith("TRANSFORMS-") or key.upper().startswith("TRANSFORMS_")):
                continue
            for transform_name in re.split(r",\s*", value):
                transform_name = transform_name.strip()
                if not transform_name:
                    continue

                # Find which app owns this transform (search all apps)
                owner_app = app_name  # default: same app
                for candidate_app, t_stanzas in all_apps_transforms.items():
                    if transform_name in t_stanzas:
                        owner_app = candidate_app
                        break

                target_node = _get_or_create_node(
                    graph, owner_app, ENTITY_TRANSFORMS_STANZA, transform_name
                )
                graph.add_edge(
                    GraphEdge(
                        source_id=source_node.node_id,
                        target_id=target_node.node_id,
                        relationship=EDGE_TRANSFORMS_REFERENCE,
                        conf_file="props.conf",
                    )
                )


def _add_savedsearches_edges(
    graph: DependencyGraph,
    app_name: str,
    savedsearches_stanzas: Dict[str, Dict[str, str]],
    all_apps_transforms: Dict[str, Dict[str, Dict[str, str]]],
    all_apps_macros: Dict[str, Dict[str, Dict[str, str]]],
) -> None:
    """
    Add edges from savedsearches.conf lookup and macro references.

    For every saved search stanza:
    - ``| lookup X`` → edge to transforms.conf stanza X (lookup definition)
    - `` `macro_name` `` → edge to macros.conf stanza macro_name
    """
    for search_name, keys in savedsearches_stanzas.items():
        if search_name == "__lines__":
            continue
        search_string = keys.get("search", "")

        source_node = _get_or_create_node(
            graph, app_name, ENTITY_SAVEDSEARCH, search_name
        )

        # Lookup references
        for lookup_name in _extract_lookup_names(search_string):
            owner_app = app_name
            for candidate_app, t_stanzas in all_apps_transforms.items():
                if lookup_name in t_stanzas:
                    owner_app = candidate_app
                    break
            target_node = _get_or_create_node(
                graph, owner_app, ENTITY_LOOKUP, lookup_name
            )
            graph.add_edge(
                GraphEdge(
                    source_id=source_node.node_id,
                    target_id=target_node.node_id,
                    relationship=EDGE_LOOKUP_REFERENCE,
                    conf_file="savedsearches.conf",
                )
            )

        # Macro references
        for macro_name in _extract_macro_names(search_string):
            owner_app = app_name
            for candidate_app, m_stanzas in all_apps_macros.items():
                if macro_name in m_stanzas:
                    owner_app = candidate_app
                    break
            target_node = _get_or_create_node(
                graph, owner_app, ENTITY_MACRO, macro_name
            )
            graph.add_edge(
                GraphEdge(
                    source_id=source_node.node_id,
                    target_id=target_node.node_id,
                    relationship=EDGE_MACRO_USAGE,
                    conf_file="savedsearches.conf",
                )
            )


def _add_eventtype_tag_edges(
    graph: DependencyGraph,
    app_name: str,
    eventtypes_stanzas: Dict[str, Dict[str, str]],
    tags_stanzas: Dict[str, Dict[str, str]],
    all_apps_props: Dict[str, Dict[str, Dict[str, str]]],
) -> None:
    """
    Add edges from eventtypes.conf/tags.conf to props.conf sourcetype stanzas.

    tags.conf [eventtype=X] → eventtypes.conf [X]
    eventtypes.conf [X] search=sourcetype=Y → props.conf [Y]
    """
    for eventtype_name, eventtype_keys in eventtypes_stanzas.items():
        if eventtype_name == "__lines__":
            continue
        search_string = eventtype_keys.get("search", "")

        et_node = _get_or_create_node(
            graph, app_name, ENTITY_EVENTTYPE, eventtype_name
        )

        # tags.conf → eventtype edge
        tag_stanza_key = f"eventtype={eventtype_name}"
        if tag_stanza_key in tags_stanzas:
            tag_node = _get_or_create_node(
                graph, app_name, ENTITY_TAG_STANZA, tag_stanza_key
            )
            graph.add_edge(
                GraphEdge(
                    source_id=tag_node.node_id,
                    target_id=et_node.node_id,
                    relationship=EDGE_EVENTTYPE_TAGGED_BY,
                    conf_file="tags.conf",
                )
            )

        # eventtype → props stanza edge (via sourcetype)
        for sourcetype in _extract_sourcetypes_from_search(search_string):
            owner_app = app_name
            for candidate_app, p_stanzas in all_apps_props.items():
                if sourcetype in p_stanzas:
                    owner_app = candidate_app
                    break
            props_node = _get_or_create_node(
                graph, owner_app, ENTITY_PROPS_STANZA, sourcetype
            )
            graph.add_edge(
                GraphEdge(
                    source_id=et_node.node_id,
                    target_id=props_node.node_id,
                    relationship=EDGE_SOURCETYPE_FEEDS,
                    conf_file="eventtypes.conf",
                )
            )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_dependency_graph(inventory: ClusterInventory) -> DependencyGraph:
    """
    Build a cross-app dependency graph from a ClusterInventory.

    Iterates over all apps in the cluster, extracting conf-level dependencies
    as directed graph edges.

    Args:
        inventory: ClusterInventory containing all parsed app baselines.

    Returns:
        DependencyGraph with nodes and edges populated.
    """
    graph = DependencyGraph()

    # Pre-index conf stanzas per app for cross-app lookups
    all_transforms: Dict[str, Dict[str, Dict[str, str]]] = {}
    all_macros: Dict[str, Dict[str, Dict[str, str]]] = {}
    all_props: Dict[str, Dict[str, Dict[str, str]]] = {}

    for app_name, baseline in inventory.apps.items():
        all_transforms[app_name] = {
            **baseline.get_default_stanzas("transforms"),
            **baseline.get_local_stanzas("transforms"),
        }
        all_macros[app_name] = {
            **baseline.get_default_stanzas("macros"),
            **baseline.get_local_stanzas("macros"),
        }
        all_props[app_name] = {
            **baseline.get_default_stanzas("props"),
            **baseline.get_local_stanzas("props"),
        }

    for app_name, baseline in inventory.apps.items():
        props = all_props[app_name]
        transforms = all_transforms[app_name]
        savedsearches = {
            **baseline.get_default_stanzas("savedsearches"),
            **baseline.get_local_stanzas("savedsearches"),
        }
        eventtypes = {
            **baseline.get_default_stanzas("eventtypes"),
            **baseline.get_local_stanzas("eventtypes"),
        }
        tags = {
            **baseline.get_default_stanzas("tags"),
            **baseline.get_local_stanzas("tags"),
        }

        _add_props_transforms_edges(
            graph, app_name, props, transforms, all_transforms
        )
        _add_savedsearches_edges(
            graph, app_name, savedsearches, all_transforms, all_macros
        )
        _add_eventtype_tag_edges(
            graph, app_name, eventtypes, tags, all_props
        )

    logger.info(
        "[DEP] Built dependency graph: %d nodes, %d edges for cluster %s",
        len(graph.nodes),
        len(graph.edges),
        inventory.cluster_name,
    )
    return graph


def trace_impact(
    graph: DependencyGraph,
    changed_entity_ids: List[str],
) -> List[ImpactPath]:
    """
    BFS from changed entities to find all downstream consumers.

    Traverses the reverse_adjacency (consumer → provider) in reverse,
    i.e. from changed providers to all upstream consumers.

    Args:
        graph: A DependencyGraph built by build_dependency_graph().
        changed_entity_ids: List of node_ids representing changed entities.

    Returns:
        List of ImpactPath objects, one per reachable downstream consumer.
        The changed entity itself is not included.
    """
    impact_paths: List[ImpactPath] = []
    visited_globally: Set[str] = set()

    for start_id in changed_entity_ids:
        if start_id not in graph.nodes:
            logger.debug("[DEP] Changed entity not in graph: %s", start_id)
            continue

        # BFS: find all nodes that depend on start_id (reverse direction)
        # We walk reverse_adjacency: consumers point to start_id
        queue: List[Tuple[str, List[str], List[str]]] = []
        # Seed queue with direct consumers of start_id
        for consumer_id in graph.reverse_adjacency.get(start_id, set()):
            queue.append((consumer_id, [start_id, consumer_id], []))

        visited: Set[str] = {start_id}

        while queue:
            current_id, path, rel_chain = queue.pop(0)

            if current_id in visited:
                continue
            visited.add(current_id)

            # Find the edge label for this hop
            edge_label = _find_edge_relationship(graph, path[-2], current_id)
            full_rel_chain = rel_chain + [edge_label]

            impact_paths.append(
                ImpactPath(
                    changed_entity_id=start_id,
                    impacted_entity_id=current_id,
                    path=list(path),
                    hop_count=len(path) - 1,
                    relationship_chain=full_rel_chain,
                )
            )
            visited_globally.add(current_id)

            # Continue BFS — consumers of current_id are also impacted
            for next_consumer_id in graph.reverse_adjacency.get(current_id, set()):
                if next_consumer_id not in visited:
                    queue.append((
                        next_consumer_id,
                        path + [next_consumer_id],
                        full_rel_chain,
                    ))

    return impact_paths


def _find_edge_relationship(
    graph: DependencyGraph, source_id: str, target_id: str
) -> str:
    """
    Find the relationship label on the edge from source_id to target_id.

    Args:
        graph: The dependency graph.
        source_id: Source node id.
        target_id: Target node id.

    Returns:
        Relationship string, or "unknown" if no matching edge is found.
    """
    for edge in graph.edges:
        if edge.source_id == source_id and edge.target_id == target_id:
            return edge.relationship
    return "unknown"


def get_dependency_summary(graph: DependencyGraph) -> Dict[str, object]:
    """
    Return a compact summary of the dependency graph.

    Args:
        graph: A DependencyGraph.

    Returns:
        Dict with node_count, edge_count, entity_type_counts,
        most_depended_upon (top 10 nodes by in-degree).
    """
    entity_type_counts: Dict[str, int] = {}
    for node in graph.nodes.values():
        entity_type_counts[node.entity_type] = (
            entity_type_counts.get(node.entity_type, 0) + 1
        )

    # Compute in-degree per node (how many others depend on it)
    in_degree: Dict[str, int] = {node_id: 0 for node_id in graph.nodes}
    for edge in graph.edges:
        in_degree[edge.target_id] = in_degree.get(edge.target_id, 0) + 1

    most_depended = sorted(in_degree.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "node_count": len(graph.nodes),
        "edge_count": len(graph.edges),
        "entity_type_counts": entity_type_counts,
        "most_depended_upon": [
            {"node_id": node_id, "in_degree": degree}
            for node_id, degree in most_depended
            if degree > 0
        ],
    }
