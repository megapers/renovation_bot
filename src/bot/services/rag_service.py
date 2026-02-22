"""
RAG (Retrieval-Augmented Generation) pipeline.

1. Accept a user question
2. Search for relevant context via pgvector semantic search
3. Build a prompt with project context + retrieved chunks
4. Generate an answer via Azure OpenAI chat completion

This gives the bot "memory" — it can answer questions about the project
based on chat history, stage data, and budget information.
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.ai_client import chat_completion, is_ai_configured
from bot.services.embedding_service import search_hybrid, search_similar
from bot.services.skills_loader import get_skill_prompt

logger = logging.getLogger(__name__)


# ── System prompt for RAG (fallback if skill file not found) ─

_RAG_SYSTEM_PROMPT_FALLBACK = (
    "Ты — умный помощник по ремонту квартир. "
    "Ты помогаешь клиентам, прорабам и дизайнерам "
    "управлять ремонтом.\n\n"
    "Тебе доступен контекст проекта (этапы, бюджет, "
    "сообщения). Используй его для ответа.\n\n"
    "Правила:\n"
    "1. Отвечай на русском языке\n"
    "2. Будь кратким и по делу\n"
    "3. Если в контексте нет информации для ответа — "
    "честно скажи об этом\n"
    "4. Если вопрос касается бюджета — указывай "
    "конкретные суммы из контекста\n"
    "5. Если вопрос касается сроков — указывай "
    "конкретные даты\n"
    "6. Не придумывай информацию, которой нет "
    "в контексте\n"
    "7. Форматируй ответ для мессенджера "
    "(короткие абзацы, без длинных таблиц)"
)


def _get_rag_system_prompt() -> str:
    """Load RAG system prompt from skill file, falling back to built-in."""
    prompt = get_skill_prompt("rag-assistant")
    if prompt:
        return prompt
    logger.debug("Skill 'rag-assistant' not found, using fallback prompt")
    return _RAG_SYSTEM_PROMPT_FALLBACK


# ── Public API ────────────────────────────────────────────────


async def ask_project(
    session: AsyncSession,
    *,
    project_id: int,
    question: str,
    project_context: str | None = None,
    top_k: int = 5,
) -> str:
    """
    Answer a question about a project using RAG.

    Responses are cached in PostgreSQL for 5 minutes to avoid
    redundant AI calls for similar questions.
    """
    if not is_ai_configured():
        return (
            "⚠️ AI-сервис не настроен. Для работы с умным помощником "
            "необходимо настроить Azure OpenAI в .env файле."
        )

    # Check cache for recent identical question
    import hashlib
    from bot.services.pg_cache import pg_cache_get, pg_cache_set
    q_hash = hashlib.md5(question.lower().strip().encode()).hexdigest()[:12]
    cache_key = f"ask:{project_id}:{q_hash}"

    cached_answer = await pg_cache_get(session, cache_key)
    if cached_answer is not None:
        logger.debug("RAG cache hit: %s", cache_key)
        return cached_answer

    # 1. Retrieve relevant context via hybrid search (vector + full-text)
    similar_chunks = await search_hybrid(
        session,
        project_id=project_id,
        query_text=question,
        top_k=top_k,
        min_similarity=0.2,
    )

    # 2. Build context block
    context_parts: list[str] = []

    if project_context:
        context_parts.append(f"=== Текущее состояние проекта ===\n{project_context}")

    if similar_chunks:
        context_parts.append("=== Релевантные сообщения и записи ===")
        for i, chunk in enumerate(similar_chunks, 1):
            meta = chunk.get("metadata") or {}
            source = meta.get("source", "сообщение")
            author = meta.get("author", "")
            date_str = meta.get("date", "")
            header = f"[{source}]"
            if author:
                header += f" от {author}"
            if date_str:
                header += f" ({date_str})"
            sources_tag = "/".join(chunk.get("sources", []))
            context_parts.append(
                f"{i}. {header} [{sources_tag}]:\n{chunk['content']}"
            )

    context_block = "\n\n".join(context_parts) if context_parts else "Контекст отсутствует."

    # 3. Generate answer
    messages = [
        {"role": "system", "content": _get_rag_system_prompt()},
        {
            "role": "user",
            "content": (
                f"Контекст проекта:\n{context_block}\n\n"
                f"Вопрос пользователя:\n{question}"
            ),
        },
    ]

    answer = await chat_completion(messages, temperature=0.4, max_tokens=1500)

    # Cache the answer for 5 minutes
    await pg_cache_set(session, cache_key, answer, ttl=300)

    logger.info(
        "RAG answer: project_id=%d, question='%s...', %d chunks used",
        project_id,
        question[:40],
        len(similar_chunks),
    )
    return answer


def build_project_context(
    project_data: dict[str, Any],
) -> str:
    """
    Build a text summary of project data for RAG context.

    Args:
        project_data: dict from repositories.get_project_full_report_data()
            Keys: project, stages, budget_summary, category_summaries

    Returns:
        Formatted text summary.
    """
    parts: list[str] = []

    project = project_data.get("project")
    if project:
        parts.append(
            f"Проект: {project.name}\n"
            f"Адрес: {project.address or 'не указан'}\n"
            f"Тип ремонта: {project.renovation_type.value}\n"
            f"Общий бюджет: {project.total_budget or 'не задан'}"
        )

    stages = project_data.get("stages", [])
    if stages:
        parts.append("Этапы:")
        for s in stages:
            line = f"  {s.order}. {s.name} — {s.status.value}"
            if s.start_date:
                line += f" (с {s.start_date.strftime('%d.%m.%Y')})"
            if s.end_date:
                line += f" (до {s.end_date.strftime('%d.%m.%Y')})"
            if s.budget:
                line += f" [бюджет: {s.budget}]"
            parts.append(line)

    budget = project_data.get("budget_summary", {})
    if budget:
        parts.append(
            f"Бюджет: потрачено {budget.get('total_spent', 0):.0f} из "
            f"{budget.get('total_budget', 'не задано')}\n"
            f"  Работы: {budget.get('total_work', 0):.0f}\n"
            f"  Материалы: {budget.get('total_materials', 0):.0f}\n"
            f"  Предоплаты: {budget.get('total_prepayments', 0):.0f}"
        )

    # Per-category expense breakdown
    from bot.core.budget_service import CATEGORY_LABELS

    cat_summaries = project_data.get("category_summaries", [])
    if cat_summaries:
        cat_lines = ["Расходы по категориям:"]
        for cs in cat_summaries:
            cat_name = CATEGORY_LABELS.get(cs["category"], cs["category"])
            cat_lines.append(
                f"  {cat_name}: работа {cs['work']:.0f}, "
                f"материалы {cs['materials']:.0f}, "
                f"итого {cs['total']:.0f}"
            )
        parts.append("\n".join(cat_lines))

    # Individual budget items (expense descriptions)
    budget_items = project_data.get("budget_items", [])
    if budget_items:
        item_lines = ["Список расходов:"]
        for bi in budget_items:
            cat_name = CATEGORY_LABELS.get(bi.category, bi.category)
            desc = bi.description or "без описания"
            amounts = []
            if float(bi.work_cost) > 0:
                amounts.append(f"работа {float(bi.work_cost):.0f}")
            if float(bi.material_cost) > 0:
                amounts.append(f"материалы {float(bi.material_cost):.0f}")
            if float(bi.prepayment) > 0:
                amounts.append(f"предоплата {float(bi.prepayment):.0f}")
            confirmed = "подтверждён" if bi.is_confirmed else "не подтверждён"
            item_lines.append(
                f"  • {cat_name} — {desc}: {', '.join(amounts)} ({confirmed})"
            )
        parts.append("\n".join(item_lines))

    return "\n\n".join(parts)
