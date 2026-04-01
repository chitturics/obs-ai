#!/usr/bin/env python3
"""
Generate Q&A Dataset from Splunk Documentation

Processes all spec files, command docs, and PDFs to create
a comprehensive Q&A dataset suitable for LLM training.

Usage:
    python generate_qa_dataset.py [--output-dir ./qa_dataset] [--format all]

Output formats:
    - JSONL (instruction fine-tuning format)
    - CSV (for analysis)
    - OpenAI format (for OpenAI fine-tuning API)
"""

import os
import sys
import argparse
import logging
from pathlib import Path
from typing import List

# Add chat_app to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'chat_app'))

from chat_app.qa_dataset_generator import QADatasetGenerator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def find_files(root_dir: str, pattern: str) -> List[str]:
    """Find all files matching pattern in directory"""
    files = []
    root = Path(root_dir)
    if root.exists():
        for file_path in root.rglob(pattern):
            if file_path.is_file():
                files.append(str(file_path))
    return files


async def main():
    parser = argparse.ArgumentParser(description='Generate Q&A dataset from Splunk documentation')
    parser.add_argument(
        '--output-dir',
        default='./qa_dataset',
        help='Output directory for Q&A dataset files'
    )
    parser.add_argument(
        '--format',
        choices=['jsonl', 'csv', 'openai', 'all'],
        default='all',
        help='Output format(s) to generate'
    )
    parser.add_argument(
        '--specs-dir',
        default='./ingest_specs',
        help='Directory containing .conf.spec files'
    )
    parser.add_argument(
        '--commands-dir',
        default='./spl_docs',
        help='Directory containing SPL command documentation'
    )
    parser.add_argument(
        '--pdfs-dir',
        default='./public/documents/pdfs',
        help='Directory containing PDF documentation'
    )
    parser.add_argument(
        '--repo-dir',
        default='./public/documents/repo',
        help='Directory containing repository .conf files'
    )
    parser.add_argument(
        '--max-files',
        type=int,
        default=None,
        help='Maximum number of files to process per type (for testing)'
    )

    args = parser.parse_args()

    logger.info("=" * 80)
    logger.info("Q&A Dataset Generation")
    logger.info("=" * 80)

    # Initialize generator
    generator = QADatasetGenerator(output_dir=args.output_dir)

    # Process .conf.spec files
    logger.info("\n[1/4] Processing .conf.spec files...")
    spec_files = find_files(args.specs_dir, '*.spec')
    if args.max_files:
        spec_files = spec_files[:args.max_files]

    logger.info(f"Found {len(spec_files)} .spec files")
    for i, file_path in enumerate(spec_files, 1):
        try:
            logger.info(f"  [{i}/{len(spec_files)}] {Path(file_path).name}")
            pairs = await generator.generate_from_spec_file(file_path)
            for pair in pairs:
                generator.add_qa_pair(pair)
        except Exception as e:
            logger.error(f"  Failed to process {file_path}: {e}")

    # Process SPL command documentation
    logger.info("\n[2/4] Processing SPL command documentation...")
    if Path(args.commands_dir).exists():
        command_files = find_files(args.commands_dir, '*.md')
        command_files.extend(find_files(args.commands_dir, '*.txt'))
        if args.max_files:
            command_files = command_files[:args.max_files]

        logger.info(f"Found {len(command_files)} command files")
        for i, file_path in enumerate(command_files, 1):
            try:
                logger.info(f"  [{i}/{len(command_files)}] {Path(file_path).name}")
                pairs = await generator.generate_from_command_file(file_path)
                for pair in pairs:
                    generator.add_qa_pair(pair)
            except Exception as e:
                logger.error(f"  Failed to process {file_path}: {e}")
    else:
        logger.warning(f"Commands directory not found: {args.commands_dir}")

    # Process PDF documentation
    logger.info("\n[3/4] Processing PDF documentation...")
    if Path(args.pdfs_dir).exists():
        pdf_files = find_files(args.pdfs_dir, '*.pdf')
        if args.max_files:
            pdf_files = pdf_files[:args.max_files]

        logger.info(f"Found {len(pdf_files)} PDF files")
        for i, file_path in enumerate(pdf_files, 1):
            try:
                logger.info(f"  [{i}/{len(pdf_files)}] {Path(file_path).name}")
                pairs = generator.generate_from_pdf(file_path, max_qa_per_page=2)
                for pair in pairs:
                    generator.add_qa_pair(pair)
            except Exception as e:
                logger.error(f"  Failed to process {file_path}: {e}")
    else:
        logger.warning(f"PDFs directory not found: {args.pdfs_dir}")

    # Process repository .conf files
    logger.info("\n[4/4] Processing repository .conf files...")
    if Path(args.repo_dir).exists():
        conf_files = find_files(args.repo_dir, '*.conf')
        if args.max_files:
            conf_files = conf_files[:args.max_files]

        logger.info(f"Found {len(conf_files)} .conf files in repository")
        for i, file_path in enumerate(conf_files, 1):
            try:
                logger.info(f"  [{i}/{len(conf_files)}] {Path(file_path).name}")
                # Treat .conf files like .spec files (they use same parser)
                pairs = await generator.generate_from_spec_file(file_path)
                for pair in pairs:
                    generator.add_qa_pair(pair)
            except Exception as e:
                logger.error(f"  Failed to process {file_path}: {e}")
    else:
        logger.warning(f"Repository directory not found: {args.repo_dir}")

    # Display statistics
    logger.info("\n" + "=" * 80)
    logger.info("Dataset Statistics")
    logger.info("=" * 80)
    stats = generator.get_statistics()
    logger.info(f"Total Q&A pairs: {stats['total_pairs']}")
    logger.info(f"\nBy source type:")
    for src_type, count in stats['by_source_type'].items():
        logger.info(f"  {src_type:15s}: {count:6d} pairs")
    logger.info(f"\nBy confidence:")
    for conf_level, count in stats['by_confidence'].items():
        logger.info(f"  {conf_level:20s}: {count:6d} pairs")
    logger.info(f"\nAverage question length: {stats['avg_question_length']:.1f} chars")
    logger.info(f"Average answer length:   {stats['avg_answer_length']:.1f} chars")

    # Save output files
    logger.info("\n" + "=" * 80)
    logger.info("Saving Output Files")
    logger.info("=" * 80)

    if args.format in ['jsonl', 'all']:
        output_file = generator.save_jsonl()
        logger.info(f"[OK] JSONL format: {output_file}")

    if args.format in ['csv', 'all']:
        output_file = generator.save_csv()
        logger.info(f"[OK] CSV format: {output_file}")

    if args.format in ['openai', 'all']:
        output_file = generator.save_openai_format()
        logger.info(f"[OK] OpenAI format: {output_file}")

    logger.info("\n" + "=" * 80)
    logger.info("Q&A Dataset Generation Complete!")
    logger.info("=" * 80)
    logger.info(f"\nOutput directory: {args.output_dir}")
    logger.info(f"Total Q&A pairs: {stats['total_pairs']}")
    logger.info("\nNext steps:")
    logger.info("  1. Review the generated Q&A pairs in CSV format")
    logger.info("  2. Filter by confidence score if needed")
    logger.info("  3. Use JSONL or OpenAI format for fine-tuning")
    logger.info("")


if __name__ == '__main__':
    main()
