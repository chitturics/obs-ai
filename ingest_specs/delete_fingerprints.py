#!/usr/bin/env python3
import chromadb

c = chromadb.HttpClient(host="127.0.0.1", port=8001)
try:
    c.delete_collection("fingerprints")
    print("✓ Deleted fingerprints collection")
except Exception as e:
    print(f"No fingerprints collection (or error): {e}")
