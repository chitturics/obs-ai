#!/usr/bin/env python3
"""
Query ChromaDB for content from a specific file.
Usage: python query_chroma_file.py [filename]
"""
import sys
import chromadb

def query_file_content(filename="Splunk_Cheat_Sheet.pdf"):
    """Query ChromaDB for all chunks from a specific file."""

    # Connect to ChromaDB
    client = chromadb.HttpClient(host='127.0.0.1', port=8001)

    # Get all collections
    collections = client.list_collections()
    print(f"Available collections: {[c.name for c in collections]}\n")

    total_found = 0

    # Search each collection
    for collection_info in collections:
        collection = client.get_collection(collection_info.name)

        # Get all items and filter by source
        all_results = collection.get(include=['documents', 'metadatas'])

        # Filter for the specific file
        matching_indices = []
        for i, metadata in enumerate(all_results.get('metadatas', [])):
            source = metadata.get('source', '')
            if filename in source:
                matching_indices.append(i)

        if matching_indices:
            print(f"{'='*60}")
            print(f"Collection: {collection_info.name}")
            print(f"{'='*60}")
            print(f"Found {len(matching_indices)} chunks from '{filename}'\n")
            total_found += len(matching_indices)

            # Show first 5 chunks
            for idx, i in enumerate(matching_indices[:5]):
                print(f"\n--- Chunk {idx+1}/{len(matching_indices)} ---")
                print(f"ID: {all_results['ids'][i]}")
                print(f"Source: {all_results['metadatas'][i].get('source', 'N/A')}")
                print(f"Kind: {all_results['metadatas'][i].get('kind', 'N/A')}")

                content = all_results['documents'][i]
                print(f"\nContent ({len(content)} chars):")
                print(f"{content[:400]}")
                if len(content) > 400:
                    print(f"... [truncated {len(content) - 400} more chars]")

            if len(matching_indices) > 5:
                print(f"\n... and {len(matching_indices) - 5} more chunks in this collection")
            print()

    if total_found == 0:
        print(f"❌ No chunks found for '{filename}' in any collection")
        print("\nTrying to list some available sources...")

        # Show some available sources
        for collection_info in collections:
            collection = client.get_collection(collection_info.name)
            all_results = collection.get(include=['metadatas'], limit=10)
            sources = set()
            for metadata in all_results.get('metadatas', []):
                source = metadata.get('source', '')
                if source:
                    sources.add(source)

            if sources:
                print(f"\nSample sources in '{collection_info.name}':")
                for source in list(sources)[:5]:
                    print(f"  - {source}")
    else:
        print(f"\n✅ Total: Found {total_found} chunks from '{filename}' across all collections")

if __name__ == "__main__":
    filename = sys.argv[1] if len(sys.argv) > 1 else "Splunk_Cheat_Sheet.pdf"
    query_file_content(filename)
