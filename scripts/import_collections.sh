#!/bin/bash
# =============================================================================
# Import Pre-built Collections
# =============================================================================
# Imports pre-built ChromaDB collections into Docker/Podman volume.
# Run this on remote machine before starting services.
# =============================================================================

set -e

cd "$(dirname "$0")/.."

# Docker/Podman detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi

INPUT_DIR="${1:-chroma_collections_backup}"

echo "================================================================================"
echo "Importing Pre-built ChromaDB Collections"
echo "================================================================================"
echo ""

# Check if input directory exists
if [ ! -d "$INPUT_DIR" ]; then
  echo "✗ Input directory not found: $INPUT_DIR"
  echo ""
  echo "Usage: $0 [input_directory]"
  echo ""
  echo "Example:"
  echo "  $0 chroma_collections_backup"
  echo "  $0 /opt/obsai/collections/data"
  exit 1
fi

echo "Input directory: $INPUT_DIR"
echo ""

# Check if volume exists
if $DOCKER_CMD volume inspect chroma_data &>/dev/null; then
  echo "⚠️  Volume 'chroma_data' already exists"
  read -p "Delete and recreate? (y/N): " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Deleting existing volume..."
    $DOCKER_CMD volume rm chroma_data
  else
    echo "Aborted"
    exit 1
  fi
fi

# Create volume
echo "Creating volume: chroma_data"
$DOCKER_CMD volume create chroma_data

# Import data
echo "Importing collections data..."

# Method 1: tar into volume
if tar -C "$INPUT_DIR" -c . | $DOCKER_CMD volume import chroma_data - 2>/dev/null; then
  echo "✓ Imported using volume import"
else
  # Method 2: Copy via temporary container
  echo "Trying alternative import method..."
  $DOCKER_CMD run --rm \
    -v chroma_data:/data \
    -v "$(realpath $INPUT_DIR):/import:ro" \
    alpine sh -c "cp -r /import/* /data/"
  echo "✓ Imported using container copy"
fi

# Verify
echo ""
echo "Verifying import..."
$DOCKER_CMD run --rm -v chroma_data:/data alpine ls -lh /data/

echo ""
echo "================================================================================"
echo "Import Complete!"
echo "================================================================================"
echo ""
echo "Next steps:"
echo "  bash docker_files/start_all.sh --no-ingest"
echo "  (or: bash docker_files/start_all_optimized.sh --no-ingest)"
echo ""
echo "Collections are ready to use!"
echo "================================================================================"
