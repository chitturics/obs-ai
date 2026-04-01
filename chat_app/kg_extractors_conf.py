"""
Conf-file KG entity extractors: savedsearches, macros, indexes, props/transforms.

Extracted from kg_builders.py for maintainability.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple


from chat_app.knowledge_graph import (
    KGEntity,
    KGRelationship,
)
from chat_app.kg_extractors_basic import SPLQueryAnalyzer

logger = logging.getLogger(__name__)

# Saved Search & Macro extractors (from .conf files in org repo)
# ---------------------------------------------------------------------------

def extract_entities_from_savedsearches(conf_path: Path) -> Tuple[List[KGEntity], List[KGRelationship]]:
    """Parse a savedsearches.conf and extract SavedSearch entities with full decomposition."""
    entities: List[KGEntity] = []
    relationships: List[KGRelationship] = []

    if not conf_path.exists():
        return entities, relationships

    text = conf_path.read_text(encoding="utf-8", errors="replace")

    # Parse stanzas
    current_stanza = None
    current_search = ""
    current_meta: Dict[str, str] = {}

    def _flush():
        nonlocal current_stanza, current_search, current_meta
        if current_stanza and current_stanza != "default" and current_search:
            search_name = current_stanza
            search_id = f"search:{search_name}"
            entities.append(KGEntity(
                id=search_id, entity_type="SavedSearch", name=search_name,
                description=current_search[:200],
                metadata={
                    "spl": current_search[:500],
                    "cron": current_meta.get("cron_schedule", ""),
                    "dispatch_earliest": current_meta.get("dispatch.earliest_time", ""),
                    "dispatch_latest": current_meta.get("dispatch.latest_time", ""),
                    "is_scheduled": current_meta.get("is_scheduled", "0") == "1",
                    "conf_path": str(conf_path),
                },
            ))

            # Analyze the SPL and create linked entities
            ents, rels = SPLQueryAnalyzer.to_entities_and_relationships(
                current_search, search_name,
            )
            # Skip the duplicate SavedSearch entity (already added above)
            for e in ents:
                if e.id != search_id:
                    entities.append(e)
            relationships.extend(rels)

        current_stanza = None
        current_search = ""
        current_meta = {}

    for line in text.split("\n"):
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue

        stanza_match = re.match(r'^\[([^\]]+)\]', line_stripped)
        if stanza_match:
            _flush()
            current_stanza = stanza_match.group(1).strip()
            continue

        if "=" in line_stripped and current_stanza:
            key, _, val = line_stripped.partition("=")
            key = key.strip()
            val = val.strip()
            if key == "search":
                current_search = val
            else:
                current_meta[key] = val

    _flush()  # Don't forget last stanza
    return entities, relationships


def extract_entities_from_macros(conf_path: Path) -> Tuple[List[KGEntity], List[KGRelationship]]:
    """Parse a macros.conf and extract Macro entities."""
    entities: List[KGEntity] = []
    relationships: List[KGRelationship] = []

    if not conf_path.exists():
        return entities, relationships

    text = conf_path.read_text(encoding="utf-8", errors="replace")

    current_stanza = None
    current_definition = ""
    current_args = ""

    def _flush():
        nonlocal current_stanza, current_definition, current_args
        if current_stanza and current_stanza != "default":
            macro_name = current_stanza.split("(")[0]  # Handle macro(arg1,arg2)
            macro_id = f"macro:{macro_name}"
            entities.append(KGEntity(
                id=macro_id, entity_type="Macro", name=macro_name,
                description=current_definition[:200],
                metadata={
                    "definition": current_definition[:500],
                    "args": current_args,
                    "conf_path": str(conf_path),
                },
            ))

            # Analyze macro body for entity references
            if current_definition:
                analysis = SPLQueryAnalyzer.analyze(current_definition)
                for idx in analysis["indexes"]:
                    idx_id = f"idx:{idx}"
                    entities.append(KGEntity(id=idx_id, entity_type="Index", name=idx))
                    relationships.append(KGRelationship(
                        source_id=macro_id, target_id=idx_id, rel_type="uses_index",
                    ))
                for st in analysis["sourcetypes"]:
                    st_id = f"st:{st}"
                    entities.append(KGEntity(id=st_id, entity_type="Sourcetype", name=st))
                    relationships.append(KGRelationship(
                        source_id=macro_id, target_id=st_id, rel_type="uses_sourcetype",
                    ))
                for fld in analysis["fields"]:
                    fld_id = f"field:{fld}"
                    entities.append(KGEntity(id=fld_id, entity_type="Field", name=fld))
                    relationships.append(KGRelationship(
                        source_id=macro_id, target_id=fld_id, rel_type="uses_field",
                    ))
                for cmd in analysis["commands"]:
                    cmd_id = f"cmd:{cmd}"
                    entities.append(KGEntity(id=cmd_id, entity_type="Command", name=cmd))
                    relationships.append(KGRelationship(
                        source_id=macro_id, target_id=cmd_id, rel_type="uses_command",
                    ))

        current_stanza = None
        current_definition = ""
        current_args = ""

    for line in text.split("\n"):
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue

        stanza_match = re.match(r'^\[([^\]]+)\]', line_stripped)
        if stanza_match:
            _flush()
            current_stanza = stanza_match.group(1).strip()
            continue

        if "=" in line_stripped and current_stanza:
            key, _, val = line_stripped.partition("=")
            key = key.strip()
            val = val.strip()
            if key == "definition":
                current_definition = val
            elif key == "args":
                current_args = val

    _flush()
    return entities, relationships


def extract_entities_from_indexes_conf(conf_path: Path) -> Tuple[List[KGEntity], List[KGRelationship]]:
    """Parse indexes.conf to extract Index entities with metadata."""
    entities: List[KGEntity] = []
    relationships: List[KGRelationship] = []

    if not conf_path.exists():
        return entities, relationships

    text = conf_path.read_text(encoding="utf-8", errors="replace")

    current_stanza = None
    current_meta: Dict[str, str] = {}

    def _flush():
        nonlocal current_stanza, current_meta
        if current_stanza and current_stanza not in ("default", "volume:"):
            idx_name = current_stanza
            idx_id = f"idx:{idx_name}"
            desc_parts = []
            if current_meta.get("homePath"):
                desc_parts.append(f"path={current_meta['homePath']}")
            if current_meta.get("frozenTimePeriodInSecs"):
                days = int(current_meta["frozenTimePeriodInSecs"]) // 86400
                desc_parts.append(f"retention={days}d")
            if current_meta.get("maxDataSizeMB"):
                desc_parts.append(f"maxSize={current_meta['maxDataSizeMB']}MB")
            entities.append(KGEntity(
                id=idx_id, entity_type="Index", name=idx_name,
                description=", ".join(desc_parts) if desc_parts else f"Index: {idx_name}",
                metadata={k: v for k, v in current_meta.items()
                          if k in ("homePath", "coldPath", "thawedPath",
                                   "frozenTimePeriodInSecs", "maxDataSizeMB",
                                   "maxTotalDataSizeMB", "datatype")},
            ))
        current_stanza = None
        current_meta = {}

    for line in text.split("\n"):
        line_stripped = line.strip()
        if not line_stripped or line_stripped.startswith("#"):
            continue
        stanza_match = re.match(r'^\[([^\]]+)\]', line_stripped)
        if stanza_match:
            _flush()
            current_stanza = stanza_match.group(1).strip()
            continue
        if "=" in line_stripped and current_stanza:
            key, _, val = line_stripped.partition("=")
            current_meta[key.strip()] = val.strip()

    _flush()
    return entities, relationships


def extract_entities_from_props_transforms(
    props_path: Optional[Path] = None,
    transforms_path: Optional[Path] = None,
) -> Tuple[List[KGEntity], List[KGRelationship]]:
    """
    Parse props.conf and transforms.conf for sourcetypes, sources,
    index-time field extractions, and field transforms.
    """
    entities: List[KGEntity] = []
    relationships: List[KGRelationship] = []

    # Props.conf — sourcetypes/sources and their field extractions
    if props_path and props_path.exists():
        text = props_path.read_text(encoding="utf-8", errors="replace")
        current_stanza = None
        current_stanza_id = None

        for line in text.split("\n"):
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith("#"):
                continue

            stanza_match = re.match(r'^\[([^\]]+)\]', line_stripped)
            if stanza_match:
                current_stanza = stanza_match.group(1).strip()
                if current_stanza.startswith("source::"):
                    src_name = current_stanza[len("source::"):]
                    current_stanza_id = f"source:{src_name}"
                    entities.append(KGEntity(
                        id=current_stanza_id, entity_type="Source", name=src_name,
                        description=f"Source: {src_name}",
                    ))
                elif current_stanza.startswith("host::"):
                    current_stanza_id = None
                elif current_stanza not in ("default",):
                    # Assume sourcetype stanza
                    current_stanza_id = f"st:{current_stanza}"
                    entities.append(KGEntity(
                        id=current_stanza_id, entity_type="Sourcetype",
                        name=current_stanza,
                        description=f"Sourcetype: {current_stanza}",
                    ))
                continue

            if current_stanza_id and "=" in line_stripped:
                key, _, val = line_stripped.partition("=")
                key = key.strip()
                val = val.strip()

                # EXTRACT- and REPORT- define field extractions
                if key.startswith(("EXTRACT-", "REPORT-")):
                    # Extract field names from regex groups
                    for field_name in re.findall(r'\?P<(\w+)>', val):
                        fld_id = f"itfield:{field_name}"
                        entities.append(KGEntity(
                            id=fld_id, entity_type="IndexTimeField",
                            name=field_name,
                            description=f"Extracted field from {current_stanza}",
                        ))
                        relationships.append(KGRelationship(
                            source_id=current_stanza_id, target_id=fld_id,
                            rel_type="extracts_field",
                        ))

                # TRANSFORMS reference
                if key.startswith("TRANSFORMS-") or key.startswith("REPORT-"):
                    for transform_name in re.split(r'[,\s]+', val):
                        transform_name = transform_name.strip()
                        if transform_name:
                            relationships.append(KGRelationship(
                                source_id=current_stanza_id,
                                target_id=f"transform:{transform_name}",
                                rel_type="references",
                            ))

    # Transforms.conf — field transforms
    if transforms_path and transforms_path.exists():
        text = transforms_path.read_text(encoding="utf-8", errors="replace")
        current_stanza = None

        for line in text.split("\n"):
            line_stripped = line.strip()
            if not line_stripped or line_stripped.startswith("#"):
                continue

            stanza_match = re.match(r'^\[([^\]]+)\]', line_stripped)
            if stanza_match:
                current_stanza = stanza_match.group(1).strip()
                if current_stanza != "default":
                    entities.append(KGEntity(
                        id=f"transform:{current_stanza}",
                        entity_type="ConfigStanza",
                        name=f"transforms/{current_stanza}",
                        description=f"Field transform: {current_stanza}",
                    ))
                continue

            if current_stanza and "=" in line_stripped:
                key, _, val = line_stripped.partition("=")
                key = key.strip()
                if key == "REGEX":
                    for field_name in re.findall(r'\?P<(\w+)>', val):
                        fld_id = f"itfield:{field_name}"
                        entities.append(KGEntity(
                            id=fld_id, entity_type="IndexTimeField",
                            name=field_name,
                        ))
                        relationships.append(KGRelationship(
                            source_id=f"transform:{current_stanza}",
                            target_id=fld_id,
                            rel_type="extracts_field",
                        ))
                elif key == "LOOKUP-":
                    lk_name = val.split()[0] if val else ""
                    if lk_name:
                        relationships.append(KGRelationship(
                            source_id=f"transform:{current_stanza}",
                            target_id=f"lookup:{lk_name}",
                            rel_type="uses_lookup",
                        ))

    return entities, relationships


# Common operators
_OPERATORS = [
    ("AND", "Logical AND"), ("OR", "Logical OR"), ("NOT", "Logical NOT"),
    ("=", "Equals"), ("!=", "Not equals"), (">", "Greater than"),
    ("<", "Less than"), (">=", "Greater or equal"), ("<=", "Less or equal"),
    ("LIKE", "Pattern match"), ("IN", "Set membership"),
]

