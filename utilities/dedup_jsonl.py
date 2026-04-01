#!/usr/bin/env python3
"""
Deduplicate a JSONL fine-tune file by instruction+response.
Usage:
  python scripts/dedup_jsonl.py data/fine_tune_data.jsonl
Writes back in place and creates a .bak copy.
"""

import hashlib
import json
import shutil
import sys
from pathlib import Path


def record_key(rec: dict) -> str:
    instr = (rec.get("instruction") or "").strip()
    resp = (rec.get("response") or "").strip()
    return hashlib.sha256(f"{instr}\u0000{resp}".encode("utf-8")).hexdigest()


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/dedup_jsonl.py /path/to/file.jsonl")
        sys.exit(1)
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"Not found: {path}")
        sys.exit(1)

    rows = []
    seen = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        k = record_key(rec)
        if k in seen:
            continue
        seen.add(k)
        rows.append(rec)

    bak = path.with_suffix(path.suffix + ".bak")
    shutil.copyfile(path, bak)
    with path.open("w", encoding="utf-8") as f:
        for rec in rows:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"Deduped {path} -> kept {len(rows)} records; backup at {bak}")


if __name__ == "__main__":
    main()
