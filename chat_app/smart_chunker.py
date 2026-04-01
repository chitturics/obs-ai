"""
Smart Chunking Module - File-Type Aware Text Splitting
========================================================

Provides optimal chunking strategies for different document types:
- Token-based sizing (vs character-based) for accurate embedding model alignment
- Semantic chunking for .conf/.spec files (stanza-aware)
- Markdown header preservation for .md files
- Language-aware code splitting for .py/.js files
- Fallback to recursive splitting for general documents

Usage:
    from chat_app.smart_chunker import get_smart_splitter, chunk_text_smart

    splitter = get_smart_splitter(file_path)
    chunks = splitter.split_text(text)
"""

import os
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable
import logging

# Lazy imports to avoid dependency issues
_tiktoken = None
_RecursiveCharacterTextSplitter = None
_MarkdownHeaderTextSplitter = None
_Language = None

logger = logging.getLogger(__name__)


def _import_dependencies():
    """Lazy import of dependencies to avoid circular imports."""
    global _tiktoken, _RecursiveCharacterTextSplitter, _MarkdownHeaderTextSplitter, _Language

    if _tiktoken is None:
        try:
            import tiktoken
            _tiktoken = tiktoken
        except ImportError:
            logger.warning("tiktoken not available - falling back to character-based chunking")
            _tiktoken = False

    if _RecursiveCharacterTextSplitter is None:
        from langchain_text_splitters import RecursiveCharacterTextSplitter
        _RecursiveCharacterTextSplitter = RecursiveCharacterTextSplitter

    if _MarkdownHeaderTextSplitter is None:
        try:
            from langchain_text_splitters import MarkdownHeaderTextSplitter
            _MarkdownHeaderTextSplitter = MarkdownHeaderTextSplitter
        except ImportError:
            logger.warning("MarkdownHeaderTextSplitter not available")
            _MarkdownHeaderTextSplitter = False

    if _Language is None:
        try:
            from langchain_text_splitters import Language
            _Language = Language
        except ImportError:
            logger.warning("Language not available for code-aware splitting")
            _Language = False


def get_token_counter() -> Optional[Callable[[str], int]]:
    """
    Returns a token counting function using tiktoken (cl100k_base encoding).
    Falls back to character-based counting if tiktoken unavailable.

    Returns:
        Callable that takes text and returns token count, or None for char-based.
    """
    _import_dependencies()

    if _tiktoken and _tiktoken is not False:
        try:
            encoding = _tiktoken.get_encoding("cl100k_base")
            return lambda text: len(encoding.encode(text, disallowed_special=()))
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning(f"Failed to initialize tiktoken: {e}")

    return None  # Fallback to character-based


def get_smart_splitter(
    file_path: Optional[Path] = None,
    file_type: Optional[str] = None,
    chunk_size: int = 400,  # In tokens (not characters!)
    chunk_overlap: int = 50,
    **kwargs
):
    """
    Returns optimal text splitter based on file type.

    Args:
        file_path: Path object to determine file type from extension
        file_type: Explicit file type override ('.md', '.py', '.conf', etc.)
        chunk_size: Target chunk size in TOKENS (default 400 tokens)
        chunk_overlap: Overlap size in TOKENS (default 50 tokens)
        **kwargs: Additional splitter-specific arguments

    Returns:
        Configured text splitter instance
    """
    _import_dependencies()

    # Determine file type
    if file_type is None and file_path:
        file_type = file_path.suffix.lower()

    # Get token counter
    token_counter = get_token_counter()

    # For .conf and .spec files: Use stanza-aware parser (returns pre-chunked text)
    if file_type in {".conf", ".spec"}:
        logger.info(f"Using stanza-aware chunking for {file_type} file")
        # Note: conf_parser.parse_conf_file_with_chunks() should be called directly
        # by the ingestion script. We return a passthrough splitter here.
        return PassthroughSplitter()

    # For .md files: Use markdown header-aware splitting
    if file_type == ".md" and _MarkdownHeaderTextSplitter:
        logger.info("Using markdown header-aware chunking")
        return get_markdown_splitter(chunk_size, chunk_overlap, token_counter)

    # For Python files: Use language-aware splitting
    if file_type == ".py" and _Language:
        logger.info("Using Python language-aware chunking")
        return _RecursiveCharacterTextSplitter.from_language(
            language=_Language.PYTHON,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=token_counter
        )

    # For JavaScript/TypeScript: Use language-aware splitting
    if file_type in {".js", ".ts", ".jsx", ".tsx"} and _Language:
        logger.info("Using JavaScript language-aware chunking")
        return _RecursiveCharacterTextSplitter.from_language(
            language=_Language.JS,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=token_counter
        )

    # Default: Token-based recursive splitting
    logger.info(f"Using token-based recursive chunking for {file_type or 'unknown'} file")
    return _RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=token_counter,
        separators=["\n\n", "\n", " ", ""]
    )


def get_markdown_splitter(chunk_size: int, chunk_overlap: int, token_counter: Optional[Callable]):
    """
    Creates a two-stage markdown splitter:
    1. Split by headers to preserve document structure
    2. Further split large sections by size
    """
    _import_dependencies()

    if not _MarkdownHeaderTextSplitter:
        # Fallback to regular splitting
        return _RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            length_function=token_counter,
            separators=["\n\n", "\n", " ", ""]
        )

    # Stage 1: Split by headers
    headers_to_split_on = [
        ("#", "h1"),
        ("##", "h2"),
        ("###", "h3"),
    ]

    header_splitter = _MarkdownHeaderTextSplitter(
        headers_to_split_on=headers_to_split_on,
        strip_headers=False  # Keep headers for context
    )

    # Stage 2: Size-based splitting within sections
    size_splitter = _RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        length_function=token_counter,
        separators=["\n\n", "\n", " ", ""]
    )

    return HierarchicalMarkdownSplitter(header_splitter, size_splitter, chunk_size, token_counter)


class HierarchicalMarkdownSplitter:
    """
    Two-stage markdown splitter that preserves headers and splits large sections.
    """

    def __init__(self, header_splitter, size_splitter, max_size, token_counter):
        self.header_splitter = header_splitter
        self.size_splitter = size_splitter
        self.max_size = max_size
        self.token_counter = token_counter or len

    def split_text(self, text: str) -> List[str]:
        """Split text by headers first, then by size if needed."""
        # Split by headers
        header_chunks = self.header_splitter.split_text(text)

        final_chunks = []
        for chunk in header_chunks:
            # Get text content (header_splitter returns Documents with metadata)
            chunk_text = chunk.page_content if hasattr(chunk, 'page_content') else chunk

            # If chunk is within size limit, keep it
            if self.token_counter(chunk_text) <= self.max_size:
                final_chunks.append(chunk_text)
            else:
                # Split large sections further
                sub_chunks = self.size_splitter.split_text(chunk_text)
                final_chunks.extend(sub_chunks)

        return final_chunks

    def create_documents(self, texts: List[str], metadatas: Optional[List[dict]] = None):
        """Create documents with metadata."""
        from langchain_core.documents import Document

        documents = []
        for i, text in enumerate(texts):
            chunks = self.split_text(text)
            metadata = metadatas[i] if metadatas else {}

            for j, chunk in enumerate(chunks):
                doc_metadata = metadata.copy()
                doc_metadata.update({
                    "chunk_index": j,
                    "total_chunks": len(chunks)
                })
                documents.append(Document(page_content=chunk, metadata=doc_metadata))

        return documents


class PassthroughSplitter:
    """
    Passthrough splitter for pre-chunked content (e.g., .conf files).
    Returns input as-is since chunking is handled elsewhere.
    """

    def split_text(self, text: str) -> List[str]:
        """Return text as single chunk."""
        return [text]

    def create_documents(self, texts: List[str], metadatas: Optional[List[dict]] = None):
        """Create documents with metadata."""
        from langchain_core.documents import Document
        return [
            Document(page_content=text, metadata=metadatas[i] if metadatas else {})
            for i, text in enumerate(texts)
        ]


def chunk_text_smart(
    text: str,
    file_path: Optional[Path] = None,
    file_type: Optional[str] = None,
    chunk_size: int = 400,
    chunk_overlap: int = 50,
    metadata: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """
    Convenience function to chunk text with optimal strategy and return dicts.

    Args:
        text: Text to chunk
        file_path: Optional file path to infer type
        file_type: Explicit file type ('.md', '.py', etc.)
        chunk_size: Target size in tokens
        chunk_overlap: Overlap in tokens
        metadata: Optional metadata to attach to each chunk

    Returns:
        List of dicts with 'text' and 'metadata' keys
    """
    splitter = get_smart_splitter(file_path, file_type, chunk_size, chunk_overlap)
    chunks = splitter.split_text(text)

    result = []
    for i, chunk in enumerate(chunks):
        chunk_meta = (metadata or {}).copy()
        chunk_meta.update({
            "chunk_index": i,
            "total_chunks": len(chunks)
        })
        result.append({
            "text": chunk,
            "metadata": chunk_meta
        })

    return result


# Environment variable overrides
DEFAULT_CHUNK_SIZE = int(os.getenv("CHUNK_SIZE_TOKENS", "400"))
DEFAULT_CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP_TOKENS", "50"))
