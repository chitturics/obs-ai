#!/usr/bin/env python3
"""
Generic Document Ingestion Script

Ingests files from a source directory into a ChromaDB collection.
Supports: .conf, .spec, .pdf, .html, .htm, .txt, .md

Environment Variables:
- CHROMA_HTTP_URL: ChromaDB server URL (default: http://127.0.0.1:8001)
- OLLAMA_BASE_URL: Ollama API URL (default: http://127.0.0.1:11430)
- OLLAMA_EMBED_MODEL: Embedding model (default: mxbai-embed-large)
- CHROMA_COLLECTION: Target collection name (REQUIRED)
- SOURCE_ROOT: Source directory to scan (REQUIRED)
- FILE_PATTERNS: Comma-separated file patterns (default: *.conf,*.spec)
- INGEST_MAX_WORKERS: Parallel workers (default: 4)
- CHUNK_SIZE: Chunk size for text splitting (default: 500)
- CHUNK_OVERLAP: Chunk overlap (default: 100)
"""

import os
import sys
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Tuple
from tqdm import tqdm
import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_ollama import OllamaEmbeddings
from langchain_chroma import Chroma
from langchain_text_splitters import RecursiveCharacterTextSplitter

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from chat_app.vectorstore import (
    ensure_vector_store as ensure_store,
    _fingerprint_bytes,
)
from chat_app.vectorstore_ingest import index_file_to_memory

# =============================================================================
# CONFIGURATION
# =============================================================================

CHROMA_HTTP_URL = os.getenv("CHROMA_HTTP_URL", "http://127.0.0.1:8001")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11430")
OLLAMA_EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "mxbai-embed-large")
CHROMA_COLLECTION = os.getenv("CHROMA_COLLECTION")  # REQUIRED
SOURCE_ROOT = os.getenv("SOURCE_ROOT")  # REQUIRED
FILE_PATTERNS = os.getenv("FILE_PATTERNS", "*.conf,*.spec").split(",")
INGEST_MAX_WORKERS = int(os.getenv("INGEST_MAX_WORKERS", "4"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "100"))

# =============================================================================
# VALIDATION
# =============================================================================

if not CHROMA_COLLECTION:
    print("ERROR: CHROMA_COLLECTION environment variable is required")
    print("Example: CHROMA_COLLECTION=org_repo_mxbai")
    sys.exit(1)

if not SOURCE_ROOT:
    print("ERROR: SOURCE_ROOT environment variable is required")
    print("Example: SOURCE_ROOT=/app/documents/repo")
    sys.exit(1)

if not os.path.exists(SOURCE_ROOT):
    print(f"ERROR: Source directory does not exist: {SOURCE_ROOT}")
    sys.exit(1)

print(f"""
================================================================================
Generic Document Ingestion
================================================================================

Configuration:
  Collection:     {CHROMA_COLLECTION}
  Source:         {SOURCE_ROOT}
  File patterns:  {', '.join(FILE_PATTERNS)}
  ChromaDB:       {CHROMA_HTTP_URL}
  Ollama:         {OLLAMA_BASE_URL}
  Embed model:    {OLLAMA_EMBED_MODEL}
  Workers:        {INGEST_MAX_WORKERS}
  Chunk size:     {CHUNK_SIZE}
  Chunk overlap:  {CHUNK_OVERLAP}

""")

# =============================================================================
# FILE DISCOVERY
# =============================================================================

def discover_files(root: str, patterns: List[str]) -> List[Path]:
    """Discover all files matching the given patterns."""
    files = []
    root_path = Path(root)

    for pattern in patterns:
        pattern = pattern.strip()
        print(f"Scanning for {pattern}...")
        matches = list(root_path.rglob(pattern))
        files.extend(matches)
        print(f"  Found {len(matches)} files")

    # Deduplicate
    files = list(set(files))
    files.sort()

    return files


print("Discovering files...")
files_to_ingest = discover_files(SOURCE_ROOT, FILE_PATTERNS)

print(f"\nTotal files to process: {len(files_to_ingest)}")

if len(files_to_ingest) == 0:
    print("No files found. Exiting.")
    sys.exit(0)

# Show first 10 files
print("\nSample files:")
for f in files_to_ingest[:10]:
    print(f"  {f.relative_to(SOURCE_ROOT)}")
if len(files_to_ingest) > 10:
    print(f"  ... and {len(files_to_ingest) - 10} more")

print("")

# =============================================================================
# INITIALIZE VECTOR STORE
# =============================================================================

print("Initializing vector store...")

try:
    # Create embeddings
    embeddings = OllamaEmbeddings(
        model=OLLAMA_EMBED_MODEL,
        base_url=OLLAMA_BASE_URL,
    )

    # Create HTTP client
    chroma_client = chromadb.HttpClient(
        host=CHROMA_HTTP_URL.split("://")[1].split(":")[0],
        port=int(CHROMA_HTTP_URL.split(":")[-1]),
    )

    # Get or create collection
    collection = chroma_client.get_or_create_collection(
        name=CHROMA_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )

    # Create Langchain Chroma wrapper
    vector_store = Chroma(
        client=chroma_client,
        collection_name=CHROMA_COLLECTION,
        embedding_function=embeddings,
    )

    initial_count = collection.count()
    print(f"✓ Vector store initialized")
    print(f"  Collection: {CHROMA_COLLECTION}")
    print(f"  Existing documents: {initial_count}")
    print("")

except Exception as e:
    print(f"ERROR: Failed to initialize vector store: {e}")
    sys.exit(1)

# =============================================================================
# INGESTION
# =============================================================================

print("Starting ingestion...")
print("")

success_count = 0
skip_count = 0
error_count = 0
errors = []

for file_path in tqdm(files_to_ingest, desc="Ingesting files"):
    try:
        # Check if already indexed by fingerprint
        with open(file_path, "rb") as f:
            file_bytes = f.read()

        fingerprint = _fingerprint_bytes(file_bytes)

        # Query collection for existing fingerprint
        try:
            results = collection.get(
                where={"fingerprint": fingerprint},
                limit=1,
            )
            if results and results.get("ids"):
                skip_count += 1
                tqdm.write(f"⊙ Skipped (already indexed): {file_path.name}")
                continue
        except Exception:
            pass  # If check fails, proceed with ingestion

        # Ingest file
        ok, result = index_file_to_memory(vector_store, str(file_path))

        if ok:
            success_count += 1
            if isinstance(result, dict):
                tqdm.write(f"✓ Indexed: {file_path.name} ({result.get('chunks', 0)} chunks)")
            else:
                tqdm.write(f"✓ Indexed: {file_path.name}")
        else:
            error_count += 1
            error_msg = str(result) if result else "Unknown error"
            tqdm.write(f"✗ Failed: {file_path.name} - {error_msg}")
            errors.append((file_path.name, error_msg))

    except KeyboardInterrupt:
        print("\n\nIngestion interrupted by user")
        break
    except Exception as e:
        error_count += 1
        error_msg = str(e)
        tqdm.write(f"✗ Error: {file_path.name} - {error_msg}")
        errors.append((file_path.name, error_msg))

# =============================================================================
# SUMMARY
# =============================================================================

final_count = collection.count()
added_count = final_count - initial_count

print("")
print("=" * 80)
print("INGESTION SUMMARY")
print("=" * 80)
print(f"Files processed:     {len(files_to_ingest)}")
print(f"  ✓ Success:         {success_count}")
print(f"  ⊙ Skipped:         {skip_count} (already indexed)")
print(f"  ✗ Errors:          {error_count}")
print("")
print(f"Collection:          {CHROMA_COLLECTION}")
print(f"  Documents before:  {initial_count}")
print(f"  Documents after:   {final_count}")
print(f"  Documents added:   {added_count}")
print("")

if errors:
    print("Errors encountered:")
    for filename, error_msg in errors[:10]:
        print(f"  {filename}: {error_msg}")
    if len(errors) > 10:
        print(f"  ... and {len(errors) - 10} more errors")
    print("")

print("=" * 80)
print("")

sys.exit(0 if error_count == 0 else 1)
