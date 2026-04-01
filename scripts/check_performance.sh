#!/bin/bash
# Check current performance and identify bottlenecks

echo "=== Performance Check ==="
echo ""

# Change to project root directory
cd "$(dirname "$0")/.."

echo "Step 1: Checking if Ollama models are loaded..."
OLLAMA_PS=$(podman exec llm_api_service ollama ps 2>/dev/null || echo "ERROR")

if echo "$OLLAMA_PS" | grep -q "NAME"; then
    echo "$OLLAMA_PS"
    echo ""

    if echo "$OLLAMA_PS" | grep -q "GPU"; then
        echo "✅ Models using GPU - should be FAST"
    elif echo "$OLLAMA_PS" | grep -q "CPU"; then
        echo "❌ PROBLEM: Models using CPU - THIS IS WHY IT'S SLOW!"
        echo ""
        echo "Your embeddings are taking 18-20 seconds each (should be <1 second with GPU)"
        echo ""
        echo "SOLUTION: Switch to faster model that works better on CPU"
        echo ""
        echo "Run this command:"
        echo "  export OLLAMA_MODEL=qwen2.5:3b"
        echo "  export OLLAMA_EMBED_MODEL=mxbai-embed-large"
        echo "  podman compose down && podman compose up -d"
        echo ""
        echo "Expected improvement:"
        echo "  - Embeddings: 20s → 2-3s each"
        echo "  - LLM: 2min → 15-30s"
        echo "  - Total query: 3min → 30-45s"
    fi
else
    echo "⚠️  No models loaded. Make a query first."
fi

echo ""
echo "Step 2: Testing embedding speed..."
echo "Timing a single embedding call..."

START=$(date +%s)
podman exec llm_api_service ollama run mxbai-embed-large "test embedding" > /dev/null 2>&1
END=$(date +%s)
DURATION=$((END - START))

echo "Embedding took: ${DURATION} seconds"
echo ""

if [ $DURATION -gt 10 ]; then
    echo "❌ TOO SLOW! Embeddings should take <1 second with GPU"
    echo "   Your embeddings are taking ${DURATION}s - this is CPU-only performance"
    echo ""
    echo "💡 QUICK FIX: Use faster embedding model"
    echo "   export OLLAMA_EMBED_MODEL=mxbai-embed-large"
    echo "   podman compose restart llm-api-service"
elif [ $DURATION -gt 2 ]; then
    echo "⚠️  Slow (CPU). With GPU should be <1 second"
else
    echo "✅ Fast! GPU is working"
fi

echo ""
echo "Step 3: Checking recent query timing..."
RECENT_TIMING=$(podman logs --tail 100 chat_ui_app 2>&1 | grep -E "Calling LLM|response received" | tail -4)

if [ -n "$RECENT_TIMING" ]; then
    echo "Recent LLM calls:"
    echo "$RECENT_TIMING"
else
    echo "No recent queries found"
fi

echo ""
echo "=== Summary ==="
echo ""
echo "Based on your logs, embeddings are taking 18-20 seconds each."
echo "This is 20x slower than they should be with GPU."
echo ""
echo "RECOMMENDATION: Switch to faster models for CPU"
echo ""
echo "Quick command:"
echo "  export OLLAMA_MODEL=qwen2.5:3b"
echo "  export OLLAMA_EMBED_MODEL=mxbai-embed-large  "
echo "  bash scripts/quick_restart.sh"
echo ""
