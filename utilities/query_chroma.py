#!/usr/bin/env python3
"""
Query ChromaDB to see what's indexed for a specific conf file.
Usage: python scripts/query_chroma.py [search_term]
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chat_app.vectorstore import VECTOR_STORE


def query_chroma(search_term="inputs.conf", k=20):
    """Query ChromaDB for a specific term."""

    print("=" * 70)
    print(f"QUERYING CHROMADB FOR: {search_term}")
    print("=" * 70)
    print()

    try:
        # Perform similarity search
        results = VECTOR_STORE.similarity_search(search_term, k=k)

        print(f"Found {len(results)} chunks")
        print()

        if not results:
            print("❌ NO RESULTS FOUND")
            print()
            print("This means one of:")
            print("1. The spec files haven't been indexed yet")
            print("2. The search term doesn't match anything in ChromaDB")
            print()
            print("To index spec files, run:")
            print("  podman compose run --rm --profile ingest ingest-specs")
            return

        # Group by source
        by_source = {}
        for doc in results:
            source = doc.metadata.get('source', 'unknown')
            if source not in by_source:
                by_source[source] = []
            by_source[source].append(doc)

        print(f"Results from {len(by_source)} unique sources:")
        print()

        # Show sources
        for i, (source, docs) in enumerate(by_source.items(), 1):
            print(f"{i}. {source}")
            print(f"   Chunks: {len(docs)}")

            # Check if it's the conf file we're looking for
            src_lower = source.lower()
            if search_term.replace('.conf', '') in src_lower:
                print(f"   ✓ MATCHES: Contains '{search_term}'")

            print()

        # Show detailed content from matching sources
        print("=" * 70)
        print("DETAILED CONTENT FROM MATCHING SOURCES")
        print("=" * 70)
        print()

        matching_chunks = 0
        for source, docs in by_source.items():
            src_lower = source.lower()
            search_base = search_term.replace('.conf', '').replace('.spec', '')

            if search_base in src_lower and 'conf' in src_lower:
                matching_chunks += len(docs)
                print(f"SOURCE: {source}")
                print(f"CHUNKS: {len(docs)}")
                print("-" * 70)

                for i, doc in enumerate(docs[:3], 1):  # Show first 3 chunks
                    content = doc.page_content
                    print(f"\nChunk {i}:")
                    print(content[:500])  # First 500 chars
                    if len(content) > 500:
                        print(f"... (truncated, total length: {len(content)} chars)")
                    print()

                if len(docs) > 3:
                    print(f"... and {len(docs) - 3} more chunks from this source")
                print()

        if matching_chunks == 0:
            print("❌ NO CHUNKS FOUND FOR THE REQUESTED CONF FILE")
            print()
            print(f"Search term '{search_term}' didn't match any source files.")
            print()
            print("Available sources that were found:")
            for source in by_source.keys():
                print(f"  - {source}")
            print()
            print("You may need to:")
            print("1. Run spec file ingestion: podman compose run --rm --profile ingest ingest-specs")
            print("2. Check if spec files exist in /tmp/specs or your LOCAL_DOCS_ROOT")
        else:
            print("=" * 70)
            print(f"✓ FOUND {matching_chunks} CHUNKS FOR '{search_term}'")
            print("=" * 70)

    except Exception as e:
        print(f"❌ ERROR querying ChromaDB: {e}")
        print()
        print("Troubleshooting:")
        print("1. Ensure ChromaDB container is running:")
        print("   podman ps | grep chroma")
        print("2. Check CHROMA_HOST and CHROMA_PORT environment variables")
        print("3. Ensure vectorstore is initialized")


if __name__ == "__main__":
    search_term = sys.argv[1] if len(sys.argv) > 1 else "inputs.conf"
    k = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    query_chroma(search_term, k)
