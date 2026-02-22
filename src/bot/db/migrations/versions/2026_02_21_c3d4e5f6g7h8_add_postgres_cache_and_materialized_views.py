"""add_postgres_cache_and_materialized_views

Add PostgreSQL-native caching infrastructure:
1. UNLOGGED cache table for key-value caching with TTL
2. Materialized views for expensive aggregation queries
3. Auto-cleanup function for expired cache entries

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-02-21
"""

from typing import Sequence, Union

from alembic import op

revision: str = 'c3d4e5f6g7h8'
down_revision: Union[str, None] = 'b2c3d4e5f6g7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. UNLOGGED cache table (fast KV store with TTL) ──
    # UNLOGGED = not written to WAL = ~10x faster writes, but lost on crash.
    # Perfect for cache — data is regenerated on miss anyway.
    op.execute("""
        CREATE UNLOGGED TABLE IF NOT EXISTS cache (
            key         TEXT PRIMARY KEY,
            value       JSONB NOT NULL,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
            expires_at  TIMESTAMPTZ NOT NULL
        )
    """)

    # Index for efficient cleanup of expired entries
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_cache_expires_at
        ON cache (expires_at)
    """)

    # ── 2. Auto-cleanup function ──
    # Called periodically to remove expired entries
    op.execute("""
        CREATE OR REPLACE FUNCTION cache_cleanup()
        RETURNS INTEGER
        LANGUAGE sql
        AS $$
            WITH deleted AS (
                DELETE FROM cache
                WHERE expires_at < now()
                RETURNING 1
            )
            SELECT count(*)::integer FROM deleted;
        $$
    """)

    # ── 3. Helper functions for cache get/set ──
    op.execute("""
        CREATE OR REPLACE FUNCTION cache_get(p_key TEXT)
        RETURNS JSONB
        LANGUAGE sql
        AS $$
            SELECT value FROM cache
            WHERE key = p_key AND expires_at > now()
            LIMIT 1;
        $$
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION cache_set(
            p_key TEXT,
            p_value JSONB,
            p_ttl_seconds INTEGER DEFAULT 300
        )
        RETURNS VOID
        LANGUAGE sql
        AS $$
            INSERT INTO cache (key, value, expires_at)
            VALUES (p_key, p_value, now() + (p_ttl_seconds || ' seconds')::interval)
            ON CONFLICT (key)
            DO UPDATE SET
                value = EXCLUDED.value,
                created_at = now(),
                expires_at = EXCLUDED.expires_at;
        $$
    """)

    op.execute("""
        CREATE OR REPLACE FUNCTION cache_invalidate(p_prefix TEXT)
        RETURNS INTEGER
        LANGUAGE sql
        AS $$
            WITH deleted AS (
                DELETE FROM cache
                WHERE key LIKE p_prefix || '%'
                RETURNING 1
            )
            SELECT count(*)::integer FROM deleted;
        $$
    """)

    # ── 4. Materialized view: budget summary per project+category ──
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_budget_summary AS
        SELECT
            bi.project_id,
            bi.category,
            COALESCE(SUM(bi.work_cost), 0)     AS total_work,
            COALESCE(SUM(bi.material_cost), 0)  AS total_materials,
            COALESCE(SUM(bi.prepayment), 0)     AS total_prepayments,
            COALESCE(SUM(bi.work_cost + bi.material_cost + bi.prepayment), 0) AS total_spent,
            COUNT(*)                            AS item_count,
            COUNT(*) FILTER (WHERE bi.is_confirmed) AS confirmed_count
        FROM budget_items bi
        GROUP BY bi.project_id, bi.category
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_mv_budget_summary_pk
        ON mv_budget_summary (project_id, category)
    """)

    # ── 5. Materialized view: stage progress per project ──
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_stage_progress AS
        SELECT
            s.project_id,
            COUNT(*)                                    AS total_stages,
            COUNT(*) FILTER (WHERE s.status = 'planned')     AS planned,
            COUNT(*) FILTER (WHERE s.status = 'in_progress') AS in_progress,
            COUNT(*) FILTER (WHERE s.status = 'completed')   AS completed,
            COUNT(*) FILTER (WHERE s.status = 'delayed')     AS delayed,
            MIN(s.start_date)                           AS earliest_start,
            MAX(s.end_date)                             AS latest_end
        FROM stages s
        GROUP BY s.project_id
    """)

    op.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS ix_mv_stage_progress_pk
        ON mv_stage_progress (project_id)
    """)

    # ── 6. Function to refresh all materialized views ──
    op.execute("""
        CREATE OR REPLACE FUNCTION refresh_materialized_views()
        RETURNS VOID
        LANGUAGE plpgsql
        AS $$
        BEGIN
            REFRESH MATERIALIZED VIEW CONCURRENTLY mv_budget_summary;
            REFRESH MATERIALIZED VIEW CONCURRENTLY mv_stage_progress;
        END;
        $$
    """)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS refresh_materialized_views()")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_stage_progress")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS mv_budget_summary")
    op.execute("DROP FUNCTION IF EXISTS cache_invalidate(TEXT)")
    op.execute("DROP FUNCTION IF EXISTS cache_set(TEXT, JSONB, INTEGER)")
    op.execute("DROP FUNCTION IF EXISTS cache_get(TEXT)")
    op.execute("DROP FUNCTION IF EXISTS cache_cleanup()")
    op.execute("DROP TABLE IF EXISTS cache")
