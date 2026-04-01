"""
Export assistant_feedback rows to static HTML pages for linking.

Usage:
  python chat_app/export_feedback.py --output ./public/feedback --db postgresql+asyncpg://chainlit:chainlit@127.0.0.1:5432/chainlit
"""
import argparse
import asyncio
import os
from pathlib import Path
from typing import List

import asyncpg


TEMPLATE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>{title}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 2rem; max-width: 800px; }}
    .meta {{ color: #555; font-size: 0.9rem; margin-bottom: 1rem; }}
    pre {{ white-space: pre-wrap; word-wrap: break-word; background: #f6f6f6; padding: 1rem; border-radius: 4px; }}
  </style>
 </head>
 <body>
   <h1>{title}</h1>
   <div class="meta">Created: {created_at} | User: {username} | Thread: {thread_id}</div>
   <pre>{comment}</pre>
 </body>
</html>
"""


async def fetch_feedback(conninfo: str, limit: int = 200) -> List[asyncpg.Record]:
    conn = await asyncpg.connect(conninfo)
    try:
        rows = await conn.fetch(
            """
            SELECT id, created_at, username, thread_id, comment
            FROM assistant_feedback
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
        )
        return rows
    finally:
        await conn.close()


def write_feedback(output_dir: Path, rows: List[asyncpg.Record]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    index_lines = ["<h1>Feedback Index</h1><ul>"]
    for row in rows:
        fid = str(row["id"])
        fname = output_dir / f"{fid}.html"
        html = TEMPLATE.format(
            title=f"Feedback {fid}",
            created_at=row["created_at"],
            username=row["username"] or "unknown",
            thread_id=row["thread_id"] or "n/a",
            comment=row["comment"] or "",
        )
        fname.write_text(html, encoding="utf-8")
        index_lines.append(f'<li><a href="{fid}.html">{row["created_at"]} | {row["username"] or "unknown"}</a></li>')
    index_lines.append("</ul>")
    (output_dir / "index.html").write_text("\n".join(index_lines), encoding="utf-8")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="./public/feedback", help="Output directory for static feedback pages")
    parser.add_argument(
        "--db",
        default=os.getenv("CHAINLIT_DB_CONNINFO") or "postgresql+asyncpg://chainlit:chainlit@127.0.0.1:5432/chainlit",
        help="Database URL (asyncpg style)",
    )
    parser.add_argument("--limit", type=int, default=200, help="Max feedback rows to export")
    args = parser.parse_args()

    rows = await fetch_feedback(args.db, args.limit)
    write_feedback(Path(args.output), rows)
    print(f"Wrote {len(rows)} feedback pages to {args.output}")


if __name__ == "__main__":
    asyncio.run(main())
