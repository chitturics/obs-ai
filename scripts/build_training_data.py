#!/usr/bin/env python3
"""
Unified training data builder for continuous LLM improvement.

Combines all knowledge sources into training data for Ollama fine-tuning:
  1. Generated Q&A pairs (spec files, conf files, SPL commands)
  2. User feedback (liked/disliked queries from PostgreSQL)
  3. Organization repo configs
  4. Synthetic SPL examples

Outputs:
  - training_data/combined_training.jsonl  (Ollama chat format)
  - training_data/combined_training_openai.jsonl  (OpenAI format)
  - training_data/Modelfile  (ready for `ollama create`)
  - training_data/stats.json

Usage:
    python scripts/build_training_data.py
    python scripts/build_training_data.py --include-feedback
    python scripts/build_training_data.py --base-model llama3.1
    python scripts/build_training_data.py --auto  # for cron/scheduled runs
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
QA_DIR = PROJECT_ROOT / "qa_dataset"
OUTPUT_DIR = PROJECT_ROOT / "training_data"
FEEDBACK_LIKED = PROJECT_ROOT / "feedback" / "liked_queries.json"

SYSTEM_PROMPT = """You are a Splunk expert assistant with deep knowledge of Splunk configuration files (.conf/.spec), SPL (Search Processing Language), deployment architecture, and troubleshooting.

Key rules:
- Never use or suggest `index=*` — always specify the correct index.
- Prefer `| tstats` with CIM data models for performance.
- Use TERM() and PREFIX() to leverage index-time tokenization.
- When explaining configs, reference the relevant .spec file documentation.
- Provide complete, working SPL queries with proper field names.
- If unsure about the user's environment, ask clarifying questions."""


def load_qa_jsonl(filepath: Path) -> List[Dict]:
    """Load Q&A pairs from JSONL file."""
    if not filepath.exists():
        return []
    pairs = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                pairs.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return pairs


def load_feedback_liked() -> List[Dict]:
    """Load liked queries from feedback JSON file."""
    if not FEEDBACK_LIKED.exists():
        return []
    try:
        with open(FEEDBACK_LIKED, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Convert to training format
        pairs = []
        items = data if isinstance(data, list) else data.get("liked", [])
        for item in items:
            q = item.get("question", item.get("query", "")).strip()
            a = item.get("answer", item.get("response", "")).strip()
            if q and a:
                pairs.append({
                    "instruction": q,
                    "input": "",
                    "output": a,
                    "metadata": {"source_type": "feedback_liked", "source_file": "liked_queries.json"},
                })
        return pairs
    except Exception as e:
        logger.warning(f"Failed to load feedback: {e}")
        return []


def load_feedback_from_db() -> List[Dict]:
    """Load liked queries from PostgreSQL (if available)."""
    try:
        import psycopg2
        db_url = os.getenv("DATABASE_URL", "")
        if not db_url:
            return []
        conn = psycopg2.connect(db_url)
        cur = conn.cursor()
        cur.execute("SELECT question, answer FROM assistant_liked_queries ORDER BY created_at DESC LIMIT 5000")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        pairs = []
        for q, a in rows:
            if q and a:
                pairs.append({
                    "instruction": q.strip(),
                    "input": "",
                    "output": a.strip(),
                    "metadata": {"source_type": "feedback_db", "source_file": "postgres"},
                })
        logger.info(f"Loaded {len(pairs)} liked Q&A from PostgreSQL")
        return pairs
    except Exception as e:
        logger.debug(f"PostgreSQL feedback not available: {e}")
        return []


def to_ollama_chat(qa: Dict, system_prompt: str) -> str:
    """Convert Q&A to Ollama chat training format."""
    question = qa.get("instruction", "")
    answer = qa.get("output", "")
    return json.dumps({
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
    }, ensure_ascii=False)


def to_openai_chat(qa: Dict, system_prompt: str) -> str:
    """Convert Q&A to OpenAI fine-tuning format."""
    question = qa.get("instruction", "")
    answer = qa.get("output", "")
    return json.dumps({
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
    }, ensure_ascii=False)


def generate_modelfile(base_model: str, training_file: str) -> str:
    """Generate Ollama Modelfile for creating a fine-tuned model."""
    return f"""# Auto-generated Modelfile for Splunk assistant
# Usage: ollama create splunk-assistant -f Modelfile

FROM {base_model}

PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER num_ctx 4096

SYSTEM \"\"\"{SYSTEM_PROMPT}\"\"\"

# Training data is in: {training_file}
# To fine-tune with Ollama (when supported):
#   ollama create splunk-assistant --file Modelfile --training {training_file}
#
# For now, use the SYSTEM prompt above with the base model:
#   ollama create splunk-assistant -f Modelfile
"""


def main():
    parser = argparse.ArgumentParser(description="Build unified training data")
    parser.add_argument("--include-feedback", action="store_true", help="Include user feedback")
    parser.add_argument("--include-db-feedback", action="store_true", help="Include PostgreSQL feedback")
    parser.add_argument("--base-model", default="llama3.1", help="Base model for Modelfile")
    parser.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Output directory")
    parser.add_argument("--auto", action="store_true", help="Non-interactive mode for cron")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_pairs: List[Dict] = []
    stats = {"sources": {}}

    # 1. Load generated Q&A pairs (primary knowledge source)
    for name in ["specs_qa.jsonl", "confs_qa.jsonl", "commands_qa.jsonl"]:
        filepath = QA_DIR / name
        pairs = load_qa_jsonl(filepath)
        if pairs:
            all_pairs.extend(pairs)
            stats["sources"][name] = len(pairs)
            logger.info(f"Loaded {len(pairs)} pairs from {name}")

    # 2. Load existing training JSONL if present
    # Load additional training JSONL files (legacy and LLM-generated)
    for legacy_name in ["qa_splunk_llm.jsonl", "qa_splunk_generated.jsonl",
                        "qa_inputs_conf_llm.jsonl", "qa_inputs_conf_generated.jsonl"]:
        extra = load_qa_jsonl(QA_DIR / legacy_name)
        if extra:
            all_pairs.extend(extra)
            stats["sources"][legacy_name] = len(extra)
            logger.info(f"Loaded {len(extra)} pairs from {legacy_name}")

    # 3. Load user feedback (high-value: human-validated)
    if args.include_feedback or args.auto:
        feedback_pairs = load_feedback_liked()
        if feedback_pairs:
            all_pairs.extend(feedback_pairs)
            stats["sources"]["feedback_liked"] = len(feedback_pairs)
            logger.info(f"Loaded {len(feedback_pairs)} liked Q&A from feedback file")

    if args.include_db_feedback or args.auto:
        db_pairs = load_feedback_from_db()
        if db_pairs:
            all_pairs.extend(db_pairs)
            stats["sources"]["feedback_db"] = len(db_pairs)

    # Deduplicate by question
    seen = set()
    unique_pairs = []
    for qa in all_pairs:
        key = qa.get("instruction", "").strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique_pairs.append(qa)
    logger.info(f"Deduplicated: {len(all_pairs)} -> {len(unique_pairs)} unique pairs")
    all_pairs = unique_pairs

    stats["total_pairs"] = len(all_pairs)
    stats["deduplicated_from"] = len(seen)

    # Write Ollama chat format
    ollama_file = output_dir / "combined_training.jsonl"
    with open(ollama_file, "w", encoding="utf-8") as f:
        for qa in all_pairs:
            f.write(to_ollama_chat(qa, SYSTEM_PROMPT) + "\n")
    logger.info(f"Wrote {len(all_pairs)} examples to {ollama_file}")

    # Write OpenAI format
    openai_file = output_dir / "combined_training_openai.jsonl"
    with open(openai_file, "w", encoding="utf-8") as f:
        for qa in all_pairs:
            f.write(to_openai_chat(qa, SYSTEM_PROMPT) + "\n")

    # Generate Modelfile
    modelfile = output_dir / "Modelfile"
    with open(modelfile, "w", encoding="utf-8") as f:
        f.write(generate_modelfile(args.base_model, str(ollama_file)))
    logger.info(f"Generated Modelfile at {modelfile}")

    # Save stats
    stats_file = output_dir / "stats.json"
    with open(stats_file, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)

    # Summary
    print(f"\nTraining data built successfully:")
    print(f"  Total pairs: {len(all_pairs)}")
    for source, count in sorted(stats["sources"].items(), key=lambda x: -x[1]):
        print(f"    {source}: {count}")
    print(f"\nOutput files:")
    print(f"  {ollama_file}")
    print(f"  {openai_file}")
    print(f"  {modelfile}")
    print(f"\nTo create the model with Ollama:")
    print(f"  ollama create splunk-assistant -f {modelfile}")


if __name__ == "__main__":
    main()
