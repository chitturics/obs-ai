# LLM Fine-Tuning Guide for Splunk Knowledge

## Overview

Fine-tuning allows the LLM to learn Splunk knowledge directly, reducing reliance on RAG retrieval and improving response speed/accuracy.

## Why Fine-Tune?

**Benefits**:
- **Faster responses**: No RAG retrieval needed for basic questions
- **More accurate**: Model "knows" Splunk internally
- **Offline capable**: Less dependent on document availability
- **Lower latency**: Direct inference without vector search

**When to use**:
- Common questions about Splunk configs
- Standard SPL command usage
- Best practices that don't change often

**When NOT to use** (still use RAG):
- Organization-specific configs in your repo
- Recently updated documentation
- Complex multi-step troubleshooting

## Step 1: Generate Training Dataset

The v3.2.0 training pipeline generates **19,717+ training entries** from 7 sources:

```bash
# Run inside the container (recommended)
podman exec chat_ui_app python3 /app/chat_app/eval_training_export.py \
    --spl-docs /app/shared/public/documents/commands \
    --specs /app/shared/public/documents/specs

# Or from host (requires dependencies)
python chat_app/eval_training_export.py --spl-docs spl_docs --specs documents/specs
```

**Training data sources**:
| Source | Entries | Description |
|--------|---------|-------------|
| SPL docs | ~4,924 | Command syntax, arguments, examples |
| Cross-command | ~480 | Multi-command pipeline patterns |
| Spec files | ~1,467 | Configuration file settings |
| Curated scenarios | 53 | Real-world use cases |
| Eval test cases | ~10,141 | Query/answer pairs |
| Paraphrases | ~3,440 | Varied phrasings |
| Metadata | ~45 | Rules and guidelines |

**Output**: `/app/data/training_data/full_training_YYYYMMDD.jsonl`

**Dataset format** (JSONL — Ollama chat-tuning compatible):
```json
{"messages": [{"role": "system", "content": "You are an expert Splunk admin..."}, {"role": "user", "content": "What does maxKBps do in inputs.conf?"}, {"role": "assistant", "content": "In inputs.conf, maxKBps limits..."}]}
```

## Step 2: Choose Fine-Tuning Method

### Option A: Ollama Built-in Fine-Tuning (Recommended)

**Prerequisites**:
- Ollama 0.3.0+ installed
- GPU with sufficient VRAM (8GB+ recommended for 3B models)
- Training dataset in JSONL format

**Process**:

1. **Create adapter using Ollama's training API**:
```bash
# Start training (this takes time - hours to days depending on dataset size)
curl http://localhost:11430/api/train -d '{
  "model": "qwen2.5:3b",
  "dataset": "splunk_finetune_dataset.jsonl",
  "output": "splunk-assistant-adapter",
  "epochs": 3,
  "learning_rate": 0.0001,
  "batch_size": 4
}'
```

2. **Monitor training progress**:
```bash
# Check training logs
tail -f ~/.ollama/logs/train.log
```

3. **Create model with adapter**:
```bash
# Create Modelfile
cat > Modelfile <<EOF
FROM qwen2.5:3b
ADAPTER ./splunk-assistant-adapter
SYSTEM """You are a Splunk administration expert with comprehensive knowledge of Splunk Enterprise configurations, SPL (Search Processing Language), and best practices.

You have been trained on official Splunk documentation including:
- Configuration file specifications (.conf.spec files)
- SPL command reference
- Common configuration patterns

Provide accurate, detailed answers about Splunk administration, always citing specific configuration files or SPL commands when relevant.
"""
PARAMETER temperature 0.3
PARAMETER top_p 0.9
PARAMETER top_k 40
EOF

# Create the fine-tuned model
ollama create splunk-assistant -f Modelfile

# Test it
ollama run splunk-assistant "What does maxKBps do in inputs.conf?"
```

### Option B: External Fine-Tuning (More Control)

Use tools like **Unsloth**, **Axolotl**, or **LLaMA-Factory** for more control.

**Example with Unsloth** (faster training):

```python
# install_and_train.py
from unsloth import FastLanguageModel
import torch
from datasets import load_dataset

# Load base model
model, tokenizer = FastLanguageModel.from_pretrained(
    model_name = "unsloth/Qwen2.5-3B-Instruct",
    max_seq_length = 2048,
    dtype = None,
    load_in_4bit = True,
)

# Prepare model for LoRA training
model = FastLanguageModel.get_peft_model(
    model,
    r = 16,  # LoRA rank
    target_modules = ["q_proj", "k_proj", "v_proj", "o_proj"],
    lora_alpha = 16,
    lora_dropout = 0,
    bias = "none",
    use_gradient_checkpointing = True,
)

# Load dataset
dataset = load_dataset("json", data_files="splunk_finetune_dataset.jsonl")

# Format for training
def formatting_prompts_func(examples):
    instructions = examples["instruction"]
    inputs = examples["input"]
    outputs = examples["output"]
    texts = []
    for instruction, input, output in zip(instructions, inputs, outputs):
        text = f"### Instruction:\n{instruction}\n\n"
        if input:
            text += f"### Input:\n{input}\n\n"
        text += f"### Response:\n{output}"
        texts.append(text)
    return {"text": texts}

dataset = dataset.map(formatting_prompts_func, batched=True)

# Train
from trl import SFTTrainer
from transformers import TrainingArguments

trainer = SFTTrainer(
    model = model,
    tokenizer = tokenizer,
    train_dataset = dataset["train"],
    dataset_text_field = "text",
    max_seq_length = 2048,
    args = TrainingArguments(
        per_device_train_batch_size = 2,
        gradient_accumulation_steps = 4,
        warmup_steps = 10,
        max_steps = 1000,
        learning_rate = 2e-4,
        fp16 = not torch.cuda.is_bf16_supported(),
        bf16 = torch.cuda.is_bf16_supported(),
        logging_steps = 1,
        optim = "adamw_8bit",
        weight_decay = 0.01,
        lr_scheduler_type = "linear",
        seed = 3407,
        output_dir = "outputs",
    ),
)

trainer.train()

# Save adapter
model.save_pretrained("splunk_adapter")
tokenizer.save_pretrained("splunk_adapter")

# Convert to GGUF for Ollama
model.save_pretrained_gguf("splunk_model", tokenizer, quantization_method="q4_k_m")
```

**Run training**:
```bash
pip install unsloth xformers trl
python install_and_train.py
```

**Import to Ollama**:
```bash
# Create Modelfile pointing to GGUF
cat > Modelfile <<EOF
FROM ./splunk_model/model-q4_k_m.gguf
SYSTEM """You are a Splunk expert..."""
EOF

ollama create splunk-assistant -f Modelfile
```

## Step 3: Configure Chainlit to Use Fine-Tuned Model

Edit `docker_files/start_all.sh`:

```bash
# Change this line (around line 82-93):
# OLD
APP_OLLAMA_MODEL="qwen2.5:3b"

# NEW - Use your fine-tuned model
APP_OLLAMA_MODEL="splunk-assistant"
```

Or set environment variable:
```bash
export ACTIVE_PROFILE=LLM_CUSTOM
export OLLAMA_MODEL=splunk-assistant
bash docker_files/start_all.sh
```

## Step 4: Hybrid Approach (Recommended)

**Best practice**: Use fine-tuned model + RAG together:

1. **Fine-tuned model handles**: Standard Splunk questions, common configs, SPL basics
2. **RAG handles**: Your org's specific configs, recent updates, complex troubleshooting

**Implementation** (already in place):
- The app will use the fine-tuned model as its LLM
- RAG still provides context from your repo/docs
- Model generates better responses because it "understands" Splunk natively

## Step 5: Evaluate Results

**Test queries**:
```bash
# Test basic knowledge (should NOT need RAG)
ollama run splunk-assistant "What is props.conf used for?"

# Test specific config (WILL need RAG from your repo)
# (Run through Chainlit app which combines model + RAG)
curl http://localhost:8000 -d "What's in my savedsearches.conf?"
```

**Quality checks**:
1. ✅ Answers basic Splunk questions without hallucination
2. ✅ Cites correct config file names
3. ✅ Explains SPL commands accurately
4. ✅ Still uses RAG for org-specific questions

## Training Tips

**Dataset quality matters**:
- ✅ Clean, accurate Q&A pairs
- ✅ Diverse question types
- ✅ Include examples and explanations
- ❌ Avoid contradictions
- ❌ Don't include outdated info

**Hyperparameters**:
- **Learning rate**: 1e-4 to 2e-4 (lower = safer)
- **Epochs**: 3-5 (more = overfitting risk)
- **Batch size**: 2-8 (limited by VRAM)
- **LoRA rank**: 8-32 (higher = more capacity)

**Hardware requirements**:
- **3B model**: 8GB+ VRAM (RTX 3060/4060)
- **7B model**: 16GB+ VRAM (RTX 4080/A4000)
- **Training time**: 1-8 hours (depends on dataset size)

## Updating the Fine-Tuned Model

When Splunk releases new docs:

```bash
# 1. Regenerate dataset with new docs
python utilities/generate_finetune_dataset.py
```

## Troubleshooting

**"Out of memory during training"**:
- Reduce batch size
- Use gradient accumulation
- Enable gradient checkpointing
- Use 4-bit quantization (bitsandbytes)

**"Model gives wrong answers"**:
- Check dataset quality
- Reduce learning rate
- Train for fewer epochs
- Add more diverse examples

**"Training too slow"**:
- Use Unsloth (2-5x faster)
- Enable flash attention
- Use mixed precision (fp16/bf16)
- Reduce sequence length

## Resources

- **Ollama Training**: https://ollama.com/blog/fine-tuning
- **Unsloth**: https://github.com/unslothai/unsloth
- **LLaMA-Factory**: https://github.com/hiyouga/LLaMA-Factory
- **LoRA paper**: https://arxiv.org/abs/2106.09685

## Summary

```bash
# Complete workflow
# From the root of the project

# 1. Generate dataset
python utilities/generate_finetune_dataset.py

# 2. Train model (choose method)
# ... (see above)

# 3. Update config
export OLLAMA_MODEL=splunk-assistant

# 4. Deploy
bash docker_files/start_all.sh --profile LLM_CUSTOM

# 5. Test
curl http://localhost:8000
```

Now your chatbot has **native Splunk knowledge** + **RAG for your org's specifics**!
