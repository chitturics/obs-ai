#!/bin/bash
# Force re-ingestion of all collections
# This script will delete all collections and re-ingest from source files
# Runs inside the chat_ui_app container — no separate ingest image needed

set -e

cd "$(dirname "$0")/.."

# Docker/Podman detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi

echo "================================================================================"
echo "Force Re-Ingestion - All Collections"
echo "================================================================================"
echo ""
echo "This will:"
echo "  1. Delete all ChromaDB collections"
echo "  2. Re-ingest all documents (specs, commands, org configs, local docs)"
echo "  3. Uses current chunking settings from config.yaml"
echo ""
read -p "Continue? (y/N) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Cancelled."
    exit 1
fi

# Check if app container is running
if ! $DOCKER_CMD ps --format '{{.Names}}' | grep -q "^chat_ui_app$"; then
    echo ""
    echo "ERROR: App container (chat_ui_app) is not running!"
    echo "Please start it first: bash docker_files/start_all.sh"
    exit 1
fi

echo ""
echo "Running full reindex inside chat_ui_app container..."
echo ""

$DOCKER_CMD exec chat_ui_app python3 /app/chat_app/run_quick_ingest.py

echo ""
echo "================================================================================"
echo "Re-Ingestion Complete!"
echo "================================================================================"
echo ""
