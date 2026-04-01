#!/bin/bash
# Ingest Q&A pairs (spec/conf/command knowledge) into ChromaDB
# Run after generate_all_qa.py and after ChromaDB is running

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

QA_FILE="${PROJECT_DIR}/qa_dataset/all_qa.jsonl"

if [ ! -f "$QA_FILE" ]; then
    echo "Q&A file not found. Generating..."
    python3 "${PROJECT_DIR}/scripts/generate_all_qa.py"
fi

echo "Ingesting Q&A pairs into ChromaDB..."
python3 "${SCRIPT_DIR}/ingest_qa_pairs.py" --file "$QA_FILE" "$@"
echo "Done."
