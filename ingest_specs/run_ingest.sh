#!/bin/bash
# Run ingest_specs ingestion
# This script runs the ingestion container to populate ChromaDB with spec files

set -e

cd "$(dirname "$0")/.."

# Docker/Podman detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi
docker() { "$DOCKER_CMD" "$@"; }

echo "=== Running Spec Ingestion ==="
echo ""

# Check if ChromaDB is running
if ! docker ps --format '{{.Names}}' | grep -q "^chat_chroma_db$"; then
  echo "ERROR: ChromaDB container (chat_chroma_db) is not running!"
  echo "Please start it first with: ./docker_files/start_all.sh"
  exit 1
fi

# Step 1: Download latest spec files from GitHub (skip if --skip-download)
if [ "$1" != "--skip-download" ]; then
  echo "Step 1: Downloading latest Splunk spec files from GitHub..."
  echo "(Use --skip-download to skip this step if files already exist)"
  echo ""

  docker run --rm \
    --name chainlit_download_specs \
    -v "$(pwd)/documents/specs:/app/documents/specs" \
    -v "$(pwd)/ingest_specs:/app/ingest_specs:ro" \
    chainlit-ingest:latest \
    -c 'cd /app/ingest_specs && python download_specs.py /app/documents/specs'

  if [ $? -ne 0 ]; then
    echo "WARNING: Download failed, but continuing with existing files..."
    echo "If you have spec files already, ingestion will proceed."
  fi

  echo ""
fi

echo "Step 2: Running ingestion..."
echo ""

docker run \
  --name chainlit_ingest_run \
  --network host \
  -v "$(pwd)/documents/specs:/app/documents/specs:ro" \
  -v "$(pwd)/ingest_specs:/app/ingest_specs:ro" \
  -v specs_chroma_data:/app/specs_chroma_store \
  -e CHROMA_HTTP_URL=http://127.0.0.1:8001 \
  -e CHROMA_COLLECTION=specs_mxbai_embed_large_v3 \
  -e PYTHONPATH=/app \
  chainlit-ingest:latest \
  -c 'cd /app/ingest_specs && python ingest_documents.py /app/documents/specs'

echo ""
echo "=== Ingestion Complete ==="
echo ""
echo "Check ChromaDB collection at: http://localhost:8001"
echo ""
echo "Container 'chainlit_ingest_run' is still running for log review."
echo "To view logs:"
echo "  podman logs chainlit_ingest_run"
echo ""
echo "To view manifest/checksums:"
echo "  podman exec chainlit_ingest_run cat /app/specs_chroma_store/ingest_specs_manifest.json"
echo ""
echo "To cleanup when done:"
echo "  podman rm chainlit_ingest_run"
echo ""
