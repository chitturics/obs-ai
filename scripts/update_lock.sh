#!/usr/bin/env bash
# =============================================================================
# update_lock.sh — Generate requirements.lock from the running container
#
# Captures exact package versions from the running chat_ui_app container
# and saves them to containers/app/requirements.lock for reproducible builds.
#
# Usage:
#   bash scripts/update_lock.sh
# =============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCK_FILE="$PROJECT_ROOT/containers/app/requirements.lock"
CONTAINER_NAME="${CONTAINER_NAME:-chat_ui_app}"

# Auto-detect container runtime
if command -v podman &>/dev/null; then
    RUNTIME="podman"
elif command -v docker &>/dev/null; then
    RUNTIME="docker"
else
    echo "ERROR: Neither podman nor docker found in PATH." >&2
    exit 1
fi

# Verify the container is running
if ! $RUNTIME ps --format '{{.Names}}' 2>/dev/null | grep -q "^${CONTAINER_NAME}$"; then
    echo "ERROR: Container '$CONTAINER_NAME' is not running." >&2
    echo "Start the application first: bash docker_files/start_all.sh" >&2
    exit 1
fi

echo "Capturing pip freeze from container '$CONTAINER_NAME' using $RUNTIME..."

# Generate the lock file with a header
{
    echo "# ============================================================================="
    echo "# requirements.lock — Auto-generated pinned dependencies"
    echo "# Generated: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
    echo "# Source: $RUNTIME exec $CONTAINER_NAME pip freeze"
    echo "# Container: $CONTAINER_NAME"
    echo "# ============================================================================="
    echo "# To regenerate: bash scripts/update_lock.sh"
    echo "# To use in build: podman build --build-arg USE_LOCK=true ..."
    echo "# ============================================================================="
    echo ""
    $RUNTIME exec "$CONTAINER_NAME" pip freeze 2>/dev/null
} > "$LOCK_FILE"

LINE_COUNT=$(grep -c -v '^\s*#\|^\s*$' "$LOCK_FILE" || true)
echo "Wrote $LOCK_FILE ($LINE_COUNT packages)"
echo "Done. Use '--build-arg USE_LOCK=true' in your next build to use pinned versions."
