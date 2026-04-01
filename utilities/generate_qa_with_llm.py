#!/usr/bin/env python3
"""
Generate Q&A Dataset Using LLM API

Uses the configured LLM API (Ollama by default) to generate high-quality,
contextual Q&A pairs from Splunk documentation. This produces better results
than template-based generation because the LLM understands Splunk concepts
and can create natural, diverse questions.

Prerequisites:
    pip install httpx

Usage:
    # Using default Ollama endpoint
    python generate_qa_with_llm.py --max-files 10

    # Custom LLM endpoint
    LLM_API_BASE_URL=http://localhost:11434 python generate_qa_with_llm.py

    # Process all files
    python generate_qa_with_llm.py
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from typing import List, Dict, Optional
import time

try:
    import httpx
except ImportError:
    print("ERROR: httpx package not installed")
    print("Install with: pip install httpx")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class LLMQAGenerator:
    """Generate Q&A pairs using LLM API (Ollama or compatible)"""

    def __init__(self, base_url: Optional[str] = None, model: str = "qwen2.5:3b"):
        self.base_url = base_url or os.getenv("LLM_API_BASE_URL", "http://localhost:11434")
        self.model = model
        self.client = httpx.Client(base_url=self.base_url, timeout=120)
        self.qa_pairs: List[Dict] = []
        self.total_tokens = 0

    def generate_qa_from_spec_file(self, file_path: str, max_qa: int = 10) -> List[Dict]:
        """Generate Q&A pairs from a .conf.spec file using LLM"""

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            filename = Path(file_path).name

            # Limit content size to avoid token limits
            if len(content) > 8000:
                logger.warning(f"  File too large ({len(content)} chars), truncating to 8000 chars")
                content = content[:8000] + "\n\n[... truncated ...]"

            prompt = self._build_spec_prompt(content, filename, max_qa)
            response_text = self._call_llm(prompt)
            pairs = self._parse_llm_response(response_text, filename, "spec")
            return pairs

        except Exception as e:
            logger.error(f"Failed to generate Q&A from {file_path}: {e}")
            return []

    def generate_qa_from_command_file(self, file_path: str, max_qa: int = 5) -> List[Dict]:
        """Generate Q&A pairs from SPL command documentation using LLM"""

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            filename = Path(file_path).name
            command_name = filename.replace('.md', '').replace('.txt', '')

            if len(content) > 6000:
                logger.warning(f"  File too large ({len(content)} chars), truncating to 6000 chars")
                content = content[:6000] + "\n\n[... truncated ...]"

            prompt = self._build_command_prompt(content, command_name, max_qa)
            response_text = self._call_llm(prompt)
            pairs = self._parse_llm_response(response_text, filename, "command")
            return pairs

        except Exception as e:
            logger.error(f"Failed to generate Q&A from {file_path}: {e}")
            return []

    def generate_qa_from_conf_file(self, file_path: str, max_qa: int = 8) -> List[Dict]:
        """Generate Q&A pairs from repository .conf files using LLM"""

        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            rel_path = str(Path(file_path))
            if 'repo' in rel_path:
                rel_path = rel_path[rel_path.index('repo'):]

            filename = Path(file_path).name

            if len(content) > 6000:
                logger.warning(f"  File too large ({len(content)} chars), truncating to 6000 chars")
                content = content[:6000] + "\n\n[... truncated ...]"

            prompt = self._build_conf_prompt(content, filename, rel_path, max_qa)
            response_text = self._call_llm(prompt)
            pairs = self._parse_llm_response(response_text, filename, "conf")
            return pairs

        except Exception as e:
            logger.error(f"Failed to generate Q&A from {file_path}: {e}")
            return []

    def _call_llm(self, prompt: str) -> str:
        """Call the LLM API and return the response text."""
        response = self.client.post("/api/generate", json={
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.7, "num_predict": 4096},
        })
        response.raise_for_status()
        return response.json().get("response", "")

    def _build_spec_prompt(self, content: str, filename: str, max_qa: int) -> str:
        """Build prompt for .conf.spec file"""
        return f"""You are a Splunk expert. Generate {max_qa} high-quality question-answer pairs from this Splunk configuration specification file.

Filename: {filename}

Content:
{content}

Generate diverse questions that a Splunk administrator or developer might ask, such as:
- "What is the [stanza_name] stanza used for?"
- "How do I configure X in {filename}?"
- "What does the 'setting_name' setting do?"
- "What are the valid values for X?"
- "Can you show an example of configuring X?"

For each Q&A pair, provide:
1. A natural, specific question
2. A clear, accurate answer with examples from the file
3. Include relevant stanza names and settings in the answer

Format your response as a JSON array:
[
  {{
    "question": "Your question here",
    "answer": "Detailed answer with examples",
    "stanza": "stanza_name if applicable",
    "confidence": 0.9
  }},
  ...
]

Only return the JSON array, no other text."""

    def _build_command_prompt(self, content: str, command_name: str, max_qa: int) -> str:
        """Build prompt for SPL command documentation"""
        return f"""You are a Splunk expert. Generate {max_qa} high-quality question-answer pairs from this SPL command documentation.

Command: {command_name}

Documentation:
{content}

Generate diverse questions that a Splunk user might ask, such as:
- "What does the {command_name} command do?"
- "How do I use {command_name} in a search?"
- "What arguments does {command_name} accept?"
- "Can you show an example of using {command_name}?"
- "When should I use {command_name}?"

Format your response as a JSON array:
[
  {{
    "question": "Your question here",
    "answer": "Detailed answer with SPL examples",
    "confidence": 0.9
  }},
  ...
]

Only return the JSON array, no other text."""

    def _build_conf_prompt(self, content: str, filename: str, rel_path: str, max_qa: int) -> str:
        """Build prompt for repository .conf files"""
        return f"""You are a Splunk expert. Generate {max_qa} high-quality question-answer pairs from this Splunk configuration file.

File: {rel_path}
Filename: {filename}

Content:
{content}

This is a real configuration file from an organization's Splunk deployment. Generate practical questions that show how these settings are used.

Format your response as a JSON array:
[
  {{
    "question": "Your question here",
    "answer": "Answer explaining the configuration",
    "stanza": "stanza_name if applicable",
    "confidence": 0.9
  }},
  ...
]

Only return the JSON array, no other text."""

    def _parse_llm_response(self, response_text: str, filename: str, source_type: str) -> List[Dict]:
        """Parse LLM JSON response into Q&A pairs"""
        try:
            start_idx = response_text.find('[')
            end_idx = response_text.rfind(']') + 1

            if start_idx == -1 or end_idx == 0:
                logger.error(f"  No JSON array found in response")
                return []

            json_str = response_text[start_idx:end_idx]
            pairs = json.loads(json_str)

            for pair in pairs:
                pair['source_file'] = filename
                pair['source_type'] = source_type
                pair['generated_by'] = 'llm'

            return pairs

        except json.JSONDecodeError as e:
            logger.error(f"  Failed to parse JSON response: {e}")
            logger.debug(f"  Response was: {response_text[:200]}")
            return []

    def save_jsonl(self, output_file: str):
        """Save Q&A pairs as JSONL"""
        with open(output_file, 'w', encoding='utf-8') as f:
            for pair in self.qa_pairs:
                record = {
                    "instruction": pair['question'],
                    "input": "",
                    "output": pair['answer'],
                    "metadata": {
                        "source_file": pair.get('source_file'),
                        "source_type": pair.get('source_type'),
                        "stanza": pair.get('stanza'),
                        "confidence": pair.get('confidence', 0.9),
                        "generated_by": pair.get('generated_by', 'llm')
                    }
                }
                f.write(json.dumps(record, ensure_ascii=False) + '\n')

        logger.info(f"Saved {len(self.qa_pairs)} Q&A pairs to {output_file}")

    def save_csv(self, output_file: str):
        """Save Q&A pairs as CSV"""
        import csv

        with open(output_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow([
                'question', 'answer', 'source_file', 'source_type',
                'stanza', 'confidence', 'generated_by'
            ])

            for pair in self.qa_pairs:
                writer.writerow([
                    pair['question'],
                    pair['answer'],
                    pair.get('source_file', ''),
                    pair.get('source_type', ''),
                    pair.get('stanza', ''),
                    pair.get('confidence', 0.9),
                    pair.get('generated_by', 'llm')
                ])

        logger.info(f"Saved {len(self.qa_pairs)} Q&A pairs to {output_file}")


def find_files(root_dir: str, pattern: str) -> List[str]:
    """Find all files matching pattern"""
    files = []
    root = Path(root_dir)
    if root.exists():
        if '*' in pattern:
            files = [str(f) for f in root.rglob(pattern) if f.is_file()]
        else:
            files = [str(f) for f in root.glob(pattern) if f.is_file()]
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(
        description='Generate Q&A dataset using LLM API',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with 5 spec files
  python generate_qa_with_llm.py --max-files 5 --specs-only

  # Generate from all sources
  python generate_qa_with_llm.py

  # Custom LLM endpoint
  LLM_API_BASE_URL=http://localhost:11434 python generate_qa_with_llm.py
        """
    )
    parser.add_argument('--output-dir', default='./qa_dataset', help='Output directory')
    parser.add_argument('--max-files', type=int, default=None, help='Max files per type')
    parser.add_argument('--specs-only', action='store_true', help='Only process .spec files')
    parser.add_argument('--commands-only', action='store_true', help='Only process SPL commands')
    parser.add_argument('--repo-only', action='store_true', help='Only process .conf files')
    parser.add_argument('--model', default='qwen2.5:3b', help='LLM model to use')
    parser.add_argument('--base-url', default=None, help='LLM API base URL')

    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("Q&A Dataset Generation with LLM")
    logger.info("=" * 80)
    logger.info(f"Model: {args.model}")
    logger.info(f"Output directory: {args.output_dir}")

    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    try:
        generator = LLMQAGenerator(base_url=args.base_url, model=args.model)
    except Exception as e:
        logger.error(f"Failed to initialize LLM client: {e}")
        return 1

    # Process .conf.spec files
    if not args.commands_only and not args.repo_only:
        logger.info("\n" + "=" * 80)
        logger.info("[1/3] Processing .conf.spec files")
        logger.info("=" * 80)

        spec_files = find_files('./ingest_specs', '*.spec')
        if args.max_files:
            spec_files = spec_files[:args.max_files]

        logger.info(f"Found {len(spec_files)} .spec files")

        for i, file_path in enumerate(spec_files, 1):
            logger.info(f"  [{i}/{len(spec_files)}] {Path(file_path).name}")
            pairs = generator.generate_qa_from_spec_file(file_path, max_qa=10)
            generator.qa_pairs.extend(pairs)
            logger.info(f"      -> Generated {len(pairs)} Q&A pairs")
            time.sleep(0.5)

    # Process SPL command documentation
    if not args.specs_only and not args.repo_only:
        logger.info("\n" + "=" * 80)
        logger.info("[2/3] Processing SPL command documentation")
        logger.info("=" * 80)

        command_dir = './spl_docs'
        if Path(command_dir).exists():
            command_files = find_files(command_dir, '*.md')
            command_files.extend(find_files(command_dir, '*.txt'))
            if args.max_files:
                command_files = command_files[:args.max_files]

            logger.info(f"Found {len(command_files)} command files")

            for i, file_path in enumerate(command_files, 1):
                logger.info(f"  [{i}/{len(command_files)}] {Path(file_path).name}")
                pairs = generator.generate_qa_from_command_file(file_path, max_qa=5)
                generator.qa_pairs.extend(pairs)
                logger.info(f"      -> Generated {len(pairs)} Q&A pairs")
                time.sleep(0.5)
        else:
            logger.warning(f"Commands directory not found: {command_dir}")

    # Process repository .conf files
    if not args.specs_only and not args.commands_only:
        logger.info("\n" + "=" * 80)
        logger.info("[3/3] Processing repository .conf files")
        logger.info("=" * 80)

        repo_dir = './public/documents/repo'
        if Path(repo_dir).exists():
            conf_files = find_files(repo_dir, '*.conf')
            if args.max_files:
                conf_files = conf_files[:args.max_files]

            logger.info(f"Found {len(conf_files)} .conf files")

            for i, file_path in enumerate(conf_files, 1):
                rel_path = Path(file_path).relative_to(repo_dir)
                logger.info(f"  [{i}/{len(conf_files)}] {rel_path}")
                pairs = generator.generate_qa_from_conf_file(file_path, max_qa=8)
                generator.qa_pairs.extend(pairs)
                logger.info(f"      -> Generated {len(pairs)} Q&A pairs")
                time.sleep(0.5)
        else:
            logger.warning(f"Repository directory not found: {repo_dir}")

    # Statistics
    logger.info("\n" + "=" * 80)
    logger.info("Generation Statistics")
    logger.info("=" * 80)
    logger.info(f"Total Q&A pairs: {len(generator.qa_pairs)}")

    by_type = {}
    for pair in generator.qa_pairs:
        src_type = pair.get('source_type', 'unknown')
        by_type[src_type] = by_type.get(src_type, 0) + 1

    logger.info(f"\nBy source type:")
    for src_type, count in sorted(by_type.items()):
        logger.info(f"  {src_type:15s}: {count:6d} pairs")

    if len(generator.qa_pairs) == 0:
        logger.error("\nNo Q&A pairs were generated!")
        return 1

    # Save output files
    logger.info("\n" + "=" * 80)
    logger.info("Saving Output Files")
    logger.info("=" * 80)

    jsonl_file = str(Path(args.output_dir) / 'qa_dataset.jsonl')
    csv_file = str(Path(args.output_dir) / 'qa_dataset.csv')

    generator.save_jsonl(jsonl_file)
    generator.save_csv(csv_file)

    logger.info(f"\n[OK] JSONL: {jsonl_file}")
    logger.info(f"[OK] CSV: {csv_file}")
    logger.info("\nQ&A Dataset Generation Complete!")

    return 0


if __name__ == '__main__':
    sys.exit(main())
