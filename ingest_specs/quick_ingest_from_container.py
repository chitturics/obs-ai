#!/usr/bin/env python3
"""
Quick ingestion script to be run from inside chat_ui_app container
Ingests spec files from /app/public/ingest_specs
"""
import os
import sys
from pathlib import Path

# Set up path
sys.path.insert(0, '/app')
os.chdir('/app')

print("Importing modules...")
from chat_app.vectorstore import index_file_to_memory, ensure_secondary_store

print("\nInitializing SECONDARY vector store (specs)...")
# Force reindex by setting environment variable
os.environ["FORCE_REINDEX"] = "1"
store = ensure_secondary_store()
if not store:
    print("ERROR: Secondary store (specs_mxbai_embed_large_v3) not configured!")
    print("Make sure CHROMA_SECONDARY_COLLECTION is set")
    sys.exit(1)
print("Specs vector store ready (FORCE_REINDEX=1)")

specs_dir = Path("/app/public/documents/specs")
if not specs_dir.exists():
    print(f"ERROR: Directory not found: {specs_dir}")
    sys.exit(1)

spec_files = list(specs_dir.glob("*.spec")) + list(specs_dir.glob("*.conf"))

print(f"\nFound {len(spec_files)} spec/conf files")
print(f"Ingesting to collection: specs_mxbai_embed_large_v3\n")

success = 0
errors = 0

for i, spec_file in enumerate(spec_files, 1):
    print(f"[{i}/{len(spec_files)}] {spec_file.name}...", end=" ", flush=True)
    try:
        ok, result = index_file_to_memory(store, str(spec_file))
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
print(f"Total: {len(spec_files)}")
