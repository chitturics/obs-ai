"""
Self-Learning Generators — Q&A extraction functions.

Extracted from self_learning.py for size management.
self_learning.py re-exports all public names.

Provides:
- _extract_qa_from_spl_doc, _extract_qa_from_config, _extract_qa_from_metadata
- _extract_qa_from_savedsearches, _extract_qa_from_macros, _extract_qa_from_indexes
- _extract_qa_from_org_config
- generate_qa_pairs_from_directory
"""
from __future__ import annotations

import hashlib
import logging
import os
import re
from pathlib import Path
from typing import List

from chat_app.self_learning_models import QAPair  # noqa: F401

logger = logging.getLogger(__name__)

# Q&A Generation from Documentation
# ---------------------------------------------------------------------------

def _extract_qa_from_spl_doc(filepath: str) -> List[QAPair]:
    """Generate Q&A pairs from SPL command documentation."""
    pairs = []
    try:
        content = Path(filepath).read_text(encoding="utf-8", errors="ignore")
        filename = Path(filepath).stem
        cmd_name = filename.replace("spl_cmd_", "")

        # Extract command description
        desc_match = re.search(r'##?\s*Description\s*\n(.*?)(?=\n##?\s|\Z)', content, re.DOTALL)
        if desc_match:
            desc = desc_match.group(1).strip()[:500]
            pairs.append(QAPair(
                question=f"What does the {cmd_name} command do in SPL?",
                answer=desc,
                source_file=filepath,
                source_type="spl_doc",
                topic=f"spl_{cmd_name}",
            ))

        # Extract syntax
        syntax_match = re.search(r'##?\s*Syntax\s*\n(.*?)(?=\n##?\s|\Z)', content, re.DOTALL)
        if syntax_match:
            syntax = syntax_match.group(1).strip()[:500]
            pairs.append(QAPair(
                question=f"What is the syntax for the {cmd_name} command?",
                answer=syntax,
                source_file=filepath,
                source_type="spl_doc",
                topic=f"spl_{cmd_name}",
            ))

        # Extract examples
        example_match = re.search(r'##?\s*Example[s]?\s*\n(.*?)(?=\n##?\s|\Z)', content, re.DOTALL)
        if example_match:
            examples = example_match.group(1).strip()[:800]
            pairs.append(QAPair(
                question=f"Show me examples of using the {cmd_name} command.",
                answer=examples,
                source_file=filepath,
                source_type="spl_doc",
                topic=f"spl_{cmd_name}",
            ))

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[SELF-LEARN] Error parsing SPL doc {filepath}: {exc}")

    return pairs


def _extract_qa_from_config(filepath: str) -> List[QAPair]:
    """Generate Q&A pairs from .conf/.spec configuration files."""
    pairs = []
    try:
        content = Path(filepath).read_text(encoding="utf-8", errors="ignore")
        filename = Path(filepath).name

        # Extract stanzas and their settings
        stanzas = re.findall(r'\[([^\]]+)\]\s*\n((?:[^[\n].*\n)*)', content)
        for stanza_name, stanza_body in stanzas[:10]:  # Limit to avoid huge files
            if stanza_body.strip():
                pairs.append(QAPair(
                    question=f"What settings are in the [{stanza_name}] stanza of {filename}?",
                    answer=f"[{stanza_name}]\n{stanza_body.strip()[:500]}",
                    source_file=filepath,
                    source_type="config",
                    topic=f"config_{filename.replace('.', '_')}",
                ))

    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.debug(f"[SELF-LEARN] Error parsing config {filepath}: {exc}")

    return pairs


def _extract_qa_from_metadata(filepath: str) -> List[QAPair]:
    """Generate Q&A pairs from metadata/context files."""
    pairs = []
    try:
        content = Path(filepath).read_text(encoding="utf-8", errors="ignore")
        Path(filepath).stem

        # Extract sections from markdown files
        sections = re.split(r'\n##?\s+', content)
        for section in sections[1:]:  # Skip pre-heading content
            lines = section.split('\n', 1)
            if len(lines) == 2:
                heading = lines[0].strip()
                body = lines[1].strip()[:600]
                if heading and body:
                    pairs.append(QAPair(
                        question=f"What is {heading}?",
                        answer=body,
                        source_file=filepath,
                        source_type="metadata",
                        topic=heading.lower().replace(' ', '_'),
                    ))

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[SELF-LEARN] Error parsing metadata {filepath}: {exc}")

    return pairs


def _extract_qa_from_savedsearches(filepath: str) -> List[QAPair]:
    """Generate Q&A pairs from savedsearches.conf files."""
    pairs = []
    try:
        content = Path(filepath).read_text(encoding="utf-8", errors="ignore")
        stanzas = re.findall(r'\[([^\]]+)\]\s*\n((?:[^[\n].*\n)*)', content)
        for name, body in stanzas[:20]:
            if name.startswith("default") or not body.strip():
                continue
            # Extract search string
            search_match = re.search(r'search\s*=\s*(.+?)(?:\n|$)', body)
            cron_match = re.search(r'cron_schedule\s*=\s*(.+?)(?:\n|$)', body)
            desc_match = re.search(r'description\s*=\s*(.+?)(?:\n|$)', body)

            if search_match:
                spl = search_match.group(1).strip()
                desc = desc_match.group(1).strip() if desc_match else ""
                schedule = cron_match.group(1).strip() if cron_match else "not scheduled"

                pairs.append(QAPair(
                    question=f"What does the saved search '{name}' do?",
                    answer=f"The saved search '{name}' runs: `{spl[:300]}`\n"
                           f"Schedule: {schedule}" + (f"\nDescription: {desc}" if desc else ""),
                    source_file=filepath, source_type="savedsearch", topic="savedsearch",
                ))
                pairs.append(QAPair(
                    question=f"Show me the SPL for the '{name}' saved search.",
                    answer=f"```spl\n{spl[:500]}\n```",
                    source_file=filepath, source_type="savedsearch", topic="savedsearch",
                ))
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[SELF-LEARN] Error parsing saved searches {filepath}: {exc}")
    return pairs


def _extract_qa_from_macros(filepath: str) -> List[QAPair]:
    """Generate Q&A pairs from macros.conf files."""
    pairs = []
    try:
        content = Path(filepath).read_text(encoding="utf-8", errors="ignore")
        stanzas = re.findall(r'\[([^\]]+)\]\s*\n((?:[^[\n].*\n)*)', content)
        for name, body in stanzas[:30]:
            if name.startswith("default") or not body.strip():
                continue
            defn_match = re.search(r'definition\s*=\s*(.+?)(?:\n|$)', body)
            args_match = re.search(r'args\s*=\s*(.+?)(?:\n|$)', body)
            desc_match = re.search(r'description\s*=\s*(.+?)(?:\n|$)', body)

            if defn_match:
                definition = defn_match.group(1).strip()
                args = args_match.group(1).strip() if args_match else "none"
                desc = desc_match.group(1).strip() if desc_match else ""

                # Determine argument count from name pattern e.g., "macro_name(2)"
                arg_count = ""
                arg_match = re.search(r'\((\d+)\)', name)
                if arg_match:
                    arg_count = f" (takes {arg_match.group(1)} argument(s))"

                pairs.append(QAPair(
                    question=f"What does the Splunk macro `{name}` do?",
                    answer=f"Macro `{name}`{arg_count}:\n"
                           f"Definition: `{definition[:400]}`\n"
                           f"Arguments: {args}" + (f"\nDescription: {desc}" if desc else ""),
                    source_file=filepath, source_type="macro", topic="macro",
                ))
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[SELF-LEARN] Error parsing macros {filepath}: {exc}")
    return pairs


def _extract_qa_from_indexes(filepath: str) -> List[QAPair]:
    """Generate Q&A pairs from indexes.conf files."""
    pairs = []
    try:
        content = Path(filepath).read_text(encoding="utf-8", errors="ignore")
        stanzas = re.findall(r'\[([^\]]+)\]\s*\n((?:[^[\n].*\n)*)', content)
        for name, body in stanzas[:30]:
            if name.startswith("default") or name.startswith("volume:") or not body.strip():
                continue
            # Extract index properties
            frozen_match = re.search(r'frozenTimePeriodInSecs\s*=\s*(\d+)', body)
            re.search(r'maxDataSizeMB\s*=\s*(\d+)', body)
            datatype_match = re.search(r'datatype\s*=\s*(\w+)', body)

            retention_days = int(frozen_match.group(1)) // 86400 if frozen_match else "unknown"
            datatype = datatype_match.group(1) if datatype_match else "event"

            pairs.append(QAPair(
                question=f"What is the '{name}' index used for and what is its retention?",
                answer=f"Index '{name}' (type: {datatype}):\n"
                       f"Retention: {retention_days} days\n"
                       f"Config:\n{body.strip()[:400]}",
                source_file=filepath, source_type="index", topic="indexing",
            ))
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[SELF-LEARN] Error parsing indexes {filepath}: {exc}")
    return pairs


def _extract_qa_from_org_config(config_path: str = None) -> List[QAPair]:
    """Generate Q&A pairs from the config.yaml organization section."""
    pairs = []
    try:
        from chat_app.utils import load_config
        config = load_config(config_path)
        org = config.get("organization", {})

        # Index mappings
        idx_maps = org.get("index_mappings", {})
        if idx_maps:
            for category, index_name in idx_maps.items():
                pairs.append(QAPair(
                    question=f"What index should I use for {category} events?",
                    answer=f"For {category} events, use `index={index_name}`",
                    source_file="config.yaml", source_type="org_config", topic="indexing",
                ))

        # Field mappings
        field_maps = org.get("field_mappings", {})
        if field_maps:
            for logical_name, actual_name in field_maps.items():
                pairs.append(QAPair(
                    question=f"What field name is used for {logical_name} in our environment?",
                    answer=f"In our environment, '{logical_name}' maps to the field `{actual_name}`",
                    source_file="config.yaml", source_type="org_config", topic="config",
                ))

        # CIM data models
        cim_models = org.get("cim_models", {})
        if cim_models:
            for model_name, model_info in cim_models.items():
                if isinstance(model_info, dict):
                    accel = model_info.get("accelerated", False)
                    idx = model_info.get("index", "unknown")
                    pairs.append(QAPair(
                        question=f"Is the {model_name} CIM data model accelerated? What index does it use?",
                        answer=f"The {model_name} data model {'is' if accel else 'is NOT'} accelerated. "
                               f"Primary index: {idx}",
                        source_file="config.yaml", source_type="org_config", topic="cim",
                    ))

        # Sourcetype mappings
        st_maps = org.get("sourcetype_mappings", {})
        if st_maps:
            for category, sourcetypes in st_maps.items():
                if isinstance(sourcetypes, list):
                    pairs.append(QAPair(
                        question=f"What sourcetypes are used for {category} data?",
                        answer=f"For {category}: {', '.join(sourcetypes)}",
                        source_file="config.yaml", source_type="org_config", topic="config",
                    ))

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.debug(f"[SELF-LEARN] Error extracting from org config: {exc}")
    return pairs


def generate_qa_pairs_from_directory(directory: str, file_patterns: List[str] = None) -> List[QAPair]:
    """
    Scan a directory and generate Q&A pairs from all supported files.

    Args:
        directory: Path to scan.
        file_patterns: Optional list of glob patterns (e.g., ['*.md', '*.conf']).

    Returns:
        List of QAPair objects.
    """
    if not os.path.isdir(directory):
        logger.debug(f"[SELF-LEARN] Directory not found: {directory}")
        return []

    patterns = file_patterns or ['*.md', '*.conf', '*.spec', '*.txt', '*.json', '*.yaml', '*.yml']
    all_pairs = []

    for pattern in patterns:
        for filepath in Path(directory).rglob(pattern):
            fp = str(filepath)
            ext = filepath.suffix.lower()

            if 'spl_cmd_' in filepath.name:
                all_pairs.extend(_extract_qa_from_spl_doc(fp))
            elif filepath.name == 'savedsearches.conf':
                all_pairs.extend(_extract_qa_from_savedsearches(fp))
            elif filepath.name == 'macros.conf':
                all_pairs.extend(_extract_qa_from_macros(fp))
            elif filepath.name == 'indexes.conf':
                all_pairs.extend(_extract_qa_from_indexes(fp))
            elif ext in ('.conf', '.spec'):
                all_pairs.extend(_extract_qa_from_config(fp))
            elif ext in ('.md', '.txt'):
                all_pairs.extend(_extract_qa_from_metadata(fp))

    # Deduplicate by question hash
    seen = set()
    unique = []
    for pair in all_pairs:
        h = hashlib.sha256(pair.question.lower().encode()).hexdigest()
        if h not in seen:
            seen.add(h)
            unique.append(pair)

    logger.info(f"[SELF-LEARN] Generated {len(unique)} Q&A pairs from {directory}")
    return unique


# ---------------------------------------------------------------------------
# Answer Reassessment
# ---------------------------------------------------------------------------

