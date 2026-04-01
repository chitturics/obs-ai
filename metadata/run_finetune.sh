#!/usr/bin/env bash
# Example OpenAI CLI fine-tune script for the Splunk AI assistant.
# Adjust model, suffix, and paths as needed.

set -euo pipefail

DATA_FILE="training.jsonl"

if [ ! -f "$DATA_FILE" ]; then
  echo "training.jsonl not found in current directory."
  exit 1
fi

# Example invocation (you must have OPENAI_API_KEY set in your environment)
openai api fine_tuning.jobs.create \
  -t "$DATA_FILE" \
  -m gpt-4.1-mini \
  --suffix "splunk-assistant-no-index-star"
