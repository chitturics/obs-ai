#!/bin/bash
# =============================================================================
# Chainlit Splunk Assistant - Production Startup Script
# =============================================================================
# Architecture:
#   - All containers run with --network host (localhost communication)
#   - Nginx gateway is the single user-facing entry point (GATEWAY_PORT)
#   - Internal service ports are NOT meant for direct external access
#   - In production, firewall all ports except GATEWAY_PORT
# =============================================================================

set -e

cd "$(dirname "$0")/.."

# =============================================================================
# ENVIRONMENT CONFIGURATION
# =============================================================================
# Load environment variables from .env file if it exists
if [ -f "docker_files/.env" ]; then
  echo "Loading environment variables from .env file..."
  set -a
  source docker_files/.env
  set +a
fi

# Set default values for variables not defined in .env
# Database — auto-generate secure password on first run
POSTGRES_USER=${POSTGRES_USER:-chainlit}
POSTGRES_DB=${POSTGRES_DB:-chainlit}
POSTGRES_PORT=${POSTGRES_PORT:-5432}
# Services
CHROMA_PORT=${CHROMA_PORT:-8001}
SEARCH_OPT_PORT=${SEARCH_OPT_PORT:-9005}
OLLAMA_PORT=${OLLAMA_PORT:-11430}
CHAINLIT_PORT=${CHAINLIT_PORT:-8000}
# Internal app port (different from CHAINLIT_PORT since nginx uses that)
APP_INTERNAL_PORT=${APP_INTERNAL_PORT:-8090}
GRAFANA_INTERNAL_PORT=${GRAFANA_INTERNAL_PORT:-3100}
PROMETHEUS_INTERNAL_PORT=${PROMETHEUS_INTERNAL_PORT:-9090}
LANGFUSE_INTERNAL_PORT=${LANGFUSE_INTERNAL_PORT:-3200}
CLICKHOUSE_HTTP_PORT=${CLICKHOUSE_HTTP_PORT:-8123}
CLICKHOUSE_NATIVE_PORT=${CLICKHOUSE_NATIVE_PORT:-9000}
# UI Framework
UI_FRAMEWORK=${UI_FRAMEWORK:-chainlit}

# =============================================================================
# SECURE CREDENTIAL GENERATION
# =============================================================================
# On first run, generate strong random credentials and persist them to .env
# Subsequent runs re-use the saved credentials for consistency.
_GENERATED_ENV="docker_files/.env.generated"
_generate_secret() { openssl rand -base64 32 2>/dev/null | tr -d '/+=' | head -c 32; }

if [ ! -f "$_GENERATED_ENV" ]; then
  echo "Generating secure credentials (first run)..."
  cat > "$_GENERATED_ENV" <<GENEOF
# Auto-generated secure credentials — $(date -Iseconds)
# Move sensitive values to a secrets manager for production deployments.
POSTGRES_PASSWORD=$(_generate_secret)
ADMIN_PASSWORD=$(_generate_secret)
CHAINLIT_AUTH_SECRET=$(_generate_secret)$(_generate_secret)
GF_SECURITY_ADMIN_PASSWORD=$(_generate_secret)
SPLUNK_ADMIN_PASSWORD=$(_generate_secret)
REDIS_PASSWORD=$(_generate_secret)
SERVICE_API_KEY=svc_$(_generate_secret)
ADMIN_API_KEY=obsai_$(_generate_secret)$(_generate_secret)
GENEOF
  chmod 600 "$_GENERATED_ENV"
  echo "Credentials saved to $_GENERATED_ENV (chmod 600)"
fi
# Source generated credentials (can be overridden by .env or environment)
set -a; source "$_GENERATED_ENV"; set +a

# Final defaults — only used if neither .env nor generated file provides a value
POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-$(openssl rand -hex 16)}
CHAINLIT_AUTH_SECRET=${CHAINLIT_AUTH_SECRET:-$(openssl rand -hex 32)}
ENABLE_AUTHENTICATION=${ENABLE_AUTHENTICATION:-true}
ADMIN_PASSWORD=${ADMIN_PASSWORD:-$(openssl rand -hex 16)}
ADMIN_API_KEY=${ADMIN_API_KEY:-obsai_$(openssl rand -hex 24)}
SERVICE_API_KEY=${SERVICE_API_KEY:-svc_$(openssl rand -hex 24)}
# Splunk Validator
SPLUNK_ADMIN_PASSWORD=${SPLUNK_ADMIN_PASSWORD:-$(openssl rand -hex 16)}
SPLUNK_MGMT_PORT=${SPLUNK_MGMT_PORT:-8089}
SPLUNK_WEB_PORT=${SPLUNK_WEB_PORT:-8000}
# Monitoring
GF_SECURITY_ADMIN_PASSWORD=${GF_SECURITY_ADMIN_PASSWORD:-$(openssl rand -hex 16)}
# Redis
REDIS_PASSWORD=${REDIS_PASSWORD:-$(openssl rand -hex 16)}

# Read ports from config.yaml if available (overrides env var defaults)
if [ -f "$PROJECT_ROOT/config.yaml" ] && command -v python3 &>/dev/null; then
  _read_port() {
    python3 -c "
import yaml
with open('$PROJECT_ROOT/config.yaml') as f:
    cfg = yaml.safe_load(f) or {}
v = cfg.get('ports',{}).get('$1','')
if v: print(v)" 2>/dev/null
  }
  _p=$(_read_port app);         [ -n "$_p" ] && CHAINLIT_PORT=$_p
  _p=$(_read_port gateway);     [ -n "$_p" ] && GATEWAY_PORT=$_p
  _p=$(_read_port gateway_ssl); [ -n "$_p" ] && GATEWAY_SSL_PORT=$_p
  _p=$(_read_port ollama);      [ -n "$_p" ] && OLLAMA_PORT=$_p
  _p=$(_read_port chromadb);    [ -n "$_p" ] && CHROMA_PORT=$_p
  _p=$(_read_port postgres);    [ -n "$_p" ] && POSTGRES_PORT=$_p
  _p=$(_read_port search_opt);  [ -n "$_p" ] && SEARCH_OPT_PORT=$_p
  _p=$(_read_port redis);       [ -n "$_p" ] && REDIS_PORT=$_p
  _p=$(_read_port grafana);     [ -n "$_p" ] && GRAFANA_INTERNAL_PORT=$_p
  _p=$(_read_port prometheus);  [ -n "$_p" ] && PROMETHEUS_INTERNAL_PORT=$_p
fi

# Final port defaults (after config.yaml overrides)
REDIS_PORT=${REDIS_PORT:-6379}

# =============================================================================
# Parse Arguments
# =============================================================================

SKIP_INGESTION=false
FORCE_RECREATE=false
START_SPLUNK_VALIDATOR=false
START_LANGFUSE=false
PRODUCTION_MODE=false
ACTIVE_PROFILE_OVERRIDE=""

for arg in "$@"; do
  case $arg in
    --no-ingest)
      SKIP_INGESTION=true
      shift
      ;;
    --force-recreate)
      FORCE_RECREATE=true
      shift
      ;;
    --with-splunk-validator)
      START_SPLUNK_VALIDATOR=true
      shift
      ;;
    --with-langfuse)
      START_LANGFUSE=true
      shift
      ;;
    --production)
      PRODUCTION_MODE=true
      shift
      ;;
    --profile)
      ACTIVE_PROFILE_OVERRIDE="$2"
      shift
      shift
      ;;
    --help)
      echo "Usage: $0 [OPTIONS]"
      echo ""
      echo "Options:"
      echo "  --no-ingest              Skip background document ingestion"
      echo "  --force-recreate         Stop and remove existing containers before starting"
      echo "  --with-splunk-validator  Start the Splunk validator container (optional)"
      echo "  --with-langfuse          Start Langfuse LLM observability containers"
      echo "  --production             Run in production mode (sets permissions and checks directories)"
      echo "  --profile <profile>      Set the active LLM profile (e.g., LLM_LITE, LLM_FAST, LLM_FULL, LLM_MAX)"
      echo "  --help                   Show this help message"
      exit 0
      ;;
  esac
done

SERVICE_COUNT=8
if [ "$START_SPLUNK_VALIDATOR" = true ]; then
    SERVICE_COUNT=$((SERVICE_COUNT + 1))
fi

# ============================================================================
# Auto-detect deployment environment
# ============================================================================

# Detect project root: use script location's parent, then check known paths
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DETECTED_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# If the detected root has config.yaml, use it (most reliable)
if [ -f "$DETECTED_ROOT/config.yaml" ]; then
  PROJECT_ROOT="$DETECTED_ROOT"
  echo "Detected project root from script location: $PROJECT_ROOT"
elif [ -f "$(pwd)/config.yaml" ]; then
  PROJECT_ROOT="$(pwd)"
  echo "Detected project root from current directory: $PROJECT_ROOT"
elif [ -d "/opt/obsai/chatbot" ]; then
  PROJECT_ROOT="/opt/obsai/chatbot"
  echo "Detected production environment (/opt/obsai/chatbot)"
elif [ -d "/opt/obsai/chatapp" ]; then
  PROJECT_ROOT="/opt/obsai/chatapp"
  echo "Detected production environment (/opt/obsai/chatapp)"
else
  PROJECT_ROOT="$(pwd)"
  echo "Detected dev/local environment: $PROJECT_ROOT"
fi

# Documents root always derives from project root
DOCUMENTS_ROOT="${DOCUMENTS_ROOT:-$PROJECT_ROOT/documents}"

PROJECT_ROOT="${PROJECT_ROOT_OVERRIDE:-$PROJECT_ROOT}"
DOCUMENTS_ROOT="${DOCUMENTS_ROOT_OVERRIDE:-$DOCUMENTS_ROOT}"

# Docker/Podman detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi
docker() { "$DOCKER_CMD" "$@"; }

echo "================================================================================"
echo "Starting Chainlit Splunk Assistant (Production)"
echo "================================================================================"
echo ""
echo "Project root:    $PROJECT_ROOT"
echo "Documents root:  $DOCUMENTS_ROOT"
echo "Container tool:  $DOCKER_CMD"
echo "Start time:      $(date)"
echo ""

# Verify documents directory
if [ ! -d "$DOCUMENTS_ROOT" ]; then
  echo "WARNING: Documents directory not found: $DOCUMENTS_ROOT"
  echo "Creating it now..."
  mkdir -p "$DOCUMENTS_ROOT"/{specs,commands,repo,pdfs}
  echo "Created: $DOCUMENTS_ROOT with subdirectories"
  echo ""
fi

# =============================================================================
# CONFIGURATION
# =============================================================================

# Read active_profile from config.yaml if not overridden
CONFIG_PROFILE=""
if [ -f "$PROJECT_ROOT/config.yaml" ]; then
  CONFIG_PROFILE=$(grep '^active_profile:' "$PROJECT_ROOT/config.yaml" | sed 's/active_profile:\s*//' | tr -d ' "'"'"'')
fi
ACTIVE_PROFILE="${ACTIVE_PROFILE_OVERRIDE:-${ACTIVE_PROFILE:-${CONFIG_PROFILE:-LLM_LITE}}}"
echo "Active profile: $ACTIVE_PROFILE"

case "$ACTIVE_PROFILE" in
  LLM_FULL | LLM_MAX)
    APP_OLLAMA_MODEL="deepseek-r1:14b"
    APP_OLLAMA_EMBED="mxbai-embed-large"
    APP_OLLAMA_NUM_CTX=16384
    APP_OLLAMA_TEMPERATURE=0.1
    ;;
  LLM_MED)
    APP_OLLAMA_MODEL="qwen2.5-coder:7b"
    APP_OLLAMA_EMBED="mxbai-embed-large"
    APP_OLLAMA_NUM_CTX=8192
    APP_OLLAMA_TEMPERATURE=0.1
    ;;
  LLM_FAST)
    APP_OLLAMA_MODEL="qwen2.5:3b"
    APP_OLLAMA_EMBED="nomic-embed-text"
    APP_OLLAMA_NUM_CTX=2048
    APP_OLLAMA_TEMPERATURE=0.01
    ;;
  *)
    APP_OLLAMA_MODEL="qwen2.5:3b"
    APP_OLLAMA_EMBED="mxbai-embed-large"
    APP_OLLAMA_NUM_CTX=2048
    APP_OLLAMA_TEMPERATURE=0.01
    ;;
esac

# Read UI framework from config.yaml if not set via env
if [ "$UI_FRAMEWORK" = "chainlit" ] && [ -f "$PROJECT_ROOT/config.yaml" ]; then
  CONFIG_UI_FRAMEWORK=$(grep -v '^\s*#' "$PROJECT_ROOT/config.yaml" | grep 'framework:' | head -1 | sed 's/.*framework:\s*//' | sed 's/\s*#.*//' | tr -d ' "'"'"'')
  if [ -n "$CONFIG_UI_FRAMEWORK" ]; then
    UI_FRAMEWORK="$CONFIG_UI_FRAMEWORK"
  fi
fi

echo "LLM model: $APP_OLLAMA_MODEL"
echo "Embedding model: $APP_OLLAMA_EMBED"
echo "UI framework: $UI_FRAMEWORK"
echo ""

# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

# Check if container exists and is running (single call optimization)
container_status() {
  local name=$1
  local status=$(docker ps -a --filter "name=^${name}$" --format "{{.Status}}" 2>/dev/null)

  if [ -z "$status" ]; then
    echo "none"
  elif [[ "$status" == Up* ]]; then
    echo "running"
  else
    echo "stopped"
  fi
}

# Wait for service to be ready with timeout
wait_for_service() {
  local service_name=$1
  local check_command=$2
  local timeout=${3:-60}
  local interval=2
  local elapsed=0

  echo -n "Waiting for $service_name to be ready"
  while [ $elapsed -lt $timeout ]; do
    if eval "$check_command" &>/dev/null; then
      echo " Ready ($elapsed seconds)"
      return 0
    fi
    echo -n "."
    sleep $interval
    elapsed=$((elapsed + interval))
  done

  echo " Timeout after $timeout seconds (non-fatal)"
  return 0
}

# Check if a port is already in use on localhost
check_port_available() {
  local port=$1
  local service=$2
  if ss -tlnp 2>/dev/null | grep -q ":${port} " || \
     bash -c "echo >/dev/tcp/127.0.0.1/${port}" 2>/dev/null; then
    # Port is in use — check if it's our container
    local container_using=$(docker ps --format '{{.Names}}' --filter "status=running" 2>/dev/null | while read name; do
      if docker inspect "$name" --format '{{.HostConfig.NetworkMode}}' 2>/dev/null | grep -q host; then
        echo "$name"
      fi
    done)
    if [ -z "$container_using" ]; then
      echo "ERROR: Port $port needed by $service is already in use by a non-container process."
      echo "       Check: ss -tlnp | grep :${port}"
      return 1
    fi
  fi
  return 0
}

# Cleanup on failure
cleanup_on_failure() {
  echo ""
  echo "Startup failed! Cleaning up..."
  if [ "$FORCE_RECREATE" = true ]; then
    docker stop chat_ui_app chat_chroma_db llm_api_service chat_db_app search_opt_service prometheus_monitoring grafana_monitoring nginx_gateway redis_cache 2>/dev/null || true
  fi
  exit 1
}

trap cleanup_on_failure ERR

# =============================================================================
# FORCE RECREATE
# =============================================================================

if [ "$FORCE_RECREATE" = true ]; then
  echo "Force recreate enabled - stopping and removing existing containers..."
  docker stop nginx_gateway chat_ui_app chat_chroma_db llm_api_service chat_db_app search_opt_service prometheus_monitoring grafana_monitoring redis_cache 2>/dev/null || true
  docker rm nginx_gateway chat_ui_app chat_chroma_db llm_api_service chat_db_app search_opt_service prometheus_monitoring grafana_monitoring redis_cache 2>/dev/null || true
  echo "Containers removed"
  echo ""
fi

# =============================================================================
# SETUP
# =============================================================================

echo "Network mode: host — all containers communicate via localhost"
echo "Gateway:      https://localhost:${GATEWAY_PORT:-8000} (HTTPS, nginx single entry point)"
echo ""

# =============================================================================
# PORT CONFLICT DETECTION
# =============================================================================

echo "Checking for port conflicts..."
PORTS_OK=true
check_port_available ${POSTGRES_PORT} "PostgreSQL" || PORTS_OK=false
check_port_available ${CHROMA_PORT} "ChromaDB" || PORTS_OK=false
check_port_available ${SEARCH_OPT_PORT} "Search Optimizer" || PORTS_OK=false
check_port_available ${OLLAMA_PORT} "Ollama" || PORTS_OK=false
check_port_available ${APP_INTERNAL_PORT} "Chat App" || PORTS_OK=false
check_port_available ${PROMETHEUS_INTERNAL_PORT} "Prometheus" || PORTS_OK=false
check_port_available ${GRAFANA_INTERNAL_PORT} "Grafana" || PORTS_OK=false
check_port_available ${REDIS_PORT} "Redis" || PORTS_OK=false
check_port_available ${GATEWAY_PORT:-${CHAINLIT_PORT}} "Nginx Gateway (HTTPS)" || PORTS_OK=false

if [ "$PORTS_OK" = true ]; then
  echo "All ports available"
fi
echo ""

# =============================================================================
# PRODUCTION MODE SETUP
# =============================================================================

if [ "$PRODUCTION_MODE" = true ]; then
  echo "================================================================================"
  echo "Production Mode Setup"
  echo "================================================================================"
  echo ""

  # Validate secrets are not defaults
  if [ "$CHAINLIT_AUTH_SECRET" = "change_this_to_a_real_secret_string" ]; then
    echo "WARNING: Using default CHAINLIT_AUTH_SECRET. Set a secure value in .env for production!"
  fi
  if [ "$POSTGRES_PASSWORD" = "chainlit" ]; then
    echo "WARNING: Using default POSTGRES_PASSWORD. Set a secure value in .env for production!"
  fi
  if [ "$ADMIN_PASSWORD" = "admin" ]; then
    echo "WARNING: Using default ADMIN_PASSWORD. Set a secure value in .env for production!"
  fi

  # Verify critical directories exist
  REQUIRED_DIRS=(
    "$PROJECT_ROOT"
    "$PROJECT_ROOT/chat_app"
    "$PROJECT_ROOT/postgres"
    "$DOCUMENTS_ROOT"
    "$DOCUMENTS_ROOT/specs"
  )

  echo "Verifying directory structure..."
  for dir in "${REQUIRED_DIRS[@]}"; do
    if [ ! -d "$dir" ]; then
      echo "Required directory missing: $dir"
      echo ""
      echo "Run setup script first:"
      echo "  sudo bash scripts/setup_production_directories.sh"
      exit 1
    fi
  done
  echo "Directory structure verified"
  echo ""

  echo "Setting up runtime directories..."

  # Create directories if they don't exist
  mkdir -p "$PROJECT_ROOT/.chainlit/blobs"
  mkdir -p "$PROJECT_ROOT/feedback"
  mkdir -p "$PROJECT_ROOT/llms"

  # Set permissions for container write access
  chmod -R 777 "$PROJECT_ROOT/.chainlit" 2>/dev/null || true
  chmod -R 777 "$PROJECT_ROOT/feedback" 2>/dev/null || true
  chmod -R 777 "$PROJECT_ROOT/llms" 2>/dev/null || true

  # SELinux context (if enabled)
  if command -v getenforce &> /dev/null && [ "$(getenforce)" != "Disabled" ]; then
    echo "SELinux enabled - applying container contexts"
    chcon -R -t container_file_t "$PROJECT_ROOT/.chainlit" 2>/dev/null || true
    chcon -R -t container_file_t "$PROJECT_ROOT/feedback" 2>/dev/null || true
    chcon -R -t container_file_t "$PROJECT_ROOT/llms" 2>/dev/null || true
    chcon -R -t container_file_t "$DOCUMENTS_ROOT" 2>/dev/null || true
  fi

  echo "Runtime directories ready"
  echo ""

  # Production firewall recommendation
  echo "================================================================================"
  echo "PRODUCTION SECURITY NOTE"
  echo "================================================================================"
  echo ""
  echo "With host networking, all service ports are accessible on localhost."
  echo "In production, configure firewall to only expose the gateway port:"
  echo ""
  echo "  # Allow only gateway port externally (HTTPS)"
  echo "  firewall-cmd --permanent --add-port=${GATEWAY_PORT:-8000}/tcp"
  echo "  firewall-cmd --reload"
  echo ""
  echo "Internal ports (block from external access):"
  echo "  PostgreSQL:      ${POSTGRES_PORT}"
  echo "  ChromaDB:        ${CHROMA_PORT}"
  echo "  Ollama:          ${OLLAMA_PORT}"
  echo "  App (internal):  ${APP_INTERNAL_PORT}"
  echo "  Search Opt:      ${SEARCH_OPT_PORT}"
  echo "  Prometheus:      ${PROMETHEUS_INTERNAL_PORT} (bound to 127.0.0.1)"
  echo "  Grafana:         ${GRAFANA_INTERNAL_PORT} (bound to 127.0.0.1)"
  echo ""
fi


# =============================================================================
# Ensure document directories exist and are readable by container (uid 1001)
# =============================================================================
echo "Preparing document directories..."
for subdir in specs commands repo pdfs cribl feedback; do
  mkdir -p "$DOCUMENTS_ROOT/$subdir" 2>/dev/null || true
done

# Ensure the container user (uid 1001) can read all document files
chmod -R a+rX "$DOCUMENTS_ROOT" 2>/dev/null || {
  echo "  Could not set permissions on $DOCUMENTS_ROOT"
  echo "  Run: sudo chmod -R a+rX $DOCUMENTS_ROOT"
}

# SELinux context for documents (if applicable)
if command -v getenforce &> /dev/null && [ "$(getenforce)" != "Disabled" ]; then
  chcon -R -t container_file_t "$DOCUMENTS_ROOT" 2>/dev/null || true
fi

echo "Document directories ready"
echo ""

# Ensure config.yaml is readable by container user (uid 1001) if it exists
if [ -f "$PROJECT_ROOT/config.yaml" ]; then
  chmod a+r "$PROJECT_ROOT/config.yaml" 2>/dev/null || {
    echo "  Could not set read permission on config.yaml"
    echo "  Run: sudo chmod a+r $PROJECT_ROOT/config.yaml"
  }
  echo "config.yaml permissions OK"
fi

echo "Creating volumes..."
# Use a loop for cleaner volume creation
for vol in postgres_data chroma_data chainlit_data app_chroma_store app_certs specs_chroma_data spl_docs_chroma_data repo_chroma_data local_docs_chroma_data prometheus_data grafana_data open_webui_data docling_models; do
  docker volume create "$vol" 2>/dev/null || true
done
echo "Volumes ready"
echo ""

# =============================================================================
# SSL Certificate Generation (self-signed for dev/testing)
# =============================================================================
# Ensure both cert AND key files exist in the app_certs volume.
# The admin API's /ssl/status endpoint checks for both; a missing key file
# causes cert_exists=true but key_exists=false.
CERTS_VOLUME_PATH=$(docker volume inspect app_certs --format '{{.Mountpoint}}' 2>/dev/null || echo "")
if [ -n "$CERTS_VOLUME_PATH" ]; then
  _CERT_FILE="$CERTS_VOLUME_PATH/server.crt"
  _KEY_FILE="$CERTS_VOLUME_PATH/server.key"
  if [ ! -f "$_CERT_FILE" ] || [ ! -f "$_KEY_FILE" ]; then
    echo "Generating self-signed SSL certificate and key..."
    openssl req -x509 -newkey rsa:2048 \
      -keyout "$_KEY_FILE" -out "$_CERT_FILE" \
      -days 365 -nodes \
      -subj "/CN=obsai-local/O=ObsAI/C=US" 2>/dev/null && {
      chmod 600 "$_KEY_FILE"
      echo "  SSL cert: $_CERT_FILE"
      echo "  SSL key:  $_KEY_FILE"
    } || echo "  SSL cert generation failed (non-fatal, openssl may not be available)"
  else
    echo "SSL certificate and key already exist"
  fi
else
  echo "Warning: Could not locate app_certs volume mount path — skipping SSL cert generation"
fi
echo ""

# =============================================================================
# SERVICE 1: PostgreSQL
# =============================================================================

echo "================================================================================"
echo "[1/$SERVICE_COUNT] PostgreSQL Database"
echo "================================================================================"
echo ""

STATUS=$(container_status "chat_db_app")

if [ "$STATUS" = "running" ]; then
  echo "PostgreSQL already running"
elif [ "$STATUS" = "stopped" ]; then
  echo "Starting existing PostgreSQL container..."
  docker start chat_db_app
  wait_for_service "PostgreSQL" "docker exec chat_db_app pg_isready -U ${POSTGRES_USER}" 30
else
  echo "Creating PostgreSQL container..."
  docker run -d \
    --name chat_db_app \
    --network host \
    --restart unless-stopped \
    --log-opt max-size=50m --log-opt max-file=3 \
    -e POSTGRES_USER=${POSTGRES_USER} \
    -e POSTGRES_PASSWORD=${POSTGRES_PASSWORD} \
    -e POSTGRES_DB=${POSTGRES_DB} \
    -e PGPORT=${POSTGRES_PORT} \
    -e POSTGRES_HOST_AUTH_METHOD=md5 \
    -v postgres_data:/var/lib/postgresql/data \
    -v "$PROJECT_ROOT/postgres/init_chainlit_schema.sql:/docker-entrypoint-initdb.d/00-init_chainlit_schema.sql:ro,Z" \
    chainlit-postgres:latest

  wait_for_service "PostgreSQL" "docker exec chat_db_app pg_isready -U ${POSTGRES_USER}" 60
fi

echo ""

# =============================================================================
# SERVICE 2: ChromaDB
# =============================================================================

echo "================================================================================"
echo "[2/$SERVICE_COUNT] ChromaDB Vector Store"
echo "================================================================================"
echo ""

STATUS=$(container_status "chat_chroma_db")

if [ "$STATUS" = "running" ]; then
  echo "ChromaDB already running"
elif [ "$STATUS" = "stopped" ]; then
  echo "Starting existing ChromaDB container..."
  docker start chat_chroma_db
  wait_for_service "ChromaDB" "bash -c 'echo > /dev/tcp/127.0.0.1/${CHROMA_PORT}' 2>/dev/null" 30
else
  echo "Creating ChromaDB container..."
  docker run -d \
    --name chat_chroma_db \
    --network host \
    --restart unless-stopped \
    --log-opt max-size=50m --log-opt max-file=3 \
    -e IS_PERSISTENT=TRUE \
    -e PERSIST_DIRECTORY=/data \
    -e ANONYMIZED_TELEMETRY=FALSE \
    -e CHROMA_SERVER_HOST=127.0.0.1 \
    -e CHROMA_SERVER_HTTP_PORT=${CHROMA_PORT} \
    -e ALLOW_RESET=FALSE \
    -v chroma_data:/data \
    chainlit-chromadb:latest

  wait_for_service "ChromaDB" "bash -c 'echo > /dev/tcp/127.0.0.1/${CHROMA_PORT}' 2>/dev/null" 60
fi

echo ""

# =============================================================================
# SERVICE 3: Search Optimizer Service
# =============================================================================

echo "================================================================================"
echo "[3/$SERVICE_COUNT] Search Optimizer Service"
echo "================================================================================"
echo ""

STATUS=$(container_status "search_opt_service")

if [ "$STATUS" = "running" ]; then
  echo "Search optimizer already running"
elif [ "$STATUS" = "stopped" ]; then
  echo "Starting existing search optimizer container..."
  docker start search_opt_service
  wait_for_service "Search Optimizer" "curl -sf http://localhost:${SEARCH_OPT_PORT}/health > /dev/null 2>&1" 45 || echo "  Search Optimizer not ready yet (non-fatal, will retry at runtime)"
else
  echo "Creating search optimizer container..."
  docker run -d \
    --name search_opt_service \
    --network host \
    --restart unless-stopped \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -e HOST=127.0.0.1 \
    -e SEARCH_OPT_DATA_DIR=/app/data \
    -e SPLUNK_VERIFY_SSL="${SPLUNK_VERIFY_SSL:-true}" \
    -e SPLUNK_CA_BUNDLE="${SPLUNK_CA_BUNDLE:-}" \
    -v "$DOCUMENTS_ROOT:/app/public/documents:ro,Z" \
    chainlit-search-opt:latest

  wait_for_service "Search Optimizer" "curl -sf http://localhost:${SEARCH_OPT_PORT}/health > /dev/null 2>&1" 45 || echo "  Search Optimizer not ready yet (non-fatal, will retry at runtime)"
fi

echo ""

# =============================================================================
# SERVICE 3.5: Splunk Enterprise (Optional)
# =============================================================================

if [ "$START_SPLUNK_VALIDATOR" = true ]; then
    echo "================================================================================"
    echo "[4/$SERVICE_COUNT] Splunk Enterprise (for live testing)"
    echo "================================================================================"
    echo ""

    STATUS=$(container_status "splunk_validator")

    if [ "$STATUS" = "running" ]; then
        echo "Splunk Enterprise already running"
    elif [ "$STATUS" = "stopped" ]; then
        echo "Starting existing Splunk Enterprise container..."
        docker start splunk_validator
        wait_for_service "Splunk Enterprise" "docker exec splunk_validator /opt/splunk/bin/splunk status 2>/dev/null | grep -q 'running'" 120
    else
        echo "Creating Splunk Enterprise container..."
        echo "Note: First start takes 2-3 minutes for Splunk initialization"

        docker run -d \
            --name splunk_validator \
            --network host \
            --restart unless-stopped \
            -e SPLUNK_START_ARGS="--accept-license" \
            -e SPLUNK_PASSWORD="${SPLUNK_ADMIN_PASSWORD}" \
            -e SPLUNK_LICENSE_URI="Free" \
            -e SPLUNK_WEB_PORT=${SPLUNK_WEB_PORT:-8100} \
            chainlit-splunk-validator:latest

        wait_for_service "Splunk Enterprise" "curl -kf https://localhost:8089/services/server/info -u admin:${SPLUNK_ADMIN_PASSWORD} 2>/dev/null | grep -q 'server_roles'" 180
    fi

    # Verify Splunk validator is reachable
    if curl -kf https://localhost:${SPLUNK_MGMT_PORT}/services/server/info -u admin:${SPLUNK_ADMIN_PASSWORD} 2>/dev/null | grep -q "server_roles"; then
        echo "Splunk REST API available at localhost:${SPLUNK_MGMT_PORT}"
    else
        echo "WARNING: Splunk Enterprise may still be starting up"
        echo "         Check status with: docker logs splunk_validator"
    fi

    echo ""
fi

# =============================================================================
# SERVICE 4: Ollama LLM
# =============================================================================

if [ "$START_SPLUNK_VALIDATOR" = true ]; then
    echo "================================================================================"
    echo "[5/$SERVICE_COUNT] Ollama LLM Service"
    echo "================================================================================"
else
    echo "================================================================================"
    echo "[4/$SERVICE_COUNT] Ollama LLM Service"
    echo "================================================================================"
fi
echo ""

STATUS=$(container_status "llm_api_service")

# GPU detection
GPU_FLAG=""
if command -v nvidia-smi &> /dev/null; then
  echo "NVIDIA GPU detected, enabling GPU support"
  GPU_FLAG="--gpus all"
fi

if [ "$STATUS" = "running" ]; then
  echo "Ollama already running"
elif [ "$STATUS" = "stopped" ]; then
  echo "Starting existing Ollama container..."
  docker start llm_api_service
  wait_for_service "Ollama" "docker exec llm_api_service ollama list > /dev/null 2>&1" 30
else
  echo "Creating Ollama container..."
  mkdir -p "$PROJECT_ROOT/llms"

  docker run -d \
    --name llm_api_service \
    --network host \
    --restart unless-stopped \
    --log-opt max-size=100m --log-opt max-file=3 \
    $GPU_FLAG \
    -e OLLAMA_HOST=127.0.0.1:${OLLAMA_PORT} \
    -e OLLAMA_KEEP_ALIVE=24h \
    -e OLLAMA_NUM_PARALLEL=4 \
    -e OLLAMA_MAX_LOADED_MODELS=2 \
    -v "$PROJECT_ROOT/llms:/root/.ollama:Z" \
    chainlit-ollama:latest

  wait_for_service "Ollama" "docker exec llm_api_service ollama list > /dev/null 2>&1" 60

  echo "Pulling required models (parallel)..."
  docker exec -e OLLAMA_HOST=127.0.0.1:${OLLAMA_PORT} llm_api_service ollama pull "$APP_OLLAMA_MODEL" &
  PID_MODEL=$!
  docker exec -e OLLAMA_HOST=127.0.0.1:${OLLAMA_PORT} llm_api_service ollama pull "$APP_OLLAMA_EMBED" &
  PID_EMBED=$!

  wait $PID_MODEL && echo "  $APP_OLLAMA_MODEL ready" || echo "  $APP_OLLAMA_MODEL (may already exist)"
  wait $PID_EMBED && echo "  $APP_OLLAMA_EMBED ready" || echo "  $APP_OLLAMA_EMBED (may already exist)"
fi

echo ""

# =============================================================================
# SERVICE: Docling Document Converter (Optional)
# =============================================================================

if [ "${DOCLING_ENABLED:-false}" = "true" ]; then
  echo "================================================================================"
  echo "[*] Docling Document Converter (optional sidecar)"
  echo "================================================================================"
  echo ""

  DOCLING_PORT=${DOCLING_PORT:-5001}
  DOCLING_STATUS=$(container_status "docling_converter")

  if [ "$DOCLING_STATUS" = "running" ]; then
    echo "Docling already running"
  elif [ "$DOCLING_STATUS" = "stopped" ]; then
    echo "Starting existing Docling container..."
    docker start docling_converter
    wait_for_service "Docling" "curl -sf http://localhost:${DOCLING_PORT}/health > /dev/null 2>&1" 60 || echo "Docling not ready (non-fatal)"
  else
    echo "Creating Docling container..."
    docker run -d \
      --name docling_converter \
      --network host \
      --restart unless-stopped \
      -v docling_models:/opt/docling_models \
      quay.io/docling-project/docling-serve-cpu:latest

    wait_for_service "Docling" "curl -sf http://localhost:${DOCLING_PORT}/health > /dev/null 2>&1" 120 || echo "Docling not ready (non-fatal, first start downloads models)"
  fi
  echo ""
else
  echo "Docling: disabled (set DOCLING_ENABLED=true to enable)"
  echo ""
fi

# =============================================================================
# SERVICE 5: Chainlit Application
# =============================================================================

UI_LABEL="Chat Application"
if [ "$UI_FRAMEWORK" = "open-webui" ]; then
  UI_LABEL="Chat Application (API mode for Open WebUI)"
else
  UI_LABEL="Chat Application (Chainlit)"
fi

if [ "$START_SPLUNK_VALIDATOR" = true ]; then
    echo "================================================================================"
    echo "[6/$SERVICE_COUNT] $UI_LABEL"
    echo "================================================================================"
else
    echo "================================================================================"
    echo "[5/$SERVICE_COUNT] $UI_LABEL"
    echo "================================================================================"
fi
echo ""

STATUS=$(container_status "chat_ui_app")

if [ "$STATUS" = "running" ]; then
  echo "Chat app already running ($UI_FRAMEWORK mode)"
elif [ "$STATUS" = "stopped" ]; then
  echo "Starting existing chat app container ($UI_FRAMEWORK mode)..."
  docker start chat_ui_app
  wait_for_service "Chat App" "curl -sf http://localhost:${APP_INTERNAL_PORT}/live > /dev/null 2>&1" 60
else
  echo "Creating chat app container ($UI_FRAMEWORK mode)..."

  # Make container runtime socket accessible (for admin UI container management)
  PODMAN_SOCK="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/podman/podman.sock"
  SOCKET_MOUNT=""
  if [ ! -S "$PODMAN_SOCK" ]; then
    # Start podman socket service if not running
    systemctl --user start podman.socket 2>/dev/null || true
    sleep 1
  fi
  if [ -S "$PODMAN_SOCK" ]; then
    chmod 666 "$PODMAN_SOCK" 2>/dev/null || true
    SOCKET_MOUNT="-v ${PODMAN_SOCK}:/var/run/docker.sock:ro"
    echo "  Podman socket: mounted for container management"
  elif [ -S /var/run/docker.sock ]; then
    chmod 666 /var/run/docker.sock 2>/dev/null || true
    SOCKET_MOUNT="-v /var/run/docker.sock:/var/run/docker.sock:ro"
    echo "  Docker socket: mounted for container management"
  else
    echo "  No container socket found (container management from admin UI will be limited)"
    echo "  To fix: systemctl --user enable --now podman.socket"
  fi

  # Only mount host config.yaml if it exists; otherwise use the one baked into the image
  APP_EXTRA_MOUNTS=()
  if [ -f "$PROJECT_ROOT/config.yaml" ]; then
    APP_EXTRA_MOUNTS+=(-v "$PROJECT_ROOT/config.yaml:/app/config.yaml:Z")
    echo "  Using host config.yaml"
  else
    echo "  Using built-in config.yaml (no host override found)"
  fi

  # Host network — all services communicate via localhost
  docker run -d \
    --name chat_ui_app \
    --network host \
    --restart unless-stopped \
    --log-opt max-size=50m --log-opt max-file=5 \
    -e UI_FRAMEWORK=${UI_FRAMEWORK} \
    -e CHAINLIT_HOST=127.0.0.1 \
    -e CHAINLIT_PORT=${APP_INTERNAL_PORT} \
    -e CHAINLIT_AUTH_SECRET=${CHAINLIT_AUTH_SECRET} \
    -e CHAINLIT_DATA_LAYER=postgresql \
    -e PG_HOST=localhost \
    -e PG_PORT=${POSTGRES_PORT} \
    -e OLLAMA_HOST=localhost \
    -e OLLAMA_PORT=${OLLAMA_PORT} \
    -e CHROMA_HOST=localhost \
    -e CHROMA_PORT=${CHROMA_PORT} \
    -e DATABASE_URL=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:${POSTGRES_PORT}/${POSTGRES_DB} \
    -e ENABLE_AUTHENTICATION=${ENABLE_AUTHENTICATION} \
    -e ADMIN_PASSWORD=${ADMIN_PASSWORD} \
    -e API_KEYS=${ADMIN_API_KEY} \
    -e SERVICE_API_KEY=${SERVICE_API_KEY} \
    -e ENABLE_CACHE=true \
    -e REDIS_HOST=localhost \
    -e REDIS_PORT=${REDIS_PORT} \
    -e REDIS_PASSWORD=${REDIS_PASSWORD} \
    -e ACTIVE_PROFILE=${ACTIVE_PROFILE} \
    -e OLLAMA_BASE_URL=http://localhost:${OLLAMA_PORT} \
    -e OLLAMA_MODEL=$APP_OLLAMA_MODEL \
    -e OLLAMA_EMBED_MODEL=$APP_OLLAMA_EMBED \
    -e OLLAMA_NUM_CTX=${APP_OLLAMA_NUM_CTX:-2048} \
    -e OLLAMA_NUM_PREDICT=${APP_OLLAMA_NUM_PREDICT:-256} \
    -e OLLAMA_TEMPERATURE=${APP_OLLAMA_TEMPERATURE:-0.01} \
    -e CHROMA_HTTP_URL=http://localhost:${CHROMA_PORT} \
    -e CHROMA_COLLECTION=assistant_memory_mxbai_v2 \
    -e CHROMA_SECONDARY_COLLECTION=specs_mxbai_embed_large_v3 \
    -e CHROMA_ADDITIONAL_COLLECTIONS=spl_commands_mxbai,org_repo_mxbai,local_docs_mxbai,cribl_docs_mxbai \
    -e SEARCH_OPT_URL=http://localhost:${SEARCH_OPT_PORT} \
    -e DOCLING_ENABLED=${DOCLING_ENABLED:-false} \
    -e DOCLING_URL=http://localhost:${DOCLING_PORT:-5001} \
    -e DOCS_BASE_URL=/public \
    -e LOCAL_DOCS_ROOT=/app/shared/public/documents/pdfs \
    -e REPO_DOCS_ROOT=/app/shared/public/documents/repo \
    -e ORG_REPO_ROOT=/app/shared/public/documents/repo \
    -e SPEC_INGEST_ROOT=/app/shared/public/documents/specs \
    -e SPEC_STATIC_ROOT=/app/shared/public/documents/specs \
    -e SPL_DOCS_ROOT=/app/shared/public/documents/commands \
    -e CRIBL_DOCS_ROOT=/app/shared/public/documents/cribl \
    -e DOCUMENTS_ROOT=/app/shared/public/documents \
    -e FEEDBACK_ROOT=/app/shared/public/documents/feedback \
    -e APP_DATA_DIR=/app/data \
    -e CONFIG_YAML_WRITABLE=/app/data/config.yaml \
    -e CHAINLIT_BLOB_STORAGE_PROVIDER=local \
    -e CHAINLIT_BLOB_STORAGE_PATH=/app/.chainlit/blobs \
    -e LANGFUSE_HOST=http://localhost:${LANGFUSE_INTERNAL_PORT} \
    -e LANGFUSE_PUBLIC_KEY=${LANGFUSE_PUBLIC_KEY:-pk-obsai-dev} \
    -e LANGFUSE_SECRET_KEY=${LANGFUSE_SECRET_KEY:-sk-obsai-dev} \
    -e SPLUNK_VALIDATOR_HOST=localhost \
    -e SPLUNK_VALIDATOR_PORT=${SPLUNK_VALIDATOR_PORT:-8089} \
    -e SPLUNK_VALIDATOR_USER=${SPLUNK_VALIDATOR_USER:-admin} \
    -e SPLUNK_VALIDATOR_PASS=${SPLUNK_VALIDATOR_PASS:-${SPLUNK_ADMIN_PASSWORD}} \
    -v "$DOCUMENTS_ROOT:/app/shared/public/documents:ro,Z" \
    -v "chainlit_data:/app/.chainlit" \
    -v "app_data:/app/data" \
    -v "app_chroma_store:/app/chroma_store" \
    -v "app_certs:/app/certs" \
    ${SOCKET_MOUNT:+$SOCKET_MOUNT} \
    "${APP_EXTRA_MOUNTS[@]}" \
    chainlit-app:latest

  wait_for_service "Chat App" "curl -sf http://localhost:${APP_INTERNAL_PORT}/live > /dev/null 2>&1" 60
fi

# If open-webui mode, also start Open WebUI container
if [ "$UI_FRAMEWORK" = "open-webui" ]; then
  OPEN_WEBUI_PORT=${OPEN_WEBUI_PORT:-3000}
  echo ""
  echo "Starting Open WebUI frontend..."
  OW_STATUS=$(container_status "open_webui")
  if [ "$OW_STATUS" = "running" ]; then
    echo "Open WebUI already running"
  elif [ "$OW_STATUS" = "stopped" ]; then
    echo "Starting existing Open WebUI container..."
    docker start open_webui
    wait_for_service "Open WebUI" "curl -sf http://localhost:${OPEN_WEBUI_PORT}/ > /dev/null 2>&1" 30
  else
    echo "Creating Open WebUI container..."
    docker run -d \
      --name open_webui \
      --network host \
      --restart unless-stopped \
      -e OPENAI_API_BASE_URL=http://localhost:${APP_INTERNAL_PORT}/v1 \
      -e OPENAI_API_KEY=${OPENAI_API_KEY:-obsai-local} \
      -e WEBUI_AUTH=${OPEN_WEBUI_AUTH:-false} \
      -e ENABLE_OLLAMA_API=false \
      -e DEFAULT_MODELS=obsai-splunk-assistant \
      -v open_webui_data:/app/backend/data \
      ghcr.io/open-webui/open-webui:main

    wait_for_service "Open WebUI" "curl -sf http://localhost:${OPEN_WEBUI_PORT}/ > /dev/null 2>&1" 60
  fi
fi

echo ""

# =============================================================================
# SERVICE 6: Prometheus Monitoring
# =============================================================================
if [ "$START_SPLUNK_VALIDATOR" = true ]; then
    echo "================================================================================"
    echo "[7/$SERVICE_COUNT] Prometheus Monitoring"
    echo "================================================================================"
else
    echo "================================================================================"
    echo "[6/$SERVICE_COUNT] Prometheus Monitoring"
    echo "================================================================================"
fi
echo ""
PROM_CONFIG="$PROJECT_ROOT/monitoring/prometheus.yml"
PROM_ALERT_RULES="$PROJECT_ROOT/containers/prometheus/alert_rules.yml"
if [ ! -f "$PROM_CONFIG" ]; then
    echo "Prometheus config not found at $PROM_CONFIG — skipping (non-fatal)"
else
    STATUS=$(container_status "prometheus_monitoring")
    if [ "$STATUS" = "running" ]; then
        echo "Prometheus already running"
    elif [ "$STATUS" = "stopped" ]; then
        echo "Starting existing Prometheus container..."
        docker start prometheus_monitoring
        wait_for_service "Prometheus" "curl -sf http://127.0.0.1:${PROMETHEUS_INTERNAL_PORT}/-/ready > /dev/null 2>&1" 20 || true
    else
        echo "Creating Prometheus container..."
        docker run -d \
            --name prometheus_monitoring \
            --network host \
            --restart unless-stopped \
            --log-opt max-size=50m --log-opt max-file=3 \
            -v "$PROM_CONFIG:/etc/prometheus/prometheus.yml:ro,Z" \
            ${PROM_ALERT_RULES:+-v "$PROM_ALERT_RULES:/etc/prometheus/alert_rules.yml:ro,Z"} \
            -v prometheus_data:/prometheus \
            docker.io/prom/prometheus:latest \
            --config.file=/etc/prometheus/prometheus.yml \
            --storage.tsdb.path=/prometheus \
            --storage.tsdb.retention.time=30d \
            --storage.tsdb.retention.size=2GB \
            --web.listen-address=127.0.0.1:${PROMETHEUS_INTERNAL_PORT} \
            --web.external-url=/prometheus/ \
            --web.route-prefix=/

        wait_for_service "Prometheus" "curl -sf http://127.0.0.1:${PROMETHEUS_INTERNAL_PORT}/-/ready > /dev/null 2>&1" 20 || true
    fi
fi
echo ""

# =============================================================================
# SERVICE 7: Grafana Dashboards
# =============================================================================
if [ "$START_SPLUNK_VALIDATOR" = true ]; then
    echo "================================================================================"
    echo "[8/$SERVICE_COUNT] Grafana Dashboards"
    echo "================================================================================"
else
    echo "================================================================================"
    echo "[7/$SERVICE_COUNT] Grafana Dashboards"
    echo "================================================================================"
fi
echo ""
STATUS=$(container_status "grafana_monitoring")
if [ "$STATUS" = "running" ]; then
    echo "Grafana already running"
elif [ "$STATUS" = "stopped" ]; then
    echo "Starting existing Grafana container..."
    docker start grafana_monitoring
    wait_for_service "Grafana" "curl -sf http://127.0.0.1:${GRAFANA_INTERNAL_PORT}/grafana/api/health > /dev/null 2>&1" 20
else
    echo "Creating Grafana container..."
    docker run -d \
        --name grafana_monitoring \
        --network host \
        --restart unless-stopped \
        --log-opt max-size=50m --log-opt max-file=3 \
        -e "GF_SECURITY_ADMIN_PASSWORD=${GF_SECURITY_ADMIN_PASSWORD:-admin}" \
        -e "GF_SECURITY_ALLOW_EMBEDDING=true" \
        -e "GF_AUTH_ANONYMOUS_ENABLED=true" \
        -e "GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer" \
        -e "GF_SERVER_ROOT_URL=%(protocol)s://%(domain)s/grafana/" \
        -e "GF_SERVER_SERVE_FROM_SUB_PATH=true" \
        -e "GF_SERVER_HTTP_PORT=${GRAFANA_INTERNAL_PORT}" \
        -e "GF_SERVER_HTTP_ADDR=127.0.0.1" \
        -v grafana_data:/var/lib/grafana \
        -v "$PROJECT_ROOT/monitoring/grafana_datasource.yml:/etc/grafana/provisioning/datasources/datasource.yml:Z" \
        -v "$PROJECT_ROOT/monitoring/grafana_dashboard_provider.yml:/etc/grafana/provisioning/dashboards/provider.yml:Z" \
        -v "$PROJECT_ROOT/monitoring/search_optimizer_dashboard.json:/etc/grafana/provisioning/dashboards/search_optimizer.json:Z" \
        -v "$PROJECT_ROOT/monitoring/chainlit_app_dashboard.json:/etc/grafana/provisioning/dashboards/chainlit_app.json:Z" \
        docker.io/grafana/grafana:latest

    wait_for_service "Grafana" "curl -sf http://127.0.0.1:${GRAFANA_INTERNAL_PORT}/grafana/api/health > /dev/null 2>&1" 20
fi
echo ""

# =============================================================================
# SERVICE 8: Redis Cache
# =============================================================================
if [ "$START_SPLUNK_VALIDATOR" = true ]; then
    echo "================================================================================"
    echo "[9/9] Redis Cache"
    echo "================================================================================"
else
    echo "================================================================================"
    echo "[8/8] Redis Cache"
    echo "================================================================================"
fi
echo ""
STATUS=$(container_status "redis_cache")
if [ "$STATUS" = "running" ]; then
    echo "Redis already running"
elif [ "$STATUS" = "stopped" ]; then
    echo "Starting existing Redis container..."
    docker start redis_cache
    wait_for_service "Redis" "docker exec redis_cache redis-cli -p ${REDIS_PORT} -a ${REDIS_PASSWORD} --no-auth-warning ping" 20
else
    echo "Creating Redis container..."
    docker run -d \
        --name redis_cache \
        --network host \
        --restart unless-stopped \
        --log-opt max-size=50m --log-opt max-file=3 \
        docker.io/redis:7-alpine \
        --bind 127.0.0.1 --port ${REDIS_PORT} --requirepass "${REDIS_PASSWORD}" --maxmemory 256mb --maxmemory-policy allkeys-lru

    wait_for_service "Redis" "docker exec redis_cache redis-cli -p ${REDIS_PORT} -a ${REDIS_PASSWORD} --no-auth-warning ping" 20
fi
echo ""

# =============================================================================
# Nginx Gateway — Single entry point for all services
# =============================================================================
# Langfuse replaced by OpenTelemetry — uncomment to re-enable
# LANGFUSE LLM OBSERVABILITY (optional — deprecated, use OTel instead)
# =============================================================================
# if [ "$START_LANGFUSE" = true ]; then
# echo "================================================================================"
# echo "Langfuse LLM Observability"
# echo "================================================================================"
# echo ""
#
# # --- Langfuse v3 infrastructure ---
# LANGFUSE_NEXTAUTH_SECRET=${LANGFUSE_NEXTAUTH_SECRET:-$(openssl rand -hex 32 2>/dev/null || echo "obsai-langfuse-secret-change-me")}
# LANGFUSE_SALT=${LANGFUSE_SALT:-$(openssl rand -hex 16 2>/dev/null || echo "obsai-langfuse-salt")}
# LANGFUSE_ENCRYPTION_KEY=${LANGFUSE_ENCRYPTION_KEY:-$(openssl rand -hex 32 2>/dev/null || echo "0000000000000000000000000000000000000000000000000000000000000000")}
# LANGFUSE_CH_PASSWORD=${LANGFUSE_CH_PASSWORD:-clickhouse}
# LANGFUSE_MINIO_PASSWORD=${LANGFUSE_MINIO_PASSWORD:-miniosecret}
# LANGFUSE_REDIS_PASSWORD=${LANGFUSE_REDIS_PASSWORD:-langfuse-redis}
#
# # --- Create langfuse_db in PostgreSQL if it doesn't exist ---
# echo "Ensuring langfuse_db database exists..."
# docker exec chat_db_app psql -U "${POSTGRES_USER}" -tc \
#     "SELECT 1 FROM pg_database WHERE datname = 'langfuse_db'" | grep -q 1 || \
#     docker exec chat_db_app psql -U "${POSTGRES_USER}" -c "CREATE DATABASE langfuse_db" 2>/dev/null || true
#
# # --- ClickHouse (OLAP database for traces/observations) ---
# STATUS=$(container_status "langfuse_clickhouse")
# if [ "$STATUS" = "running" ]; then
#     echo "  ClickHouse already running"
# elif [ "$STATUS" = "stopped" ]; then
#     echo "  Starting existing ClickHouse..."
#     docker start langfuse_clickhouse
# else
#     echo "  Creating ClickHouse container..."
#     docker run -d \
#         --name langfuse_clickhouse \
#         --network host \
#         --restart unless-stopped \
#         -e CLICKHOUSE_DB=default \
#         -e CLICKHOUSE_USER=clickhouse \
#         -e CLICKHOUSE_PASSWORD="${LANGFUSE_CH_PASSWORD}" \
#         -e TZ=UTC \
#         -v langfuse_clickhouse_data:/var/lib/clickhouse \
#         -v langfuse_clickhouse_logs:/var/log/clickhouse-server \
#         docker.io/clickhouse/clickhouse-server:24.3
#     echo "  Waiting for ClickHouse..."
#     sleep 5
# fi
#
# # --- MinIO (S3-compatible blob store for events/media) ---
# STATUS=$(container_status "langfuse_minio")
# if [ "$STATUS" = "running" ]; then
#     echo "  MinIO already running"
# elif [ "$STATUS" = "stopped" ]; then
#     echo "  Starting existing MinIO..."
#     docker start langfuse_minio
# else
#     echo "  Creating MinIO container..."
#     docker run -d \
#         --name langfuse_minio \
#         --network host \
#         --restart unless-stopped \
#         -e MINIO_ROOT_USER=minio \
#         -e MINIO_ROOT_PASSWORD="${LANGFUSE_MINIO_PASSWORD}" \
#         -v langfuse_minio_data:/data \
#         --entrypoint sh \
#         cgr.dev/chainguard/minio \
#         -c 'mkdir -p /data/langfuse && minio server --address ":9010" --console-address ":9011" /data'
#     echo "  Waiting for MinIO..."
#     sleep 3
# fi
#
# # --- Langfuse Redis (dedicated, not shared with ObsAI Redis) ---
# STATUS=$(container_status "langfuse_redis")
# if [ "$STATUS" = "running" ]; then
#     echo "  Langfuse Redis already running"
# elif [ "$STATUS" = "stopped" ]; then
#     echo "  Starting existing Langfuse Redis..."
#     docker start langfuse_redis
# else
#     echo "  Creating Langfuse Redis container..."
#     docker run -d \
#         --name langfuse_redis \
#         --network host \
#         --restart unless-stopped \
#         -v langfuse_redis_data:/data \
#         docker.io/redis:7 \
#         --port 6399 --requirepass "${LANGFUSE_REDIS_PASSWORD}" --maxmemory-policy noeviction
#     sleep 2
# fi
#
# # --- Shared Langfuse env vars ---
# LANGFUSE_COMMON_ENV=(
#     -e DATABASE_URL="postgresql://${POSTGRES_USER}:${POSTGRES_PASSWORD}@localhost:5432/langfuse_db"
#     -e NEXTAUTH_URL="http://localhost:${GATEWAY_PORT:-8000}"
#     -e NEXTAUTH_SECRET="${LANGFUSE_NEXTAUTH_SECRET}"
#     -e SALT="${LANGFUSE_SALT}"
#     -e ENCRYPTION_KEY="${LANGFUSE_ENCRYPTION_KEY}"
#     -e CLICKHOUSE_URL="http://localhost:${CLICKHOUSE_HTTP_PORT}"
#     -e CLICKHOUSE_MIGRATION_URL="clickhouse://localhost:${CLICKHOUSE_NATIVE_PORT}"
#     -e CLICKHOUSE_USER=clickhouse
#     -e CLICKHOUSE_PASSWORD="${LANGFUSE_CH_PASSWORD}"
#     -e CLICKHOUSE_CLUSTER_ENABLED=false
#     -e REDIS_HOST=localhost
#     -e REDIS_PORT=6399
#     -e REDIS_AUTH="${LANGFUSE_REDIS_PASSWORD}"
#     -e LANGFUSE_S3_EVENT_UPLOAD_BUCKET=langfuse
#     -e LANGFUSE_S3_EVENT_UPLOAD_REGION=auto
#     -e LANGFUSE_S3_EVENT_UPLOAD_ACCESS_KEY_ID=minio
#     -e LANGFUSE_S3_EVENT_UPLOAD_SECRET_ACCESS_KEY="${LANGFUSE_MINIO_PASSWORD}"
#     -e LANGFUSE_S3_EVENT_UPLOAD_ENDPOINT="http://localhost:9010"
#     -e LANGFUSE_S3_EVENT_UPLOAD_FORCE_PATH_STYLE=true
#     -e LANGFUSE_S3_EVENT_UPLOAD_PREFIX=events/
#     -e LANGFUSE_S3_MEDIA_UPLOAD_BUCKET=langfuse
#     -e LANGFUSE_S3_MEDIA_UPLOAD_REGION=auto
#     -e LANGFUSE_S3_MEDIA_UPLOAD_ACCESS_KEY_ID=minio
#     -e LANGFUSE_S3_MEDIA_UPLOAD_SECRET_ACCESS_KEY="${LANGFUSE_MINIO_PASSWORD}"
#     -e LANGFUSE_S3_MEDIA_UPLOAD_ENDPOINT="http://localhost:9010"
#     -e LANGFUSE_S3_MEDIA_UPLOAD_FORCE_PATH_STYLE=true
#     -e LANGFUSE_S3_MEDIA_UPLOAD_PREFIX=media/
#     -e LANGFUSE_S3_BATCH_EXPORT_ENABLED=false
#     -e TELEMETRY_ENABLED=false
# )
#
# # --- Langfuse Worker (async event processing) ---
# STATUS=$(container_status "langfuse_worker")
# if [ "$STATUS" = "running" ]; then
#     echo "  Langfuse Worker already running"
# elif [ "$STATUS" = "stopped" ]; then
#     echo "  Starting existing Langfuse Worker..."
#     docker start langfuse_worker
# else
#     echo "  Creating Langfuse Worker container..."
#     docker run -d \
#         --name langfuse_worker \
#         --network host \
#         --restart unless-stopped \
#         "${LANGFUSE_COMMON_ENV[@]}" \
#         docker.io/langfuse/langfuse-worker:3
#     echo "  Waiting for Langfuse Worker..."
#     sleep 5
# fi
#
# # --- Langfuse Web (UI + API, replaces old langfuse_api) ---
# STATUS=$(container_status "langfuse_api")
# if [ "$STATUS" = "running" ]; then
#     echo "  Langfuse Web already running"
# elif [ "$STATUS" = "stopped" ]; then
#     echo "  Starting existing Langfuse Web..."
#     docker start langfuse_api
# else
#     echo "  Creating Langfuse Web container..."
#     docker run -d \
#         --name langfuse_api \
#         --network host \
#         --restart unless-stopped \
#         "${LANGFUSE_COMMON_ENV[@]}" \
#         -e LANGFUSE_INIT_ORG_ID="obsai" \
#         -e LANGFUSE_INIT_ORG_NAME="ObsAI" \
#         -e LANGFUSE_INIT_PROJECT_ID="obsai-dev" \
#         -e LANGFUSE_INIT_PROJECT_NAME="ObsAI Development" \
#         -e LANGFUSE_INIT_PROJECT_PUBLIC_KEY="${LANGFUSE_PUBLIC_KEY:-pk-obsai-dev}" \
#         -e LANGFUSE_INIT_PROJECT_SECRET_KEY="${LANGFUSE_SECRET_KEY:-sk-obsai-dev}" \
#         -e LANGFUSE_INIT_USER_EMAIL="${LANGFUSE_ADMIN_EMAIL:-admin@obsai.local}" \
#         -e LANGFUSE_INIT_USER_NAME="${LANGFUSE_ADMIN_USER:-admin}" \
#         -e LANGFUSE_INIT_USER_PASSWORD="${LANGFUSE_ADMIN_PASSWORD:-obsai-admin-2026}" \
#         -e HOSTNAME=0.0.0.0 \
#         -e PORT=${LANGFUSE_INTERNAL_PORT:-3200} \
#         docker.io/langfuse/langfuse:3
#     echo "  Waiting for Langfuse Web to start..."
#     sleep 15
# fi
# echo "  Langfuse UI: http://localhost:${GATEWAY_PORT:-8000}/langfuse/"
# echo "  Default login: admin@obsai.local / obsai-admin-2026"
# echo ""
# fi

# =============================================================================
echo "================================================================================"
echo "Nginx Gateway (single-port access)"
echo "================================================================================"
echo ""

GATEWAY_PORT="${GATEWAY_PORT:-${CHAINLIT_PORT}}"

# Generate nginx config from template with correct ports
NGINX_CONF_DIR="$PROJECT_ROOT/containers/nginx"
if [ -f "$NGINX_CONF_DIR/nginx.conf.template" ]; then
    export NGINX_LISTEN_PORT=${GATEWAY_PORT}
    export APP_PORT=${APP_INTERNAL_PORT}
    export GRAFANA_PORT=${GRAFANA_INTERNAL_PORT}
    export PROMETHEUS_PORT=${PROMETHEUS_INTERNAL_PORT}
    export SEARCH_OPT_PORT=${SEARCH_OPT_PORT}
    export LANGFUSE_PORT=${LANGFUSE_INTERNAL_PORT}
    envsubst '${NGINX_LISTEN_PORT} ${APP_PORT} ${GRAFANA_PORT} ${PROMETHEUS_PORT} ${SEARCH_OPT_PORT} ${LANGFUSE_PORT}' \
        < "$NGINX_CONF_DIR/nginx.conf.template" \
        > "$NGINX_CONF_DIR/nginx.generated.conf"
    NGINX_CONF="$NGINX_CONF_DIR/nginx.generated.conf"
    echo "  Generated nginx.conf (HTTPS :${GATEWAY_PORT}, app :${APP_INTERNAL_PORT})"
else
    NGINX_CONF="$PROJECT_ROOT/nginx/nginx.conf"
fi

STATUS=$(container_status "nginx_gateway")
if [ "$STATUS" = "running" ]; then
    echo "Nginx gateway already running"
elif [ "$STATUS" = "stopped" ]; then
    echo "Starting existing Nginx gateway..."
    docker start nginx_gateway
else
    echo "Creating Nginx gateway container..."

    # SSL certificates: generate self-signed if none exist
    CERTS_DIR="$PROJECT_ROOT/certs"
    mkdir -p "$CERTS_DIR"
    if [ -f "$CERTS_DIR/cert.pem" ] && [ -f "$CERTS_DIR/key.pem" ]; then
        echo "  SSL: Using production certificates from $CERTS_DIR/"
    else
        echo "  SSL: Generating self-signed certificate"
        openssl req -x509 -newkey rsa:2048 \
            -keyout "$CERTS_DIR/key.pem" \
            -out "$CERTS_DIR/cert.pem" \
            -days 365 -nodes \
            -subj "/CN=localhost/O=ObsAI/C=US" 2>/dev/null
        echo "  SSL: Self-signed certificate generated (valid 365 days)"
    fi

    # Build custom nginx image with admin UI + certs baked in (no volume permission issues)
    NGINX_IMAGE="obsai-nginx:latest"
    echo "  Building nginx image with admin UI and SSL certs..."
    docker build -q -t "$NGINX_IMAGE" -f containers/nginx/Dockerfile.nginx "$PROJECT_ROOT" 2>/dev/null \
        && echo "  Nginx image built: $NGINX_IMAGE" \
        || { echo "  Nginx image build failed — falling back to volume mounts"; NGINX_IMAGE="docker.io/nginx:alpine"; }

    # Determine mount strategy based on image
    ADMIN_UI_MOUNT=""
    CERTS_MOUNT=""
    if [ "$NGINX_IMAGE" = "docker.io/nginx:alpine" ]; then
        # Fallback: use volume mounts (may have permission issues on rootless podman)
        ADMIN_UI_DIR="${PROJECT_ROOT}/frontend/dist"
        [ -d "$ADMIN_UI_DIR" ] && ADMIN_UI_MOUNT="-v ${ADMIN_UI_DIR}:/usr/share/nginx/admin-ui:ro,Z"
        CERTS_MOUNT="-v ${CERTS_DIR}:/etc/nginx/certs:ro,Z"
        echo "  Admin UI: volume mounted (may need permission fix)"
    else
        echo "  Admin UI: baked into nginx image (no permission issues)"
    fi

    docker run -d \
        --name nginx_gateway \
        --network host \
        --restart unless-stopped \
        --log-opt max-size=50m --log-opt max-file=3 \
        -v "$NGINX_CONF:/etc/nginx/nginx.conf:ro,Z" \
        $ADMIN_UI_MOUNT \
        $CERTS_MOUNT \
        "$NGINX_IMAGE"

    # Wait for nginx — try HTTPS first, fall back to checking if port is open
    wait_for_service "Nginx Gateway" "curl -skf https://localhost:${GATEWAY_PORT}/nginx-health > /dev/null 2>&1 || bash -c 'echo > /dev/tcp/127.0.0.1/${GATEWAY_PORT}' 2>/dev/null" 60 \
        || echo "  WARNING: Nginx health check timed out but container may still be starting"
fi
echo "  All services via https://localhost:${GATEWAY_PORT}"
echo "  /grafana  /prometheus  /search-opt"
echo ""

# =============================================================================
# BACKGROUND INGESTION
# =============================================================================

if [ "$SKIP_INGESTION" = false ]; then
  echo "================================================================================"
  echo "Background Document Ingestion"
  echo "================================================================================"
  echo ""

  if [ "${FORCE_REINDEX:-false}" = "true" ]; then
    echo "Starting full reindex (delete + re-ingest) inside chat_ui_app..."
    docker exec -d chat_ui_app python3 /app/chat_app/run_quick_ingest.py > /dev/null 2>&1
    echo "Full reindex started in background inside container"
  else
    echo "Starting incremental ingestion inside chat_ui_app..."
    docker exec -d chat_ui_app python3 /app/chat_app/run_quick_ingest.py --skip-delete > /dev/null 2>&1
    echo "Incremental ingestion started in background inside container"
  fi
  echo "  - Monitor: docker exec chat_ui_app ps aux | grep run_quick"
  echo "  - Full reindex: FORCE_REINDEX=true bash docker_files/start_all.sh"
  echo ""
else
  echo "================================================================================"
  echo "Background Document Ingestion"
  echo "================================================================================"
  echo ""
  echo "Skipped (--no-ingest flag)"
  echo ""
fi

# =============================================================================
# POST-STARTUP TASKS (run after app is ready)
# =============================================================================
echo "================================================================================"
echo "Post-Startup Tasks"
echo "================================================================================"
echo ""

APP_URL="https://localhost:${GATEWAY_PORT}"

# Auth header for admin API calls
AUTH_HEADER=""
if [ -n "${ADMIN_API_KEY:-}" ]; then
  AUTH_HEADER="-H X-API-Key:${ADMIN_API_KEY}"
fi

# Sync generated API key into .mcp.json so MCP clients auto-authenticate
if [ -f "$PROJECT_ROOT/.mcp.json" ] && [ -n "${ADMIN_API_KEY:-}" ]; then
  python3 -c "
import json, sys
try:
    with open('$PROJECT_ROOT/.mcp.json') as f:
        d = json.load(f)
    if 'mcpServers' in d and 'obsai' in d['mcpServers']:
        d['mcpServers']['obsai']['env']['OBSAI_API_KEY'] = '${ADMIN_API_KEY}'
        with open('$PROJECT_ROOT/.mcp.json', 'w') as f:
            json.dump(d, f, indent=2)
            f.write('\n')
        print('  .mcp.json updated with current API key')
    else:
        print('  .mcp.json has no obsai server entry — skipped')
except Exception as e:
    print(f'  .mcp.json update failed: {e}', file=sys.stderr)
" 2>/dev/null || echo "  .mcp.json sync skipped (python3 not available)"
fi

# Trigger Splunkbase catalog refresh (background, non-blocking)
echo "Triggering Splunkbase catalog refresh..."
curl -sk ${AUTH_HEADER} -X POST "${APP_URL}/api/admin/splunkbase/refresh" > /dev/null 2>&1 &
echo "  Catalog refresh started in background"

# Trigger collection reindex if requested
if [ "${FORCE_REINDEX:-false}" = "true" ]; then
  echo "Triggering full collection reindex..."
  curl -sk ${AUTH_HEADER} -X POST "${APP_URL}/api/admin/collections/reindex" > /dev/null 2>&1 &
  echo "  Reindex started in background"
fi

# Trigger knowledge graph rebuild
echo "Triggering knowledge graph rebuild..."
curl -sk ${AUTH_HEADER} -X POST "${APP_URL}/api/admin/knowledge-graph/rebuild" > /dev/null 2>&1 &
echo "  Knowledge graph rebuild started in background"

echo ""

# =============================================================================
# COMPLETION
# =============================================================================

echo "================================================================================"
echo "Startup Complete!"
echo "================================================================================"
echo ""
echo "All services accessible at: https://localhost:${GATEWAY_PORT}"
echo ""
echo "  Chat UI        https://localhost:${GATEWAY_PORT}/"
echo "  Admin v2       https://localhost:${GATEWAY_PORT}/api/admin/v2/"
echo "  Docs           https://localhost:${GATEWAY_PORT}/api/admin/docs"
echo "  Commands       https://localhost:${GATEWAY_PORT}/api/admin/v2/interactive"
echo "  Grafana        https://localhost:${GATEWAY_PORT}/grafana/"
echo "  Prometheus     https://localhost:${GATEWAY_PORT}/prometheus/"
echo "  Search Opt     https://localhost:${GATEWAY_PORT}/search-opt/"
echo ""
echo "Internal service ports (localhost only):"
echo "  PostgreSQL     localhost:${POSTGRES_PORT}"
echo "  ChromaDB       localhost:${CHROMA_PORT}"
echo "  Ollama         localhost:${OLLAMA_PORT}"
echo "  App            localhost:${APP_INTERNAL_PORT}"
echo "  Search Opt     localhost:${SEARCH_OPT_PORT}"
echo "  Redis          localhost:${REDIS_PORT}"
echo "  Prometheus     localhost:${PROMETHEUS_INTERNAL_PORT}"
echo "  Grafana        localhost:${GRAFANA_INTERNAL_PORT}"
echo ""
if [ "${ENABLE_AUTHENTICATION}" = "true" ]; then
echo "API Authentication:"
echo "  Admin API Key:     ${ADMIN_API_KEY}"
echo "  Admin Password:    ${ADMIN_PASSWORD}"
echo ""
fi
echo "Useful Commands:"
echo "  Check status:      docker ps"
echo "  View logs:         docker logs chat_ui_app"
echo "  Stop all:          bash docker_files/stop_all.sh"
echo "  Restart:           bash docker_files/start_all.sh"
echo "  Check collections: bash docker_files/check_chroma.sh"
echo ""
echo "================================================================================"
