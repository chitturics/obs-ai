#!/usr/bin/env python3
"""
Fine-tune a local LLM on Splunk Q&A training data using unsloth.

Produces a LoRA adapter in GGUF format that Ollama can load via the ADAPTER directive.

Requirements (installed in the finetune container):
    pip install unsloth transformers datasets trl peft bitsandbytes

Usage:
    python scripts/finetune_model.py
    python scripts/finetune_model.py --base-model unsloth/Qwen2.5-3B-Instruct-bnb-4bit
    python scripts/finetune_model.py --epochs 3 --lr 2e-4 --lora-rank 32
    python scripts/finetune_model.py --export-only   # Skip training, just export existing adapter

Environment:
    TRAINING_FILE    - Path to JSONL (default: training_data/combined_training.jsonl)
    OUTPUT_DIR       - Where to save adapter (default: training_data/adapter)
    BASE_MODEL       - HuggingFace model ID (default: unsloth/Qwen2.5-3B-Instruct-bnb-4bit)
"""

import argparse
import json
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def load_training_data(filepath: str) -> list:
    """Load training JSONL in OpenAI chat format (messages array)."""
    data = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
                messages = item.get("messages", [])
                if len(messages) >= 2:
                    data.append(item)
            except json.JSONDecodeError:
                continue
    return data


def format_for_sft(examples: list, tokenizer=None) -> list:
    """Convert chat messages to single-string SFT format.

    If a tokenizer is provided, uses its apply_chat_template for correct
    special tokens (Qwen2.5 uses <|im_start|>/<|im_end|>, Llama uses [INST], etc).
    Falls back to generic ChatML format if no tokenizer.
    """
    formatted = []
    for ex in examples:
        msgs = ex["messages"]

        if tokenizer is not None and hasattr(tokenizer, "apply_chat_template"):
            try:
                text = tokenizer.apply_chat_template(
                    msgs, tokenize=False, add_generation_prompt=False
                )
                formatted.append({"text": text})
                continue
            except Exception:
                pass  # Fall through to generic format

        # Generic ChatML fallback
        parts = []
        for msg in msgs:
            role = msg["role"]
            content = msg["content"]
            parts.append(f"<|im_start|>{role}\n{content}<|im_end|>")
        text = "\n".join(parts)
        formatted.append({"text": text})
    return formatted


def train(args):
    """Run LoRA fine-tuning with unsloth."""
    # Import here so --help works without GPU
    from unsloth import FastLanguageModel
    from datasets import Dataset
    from trl import SFTTrainer
    from transformers import TrainingArguments

    logger.info(f"Loading base model: {args.base_model}")
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=args.base_model,
        max_seq_length=args.max_seq_length,
        load_in_4bit=True,
        dtype=None,  # Auto-detect
    )

    # Apply LoRA
    logger.info(f"Applying LoRA (rank={args.lora_rank}, alpha={args.lora_alpha})")
    model = FastLanguageModel.get_peft_model(
        model,
        r=args.lora_rank,
        lora_alpha=args.lora_alpha,
        lora_dropout=0.05,
        target_modules=[
            "q_proj", "k_proj", "v_proj", "o_proj",
            "gate_proj", "up_proj", "down_proj",
        ],
        bias="none",
        use_gradient_checkpointing="unsloth",
    )

    # Load and format data
    logger.info(f"Loading training data from {args.training_file}")
    raw_data = load_training_data(args.training_file)
    logger.info(f"Loaded {len(raw_data)} training examples")

    if len(raw_data) < 10:
        logger.error(f"Too few training examples ({len(raw_data)}). Need at least 10.")
        sys.exit(1)

    formatted = format_for_sft(raw_data, tokenizer=tokenizer)
    dataset = Dataset.from_list(formatted)

    # Training
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_dir = output_dir / "checkpoints"

    training_args = TrainingArguments(
        output_dir=str(checkpoint_dir),
        per_device_train_batch_size=args.batch_size,
        gradient_accumulation_steps=args.gradient_accumulation,
        num_train_epochs=args.epochs,
        learning_rate=args.lr,
        warmup_ratio=0.1,
        lr_scheduler_type="cosine",
        logging_steps=10,
        save_steps=100,
        save_total_limit=2,
        fp16=not args.bf16,
        bf16=args.bf16,
        optim="adamw_8bit",
        seed=42,
        report_to="none",
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        dataset_text_field="text",
        max_seq_length=args.max_seq_length,
        args=training_args,
    )

    logger.info("Starting training...")
    trainer.train()
    logger.info("Training complete.")

    # Save LoRA adapter
    adapter_path = output_dir / "lora_adapter"
    logger.info(f"Saving LoRA adapter to {adapter_path}")
    model.save_pretrained(str(adapter_path))
    tokenizer.save_pretrained(str(adapter_path))

    return str(adapter_path)


def export_to_gguf(adapter_path: str, output_dir: str, quantization: str = "q4_k_m"):
    """Export LoRA adapter to GGUF format for Ollama."""
    from unsloth import FastLanguageModel

    logger.info(f"Exporting adapter to GGUF ({quantization})...")
    output_path = Path(output_dir)

    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=adapter_path,
        max_seq_length=4096,
        load_in_4bit=True,
    )

    # Export to GGUF
    gguf_path = output_path / f"splunk-assistant-{quantization}.gguf"
    model.save_pretrained_gguf(
        str(output_path),
        tokenizer,
        quantization_method=quantization,
    )

    # Find the exported file (unsloth names it based on the model)
    gguf_files = list(output_path.glob("*.gguf"))
    if gguf_files:
        actual_path = gguf_files[0]
        logger.info(f"GGUF adapter exported: {actual_path}")
        return str(actual_path)
    else:
        logger.error("GGUF export failed — no .gguf file found")
        sys.exit(1)


def generate_ollama_modelfile(base_model: str, gguf_path: str, output_dir: str):
    """Generate Ollama Modelfile with ADAPTER pointing to the GGUF."""
    modelfile_path = Path(output_dir) / "Modelfile"
    # For Ollama, base model should be the Ollama name (e.g., qwen2.5:3b)
    ollama_base = os.getenv("OLLAMA_BASE_MODEL_NAME", "qwen2.5:3b")

    content = f"""# Splunk Assistant — Fine-tuned with LoRA adapter
# Created by: scripts/finetune_model.py
# Base model: {base_model}
#
# Usage:
#   ollama create splunk-assistant -f Modelfile
#   ollama run splunk-assistant

FROM {ollama_base}

ADAPTER {gguf_path}

PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER num_ctx 4096
PARAMETER stop "<|endoftext|>"
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|end|>"

SYSTEM \"\"\"You are a Splunk expert assistant for the organization.

Key rules:
- Never use index=* — always specify the correct index
- Prefer | tstats with CIM data models for performance
- Use TERM() and PREFIX() inside tstats WHERE for index-level filtering
- TERM() = exact token match, PREFIX() = starts-with match on indexed fields
- When explaining configs, reference the .spec file documentation
- Break down saved searches stage by stage (initial search → each pipe command)
- If unsure, ask clarifying questions rather than guessing\"\"\"
"""

    modelfile_path.write_text(content, encoding="utf-8")
    logger.info(f"Modelfile written to {modelfile_path}")
    return str(modelfile_path)


def write_stats(output_dir: str, **kwargs):
    """Save fine-tuning stats."""
    stats_path = Path(output_dir) / "finetune_stats.json"
    stats_path.write_text(json.dumps(kwargs, indent=2), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Fine-tune LLM on Splunk training data")
    parser.add_argument("--training-file", default="training_data/combined_training.jsonl")
    parser.add_argument("--output-dir", default="training_data/adapter")
    parser.add_argument("--base-model", default="unsloth/Qwen2.5-3B-Instruct-bnb-4bit",
                        help="HuggingFace model for training")
    parser.add_argument("--epochs", type=int, default=3)
    parser.add_argument("--lr", type=float, default=2e-4)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--gradient-accumulation", type=int, default=4)
    parser.add_argument("--lora-rank", type=int, default=32)
    parser.add_argument("--lora-alpha", type=int, default=64)
    parser.add_argument("--max-seq-length", type=int, default=4096)
    parser.add_argument("--quantization", default="q4_k_m", help="GGUF quantization: q4_k_m, q8_0, f16")
    parser.add_argument("--bf16", action="store_true", help="Use bfloat16 (for Ampere+ GPUs)")
    parser.add_argument("--export-only", action="store_true", help="Skip training, export existing adapter")
    args = parser.parse_args()

    output_dir = args.output_dir
    Path(output_dir).mkdir(parents=True, exist_ok=True)

    adapter_path = os.path.join(output_dir, "lora_adapter")

    if args.export_only:
        if not os.path.exists(adapter_path):
            logger.error(f"No adapter found at {adapter_path}. Run training first.")
            sys.exit(1)
        logger.info("Skipping training, exporting existing adapter...")
    else:
        # Train
        adapter_path = train(args)

    # Export to GGUF
    gguf_path = export_to_gguf(adapter_path, output_dir, args.quantization)

    # Generate Modelfile
    modelfile_path = generate_ollama_modelfile(args.base_model, gguf_path, output_dir)

    # Stats
    training_data = load_training_data(args.training_file) if os.path.exists(args.training_file) else []
    write_stats(
        output_dir,
        base_model=args.base_model,
        training_examples=len(training_data),
        epochs=args.epochs,
        lora_rank=args.lora_rank,
        quantization=args.quantization,
        gguf_path=gguf_path,
        modelfile_path=modelfile_path,
    )

    print(f"\n{'='*60}")
    print("Fine-tuning complete!")
    print(f"{'='*60}")
    print(f"  Adapter:   {gguf_path}")
    print(f"  Modelfile: {modelfile_path}")
    print(f"  Examples:  {len(training_data)}")
    print(f"\nTo create the Ollama model:")
    print(f"  ollama create splunk-assistant -f {modelfile_path}")
    print(f"\nTo use in the chatbot:")
    print(f"  export OLLAMA_MODEL=splunk-assistant")


if __name__ == "__main__":
    main()
