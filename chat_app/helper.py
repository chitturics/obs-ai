"""Helper utilities for ObsAI - Observability AI Assistant.

Provides common utility functions used across the application:
- ``current_username()`` / ``current_thread_id()`` — session helpers
- ``extract_urls()`` — URL extraction from text
- ``build_splunk_link()`` — construct Splunk Web search URLs
"""

import os
import re
import urllib.parse
import logging
from typing import List

import chainlit as cl

logger = logging.getLogger(__name__)

URL_REGEX = re.compile(r"https?://\S+")


def current_username() -> str:
    """Return the current authenticated user's identifier, or ``"anonymous"``."""
    user = cl.user_session.get("user")
    if user:
        ident = getattr(user, "identifier", None) or getattr(user, "username", None)
        if ident and str(ident).strip():
            return str(ident).strip()
    return "anonymous"


def current_thread_id() -> str:
    """Return the current chat thread ID, or ``"unknown"``."""
    thread = cl.user_session.get("thread")
    if thread:
        return thread.get("id", "unknown")
    return "unknown"


def extract_urls(text: str) -> List[str]:
    """Extract HTTP/HTTPS URLs from text.

    Args:
        text: Text to search for URLs.

    Returns:
        List of URL strings found in text.
    """
    if not text:
        return []
    return URL_REGEX.findall(text)


def build_splunk_link(query: str, earliest: str = "-24h", latest: str = "now") -> str:
    """Build a clickable Splunk Web search URL.

    The base URL is read from the ``SPLUNK_BASE_URL`` environment variable.
    If not set, a placeholder URL is used.

    Args:
        query: SPL query string.
        earliest: Earliest time for search (default: ``-24h``).
        latest: Latest time for search (default: ``now``).

    Returns:
        Full Splunk search URL with encoded parameters.
    """
    base = os.getenv(
        "SPLUNK_BASE_URL",
        "https://splunk.example.com/en-US/app/search/search",
    )
    q = urllib.parse.quote(query)
    e = urllib.parse.quote(earliest)
    lt = urllib.parse.quote(latest)
    sep = "&" if "?" in base else "?"
    return f"{base}{sep}q={q}&earliest={e}&latest={lt}"
