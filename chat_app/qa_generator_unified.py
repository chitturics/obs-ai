"""
Unified Q&A Dataset Generator

Integrated into the existing system. Uses external LLM API if available,
falls back to template-based generation otherwise.

Usage from container:
    podman exec chat_ui_app python3 /app/chat_app/qa_generator_unified.py --max-files 5
"""

import os
import sys
import json
import argparse
import logging
from pathlib import Path
from typing import List, Dict, Optional
import time

# Try to import LLM provider (optional)
try:
    import httpx
    LLM_API_AVAILABLE = True
except ImportError:
    LLM_API_AVAILABLE = False

# Import existing modules
sys.path.insert(0, '/app')
from conf_parser import parse_conf_stanzas, extract_app_metadata

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class UnifiedQAGenerator:
    """Generate Q&A pairs using external LLM API or templates"""

    def __init__(self, use_llm: bool = True, api_key: Optional[str] = None):
        self.use_llm = use_llm and LLM_API_AVAILABLE

        if self.use_llm:
            self.api_key = api_key or os.getenv("LLM_API_KEY")
            if not self.api_key:
                logger.warning("LLM_API_KEY not set. Falling back to template-based generation.")
                self.use_llm = False
            else:
                try:
                    self.base_url = os.getenv("LLM_API_BASE_URL", "http://localhost:11434")
                    self.model = os.getenv("LLM_QA_MODEL", "qwen2.5:3b")
                    self.client = httpx.Client(base_url=self.base_url, timeout=120)
                    logger.info(f"Using LLM API for Q&A generation (model: {self.model})")
                except (ConnectionError, TimeoutError, OSError, ValueError, RuntimeError) as e:
                    logger.warning(f"Failed to initialize LLM client: {e}. Falling back to templates.")
                    self.use_llm = False

        if not self.use_llm:
            logger.info("Using template-based Q&A generation (free)")

        self.qa_pairs: List[Dict] = []
        self.total_tokens = 0
        self.total_cost = 0.0

    def generate_from_spec_file(self, file_path: str, max_qa: int = 10) -> List[Dict]:
        """Generate Q&A from spec file using LLM or templates"""
        if self.use_llm:
            return self._generate_with_llm_spec(file_path, max_qa)
        else:
            return self._generate_with_template_spec(file_path)

    def _generate_with_llm_spec(self, file_path: str, max_qa: int) -> List[Dict]:
        """Generate with LLM API"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            filename = Path(file_path).name

            # Limit content size
            if len(content) > 8000:
                content = content[:8000] + "\n\n[... truncated ...]"

            prompt = f"""You are a Splunk expert. Generate {max_qa} high-quality question-answer pairs from this Splunk configuration specification file.

Filename: {filename}

Content:
{content}

Generate diverse questions that a Splunk administrator might ask. For each Q&A pair, provide natural questions and clear answers with examples.

Format as JSON array:
[
  {{"question": "Your question", "answer": "Detailed answer", "stanza": "stanza_name", "confidence": 0.9}},
  ...
]

Only return the JSON array."""

            response = self.client.post("/api/generate", json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.7, "num_predict": 4096},
            })
            response.raise_for_status()
            response_text = response.json().get("response", "")

            # Parse response
            start_idx = response_text.find('[')
            end_idx = response_text.rfind(']') + 1

            if start_idx == -1 or end_idx == 0:
                logger.error("  No JSON in LLM response, falling back to templates")
                return self._generate_with_template_spec(file_path)

            pairs = json.loads(response_text[start_idx:end_idx])

            for pair in pairs:
                pair['source_file'] = filename
                pair['source_type'] = 'spec'
                pair['method'] = 'llm'

            return pairs

        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            logger.error(f"  LLM generation failed: {e}, falling back to templates")
            return self._generate_with_template_spec(file_path)

    def _generate_with_template_spec(self, file_path: str) -> List[Dict]:
        """Generate with templates (fallback)"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()

            stanzas = parse_conf_stanzas(content)
            extract_app_metadata(file_path)
            filename = Path(file_path).name
            conf_name = filename.replace('.spec', '')

            pairs = []
            for stanza in stanzas:
                if not stanza.content.strip():
                    continue


                # Q1: What is this stanza for?
                if stanza.name != "__preamble__":
                    pairs.append({
                        'question': f"What is the [{stanza.name}] stanza in {conf_name} used for?",
                        'answer': f"The [{stanza.name}] stanza in {conf_name} is used to configure:\n\n[{stanza.name}]\n{stanza.content.strip()}",
                        'stanza': stanza.name,
                        'source_file': filename,
                        'source_type': 'spec',
                        'method': 'template',
                        'confidence': 0.9
                    })

                # Q2: How do I configure?
                if stanza.name != "__preamble__":
                    pairs.append({
                        'question': f"How do I configure {stanza.name} in {conf_name}?",
                        'answer': f"To configure [{stanza.name}] in {conf_name}, use:\n\n[{stanza.name}]\n{stanza.content.strip()}",
                        'stanza': stanza.name,
                        'source_file': filename,
                        'source_type': 'spec',
                        'method': 'template',
                        'confidence': 0.9
                    })

            return pairs

        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.error(f"Failed to generate from {file_path}: {e}")
            return []

    def save_jsonl(self, output_file: str):
        """Save as JSONL"""
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
                        "method": pair.get('method', 'template'),
                        "confidence": pair.get('confidence', 0.9)
                    }
                }
                f.write(json.dumps(record, ensure_ascii=False) + '\n')
        logger.info(f"Saved {len(self.qa_pairs)} pairs to {output_file}")

    def save_csv(self, output_file: str):
        """Save as CSV"""
        import csv
        with open(output_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['question', 'answer', 'source_file', 'source_type', 'stanza', 'method', 'confidence'])
            for pair in self.qa_pairs:
                writer.writerow([
                    pair['question'],
                    pair['answer'],
                    pair.get('source_file', ''),
                    pair.get('source_type', ''),
                    pair.get('stanza', ''),
                    pair.get('method', 'template'),
                    pair.get('confidence', 0.9)
                ])
        logger.info(f"Saved {len(self.qa_pairs)} pairs to {output_file}")


def find_files(root_dir: str, pattern: str) -> List[str]:
    """Find files matching pattern"""
    files = []
    root = Path(root_dir)
    if root.exists():
        for f in root.rglob(pattern):
            if f.is_file():
                files.append(str(f))
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(description='Generate Q&A dataset (unified)')
    parser.add_argument('--output-dir', default='/app/public/qa_dataset', help='Output directory')
    parser.add_argument('--max-files', type=int, default=None, help='Max files per type')
    parser.add_argument('--use-llm', action='store_true', help='Use LLM API if available')
    parser.add_argument('--specs-only', action='store_true', help='Only process specs')

    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("Unified Q&A Dataset Generator")
    logger.info("=" * 80)

    # Check if LLM API is available
    if args.use_llm:
        if not LLM_API_AVAILABLE:
            logger.warning("httpx package not installed. Using templates.")
            logger.warning("To install: pip install httpx")
        elif not os.getenv("LLM_API_KEY") and not os.getenv("LLM_API_BASE_URL"):
            logger.warning("LLM_API_KEY or LLM_API_BASE_URL not set. Using templates.")

    # Initialize
    generator = UnifiedQAGenerator(use_llm=args.use_llm)
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)

    # Process specs
    logger.info("\nProcessing .conf.spec files...")
    spec_files = find_files('/app/public/ingest_specs', '*.spec')
    if args.max_files:
        spec_files = spec_files[:args.max_files]

    logger.info(f"Found {len(spec_files)} spec files")
    for i, file_path in enumerate(spec_files, 1):
        logger.info(f"  [{i}/{len(spec_files)}] {Path(file_path).name}")
        pairs = generator.generate_from_spec_file(file_path)
        generator.qa_pairs.extend(pairs)
        logger.info(f"      -> Generated {len(pairs)} Q&A pairs")
        if generator.use_llm:
            time.sleep(0.5)  # Rate limiting

    # Stats
    logger.info("\n" + "=" * 80)
    logger.info(f"Total Q&A pairs: {len(generator.qa_pairs)}")
    if generator.use_llm:
        logger.info(f"LLM tokens: {generator.total_tokens:,}")

    # Count by method
    by_method = {}
    for pair in generator.qa_pairs:
        method = pair.get('method', 'template')
        by_method[method] = by_method.get(method, 0) + 1

    logger.info("\nBy generation method:")
    for method, count in sorted(by_method.items()):
        logger.info(f"  {method:15s}: {count:6d} pairs")

    # Save
    logger.info("\n" + "=" * 80)
    generator.save_jsonl(f"{args.output_dir}/qa_dataset.jsonl")
    generator.save_csv(f"{args.output_dir}/qa_dataset.csv")

    logger.info("\n" + "=" * 80)
    logger.info("Complete!")
    logger.info(f"Output: {args.output_dir}")
    logger.info("=" * 80)

    return 0


if __name__ == '__main__':
    sys.exit(main())
