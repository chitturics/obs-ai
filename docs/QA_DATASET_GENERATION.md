# Q&A Dataset Generation for LLM Training

This document explains how to generate question-answer datasets from your Splunk documentation for fine-tuning LLMs or building instruction-following models.

## Overview

The Q&A dataset generator converts your existing documentation into structured question-answer pairs:

- **Input**: .conf.spec files, .conf files, SPL command docs, PDFs
- **Output**: JSONL, CSV, or OpenAI fine-tuning format
- **Use Cases**: Fine-tuning LLMs, creating training datasets, building instruction models

## What Gets Generated

### From .conf.spec Files

For each stanza, the system generates:

1. **General purpose question**: "What is the [stanza_name] stanza in inputs.conf used for?"
2. **Configuration question**: "How do I configure monitor in inputs.conf?"
3. **Setting-specific questions**: "What does the 'sourcetype' setting do in inputs.conf [monitor]?"

**Example Output**:
```json
{
  "instruction": "What is the [monitor://path] stanza in inputs.conf used for?",
  "input": "",
  "output": "The [monitor://path] stanza in inputs.conf is used to configure:\n\n[monitor://path]\nsourcetype = <string>\nindex = <string>\n...",
  "metadata": {
    "source_file": "inputs.conf.spec",
    "source_type": "spec",
    "stanza": "monitor://path",
    "confidence": 0.9
  }
}
```

### From .conf Files (Repository)

Same as .spec files, but extracts actual configuration examples from your apps:

- Includes app metadata (app_name, app_type, app_path)
- Provides real-world configuration examples
- Shows how settings are used in practice

**Example Output**:
```json
{
  "instruction": "How do I configure search in savedsearches.conf?",
  "input": "",
  "output": "To configure [search] in savedsearches.conf, use:\n\n[search]\nsearch = index=main sourcetype=access_combined | stats count by status\ndispatch.earliest_time = -24h\n...",
  "metadata": {
    "source_file": "savedsearches.conf",
    "source_type": "spec",
    "stanza": "search",
    "app_name": "org-search",
    "app_type": "UIs",
    "confidence": 0.9
  }
}
```

### From SPL Command Documentation

For each command file, generates:

1. **Purpose question**: "What does the stats command do in Splunk?"
2. **Usage question**: "How do I use the stats command in Splunk?"
3. **Arguments question**: "What arguments does the stats command accept?"

### From PDF Documentation

Extracts paragraphs and generates contextual questions:

- "How do I configure X?" (for configuration content)
- "How do I install X?" (for installation content)
- "Can you show an example of using X?" (for example content)
- Includes page numbers in metadata

## Usage

### Option 1: Run from Container (Recommended for Remote Machine)

This is the easiest method when working on the remote machine:

```bash
# SSH to remote machine
ssh user@remote-machine

cd /opt/obsai/chatbot

# Generate Q&A dataset (all formats)
podman exec chat_ui_app python3 /app/utilities/generate_qa_dataset.py

# Or with custom options
podman exec chat_ui_app python3 /app/utilities/generate_qa_dataset.py \
    --output-dir /app/public/qa_dataset \
    --format jsonl \
    --max-files 10

# Copy results to host
podman cp chat_ui_app:/app/public/qa_dataset ./qa_dataset

# Review the CSV file
less qa_dataset/qa_dataset.csv
```

### Option 2: Run Locally (Development)

For local testing or development:

```bash
cd /path/to/chainlit

# Generate Q&A dataset
python utilities/generate_qa_dataset.py \
    --output-dir ./qa_dataset \
    --format all \
    --specs-dir ./ingest_specs \
    --commands-dir ./spl_docs \
    --pdfs-dir ./public/documents/pdfs \
    --repo-dir ./public/documents/repo
```

### Command-Line Options

Both scripts support the same options:

| Option | Description | Default |
|--------|-------------|---------|
| `--output-dir` | Output directory for dataset files | `./qa_dataset` |
| `--format` | Output format: `jsonl`, `csv`, `openai`, or `all` | `all` |
| `--max-files` | Max files per type (for testing) | None (all files) |
| `--skip-specs` | Skip .conf.spec files | False |
| `--skip-commands` | Skip SPL command docs | False |
| `--skip-pdfs` | Skip PDF files | False |
| `--skip-repo` | Skip repository .conf files | False |

### Testing Mode

Start with a small sample to verify output quality:

```bash
# Generate dataset from only 5 files per type
podman exec chat_ui_app python3 /app/public/generate_qa_from_container.py \
    --max-files 5 \
    --format csv

# Review output
podman cp chat_ui_app:/app/public/qa_dataset/qa_dataset.csv .
cat qa_dataset.csv
```

## Output Formats

### 1. JSONL Format (Instruction Fine-Tuning)

**File**: `qa_dataset.jsonl`

Standard instruction fine-tuning format compatible with most LLM training pipelines:

```json
{"instruction": "What is the [default] stanza in inputs.conf used for?", "input": "", "output": "The [default] stanza...", "metadata": {...}}
{"instruction": "How do I configure monitor in inputs.conf?", "input": "", "output": "To configure [monitor]...", "metadata": {...}}
```

**Best for**:
- Alpaca-style fine-tuning
- LLaMA/Mistral fine-tuning
- Custom training pipelines

### 2. CSV Format (Analysis & Review)

**File**: `qa_dataset.csv`

Easy-to-read format for reviewing and filtering:

```csv
question,answer,source_file,source_type,stanza,app_name,app_type,confidence
"What is the [default] stanza...","The [default] stanza...","inputs.conf.spec","spec","default","","",0.9
```

**Best for**:
- Manual review and quality checking
- Filtering by confidence score
- Excel/spreadsheet analysis
- Data exploration

### 3. OpenAI Format (OpenAI Fine-Tuning API)

**File**: `qa_dataset_openai.jsonl`

Chat completion format for OpenAI's fine-tuning API:

```json
{"messages": [
  {"role": "system", "content": "You are a Splunk expert assistant."},
  {"role": "user", "content": "What is the [default] stanza in inputs.conf used for?"},
  {"role": "assistant", "content": "The [default] stanza in inputs.conf is used to configure..."}
]}
```

**Best for**:
- OpenAI GPT-3.5/GPT-4 fine-tuning
- Chat-based instruction following
- OpenAI API integration

## Dataset Statistics

After generation, you'll see comprehensive statistics:

```
Dataset Statistics
================================================================================
Total Q&A pairs: 8,432

By source type:
  spec           :  5,124 pairs (60.8%)
  command        :  1,245 pairs (14.8%)
  pdf            :    892 pairs (10.6%)
  conf           :  1,171 pairs (13.9%)

By confidence:
  high (>=0.9)       :  6,234 pairs (73.9%)
  medium (0.7-0.9)   :  1,876 pairs (22.3%)
  low (<0.7)         :    322 pairs ( 3.8%)

Average question length: 67.3 chars
Average answer length:   342.8 chars
```

## Filtering by Confidence

The generator assigns confidence scores to each Q&A pair:

- **0.9**: High confidence (spec stanzas, clear command docs)
- **0.8**: Medium confidence (setting-specific questions)
- **0.7**: Lower confidence (PDF-extracted content)

Filter low-confidence pairs if needed:

```python
import json

# Read JSONL
with open('qa_dataset.jsonl', 'r') as f:
    pairs = [json.loads(line) for line in f]

# Filter by confidence >= 0.9
high_conf = [p for p in pairs if p['metadata']['confidence'] >= 0.9]

# Save filtered dataset
with open('qa_dataset_high_conf.jsonl', 'w') as f:
    for pair in high_conf:
        f.write(json.dumps(pair) + '\n')
```

## Using the Dataset for Fine-Tuning

### LLaMA/Mistral (Alpaca Format)

```bash
# Use the JSONL format directly
python train.py \
    --model_name meta-llama/Llama-2-7b-hf \
    --data_path qa_dataset.jsonl \
    --output_dir ./splunk-llama-7b \
    --num_epochs 3
```

### OpenAI Fine-Tuning

```bash
# Validate format
openai tools fine_tunes.prepare_data -f qa_dataset_openai.jsonl

# Upload and fine-tune
openai api fine_tunes.create \
    -t qa_dataset_openai.jsonl \
    -m gpt-3.5-turbo \
    --suffix "splunk-expert"
```

### Hugging Face Transformers

```python
from datasets import load_dataset
from transformers import AutoModelForCausalLM, AutoTokenizer, Trainer

# Load dataset
dataset = load_dataset('json', data_files='qa_dataset.jsonl')

# Load model
model = AutoModelForCausalLM.from_pretrained('mistralai/Mistral-7B-v0.1')
tokenizer = AutoTokenizer.from_pretrained('mistralai/Mistral-7B-v0.1')

# Format for training
def format_prompt(example):
    return f"### Instruction:\n{example['instruction']}\n\n### Response:\n{example['output']}"

# Train
trainer = Trainer(model=model, train_dataset=dataset, ...)
trainer.train()
```

## Customizing Q&A Generation

The generator is modular and can be extended. Edit [chat_app/qa_dataset_generator.py](../chat_app/qa_dataset_generator.py):

### Add New Question Templates

```python
# In _generate_stanza_qa method
def _generate_stanza_qa(self, stanza, conf_name, filename, metadata):
    pairs = []

    # Your custom question template
    question = f"Give me an example of {stanza.name} in {conf_name}"
    answer = f"Here's an example:\n\n[{stanza.name}]\n{stanza.content}"
    pairs.append(QAPair(question=question, answer=answer, ...))

    return pairs
```

### Change Confidence Scoring

```python
# Adjust confidence based on your criteria
confidence = 0.9 if len(stanza.content) > 100 else 0.7
```

### Add Metadata Filters

```python
# Skip certain app types
if metadata.get('app_type') == 'Scripts':
    return []  # Skip scripts
```

## File Structure

```
chainlit/
├── chat_app/
│   └── qa_dataset_generator.py       # Core Q&A generation logic
├── utilities/
│   └── generate_qa_dataset.py        # Main execution script
├── docs/
│   └── QA_DATASET_GENERATION.md      # This file
└── qa_dataset/                        # Output directory (created)
    ├── qa_dataset.jsonl               # JSONL format
    ├── qa_dataset.csv                 # CSV format
    └── qa_dataset_openai.jsonl        # OpenAI format
```

## Troubleshooting

### No Q&A Pairs Generated

**Problem**: `Total Q&A pairs: 0`

**Solutions**:
```bash
# Check input directories exist
podman exec chat_ui_app ls -la /app/ingest_specs
podman exec chat_ui_app ls -la /app/documents/repo

# Verify files are readable
podman exec chat_ui_app head /app/ingest_specs/inputs.conf.spec
```

### Import Errors

**Problem**: `ModuleNotFoundError: No module named 'chat_app.conf_parser'`

**Solutions**:
```bash
# Rebuild container with updated code
cd /opt/obsai/chatbot
bash docker_files/build_all.sh

# Or copy files directly
podman cp utilities/generate_qa_dataset.py chat_ui_app:/app/utilities/
```

### Low Quality Q&A Pairs

**Problem**: Generated questions/answers don't make sense

**Solutions**:
1. Filter by confidence: `--format csv` then review manually
2. Adjust `max_files` to process only high-quality sources first
3. Customize question templates in `qa_dataset_generator.py`
4. Skip problematic source types: `--skip-pdfs` or `--skip-commands`

### Out of Memory

**Problem**: Container runs out of memory processing large PDFs

**Solutions**:
```bash
# Process in batches
podman exec chat_ui_app python3 /app/public/generate_qa_from_container.py \
    --skip-pdfs --skip-commands  # Process specs only

podman exec chat_ui_app python3 /app/public/generate_qa_from_container.py \
    --skip-specs --skip-repo  # Process PDFs/commands only

# Merge results manually
```

## Performance

Typical generation times (on remote machine with 8 cores):

| Source Type | Files | Q&A Pairs | Time |
|-------------|-------|-----------|------|
| .conf.spec (67 files) | 67 | ~5,000 | 2-3 min |
| .conf (repo, ~200 files) | 200 | ~1,500 | 3-5 min |
| Commands (50 files) | 50 | ~150 | 1-2 min |
| PDFs (20 files) | 20 | ~800 | 5-10 min |
| **Total** | **~337** | **~7,450** | **11-20 min** |

## Best Practices

1. **Start Small**: Use `--max-files 10` to test quality before full generation
2. **Review CSV First**: Always check CSV output before using JSONL for training
3. **Filter by Confidence**: Remove low-confidence pairs for better training data
4. **Iterate**: Adjust question templates based on initial results
5. **Version Control**: Keep different versions of the dataset for comparison
6. **Document Changes**: Track any manual edits or filters applied

## Next Steps

1. **Generate your first dataset**:
   ```bash
   podman exec chat_ui_app python3 /app/public/generate_qa_from_container.py --max-files 5
   ```

2. **Review the output**:
   ```bash
   podman cp chat_ui_app:/app/public/qa_dataset/qa_dataset.csv .
   less qa_dataset.csv
   ```

3. **Generate full dataset**:
   ```bash
   podman exec chat_ui_app python3 /app/public/generate_qa_from_container.py
   ```

4. **Use for fine-tuning**:
   - See [Using the Dataset for Fine-Tuning](#using-the-dataset-for-fine-tuning) section above

## References

- [Alpaca Format](https://github.com/tatsu-lab/stanford_alpaca)
- [OpenAI Fine-Tuning](https://platform.openai.com/docs/guides/fine-tuning)
- [Hugging Face Datasets](https://huggingface.co/docs/datasets/)
- [LLaMA Fine-Tuning Guide](https://github.com/facebookresearch/llama)
