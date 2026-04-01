#!/bin/bash
# Wrapper script to run quick ingestion from inside chat_ui_app container
# Usage: bash ingest_specs/run_quick_ingest.sh

set -e

# Find project root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

CTN="${CTN:-chat_ui_app}"

echo "=== Running Quick Ingestion from Container ==="
echo "Container: $CTN"
echo "Target: /app/public/documents/specs"
echo ""

# Podman/Docker detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi

# Check if container is running
if ! $DOCKER_CMD ps --format '{{.Names}}' | grep -q "^${CTN}$"; then
  echo "ERROR: Container ${CTN} is not running!"
  echo "Start it first with: bash docker_files/start_all.sh"
  exit 1
fi

# Check if spec files exist
echo "Checking for spec files in container..."
FILE_COUNT=$($DOCKER_CMD exec "${CTN}" bash -c "ls -1 /app/public/documents/specs/*.spec 2>/dev/null | wc -l" || echo "0")

if [ "$FILE_COUNT" -eq 0 ]; then
  echo "WARNING: No .spec files found in /app/public/documents/specs"
  echo "Run ingestion download first: bash ingest_specs/run_ingest.sh"
  exit 1
fi

echo "Found $FILE_COUNT spec files"
echo ""

# Run quick ingestion
echo "Starting ingestion..."
$DOCKER_CMD exec -it "${CTN}" python3 /app/ingest_specs/quick_ingest_from_container.py

echo ""
echo "=== Ingestion Complete ==="
echo ""
echo "Check collection status with:"
echo "  bash docker_files/check_chroma.sh"
