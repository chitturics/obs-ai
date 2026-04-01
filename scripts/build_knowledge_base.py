"""
Knowledge Base Builder from Configuration Files

This script orchestrates the generation of a Question-Answer dataset from
Splunk configuration and specification files, and then ingests this dataset
into the ChromaDB vector store.

This process enables the assistant to answer questions about configurations
it has never seen before, effectively allowing it to "train" on new knowledge.

The process is as follows:
1.  Scan for .conf.spec files in the project.
2.  For each file, use an LLM to generate insightful Q&A pairs about the
    stanzas and settings within.
3.  Take the generated Q&A pairs.
4.  Format them as documents.
5.  Ingest these documents into the main ChromaDB vector store.
"""

import os
import sys
import asyncio
import logging
from pathlib import Path

# Add parent directories to path to allow imports from chat_app and shared
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "chat_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "shared"))


from chat_app.helper import create_llm
from chat_app.vectorstore import ensure_vector_store, _persist
from chat_app.qa_dataset_generator import QADatasetGenerator

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Configuration ---
# Directory containing the .conf.spec files
SPEC_FILES_DIR = Path(__file__).resolve().parent.parent / "ingest_specs"


async def main():
    """
    Main orchestration function.
    """
    logger.info("--- Starting Knowledge Base Builder ---")

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

    # --- 2. Find source files ---
    spec_files = list(SPEC_FILES_DIR.rglob("*.spec"))
    if not spec_files:
        logger.error(f"No .spec files found in {SPEC_FILES_DIR}. Nothing to process.")
        return
    
    logger.info(f"Found {len(spec_files)} .spec files to process.")

    # --- 3. Generate Q&A pairs ---
    logger.info("Generating Q&A pairs using the LLM...")
    qa_generator = QADatasetGenerator(llm=llm)

    # Create async tasks for each file
    tasks = [qa_generator.generate_from_spec_file(str(f)) for f in spec_files]
    
    # Run tasks concurrently
    results = await asyncio.gather(*tasks, return_exceptions=True)

    all_qa_pairs = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Error processing file {spec_files[i]}: {result}")
        elif result:
            all_qa_pairs.extend(result)
    
    if not all_qa_pairs:
        logger.warning("No Q&A pairs were generated. Nothing to ingest.")
        return

    logger.info(f"Generated a total of {len(all_qa_pairs)} Q&A pairs.")

    # --- 4. Ingest Q&A pairs into ChromaDB ---
    logger.info("Ingesting generated Q&A pairs into the vector store...")
    
    batch_size = 100
    total_ingested = 0

    for i in range(0, len(all_qa_pairs), batch_size):
        batch = all_qa_pairs[i:i + batch_size]
        
        texts_to_ingest = []
        metadatas_to_ingest = []

        for pair in batch:
            # Format the Q&A pair into a single text document
            text = f"Question: {pair.question}

Answer: {pair.answer}"
            texts_to_ingest.append(text)
            
            # Create metadata for the document
            metadata = {
                "source": pair.source_file,
                "kind": "generated_qa_v1", # Versioned identifier
                "stanza": pair.stanza or "general",
                "generator": "build_knowledge_base.py"
            }
            metadatas_to_ingest.append(metadata)

        try:
            vector_store.add_texts(texts=texts_to_ingest, metadatas=metadatas_to_ingest)
            total_ingested += len(texts_to_ingest)
            logger.info(f"Ingested batch {i // batch_size + 1}, containing {len(texts_to_ingest)} pairs.")
        except Exception as e:
            logger.error(f"Error during batch ingestion: {e}")

    # --- 5. Persist changes to the vector store ---
    if total_ingested > 0:
        logger.info("Persisting changes to the vector store...")
        try:
            _persist(vector_store)
            logger.info("Vector store persisted successfully.")
        except Exception as e:
            logger.error(f"Failed to persist vector store: {e}")

    logger.info("--- Knowledge Base Builder Finished ---")
    logger.info(f"Successfully ingested {total_ingested} new Q&A documents.")


if __name__ == "__main__":
    # This allows running the script from the command line.
    # e.g., python scripts/build_knowledge_base.py
    asyncio.run(main())
