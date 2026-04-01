#!/bin/bash
#
# Ingests Cribl documentation from the documents/cribl directory.
#
# This script runs the generic ingestion script with the correct environment
# variables to populate the `cribl_docs_mxbai` collection.
#
# Usage:
#   bash ingest_specs/run_ingest_cribl.sh
#

set -e

# Get the directory of this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Docker/Podman detection
if command -v podman &> /dev/null; then
    DOCKER_CMD="podman"
else
    DOCKER_CMD="docker"
fi
docker() { "$DOCKER_CMD" "$@"; }


echo "======================================================================"
echo "Ingesting Cribl Documentation"
echo "======================================================================"
echo ""
echo "Project root: $PROJECT_ROOT"
echo "Start time: $(date)"
echo ""

# Check if ChromaDB is running
if ! curl -s http://127.0.0.1:8001/api/v1/heartbeat > /dev/null 2>&1; then
    echo "ERROR: ChromaDB is not running on port 8001"
    echo "Please start it first: wsl bash docker_files/start_all.sh"
    exit 1
fi

echo "✓ ChromaDB is running"
echo ""

docker run --rm \
    --network chainlit_net \
    -v "$PROJECT_ROOT:/app" \
    -e CHROMA_HTTP_URL=http://chat_chroma_db:8001 \
    -e OLLAMA_BASE_URL=http://llm_api_service:11430 \
    -e OLLAMA_EMBED_MODEL=mxbai-embed-large \
    -e CHROMA_COLLECTION=cribl_docs_mxbai \
    -e SOURCE_ROOT=/app/documents/cribl \
    -e FILE_PATTERNS="*.html,*.pdf,*.md" \
    -e CHUNK_SIZE="1000" \
    -e CHUNK_OVERLAP="200" \
    -e INGEST_MAX_WORKERS=4 \
    chainlit-ingest:latest \
    python3 /app/ingest_specs/ingest_generic.py

echo ""
echo "✓ Cribl documentation ingestion completed"
echo ""
echo "======================================================================"
echo "Ingestion Complete!"
echo "======================================================================"
echo ""
echo "To verify collections, run:"
echo "  wsl bash docker_files/check_chroma.sh"
echo ""

