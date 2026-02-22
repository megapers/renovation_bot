"""
Scheduler — runs periodic monitoring jobs.

Uses APScheduler to run background tasks that check deadlines,
send reminders, and detect budget overruns. This module is
platform-agnostic — it produces Notification objects and hands
them to a callback for delivery.

The platform adapter is responsible for:
  1. Calling `start_scheduler()` when the bot starts
  2. Providing a `send_notification` callback
  3. Calling `stop_scheduler()` on shutdown
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from bot.core.notification_service import (
    Notification,
    build_deadline_approaching,
    build_deadline_overdue,
    build_furniture_order_reminder,
    build_overspending_alert,
    build_status_update_request,
    build_weekly_report_notification,
)
from bot.db import repositories as repo
from bot.db.models import RoleType, StageStatus
from bot.db.session import async_session_factory, get_session

logger = logging.getLogger(__name__)

# Type alias for the callback that actually sends notifications
NotificationSender = Callable[[Notification], Awaitable[None]]

# Module-level scheduler instance
_scheduler: AsyncIOScheduler | None = None
_send_notification: NotificationSender | None = None


async def _check_deadlines() -> None:
    """Check for stages approaching deadline (within 1 day)."""
    if not _send_notification:
        return

    try:
        async with get_session() as session:
            stages = await repo.get_stages_due_soon(session, within_days=1)
            for stage in stages:
                project = stage.project
                owner_ids = await repo.get_project_owner_ids(session, project.id)
                recipient_ids = list(set(owner_ids))
                if stage.responsible_user_id:
                    recipient_ids.append(stage.responsible_user_id)
                    recipient_ids = list(set(recipient_ids))

                notification = build_deadline_approaching(
                    project_id=project.id,
                    project_name=project.name,
                    stage_id=stage.id,
                    stage_name=stage.name,
                    end_date=stage.end_date,
                    responsible_contact=stage.responsible_contact,
                    recipient_ids=recipient_ids,
                )
                await _send_notification(notification)

            logger.info("Deadline check: %d stages approaching deadline", len(stages))
    except Exception:
        logger.exception("Error in deadline check job")


async def _check_overdue() -> None:
    """Check for overdue stages."""
    if not _send_notification:
        return

    try:
        async with get_session() as session:
            stages = await repo.get_overdue_stages(session)
            for stage in stages:
                project = stage.project
                now = datetime.now().astimezone()
                days_overdue = (now - stage.end_date).days

                owner_ids = await repo.get_project_owner_ids(session, project.id)
                recipient_ids = list(set(owner_ids))
                if stage.responsible_user_id:
                    recipient_ids.append(stage.responsible_user_id)
                    recipient_ids = list(set(recipient_ids))

                notification = build_deadline_overdue(
                    project_id=project.id,
                    project_name=project.name,
                    stage_id=stage.id,
                    stage_name=stage.name,
                    end_date=stage.end_date,
                    days_overdue=days_overdue,
                    responsible_contact=stage.responsible_contact,
                    recipient_ids=recipient_ids,
                )
                await _send_notification(notification)

            logger.info("Overdue check: %d stages overdue", len(stages))
    except Exception:
        logger.exception("Error in overdue check job")


async def _check_status_updates() -> None:
    """Prompt responsible parties for status updates on idle stages."""
    if not _send_notification:
        return

    try:
        async with get_session() as session:
            stages = await repo.get_stages_needing_status_update(session, idle_days=3)
            for stage in stages:
                project = stage.project
                recipient_ids = []
                if stage.responsible_user_id:
                    recipient_ids.append(stage.responsible_user_id)
                if not recipient_ids:
                    continue

                notification = build_status_update_request(
                    project_id=project.id,
                    project_name=project.name,
                    stage_id=stage.id,
                    stage_name=stage.name,
                    recipient_ids=recipient_ids,
                )
                await _send_notification(notification)

            logger.info("Status update check: %d stages prompted", len(stages))
    except Exception:
        logger.exception("Error in status update check job")


async def _check_furniture_reminders() -> None:
    """Remind about custom furniture orders 30-45 days before installation."""
    if not _send_notification:
        return

    try:
        async with get_session() as session:
            stages = await repo.get_parallel_stages_with_upcoming_installation(
                session, within_days=45
            )
            for stage in stages:
                project = stage.project
                # Find the installation sub-stage date
                install_date = None
                for sub in stage.sub_stages:
                    if "монтаж" in sub.name.lower() or "установка" in sub.name.lower():
                        install_date = sub.start_date
                        break

                if not install_date:
                    continue

                days_until = (install_date - datetime.now().astimezone()).days
                owner_ids = await repo.get_project_owner_ids(session, project.id)
                recipient_ids = await repo.get_project_role_user_ids(
                    session, project.id,
                    [RoleType.OWNER, RoleType.CO_OWNER, RoleType.FOREMAN, RoleType.DESIGNER],
                )
                recipient_ids = list(set(recipient_ids))

                notification = build_furniture_order_reminder(
                    project_id=project.id,
                    project_name=project.name,
                    stage_id=stage.id,
                    stage_name=stage.name,
                    installation_date=install_date,
                    days_until=days_until,
                    recipient_ids=recipient_ids,
                )
                await _send_notification(notification)

            logger.info("Furniture reminder check: %d stages", len(stages))
    except Exception:
        logger.exception("Error in furniture reminder check job")


async def _check_overspending() -> None:
    """Check for budget overruns across all active projects."""
    if not _send_notification:
        return

    try:
        async with get_session() as session:
            projects = await repo.get_all_active_projects(session)
            alerts_sent = 0
            for project in projects:
                if not project.total_budget or float(project.total_budget) <= 0:
                    continue

                summary = await repo.get_project_budget_summary(session, project.id)
                total_spent = summary["total_spent"]
                budget = float(project.total_budget)

                if total_spent <= 0:
                    continue

                owner_ids = await repo.get_project_owner_ids(session, project.id)

                if total_spent > budget:
                    overspend_pct = ((total_spent - budget) / budget) * 100
                    notification = build_overspending_alert(
                        project_id=project.id,
                        project_name=project.name,
                        current_total=total_spent,
                        budget_limit=budget,
                        overspend_pct=overspend_pct,
                        owner_ids=owner_ids,
                    )
                    await _send_notification(notification)
                    alerts_sent += 1

            logger.info("Overspending check: %d alerts sent", alerts_sent)
    except Exception:
        logger.exception("Error in overspending check job")


async def _send_weekly_reports() -> None:
    """Generate and send weekly reports to project owners."""
    if not _send_notification:
        return

    try:
        from bot.adapters.telegram.formatters import format_weekly_report
        from bot.core.report_service import build_weekly_report

        async with get_session() as session:
            projects = await repo.get_all_active_projects(session)
            reports_sent = 0

            for project in projects:
                owner_ids = await repo.get_project_owner_ids(session, project.id)
                if not owner_ids:
                    continue

                stages = list(
                    await repo.get_stages_for_project(session, project.id)
                )
                budget_summary = await repo.get_project_budget_summary(
                    session, project.id
                )
                cat_summaries = await repo.get_budget_summary_by_category(
                    session, project.id
                )

                total_budget = (
                    float(project.total_budget)
                    if project.total_budget
                    else None
                )

                report_data = await build_weekly_report(
                    project_id=project.id,
                    project_name=project.name,
                    total_budget=total_budget,
                    stages=stages,
                    budget_summary=budget_summary,
                    category_summaries=cat_summaries,
                )

                report_text = format_weekly_report(report_data)

                notification = build_weekly_report_notification(
                    project_id=project.id,
                    project_name=project.name,
                    report_text=report_text,
                    owner_ids=owner_ids,
                )
                await _send_notification(notification)
                reports_sent += 1

            logger.info("Weekly reports sent: %d", reports_sent)
    except Exception:
        logger.exception("Error in weekly report job")


def start_scheduler(send_notification: NotificationSender) -> AsyncIOScheduler:
    """
    Create and start the background scheduler.

    Args:
        send_notification: async callback to deliver notifications.
            The adapter provides this — it maps Notification → actual messages.
    """
    global _scheduler, _send_notification
    _send_notification = send_notification

    _scheduler = AsyncIOScheduler()

    # ── Register jobs ────────────────────────────────────────

    # Deadline approaching — check every hour
    _scheduler.add_job(
        _check_deadlines,
        "interval",
        hours=1,
        id="check_deadlines",
        name="Check approaching deadlines",
        replace_existing=True,
    )

    # Overdue stages — check every 2 hours
    _scheduler.add_job(
        _check_overdue,
        "interval",
        hours=2,
        id="check_overdue",
        name="Check overdue stages",
        replace_existing=True,
    )

    # Status update prompts — check every 6 hours
    _scheduler.add_job(
        _check_status_updates,
        "interval",
        hours=6,
        id="check_status_updates",
        name="Request status updates",
        replace_existing=True,
    )

    # Furniture order reminders — check daily
    _scheduler.add_job(
        _check_furniture_reminders,
        "interval",
        hours=24,
        id="check_furniture_reminders",
        name="Furniture order reminders",
        replace_existing=True,
    )

    # Overspending alerts — check every 4 hours
    _scheduler.add_job(
        _check_overspending,
        "interval",
        hours=4,
        id="check_overspending",
        name="Check budget overspending",
        replace_existing=True,
    )

    # Weekly reports — every Monday at 09:00
    _scheduler.add_job(
        _send_weekly_reports,
        "cron",
        day_of_week="mon",
        hour=9,
        minute=0,
        id="send_weekly_reports",
        name="Send weekly reports to owners",
        replace_existing=True,
    )

    # Cache maintenance — cleanup expired entries + refresh views every 60s
    _scheduler.add_job(
        _cache_maintenance,
        "interval",
        seconds=60,
        id="cache_maintenance",
        name="Cache cleanup and view refresh",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info("Scheduler started with %d jobs", len(_scheduler.get_jobs()))
    return _scheduler


def stop_scheduler() -> None:
    """Shut down the scheduler gracefully."""
    global _scheduler
    if _scheduler and _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
    _scheduler = None


async def _cache_maintenance() -> None:
    """Periodic cache cleanup and materialized view refresh."""
    try:
        from bot.services.pg_cache import pg_cache_cleanup, refresh_views
        async with async_session_factory() as session:
            await pg_cache_cleanup(session)
            await refresh_views(session)
            await session.commit()
    except Exception as e:
        logger.debug("Cache maintenance: %s", e)
