"""
Shell Scripting Skill — Analyze, generate, improve, and explain shell scripts.

Provides shellcheck-style analysis, template-based generation with proper error
handling patterns, and line-by-line explanation of complex scripts.
"""
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Script Templates
# ---------------------------------------------------------------------------

SHELL_TEMPLATES: Dict[str, str] = {
    "backup": '''#!/usr/bin/env bash
set -euo pipefail
IFS=$'\\n\\t'

# =============================================================================
# Backup Script
# Usage: ./backup.sh [-d /source/dir] [-o /backup/dir] [-r 30]
# =============================================================================

SCRIPT_NAME="$(basename "$0")"
LOG_FILE="/var/log/${SCRIPT_NAME%.sh}.log"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"

# Defaults
SOURCE_DIR="/opt/app/data"
BACKUP_DIR="/backups"
RETAIN_DAYS=30

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"; }
die() { log "FATAL: $*"; exit 1; }

usage() {
    cat <<EOF
Usage: $SCRIPT_NAME [-d source_dir] [-o backup_dir] [-r retain_days] [-h]
  -d  Source directory to backup (default: $SOURCE_DIR)
  -o  Backup destination directory (default: $BACKUP_DIR)
  -r  Days to retain backups (default: $RETAIN_DAYS)
  -h  Show this help
EOF
    exit 0
}

while getopts "d:o:r:h" opt; do
    case "$opt" in
        d) SOURCE_DIR="$OPTARG" ;;
        o) BACKUP_DIR="$OPTARG" ;;
        r) RETAIN_DAYS="$OPTARG" ;;
        h) usage ;;
        *) usage ;;
    esac
done

# Validate
[[ -d "$SOURCE_DIR" ]] || die "Source directory does not exist: $SOURCE_DIR"
mkdir -p "$BACKUP_DIR" || die "Cannot create backup directory: $BACKUP_DIR"

# Cleanup handler
cleanup() {
    local exit_code=$?
    if [[ $exit_code -ne 0 ]]; then
        log "ERROR: Backup failed with exit code $exit_code"
        [[ -f "${BACKUP_DIR}/backup_${TIMESTAMP}.tar.gz" ]] && rm -f "${BACKUP_DIR}/backup_${TIMESTAMP}.tar.gz"
    fi
}
trap cleanup EXIT

# Create backup
BACKUP_FILE="${BACKUP_DIR}/backup_${TIMESTAMP}.tar.gz"
log "Starting backup: $SOURCE_DIR -> $BACKUP_FILE"
tar -czf "$BACKUP_FILE" -C "$(dirname "$SOURCE_DIR")" "$(basename "$SOURCE_DIR")" 2>>"$LOG_FILE"
log "Backup complete: $(du -sh "$BACKUP_FILE" | cut -f1)"

# Cleanup old backups
log "Cleaning backups older than $RETAIN_DAYS days..."
find "$BACKUP_DIR" -name "backup_*.tar.gz" -mtime +"$RETAIN_DAYS" -delete 2>>"$LOG_FILE"
REMAINING=$(find "$BACKUP_DIR" -name "backup_*.tar.gz" | wc -l)
log "Cleanup done. $REMAINING backup(s) remaining."
''',
    "log_rotate": '''#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Log Rotation Script
# Usage: ./log_rotate.sh [-d /var/log/app] [-m 100] [-k 7]
# =============================================================================

LOG_DIR="/var/log/app"
MAX_SIZE_MB=100
KEEP_COUNT=7

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

while getopts "d:m:k:" opt; do
    case "$opt" in
        d) LOG_DIR="$OPTARG" ;;
        m) MAX_SIZE_MB="$OPTARG" ;;
        k) KEEP_COUNT="$OPTARG" ;;
        *) echo "Usage: $0 [-d log_dir] [-m max_mb] [-k keep_count]"; exit 1 ;;
    esac
done

[[ -d "$LOG_DIR" ]] || { log "Log directory not found: $LOG_DIR"; exit 1; }

shopt -s nullglob
for logfile in "$LOG_DIR"/*.log; do
    size_mb=$(( $(stat -c%s "$logfile" 2>/dev/null || echo 0) / 1048576 ))
    if [[ $size_mb -ge $MAX_SIZE_MB ]]; then
        log "Rotating $logfile (${size_mb}MB >= ${MAX_SIZE_MB}MB)"

        # Shift existing rotated logs
        for i in $(seq $((KEEP_COUNT - 1)) -1 1); do
            [[ -f "${logfile}.${i}.gz" ]] && mv "${logfile}.${i}.gz" "${logfile}.$((i + 1)).gz"
        done

        # Compress current log
        cp "$logfile" "${logfile}.1"
        gzip "${logfile}.1"
        truncate -s 0 "$logfile"

        # Remove excess rotated logs
        for old in "${logfile}".*.gz; do
            num="${old##*.gz}"
            num="${old%.gz}"; num="${num##*.}"
            if [[ "$num" =~ ^[0-9]+$ ]] && [[ "$num" -gt "$KEEP_COUNT" ]]; then
                rm -f "$old"
            fi
        done

        log "Rotated $logfile"
    fi
done
log "Log rotation complete."
''',
    "health_check": '''#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# System Health Check Script
# Usage: ./health_check.sh [-w] [-j]
# =============================================================================

WARN_CPU=80
WARN_MEM=85
WARN_DISK=90
OUTPUT_JSON=false
HAS_WARNINGS=false

while getopts "wj" opt; do
    case "$opt" in
        w) WARN_CPU=70; WARN_MEM=75; WARN_DISK=80 ;;
        j) OUTPUT_JSON=true ;;
        *) echo "Usage: $0 [-w strict] [-j json]"; exit 1 ;;
    esac
done

warn() { HAS_WARNINGS=true; echo "  WARNING: $*"; }
ok() { echo "  OK: $*"; }

echo "=== System Health Check ==="
echo "Host: $(hostname) | Date: $(date)"
echo ""

# CPU Load
echo "--- CPU ---"
load_1=$(awk '{print $1}' /proc/loadavg)
cores=$(nproc 2>/dev/null || echo 1)
load_pct=$(awk "BEGIN{printf \"%.0f\", ($load_1/$cores)*100}")
if [[ $load_pct -ge $WARN_CPU ]]; then
    warn "CPU load ${load_pct}% (1min avg: $load_1, cores: $cores)"
else
    ok "CPU load ${load_pct}% (1min avg: $load_1, cores: $cores)"
fi

# Memory
echo "--- Memory ---"
mem_total=$(awk '/MemTotal/{print $2}' /proc/meminfo)
mem_avail=$(awk '/MemAvailable/{print $2}' /proc/meminfo)
mem_pct=$(( (mem_total - mem_avail) * 100 / mem_total ))
if [[ $mem_pct -ge $WARN_MEM ]]; then
    warn "Memory ${mem_pct}% used ($(( (mem_total - mem_avail) / 1024 ))MB / $(( mem_total / 1024 ))MB)"
else
    ok "Memory ${mem_pct}% used ($(( (mem_total - mem_avail) / 1024 ))MB / $(( mem_total / 1024 ))MB)"
fi

# Disk
echo "--- Disk ---"
while IFS= read -r line; do
    usage=$(echo "$line" | awk '{print $5}' | tr -d '%')
    mount=$(echo "$line" | awk '{print $6}')
    if [[ $usage -ge $WARN_DISK ]]; then
        warn "Disk $mount at ${usage}%"
    else
        ok "Disk $mount at ${usage}%"
    fi
done < <(df -h --output=source,size,used,avail,pcent,target -x tmpfs -x devtmpfs 2>/dev/null | tail -n +2)

# Services
echo "--- Key Services ---"
for svc in sshd nginx docker postgresql redis; do
    if systemctl is-active "$svc" &>/dev/null; then
        ok "$svc is running"
    elif systemctl list-unit-files "${svc}.service" &>/dev/null 2>&1; then
        warn "$svc is NOT running"
    fi
done

echo ""
if $HAS_WARNINGS; then
    echo "STATUS: WARNINGS DETECTED"
    exit 1
else
    echo "STATUS: ALL HEALTHY"
    exit 0
fi
''',
    "deploy": '''#!/usr/bin/env bash
set -euo pipefail
IFS=$'\\n\\t'

# =============================================================================
# Deployment Script
# Usage: ./deploy.sh -v <version> [-e staging|production] [-r]
# =============================================================================

SCRIPT_NAME="$(basename "$0")"
APP_DIR="/opt/app"
APP_USER="appuser"
VERSION=""
ENVIRONMENT="staging"
ROLLBACK=false

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$ENVIRONMENT] $*"; }
die() { log "FATAL: $*"; exit 1; }

usage() {
    cat <<EOF
Usage: $SCRIPT_NAME -v <version> [-e staging|production] [-r rollback]
  -v  Version to deploy (required)
  -e  Environment (default: staging)
  -r  Rollback to previous version
EOF
    exit 1
}

while getopts "v:e:rh" opt; do
    case "$opt" in
        v) VERSION="$OPTARG" ;;
        e) ENVIRONMENT="$OPTARG" ;;
        r) ROLLBACK=true ;;
        h) usage ;;
        *) usage ;;
    esac
done

[[ -n "$VERSION" ]] || die "Version is required (-v)"
[[ "$ENVIRONMENT" =~ ^(staging|production)$ ]] || die "Invalid environment: $ENVIRONMENT"

# Lock to prevent concurrent deploys
LOCK_FILE="/tmp/deploy.lock"
exec 200>"$LOCK_FILE"
flock -n 200 || die "Another deployment is already running"

cleanup() {
    local exit_code=$?
    flock -u 200 2>/dev/null || true
    if [[ $exit_code -ne 0 ]]; then
        log "Deployment FAILED. Check logs for details."
    fi
}
trap cleanup EXIT

# Backup current version
log "Backing up current version..."
CURRENT_VERSION=$(cat "$APP_DIR/.version" 2>/dev/null || echo "unknown")
if [[ -d "$APP_DIR/current" ]]; then
    cp -a "$APP_DIR/current" "$APP_DIR/rollback_${CURRENT_VERSION}" 2>/dev/null || true
fi

# Deploy
log "Deploying version $VERSION to $ENVIRONMENT..."
log "  Stopping service..."
sudo systemctl stop myapp || log "  Service was not running"

log "  Extracting release..."
tar -xzf "/releases/myapp-${VERSION}.tar.gz" -C "$APP_DIR/" || die "Failed to extract release"

log "  Running migrations..."
sudo -u "$APP_USER" "$APP_DIR/current/migrate.sh" || die "Migration failed"

log "  Starting service..."
sudo systemctl start myapp || die "Failed to start service"

# Health check
log "  Waiting for health check..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8080/health > /dev/null 2>&1; then
        log "  Health check passed on attempt $i"
        echo "$VERSION" > "$APP_DIR/.version"
        log "Deployment of $VERSION to $ENVIRONMENT SUCCESSFUL"
        exit 0
    fi
    sleep 2
done

die "Health check failed after 60 seconds"
''',
    "cleanup": '''#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# System Cleanup Script
# Usage: ./cleanup.sh [-n dry-run] [-v verbose]
# =============================================================================

DRY_RUN=false
VERBOSE=false
FREED=0

log() { echo "[CLEANUP] $*"; }
vlog() { $VERBOSE && log "$*" || true; }

while getopts "nv" opt; do
    case "$opt" in
        n) DRY_RUN=true; log "DRY RUN MODE" ;;
        v) VERBOSE=true ;;
        *) echo "Usage: $0 [-n dry-run] [-v verbose]"; exit 1 ;;
    esac
done

clean_dir() {
    local dir="$1" pattern="$2" age="$3"
    [[ -d "$dir" ]] || return 0
    local count
    count=$(find "$dir" -name "$pattern" -mtime +"$age" 2>/dev/null | wc -l)
    if [[ $count -gt 0 ]]; then
        local size
        size=$(find "$dir" -name "$pattern" -mtime +"$age" -exec du -cb {} + 2>/dev/null | tail -1 | cut -f1 || echo 0)
        log "Found $count files in $dir ($(( size / 1048576 ))MB)"
        if ! $DRY_RUN; then
            find "$dir" -name "$pattern" -mtime +"$age" -delete 2>/dev/null
            FREED=$(( FREED + size ))
        fi
    fi
}

log "Starting cleanup..."

# Temp files
clean_dir /tmp "*.tmp" 1
clean_dir /tmp "tmp.*" 1
clean_dir /var/tmp "*" 7

# Old logs
clean_dir /var/log "*.gz" 30
clean_dir /var/log "*.log.*" 14

# Package caches
if command -v apt-get &>/dev/null && ! $DRY_RUN; then
    log "Cleaning apt cache..."
    apt-get clean 2>/dev/null || true
fi

# Docker cleanup
if command -v docker &>/dev/null && ! $DRY_RUN; then
    log "Pruning Docker resources..."
    docker system prune -f --volumes 2>/dev/null || true
fi

# Journal logs
if command -v journalctl &>/dev/null && ! $DRY_RUN; then
    log "Vacuuming journal logs (keep 7 days)..."
    journalctl --vacuum-time=7d 2>/dev/null || true
fi

log "Cleanup complete. Freed approximately $(( FREED / 1048576 ))MB"
''',
    "service_wrapper": '''#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Service Wrapper — Run application as a managed service with restart logic
# Usage: ./service_wrapper.sh [-c config.yml] [-p pidfile]
# =============================================================================

APP_CMD="/opt/app/bin/server"
CONFIG_FILE="/etc/app/config.yml"
PID_FILE="/var/run/app.pid"
MAX_RESTARTS=5
RESTART_DELAY=5
RESTART_COUNT=0

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [SERVICE] $*"; }

while getopts "c:p:" opt; do
    case "$opt" in
        c) CONFIG_FILE="$OPTARG" ;;
        p) PID_FILE="$OPTARG" ;;
        *) echo "Usage: $0 [-c config] [-p pidfile]"; exit 1 ;;
    esac
done

shutdown_handler() {
    log "Received shutdown signal"
    if [[ -f "$PID_FILE" ]]; then
        local pid
        pid=$(cat "$PID_FILE")
        kill "$pid" 2>/dev/null || true
        wait "$pid" 2>/dev/null || true
        rm -f "$PID_FILE"
    fi
    log "Shutdown complete"
    exit 0
}
trap shutdown_handler SIGTERM SIGINT

[[ -f "$CONFIG_FILE" ]] || { log "Config not found: $CONFIG_FILE"; exit 1; }
[[ -x "$APP_CMD" ]] || { log "App not executable: $APP_CMD"; exit 1; }

while true; do
    log "Starting application (attempt $((RESTART_COUNT + 1)))..."
    $APP_CMD --config "$CONFIG_FILE" &
    APP_PID=$!
    echo "$APP_PID" > "$PID_FILE"

    wait "$APP_PID" || true
    EXIT_CODE=$?
    rm -f "$PID_FILE"

    if [[ $EXIT_CODE -eq 0 ]]; then
        log "Application exited cleanly"
        break
    fi

    RESTART_COUNT=$((RESTART_COUNT + 1))
    if [[ $RESTART_COUNT -ge $MAX_RESTARTS ]]; then
        log "Max restarts ($MAX_RESTARTS) reached. Giving up."
        exit 1
    fi

    log "Application crashed (exit $EXIT_CODE). Restarting in ${RESTART_DELAY}s..."
    sleep $RESTART_DELAY
done
''',
    "cron_job": '''#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# Cron Job Template — With locking, logging, and alerting
# Add to crontab: 0 * * * * /opt/scripts/cron_job.sh >> /var/log/cron_job.log 2>&1
# =============================================================================

SCRIPT_NAME="$(basename "$0")"
LOCK_FILE="/tmp/${SCRIPT_NAME}.lock"
LOG_FILE="/var/log/${SCRIPT_NAME%.sh}.log"
ALERT_EMAIL="${ALERT_EMAIL:-admin@example.com}"
MAX_RUNTIME=3600  # seconds

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }

# Lock to prevent overlapping runs
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    log "SKIP: Previous run still in progress"
    exit 0
fi

# Timeout protection
( sleep $MAX_RUNTIME; log "TIMEOUT: Killing long-running job"; kill $$ 2>/dev/null ) &
WATCHDOG=$!

cleanup() {
    kill "$WATCHDOG" 2>/dev/null || true
    flock -u 200 2>/dev/null || true
}
trap cleanup EXIT

log "START: $SCRIPT_NAME"
START_TIME=$(date +%s)

# ==============================
# YOUR CRON JOB LOGIC HERE
# ==============================

# Example: Database maintenance
# pg_dump mydb | gzip > /backups/mydb_$(date +%Y%m%d).sql.gz

# Example: Data sync
# rsync -avz /opt/data/ remote:/backup/data/

# ==============================

END_TIME=$(date +%s)
DURATION=$(( END_TIME - START_TIME ))
log "END: $SCRIPT_NAME (${DURATION}s)"
''',
    "file_processor": '''#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# File Processor — Process files in a directory with parallel execution
# Usage: ./file_processor.sh -d /input/dir -o /output/dir [-p 4]
# =============================================================================

INPUT_DIR=""
OUTPUT_DIR=""
PARALLEL=4
PATTERN="*.csv"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

usage() {
    echo "Usage: $0 -d <input_dir> -o <output_dir> [-p parallel] [-f pattern]"
    exit 1
}

while getopts "d:o:p:f:h" opt; do
    case "$opt" in
        d) INPUT_DIR="$OPTARG" ;;
        o) OUTPUT_DIR="$OPTARG" ;;
        p) PARALLEL="$OPTARG" ;;
        f) PATTERN="$OPTARG" ;;
        h) usage ;;
        *) usage ;;
    esac
done

[[ -n "$INPUT_DIR" && -n "$OUTPUT_DIR" ]] || usage
[[ -d "$INPUT_DIR" ]] || { log "Input dir not found: $INPUT_DIR"; exit 1; }
mkdir -p "$OUTPUT_DIR"

process_file() {
    local input="$1"
    local filename
    filename="$(basename "$input")"
    local output="${OUTPUT_DIR}/${filename%.csv}_processed.csv"

    log "Processing: $filename"

    # Example: Add header, filter, transform
    head -1 "$input" > "$output"
    tail -n +2 "$input" | \
        grep -v "^#" | \
        sort -t',' -k1,1 >> "$output"

    log "Done: $filename -> $(basename "$output")"
}

export -f process_file log OUTPUT_DIR
TOTAL=$(find "$INPUT_DIR" -name "$PATTERN" | wc -l)
log "Processing $TOTAL files with $PARALLEL parallel workers..."

find "$INPUT_DIR" -name "$PATTERN" -print0 | \
    xargs -0 -P "$PARALLEL" -I{} bash -c 'process_file "$@"' _ {}

log "All files processed."
''',
}


# ---------------------------------------------------------------------------
# Analysis patterns — Common shell script issues
# ---------------------------------------------------------------------------

SHELL_ISSUES = [
    {
        "pattern": r'\$\{?\w+\}?(?!\s*["\'])',
        "refined": r'(?<!["\'])\$\w+(?!["\w])',
        "id": "unquoted_var",
        "severity": "warning",
        "message": "Unquoted variable expansion — may cause word splitting or globbing",
        "fix": 'Wrap in double quotes: "$VAR" or "${VAR}"',
    },
    {
        "pattern": r'^#!/bin/sh',
        "id": "posix_shebang",
        "severity": "info",
        "message": "Using /bin/sh — ensure POSIX compatibility (no bashisms)",
        "fix": "Use #!/usr/bin/env bash if you need bash features",
    },
    {
        "pattern": r'\brm\s+-rf\s+["\']?\$',
        "id": "dangerous_rm",
        "severity": "error",
        "message": "rm -rf with variable — could delete everything if variable is empty",
        "fix": 'Use: rm -rf "${DIR:?Variable not set}/" or validate first',
    },
    {
        "pattern": r'\beval\b',
        "id": "eval_usage",
        "severity": "warning",
        "message": "eval usage — potential code injection vulnerability",
        "fix": "Avoid eval; use arrays or other safe alternatives",
    },
    {
        "pattern": r'\[\s+',
        "id": "single_bracket",
        "severity": "info",
        "message": "Single bracket test [ ] — consider using [[ ]] for bash",
        "fix": "Use [[ ]] for pattern matching and safer string comparison",
    },
    {
        "pattern": r'`[^`]+`',
        "id": "backtick",
        "severity": "info",
        "message": "Backtick command substitution — harder to nest and read",
        "fix": "Use $() instead: result=$(command)",
    },
    {
        "pattern": r'\bcd\b(?!.*\|\||&&)',
        "id": "unchecked_cd",
        "severity": "warning",
        "message": "cd without error check — script continues in wrong directory on failure",
        "fix": 'Use: cd "$dir" || exit 1',
    },
    {
        "pattern": r'/tmp/[a-zA-Z]',
        "id": "predictable_tmp",
        "severity": "warning",
        "message": "Predictable temp file path — potential symlink attack",
        "fix": 'Use: tmpfile=$(mktemp) or tmpdir=$(mktemp -d)',
    },
]


# ---------------------------------------------------------------------------
# Handlers
# ---------------------------------------------------------------------------

def shell_analyze_script(user_input: str, **kwargs: Any) -> Dict[str, Any]:
    """Analyze a shell script for common issues and best practices."""
    script = kwargs.get("script_content", "") or kwargs.get("content", "")
    if not script:
        code_match = re.search(r'```(?:bash|sh|shell)?\s*\n(.*?)```', user_input, re.DOTALL)
        script = code_match.group(1) if code_match else user_input

    if not script.strip():
        return {"success": False, "output": "No script content found to analyze."}

    issues: List[Dict[str, str]] = []
    lines = script.split('\n')

    # Check for shebang
    if lines and not lines[0].startswith('#!'):
        issues.append({"severity": "error", "line": 1, "message": "Missing shebang line", "fix": "Add #!/usr/bin/env bash as first line"})

    # Check for set -e / set -euo pipefail
    has_strict = any(re.search(r'set\s+-[euo]', line) for line in lines[:10])
    if not has_strict:
        issues.append({"severity": "warning", "line": 0, "message": "No strict mode (set -euo pipefail)", "fix": "Add 'set -euo pipefail' after shebang for safer execution"})

    # Check for trap/cleanup
    has_trap = any('trap ' in line for line in lines)
    if not has_trap and len(lines) > 20:
        issues.append({"severity": "info", "line": 0, "message": "No trap handler for cleanup", "fix": "Add: trap 'cleanup' EXIT for resource cleanup on exit"})

    # Line-by-line analysis
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue

        # Unquoted variables (simplified check)
        var_refs = re.findall(r'(?<!")\$\{?(\w+)\}?(?!")', stripped)
        for var in var_refs:
            if var not in ('?', '$', '!', '#', '@', '*', '0', '_', 'OPTARG', 'OPTIND'):
                # Check if it's already inside double quotes
                if not re.search(rf'"[^"]*\${{{var}}}[^"]*"', stripped) and \
                   not re.search(rf'"[^"]*\${var}[^"]*"', stripped):
                    if f'${var}' in stripped or f'${{{var}}}' in stripped:
                        # Only flag in contexts where it matters
                        if any(ctx in stripped for ctx in ('rm ', 'cp ', 'mv ', 'cat ', 'echo ', '[ ', 'test ')):
                            issues.append({"severity": "warning", "line": i, "message": f"Potentially unquoted variable ${var}", "fix": f'Use "${var}" or "${{{var}}}"'})

        # Dangerous rm
        if re.search(r'rm\s+-rf\s+["\']?\$', stripped):
            issues.append({"severity": "error", "line": i, "message": "rm -rf with variable — could be catastrophic if empty", "fix": 'Use "${DIR:?}" or validate before removing'})

        # eval
        if re.match(r'\s*eval\b', stripped):
            issues.append({"severity": "warning", "line": i, "message": "eval usage — potential code injection", "fix": "Avoid eval; use arrays or indirect expansion"})

        # Backticks
        if '`' in stripped and '$(' not in stripped:
            issues.append({"severity": "info", "line": i, "message": "Backtick command substitution", "fix": "Use $() instead for better readability and nesting"})

    # Summarize
    error_count = sum(1 for i in issues if i["severity"] == "error")
    warn_count = sum(1 for i in issues if i["severity"] == "warning")
    info_count = sum(1 for i in issues if i["severity"] == "info")

    output_lines = [f"## Shell Script Analysis\n"]
    output_lines.append(f"**{len(lines)} lines** | {error_count} errors | {warn_count} warnings | {info_count} info\n")

    if not issues:
        output_lines.append("Script looks clean! No issues detected.")
    else:
        for issue in sorted(issues, key=lambda x: {"error": 0, "warning": 1, "info": 2}[x["severity"]]):
            icon = {"error": "[ERROR]", "warning": "[WARN]", "info": "[INFO]"}[issue["severity"]]
            line_ref = f"Line {issue['line']}: " if issue.get("line") else ""
            output_lines.append(f"- {icon} {line_ref}{issue['message']}")
            output_lines.append(f"  Fix: {issue['fix']}")

    return {"success": True, "output": "\n".join(output_lines), "issues": issues}


def _get_llm():
    """Get the LLM instance for script generation."""
    try:
        import sys, os
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'chat_app'))
        from llm_utils import LLM
        return LLM
    except Exception:
        return None


def _find_best_shell_template(description: str) -> Optional[str]:
    """Find best matching shell template by keyword."""
    lower = description.lower()
    keyword_map = {
        "backup": "backup", "archive": "backup", "tar": "backup",
        "log rotat": "log_rotate", "logrotate": "log_rotate",
        "health": "health_check", "monitor": "health_check", "status": "health_check",
        "deploy": "deploy", "release": "deploy",
        "clean": "cleanup", "purge": "cleanup", "prune": "cleanup",
        "service": "service_wrapper", "daemon": "service_wrapper", "wrapper": "service_wrapper",
        "cron": "cron_job", "schedule": "cron_job", "periodic": "cron_job",
        "file process": "file_processor", "batch": "file_processor", "parallel": "file_processor",
    }
    for keyword, tpl in keyword_map.items():
        if keyword in lower:
            return tpl
    return None


def shell_generate_script(user_input: str, **kwargs: Any) -> Dict[str, Any]:
    """Generate a shell script from description using LLM, with template fallback."""
    template_name = kwargs.get("template", "")
    description = kwargs.get("description", user_input)

    if template_name and template_name != "custom" and template_name in SHELL_TEMPLATES:
        return {"success": True, "output": SHELL_TEMPLATES[template_name], "template_used": template_name}

    ref_tpl_name = _find_best_shell_template(description)
    ref_tpl = SHELL_TEMPLATES.get(ref_tpl_name or "backup", "")

    llm = _get_llm()
    if llm is not None:
        try:
            prompt = f"""You are an expert shell scripting engineer. Generate a complete, production-ready bash script based on the user's request.

Requirements:
- Output ONLY the script — no markdown fences, no explanation
- Start with #!/usr/bin/env bash
- Use set -euo pipefail
- Include proper error handling, logging, and cleanup traps
- Add meaningful comments and usage function
- Use # <-- Change: markers for values the user should customize

Reference template for style (adapt to the user's actual request):
```bash
{ref_tpl[:1500]}
```

User request: {description}

Generate the complete script now:"""
            response = llm.invoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            content = content.strip()
            if content.startswith("```"):
                lines = content.split("\n")
                if lines[-1].strip() == "```":
                    lines = lines[1:-1]
                else:
                    lines = lines[1:]
                content = "\n".join(lines)
            if not content.startswith("#!"):
                content = "#!/usr/bin/env bash\nset -euo pipefail\n\n" + content
            return {
                "success": True,
                "output": content,
                "template_used": f"llm_generated (ref: {ref_tpl_name or 'none'})",
                "note": "Generated by LLM. Review and customize before use.",
            }
        except Exception as exc:
            logger.warning("LLM generation failed for shell script: %s", exc)

    if ref_tpl_name:
        return {"success": True, "output": SHELL_TEMPLATES[ref_tpl_name], "template_used": ref_tpl_name, "note": "LLM unavailable. Returned matching template."}

    return {"success": True, "output": SHELL_TEMPLATES.get("backup", "#!/usr/bin/env bash\necho 'TODO'"), "template_used": "backup", "note": "LLM unavailable. Returned backup template."}


def shell_improve_script(user_input: str, **kwargs: Any) -> Dict[str, Any]:
    """Suggest improvements for a shell script."""
    script = kwargs.get("script_content", "") or kwargs.get("content", "")
    if not script:
        code_match = re.search(r'```(?:bash|sh|shell)?\s*\n(.*?)```', user_input, re.DOTALL)
        script = code_match.group(1) if code_match else ""

    if not script.strip():
        return {"success": False, "output": "No script content found to improve."}

    suggestions: List[str] = []

    if not re.search(r'set\s+-[euo]', script):
        suggestions.append("**Add strict mode:** `set -euo pipefail` after shebang for safer execution")

    if 'trap ' not in script and len(script.split('\n')) > 15:
        suggestions.append("**Add cleanup trap:** `trap 'cleanup_func' EXIT` to handle errors gracefully")

    if 'usage()' not in script and 'getopts' not in script and len(script.split('\n')) > 20:
        suggestions.append("**Add argument parsing:** Use `getopts` with a `usage()` function for CLI interface")

    if 'log()' not in script and 'logger ' not in script:
        suggestions.append("**Add logging function:** `log() { echo \"[$(date)] $*\"; }` for timestamped output")

    if re.search(r'`[^`]+`', script):
        suggestions.append("**Replace backticks:** Use `$()` instead of backticks for command substitution")

    if re.search(r'\[\s+', script) and '[[' not in script:
        suggestions.append("**Use double brackets:** `[[ ]]` instead of `[ ]` for safer bash conditionals")

    if not suggestions:
        return {"success": True, "output": "Script already follows good practices. No major improvements needed."}

    output = "## Suggested Improvements\n\n" + "\n".join(f"- {s}" for s in suggestions)
    return {"success": True, "output": output, "suggestion_count": len(suggestions)}


def shell_explain_script(user_input: str, **kwargs: Any) -> Dict[str, Any]:
    """Explain a shell script line by line."""
    script = kwargs.get("script_content", "") or kwargs.get("content", "")
    if not script:
        code_match = re.search(r'```(?:bash|sh|shell)?\s*\n(.*?)```', user_input, re.DOTALL)
        script = code_match.group(1) if code_match else user_input

    if not script.strip():
        return {"success": False, "output": "No script content found to explain."}

    lines = script.strip().split('\n')
    explanations: List[str] = ["## Script Explanation\n"]

    EXPLANATIONS_MAP = {
        r'^#!/': "**Shebang** — specifies the interpreter for this script",
        r'^set\s+-e': "**Strict mode** — exit immediately if any command fails (`-e`), treat unset vars as errors (`-u`), fail on pipe errors (`pipefail`)",
        r'^IFS=': "**Input Field Separator** — controls word splitting; `$'\\n\\t'` = only split on newlines and tabs (safer than default spaces)",
        r'^\w+\(\)': "**Function definition** — reusable block of code",
        r'^trap\s': "**Trap handler** — executes specified function on signal (EXIT, SIGTERM, etc.)",
        r'^while\s+getopts': "**Argument parser** — processes command-line flags (e.g., -v, -d DIR)",
        r'^case\s': "**Case statement** — pattern matching switch (like switch/case in other languages)",
        r'^\s*for\s': "**For loop** — iterates over list of items",
        r'^\s*while\s': "**While loop** — repeats while condition is true",
        r'^\s*if\s': "**Conditional** — branches execution based on condition",
        r'export\s': "**Export** — makes variable available to child processes",
        r'^\s*local\s': "**Local variable** — scoped to current function only",
        r'readonly\s': "**Readonly** — constant that cannot be changed",
    }

    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith('#') and i > 1:
            explanations.append(f"**Line {i}:** Comment: `{stripped}`")
            continue

        explained = False
        for pattern, explanation in EXPLANATIONS_MAP.items():
            if re.search(pattern, stripped):
                explanations.append(f"**Line {i}:** `{stripped[:80]}` — {explanation}")
                explained = True
                break

        if not explained and stripped and not stripped.startswith('#'):
            explanations.append(f"**Line {i}:** `{stripped[:80]}`")

    return {"success": True, "output": "\n".join(explanations[:100])}  # Cap at 100 lines
