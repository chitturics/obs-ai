#!/bin/bash
# Helper script to manually create all ChromaDB collections
# Use this if collections don't auto-create properly

set -e

echo "Creating ChromaDB collections..."

# Use podman or docker
CONTAINER_CMD="podman"
if ! command -v podman &> /dev/null; then
    if command -v docker &> /dev/null; then
        CONTAINER_CMD="docker"
    else
        echo "ERROR: Neither podman nor docker found!"
        exit 1
    fi
fi

echo "Using: $CONTAINER_CMD"

$CONTAINER_CMD exec chat_ui_app python3 << 'EOF'
import chromadb
import sys

c = chromadb.HttpClient(host="127.0.0.1", port=8001)

# Collections to create
collections = [
    "specs_mxbai_embed_large_v3",
    "spl_commands_mxbai",
    "org_repo_mxbai",
    "local_docs_mxbai",
    "assistant_memory_mxbai_v2",
    "feedback_qa_mxbai_embed_large"
]

print("Creating collections...")
success = 0
failed = 0

for coll_name in collections:
    try:
        c.get_or_create_collection(coll_name)
        print(f"✓ Created/ensured: {coll_name}")
        success += 1
    except Exception as e:
        print(f"✗ Failed {coll_name}: {e}")
        failed += 1

print(f"\nSummary: {success} succeeded, {failed} failed")

# List all collections
print("\nCurrent collections:")
colls = c.list_collections()
for col in colls:
    print(f"  {col.name}: {col.count()} documents")

sys.exit(0 if failed == 0 else 1)
EOF

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ All collections created successfully"
    echo "Restarting chat_ui_app to pick up collections..."
    $CONTAINER_CMD restart chat_ui_app
    echo "Done!"
else
    echo ""
    echo "✗ Some collections failed to create"
    echo "Check ChromaDB logs: $CONTAINER_CMD logs chat_chroma_db"
    exit 1
fi
