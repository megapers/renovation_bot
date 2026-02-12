"""
Telegram notification handlers — checkpoint approval, notification delivery.

Callback handlers for inline keyboard actions related to checkpoints
and stage status updates. Also provides the function to deliver
Notification objects via Telegram.
"""

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery

from bot.adapters.telegram.formatters import format_stage_detail
from bot.adapters.telegram.keyboards import (
    back_to_stage_keyboard,
    checkpoint_keyboard,
    stage_actions_keyboard,
    stages_list_keyboard,
)
from bot.core.notification_service import (
    Notification,
    NotificationType,
    build_checkpoint_reached,
)
from bot.core.stage_service import get_checkpoint_description
from bot.db import repositories as repo
from bot.db.models import RoleType, StageStatus
from bot.db.session import get_session

logger = logging.getLogger(__name__)

router = Router(name="notification")


# ── Checkpoint approval / rejection ──────────────────────────


@router.callback_query(F.data.startswith("chkpt:"))
async def on_checkpoint_action(callback: CallbackQuery) -> None:
    """
    Handle checkpoint approval or rejection.

    Callback data format: chkpt:{action}:{stage_id}
    Actions: approve, reject
    """
    await callback.answer()

    parts = callback.data.split(":")
    if len(parts) != 3:
        return

    action = parts[1]
    stage_id = int(parts[2])

    user = callback.message_data.get("db_user") if hasattr(callback, "message_data") else None

    async with get_session() as session:
        stage = await repo.get_stage_with_substages(session, stage_id)
        if not stage:
            await callback.message.edit_text("❌ Этап не найден.")
            return

        # Check that user is owner
        user_roles = []
        if callback.from_user:
            db_user = await repo.get_user_by_telegram_id(session, callback.from_user.id)
            if db_user:
                user_roles = await repo.get_user_roles_in_project(
                    session, db_user.id, stage.project_id
                )

        if RoleType.OWNER not in user_roles:
            await callback.message.edit_text(
                "❌ Только владелец проекта может одобрить контрольную точку."
            )
            return

        project = await repo.get_project_with_stages(session, stage.project_id)

        if action == "approve":
            # Move next stage to IN_PROGRESS
            next_stage = await repo.get_next_stage(session, stage)
            response_lines = [
                f"✅ Контрольная точка «{stage.name}» одобрена!",
            ]
            if next_stage:
                next_stage.status = StageStatus.IN_PROGRESS
                await session.flush()
                response_lines.append(
                    f"\n🔨 Следующий этап «{next_stage.name}» переведён в работу."
                )
            else:
                response_lines.append("\nВсе этапы завершены! 🎉")

            await callback.message.edit_text(
                "\n".join(response_lines),
                parse_mode="HTML",
            )
            await session.commit()

        elif action == "reject":
            # Mark stage as delayed, request rework
            stage.status = StageStatus.DELAYED
            await session.flush()
            await callback.message.edit_text(
                f"❌ Контрольная точка «{stage.name}» отклонена.\n\n"
                "Этап возвращён в статус «Задержка» для доработки.\n"
                "Ответственный будет уведомлён.",
                parse_mode="HTML",
            )
            await session.commit()


# ── Stage completion with checkpoint check ───────────────────


@router.callback_query(F.data.startswith("stgcomplete:"))
async def on_stage_complete(callback: CallbackQuery) -> None:
    """
    Mark a stage as completed. If it's a checkpoint, request approval.

    Callback data format: stgcomplete:{stage_id}
    """
    await callback.answer()

    stage_id = int(callback.data.split(":")[1])

    async with get_session() as session:
        stage = await repo.get_stage_with_substages(session, stage_id)
        if not stage:
            await callback.message.edit_text("❌ Этап не найден.")
            return

        # Mark stage as completed
        stage.status = StageStatus.COMPLETED
        await session.flush()

        project = await repo.get_project_with_stages(session, stage.project_id)

        if stage.is_checkpoint:
            # Checkpoint reached — ask owner for approval
            desc = get_checkpoint_description(stage.name)
            text = (
                f"🔒 <b>Контрольная точка: {stage.name}</b>\n\n"
                f"Этап «{stage.name}» завершён.\n\n"
                f"📋 {desc}\n\n"
                "Рекомендуется вызвать эксперта для проверки качества.\n\n"
                "Одобрить переход к следующему этапу?"
            )
            await callback.message.edit_text(
                text,
                reply_markup=checkpoint_keyboard(stage_id),
                parse_mode="HTML",
            )
        else:
            # No checkpoint — auto-advance to next stage
            next_stage = await repo.get_next_stage(session, stage)
            if next_stage:
                next_stage.status = StageStatus.IN_PROGRESS
                await session.flush()
                await callback.message.edit_text(
                    f"✅ Этап «{stage.name}» завершён!\n"
                    f"🔨 Следующий этап «{next_stage.name}» переведён в работу.",
                    parse_mode="HTML",
                )
            else:
                await callback.message.edit_text(
                    f"✅ Этап «{stage.name}» завершён!\n"
                    "🎉 Все этапы проекта завершены!",
                    parse_mode="HTML",
                )

        await session.commit()


# ── Stage status change (from stage detail) ──────────────────


@router.callback_query(F.data.startswith("stgsts:"))
async def on_stage_status_change(callback: CallbackQuery) -> None:
    """
    Change a stage's status.

    Callback data format: stgsts:{status}:{stage_id}
    """
    await callback.answer()

    parts = callback.data.split(":")
    if len(parts) != 3:
        return

    new_status_str = parts[1]
    stage_id = int(parts[2])

    try:
        new_status = StageStatus(new_status_str)
    except ValueError:
        return

    async with get_session() as session:
        stage = await repo.update_stage(session, stage_id, status=new_status)
        if not stage:
            await callback.message.edit_text("❌ Этап не найден.")
            return

        # If marking as completed, check for checkpoint
        if new_status == StageStatus.COMPLETED and stage.is_checkpoint:
            desc = get_checkpoint_description(stage.name)
            text = (
                f"🔒 <b>Контрольная точка: {stage.name}</b>\n\n"
                f"Этап «{stage.name}» завершён.\n\n"
                f"📋 {desc}\n\n"
                "Одобрить переход к следующему этапу?"
            )
            await callback.message.edit_text(
                text,
                reply_markup=checkpoint_keyboard(stage_id),
                parse_mode="HTML",
            )
        elif new_status == StageStatus.COMPLETED:
            next_stage = await repo.get_next_stage(session, stage)
            if next_stage:
                next_stage.status = StageStatus.IN_PROGRESS
                await session.flush()

            # Reload stage for display
            stage = await repo.get_stage_with_substages(session, stage_id)
            text = format_stage_detail(stage)
            if next_stage:
                text += f"\n\n🔨 Следующий этап «{next_stage.name}» переведён в работу."
            await callback.message.edit_text(
                text,
                reply_markup=stage_actions_keyboard(stage_id),
                parse_mode="HTML",
            )
        else:
            # Just update the display
            stage = await repo.get_stage_with_substages(session, stage_id)
            await callback.message.edit_text(
                format_stage_detail(stage),
                reply_markup=stage_actions_keyboard(stage_id),
                parse_mode="HTML",
            )

        await session.commit()


# ── Notification delivery via Telegram ───────────────────────


async def deliver_notification(
    notification: Notification,
    bot,  # aiogram Bot instance
) -> None:
    """
    Deliver a Notification object to all recipients via Telegram.

    Resolves user IDs to Telegram IDs and sends the message.
    """
    async with get_session() as session:
        for user_id in notification.recipient_user_ids:
            user = await repo.get_user_by_id(session, user_id)
            if not user or not user.telegram_id:
                logger.debug(
                    "Cannot deliver notification to user_id=%d: no Telegram ID",
                    user_id,
                )
                continue

            if not user.is_bot_started:
                logger.debug(
                    "User %s (id=%d) hasn't started the bot, skipping",
                    user.full_name, user_id,
                )
                continue

            try:
                # Format the notification with optional inline keyboard
                reply_markup = None
                if notification.notification_type == NotificationType.CHECKPOINT_REACHED:
                    reply_markup = checkpoint_keyboard(notification.stage_id)

                await bot.send_message(
                    chat_id=user.telegram_id,
                    text=f"🔔 <b>{notification.title}</b>\n\n{notification.body}",
                    parse_mode="HTML",
                    reply_markup=reply_markup,
                )
                logger.debug(
                    "Sent %s notification to user %s",
                    notification.notification_type.value,
                    user.full_name,
                )
            except Exception:
                logger.exception(
                    "Failed to send notification to user %s (tg_id=%d)",
                    user.full_name, user.telegram_id,
                )
