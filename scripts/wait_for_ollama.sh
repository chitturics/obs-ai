#!/bin/bash
# =============================================================================
# Wait for Ollama to be Ready
# =============================================================================
# This script waits for Ollama service to be fully ready before continuing.
# Useful before running ingestion or other operations that need Ollama.
# =============================================================================

TIMEOUT=${1:-120}  # Default 120 seconds timeout
INTERVAL=2

# Docker/Podman detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi

echo "Waiting for Ollama to be ready (timeout: ${TIMEOUT}s)..."

elapsed=0
while [ $elapsed -lt $TIMEOUT ]; do
  # Check if Ollama container is running
  if ! $DOCKER_CMD ps --format '{{.Names}}' | grep -q "^llm_api_service$"; then
    echo ""
    echo "✗ Ollama container (llm_api_service) is not running"
    echo "  Start it with: bash docker_files/start_all.sh"
    exit 1
  fi

  # Check if Ollama responds to commands
  if $DOCKER_CMD exec llm_api_service ollama list &>/dev/null; then
    echo ""
    echo "✓ Ollama is ready ($elapsed seconds)"

    # Extra buffer for model loading
    echo "Waiting 5 more seconds for model initialization..."
    sleep 5

    echo "✓ Ollama fully ready"
    exit 0
  fi

  echo -n "."
  sleep $INTERVAL
  elapsed=$((elapsed + INTERVAL))
done

echo ""
echo "✗ Timeout: Ollama did not become ready after ${TIMEOUT} seconds"
echo ""
echo "Troubleshooting:"
echo "  1. Check Ollama logs: $DOCKER_CMD logs llm_api_service"
echo "  2. Check if models are downloaded: $DOCKER_CMD exec llm_api_service ollama list"
echo "  3. Restart Ollama: $DOCKER_CMD restart llm_api_service"
exit 1
