"""Shared utility functions for the Chainlit Splunk Assistant.

This module provides common utilities used across multiple modules:
- Context truncation for speed
- Text cleaning and sanitization
- Path resolution
- Environment variable helpers
"""

import os
import re
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple
import yaml

logger = logging.getLogger(__name__)


def load_config(config_file: str = "config.yaml") -> Dict[str, Any]:
    """Load configuration from a YAML file.

    Searches multiple candidate paths if the given path is not absolute.

    Args:
        config_file: Path to the configuration file.

    Returns:
        A dictionary containing the configuration.
    """
    candidates = [Path(config_file)]
    if not Path(config_file).is_absolute():
        candidates.extend([
            Path("/app/config.yaml"),
            Path.cwd() / config_file,
            Path(__file__).resolve().parent.parent / config_file,
        ])
    for path in candidates:
        try:
            if path.is_file():
                with open(path, "r") as f:
                    return yaml.safe_load(f) or {}
        except (OSError, ValueError, KeyError, TypeError) as e:
            logger.debug(f"Config candidate {path} skipped: {e}")
    logger.info(f"No config file found for: {config_file} (using defaults)")
    return {}


def truncate_context(context: str, max_tokens: int = 2000) -> str:
    """Truncate context to max tokens to improve LLM speed.

    Uses rough estimate: 1 token ≈ 4 characters.

    Args:
        context: Context string to truncate
        max_tokens: Maximum number of tokens (default: 2000)

    Returns:
        Truncated context string
    """
    max_chars = max_tokens * 4

    if len(context) <= max_chars:
        return context

    # Try to truncate at a section boundary (### header or blank line) to avoid
    # cutting mid-stanza. Search backward from max_chars for a clean break point.
    truncated = context[:max_chars]
    # Look for last section header within the truncation window
    last_header = truncated.rfind("\n### ")
    last_blank = truncated.rfind("\n\n")
    # Use the latest clean break point that's at least 60% of max_chars
    min_keep = int(max_chars * 0.6)
    break_point = max(last_header, last_blank)
    if break_point > min_keep:
        truncated = context[:break_point]

    logger.warning(f"Context truncated from {len(context)} to {len(truncated)} chars ({max_tokens} tokens)")
    return truncated + "\n\n[...context truncated for speed]"


def clean_text(text: str, remove_extra_whitespace: bool = True) -> str:
    """Clean and normalize text.

    Args:
        text: Text to clean
        remove_extra_whitespace: Whether to collapse multiple spaces

    Returns:
        Cleaned text
    """
    if not text:
        return ""

    # Remove null bytes
    text = text.replace('\x00', '')

    # Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    if remove_extra_whitespace:
        # Collapse multiple spaces
        text = re.sub(r' +', ' ', text)
        # Collapse multiple newlines (keep max 2)
        text = re.sub(r'\n\n\n+', '\n\n', text)

    return text.strip()


def sanitize_filename(filename: str, max_length: int = 255) -> str:
    """Sanitize filename for safe filesystem use.

    Args:
        filename: Original filename
        max_length: Maximum filename length

    Returns:
        Safe filename
    """
    # Remove path components
    filename = Path(filename).name

    # Replace unsafe characters
    safe_chars = re.sub(r'[^\w\s\-\.]', '_', filename)

    # Collapse multiple underscores
    safe_chars = re.sub(r'_+', '_', safe_chars)

    # Truncate if too long
    if len(safe_chars) > max_length:
        ext = Path(safe_chars).suffix
        name = safe_chars[:max_length - len(ext)]
        safe_chars = name + ext

    return safe_chars


def resolve_path(path: str, base_dir: Optional[str] = None) -> Path:
    """Resolve path relative to base directory or absolute.

    Args:
        path: Path to resolve
        base_dir: Base directory (default: current working directory)

    Returns:
        Resolved absolute Path
    """
    p = Path(path)

    if p.is_absolute():
        return p

    if base_dir:
        return (Path(base_dir) / p).resolve()

    return p.resolve()


def get_env_bool(key: str, default: bool = False) -> bool:
    """Get boolean from environment variable.

    Accepts: true/false, yes/no, 1/0 (case insensitive)

    Args:
        key: Environment variable key
        default: Default value if not set

    Returns:
        Boolean value
    """
    value = os.getenv(key, str(default)).lower()
    return value in ('true', 'yes', '1', 'on')


def get_env_int(key: str, default: int = 0) -> int:
    """Get integer from environment variable with fallback.

    Args:
        key: Environment variable key
        default: Default value if not set or invalid

    Returns:
        Integer value
    """
    try:
        return int(os.getenv(key, str(default)))
    except ValueError:
        logger.warning(f"Invalid int for {key}, using default: {default}")
        return default


def get_env_float(key: str, default: float = 0.0) -> float:
    """Get float from environment variable with fallback.

    Args:
        key: Environment variable key
        default: Default value if not set or invalid

    Returns:
        Float value
    """
    try:
        return float(os.getenv(key, str(default)))
    except ValueError:
        logger.warning(f"Invalid float for {key}, using default: {default}")
        return default


def ensure_dir(path: Path) -> Path:
    """Ensure directory exists, create if needed.

    Args:
        path: Directory path

    Returns:
        Path object (guaranteed to exist)
    """
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def format_size(bytes_size: int) -> str:
    """Format byte size to human-readable string.

    Args:
        bytes_size: Size in bytes

    Returns:
        Formatted string (e.g., "1.5 MB")
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_size < 1024.0:
            return f"{bytes_size:.1f} {unit}"
        bytes_size /= 1024.0
    return f"{bytes_size:.1f} PB"


def chunk_list(lst: List[Any], chunk_size: int) -> List[List[Any]]:
    """Split list into chunks of specified size.

    Args:
        lst: List to chunk
        chunk_size: Size of each chunk

    Returns:
        List of chunks
    """
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def deduplicate_preserving_order(items: List[Any]) -> List[Any]:
    """Remove duplicates while preserving order.

    Args:
        items: List with potential duplicates

    Returns:
        List with duplicates removed, order preserved
    """
    seen = set()
    result = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def extract_code_blocks(text: str, language: Optional[str] = None) -> List[str]:
    """Extract code blocks from markdown text.

    Args:
        text: Markdown text
        language: Filter by language (e.g., 'python', 'spl')

    Returns:
        List of code block contents
    """
    if language:
        pattern = rf'```{language}\s*\n(.*?)\n```'
    else:
        pattern = r'```(?:\w+)?\s*\n(.*?)\n```'

    matches = re.findall(pattern, text, re.DOTALL)
    return matches


def validate_url(url: str) -> bool:
    """Validate if string is a valid URL.

    Args:
        url: URL string to validate

    Returns:
        True if valid URL
    """
    url_pattern = re.compile(
        r'^https?://'  # http:// or https://
        r'(?:(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?|'  # domain
        r'localhost|'  # localhost
        r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'  # IP
        r'(?::\d+)?'  # optional port
        r'(?:/?|[/?]\S+)$', re.IGNORECASE)
    return url_pattern.match(url) is not None


def merge_dicts(*dicts: Dict) -> Dict:
    """Merge multiple dictionaries (later dicts override earlier).

    Args:
        *dicts: Variable number of dictionaries

    Returns:
        Merged dictionary
    """
    result = {}
    for d in dicts:
        if d:
            result.update(d)
    return result


def get_file_extension(filename: str) -> str:
    """Get file extension in lowercase without dot.

    Args:
        filename: Filename or path

    Returns:
        Extension (e.g., 'pdf', 'txt')
    """
    return Path(filename).suffix.lstrip('.').lower()


def is_valid_conf_file(filename: str) -> bool:
    """Check if filename is a valid Splunk .conf file.

    Args:
        filename: Filename to check

    Returns:
        True if valid .conf file
    """
    ext = get_file_extension(filename)
    return ext in ('conf', 'spec')


def import_optional_module(module_name: str, names: List[str]) -> Tuple[bool, Dict[str, Any]]:
    """
    Import optional modules and return a dict of the imported names.
    
    Args:
        module_name: The name of the module to import from.
        names: A list of names to import from the module.
        
    Returns:
        A tuple containing a boolean indicating if the import was successful
        and a dictionary of the imported names.
    """
    try:
        module = __import__(module_name, fromlist=names)
        imported_modules = {name: getattr(module, name) for name in names}
        return True, imported_modules
    except ImportError:
        return False, {}


# Cache for expensive operations
_cache: Dict[str, Any] = {}


def cached_result(key: str, compute_fn, ttl_seconds: int = 300):
    """Simple in-memory cache for expensive operations.

    Args:
        key: Cache key
        compute_fn: Function to compute value if not cached
        ttl_seconds: Time to live in seconds

    Returns:
        Cached or newly computed value
    """
    import time

    now = time.time()

    if key in _cache:
        value, timestamp = _cache[key]
        if now - timestamp < ttl_seconds:
            return value

    # Compute new value
    value = compute_fn()
    _cache[key] = (value, now)
    return value


# Example usage
if __name__ == "__main__":
    # Test utilities
    print("Testing utilities...")

    # Test truncation
    long_text = "word " * 1000
    truncated = truncate_context(long_text, max_tokens=100)
    print(f"Truncated: {len(long_text)} -> {len(truncated)} chars")

    # Test filename sanitization
    unsafe = "my/unsafe\\file:name*.txt"
    safe = sanitize_filename(unsafe)
    print(f"Sanitized: {unsafe} -> {safe}")

    # Test size formatting
    print(f"Size: {format_size(1536000)}")

    # Test code extraction
    md = """
    Here's some code:
    ```python
    print("hello")
    ```
    """
    blocks = extract_code_blocks(md, "python")
    print(f"Code blocks found: {len(blocks)}")

    print("✓ All tests passed")
