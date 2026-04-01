#!/usr/bin/env python3
"""
Download latest Splunk spec files from GitHub repository
https://github.com/jewnix/splunk-spec-files
"""

import os
import sys
import json
import shutil
import requests
import tempfile
from pathlib import Path
from typing import Optional, Dict, List, Any
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# GitHub repository details
GITHUB_REPO = "jewnix/splunk-spec-files"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_REPO}"
GITHUB_RAW_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}"
# Preferred version (can be overridden via env). Default pinned to 9.3.2 per deployment requirement.
DEFAULT_VERSION = os.getenv("SPLUNK_SPEC_VERSION", "9.3.2")


def get_latest_version() -> Optional[str]:
    """
    Get the latest Splunk version available in the repository.
    Returns version string like "9.2" or None if unable to fetch.
    """
    # If an explicit default is configured, use it without hitting the API.
    if DEFAULT_VERSION:
        logger.info(f"Using configured default version: {DEFAULT_VERSION}")
        return DEFAULT_VERSION

    try:
        # Get directory listing from GitHub API
        url = f"{GITHUB_API_URL}/contents"
        headers = {
            'Accept': 'application/vnd.github.v3+json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()

        contents = response.json()

        # Check if we got an error message
        if isinstance(contents, dict) and 'message' in contents:
            logger.error(f"GitHub API error: {contents['message']}")
            # Fallback to known versions if API fails
            logger.warning("Using fallback to known Splunk versions")
            return DEFAULT_VERSION or "9.3.2"  # Default to pinned version

        # Find all version directories (numeric folders like 9.2, 9.1, etc.)
        versions = []
        for item in contents:
            if isinstance(item, dict) and item.get('type') == 'dir':
                name = item.get('name', '')
                # Check if it looks like a version number (e.g., "9.2", "8.0")
                if name and name.replace('.', '').replace('-', '').isdigit():
                    versions.append(name)

        if not versions:
            logger.warning("No version directories found in API response")
            logger.info("Falling back to known Splunk versions")
            # Fallback to known versions (9.2 is confirmed to exist)
            known_versions = ["9.3.2", "9.2", "9.1", "9.0", "8.2", "8.1", "8.0", "7.3"]
            return known_versions[0]

        # Sort versions and get the latest
        versions.sort(key=lambda x: [int(i) for i in x.split('.') if i.isdigit()], reverse=True)
        latest = versions[0]

        logger.info(f"Latest Splunk version found: {latest}")
        logger.info(f"Available versions: {', '.join(versions)}")

        return latest

    except Exception as e:
        logger.error(f"Failed to get latest version: {e}")
        logger.info(f"Using default version {DEFAULT_VERSION or '9.3.2'}")
        return DEFAULT_VERSION or "9.3.2"  # Fallback to a pinned default


def _fetch_contents(path: str = "", ref: Optional[str] = None) -> List[Dict[str, Any]]:
    url = f"{GITHUB_API_URL}/contents"
    if path:
        url = f"{url}/{path.strip('/')}"
    params = {"ref": ref} if ref else {}
    resp = requests.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_version_files(version: str) -> List[Dict[str, str]]:
    """
    Get list of all files for a specific version.
    Tries folder-style paths first, then branch/tag refs at repo root.
    """
    candidates = [
        {"path": version, "ref": None},         # folder named version
        {"path": "", "ref": version},           # branch/tag named version at repo root
    ]

    for candidate in candidates:
        try:
            contents = _fetch_contents(candidate["path"], candidate["ref"])
        except requests.HTTPError as exc:
            if exc.response.status_code == 404:
                continue
            logger.error(f"Failed to fetch contents for version {version}: {exc}")
            continue
        except Exception as exc:
            logger.error(f"Failed to fetch contents for version {version}: {exc}")
            continue

        files: List[Dict[str, str]] = []
        for item in contents:
            if item.get("type") == "file":
                name = item.get("name", "")
                if name.endswith(".spec") or name.endswith(".conf"):
                    files.append(
                        {
                            "name": name,
                            "download_url": item.get("download_url"),
                            "size": item.get("size", 0),
                        }
                    )

        if files:
            logger.info(
                f"Found {len(files)} spec/conf files in version {version} "
                f"(path='{candidate['path']}', ref='{candidate['ref'] or 'default'}')"
            )
            return files

    logger.error(f"No spec/conf files found for version {version}")
    return []


def download_file(file_info: Dict[str, str], target_dir: Path) -> bool:
    """
    Download a single file from GitHub.
    Returns True if successful, False otherwise.
    """
    try:
        name = file_info['name']
        url = file_info['download_url']
        target_path = target_dir / name

        response = requests.get(url, timeout=30)
        response.raise_for_status()

        # Write file
        target_path.write_bytes(response.content)
        logger.debug(f"Downloaded: {name} ({file_info['size']} bytes)")

        return True

    except Exception as e:
        logger.error(f"Failed to download {file_info['name']}: {e}")
        return False


def download_specs(target_dir: Path, version: Optional[str] = None, clean: bool = True) -> bool:
    """
    Download all spec files from GitHub repository.

    Args:
        target_dir: Directory to save files to
        version: Specific version to download (e.g., "9.2"), or None for latest
        clean: If True, remove existing .spec and .conf files before downloading

    Returns:
        True if successful, False otherwise
    """
    logger.info("=" * 80)
    logger.info("SPLUNK SPEC FILES DOWNLOADER")
    logger.info("=" * 80)
    logger.info(f"Repository: https://github.com/{GITHUB_REPO}")
    logger.info(f"Target directory: {target_dir}")

    # Ensure target directory exists
    target_dir.mkdir(parents=True, exist_ok=True)

    # Get version to download
    if version is None:
        logger.info("Finding latest/pinned version...")
        version = get_latest_version()
        if version is None:
            logger.error("Failed to determine version")
            return False
    else:
        logger.info(f"Using specified version: {version}")

    # Clean target directory if requested
    if clean:
        logger.info("Cleaning existing spec/conf files...")
        removed = 0
        for ext in ['.spec', '.conf']:
            for file in target_dir.glob(f'*{ext}'):
                file.unlink()
                removed += 1
        if removed > 0:
            logger.info(f"Removed {removed} existing files")

    # Get file list
    logger.info(f"Fetching file list for version {version}...")
    files = get_version_files(version)

    if not files:
        logger.error("No files found to download")
        return False

    # Download all files
    logger.info(f"Downloading {len(files)} files...")
    success_count = 0
    failed_count = 0

    for i, file_info in enumerate(files, 1):
        logger.info(f"  [{i}/{len(files)}] {file_info['name']}")
        if download_file(file_info, target_dir):
            success_count += 1
        else:
            failed_count += 1

    # Summary
    logger.info("=" * 80)
    logger.info("DOWNLOAD COMPLETE")
    logger.info("=" * 80)
    logger.info(f"Version: {version}")
    logger.info(f"Files downloaded: {success_count}")
    logger.info(f"Files failed: {failed_count}")
    logger.info(f"Target directory: {target_dir}")

    # Save metadata
    metadata = {
        'version': version,
        'download_date': str(Path(__file__).stat().st_mtime),
        'repository': GITHUB_REPO,
        'total_files': len(files),
        'success_count': success_count,
        'failed_count': failed_count
    }

    metadata_file = target_dir / '.download_metadata.json'
    metadata_file.write_text(json.dumps(metadata, indent=2))
    logger.info(f"Metadata saved to: {metadata_file}")

    return failed_count == 0


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Download latest Splunk spec files from GitHub'
    )
    parser.add_argument(
        'target_dir',
        type=Path,
        help='Directory to save spec files to'
    )
    parser.add_argument(
        '-v', '--version',
        help='Specific version to download (e.g., 9.2). Default: latest'
    )
    parser.add_argument(
        '--no-clean',
        action='store_true',
        help='Do not remove existing spec/conf files before downloading'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='Enable debug logging'
    )

    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Download specs
    success = download_specs(
        target_dir=args.target_dir,
        version=args.version,
        clean=not args.no_clean
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
