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
    # Clear existing embeddings first (avoids cast issues + incompatible dims)
    op.execute("DELETE FROM embeddings")

    # Drop any existing vector indexes
    op.execute("DROP INDEX IF EXISTS ix_embeddings_hnsw")

    # Change column type to untyped vector (accepts any dimension)
    # Safe because we just cleared all rows
    op.execute("ALTER TABLE embeddings ALTER COLUMN embedding TYPE vector USING NULL")


def downgrade() -> None:
    op.execute("DELETE FROM embeddings")
    op.execute("DROP INDEX IF EXISTS ix_embeddings_hnsw")
    op.execute("ALTER TABLE embeddings ALTER COLUMN embedding TYPE vector(1536) USING NULL")
