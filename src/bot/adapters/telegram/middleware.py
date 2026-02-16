"""
Telegram middleware for role-based access control.

This middleware runs before every handler and injects:
  - `user`       — the User ORM object (or None)
  - `project`    — the Project linked to this chat (or None, for group chats)
  - `user_roles` — list of RoleType the user has in the project

It also handles the /start-requirement check: if a user hasn't started
the bot yet and tries to interact, they get a prompt.

Usage in handlers:
    @router.message(Command("stages"))
    async def cmd_stages(message: Message, user: User, project: Project | None, user_roles: list[RoleType]):
        ...

To require specific permissions, use the `require_permission` filter.
"""

import logging
from typing import Any, Callable, Awaitable

from aiogram import BaseMiddleware
from aiogram.types import Message, CallbackQuery, TelegramObject

from bot.db.models import User, Project, RoleType
from bot.db.repositories import (
    get_user_by_telegram_id,
    get_project_by_telegram_chat_id,
    get_user_roles_in_project,
)
from bot.db.session import async_session_factory

logger = logging.getLogger(__name__)


class RoleMiddleware(BaseMiddleware):
    """
    Injects user, project, and role context into every handler.

    For private chats: user is loaded, project is None (unless FSM has project_id).
    For group chats: user is loaded, project is looked up via telegram_chat_id.
    """

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Extract the Telegram user and chat
        tg_user = None
        chat_id = None

        if isinstance(event, Message):
            tg_user = event.from_user
            chat_id = event.chat.id
        elif isinstance(event, CallbackQuery):
            tg_user = event.from_user
            if event.message:
                chat_id = event.message.chat.id

        if tg_user is None:
            # Can't identify user — pass through (e.g. channel posts)
            data["user"] = None
            data["project"] = None
            data["user_roles"] = []
            return await handler(event, data)

        async with async_session_factory() as session:
            # Load user
            user = await get_user_by_telegram_id(session, tg_user.id)
            logger.debug(
                "RoleMiddleware: tg_user.id=%d, found user=%s, chat_id=%s",
                tg_user.id, user, chat_id,
            )

            # Load project from group chat
            project = None
            if chat_id and chat_id < 0:  # negative = group chat
                project = await get_project_by_telegram_chat_id(session, chat_id)

            # Load roles
            user_roles: list[RoleType] = []
            if user and project:
                user_roles = await get_user_roles_in_project(
                    session, user.id, project.id
                )

        data["user"] = user
        data["project"] = project
        data["user_roles"] = user_roles

        return await handler(event, data)
