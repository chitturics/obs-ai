#!/bin/bash
set -euo pipefail

# Function to wait for a TCP port to be open (DNS-resilient for podman)
# Tries both IPv4 and IPv6 (podman rootless often only exposes IPv6)
wait_for_service() {
    local service_name="$1"
    local host="$2"
    local port="$3"
    local max_retries=12
    local retry_count=0

    echo "Waiting for $service_name at $host:$port..."

    while true; do
        # Try configured host first, then IPv6 loopback as fallback
        if python3 -c "import socket; s=socket.create_connection(('$host', $port), 2); s.close()" 2>/dev/null; then
            break
        fi
        # Podman rootless: try IPv6 loopback if host is localhost/127.0.0.1
        if [ "$host" = "localhost" ] || [ "$host" = "127.0.0.1" ]; then
            if python3 -c "import socket; s=socket.create_connection(('::1', $port), 2); s.close()" 2>/dev/null; then
                echo "$service_name is ready (via IPv6 [::1]:$port)."
                return 0
            fi
        fi
        retry_count=$((retry_count + 1))
        if [ $retry_count -ge $max_retries ]; then
            echo "WARNING: $service_name at $host:$port did not become ready after $((max_retries * 5)) seconds"
            echo "  If using podman, ensure containers share a network:"
            echo "    podman network create chainlit_net"
            echo "    podman run --network chainlit_net ..."
            echo "  Continuing anyway - the app will retry connections at runtime."
            return 0
        fi
        echo "$service_name not ready yet. Waiting 5 more seconds... (attempt $retry_count/$max_retries)"
        sleep 5
    done
    echo "$service_name is ready."
}

# Use environment variables with defaults for service locations
PG_HOST="${PG_HOST:-chat_db_app}"
PG_PORT="${PG_PORT:-5432}"
# Strip http:// or https:// from OLLAMA_HOST if present, extract host and port
_OLLAMA_RAW="${OLLAMA_HOST:-llm_api_service}"
_OLLAMA_RAW="${_OLLAMA_RAW#http://}"
_OLLAMA_RAW="${_OLLAMA_RAW#https://}"
# Split host:port if port is embedded (e.g., "127.0.0.1:11430")
if [[ "$_OLLAMA_RAW" == *":"* ]]; then
    OLLAMA_HOST_RESOLVED="${_OLLAMA_RAW%%:*}"
    OLLAMA_PORT="${_OLLAMA_RAW##*:}"
else
    OLLAMA_HOST_RESOLVED="$_OLLAMA_RAW"
    OLLAMA_PORT="${OLLAMA_PORT:-11430}"
fi
CHROMA_HOST="${CHROMA_HOST:-chat_chroma_db}"
CHROMA_PORT="${CHROMA_PORT:-8001}"

# Wait for all services (non-fatal - app retries at runtime)
wait_for_service "PostgreSQL" "$PG_HOST" "$PG_PORT"
wait_for_service "Ollama" "$OLLAMA_HOST_RESOLVED" "$OLLAMA_PORT"
wait_for_service "ChromaDB" "$CHROMA_HOST" "$CHROMA_PORT"

echo 'All services READY (or skipped).'

# Ensure Python can find all modules in chat_app/ and the parent directory
export PYTHONPATH="/app/chat_app:/app:${PYTHONPATH:-}"

# ---- Docker socket access (for container management from admin UI) ----
if [ -S /var/run/docker.sock ]; then
    # In rootless podman, the socket GID may not map correctly.
    # Try to make it accessible to our user via group or chmod.
    if docker ps > /dev/null 2>&1; then
        echo "  Docker socket: OK (accessible)"
    else
        # Try chmod if we have permission (works when running as root entrypoint)
        chmod 666 /var/run/docker.sock 2>/dev/null && echo "  Docker socket: fixed permissions (666)" || \
        echo "  Docker socket: mounted but not accessible (container management will be limited)"
    fi
fi

# ---- Startup diagnostics ----
echo '--- Startup Diagnostics ---'
if [ -f /app/config.yaml ]; then
    if [ -r /app/config.yaml ]; then
        echo "  config.yaml: OK (readable)"
    else
        echo "  WARNING: /app/config.yaml exists but is NOT readable (permission denied)"
        echo "  The app will use defaults + env vars instead."
        echo "  Fix on host: chmod a+r /path/to/config.yaml"
    fi
elif [ -d /app/config.yaml ]; then
    echo "  WARNING: /app/config.yaml is a DIRECTORY (bad volume mount!)"
    echo "  Removing it so the app can use defaults..."
    rmdir /app/config.yaml 2>/dev/null || rm -rf /app/config.yaml 2>/dev/null || true
else
    echo "  config.yaml: not present (using defaults + env vars)"
fi

# Verify critical directories
for dir in /app/chat_app /app/shared/public/documents; do
    if [ -d "$dir" ]; then
        echo "  $dir: OK"
    else
        echo "  WARNING: $dir missing"
    fi
done

# Verify document subdirectories (all read-only)
for subdir in specs commands repo pdfs cribl feedback; do
    target="/app/shared/public/documents/$subdir"
    if [ -d "$target" ]; then
        echo "  documents/$subdir: OK"
    else
        echo "  documents/$subdir: not found (non-fatal)"
    fi
done

# Check prometheus_client availability
python3 -c "import prometheus_client; print('  prometheus_client:', prometheus_client.__version__)" 2>/dev/null \
    || echo "  prometheus_client: not installed (health metrics disabled, non-fatal)"

echo '---'

# Auto-create PostgreSQL schema (idempotent - safe to run every startup)
echo 'Ensuring database schema exists...'
python3 /app/chat_app/init_schema.py 2>&1 || echo 'Schema init completed with warnings (non-fatal)'

# Determine UI framework from env var or config.yaml
UI_FRAMEWORK="${UI_FRAMEWORK:-}"
if [ -z "$UI_FRAMEWORK" ] && [ -f /app/config.yaml ]; then
    UI_FRAMEWORK=$(python3 -c "
import yaml
try:
    with open('/app/config.yaml') as f:
        cfg = yaml.safe_load(f) or {}
    print(cfg.get('ui', {}).get('framework', 'chainlit'))
except Exception:
    print('chainlit')
" 2>/dev/null)
fi
UI_FRAMEWORK="${UI_FRAMEWORK:-chainlit}"

cd /app/chat_app

# Detect application port from config.yaml (fallback to env / 8000)
APP_PORT="${CHAINLIT_PORT:-8000}"
if [ -f /app/config.yaml ]; then
    CFG_PORT=$(python3 -c "
import yaml
try:
    with open('/app/config.yaml') as f:
        cfg = yaml.safe_load(f) or {}
    p = cfg.get('ports',{}).get('app') or cfg.get('ui',{}).get('port')
    if p: print(p)
except Exception:
    pass
" 2>/dev/null)
    [ -n "$CFG_PORT" ] && APP_PORT=$CFG_PORT
fi
echo "Application port: $APP_PORT"

# Detect SSL configuration from config.yaml
SSL_ARGS=""
if [ -f /app/config.yaml ]; then
    SSL_ENABLED=$(python3 -c "
import yaml
try:
    with open('/app/config.yaml') as f:
        cfg = yaml.safe_load(f) or {}
    ssl = cfg.get('ui', {}).get('ssl', {})
    if ssl.get('enabled'):
        cert = ssl.get('cert_file', '')
        key = ssl.get('key_file', '')
        if cert and key:
            print(f'--ssl-certfile {cert} --ssl-keyfile {key}')
except Exception:
    pass
" 2>/dev/null)
    if [ -n "$SSL_ENABLED" ]; then
        SSL_ARGS="$SSL_ENABLED"
        echo "SSL/TLS enabled: $SSL_ARGS"
    fi
fi

if [ "$UI_FRAMEWORK" = "open-webui" ]; then
    echo "Starting ObsAI API server (Open WebUI mode)..."
    exec uvicorn app_api:app --host 0.0.0.0 --port $APP_PORT $SSL_ARGS
else
    echo "Starting Chainlit..."
    if [ -n "$SSL_ARGS" ]; then
        echo "NOTE: SSL enabled — starting via uvicorn with Chainlit app"
        exec uvicorn app:socket_app --host 0.0.0.0 --port $APP_PORT $SSL_ARGS
    else
        exec chainlit run app.py --port $APP_PORT
    fi
fi
