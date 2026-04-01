"""
Document Ingestor Types — Core data structures for document ingestion.

Extracted from document_ingestor.py to allow document_parsers.py to import
them without creating a circular import. Re-exported by document_ingestor.py.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class IngestedDocument:
    """Represents a parsed and chunked document."""
    source: str           # File path or URL
    source_type: str      # pdf, html, sharepoint, confluence, json, csv
    title: str = ""
    chunks: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    fingerprint: str = ""
    chunk_count: int = 0
    error: Optional[str] = None


@dataclass
class IngestionResult:
    """Summary of an ingestion operation."""
    documents_processed: int = 0
    documents_skipped: int = 0  # Already ingested (dedup)
    chunks_created: int = 0
    errors: List[str] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
