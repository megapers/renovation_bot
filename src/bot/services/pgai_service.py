"""
pgai integration — in-database AI functions via Timescale pgai extension.

This module provides SQL-level AI capabilities:
  - In-database embedding generation (no Python round-trip)
  - In-database RAG search (embed + search in single query)
  - Auto-vectorization setup for tables

pgai supports multiple backends:
  - openai_embed()   — OpenAI / Azure OpenAI / OpenAI-compatible APIs
  - ollama_embed()   — Local Ollama server
  - litellm_embed()  — LiteLLM proxy (routes to any provider)

The backend is configured via the AI_PROVIDER / AI_BASE_URL settings.
When using self-hosted models (Ollama, vLLM), pgai calls the model
server directly from PostgreSQL — no Python intermediary needed.

Usage:
    from bot.services.pgai_service import pgai_embed_and_search

    results = await pgai_embed_and_search(
        session, project_id=5, query="бюджет на электрику"
    )
"""

import json
import logging
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import settings

logger = logging.getLogger(__name__)


def _get_embed_function_sql() -> str:
    """
    Return the pgai SQL function call for embedding based on AI_PROVIDER.

    For OpenAI/Azure/compatible:
        ai.openai_embed(model, text, base_url, api_key, dimensions)
    For Ollama:
        ai.ollama_embed(model, text, host)
    """
    provider = settings.ai_provider

    if provider in ("openai", "openai_compatible"):
        base_url = settings.ai_base_url or "https://api.openai.com/v1"
        api_key = settings.ai_api_key
        model = settings.effective_embedding_model
        dims = settings.ai_embedding_dimensions

        # Build the function call with parameters
        parts = [f"'{model}'", ":query_text"]
        if base_url and provider == "openai_compatible":
            parts.append(f"_base_url => '{base_url}'")
        if api_key:
            parts.append(f"_api_key => '{api_key}'")
        if dims:
            parts.append(f"_dimensions => {dims}")

        return f"ai.openai_embed({', '.join(parts)})"

    elif provider == "azure":
        # Azure OpenAI uses the same openai_embed but with azure endpoint
        endpoint = settings.azure_openai_endpoint
        api_key = settings.azure_openai_api_key
        model = settings.effective_embedding_model

        if not api_key:
            # Entra ID auth not supported in pgai SQL — fall back to Python
            logger.warning(
                "pgai: Azure Entra ID auth not supported for in-DB embeddings. "
                "Falling back to Python-side embedding."
            )
            return ""

        # Azure endpoint needs /openai/deployments/{model}/embeddings path
        base_url = f"{endpoint.rstrip('/')}/openai/deployments/{model}/embeddings?api-version={settings.azure_openai_api_version}"
        return f"ai.openai_embed('{model}', :query_text, _api_key => '{api_key}', _base_url => '{base_url}')"

    else:
        return ""


async def pgai_search(
    session: AsyncSession,
    *,
    project_id: int,
    query_embedding: list[float],
    top_k: int = 5,
    min_similarity: float = 0.3,
) -> list[dict[str, Any]]:
    """
    Search embeddings using a pre-computed query vector.

    This is useful when the embedding is generated Python-side
    (e.g., via ai_client.generate_embedding) and you want to
    search using pgvector's cosine distance.
    """
    vec_str = "[" + ",".join(str(v) for v in query_embedding) + "]"

    sql = text("""
        SELECT
            id, content, metadata AS metadata_,
            1 - (embedding <=> CAST(:query_vec AS vector)) AS similarity
        FROM embeddings
        WHERE project_id = :project_id
          AND 1 - (embedding <=> CAST(:query_vec AS vector)) >= :min_sim
        ORDER BY embedding <=> CAST(:query_vec AS vector)
        LIMIT :top_k
    """)

    result = await session.execute(sql, {
        "query_vec": vec_str,
        "project_id": project_id,
        "min_sim": min_similarity,
        "top_k": top_k,
    })

    return [
        {
            "id": row.id,
            "content": row.content,
            "metadata": json.loads(row.metadata_) if row.metadata_ else None,
            "similarity": float(row.similarity),
        }
        for row in result.fetchall()
    ]


async def pgai_embed_and_search(
    session: AsyncSession,
    *,
    project_id: int,
    query_text: str,
    top_k: int = 5,
    min_similarity: float = 0.3,
) -> list[dict[str, Any]]:
    """
    Generate embedding and search in a single SQL query using pgai.

    The embedding is generated inside PostgreSQL by pgai calling the
    configured AI provider directly — no Python round-trip for the
    embedding step.

    Falls back to Python-side embedding if pgai SQL embedding is not
    available (e.g., Azure Entra ID auth).
    """
    embed_fn = _get_embed_function_sql()

    if not embed_fn:
        # Fall back to Python-side embedding + search
        from bot.services.embedding_service import search_similar
        return await search_similar(
            session, project_id=project_id,
            query_text=query_text, top_k=top_k,
            min_similarity=min_similarity,
        )

    sql = text(f"""
        WITH query_embedding AS (
            SELECT {embed_fn} AS vec
        )
        SELECT
            e.id, e.content, e.metadata AS metadata_,
            1 - (e.embedding <=> q.vec) AS similarity
        FROM embeddings e, query_embedding q
        WHERE e.project_id = :project_id
          AND 1 - (e.embedding <=> q.vec) >= :min_sim
        ORDER BY e.embedding <=> q.vec
        LIMIT :top_k
    """)

    result = await session.execute(sql, {
        "query_text": query_text,
        "project_id": project_id,
        "min_sim": min_similarity,
        "top_k": top_k,
    })

    return [
        {
            "id": row.id,
            "content": row.content,
            "metadata": json.loads(row.metadata_) if row.metadata_ else None,
            "similarity": float(row.similarity),
        }
        for row in result.fetchall()
    ]


async def pgai_chat(
    session: AsyncSession,
    *,
    system_prompt: str,
    user_message: str,
    model: str | None = None,
) -> str:
    """
    Call a chat completion from inside PostgreSQL via pgai.

    Useful for simple AI calls without Python overhead.
    For complex multi-turn conversations, use ai_client.chat_completion().
    """
    model = model or settings.effective_chat_model
    provider = settings.ai_provider

    if provider in ("openai", "openai_compatible"):
        base_url = settings.ai_base_url or "https://api.openai.com/v1"
        api_key = settings.ai_api_key

        sql = text("""
            SELECT ai.openai_chat_complete_simple(
                :model, :message,
                _base_url => :base_url,
                _api_key => :api_key
            ) AS response
        """)
        result = await session.execute(sql, {
            "model": model,
            "message": user_message,
            "base_url": base_url,
            "api_key": api_key,
        })
        row = result.fetchone()
        return row.response if row else ""

    # For other providers, fall back to Python
    from bot.services.ai_client import chat_completion
    return await chat_completion([
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_message},
    ])


async def check_pgai_available(session: AsyncSession) -> bool:
    """Check if pgai extension is installed and functional."""
    try:
        result = await session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'ai'")
        )
        row = result.fetchone()
        if row:
            logger.info("pgai extension available: v%s", row.extversion)
            return True
        return False
    except Exception:
        return False
