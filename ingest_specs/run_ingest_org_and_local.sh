#!/bin/bash
# ============================================================================
# Ingest Organization-Specific Configs and Local Documentation
# ============================================================================
# This script ingests:
# 1. Organization .conf files from documents/repo → org_repo_mxbai collection
# 2. Local PDF/HTML files from documents/ → local_docs_mxbai collection
#
# Collections created:
# - org_repo_mxbai: Organization-specific Splunk configs (PRIORITY 2 in search)
# - local_docs_mxbai: Local documentation PDFs/HTMLs (PRIORITY 6 in search)
# ============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Docker/Podman detection
if command -v podman &> /dev/null; then
    DOCKER_CMD="podman"
else
    DOCKER_CMD="docker"
fi
docker() { "$DOCKER_CMD" "$@"; }

echo "======================================================================"
echo "Ingesting Organization Configs and Local Documentation"
echo "======================================================================"
echo ""
echo "Project root: $PROJECT_ROOT"
echo "Start time: $(date)"
echo ""

# Check if ChromaDB is running
CHROMA_HOST="${CHROMA_HOST:-127.0.0.1}"
CHROMA_PORT="${CHROMA_PORT:-8001}"
if ! curl -s "http://${CHROMA_HOST}:${CHROMA_PORT}/api/v1/heartbeat" > /dev/null 2>&1; then
    echo "ERROR: ChromaDB is not running on ${CHROMA_HOST}:${CHROMA_PORT}"
    echo "Please start it first: bash docker_files/start_all.sh"
    exit 1
fi

echo "✓ ChromaDB is running"
echo ""

# ============================================================================
# STEP 1: Ingest Organization Repo Configs
# ============================================================================
echo "============================================================================"
echo "STEP 1/2: Ingesting Organization-Specific Configs"
echo "============================================================================"
echo ""
echo "Source: documents/repo/"
echo "Target collection: org_repo_mxbai"
echo "File types: *.conf, *.conf.spec"
echo ""

ORG_REPO_DIR="$PROJECT_ROOT/documents/repo"

if [ ! -d "$ORG_REPO_DIR" ]; then
    echo "⚠️  Warning: Organization repo directory not found: $ORG_REPO_DIR"
    echo "Creating directory..."
    mkdir -p "$ORG_REPO_DIR"
    echo "✓ Directory created. Place your .conf files there and re-run this script."
else
    CONF_COUNT=$(find "$ORG_REPO_DIR" -type f \( -name "*.conf" -o -name "*.spec" \) 2>/dev/null | wc -l)
    echo "Found $CONF_COUNT .conf/.spec files in org repo"

    if [ "$CONF_COUNT" -gt 0 ]; then
        echo ""
        echo "Running ingestion..."
        docker run --rm \
            --network chainlit_net \
            -v "$PROJECT_ROOT:/app" \
            -e CHROMA_HTTP_URL=http://chat_chroma_db:8001 \
            -e OLLAMA_BASE_URL=http://llm_api_service:11430 \
            -e OLLAMA_EMBED_MODEL=mxbai-embed-large \
            -e CHROMA_COLLECTION=org_repo_mxbai \
            -e SOURCE_ROOT=/app/documents/repo \
            -e FILE_PATTERNS="*.conf,*.spec" \
            -e INGEST_MAX_WORKERS=4 \
            chainlit-ingest:latest \
            python3 /app/ingest_specs/ingest_generic.py

        echo ""
        echo "✓ Organization configs ingestion completed"
    else
        echo "⚠️  No .conf or .spec files found. Skipping."
    fi
fi

echo ""

# ============================================================================
# STEP 2: Ingest Local Documentation
# ============================================================================
echo "============================================================================"
echo "STEP 2/2: Ingesting Local Documentation (PDF/HTML)"
echo "============================================================================"
echo ""
echo "Source: documents/"
echo "Target collection: local_docs_mxbai"
echo "File types: *.pdf, *.html"
echo ""

DOCS_DIR="$PROJECT_ROOT/documents"

if [ ! -d "$DOCS_DIR" ]; then
    echo "⚠️  Warning: Documents directory not found: $DOCS_DIR"
    echo "Creating directory..."
    mkdir -p "$DOCS_DIR"
    echo "✓ Directory created. Place your PDF/HTML files there and re-run this script."
else
    PDF_COUNT=$(find "$DOCS_DIR" -type f -name "*.pdf" 2>/dev/null | wc -l)
    HTML_COUNT=$(find "$DOCS_DIR" -type f \( -name "*.html" -o -name "*.htm" \) 2>/dev/null | wc -l)
    TOTAL_COUNT=$((PDF_COUNT + HTML_COUNT))

    echo "Found $PDF_COUNT PDF files"
    echo "Found $HTML_COUNT HTML files"
    echo "Total: $TOTAL_COUNT documents"

    if [ "$TOTAL_COUNT" -gt 0 ]; then
        echo ""
        echo "Running ingestion..."
        docker run --rm \
            --network chainlit_net \
            -v "$PROJECT_ROOT:/app" \
            -e CHROMA_HTTP_URL=http://chat_chroma_db:8001 \
            -e OLLAMA_BASE_URL=http://llm_api_service:11430 \
            -e OLLAMA_EMBED_MODEL=mxbai-embed-large \
            -e CHROMA_COLLECTION=local_docs_mxbai \
            -e SOURCE_ROOT=/app/documents \
            -e FILE_PATTERNS="*.pdf,*.html,*.htm" \
            -e INGEST_MAX_WORKERS=4 \
            chainlit-ingest:latest \
            python3 /app/ingest_specs/ingest_generic.py

        echo ""
        echo "✓ Local documentation ingestion completed"
    else
        echo "⚠️  No PDF or HTML files found. Skipping."
    fi
fi

echo ""
echo "======================================================================"
echo "Ingestion Complete!"
echo "======================================================================"
echo ""
echo "Collections created/updated:"
echo "  1. org_repo_mxbai - Organization-specific configs (Priority 2 in search)"
echo "  2. local_docs_mxbai - Local PDF/HTML documentation (Priority 6 in search)"
echo ""
echo "End time: $(date)"
echo ""
echo "To verify collections, run:"
echo "  bash docker_files/check_chroma.sh"
echo ""
