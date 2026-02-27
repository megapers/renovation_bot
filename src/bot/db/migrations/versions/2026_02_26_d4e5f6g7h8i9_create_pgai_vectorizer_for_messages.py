"""create_pgai_vectorizer_for_messages

Set up pgai Vectorizer to automatically create and update embeddings
when messages are inserted/updated/deleted. Replaces manual Python-side
embedding calls.

The vectorizer worker (external Docker container) polls for changes
and creates embeddings using Ollama BGE-M3.

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-02-26
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text as sa_text

revision: str = 'd4e5f6g7h8i9'
down_revision: Union[str, None] = 'c3d4e5f6g7h8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # Ensure pgai extension is available
    conn.execute(sa_text("CREATE EXTENSION IF NOT EXISTS ai CASCADE"))

    # Create a vectorizer on the messages table.
    # The vectorizer worker automatically:
    # 1. Watches for INSERT/UPDATE/DELETE on messages
    # 2. Chunks the transcribed_text
    # 3. Calls Ollama BGE-M3 to generate embeddings
    # 4. Stores results in messages_transcribed_text_embeddings table
    #
    # The embedding model and host are configured via environment
    # variables in the vectorizer-worker container (OLLAMA_HOST).
    conn.execute(sa_text("""
        SELECT ai.create_vectorizer(
            'public.messages'::regclass,
            loading => ai.loading_column('transcribed_text'),
            embedding => ai.embedding_ollama('bge-m3', 1024),
            destination => ai.destination_table('messages_embeddings_auto'),
            chunking => ai.chunking_recursive_character_text_splitter(
                'transcribed_text',
                chunk_size => 512,
                chunk_overlap => 50
            )
        )
    """))


def downgrade() -> None:
    conn = op.get_bind()
    # Drop the vectorizer (this removes the auto-sync triggers)
    # First find and drop the vectorizer
    conn.execute(sa_text("""
        DO $do$
        DECLARE
            v_id INT;
        BEGIN
            SELECT id INTO v_id FROM ai.vectorizer WHERE source_table = 'messages' LIMIT 1;
            IF v_id IS NOT NULL THEN
                PERFORM ai.drop_vectorizer(v_id);
            END IF;
        END $do$
    """))
    conn.execute(sa_text("DROP TABLE IF EXISTS messages_embeddings_auto"))
