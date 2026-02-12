"""
Core notification service — platform-agnostic.

Defines notification types, builds notification content, and determines
who should receive each notification based on project roles.

This module never imports platform-specific code. Platform adapters
subscribe to notifications and translate them into actual messages.
"""

import enum
import logging
from dataclasses import dataclass, field
from datetime import datetime

from bot.db.models import RoleType

logger = logging.getLogger(__name__)


class NotificationType(str, enum.Enum):
    """Types of notifications the system can generate."""

    # Deadline-related
    DEADLINE_APPROACHING = "deadline_approaching"       # 1 day before stage end_date
    DEADLINE_OVERDUE = "deadline_overdue"               # Stage end_date has passed
    STAGE_STARTING_SOON = "stage_starting_soon"         # 1 day before stage start_date

    # Status prompts
    STATUS_UPDATE_REQUEST = "status_update_request"     # Ask responsible person for status

    # Checkpoints
    CHECKPOINT_REACHED = "checkpoint_reached"           # Stage completed, checkpoint approval needed
    CHECKPOINT_APPROVED = "checkpoint_approved"         # Owner approved checkpoint
    CHECKPOINT_REJECTED = "checkpoint_rejected"         # Owner rejected checkpoint

    # Furniture / parallel stages
    FURNITURE_ORDER_REMINDER = "furniture_order_reminder"  # 30-45 days before installation

    # Budget
    OVERSPENDING_ALERT = "overspending_alert"           # Stage or total budget exceeded
    BUDGET_WARNING = "budget_warning"                   # Approaching budget limit (90%+)

    # Reports
    WEEKLY_REPORT = "weekly_report"                     # Automated weekly report to owners


@dataclass
class Notification:
    """
    Platform-agnostic notification ready to be sent.

    The notification service creates these. Platform adapters consume
    them and send actual messages via Telegram/WhatsApp/etc.
    """

    notification_type: NotificationType
    project_id: int
    project_name: str
    title: str                          # short summary (e.g. "Deadline approaching")
    body: str                           # full message text (plain text, no HTML)
    recipient_user_ids: list[int]       # internal user IDs to notify
    stage_id: int | None = None
    stage_name: str | None = None
    extra_data: dict = field(default_factory=dict)  # flexible payload
    created_at: datetime = field(default_factory=lambda: datetime.now().astimezone())


# ── Notification builders ────────────────────────────────────
# Each function creates a Notification from project/stage data.
# They return plain text — formatting is the adapter's job.


def build_deadline_approaching(
    project_id: int,
    project_name: str,
    stage_id: int,
    stage_name: str,
    end_date: datetime,
    responsible_contact: str | None,
    recipient_ids: list[int],
) -> Notification:
    """Build a 'deadline approaching' notification (1 day before end_date)."""
    date_str = end_date.strftime("%d.%m.%Y")
    body = (
        f"Этап «{stage_name}» проекта «{project_name}» "
        f"завершается завтра ({date_str})."
    )
    if responsible_contact:
        body += f"\nОтветственный: {responsible_contact}"

    return Notification(
        notification_type=NotificationType.DEADLINE_APPROACHING,
        project_id=project_id,
        project_name=project_name,
        title=f"Срок завершения: {stage_name}",
        body=body,
        recipient_user_ids=recipient_ids,
        stage_id=stage_id,
        stage_name=stage_name,
        extra_data={"end_date": date_str},
    )


def build_deadline_overdue(
    project_id: int,
    project_name: str,
    stage_id: int,
    stage_name: str,
    end_date: datetime,
    days_overdue: int,
    responsible_contact: str | None,
    recipient_ids: list[int],
) -> Notification:
    """Build an 'overdue' alert for a stage past its end_date."""
    date_str = end_date.strftime("%d.%m.%Y")
    body = (
        f"Этап «{stage_name}» проекта «{project_name}» просрочен!\n"
        f"Дедлайн был: {date_str} (просрочка: {days_overdue} дн.)"
    )
    if responsible_contact:
        body += f"\nОтветственный: {responsible_contact}"

    return Notification(
        notification_type=NotificationType.DEADLINE_OVERDUE,
        project_id=project_id,
        project_name=project_name,
        title=f"Просрочка: {stage_name}",
        body=body,
        recipient_user_ids=recipient_ids,
        stage_id=stage_id,
        stage_name=stage_name,
        extra_data={"end_date": date_str, "days_overdue": days_overdue},
    )


def build_status_update_request(
    project_id: int,
    project_name: str,
    stage_id: int,
    stage_name: str,
    recipient_ids: list[int],
) -> Notification:
    """Build a request for status update from the responsible person."""
    body = (
        f"Как продвигается этап «{stage_name}» проекта «{project_name}»?\n"
        "Пожалуйста, обновите статус работ."
    )

    return Notification(
        notification_type=NotificationType.STATUS_UPDATE_REQUEST,
        project_id=project_id,
        project_name=project_name,
        title=f"Запрос статуса: {stage_name}",
        body=body,
        recipient_user_ids=recipient_ids,
        stage_id=stage_id,
        stage_name=stage_name,
    )


def build_checkpoint_reached(
    project_id: int,
    project_name: str,
    stage_id: int,
    stage_name: str,
    owner_ids: list[int],
) -> Notification:
    """Build a checkpoint notification asking the owner for approval."""
    body = (
        f"Этап «{stage_name}» проекта «{project_name}» завершён.\n"
        "Это контрольная точка — требуется ваше одобрение "
        "перед переходом к следующему этапу.\n\n"
        "Рекомендуется вызвать эксперта для проверки качества."
    )

    return Notification(
        notification_type=NotificationType.CHECKPOINT_REACHED,
        project_id=project_id,
        project_name=project_name,
        title=f"Контрольная точка: {stage_name}",
        body=body,
        recipient_user_ids=owner_ids,
        stage_id=stage_id,
        stage_name=stage_name,
    )


def build_furniture_order_reminder(
    project_id: int,
    project_name: str,
    stage_id: int,
    stage_name: str,
    installation_date: datetime,
    days_until: int,
    recipient_ids: list[int],
) -> Notification:
    """Build a reminder to order custom furniture 30-45 days before installation."""
    date_str = installation_date.strftime("%d.%m.%Y")
    body = (
        f"Напоминание: этап «{stage_name}» проекта «{project_name}».\n"
        f"До монтажа мебели осталось {days_until} дн. (дата: {date_str}).\n"
        "Убедитесь, что заказ размещён и производство запущено."
    )

    return Notification(
        notification_type=NotificationType.FURNITURE_ORDER_REMINDER,
        project_id=project_id,
        project_name=project_name,
        title=f"Заказ мебели: {stage_name}",
        body=body,
        recipient_user_ids=recipient_ids,
        stage_id=stage_id,
        stage_name=stage_name,
        extra_data={"installation_date": date_str, "days_until": days_until},
    )


def build_overspending_alert(
    project_id: int,
    project_name: str,
    current_total: float,
    budget_limit: float,
    overspend_pct: float,
    owner_ids: list[int],
    stage_id: int | None = None,
    stage_name: str | None = None,
) -> Notification:
    """Build an overspending alert when budget is exceeded."""
    if stage_name:
        body = (
            f"Бюджет этапа «{stage_name}» проекта «{project_name}» превышен!\n"
            f"Текущие расходы: {current_total:,.0f} ₸ / "
            f"Бюджет: {budget_limit:,.0f} ₸ "
            f"(+{overspend_pct:.0f}%)"
        )
        title = f"Превышение бюджета: {stage_name}"
    else:
        body = (
            f"Общий бюджет проекта «{project_name}» превышен!\n"
            f"Текущие расходы: {current_total:,.0f} ₸ / "
            f"Бюджет: {budget_limit:,.0f} ₸ "
            f"(+{overspend_pct:.0f}%)"
        )
        title = f"Превышение бюджета: {project_name}"

    return Notification(
        notification_type=NotificationType.OVERSPENDING_ALERT,
        project_id=project_id,
        project_name=project_name,
        title=title,
        body=body,
        recipient_user_ids=owner_ids,
        stage_id=stage_id,
        stage_name=stage_name,
        extra_data={
            "current_total": current_total,
            "budget_limit": budget_limit,
            "overspend_pct": overspend_pct,
        },
    )


def build_budget_warning(
    project_id: int,
    project_name: str,
    current_total: float,
    budget_limit: float,
    usage_pct: float,
    owner_ids: list[int],
) -> Notification:
    """Build a warning when budget usage reaches 90%."""
    body = (
        f"Бюджет проекта «{project_name}» использован на {usage_pct:.0f}%.\n"
        f"Расходы: {current_total:,.0f} ₸ / Бюджет: {budget_limit:,.0f} ₸"
    )

    return Notification(
        notification_type=NotificationType.BUDGET_WARNING,
        project_id=project_id,
        project_name=project_name,
        title=f"Бюджет на исходе: {project_name}",
        body=body,
        recipient_user_ids=owner_ids,
        extra_data={
            "current_total": current_total,
            "budget_limit": budget_limit,
            "usage_pct": usage_pct,
        },
    )


# ── Role-based recipient resolution ─────────────────────────

def build_weekly_report_notification(
    project_id: int,
    project_name: str,
    report_text: str,
    owner_ids: list[int],
) -> Notification:
    """Build a weekly report notification for project owners."""
    return Notification(
        notification_type=NotificationType.WEEKLY_REPORT,
        project_id=project_id,
        project_name=project_name,
        title=f"Еженедельный отчёт: {project_name}",
        body=report_text,
        recipient_user_ids=owner_ids,
        extra_data={"is_html": True},
    )


# Which roles receive which notification types
NOTIFICATION_RECIPIENTS: dict[NotificationType, list[RoleType]] = {
    NotificationType.DEADLINE_APPROACHING: [
        RoleType.OWNER, RoleType.CO_OWNER, RoleType.FOREMAN,
    ],
    NotificationType.DEADLINE_OVERDUE: [
        RoleType.OWNER, RoleType.CO_OWNER, RoleType.FOREMAN,
    ],
    NotificationType.STAGE_STARTING_SOON: [
        RoleType.OWNER, RoleType.FOREMAN,
    ],
    NotificationType.STATUS_UPDATE_REQUEST: [
        # Sent to the responsible person (tradesperson/foreman)
        # Recipient is determined dynamically, not by role
    ],
    NotificationType.CHECKPOINT_REACHED: [
        RoleType.OWNER, RoleType.CO_OWNER,
    ],
    NotificationType.CHECKPOINT_APPROVED: [
        RoleType.OWNER, RoleType.FOREMAN, RoleType.CO_OWNER,
    ],
    NotificationType.CHECKPOINT_REJECTED: [
        RoleType.OWNER, RoleType.FOREMAN, RoleType.CO_OWNER,
    ],
    NotificationType.FURNITURE_ORDER_REMINDER: [
        RoleType.OWNER, RoleType.CO_OWNER, RoleType.FOREMAN, RoleType.DESIGNER,
    ],
    NotificationType.OVERSPENDING_ALERT: [
        RoleType.OWNER, RoleType.CO_OWNER,
    ],
    NotificationType.BUDGET_WARNING: [
        RoleType.OWNER, RoleType.CO_OWNER,
    ],
    NotificationType.WEEKLY_REPORT: [
        RoleType.OWNER, RoleType.CO_OWNER,
    ],
}
