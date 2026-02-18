"""
Unified project resolution for all Telegram handlers.

This module provides a single `resolve_project()` function that every
command handler uses to determine which project the user is working with.

Resolution logic:
  1. **Group chat**: look up the project linked to this chat via
     `get_project_by_telegram_chat_id`. If found → return immediately.
     If not linked → tell the user to run /link.
  2. **Private chat, 1 project**: auto-return that project.
  3. **Private chat, N projects**: show a project picker keyboard and
     store the `intent` in FSM so the callback can dispatch correctly.
  4. **No projects**: prompt the user to create one with /newproject.
"""

import logging
from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.adapters.telegram.keyboards import project_select_keyboard
from bot.db.repositories import (
    get_project_by_telegram_chat_id,
    get_user_by_telegram_id,
    get_user_projects,
)
from bot.db.session import async_session_factory

logger = logging.getLogger(__name__)


class ResolvedProject:
    """Result of project resolution — holds project and user info."""

    __slots__ = ("project", "user_id")

    def __init__(self, project: Any, user_id: int) -> None:
        self.project = project
        self.user_id = user_id

    @property
    def id(self) -> int:
        return self.project.id


async def resolve_project(
    event: Message | CallbackQuery,
    state: FSMContext,
    *,
    intent: str,
    picker_state: Any,
    tenant_id: int | None = None,
    no_project_msg: str = (
        "У вас нет активных проектов.\n"
        "Создайте проект командой /newproject"
    ),
) -> ResolvedProject | None:
    """
    Resolve the active project for the current user/chat.

    Parameters
    ----------
    event : Message | CallbackQuery
        The incoming Telegram event.
    state : FSMContext
        aiogram FSM context — used to store picker intent.
    intent : str
        An identifier for the caller, e.g. "stages", "budget", "report".
        Stored in FSM data so the picker callback knows who to dispatch to.
    picker_state : State
        The FSM state to enter when showing the project picker.
    no_project_msg : str
        Message to show when the user has zero projects.

    Returns
    -------
    ResolvedProject | None
        The resolved project wrapper, or None if a picker was shown
        (callback will arrive separately) or the user has no projects.
    """
    # Determine chat + target message for replying
    if isinstance(event, CallbackQuery):
        message = event.message
        tg_user = event.from_user
        chat = message.chat if message else None
    else:
        message = event
        tg_user = event.from_user
        chat = event.chat

    if tg_user is None or chat is None or message is None:
        return None

    # ── Look up internal user ──
    async with async_session_factory() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if user is None:
            await message.answer(  # type: ignore[union-attr]
                "❌ Вы не зарегистрированы. Отправьте /start сначала."
            )
            return None

        # ── Group chat: auto-resolve to linked project ──
        if chat.type in ("group", "supergroup"):
            project = await get_project_by_telegram_chat_id(session, chat.id)
            if project:
                return ResolvedProject(project, user.id)

            # Group not linked to any project
            await message.answer(  # type: ignore[union-attr]
                "❌ Эта группа не привязана к проекту.\n"
                "Используйте /link чтобы привязать группу к проекту."
            )
            return None

        # ── Private chat ──
        projects = await get_user_projects(session, user.id, tenant_id=tenant_id)

    if not projects:
        await message.answer(no_project_msg)  # type: ignore[union-attr]
        return None

    if len(projects) == 1:
        return ResolvedProject(projects[0], user.id)

    # Multiple projects → show picker
    await state.set_state(picker_state)
    await state.update_data(intent=intent, resolver_user_id=user.id)
    await message.answer(  # type: ignore[union-attr]
        "Выберите проект:",
        reply_markup=project_select_keyboard(projects),
    )
    return None
