"""
Participant summary service.

Generates per-participant summaries by collecting all messages each user
sent in a project and asking the LLM to describe their contributions,
purchases, and activity.

Also exposes a conversation-search helper that combines vector and
full-text results over the *messages* table (not just embeddings).
"""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from bot.db import repositories as repo
from bot.services.ai_client import chat_completion, is_ai_configured
from bot.services.skills_loader import get_skill_prompt

logger = logging.getLogger(__name__)

_PARTICIPANT_PROMPT_FALLBACK = (
    "Ты — аналитик ремонтных проектов. Тебе дан список сообщений "
    "одного участника чата по ремонту квартиры.\n\n"
    "Составь краткое резюме вклада этого участника:\n"
    "1. Что он делал (какие работы выполнил или организовал)\n"
    "2. Что он купил (материалы, оборудование)\n"
    "3. Какие суммы упоминались\n"
    "4. Ключевые решения или проблемы\n\n"
    "Отвечай на русском. Будь кратким, по делу. "
    "Если информации мало — скажи об этом честно."
)


def _get_participant_prompt() -> str:
    prompt = get_skill_prompt("participant-summary")
    if prompt:
        return prompt
    return _PARTICIPANT_PROMPT_FALLBACK


async def summarize_participant(
    session: AsyncSession,
    *,
    project_id: int,
    user_id: int,
    max_messages: int = 200,
) -> dict[str, Any]:
    """
    Summarize a single participant's contributions to a project.

    Returns:
        {
            "user_id": int,
            "user_name": str,
            "message_count": int,
            "summary": str,  # AI-generated summary
        }
    """
    grouped = await repo.get_messages_grouped_by_user(
        session, project_id, limit_per_user=max_messages,
    )
    messages = grouped.get(user_id, [])

    # Get user name
    user = await repo.get_user_by_id(session, user_id)
    user_name = user.full_name if user else f"User #{user_id}"

    if not messages:
        return {
            "user_id": user_id,
            "user_name": user_name,
            "message_count": 0,
            "summary": "Нет сообщений от этого участника.",
        }

    # Build message list for the LLM
    lines = []
    for msg in messages:
        date_str = msg.created_at.strftime("%d.%m.%Y %H:%M") if msg.created_at else ""
        text = msg.transcribed_text or msg.raw_text or ""
        type_tag = f"[{msg.message_type.value}]" if msg.message_type.value != "text" else ""
        lines.append(f"[{date_str}] {type_tag} {text}")

    conversation_text = "\n".join(lines)

    if not is_ai_configured():
        return {
            "user_id": user_id,
            "user_name": user_name,
            "message_count": len(messages),
            "summary": "⚠️ AI не настроен — резюме недоступно.",
        }

    prompt_messages = [
        {"role": "system", "content": _get_participant_prompt()},
        {
            "role": "user",
            "content": (
                f"Участник: {user_name}\n"
                f"Количество сообщений: {len(messages)}\n\n"
                f"Сообщения:\n{conversation_text}"
            ),
        },
    ]

    summary = await chat_completion(prompt_messages, temperature=0.3, max_tokens=1000)

    return {
        "user_id": user_id,
        "user_name": user_name,
        "message_count": len(messages),
        "summary": summary,
    }


async def summarize_all_participants(
    session: AsyncSession,
    *,
    project_id: int,
    max_messages_per_user: int = 200,
) -> list[dict[str, Any]]:
    """
    Summarize every participant's contributions in a project.

    Returns a list of per-participant summaries (same shape as
    ``summarize_participant`` output), ordered by message count desc.
    """
    grouped = await repo.get_messages_grouped_by_user(
        session, project_id, limit_per_user=max_messages_per_user,
    )

    if not grouped:
        return []

    results: list[dict[str, Any]] = []
    for uid, messages in grouped.items():
        user = messages[0].user if messages and messages[0].user else None
        user_name = user.full_name if user else f"User #{uid}"

        lines = []
        for msg in messages:
            date_str = msg.created_at.strftime("%d.%m.%Y %H:%M") if msg.created_at else ""
            text = msg.transcribed_text or msg.raw_text or ""
            type_tag = f"[{msg.message_type.value}]" if msg.message_type.value != "text" else ""
            lines.append(f"[{date_str}] {type_tag} {text}")

        conversation_text = "\n".join(lines)

        if is_ai_configured():
            prompt_messages = [
                {"role": "system", "content": _get_participant_prompt()},
                {
                    "role": "user",
                    "content": (
                        f"Участник: {user_name}\n"
                        f"Количество сообщений: {len(messages)}\n\n"
                        f"Сообщения:\n{conversation_text}"
                    ),
                },
            ]
            summary = await chat_completion(
                prompt_messages, temperature=0.3, max_tokens=1000,
            )
        else:
            summary = "⚠️ AI не настроен — резюме недоступно."

        results.append({
            "user_id": uid,
            "user_name": user_name,
            "message_count": len(messages),
            "summary": summary,
        })

    # Sort by message count descending
    results.sort(key=lambda r: r["message_count"], reverse=True)
    return results
