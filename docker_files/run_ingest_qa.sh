#!/bin/bash
# Full Q&A pipeline: generate, ingest into ChromaDB, build training data, create Ollama model.
# Requires: Ollama + ChromaDB already running (via start_all.sh)
#
# Usage:
#   bash docker_files/run_ingest_qa.sh                  # Full pipeline (all 5 steps)
#   bash docker_files/run_ingest_qa.sh --skip-training   # Steps 1-3 only (no fine-tune)
#   bash docker_files/run_ingest_qa.sh --regenerate       # Force regenerate Q&A even if file exists
#   bash docker_files/run_ingest_qa.sh --collection X     # Override ChromaDB collection name
#   bash docker_files/run_ingest_qa.sh --dry-run          # Passed to ingest_qa_pairs.py

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Parse our flags vs pass-through args
SKIP_TRAINING=false
REGENERATE=false
EXTRA_ARGS=""
for arg in "$@"; do
    case "$arg" in
        --skip-training) SKIP_TRAINING=true ;;
        --regenerate)    REGENERATE=true ;;
        *)               EXTRA_ARGS="$EXTRA_ARGS $arg" ;;
    esac
done

# Docker/Podman detection
if command -v podman &> /dev/null; then
  DOCKER_CMD="podman"
else
  DOCKER_CMD="docker"
fi
docker() { "$DOCKER_CMD" "$@"; }

# Clean up any leftover containers on exit
cleanup() {
    for c in chainlit_generate_qa qa_ingest_job qa_build_training; do
        docker rm -f "$c" 2>/dev/null || true
    done
}
trap cleanup EXIT

# Determine the image
IMAGE_NAME=""
for candidate in "chainlit-ingest:latest" "localhost/chainlit-ingest:latest" "chainlit-app:latest" "localhost/chainlit-app:latest"; do
    if docker image inspect "$candidate" >/dev/null 2>&1; then
        IMAGE_NAME="$candidate"
        break
    fi
done

if [ -z "$IMAGE_NAME" ]; then
    echo "ERROR: No suitable container image found (tried chainlit-ingest, chainlit-app)"
    exit 1
fi

echo "Using image: $IMAGE_NAME"

# Check if services are running
if ! curl -sf http://127.0.0.1:11430/ >/dev/null 2>&1; then
    echo "ERROR: Ollama is not running on port 11430. Start services first."
    exit 1
fi
if ! curl -sf http://127.0.0.1:8001/api/v2/heartbeat >/dev/null 2>&1; then
    echo "ERROR: ChromaDB is not running on port 8001. Start services first."
    exit 1
fi

echo ""
echo "============================================================"
echo "  Q&A Full Pipeline"
echo "============================================================"

# ──────────────────────────────────────────────────────────────
# Step 1: Generate Q&A pairs from spec/conf/command files
# ──────────────────────────────────────────────────────────────
QA_FILE="$PROJECT_ROOT/qa_dataset/all_qa.jsonl"
mkdir -p "$PROJECT_ROOT/qa_dataset"

if [ "$REGENERATE" = true ] || [ ! -f "$QA_FILE" ]; then
    echo ""
    echo "[Step 1/5] Generating Q&A pairs from spec/conf/command files..."
    # Remove old file if regenerating
    [ "$REGENERATE" = true ] && rm -f "$QA_FILE"

    GEN_CONTAINER="chainlit_generate_qa"
    docker rm -f "$GEN_CONTAINER" 2>/dev/null || true

    docker create --name "$GEN_CONTAINER" \
        --entrypoint /bin/bash \
        --network host \
        -e PYTHONPATH=/app \
        "$IMAGE_NAME" \
        -c 'mkdir -p /app/qa_dataset /app/scripts /app/ingest_specs && cd /app && python3 scripts/generate_all_qa.py'

    # Copy source files into container
    docker cp "$PROJECT_ROOT/scripts" "$GEN_CONTAINER:/app/scripts"
    docker cp "$PROJECT_ROOT/ingest_specs" "$GEN_CONTAINER:/app/ingest_specs"

    docker start -a "$GEN_CONTAINER"

    # Copy generated QA files back
    docker cp "$GEN_CONTAINER:/app/qa_dataset" "$PROJECT_ROOT/qa_dataset"
    docker rm -f "$GEN_CONTAINER" 2>/dev/null || true

    if [ ! -f "$QA_FILE" ]; then
        echo "ERROR: Failed to generate Q&A file at $QA_FILE"
        exit 1
    fi
else
    echo ""
    echo "[Step 1/5] Q&A file already exists (use --regenerate to recreate)"
fi

QA_COUNT=$(wc -l < "$QA_FILE")
echo "  Found $QA_COUNT Q&A pairs"

# ──────────────────────────────────────────────────────────────
# Step 2: Ingest Q&A pairs into ChromaDB (with embeddings)
# ──────────────────────────────────────────────────────────────
echo ""
echo "[Step 2/5] Ingesting Q&A pairs into ChromaDB..."

# When regenerating, pass --force to skip fingerprint checks (re-ingest everything)
INGEST_EXTRA="$EXTRA_ARGS"
if [ "$REGENERATE" = true ]; then
    INGEST_EXTRA="$INGEST_EXTRA --force"
fi

INGEST_CONTAINER="qa_ingest_job"
docker rm -f "$INGEST_CONTAINER" 2>/dev/null || true

docker create --name "$INGEST_CONTAINER" \
    --entrypoint /bin/bash \
    --network host \
    -e OLLAMA_BASE_URL=http://127.0.0.1:11430 \
    -e OLLAMA_EMBED_MODEL="${OLLAMA_EMBED_MODEL:-mxbai-embed-large}" \
    -e CHROMA_HTTP_URL=http://127.0.0.1:8001 \
    -e CHROMA_COLLECTION="${CHROMA_COLLECTION:-assistant_memory_mxbai_v2}" \
    -e PYTHONPATH=/app/chat_app:/app \
    "$IMAGE_NAME" \
    -c "cd /app && python3 ingest_specs/ingest_qa_pairs.py --file /app/qa_dataset/all_qa.jsonl $INGEST_EXTRA"

# Copy files into container
docker cp "$PROJECT_ROOT/qa_dataset" "$INGEST_CONTAINER:/app/qa_dataset"
docker cp "$PROJECT_ROOT/ingest_specs" "$INGEST_CONTAINER:/app/ingest_specs"
docker cp "$PROJECT_ROOT/chat_app" "$INGEST_CONTAINER:/app/chat_app"

docker start -a "$INGEST_CONTAINER"
docker rm -f "$INGEST_CONTAINER" 2>/dev/null || true

echo "  ChromaDB ingestion complete."

# ──────────────────────────────────────────────────────────────
# Step 3: Verify ChromaDB collections
# ──────────────────────────────────────────────────────────────
echo ""
echo "[Step 3/5] Verifying ChromaDB collections..."

docker run --rm \
    --name qa_verify_collections \
    --entrypoint /bin/bash \
    --network host \
    -e CHROMA_HTTP_URL=http://127.0.0.1:8001 \
    "$IMAGE_NAME" \
    -c 'python3 -c "
import chromadb, os
try:
    url = os.getenv(\"CHROMA_HTTP_URL\", \"http://127.0.0.1:8001\")
    from urllib.parse import urlparse
    p = urlparse(url)
    client = chromadb.HttpClient(host=p.hostname, port=p.port or 8001)
    collections = client.list_collections()
    print(\"  Collections:\")
    for c in collections:
        name = c if isinstance(c, str) else c.name
        try:
            col = client.get_collection(name)
            count = col.count()
        except:
            count = \"?\"
        print(f\"    {name}: {count} chunks\")
except Exception as e:
    print(f\"  Warning: Could not verify collections: {e}\")
"'

if [ "$SKIP_TRAINING" = true ]; then
    echo ""
    echo "[Step 4/5] Skipped (--skip-training)"
    echo "[Step 5/5] Skipped (--skip-training)"
    echo ""
    echo "============================================================"
    echo "  Pipeline complete (steps 1-3). Q&A ingested into ChromaDB."
    echo "============================================================"
    exit 0
fi

# ──────────────────────────────────────────────────────────────
# Step 4: Build training data (combines QA + feedback)
# ──────────────────────────────────────────────────────────────
echo ""
echo "[Step 4/5] Building training data (QA + feedback)..."
mkdir -p "$PROJECT_ROOT/training_data"
mkdir -p "$PROJECT_ROOT/feedback"

# Detect DATABASE_URL for feedback inclusion
DB_URL_ENV=""
if [ -n "${DATABASE_URL:-}" ]; then
    DB_URL_ENV="-e DATABASE_URL=$DATABASE_URL"
fi

# Use a named container so we can docker cp results out (avoids mount permission issues)
TRAIN_CONTAINER="qa_build_training"
docker rm -f "$TRAIN_CONTAINER" 2>/dev/null || true

docker create --name "$TRAIN_CONTAINER" \
    --entrypoint /bin/bash \
    --network host \
    -e PYTHONPATH=/app \
    $DB_URL_ENV \
    "$IMAGE_NAME" \
    -c "mkdir -p /app/training_data /app/qa_dataset /app/feedback /app/scripts && cd /app && python3 scripts/build_training_data.py --include-feedback --auto --base-model ${OLLAMA_BASE_MODEL:-llama3.1}"

# Copy files into the container
docker cp "$PROJECT_ROOT/scripts" "$TRAIN_CONTAINER:/app/scripts"
docker cp "$PROJECT_ROOT/qa_dataset" "$TRAIN_CONTAINER:/app/qa_dataset"
docker cp "$PROJECT_ROOT/feedback" "$TRAIN_CONTAINER:/app/feedback"

# Run
docker start -a "$TRAIN_CONTAINER"

# Copy results back
docker cp "$TRAIN_CONTAINER:/app/training_data" "$PROJECT_ROOT/training_data"
docker rm -f "$TRAIN_CONTAINER" 2>/dev/null || true

if [ -f "$PROJECT_ROOT/training_data/stats.json" ]; then
    echo "  Training data stats:"
    cat "$PROJECT_ROOT/training_data/stats.json" | python3 -c "
import json, sys
stats = json.load(sys.stdin)
total = stats.get('total_pairs', 0)
print(f'    Total training pairs: {total}')
for src, cnt in stats.get('sources', {}).items():
    print(f'      {src}: {cnt}')
" 2>/dev/null || echo "  (stats available in training_data/stats.json)"
fi

# ──────────────────────────────────────────────────────────────
# Step 5: Fine-tune model (LoRA) or create system-prompt model
# ──────────────────────────────────────────────────────────────
echo ""
echo "[Step 5/5] Model creation..."

# Check if GPU is available (determines LoRA vs system-prompt-only)
HAS_GPU=false
if [ -e /dev/nvidia0 ] || (command -v nvidia-smi &>/dev/null && nvidia-smi &>/dev/null); then
    HAS_GPU=true
fi

if [ "$HAS_GPU" = true ]; then
    echo "  GPU detected — will do LoRA fine-tuning (bakes knowledge into weights)."

    # Auto-build finetune image if not present
    FINETUNE_IMAGE=""
    for candidate in "chainlit-finetune:latest" "localhost/chainlit-finetune:latest"; do
        if docker image inspect "$candidate" >/dev/null 2>&1; then
            FINETUNE_IMAGE="$candidate"
            break
        fi
    done

    if [ -z "$FINETUNE_IMAGE" ]; then
        echo "  Building finetune container (first time only, this downloads ~8GB)..."
        docker build -f "$SCRIPT_DIR/Dockerfile.finetune" -t chainlit-finetune:latest "$PROJECT_ROOT"
    fi

    echo "  Running LoRA fine-tuning + Ollama model creation..."
    bash "$SCRIPT_DIR/run_finetune.sh"
else
    echo "  No GPU detected — creating system-prompt model (no weight training)."
    echo "  For real LoRA fine-tuning, run on a machine with an NVIDIA GPU."
    echo ""

    # Fall back to system-prompt-only model via Ollama API
    MODEL_NAME="${OLLAMA_FINE_TUNED_MODEL:-splunk-assistant}"
    OLLAMA_CONTAINER=$(docker ps --format '{{.Names}}' | grep -E 'ollama|llm_api' | head -1 || true)

    if [ -n "$OLLAMA_CONTAINER" ]; then
        OLLAMA_BASE="${OLLAMA_BASE_MODEL:-qwen2.5:3b}"
        echo "  Creating system-prompt model '$MODEL_NAME' from $OLLAMA_BASE..."

        docker exec "$OLLAMA_CONTAINER" bash -c "cat > /tmp/Modelfile <<'MFEOF'
FROM $OLLAMA_BASE
PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER num_ctx 4096
SYSTEM \"\"\"You are a Splunk expert assistant for the organization.
Key rules:
- Never use index=* — always specify the correct index
- Prefer | tstats with CIM data models for performance
- Use TERM() and PREFIX() inside tstats WHERE for index-level filtering
- TERM() = exact token match, PREFIX() = starts-with on indexed fields
- Break down saved searches stage by stage
- If unsure, ask clarifying questions\"\"\"
MFEOF
"
        docker exec "$OLLAMA_CONTAINER" ollama create "$MODEL_NAME" -f /tmp/Modelfile
        echo "  Model '$MODEL_NAME' created (system-prompt only, no LoRA)."
    else
        echo "  WARNING: No Ollama container found. Skipping model creation."
    fi
fi

echo ""
echo "============================================================"
echo "  Pipeline complete!"
echo "============================================================"
echo ""
echo "  Summary:"
echo "    1. Q&A generated:    $QA_COUNT pairs from spec/conf/commands"
echo "    2. ChromaDB ingested: assistant_memory_mxbai_v2 (RAG retrieval)"
echo "    3. Collections:       verified"
echo "    4. Training data:     training_data/combined_training.jsonl"
echo "    5. Model:             ${OLLAMA_FINE_TUNED_MODEL:-splunk-assistant}"
echo ""
echo "  To use in the chatbot:"
echo "    OLLAMA_MODEL=${OLLAMA_FINE_TUNED_MODEL:-splunk-assistant}"
echo ""
echo "  For real LoRA fine-tuning (bakes knowledge into weights):"
echo "    podman build -f docker_files/Dockerfile.finetune -t chainlit-finetune ."
echo "    bash docker_files/run_finetune.sh"
echo ""
echo "  Re-run anytime (idempotent). Use --regenerate to recreate Q&A."
echo "  Use --skip-training to only do steps 1-3 (ChromaDB only)."
echo ""
