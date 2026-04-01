#!/bin/bash
# =============================================================================
# Check ChromaDB Collections Status
# =============================================================================
# Displays all ChromaDB collections and document counts
# =============================================================================

set -e

# Docker/Podman detection
if command -v podman &> /dev/null; then
    DOCKER_CMD="podman"
    echo "✓ Using: Podman"
elif command -v docker &> /dev/null; then
    DOCKER_CMD="docker"
    echo "✓ Using: Docker"
else
    echo "✗ ERROR: Neither Docker nor Podman found!"
    exit 1
fi

echo ""
echo "================================================================================"
echo "ChromaDB Collections Status"
echo "================================================================================"
echo ""

# Check if ChromaDB is running
if ! $DOCKER_CMD ps --format '{{.Names}}' | grep -q "^chat_chroma_db$"; then
    echo "❌ ChromaDB container (chat_chroma_db) is not running!"
    echo ""
    echo "Start it with:"
    echo "  bash docker_files/start_all.sh"
    exit 1
fi

# Check HTTP endpoint
if ! curl -s http://localhost:8001/api/v1/heartbeat &>/dev/null; then
    echo "❌ ChromaDB HTTP endpoint not responding at http://localhost:8001"
    echo ""
    echo "Container logs:"
    $DOCKER_CMD logs chat_chroma_db 2>&1 | tail -20
    exit 1
fi

echo "✓ ChromaDB responding at http://localhost:8001"
echo ""

# Query collections using Python
$DOCKER_CMD run --rm --network host chainlit-ingest:latest python3 << 'PYTHON'
import chromadb

try:
    c = chromadb.HttpClient(host="127.0.0.1", port=8001)
    colls = c.list_collections()

    if not colls:
        print("⚠️  No collections found in ChromaDB!")
        print("")
        print("To create collections, run ingestion:")
        print("  bash ingest_specs/run_ingest_all.sh")
    else:
        print(f"Total collections: {len(colls)}")
        print("")
        print(f"{'Collection Name':<50} {'Documents':>10}")
        print("=" * 62)

        total_docs = 0
        for col in sorted(colls, key=lambda x: x.name):
            count = col.count()
            total_docs += count
            print(f"{col.name:<50} {count:>10,}")

        print("=" * 62)
        print(f"{'TOTAL':<50} {total_docs:>10,}")
        print("")

except Exception as e:
    print(f"❌ Error querying ChromaDB: {e}")
    exit(1)
PYTHON

echo ""
echo "================================================================================"
