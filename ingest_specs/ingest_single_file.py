#!/usr/bin/env python3
"""Ingest a single file for testing"""
import os
import sys
from pathlib import Path

sys.path.insert(0, '/app')
os.chdir('/app')

from chat_app.vectorstore import index_file_to_memory, ensure_secondary_store

print("Initializing SECONDARY vector store (specs)...")
os.environ["FORCE_REINDEX"] = "1"
store = ensure_secondary_store()

if not store:
    print("ERROR: Secondary store not configured!")
    sys.exit(1)

print("Store ready\n")

# Ingest inputs.conf.spec
file_path = "/app/public/ingest_specs/inputs.conf.spec"
print(f"Ingesting {file_path}...")

ok, result = index_file_to_memory(store, file_path)
if ok:
    chunk_count = result.get('chunks', 0) if isinstance(result, dict) else 0
    print(f"✓ Success! Indexed {chunk_count} chunks")
else:
    print(f"✗ Failed: {result}")
