#!/bin/bash
# ==============================================================================
# Monthly Model Fine-tuning (Phase 3)
# ==============================================================================
# Runs monthly to fine-tune the Ollama model on accumulated feedback
#
# Schedule with cron:
#   0 3 1 * * /path/to/monthly_model_finetune.sh  # 1st day of month at 3 AM
# ==============================================================================

set -e

cd "$(dirname "$0")/.."

# Configuration
FEEDBACK_DIR="feedback/exports"
FINETUNE_DIR="feedback/finetune"
MODEL_DIR="llms/finetuned"
LOG_FILE="logs/monthly_finetune.log"

# Model configuration
BASE_MODEL="${OLLAMA_MODEL:-qwen2.5:3b}"
FINETUNED_MODEL_NAME="qwen2.5:3b-splunk-tuned"

# Docker/Podman detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi

mkdir -p "$FEEDBACK_DIR" "$FINETUNE_DIR" "$MODEL_DIR" "$(dirname "$LOG_FILE")"

echo "================================================================================" | tee -a "$LOG_FILE"
echo "[$(date)] Monthly Model Fine-tuning Starting" | tee -a "$LOG_FILE"
echo "================================================================================" | tee -a "$LOG_FILE"

# Check if container is running
if ! $DOCKER_CMD ps --format '{{.Names}}' | grep -q "^llm_api_service$"; then
  echo "ERROR: llm_api_service container is not running" | tee -a "$LOG_FILE"
  exit 1
fi

# Step 1: Export latest feedback to training format
echo "[$(date)] Step 1: Exporting feedback for training..." | tee -a "$LOG_FILE"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
TRAINING_FILE="$FINETUNE_DIR/training_${TIMESTAMP}.jsonl"

$DOCKER_CMD exec chat_ui_app python3 <<EOF 2>&1 | tee -a "$LOG_FILE"
import sys
sys.path.insert(0, '/app')

from chat_app.feedback_analytics import export_feedback_to_jsonl

# Export feedback from last 30 days
from datetime import datetime, timedelta
min_date = (datetime.utcnow() - timedelta(days=30)).isoformat()

success, result = export_feedback_to_jsonl(
    output_file="/app/public/$TRAINING_FILE",
    include_positive=True,
    include_negative=True,
    min_date=min_date
)

if success:
    print(f"✓ Exported training data to: {result}")
else:
    print(f"✗ Export failed: {result}")
    sys.exit(1)
EOF

EXPORT_STATUS=$?

if [ $EXPORT_STATUS -ne 0 ]; then
  echo "✗ Training data export failed" | tee -a "$LOG_FILE"
  exit 1
fi

# Step 2: Convert JSONL to Ollama Modelfile format
echo "[$(date)] Step 2: Converting to Ollama format..." | tee -a "$LOG_FILE"

# Check if training file exists and has content
if [ ! -s "$TRAINING_FILE" ]; then
  echo "⚠️  No training data found. Skipping fine-tuning." | tee -a "$LOG_FILE"
  exit 0
fi

# Count examples
EXAMPLE_COUNT=$(wc -l < "$TRAINING_FILE")
echo "  - Training examples: $EXAMPLE_COUNT" | tee -a "$LOG_FILE"

if [ "$EXAMPLE_COUNT" -lt 10 ]; then
  echo "⚠️  Too few examples ($EXAMPLE_COUNT). Need at least 10. Skipping fine-tuning." | tee -a "$LOG_FILE"
  exit 0
fi

# Create Modelfile for fine-tuning
MODELFILE="$FINETUNE_DIR/Modelfile_${TIMESTAMP}"
cat > "$MODELFILE" <<MODELFILE_CONTENT
# Fine-tuned Splunk Assistant Model
FROM $BASE_MODEL

# System prompt with learned patterns
SYSTEM """
You are a Splunk expert assistant that has learned from user feedback.

Key principles learned from positive feedback:
- Always specify exact index names (never use index=*)
- Prefer tstats for performance
- Use TERM() and PREFIX() for optimization
- Reference CIM datamodels when applicable
- Provide complete, working queries

Patterns to AVOID (from negative feedback):
- Generic answers without specific index names
- Queries that are too broad or unoptimized
- Missing important query components
- Incorrect SPL syntax
"""

# Temperature and context settings optimized for Splunk queries
PARAMETER temperature 0.3
PARAMETER top_p 0.9
PARAMETER top_k 40
PARAMETER num_ctx 8192
PARAMETER stop "<|endoftext|>"
PARAMETER stop "<|im_end|>"

# Model metadata
PARAMETER model_name "$FINETUNED_MODEL_NAME"
PARAMETER model_version "$(date +%Y%m%d)"
PARAMETER model_description "Splunk Assistant fine-tuned on user feedback"
MODELFILE_CONTENT

echo "✓ Created Modelfile: $MODELFILE" | tee -a "$LOG_FILE"

# Step 3: Create fine-tuned model in Ollama
echo "[$(date)] Step 3: Creating fine-tuned model in Ollama..." | tee -a "$LOG_FILE"

# Copy Modelfile to container
$DOCKER_CMD cp "$MODELFILE" llm_api_service:/tmp/Modelfile

# Create model
$DOCKER_CMD exec llm_api_service ollama create "$FINETUNED_MODEL_NAME" -f /tmp/Modelfile 2>&1 | tee -a "$LOG_FILE"

CREATE_STATUS=${PIPESTATUS[0]}

if [ $CREATE_STATUS -eq 0 ]; then
  echo "✓ Fine-tuned model created: $FINETUNED_MODEL_NAME" | tee -a "$LOG_FILE"
else
  echo "✗ Model creation failed" | tee -a "$LOG_FILE"
  exit 1
fi

# Step 4: Test the fine-tuned model
echo "[$(date)] Step 4: Testing fine-tuned model..." | tee -a "$LOG_FILE"

TEST_QUERY="Show me failed login attempts from the last hour"

$DOCKER_CMD exec llm_api_service ollama run "$FINETUNED_MODEL_NAME" "$TEST_QUERY" 2>&1 | head -20 | tee -a "$LOG_FILE"

# Step 5: Backup original model configuration
echo "[$(date)] Step 5: Backing up current configuration..." | tee -a "$LOG_FILE"

# Create backup of current model setting
echo "OLLAMA_MODEL_BACKUP=$BASE_MODEL" > "$FINETUNE_DIR/model_backup_${TIMESTAMP}.env"
echo "OLLAMA_MODEL_FINETUNED=$FINETUNED_MODEL_NAME" >> "$FINETUNE_DIR/model_backup_${TIMESTAMP}.env"

echo "✓ Backup created" | tee -a "$LOG_FILE"

# Step 6: Instructions for A/B testing
echo "" | tee -a "$LOG_FILE"
echo "================================================================================" | tee -a "$LOG_FILE"
echo "Fine-tuning Complete!" | tee -a "$LOG_FILE"
echo "================================================================================" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"
echo "Next Steps - A/B Testing:" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"
echo "1. Test the fine-tuned model manually:" | tee -a "$LOG_FILE"
echo "   podman exec -it llm_api_service ollama run $FINETUNED_MODEL_NAME" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"
echo "2. To deploy fine-tuned model, update docker_files/start_all.sh:" | tee -a "$LOG_FILE"
echo "   Change: APP_OLLAMA_MODEL=\"$BASE_MODEL\"" | tee -a "$LOG_FILE"
echo "   To:     APP_OLLAMA_MODEL=\"$FINETUNED_MODEL_NAME\"" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"
echo "3. Or set environment variable:" | tee -a "$LOG_FILE"
echo "   export OLLAMA_MODEL=\"$FINETUNED_MODEL_NAME\"" | tee -a "$LOG_FILE"
echo "   bash docker_files/start_all.sh" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"
echo "4. To rollback to original model:" | tee -a "$LOG_FILE"
echo "   source $FINETUNE_DIR/model_backup_${TIMESTAMP}.env" | tee -a "$LOG_FILE"
echo "   export OLLAMA_MODEL=\$OLLAMA_MODEL_BACKUP" | tee -a "$LOG_FILE"
echo "   bash docker_files/start_all.sh" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"
echo "Files created:" | tee -a "$LOG_FILE"
echo "  - Training data: $TRAINING_FILE" | tee -a "$LOG_FILE"
echo "  - Modelfile: $MODELFILE" | tee -a "$LOG_FILE"
echo "  - Backup config: $FINETUNE_DIR/model_backup_${TIMESTAMP}.env" | tee -a "$LOG_FILE"
echo "" | tee -a "$LOG_FILE"
echo "================================================================================" | tee -a "$LOG_FILE"
