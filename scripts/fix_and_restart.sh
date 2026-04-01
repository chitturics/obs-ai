#!/bin/bash
# =============================================================================
# Complete Recovery Script - Fix All Issues and Restart
# =============================================================================
# This script fixes all known issues:
# 1. PostgreSQL schema initialization
# 2. Ollama permission errors (SELinux :z flags)
# 3. .chainlit permission errors
# 4. Volume cleanup and recreation
# =============================================================================

set -e

cd "$(dirname "$0")/.."

# Docker/Podman detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi

echo "================================================================================"
echo "Complete System Recovery and Restart"
echo "================================================================================"
echo ""
echo "This will:"
echo "  1. Stop all containers"
echo "  2. Clean up volumes (keeping models)"
echo "  3. Fix all permission issues"
echo "  4. Restart with proper configuration"
echo ""
read -p "Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Aborted"
  exit 1
fi

echo ""
echo "================================================================================"
echo "Step 1: Stopping All Containers"
echo "================================================================================"
echo ""

# Stop containers in reverse dependency order
for container in chat_ui_app llm_api_service chat_chroma_db chat_db_app; do
  if $DOCKER_CMD ps -a --format '{{.Names}}' | grep -q "^${container}$"; then
    echo "Stopping $container..."
    $DOCKER_CMD stop $container 2>/dev/null || true
    echo "Removing $container..."
    $DOCKER_CMD rm $container 2>/dev/null || true
  fi
done

echo "✓ All containers stopped and removed"
echo ""

echo "================================================================================"
echo "Step 2: Cleaning Up Volumes (Except Model Data)"
echo "================================================================================"
echo ""

# Remove problematic volumes (will be recreated with init scripts)
for volume in postgres_data chainlit_data; do
  if $DOCKER_CMD volume inspect $volume &>/dev/null; then
    echo "Removing volume: $volume"
    $DOCKER_CMD volume rm $volume || true
  fi
done

echo "✓ Problematic volumes removed"
echo ""

echo "================================================================================"
echo "Step 3: Fixing PostgreSQL Schema File"
echo "================================================================================"
echo ""

PROJECT_ROOT="$(pwd)"

# Ensure postgres directory exists
mkdir -p "$PROJECT_ROOT/postgres"

# Check if init script exists
if [ ! -f "$PROJECT_ROOT/postgres/init_chainlit_schema.sql" ]; then
  echo "Creating PostgreSQL init script..."
  cat > "$PROJECT_ROOT/postgres/init_chainlit_schema.sql" << 'EOSQL'
CREATE TABLE IF NOT EXISTS users (
    "id" UUID PRIMARY KEY,
    "identifier" TEXT NOT NULL UNIQUE,
    "metadata" JSONB NOT NULL,
    "createdAt" TEXT
);

CREATE TABLE IF NOT EXISTS threads (
    "id" UUID PRIMARY KEY,
    "createdAt" TEXT,
    "name" TEXT,
    "userId" UUID,
    "userIdentifier" TEXT,
    "tags" TEXT[],
    "metadata" JSONB,
    FOREIGN KEY ("userId") REFERENCES users("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS steps (
    "id" UUID PRIMARY KEY,
    "name" TEXT NOT NULL,
    "type" TEXT NOT NULL,
    "threadId" UUID NOT NULL,
    "parentId" UUID,
    "streaming" BOOLEAN NOT NULL,
    "waitForAnswer" BOOLEAN,
    "isError" BOOLEAN,
    "metadata" JSONB,
    "tags" TEXT[],
    "input" TEXT,
    "output" TEXT,
    "createdAt" TEXT,
    "command" TEXT,
    "start" TEXT,
    "end" TEXT,
    "generation" JSONB,
    "showInput" TEXT,
    "language" TEXT,
    "indent" INT,
    "defaultOpen" BOOLEAN,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS elements (
    "id" UUID PRIMARY KEY,
    "threadId" UUID,
    "type" TEXT,
    "url" TEXT,
    "chainlitKey" TEXT,
    "name" TEXT NOT NULL,
    "display" TEXT,
    "objectKey" TEXT,
    "size" TEXT,
    "page" INT,
    "language" TEXT,
    "forId" UUID,
    "mime" TEXT,
    "props" JSONB,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedbacks (
    "id" UUID PRIMARY KEY,
    "forId" UUID NOT NULL,
    "threadId" UUID NOT NULL,
    "value" INT NOT NULL,
    "comment" TEXT,
    FOREIGN KEY ("threadId") REFERENCES threads("id") ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS assistant_interactions (
    "id" UUID PRIMARY KEY,
    "username" TEXT NOT NULL,
    "thread_id" TEXT,
    "question" TEXT,
    "answer" TEXT,
    "context" TEXT,
    "created_at" TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assistant_feedback (
    "id" UUID PRIMARY KEY,
    "message_id" TEXT,
    "value" INT,
    "comment" TEXT,
    "username" TEXT,
    "thread_id" TEXT,
    "created_at" TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS assistant_notes (
    "id" UUID PRIMARY KEY,
    "title" TEXT,
    "body" TEXT,
    "created_by" TEXT,
    "thread_id" TEXT,
    "created_at" TIMESTAMPTZ DEFAULT NOW()
);
EOSQL
  echo "✓ Created init_chainlit_schema.sql"
else
  echo "✓ init_chainlit_schema.sql already exists"
fi

echo ""

echo "================================================================================"
echo "Step 4: Fixing Directory Permissions"
echo "================================================================================"
echo ""

# Create necessary directories with proper permissions
mkdir -p "$PROJECT_ROOT/.chainlit"
mkdir -p "$PROJECT_ROOT/.chainlit/blobs"
mkdir -p "$PROJECT_ROOT/feedback"
mkdir -p "$PROJECT_ROOT/llms"

# Fix permissions (wide open for SELinux compatibility)
echo "Setting directory permissions..."
chmod -R 777 "$PROJECT_ROOT/.chainlit" 2>/dev/null || true
chmod -R 777 "$PROJECT_ROOT/feedback" 2>/dev/null || true
chmod -R 755 "$PROJECT_ROOT/llms" 2>/dev/null || true

echo "✓ Directory permissions fixed"
echo ""

echo "================================================================================"
echo "Step 5: Creating start_all_fixed.sh with SELinux Fixes"
echo "================================================================================"
echo ""

# Create a patched version of start_all.sh with all fixes
cp "$PROJECT_ROOT/docker_files/start_all.sh" "$PROJECT_ROOT/docker_files/start_all_fixed.sh"

# Apply SELinux :z flag fixes
if command -v sed &> /dev/null; then
  # Fix Ollama volume mount (line 235)
  sed -i 's|-v "$PROJECT_ROOT/llms:/root/.ollama"|-v "$PROJECT_ROOT/llms:/root/.ollama:z"|g' \
    "$PROJECT_ROOT/docker_files/start_all_fixed.sh"

  # Fix .chainlit volume mount (line 306)
  sed -i 's|-v "$PROJECT_ROOT/.chainlit:/app/.chainlit"|-v "$PROJECT_ROOT/.chainlit:/app/.chainlit:rw,z"|g' \
    "$PROJECT_ROOT/docker_files/start_all_fixed.sh"

  # Fix feedback volume mount (line 307)
  sed -i 's|-v "$PROJECT_ROOT/feedback:/app/public/feedback"|-v "$PROJECT_ROOT/feedback:/app/public/feedback:rw,z"|g' \
    "$PROJECT_ROOT/docker_files/start_all_fixed.sh"

  echo "✓ Created start_all_fixed.sh with SELinux :z flags"
else
  echo "⚠️  sed not available, manual edits needed"
fi

echo ""

echo "================================================================================"
echo "Step 6: Starting Services with Fixed Configuration"
echo "================================================================================"
echo ""

# Use the fixed script
bash "$PROJECT_ROOT/docker_files/start_all_fixed.sh" --no-ingest

echo ""
echo "================================================================================"
echo "Step 7: Verifying Services"
echo "================================================================================"
echo ""

sleep 10

echo "Checking container status..."
$DOCKER_CMD ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

echo ""
echo "Checking PostgreSQL tables..."
if $DOCKER_CMD exec chat_db_app psql -U chainlit -d chainlit -c "\dt" 2>/dev/null; then
  echo "✓ PostgreSQL schema created successfully"
else
  echo "⚠️  PostgreSQL may still be initializing"
fi

echo ""
echo "Checking Ollama..."
if $DOCKER_CMD exec llm_api_service ollama list &>/dev/null; then
  echo "✓ Ollama responding"
  $DOCKER_CMD exec llm_api_service ollama list
else
  echo "⚠️  Ollama not ready yet (may need more time)"
fi

echo ""
echo "Checking ChromaDB..."
if curl -s http://localhost:8001/api/v1/heartbeat &>/dev/null; then
  echo "✓ ChromaDB responding"
else
  echo "⚠️  ChromaDB not accessible"
fi

echo ""
echo "================================================================================"
echo "Recovery Complete!"
echo "================================================================================"
echo ""
echo "Services should be available at:"
echo "  - Chainlit UI:    http://localhost:8000"
echo "  - ChromaDB:       http://localhost:8001"
echo "  - PostgreSQL:     localhost:5432"
echo "  - Ollama:         http://localhost:11430"
echo ""
echo "Check logs if issues persist:"
echo "  $DOCKER_CMD logs chat_db_app       # PostgreSQL"
echo "  $DOCKER_CMD logs llm_api_service   # Ollama"
echo "  $DOCKER_CMD logs chat_chroma_db    # ChromaDB"
echo "  $DOCKER_CMD logs chat_ui_app       # Chainlit app"
echo ""
echo "To run ingestion after services stabilize:"
echo "  bash docker_files/start_all_fixed.sh"
echo "  (or manually trigger ingestion after verifying all services work)"
echo ""
echo "================================================================================"
