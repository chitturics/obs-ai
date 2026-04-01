#!/bin/bash
# Generate a secure .env file with random passwords and secrets
# Usage: bash scripts/generate_env.sh [output_file]
#
# Generates cryptographically random values for all secrets.
# Safe to run multiple times — always generates new values.

set -euo pipefail

OUTPUT="${1:-.env}"

if [ -f "$OUTPUT" ]; then
    echo "WARNING: $OUTPUT already exists."
    read -p "Overwrite? (y/N): " confirm
    if [ "$confirm" != "y" ] && [ "$confirm" != "Y" ]; then
        echo "Aborted."
        exit 0
    fi
    cp "$OUTPUT" "${OUTPUT}.backup.$(date +%Y%m%d_%H%M%S)"
    echo "Backup created."
fi

# Generate random values
POSTGRES_PASSWORD=$(openssl rand -hex 16)
ADMIN_PASSWORD=$(openssl rand -base64 24 | tr -d '/+=' | head -c 24)
CHAINLIT_AUTH_SECRET=$(openssl rand -hex 32)
JWT_SECRET=$(openssl rand -hex 32)
ADMIN_API_KEY="obsai_$(openssl rand -hex 24)"
SERVICE_API_KEY="svc_$(openssl rand -hex 16)"
REDIS_PASSWORD=$(openssl rand -hex 16)
SPLUNK_ADMIN_PASSWORD="Sp$(openssl rand -base64 16 | tr -d '/+=' | head -c 16)!1"
GRAFANA_PASSWORD=$(openssl rand -base64 16 | tr -d '/+=' | head -c 16)

cat > "$OUTPUT" << ENVFILE
# =============================================================================
# ObsAI Environment Configuration
# Generated: $(date -Iseconds)
# =============================================================================

# ── PostgreSQL ────────────────────────────────────────────
POSTGRES_USER=chainlit_user
POSTGRES_PASSWORD=${POSTGRES_PASSWORD}
POSTGRES_DB=chainlit_db
POSTGRES_PORT=5432

# ── Application ───────────────────────────────────────────
ACTIVE_PROFILE=LLM_LITE
APP_LOG_LEVEL=INFO
ENABLE_AUTHENTICATION=true
ADMIN_PASSWORD=${ADMIN_PASSWORD}

# ── Authentication Secrets ────────────────────────────────
CHAINLIT_AUTH_SECRET=${CHAINLIT_AUTH_SECRET}
JWT_SECRET=${JWT_SECRET}

# ── API Keys ──────────────────────────────────────────────
ADMIN_API_KEY=${ADMIN_API_KEY}
SERVICE_API_KEY=${SERVICE_API_KEY}

# ── Ollama LLM ────────────────────────────────────────────
OLLAMA_PORT=11430
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_EMBED_MODEL=mxbai-embed-large

# ── ChromaDB ──────────────────────────────────────────────
CHROMA_PORT=8001
CHROMA_COLLECTION=assistant_memory_mxbai_v2

# ── Redis Cache ───────────────────────────────────────────
REDIS_PORT=6379
REDIS_PASSWORD=${REDIS_PASSWORD}

# ── Gateway ───────────────────────────────────────────────
GATEWAY_PORT=8000

# ── Monitoring ────────────────────────────────────────────
PROMETHEUS_PORT=9090
GRAFANA_PORT=3100
GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASSWORD}

# ── Splunk (optional) ─────────────────────────────────────
# SPLUNK_HOST=
# SPLUNK_TOKEN=
SPLUNK_ADMIN_PASSWORD=${SPLUNK_ADMIN_PASSWORD}
ENVFILE

echo ""
echo "Generated: $OUTPUT"
echo ""
echo "Key values (save these):"
echo "  Admin Password:  ${ADMIN_PASSWORD}"
echo "  Admin API Key:   ${ADMIN_API_KEY}"
echo "  DB Password:     ${POSTGRES_PASSWORD}"
echo ""
echo "Start the app:  bash docker_files/start_all.sh"
