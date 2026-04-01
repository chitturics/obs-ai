#!/bin/bash
# ==============================================================================
# Weekly Feedback Export (Phase 2)
# ==============================================================================
# Runs weekly to export feedback to JSONL format for analysis
#
# Schedule with cron:
#   0 2 * * 0 /path/to/weekly_feedback_export.sh  # Every Sunday at 2 AM
# ==============================================================================

set -e

cd "$(dirname "$0")/.."

# Configuration
FEEDBACK_DIR="feedback/exports"
REPORT_DIR="feedback/reports"
LOG_FILE="logs/weekly_export.log"

# Docker/Podman detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi

mkdir -p "$FEEDBACK_DIR" "$REPORT_DIR" "$(dirname "$LOG_FILE")"

echo "================================================================================" | tee -a "$LOG_FILE"
echo "[$(date)] Weekly Feedback Export Starting" | tee -a "$LOG_FILE"
echo "================================================================================" | tee -a "$LOG_FILE"

# Check if container is running
if ! $DOCKER_CMD ps --format '{{.Names}}' | grep -q "^chat_ui_app$"; then
  echo "ERROR: chat_ui_app container is not running" | tee -a "$LOG_FILE"
  exit 1
fi

# Export feedback to JSONL
echo "[$(date)] Exporting feedback to JSONL..." | tee -a "$LOG_FILE"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

$DOCKER_CMD exec chat_ui_app python3 <<EOF 2>&1 | tee -a "$LOG_FILE"
import sys
sys.path.insert(0, '/app')

from chat_app.feedback_analytics import export_feedback_to_jsonl

# Export all feedback (positive and negative)
success, result = export_feedback_to_jsonl(
    output_file="/app/public/feedback/exports/training_${TIMESTAMP}.jsonl",
    include_positive=True,
    include_negative=True
)

if success:
    print(f"✓ Exported feedback to: {result}")
else:
    print(f"✗ Export failed: {result}")
    sys.exit(1)
EOF

EXPORT_STATUS=$?

if [ $EXPORT_STATUS -eq 0 ]; then
  echo "✓ Feedback export completed successfully" | tee -a "$LOG_FILE"
else
  echo "✗ Feedback export failed" | tee -a "$LOG_FILE"
  exit 1
fi

# Generate feedback analysis report
echo "[$(date)] Generating feedback analysis report..." | tee -a "$LOG_FILE"

$DOCKER_CMD exec chat_ui_app python3 <<EOF 2>&1 | tee -a "$LOG_FILE"
import sys
sys.path.insert(0, '/app')

from chat_app.feedback_analytics import generate_feedback_report

success, result = generate_feedback_report(
    output_file="/app/public/feedback/reports/report_${TIMESTAMP}.md"
)

if success:
    print(f"✓ Generated report: {result}")
else:
    print(f"✗ Report generation failed: {result}")
    sys.exit(1)
EOF

REPORT_STATUS=$?

if [ $REPORT_STATUS -eq 0 ]; then
  echo "✓ Report generation completed successfully" | tee -a "$LOG_FILE"
else
  echo "✗ Report generation failed" | tee -a "$LOG_FILE"
  exit 1
fi

# Print statistics
echo "" | tee -a "$LOG_FILE"
echo "Summary:" | tee -a "$LOG_FILE"
echo "  - Export file: feedback/exports/training_${TIMESTAMP}.jsonl" | tee -a "$LOG_FILE"
echo "  - Report file: feedback/reports/report_${TIMESTAMP}.md" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"

# Show recent exports
echo "Recent exports:" | tee -a "$LOG_FILE"
ls -lh "$FEEDBACK_DIR" | tail -5 | tee -a "$LOG_FILE"

echo "================================================================================" | tee -a "$LOG_FILE"
echo "[$(date)] Weekly Feedback Export Complete" | tee -a "$LOG_FILE"
echo "================================================================================" | tee -a "$LOG_FILE"
