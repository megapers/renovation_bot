"""
NLP stage parser — extract structured stage/sub-stage data from natural text.

Uses Azure OpenAI chat completions with JSON mode to parse messages like:
  "Демонтаж займёт 2 недели: 3 дня убрать плитку, 3 дня поднять пол,
   4 дня снять обои, 2 дня снять двери, 1 день вывоз мусора."

Into structured data:
  {
    "stage_name": "Демонтаж",
    "total_days": 14,
    "sub_stages": [
      {"name": "Убрать плитку", "days": 3},
      {"name": "Поднять пол", "days": 3},
      ...
    ]
  }
"""

import json
import logging
from datetime import date, timedelta
from typing import Any

from pydantic import BaseModel, Field

from bot.services.ai_client import chat_completion, is_ai_configured

logger = logging.getLogger(__name__)


# ── Pydantic models for parsed output ────────────────────────


class ParsedSubStage(BaseModel):
    """A sub-stage extracted from natural language."""
    name: str = Field(description="Название подэтапа")
    days: int | None = Field(default=None, description="Длительность в днях")


class ParsedStageInfo(BaseModel):
    """Structured stage info extracted from a message."""
    stage_name: str = Field(description="Название этапа")
    total_days: int | None = Field(default=None, description="Общая длительность в днях")
    sub_stages: list[ParsedSubStage] = Field(default_factory=list)
    estimated_budget: float | None = Field(default=None, description="Бюджет если упомянут")
    notes: str | None = Field(default=None, description="Дополнительные заметки")


class ParsedExpense(BaseModel):
    """An expense extracted from natural language."""
    category: str = Field(description="Категория расхода")
    description: str = Field(description="Описание")
    amount: float = Field(description="Сумма")
    is_materials: bool = Field(default=False, description="True если материалы, False если работа")


class ParsedMessage(BaseModel):
    """Full result of NLP message parsing."""
    intent: str = Field(description="Намерение: stage_plan | expense | status_update | question | other")
    stages: list[ParsedStageInfo] = Field(default_factory=list)
    expenses: list[ParsedExpense] = Field(default_factory=list)
    status_update: str | None = Field(default=None)
    raw_summary: str = Field(default="", description="Краткое резюме сообщения")


# ── System prompts ─────────────────────────────────────────


_STAGE_PARSER_SYSTEM = """Ты — помощник по ремонту квартир. Твоя задача — извлечь структурированную информацию из сообщений прорабов, дизайнеров и рабочих.

Тебе дают текст сообщения. Определи намерение (intent) и извлеки данные.

Возможные intent:
- "stage_plan" — описание этапа работ с подэтапами и сроками
- "expense" — информация о расходах, оплатах, стоимости
- "status_update" — обновление статуса работ ("плитку положили", "электрика готова")
- "question" — вопрос от участника
- "other" — прочее

Правила:
1. Если упоминаются сроки в неделях — переведи в дни (1 неделя = 7 дней)
2. Если упоминаются несколько подэтапов — перечисли каждый отдельно
3. Если упоминается бюджет/стоимость — извлеки числа
4. Суммы в рублях, если не указана другая валюта
5. Названия подэтапов начинай с заглавной буквы
6. Всегда возвращай краткое резюме (raw_summary)

Ответ ТОЛЬКО в формате JSON (без markdown), строго следуя схеме."""

_STAGE_PARSER_SCHEMA = """{
  "intent": "stage_plan | expense | status_update | question | other",
  "stages": [
    {
      "stage_name": "string",
      "total_days": number | null,
      "sub_stages": [
        {"name": "string", "days": number | null}
      ],
      "estimated_budget": number | null,
      "notes": "string | null"
    }
  ],
  "expenses": [
    {
      "category": "string",
      "description": "string",
      "amount": number,
      "is_materials": boolean
    }
  ],
  "status_update": "string | null",
  "raw_summary": "string"
}"""


# ── Public API ────────────────────────────────────────────────


async def parse_message(text: str) -> ParsedMessage | None:
    """
    Parse a natural-language message and extract structured renovation data.

    Returns None if AI is not configured.
    """
    if not is_ai_configured():
        logger.warning("AI not configured — skipping message parsing")
        return None

    if not text or not text.strip():
        return None

    messages = [
        {"role": "system", "content": _STAGE_PARSER_SYSTEM},
        {
            "role": "user",
            "content": (
                f"Извлеки структурированные данные из сообщения.\n\n"
                f"Схема ответа:\n{_STAGE_PARSER_SCHEMA}\n\n"
                f"Сообщение:\n{text}"
            ),
        },
    ]

    try:
        raw = await chat_completion(
            messages,
            temperature=0.1,
            max_tokens=2000,
            response_format={"type": "json_object"},
        )
        data = json.loads(raw)
        parsed = ParsedMessage(**data)
        logger.info(
            "Parsed message: intent=%s, %d stages, %d expenses",
            parsed.intent, len(parsed.stages), len(parsed.expenses),
        )
        return parsed
    except (json.JSONDecodeError, Exception) as e:
        logger.error("Failed to parse NLP response: %s", e)
        return None


async def parse_stage_description(text: str) -> list[ParsedStageInfo]:
    """
    Parse text specifically for stage planning info.

    Convenience wrapper that calls parse_message and returns only stages.
    """
    result = await parse_message(text)
    if result and result.stages:
        return result.stages
    return []


async def parse_expenses_from_text(text: str) -> list[ParsedExpense]:
    """
    Parse text specifically for expense/budget info.

    Convenience wrapper that calls parse_message and returns only expenses.
    """
    result = await parse_message(text)
    if result and result.expenses:
        return result.expenses
    return []


def compute_substage_dates(
    start: date,
    sub_stages: list[ParsedSubStage],
) -> list[dict[str, Any]]:
    """
    Compute start/end dates for sub-stages given a starting date.

    Sub-stages are laid out sequentially. Each sub-stage's end date
    feeds into the next one's start date.

    Returns list of:
        {"name": str, "start_date": date, "end_date": date, "days": int}
    """
    result: list[dict[str, Any]] = []
    current = start

    for sub in sub_stages:
        days = sub.days or 1  # default 1 day if not specified
        end = current + timedelta(days=days)
        result.append({
            "name": sub.name,
            "start_date": current,
            "end_date": end,
            "days": days,
        })
        current = end

    return result
