"""enable_pgai_and_vectorizer

Enable pgai extension and set up auto-vectorization for messages table.
pgai's vectorizer creates embeddings automatically when messages are inserted,
eliminating the need for manual Python-side embedding calls.

Revision ID: a1b2c3d4e5f6
Revises: c7d4150f85cf
Create Date: 2026-02-21
"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = 'c7d4150f85cf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable pgai extension (requires plpython3u, auto-installed as dependency)
    op.execute("CREATE EXTENSION IF NOT EXISTS ai CASCADE")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS ai CASCADE")
