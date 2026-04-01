#!/usr/bin/env python3
"""
Local documentation ingestion script
Ingests PDF, HTML, MD files from the documents directory into the
local_docs_mxbai collection (NOT the primary collection).
"""
import os
import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, '/app')

from chat_app.vectorstore import index_file_to_memory, get_vector_store

# Target collection name for local docs
LOCAL_DOCS_COLLECTION = os.getenv("LOCAL_DOCS_COLLECTION", "local_docs_mxbai")


def ingest_local_docs():
    """Ingest local documentation files into the local_docs_mxbai collection."""
    print(f"Initializing vector store for collection: {LOCAL_DOCS_COLLECTION}...")
    store = get_vector_store(collection_name=LOCAL_DOCS_COLLECTION)
    print(f"Vector store ready (collection: {LOCAL_DOCS_COLLECTION})")

    # Support multiple document directories
    docs_dirs = [
        Path("/app/documents"),
        Path(os.getenv("LOCAL_DOCS_DIR", "/app/public/documents")),
    ]
    # De-duplicate and filter to existing
    seen = set()
    valid_dirs = []
    for d in docs_dirs:
        resolved = d.resolve()
        if resolved not in seen and resolved.exists():
            seen.add(resolved)
            valid_dirs.append(resolved)

    if not valid_dirs:
        print(f"No document directories found. Checked: {[str(d) for d in docs_dirs]}")
        return

    # Find all supported file types across all valid directories
    extensions = ["*.pdf", "*.html", "*.htm", "*.md", "*.txt"]
    doc_files = []
    for docs_dir in valid_dirs:
        for ext in extensions:
            doc_files.extend(docs_dir.rglob(ext))

    if not doc_files:
        print("No documentation files found")
        return

    print(f"\nFound {len(doc_files)} documentation files in {len(valid_dirs)} directories")
    print(f"Ingesting to collection: {LOCAL_DOCS_COLLECTION}\n")

    success = 0
    errors = 0

    for i, doc_file in enumerate(doc_files, 1):
        print(f"[{i}/{len(doc_files)}] {doc_file.name}...", end=" ")
        try:
            ok, result = index_file_to_memory(store, str(doc_file))
            if ok:
                chunk_count = result.get('chunks', 0) if isinstance(result, dict) else 0
                print(f"✓ ({chunk_count} chunks)")
                success += 1
            else:
                print(f"✗ {result}")
                errors += 1
        except Exception as e:
            print(f"✗ ERROR: {e}")
            errors += 1

    print(f"\n=== Summary ===")
    print(f"Success: {success}")
    print(f"Errors: {errors}")
    print(f"Total: {len(doc_files)}")

if __name__ == "__main__":
    ingest_local_docs()
