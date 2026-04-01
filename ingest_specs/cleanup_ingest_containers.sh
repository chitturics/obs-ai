#!/bin/bash
# Cleanup ingestion containers after reviewing logs/manifests
# These containers are left running by run_ingest_all.sh for inspection

set -e

# Docker/Podman detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi

echo "=== Cleaning up ingestion containers ==="
echo ""

CONTAINERS=(
  "chainlit_ingest_specs"
  "chainlit_ingest_spl_docs"
  "chainlit_ingest_org_repo"
  "chainlit_ingest_local_docs"
  "chainlit_ingest_run"
)

for container in "${CONTAINERS[@]}"; do
  if $DOCKER_CMD ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
    echo "Removing container: $container"
    $DOCKER_CMD rm -f "$container"
  else
    echo "Container not found (already removed or never created): $container"
  fi
done

echo ""
echo "✓ Cleanup complete"
echo ""
echo "Note: This does NOT remove the data volumes (specs_chroma_data, etc.)"
echo "To remove data volumes as well, run:"
echo "  $DOCKER_CMD volume rm specs_chroma_data spl_docs_chroma_data repo_chroma_data local_docs_chroma_data"
echo ""
