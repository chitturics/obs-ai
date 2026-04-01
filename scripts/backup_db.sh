#!/bin/bash
# Database backup script for ObsAI PostgreSQL
# Usage: bash scripts/backup_db.sh [backup_dir]
#
# Creates a timestamped pg_dump backup of the Chainlit database.
# Designed to run via cron for daily automated backups.
#
# Cron example (daily at 2 AM):
#   0 2 * * * /path/to/chainlit/scripts/backup_db.sh /path/to/backups

set -euo pipefail

BACKUP_DIR="${1:-/mnt/c/tools/chainlit/backups/db}"
CONTAINER_NAME="${DB_CONTAINER:-chat_db_app}"
POSTGRES_USER="${POSTGRES_USER:-chainlit_user}"
POSTGRES_DB="${POSTGRES_DB:-chainlit_db}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
RUNTIME="${CONTAINER_RUNTIME:-podman}"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/obsai_db_${TIMESTAMP}.sql.gz"

# Ensure backup directory exists
mkdir -p "$BACKUP_DIR"

echo "[BACKUP] Starting database backup at $(date -Iseconds)"
echo "  Container: ${CONTAINER_NAME}"
echo "  Database:  ${POSTGRES_DB}"
echo "  Output:    ${BACKUP_FILE}"

# Dump and compress
if ${RUNTIME} exec "${CONTAINER_NAME}" pg_dump -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" --clean --if-exists 2>/dev/null | gzip > "${BACKUP_FILE}"; then
    SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)
    echo "[BACKUP] Success: ${BACKUP_FILE} (${SIZE})"

    # Verify backup integrity (check gzip is valid)
    if gzip -t "${BACKUP_FILE}" 2>/dev/null; then
        echo "[BACKUP] Integrity check: PASSED"
    else
        echo "[BACKUP] WARNING: Integrity check failed — backup may be corrupt"
    fi
else
    echo "[BACKUP] ERROR: pg_dump failed"
    rm -f "${BACKUP_FILE}"
    exit 1
fi

# Cleanup old backups beyond retention period
DELETED=0
if [ -d "${BACKUP_DIR}" ]; then
    while IFS= read -r old_backup; do
        rm -f "$old_backup"
        DELETED=$((DELETED + 1))
    done < <(find "${BACKUP_DIR}" -name "obsai_db_*.sql.gz" -mtime +"${RETENTION_DAYS}" -type f 2>/dev/null)
fi

if [ $DELETED -gt 0 ]; then
    echo "[BACKUP] Cleaned up ${DELETED} backup(s) older than ${RETENTION_DAYS} days"
fi

# Summary
TOTAL=$(find "${BACKUP_DIR}" -name "obsai_db_*.sql.gz" -type f 2>/dev/null | wc -l)
TOTAL_SIZE=$(du -sh "${BACKUP_DIR}" 2>/dev/null | cut -f1)
echo "[BACKUP] Complete: ${TOTAL} backups in ${BACKUP_DIR} (${TOTAL_SIZE} total)"
