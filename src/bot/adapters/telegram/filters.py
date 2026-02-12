"""
Custom aiogram filters for role-based access control.

These filters can be used as handler decorators to restrict commands
to users with specific permissions.

Usage:
    from bot.adapters.telegram.filters import RequirePermission
    from bot.core.role_service import Permission

    @router.message(Command("launch"), RequirePermission(Permission.LAUNCH_PROJECT))
    async def cmd_launch(message: Message, ...):
        ...
"""

import logging

from aiogram.filters import BaseFilter
from aiogram.types import Message, CallbackQuery

from bot.core.role_service import Permission, has_permission, ROLE_LABELS
from bot.db.models import RoleType

logger = logging.getLogger(__name__)


class RequirePermission(BaseFilter):
    """
    Filter that checks if the user has a required permission.

    Works with the RoleMiddleware which injects `user_roles` into handler data.
    If permission check fails, sends a access-denied message.
    """

    def __init__(self, permission: Permission) -> None:
        self.permission = permission

    async def __call__(
        self,
        event: Message | CallbackQuery,
        user_roles: list[RoleType] | None = None,
        **kwargs,
    ) -> bool:
        roles = user_roles or []

        # If no roles at all (not a member of any project in this chat),
        # allow access — the handler itself may deal with project selection.
        if not roles:
            return True

        if has_permission(roles, self.permission):
            return True

        # Access denied
        text = (
            "🚫 <b>Доступ запрещён</b>\n\n"
            f"У вас нет прав для этого действия.\n"
            f"Ваши роли: {', '.join(ROLE_LABELS.get(r, r.value) for r in roles)}"
        )

        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer("🚫 Нет доступа", show_alert=True)

        logger.info(
            "Permission %s denied for user roles=%s",
            self.permission.value,
            [r.value for r in roles],
        )
        return False


class RequireRegistration(BaseFilter):
    """
    Filter that checks if the user is registered (has sent /start).

    Works with the RoleMiddleware which injects `user` into handler data.
    """

    async def __call__(
        self,
        event: Message | CallbackQuery,
        user=None,
        **kwargs,
    ) -> bool:
        if user is not None:
            return True

        text = "❌ Вы не зарегистрированы. Отправьте /start сначала."

        if isinstance(event, Message):
            await event.answer(text)
        elif isinstance(event, CallbackQuery):
            await event.answer("❌ Сначала отправьте /start", show_alert=True)

        return False


class IsGroupChat(BaseFilter):
    """Filter that passes only in group chats (negative chat IDs)."""

    async def __call__(self, event: Message | CallbackQuery, **kwargs) -> bool:
        chat_id = None
        if isinstance(event, Message):
            chat_id = event.chat.id
        elif isinstance(event, CallbackQuery) and event.message:
            chat_id = event.message.chat.id

        return chat_id is not None and chat_id < 0


class IsPrivateChat(BaseFilter):
    """Filter that passes only in private chats (positive chat IDs)."""

    async def __call__(self, event: Message | CallbackQuery, **kwargs) -> bool:
        chat_id = None
        if isinstance(event, Message):
            chat_id = event.chat.id
        elif isinstance(event, CallbackQuery) and event.message:
            chat_id = event.message.chat.id

        return chat_id is not None and chat_id > 0
