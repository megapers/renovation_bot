"""
Core service for stage management — deadlines, assignments, budgets,
sub-stages, and project launch readiness.

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


def format_stage_detail(stage: Stage) -> str:
    """Format a single stage's details for display."""
    lines: list[str] = []

    icon = STATUS_ICONS.get(stage.status.value, "📋")
    lines.append(f"{icon} <b>{stage.name}</b>")
    lines.append(f"Статус: {STATUS_LABELS.get(stage.status.value, stage.status.value)}")

    if stage.is_checkpoint:
        lines.append("🔒 Контрольная точка (требуется одобрение)")
    if stage.is_parallel:
        lines.append("🪑 Параллельный этап (мебель на заказ)")

    lines.append("")

    # Dates
    if stage.start_date or stage.end_date:
        start = format_date(stage.start_date)
        end = format_date(stage.end_date)
        lines.append(f"📅 Сроки: {start} — {end}")
        if stage.start_date and stage.end_date:
            duration = days_between(stage.start_date, stage.end_date)
            lines.append(f"   Длительность: {duration} дн.")
    else:
        lines.append("📅 Сроки: <i>не указаны</i>")

    # Responsible person
    if stage.responsible_contact:
        lines.append(f"👤 Ответственный: {stage.responsible_contact}")
    else:
        lines.append("👤 Ответственный: <i>не назначен</i>")

    # Budget
    if stage.budget:
        lines.append(f"💰 Бюджет: {stage.budget:,.0f} ₸")
    else:
        lines.append("💰 Бюджет: <i>не указан</i>")

    # Sub-stages
    if stage.sub_stages:
        lines.append("")
        lines.append(f"📝 Подзадачи ({len(stage.sub_stages)}):")
        for sub in stage.sub_stages:
            sub_icon = STATUS_ICONS.get(sub.status.value, "📋")
            lines.append(f"  {sub_icon} {sub.order}. {sub.name}")

    return "\n".join(lines)


def format_stages_overview(stages: list[Stage]) -> str:
    """Format a compact overview of all stages for display."""
    main = [s for s in stages if not s.is_parallel]
    parallel = [s for s in stages if s.is_parallel]

    lines: list[str] = ["📋 <b>Этапы ремонта:</b>", ""]

    for stage in main:
        icon = STATUS_ICONS.get(stage.status.value, "📋")
        info_parts: list[str] = []
        if stage.start_date and stage.end_date:
            info_parts.append(
                f"{format_date(stage.start_date)}–{format_date(stage.end_date)}"
            )
        if stage.responsible_contact:
            info_parts.append(stage.responsible_contact)
        if stage.budget:
            info_parts.append(f"{stage.budget:,.0f} ₸")

        info = f" — {', '.join(info_parts)}" if info_parts else ""
        checkpoint = " 🔒" if stage.is_checkpoint else ""
        lines.append(f"{icon} {stage.order}. {stage.name}{checkpoint}{info}")

    if parallel:
        lines.append("")
        lines.append("<b>🪑 Параллельные этапы:</b>")
        for stage in parallel:
            icon = STATUS_ICONS.get(stage.status.value, "📋")
            lines.append(f"  {icon} {stage.name}")

    return "\n".join(lines)


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


def format_launch_summary(project: Project) -> str:
    """Format a complete project summary for the launch confirmation screen."""
    from bot.core.project_service import format_project_summary

    lines: list[str] = [
        "🚀 <b>Запуск проекта</b>",
        "",
        format_project_summary(project),
    ]

    is_ready, warnings = validate_launch_readiness(project)

    if warnings:
        lines.append("")
        lines.append(f"⚠️ <b>Предупреждения ({len(warnings)}):</b>")
        for w in warnings:
            lines.append(f"  • {w}")

    if is_ready:
        lines.append("")
        lines.append("Нажмите <b>🚀 Запустить</b>, чтобы начать ремонт.")
        lines.append("Первый этап будет переведён в статус «В работе».")
    else:
        lines.append("")
        lines.append("❌ Проект <b>не готов к запуску</b>.")
        lines.append("Устраните проблемы и попробуйте снова.")

    return "\n".join(lines)
