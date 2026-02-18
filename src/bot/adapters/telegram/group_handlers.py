"""
Telegram handlers for group chat integration.

Handles:
  - Bot being added to a group chat
  - /link command to link a group chat to a project
  - Auto-registering group members when they send /start

When the bot is added to a Telegram group, it can be linked to a
specific renovation project. All subsequent messages in that group
are associated with the linked project.
"""

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, ChatMemberUpdatedFilter, IS_MEMBER, IS_NOT_MEMBER
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message

from bot.adapters.telegram.keyboards import project_select_keyboard
from bot.db.repositories import (
    get_project_by_telegram_chat_id,
    get_project_with_stages,
    get_user_by_telegram_id,
    get_user_projects,
    link_project_to_chat,
)
from bot.db.session import async_session_factory

logger = logging.getLogger(__name__)
router = Router(name="group_chat")


# ═══════════════════════════════════════════════════════════════
# Bot added/removed from group
# ═══════════════════════════════════════════════════════════════


@router.my_chat_member(
    ChatMemberUpdatedFilter(
        member_status_changed=IS_NOT_MEMBER >> IS_MEMBER
    )
)
async def bot_added_to_group(event: ChatMemberUpdated) -> None:
    """
    Handle the bot being added to a group chat.

    If added via a deep link (?startgroup=proj_N), auto-link to that project.
    Otherwise, send instructions to use /link.
    """
    chat = event.chat
    logger.info(
        "Bot added to group: '%s' (chat_id=%d) by user tg_id=%d",
        chat.title or "—",
        chat.id,
        event.from_user.id,
    )

    await event.answer(
        "👋 <b>Бот подключён к группе!</b>\n\n"
        f"Группа: <b>{chat.title or '—'}</b>\n\n"
        "Чтобы привязать эту группу к проекту ремонта, "
        "отправьте команду /link\n\n"
        "⚠️ Каждый участник должен отправить /start боту "
        "в личном чате, чтобы получать уведомления."
    )


@router.my_chat_member(
    ChatMemberUpdatedFilter(
        member_status_changed=IS_MEMBER >> IS_NOT_MEMBER
    )
)
async def bot_removed_from_group(event: ChatMemberUpdated) -> None:
    """Handle the bot being removed from a group chat."""
    logger.info(
        "Bot removed from group: chat_id=%d by user tg_id=%d",
        event.chat.id,
        event.from_user.id,
    )


# ═══════════════════════════════════════════════════════════════
# Deep link — /start proj_N in group
# ═══════════════════════════════════════════════════════════════

_PROJ_DEEPLINK_RE = re.compile(r"^proj_(\d+)$")


@router.message(
    CommandStart(deep_link=True),
    F.chat.type.in_({"group", "supergroup"}),
)
async def handle_startgroup_deeplink(message: Message) -> None:
    """
    Handle /start with deep link parameter in a group chat.

    When the bot is added to a group via t.me/bot?startgroup=proj_N,
    Telegram sends "/start proj_N" in the group. This handler
    auto-links the group to the project.
    """
    # Extract project ID from deep link
    text = (message.text or "").strip()
    parts = text.split(maxsplit=1)
    if len(parts) < 2:
        return

    payload = parts[1]
    match = _PROJ_DEEPLINK_RE.match(payload)
    if not match:
        return

    project_id = int(match.group(1))
    chat_id = message.chat.id

    async with async_session_factory() as session:
        # Check if already linked
        existing = await get_project_by_telegram_chat_id(session, chat_id)
        if existing:
            await message.answer(
                f"ℹ️ Эта группа уже привязана к проекту "
                f"<b>{existing.name}</b>."
            )
            return

        # Verify the project exists
        project = await get_project_with_stages(session, project_id)
        if project is None:
            await message.answer("❌ Проект не найден.")
            return

        # Link the project
        project = await link_project_to_chat(session, project_id, chat_id)
        await session.commit()

    if project:
        await message.answer(
            f"✅ Группа автоматически привязана к проекту "
            f"<b>{project.name}</b>!\n\n"
            "Теперь бот будет отслеживать сообщения в этой группе "
            "для данного проекта.\n\n"
            "Доступные команды:\n"
            "/stages — этапы ремонта\n"
            "/budget — бюджет\n"
            "/team — команда проекта\n"
            "/status — статус проекта"
        )
        logger.info(
            "Deep link: linked project_id=%d to chat_id=%d",
            project_id, chat_id,
        )
    else:
        await message.answer("❌ Не удалось привязать проект.")


# ═══════════════════════════════════════════════════════════════
# /link — Link group chat to a project
# ═══════════════════════════════════════════════════════════════


@router.message(Command("link"), F.chat.type.in_({"group", "supergroup"}))
async def cmd_link(message: Message, state: FSMContext, **kwargs) -> None:
    """
    Link this group chat to a renovation project.

    Only works in group chats. The user must be a project owner.
    """
    tg_user = message.from_user
    if tg_user is None:
        return

    chat_id = message.chat.id

    async with async_session_factory() as session:
        # Check if already linked
        existing = await get_project_by_telegram_chat_id(session, chat_id)
        if existing:
            await message.answer(
                f"ℹ️ Эта группа уже привязана к проекту "
                f"<b>{existing.name}</b>."
            )
            return

        # Get user's projects
        user = await get_user_by_telegram_id(session, tg_user.id)
        if user is None:
            await message.answer(
                "❌ Вы не зарегистрированы. "
                "Отправьте /start боту в личном чате."
            )
            return

        projects = await get_user_projects(session, user.id, tenant_id=kwargs.get("tenant_id"))

    if not projects:
        await message.answer("У вас нет проектов для привязки.")
        return

    # Filter to projects not already linked to another chat
    unlinked = [p for p in projects if p.telegram_chat_id is None]

    if not unlinked:
        await message.answer(
            "Все ваши проекты уже привязаны к группам.\n"
            "Отвяжите проект из другой группы, чтобы привязать здесь."
        )
        return

    if len(unlinked) == 1:
        # Auto-link the only available project
        await _link_project(message, unlinked[0].id, chat_id)
    else:
        # Store chat_id in FSM for the callback
        await state.update_data(link_chat_id=chat_id)
        await message.answer(
            "Выберите проект для привязки к этой группе:",
            reply_markup=project_select_keyboard(unlinked),
        )


@router.callback_query(F.data.startswith("prjsel:"), F.message.chat.type.in_({"group", "supergroup"}))
async def link_project_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Handle project selection for /link in a group chat."""
    await callback.answer()
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    data = await state.get_data()
    chat_id = data.get("link_chat_id", callback.message.chat.id)  # type: ignore[union-attr]

    await _link_project(
        callback.message,  # type: ignore[arg-type]
        project_id,
        chat_id,
    )
    await state.clear()


async def _link_project(target: Message, project_id: int, chat_id: int) -> None:
    """Execute the project ↔ group link."""
    async with async_session_factory() as session:
        project = await link_project_to_chat(session, project_id, chat_id)
        await session.commit()

    if project:
        await target.answer(
            f"✅ Группа привязана к проекту <b>{project.name}</b>!\n\n"
            "Теперь бот будет отслеживать сообщения в этой группе "
            "для данного проекта.\n\n"
            "Доступные команды:\n"
            "/stages — этапы ремонта\n"
            "/team — команда проекта\n"
            "/myrole — ваша роль"
        )
        logger.info("Linked project_id=%d to chat_id=%d", project_id, chat_id)
    else:
        await target.answer("❌ Не удалось привязать проект.")
