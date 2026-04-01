#!/bin/bash
# =====================================================================
# AUTOMATED BACKUP SCRIPT FOR SPLUNK ASSISTANT
# =====================================================================
# Backs up: PostgreSQL, ChromaDB, Ollama models, configuration files
#
# Usage:
#   ./backup_all.sh [--full]
#
# Options:
#   --full    Perform full backup (includes all Ollama models)
#
# Schedule with cron:
#   0 2 * * * /app/scripts/backup_all.sh >> /var/log/backup.log 2>&1

set -euo pipefail

# =====================================================================
# CONFIGURATION
# =====================================================================

BACKUP_ROOT="${BACKUP_ROOT:-/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="$BACKUP_ROOT/$TIMESTAMP"
RETENTION_DAYS=${RETENTION_DAYS:-30}
FULL_BACKUP=false

# Parse arguments
for arg in "$@"; do
    case $arg in
        --full)
            FULL_BACKUP=true
            shift
            ;;
    esac
done

# =====================================================================
# LOGGING
# =====================================================================

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

log_error() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ERROR: $*" >&2
}

# =====================================================================
# BACKUP FUNCTIONS
# =====================================================================

backup_postgres() {
    log "Backing up PostgreSQL database..."
    local db_name="${POSTGRES_DB:-chainlit}"
    local db_user="${POSTGRES_USER:-chainlit}"
    local output="$BACKUP_DIR/postgres.sql.gz"

    if command -v docker &>/dev/null; then
        docker exec chat_db_app pg_dump -U "$db_user" "$db_name" | gzip > "$output"
    elif command -v podman &>/dev/null; then
        podman exec chat_db_app pg_dump -U "$db_user" "$db_name" | gzip > "$output"
    else
        log_error "Neither docker nor podman found"
        return 1
    fi

    local size=$(du -h "$output" | cut -f1)
    log "✓ PostgreSQL backup complete: $output ($size)"
}

backup_chroma() {
    log "Backing up ChromaDB vector stores..."

    # Primary collection
    if command -v docker &>/dev/null; then
        docker cp chat_chroma_db:/data "$BACKUP_DIR/chroma_data"
    elif command -v podman &>/dev/null; then
        podman cp chat_chroma_db:/data "$BACKUP_DIR/chroma_data"
    fi

    # Compress
    tar -czf "$BACKUP_DIR/chroma_data.tar.gz" -C "$BACKUP_DIR" chroma_data
    rm -rf "$BACKUP_DIR/chroma_data"

    local size=$(du -h "$BACKUP_DIR/chroma_data.tar.gz" | cut -f1)
    log "✓ ChromaDB backup complete: $BACKUP_DIR/chroma_data.tar.gz ($size)"
}

backup_ollama_models() {
    log "Backing up Ollama models..."

    if [ "$FULL_BACKUP" = true ]; then
        log "  Full backup mode: including all models"
        if command -v docker &>/dev/null; then
            docker exec llm_api_service tar -czf - /root/.ollama > "$BACKUP_DIR/ollama_models_full.tar.gz"
        elif command -v podman &>/dev/null; then
            podman exec llm_api_service tar -czf - /root/.ollama > "$BACKUP_DIR/ollama_models_full.tar.gz"
        fi
        local size=$(du -h "$BACKUP_DIR/ollama_models_full.tar.gz" | cut -f1)
        log "✓ Ollama full backup complete: $size"
    else
        log "  Incremental backup: metadata only"
        # Backup only model manifests (not the large blobs)
        if command -v docker &>/dev/null; then
            docker exec llm_api_service tar -czf - /root/.ollama/models/manifests > "$BACKUP_DIR/ollama_manifests.tar.gz"
        elif command -v podman &>/dev/null; then
            podman exec llm_api_service tar -czf - /root/.ollama/models/manifests > "$BACKUP_DIR/ollama_manifests.tar.gz"
        fi
        local size=$(du -h "$BACKUP_DIR/ollama_manifests.tar.gz" | cut -f1)
        log "✓ Ollama manifest backup complete: $size"
    fi
}

backup_config_files() {
    log "Backing up configuration files..."

    local app_root="$(dirname "$(dirname "$(readlink -f "$0")")")"
    mkdir -p "$BACKUP_DIR/config"

    # Copy important config files
    cp "$app_root/.env.template" "$BACKUP_DIR/config/" 2>/dev/null || true
    cp "$app_root/docker-compose.yml" "$BACKUP_DIR/config/"
    cp "$app_root/nginx-proxy.conf" "$BACKUP_DIR/config/" 2>/dev/null || true
    cp "$app_root/chat_app/chainlit.toml" "$BACKUP_DIR/config/"
    cp "$app_root/context.json" "$BACKUP_DIR/config/" 2>/dev/null || true

    # DO NOT copy .env (contains secrets)
    # DO NOT copy certs (can be regenerated)

    tar -czf "$BACKUP_DIR/config.tar.gz" -C "$BACKUP_DIR" config
    rm -rf "$BACKUP_DIR/config"

    log "✓ Configuration backup complete"
}

backup_feedback() {
    log "Backing up user feedback..."

    local app_root="$(dirname "$(dirname "$(readlink -f "$0")")")"
    local feedback_dir="$app_root/public/feedback"

    if [ -d "$feedback_dir" ] && [ "$(ls -A "$feedback_dir" 2>/dev/null)" ]; then
        tar -czf "$BACKUP_DIR/feedback.tar.gz" -C "$app_root/public" feedback
        local size=$(du -h "$BACKUP_DIR/feedback.tar.gz" | cut -f1)
        log "✓ Feedback backup complete: $size"
    else
        log "  No feedback files to backup"
    fi
}

create_manifest() {
    log "Creating backup manifest..."

    cat > "$BACKUP_DIR/MANIFEST.txt" <<EOF
Splunk Assistant Backup Manifest
=================================
Timestamp: $TIMESTAMP
Backup Type: $([ "$FULL_BACKUP" = true ] && echo "FULL" || echo "INCREMENTAL")
Created: $(date +'%Y-%m-%d %H:%M:%S %Z')

Contents:
---------
EOF

    # List all files with sizes
    find "$BACKUP_DIR" -type f -exec ls -lh {} \; | awk '{print $9, "(" $5 ")"}' >> "$BACKUP_DIR/MANIFEST.txt"

    # Calculate total size
    local total_size=$(du -sh "$BACKUP_DIR" | cut -f1)
    echo "" >> "$BACKUP_DIR/MANIFEST.txt"
    echo "Total Size: $total_size" >> "$BACKUP_DIR/MANIFEST.txt"

    log "✓ Manifest created"
}

cleanup_old_backups() {
    log "Cleaning up backups older than $RETENTION_DAYS days..."

    local deleted_count=0
    while IFS= read -r -d '' old_backup; do
        log "  Deleting: $(basename "$old_backup")"
        rm -rf "$old_backup"
        ((deleted_count++))
    done < <(find "$BACKUP_ROOT" -maxdepth 1 -type d -mtime +$RETENTION_DAYS -print0)

    if [ $deleted_count -gt 0 ]; then
        log "✓ Deleted $deleted_count old backup(s)"
    else
        log "  No old backups to delete"
    fi
}

# =====================================================================
# MAIN BACKUP WORKFLOW
# =====================================================================

main() {
    log "=========================================="
    log "Starting backup: $TIMESTAMP"
    log "=========================================="

    # Create backup directory
    mkdir -p "$BACKUP_DIR"

    # Run backups
    backup_postgres || log_error "PostgreSQL backup failed"
    backup_chroma || log_error "ChromaDB backup failed"
    backup_ollama_models || log_error "Ollama backup failed"
    backup_config_files || log_error "Config backup failed"
    backup_feedback || log_error "Feedback backup failed"

    # Create manifest
    create_manifest

    # Cleanup old backups
    cleanup_old_backups

    # Final summary
    local total_size=$(du -sh "$BACKUP_DIR" | cut -f1)
    log "=========================================="
    log "Backup complete: $BACKUP_DIR"
    log "Total size: $total_size"
    log "=========================================="

    # Optional: Upload to cloud storage
    # Uncomment and configure for your environment
    # upload_to_cloud_storage "$BACKUP_DIR"
}

# =====================================================================
# CLOUD STORAGE UPLOAD (OPTIONAL)
# =====================================================================

upload_to_cloud_storage() {
    local backup_path="$1"

    # Example: AWS S3
    # if command -v aws &>/dev/null; then
    #     log "Uploading to S3..."
    #     aws s3 sync "$backup_path" "s3://your-backup-bucket/chainlit/$TIMESTAMP/" \
    #         --storage-class GLACIER
    #     log "✓ Upload complete"
    # fi

    # Example: Azure Blob Storage
    # if command -v az &>/dev/null; then
    #     log "Uploading to Azure Blob Storage..."
    #     az storage blob upload-batch \
    #         --account-name your-storage-account \
    #         --destination chainlit-backups \
    #         --source "$backup_path"
    #     log "✓ Upload complete"
    # fi

    log "  Cloud upload not configured (edit upload_to_cloud_storage function)"
}

# =====================================================================
# EXECUTE
# =====================================================================

main
