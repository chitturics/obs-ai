# Splunk AI Assistant Fine-Tuning Bundle

This bundle contains:

- `training.jsonl` — Instruction/response pairs for fine-tuning a Splunk-aware assistant.
- `metadata.json` — Declarative description of indexes, fields, and lookups.
- `splunk_rules.md` — Guardrails and behavioral rules (no index=*, prefer tstats, etc.).
- `rag_context.md` — Extra context for a RAG pipeline.
- `run_finetune.sh` — Example OpenAI CLI script to kick off fine-tuning.
- `ollama_modelfile` — Example Modelfile snippet for use with Ollama.

## Training Format

`training.jsonl` is in the common instruction-tuning format:

```jsonl
{"instruction": "User question here", "response": "Ideal Splunk-aware answer here"}
```

You can upload this directly to:

- OpenAI fine-tuning,
- or convert/adapt for other frameworks.

## Key Design Decisions

- **Never** use `index=*` in any example.
- Always show **tstats** patterns when possible.
- Use **TERM()** and **PREFIX()** where appropriate.
- Encourage **CIM datamodel** usage.
- Use environment-specific entities:
  - Indexes: `snow`, `idc_asa`, `pan_logs`, `network`, `wineventlog`, `linux_auth`, `web`, `api`.
  - Lookups: `infoblox_networks_lite`, `unit_id_list`.
  - Fields: `unit_id`, `circuit`, `network`, `u_business_unit`, `u_business_service`.

## How to Use This Bundle

1. Review `splunk_rules.md` and adjust if your standards differ.
2. Append your own internal Q&A to `training.jsonl` if desired.
3. Upload `training.jsonl` to your fine-tuning platform.
4. Optionally serve `rag_context.md` and `metadata.json` via a vector store and RAG pipeline.

See `run_finetune.sh` and `ollama_modelfile` for examples.
