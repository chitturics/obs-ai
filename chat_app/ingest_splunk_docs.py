import os
import glob
import logging
import sys

# Add chat_app to the path to allow for relative imports
sys.path.append(os.path.join(os.path.dirname(__file__), '..', 'chat_app'))



from vectorstore import ensure_vector_store
from vectorstore_ingest import index_file_to_memory

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def ingest_splunk_documents():
    """
    Ingests Splunk command documentation and configuration specs into the vector store.
    """
    logger.info("Attempting to get vector store...")
    store = ensure_vector_store()
    if not store:
        logger.error("Failed to get vector store. Aborting ingestion.")
        return

    # Look for documents relative to the project root
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__)))

    # Corrected paths to be relative to the script's location
    doc_roots = [
        os.path.join(project_root, '..', 'documents', 'commands'),
        os.path.join(project_root, '..', 'documents', 'specs'),
        os.path.join(project_root, '..', 'ingest_specs')
    ]
    extensions = ["*.md", "*.conf", "*.spec"]

    files_to_ingest = []
    for root in doc_roots:
        if not os.path.isdir(root):
            logger.warning(f"Directory not found, skipping: {root}")
            continue
        for ext in extensions:
            pattern = os.path.join(root, "**", ext)
            found_files = glob.glob(pattern, recursive=True)
            logger.info(f"Found {len(found_files)} files in {pattern}")
            files_to_ingest.extend(found_files)

    if not files_to_ingest:
        logger.warning("No documents found to ingest.")
        return

    logger.info(f"Found a total of {len(files_to_ingest)} documents to ingest.")

    for file_path in files_to_ingest:
        logger.info(f"Ingesting {file_path}...")
        try:
            # vectorstore_ingest functions work with paths relative to the project root
            success, result = index_file_to_memory(store, file_path)
            if success:
                # The result can be a dict, so handle it nicely
                res_str = str(result)
                if len(res_str) > 200:
                    res_str = res_str[:200] + "..."
                logger.info(f"Successfully ingested {file_path}. Result: {res_str}")
            else:
                logger.error(f"Failed to ingest {file_path}. Reason: {result}")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.error(f"An exception occurred while ingesting {file_path}: {e}", exc_info=True)

if __name__ == "__main__":
    # We expect to be run from the root of the project, i.e. `python chat_app/ingest_splunk_docs.py`
    ingest_splunk_documents()
