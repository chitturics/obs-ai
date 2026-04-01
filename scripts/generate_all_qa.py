#!/usr/bin/env python3
"""
Generate Q&A pairs + summaries from all Splunk spec files, conf files, and SPL commands.

Usage:
    python scripts/generate_all_qa.py
    python scripts/generate_all_qa.py --output-dir ./qa_dataset
    python scripts/generate_all_qa.py --specs-only
    python scripts/generate_all_qa.py --commands-only

Outputs:
    qa_dataset/
        specs_qa.jsonl          - Q&A from .spec files
        confs_qa.jsonl          - Q&A from .conf files
        commands_qa.jsonl       - Q&A from searchbnf.conf commands
        all_qa.jsonl            - Combined (instruction fine-tuning format)
        all_qa_openai.jsonl     - Combined (OpenAI chat format)
        all_qa.csv              - Combined CSV for review
        summaries/
            specs_summary.md    - Summary of all spec files
            confs_summary.md    - Summary of all conf files
            commands_summary.md - Summary of all SPL commands
"""

import argparse
import csv
import json
import logging
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class QAPair:
    question: str
    answer: str
    source_file: str
    source_type: str  # spec, conf, command
    stanza: Optional[str] = None
    confidence: float = 0.9
    metadata: Optional[Dict] = None


@dataclass
class CommandInfo:
    name: str
    shortdesc: str = ""
    description: str = ""
    syntax: str = ""
    simplesyntax: str = ""
    usage: str = ""
    category: str = ""
    related: str = ""
    tags: str = ""
    note: str = ""
    examples: List[Tuple[str, str]] = field(default_factory=list)  # (example, comment)


# ---------------------------------------------------------------------------
# searchbnf.conf parser
# ---------------------------------------------------------------------------

def parse_searchbnf(path: str) -> List[CommandInfo]:
    """Parse searchbnf.conf and extract command definitions."""
    commands = []
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # Split into stanzas
    stanza_re = re.compile(r"^\[([^\]]+)\]\s*$", re.MULTILINE)
    positions = [(m.group(1), m.start(), m.end()) for m in stanza_re.finditer(content)]

    for idx, (name, _, end) in enumerate(positions):
        # Only process *-command stanzas
        if not name.endswith("-command"):
            continue

        # Get stanza body
        next_start = positions[idx + 1][1] if idx + 1 < len(positions) else len(content)
        body = content[end:next_start]

        cmd = CommandInfo(name=name.replace("-command", ""))

        # Parse key = value (with line continuation via \)
        lines = body.split("\n")
        current_key = None
        current_val = []

        def flush():
            nonlocal current_key, current_val
            if current_key:
                val = " ".join(current_val).strip()
                # Clean up description formatting
                val = val.replace("\\p\\", "\n\n").replace("\\i\\", "\n  ")
                val = re.sub(r"\s+", " ", val).strip()
                setattr_cmd(cmd, current_key, val)
            current_key = None
            current_val = []

        def setattr_cmd(cmd, key, val):
            if key == "shortdesc":
                cmd.shortdesc = val
            elif key == "description":
                cmd.description = val
            elif key == "syntax":
                cmd.syntax = val
            elif key == "simplesyntax":
                cmd.simplesyntax = val
            elif key == "usage":
                cmd.usage = val
            elif key in ("category", "external category"):
                cmd.category = val
            elif key == "related":
                cmd.related = val
            elif key == "tags":
                cmd.tags = val
            elif key == "note":
                cmd.note = val
            elif key.startswith("example"):
                # example1, examplecheat1, etc.
                pass  # handled separately
            elif key.startswith("comment"):
                pass  # handled with examples

        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                flush()
                continue

            kv_match = re.match(r"^([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.*)", stripped)
            if kv_match:
                flush()
                current_key = kv_match.group(1).strip()
                val = kv_match.group(2).strip()
                if val.endswith("\\"):
                    current_val = [val[:-1]]
                else:
                    current_val = [val]
                    flush()
            elif current_val and stripped:
                # Continuation line
                if stripped.endswith("\\"):
                    current_val.append(stripped[:-1])
                else:
                    current_val.append(stripped)
                    flush()
        flush()

        # Parse examples separately
        example_map = {}
        comment_map = {}
        for line in lines:
            stripped = line.strip()
            em = re.match(r"^(example\w*\d+)\s*=\s*(.*)", stripped)
            if em:
                example_map[em.group(1)] = em.group(2).strip()
            cm = re.match(r"^(comment\w*\d+)\s*=\s*(.*)", stripped)
            if cm:
                comment_map[cm.group(1)] = cm.group(2).strip()

        for key in sorted(example_map.keys()):
            ex = example_map[key]
            # Find matching comment (example1 -> comment1, examplecheat1 -> commentcheat1)
            comment_key = key.replace("example", "comment")
            comment = comment_map.get(comment_key, "")
            cmd.examples.append((ex, comment))

        # Only include public commands
        if cmd.usage and cmd.usage not in ("public", ""):
            if cmd.usage in ("deprecated", "internal"):
                continue

        if cmd.shortdesc or cmd.description:
            commands.append(cmd)

    return commands


# ---------------------------------------------------------------------------
# Spec/Conf file parser (lightweight)
# ---------------------------------------------------------------------------

def parse_stanzas(content: str) -> List[Tuple[str, str]]:
    """Parse conf/spec content into (stanza_name, body) tuples."""
    stanzas = []
    current_name = "__preamble__"
    current_lines = []

    for line in content.split("\n"):
        m = re.match(r"^\[([^\]]+)\]", line)
        if m:
            if current_lines:
                stanzas.append((current_name, "\n".join(current_lines)))
            current_name = m.group(1)
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        stanzas.append((current_name, "\n".join(current_lines)))

    return stanzas


def extract_settings_from_body(body: str) -> List[Tuple[str, str]]:
    """Extract setting = value pairs with following comment lines as description."""
    settings = []
    lines = body.split("\n")
    i = 0
    while i < len(lines):
        m = re.match(r"^([a-zA-Z_][a-zA-Z0-9_.-]*)\s*=\s*(.*)", lines[i])
        if m:
            name = m.group(1)
            desc_lines = [lines[i]]
            i += 1
            # Collect following comment/description lines
            while i < len(lines):
                sl = lines[i].strip()
                if sl.startswith("#") or sl.startswith("*"):
                    desc_lines.append(lines[i])
                    i += 1
                elif sl == "":
                    i += 1
                    break
                else:
                    break
            settings.append((name, "\n".join(desc_lines)))
        else:
            i += 1
    return settings


# ---------------------------------------------------------------------------
# Q&A generators
# ---------------------------------------------------------------------------

def generate_spec_qa(spec_dir: str) -> Tuple[List[QAPair], str]:
    """Generate Q&A from all .spec files and return (pairs, summary_markdown)."""
    pairs = []
    summaries = []
    spec_files = sorted(Path(spec_dir).glob("*.spec"))

    for spec_path in spec_files:
        filename = spec_path.name
        conf_name = filename.replace(".spec", "")

        try:
            content = spec_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.warning(f"Cannot read {spec_path}: {e}")
            continue

        stanzas = parse_stanzas(content)
        stanza_names = [s[0] for s in stanzas if s[0] != "__preamble__"]

        # File-level summary
        preamble = ""
        for name, body in stanzas:
            if name == "__preamble__":
                # Extract overview from comments
                overview_lines = [l.lstrip("# ").strip() for l in body.split("\n")
                                  if l.strip().startswith("#") and len(l.strip()) > 3]
                preamble = " ".join(overview_lines[:5])
                break

        summary_entry = f"### {conf_name}\n\n"
        if preamble:
            summary_entry += f"{preamble[:300]}\n\n"
        if stanza_names:
            summary_entry += f"**Stanzas ({len(stanza_names)}):** "
            summary_entry += ", ".join(f"`[{s}]`" for s in stanza_names[:15])
            if len(stanza_names) > 15:
                summary_entry += f" ... and {len(stanza_names) - 15} more"
            summary_entry += "\n\n"
        summaries.append(summary_entry)

        # Q&A: Overview question
        pairs.append(QAPair(
            question=f"What is {conf_name} used for in Splunk?",
            answer=f"{conf_name} in Splunk:\n\n{preamble[:500]}\n\nKey stanzas: {', '.join(f'[{s}]' for s in stanza_names[:10])}" if preamble else f"{conf_name} contains {len(stanza_names)} configuration stanzas: {', '.join(f'[{s}]' for s in stanza_names[:10])}",
            source_file=filename,
            source_type="spec",
            confidence=0.9,
        ))

        # Q&A per stanza
        for stanza_name, body in stanzas:
            if stanza_name == "__preamble__":
                continue
            body_clean = body.strip()
            if not body_clean or len(body_clean) < 10:
                continue

            # Truncate very large stanzas
            body_trunc = body_clean[:1500]

            # What is this stanza?
            pairs.append(QAPair(
                question=f"What is the [{stanza_name}] stanza in {conf_name}?",
                answer=f"The [{stanza_name}] stanza in {conf_name}:\n\n{body_trunc}",
                source_file=filename,
                source_type="spec",
                stanza=stanza_name,
                confidence=0.9,
            ))

            # How to configure?
            pairs.append(QAPair(
                question=f"How do I configure [{stanza_name}] in {conf_name}?",
                answer=f"To configure [{stanza_name}] in {conf_name}, add the following to your local {conf_name}:\n\n[{stanza_name}]\n{body_trunc}",
                source_file=filename,
                source_type="spec",
                stanza=stanza_name,
                confidence=0.9,
            ))

            # Per-setting Q&A (top 5)
            settings = extract_settings_from_body(body)
            for setting_name, setting_desc in settings[:5]:
                pairs.append(QAPair(
                    question=f"What does '{setting_name}' do in {conf_name} [{stanza_name}]?",
                    answer=f"In {conf_name} [{stanza_name}]:\n\n{setting_desc}",
                    source_file=filename,
                    source_type="spec",
                    stanza=stanza_name,
                    confidence=0.85,
                ))

    summary_md = f"# Splunk Spec Files Summary\n\n**Total spec files:** {len(spec_files)}\n**Total Q&A pairs:** {len(pairs)}\n\n"
    summary_md += "\n".join(summaries)
    return pairs, summary_md


def generate_conf_qa(conf_dir: str) -> Tuple[List[QAPair], str]:
    """Generate Q&A from all .conf files (default configs)."""
    pairs = []
    summaries = []
    conf_files = sorted(Path(conf_dir).glob("*.conf"))

    for conf_path in conf_files:
        filename = conf_path.name
        # Skip searchbnf.conf — handled separately as commands
        if filename == "searchbnf.conf":
            continue

        try:
            content = conf_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.warning(f"Cannot read {conf_path}: {e}")
            continue

        stanzas = parse_stanzas(content)
        real_stanzas = [(n, b) for n, b in stanzas if n != "__preamble__"]

        summary_entry = f"### {filename}\n\n"
        summary_entry += f"**Stanzas ({len(real_stanzas)}):** "
        names = [s[0] for s in real_stanzas[:15]]
        summary_entry += ", ".join(f"`[{n}]`" for n in names)
        if len(real_stanzas) > 15:
            summary_entry += f" ... and {len(real_stanzas) - 15} more"
        summary_entry += "\n\n"
        summaries.append(summary_entry)

        # Overview Q&A
        pairs.append(QAPair(
            question=f"What are the default settings in {filename}?",
            answer=f"The default {filename} contains {len(real_stanzas)} stanzas: {', '.join(f'[{n}]' for n, _ in real_stanzas[:10])}",
            source_file=filename,
            source_type="conf",
            confidence=0.85,
        ))

        # Per stanza
        for stanza_name, body in real_stanzas:
            body_clean = body.strip()
            if not body_clean or len(body_clean) < 10:
                continue

            pairs.append(QAPair(
                question=f"What does the [{stanza_name}] stanza contain in default {filename}?",
                answer=f"Default [{stanza_name}] in {filename}:\n\n{body_clean[:1000]}",
                source_file=filename,
                source_type="conf",
                stanza=stanza_name,
                confidence=0.85,
            ))

    summary_md = f"# Splunk Default Conf Files Summary\n\n**Total conf files:** {len(conf_files) - 1}\n**Total Q&A pairs:** {len(pairs)}\n\n"
    summary_md += "\n".join(summaries)
    return pairs, summary_md


def generate_command_qa(searchbnf_path: str) -> Tuple[List[QAPair], str]:
    """Generate Q&A from searchbnf.conf SPL commands."""
    commands = parse_searchbnf(searchbnf_path)
    pairs = []
    summaries = []

    for cmd in commands:
        desc = cmd.description or cmd.shortdesc
        syntax = cmd.simplesyntax or cmd.syntax

        summary_entry = f"### {cmd.name}\n\n"
        if cmd.shortdesc:
            summary_entry += f"{cmd.shortdesc}\n\n"
        if syntax:
            summary_entry += f"**Syntax:** `{syntax[:200]}`\n\n"
        if cmd.category:
            summary_entry += f"**Category:** {cmd.category}\n\n"
        if cmd.examples:
            summary_entry += f"**Examples:** {len(cmd.examples)}\n\n"
        summaries.append(summary_entry)

        # Q1: What does this command do?
        if desc:
            answer = f"The `{cmd.name}` command in Splunk: {desc}"
            if syntax:
                answer += f"\n\nSyntax: `{syntax}`"
            pairs.append(QAPair(
                question=f"What does the {cmd.name} command do in Splunk?",
                answer=answer,
                source_file="searchbnf.conf",
                source_type="command",
                confidence=0.95,
                metadata={"command": cmd.name, "category": cmd.category},
            ))

        # Q2: How to use / syntax
        if syntax:
            syntax_answer = f"Syntax for the `{cmd.name}` command:\n\n```\n{syntax}\n```"
            if cmd.shortdesc:
                syntax_answer += f"\n\n{cmd.shortdesc}"
            pairs.append(QAPair(
                question=f"What is the syntax for the {cmd.name} command in Splunk?",
                answer=syntax_answer,
                source_file="searchbnf.conf",
                source_type="command",
                confidence=0.95,
                metadata={"command": cmd.name},
            ))

        # Q3: Examples
        if cmd.examples:
            examples_text = "\n".join(
                f"- `{ex}`" + (f" — {comment}" if comment else "")
                for ex, comment in cmd.examples[:5]
            )
            pairs.append(QAPair(
                question=f"Show me examples of using the {cmd.name} command in Splunk.",
                answer=f"Examples of the `{cmd.name}` command:\n\n{examples_text}",
                source_file="searchbnf.conf",
                source_type="command",
                confidence=0.9,
                metadata={"command": cmd.name},
            ))

        # Q4: Related commands
        if cmd.related:
            pairs.append(QAPair(
                question=f"What commands are related to {cmd.name} in Splunk?",
                answer=f"Commands related to `{cmd.name}`: {cmd.related}",
                source_file="searchbnf.conf",
                source_type="command",
                confidence=0.85,
                metadata={"command": cmd.name},
            ))

    summary_md = f"# Splunk SPL Commands Summary\n\n**Total commands:** {len(commands)}\n**Total Q&A pairs:** {len(pairs)}\n\n"
    # Group by category
    cats = {}
    for cmd in commands:
        cat = cmd.category or "uncategorized"
        cats.setdefault(cat, []).append(cmd.name)
    summary_md += "## Commands by Category\n\n"
    for cat in sorted(cats.keys()):
        summary_md += f"**{cat}:** {', '.join(sorted(cats[cat]))}\n\n"
    summary_md += "## Individual Commands\n\n"
    summary_md += "\n".join(summaries)
    return pairs, summary_md


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------

def write_jsonl(pairs: List[QAPair], path: Path, fmt: str = "instruction"):
    """Write Q&A pairs as JSONL."""
    with open(path, "w", encoding="utf-8") as f:
        for p in pairs:
            if fmt == "openai":
                record = {
                    "messages": [
                        {"role": "system", "content": "You are a Splunk expert assistant. Answer questions about SPL commands, .conf configuration files, and Splunk administration."},
                        {"role": "user", "content": p.question},
                        {"role": "assistant", "content": p.answer},
                    ]
                }
            else:
                record = {
                    "instruction": p.question,
                    "input": "",
                    "output": p.answer,
                    "metadata": {
                        "source_file": p.source_file,
                        "source_type": p.source_type,
                        "stanza": p.stanza,
                        "confidence": p.confidence,
                        **(p.metadata or {}),
                    },
                }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info(f"Wrote {len(pairs)} pairs to {path}")


def write_csv(pairs: List[QAPair], path: Path):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["question", "answer", "source_file", "source_type", "stanza", "confidence"])
        for p in pairs:
            writer.writerow([p.question, p.answer, p.source_file, p.source_type, p.stanza or "", p.confidence])
    logger.info(f"Wrote {len(pairs)} pairs to {path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Generate Q&A pairs from Splunk specs, confs, and commands")
    parser.add_argument("--specs-dir", default="ingest_specs", help="Directory with .spec and .conf files")
    parser.add_argument("--output-dir", default="qa_dataset", help="Output directory")
    parser.add_argument("--specs-only", action="store_true")
    parser.add_argument("--confs-only", action="store_true")
    parser.add_argument("--commands-only", action="store_true")
    args = parser.parse_args()

    specs_dir = Path(args.specs_dir)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    summaries_dir = out_dir / "summaries"
    summaries_dir.mkdir(exist_ok=True)

    do_all = not (args.specs_only or args.confs_only or args.commands_only)
    all_pairs: List[QAPair] = []

    # --- Specs ---
    if do_all or args.specs_only:
        logger.info("Processing .spec files...")
        spec_pairs, spec_summary = generate_spec_qa(str(specs_dir))
        write_jsonl(spec_pairs, out_dir / "specs_qa.jsonl")
        (summaries_dir / "specs_summary.md").write_text(spec_summary, encoding="utf-8")
        all_pairs.extend(spec_pairs)
        logger.info(f"Specs: {len(spec_pairs)} Q&A pairs")

    # --- Confs ---
    if do_all or args.confs_only:
        logger.info("Processing .conf files...")
        conf_pairs, conf_summary = generate_conf_qa(str(specs_dir))
        write_jsonl(conf_pairs, out_dir / "confs_qa.jsonl")
        (summaries_dir / "confs_summary.md").write_text(conf_summary, encoding="utf-8")
        all_pairs.extend(conf_pairs)
        logger.info(f"Confs: {len(conf_pairs)} Q&A pairs")

    # --- Commands ---
    if do_all or args.commands_only:
        searchbnf = specs_dir / "searchbnf.conf"
        if searchbnf.exists():
            logger.info("Processing searchbnf.conf...")
            cmd_pairs, cmd_summary = generate_command_qa(str(searchbnf))
            write_jsonl(cmd_pairs, out_dir / "commands_qa.jsonl")
            (summaries_dir / "commands_summary.md").write_text(cmd_summary, encoding="utf-8")
            all_pairs.extend(cmd_pairs)
            logger.info(f"Commands: {len(cmd_pairs)} Q&A pairs")
        else:
            logger.warning(f"searchbnf.conf not found at {searchbnf}")

    # --- Combined outputs ---
    if all_pairs:
        write_jsonl(all_pairs, out_dir / "all_qa.jsonl", fmt="instruction")
        write_jsonl(all_pairs, out_dir / "all_qa_openai.jsonl", fmt="openai")
        write_csv(all_pairs, out_dir / "all_qa.csv")

    # --- Stats ---
    by_type = {}
    for p in all_pairs:
        by_type[p.source_type] = by_type.get(p.source_type, 0) + 1

    print(f"\n{'='*60}")
    print(f"Q&A Dataset Generation Complete")
    print(f"{'='*60}")
    print(f"Total Q&A pairs: {len(all_pairs)}")
    for st, count in sorted(by_type.items()):
        print(f"  {st}: {count}")
    print(f"\nOutput directory: {out_dir}")
    print(f"  all_qa.jsonl         - Instruction format (fine-tuning)")
    print(f"  all_qa_openai.jsonl  - OpenAI chat format")
    print(f"  all_qa.csv           - CSV for review")
    print(f"  summaries/           - Markdown summaries")


if __name__ == "__main__":
    main()
