#!/usr/bin/env python3
"""
Deduplicate Chroma docs by fingerprint metadata.
Runs against the HTTP Chroma server exposed at CHROMA_HTTP_URL (default http://127.0.0.1:8001).
Set CHROMA_COLLECTION to override the collection name.
"""

import os
from chromadb import HttpClient
from chromadb.config import Settings


def main() -> None:
    http_url = os.getenv("CHROMA_HTTP_URL", "http://127.0.0.1:8001")
    coll_name = os.getenv("CHROMA_COLLECTION", "assistant_memory_mxbai_embed_large")

    parsed = http_url if "://" in http_url else f"http://{http_url}"
    host = parsed.split("://", 1)[-1].split(":")[0]
    port = int(parsed.split(":")[-1]) if ":" in parsed.split("://")[-1] else 8001

    client = HttpClient(host=host, port=port, settings=Settings(anonymized_telemetry=False, allow_reset=True))
    coll = client.get_or_create_collection(coll_name)
    print(f"[dedup-chroma] connected to collection: {coll_name}")

    limit = 500
    offset = 0
    seen = {}
    to_delete = []

    while True:
        res = coll.get(limit=limit, offset=offset, include=["metadatas"])
        ids = res.get("ids") or []
        metas = res.get("metadatas") or []
        if not ids:
            break
        for doc_id, meta in zip(ids, metas):
            fp = (meta or {}).get("fingerprint")
            if not fp:
                continue
            if fp in seen:
                to_delete.append(doc_id)
            else:
                seen[fp] = doc_id
        offset += len(ids)
        print(f"[dedup-chroma] scanned {offset} docs… duplicates so far: {len(to_delete)}")

    if to_delete:
        print(f"[dedup-chroma] deleting {len(to_delete)} duplicate ids…")
        coll.delete(ids=to_delete)
    else:
        print("[dedup-chroma] no duplicates found.")
    print("[dedup-chroma] done.")


if __name__ == "__main__":
    main()
