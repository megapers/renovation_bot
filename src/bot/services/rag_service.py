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
from bot.services.embedding_service import search_similar
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

    Args:
        session: async DB session
        project_id: the project to query about
        question: user's question in natural language
        project_context: optional pre-built project summary
            (stages, budget, etc.) to include as context
        top_k: number of similar chunks to retrieve

    Returns:
        AI-generated answer (Russian).
    """
    if not is_ai_configured():
        return (
            "⚠️ AI-сервис не настроен. Для работы с умным помощником "
            "необходимо настроить Azure OpenAI в .env файле."
        )

    # 1. Retrieve relevant context from embeddings
    similar_chunks = await search_similar(
        session,
        project_id=project_id,
        query_text=question,
        top_k=top_k,
        min_similarity=0.25,
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
            context_parts.append(f"{i}. {header}:\n{chunk['content']}")

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

    return "\n\n".join(parts)
