"""
Conversational chat service for project owners / co-owners.

Provides a rich, multi-turn conversation mode where the LLM can answer
questions about the project by pulling together:
  - Project metadata (name, address, type, budget)
  - Stage & sub-stage details (statuses, deadlines, budgets, responsible)
  - Budget items & category summaries
  - Team roster with roles and message counts
  - Message search (hybrid: vector + full-text)
  - Per-participant message history

The service maintains a short conversation history (last N turns) so the
user can ask follow-up questions naturally.

Access is restricted to Owner and Co-Owner roles.
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repositories as repo
from bot.db.models import RoleType
from bot.services.ai_client import chat_completion, is_ai_configured
from bot.services.embedding_service import search_hybrid
from bot.services.rag_service import build_project_context
from bot.services.skills_loader import get_skill_prompt

logger = logging.getLogger(__name__)

# Maximum conversation turns to keep in memory (system + user + assistant)
MAX_HISTORY_TURNS = 10

# ── System prompt ────────────────────────────────────────────

_CHAT_SYSTEM_PROMPT_FALLBACK = """\
Ты — AI-ассистент по управлению ремонтом квартиры. Ты работаешь \
с владельцем проекта и отвечаешь на любые вопросы о ремонте.

Тебе доступна полная информация о проекте:
- Параметры проекта (название, адрес, тип, бюджет)
- Этапы работ (статусы, сроки, ответственные, подэтапы)
- Бюджет по категориям (работы, материалы, предоплаты)
- Команда проекта (участники, роли, активность)
- История сообщений участников (что писали, покупки, решения)
- Результаты поиска по сообщениям (семантический + полнотекстовый)

Правила:
1. Отвечай на русском языке
2. Будь кратким и по делу
3. Если вопрос о конкретном участнике — используй данные его сообщений
4. Если вопрос о бюджете — указывай конкретные суммы
5. Если вопрос о сроках — указывай конкретные даты
6. Не придумывай информацию, которой нет в контексте
7. Если информации недостаточно — честно скажи об этом
8. Форматируй ответ для мессенджера (короткие абзацы)
9. Если пользователь просит резюме по участнику — дай подробный \
   обзор его вклада на основе сообщений
10. Если пользователь просит найти что-то — используй результаты \
    поиска по сообщениям
"""


def _get_chat_system_prompt() -> str:
    """Load chat system prompt from skill file, falling back to built-in."""
    prompt = get_skill_prompt("chat-assistant")
    if prompt:
        return prompt
    return _CHAT_SYSTEM_PROMPT_FALLBACK


# ── Context builders ─────────────────────────────────────────


def _format_team_roster(roster: list[dict]) -> str:
    """Format team roster for LLM context."""
    if not roster:
        return "Команда: нет участников."
    lines = ["=== Команда проекта ==="]
    for m in roster:
        roles_str = ", ".join(m["roles"])
        lines.append(
            f"  • {m['full_name']} — роли: {roles_str}, "
            f"сообщений: {m['message_count']}"
        )
    return "\n".join(lines)


def _format_messages(messages: list, label: str = "Сообщения") -> str:
    """Format a list of Message objects into readable text."""
    if not messages:
        return ""
    lines = [f"=== {label} ==="]
    for msg in messages:
        date_str = msg.created_at.strftime("%d.%m.%Y %H:%M") if msg.created_at else ""
        author = msg.user.full_name if msg.user else "?"
        text = msg.transcribed_text or msg.raw_text or ""
        type_tag = f"[{msg.message_type.value}] " if msg.message_type.value != "text" else ""
        lines.append(f"[{date_str}] {author}: {type_tag}{text}")
    return "\n".join(lines)


def _format_search_results(results: list[dict]) -> str:
    """Format hybrid search results for LLM context."""
    if not results:
        return ""
    lines = ["=== Результаты поиска ==="]
    for i, r in enumerate(results, 1):
        meta = r.get("metadata") or {}
        source = meta.get("source", "сообщение")
        sources_tag = "/".join(r.get("sources", []))
        lines.append(f"{i}. [{source}] [{sources_tag}]: {r['content'][:300]}")
    return "\n".join(lines)


def _format_budget_categories(categories: list[dict]) -> str:
    """Format budget category summaries."""
    if not categories:
        return ""
    lines = ["=== Бюджет по категориям ==="]
    for cat in categories:
        lines.append(
            f"  {cat['category']}: работы={cat['work']:.0f}, "
            f"материалы={cat['materials']:.0f}, "
            f"предоплаты={cat['prepayments']:.0f}, "
            f"итого={cat['total']:.0f}, "
            f"подтверждено={cat['confirmed']:.0f}"
        )
    return "\n".join(lines)


# ── Main chat function ───────────────────────────────────────


async def chat_with_project(
    session: AsyncSession,
    *,
    project_id: int,
    user_message: str,
    conversation_history: list[dict[str, str]],
) -> tuple[str, list[dict[str, str]]]:
    """
    Handle a conversational message from the project owner/co-owner.

    Gathers rich context from the database, runs hybrid search on the
    user's question, and produces an AI answer in the context of full
    project data.

    Args:
        session: async DB session
        project_id: the project being discussed
        user_message: the user's latest message text
        conversation_history: list of prior {"role": ..., "content": ...}
            messages (without system prompt)

    Returns:
        (answer_text, updated_history) — the AI response and the
        conversation history with the new turn appended.
    """
    if not is_ai_configured():
        return (
            "⚠️ AI-сервис не настроен.",
            conversation_history,
        )

    # ── 1. Gather project context ──
    report_data = await repo.get_project_full_report_data(session, project_id)
    project_ctx = build_project_context(report_data)

    # ── 2. Team roster ──
    roster = await repo.get_team_roster_with_stats(session, project_id)
    roster_text = _format_team_roster(roster)

    # ── 3. Budget categories ──
    category_summaries = report_data.get("category_summaries", [])
    budget_text = _format_budget_categories(category_summaries)

    # ── 4. Hybrid search on user's question ──
    search_results = await search_hybrid(
        session,
        project_id=project_id,
        query_text=user_message,
        top_k=8,
        min_similarity=0.15,
    )
    search_text = _format_search_results(search_results)

    # ── 5. Check if the question mentions a specific team member ──
    participant_text = ""
    for member in roster:
        name_lower = member["full_name"].lower()
        # Check if the user's question mentions this person's name
        if name_lower in user_message.lower() or any(
            part in user_message.lower()
            for part in name_lower.split()
            if len(part) >= 3
        ):
            # Fetch their recent messages
            user_msgs = await repo.get_recent_messages_for_user_in_project(
                session, project_id, member["user_id"], limit=30,
            )
            if user_msgs:
                participant_text += _format_messages(
                    list(reversed(user_msgs)),
                    label=f"Сообщения от {member['full_name']}",
                ) + "\n\n"

    # ── 6. Build the full context block ──
    context_parts = [project_ctx, roster_text]
    if budget_text:
        context_parts.append(budget_text)
    if participant_text:
        context_parts.append(participant_text.strip())
    if search_text:
        context_parts.append(search_text)

    full_context = "\n\n".join(context_parts)

    # ── 7. Build messages for LLM ──
    system_prompt = _get_chat_system_prompt()
    system_content = f"{system_prompt}\n\n{full_context}"

    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_content},
    ]

    # Add conversation history (trimmed to MAX_HISTORY_TURNS)
    trimmed_history = conversation_history[-(MAX_HISTORY_TURNS * 2):]
    messages.extend(trimmed_history)

    # Add the new user message
    messages.append({"role": "user", "content": user_message})

    # ── 8. Generate response ──
    answer = await chat_completion(messages, temperature=0.4, max_tokens=2000)

    # ── 9. Update conversation history ──
    new_history = list(trimmed_history)
    new_history.append({"role": "user", "content": user_message})
    new_history.append({"role": "assistant", "content": answer})

    logger.info(
        "Chat: project_id=%d, question='%s...', %d search results, "
        "%d history turns",
        project_id,
        user_message[:40],
        len(search_results),
        len(new_history) // 2,
    )

    return answer, new_history
