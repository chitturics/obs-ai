"""
Episodic Memory — Structured storage of past interaction episodes.

Each episode captures: what the user asked, what the agent did,
what strategy was used, and whether it succeeded. This enables:
- Avoiding repeated failures (same query pattern, same failure)
- Reusing successful strategies for similar queries
- Building semantic facts from episode patterns over time
"""
import hashlib
import logging
import uuid
from typing import Any, Dict, List

from sqlalchemy import (
    Column, DateTime, Float, Integer, MetaData, String, Table, Text, func,
    insert, select,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.ext.asyncio import AsyncEngine

logger = logging.getLogger(__name__)

metadata = MetaData()

episodes_table = Table(
    "assistant_episodes",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("username", String, nullable=False),
    Column("query_hash", String(64), nullable=False),
    Column("query", Text, nullable=False),
    Column("intent", String(50)),
    Column("profile", String(50)),
    Column("strategy_used", String(100)),
    Column("collections_searched", Text),  # JSON list
    Column("chunks_found", Integer, default=0),
    Column("response_length", Integer, default=0),
    Column("confidence", Float, default=0.0),
    Column("success", Integer, default=-1),  # -1=unknown, 0=negative, 1=positive
    Column("failure_reason", Text),
    Column("duration_ms", Integer, default=0),
    Column("metadata", JSONB),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

semantic_facts_table = Table(
    "assistant_semantic_facts",
    metadata,
    Column("id", UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
    Column("pattern_hash", String(64), unique=True),
    Column("rule", Text, nullable=False),
    Column("category", String(50)),  # retrieval, profile, response_style, tool_use
    Column("confidence", Float, default=0.5),
    Column("times_applied", Integer, default=0),
    Column("times_succeeded", Integer, default=0),
    Column("source_episodes", Integer, default=0),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), server_default=func.now()),
)


def _query_hash(query: str) -> str:
    """Create a hash for query similarity grouping."""
    normalized = query.lower().strip()
    return hashlib.sha256(normalized.encode()).hexdigest()[:32]


async def ensure_episode_tables(engine: AsyncEngine):
    """Create episode tables if they don't exist."""
    try:
        async with engine.begin() as conn:
            await conn.run_sync(metadata.create_all)
        logger.info("[EPISODIC] Episode tables ensured")
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[EPISODIC] Could not create tables: {exc}")


async def store_episode(
    engine: AsyncEngine,
    username: str,
    query: str,
    intent: str = "",
    profile: str = "",
    strategy_used: str = "",
    collections_searched: List[str] = None,
    chunks_found: int = 0,
    response_length: int = 0,
    confidence: float = 0.0,
    success: int = -1,
    failure_reason: str = "",
    duration_ms: int = 0,
    extra_metadata: Dict = None,
):
    """Store an interaction episode for later analysis."""
    try:
        import json
        async with engine.begin() as conn:
            await conn.execute(
                insert(episodes_table).values(
                    id=uuid.uuid4(),
                    username=username,
                    query_hash=_query_hash(query),
                    query=query,
                    intent=intent,
                    profile=profile,
                    strategy_used=strategy_used,
                    collections_searched=json.dumps(collections_searched or []),
                    chunks_found=chunks_found,
                    response_length=response_length,
                    confidence=confidence,
                    success=success,
                    failure_reason=failure_reason,
                    duration_ms=duration_ms,
                    metadata=extra_metadata or {},
                )
            )
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        logger.warning(f"[EPISODIC] Failed to store episode: {exc}")


async def find_similar_episodes(
    engine: AsyncEngine,
    query: str,
    username: str = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """Find past episodes with the same query hash (exact or near-match)."""
    try:
        qh = _query_hash(query)
        stmt = (
            select(episodes_table)
            .where(episodes_table.c.query_hash == qh)
            .order_by(episodes_table.c.created_at.desc())
            .limit(limit)
        )
        if username:
            stmt = stmt.where(episodes_table.c.username == username)

        async with engine.begin() as conn:
            result = await conn.execute(stmt)
            rows = result.mappings().all()
            return [dict(r) for r in rows]
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[EPISODIC] Failed to find episodes: {exc}")
        return []


async def update_episode_outcome(
    engine: AsyncEngine,
    query: str,
    username: str,
    success: int,
    failure_reason: str = "",
):
    """Update the most recent episode for this query with feedback outcome."""
    try:
        from sqlalchemy import update
        qh = _query_hash(query)
        stmt = (
            update(episodes_table)
            .where(episodes_table.c.query_hash == qh)
            .where(episodes_table.c.username == username)
            .where(episodes_table.c.success == -1)
            .values(success=success, failure_reason=failure_reason)
        )
        async with engine.begin() as conn:
            await conn.execute(stmt)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[EPISODIC] Failed to update episode: {exc}")


async def get_episode_stats(
    engine: AsyncEngine,
    username: str = None,
) -> Dict[str, Any]:
    """Get aggregated episode statistics."""
    try:
        from sqlalchemy import func as sqlfunc
        stmt = select(
            sqlfunc.count().label("total"),
            sqlfunc.sum(
                sqlfunc.cast(episodes_table.c.success == 1, Integer)
            ).label("successes"),
            sqlfunc.sum(
                sqlfunc.cast(episodes_table.c.success == 0, Integer)
            ).label("failures"),
            sqlfunc.avg(episodes_table.c.confidence).label("avg_confidence"),
            sqlfunc.avg(episodes_table.c.duration_ms).label("avg_duration"),
        )
        if username:
            stmt = stmt.where(episodes_table.c.username == username)

        async with engine.begin() as conn:
            result = await conn.execute(stmt)
            row = result.mappings().first()
            return dict(row) if row else {}
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[EPISODIC] Failed to get stats: {exc}")
        return {}


# --- Semantic Facts ---

async def store_semantic_fact(
    engine: AsyncEngine,
    rule: str,
    category: str = "general",
    confidence: float = 0.5,
    source_episodes: int = 1,
):
    """Store or update a learned semantic fact."""
    try:
        pattern_hash = hashlib.sha256(rule.lower().encode()).hexdigest()[:32]

        from sqlalchemy.dialects.postgresql import insert as pg_insert
        stmt = pg_insert(semantic_facts_table).values(
            id=uuid.uuid4(),
            pattern_hash=pattern_hash,
            rule=rule,
            category=category,
            confidence=confidence,
            source_episodes=source_episodes,
        ).on_conflict_do_update(
            index_elements=["pattern_hash"],
            set_={
                "confidence": func.least(semantic_facts_table.c.confidence + 0.05, 1.0),
                "source_episodes": semantic_facts_table.c.source_episodes + 1,
                "updated_at": func.now(),
            },
        )
        async with engine.begin() as conn:
            await conn.execute(stmt)
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[SEMANTIC] Failed to store fact: {exc}")


async def get_relevant_facts(
    engine: AsyncEngine,
    category: str = None,
    min_confidence: float = 0.3,
    limit: int = 10,
) -> List[Dict[str, Any]]:
    """Retrieve high-confidence semantic facts."""
    try:
        stmt = (
            select(semantic_facts_table)
            .where(semantic_facts_table.c.confidence >= min_confidence)
            .order_by(semantic_facts_table.c.confidence.desc())
            .limit(limit)
        )
        if category:
            stmt = stmt.where(semantic_facts_table.c.category == category)

        async with engine.begin() as conn:
            result = await conn.execute(stmt)
            rows = result.mappings().all()
            return [dict(r) for r in rows]
    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[SEMANTIC] Failed to get facts: {exc}")
        return []


async def consolidate_episodes_to_facts(engine: AsyncEngine, min_episodes: int = 3):
    """
    Analyze episode patterns and discover semantic facts.

    Runs periodically (e.g., daily) to turn episode clusters into rules.
    For example: "queries about transforms.conf succeed 90% of the time
    with config_helper profile" → semantic fact.
    """
    try:
        # Find intent+profile combinations with enough episodes
        from sqlalchemy import func as sqlfunc
        stmt = (
            select(
                episodes_table.c.intent,
                episodes_table.c.profile,
                sqlfunc.count().label("count"),
                sqlfunc.avg(
                    sqlfunc.cast(episodes_table.c.success == 1, Integer)
                ).label("success_rate"),
                sqlfunc.avg(episodes_table.c.confidence).label("avg_confidence"),
            )
            .where(episodes_table.c.success >= 0)
            .group_by(episodes_table.c.intent, episodes_table.c.profile)
            .having(sqlfunc.count() >= min_episodes)
        )

        async with engine.begin() as conn:
            result = await conn.execute(stmt)
            rows = result.mappings().all()

        facts_created = 0
        for row in rows:
            intent = row["intent"] or "unknown"
            profile = row["profile"] or "general"
            success_rate = float(row["success_rate"] or 0)
            count = int(row["count"])

            if success_rate > 0.7:
                rule = f"For '{intent}' queries, profile '{profile}' succeeds {success_rate:.0%} of the time ({count} episodes)"
                await store_semantic_fact(engine, rule, category="profile", confidence=success_rate, source_episodes=count)
                facts_created += 1
            elif success_rate < 0.3 and count >= 5:
                rule = f"Avoid profile '{profile}' for '{intent}' queries — only {success_rate:.0%} success ({count} episodes)"
                await store_semantic_fact(engine, rule, category="profile", confidence=1 - success_rate, source_episodes=count)
                facts_created += 1

        logger.info(f"[CONSOLIDATE] Created {facts_created} semantic facts from {len(rows)} episode patterns")
        return facts_created

    except (ImportError, OSError, ValueError, KeyError, TypeError, AttributeError, RuntimeError) as exc:
        logger.warning(f"[CONSOLIDATE] Failed: {exc}")
        return 0
