#!/bin/bash
# =============================================================================
# Quick Diagnostic Script
# =============================================================================
# Quickly diagnose what's broken in the current deployment
# =============================================================================

# Docker/Podman detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi

echo "================================================================================"
echo "System Diagnostic Report"
echo "================================================================================"
echo ""
echo "Generated: $(date)"
echo ""

# Container Status
echo "================================================================================"
echo "Container Status"
echo "================================================================================"
echo ""
$DOCKER_CMD ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "No containers found"
echo ""

# Volume Status
echo "================================================================================"
echo "Volume Status"
echo "================================================================================"
echo ""
$DOCKER_CMD volume ls --format "table {{.Name}}\t{{.Driver}}" 2>/dev/null || echo "No volumes found"
echo ""

# File Checks
echo "================================================================================"
echo "Critical Files Check"
echo "================================================================================"
echo ""

PROJECT_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

files=(
  "$PROJECT_ROOT/postgres/init_chainlit_schema.sql"
  "$PROJECT_ROOT/docker_files/start_all.sh"
  "$PROJECT_ROOT/.chainlit"
  "$PROJECT_ROOT/feedback"
  "$PROJECT_ROOT/llms"
)

for file in "${files[@]}"; do
  if [ -e "$file" ]; then
    if [ -d "$file" ]; then
      echo "✓ Directory exists: $file"
      ls -ld "$file"
    else
      echo "✓ File exists: $file"
      ls -lh "$file"
    fi
  else
    echo "✗ MISSING: $file"
  fi
done
echo ""

# PostgreSQL Check
echo "================================================================================"
echo "PostgreSQL Status"
echo "================================================================================"
echo ""

if $DOCKER_CMD ps --format '{{.Names}}' | grep -q "^chat_db_app$"; then
  echo "Container: RUNNING"
  echo ""
  echo "Database tables:"
  $DOCKER_CMD exec chat_db_app psql -U chainlit -d chainlit -c "\dt" 2>&1 || echo "✗ Failed to query tables"
  echo ""
  echo "Recent logs (last 10 lines):"
  $DOCKER_CMD logs chat_db_app 2>&1 | tail -10
else
  echo "✗ Container NOT RUNNING"
  echo ""
  echo "Last known logs:"
  $DOCKER_CMD logs chat_db_app 2>&1 | tail -20 || echo "(no logs available)"
fi
echo ""

# Ollama Check
echo "================================================================================"
echo "Ollama Status"
echo "================================================================================"
echo ""

if $DOCKER_CMD ps --format '{{.Names}}' | grep -q "^llm_api_service$"; then
  echo "Container: RUNNING"
  echo ""
  echo "Models available:"
  $DOCKER_CMD exec llm_api_service ollama list 2>&1 || echo "✗ Failed to query models"
  echo ""
  echo "Permission check:"
  $DOCKER_CMD exec llm_api_service ls -la /root/.ollama/ 2>&1 | head -10 || echo "✗ Cannot access /root/.ollama"
  echo ""
  echo "Recent errors:"
  $DOCKER_CMD logs llm_api_service 2>&1 | grep -i "error\|permission denied" | tail -10 || echo "(no errors)"
else
  echo "✗ Container NOT RUNNING"
  echo ""
  echo "Last known logs:"
  $DOCKER_CMD logs llm_api_service 2>&1 | tail -20 || echo "(no logs available)"
fi
echo ""

# ChromaDB Check
echo "================================================================================"
echo "ChromaDB Status"
echo "================================================================================"
echo ""

if $DOCKER_CMD ps --format '{{.Names}}' | grep -q "^chat_chroma_db$"; then
  echo "Container: RUNNING"
  echo ""
  echo "HTTP endpoint check:"
  if curl -s http://localhost:8001/api/v1/heartbeat &>/dev/null; then
    echo "✓ Responding on http://localhost:8001"
  else
    echo "✗ Not responding on http://localhost:8001"
  fi
  echo ""
  echo "Recent logs (last 10 lines):"
  $DOCKER_CMD logs chat_chroma_db 2>&1 | tail -10
else
  echo "✗ Container NOT RUNNING"
  echo ""
  echo "Last known logs:"
  $DOCKER_CMD logs chat_chroma_db 2>&1 | tail -20 || echo "(no logs available)"
fi
echo ""

# Chainlit App Check
echo "================================================================================"
echo "Chainlit App Status"
echo "================================================================================"
echo ""

if $DOCKER_CMD ps --format '{{.Names}}' | grep -q "^chat_ui_app$"; then
  echo "Container: RUNNING"
  echo ""
  echo "Permission errors:"
  $DOCKER_CMD logs chat_ui_app 2>&1 | grep -i "permission denied" | tail -10 || echo "✓ No permission errors"
  echo ""
  echo "Collection errors:"
  $DOCKER_CMD logs chat_ui_app 2>&1 | grep -i "collection does not exist" | tail -10 || echo "✓ No collection errors"
  echo ""
  echo "Recent logs (last 15 lines):"
  $DOCKER_CMD logs chat_ui_app 2>&1 | tail -15
else
  echo "✗ Container NOT RUNNING"
  echo ""
  echo "Last known logs:"
  $DOCKER_CMD logs chat_ui_app 2>&1 | tail -20 || echo "(no logs available)"
fi
echo ""

# SELinux Check
echo "================================================================================"
echo "SELinux Status"
echo "================================================================================"
echo ""

if command -v getenforce &> /dev/null; then
  echo "SELinux mode: $(getenforce)"
  echo ""
  echo "Recent denials:"
  if command -v ausearch &> /dev/null; then
    ausearch -m avc -ts recent 2>/dev/null | grep -i denied | tail -10 || echo "(no recent denials)"
  else
    echo "(ausearch not available)"
  fi
else
  echo "SELinux not detected"
fi
echo ""

# Summary
echo "================================================================================"
echo "Summary"
echo "================================================================================"
echo ""

issues=0

if ! $DOCKER_CMD ps --format '{{.Names}}' | grep -q "^chat_db_app$"; then
  echo "❌ PostgreSQL not running"
  ((issues++))
fi

if ! $DOCKER_CMD ps --format '{{.Names}}' | grep -q "^llm_api_service$"; then
  echo "❌ Ollama not running"
  ((issues++))
fi

if ! $DOCKER_CMD ps --format '{{.Names}}' | grep -q "^chat_chroma_db$"; then
  echo "❌ ChromaDB not running"
  ((issues++))
fi

if ! $DOCKER_CMD ps --format '{{.Names}}' | grep -q "^chat_ui_app$"; then
  echo "❌ Chainlit app not running"
  ((issues++))
fi

if $DOCKER_CMD logs chat_ui_app 2>&1 | grep -qi "permission denied"; then
  echo "❌ Permission errors in Chainlit app"
  ((issues++))
fi

if $DOCKER_CMD logs llm_api_service 2>&1 | grep -qi "permission denied"; then
  echo "❌ Permission errors in Ollama"
  ((issues++))
fi

if [ ! -f "$PROJECT_ROOT/postgres/init_chainlit_schema.sql" ]; then
  echo "❌ PostgreSQL init script missing"
  ((issues++))
fi

if [ $issues -eq 0 ]; then
  echo "✅ No critical issues detected!"
else
  echo ""
  echo "Found $issues issue(s)."
  echo ""
  echo "To fix, run:"
  echo "  bash scripts/fix_and_restart.sh"
  echo ""
  echo "Or see manual recovery guide:"
  echo "  cat docs/EMERGENCY_RECOVERY.md"
fi

echo ""
echo "================================================================================"
