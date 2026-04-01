"""
Unified Knowledge Base Ingestion Pipeline

This script orchestrates the ingestion of all knowledge sources into the
Splunk Assistant's memory. It implements a sophisticated two-step process
for each source, as requested by the architect:

1.  **Store Raw Original**: The original document (spec, conf, command doc,
    feedback, etc.) is stored in its original format for reference and
    traceability. (Currently, this means referencing the existing file path).

2.  **Generate & Ingest Q&A**: The content of the raw document is processed
    by an LLM to generate high-quality, insightful Question-Answer pairs.
    These Q&A pairs are then ingested into the ChromaDB vector store, creating
    a "smart" knowledge base that is optimized for semantic search.

This script is intended to be the single entry point for all knowledge base
management and can be extended to handle new data sources.
"""

import os
import sys
import asyncio
import logging
from pathlib import Path
from typing import List

# Add parent directories to path to allow imports from chat_app and shared
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "chat_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))

from chat_app.helper import create_llm
from chat_app.vectorstore import ensure_vector_store, _persist
from chat_app.qa_dataset_generator import QADatasetGenerator, QAPair

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Configuration ---
# Root directory of the project
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Source directories
SPEC_FILES_DIR = PROJECT_ROOT / "ingest_specs"
COMMANDS_DIR = PROJECT_ROOT / "spl_docs"
REPO_DIR = PROJECT_ROOT / "documents" / "repo"


async def process_spec_files(qa_generator: QADatasetGenerator, vector_store):
    """
    Finds all .spec files, generates Q&A for them, and ingests them.
    """
    logger.info("--- Processing Spec Files ---")
    spec_files = list(SPEC_FILES_DIR.rglob("*.spec"))
    if not spec_files:
        logger.warning(f"No .spec files found in {SPEC_FILES_DIR}.")
        return

    logger.info(f"Found {len(spec_files)} .spec files.")

    tasks = [qa_generator.generate_from_spec_file(str(f)) for f in spec_files]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_qa_pairs = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Error processing spec file {spec_files[i]}: {result}")
        elif result:
            all_qa_pairs.extend(result)
            
    ingested_count = await qa_generator.ingest_qa_pairs(vector_store, all_qa_pairs)
    logger.info(f"--- Finished processing spec files. Ingested {ingested_count} Q&A pairs. ---")


async def process_command_files(qa_generator: QADatasetGenerator, vector_store):
    """
    Finds all SPL command docs, generates Q&A for them, and ingests them.
    """
    logger.info("--- Processing Command Files ---")
    command_files = list(COMMANDS_DIR.rglob("*.md"))
    if not command_files:
        logger.warning(f"No command files (.md) found in {COMMANDS_DIR}.")
        return

    logger.info(f"Found {len(command_files)} command files.")

    tasks = [qa_generator.generate_from_command_file(str(f)) for f in command_files]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_qa_pairs = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Error processing command file {command_files[i]}: {result}")
        elif result:
            all_qa_pairs.extend(result)

    ingested_count = await qa_generator.ingest_qa_pairs(vector_store, all_qa_pairs)
    logger.info(f"--- Finished processing command files. Ingested {ingested_count} Q&A pairs. ---")


async def process_repo_files(qa_generator: QADatasetGenerator, vector_store):
    """
    Finds all .conf files in the org repo, generates Q&A, and ingests them.
    """
    logger.info("--- Processing Repo Config Files ---")
    repo_conf_files = list(REPO_DIR.rglob("*.conf"))
    if not repo_conf_files:
        logger.warning(f"No .conf files found in {REPO_DIR}.")
        return

    logger.info(f"Found {len(repo_conf_files)} repo .conf files.")

    tasks = [qa_generator.generate_from_conf_file(str(f)) for f in repo_conf_files]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_qa_pairs = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Error processing repo file {repo_conf_files[i]}: {result}")
        elif result:
            all_qa_pairs.extend(result)

    ingested_count = await qa_generator.ingest_qa_pairs(vector_store, all_qa_pairs)
    logger.info(f"--- Finished processing repo files. Ingested {ingested_count} Q&A pairs. ---")


async def main():
    """
    Main orchestration function for the unified ingestion pipeline.
    """
    logger.info("===== Starting Unified Ingestion Pipeline =====")

    # --- 1. Initialize services ---
    logger.info("Initializing LLM and Vector Store...")
    try:
        llm = create_llm()
        vector_store = ensure_vector_store()
        logger.info("Services initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize services: {e}")
        logger.error("Please ensure Ollama is running and accessible.")
        return

    # --- 2. Instantiate the Q&A Generator ---
    qa_generator = QADatasetGenerator(llm=llm)

    # --- 3. Process different sources ---
    await process_spec_files(qa_generator, vector_store)
    await process_command_files(qa_generator, vector_store)
    await process_repo_files(qa_generator, vector_store)
    
    # (Future iterations will add process_feedback, etc.)

    # --- 4. Persist all changes to the vector store ---
    logger.info("Persisting all changes to the vector store...")
    try:
        _persist(vector_store)
        logger.info("Vector store persisted successfully.")
    except Exception as e:
        logger.error(f"Failed to persist vector store: {e}")

    logger.info("===== Unified Ingestion Pipeline Finished =====")


if __name__ == "__main__":
    # This allows running the script from the command line:
    # python scripts/run_ingest_all.py
    asyncio.run(main())

