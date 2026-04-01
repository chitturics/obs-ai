"""
File Upload Handler - Process uploaded files for ingestion
Handles large files by chunking properly before embedding
"""

import tempfile
import logging
from pathlib import Path
from typing import Tuple
import hashlib

logger = logging.getLogger(__name__)


def save_uploaded_file(file_content: bytes, filename: str) -> Path:
    """
    Save uploaded file to temp directory.

    Args:
        file_content: File bytes
        filename: Original filename

    Returns:
        Path to saved temp file
    """
    # Create temp directory if doesn't exist
    temp_dir = Path(tempfile.gettempdir()) / "chainlit_uploads"
    temp_dir.mkdir(exist_ok=True)

    # Generate unique filename
    file_hash = hashlib.sha256(file_content).hexdigest()[:8]
    safe_filename = f"{file_hash}_{Path(filename).name}"
    temp_path = temp_dir / safe_filename

    # Save file
    with open(temp_path, 'wb') as f:
        f.write(file_content)

    logger.info(f"Saved uploaded file to {temp_path} (size: {len(file_content)} bytes)")
    return temp_path


def chunk_and_ingest_file(
    file_path: Path,
    vectorstore,
    collection_name: str = "assistant_memory_mxbai_v2",
    max_file_size_mb: int = 50
) -> Tuple[bool, str, int]:
    """
    Chunk and ingest a file into vector store.

    Uses ingest_documents.py logic for proper chunking regardless of file size.

    Args:
        file_path: Path to file
        vectorstore: ChromaDB vectorstore
        collection_name: Target collection
        max_file_size_mb: Maximum file size to process (default 50MB)

    Returns:
        Tuple of (success, message, chunk_count)
    """
    try:
        # Check file size
        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        if file_size_mb > max_file_size_mb:
            return False, f"File too large: {file_size_mb:.1f}MB (max: {max_file_size_mb}MB)", 0

        # Use vectorstore's index_file_to_memory for proper chunking
        try:
            from vectorstore_ingest import index_file_to_memory
        except ImportError as e:
            logger.error(f"Cannot import vectorstore: {e}")
            return False, "Ingestion module not available", 0

        logger.info(f"Ingesting {file_path.name} (size: {file_size_mb:.2f}MB)")

        ok, result = index_file_to_memory(vectorstore, str(file_path))

        if ok and isinstance(result, dict):
            chunk_count = result.get('chunks', 0)
            return True, f"Ingested {chunk_count} chunks from {file_path.name}", chunk_count
        elif ok:
            return True, f"Ingested {file_path.name}", 0
        else:
            return False, f"Ingestion failed for {file_path.name}: {result}", 0

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.error(f"Error ingesting file {file_path}: {e}")
        return False, f"Error: {str(e)}", 0

    finally:
        # Cleanup temp file
        try:
            if file_path.exists():
                file_path.unlink()
                logger.info(f"Cleaned up temp file: {file_path}")
        except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
            logger.warning(f"Could not delete temp file {file_path}: {e}")


def process_uploaded_file(
    file_content: bytes,
    filename: str,
    vectorstore,
    collection_name: str = "assistant_memory_mxbai_v2"
) -> Tuple[bool, str, int]:
    """
    High-level function to process an uploaded file.

    1. Saves file to temp location
    2. Chunks properly using ingest_documents.py
    3. Ingests to vector store
    4. Cleans up temp file

    Args:
        file_content: File bytes
        filename: Original filename
        vectorstore: ChromaDB vectorstore
        collection_name: Target collection

    Returns:
        Tuple of (success, message, chunk_count)
    """
    # Validate file type
    ext = Path(filename).suffix.lower()
    allowed_extensions = {
        '.pdf', '.txt', '.md', '.html', '.htm',
        '.conf', '.spec', '.py', '.js', '.json',
        '.xml', '.yaml', '.yml', '.log'
    }

    if ext not in allowed_extensions:
        return False, f"Unsupported file type: {ext}", 0

    try:
        # Save to temp
        temp_path = save_uploaded_file(file_content, filename)

        # Chunk and ingest
        success, message, chunk_count = chunk_and_ingest_file(
            temp_path,
            vectorstore,
            collection_name
        )

        return success, message, chunk_count

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.error(f"Error processing uploaded file {filename}: {e}")
        return False, f"Processing error: {str(e)}", 0


def get_file_info(file_content: bytes, filename: str) -> dict:
    """
    Get information about an uploaded file without ingesting.

    Args:
        file_content: File bytes
        filename: Original filename

    Returns:
        Dictionary with file information
    """
    size_bytes = len(file_content)
    size_mb = size_bytes / (1024 * 1024)
    ext = Path(filename).suffix.lower()

    # Estimate chunks
    try:
        from vectorstore import PDF_CHUNK_SIZE, CODE_CHUNK_SIZE, CHUNK_SIZE
    except ImportError:
        PDF_CHUNK_SIZE = CODE_CHUNK_SIZE = CHUNK_SIZE = 500

    if ext == '.pdf':
        estimated_chunks = max(1, size_bytes // (PDF_CHUNK_SIZE * 4))
    elif ext in {'.conf', '.spec', '.py'}:
        estimated_chunks = max(1, size_bytes // (CODE_CHUNK_SIZE * 4))
    else:
        estimated_chunks = max(1, size_bytes // (CHUNK_SIZE * 4))

    return {
        "filename": filename,
        "extension": ext,
        "size_bytes": size_bytes,
        "size_mb": round(size_mb, 2),
        "estimated_chunks": estimated_chunks,
        "can_ingest": ext in {
            '.pdf', '.txt', '.md', '.html', '.htm',
            '.conf', '.spec', '.py', '.js', '.json',
            '.xml', '.yaml', '.yml', '.log'
        }
    }


async def handle_file_upload_in_chat(file_content: bytes, filename: str, vectorstore) -> str:
    """
    Handle file upload within chat interface.

    Args:
        file_content: File bytes
        filename: Original filename
        vectorstore: ChromaDB vectorstore

    Returns:
        Message to display to user
    """
    try:
        # Get file info first
        info = get_file_info(file_content, filename)

        if not info['can_ingest']:
            return f"❌ Cannot ingest {info['extension']} files. Supported: PDF, TXT, MD, HTML, CONF, SPEC, etc."

        if info['size_mb'] > 50:
            return f"❌ File too large: {info['size_mb']}MB (max: 50MB)"

        # Process file
        success, message, chunk_count = process_uploaded_file(
            file_content,
            filename,
            vectorstore
        )

        if success:
            return f"✅ {message}\n📊 File info: {info['size_mb']}MB, ~{chunk_count} chunks"
        else:
            return f"❌ {message}"

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as e:
        logger.error(f"Error handling file upload: {e}")
        return f"❌ Upload failed: {str(e)}"


if __name__ == "__main__":
    # Test file info
    test_content = b"Test content" * 1000
    info = get_file_info(test_content, "test.conf")
    print(f"File info: {info}")
