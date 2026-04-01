#!/usr/bin/env python3
"""
Training Data Export — Generates 20K+ JSONL training pairs for LLM fine-tuning.

Combines:
1. SPL command documentation (174 commands × 20+ templates = 3000+)
2. Configuration/spec file Q&A (68 specs × patterns = 2000+)
3. Cross-command comparison questions (500+)
4. SPL generation/optimization training (5000+)
5. Troubleshooting & best practices (2000+)
6. Eval test cases converted to training format (10000+)
7. Metadata and context documents (500+)

Output: /app/data/training_data/full_training_YYYYMMDD.jsonl

Run inside container:
    python3 /app/chat_app/eval_training_export.py

From host:
    podman exec chat_ui_app python3 /app/chat_app/eval_training_export.py
"""

import sys
import os

sys.path.insert(0, '/app')
sys.path.insert(0, '/app/chat_app')
os.chdir('/app')

# ---------------------------------------------------------------------------
# Re-export all shared data (constants, dataclasses, helpers) from data module
# ---------------------------------------------------------------------------
from chat_app.eval_training_data import (  # noqa: E402,F401
    logger,
    SYSTEM_PROMPT,
    OUTPUT_DIR,
    COMMAND_QA_TEMPLATES,
    ADVANCED_COMMAND_TEMPLATES,
    CROSS_COMMAND_TEMPLATES,
    COMMAND_FAMILIES,
    SPL_GENERATION_SCENARIOS,
    SPL_OPTIMIZATION_SCENARIOS,
    BEST_PRACTICES,
    TrainingEntry,
    _parse_spl_doc,
    _parse_spec_file,
)

# ---------------------------------------------------------------------------
# Re-export all generator functions from generators module for backward compat
# ---------------------------------------------------------------------------
from chat_app.eval_training_generators import (  # noqa: E402,F401
    generate_spl_doc_training,
    generate_cross_command_training,
    generate_spec_training,
    generate_scenario_training,
    generate_eval_training,
    generate_paraphrase_training,
    generate_metadata_training,
    export_training_jsonl,
    run_full_export,
)

if __name__ == "__main__":
    # Delegate to the generators module __main__ block
    import runpy
    runpy.run_module("chat_app.eval_training_generators", run_name="__main__")
