#!/bin/bash
# Nuclear option - kill EVERYTHING and start fresh

echo "=== NUCLEAR RESTART - Killing Everything ==="
echo ""

cd /mnt/c/tools/chainlit

echo "Step 1: Stop ALL podman containers..."
podman stop $(podman ps -aq) 2>/dev/null || true
podman rm -f $(podman ps -aq) 2>/dev/null || true

echo ""
echo "Step 2: Kill ALL processes using ports 8001 and 11430..."

# Port 8001 (ChromaDB)
echo "Checking port 8001..."
while sudo lsof -ti:8001 >/dev/null 2>&1; do
    PID=$(sudo lsof -ti:8001)
    echo "  Killing PID $PID on port 8001"
    sudo kill -9 $PID 2>/dev/null || true
    sleep 1
done
echo "✅ Port 8001 is FREE"

# Port 11430 (Ollama)
echo "Checking port 11430..."
while sudo lsof -ti:11430 >/dev/null 2>&1; do
    PID=$(sudo lsof -ti:11430)
    echo "  Killing PID $PID on port 11430"
    sudo kill -9 $PID 2>/dev/null || true
    sleep 1
done
echo "✅ Port 11430 is FREE"

echo ""
echo "Step 3: Kill ALL chroma processes by name..."
sudo pkill -9 -f chroma 2>/dev/null || true
sudo pkill -9 -f chromadb 2>/dev/null || true
sleep 2

echo ""
echo "Step 4: Verify NO chroma processes exist..."
CHROMA_COUNT=$(ps aux | grep -i chroma | grep -v grep | wc -l)
if [ "$CHROMA_COUNT" -eq 0 ]; then
    echo "✅ No chroma processes running"
else
    echo "⚠️  Still found $CHROMA_COUNT chroma processes:"
    ps aux | grep -i chroma | grep -v grep
    echo "Killing them..."
    ps aux | grep -i chroma | grep -v grep | awk '{print $2}' | xargs -r sudo kill -9
fi

echo ""
echo "Step 5: Final port verification..."
if sudo netstat -tlnp | grep -q 8001; then
    echo "❌ Port 8001 STILL in use!"
    sudo netstat -tlnp | grep 8001
    exit 1
else
    echo "✅ Port 8001 confirmed FREE"
fi

if sudo netstat -tlnp | grep -q 11430; then
    echo "❌ Port 11430 STILL in use!"
    sudo netstat -tlnp | grep 11430
    exit 1
else
    echo "✅ Port 11430 confirmed FREE"
fi

echo ""
echo "Step 6: Starting containers ONE AT A TIME..."

# Start ChromaDB first
echo "Starting ChromaDB..."
podman compose up -d chat-chroma-db

echo "Waiting 15 seconds for ChromaDB to start..."
sleep 15

# Check if ChromaDB is actually running
if podman ps --filter "name=chat_chroma_db" --format "{{.Status}}" | grep -q "Up"; then
    echo "✅ ChromaDB container is UP"

    # Check if it's listening on port 8001
    if sudo netstat -tlnp | grep 8001 | grep -q "chroma\|LISTEN"; then
        echo "✅ ChromaDB is listening on port 8001"
    else
        echo "❌ ChromaDB container up but NOT listening on 8001!"
        podman logs --tail 20 chat_chroma_db
        exit 1
    fi
else
    echo "❌ ChromaDB container failed to start!"
    podman logs --tail 20 chat_chroma_db
    exit 1
fi

# Start other services
echo ""
echo "Starting other services..."
podman compose up -d

echo ""
echo "Waiting 20 seconds for all services..."
sleep 20

echo ""
echo "Step 7: Final status check..."
podman ps --format "table {{.Names}}\t{{.Status}}"

echo ""
echo "Step 8: Health checks..."

# ChromaDB health
if curl -sf http://127.0.0.1:8001/api/v1/heartbeat >/dev/null 2>&1; then
    echo "✅ ChromaDB API responding"
else
    echo "⚠️  ChromaDB not responding (may need more time)"
fi

# Ollama health
if curl -sf http://127.0.0.1:11430/ >/dev/null 2>&1; then
    echo "✅ Ollama API responding"
else
    echo "⚠️  Ollama not responding (may need more time)"
fi

echo ""
echo "=== RESTART COMPLETE ==="
echo ""
echo "Access app at: http://localhost:8000"
echo ""
echo "If issues persist, check logs:"
echo "  podman logs chat_chroma_db"
echo "  podman logs llm_api_service"
echo "  podman logs chat_ui_app"
echo ""
