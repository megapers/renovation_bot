"""
Core service for stage management — deadlines, assignments, budgets,
sub-stages, and project launch readiness.

Contains platform-agnostic business logic. Called by platform adapters
(Telegram, WhatsApp) but never imports platform-specific code.
"""

import logging
from datetime import datetime, timezone

from bot.db.models import Project

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


# format_launch_summary has been moved to adapters/telegram/formatters.py
