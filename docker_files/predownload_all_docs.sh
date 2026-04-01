#!/bin/bash
# Pre-download all documentation files for packaging
# This creates a complete offline documentation package

set -e

cd "$(dirname "$0")/.."

echo "=========================================================================="
echo "PRE-DOWNLOADING ALL DOCUMENTATION FOR PACKAGING"
echo "=========================================================================="
echo ""
echo "This will download:"
echo "  1. Splunk spec files (.spec, .conf) from GitHub"
echo "  2. SPL command documentation (.md) from docs.splunk.com"
echo ""
echo "Files will be saved to:"
echo "  - ingest_specs/    (spec and conf files)"
echo "  - spl_docs/        (SPL command markdown files)"
echo ""

# Create directories
mkdir -p "$(pwd)/ingest_specs"
mkdir -p "$(pwd)/spl_docs"

echo "=========================================================================="
echo "STEP 1: Downloading Splunk Spec Files"
echo "=========================================================================="
echo ""

# Check if ingest container image exists
if ! docker images | grep -q "chainlit-ingest"; then
  echo "ERROR: chainlit-ingest image not found!"
  echo "Please build it first with: wsl bash docker_files/build_all.sh"
  exit 1
fi

# Download spec files from GitHub
echo "Downloading spec files from GitHub (jewnix/splunk-spec-files)..."
echo ""

docker run --rm \
  --name chainlit_predownload_specs \
  -v "$(pwd)/ingest_specs:/app/ingest_specs" \
  chainlit-ingest:latest \
  -c 'cd /app/ingest_specs && python download_specs.py /app/ingest_specs'

if [ $? -ne 0 ]; then
  echo "ERROR: Failed to download spec files"
  exit 1
fi

echo ""
echo "✓ Spec files downloaded successfully"
echo ""

# Count spec files
SPEC_COUNT=$(find "$(pwd)/ingest_specs" -name "*.spec" | wc -l)
CONF_COUNT=$(find "$(pwd)/ingest_specs" -name "*.conf" | wc -l)

echo "Downloaded files:"
echo "  - .spec files: $SPEC_COUNT"
echo "  - .conf files: $CONF_COUNT"
echo ""

echo "=========================================================================="
echo "STEP 2: Downloading SPL Command Documentation"
echo "=========================================================================="
echo ""

# Download SPL command docs from docs.splunk.com
echo "Downloading SPL command documentation from docs.splunk.com..."
echo "This may take 10-15 minutes depending on network speed..."
echo ""

docker run --rm \
  --name chainlit_predownload_spl_docs \
  -v "$(pwd)/spl_docs:/app/spl_docs" \
  -v "$(pwd)/ingest_specs:/app/ingest_specs:ro" \
  chainlit-ingest:latest \
  -c 'cd /app/ingest_specs && python download_spl_docs.py /app/spl_docs'

if [ $? -ne 0 ]; then
  echo "WARNING: SPL docs download had some failures (this is normal)"
  echo "Some commands may not have individual documentation pages"
fi

echo ""
echo "✓ SPL documentation downloaded"
echo ""

# Count SPL docs
MD_COUNT=$(find "$(pwd)/spl_docs" -name "*.md" | wc -l)

echo "Downloaded files:"
echo "  - .md files: $MD_COUNT"
echo ""

echo "=========================================================================="
echo "STEP 3: Creating Metadata and Package Info"
echo "=========================================================================="
echo ""

# Create package metadata file
PACKAGE_META="$(pwd)/DOCUMENTATION_PACKAGE_INFO.json"

cat > "$PACKAGE_META" << EOF
{
  "package_name": "splunk_documentation_offline",
  "package_date": "$(date -u +"%Y-%m-%d %H:%M:%S UTC")",
  "version": "1.0.0",
  "contents": {
    "spec_files": {
      "directory": "ingest_specs/",
      "spec_count": $SPEC_COUNT,
      "conf_count": $CONF_COUNT,
      "total_count": $((SPEC_COUNT + CONF_COUNT)),
      "source": "https://github.com/jewnix/splunk-spec-files",
      "splunk_version": "9.3.2"
    },
    "spl_commands": {
      "directory": "spl_docs/",
      "md_count": $MD_COUNT,
      "source": "https://docs.splunk.com/Documentation/Splunk/latest/SearchReference/",
      "command_version": "9.4"
    }
  },
  "total_files": $((SPEC_COUNT + CONF_COUNT + MD_COUNT)),
  "deployment_instructions": {
    "step_1": "Copy ingest_specs/ and spl_docs/ directories to deployment machine",
    "step_2": "Run: wsl bash docker_files/run_ingest_all.sh --skip-download",
    "step_3": "This will ingest pre-downloaded files without re-downloading"
  },
  "disk_usage": {
    "ingest_specs": "$(du -sh "$(pwd)/ingest_specs" | cut -f1)",
    "spl_docs": "$(du -sh "$(pwd)/spl_docs" | cut -f1)",
    "total": "$(du -sh "$(pwd)/ingest_specs" "$(pwd)/spl_docs" | tail -1 | cut -f1)"
  }
}
EOF

echo "✓ Created package metadata: $PACKAGE_META"
echo ""

echo "=========================================================================="
echo "STEP 4: Creating Deployment Package Archive (Optional)"
echo "=========================================================================="
echo ""

# Ask user if they want to create tar.gz archive
read -p "Create tar.gz archive for easy deployment? (y/n) " -n 1 -r
echo ""

if [[ $REPLY =~ ^[Yy]$ ]]; then
  ARCHIVE_NAME="splunk_docs_offline_$(date +%Y%m%d_%H%M%S).tar.gz"

  echo "Creating archive: $ARCHIVE_NAME"
  echo "This may take a few minutes..."
  echo ""

  tar -czf "$ARCHIVE_NAME" \
    ingest_specs/ \
    spl_docs/ \
    DOCUMENTATION_PACKAGE_INFO.json \
    docker_files/run_ingest_all.sh \
    ingest_specs/ingest_specs.py \
    ingest_specs/download_specs.py \
    ingest_specs/download_spl_docs.py

  ARCHIVE_SIZE=$(du -sh "$ARCHIVE_NAME" | cut -f1)

  echo "✓ Archive created: $ARCHIVE_NAME ($ARCHIVE_SIZE)"
  echo ""
  echo "To deploy on another machine:"
  echo "  1. Copy $ARCHIVE_NAME to target machine"
  echo "  2. Extract: tar -xzf $ARCHIVE_NAME"
  echo "  3. Run ingestion: wsl bash docker_files/run_ingest_all.sh --skip-download"
  echo ""
fi

echo "=========================================================================="
echo "DOWNLOAD COMPLETE - SUMMARY"
echo "=========================================================================="
echo ""
echo "Documentation files ready for packaging:"
echo ""
echo "Directory Structure:"
echo "  ingest_specs/"
echo "    ├── *.spec files: $SPEC_COUNT"
echo "    ├── *.conf files: $CONF_COUNT"
echo "    ├── download_specs.py"
echo "    ├── download_spl_docs.py"
echo "    └── ingest_specs.py"
echo ""
echo "  spl_docs/"
echo "    └── spl_cmd_*.md files: $MD_COUNT"
echo ""
echo "Total documentation files: $((SPEC_COUNT + CONF_COUNT + MD_COUNT))"
echo ""
echo "Disk usage:"
cat "$PACKAGE_META" | grep -A3 '"disk_usage"' | grep -v 'disk_usage'
echo ""
echo "Package metadata: DOCUMENTATION_PACKAGE_INFO.json"
echo ""
echo "=========================================================================="
echo "DEPLOYMENT OPTIONS"
echo "=========================================================================="
echo ""
echo "Option 1: Copy directories to deployment machine"
echo "  - Copy ingest_specs/ and spl_docs/ directories"
echo "  - Run: wsl bash docker_files/run_ingest_all.sh --skip-download"
echo ""
echo "Option 2: Use tar.gz archive (if created above)"
echo "  - Copy the .tar.gz file to deployment machine"
echo "  - Extract and run ingestion with --skip-download"
echo ""
echo "Option 3: Include in Docker image"
echo "  - Add COPY statements to Dockerfile to include these directories"
echo "  - Files will be available inside container without downloading"
echo ""
echo "=========================================================================="
echo "VERIFICATION"
echo "=========================================================================="
echo ""
echo "Verify downloads:"
echo "  ls -lh ingest_specs/*.spec | head -5"
echo "  ls -lh spl_docs/*.md | head -5"
echo ""
echo "View package info:"
echo "  cat DOCUMENTATION_PACKAGE_INFO.json"
echo ""
echo "Test ingestion with pre-downloaded files:"
echo "  wsl bash docker_files/run_ingest_all.sh --skip-download"
echo ""
echo "=========================================================================="
echo ""
