#!/bin/bash
# Wrapper script to query ChromaDB from container
# Usage: bash utilities/run_query_chroma.sh "inputs.conf" [k]

set -e

# Find project root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

CTN="${CTN:-chat_ui_app}"
SEARCH_TERM="${1:-inputs.conf}"
K="${2:-20}"

echo "=== Querying ChromaDB ==="
echo "Container: $CTN"
echo "Search term: $SEARCH_TERM"
echo "Top K: $K"
echo ""

# Podman/Docker detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi

# Run query in container
$DOCKER_CMD exec -it "${CTN}" python3 /app/utilities/query_chroma.py "$SEARCH_TERM" "$K"
