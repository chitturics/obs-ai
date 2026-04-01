"""
Generate fine-tuning dataset from Splunk documentation for LLM training.
Output format: JSONL for Ollama/LLama fine-tuning.

This allows the LLM to learn Splunk knowledge directly without always needing RAG.
"""
import json
import os
import re
from pathlib import Path
from typing import List, Dict
import sys

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))


def parse_spec_file(file_path: Path) -> List[Dict[str, str]]:
    """
    Parse .spec file and generate Q&A pairs.

    Returns:
        List of {"instruction": ..., "input": ..., "output": ...} dicts
    """
    qa_pairs = []

    try:
        content = file_path.read_text(encoding='utf-8', errors='ignore')
        lines = content.splitlines()

        current_stanza = None
        current_setting = None
        current_desc = []

        for line in lines:
            line = line.rstrip()

            # Stanza header [section_name]
            if line.startswith('[') and line.endswith(']'):
                current_stanza = line[1:-1]
                continue

            # Setting = value
            if '=' in line and not line.startswith('#'):
                if current_setting and current_desc:
                    # Create Q&A for previous setting
                    desc_text = ' '.join(current_desc)
                    qa_pairs.append({
                        "instruction": f"What does the '{current_setting}' setting do in {file_path.stem}?",
                        "input": "",
                        "output": f"In {file_path.stem}, '{current_setting}' {desc_text}"
                    })

                current_setting = line.split('=')[0].strip()
                current_desc = []

            # Description/comment lines
            elif line.startswith('#') and current_setting:
                desc = line.lstrip('#').strip()
                if desc and not desc.startswith('*'):
                    current_desc.append(desc)

    except Exception as e:
        print(f"Error parsing {file_path}: {e}")

    return qa_pairs


def parse_conf_file(file_path: Path) -> List[Dict[str, str]]:
    """
    Parse .conf file and generate Q&A pairs about configuration examples.
    """
    qa_pairs = []

    try:
        content = file_path.read_text(encoding='utf-8', errors='ignore')

        # Extract stanzas as examples
        stanzas = re.findall(r'\[([^\]]+)\](.*?)(?=\n\[|\Z)', content, re.DOTALL)

        for stanza_name, stanza_content in stanzas:
            if stanza_name and stanza_content.strip():
                qa_pairs.append({
                    "instruction": f"Show me an example {file_path.stem} stanza for '{stanza_name}'",
                    "input": "",
                    "output": f"[{stanza_name}]{stanza_content.strip()}"
                })

    except Exception as e:
        print(f"Error parsing {file_path}: {e}")

    return qa_pairs


def parse_spl_docs(file_path: Path) -> List[Dict[str, str]]:
    """
    Parse SPL command documentation markdown and generate Q&A.
    """
    qa_pairs = []

    try:
        content = file_path.read_text(encoding='utf-8', errors='ignore')

        command_name = file_path.stem.replace('_', ' ')

        # Extract summary
        lines = content.splitlines()
        summary = []
        in_summary = False

        for line in lines:
            if line.startswith('## Description') or line.startswith('## Summary'):
                in_summary = True
                continue
            if in_summary:
                if line.startswith('##'):
                    break
                if line.strip():
                    summary.append(line.strip())

        if summary:
            summary_text = ' '.join(summary)
            qa_pairs.append({
                "instruction": f"Explain the SPL command '{command_name}'",
                "input": "",
                "output": summary_text
            })

        # Extract syntax examples
        syntax_examples = re.findall(r'```(?:spl)?\n(.*?)\n```', content, re.DOTALL)
        for i, example in enumerate(syntax_examples[:3], 1):  # First 3 examples
            if example.strip():
                qa_pairs.append({
                    "instruction": f"Give me an example of using the '{command_name}' command",
                    "input": "",
                    "output": example.strip()
                })

    except Exception as e:
        print(f"Error parsing {file_path}: {e}")

    return qa_pairs


def generate_dataset(
    specs_dir: Path,
    spl_docs_dir: Path,
    output_file: Path,
    max_examples: int = 5000
):
    """
    Generate complete fine-tuning dataset.

    Args:
        specs_dir: Directory containing .spec files
        spl_docs_dir: Directory containing SPL command docs
        output_file: Output JSONL file path
        max_examples: Maximum number of examples to generate
    """
    all_qa = []

    print(f"Generating fine-tuning dataset...")
    print(f"Specs dir: {specs_dir}")
    print(f"SPL docs dir: {spl_docs_dir}")

    # Process spec files
    if specs_dir.exists():
        print(f"\nProcessing spec files...")
        for spec_file in specs_dir.glob("*.spec"):
            qa_pairs = parse_spec_file(spec_file)
            all_qa.extend(qa_pairs)
            print(f"  {spec_file.name}: {len(qa_pairs)} Q&A pairs")

    # Process conf examples
    if specs_dir.exists():
        print(f"\nProcessing conf examples...")
        for conf_file in specs_dir.glob("*.conf"):
            qa_pairs = parse_conf_file(conf_file)
            all_qa.extend(qa_pairs)
            print(f"  {conf_file.name}: {len(qa_pairs)} Q&A pairs")

    # Process SPL docs
    if spl_docs_dir.exists():
        print(f"\nProcessing SPL documentation...")
        for doc_file in spl_docs_dir.glob("*.md"):
            qa_pairs = parse_spl_docs(doc_file)
            all_qa.extend(qa_pairs)
            print(f"  {doc_file.name}: {len(qa_pairs)} Q&A pairs")

    # Limit to max_examples
    if len(all_qa) > max_examples:
        print(f"\nLimiting dataset to {max_examples} examples (from {len(all_qa)})")
        all_qa = all_qa[:max_examples]

    # Write to JSONL
    print(f"\nWriting to {output_file}...")
    with open(output_file, 'w', encoding='utf-8') as f:
        for qa in all_qa:
            f.write(json.dumps(qa, ensure_ascii=False) + '\n')

    print(f"\n✓ Generated {len(all_qa)} training examples")
    print(f"✓ Output: {output_file}")
    print(f"\nTo fine-tune Ollama model:")
    print(f"  ollama create splunk-assistant -f Modelfile")
    print(f"\nModelfile content:")
    print(f"  FROM qwen2.5:3b")
    print(f"  ADAPTER ./adapter")
    print(f"  SYSTEM \"You are a Splunk administration expert...\"")


def main():
    """Main entry point."""
    # Default paths (adjust as needed)
    specs_dir = Path("/opt/obsai/documents/specs")
    spl_docs_dir = Path("/opt/obsai/documents/commands")
    output_file = Path("/opt/obsai/chatbot/splunk_finetune_dataset.jsonl")

    # Allow override from command line
    if len(sys.argv) > 1:
        specs_dir = Path(sys.argv[1])
    if len(sys.argv) > 2:
        spl_docs_dir = Path(sys.argv[2])
    if len(sys.argv) > 3:
        output_file = Path(sys.argv[3])

    generate_dataset(specs_dir, spl_docs_dir, output_file)


if __name__ == "__main__":
    main()
