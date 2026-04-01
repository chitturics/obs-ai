#!/bin/bash
# =====================================================================
# RESTORE SCRIPT FOR SPLUNK ASSISTANT
# =====================================================================
# Restores: PostgreSQL, ChromaDB, configuration files, feedback data
#
# Usage:
#   ./restore_from_backup.sh <backup_directory>
#
# Examples:
#   ./restore_from_backup.sh /backups/20260215_020000
#   ./restore_from_backup.sh /backups/latest
#
# WARNING: This will overwrite current data!

set -euo pipefail

# =====================================================================
# CONFIGURATION
# =====================================================================

BACKUP_DIR="${1:-}"
SKIP_CONFIRM="${SKIP_CONFIRM:-false}"

if [ -z "$BACKUP_DIR" ]; then
    echo "Usage: $0 <backup_directory>"
    echo ""
    echo "Available backups:"
    BACKUP_ROOT="${BACKUP_ROOT:-/backups}"
    if [ -d "$BACKUP_ROOT" ]; then
        ls -dt "$BACKUP_ROOT"/*/ 2>/dev/null | head -10 | while read dir; do
            echo "  $(basename "$dir")"
        done
    else
        echo "  No backup directory found at $BACKUP_ROOT"
    fi
    exit 1
fi

if [ ! -d "$BACKUP_DIR" ]; then
    echo "ERROR: Backup directory not found: $BACKUP_DIR"
    exit 1
fi

# =====================================================================
# LOGGING
# =====================================================================

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

log_error() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
}

# Docker/Podman detection
if command -v podman &> /dev/null; then
    DOCKER_CMD="podman"
else
    DOCKER_CMD="docker"
fi

# =====================================================================
# CONFIRMATION
# =====================================================================

if [ "$SKIP_CONFIRM" != "true" ]; then
    echo "=========================================="
    echo "RESTORE FROM BACKUP"
    echo "=========================================="
    echo ""
    echo "Backup source: $BACKUP_DIR"
    echo ""

    if [ -f "$BACKUP_DIR/MANIFEST.txt" ]; then
        echo "Backup manifest:"
        cat "$BACKUP_DIR/MANIFEST.txt"
        echo ""
    fi

    echo "WARNING: This will OVERWRITE current data!"
    echo ""
    read -p "Are you sure you want to proceed? (yes/no): " confirm
    if [ "$confirm" != "yes" ]; then
        echo "Restore cancelled."
        exit 0
    fi
fi

# =====================================================================
# RESTORE FUNCTIONS
# =====================================================================

restore_postgres() {
    local dump_file="$BACKUP_DIR/postgres.sql.gz"
    if [ ! -f "$dump_file" ]; then
        log "No PostgreSQL backup found, skipping"
        return 0
    fi

    log "Restoring PostgreSQL database..."
    local db_name="${POSTGRES_DB:-chainlit}"
    local db_user="${POSTGRES_USER:-chainlit}"

    # Drop and recreate database
    $DOCKER_CMD exec chat_db_app psql -U "$db_user" -d postgres \
        -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$db_name' AND pid <> pg_backend_pid();" 2>/dev/null || true
    $DOCKER_CMD exec chat_db_app psql -U "$db_user" -d postgres \
        -c "DROP DATABASE IF EXISTS $db_name;" 2>/dev/null || true
    $DOCKER_CMD exec chat_db_app psql -U "$db_user" -d postgres \
        -c "CREATE DATABASE $db_name OWNER $db_user;" 2>/dev/null || true

    # Restore
    gunzip -c "$dump_file" | $DOCKER_CMD exec -i chat_db_app psql -U "$db_user" "$db_name"

    log "PostgreSQL restore complete"
}

restore_chroma() {
    local archive="$BACKUP_DIR/chroma_data.tar.gz"
    if [ ! -f "$archive" ]; then
        log "No ChromaDB backup found, skipping"
        return 0
    fi

    log "Restoring ChromaDB vector stores..."

    # Stop ChromaDB to safely replace data
    $DOCKER_CMD stop chat_chroma_db 2>/dev/null || true

    # Extract to temporary location
    local tmp_dir=$(mktemp -d)
    tar -xzf "$archive" -C "$tmp_dir"

    # Copy data back into container volume
    $DOCKER_CMD start chat_chroma_db
    sleep 3
    $DOCKER_CMD cp "$tmp_dir/chroma_data/." chat_chroma_db:/data/

    # Cleanup
    rm -rf "$tmp_dir"

    # Restart ChromaDB
    $DOCKER_CMD restart chat_chroma_db
    sleep 5

    log "ChromaDB restore complete"
}

restore_config() {
    local archive="$BACKUP_DIR/config.tar.gz"
    if [ ! -f "$archive" ]; then
        log "No configuration backup found, skipping"
        return 0
    fi

    log "Restoring configuration files..."

    local app_root="$(dirname "$(dirname "$(readlink -f "$0")")")"
    local tmp_dir=$(mktemp -d)
    tar -xzf "$archive" -C "$tmp_dir"

    # Restore specific config files (don't blindly overwrite)
    for file in docker-compose.yml chainlit.toml context.json; do
        if [ -f "$tmp_dir/config/$file" ]; then
            local target
            case "$file" in
                chainlit.toml) target="$app_root/chat_app/chainlit.toml" ;;
                *) target="$app_root/$file" ;;
            esac
            cp "$tmp_dir/config/$file" "$target"
            log "  Restored: $file"
        fi
    done

    rm -rf "$tmp_dir"
    log "Configuration restore complete"
}

restore_feedback() {
    local archive="$BACKUP_DIR/feedback.tar.gz"
    if [ ! -f "$archive" ]; then
        log "No feedback backup found, skipping"
        return 0
    fi

    log "Restoring feedback data..."
    local app_root="$(dirname "$(dirname "$(readlink -f "$0")")")"
    tar -xzf "$archive" -C "$app_root/public/"

    log "Feedback restore complete"
}

# =====================================================================
# MAIN RESTORE WORKFLOW
# =====================================================================

main() {
    log "=========================================="
    log "Starting restore from: $BACKUP_DIR"
    log "=========================================="

    restore_postgres || log_error "PostgreSQL restore failed"
    restore_chroma || log_error "ChromaDB restore failed"
    restore_config || log_error "Configuration restore failed"
    restore_feedback || log_error "Feedback restore failed"

    log "=========================================="
    log "Restore complete!"
    log "=========================================="
    log ""
    log "IMPORTANT: Restart the application to apply changes:"
    log "  bash docker_files/stop_all.sh && bash docker_files/start_all.sh"
}

main
