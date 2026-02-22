"""
Telegram middleware for role-based access control and tenant resolution.

This middleware runs before every handler and injects:
  - `tenant_id`  — the tenant associated with this bot instance (or None)
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
    Injects user, project, tenant, and role context into every handler.

    For private chats: user is loaded, project is None (unless FSM has project_id).
    For group chats: user is loaded, project is looked up via telegram_chat_id.

    tenant_id is passed through from dispatcher-level kwargs (set by the
    multi-bot launcher for each bot).
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

        # Ensure tenant_id is always in data (may be set by multi-bot launcher)
        if "tenant_id" not in data:
            data["tenant_id"] = None

        if tg_user is None:
            # Can't identify user — pass through (e.g. channel posts)
            data["user"] = None
            data["project"] = None
            data["user_roles"] = []
            return await handler(event, data)

        async with async_session_factory() as session:
            # Load user (with cache — avoids DB hit on every message)
            from bot.services.pg_cache import pg_cache_get, pg_cache_set
            cache_key = f"user:tg:{tg_user.id}"
            cached_user_id = await pg_cache_get(session, cache_key)

            if cached_user_id is not None:
                # Cache hit — load user by internal ID (faster than telegram_id lookup)
                from bot.db.repositories import get_user_by_id
                user = await get_user_by_id(session, cached_user_id)
            else:
                user = await get_user_by_telegram_id(session, tg_user.id)
                if user:
                    await pg_cache_set(session, cache_key, user.id, ttl=600)
                    await session.commit()
            logger.debug(
                "RoleMiddleware: tg_user.id=%d, found user=%s, chat_id=%s",
                tg_user.id, user, chat_id,
            )

            # Load project from group chat (with cache)
            project = None
            if chat_id and chat_id < 0:  # negative = group chat
                proj_cache_key = f"project:chat:{chat_id}"
                cached_proj_id = await pg_cache_get(session, proj_cache_key)
                if cached_proj_id is not None:
                    from bot.db.repositories import get_project_with_stages
                    project = await get_project_with_stages(session, cached_proj_id)
                else:
                    project = await get_project_by_telegram_chat_id(session, chat_id)
                    if project:
                        await pg_cache_set(session, proj_cache_key, project.id, ttl=600)
                        await session.commit()

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
