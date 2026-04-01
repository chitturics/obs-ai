"""
Knowledge Graph Entity Extractors and Build Orchestrator.

Extracted from knowledge_graph.py. Contains:
- Entity extraction from SPL docs, RAG context, Splunk rules, spec files, org config
- SPLQueryAnalyzer: decomposes SPL queries into constituent entities
- Saved search and macro extractors
- Config relationship builder
- build_knowledge_graph: main build orchestrator

Implementation is split for maintainability:
    kg_extractors_basic.py  — Basic extractors (SPL docs, RAG context, rules, specs, org config) + SPLQueryAnalyzer
    kg_extractors_conf.py   — Conf-file extractors (savedsearches, macros, indexes, props/transforms)
All extracted functions are re-exported here for backward-compatible imports.
"""

from __future__ import annotations

import logging
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List


from chat_app.knowledge_graph import (
    KGEntity,
    KGRelationship,
    SplunkKnowledgeGraph,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Re-exports from sub-modules (backward-compatible imports)
# ---------------------------------------------------------------------------

from chat_app.kg_extractors_basic import (  # noqa: F401
    SPLQueryAnalyzer,
    extract_entities_from_org_config,
    extract_entities_from_rag_context,
    extract_entities_from_spec_file,
    extract_entities_from_spl_doc,
    extract_entities_from_splunk_rules,
)
from chat_app.kg_extractors_conf import (  # noqa: F401
    extract_entities_from_indexes_conf,
    extract_entities_from_macros,
    extract_entities_from_props_transforms,
    extract_entities_from_savedsearches,
)

# ---------------------------------------------------------------------------
# Operator constants and helpers
# ---------------------------------------------------------------------------

# Common operators
_OPERATORS = [
    ("AND", "Logical AND"), ("OR", "Logical OR"), ("NOT", "Logical NOT"),
    ("=", "Equals"), ("!=", "Not equals"), (">", "Greater than"),
    ("<", "Less than"), (">=", "Greater or equal"), ("<=", "Less or equal"),
    ("LIKE", "Pattern match"), ("IN", "Set membership"),
]


def _add_operators(kg: SplunkKnowledgeGraph) -> None:
    """Add common operators as entities."""
    for op_name, op_desc in _OPERATORS:
        op_id = f"op:{op_name}"
        kg.add_entity(KGEntity(
            id=op_id, entity_type="Operator", name=op_name,
            description=op_desc,
        ))


# ---------------------------------------------------------------------------
# Command alias helpers
# ---------------------------------------------------------------------------

# Well-known SPL command aliases
_COMMAND_ALIASES: Dict[str, str] = {
    "bin": "bucket",
    "readmeta": "metadata",
    "rtorder": "rtorder",
    "scrub": "anonymize",
    "sichart": "chart",
    "sirare": "rare",
    "sistats": "stats",
    "sitimechart": "timechart",
    "sitop": "top",
    "untable": "xyseries",
}


def _add_command_aliases(kg: SplunkKnowledgeGraph) -> None:
    """Add alias_of relationships between SPL command aliases."""
    for alias, canonical in _COMMAND_ALIASES.items():
        alias_id = f"cmd:{alias}"
        canon_id = f"cmd:{canonical}"
        # Ensure both entities exist
        if not kg.get_entity(alias_id):
            kg.add_entity(KGEntity(
                id=alias_id, entity_type="Command", name=alias,
                description=f"Alias for the {canonical} command",
            ))
        if not kg.get_entity(canon_id):
            kg.add_entity(KGEntity(
                id=canon_id, entity_type="Command", name=canonical,
            ))
        kg.add_relationship(KGRelationship(
            source_id=alias_id, target_id=canon_id,
            rel_type="alternative_to",
            metadata={"alias": True},
        ))


# ---------------------------------------------------------------------------
# Build orchestrator
# ---------------------------------------------------------------------------

def _ingest_org_conf_files(kg: SplunkKnowledgeGraph, org_repo: str) -> None:
    """Scan org repo for .conf files and extract entities from known conf types."""
    repo_path = Path(org_repo)
    if not repo_path.exists():
        return

    conf_handlers = {
        "savedsearches.conf": extract_entities_from_savedsearches,
        "macros.conf": extract_entities_from_macros,
        "indexes.conf": extract_entities_from_indexes_conf,
    }

    # Scan for known conf files
    for conf_file in repo_path.rglob("*.conf"):
        handler = conf_handlers.get(conf_file.name)
        if handler:
            try:
                ents, rels = handler(conf_file)
                for e in ents:
                    kg.add_entity(e)
                for r in rels:
                    kg.add_relationship(r)
                if ents:
                    logger.info("[KG] Extracted %d entities from %s", len(ents), conf_file)
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                logger.debug("[KG] Failed to parse %s: %s", conf_file, exc)

    # Props + transforms (paired extraction)
    props_files = list(repo_path.rglob("props.conf"))
    transforms_files = list(repo_path.rglob("transforms.conf"))

    # Match by parent directory when possible
    props_by_dir = {f.parent: f for f in props_files}
    transforms_by_dir = {f.parent: f for f in transforms_files}

    all_dirs = set(props_by_dir.keys()) | set(transforms_by_dir.keys())
    for d in all_dirs:
        try:
            ents, rels = extract_entities_from_props_transforms(
                props_path=props_by_dir.get(d),
                transforms_path=transforms_by_dir.get(d),
            )
            for e in ents:
                kg.add_entity(e)
            for r in rels:
                kg.add_relationship(r)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.debug("[KG] Failed to parse props/transforms in %s: %s", d, exc)


# ---------------------------------------------------------------------------
# Config relationship builder — cross-links ConfigStanza nodes
# ---------------------------------------------------------------------------

# Map conf file base names to the SPL commands that read/use them
_CONF_TO_COMMANDS: Dict[str, List[str]] = {
    "props.conf": ["props"],
    "transforms.conf": ["transforms"],
    "inputs.conf": ["inputs"],
    "outputs.conf": ["outputs"],
    "authorize.conf": ["authorize"],
    "indexes.conf": ["indexes"],
    "savedsearches.conf": ["savedsearch"],
    "macros.conf": ["macro"],
    "fields.conf": ["fields"],
    "limits.conf": ["limits"],
    "commands.conf": ["commands"],
    "alert_actions.conf": ["sendalert", "sendemail"],
    "eventtypes.conf": ["eventstats", "typeahead", "typer"],
    "tags.conf": ["tags"],
    "collections.conf": ["collect", "mcollect"],
    "distsearch.conf": ["search"],
    "server.conf": ["rest"],
    "web.conf": ["rest"],
    "authentication.conf": ["rest"],
    "app.conf": ["rest"],
    "deploymentclient.conf": ["rest"],
    "serverclass.conf": ["rest"],
    "times.conf": ["timechart", "timewrap"],
    "multikv.conf": ["multikv"],
    "transactiontypes.conf": ["transaction"],
    "workflow_actions.conf": ["search"],
    "viewstates.conf": ["search"],
    "lookup-editor.conf": ["lookup", "inputlookup", "outputlookup"],
    "data.ui-views.conf": ["search"],
}

# Conf files that commonly reference indexes
_INDEX_REFERENCING_CONFS = {
    "inputs.conf", "indexes.conf", "props.conf", "transforms.conf",
    "savedsearches.conf",
}


def _build_config_relationships(kg: SplunkKnowledgeGraph) -> int:
    """Build cross-entity relationships for ConfigStanza nodes.

    Creates four relationship families:
    1. ConfigStanza → Command (configures) and Command → ConfigStanza (reads_config)
    2. ConfigStanza → ConfigStanza (related_stanza) for same conf file
    3. ConfigStanza → Index (targets_index) when stanza references an index
    4. Field → ConfigStanza (configured_by) reverse link from defines

    Returns the number of new relationships created.
    """
    added = 0

    # Collect all ConfigStanza entities grouped by conf file
    stanzas_by_conf: Dict[str, List[str]] = defaultdict(list)  # conf_name -> [entity_id]
    stanza_entities: Dict[str, KGEntity] = {}

    for eid in kg._type_index.get("ConfigStanza", set()):
        entity = kg._entity_index.get(eid)
        if not entity:
            continue
        stanza_entities[eid] = entity
        # Extract conf file from metadata or entity name
        conf_file = entity.metadata.get("conf_file", "")
        if not conf_file and "/" in entity.name:
            conf_file = entity.name.split("/")[0]
        if conf_file:
            stanzas_by_conf[conf_file].append(eid)

    # Collect all Command entity IDs for fast lookup
    cmd_ids: Dict[str, str] = {}  # cmd_name -> entity_id
    for eid in kg._type_index.get("Command", set()):
        entity = kg._entity_index.get(eid)
        if entity:
            cmd_ids[entity.name.lower()] = eid

    # Collect all Index entity IDs for fast lookup
    idx_ids: Dict[str, str] = {}  # idx_name -> entity_id
    for eid in kg._type_index.get("Index", set()):
        entity = kg._entity_index.get(eid)
        if entity:
            idx_ids[entity.name.lower()] = eid

    # --- 1. ConfigStanza <-> Command relationships ---
    for conf_name, stanza_eids in stanzas_by_conf.items():
        commands = _CONF_TO_COMMANDS.get(conf_name, [])
        for cmd_name in commands:
            cmd_eid = cmd_ids.get(cmd_name)
            if not cmd_eid:
                # Create a lightweight Command entity for conf-management commands
                # (e.g., "props", "inputs") so the graph stays navigable
                cmd_eid = f"cmd:{cmd_name}"
                kg.add_entity(KGEntity(
                    id=cmd_eid, entity_type="Command", name=cmd_name,
                    description=f"Splunk configuration context: {conf_name}",
                    metadata={"conf_based": True},
                ))
                cmd_ids[cmd_name] = cmd_eid
            for stanza_eid in stanza_eids:
                # ConfigStanza → Command: configures
                kg.add_relationship(KGRelationship(
                    source_id=stanza_eid, target_id=cmd_eid,
                    rel_type="configures", weight=0.8,
                ))
                # Command → ConfigStanza: reads_config
                kg.add_relationship(KGRelationship(
                    source_id=cmd_eid, target_id=stanza_eid,
                    rel_type="reads_config", weight=0.8,
                ))
                added += 2

    # --- 2. ConfigStanza → ConfigStanza (related_stanza) within same conf ---
    # For conf files with a manageable number of stanzas, link them
    for conf_name, stanza_eids in stanzas_by_conf.items():
        if len(stanza_eids) < 2:
            continue
        # Group stanzas by namespace prefix for smarter linking
        # e.g., "capability::list_inputs" shares namespace "capability" with "capability::edit_inputs"
        namespace_groups: Dict[str, List[str]] = defaultdict(list)
        ungrouped: List[str] = []

        for eid in stanza_eids:
            entity = stanza_entities.get(eid)
            if not entity:
                continue
            # Extract stanza name (after the conf_name/ prefix)
            stanza_name = entity.name.split("/", 1)[-1] if "/" in entity.name else entity.name
            # Extract namespace: text before :: or before the first special char
            ns_match = re.match(r'^([a-zA-Z_]+)::', stanza_name)
            if ns_match:
                namespace_groups[ns_match.group(1)].append(eid)
            else:
                ungrouped.append(eid)

        # Link stanzas within same namespace
        for ns, ns_eids in namespace_groups.items():
            if len(ns_eids) < 2:
                continue
            # For large groups, only link neighbors (limit fan-out)
            max_links = min(len(ns_eids), 50)
            for i in range(max_links):
                for j in range(i + 1, min(i + 4, max_links)):
                    kg.add_relationship(KGRelationship(
                        source_id=ns_eids[i], target_id=ns_eids[j],
                        rel_type="related_stanza", weight=0.6,
                        metadata={"namespace": ns, "conf": conf_name},
                    ))
                    added += 1

        # For ungrouped stanzas, link them to each other if few enough
        # and also cross-link to first stanza of each namespace group
        if len(ungrouped) >= 2 and len(ungrouped) <= 30:
            for i in range(len(ungrouped)):
                for j in range(i + 1, min(i + 3, len(ungrouped))):
                    kg.add_relationship(KGRelationship(
                        source_id=ungrouped[i], target_id=ungrouped[j],
                        rel_type="related_stanza", weight=0.4,
                        metadata={"conf": conf_name},
                    ))
                    added += 1

    # --- 3. ConfigStanza → Index (targets_index) ---
    # Stanzas in index-referencing confs that mention an index name
    for conf_name in _INDEX_REFERENCING_CONFS:
        for stanza_eid in stanzas_by_conf.get(conf_name, []):
            entity = stanza_entities.get(stanza_eid)
            if not entity:
                continue
            stanza_name = entity.name.split("/", 1)[-1] if "/" in entity.name else entity.name
            desc = (entity.description or "").lower()
            # Check if stanza name or description references a known index
            for idx_name, idx_eid in idx_ids.items():
                if idx_name in stanza_name.lower() or idx_name in desc:
                    kg.add_relationship(KGRelationship(
                        source_id=stanza_eid, target_id=idx_eid,
                        rel_type="targets_index", weight=0.7,
                    ))
                    added += 1

    # For indexes.conf stanzas specifically, each stanza IS an index definition
    for stanza_eid in stanzas_by_conf.get("indexes.conf", []):
        entity = stanza_entities.get(stanza_eid)
        if not entity:
            continue
        stanza_name = entity.name.split("/", 1)[-1] if "/" in entity.name else entity.name
        # The stanza name itself is the index name
        matched_idx_eid = idx_ids.get(stanza_name.lower())
        if matched_idx_eid and matched_idx_eid != stanza_eid:
            kg.add_relationship(KGRelationship(
                source_id=stanza_eid, target_id=matched_idx_eid,
                rel_type="configures", weight=1.0,
            ))
            added += 1

    # --- 4. Field → ConfigStanza (configured_by) reverse of defines ---
    # For each "defines" relationship (ConfigStanza → Field), add the reverse
    for source_id, target_id, data in list(kg._graph.edges(data=True)):
        if data.get("rel_type") == "defines":
            # target is a Field, source is a ConfigStanza
            kg.add_relationship(KGRelationship(
                source_id=target_id, target_id=source_id,
                rel_type="configured_by", weight=0.5,
            ))
            added += 1

    logger.info("[KG] Config relationship builder added %d relationships", added)
    return added


def build_knowledge_graph(
    spl_docs_dir: str = "/app/spl_docs",
    metadata_dir: str = "/app/metadata",
    spec_dir: str = "/app/ingest_specs",
    cache_path: str = "/app/data/knowledge_graph.json",
    force_rebuild: bool = False,
) -> SplunkKnowledgeGraph:
    """Build or load the knowledge graph.

    1. If cache exists and force_rebuild is False, load from JSON
    2. Otherwise, extract entities from all sources and build graph
    3. Save to JSON for next startup
    """
    kg = SplunkKnowledgeGraph()

    # Try loading from cache (with staleness check)
    if not force_rebuild and cache_path:
        cache_file = Path(cache_path)
        if cache_file.exists():
            # Check if any source directory has newer files than the cache
            cache_mtime = cache_file.stat().st_mtime
            source_dirs = [Path(spl_docs_dir), Path(metadata_dir), Path(spec_dir)]
            stale = False
            for src_dir in source_dirs:
                if src_dir.exists():
                    for f in src_dir.rglob("*"):
                        if f.is_file() and f.stat().st_mtime > cache_mtime:
                            logger.info("[KG] Cache stale: %s newer than cache", f.name)
                            stale = True
                            break
                if stale:
                    break

            if not stale and kg.load_from_json(cache_path):
                return kg
            elif stale:
                logger.info("[KG] Rebuilding due to stale cache")

    logger.info("[KG] Building knowledge graph from source files...")
    start = time.time()

    # Extract from SPL docs
    spl_dir = Path(spl_docs_dir)
    if spl_dir.exists():
        doc_files = sorted(spl_dir.glob("spl_cmd_*.md"))
        for doc_path in doc_files:
            try:
                ents, rels = extract_entities_from_spl_doc(doc_path)
                for e in ents:
                    kg.add_entity(e)
                for r in rels:
                    kg.add_relationship(r)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                logger.debug("[KG] Failed to parse %s: %s", doc_path.name, exc)

    # Extract from rag_context.md
    rag_ctx = Path(metadata_dir) / "rag_context.md"
    if rag_ctx.exists():
        try:
            ents, rels = extract_entities_from_rag_context(rag_ctx)
            for e in ents:
                kg.add_entity(e)
            for r in rels:
                kg.add_relationship(r)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.debug("[KG] Failed to parse rag_context.md: %s", exc)

    # Extract from splunk_rules.md
    rules_path = Path(metadata_dir) / "splunk_rules.md"
    if rules_path.exists():
        try:
            ents, rels = extract_entities_from_splunk_rules(rules_path)
            for e in ents:
                kg.add_entity(e)
            for r in rels:
                kg.add_relationship(r)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            logger.debug("[KG] Failed to parse splunk_rules.md: %s", exc)

    # Extract from spec files (sample: first 20 for speed)
    spec_path = Path(spec_dir)
    if spec_path.exists():
        spec_files = sorted(spec_path.glob("*.spec"))
        for sf in spec_files:
            try:
                ents, rels = extract_entities_from_spec_file(sf)
                for e in ents:
                    kg.add_entity(e)
                for r in rels:
                    kg.add_relationship(r)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                logger.debug("[KG] Failed to parse %s: %s", sf.name, exc)

    # Extract from organization config
    try:
        from chat_app.settings import _load_yaml_config
        cfg = _load_yaml_config()
        ents, rels = extract_entities_from_org_config(cfg)
        for e in ents:
            kg.add_entity(e)
        for r in rels:
            kg.add_relationship(r)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[KG] Failed to parse org config: %s", exc)

    # Extract from org repo: saved searches, macros, indexes.conf, props/transforms
    try:
        from chat_app.settings import get_settings
        org_repo: str = get_settings().paths.org_repo_root or "/app/shared/public/documents/repo"
    except Exception as _exc:  # broad catch — resilience against all failures
        org_repo = os.environ.get("ORG_REPO_ROOT", "/app/shared/public/documents/repo")

    _ingest_org_conf_files(kg, org_repo)

    # Add operators
    _add_operators(kg)

    # Add command aliases (bin→bucket, etc.)
    _add_command_aliases(kg)

    # Build cross-entity config relationships (density improvement)
    _build_config_relationships(kg)

    # Entity deduplication pass
    kg.deduplicate_entities()

    # Cross-reference with tool registry and skill catalog
    try:
        kg.add_tool_entities()
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug("[KG] Tool entity injection skipped: %s", exc)

    elapsed_ms = (time.time() - start) * 1000
    kg._build_timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    kg._build_time_ms = round(elapsed_ms, 1)

    stats = kg.get_stats()
    logger.info("[KG] Graph built in %.1fms: %d entities, %d relationships",
                elapsed_ms, stats["total_entities"], stats["total_relationships"])

    # Save to cache
    if cache_path:
        try:
            kg.save_to_json(cache_path)
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
            logger.warning("[KG] Failed to save graph cache: %s", exc)

    return kg
