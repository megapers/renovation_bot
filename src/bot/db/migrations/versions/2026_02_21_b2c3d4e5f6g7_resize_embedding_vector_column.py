"""resize_embedding_vector_column

Remove fixed Vector(1536) dimension constraint to support any embedding model.
BGE-M3 uses 1024 dims, text-embedding-3-large uses 3072, etc.

When switching embedding models, existing embeddings become incompatible.
This migration clears them so /backfill can regenerate with the new model.

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-02-21
"""

from typing import Sequence, Union

from alembic import op

revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop the HNSW index (it's dimension-specific)
    op.execute("DROP INDEX IF EXISTS ix_embeddings_hnsw")

    # Change column type from vector(1536) to vector (no dimension constraint)
    op.execute("ALTER TABLE embeddings ALTER COLUMN embedding TYPE vector USING embedding::vector")

    # Clear existing embeddings (incompatible dimensions when switching models)
    # Users should run /backfill after switching embedding models
    op.execute("DELETE FROM embeddings")

    # Recreate HNSW index without dimension constraint
    # Note: pgvector HNSW requires all vectors to have the same dimensions
    # at query time, which they will since they come from the same model
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_embeddings_hnsw
        ON embeddings USING hnsw (embedding vector_cosine_ops)
    """)


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_embeddings_hnsw")
    op.execute("DELETE FROM embeddings")
    op.execute("ALTER TABLE embeddings ALTER COLUMN embedding TYPE vector(1536) USING embedding::vector(1536)")
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_embeddings_hnsw
        ON embeddings USING hnsw (embedding vector_cosine_ops)
    """)
