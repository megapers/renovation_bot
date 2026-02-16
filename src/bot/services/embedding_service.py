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


# ── Full-text search (tsvector / tsquery) ────────────────────


def _build_tsquery(query_text: str) -> str:
    """
    Build a PostgreSQL tsquery string from a user query.

    Tokenises the input, drops very short tokens, and joins with '|' (OR)
    so that any keyword match counts.  Uses the 'simple' text-search
    config (language-agnostic, works well for Russian).
    """
    tokens = query_text.split()
    # Keep tokens with ≥2 chars; strip punctuation
    clean = []
    for t in tokens:
        t = t.strip(".,;:!?\"'()[]{}«»—–")
        if len(t) >= 2:
            clean.append(t)
    if not clean:
        return query_text.strip() or ""
    # prefix matching (lexeme:*) so partial words still hit
    return " | ".join(f"{t}:*" for t in clean)


async def search_fulltext(
    session: AsyncSession,
    *,
    project_id: int,
    query_text: str,
    top_k: int = 10,
) -> list[dict[str, Any]]:
    """
    Full-text search over embeddings using PostgreSQL tsvector / tsquery.

    Searches the ``search_tsv`` generated column with a 'simple'-config
    tsquery.  Results are ranked by ``ts_rank``.

    Returns:
        List of dicts: {"id", "content", "metadata", "rank"}
        sorted by descending rank.
    """
    tsq = _build_tsquery(query_text)
    if not tsq:
        return []

    sql = text("""
        SELECT
            id,
            content,
            metadata AS metadata_,
            ts_rank(search_tsv, to_tsquery('simple', :tsq)) AS rank
        FROM embeddings
        WHERE project_id = :project_id
          AND search_tsv @@ to_tsquery('simple', :tsq)
        ORDER BY rank DESC
        LIMIT :top_k
    """)

    result = await session.execute(
        sql,
        {"project_id": project_id, "tsq": tsq, "top_k": top_k},
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
            "rank": float(row.rank),
        })

    logger.debug(
        "Full-text search: project_id=%d query='%s' → %d results",
        project_id, query_text[:50], len(results),
    )
    return results


# ── Hybrid search (vector + full-text, RRF fusion) ──────────


async def search_hybrid(
    session: AsyncSession,
    *,
    project_id: int,
    query_text: str,
    top_k: int = 5,
    vector_weight: float = 0.6,
    fts_weight: float = 0.4,
    min_similarity: float = 0.2,
) -> list[dict[str, Any]]:
    """
    Hybrid search combining pgvector semantic similarity and PostgreSQL
    full-text search using Reciprocal Rank Fusion (RRF).

    The RRF formula: ``score = sum(1 / (k + rank_i))`` across retrieval
    methods, where ``k=60`` (standard constant).  Weights are applied as
    multipliers so the caller can bias towards vector or keyword matches.

    Args:
        project_id: restrict search to this project
        query_text: user's search query
        top_k: max results to return after fusion
        vector_weight: multiplier for vector RRF score (default 0.6)
        fts_weight: multiplier for FTS RRF score (default 0.4)
        min_similarity: minimum cosine similarity for vector arm

    Returns:
        List of dicts: {"id", "content", "metadata", "score", "sources"}
        sorted by descending fused score.
    """
    RRF_K = 60  # standard RRF constant

    # Run both arms (vector needs AI; FTS does not)
    vector_results = await search_similar(
        session,
        project_id=project_id,
        query_text=query_text,
        top_k=top_k * 2,  # over-fetch for better fusion
        min_similarity=min_similarity,
    )
    fts_results = await search_fulltext(
        session,
        project_id=project_id,
        query_text=query_text,
        top_k=top_k * 2,
    )

    # Build RRF score map   id → {"score", "content", "metadata", "sources"}
    merged: dict[int, dict[str, Any]] = {}

    for rank_pos, item in enumerate(vector_results):
        eid = item["id"]
        rrf = vector_weight / (RRF_K + rank_pos + 1)
        if eid not in merged:
            merged[eid] = {
                "id": eid,
                "content": item["content"],
                "metadata": item["metadata"],
                "score": 0.0,
                "sources": [],
            }
        merged[eid]["score"] += rrf
        merged[eid]["sources"].append("vector")

    for rank_pos, item in enumerate(fts_results):
        eid = item["id"]
        rrf = fts_weight / (RRF_K + rank_pos + 1)
        if eid not in merged:
            merged[eid] = {
                "id": eid,
                "content": item["content"],
                "metadata": item["metadata"],
                "score": 0.0,
                "sources": [],
            }
        merged[eid]["score"] += rrf
        merged[eid]["sources"].append("fts")

    # Sort by fused score and trim
    ranked = sorted(merged.values(), key=lambda x: x["score"], reverse=True)[:top_k]

    logger.debug(
        "Hybrid search: project_id=%d query='%s' → %d vec, %d fts → %d fused",
        project_id,
        query_text[:50],
        len(vector_results),
        len(fts_results),
        len(ranked),
    )
    return ranked
