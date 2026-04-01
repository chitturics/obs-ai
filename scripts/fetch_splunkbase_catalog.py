#!/usr/bin/env python3
"""
Fetch Splunkbase catalog from the API and save as JSON.

Run this on a machine WITH internet access, then copy the output file
to the production server at: documents/splunkbase_catalog.json

The start_all.sh script mounts documents/ into the container, so the
catalog will be available at /app/shared/public/documents/splunkbase_catalog.json

Usage:
    python3 scripts/fetch_splunkbase_catalog.py
    python3 scripts/fetch_splunkbase_catalog.py --output /path/to/catalog.json
    python3 scripts/fetch_splunkbase_catalog.py --max-apps 100  # quick test
"""
import argparse
import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

SPLUNKBASE_API = "https://splunkbase.splunk.com/api/v1/app/"
PAGE_SIZE = 100


def fetch_page(offset: int, limit: int) -> dict:
    """Fetch one page of apps from Splunkbase API (with releases included)."""
    url = f"{SPLUNKBASE_API}?limit={limit}&offset={offset}&order=latest&include=releases"
    req = Request(url, headers={"User-Agent": "ObsAI-CatalogBuilder/1.0"})
    with urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_version_tuple(v: str):
    """Parse '1.2.3' into (1, 2, 3) for comparison."""
    parts = []
    for s in v.split("."):
        try:
            parts.append(int(s))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def extract_app(app_data: dict) -> dict:
    """Extract catalog entry from API response item."""
    uid = str(app_data.get("uid", app_data.get("id", "")))
    releases_raw = app_data.get("releases", app_data.get("release", []))
    if isinstance(releases_raw, dict):
        releases_raw = [releases_raw]

    releases = []
    for rel in (releases_raw or []):
        releases.append({
            "version": rel.get("name", rel.get("title", rel.get("version", "unknown"))),
            "release_date": rel.get("published_datetime", rel.get("created_datetime", "")),
            "product_versions": [
                pv.get("name", str(pv)) if isinstance(pv, dict) else str(pv)
                for pv in (rel.get("product_versions", []) or [])
            ],
        })

    releases.sort(key=lambda r: parse_version_tuple(r["version"]), reverse=True)
    latest = releases[0] if releases else {}
    latest_version = latest.get("version") or app_data.get("version", "unknown")

    return {
        "uid": uid,
        "title": app_data.get("title", ""),
        "app_id": app_data.get("appid", app_data.get("name", "")),
        "latest_version": latest_version,
        "latest_release_date": latest.get("release_date", app_data.get("updated_time", "")),
        "supported_splunk_versions": latest.get("product_versions", []),
        "sourcetypes": app_data.get("sourcetypes", []) or [],
        "releases": releases,
    }


def main():
    parser = argparse.ArgumentParser(description="Fetch Splunkbase catalog")
    parser.add_argument("--output", "-o", default="documents/splunkbase_catalog.json")
    parser.add_argument("--max-apps", type=int, default=0, help="0 = fetch all")
    args = parser.parse_args()

    print(f"Fetching Splunkbase catalog...")
    print(f"Output: {args.output}")

    all_apps = []
    offset = 0
    api_total = None

    while True:
        if args.max_apps > 0 and len(all_apps) >= args.max_apps:
            break

        try:
            data = fetch_page(offset, PAGE_SIZE)
        except (URLError, OSError, ValueError) as e:
            print(f"  ERROR fetching page at offset {offset}: {e}")
            if not all_apps:
                print("No apps fetched. Check internet connectivity.")
                sys.exit(1)
            break

        if api_total is None:
            api_total = data.get("total", 0)
            print(f"  API reports {api_total} total apps")

        results = data.get("results", [])
        if not results:
            break

        all_apps.extend(results)
        offset += len(results)

        pct = (len(all_apps) / max(api_total, 1)) * 100 if api_total else 0
        print(f"  Fetched {len(all_apps)}/{api_total} ({pct:.0f}%)")

        if len(results) < PAGE_SIZE:
            break
        if api_total and len(all_apps) >= api_total:
            break

        time.sleep(0.5)  # Be polite to the API

    # Build catalog
    catalog = {"metadata": {}, "apps": {}}
    failed = 0
    for app_data in all_apps:
        uid = str(app_data.get("uid", app_data.get("id", "")))
        if not uid:
            continue
        try:
            catalog["apps"][uid] = extract_app(app_data)
        except Exception as e:
            failed += 1

    from datetime import datetime, timezone
    catalog["metadata"] = {
        "last_updated": datetime.now(timezone.utc).isoformat(),
        "total_apps": len(catalog["apps"]),
        "source": "splunkbase_api_offline_fetch",
    }

    # Write
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(catalog, indent=2, default=str), encoding="utf-8")

    print(f"\nDone: {len(catalog['apps'])} apps saved to {out_path}")
    print(f"  Failed: {failed}")
    print(f"\nCopy this file to your production server:")
    print(f"  scp {out_path} user@server:/opt/obsai/chatbot/documents/splunkbase_catalog.json")
    print(f"\nThe app will auto-load it on next scan.")


if __name__ == "__main__":
    main()
