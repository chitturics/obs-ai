#!/bin/bash
# =====================================================================
# SECURITY SCANNING FOR SPLUNK ASSISTANT
# =====================================================================
# Scans Python dependencies and Docker images for vulnerabilities.
#
# Tools used:
#   - pip-audit: Python dependency vulnerability scanning
#   - bandit: Python static security analysis
#   - trivy: Docker container scanning (if installed)
#
# Usage:
#   ./security_scan.sh [--fix] [--report <output_file>]

set -euo pipefail

cd "$(dirname "$0")/.."

REPORT_FILE=""
AUTO_FIX=false
EXIT_CODE=0

for arg in "$@"; do
    case $arg in
        --fix)
            AUTO_FIX=true
            ;;
        --report)
            REPORT_FILE="$2"
            shift
            ;;
    esac
    shift 2>/dev/null || true
done

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*"
}

REPORT=""
append_report() {
    REPORT+="$1"$'\n'
}

append_report "# Security Scan Report"
append_report "Date: $(date +'%Y-%m-%d %H:%M:%S')"
append_report ""

# =====================================================================
# 1. Python Dependency Audit
# =====================================================================

log "=========================================="
log "Python Dependency Vulnerability Scan"
log "=========================================="

append_report "## Python Dependencies"
append_report ""

# Check pip-audit
if command -v pip-audit &>/dev/null; then
    log "Running pip-audit on app requirements..."

    for req_file in containers/app/requirements.txt containers/search_opt/requirements.txt containers/ingest/requirements.txt; do
        if [ -f "$req_file" ]; then
            log "  Scanning: $req_file"
            append_report "### $req_file"

            if pip-audit -r "$req_file" --desc 2>&1; then
                append_report "No vulnerabilities found."
            else
                EXIT_CODE=1
                append_report "Vulnerabilities detected! See output above."

                if [ "$AUTO_FIX" = true ]; then
                    log "  Attempting auto-fix..."
                    pip-audit -r "$req_file" --fix --desc 2>&1 || true
                fi
            fi
            append_report ""
        fi
    done
else
    log "pip-audit not found. Install with: pip install pip-audit"
    append_report "pip-audit not installed. Skipped."
    append_report ""
fi

# =====================================================================
# 2. Python Static Security Analysis
# =====================================================================

log ""
log "=========================================="
log "Python Static Security Analysis (Bandit)"
log "=========================================="

append_report "## Static Security Analysis"
append_report ""

if command -v bandit &>/dev/null; then
    log "Running bandit on chat_app/..."

    BANDIT_OUTPUT=$(bandit -r chat_app/ -ll -ii --format txt 2>&1) || true
    echo "$BANDIT_OUTPUT"

    if echo "$BANDIT_OUTPUT" | grep -q "No issues identified"; then
        append_report "No security issues found in chat_app/."
    else
        # Count issues by severity
        HIGH_COUNT=$(echo "$BANDIT_OUTPUT" | grep -c "Severity: High" 2>/dev/null || echo "0")
        MED_COUNT=$(echo "$BANDIT_OUTPUT" | grep -c "Severity: Medium" 2>/dev/null || echo "0")

        append_report "Issues found:"
        append_report "- High severity: $HIGH_COUNT"
        append_report "- Medium severity: $MED_COUNT"

        if [ "$HIGH_COUNT" -gt 0 ]; then
            EXIT_CODE=1
        fi
    fi
    append_report ""
else
    log "bandit not found. Install with: pip install bandit"
    append_report "bandit not installed. Skipped."
    append_report ""
fi

# =====================================================================
# 3. Docker Image Scanning
# =====================================================================

log ""
log "=========================================="
log "Docker Image Security Scan"
log "=========================================="

append_report "## Docker Images"
append_report ""

if command -v trivy &>/dev/null; then
    IMAGES=("chainlit-app:latest" "chainlit-search-opt:latest" "chainlit-chromadb:latest" "chainlit-postgres:latest")

    for image in "${IMAGES[@]}"; do
        log "Scanning: $image"
        append_report "### $image"

        if docker image inspect "$image" &>/dev/null; then
            TRIVY_OUTPUT=$(trivy image --severity HIGH,CRITICAL "$image" 2>&1) || true
            echo "$TRIVY_OUTPUT"

            if echo "$TRIVY_OUTPUT" | grep -q "Total: 0"; then
                append_report "No high/critical vulnerabilities."
            else
                VULN_COUNT=$(echo "$TRIVY_OUTPUT" | grep -oP 'Total: \K\d+' 2>/dev/null || echo "unknown")
                append_report "Vulnerabilities found: $VULN_COUNT"
                EXIT_CODE=1
            fi
        else
            append_report "Image not found locally. Build first."
        fi
        append_report ""
    done
else
    log "trivy not found. Install from: https://aquasecurity.github.io/trivy/"
    append_report "trivy not installed. Skipped."
    append_report ""
fi

# =====================================================================
# 4. Secrets Detection
# =====================================================================

log ""
log "=========================================="
log "Secrets Detection"
log "=========================================="

append_report "## Secrets Detection"
append_report ""

log "Checking for hardcoded secrets..."

# Simple pattern-based secret detection
SECRET_PATTERNS=(
    'password\s*=\s*["\x27][^"\x27]+["\x27]'
    'api_key\s*=\s*["\x27][^"\x27]+["\x27]'
    'secret\s*=\s*["\x27][^"\x27]+["\x27]'
    'token\s*=\s*["\x27][^"\x27]+["\x27]'
)

FOUND_SECRETS=false
for pattern in "${SECRET_PATTERNS[@]}"; do
    MATCHES=$(grep -rin "$pattern" chat_app/ --include="*.py" 2>/dev/null | grep -v "os.getenv" | grep -v "\.example" | grep -v "#" | grep -v "test_" || true)
    if [ -n "$MATCHES" ]; then
        FOUND_SECRETS=true
        log "  POTENTIAL SECRET FOUND:"
        echo "$MATCHES"
        append_report "Potential hardcoded secrets detected. Review the output above."
    fi
done

if [ "$FOUND_SECRETS" = false ]; then
    log "  No hardcoded secrets detected"
    append_report "No hardcoded secrets detected."
fi
append_report ""

# =====================================================================
# REPORT OUTPUT
# =====================================================================

append_report "## Summary"
append_report ""
if [ $EXIT_CODE -eq 0 ]; then
    append_report "Overall: PASS - No critical issues found."
else
    append_report "Overall: FAIL - Issues detected. Review and fix before deployment."
fi

if [ -n "$REPORT_FILE" ]; then
    echo "$REPORT" > "$REPORT_FILE"
    log "Report saved to: $REPORT_FILE"
fi

echo ""
echo "$REPORT"

exit $EXIT_CODE
