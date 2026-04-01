#!/bin/bash
set -euo pipefail

# Fix permissions on mounted volume (host UID may differ)
chmod 755 /root/.ollama 2>/dev/null || true
chmod 600 /root/.ollama/id_ed25519 2>/dev/null || true

ollama serve &
OLLAMA_PID=$!

sleep 10

# Pull models if specified
if [ -n "${OLLAMA_MODEL:-}" ]; then
    echo "Pulling model: ${OLLAMA_MODEL}"
    ollama pull "${OLLAMA_MODEL}" || true
fi

if [ -n "${OLLAMA_EMBED_MODEL:-}" ]; then
    echo "Pulling embedding model: ${OLLAMA_EMBED_MODEL}"
    ollama pull "${OLLAMA_EMBED_MODEL}" || true
fi

wait $OLLAMA_PID
