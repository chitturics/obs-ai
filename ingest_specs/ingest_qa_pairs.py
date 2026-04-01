#!/usr/bin/env python3
"""
Ingest Q&A pairs from JSONL files into ChromaDB.

Loads the generated Q&A dataset (from scripts/generate_all_qa.py) into the
primary ChromaDB collection so the chatbot can retrieve spec/conf/command
knowledge when answering user queries.

Each Q&A pair is stored as a single chunk containing the question + answer,
with the question text used for embedding similarity matching.

Usage:
    python ingest_specs/ingest_qa_pairs.py
    python ingest_specs/ingest_qa_pairs.py --file qa_dataset/all_qa.jsonl
    python ingest_specs/ingest_qa_pairs.py --collection splunk_qa_knowledge
    python ingest_specs/ingest_qa_pairs.py --dry-run

Environment Variables:
    CHROMA_HTTP_URL: ChromaDB server URL (default: http://127.0.0.1:8001)
    OLLAMA_BASE_URL: Ollama API URL (default: http://127.0.0.1:11434)
    OLLAMA_EMBED_MODEL: Embedding model (default: mxbai-embed-large)
    CHROMA_COLLECTION: Target collection (default: from vectorstore config)
"""

import argparse
import hashlib
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Add chat_app to path for vectorstore imports
sys.path.insert(0, str(Path(__file__).parent.parent / "chat_app"))

DEFAULT_QA_FILE = str(Path(__file__).parent.parent / "qa_dataset" / "all_qa.jsonl")
BATCH_SIZE = 20
# mxbai-embed-large context is 512 tokens. Dense technical text tokenizes at ~3 chars/token.
# With question prefix (~200 chars) + answer + source suffix, target ~1000 total.
# So answer portion should be ~700-800 chars max.
MAX_ANSWER_CHARS = 700
MAX_TOTAL_CHARS = 1100  # Final safety limit for entire chunk
# Overlap between chunks for context continuity
CHUNK_OVERLAP = 150


def _fingerprint(text: str) -> str:
    """SHA256 fingerprint of text content."""
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def load_qa_pairs(filepath: str) -> List[Dict]:
    """Load Q&A pairs from a JSONL file."""
    pairs = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
                question = record.get("instruction", "").strip()
                answer = record.get("output", "").strip()
                metadata = record.get("metadata", {})
                if question and answer:
                    pairs.append({
                        "question": question,
                        "answer": answer,
                        "source_file": metadata.get("source_file", ""),
                        "source_type": metadata.get("source_type", ""),
                        "stanza": metadata.get("stanza", ""),
                        "confidence": metadata.get("confidence", 0.8),
                    })
            except json.JSONDecodeError as e:
                logger.warning(f"Skipping line {line_num}: {e}")
    return pairs


def build_chunks_for_qa(qa: Dict) -> List[Tuple[str, Dict]]:
    """Split a Q&A pair into one or more chunks that fit the embedding context.

    Each chunk includes the question prefix for embedding similarity matching.
    Long answers are split with overlap to preserve context.

    Returns list of (chunk_text, metadata) tuples.
    """
    question = qa["question"]
    answer = qa["answer"]
    source_file = qa.get("source_file", "qa_knowledge")
    source_type = qa.get("source_type", "qa")
    stanza = qa.get("stanza") or ""

    # Build the question prefix (appears in every chunk)
    q_prefix = f"Q: {question}\n\nA: "
    source_suffix = f"\n\nSource: {source_file}" if source_file else ""

    # Calculate how much space we have for the answer in each chunk
    prefix_len = len(q_prefix) + len(source_suffix)
    max_answer_per_chunk = MAX_ANSWER_CHARS

    chunks = []

    # If answer fits in one chunk, keep it simple
    if len(answer) <= max_answer_per_chunk:
        chunk_text = q_prefix + answer + source_suffix
        # Safety truncation to prevent embedding context length errors
        if len(chunk_text) > MAX_TOTAL_CHARS:
            chunk_text = chunk_text[:MAX_TOTAL_CHARS - 15] + "\n[...truncated]"
        fp = _fingerprint(chunk_text)
        meta = {
            "kind": "qa_knowledge",
            "source": f"qa://{source_type}/{source_file}" + (f"/{stanza}" if stanza else ""),
            "source_type": source_type,
            "source_file": source_file,
            "stanza": stanza,
            "fingerprint": fp,
            "chunk_id": f"{fp[:16]}-0",
            "chunk_index": 0,
            "total_chunks": 1,
            "chunk_preview": question[:200],
            "question": question[:500],
        }
        chunks.append((chunk_text, meta))
    else:
        # Split long answer into multiple chunks with overlap
        answer_chunks = _split_answer(answer, max_answer_per_chunk, CHUNK_OVERLAP)
        total = len(answer_chunks)

        # Use question fingerprint as base for all chunks from same Q&A
        base_fp = _fingerprint(question)

        for idx, ans_part in enumerate(answer_chunks):
            # Add continuation marker for chunks after the first
            if idx > 0:
                ans_part = f"(continued) {ans_part}"

            chunk_text = q_prefix + ans_part + source_suffix
            # Safety truncation to prevent embedding context length errors
            if len(chunk_text) > MAX_TOTAL_CHARS:
                chunk_text = chunk_text[:MAX_TOTAL_CHARS - 15] + "\n[...truncated]"
            chunk_fp = _fingerprint(chunk_text)

            meta = {
                "kind": "qa_knowledge",
                "source": f"qa://{source_type}/{source_file}" + (f"/{stanza}" if stanza else ""),
                "source_type": source_type,
                "source_file": source_file,
                "stanza": stanza,
                "fingerprint": chunk_fp,
                "chunk_id": f"{base_fp[:16]}-{idx}",
                "chunk_index": idx,
                "total_chunks": total,
                "chunk_preview": question[:200],
                "question": question[:500],
            }
            chunks.append((chunk_text, meta))

    return chunks


def _split_answer(text: str, max_chars: int, overlap: int) -> List[str]:
    """Split answer text into chunks with overlap, breaking at sentence/word boundaries."""
    if len(text) <= max_chars:
        return [text]

    chunks = []
    start = 0

    while start < len(text):
        end = start + max_chars

        if end >= len(text):
            # Last chunk
            chunks.append(text[start:].strip())
            break

        # Try to break at sentence boundary (. ! ?)
        chunk = text[start:end]
        last_sentence = max(
            chunk.rfind(". "),
            chunk.rfind(".\n"),
            chunk.rfind("! "),
            chunk.rfind("? "),
        )

        if last_sentence > max_chars // 2:
            end = start + last_sentence + 1
        else:
            # Fall back to word boundary
            last_space = chunk.rfind(" ")
            if last_space > max_chars // 2:
                end = start + last_space

        chunks.append(text[start:end].strip())

        # Next chunk starts with overlap
        start = end - overlap
        if start < 0:
            start = 0

    return chunks


def _flush_batch(store, texts: list, metas: list) -> int:
    """Try to add a batch; on failure, fall back to one-at-a-time."""
    try:
        store.add_texts(texts, metadatas=metas)
        return len(texts)
    except Exception as e:
        logger.warning(f"Batch of {len(texts)} failed ({e}), retrying one-by-one...")
        added = 0
        for t, m in zip(texts, metas):
            try:
                store.add_texts([t], metadatas=[m])
                added += 1
            except Exception as e2:
                logger.warning(f"Skipped chunk ({len(t)} chars): {e2}")
        return added


def ingest_qa_pairs(
    qa_pairs: List[Dict],
    collection_name: str = None,
    dry_run: bool = False,
    force: bool = False,
) -> Tuple[int, int]:
    """Ingest Q&A pairs into ChromaDB.

    Each Q&A pair may produce multiple chunks if the answer is long.
    Returns (ingested_chunk_count, skipped_chunk_count).
    """
    from vectorstore import get_vector_store, get_existing_fingerprints, _persist

    store = get_vector_store(collection_name=collection_name)
    logger.info(f"Connected to ChromaDB collection: {collection_name or 'default'}")

    # Build all chunks first
    all_chunks = []  # List of (qa, chunk_text, meta)
    for qa in qa_pairs:
        chunks = build_chunks_for_qa(qa)
        for chunk_text, meta in chunks:
            all_chunks.append((qa, chunk_text, meta))

    logger.info(f"Built {len(all_chunks)} total chunks from {len(qa_pairs)} Q&A pairs")

    # Batch check which fingerprints already exist (MUCH faster than one-by-one)
    existing_fingerprints = set()
    if not force:
        all_fingerprints = [meta["fingerprint"] for _, _, meta in all_chunks]
        logger.info(f"Checking {len(all_fingerprints)} fingerprints against ChromaDB...")
        existing_fingerprints = get_existing_fingerprints(store, all_fingerprints)
        logger.info(f"Found {len(existing_fingerprints)} existing fingerprints (will skip)")

    ingested = 0
    skipped = 0
    batch_texts = []
    batch_metas = []

    for qa, chunk_text, meta in all_chunks:
        # Skip duplicates (unless --force)
        if not force and meta["fingerprint"] in existing_fingerprints:
            skipped += 1
            continue

        if dry_run:
            if ingested < 5:
                logger.info(f"[DRY RUN] Would ingest chunk {meta['chunk_index']+1}/{meta['total_chunks']}: {qa['question'][:60]}...")
            ingested += 1
            continue

        batch_texts.append(chunk_text)
        batch_metas.append(meta)

        if len(batch_texts) >= BATCH_SIZE:
            ingested += _flush_batch(store, batch_texts, batch_metas)
            logger.info(f"Ingested so far: {ingested} chunks ({skipped} skipped)")
            batch_texts.clear()
            batch_metas.clear()

    # Final batch
    if batch_texts and not dry_run:
        ingested += _flush_batch(store, batch_texts, batch_metas)

    if not dry_run:
        _persist(store)

    logger.info(f"Done: ingested_chunks={ingested}, skipped_chunks={skipped}, total_qa_pairs={len(qa_pairs)}")
    return ingested, skipped


def main():
    parser = argparse.ArgumentParser(description="Ingest Q&A pairs into ChromaDB")
    parser.add_argument("--file", default=DEFAULT_QA_FILE, help="JSONL file with Q&A pairs")
    parser.add_argument("--collection", default=None, help="ChromaDB collection name")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be ingested")
    parser.add_argument("--force", action="store_true", help="Re-ingest all pairs (skip fingerprint dedup)")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        logger.error(f"Q&A file not found: {args.file}")
        logger.info("Run 'python scripts/generate_all_qa.py' first to generate Q&A pairs")
        sys.exit(1)

    qa_pairs = load_qa_pairs(args.file)
    logger.info(f"Loaded {len(qa_pairs)} Q&A pairs from {args.file}")

    if not qa_pairs:
        logger.warning("No Q&A pairs found")
        sys.exit(0)

    # Show breakdown by source type
    by_type = {}
    for qa in qa_pairs:
        t = qa.get("source_type", "unknown")
        by_type[t] = by_type.get(t, 0) + 1
    for t, count in sorted(by_type.items()):
        logger.info(f"  {t}: {count} pairs")

    ingested, skipped = ingest_qa_pairs(
        qa_pairs,
        collection_name=args.collection,
        dry_run=args.dry_run,
        force=args.force,
    )

    if args.dry_run:
        print(f"\n[DRY RUN] Would ingest {ingested} chunks from {len(qa_pairs)} Q&A pairs ({skipped} already exist)")
    else:
        print(f"\nIngested {ingested} chunks from {len(qa_pairs)} Q&A pairs ({skipped} duplicates skipped)")


if __name__ == "__main__":
    main()
