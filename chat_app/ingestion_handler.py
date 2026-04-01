"""
Document ingestion handlers for the Splunk Assistant.

Handles file uploads, URL fetching, text block indexing, and inline directives.
"""
import os
import re
import logging
from pathlib import Path
from typing import List, Tuple

import chainlit as cl
from vectorstore import fingerprint_file, has_fingerprint
from vectorstore_ingest import (
    index_file_to_memory,
    index_url_to_memory,
    index_text_to_memory,
)
from feedback_logger import log_doc_ingest

logger = logging.getLogger(__name__)


async def process_file_upload(
    file_path: str,
    file_name: str,
    vector_store,
) -> Tuple[bool, str]:
    """
    Process a single file upload and index it to the vector store.

    Returns:
        Tuple of (success, message)
    """
    try:
        if not os.path.exists(file_path):
            return False, f"File not found: `{file_name}`"

        fp = fingerprint_file(file_path)
        if fp and has_fingerprint(vector_store, fp):
            return True, f"`{file_name}` already in knowledge base"

        ok, result = await cl.make_async(index_file_to_memory)(vector_store, file_path)

        if ok and isinstance(result, dict):
            summary_msg = (
                f"**Indexed File:** `{result.get('file_name', file_name)}`\n"
                f"- Type: {result.get('type', 'unknown')}\n"
                f"- Chunks: {result.get('chunks', 0)}\n"
                f"- Preview: {result.get('preview', '')[:150]}..."
            )
            return True, summary_msg
        elif ok:
            return True, f"Indexed `{file_name}`"
        else:
            return False, f"Failed to index `{file_name}`: {result}"

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error(f"[FILE_UPLOAD] Error processing {file_name}: {exc}")
        return False, f"Error with `{file_name}`: {exc}"


async def process_url_upload(
    url: str,
    vector_store,
) -> Tuple[bool, str]:
    """
    Process a single URL and index it to the vector store.

    Returns:
        Tuple of (success, message)
    """
    try:
        url = url.strip()
        ok, result = await cl.make_async(index_url_to_memory)(vector_store, url)

        if ok and isinstance(result, dict):
            summary_msg = (
                f"**Indexed URL:** `{result.get('url', url)}`\n"
                f"- Type: {result.get('type', 'unknown')}\n"
                f"- Chunks: {result.get('chunks', 0)}\n"
                f"- Preview: {result.get('preview', '')[:150]}..."
            )
            return True, summary_msg
        elif ok:
            return True, f"Indexed URL: `{url}` (already indexed)"
        else:
            return False, f"Failed to index URL `{url}`: {result}"

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error(f"[URL_UPLOAD] Error processing {url}: {exc}")
        return False, f"Error with URL `{url}`: {exc}"


async def process_text_upload(
    text: str,
    label: str,
    vector_store,
) -> Tuple[bool, str]:
    """
    Process a text block and index it to the vector store.

    Returns:
        Tuple of (success, message)
    """
    try:
        ok, result = await cl.make_async(index_text_to_memory)(vector_store, text, label=label)

        if ok and isinstance(result, dict):
            summary_msg = (
                f"**Indexed Text Block:**\n"
                f"- Chunks: {result.get('chunks', 0)}\n"
                f"- Preview: {result.get('preview', '')[:150]}..."
            )
            return True, summary_msg
        elif ok:
            return True, "Indexed text block (already indexed)"
        else:
            return False, f"Failed to index text: {result}"

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.error(f"[TEXT_UPLOAD] Error processing text block: {exc}")
        return False, f"Error with text block: {exc}"


async def process_ingestion_directives(
    user_input: str,
    vector_store,
    engine,
    username: str,
    thread_id: str,
    search_roots: List[str] = None,
) -> Tuple[str, List[str]]:
    """
    Process read_url, read_file, read_text directives.
    Returns (cleaned_input, directive_messages).
    """
    if search_roots is None:
        search_roots = []

    directive_msgs = []

    # Extract directives
    read_url_matches = re.findall(r'read_url\s*:\s*(\S+)', user_input, re.IGNORECASE)
    read_file_matches = re.findall(r'read_file\s*:\s*(\S+)', user_input, re.IGNORECASE)
    read_text_raw = re.findall(r'read_text\s*:\s*(?:"([^"]+)"|(\S+))', user_input, re.IGNORECASE)
    read_text_matches = [quoted or unquoted for quoted, unquoted in read_text_raw]

    # Process URLs
    for url in read_url_matches:
        ok, msg = await process_url_upload(url, vector_store)
        directive_msgs.append(msg)
        if ok:
            await log_doc_ingest(engine, username, thread_id, url.strip(), "url", None)

    # Process files
    for file_path in read_file_matches:
        candidate = Path(file_path.strip())
        if not candidate.is_absolute():
            for root_dir in search_roots:
                alt = Path(root_dir) / file_path.strip()
                if alt.exists():
                    candidate = alt
                    break

        if candidate.exists():
            ok, msg = await process_file_upload(str(candidate), candidate.name, vector_store)
            directive_msgs.append(msg)
            if ok:
                fp = fingerprint_file(str(candidate))
                await log_doc_ingest(engine, username, thread_id, f"file://{candidate}", "file", fp)
        else:
            directive_msgs.append(f"File not found: `{file_path}`")

    # Process text blocks
    for idx, text_block in enumerate(read_text_matches, 1):
        label = f"read_text_{idx}"
        ok, msg = await process_text_upload(text_block, label, vector_store)
        directive_msgs.append(msg)

    # Clean directives from input
    cleaned = user_input
    for pattern in [r'read_url\s*:\s*\S+', r'read_file\s*:\s*\S+', r'read_text\s*:\s*"[^"]+"', r'read_text\s*:\s*\S+']:
        cleaned = re.sub(pattern, '', cleaned, flags=re.IGNORECASE)

    return cleaned.strip(), directive_msgs


async def handle_attachments(message: cl.Message, vector_store, engine, username, thread_id):
    """Handles file uploads and URL ingestions."""
    if message.elements:
        for el in message.elements:
            name = getattr(el, "name", "file")
            path = getattr(el, "path", None)
            url_el = getattr(el, "url", None)
            try:
                if path and os.path.exists(path):
                    ok, msg = await process_file_upload(path, name, vector_store)
                    await cl.Message(content=msg).send()
                    if ok:
                        fp = fingerprint_file(path)
                        await log_doc_ingest(engine, username, thread_id, f"file://{path}", "file", fp)
                elif url_el:
                    ok, msg = await process_url_upload(url_el, vector_store)
                    await cl.Message(content=msg).send()
                    if ok:
                        await log_doc_ingest(engine, username, thread_id, url_el, "url", None)
            except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
                await cl.Message(content=f"Error with `{name}`: {exc}").send()
    from helper import extract_urls
    urls = extract_urls(message.content or "")
    for url in urls:
        ok, _ = await process_url_upload(url, vector_store)
        if ok:
            await log_doc_ingest(engine, username, thread_id, url, "url", None)
