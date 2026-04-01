"""
Postgres-backed interaction and feedback logging for Chainlit.
Creates tables if missing and exposes async helpers for logging and retrieval.
"""
import uuid
import json
import os
import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from langchain_chroma import Chroma
from chat_app.vectorstore import _get_by_filter

from sqlalchemy import (
    Column,
    DateTime,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    func,
    insert,
    delete,
    select,
)
from sqlalchemy.dialects.postgresql import UUID, insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


metadata = MetaData()

doc_ingests = Table(
    "assistant_doc_ingests",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("username", String),
    Column("thread_id", String),
    Column("source", Text),
    Column("kind", String),  # url, file, upload
    Column("fingerprint", String),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

interactions = Table(
    "assistant_interactions",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("username", String, nullable=False),
    Column("thread_id", String),
    Column("question", Text),
    Column("answer", Text),
    Column("context", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

user_feedback = Table(
    "assistant_feedback",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("message_id", String),
    Column("value", Integer),
    Column("comment", Text),
    Column("username", String),
    Column("thread_id", String),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

notes = Table(
    "assistant_notes",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("title", String),
    Column("body", Text),
    Column("created_by", String),
    Column("thread_id", String),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

liked_queries = Table(
    "assistant_liked_queries",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("username", String),
    Column("thread_id", String),
    Column("question", Text),
    Column("answer", Text),
    Column("context", Text),
    Column("source_message_id", String),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

disliked_queries = Table(
    "assistant_disliked_queries",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("username", String),
    Column("thread_id", String),
    Column("question", Text),
    Column("answer", Text),
    Column("context", Text),
    Column("source_message_id", String),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

bad_spl_generations = Table(
    "assistant_bad_spl_generations",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("username", String),
    Column("thread_id", String),
    Column("user_question", Text),
    Column("generated_spl", Text),
    Column("validation_errors", Text),
    Column("llm_context", Text),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

mcp_tokens = Table(
    "assistant_mcp_tokens",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("user_id", String, nullable=False),
    Column("server_name", String, nullable=False),
    Column("auth_scheme", String, default="none"),
    Column("access_token", Text, nullable=False),
    Column("refresh_token", Text),
    Column("expires_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
    UniqueConstraint("user_id", "server_name", name="uq_mcp_tokens_user_server"),
)

followup_sequences = Table(
    "assistant_followup_sequences",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("parent_question_hash", String(64), nullable=False),
    Column("followup_question", Text, nullable=False),
    Column("parent_question", Text),
    Column("username", String),
    Column("thread_id", String),
    Column("count", Integer, default=1, nullable=False),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now(), onupdate=func.now()),
    UniqueConstraint("parent_question_hash", "followup_question", name="uq_followup_parent_followup"),
)


async def init_storage(conninfo: str, existing_engine: AsyncEngine = None) -> AsyncEngine:
    """Initialize storage schema. Uses existing_engine if provided to avoid connection leaks."""
    engine = existing_engine or create_async_engine(conninfo, future=True)
    # Use IF NOT EXISTS DDL to avoid duplicate-type errors when volumes
    # already hold these tables (e.g., recreated containers).
    ddl_statements = [
        """
        CREATE TABLE IF NOT EXISTS assistant_doc_ingests (
            id UUID PRIMARY KEY,
            username TEXT,
            thread_id TEXT,
            source TEXT,
            kind TEXT,
            fingerprint TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_interactions (
            id UUID PRIMARY KEY,
            username TEXT NOT NULL,
            thread_id TEXT,
            question TEXT,
            answer TEXT,
            context TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_feedback (
            id UUID PRIMARY KEY,
            message_id TEXT,
            value INT,
            comment TEXT,
            username TEXT,
            thread_id TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_notes (
            id UUID PRIMARY KEY,
            title TEXT,
            body TEXT,
            created_by TEXT,
            thread_id TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_liked_queries (
            id UUID PRIMARY KEY,
            username TEXT,
            thread_id TEXT,
            question TEXT,
            answer TEXT,
            context TEXT,
            source_message_id TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_disliked_queries (
            id UUID PRIMARY KEY,
            username TEXT,
            thread_id TEXT,
            question TEXT,
            answer TEXT,
            context TEXT,
            source_message_id TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_bad_spl_generations (
            id UUID PRIMARY KEY,
            username TEXT,
            thread_id TEXT,
            user_question TEXT,
            generated_spl TEXT,
            validation_errors TEXT,
            llm_context TEXT,
            created_at TIMESTAMPTZ DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_mcp_tokens (
            id UUID PRIMARY KEY,
            user_id TEXT NOT NULL,
            server_name TEXT NOT NULL,
            auth_scheme TEXT DEFAULT 'none',
            access_token TEXT NOT NULL,
            refresh_token TEXT,
            expires_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(user_id, server_name)
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assistant_followup_sequences (
            id UUID PRIMARY KEY,
            parent_question_hash VARCHAR(64) NOT NULL,
            followup_question TEXT NOT NULL,
            parent_question TEXT,
            username TEXT,
            thread_id TEXT,
            count INT DEFAULT 1 NOT NULL,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW(),
            UNIQUE(parent_question_hash, followup_question)
        )
        """,
    ]
    async with engine.begin() as conn:
        for ddl in ddl_statements:
            await conn.exec_driver_sql(ddl)
        # Also create metadata tables if missing (idempotent)
        await conn.run_sync(metadata.create_all, checkfirst=True)
    return engine


async def log_interaction(
    engine: AsyncEngine,
    username: str,
    thread_id: Optional[str],
    question: str,
    answer: str,
    context: str,
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            insert(interactions).values(
                id=uuid.uuid4(),
                username=username,
                thread_id=thread_id,
                question=question,
                answer=answer,
                context=context,
            )
        )


async def log_feedback(
    engine: AsyncEngine,
    message_id: str,
    value: int,
    comment: Optional[str],
    username: str,
    thread_id: Optional[str],
    title: Optional[str] = None,
    question: Optional[str] = None,
    answer: Optional[str] = None,
    context: Optional[str] = None,
) -> Optional[str]:
    async with engine.begin() as conn:
        await conn.execute(
            insert(user_feedback).values(
                id=uuid.uuid4(),
                message_id=message_id,
                value=value,
                comment=comment or "",
                username=username,
                thread_id=thread_id,
            )
        )
        if comment:
            note_title = title or (question or "User feedback")
            await conn.execute(
                insert(notes).values(
                    id=uuid.uuid4(),
                    title=note_title,
                    body=comment,
                    created_by=username,
                    thread_id=thread_id,
                )
            )

    return _maybe_write_feedback_html(
        message_id=message_id,
        value=value,
        comment=comment or "",
        username=username,
        thread_id=thread_id,
        title=title or question or "User feedback",
        question=question or "",
        answer=answer or "",
        context=context or "",
    )


async def log_doc_ingest(
    engine: AsyncEngine,
    username: str,
    thread_id: Optional[str],
    source: str,
    kind: str,
    fingerprint: Optional[str],
) -> None:
    async with engine.begin() as conn:
        await conn.execute(
            insert(doc_ingests).values(
                id=uuid.uuid4(),
                username=username,
                thread_id=thread_id,
                source=source,
                kind=kind,
                fingerprint=fingerprint or "",
            )
        )


async def log_query_preference(
    engine: AsyncEngine,
    username: str,
    thread_id: Optional[str],
    question: str,
    answer: str,
    context: str,
    liked: bool,
    source_message_id: Optional[str],
) -> None:
    table = liked_queries if liked else disliked_queries
    async with engine.begin() as conn:
        await conn.execute(
            insert(table).values(
                id=uuid.uuid4(),
                username=username,
                thread_id=thread_id,
                question=question,
                answer=answer,
                context=context,
                source_message_id=source_message_id or "",
            )
        )


async def log_bad_spl_generation(
    engine: AsyncEngine,
    username: str,
    thread_id: Optional[str],
    user_question: str,
    generated_spl: str,
    validation_errors: List[str],
    llm_context: str,
) -> None:
    """Logs a known-bad SPL generation for future fine-tuning."""
    async with engine.begin() as conn:
        await conn.execute(
            insert(bad_spl_generations).values(
                id=uuid.uuid4(),
                username=username,
                thread_id=thread_id,
                user_question=user_question,
                generated_spl=generated_spl,
                validation_errors=json.dumps(validation_errors),
                llm_context=llm_context,
            )
        )


async def log_followup_sequence(
    engine: AsyncEngine,
    username: str,
    thread_id: Optional[str],
    parent_question: str,
    followup_question: str,
) -> None:
    """Logs that a user chose a specific follow-up, incrementing a counter."""
    import hashlib

    parent_hash = hashlib.sha256(parent_question.encode("utf-8", "ignore")).hexdigest()

    async with engine.begin() as conn:
        stmt = pg_insert(followup_sequences).values(
            id=uuid.uuid4(),
            parent_question_hash=parent_hash,
            followup_question=followup_question,
            parent_question=parent_question,
            username=username,
            thread_id=thread_id,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[
                followup_sequences.c.parent_question_hash,
                followup_sequences.c.followup_question,
            ],
            set_={
                "count": followup_sequences.c.count + 1,
                "updated_at": func.now(),
                "username": username, # Also update username to last user
            },
        )
        await conn.execute(stmt)


async def _fetch_lines(engine: AsyncEngine, stmt) -> List[str]:
    async with engine.connect() as conn:
        result = await conn.execute(stmt)
        rows: Sequence = result.fetchall()
    lines: List[str] = []
    for row in rows:
        created = getattr(row, "created_at", None)
        timestamp = created.isoformat() if created else ""
        if hasattr(row, "question") and hasattr(row, "answer"):
            q = (row.question or "").strip()
            a = (row.answer or "").strip()
            q_short = (q[:180] + "...") if len(q) > 180 else q
            a_short = (a[:180] + "...") if len(a) > 180 else a
            lines.append(f"{timestamp} | Q: {q_short} | A: {a_short}")
        elif hasattr(row, "body"):
            body = (row.body or "").strip()
            lines.append(f"{timestamp} | {body}")
    return lines


async def get_recent_interactions(engine: AsyncEngine, username: str, limit: int = 5) -> List[str]:
    stmt = (
        select(
            interactions.c.question,
            interactions.c.answer,
            interactions.c.created_at,
        )
        .where(interactions.c.username == username)
        .order_by(interactions.c.created_at.desc())
        .limit(limit)
    )
    return await _fetch_lines(engine, stmt)


async def get_thread_tail(engine: AsyncEngine, thread_id: str, limit: int = 3) -> List[str]:
    if not thread_id:
        return []
    stmt = (
        select(
            interactions.c.question,
            interactions.c.answer,
            interactions.c.created_at,
        )
        .where(interactions.c.thread_id == thread_id)
        .order_by(interactions.c.created_at.desc())
        .limit(limit)
    )
    return await _fetch_lines(engine, stmt)


async def get_recent_global_notes(engine: AsyncEngine, limit: int = 3) -> List[str]:
    stmt = (
        select(
            notes.c.body,
            notes.c.created_at,
        )
        .order_by(notes.c.created_at.desc())
        .limit(limit)
    )
    return await _fetch_lines(engine, stmt)


async def get_recent_global_notes_raw(engine: AsyncEngine, limit: int = 3):
    stmt = (
        select(
            notes.c.body,
            notes.c.created_at,
            notes.c.title,
            notes.c.created_by,
            notes.c.thread_id,
        )
        .order_by(notes.c.created_at.desc())
        .limit(limit)
    )
    async with engine.connect() as conn:
        result = await conn.execute(stmt)
        rows: Sequence = result.fetchall()
    payload = []
    for row in rows:
        payload.append(
            {
                "body": getattr(row, "body", "") or "",
                "created_at": getattr(row, "created_at", ""),
                "title": getattr(row, "title", "") or "",
                "created_by": getattr(row, "created_by", "") or "",
                "thread_id": getattr(row, "thread_id", "") or "",
            }
        )
    return payload


async def get_recent_query_preferences(
    engine: AsyncEngine, liked: bool, limit: int = 5
) -> List[str]:
    table = liked_queries if liked else disliked_queries
    stmt = (
        select(
            table.c.question,
            table.c.answer,
            table.c.created_at,
        )
        .order_by(table.c.created_at.desc())
        .limit(limit)
    )
    return await _fetch_lines(engine, stmt)


async def get_query_preference_stats(
    engine: AsyncEngine, liked: bool, limit: int = 5
) -> List[str]:
    """
    Aggregate liked/disliked queries with counts and distinct users.
    Groups by question + source_message_id to keep answers aligned.
    """
    table = liked_queries if liked else disliked_queries
    stmt = (
        select(
            table.c.question,
            table.c.source_message_id,
            func.count().label("cnt"),
            func.array_agg(func.distinct(table.c.username)).label("users"),
            func.max(table.c.created_at).label("last_ts"),
        )
        .group_by(table.c.question, table.c.source_message_id)
        .order_by(func.count().desc(), func.max(table.c.created_at).desc())
        .limit(limit)
    )
    async with engine.connect() as conn:
        result = await conn.execute(stmt)
        rows: Sequence = result.fetchall()

    lines: List[str] = []
    for row in rows:
        q = (row.question or "").strip()
        q_short = (q[:140] + "...") if len(q) > 140 else q
        users = [u for u in (row.users or []) if u]
        user_str = ", ".join(users)
        lines.append(f"{row.cnt} vote(s) | users: {user_str or 'n/a'} | Q: {q_short}")
    return lines


async def save_mcp_token(
    engine: AsyncEngine,
    user_id: str,
    server_name: str,
    access_token: str,
    auth_scheme: str = "bearer",
    refresh_token: Optional[str] = None,
    expires_at: Optional[datetime] = None,
) -> None:
    """Upsert an MCP token for a user/server pair."""
    async with engine.begin() as conn:
        stmt = pg_insert(mcp_tokens).values(
            id=uuid.uuid4(),
            user_id=user_id,
            server_name=server_name,
            auth_scheme=auth_scheme,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[mcp_tokens.c.user_id, mcp_tokens.c.server_name],
            set_={
                "access_token": access_token,
                "auth_scheme": auth_scheme,
                "refresh_token": refresh_token,
                "expires_at": expires_at,
                "updated_at": func.now(),
            },
        )
        await conn.execute(stmt)


async def load_mcp_token(
    engine: AsyncEngine, user_id: str, server_name: str
) -> Optional[Dict[str, Any]]:
    stmt = (
        select(
            mcp_tokens.c.user_id,
            mcp_tokens.c.server_name,
            mcp_tokens.c.auth_scheme,
            mcp_tokens.c.access_token,
            mcp_tokens.c.refresh_token,
            mcp_tokens.c.expires_at,
            mcp_tokens.c.created_at,
            mcp_tokens.c.updated_at,
        )
        .where(
            mcp_tokens.c.user_id == user_id,
            mcp_tokens.c.server_name == server_name,
        )
        .limit(1)
    )
    async with engine.connect() as conn:
        result = await conn.execute(stmt)
        row = result.mappings().first()
    return dict(row) if row else None


async def delete_mcp_token(engine: AsyncEngine, user_id: str, server_name: str) -> None:
    stmt = delete(mcp_tokens).where(
        mcp_tokens.c.user_id == user_id, mcp_tokens.c.server_name == server_name
    )
    async with engine.begin() as conn:
        await conn.execute(stmt)


async def list_mcp_tokens(
    engine: AsyncEngine, user_id: str
) -> List[Dict[str, Any]]:
    stmt = (
        select(
            mcp_tokens.c.server_name,
            mcp_tokens.c.auth_scheme,
            mcp_tokens.c.created_at,
            mcp_tokens.c.updated_at,
            mcp_tokens.c.expires_at,
        )
        .where(mcp_tokens.c.user_id == user_id)
        .order_by(mcp_tokens.c.updated_at.desc())
    )
    async with engine.connect() as conn:
        result = await conn.execute(stmt)
        rows = result.mappings().all()
    return [dict(r) for r in rows]


def get_chunks_by_fingerprint(store: Chroma, fingerprint: str, limit: int = 4) -> List[str]:
    if not fingerprint:
        return []
    return _get_by_filter(store, {"fingerprint": fingerprint}, limit=limit, label=None)


def _maybe_write_feedback_html(
    message_id: str,
    value: int,
    comment: str,
    username: str,
    thread_id: Optional[str],
    title: str,
    question: str,
    answer: str,
    context: str,
) -> None:
    """
    Persist feedback as an HTML file under FEEDBACK_PUBLIC_DIR (served by static-docs).
    """
    base_dir = Path(os.getenv("FEEDBACK_PUBLIC_DIR", "/app/public/feedback"))
    try:
        base_dir.mkdir(parents=True, exist_ok=True)
    except Exception as _exc:  # broad catch — resilience at boundary  # narrowed
        return

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_id = message_id or str(uuid.uuid4())
    fname = f"feedback_{ts}_{safe_id}.html"
    path = base_dir / fname

    def esc(val: str) -> str:
        return html.escape(val or "")

    rows = [
        ("Submitted at (UTC)", ts),
        ("User", username or "anonymous"),
        ("Thread ID", thread_id or ""),
        ("Message ID", message_id or ""),
        ("Feedback value", str(value)),
        ("Title", title or ""),
        ("Question", question or ""),
        ("Answer", answer or ""),
        ("Context", context or ""),
        ("Comment", comment or ""),
    ]

    html_rows = "\n".join(
        f"<tr><th style='text-align:left; padding:4px 8px;'>{esc(k)}</th>"
        f"<td style='padding:4px 8px; white-space:pre-wrap'>{esc(v)}</td></tr>"
        for k, v in rows
    )

    doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Feedback {esc(safe_id)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; font-size: 14px; margin: 16px; }}
    table {{ border-collapse: collapse; width: 100%; max-width: 900px; }}
    th {{ background: #f5f5f5; border: 1px solid #ddd; }}
    td {{ border: 1px solid #ddd; }}
  </style>
 </head>
 <body>
   <h2>User submitted feedback</h2>
   <table>
     {html_rows}
   </table>
 </body>
</html>
"""
    try:
        path.write_text(doc, encoding="utf-8")
        return fname
    except Exception as _exc:  # broad catch — resilience against all failures
        return None


async def get_top_followups(
    engine: AsyncEngine, parent_question: str, limit: int = 3
) -> List[str]:
    """Get the most frequently chosen follow-up questions for a given parent question."""
    import hashlib

    parent_hash = hashlib.sha256(parent_question.encode("utf-8", "ignore")).hexdigest()

    stmt = (
        select(followup_sequences.c.followup_question)
        .where(followup_sequences.c.parent_question_hash == parent_hash)
        .order_by(followup_sequences.c.count.desc(), followup_sequences.c.updated_at.desc())
        .limit(limit)
    )
    async with engine.connect() as conn:
        result = await conn.execute(stmt)
        rows: Sequence = result.fetchall()

    return [row.followup_question for row in rows]
