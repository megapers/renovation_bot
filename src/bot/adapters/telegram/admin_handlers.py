"""
Admin commands for managing bot tenants via Telegram.

Commands (restricted to ADMIN_TELEGRAM_IDS):
  /addbot <token>    — register a new tenant bot
  /listbots          — list all registered tenants
  /removebot <id>    — deactivate a tenant

These commands run on the primary bot (TELEGRAM_BOT_TOKEN from .env).
Non-admin users get no response (command is silently ignored).
"""

import logging
import re

from aiogram import Bot, Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import settings
from bot.db.models import Tenant
from bot.db.repositories import (
    create_tenant,
    get_all_active_tenants,
    get_tenant_by_bot_token,
)
from bot.db.session import async_session_factory

logger = logging.getLogger(__name__)
router = Router(name="admin_handlers")

# Telegram bot token regex: digits:alphanumeric
_TOKEN_RE = re.compile(r"^\d+:[A-Za-z0-9_-]+$")


def _is_admin(telegram_id: int) -> bool:
    """Check if a Telegram user ID is in the admin list."""
    return telegram_id in settings.admin_ids


@router.message(Command("addbot"))
async def cmd_addbot(message: Message, **kwargs) -> None:
    """
    /addbot <token> — Register a new Telegram bot as a tenant.

    The token is obtained from @BotFather after creating a new bot.
    The new bot will start polling on next restart.

    Only available to admin users (ADMIN_TELEGRAM_IDS in .env).
    """
    tg_user = message.from_user
    if tg_user is None or not _is_admin(tg_user.id):
        return  # Silently ignore for non-admins

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip():
        await message.answer(
            "📝 <b>Использование:</b>\n\n"
            "<code>/addbot TOKEN</code>\n\n"
            "Получите токен у @BotFather после создания нового бота.\n\n"
            "Пример:\n"
            "<code>/addbot 7123456789:AAF...</code>"
        )
        return

    token = args[1].strip()

    # Validate token format
    if not _TOKEN_RE.match(token):
        await message.answer(
            "❌ Неверный формат токена.\n\n"
            "Токен должен выглядеть так: <code>1234567890:ABCdef...</code>\n"
            "Скопируйте его из @BotFather."
        )
        return

    # Check if already registered
    async with async_session_factory() as session:
        existing = await get_tenant_by_bot_token(session, token)
        if existing:
            status = "✅ активен" if existing.is_active else "⏸ неактивен"
            await message.answer(
                f"⚠️ Этот бот уже зарегистрирован.\n\n"
                f"ID: {existing.id}\n"
                f"Имя: {existing.name}\n"
                f"Username: @{existing.telegram_bot_username or '?'}\n"
                f"Статус: {status}"
            )
            return

    # Validate the token by calling Telegram API
    try:
        test_bot = Bot(token=token)
        bot_info = await test_bot.me()
        bot_name = bot_info.first_name or "Unknown"
        bot_username = bot_info.username or ""
        await test_bot.session.close()
    except Exception as e:
        await message.answer(
            f"❌ Не удалось подключиться к Telegram API.\n\n"
            f"Проверьте токен. Ошибка: {e}"
        )
        return

    # Register in database
    async with async_session_factory() as session:
        tenant = await create_tenant(
            session,
            name=bot_name,
            telegram_bot_token=token,
            telegram_bot_username=bot_username,
        )
        await session.commit()
        tenant_id = tenant.id

    # Hot-start polling — no restart needed
    try:
        adapter = kwargs.get("adapter")
        if adapter:
            await adapter.hot_add_bot(token, tenant_id)
            status_line = "🟢 Бот запущен и готов к работе!"
        else:
            status_line = (
                "⚠️ Бот зарегистрирован, но не удалось запустить автоматически.\n"
                "Перезапустите процесс (<code>python -m bot</code>)."
            )
    except Exception as e:
        logger.error("Hot-start failed for tenant %d: %s", tenant_id, e)
        status_line = (
            "⚠️ Бот зарегистрирован, но не удалось запустить автоматически.\n"
            f"Ошибка: {e}\n"
            "Перезапустите процесс (<code>python -m bot</code>)."
        )

    await message.answer(
        f"✅ <b>Бот зарегистрирован!</b>\n\n"
        f"🤖 Имя: {bot_name}\n"
        f"👤 Username: @{bot_username}\n"
        f"🆔 Tenant ID: {tenant_id}\n\n"
        f"{status_line}"
    )
    logger.info(
        "Admin %d registered new tenant: @%s (tenant_id=%d)",
        tg_user.id, bot_username, tenant_id,
    )


@router.message(Command("listbots"))
async def cmd_listbots(message: Message) -> None:
    """
    /listbots — List all registered bot tenants.

    Only available to admin users (ADMIN_TELEGRAM_IDS in .env).
    """
    tg_user = message.from_user
    if tg_user is None or not _is_admin(tg_user.id):
        return

    async with async_session_factory() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(Tenant).order_by(Tenant.id)
        )
        tenants = result.scalars().all()

    if not tenants:
        await message.answer("📋 Нет зарегистрированных ботов.")
        return

    lines = ["📋 <b>Зарегистрированные боты:</b>\n"]
    for t in tenants:
        status = "🟢" if t.is_active else "🔴"
        username = f"@{t.telegram_bot_username}" if t.telegram_bot_username else "—"
        lines.append(
            f"{status} <b>{t.name}</b>\n"
            f"   ID: {t.id} | {username}\n"
        )

    lines.append(f"Всего: {len(tenants)}")
    await message.answer("\n".join(lines))


@router.message(Command("removebot"))
async def cmd_removebot(message: Message) -> None:
    """
    /removebot <id> — Deactivate a tenant bot.

    The bot will stop polling on next restart.
    Only available to admin users (ADMIN_TELEGRAM_IDS in .env).
    """
    tg_user = message.from_user
    if tg_user is None or not _is_admin(tg_user.id):
        return

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or not args[1].strip().isdigit():
        await message.answer(
            "📝 <b>Использование:</b>\n\n"
            "<code>/removebot ID</code>\n\n"
            "ID можно узнать через /listbots"
        )
        return

    tenant_id = int(args[1].strip())

    async with async_session_factory() as session:
        from sqlalchemy import select
        result = await session.execute(
            select(Tenant).where(Tenant.id == tenant_id)
        )
        tenant = result.scalar_one_or_none()

        if not tenant:
            await message.answer(f"❌ Тенант с ID {tenant_id} не найден.")
            return

        if not tenant.is_active:
            await message.answer(
                f"⚠️ Бот <b>{tenant.name}</b> уже деактивирован."
            )
            return

        tenant.is_active = False
        await session.commit()

    await message.answer(
        f"✅ Бот <b>{tenant.name}</b> (@{tenant.telegram_bot_username or '?'}) "
        f"деактивирован.\n\n"
        f"Перезапустите процесс, чтобы изменения вступили в силу."
    )
    logger.info(
        "Admin %d deactivated tenant %d (%s)",
        tg_user.id, tenant_id, tenant.name,
    )
