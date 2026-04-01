#!/bin/bash
# Wrapper script to deduplicate all ChromaDB collections
# Runs from any location - auto-detects project root

set -e

# Find project root
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$PROJECT_ROOT"

CTN="${CTN:-chat_ui_app}"
CHROMA_HOST="${CHROMA_HOST:-127.0.0.1}"
CHROMA_PORT="${CHROMA_PORT:-8001}"

echo "=== Deduplicating All ChromaDB Collections ==="
echo "Project Root: $PROJECT_ROOT"
echo "Container: $CTN"
echo ""

# Podman/Docker detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi

# Copy dedup script into container
echo "Copying dedup_chroma.py into container..."
$DOCKER_CMD cp "$PROJECT_ROOT/utilities/dedup_chroma.py" "${CTN}":/app/dedup_chroma.py

# Get list of collections
echo "Fetching collection list..."
collections=$($DOCKER_CMD exec -i "${CTN}" python3 - <<'PY'
from chromadb import HttpClient
from chromadb.config import Settings
cli = HttpClient(host='127.0.0.1', port=8001, settings=Settings(anonymized_telemetry=False, allow_reset=True))
names = [c.name for c in cli.list_collections()]
print(' '.join(names))
print(f'Total collections: {len(names)}', file=__import__('sys').stderr)
PY
)

echo "$collections" >&2
echo ""

# Extract first line of names (space-separated)
name_line=$(echo "${collections}" | head -n1 | tr -d '\r')

if [ -z "$name_line" ]; then
  echo "No collections found!"
  exit 0
fi

# Deduplicate each collection
for coll in ${name_line}; do
  echo "=== Deduping collection: ${coll} ==="
  $DOCKER_CMD exec -i "${CTN}" bash -c "CHROMA_COLLECTION='${coll}' python3 /app/dedup_chroma.py"
  echo ""
done

echo "=== Deduplication Complete ==="
