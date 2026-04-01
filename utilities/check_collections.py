#!/usr/bin/env python3
import chromadb

c = chromadb.HttpClient(host="127.0.0.1", port=8001)
colls = c.list_collections()
print(f"\nTotal collections: {len(colls)}\n")
for col in colls:
    print(f"{col.name:40} {col.count():>6} documents")
print()
