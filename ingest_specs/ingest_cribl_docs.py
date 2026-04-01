#!/usr/bin/env python3
"""
Cribl Documentation Ingestion Script

This script downloads key pages from the Cribl documentation website and ingests
them into a dedicated ChromaDB collection.

Steps:
1. Downloads a predefined list of URLs.
2. Saves the HTML content to the `documents/cribl` directory.
3. Runs the `ingest_generic.py` script to process the downloaded files
   into the `cribl_docs_mxbai` collection.
"""

import os
import sys
import hashlib
import subprocess
from pathlib import Path
import httpx
from tqdm import tqdm

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from chat_app.puppeteer import fetch_with_playwright


# =============================================================================
# CONFIGURATION
# =============================================================================

# URLs to download
CRIBL_DOCS_URLS = [
    "https://docs.cribl.io/stream/latest/architecture",
    "https://docs.cribl.io/stream/latest/sources",
    "https://docs.cribl.io/stream/latest/destinations",
    "https://docs.cribl.io/stream/latest/pipelines",
    "https://docs.cribl.io/stream/latest/functions",
    "https://docs.cribl.io/stream/latest/routing",
    "https://docs.cribl.io/stream/latest/lookups",
    "https://docs.cribl.io/stream/latest/data-formats",
]

# Ingestion configuration
DOWNLOAD_DIR = Path(__file__).parent.parent / "documents" / "cribl"
CHROMA_COLLECTION = "cribl_docs_mxbai"
INGEST_SCRIPT = Path(__file__).parent / "ingest_generic.py"

# =============================================================================
# DOWNLOAD
# =============================================================================

def download_url(url: str, output_dir: Path) -> Path:
    """Download a single URL using Playwright and save it to a file."""
    try:
        content_type, html_content = fetch_with_playwright(url)
    except Exception as e:
        raise RuntimeError(f"Playwright fetch failed for {url}: {e}")

    if "html" not in content_type:
        raise RuntimeError(f"Content type is not HTML: {content_type}")

    # Create a filename from the URL
    filename = url.split("://")[1].replace("/", "_") + ".html"
    output_path = output_dir / filename

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    return output_path

def download_all_docs():
    """Download all configured Cribl documentation pages."""
    print(f"Downloading {len(CRIBL_DOCS_URLS)} Cribl documentation pages using Playwright...")
    print(f"Output directory: {DOWNLOAD_DIR}")
    print("")

    DOWNLOAD_DIR.mkdir(exist_ok=True)
    downloaded_files = []

    for url in tqdm(CRIBL_DOCS_URLS, desc="Downloading URLs"):
        try:
            output_path = download_url(url, DOWNLOAD_DIR)
            downloaded_files.append(output_path)
            tqdm.write(f"✓ Downloaded: {url} -> {output_path.name}")
        except Exception as e:
            tqdm.write(f"Failed to download {url}: {e}")

    print(f"\nSuccessfully downloaded {len(downloaded_files)} files.")
    return downloaded_files

# =============================================================================
# INGEST
# =============================================================================

def run_ingestion():
    """Run the generic ingestion script on the downloaded files."""
    print("\n" + "="*80)
    print("STARTING INGESTION OF CRIBL DOCUMENTATION")
    print("="*80)

    # Set environment variables for the ingestion script
    env = os.environ.copy()
    env["CHROMA_COLLECTION"] = CHROMA_COLLECTION
    env["SOURCE_ROOT"] = str(DOWNLOAD_DIR)
    env["FILE_PATTERNS"] = "*.html"
    env["CHUNK_SIZE"] = "1000"
    env["CHUNK_OVERLAP"] = "200"

    try:
        process = subprocess.run(
            [sys.executable, str(INGEST_SCRIPT)],
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        print(process.stdout)
        if process.stderr:
            print("--- STDERR ---")
            print(process.stderr)

        print("\nIngestion process completed successfully.")

    except subprocess.CalledProcessError as e:
        print(f"ERROR: Ingestion script failed with exit code {e.returncode}")
        print("\n--- STDOUT ---")
        print(e.stdout)
        print("\n--- STDERR ---")
        print(e.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        sys.exit(1)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    # Step 1: Download documentation
    downloaded = download_all_docs()

    if not downloaded:
        print("\nNo files were downloaded. Aborting ingestion.")
        sys.exit(1)

    # Step 2: Run ingestion
    run_ingestion()

    print("\nCribl documentation ingestion complete.")
    sys.exit(0)
