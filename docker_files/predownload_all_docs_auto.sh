#!/bin/bash
# Pre-download all documentation files for packaging (non-interactive)
# This creates a complete offline documentation package automatically

set -e

cd "$(dirname "$0")/.."

echo "=========================================================================="
echo "PRE-DOWNLOADING ALL DOCUMENTATION FOR PACKAGING"
echo "=========================================================================="
echo ""

# Create directories
mkdir -p "$(pwd)/ingest_specs"
mkdir -p "$(pwd)/spl_docs"

# Check if ingest container image exists
if ! docker images | grep -q "chainlit-ingest"; then
  echo "ERROR: chainlit-ingest image not found!"
  echo "Building it now..."
  wsl bash docker_files/build_all.sh
fi

echo "=========================================================================="
echo "STEP 1: Downloading Splunk Spec Files"
echo "=========================================================================="
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
echo "✓ Spec files downloaded"

# Count spec files
SPEC_COUNT=$(find "$(pwd)/ingest_specs" -name "*.spec" 2>/dev/null | wc -l)
CONF_COUNT=$(find "$(pwd)/ingest_specs" -name "*.conf" 2>/dev/null | wc -l)

echo "  - .spec files: $SPEC_COUNT"
echo "  - .conf files: $CONF_COUNT"
echo ""

echo "=========================================================================="
echo "STEP 2: Downloading SPL Command Documentation"
echo "=========================================================================="
echo ""

docker run --rm \
  --name chainlit_predownload_spl_docs \
  -v "$(pwd)/spl_docs:/app/spl_docs" \
  -v "$(pwd)/ingest_specs:/app/ingest_specs:ro" \
  chainlit-ingest:latest \
  -c 'cd /app/ingest_specs && python download_spl_docs.py /app/spl_docs'

echo ""
echo "✓ SPL documentation downloaded"

# Count SPL docs
MD_COUNT=$(find "$(pwd)/spl_docs" -name "*.md" 2>/dev/null | wc -l)
echo "  - .md files: $MD_COUNT"
echo ""

echo "=========================================================================="
echo "STEP 3: Creating Package Metadata"
echo "=========================================================================="
echo ""

# Get disk usage
INGEST_SIZE=$(du -sh "$(pwd)/ingest_specs" 2>/dev/null | cut -f1 || echo "N/A")
SPL_SIZE=$(du -sh "$(pwd)/spl_docs" 2>/dev/null | cut -f1 || echo "N/A")

# Create package metadata file
cat > "$(pwd)/DOCUMENTATION_PACKAGE_INFO.json" << EOF
{
  "package_name": "splunk_documentation_offline",
  "package_date": "$(date -u +"%Y-%m-%d %H:%M:%S UTC" 2>/dev/null || date)",
  "version": "1.0.0",
  "contents": {
    "spec_files": {
      "directory": "ingest_specs/",
      "spec_count": $SPEC_COUNT,
      "conf_count": $CONF_COUNT,
      "total_count": $((SPEC_COUNT + CONF_COUNT)),
      "source": "https://github.com/jewnix/splunk-spec-files",
      "splunk_version": "9.3.2",
      "disk_size": "$INGEST_SIZE"
    },
    "spl_commands": {
      "directory": "spl_docs/",
      "md_count": $MD_COUNT,
      "source": "https://docs.splunk.com/Documentation/Splunk/latest/SearchReference/",
      "command_version": "9.4",
      "disk_size": "$SPL_SIZE"
    }
  },
  "total_files": $((SPEC_COUNT + CONF_COUNT + MD_COUNT)),
  "deployment_instructions": {
    "step_1": "Copy ingest_specs/ and spl_docs/ directories to deployment",
    "step_2": "Run: wsl bash docker_files/run_ingest_all.sh --skip-download",
    "step_3": "Pre-downloaded files will be ingested without re-downloading"
  }
}
EOF

echo "✓ Created: DOCUMENTATION_PACKAGE_INFO.json"
echo ""

echo "=========================================================================="
echo "DOWNLOAD COMPLETE"
echo "=========================================================================="
echo ""
echo "Total documentation files: $((SPEC_COUNT + CONF_COUNT + MD_COUNT))"
echo "  - Spec files (.spec): $SPEC_COUNT"
echo "  - Conf files (.conf): $CONF_COUNT"
echo "  - SPL docs (.md): $MD_COUNT"
echo ""
echo "Directories:"
echo "  - ingest_specs/ ($INGEST_SIZE)"
echo "  - spl_docs/ ($SPL_SIZE)"
echo ""
echo "To deploy on another machine:"
echo "  1. Copy ingest_specs/ and spl_docs/ directories"
echo "  2. Run: wsl bash docker_files/run_ingest_all.sh --skip-download"
echo ""
echo "To create archive for deployment:"
echo "  tar -czf splunk_docs_$(date +%Y%m%d).tar.gz ingest_specs/ spl_docs/ DOCUMENTATION_PACKAGE_INFO.json"
echo ""
