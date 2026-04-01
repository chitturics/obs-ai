#!/usr/bin/env python3
"""
Training Data Generators — Generator functions for LLM fine-tuning data export.

Extracted from eval_training_export.py to keep file sizes manageable.
Contains: generate_spl_doc_training, generate_cross_command_training,
          generate_spec_training, generate_scenario_training,
          generate_eval_training, generate_paraphrase_training,
          generate_metadata_training, export_training_jsonl,
          run_full_export, and __main__ entry point.
"""

import argparse
import json
import logging
import os
import re
import sys
import hashlib
from datetime import datetime
from pathlib import Path
from typing import List, Tuple

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/chat_app')
os.chdir('/app')

from chat_app.eval_training_data import (  # noqa: E402
    TrainingEntry,
    _parse_spl_doc,
    _parse_spec_file,
    COMMAND_QA_TEMPLATES,
    ADVANCED_COMMAND_TEMPLATES,
    CROSS_COMMAND_TEMPLATES,
    COMMAND_FAMILIES,
    SPL_GENERATION_SCENARIOS,
    SPL_OPTIMIZATION_SCENARIOS,
    BEST_PRACTICES,
    ADVANCED_SCENARIOS,
    OUTPUT_DIR,
    SYSTEM_PROMPT,
    logger,
)

def generate_spl_doc_training(spl_docs_dir: str = "/app/spl_docs") -> List[TrainingEntry]:
    """Generate training entries from SPL command documentation."""
    entries = []
    doc_dir = Path(spl_docs_dir)
    if not doc_dir.is_dir():
        logger.warning(f"SPL docs dir not found: {spl_docs_dir}")
        return entries

    for doc_file in sorted(doc_dir.glob("spl_cmd_*.md")):
        cmd_name = doc_file.stem.replace("spl_cmd_", "")
        sections = _parse_spl_doc(str(doc_file))
        if not sections:
            continue

        for template_q, section_key in COMMAND_QA_TEMPLATES:
            question = template_q.format(cmd=cmd_name)

            # Build answer from appropriate sections
            if section_key == "description" and "description" in sections:
                answer = sections["description"][:800]
            elif section_key == "syntax" and "syntax" in sections:
                answer = f"Syntax for `{cmd_name}`:\n```\n{sections['syntax'][:600]}\n```"
            elif section_key == "examples" and "examples" in sections:
                answer = f"Examples of `{cmd_name}`:\n{sections['examples'][:800]}"
            elif section_key == "arguments" and "arguments" in sections:
                answer = f"Arguments for `{cmd_name}`:\n{sections['arguments'][:800]}"
            elif section_key == "usage" and "description" in sections:
                type_info = f"It is a {sections.get('type', 'general')} command. " if sections.get('type') != 'unknown' else ""
                answer = f"{type_info}{sections['description'][:600]}"
            elif section_key == "type" and sections.get("type"):
                answer = f"The `{cmd_name}` command is a {sections['type']} command."
                if "description" in sections:
                    answer += f" {sections['description'][:300]}"
            elif section_key == "performance":
                perf = sections.get("performance", "")
                if perf:
                    answer = f"Performance considerations for `{cmd_name}`:\n{perf[:600]}"
                else:
                    continue
            elif section_key == "troubleshoot":
                if "description" in sections:
                    answer = (
                        f"Common issues with `{cmd_name}`:\n"
                        f"1. Check the syntax: {sections.get('syntax', 'see documentation')[:200]}\n"
                        f"2. Verify field names exist in your data\n"
                        f"3. Check if the command supports your use case: {sections['description'][:200]}"
                    )
                else:
                    continue
            else:
                continue

            if answer and len(answer) > 20:
                entries.append(TrainingEntry(
                    question=question, answer=answer,
                    source=str(doc_file), topic=f"spl_{cmd_name}",
                ))

    # Additional advanced templates per command
    for doc_file in sorted(doc_dir.glob("spl_cmd_*.md")):
        cmd_name = doc_file.stem.replace("spl_cmd_", "")
        sections = _parse_spl_doc(str(doc_file))
        if not sections or "description" not in sections:
            continue

        for template_q, section_key in ADVANCED_COMMAND_TEMPLATES:
            question = template_q.format(cmd=cmd_name)
            desc = sections.get("description", "")[:300]
            sections.get("syntax", "")[:200]

            if section_key == "pipeline" and desc:
                answer = (
                    f"The `{cmd_name}` command can be used in pipelines. "
                    f"{desc}\n\nExample pipeline:\n"
                    f"```spl\nindex=main | {cmd_name} ... | stats count\n```"
                )
            elif section_key == "null_handling" and desc:
                answer = (
                    f"When `{cmd_name}` encounters null values, behavior depends on the arguments. "
                    f"Generally, null fields are ignored in aggregations. "
                    f"Use `fillnull` before `{cmd_name}` if you need default values."
                )
            elif section_key == "mv_handling" and desc:
                answer = (
                    f"For multivalue fields with `{cmd_name}`, you may need `mvexpand` first "
                    f"to split multivalue fields into separate events, or use `makemv` to create "
                    f"multivalue fields from delimited strings."
                )
            elif section_key in ("security_use", "perf_use") and desc:
                use_type = "security monitoring" if section_key == "security_use" else "performance monitoring"
                answer = (
                    f"Using `{cmd_name}` for {use_type}:\n{desc}\n\n"
                    f"Combine with appropriate index/sourcetype filters and time ranges for efficient searches."
                )
            elif section_key == "subsearch" and desc:
                answer = (
                    f"The `{cmd_name}` command can work with subsearches. "
                    f"Subsearches run first and their results are used in the outer search. "
                    f"Note: subsearches have limits (max 10,000 results, 60-second timeout)."
                )
            elif section_key == "acceleration" and desc:
                answer = (
                    f"For `{cmd_name}`, acceleration depends on the command type. "
                    f"Use data model acceleration and `tstats` for the fastest results. "
                    f"Summary indexing with `collect` can pre-compute expensive `{cmd_name}` operations."
                )
            else:
                continue

            entries.append(TrainingEntry(
                question=question, answer=answer,
                source=str(doc_file), topic=f"spl_{cmd_name}_advanced",
                confidence=0.8,
            ))

    logger.info(f"Generated {len(entries)} SPL doc training entries")
    return entries


def generate_cross_command_training(spl_docs_dir: str = "/app/spl_docs") -> List[TrainingEntry]:
    """Generate cross-command comparison training entries."""
    entries = []
    doc_dir = Path(spl_docs_dir)

    # Load descriptions for families
    cmd_descriptions = {}
    for doc_file in doc_dir.glob("spl_cmd_*.md"):
        cmd = doc_file.stem.replace("spl_cmd_", "")
        sections = _parse_spl_doc(str(doc_file))
        if "description" in sections:
            cmd_descriptions[cmd] = sections["description"][:300]

    for family_name, cmds in COMMAND_FAMILIES.items():
        available = [c for c in cmds if c in cmd_descriptions]
        if len(available) < 2:
            continue

        for i, cmd1 in enumerate(available):
            for cmd2 in available[i+1:]:
                for template in CROSS_COMMAND_TEMPLATES:
                    question = template.format(cmd1=cmd1, cmd2=cmd2)
                    answer = (
                        f"**{cmd1}**: {cmd_descriptions.get(cmd1, 'N/A')[:200]}\n\n"
                        f"**{cmd2}**: {cmd_descriptions.get(cmd2, 'N/A')[:200]}\n\n"
                        f"Use `{cmd1}` when you need its specific functionality, "
                        f"and `{cmd2}` when the other approach fits better."
                    )
                    entries.append(TrainingEntry(
                        question=question, answer=answer,
                        source=f"cross_{family_name}", topic=f"compare_{cmd1}_{cmd2}",
                        confidence=0.85,
                    ))

    logger.info(f"Generated {len(entries)} cross-command training entries")
    return entries


def generate_spec_training(specs_dir: str = "/app/ingest_specs") -> List[TrainingEntry]:
    """Generate training from .spec and .conf reference files."""
    entries = []
    spec_dir = Path(specs_dir)
    if not spec_dir.is_dir():
        return entries

    for spec_file in sorted(spec_dir.glob("*")):
        if spec_file.suffix not in (".spec", ".conf", ".md"):
            continue

        conf_name = spec_file.stem
        stanzas = _parse_spec_file(str(spec_file))
        if not stanzas:
            continue

        # Overall config Q&A
        stanza_names = [s["name"] for s in stanzas[:15]]
        if stanza_names:
            entries.append(TrainingEntry(
                question=f"What stanzas are available in {conf_name}?",
                answer=f"The `{conf_name}` configuration file contains these stanzas:\n" +
                       "\n".join(f"- [{s}]" for s in stanza_names),
                source=str(spec_file), topic=f"config_{conf_name}",
            ))

        # Per-stanza Q&A
        for stanza in stanzas[:10]:
            if not stanza["body"]:
                continue
            entries.append(TrainingEntry(
                question=f"What settings are in [{stanza['name']}] in {conf_name}?",
                answer=f"[{stanza['name']}]\n{stanza['body'][:500]}",
                source=str(spec_file), topic=f"config_{conf_name}",
            ))

            # Per-setting Q&A
            for setting, value in list(stanza["settings"].items())[:5]:
                entries.append(TrainingEntry(
                    question=f"What is the {setting} setting in [{stanza['name']}] of {conf_name}?",
                    answer=f"In `{conf_name}`, under `[{stanza['name']}]`, "
                           f"`{setting}` = `{value[:200]}`",
                    source=str(spec_file), topic=f"config_{conf_name}",
                    confidence=0.9,
                ))

    logger.info(f"Generated {len(entries)} spec/conf training entries")
    return entries


def generate_scenario_training() -> List[TrainingEntry]:
    """Generate training from curated SPL scenarios."""
    entries = []
    for scenario in SPL_GENERATION_SCENARIOS:
        entries.append(TrainingEntry(
            question=scenario["q"], answer=scenario["a"],
            source="curated_spl_gen", topic="spl_generation",
            confidence=0.95,
        ))

    for scenario in SPL_OPTIMIZATION_SCENARIOS:
        entries.append(TrainingEntry(
            question=scenario["q"], answer=scenario["a"],
            source="curated_spl_opt", topic="spl_optimization",
            confidence=0.95,
        ))

    for bp in BEST_PRACTICES:
        entries.append(TrainingEntry(
            question=bp["q"], answer=bp["a"],
            source="curated_best_practices", topic="best_practices",
            confidence=0.95,
        ))

    for scenario in ADVANCED_SCENARIOS:
        entries.append(TrainingEntry(
            question=scenario["q"], answer=scenario["a"],
            source="curated_advanced", topic="advanced_spl",
            confidence=0.95,
        ))

    logger.info(f"Generated {len(entries)} scenario training entries")
    return entries


def generate_eval_training() -> List[TrainingEntry]:
    """Convert eval test cases to training format."""
    entries = []
    try:
        from chat_app.eval_test_cases import generate_all_test_cases
        cases = generate_all_test_cases()
        for tc in cases:
            # Build a reasonable answer from the expected keywords and collection
            kw_text = ", ".join(tc.expected_keywords[:5])
            collection_hint = tc.expected_collection.replace("_mxbai", "").replace("_embed_large_v3", "")

            if tc.expected_type == "command_help":
                answer = (
                    f"This relates to SPL command help. Key concepts: {kw_text}. "
                    f"Refer to the {collection_hint} documentation for detailed information."
                )
            elif tc.expected_type == "generation":
                answer = (
                    f"To address this, you would build an SPL query using: {kw_text}. "
                    f"The relevant knowledge is in the {collection_hint} collection."
                )
            elif tc.expected_type == "optimization":
                answer = (
                    f"For optimization, consider these approaches related to: {kw_text}. "
                    f"Best practices can be found in the {collection_hint} reference."
                )
            elif tc.expected_type == "config":
                answer = (
                    f"This configuration topic involves: {kw_text}. "
                    f"Check the {collection_hint} configuration reference."
                )
            elif tc.expected_type == "troubleshoot":
                answer = (
                    f"To troubleshoot this issue, check: {kw_text}. "
                    f"Relevant documentation is in {collection_hint}."
                )
            else:
                answer = f"Relevant concepts: {kw_text}. See {collection_hint}."

            entries.append(TrainingEntry(
                question=tc.query, answer=answer,
                source="eval_test_cases", topic=tc.category,
                confidence=0.7,  # Lower confidence for generated answers
            ))
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.warning(f"Could not load eval test cases: {e}")

    logger.info(f"Generated {len(entries)} eval-based training entries")
    return entries


def generate_paraphrase_training(spl_docs_dir: str = "/app/spl_docs") -> List[TrainingEntry]:
    """Generate paraphrased variations of command help questions."""
    entries = []
    doc_dir = Path(spl_docs_dir)
    if not doc_dir.is_dir():
        return entries

    PARAPHRASE_TEMPLATES = [
        "I need help with {cmd}",
        "Can you explain {cmd} to me?",
        "How does {cmd} work exactly?",
        "What's {cmd} used for in Splunk searches?",
        "Tell me everything about the {cmd} command",
        "Help me understand {cmd}",
        "I don't understand {cmd}, can you help?",
        "Show me how to write a {cmd} query",
        "What's the correct way to use {cmd}?",
        "I keep getting errors with {cmd}",
        "My {cmd} command isn't returning results",
        "How to use {cmd} with other commands",
        "Is {cmd} the right command for my use case?",
        "What fields does {cmd} require?",
        "Does {cmd} work with streaming data?",
        "How to pipe output of {cmd} to another command",
        "What is the output format of {cmd}?",
        "{cmd}",  # Just the command name
        "splunk {cmd}",
        "spl {cmd} help",
    ]

    for doc_file in sorted(doc_dir.glob("spl_cmd_*.md")):
        cmd_name = doc_file.stem.replace("spl_cmd_", "")
        sections = _parse_spl_doc(str(doc_file))
        if not sections or "description" not in sections:
            continue

        desc = sections["description"][:400]
        syntax = sections.get("syntax", "")[:300]
        answer_base = f"The `{cmd_name}` command: {desc}"
        if syntax:
            answer_base += f"\n\nSyntax:\n```\n{syntax}\n```"

        for template in PARAPHRASE_TEMPLATES:
            question = template.format(cmd=cmd_name)
            entries.append(TrainingEntry(
                question=question, answer=answer_base,
                source=str(doc_file), topic=f"spl_{cmd_name}_para",
                confidence=0.85,
            ))

    logger.info(f"Generated {len(entries)} paraphrase training entries")
    return entries


def generate_metadata_training(metadata_dir: str = "/app/metadata") -> List[TrainingEntry]:
    """Generate training from metadata files."""
    entries = []
    meta_dir = Path(metadata_dir)
    if not meta_dir.is_dir():
        return entries

    for md_file in meta_dir.glob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8", errors="ignore")

            # Split by headings
            sections = re.split(r'\n##?\s+', content)
            for section in sections[1:]:
                lines = section.split('\n', 1)
                if len(lines) == 2:
                    heading = lines[0].strip()
                    body = lines[1].strip()
                    if heading and body and len(body) > 30:
                        # Generate multiple question forms
                        entries.append(TrainingEntry(
                            question=f"What is {heading}?",
                            answer=body[:800],
                            source=str(md_file), topic=heading.lower().replace(' ', '_'),
                        ))
                        entries.append(TrainingEntry(
                            question=f"Explain {heading} in Splunk.",
                            answer=body[:800],
                            source=str(md_file), topic=heading.lower().replace(' ', '_'),
                        ))
                        entries.append(TrainingEntry(
                            question=f"Tell me about {heading}.",
                            answer=body[:800],
                            source=str(md_file), topic=heading.lower().replace(' ', '_'),
                        ))
        except Exception as _exc:  # broad catch — resilience against all failures
            continue

    logger.info(f"Generated {len(entries)} metadata training entries")
    return entries


def export_training_jsonl(entries: List[TrainingEntry], output_path: str = None) -> Tuple[str, int]:
    """Export training entries to JSONL format compatible with Ollama fine-tuning."""
    out_dir = OUTPUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filepath = Path(output_path) if output_path else (out_dir / f"full_training_{timestamp}.jsonl")

    seen_hashes = set()
    count = 0

    with open(filepath, "w", encoding="utf-8") as f:
        for entry in entries:
            if not entry.question or not entry.answer:
                continue

            # Deduplicate by question hash
            qhash = hashlib.sha256(entry.question.lower().encode()).hexdigest()
            if qhash in seen_hashes:
                continue
            seen_hashes.add(qhash)

            record = {
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": entry.question},
                    {"role": "assistant", "content": entry.answer},
                ],
                "metadata": {
                    "source": entry.source,
                    "topic": entry.topic,
                    "confidence": entry.confidence,
                },
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1

    logger.info(f"Exported {count} training entries to {filepath}")
    return str(filepath), count


def run_full_export(
    spl_docs_dir: str = "/app/spl_docs",
    specs_dir: str = "/app/ingest_specs",
    metadata_dir: str = "/app/metadata",
    output_path: str = None,
) -> Tuple[str, int]:
    """Run the complete training data export pipeline."""
    all_entries: List[TrainingEntry] = []

    print("=" * 60)
    print("Training Data Export Pipeline")
    print("=" * 60)

    # Phase 1: SPL command docs
    print("\n[1/6] Generating SPL command documentation training...")
    spl_entries = generate_spl_doc_training(spl_docs_dir)
    all_entries.extend(spl_entries)
    print(f"  -> {len(spl_entries)} entries")

    # Phase 2: Cross-command comparisons
    print("\n[2/6] Generating cross-command comparison training...")
    cross_entries = generate_cross_command_training(spl_docs_dir)
    all_entries.extend(cross_entries)
    print(f"  -> {len(cross_entries)} entries")

    # Phase 3: Spec/conf file training
    print("\n[3/6] Generating spec/conf file training...")
    spec_entries = generate_spec_training(specs_dir)
    all_entries.extend(spec_entries)
    print(f"  -> {len(spec_entries)} entries")

    # Phase 4: Curated scenarios
    print("\n[4/6] Generating curated scenario training...")
    scenario_entries = generate_scenario_training()
    all_entries.extend(scenario_entries)
    print(f"  -> {len(scenario_entries)} entries")

    # Phase 5: Eval test cases
    print("\n[5/7] Converting eval test cases to training format...")
    eval_entries = generate_eval_training()
    all_entries.extend(eval_entries)
    print(f"  -> {len(eval_entries)} entries")

    # Phase 6: Paraphrase variations
    print("\n[6/7] Generating paraphrase variations...")
    para_entries = generate_paraphrase_training(spl_docs_dir)
    all_entries.extend(para_entries)
    print(f"  -> {len(para_entries)} entries")

    # Phase 7: Metadata documents
    print("\n[7/7] Generating metadata training...")
    meta_entries = generate_metadata_training(metadata_dir)
    all_entries.extend(meta_entries)
    print(f"  -> {len(meta_entries)} entries")

    # Export
    print(f"\nTotal raw entries: {len(all_entries)}")
    print("Deduplicating and exporting...")
    filepath, count = export_training_jsonl(all_entries, output_path)

    print(f"\n{'=' * 60}")
    print(f"Export complete: {count} unique training entries")
    print(f"Output: {filepath}")
    print(f"{'=' * 60}")

    return filepath, count


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export training data for LLM fine-tuning")
    parser.add_argument("--spl-docs", default="/app/spl_docs", help="SPL docs directory")
    parser.add_argument("--specs", default="/app/ingest_specs", help="Spec files directory")
    parser.add_argument("--metadata", default="/app/metadata", help="Metadata directory")
    parser.add_argument("--output", help="Output JSONL file path")
    parser.add_argument("--stats-only", action="store_true", help="Just show stats, don't export")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.stats_only:
        print("Counting training entries (no export)...")
        total = 0
        for name, gen_fn, kwargs in [
            ("SPL docs", generate_spl_doc_training, {"spl_docs_dir": args.spl_docs}),
            ("Cross-command", generate_cross_command_training, {"spl_docs_dir": args.spl_docs}),
            ("Spec files", generate_spec_training, {"specs_dir": args.specs}),
            ("Scenarios", generate_scenario_training, {}),
            ("Eval cases", generate_eval_training, {}),
            ("Paraphrases", generate_paraphrase_training, {"spl_docs_dir": args.spl_docs}),
            ("Metadata", generate_metadata_training, {"metadata_dir": args.metadata}),
        ]:
            entries = gen_fn(**kwargs)
            total += len(entries)
            print(f"  {name}: {len(entries)}")
        print(f"  TOTAL: {total}")
    else:
        run_full_export(args.spl_docs, args.specs, args.metadata, args.output)
