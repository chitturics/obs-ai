#!/bin/bash
# Prepare documentation files for inclusion in Docker image
# This downloads all spec and SPL docs before building the ingest container

set -e

cd "$(dirname "$0")/.."

echo "=========================================================================="
echo "PREPARING DOCUMENTATION FOR DOCKER IMAGE INCLUSION"
echo "=========================================================================="
echo ""

# Create staging directories if they don't exist
mkdir -p "$(pwd)/ingest_specs_bundled"
mkdir -p "$(pwd)/spl_docs_bundled"

# Check if we need to download or use existing files
USE_EXISTING=false
if [ -d "$(pwd)/ingest_specs" ] && [ -n "$(ls -A $(pwd)/ingest_specs/*.spec 2>/dev/null)" ]; then
  EXISTING_SPECS=$(find "$(pwd)/ingest_specs" -name "*.spec" | wc -l)
  if [ "$EXISTING_SPECS" -gt 50 ]; then
    echo "Found existing spec files in ingest_specs/ ($EXISTING_SPECS files)"
    read -p "Use existing files instead of re-downloading? (y/n) " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
      USE_EXISTING=true
    fi
  fi
fi

if [ "$USE_EXISTING" = true ]; then
  echo "Using existing files..."
  echo ""

  # Copy existing files to bundled directories
  echo "Copying spec files..."
  cp -r "$(pwd)/ingest_specs"/*.{spec,conf} "$(pwd)/ingest_specs_bundled/" 2>/dev/null || true

  echo "Copying SPL docs..."
  cp -r "$(pwd)/spl_docs"/*.md "$(pwd)/spl_docs_bundled/" 2>/dev/null || true

else
  echo "Building temporary ingest image to download documentation..."
  echo ""

  # Build a minimal ingest image with just the download scripts
  docker build -f - -t chainlit-ingest-temp:latest . << 'EOF'
FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl \
    && rm -rf /var/lib/apt/lists/*

COPY containers/ingest/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir requests beautifulsoup4 lxml tqdm

COPY chat_app /app/chat_app
COPY ingest_specs/*.py /app/ingest_specs/

ENTRYPOINT ["/bin/bash"]
EOF

  echo ""
  echo "Downloading spec files from GitHub..."
  docker run --rm \
    --name chainlit_prep_download_specs \
    -v "$(pwd)/ingest_specs_bundled:/app/ingest_specs_bundled" \
    chainlit-ingest-temp:latest \
    -c 'cd /app/ingest_specs && python download_specs.py /app/ingest_specs_bundled'

  echo ""
  echo "Downloading SPL command documentation..."
  docker run --rm \
    --name chainlit_prep_download_spl \
    -v "$(pwd)/spl_docs_bundled:/app/spl_docs_bundled" \
    -v "$(pwd)/ingest_specs_bundled:/app/ingest_specs_bundled:ro" \
    chainlit-ingest-temp:latest \
    -c 'cd /app/ingest_specs && python download_spl_docs.py /app/spl_docs_bundled'

  echo ""
  echo "Cleaning up temporary image..."
  docker rmi chainlit-ingest-temp:latest
fi

echo ""
echo "=========================================================================="
echo "DOCUMENTATION PREPARATION COMPLETE"
echo "=========================================================================="
echo ""

# Count files
SPEC_COUNT=$(find "$(pwd)/ingest_specs_bundled" -name "*.spec" 2>/dev/null | wc -l)
CONF_COUNT=$(find "$(pwd)/ingest_specs_bundled" -name "*.conf" 2>/dev/null | wc -l)
MD_COUNT=$(find "$(pwd)/spl_docs_bundled" -name "*.md" 2>/dev/null | wc -l)

echo "Files ready for Docker image inclusion:"
echo "  - .spec files: $SPEC_COUNT"
echo "  - .conf files: $CONF_COUNT"
echo "  - .md files: $MD_COUNT"
echo ""
echo "Directories created:"
echo "  - ingest_specs_bundled/ (will be copied into Docker image)"
echo "  - spl_docs_bundled/ (will be copied into Docker image)"
echo ""
echo "Next steps:"
echo "  1. These files will be included when you build the ingest image"
echo "  2. Run: wsl bash docker_files/build_all.sh"
echo "  3. The ingest container will have all docs pre-loaded"
echo ""
