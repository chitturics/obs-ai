#!/usr/bin/env python3
"""Quick script to ingest spec files from chat_ui_app container"""
import os
import sys
sys.path.insert(0, '/app')

from pathlib import Path
from chat_app.vectorstore import index_file_to_memory, ensure_vector_store

print("Initializing vector store...")
store = ensure_vector_store()
print(f"Vector store ready")

specs_dir = Path("/app/public/ingest_specs")
spec_files = list(specs_dir.glob("*.spec")) + list(specs_dir.glob("*.conf"))

print(f"\nFound {len(spec_files)} spec/conf files")
print(f"Ingesting to collection: specs_mxbai_embed_large_v3\n")

success = 0
errors = 0

for i, spec_file in enumerate(spec_files, 1):
    print(f"[{i}/{len(spec_files)}] {spec_file.name}...", end=" ")
    try:
        ok, result = index_file_to_memory(store, str(spec_file))
        if ok:
            print(f"✓ ({result.get('chunks', 0)} chunks)")
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
