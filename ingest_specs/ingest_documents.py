import os
import sys
import pathlib
import time
import hashlib
import json
import logging
import traceback
from typing import List, Tuple, Dict, Any, Optional, Generator
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import gc  # For explicit garbage collection

# Project logging helper for consistent key=value logs
from chat_app.logging_utils import setup_logging
# --- External Imports ---
from tqdm import tqdm 
from tqdm.contrib.logging import logging_redirect_tqdm

# Import LangChain components
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.documents import Document

# Assuming these are correct from your project setup
from chat_app.vectorstore import (
    get_vector_store,
    fingerprint_bytes,
    has_fingerprint,
    get_existing_fingerprints,
)


# ============================================================================
# CONFIGURATION SECTION - All tunable parameters in one place
# ============================================================================

# Logging configuration - unified key=value format (UTC with ms)
LOGGING_LEVEL = os.getenv("INGEST_LOG_LEVEL", "INFO").upper()
logger = setup_logging(app_name="ingest_specs", level=LOGGING_LEVEL)

# Environment variables with sensible defaults
EMBED_MODEL: str = os.getenv("OLLAMA_EMBED_MODEL", "mxbai-embed-large")
# Conservative chunk sizes for mxbai-embed-large (1024-dim embeddings)
# Model context: ~512 tokens, ~4 chars per token = ~2048 chars max
# Using 500/450 to stay well under limit even with metadata overhead
CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "100"))
SPEC_CHUNK_SIZE: int = int(os.getenv("SPEC_CHUNK_SIZE", "450"))
SPEC_CHUNK_OVERLAP: int = int(os.getenv("SPEC_CHUNK_OVERLAP", "100"))
# Support .md files via ALLOWED_EXTS env var (e.g., "ALLOWED_EXTS=.md" for SPL command docs)
_allowed_exts_env = os.getenv("ALLOWED_EXTS", "").strip()
ALLOWED_EXTS: set[str] = (
    {ext.strip().lower() for ext in _allowed_exts_env.split(",") if ext.strip()}
    if _allowed_exts_env
    else {".spec", ".conf"}
)
_allowed_files_env = os.getenv("SPECS_ALLOWED_FILES", "").strip()
ALLOWED_FILES: set[str] = (
    {
        name.strip().lower()
        for name in _allowed_files_env.split(",")
        if name.strip()
    }
    if _allowed_files_env
    else set()
)
SKIP_DEDUP: bool = os.getenv("SKIP_DEDUP", "0") == "1"
FORCE_REINDEX: bool = os.getenv("FORCE_REINDEX", "0") == "1"  # Force re-indexing even if checksum unchanged
MAX_RETRIES: int = int(os.getenv("INGEST_MAX_RETRIES", "3"))

# File paths for persistence (default to the specs store)
_store_dir = os.getenv("CHROMA_DIR", "/app/specs_chroma_store")
CHECKSUM_FILE: pathlib.Path = pathlib.Path(
    os.getenv("INGEST_CHECKSUM_FILE", f"{_store_dir}/ingest_specs_checksum.txt")
)
MANIFEST_FILE: pathlib.Path = pathlib.Path(
    os.getenv("INGEST_MANIFEST_FILE", f"{_store_dir}/ingest_specs_manifest.json")
)

# Performance tuning parameters
# CRITICAL: These have the biggest impact on performance
MAX_WORKERS: int = int(os.getenv("INGEST_MAX_WORKERS", "4"))  
# Explanation: 4 workers optimal for I/O-bound file reading
# Too many workers causes disk thrashing, too few underutilizes system

BATCH_SIZE: int = int(os.getenv("INGEST_BATCH_SIZE", "1000"))  
# Explanation: Larger batches reduce embedding API overhead
# 1000-2000 is sweet spot for most systems. Increase if you have more RAM.

CHUNK_CACHE_SIZE: int = int(os.getenv("CHUNK_CACHE_SIZE", "10000"))
# Explanation: Max chunks to accumulate before forcing a memory cleanup

CHECKSUM_READ_BUFFER: int = int(os.getenv("CHECKSUM_READ_BUFFER", "65536"))  # 64KB
# Explanation: Buffer size for reading files during checksum (larger = faster for big files)

ENABLE_PROFILING: bool = os.getenv("ENABLE_PROFILING", "0") == "1"
# Explanation: Enable detailed performance profiling (adds slight overhead)

# Memory management
GC_THRESHOLD: int = int(os.getenv("GC_THRESHOLD", "5000"))
# Explanation: Trigger garbage collection every N chunks to prevent memory bloat

# Self-learning / run history
HISTORY_FILE: pathlib.Path = pathlib.Path(
    os.getenv("INGEST_HISTORY_FILE", "/app/specs_chroma_store/ingest_specs_history.json")
)
MAX_HISTORY_RUNS: int = int(os.getenv("INGEST_HISTORY_KEEP", "20"))


def _load_history() -> list[dict]:
    try:
        if HISTORY_FILE.exists():
            return json.loads(HISTORY_FILE.read_text())
    except Exception as exc:
        logger.warning(f"History load skipped: {exc}")
    return []


def _save_history(runs: list[dict]) -> None:
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        HISTORY_FILE.write_text(json.dumps(runs[-MAX_HISTORY_RUNS:], indent=2))
    except Exception as exc:
        logger.warning(f"History save failed: {exc}")


def _retry_queue_from_history(history: list[dict]) -> list[str]:
    if not history:
        return []
    last = history[-1]
    return [f["path"] for f in last.get("files", []) if f.get("status") in {"load_failed", "error"}]


# ============================================================================
# PERFORMANCE MONITORING CLASS
# ============================================================================

class PerformanceMonitor:
    """
    Tracks detailed performance metrics for profiling and optimization.
    Helps identify bottlenecks in the ingestion pipeline.
    """
    
    def __init__(self):
        self.timings: Dict[str, List[float]] = defaultdict(list)
        self.counters: Dict[str, int] = defaultdict(int)
        self.start_times: Dict[str, float] = {}
        
    def start_timer(self, name: str) -> None:
        """Start timing an operation."""
        self.start_times[name] = time.monotonic()
        
    def stop_timer(self, name: str) -> float:
        """Stop timing an operation and record duration."""
        if name not in self.start_times:
            logger.warning(f"Timer '{name}' was never started")
            return 0.0
        duration = time.monotonic() - self.start_times[name]
        self.timings[name].append(duration)
        del self.start_times[name]
        return duration
        
    def increment(self, name: str, amount: int = 1) -> None:
        """Increment a counter."""
        self.counters[name] += amount
        
    def get_stats(self, name: str) -> Dict[str, float]:
        """Get statistics for a timer."""
        if name not in self.timings or not self.timings[name]:
            return {}
        times = self.timings[name]
        return {
            "count": len(times),
            "total": sum(times),
            "mean": sum(times) / len(times),
            "min": min(times),
            "max": max(times),
        }
        
    def report(self) -> None:
        """Log comprehensive performance report."""
        logger.info("=" * 80)
        logger.info("PERFORMANCE REPORT")
        logger.info("=" * 80)
        
        # Report timings
        if self.timings:
            logger.info("\nTiming Statistics:")
            for name in sorted(self.timings.keys()):
                stats = self.get_stats(name)
                logger.info(
                    f"  {name:30s}: "
                    f"count={stats['count']:5d}, "
                    f"total={stats['total']:7.2f}s, "
                    f"mean={stats['mean']:6.3f}s, "
                    f"min={stats['min']:6.3f}s, "
                    f"max={stats['max']:6.3f}s"
                )
        
        # Report counters
        if self.counters:
            logger.info("\nOperation Counters:")
            for name in sorted(self.counters.keys()):
                logger.info(f"  {name:30s}: {self.counters[name]:,}")
        
        logger.info("=" * 80)


# Initialize global performance monitor
perf = PerformanceMonitor() if ENABLE_PROFILING else None


# ============================================================================
# TEXT SPLITTER INITIALIZATION
# ============================================================================

# Initialize Text Splitters globally to avoid repeated instantiation
# Default splitter and a spec/conf-optimized splitter
# Splitters will be initialized in ingest_dir() to use environment variables
splitter_default = None
splitter_spec = None

def _init_splitters():
    """
    Initialize text splitters with token-based chunking via smart_chunker module.
    Falls back to character-based if smart_chunker unavailable.
    """
    global splitter_default, splitter_spec

    if splitter_default is not None:
        return  # Already initialized

    try:
        # Import smart chunker for token-based chunking
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "chat_app"))
        from smart_chunker import get_smart_splitter, get_token_counter

        token_counter = get_token_counter()

        # Default splitter: token-based with 250 tokens
        # mxbai-embed-large context: 512 tokens. After adding contextual
        # prefix + prev/next previews (~80 tokens overhead) the final chunk
        # must stay under 512 tokens.  250 + 80 = 330 tokens — safe margin.
        splitter_default = get_smart_splitter(
            file_type=None,  # Generic
            chunk_size=250,  # tokens (safe for mxbai-embed-large 512-token context)
            chunk_overlap=40
        )

        # Spec splitter: for .spec/.conf files (uses stanza-aware via passthrough)
        splitter_spec = get_smart_splitter(
            file_type=".spec",
            chunk_size=250,  # tokens (but stanza parser ignores this)
            chunk_overlap=40
        )

        logger.info(
            f"Initialized TOKEN-BASED splitters: default=250 tokens/40 overlap, "
            f"spec=stanza-aware (semantic chunking)"
        )
    except ImportError as e:
        # Fallback to character-based chunking
        logger.warning(f"smart_chunker not available ({e}), using character-based chunking")

        splitter_default = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            length_function=len,
            is_separator_regex=False,
            separators=["\n\n", "\n", " ", ""],
        )
        splitter_spec = RecursiveCharacterTextSplitter(
            chunk_size=SPEC_CHUNK_SIZE,
            chunk_overlap=SPEC_CHUNK_OVERLAP,
            length_function=len,
            is_separator_regex=False,
            separators=["\n\n", "\n", " ", ""],
        )

        logger.info(
            f"Initialized CHARACTER-BASED splitters (fallback): default={CHUNK_SIZE}/{CHUNK_OVERLAP}, "
            f"spec={SPEC_CHUNK_SIZE}/{SPEC_CHUNK_OVERLAP}"
        )


# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def format_bytes(size_bytes: int) -> str:
    """
    Format bytes into human-readable format.
    Example: 1536 -> "1.50 KB"
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} PB"


def format_duration(seconds: float) -> str:
    """
    Format duration in seconds to human-readable format.
    Example: 125.5 -> "2m 5.5s"
    """
    if seconds < 60:
        return f"{seconds:.2f}s"
    elif seconds < 3600:
        mins = int(seconds // 60)
        secs = seconds % 60
        return f"{mins}m {secs:.1f}s"
    else:
        hours = int(seconds // 3600)
        mins = int((seconds % 3600) // 60)
        secs = seconds % 60
        return f"{hours}h {mins}m {secs:.0f}s"


def safe_divide(numerator: float, denominator: float, default: float = 0.0) -> float:
    """Safely divide two numbers, returning default if denominator is zero."""
    return numerator / denominator if denominator != 0 else default


# ============================================================================
# CHECKSUM COMPUTATION
# ============================================================================

def compute_checksum(base: pathlib.Path) -> str:
    """
    Computes a SHA256 checksum for all relevant files in the directory.
    
    This checksum represents the entire state of the spec files directory.
    If unchanged, we can skip the entire ingestion process.
    
    Performance optimization: Reads files in chunks to minimize memory usage.
    
    Args:
        base: Base directory to compute checksum for
        
    Returns:
        Hexadecimal SHA256 digest string
    """
    logger.info(f"PHASE 0.1: Computing directory checksum for {base}")
    logger.debug(f"Allowed extensions: {ALLOWED_EXTS}")
    logger.debug(f"Checksum buffer size: {format_bytes(CHECKSUM_READ_BUFFER)}")
    
    start = time.monotonic()
    h = hashlib.sha256()
    file_count = 0
    total_bytes = 0
    
    # Collect all eligible files first
    logger.debug("Discovering files for checksum computation...")
    eligible_files = []
    for path in base.rglob("*"):
        if path.is_file() and path.suffix.lower() in ALLOWED_EXTS:
            eligible_files.append(path)
    
    # Sort for deterministic checksum
    eligible_files.sort()
    logger.debug(f"Found {len(eligible_files)} files for checksum")
    
    # Process each file
    for path in eligible_files:
        try:
            file_size = path.stat().st_size
            rel_path = str(path.relative_to(base))
            
            # Include relative path in checksum for file identity
            h.update(rel_path.encode('utf-8'))
            
            # Read file in chunks to minimize memory footprint
            with path.open('rb') as f:
                while chunk := f.read(CHECKSUM_READ_BUFFER):
                    h.update(chunk)
            
            file_count += 1
            total_bytes += file_size
            
            if file_count % 100 == 0:
                logger.debug(f"Processed {file_count}/{len(eligible_files)} files for checksum...")
                
        except Exception as exc:
            logger.error(f"Failed to checksum {path}: {exc}")
            # Continue with other files - one bad file shouldn't break everything
    
    digest = h.hexdigest()
    duration = time.monotonic() - start
    
    logger.info(
        f"Checksum computation complete: {digest[:16]}... "
        f"({file_count} files, {format_bytes(total_bytes)}, {format_duration(duration)})"
    )
    
    if perf:
        perf.stop_timer("checksum_computation")
        perf.increment("files_checksummed", file_count)
        perf.increment("bytes_checksummed", total_bytes)
    
    return digest


# ============================================================================
# MANIFEST MANAGEMENT
# ============================================================================

def load_manifest() -> Dict[str, str]:
    """
    Load the fingerprint manifest if present.
    
    The manifest tracks file fingerprints to detect changes at the file level.
    This allows us to skip unchanged files without re-reading them.
    
    Returns:
        Dictionary mapping relative paths to fingerprints
    """
    logger.debug(f"Loading manifest from {MANIFEST_FILE}")
    
    try:
        if MANIFEST_FILE.exists():
            manifest = json.loads(MANIFEST_FILE.read_text())
            logger.info(f"Loaded manifest with {len(manifest)} entries")
            return manifest
        else:
            logger.info("No existing manifest found - will create new one")
            return {}
    except json.JSONDecodeError as exc:
        logger.error(f"Manifest is corrupted (JSON parse error): {exc}")
        return {}
    except Exception as exc:
        logger.warning(f"Manifest load failed: {exc}")
        return {}


def save_manifest(manifest: Dict[str, str]) -> None:
    """
    Persist the fingerprint manifest to disk.
    
    Args:
        manifest: Dictionary mapping relative paths to fingerprints
    """
    logger.debug(f"Saving manifest with {len(manifest)} entries to {MANIFEST_FILE}")
    
    try:
        # Ensure parent directory exists
        MANIFEST_FILE.parent.mkdir(parents=True, exist_ok=True)
        
        # Write with pretty formatting for human readability
        MANIFEST_FILE.write_text(
            json.dumps(manifest, indent=2, sort_keys=True)
        )
        
        logger.info(f"Successfully wrote manifest to {MANIFEST_FILE}")
        
    except PermissionError as exc:
        logger.error(f"Permission denied writing manifest: {exc}")
    except Exception as exc:
        logger.error(f"Failed to write manifest: {exc}")
        logger.debug(traceback.format_exc())


# ============================================================================
# FILE LOADING AND SPLITTING
# ============================================================================

def load_and_split_file_with_fp(
    base_dir: pathlib.Path, 
    path: pathlib.Path
) -> Optional[Tuple[List[Document], str, str]]:
    """
    Loads a file, computes its fingerprint, and splits it into LangChain Documents.
    
    This is the core processing function for each file, designed to be called
    in parallel by multiple workers. It performs:
    1. File reading and fingerprinting
    2. Text decoding with error handling
    3. Text splitting into chunks
    4. Document metadata creation
    
    Performance optimizations:
    - Pre-computes common metadata fields to avoid repeated string operations
    - Minimizes intermediate variable creation
    - Uses efficient string formatting
    
    Args:
        base_dir: Base directory for computing relative paths
        path: Absolute path to the file to process
        
    Returns:
        Tuple of (documents, fingerprint, rel_path) on success, None on failure
    """
    if perf:
        perf.start_timer("file_load_and_split")
    
    try:
        # Read file and compute fingerprint
        logger.debug(f"Loading file: {path.name}")
        raw_bytes = path.read_bytes()
        file_size = len(raw_bytes)
        
        fp = fingerprint_bytes(raw_bytes)
        rel_path = str(path.relative_to(base_dir))
        
        logger.debug(f"File {path.name}: size={format_bytes(file_size)}, fingerprint={fp[:16]}...")
        
        # Decode text with error handling
        # 'ignore' skips invalid UTF-8 sequences rather than crashing
        text = raw_bytes.decode("utf-8", errors="ignore")
        text_length = len(text)
        
        # Split text into chunks
        if perf:
            perf.start_timer("text_splitting")
        
        suffix = path.suffix.lower()
        splitter = splitter_spec if suffix in {".spec", ".conf"} else splitter_default
        chunks = splitter.split_text(text)
        
        if perf:
            perf.stop_timer("text_splitting")
        
        logger.debug(
            f"File {path.name}: split into {len(chunks)} chunks "
            f"(text_length={text_length:,} chars)"
        )
        
        # Pre-compute common metadata fields (optimization)
        source = f"spec://{rel_path}"
        file_name = path.name
        
        # Build document list with metadata and a small contextual prefix to help retrieval
        # CRITICAL: Limit final chunk size to prevent embedding context length errors
        # mxbai-embed-large context: 512 tokens. Average ~4 chars/token = ~2048 chars.
        # After contextual prefix + prev/next previews the chunk is ~1200-1400 chars.
        # 1800 chars is the hard safety cap (≈450 tokens, under the 512 limit).
        MAX_CONTEXT_CHARS = 1800  # Safety cap for mxbai-embed-large (512 tokens ≈ 2048 chars)

        documents = []
        total = len(chunks)
        for i, chunk in enumerate(chunks):
            prev_tail = chunks[i - 1][-100:] if i > 0 else ""
            next_head = chunks[i + 1][:100] if i + 1 < total else ""
            prefix = f"[file:{file_name}] [path:{rel_path}] [chunk:{i+1}/{total}]\n"
            contextual_parts = [prefix]
            if prev_tail:
                contextual_parts.append(f"[prev...]{prev_tail}")
            contextual_parts.append(chunk)
            if next_head:
                contextual_parts.append(f"[next...]{next_head}")
            contextual_chunk = "\n".join(contextual_parts)

            # Truncate if too large to prevent embedding errors
            if len(contextual_chunk) > MAX_CONTEXT_CHARS:
                logger.warning(
                    f"Chunk {i+1}/{total} in {file_name} exceeds {MAX_CONTEXT_CHARS} chars "
                    f"({len(contextual_chunk)} chars), truncating to prevent embedding error"
                )
                contextual_chunk = contextual_chunk[:MAX_CONTEXT_CHARS] + "\n[...truncated]"

            documents.append(Document(
                page_content=contextual_chunk,
                metadata={
                    "kind": "file",
                    "source": source,
                    "fingerprint": fp,
                    "repo": "splunk-spec-files",
                    "rel_path": rel_path,
                    "file_name": file_name,
                    # Make chunk_id unique even if two files have identical content
                    "chunk_id": f"{fp}-{abs(hash(rel_path))}-{i}",
                    "chunk_index": i,  # Position within file
                    "total_chunks": total,  # Total chunks for this file
                }
            ))
        
        if perf:
            duration = perf.stop_timer("file_load_and_split")
            perf.increment("files_processed", 1)
            perf.increment("chunks_created", len(chunks))
            perf.increment("bytes_processed", file_size)
            logger.debug(f"Processed {path.name} in {duration:.3f}s")
        
        return documents, fp, rel_path

    except UnicodeDecodeError as exc:
        logger.error(f"Unicode decode error in {path}: {exc}")
        return None
    except MemoryError as exc:
        logger.critical(f"Out of memory processing {path}: {exc}")
        return None
    except Exception as exc:
        logger.error(f"Failed to load or split {path}: {exc}")
        logger.debug(traceback.format_exc())
        return None


# ============================================================================
# MAIN INGESTION FUNCTION
# ============================================================================

def ingest_dir(root: pathlib.Path) -> None:
    """
    Main ingestion logic with optimized two-phase processing.
    
    PHASE 0: Pre-flight checks
        - Compute directory checksum and compare with previous run
        - Load manifest and prepare vector store
        
    PHASE 1: Parallel file loading and splitting (I/O-bound)
        - Discover and filter files
        - Load files in parallel with thread pool
        - Split into chunks and accumulate in memory
        
    PHASE 2: Batched embedding and database insertion (CPU/Network-bound)
        - Batch documents for efficient embedding
        - Retry failed batches with exponential backoff
        - Persist vector store and update manifest
    
    Args:
        root: Root directory containing files to ingest
    """
    # Initialize text splitters with current environment variable values
    _init_splitters()

    logger.info("=" * 80)
    logger.info(f"STARTING INGESTION PROCESS FOR: {root}")
    logger.info("=" * 80)
    logger.info(f"Configuration:")
    logger.info(f"  Embedding Model: {EMBED_MODEL}")
    logger.info(f"  Chunk Size: {CHUNK_SIZE}, Overlap: {CHUNK_OVERLAP}")
    logger.info(f"  Max Workers: {MAX_WORKERS}")
    logger.info(f"  Batch Size: {BATCH_SIZE}")
    logger.info(f"  Allowed Extensions: {ALLOWED_EXTS}")
    logger.info(f"  Allowed Files: {ALLOWED_FILES if ALLOWED_FILES else 'all'}")
    logger.info(f"  Skip Deduplication: {SKIP_DEDUP}")
    logger.info(f"  Profiling Enabled: {ENABLE_PROFILING}")
    logger.info("=" * 80)
    
    run_id = hashlib.sha1(str(time.time()).encode("utf-8")).hexdigest()[:8]
    run_start = time.monotonic()
    history = _load_history()
    
    start_total = time.monotonic()
    if perf:
        perf.start_timer("total_ingestion")
    
    # ========================================================================
    # PHASE 0: PRE-FLIGHT CHECKS
    # ========================================================================
    
    logger.info("PHASE 0: Pre-flight checks")
    
    # Compute and compare checksum
    if perf:
        perf.start_timer("checksum_computation")
    
    try:
        new_checksum = compute_checksum(root)
        old_checksum = None

        skip_due_to_checksum = False
        if FORCE_REINDEX:
            logger.info("⚠️  FORCE_REINDEX=1 - Forcing re-indexing regardless of checksum")
        elif CHECKSUM_FILE.exists():
            old_checksum = CHECKSUM_FILE.read_text().strip()
            logger.info(f"Previous checksum: {old_checksum[:16]}...")
            logger.info(f"Current checksum:  {new_checksum[:16]}...")

            if old_checksum == new_checksum:
                logger.info("✓ Checksum unchanged - directory has not been modified")
                skip_due_to_checksum = True
            else:
                logger.info("✗ Checksum changed - directory has been modified")
        else:
            logger.info("No previous checksum found - performing full ingestion")
            
    except Exception as exc:
        logger.warning(f"Checksum check failed, proceeding anyway: {exc}")
        logger.debug(traceback.format_exc())
        new_checksum = None

    # Initialize vector store
    logger.info("Initializing vector store...")
    try:
        store = get_vector_store()
        logger.info("✓ Vector store initialized successfully")
    except Exception as exc:
        logger.critical(f"Failed to initialize vector store: {exc}")
        logger.debug(traceback.format_exc())
        return

    # If checksum unchanged, only skip when collection is already populated
    if skip_due_to_checksum:
        existing = 0
        try:
            coll = getattr(store, "_collection", None)
            if coll:
                existing = coll.count()
        except Exception as exc:
            logger.warning(f"Could not count existing documents, proceeding with ingestion: {exc}")
        if existing > 0:
            logger.info(f"Skipping ingestion (collection already populated with {existing} documents).")
            logger.info("To force re-indexing, set FORCE_REINDEX=1")
            return
        else:
            logger.info("Collection empty or missing despite unchanged checksum; proceeding with ingestion.")
    
    # Load manifest
    manifest = load_manifest()
    
    # ========================================================================
    # PHASE 1: FILE DISCOVERY AND FILTERING
    # ========================================================================
    
    logger.info("=" * 80)
    logger.info("PHASE 1: File discovery, filtering, and parallel loading")
    logger.info("=" * 80)
    
    if perf:
        perf.start_timer("file_discovery")
    
    # Statistics for reporting
    stats = {
        "total_discovered": 0,
        "skipped_ext": 0,
        "skipped_dedup": 0,
        "skipped_manifest": 0,
        "trimmed_test": 0,
        "to_process": 0,
    }
    
    files_to_process: List[pathlib.Path] = []
    
    logger.info("Scanning directory tree...")
    
    # First pass: collect all files and their fingerprints
    file_fp_map: Dict[pathlib.Path, Tuple[str, str]] = {}
    
    for path in root.rglob("*"):
        if not path.is_file():
            continue
            
        stats["total_discovered"] += 1
        
        # Filter by extension and allowed filenames
        if path.suffix.lower() not in ALLOWED_EXTS:
            stats["skipped_ext"] += 1
            continue
        name_lower = path.name.lower()
        if ALLOWED_FILES and not any(
            name_lower == allowed or name_lower.startswith(allowed)
            for allowed in ALLOWED_FILES
        ):
            stats["skipped_ext"] += 1
            continue
        
        try:
            # Read and fingerprint
            raw = path.read_bytes()
            fp = fingerprint_bytes(raw)
            rel_path = str(path.relative_to(root))
            
            # Check manifest for unchanged files
            if manifest.get(rel_path) == fp:
                stats["skipped_manifest"] += 1
                logger.debug(f"Skipping {rel_path} (unchanged per manifest)")
                continue
            
            # Store for deduplication check
            file_fp_map[path] = (fp, rel_path)
            
        except Exception as exc:
            logger.error(f"Error processing {path} during discovery: {exc}")
            continue
    
    if perf:
        perf.stop_timer("file_discovery")
    
    logger.info(f"Discovery scan complete: found {stats['total_discovered']} total files")
    logger.info(f"  Filtered by extension: {stats['skipped_ext']} files")
    logger.info(f"  Filtered by manifest: {stats['skipped_manifest']} files")
    logger.info(f"  Candidates for processing: {len(file_fp_map)} files")
    
    # Second pass: check for duplicates in vector store (if enabled)
    if not SKIP_DEDUP and file_fp_map:
        logger.info("Running deduplication check against vector store...")
        
        if perf:
            perf.start_timer("deduplication_check")
        
        dedup_start = time.monotonic()
        
        # Batch check all fingerprints at once (much faster than one-by-one)
        all_fingerprints = [fp for fp, _ in file_fp_map.values()]
        logger.info(f"Batch checking {len(all_fingerprints)} fingerprints...")
        try:
            existing_fps = get_existing_fingerprints(store, all_fingerprints)
            logger.info(f"Found {len(existing_fps)} existing fingerprints")
        except Exception as exc:
            logger.error(f"Batch fingerprint check failed: {exc}, falling back to one-by-one")
            existing_fps = set()
            # Fallback to one-by-one if batch fails
            for path, (fp, rel_path) in file_fp_map.items():
                try:
                    if has_fingerprint(store, fp):
                        existing_fps.add(fp)
                except Exception:
                    pass

        for path, (fp, rel_path) in file_fp_map.items():
            if fp in existing_fps:
                stats["skipped_dedup"] += 1
                logger.debug(f"Skipping {rel_path} (duplicate fingerprint)")
            else:
                files_to_process.append(path)
        
        dedup_duration = time.monotonic() - dedup_start
        logger.info(
            f"Deduplication complete: {stats['skipped_dedup']} duplicates found "
            f"in {format_duration(dedup_duration)}"
        )
        
        if perf:
            perf.stop_timer("deduplication_check")
    else:
        if SKIP_DEDUP:
            logger.info("Deduplication disabled - processing all candidates")
        files_to_process = list(file_fp_map.keys())

    # Move last-run failures to the front to retry first
    retry_first = _retry_queue_from_history(history)
    if retry_first:
        retry_set = {pathlib.Path(p).as_posix() for p in retry_first}
        reordered: List[pathlib.Path] = []
        for p in retry_first:
            pp = pathlib.Path(p)
            if pp.exists():
                reordered.append(pp)
        reordered.extend([f for f in files_to_process if f.as_posix() not in retry_set])
        files_to_process = reordered

    stats["to_process"] = len(files_to_process)

    # Report filtering statistics
    logger.info("=" * 80)
    logger.info("FILTERING SUMMARY:")
    logger.info(f"  Total files discovered:     {stats['total_discovered']:6,}")
    logger.info(f"  Skipped (wrong extension):  {stats['skipped_ext']:6,}")
    logger.info(f"  Skipped (unchanged):        {stats['skipped_manifest']:6,}")
    logger.info(f"  Skipped (duplicate):        {stats['skipped_dedup']:6,}")
    logger.info(f"  Trimmed for speed:          {stats['trimmed_test']:6,}")
    logger.info(f"  Files to process:           {stats['to_process']:6,}")
    logger.info("=" * 80)
    
    if stats["to_process"] < 20:
        logger.warning(
            f"Only {stats['to_process']} files to ingest. This is unusually low; "
            "check that the specs repo cloned correctly and that /tmp/specs contains the full set."
        )
    
    if not files_to_process:
        logger.info("✓ No new files to ingest - all files up to date")
        return

    # ========================================================================
    # PHASE 1B: PARALLEL LOAD & SPLIT
    # ========================================================================
    
    logger.info(f"Starting parallel file processing with {MAX_WORKERS} workers...")

    all_documents: List[Document] = []
    # Track file metadata for manifest updates (only update after successful insertion)
    file_fingerprints: Dict[str, str] = {}  # rel_path -> fingerprint
    file_status: Dict[str, str] = {}
    
    start_phase_1 = time.monotonic()
    if perf:
        perf.start_timer("phase1_parallel_loading")
    
    # Use ThreadPoolExecutor for I/O-bound file loading
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        # Submit all file processing tasks
        futures = {
            executor.submit(load_and_split_file_with_fp, root, path): path 
            for path in files_to_process
        }
        
        # Track progress with tqdm
        with tqdm(
            total=len(files_to_process), 
            desc="Loading & Splitting", 
            unit="file",
            ncols=100
        ) as pbar:
            for future in as_completed(futures):
                path = futures[future]
                
                try:
                    result = future.result(timeout=30)  # 30 second timeout per file
                    
                    if result:
                        documents, fp, rel_path = result
                        all_documents.extend(documents)
                        # Store fingerprint but don't update manifest yet (wait for successful insertion)
                        file_fingerprints[rel_path] = fp
                        file_status[str(path)] = "ok"

                        # Update progress bar with current stats
                        pbar.set_postfix_str(
                            f"Chunks: {len(all_documents):,}, "
                            f"Last: {path.name[:20]}"
                        )
                    else:
                        logger.warning(f"File processing returned no result: {path.name}")
                        file_status[str(path)] = "load_failed"
                        
                except TimeoutError:
                    logger.error(f"Timeout processing file (>30s): {path}")
                    file_status[str(path)] = "timeout"
                except Exception as exc:
                    logger.critical(
                        f"UNHANDLED EXCEPTION in worker thread for {path.name}: {exc}"
                    )
                    logger.debug(traceback.format_exc())
                    file_status[str(path)] = f"error:{exc}"
                
                pbar.update(1)
                
                # Periodic garbage collection to prevent memory bloat
                if len(all_documents) % GC_THRESHOLD == 0:
                    logger.debug(f"Running garbage collection (chunks: {len(all_documents)})")
                    gc.collect()

    duration_phase_1 = time.monotonic() - start_phase_1
    total_chunks = len(all_documents)
    
    if perf:
        perf.stop_timer("phase1_parallel_loading")
    
    logger.info("=" * 80)
    logger.info("PHASE 1 COMPLETE:")
    logger.info(f"  Files processed:     {len(file_fingerprints):6,}")
    logger.info(f"  Chunks generated:    {total_chunks:6,}")
    logger.info(f"  Duration:            {format_duration(duration_phase_1)}")
    logger.info(f"  Processing rate:     {len(files_to_process)/duration_phase_1:.1f} files/sec")
    logger.info(f"  Chunk rate:          {total_chunks/duration_phase_1:.1f} chunks/sec")
    logger.info("=" * 80)
    
    if not all_documents:
        logger.warning("No documents generated during processing - nothing to ingest")
        return
    
    # ========================================================================
    # PHASE 2: BATCHED EMBEDDING AND DATABASE INSERTION
    # ========================================================================
    
    logger.info("PHASE 2: Batched embedding and vector store insertion")
    logger.info("=" * 80)
    logger.info(f"Total chunks to embed: {total_chunks:,}")
    logger.info(f"Batch size: {BATCH_SIZE}")
    logger.info(f"Estimated batches: {(total_chunks + BATCH_SIZE - 1) // BATCH_SIZE}")
    logger.info("=" * 80)
    
    start_phase_2 = time.monotonic()
    if perf:
        perf.start_timer("phase2_embedding_insertion")
    
    def batched(seq: List[Any], size: int) -> Generator[List[Any], None, None]:
        """Generator for memory-efficient batching."""
        for i in range(0, len(seq), size):
            yield seq[i : i + size]
    
    processed = 0
    failed_batches = 0
    batch_times = []
    successfully_inserted_chunks: set = set()  # Track chunk_ids that were successfully inserted

    with tqdm(
        total=total_chunks,
        desc="Embedding & Inserting",
        unit="chunk",
        ncols=100
    ) as pbar:
        
        for batch_num, batch_docs in enumerate(batched(all_documents, BATCH_SIZE)):
            batch_start = time.monotonic()
            batch_size = len(batch_docs)
            batch_ids = [doc.metadata["chunk_id"] for doc in batch_docs]
            
            logger.debug(
                f"Processing batch {batch_num + 1}: "
                f"{batch_size} chunks (IDs: {batch_ids[0]}...{batch_ids[-1]})"
            )
            
            success = False
            last_error = None
            
            # Retry logic with exponential backoff
            for attempt in range(1, MAX_RETRIES + 1):
                try:
                    # This is the expensive operation: embedding + database insert
                    store.add_documents(batch_docs, ids=batch_ids)

                    success = True
                    processed += batch_size
                    # Track successfully inserted chunk IDs for manifest verification
                    successfully_inserted_chunks.update(batch_ids)

                    batch_duration = time.monotonic() - batch_start
                    batch_times.append(batch_duration)

                    logger.debug(
                        f"Batch {batch_num + 1} succeeded in {batch_duration:.2f}s "
                        f"({batch_size/batch_duration:.1f} chunks/sec)"
                    )

                    if perf:
                        perf.increment("batches_succeeded", 1)
                        perf.increment("chunks_embedded", batch_size)

                    break
                    
                except Exception as exc:
                    last_error = exc
                    logger.error(
                        f"Batch {batch_num + 1} failed (attempt {attempt}/{MAX_RETRIES}): "
                        f"{type(exc).__name__}: {exc}"
                    )
                    
                    if attempt < MAX_RETRIES:
                        # Exponential backoff capped at 10 seconds
                        sleep_time = min(2 ** attempt, 10)
                        logger.info(f"Retrying in {sleep_time}s...")
                        time.sleep(sleep_time)
                    else:
                        logger.error(f"Batch {batch_num + 1} failed after all retries")
                        if perf:
                            perf.increment("batches_failed", 1)
            
            if not success:
                failed_batches += 1
                logger.error(
                    f"BATCH FAILURE: Batch {batch_num + 1} could not be inserted after "
                    f"{MAX_RETRIES} attempts. Last error: {last_error}"
                )
                # Continue with next batch instead of stopping entirely
            
            # Update progress bar
            pbar.update(batch_size)
            
            # Show rolling average speed
            if batch_times:
                avg_batch_time = sum(batch_times[-10:]) / len(batch_times[-10:])
                avg_speed = BATCH_SIZE / avg_batch_time if avg_batch_time > 0 else 0
                pbar.set_postfix_str(f"Speed: {avg_speed:.0f} chunks/s")

    duration_phase_2 = time.monotonic() - start_phase_2
    
    if perf:
        perf.stop_timer("phase2_embedding_insertion")
    
    # ========================================================================
    # PHASE 2 SUMMARY
    # ========================================================================
    
    logger.info("=" * 80)
    logger.info("PHASE 2 COMPLETE:")
    logger.info(f"  Chunks processed:    {processed:6,} / {total_chunks:,}")
    logger.info(f"  Success rate:        {100 * processed / total_chunks:.1f}%")
    logger.info(f"  Failed batches:      {failed_batches:6,}")
    logger.info(f"  Duration:            {format_duration(duration_phase_2)}")
    logger.info(f"  Embedding rate:      {safe_divide(processed, duration_phase_2):.1f} chunks/sec")
    
    if batch_times:
        avg_batch = sum(batch_times) / len(batch_times)
        min_batch = min(batch_times)
        max_batch = max(batch_times)
        logger.info(f"  Batch timing:")
        logger.info(f"    Average:           {avg_batch:.2f}s")
        logger.info(f"    Fastest:           {min_batch:.2f}s")
        logger.info(f"    Slowest:           {max_batch:.2f}s")
    
    if failed_batches > 0:
        logger.warning(f"⚠ {failed_batches} batches failed - some chunks were not indexed")
    else:
        logger.info("✓ All batches processed successfully")
    
    logger.info("=" * 80)

    # ========================================================================
    # BUILD UPDATED MANIFEST (Only for fully successful files)
    # ========================================================================

    logger.info("Building updated manifest (only for files with all chunks successfully inserted)...")

    # Build reverse mapping: rel_path -> set of chunk_ids for that file
    file_to_chunks: Dict[str, set] = {}
    for doc in all_documents:
        rel_path = doc.metadata.get("rel_path")
        chunk_id = doc.metadata.get("chunk_id")
        if rel_path and chunk_id:
            if rel_path not in file_to_chunks:
                file_to_chunks[rel_path] = set()
            file_to_chunks[rel_path].add(chunk_id)

    # Only update manifest for files where ALL chunks were successfully inserted
    updated_manifest: Dict[str, str] = dict(manifest)
    fully_successful_files = 0
    partially_failed_files = 0

    for rel_path, fingerprint in file_fingerprints.items():
        expected_chunks = file_to_chunks.get(rel_path, set())
        inserted_chunks = expected_chunks & successfully_inserted_chunks

        if expected_chunks and inserted_chunks == expected_chunks:
            # All chunks for this file were successfully inserted
            updated_manifest[rel_path] = fingerprint
            fully_successful_files += 1
        else:
            # Some chunks failed - don't update manifest so file will be retried next run
            partially_failed_files += 1
            missing_count = len(expected_chunks - inserted_chunks)
            logger.warning(
                f"File {rel_path} had {missing_count}/{len(expected_chunks)} chunks fail - "
                f"will retry on next run"
            )

    logger.info(f"Manifest update summary:")
    logger.info(f"  Fully successful files:    {fully_successful_files:6,}")
    logger.info(f"  Partially failed files:    {partially_failed_files:6,}")
    logger.info(f"  Total manifest entries:    {len(updated_manifest):6,}")

    # ========================================================================
    # PERSISTENCE AND CLEANUP
    # ========================================================================

    logger.info("PHASE 3: Persistence and cleanup")
    
    # Persist vector store
    try:
        logger.info("Persisting vector store to disk...")
        if hasattr(store, "persist"):
            persist_start = time.monotonic()
            store.persist()
            persist_duration = time.monotonic() - persist_start
            logger.info(f"✓ Vector store persisted in {format_duration(persist_duration)}")
        else:
            logger.info("Vector store does not support explicit persistence")
    except Exception as exc:
        logger.error(f"Failed to persist vector store: {exc}")
        logger.debug(traceback.format_exc())
    
    # Save checksum
    if new_checksum:
        try:
            logger.info("Saving new directory checksum...")
            CHECKSUM_FILE.parent.mkdir(parents=True, exist_ok=True)
            CHECKSUM_FILE.write_text(new_checksum)
            logger.info(f"✓ Checksum saved to {CHECKSUM_FILE}")
        except Exception as exc:
            logger.error(f"Failed to write checksum: {exc}")
    
    # Save manifest
    try:
        logger.info("Saving updated manifest...")
        save_manifest(updated_manifest)
    except Exception as exc:
        logger.error(f"Failed to save manifest: {exc}")
    
    # Final cleanup
    logger.info("Running final garbage collection...")
    gc.collect()
    
    # ========================================================================
    # FINAL SUMMARY
    # ========================================================================
    
    total_duration = time.monotonic() - start_total
    
    if perf:
        perf.stop_timer("total_ingestion")
        perf.report()
    
    failed_files = [
        {"path": path, "status": status}
        for path, status in file_status.items()
        if status != "ok"
    ]
    history.append(
        {
            "run_id": run_id,
            "started_at": time.time(),
            "root": str(root),
            "processed_files": len(file_status) - len(failed_files),
            "failed_files": failed_files,
            "failed_batches": failed_batches,
            "elapsed_sec": total_duration,
        }
    )
    _save_history(history)
    
    logger.info("=" * 80)
    logger.info("INGESTION COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Summary:")
    logger.info(f"  Total files processed:        {stats['to_process']:6,}")
    logger.info(f"  Total chunks indexed:         {processed:6,}")
    logger.info(f"  Failed chunks:                {total_chunks - processed:6,}")
    logger.info(f"  Total time:                   {format_duration(total_duration)}")
    logger.info(f"  Overall processing rate:      {safe_divide(processed, total_duration):.1f} chunks/sec")
    logger.info(f"")
    logger.info(f"Phase breakdown:")
    logger.info(f"  Phase 1 (Load/Split):         {format_duration(duration_phase_1)} ({100*duration_phase_1/total_duration:.1f}%)")
    logger.info(f"  Phase 2 (Embed/Insert):       {format_duration(duration_phase_2)} ({100*duration_phase_2/total_duration:.1f}%)")
    logger.info(f"")
    
    if failed_batches == 0 and processed == total_chunks:
        logger.info("✓ SUCCESS: All files and chunks processed successfully")
    else:
        logger.warning(f"⚠ PARTIAL SUCCESS: {failed_batches} batches failed")
    
    logger.info("=" * 80)


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    # Parse command line arguments
    if len(sys.argv) < 2:
        print("Usage: python ingest_documents.py /path/to/documents")
        print("")
        print("Environment variables:")
        print("  INGEST_LOG_LEVEL        - Logging level (DEBUG, INFO, WARNING, ERROR)")
        print("  OLLAMA_EMBED_MODEL      - Embedding model name")
        print("  CHUNK_SIZE              - Size of text chunks")
        print("  CHUNK_OVERLAP           - Overlap between chunks")
        print("  INGEST_MAX_WORKERS      - Number of parallel workers")
        print("  INGEST_BATCH_SIZE       - Batch size for embedding")
        print("  ENABLE_PROFILING        - Enable performance profiling (0 or 1)")
        print("  SKIP_DEDUP              - Skip deduplication check (0 or 1)")
        sys.exit(1)
    
    base = pathlib.Path(sys.argv[1]).resolve()
    
    if not base.exists():
        print(f"Error: Path not found: {base}")
        sys.exit(1)
    
    if not base.is_dir():
        print(f"Error: Path is not a directory: {base}")
        sys.exit(1)
    
    # Log startup information
    logger.info(f"Python version: {sys.version}")
    logger.info(f"Working directory: {os.getcwd()}")
    logger.info(f"Target directory: {base}")
    
    # Run ingestion with tqdm logging redirect
    # This prevents log messages from interfering with progress bars
    try:
        with logging_redirect_tqdm():
            ingest_dir(base)
    except KeyboardInterrupt:
        logger.warning("Ingestion interrupted by user (Ctrl+C)")
        sys.exit(130)
    except Exception as exc:
        logger.critical(f"Fatal error during ingestion: {exc}")
        logger.debug(traceback.format_exc())
        sys.exit(1)
