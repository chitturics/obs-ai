#!/bin/bash
# Build Chainlit app with documents baked in (no external mounts)
# Auto-detects /opt/obsai/chatbot or /opt/obsai/chatapp

set -e

cd "$(dirname "$0")/.."

# Docker/Podman detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi

echo "================================================================================"
echo "Building Chainlit App with Documents Baked In"
echo "================================================================================"
echo ""
echo "Container tool: $DOCKER_CMD"
echo "Build time:     $(date)"
echo ""

# Auto-detect documents directory from project root
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
if [ -d "$PROJECT_DIR/documents" ]; then
  DOCS_DIR="${DOCS_DIR:-$PROJECT_DIR/documents}"
elif [ -d "/opt/obsai/chatbot/documents" ]; then
  DOCS_DIR="${DOCS_DIR:-/opt/obsai/chatbot/documents}"
else
  DOCS_DIR="${DOCS_DIR:-./documents}"
fi

echo "📁 Checking for documents at: $DOCS_DIR"
echo ""

if [ ! -d "$DOCS_DIR" ]; then
    echo "❌ ERROR: Documents directory not found: $DOCS_DIR"
    echo ""
    echo "Expected structure:"
    echo "  $DOCS_DIR/specs/       - Splunk .spec files"
    echo "  $DOCS_DIR/repo/        - Your org repo configs"
    echo "  $DOCS_DIR/commands/    - SPL command docs"
    echo "  $DOCS_DIR/pdfs/        - PDF documentation"
    echo ""
    echo "Please create the documents directory or set DOCS_DIR:"
    echo "  export DOCS_DIR=/path/to/your/documents"
    echo "  bash docker_files/build_with_documents.sh"
    exit 1
fi

# Check subdirectories
for subdir in specs repo commands pdfs; do
    if [ -d "$DOCS_DIR/$subdir" ]; then
        COUNT=$(find "$DOCS_DIR/$subdir" -type f 2>/dev/null | wc -l)
        echo "  ✅ $subdir/ ($COUNT files)"
    else
        echo "  ⚠️  $subdir/ (missing - will create empty)"
        mkdir -p "$DOCS_DIR/$subdir"
    fi
done

echo ""
echo "📦 Total files to copy: $(find "$DOCS_DIR" -type f | wc -l)"
echo ""

# Create temporary build context with documents
echo "🔨 Preparing build context..."

BUILD_DIR=$(mktemp -d)
trap "rm -rf $BUILD_DIR" EXIT

# Copy application code
echo "  Copying application code..."
cp -r chat_app "$BUILD_DIR/"
cp -r containers "$BUILD_DIR/"
cp -r shared "$BUILD_DIR/"
cp -r public "$BUILD_DIR/"
cp -r skills "$BUILD_DIR/"
cp -r metadata "$BUILD_DIR/"
cp -r postgres "$BUILD_DIR/"
cp -r frontend/dist "$BUILD_DIR/admin-ui" 2>/dev/null || true
cp config.yaml "$BUILD_DIR/" 2>/dev/null || true
cp docker_files/entrypoint.app.sh "$BUILD_DIR/" 2>/dev/null || true

# Copy documents
echo "  Copying documents from $DOCS_DIR..."
mkdir -p "$BUILD_DIR/documents"
cp -r "$DOCS_DIR"/* "$BUILD_DIR/documents/" 2>/dev/null || true

# Copy Dockerfile
cp docker_files/Dockerfile.app.no_mounts "$BUILD_DIR/Dockerfile"

echo "✅ Build context ready"
echo ""

# Build image
echo "🏗️  Building Docker image..."
echo ""

$DOCKER_CMD build \
  -f "$BUILD_DIR/Dockerfile" \
  -t chainlit-app:latest \
  "$BUILD_DIR"

if [ $? -eq 0 ]; then
    echo ""
    echo "================================================================================"
    echo "✅ BUILD SUCCESSFUL"
    echo "================================================================================"
    echo ""
    echo "Image: chainlit-app:latest"
    echo ""
    echo "Documents baked in:"
    $DOCKER_CMD run --rm chainlit-app:latest find /app/chat_app/public/documents -type f | wc -l | xargs echo "  Total files:"
    echo ""
    echo "Next steps:"
    echo "  1. Start containers:"
    echo "     bash docker_files/start_no_mounts.sh"
    echo ""
    echo "  2. Access app:"
    echo "     http://your-server:8000"
    echo ""
    echo "To update documents:"
    echo "  1. Update files in $DOCS_DIR"
    echo "  2. Rebuild:"
    echo "     bash docker_files/build_with_documents.sh"
    echo "  3. Restart:"
    echo "     bash docker_files/start_no_mounts.sh"
    echo ""
else
    echo ""
    echo "================================================================================"
    echo "❌ BUILD FAILED"
    echo "================================================================================"
    echo ""
    echo "Check error messages above for details."
    echo ""
    exit 1
fi
