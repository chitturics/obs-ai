#!/bin/bash
# Full reindex: delete all ChromaDB collections and re-ingest everything
#
# Usage:
#   bash docker_files/reindex_all.sh              # Full reindex
#   bash docker_files/reindex_all.sh --dry-run     # Show what would happen
#   bash docker_files/reindex_all.sh --skip-delete  # Incremental only
#   bash docker_files/reindex_all.sh --list         # List current collections
#   bash docker_files/reindex_all.sh --collection spl_docs  # Reindex one collection

set -e

cd "$(dirname "$0")/.."

# Docker/Podman detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi

echo "==========================================================================="
echo "ChromaDB Full Reindex"
echo "==========================================================================="
echo ""

# Check if app container is running
if ! $DOCKER_CMD ps --format '{{.Names}}' | grep -q "^chat_ui_app$"; then
  echo "ERROR: App container (chat_ui_app) is not running!"
  echo "Please start it first: bash docker_files/start_all.sh"
  exit 1
fi

echo "Running reindex inside chat_ui_app container..."
echo ""

# Pass all arguments through to the Python script
$DOCKER_CMD exec chat_ui_app python3 /app/chat_app/run_quick_ingest.py "$@"

echo ""
echo "==========================================================================="
echo "Done!"
echo "==========================================================================="
