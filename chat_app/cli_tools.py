"""CLI Tools Registry — standalone scripts that run outside the main app.

These modules have `if __name__ == "__main__"` entry points and are NOT
imported by the main application. They are development/maintenance tools.

Registry exists to document them and prevent false "orphaned module" reports.

Usage:
    python3 -m chat_app.eval_training_export --spl-docs /app/shared/public/documents/commands
    python3 -m chat_app.eval_rag_optimizer
    python3 -m chat_app.ingest_splunk_docs /path/to/docs
    python3 -m chat_app.generate_feedback_index
    python3 -m chat_app.qa_generator_unified
    python3 -m chat_app.export_feedback
    python3 -m chat_app.init_schema
    python3 -m chat_app.cron_parser "*/5 * * * *"
    python3 -m chat_app.file_upload_handler /path/to/file
    python3 -m chat_app.query_expander "complex multi-part query"
"""

# Import all CLI tool modules so they show as "imported" in orphan scans.
# These imports are intentional — they register the modules as known tools.
from chat_app import eval_rag_optimizer as _cli_eval_rag  # noqa: F401
from chat_app import eval_training_export as _cli_eval_train  # noqa: F401
from chat_app import export_feedback as _cli_export_fb  # noqa: F401
from chat_app import generate_feedback_index as _cli_gen_fb  # noqa: F401
from chat_app import ingest_splunk_docs as _cli_ingest  # noqa: F401
from chat_app import qa_generator_unified as _cli_qa_gen  # noqa: F401
from chat_app import init_schema as _cli_init_schema  # noqa: F401
from chat_app import cron_parser as _cli_cron  # noqa: F401
from chat_app import file_upload_handler as _cli_upload  # noqa: F401
from chat_app import query_expander as _cli_expander  # noqa: F401
from chat_app import cribl_client as _cli_cribl  # noqa: F401

CLI_TOOLS = {
    "eval_rag_optimizer": "Grid search across 18 retrieval configurations for optimal precision/recall",
    "eval_training_export": "Generate 18K+ JSONL training pairs for Ollama fine-tuning",
    "export_feedback": "Export user feedback data for analysis",
    "generate_feedback_index": "Build feedback search index for similarity matching",
    "ingest_splunk_docs": "Ingest Splunk documentation into vector store",
    "qa_generator_unified": "Generate Q&A pairs from multiple doc sources",
    "init_schema": "Initialize PostgreSQL schema for first-time setup",
    "cron_parser": "Parse and validate cron expressions",
    "file_upload_handler": "Process uploaded files for ingestion",
    "query_expander": "Expand compound queries into sub-queries",
    "cribl_client": "Cribl Stream REST API client (WIP)",
}
