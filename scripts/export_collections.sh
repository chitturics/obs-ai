#!/bin/bash
# =============================================================================
# Export Pre-built Collections for Repo
# =============================================================================
# Exports ChromaDB collections data for committing to repo or separate repo.
# Run this after full ingestion is complete.
# =============================================================================

set -e

cd "$(dirname "$0")/.."

# Docker/Podman detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi

OUTPUT_DIR="${1:-chroma_collections_backup}"

echo "================================================================================"
echo "Exporting ChromaDB Collections"
echo "================================================================================"
echo ""
echo "Output directory: $OUTPUT_DIR"
echo ""

# Create output directory
mkdir -p "$OUTPUT_DIR"

# Check if ChromaDB container is running
if ! $DOCKER_CMD ps --format '{{.Names}}' | grep -q "^chat_chroma_db$"; then
  echo "✗ ChromaDB container is not running"
  echo "  Start it with: bash docker_files/start_all.sh"
  exit 1
fi

# Export ChromaDB data
echo "Exporting ChromaDB volume data..."

# Method 1: Direct copy from container
if $DOCKER_CMD cp chat_chroma_db:/data/. "$OUTPUT_DIR/" 2>/dev/null; then
  echo "✓ Exported using direct copy"
else
  # Method 2: Volume export
  echo "Trying volume export method..."
  $DOCKER_CMD volume export chroma_data | tar -xv -C "$OUTPUT_DIR/"
  echo "✓ Exported using volume export"
fi

# Check what was exported
echo ""
echo "Exported collections:"
ls -lh "$OUTPUT_DIR/"
echo ""

# Calculate size
TOTAL_SIZE=$(du -sh "$OUTPUT_DIR/" | cut -f1)
echo "Total size: $TOTAL_SIZE"
echo ""

# List collections
echo "Collections in export:"
if [ -f "$OUTPUT_DIR/chroma.sqlite3" ]; then
  echo "  ✓ chroma.sqlite3 (metadata database)"
fi
if [ -d "$OUTPUT_DIR/chroma" ]; then
  ls -lh "$OUTPUT_DIR/chroma/" | grep -v "^total" || echo "  (empty)"
fi

echo ""
echo "================================================================================"
echo "Export Complete!"
echo "================================================================================"
echo ""
echo "Next steps:"
echo ""
echo "Option 1: Commit to main repo"
echo "  git add $OUTPUT_DIR/"
echo "  git commit -m 'Add pre-built collections'"
echo "  git push"
echo ""
echo "Option 2: Create separate repo"
echo "  mkdir ~/splunk-collections"
echo "  cp -r $OUTPUT_DIR/* ~/splunk-collections/"
echo "  cd ~/splunk-collections"
echo "  git init && git add . && git commit -m 'Initial collections'"
echo ""
echo "Option 3: Transfer to remote"
echo "  tar -czf collections.tar.gz $OUTPUT_DIR/"
echo "  scp collections.tar.gz remote:/opt/obsai/"
echo ""
echo "================================================================================"
