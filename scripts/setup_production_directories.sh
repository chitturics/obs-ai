#!/bin/bash
# =============================================================================
# Production Directory Setup Script
# =============================================================================
# Sets up the project root directory with proper permissions.
# Run this ONCE on the remote machine before deploying.
#
# Usage:
#   sudo ./setup_production_directories.sh [/path/to/install]
#   Default: /opt/obsai/chatbot  (override with first argument)
# =============================================================================

set -e

# Configurable install path — pass as first arg or override via env
INSTALL_ROOT="${1:-${OBSAI_ROOT:-/opt/obsai/chatbot}}"

# Require root
if [ "$EUID" -ne 0 ]; then
  echo "This script must be run as root (use sudo)"
  exit 1
fi

echo "================================================================================"
echo "Production Directory Setup"
echo "================================================================================"
echo ""
echo "This will create and configure:"
echo "  $INSTALL_ROOT              - Application and runtime data"
echo "  $INSTALL_ROOT/documents    - Documentation (read-only)"
echo ""
read -p "Continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
  echo "Aborted"
  exit 1
fi

echo ""

# =============================================================================
# Create Directory Structure
# =============================================================================

echo "Creating directory structure..."
echo ""

# Base directories
mkdir -p $INSTALL_ROOT

# Chatbot subdirectories
mkdir -p $INSTALL_ROOT/chat_app
mkdir -p $INSTALL_ROOT/containers
mkdir -p $INSTALL_ROOT/docker_files
mkdir -p $INSTALL_ROOT/scripts
mkdir -p $INSTALL_ROOT/postgres
mkdir -p $INSTALL_ROOT/ingest_specs
mkdir -p $INSTALL_ROOT/docs

# Runtime directories (container writes here)
mkdir -p $INSTALL_ROOT/.chainlit/blobs
mkdir -p $INSTALL_ROOT/feedback
mkdir -p $INSTALL_ROOT/llms

# Documents subdirectories (read-only for containers)
mkdir -p $INSTALL_ROOT/documents/specs
mkdir -p $INSTALL_ROOT/documents/commands
mkdir -p $INSTALL_ROOT/documents/repo
mkdir -p $INSTALL_ROOT/documents/pdfs
mkdir -p $INSTALL_ROOT/documents/cribl
mkdir -p $INSTALL_ROOT/documents/feedback

echo "✓ Directories created"
echo ""

# =============================================================================
# Set Ownership
# =============================================================================

echo "Setting ownership..."

chown -R root:root $INSTALL_ROOT

echo "✓ Ownership set to root:root"
echo ""

# =============================================================================
# Set Permissions
# =============================================================================

echo "Setting permissions..."

# Base directories - standard restrictive permissions
chmod 755 "$(dirname "$INSTALL_ROOT")"
chmod 755 $INSTALL_ROOT

# Application directories - read-only for containers
chmod -R 755 $INSTALL_ROOT/chat_app
chmod -R 755 $INSTALL_ROOT/containers
chmod -R 755 $INSTALL_ROOT/docker_files
chmod -R 755 $INSTALL_ROOT/scripts
chmod -R 755 $INSTALL_ROOT/postgres
chmod -R 755 $INSTALL_ROOT/ingest_specs
chmod -R 755 $INSTALL_ROOT/docs

# Runtime directories - wide open for container writes (with SELinux :z flags)
chmod -R 777 $INSTALL_ROOT/.chainlit
chmod -R 777 $INSTALL_ROOT/feedback
chmod -R 777 $INSTALL_ROOT/llms

# Document directories - read-only for containers
chmod -R 755 $INSTALL_ROOT/documents

echo "✓ Permissions configured"
echo ""

# =============================================================================
# SELinux Configuration (if enabled)
# =============================================================================

if command -v getenforce &> /dev/null && [ "$(getenforce)" != "Disabled" ]; then
  echo "SELinux detected - applying container file contexts..."

  # Container writable directories
  chcon -R -t container_file_t $INSTALL_ROOT/.chainlit 2>/dev/null || true
  chcon -R -t container_file_t $INSTALL_ROOT/feedback 2>/dev/null || true
  chcon -R -t container_file_t $INSTALL_ROOT/llms 2>/dev/null || true

  # Container readable directories (documents)
  chcon -R -t container_file_t $INSTALL_ROOT/documents 2>/dev/null || true

  echo "✓ SELinux contexts applied"
  echo ""
else
  echo "⚠️  SELinux not enabled - skipping context setup"
  echo ""
fi

# =============================================================================
# Create PostgreSQL Init Script
# =============================================================================

echo "Creating PostgreSQL initialization script..."

cat > $INSTALL_ROOT/postgres/init_chainlit_schema.sql << 'EOSQL'
-- Chainlit Core Tables
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

-- Custom Application Tables
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

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_threads_user ON threads("userId");
CREATE INDEX IF NOT EXISTS idx_steps_thread ON steps("threadId");
CREATE INDEX IF NOT EXISTS idx_elements_thread ON elements("threadId");
CREATE INDEX IF NOT EXISTS idx_feedbacks_thread ON feedbacks("threadId");
CREATE INDEX IF NOT EXISTS idx_assistant_interactions_username ON assistant_interactions("username");
CREATE INDEX IF NOT EXISTS idx_assistant_feedback_message ON assistant_feedback("message_id");
EOSQL

chmod 644 $INSTALL_ROOT/postgres/init_chainlit_schema.sql

echo "✓ PostgreSQL init script created"
echo ""

# =============================================================================
# Create .gitkeep Files
# =============================================================================

echo "Creating .gitkeep files for empty directories..."

touch $INSTALL_ROOT/.chainlit/.gitkeep
touch $INSTALL_ROOT/feedback/.gitkeep
touch $INSTALL_ROOT/llms/.gitkeep
touch $INSTALL_ROOT/documents/specs/.gitkeep
touch $INSTALL_ROOT/documents/commands/.gitkeep
touch $INSTALL_ROOT/documents/repo/.gitkeep
touch $INSTALL_ROOT/documents/pdfs/.gitkeep
touch $INSTALL_ROOT/documents/cribl/.gitkeep
touch $INSTALL_ROOT/documents/feedback/.gitkeep

echo "✓ .gitkeep files created"
echo ""

# =============================================================================
# Display Summary
# =============================================================================

echo "================================================================================"
echo "Directory Setup Complete!"
echo "================================================================================"
echo ""
echo "Created directory structure:"
echo ""
echo "$INSTALL_ROOT/"
tree -L 2 -d $INSTALL_ROOT/ 2>/dev/null || ls -la $INSTALL_ROOT/
echo ""
echo "$INSTALL_ROOT/documents/"
tree -L 2 -d $INSTALL_ROOT/documents/ 2>/dev/null || ls -la $INSTALL_ROOT/documents/
echo ""

echo "Permissions:"
echo ""
ls -ld $INSTALL_ROOT
ls -ld $INSTALL_ROOT/.chainlit
ls -ld $INSTALL_ROOT/feedback
ls -ld $INSTALL_ROOT/llms
ls -ld $INSTALL_ROOT/documents
echo ""

if command -v getenforce &> /dev/null && [ "$(getenforce)" != "Disabled" ]; then
  echo "SELinux contexts:"
  echo ""
  ls -ldZ $INSTALL_ROOT/.chainlit
  ls -ldZ $INSTALL_ROOT/feedback
  ls -ldZ $INSTALL_ROOT/llms
  ls -ldZ $INSTALL_ROOT/documents
  echo ""
fi

echo "Disk space:"
df -h /opt
echo ""

echo "================================================================================"
echo "Next Steps"
echo "================================================================================"
echo ""
echo "1. Copy application code to $INSTALL_ROOT:"
echo "   scp -r chat_app/ user@remote:$INSTALL_ROOT/"
echo "   scp -r containers/ user@remote:$INSTALL_ROOT/"
echo "   scp -r docker_files/ user@remote:$INSTALL_ROOT/"
echo "   scp -r scripts/ user@remote:$INSTALL_ROOT/"
echo "   scp -r ingest_specs/ user@remote:$INSTALL_ROOT/"
echo "   scp requirements.txt user@remote:$INSTALL_ROOT/"
echo ""
echo "2. Copy documentation to $INSTALL_ROOT/documents:"
echo "   scp -r ingest_specs/*.conf.spec user@remote:$INSTALL_ROOT/documents/specs/"
echo "   scp -r spl_docs/* user@remote:$INSTALL_ROOT/documents/commands/"
echo ""
echo "3. Build container images:"
echo "   cd $INSTALL_ROOT"
echo "   bash docker_files/build_all.sh"
echo ""
echo "4. Start services:"
echo "   cd $INSTALL_ROOT"
echo "   bash docker_files/start_all_production.sh"
echo ""
echo "================================================================================"
