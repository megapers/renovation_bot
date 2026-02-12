"""
Embedding service — generate, store, and search vector embeddings.

Uses pgvector HNSW index for fast approximate nearest-neighbor search
over text-embedding-3-small (1536-dim) embeddings.
"""

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bot.db.models import Embedding
from bot.services.ai_client import generate_embedding, generate_embeddings_batch, is_ai_configured

logger = logging.getLogger(__name__)


async def embed_and_store(
    session: AsyncSession,
    *,
    project_id: int,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> Embedding | None:
    """
    Generate an embedding for text and store it in the database.

    Args:
        session: async DB session
        project_id: owning project
        content: text to embed
        metadata: optional JSON-serializable metadata (message_id, source, etc.)

    Returns:
        The created Embedding row, or None if AI is not configured.
    """
    if not is_ai_configured():
        logger.warning("AI not configured — skipping embedding for project_id=%d", project_id)
        return None

    if not content or not content.strip():
        logger.debug("Empty content — skipping embedding")
        return None

    vector = await generate_embedding(content)

    emb = Embedding(
        project_id=project_id,
        content=content,
        embedding=vector,
        metadata_=json.dumps(metadata, ensure_ascii=False) if metadata else None,
    )
    session.add(emb)
    await session.flush()

    logger.debug("Stored embedding id=%d for project_id=%d (%d chars)", emb.id, project_id, len(content))
    return emb


async def embed_and_store_batch(
    session: AsyncSession,
    *,
    project_id: int,
    items: list[dict[str, Any]],
) -> list[Embedding]:
    """
    Batch-embed and store multiple texts.

    Each item: {"content": str, "metadata": dict | None}

    Returns:
        List of created Embedding rows.
    """
    if not is_ai_configured():
        logger.warning("AI not configured — skipping batch embedding")
        return []

    texts = [item["content"] for item in items if item.get("content", "").strip()]
    if not texts:
        return []

    vectors = await generate_embeddings_batch(texts)

    embeddings: list[Embedding] = []
    for item_data, vector in zip(items, vectors):
        content = item_data["content"]
        metadata = item_data.get("metadata")
        emb = Embedding(
            project_id=project_id,
            content=content,
            embedding=vector,
            metadata_=json.dumps(metadata, ensure_ascii=False) if metadata else None,
        )
        session.add(emb)
        embeddings.append(emb)

    await session.flush()
    logger.info("Stored %d embeddings for project_id=%d", len(embeddings), project_id)
    return embeddings


async def search_similar(
    session: AsyncSession,
    *,
    project_id: int,
    query_text: str,
    top_k: int = 5,
    min_similarity: float = 0.3,
) -> list[dict[str, Any]]:
    """
    Semantic search: find the most similar stored texts for a project.

    Uses cosine distance with pgvector: 1 - (embedding <=> query_vector).

    Args:
        project_id: restrict search to this project
        query_text: the user's question / query
        top_k: max number of results
        min_similarity: minimum cosine similarity threshold (0–1)

    Returns:
        List of dicts: {"id", "content", "metadata", "similarity"}
        sorted by descending similarity.
    """
    if not is_ai_configured():
        return []

    query_vector = await generate_embedding(query_text)

    # pgvector cosine distance operator: <=>
    # similarity = 1 - cosine_distance
    # Use CAST() instead of :: to avoid asyncpg parameter parsing conflict
    sql = text("""
        SELECT
            id,
            content,
            metadata AS metadata_,
            1 - (embedding <=> CAST(:query_vec AS vector)) AS similarity
        FROM embeddings
        WHERE project_id = :project_id
          AND 1 - (embedding <=> CAST(:query_vec AS vector)) >= :min_sim
        ORDER BY embedding <=> CAST(:query_vec AS vector)
        LIMIT :top_k
    """)

    # Convert vector to string format pgvector expects: [0.1, 0.2, ...]
    vec_str = "[" + ",".join(str(v) for v in query_vector) + "]"

    result = await session.execute(
        sql,
        {
            "query_vec": vec_str,
            "project_id": project_id,
            "min_sim": min_similarity,
            "top_k": top_k,
        },
    )
    rows = result.fetchall()

    results = []
    for row in rows:
        metadata = None
        if row.metadata_:
            try:
                metadata = json.loads(row.metadata_)
            except json.JSONDecodeError:
                metadata = {"raw": row.metadata_}

        results.append({
            "id": row.id,
            "content": row.content,
            "metadata": metadata,
            "similarity": float(row.similarity),
        })

    logger.debug(
        "Semantic search: project_id=%d query='%s' → %d results (top sim=%.3f)",
        project_id,
        query_text[:50],
        len(results),
        results[0]["similarity"] if results else 0,
    )
    return results
