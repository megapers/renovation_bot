"""
Core service for stage management — deadlines, assignments, budgets,
sub-stages, project launch readiness, and checkpoint logic.

Contains platform-agnostic business logic. Called by platform adapters
(Telegram, WhatsApp) but never imports platform-specific code.
"""

import logging
from datetime import datetime, timezone

from bot.db.models import Project, Stage, StageStatus

logger = logging.getLogger(__name__)

# ── Date helpers ─────────────────────────────────────────────

DATE_FORMAT = "%d.%m.%Y"


def parse_date(text: str) -> datetime | None:
    """
    Parse a date string into a timezone-aware datetime.

    Accepts DD.MM.YYYY, DD/MM/YYYY, or YYYY-MM-DD.
    Returns None if parsing fails.
    """
    text = text.strip()
    for fmt in (DATE_FORMAT, "%d/%m/%Y", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def format_date(dt: datetime | None) -> str:
    """Format a datetime as DD.MM.YYYY or '—' if None."""
    if dt is None:
        return "—"
    return dt.strftime(DATE_FORMAT)


def days_between(start: datetime, end: datetime) -> int:
    """Calculate whole days between two datetimes."""
    return (end.date() - start.date()).days


# ── Stage formatting ─────────────────────────────────────────

STATUS_LABELS: dict[str, str] = {
    "planned": "📋 Запланирован",
    "in_progress": "🔨 В работе",
    "completed": "✅ Завершён",
    "delayed": "⚠️ Задержка",
}

STATUS_ICONS: dict[str, str] = {
    "planned": "📋",
    "in_progress": "🔨",
    "completed": "✅",
    "delayed": "⚠️",
}


# NOTE: format_stage_detail, format_stages_overview, and format_launch_summary
# have been moved to adapters/telegram/formatters.py — they contain HTML
# markup which is Telegram-specific. Core only provides data + utilities.


# ── Launch validation ────────────────────────────────────────


def validate_launch_readiness(project: Project) -> tuple[bool, list[str]]:
    """
    Check whether a project is ready to launch.

    Returns (is_ready, warnings).
    A project is ready if the first stage has a start date.
    Warnings list issues that don't block launch but should be addressed.
    """
    warnings: list[str] = []

    if not project.stages:
        return False, ["Нет этапов в проекте"]

    main_stages = [s for s in project.stages if not s.is_parallel]

    # First stage must have a start date
    first = main_stages[0] if main_stages else None
    if first is None:
        return False, ["Нет основных этапов"]

    if first.start_date is None:
        return False, ["Первый этап должен иметь дату начала"]

    # Warnings for incomplete stages
    for stage in main_stages:
        if stage.start_date is None:
            warnings.append(f"«{stage.name}» — нет даты начала")
        if stage.responsible_contact is None:
            warnings.append(f"«{stage.name}» — нет ответственного")
        if stage.budget is None:
            warnings.append(f"«{stage.name}» — нет бюджета")

    return True, warnings


# ── Checkpoint logic ─────────────────────────────────────────


# Checkpoint stage descriptions (Russian)
CHECKPOINT_DESCRIPTIONS: dict[str, str] = {
    "Электрика": "Проверьте количество и расположение розеток по плану",
    "Сантехника": "Проверьте расположение выводов для душа, смесителей и унитаза",
    "Плитка": "Самая частая точка для вызова эксперта — проверка качества укладки",
    "Шпаклёвка": "Важная контрольная точка — проверка качества перед покраской",
    "Итоговая приёмка": "Общая проверка завершённых работ",
}


def get_checkpoint_description(stage_name: str) -> str:
    """
    Get a human-readable description for a checkpoint stage.

    Returns a default message if the stage name isn't in the known checkpoints.
    """
    for key, desc in CHECKPOINT_DESCRIPTIONS.items():
        if key.lower() in stage_name.lower():
            return desc
    return "Контрольная точка — требуется проверка и одобрение перед продолжением"


def can_proceed_to_next_stage(completed_stage: Stage) -> tuple[bool, str]:
    """
    Check if we can proceed to the next stage after the given stage is completed.

    If the completed stage is a checkpoint, it requires explicit owner approval.

    Returns:
        (can_proceed, reason)
    """
    if completed_stage.is_checkpoint:
        return False, (
            f"Этап «{completed_stage.name}» — контрольная точка.\n"
            f"{get_checkpoint_description(completed_stage.name)}\n"
            "Требуется одобрение владельца проекта."
        )
    return True, ""


def get_stage_completion_info(stage: Stage) -> dict:
    """
    Get a summary of stage completion status.

    Useful for generating completion reports.
    """
    info = {
        "name": stage.name,
        "status": stage.status.value,
        "is_checkpoint": stage.is_checkpoint,
        "started": stage.start_date is not None,
        "has_deadline": stage.end_date is not None,
        "has_responsible": stage.responsible_contact is not None or stage.responsible_user_id is not None,
        "has_budget": stage.budget is not None,
    }

    if stage.end_date and stage.status == StageStatus.IN_PROGRESS:
        now = datetime.now(tz=timezone.utc)
        remaining = (stage.end_date - now).days
        info["days_remaining"] = remaining
        info["is_overdue"] = remaining < 0

    return info


# format_launch_summary has been moved to adapters/telegram/formatters.py
