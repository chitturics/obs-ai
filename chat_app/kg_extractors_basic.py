"""
Basic KG entity extractors: SPL docs, RAG context, Splunk rules, spec files, org config.
Also contains SPLQueryAnalyzer.

Extracted from kg_builders.py for maintainability.
"""
from __future__ import annotations

import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml

from chat_app.knowledge_graph import (
    KNOWN_COMMANDS,
    KNOWN_FUNCTIONS,
    KGEntity,
    KGRelationship,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Markdown helper utilities (used by SPL doc and spec parsers)
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> Dict[str, str]:
    """Parse YAML frontmatter from markdown text."""
    match = re.match(r'^---\s*\n(.*?)\n---', text, re.DOTALL)
    if not match:
        return {}
    try:
        return yaml.safe_load(match.group(1)) or {}
    except Exception as _exc:  # broad catch — resilience against all failures
        return {}


def _strip_frontmatter(text: str) -> str:
    """Remove YAML frontmatter from markdown text."""
    match = re.match(r'^---\s*\n.*?\n---\s*\n', text, re.DOTALL)
    if match:
        return text[match.end():]
    return text


def _first_paragraph(text: str) -> str:
    """Extract first non-empty paragraph from markdown.

    Skips headings, blank lines, and YAML artifacts. Returns up to 200 chars.
    """
    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            continue
        # Skip markdown formatting artifacts
        if stripped in ("---", "```", "```spl"):
            continue
        # Must have at least a few real words (not just punctuation)
        if len(stripped) > 10:
            return stripped[:200]
    return ""


# ---------------------------------------------------------------------------

def extract_entities_from_spl_doc(doc_path: Path) -> Tuple[List[KGEntity], List[KGRelationship]]:
    """Parse a single spl_docs/spl_cmd_*.md file to extract entities and relationships."""
    entities: List[KGEntity] = []
    relationships: List[KGRelationship] = []

    if not doc_path.exists():
        return entities, relationships

    text = doc_path.read_text(encoding="utf-8", errors="replace")

    # Parse YAML frontmatter
    fm = _parse_frontmatter(text)
    cmd_name = fm.get("command", "").strip()
    if not cmd_name:
        return entities, relationships

    cmd_id = f"cmd:{cmd_name}"

    # Extract first paragraph as description
    body = _strip_frontmatter(text)
    desc = _first_paragraph(body)

    entities.append(KGEntity(
        id=cmd_id,
        entity_type="Command",
        name=cmd_name,
        description=desc,
        metadata={
            "source_url": fm.get("source_url", ""),
            "doc_path": str(doc_path.name),
        },
    ))

    # Extract function references (word followed by parentheses in text)
    func_pattern = re.compile(r'\b(' + '|'.join(re.escape(f) for f in KNOWN_FUNCTIONS) + r')\s*\(', re.IGNORECASE)
    found_functions = set()
    for m in func_pattern.finditer(body):
        fn_name = m.group(1).lower()
        found_functions.add(fn_name)

    for fn_name in found_functions:
        fn_id = f"fn:{fn_name}"
        entities.append(KGEntity(
            id=fn_id, entity_type="Function", name=fn_name,
            description=f"SPL function {fn_name}()",
        ))
        relationships.append(KGRelationship(
            source_id=cmd_id, target_id=fn_id,
            rel_type="uses_functions",
        ))

    # Extract pipes_to from SPL code examples
    spl_blocks = re.findall(r'```(?:spl)?\s*\n(.*?)\n```', body, re.DOTALL)
    # Also look for inline pipe patterns: | cmd1 ... | cmd2
    pipe_pattern = re.compile(r'\|\s*([a-z][a-z0-9_]*)', re.IGNORECASE)
    pipe_counts: Dict[tuple, int] = defaultdict(int)

    for block in spl_blocks:
        cmds_in_block = pipe_pattern.findall(block)
        for i in range(len(cmds_in_block) - 1):
            c1 = cmds_in_block[i].lower()
            c2 = cmds_in_block[i + 1].lower()
            if c1 in KNOWN_COMMANDS and c2 in KNOWN_COMMANDS and c1 != c2:
                pipe_counts[(c1, c2)] += 1

    # Also extract from prose (e.g., "The search uses | stats ... | sort")
    for line in body.split("\n"):
        cmds_in_line = pipe_pattern.findall(line)
        if len(cmds_in_line) >= 2:
            for i in range(len(cmds_in_line) - 1):
                c1 = cmds_in_line[i].lower()
                c2 = cmds_in_line[i + 1].lower()
                if c1 in KNOWN_COMMANDS and c2 in KNOWN_COMMANDS and c1 != c2:
                    pipe_counts[(c1, c2)] += 1

    for (c1, c2), count in pipe_counts.items():
        src_id = f"cmd:{c1}"
        tgt_id = f"cmd:{c2}"
        entities.append(KGEntity(id=tgt_id, entity_type="Command", name=c2))
        relationships.append(KGRelationship(
            source_id=src_id, target_id=tgt_id,
            rel_type="pipes_to",
            weight=min(count, 5),
        ))

    # Extract arguments from "Required arguments" / "Optional arguments" sections
    arg_section = re.findall(
        r'(?:Required|Optional)\s+arguments?\s*\n(.*?)(?=\n###|\n##|\Z)',
        body, re.DOTALL | re.IGNORECASE,
    )
    for section_text in arg_section:
        # Look for argument names as bold or code-formatted
        arg_names = re.findall(r'(?:\*\*|`)([a-z_][a-z0-9_]*)(?:\*\*|`)', section_text, re.IGNORECASE)
        for arg_name in arg_names:
            arg_lower = arg_name.lower()
            if arg_lower in KNOWN_COMMANDS or arg_lower in KNOWN_FUNCTIONS:
                continue
            if len(arg_lower) < 2:
                continue
            arg_id = f"arg:{cmd_name}:{arg_lower}"
            entities.append(KGEntity(
                id=arg_id, entity_type="Argument", name=arg_lower,
                description=f"Argument for {cmd_name} command",
            ))
            relationships.append(KGRelationship(
                source_id=cmd_id, target_id=arg_id,
                rel_type="has_arguments",
            ))

    # Extract "See also" references
    see_also_match = re.search(r'### See also\s*\n(.*?)(?=\n###|\n##|\Z)', body, re.DOTALL)
    if see_also_match:
        see_text = see_also_match.group(1)
        for ref_cmd in re.findall(r'\b([a-z][a-z0-9_]*)\b', see_text):
            ref_lower = ref_cmd.lower()
            if ref_lower in KNOWN_COMMANDS and ref_lower != cmd_name:
                ref_id = f"cmd:{ref_lower}"
                entities.append(KGEntity(id=ref_id, entity_type="Command", name=ref_lower))
                relationships.append(KGRelationship(
                    source_id=cmd_id, target_id=ref_id,
                    rel_type="compatible_with",
                ))

    return entities, relationships


def extract_entities_from_rag_context(md_path: Path) -> Tuple[List[KGEntity], List[KGRelationship]]:
    """Parse metadata/rag_context.md for indexes, fields, lookups."""
    entities: List[KGEntity] = []
    relationships: List[KGRelationship] = []

    if not md_path.exists():
        return entities, relationships

    text = md_path.read_text(encoding="utf-8", errors="replace")

    # Extract indexes from "Core Indexes" section
    idx_section = re.search(r'## 1\.\s*Core Indexes\s*\n(.*?)(?=\n##|\Z)', text, re.DOTALL)
    if idx_section:
        for m in re.finditer(r'-\s*`([^`]+)`\s*:\s*(.*)', idx_section.group(1)):
            idx_name = m.group(1).strip()
            idx_desc = m.group(2).strip()
            idx_id = f"idx:{idx_name}"
            entities.append(KGEntity(
                id=idx_id, entity_type="Index", name=idx_name,
                description=idx_desc,
            ))

    # Extract fields from "Important Fields" section
    field_section = re.search(r'## 2\.\s*Important Fields\s*\n(.*?)(?=\n##|\Z)', text, re.DOTALL)
    if field_section:
        for m in re.finditer(r'-\s*`([^`]+)`\s*:\s*(.*)', field_section.group(1)):
            field_name = m.group(1).strip()
            field_desc = m.group(2).strip()
            field_id = f"field:{field_name}"
            entities.append(KGEntity(
                id=field_id, entity_type="Field", name=field_name,
                description=field_desc,
            ))

    # Extract CIM fields mentioned in the fields section
    cim_fields_match = re.search(r'CIM fields like\s+(.*?)\.', text)
    if cim_fields_match:
        for m in re.finditer(r'`([^`]+)`', cim_fields_match.group(1)):
            cim_field = m.group(1).strip()
            field_id = f"field:{cim_field}"
            entities.append(KGEntity(
                id=field_id, entity_type="Field", name=cim_field,
                description=f"CIM field: {cim_field}",
            ))

    # Extract lookups from "Lookups" section
    lookup_section = re.search(r'## 3\.\s*Lookups\s*\n(.*?)(?=\n##|\Z)', text, re.DOTALL)
    if lookup_section:
        # Parse lookup subsections (### lookup_name)
        for lk_match in re.finditer(r'###\s*`([^`]+)`\s*\n(.*?)(?=\n###|\Z)',
                                     lookup_section.group(1), re.DOTALL):
            lk_name = lk_match.group(1).strip()
            lk_body = lk_match.group(2).strip()
            lk_id = f"lookup:{lk_name}"
            entities.append(KGEntity(
                id=lk_id, entity_type="Lookup", name=lk_name,
                description=f"Lookup table: {lk_name}",
            ))

            # Extract key and output fields
            key_match = re.search(r'Key:\s*`([^`]+)`', lk_body)
            if key_match:
                key_field = key_match.group(1).strip()
                key_fid = f"field:{key_field}"
                entities.append(KGEntity(
                    id=key_fid, entity_type="Field", name=key_field,
                ))
                relationships.append(KGRelationship(
                    source_id=lk_id, target_id=key_fid,
                    rel_type="references",
                ))

            outputs_match = re.search(r'Outputs?:\s*(.*?)$', lk_body, re.MULTILINE)
            if outputs_match:
                for om in re.finditer(r'`([^`]+)`', outputs_match.group(1)):
                    out_field = om.group(1).strip()
                    out_fid = f"field:{out_field}"
                    entities.append(KGEntity(
                        id=out_fid, entity_type="Field", name=out_field,
                    ))
                    relationships.append(KGRelationship(
                        source_id=lk_id, target_id=out_fid,
                        rel_type="enriches",
                    ))

    return entities, relationships


def extract_entities_from_splunk_rules(rules_path: Path) -> Tuple[List[KGEntity], List[KGRelationship]]:
    """Parse metadata/splunk_rules.md for CIM datamodels and behavioral hints."""
    entities: List[KGEntity] = []
    relationships: List[KGRelationship] = []

    if not rules_path.exists():
        return entities, relationships

    text = rules_path.read_text(encoding="utf-8", errors="replace")

    # Extract CIM datamodel mentions
    dm_pattern = re.compile(r'datamodel[=\s]+(\w+)', re.IGNORECASE)
    found_dms = set()
    for m in dm_pattern.finditer(text):
        dm_name = m.group(1)
        if dm_name not in found_dms:
            found_dms.add(dm_name)
            dm_id = f"dm:{dm_name}"
            entities.append(KGEntity(
                id=dm_id, entity_type="Datamodel", name=dm_name,
                description=f"CIM data model: {dm_name}",
            ))

    # Extract tstats -> datamodel relationship (suggests)
    if found_dms:
        tstats_id = "cmd:tstats"
        entities.append(KGEntity(id=tstats_id, entity_type="Command", name="tstats"))
        for dm_name in found_dms:
            dm_id = f"dm:{dm_name}"
            relationships.append(KGRelationship(
                source_id=tstats_id, target_id=dm_id,
                rel_type="operates_on",
            ))

    return entities, relationships


def extract_entities_from_spec_file(spec_path: Path) -> Tuple[List[KGEntity], List[KGRelationship]]:
    """Parse a .conf.spec file for config stanzas and their fields."""
    entities: List[KGEntity] = []
    relationships: List[KGRelationship] = []

    if not spec_path.exists():
        return entities, relationships

    text = spec_path.read_text(encoding="utf-8", errors="replace")
    conf_name = spec_path.stem  # e.g., "app.conf" from "app.conf.spec"

    current_stanza = None
    current_stanza_id = None

    for line in text.split("\n"):
        line = line.strip()

        # Stanza header
        stanza_match = re.match(r'^\[([^\]]+)\]', line)
        if stanza_match:
            stanza_name = stanza_match.group(1).strip()
            current_stanza = stanza_name
            current_stanza_id = f"stanza:{conf_name}:{stanza_name}"
            entities.append(KGEntity(
                id=current_stanza_id,
                entity_type="ConfigStanza",
                name=f"{conf_name}/{stanza_name}",
                description=f"Configuration stanza [{stanza_name}] in {conf_name}",
                metadata={"conf_file": conf_name},
            ))
            continue

        # Key = <type> or key = value
        if current_stanza_id and "=" in line and not line.startswith("#") and not line.startswith("*"):
            key_match = re.match(r'^([a-zA-Z_][a-zA-Z0-9_.]*)\s*=', line)
            if key_match:
                key_name = key_match.group(1).strip()
                key_id = f"conf_field:{conf_name}:{current_stanza}:{key_name}"
                entities.append(KGEntity(
                    id=key_id, entity_type="Field", name=key_name,
                    description=f"Config key in [{current_stanza}] of {conf_name}",
                    metadata={"conf_file": conf_name, "stanza": current_stanza},
                ))
                relationships.append(KGRelationship(
                    source_id=current_stanza_id, target_id=key_id,
                    rel_type="defines",
                ))

    return entities, relationships


def extract_entities_from_org_config(cfg: Dict[str, Any]) -> Tuple[List[KGEntity], List[KGRelationship]]:
    """Extract entities from organization config section."""
    entities: List[KGEntity] = []
    relationships: List[KGRelationship] = []

    org = cfg.get("organization", {})

    # Index mappings
    idx_map = org.get("index_mappings", {})
    for intent_key, idx_name in idx_map.items():
        idx_id = f"idx:{idx_name}"
        entities.append(KGEntity(
            id=idx_id, entity_type="Index", name=idx_name,
            description=f"Index for {intent_key} data",
        ))

    # Field mappings
    field_map = org.get("field_mappings", {})
    for generic_name, actual_name in field_map.items():
        field_id = f"field:{actual_name}"
        entities.append(KGEntity(
            id=field_id, entity_type="Field", name=actual_name,
            description=f"Field (alias: {generic_name})",
        ))

    # CIM models
    cim_models = org.get("additional_cim_models", {})
    for model_name, model_cfg in cim_models.items():
        dm_id = f"dm:{model_name}"
        entities.append(KGEntity(
            id=dm_id, entity_type="Datamodel", name=model_name,
            description=f"CIM data model: {model_name}",
            metadata={
                "dataset": model_cfg.get("dataset", ""),
                "indicators": model_cfg.get("indicators", []),
            },
        ))
        # CIM field mappings
        for field_alias, cim_path in model_cfg.get("fields", {}).items():
            field_id = f"field:{field_alias}"
            entities.append(KGEntity(
                id=field_id, entity_type="Field", name=field_alias,
                description=f"CIM mapped field: {cim_path}",
            ))
            relationships.append(KGRelationship(
                source_id=field_id, target_id=dm_id,
                rel_type="maps_to_cim",
            ))

    return entities, relationships


# ---------------------------------------------------------------------------
# SPL Query Analyzer — decompose any SPL into constituent entities
# ---------------------------------------------------------------------------

class SPLQueryAnalyzer:
    """
    Analyzes SPL queries to extract constituent entities and relationships.

    Given a raw SPL string, identifies:
    - Commands used (stats, eval, where, etc.)
    - Functions used (count, avg, values, etc.)
    - Fields referenced (explicit field names)
    - Indexes (from index= clauses)
    - Sourcetypes (from sourcetype= clauses)
    - Sources (from source= clauses)
    - Macros (backtick-delimited)
    - Lookups (from | lookup or | inputlookup)
    - Search filters (key=value patterns)
    - Summarizations (tstats, datamodel references)
    """

    # Patterns for SPL decomposition
    _INDEX_PAT = re.compile(r'index\s*=\s*["\']?([a-zA-Z0-9_*-]+)["\']?', re.IGNORECASE)
    _SOURCETYPE_PAT = re.compile(r'sourcetype\s*=\s*["\']?([a-zA-Z0-9_:*.-]+)["\']?', re.IGNORECASE)
    _SOURCE_PAT = re.compile(r'source\s*=\s*["\']?([^\s"\'|]+)["\']?', re.IGNORECASE)
    _MACRO_PAT = re.compile(r'`([a-zA-Z_][a-zA-Z0-9_]*(?:\([^)]*\))?)`')
    _LOOKUP_PAT = re.compile(r'\|\s*(?:lookup|inputlookup)\s+([a-zA-Z0-9_.-]+)', re.IGNORECASE)
    _FIELD_PAT = re.compile(r'\b([a-zA-Z_][a-zA-Z0-9_.]*)\s*[=!<>]', re.IGNORECASE)
    _BY_FIELDS_PAT = re.compile(r'\bby\s+([\w.,\s]+?)(?:\||$)', re.IGNORECASE)
    _AS_FIELD_PAT = re.compile(r'\bas\s+([a-zA-Z_]\w*)', re.IGNORECASE)
    _FUNC_PAT = re.compile(r'\b(' + '|'.join(re.escape(f) for f in KNOWN_FUNCTIONS) + r')\s*\(', re.IGNORECASE)
    _CMD_PAT = re.compile(r'\|\s*([a-z][a-z0-9_]*)', re.IGNORECASE)
    _DATAMODEL_PAT = re.compile(r'(?:datamodel|from\s+datamodel)\s*[=:]\s*["\']?(\w+)', re.IGNORECASE)
    _TSTATS_PAT = re.compile(r'\|\s*tstats\b', re.IGNORECASE)
    _FILTER_PAT = re.compile(r'\b([a-zA-Z_]\w*)\s*=\s*["\']?([^\s"\'|]+)["\']?')

    # Fields to skip (SPL keywords, not real fields)
    _SKIP_FIELDS = {
        "index", "sourcetype", "source", "host", "splunk_server",
        "search", "where", "eval", "stats", "table", "fields",
        "rename", "sort", "dedup", "head", "tail", "top", "rare",
        "by", "as", "or", "and", "not", "true", "false", "null",
        "count", "earliest", "latest", "span", "limit", "maxresults",
    }

    @classmethod
    def analyze(cls, spl: str) -> Dict[str, Any]:
        """
        Analyze an SPL query and return structured decomposition.

        Returns dict with keys: commands, functions, fields, indexes,
        sourcetypes, sources, macros, lookups, filters, datamodels,
        has_tstats, has_summarization.
        """
        result: Dict[str, Any] = {
            "commands": [],
            "functions": [],
            "fields": [],
            "indexes": [],
            "sourcetypes": [],
            "sources": [],
            "macros": [],
            "lookups": [],
            "filters": [],
            "datamodels": [],
            "has_tstats": False,
            "has_summarization": False,
        }

        if not spl or not spl.strip():
            return result

        # Commands
        result["commands"] = list(dict.fromkeys(
            c.lower() for c in cls._CMD_PAT.findall(spl)
            if c.lower() in KNOWN_COMMANDS
        ))

        # Functions
        result["functions"] = list(dict.fromkeys(
            f.lower() for f in cls._FUNC_PAT.findall(spl)
        ))

        # Indexes
        result["indexes"] = list(dict.fromkeys(cls._INDEX_PAT.findall(spl)))

        # Sourcetypes
        result["sourcetypes"] = list(dict.fromkeys(cls._SOURCETYPE_PAT.findall(spl)))

        # Sources
        result["sources"] = list(dict.fromkeys(cls._SOURCE_PAT.findall(spl)))

        # Macros
        result["macros"] = list(dict.fromkeys(cls._MACRO_PAT.findall(spl)))

        # Lookups
        result["lookups"] = list(dict.fromkeys(cls._LOOKUP_PAT.findall(spl)))

        # Fields — from field=value, by clauses, as aliases
        fields = set()
        for f in cls._FIELD_PAT.findall(spl):
            fl = f.lower()
            if fl not in cls._SKIP_FIELDS and len(fl) > 1:
                fields.add(fl)
        for by_match in cls._BY_FIELDS_PAT.finditer(spl):
            for bf in re.split(r'[,\s]+', by_match.group(1)):
                bf = bf.strip().lower()
                if bf and bf not in cls._SKIP_FIELDS and len(bf) > 1:
                    fields.add(bf)
        for as_match in cls._AS_FIELD_PAT.finditer(spl):
            af = as_match.group(1).lower()
            if af not in cls._SKIP_FIELDS:
                fields.add(af)
        result["fields"] = sorted(fields)

        # Search filters (key=value pairs that aren't index/sourcetype/source)
        for fm in cls._FILTER_PAT.finditer(spl):
            key = fm.group(1).lower()
            val = fm.group(2)
            if key not in ("index", "sourcetype", "source") and key not in cls._SKIP_FIELDS:
                result["filters"].append({"field": key, "value": val})

        # Datamodels
        result["datamodels"] = list(dict.fromkeys(cls._DATAMODEL_PAT.findall(spl)))

        # tstats / summarization detection
        result["has_tstats"] = bool(cls._TSTATS_PAT.search(spl))
        result["has_summarization"] = result["has_tstats"] or bool(result["datamodels"])

        return result

    @classmethod
    def to_entities_and_relationships(
        cls, spl: str, search_name: str = "query",
    ) -> Tuple[List[KGEntity], List[KGRelationship]]:
        """
        Analyze SPL and return entities + relationships suitable for graph injection.

        Creates a temporary SavedSearch node and links all extracted entities to it.
        """
        analysis = cls.analyze(spl)
        entities: List[KGEntity] = []
        relationships: List[KGRelationship] = []

        search_id = f"search:{search_name}"
        entities.append(KGEntity(
            id=search_id, entity_type="SavedSearch", name=search_name,
            description=spl[:200],
            metadata={"spl": spl[:500], "analysis": {
                k: v for k, v in analysis.items()
                if k not in ("filters",) and v  # skip empty and large
            }},
        ))

        # Link indexes
        for idx in analysis["indexes"]:
            idx_id = f"idx:{idx}"
            entities.append(KGEntity(id=idx_id, entity_type="Index", name=idx))
            relationships.append(KGRelationship(
                source_id=search_id, target_id=idx_id, rel_type="uses_index",
            ))

        # Link sourcetypes
        for st in analysis["sourcetypes"]:
            st_id = f"st:{st}"
            entities.append(KGEntity(id=st_id, entity_type="Sourcetype", name=st))
            relationships.append(KGRelationship(
                source_id=search_id, target_id=st_id, rel_type="uses_sourcetype",
            ))

        # Link commands
        for cmd in analysis["commands"]:
            cmd_id = f"cmd:{cmd}"
            entities.append(KGEntity(id=cmd_id, entity_type="Command", name=cmd))
            relationships.append(KGRelationship(
                source_id=search_id, target_id=cmd_id, rel_type="uses_command",
            ))

        # Link functions
        for fn in analysis["functions"]:
            fn_id = f"fn:{fn}"
            entities.append(KGEntity(id=fn_id, entity_type="Function", name=fn))
            relationships.append(KGRelationship(
                source_id=search_id, target_id=fn_id, rel_type="uses_functions",
            ))

        # Link fields
        for fld in analysis["fields"]:
            fld_id = f"field:{fld}"
            entities.append(KGEntity(id=fld_id, entity_type="Field", name=fld))
            relationships.append(KGRelationship(
                source_id=search_id, target_id=fld_id, rel_type="uses_field",
            ))

        # Link macros
        for macro in analysis["macros"]:
            macro_name = macro.split("(")[0]  # strip args
            macro_id = f"macro:{macro_name}"
            entities.append(KGEntity(id=macro_id, entity_type="Macro", name=macro_name))
            relationships.append(KGRelationship(
                source_id=search_id, target_id=macro_id, rel_type="uses_macro",
            ))

        # Link lookups
        for lk in analysis["lookups"]:
            lk_id = f"lookup:{lk}"
            entities.append(KGEntity(id=lk_id, entity_type="Lookup", name=lk))
            relationships.append(KGRelationship(
                source_id=search_id, target_id=lk_id, rel_type="uses_lookup",
            ))

        # Link datamodels
        for dm in analysis["datamodels"]:
            dm_id = f"dm:{dm}"
            entities.append(KGEntity(id=dm_id, entity_type="Datamodel", name=dm))
            relationships.append(KGRelationship(
                source_id=search_id, target_id=dm_id, rel_type="operates_on",
            ))

        # Summarization node
        if analysis["has_summarization"]:
            summ_id = f"summ:{search_name}"
            entities.append(KGEntity(
                id=summ_id, entity_type="Summarization", name=f"{search_name}_summary",
                description="Report acceleration / tstats summarization",
            ))
            relationships.append(KGRelationship(
                source_id=search_id, target_id=summ_id, rel_type="accelerated_by",
            ))

        return entities, relationships


# ---------------------------------------------------------------------------
