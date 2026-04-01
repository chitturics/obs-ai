#!/bin/bash
# Run ingestion for SPL command documentation only

set -e

cd "$(dirname "$0")/.."

# Docker/Podman detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi
docker() { "$DOCKER_CMD" "$@"; }

echo "=== Running SPL Command Documentation Ingestion ==="
echo ""

# Require ChromaDB to be running (host network expected)
if ! docker ps --format '{{.Names}}' | grep -q "^chat_chroma_db$"; then
  echo "ERROR: ChromaDB container (chat_chroma_db) is not running!"
  echo "Start it first with: ./docker_files/start_all.sh"
  exit 1
fi

# Ensure volumes/dirs exist (ignore if already present)
docker volume create spl_docs_chroma_data >/dev/null 2>&1 || true
mkdir -p "$(pwd)/documents/commands"

echo "Step 1: Downloading SPL command documentation from docs.splunk.com..."
docker run --rm \
  --name chainlit_download_spl_docs \
  -v "$(pwd)/documents/commands:/app/documents/commands" \
  -v "$(pwd)/ingest_specs:/app/ingest_specs:ro" \
  chainlit-ingest:latest \
  -c 'cd /app/ingest_specs && python download_spl_docs.py /app/documents/commands'

echo ""
echo "Step 2: Ingesting SPL command docs into Chroma (collection: spl_commands_mxbai)..."
docker run \
  --name chainlit_ingest_spl_docs \
  --network host \
  -v "$(pwd)/documents/commands:/app/documents/commands:ro" \
  -v "$(pwd)/ingest_specs:/app/ingest_specs:ro" \
  -v spl_docs_chroma_data:/app/spl_docs_chroma_store \
  -e CHROMA_HTTP_URL=http://127.0.0.1:8001 \
  -e CHROMA_COLLECTION=spl_commands_mxbai \
  -e CHROMA_DIR=/app/spl_docs_chroma_store \
  -e PYTHONPATH=/app \
  -e ALLOWED_EXTS=.md \
  chainlit-ingest:latest \
  -c 'cd /app/ingest_specs && python ingest_documents.py /app/documents/commands'

echo ""
echo "=== SPL command ingestion complete ==="
echo "Collection: spl_commands_mxbai"
echo "Docs path: $(pwd)/documents/commands"
echo ""
echo "Container 'chainlit_ingest_spl_docs' is still running for log review."
echo "To view logs:"
echo "  podman logs chainlit_ingest_spl_docs"
echo ""
echo "To cleanup when done:"
echo "  podman rm chainlit_ingest_spl_docs"
echo ""
