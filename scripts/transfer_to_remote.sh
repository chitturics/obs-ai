#!/bin/bash
# =============================================================================
# Transfer Files to Remote Production Server
# =============================================================================
# Transfers all necessary files from local machine to remote server
# Run this from your LOCAL machine (Windows/WSL/Linux)
# =============================================================================

set -e

# =============================================================================
# Configuration
# =============================================================================

echo "================================================================================"
echo "Transfer Files to Remote Production Server"
echo "================================================================================"
echo ""

# Check if remote details are provided
if [ -z "$1" ] || [ -z "$2" ]; then
  echo "Usage: $0 <remote-user> <remote-host> [remote-base-path]"
  echo ""
  echo "Example:"
  echo "  $0 admin 192.168.1.100"
  echo "  $0 admin 192.168.1.100 /opt/obsai/chatbot"
  echo ""
  exit 1
fi

REMOTE_USER="$1"
REMOTE_HOST="$2"
REMOTE_BASE="${3:-/opt/obsai/chatbot}"
REMOTE_DOCS="$REMOTE_BASE/documents"

echo "Remote user:     $REMOTE_USER"
echo "Remote host:     $REMOTE_HOST"
echo "Remote base:     $REMOTE_BASE"
echo "Remote docs:     $REMOTE_DOCS"
echo ""

# Verify we're in the right directory
if [ ! -f "requirements.txt" ] || [ ! -d "chat_app" ]; then
  echo "✗ Not in project root directory"
  echo "  Please run this script from the root of the chainlit project"
  exit 1
fi

# Test SSH connection
echo "Testing SSH connection..."
if ! ssh -o ConnectTimeout=5 "$REMOTE_USER@$REMOTE_HOST" "echo '✓ SSH connection successful'" 2>/dev/null; then
  echo "✗ Cannot connect to $REMOTE_USER@$REMOTE_HOST"
  echo "  Please check SSH access and credentials"
  exit 1
fi
echo ""

# =============================================================================
# Step 1: Setup Script
# =============================================================================

echo "================================================================================"
echo "Step 1: Transfer and Run Setup Script"
echo "================================================================================"
echo ""

echo "Transferring setup script..."
scp scripts/setup_production_directories.sh "$REMOTE_USER@$REMOTE_HOST:/tmp/"

echo "Running setup script on remote (requires sudo)..."
ssh -t "$REMOTE_USER@$REMOTE_HOST" "sudo bash /tmp/setup_production_directories.sh"

echo "✓ Setup complete"
echo ""

# =============================================================================
# Step 2: Transfer Application Code
# =============================================================================

echo "================================================================================"
echo "Step 2: Transfer Application Code"
echo "================================================================================"
echo ""

# Create temporary directory for transfer
TEMP_DIR=$(mktemp -d)
echo "Creating transfer bundle in $TEMP_DIR..."

# Copy files to temp directory
cp -r chat_app "$TEMP_DIR/"
cp -r containers "$TEMP_DIR/"
cp -r docker_files "$TEMP_DIR/"
cp -r scripts "$TEMP_DIR/"
cp -r ingest_specs "$TEMP_DIR/"
cp -r docs "$TEMP_DIR/" 2>/dev/null || mkdir "$TEMP_DIR/docs"
cp -r postgres "$TEMP_DIR/"
cp requirements.txt "$TEMP_DIR/"
cp -r metadata "$TEMP_DIR/" 2>/dev/null || true

echo "Transferring application code..."
rsync -avz --progress "$TEMP_DIR/" "$REMOTE_USER@$REMOTE_HOST:$REMOTE_BASE/"

# Cleanup
rm -rf "$TEMP_DIR"

echo "✓ Application code transferred"
echo ""

# =============================================================================
# Step 3: Transfer Documentation
# =============================================================================

echo "================================================================================"
echo "Step 3: Transfer Documentation"
echo "================================================================================"
echo ""

# Create temp directory for docs
DOC_TEMP=$(mktemp -d)
mkdir -p "$DOC_TEMP/specs"
mkdir -p "$DOC_TEMP/commands"
mkdir -p "$DOC_TEMP/advanced"

echo "Collecting Splunk documentation..."

# Copy .spec files
if ls ingest_specs/*.spec 1> /dev/null 2>&1; then
  cp ingest_specs/*.spec "$DOC_TEMP/specs/"
  echo "  ✓ Found $(ls ingest_specs/*.spec | wc -l) .spec files"
else
  echo "  ⚠️  No .spec files found in ingest_specs/"
fi

# Copy .conf files (if any)
if ls ingest_specs/*.conf 1> /dev/null 2>&1; then
  cp ingest_specs/*.conf "$DOC_TEMP/specs/"
  echo "  ✓ Found $(ls ingest_specs/*.conf | wc -l) .conf files"
fi

# Copy SPL docs (if exists)
if [ -d "spl_docs" ]; then
  cp -r spl_docs/* "$DOC_TEMP/commands/" 2>/dev/null || true
  echo "  ✓ Copied SPL documentation"
fi

# Copy advanced docs (if exists)
if [ -d "splunk_advanced_docs" ]; then
  cp -r splunk_advanced_docs/* "$DOC_TEMP/advanced/" 2>/dev/null || true
  echo "  ✓ Copied advanced documentation"
fi

echo ""
echo "Transferring documentation to remote..."
ssh "$REMOTE_USER@$REMOTE_HOST" "sudo mkdir -p $REMOTE_DOCS/{specs,commands,advanced}"
rsync -avz --progress "$DOC_TEMP/" "$REMOTE_USER@$REMOTE_HOST:/tmp/docs_transfer/"
ssh "$REMOTE_USER@$REMOTE_HOST" "sudo cp -r /tmp/docs_transfer/* $REMOTE_DOCS/ && sudo rm -rf /tmp/docs_transfer && sudo chmod -R 755 $REMOTE_DOCS"

# Cleanup
rm -rf "$DOC_TEMP"

echo "✓ Documentation transferred"
echo ""

# =============================================================================
# Step 4: Set Permissions
# =============================================================================

echo "================================================================================"
echo "Step 4: Fix Permissions on Remote"
echo "================================================================================"
echo ""

ssh "$REMOTE_USER@$REMOTE_HOST" << 'EOSSH'
sudo chmod +x $REMOTE_BASE/scripts/*.sh
sudo chmod +x $REMOTE_BASE/docker_files/*.sh
sudo chmod -R 755 $REMOTE_BASE/chat_app
sudo chmod -R 777 $REMOTE_BASE/.chainlit
sudo chmod -R 777 $REMOTE_BASE/feedback
sudo chmod -R 777 $REMOTE_BASE/llms
sudo chmod -R 755 /opt/obsai/documents
EOSSH

echo "✓ Permissions fixed"
echo ""

# =============================================================================
# Summary
# =============================================================================

echo "================================================================================"
echo "Transfer Complete!"
echo "================================================================================"
echo ""
echo "Files transferred to: $REMOTE_USER@$REMOTE_HOST:$REMOTE_BASE"
echo ""
echo "Next steps (on remote server):"
echo ""
echo "  1. SSH to remote:"
echo "     ssh $REMOTE_USER@$REMOTE_HOST"
echo ""
echo "  2. Build container images:"
echo "     cd $REMOTE_BASE"
echo "     bash docker_files/build_all.sh"
echo ""
echo "  3. Start services:"
echo "     bash docker_files/start_all_production.sh"
echo ""
echo "  4. Access UI:"
echo "     http://$REMOTE_HOST:8000"
echo ""
echo "Verify transfer:"
echo ""
echo "  ssh $REMOTE_USER@$REMOTE_HOST 'ls -la $REMOTE_BASE'"
echo "  ssh $REMOTE_USER@$REMOTE_HOST 'ls -la $REMOTE_DOCS/specs | head -10'"
echo ""
echo "================================================================================"
