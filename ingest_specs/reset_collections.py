#!/usr/bin/env python3
"""Reset all collections by deleting them"""
import chromadb

c = chromadb.HttpClient(host="127.0.0.1", port=8001)

# Collections to reset (excluding feedback_qa which has user data)
collections_to_reset = [
    "specs_mxbai_embed_large_v3",
    "spl_commands_mxbai",
    "org_repo_mxbai",
    "local_docs_mxbai",
    "assistant_memory_mxbai_v2"
]

print("Resetting collections...")
for coll_name in collections_to_reset:
    try:
        c.delete_collection(coll_name)
        print(f"✓ Deleted: {coll_name}")
    except Exception as e:
        print(f"✗ {coll_name}: {e}")

print("\nDone! Collections will be recreated on next ingestion.")
