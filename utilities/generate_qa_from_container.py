#!/usr/bin/env python3
"""
Generate Q&A Dataset from Splunk Documentation (Container Version)

Runs inside the chat_ui_app container with access to all mounted volumes.

Usage (from remote machine):
    podman exec chat_ui_app python3 /app/public/generate_qa_from_container.py

Or with custom options:
    podman exec chat_ui_app python3 /app/public/generate_qa_from_container.py \
        --output-dir /app/public/qa_dataset \
        --format all \
        --max-files 10
"""

import os
import sys
import argparse
import logging
from pathlib import Path

# Add chat_app to path
sys.path.insert(0, '/app')
sys.path.insert(0, '/app/chat_app')

from chat_app.qa_dataset_generator import QADatasetGenerator

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def find_files(root_dir: str, pattern: str) -> list:
    """Find all files matching pattern in directory"""
    files = []
    root = Path(root_dir)
    if root.exists():
        for file_path in root.rglob(pattern):
            if file_path.is_file():
                files.append(str(file_path))
    return sorted(files)


def main():
    parser = argparse.ArgumentParser(
        description='Generate Q&A dataset from Splunk documentation (container version)'
    )
    parser.add_argument(
        '--output-dir',
        default='/app/public/qa_dataset',
        help='Output directory for Q&A dataset files'
    )
    parser.add_argument(
        '--format',
        choices=['jsonl', 'csv', 'openai', 'all'],
        default='all',
        help='Output format(s) to generate'
    )
    parser.add_argument(
        '--max-files',
        type=int,
        default=None,
        help='Maximum number of files to process per type (for testing)'
    )
    parser.add_argument(
        '--skip-specs',
        action='store_true',
        help='Skip processing .conf.spec files'
    )
    parser.add_argument(
        '--skip-commands',
        action='store_true',
        help='Skip processing SPL command documentation'
    )
    parser.add_argument(
        '--skip-pdfs',
        action='store_true',
        help='Skip processing PDF documentation'
    )
    parser.add_argument(
        '--skip-repo',
        action='store_true',
        help='Skip processing repository .conf files'
    )

    args = parser.parse_args()

    # Container paths
    SPECS_DIR = '/app/public/ingest_specs'
    COMMANDS_DIR = '/app/public/documents/commands'
    PDFS_DIR = '/app/public/documents/pdfs'
    REPO_DIR = '/app/public/documents/repo'

    logger.info("=" * 80)
    logger.info("Q&A Dataset Generation (Container Version)")
    logger.info("=" * 80)
    logger.info(f"Output directory: {args.output_dir}")
    logger.info(f"Output format(s): {args.format}")
    if args.max_files:
        logger.info(f"Max files per type: {args.max_files} (testing mode)")

    # Initialize generator
    generator = QADatasetGenerator(output_dir=args.output_dir)

    # Process .conf.spec files
    if not args.skip_specs:
        logger.info("\n" + "=" * 80)
        logger.info("[1/4] Processing .conf.spec files")
        logger.info("=" * 80)
        spec_files = find_files(SPECS_DIR, '*.spec')
        if args.max_files:
            spec_files = spec_files[:args.max_files]

        logger.info(f"Found {len(spec_files)} .spec files in {SPECS_DIR}")
        spec_count = 0
        for i, file_path in enumerate(spec_files, 1):
            try:
                filename = Path(file_path).name
                logger.info(f"  [{i}/{len(spec_files)}] {filename}")
                pairs = generator.generate_from_spec_file(file_path)
                for pair in pairs:
                    generator.add_qa_pair(pair)
                spec_count += len(pairs)
                logger.info(f"      -> Generated {len(pairs)} Q&A pairs")
            except Exception as e:
                logger.error(f"      -> Failed: {e}")
        logger.info(f"\nTotal from specs: {spec_count} Q&A pairs")

    # Process SPL command documentation
    if not args.skip_commands:
        logger.info("\n" + "=" * 80)
        logger.info("[2/4] Processing SPL command documentation")
        logger.info("=" * 80)
        if Path(COMMANDS_DIR).exists():
            command_files = find_files(COMMANDS_DIR, '*.md')
            command_files.extend(find_files(COMMANDS_DIR, '*.txt'))
            if args.max_files:
                command_files = command_files[:args.max_files]

            logger.info(f"Found {len(command_files)} command files in {COMMANDS_DIR}")
            cmd_count = 0
            for i, file_path in enumerate(command_files, 1):
                try:
                    filename = Path(file_path).name
                    logger.info(f"  [{i}/{len(command_files)}] {filename}")
                    pairs = generator.generate_from_command_file(file_path)
                    for pair in pairs:
                        generator.add_qa_pair(pair)
                    cmd_count += len(pairs)
                    logger.info(f"      -> Generated {len(pairs)} Q&A pairs")
                except Exception as e:
                    logger.error(f"      -> Failed: {e}")
            logger.info(f"\nTotal from commands: {cmd_count} Q&A pairs")
        else:
            logger.warning(f"Commands directory not found: {COMMANDS_DIR}")

    # Process PDF documentation
    if not args.skip_pdfs:
        logger.info("\n" + "=" * 80)
        logger.info("[3/4] Processing PDF documentation")
        logger.info("=" * 80)
        if Path(PDFS_DIR).exists():
            pdf_files = find_files(PDFS_DIR, '*.pdf')
            if args.max_files:
                pdf_files = pdf_files[:args.max_files]

            logger.info(f"Found {len(pdf_files)} PDF files in {PDFS_DIR}")
            pdf_count = 0
            for i, file_path in enumerate(pdf_files, 1):
                try:
                    filename = Path(file_path).name
                    logger.info(f"  [{i}/{len(pdf_files)}] {filename}")
                    pairs = generator.generate_from_pdf(file_path, max_qa_per_page=2)
                    for pair in pairs:
                        generator.add_qa_pair(pair)
                    pdf_count += len(pairs)
                    logger.info(f"      -> Generated {len(pairs)} Q&A pairs")
                except Exception as e:
                    logger.error(f"      -> Failed: {e}")
            logger.info(f"\nTotal from PDFs: {pdf_count} Q&A pairs")
        else:
            logger.warning(f"PDFs directory not found: {PDFS_DIR}")

    # Process repository .conf files
    if not args.skip_repo:
        logger.info("\n" + "=" * 80)
        logger.info("[4/4] Processing repository .conf files")
        logger.info("=" * 80)
        if Path(REPO_DIR).exists():
            conf_files = find_files(REPO_DIR, '*.conf')
            if args.max_files:
                conf_files = conf_files[:args.max_files]

            logger.info(f"Found {len(conf_files)} .conf files in {REPO_DIR}")
            repo_count = 0
            for i, file_path in enumerate(conf_files, 1):
                try:
                    # Show relative path from REPO_DIR
                    rel_path = Path(file_path).relative_to(REPO_DIR)
                    logger.info(f"  [{i}/{len(conf_files)}] {rel_path}")
                    # Treat .conf files like .spec files (they use same parser)
                    pairs = generator.generate_from_spec_file(file_path)
                    for pair in pairs:
                        generator.add_qa_pair(pair)
                    repo_count += len(pairs)
                    logger.info(f"      -> Generated {len(pairs)} Q&A pairs")
                except Exception as e:
                    logger.error(f"      -> Failed: {e}")
            logger.info(f"\nTotal from repo: {repo_count} Q&A pairs")
        else:
            logger.warning(f"Repository directory not found: {REPO_DIR}")

    # Display statistics
    logger.info("\n" + "=" * 80)
    logger.info("Dataset Statistics")
    logger.info("=" * 80)
    stats = generator.get_statistics()
    logger.info(f"Total Q&A pairs: {stats['total_pairs']}")

    if stats['total_pairs'] == 0:
        logger.error("\nNo Q&A pairs were generated!")
        logger.error("Check that the input directories contain valid files.")
        return 1

    logger.info(f"\nBy source type:")
    for src_type, count in sorted(stats['by_source_type'].items()):
        pct = (count / stats['total_pairs']) * 100
        logger.info(f"  {src_type:15s}: {count:6d} pairs ({pct:5.1f}%)")

    logger.info(f"\nBy confidence:")
    for conf_level, count in sorted(stats['by_confidence'].items()):
        pct = (count / stats['total_pairs']) * 100
        logger.info(f"  {conf_level:20s}: {count:6d} pairs ({pct:5.1f}%)")

    logger.info(f"\nAverage question length: {stats['avg_question_length']:.1f} chars")
    logger.info(f"Average answer length:   {stats['avg_answer_length']:.1f} chars")

    # Save output files
    logger.info("\n" + "=" * 80)
    logger.info("Saving Output Files")
    logger.info("=" * 80)

    output_files = []

    if args.format in ['jsonl', 'all']:
        output_file = generator.save_jsonl()
        output_files.append(str(output_file))
        logger.info(f"[OK] JSONL format: {output_file}")
        logger.info(f"     Size: {Path(output_file).stat().st_size / 1024 / 1024:.2f} MB")

    if args.format in ['csv', 'all']:
        output_file = generator.save_csv()
        output_files.append(str(output_file))
        logger.info(f"[OK] CSV format: {output_file}")
        logger.info(f"     Size: {Path(output_file).stat().st_size / 1024 / 1024:.2f} MB")

    if args.format in ['openai', 'all']:
        output_file = generator.save_openai_format()
        output_files.append(str(output_file))
        logger.info(f"[OK] OpenAI format: {output_file}")
        logger.info(f"     Size: {Path(output_file).stat().st_size / 1024 / 1024:.2f} MB")

    logger.info("\n" + "=" * 80)
    logger.info("Q&A Dataset Generation Complete!")
    logger.info("=" * 80)
    logger.info(f"\nOutput directory: {args.output_dir}")
    logger.info(f"Total Q&A pairs: {stats['total_pairs']}")
    logger.info(f"\nGenerated files:")
    for f in output_files:
        logger.info(f"  - {f}")

    logger.info("\nNext steps:")
    logger.info("  1. Copy files from container to host:")
    logger.info(f"     podman cp chat_ui_app:{args.output_dir} ./qa_dataset")
    logger.info("  2. Review the generated Q&A pairs (CSV format is easiest)")
    logger.info("  3. Filter by confidence score if needed")
    logger.info("  4. Use JSONL or OpenAI format for fine-tuning")
    logger.info("")

    return 0


if __name__ == '__main__':
    sys.exit(main())
