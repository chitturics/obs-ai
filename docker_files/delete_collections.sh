#!/bin/bash
# Delete ChromaDB collections to force clean re-ingestion
# This removes all ingested documentation from the vector database

set -e

cd "$(dirname "$0")/.."

# Docker/Podman detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi
docker() { "$DOCKER_CMD" "$@"; }

echo "==========================================================================="
echo "DELETE CHROMADB COLLECTIONS"
echo "==========================================================================="
echo ""
echo "This will DELETE all ChromaDB collections and their data:"
echo "  - specs_mxbai_embed_large_v3 (spec files)"
echo "  - spl_commands_mxbai (SPL command docs)"
echo ""
echo "⚠️  WARNING: This cannot be undone!"
echo ""

# Confirm deletion
read -p "Are you sure you want to delete all collections? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "Cancelled."
  exit 0
fi

echo ""
echo "Deleting collections..."
echo ""

# Check if ChromaDB is running
if ! docker ps --format '{{.Names}}' | grep -q "^chat_chroma_db$"; then
  echo "ERROR: ChromaDB container (chat_chroma_db) is not running!"
  echo "Please start it first with: ./docker_files/start_all.sh"
  exit 1
fi

# Delete collections using Python script
docker run --rm \
  --name chainlit_delete_collections \
  --network host \
  -e PYTHONPATH=/app \
  chainlit-ingest:latest \
  -c 'python3 << EOF
import chromadb
import sys

try:
    client = chromadb.HttpClient(host="127.0.0.1", port=8001)

    # Get all collections
    collections = client.list_collections()
    print(f"Found {len(collections)} collections")

    # Delete each collection
    for collection in collections:
        print(f"Deleting collection: {collection.name}")
        client.delete_collection(collection.name)
        print(f"✓ Deleted: {collection.name}")

    print("")
    print("✓ All collections deleted successfully!")
    sys.exit(0)

except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)
EOF
'

if [ $? -eq 0 ]; then
  echo ""
  echo "==========================================================================="
  echo "COLLECTIONS DELETED"
  echo "==========================================================================="
  echo ""
  echo "All ChromaDB collections have been deleted."
  echo ""
  echo "Next steps:"
  echo "  1. Run ingestion to rebuild collections:"
  echo "     wsl bash docker_files/run_ingest_all.sh"
  echo ""
  echo "  2. Or use the reindex script:"
  echo "     wsl bash docker_files/reindex_all.sh"
  echo ""
else
  echo ""
  echo "ERROR: Failed to delete collections"
  exit 1
fi
