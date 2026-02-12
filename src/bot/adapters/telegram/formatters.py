"""
Telegram-specific message formatters — HTML output.

These functions format structured data into HTML strings suitable for
Telegram's HTML parse mode. A WhatsApp adapter would have its own
formatters producing plain text or WhatsApp-specific markup.

Core services return raw data or plain text. All HTML formatting
belongs here, never in core/.
"""

from bot.core.role_service import format_role_list
from bot.core.stage_service import (
    STATUS_ICONS,
    STATUS_LABELS,
    days_between,
    format_date,
    validate_launch_readiness,
)
from bot.db.models import Project, RenovationType, RoleType, Stage


# ── Project formatting ────────────────────────────────────────


def format_project_summary(project: Project) -> str:
    """
    Format a project summary with Telegram HTML markup.

    Used after project creation and in launch summaries.
    """
    type_labels = {
        RenovationType.COSMETIC: "Косметический",
        RenovationType.STANDARD: "Стандартный",
        RenovationType.MAJOR: "Капитальный",
        RenovationType.DESIGNER: "Дизайнерский",
    }

    lines = [
        f"🏠 <b>{project.name}</b>",
        "",
    ]

    if project.address:
        lines.append(f"📍 Адрес: {project.address}")
    if project.area_sqm:
        lines.append(f"📐 Площадь: {project.area_sqm} м²")

    lines.append(
        f"🔧 Тип ремонта: "
        f"{type_labels.get(project.renovation_type, project.renovation_type.value)}"
    )

    if project.total_budget:
        lines.append(f"💰 Бюджет: {project.total_budget:,.0f} ₸")

    if project.stages:
        lines.append("")
        lines.append(f"📋 <b>Этапы ({len(project.stages)}):</b>")

        main_stages = [s for s in project.stages if not s.is_parallel]
        parallel_stages = [s for s in project.stages if s.is_parallel]

        for stage in main_stages:
            checkpoint = " ✅" if stage.is_checkpoint else ""
            lines.append(f"  {stage.order}. {stage.name}{checkpoint}")

        if parallel_stages:
            lines.append("")
            lines.append("  <b>Параллельные (мебель на заказ):</b>")
            for stage in parallel_stages:
                lines.append(f"  • {stage.name}")

    return "\n".join(lines)


# ── Stage formatting ──────────────────────────────────────────


def format_stage_detail(stage: Stage) -> str:
    """Format a single stage's details with HTML markup."""
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
    """Format a compact overview of all stages with HTML markup."""
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


# ── Launch formatting ─────────────────────────────────────────


def format_launch_summary(project: Project) -> str:
    """Format a complete project summary for the launch confirmation screen."""
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


# ── Team formatting ───────────────────────────────────────────


def format_team_list(
    members: list[tuple[str, list[RoleType], bool]],
) -> str:
    """
    Format the project team with HTML markup.

    Args:
        members: list of (full_name, [roles], is_bot_started)
    """
    lines: list[str] = ["👥 <b>Команда проекта:</b>", ""]
    for name, roles, started in members:
        role_text = format_role_list(roles)
        status = "" if started else " ⚠️ (не запустил бота)"
        lines.append(f"• <b>{name}</b> — {role_text}{status}")
    return "\n".join(lines)
