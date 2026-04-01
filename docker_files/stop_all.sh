#!/bin/bash
# =============================================================================
# Stop All Containers - Optimized
# =============================================================================
# Gracefully stops all Chainlit containers while preserving data volumes
# =============================================================================

set -e

# Parse arguments
REMOVE_CONTAINERS=false
FORCE_STOP=false

for arg in "$@"; do
    case $arg in
        --remove)
            REMOVE_CONTAINERS=true
            shift
            ;;
        --force)
            FORCE_STOP=true
            shift
            ;;
        --help)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  --remove    Remove containers after stopping"
            echo "  --force     Force stop (kill) instead of graceful shutdown"
            echo "  --help      Show this help"
            exit 0
            ;;
    esac
done

# Docker/Podman detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
  echo "✓ Using: Podman"
elif command -v docker &> /dev/null; then
  DOCKER_CMD="docker"
  echo "✓ Using: Docker"
else
  echo "✗ ERROR: Neither Docker nor Podman found!"
  exit 1
fi

docker() { "$DOCKER_CMD" "$@"; }

echo ""
echo "================================================================================"
echo "Stopping All Containers"
echo "================================================================================"
echo ""

# Define containers in stop order (reverse of startup)
CONTAINERS=(
  "nginx_gateway"
  "open_webui"
  "langfuse_api"
  "langfuse_worker"
  "langfuse_clickhouse"
  "langfuse_minio"
  "langfuse_redis"
  "redis_cache"
  "grafana_monitoring"
  "prometheus_monitoring"
  "chat_ui_app"
  "docling_converter"
  "llm_api_service"
  "splunk_validator"
  "search_opt_service"
  "chat_chroma_db"
  "chat_db_app"
)

# Stop containers
for container in "${CONTAINERS[@]}"; do
    if docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
        echo -n "Stopping $container... "
        if [ "$FORCE_STOP" = true ]; then
            docker kill "$container" 2>/dev/null || true
            echo "✓ Killed"
        else
            docker stop "$container" 2>/dev/null || true
            echo "✓ Stopped"
        fi
    fi
done

echo ""

# Remove containers if requested
if [ "$REMOVE_CONTAINERS" = true ]; then
    echo "Removing containers..."
    for container in "${CONTAINERS[@]}"; do
        if docker ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
            echo -n "Removing $container... "
            docker rm "$container" 2>/dev/null || true
            echo "✓"
        fi
    done
    echo ""
fi

# Summary
echo "================================================================================"
echo "Stop Complete"
echo "================================================================================"
echo ""
echo "Status:"
docker ps -a --format "table {{.Names}}\t{{.Status}}" | grep -E "chat_|llm_|splunk_|search_opt|prometheus_|grafana_|nginx_|redis_|docling_|open_webui|langfuse_|NAME" || echo "  No containers running"
echo ""
echo "Data preserved in volumes:"
docker volume ls | grep -E "postgres_data|chroma_data|chainlit_data|app_chroma_store|app_certs|prometheus_data|grafana_data|open_webui_data|docling_models|langfuse_|NAME" || echo "  (volumes may not exist yet)"
echo ""
echo "Next steps:"
echo "  Restart services:  bash docker_files/start_all.sh"
echo "  Remove all data:   $DOCKER_CMD volume rm postgres_data chroma_data chainlit_data app_chroma_store app_certs specs_chroma_data spl_docs_chroma_data repo_chroma_data local_docs_chroma_data prometheus_data grafana_data open_webui_data docling_models"
echo ""
echo "================================================================================"
