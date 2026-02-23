"""
PostgreSQL-native cache service.

Uses an UNLOGGED table for fast key-value caching with TTL.
UNLOGGED tables skip WAL writes (~10x faster), and data loss
on crash is acceptable since it's regenerated on cache miss.

Also provides access to materialized views for expensive
aggregation queries (budget summaries, stage progress).

Usage:
    from bot.services.pg_cache import pg_cache_get, pg_cache_set

    # Simple get/set
    data = await pg_cache_get(session, "budget:5")
    if data is None:
        data = await compute_budget(project_id=5)
        await pg_cache_set(session, "budget:5", data, ttl=300)

    # Invalidate on data change
    await pg_cache_invalidate(session, "budget:5")

    # Materialized views
    summary = await get_cached_budget_summary(session, project_id=5)
    progress = await get_cached_stage_progress(session, project_id=5)
"""

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


# ── Key-Value Cache (UNLOGGED table) ─────────────────────────


async def pg_cache_get(
    session: AsyncSession,
    key: str,
) -> Any | None:
    """
    Get a cached value by key. Returns None on miss or expiry.

    The value is stored as JSONB and deserialized automatically.
    """
    result = await session.execute(
        text("SELECT cache_get(:key) AS value"),
        {"key": key},
    )
    row = result.fetchone()
    if row and row.value is not None:
        logger.debug("Cache HIT: %s", key)
        return row.value
    logger.debug("Cache MISS: %s", key)
    return None


async def pg_cache_set(
    session: AsyncSession,
    key: str,
    value: Any,
    ttl: int = 300,
) -> None:
    """
    Set a cache entry with TTL (in seconds).

    Args:
        key: cache key (e.g., "budget:5", "user:610379797")
        value: any JSON-serializable value
        ttl: time-to-live in seconds (default: 5 minutes)
    """
    # Convert Python objects to JSON-compatible format
    if not isinstance(value, (dict, list, str, int, float, bool)):
        value = json.loads(json.dumps(value, default=str, ensure_ascii=False))

    await session.execute(
        text("SELECT cache_set(:key, CAST(:value AS jsonb), :ttl)"),
        {"key": key, "value": json.dumps(value, ensure_ascii=False), "ttl": ttl},
    )
    logger.debug("Cache SET: %s (ttl=%ds)", key, ttl)


async def pg_cache_invalidate(
    session: AsyncSession,
    prefix: str,
) -> int:
    """
    Invalidate all cache entries matching a key prefix.

    Examples:
        pg_cache_invalidate(session, "budget:5")    — one project's budget
        pg_cache_invalidate(session, "budget:")      — all budget caches
        pg_cache_invalidate(session, "user:610")     — one user
    """
    result = await session.execute(
        text("SELECT cache_invalidate(:prefix) AS count"),
        {"prefix": prefix},
    )
    row = result.fetchone()
    count = row.count if row else 0
    if count:
        logger.debug("Cache INVALIDATE: %s (%d entries)", prefix, count)
    return count


async def pg_cache_cleanup(session: AsyncSession) -> int:
    """Remove all expired cache entries. Returns count of removed entries."""
    result = await session.execute(text("SELECT cache_cleanup() AS count"))
    row = result.fetchone()
    count = row.count if row else 0
    if count:
        logger.info("Cache cleanup: removed %d expired entries", count)
    return count


# ── Convenience: cached get-or-compute ───────────────────────


async def cached(
    session: AsyncSession,
    key: str,
    compute_fn,
    ttl: int = 300,
) -> Any:
    """
    Get from cache or compute and store.

    Usage:
        result = await cached(
            session, f"budget:{project_id}",
            lambda: get_project_budget_summary(session, project_id),
            ttl=300,
        )
    """
    value = await pg_cache_get(session, key)
    if value is not None:
        return value

    value = await compute_fn()
    await pg_cache_set(session, key, value, ttl=ttl)
    return value


# ── Materialized Views ───────────────────────────────────────


async def get_cached_budget_summary(
    session: AsyncSession,
    project_id: int,
) -> list[dict[str, Any]]:
    """
    Get budget summary per category from the materialized view.

    Much faster than SUM/GROUP BY on every request.
    Data is refreshed by calling refresh_materialized_views().
    """
    result = await session.execute(
        text("""
            SELECT category, total_work, total_materials,
                   total_prepayments, total_spent,
                   item_count, confirmed_count
            FROM mv_budget_summary
            WHERE project_id = :project_id
            ORDER BY category
        """),
        {"project_id": project_id},
    )
    return [
        {
            "category": row.category,
            "total_work": float(row.total_work),
            "total_materials": float(row.total_materials),
            "total_prepayments": float(row.total_prepayments),
            "total_spent": float(row.total_spent),
            "item_count": row.item_count,
            "confirmed_count": row.confirmed_count,
        }
        for row in result.fetchall()
    ]


async def get_cached_stage_progress(
    session: AsyncSession,
    project_id: int,
) -> dict[str, Any] | None:
    """
    Get stage progress from the materialized view.

    Returns counts of planned/in_progress/completed/delayed stages.
    """
    result = await session.execute(
        text("""
            SELECT total_stages, planned, in_progress, completed, delayed,
                   earliest_start, latest_end
            FROM mv_stage_progress
            WHERE project_id = :project_id
        """),
        {"project_id": project_id},
    )
    row = result.fetchone()
    if not row:
        return None

    return {
        "total_stages": row.total_stages,
        "planned": row.planned,
        "in_progress": row.in_progress,
        "completed": row.completed,
        "delayed": row.delayed,
        "earliest_start": str(row.earliest_start) if row.earliest_start else None,
        "latest_end": str(row.latest_end) if row.latest_end else None,
    }


async def refresh_views(session: AsyncSession) -> None:
    """
    Refresh all materialized views.

    Call this after data changes (new expense, stage status update, etc.)
    or on a periodic schedule (e.g., every 60 seconds via the scheduler).
    """
    await session.execute(text("SELECT refresh_materialized_views()"))
    logger.debug("Materialized views refreshed")
