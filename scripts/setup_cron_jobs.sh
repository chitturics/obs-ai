#!/bin/bash
# ==============================================================================
# Setup Cron Jobs for Self-Learning AI Agent
# ==============================================================================
# This script sets up automated cron jobs for:
# - Weekly feedback export and analysis (Phase 2)
# - Monthly model fine-tuning (Phase 3)
# ==============================================================================

set -e

cd "$(dirname "$0")/.."
PROJECT_ROOT="$(pwd)"

echo "================================================================================"
echo "Setting Up Cron Jobs for Self-Learning AI Agent"
echo "================================================================================"
echo ""
echo "Project root: $PROJECT_ROOT"
echo ""

# Check if running on Linux (cron available)
if ! command -v crontab &> /dev/null; then
  echo "⚠️  WARNING: crontab command not found"
  echo ""
  echo "This script requires cron (Linux/Unix)."
  echo "For Windows, you need to:"
  echo "  1. Use WSL (Windows Subsystem for Linux)"
  echo "  2. Or use Windows Task Scheduler manually"
  echo ""
  exit 1
fi

# Create cron job entries
WEEKLY_EXPORT_SCRIPT="$PROJECT_ROOT/scripts/weekly_feedback_export.sh"
MONTHLY_FINETUNE_SCRIPT="$PROJECT_ROOT/scripts/monthly_model_finetune.sh"

# Verify scripts exist
if [ ! -f "$WEEKLY_EXPORT_SCRIPT" ]; then
  echo "✗ ERROR: $WEEKLY_EXPORT_SCRIPT not found"
  exit 1
fi

if [ ! -f "$MONTHLY_FINETUNE_SCRIPT" ]; then
  echo "✗ ERROR: $MONTHLY_FINETUNE_SCRIPT not found"
  exit 1
fi

# Make scripts executable
chmod +x "$WEEKLY_EXPORT_SCRIPT"
chmod +x "$MONTHLY_FINETUNE_SCRIPT"

echo "✓ Scripts are executable"
echo ""

# Create temporary cron file
TEMP_CRON=$(mktemp)

# Get existing crontab (if any)
crontab -l > "$TEMP_CRON" 2>/dev/null || true

# Remove old entries for these scripts (if they exist)
sed -i "\|$WEEKLY_EXPORT_SCRIPT|d" "$TEMP_CRON"
sed -i "\|$MONTHLY_FINETUNE_SCRIPT|d" "$TEMP_CRON"

# Add new cron entries
cat >> "$TEMP_CRON" <<CRON_ENTRIES

# ==============================================================================
# Chainlit Splunk Assistant - Self-Learning AI Agent
# ==============================================================================

# Weekly Feedback Export and Analysis (Every Sunday at 2 AM)
0 2 * * 0 $WEEKLY_EXPORT_SCRIPT

# Monthly Model Fine-tuning (1st day of month at 3 AM)
0 3 1 * * $MONTHLY_FINETUNE_SCRIPT

CRON_ENTRIES

# Install new crontab
crontab "$TEMP_CRON"
rm "$TEMP_CRON"

echo "✓ Cron jobs installed successfully!"
echo ""

# Display installed cron jobs
echo "================================================================================"
echo "Installed Cron Jobs:"
echo "================================================================================"
crontab -l | grep -A 5 "Chainlit Splunk Assistant"
echo ""

echo "================================================================================"
echo "Schedule Summary:"
echo "================================================================================"
echo ""
echo "📅 Weekly (Every Sunday at 2 AM):"
echo "   - Export feedback to JSONL"
echo "   - Generate analysis report"
echo "   Script: $WEEKLY_EXPORT_SCRIPT"
echo ""
echo "📅 Monthly (1st of month at 3 AM):"
echo "   - Export training data"
echo "   - Fine-tune Ollama model"
echo "   - Create A/B test model"
echo "   Script: $MONTHLY_FINETUNE_SCRIPT"
echo ""
echo "================================================================================"
echo "Logs:"
echo "================================================================================"
echo ""
echo "  Weekly export:      logs/weekly_export.log"
echo "  Monthly fine-tune:  logs/monthly_finetune.log"
echo ""
echo "To view logs:"
echo "  tail -f logs/weekly_export.log"
echo "  tail -f logs/monthly_finetune.log"
echo ""
echo "================================================================================"
echo "Manual Execution:"
echo "================================================================================"
echo ""
echo "To run weekly export manually:"
echo "  bash scripts/weekly_feedback_export.sh"
echo ""
echo "To run monthly fine-tuning manually:"
echo "  bash scripts/monthly_model_finetune.sh"
echo ""
echo "================================================================================"
echo "To Remove Cron Jobs:"
echo "================================================================================"
echo ""
echo "  crontab -e"
echo "  # Then delete the lines under 'Chainlit Splunk Assistant'"
echo ""
echo "================================================================================"
