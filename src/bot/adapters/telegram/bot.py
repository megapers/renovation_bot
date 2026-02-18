"""
Telegram adapter — implements PlatformAdapter using aiogram 3.x.

Supports multi-tenant mode: each tenant gets its own Telegram bot identity,
all sharing the same Dispatcher and handlers.  When TELEGRAM_BOT_TOKEN is
set in .env, the bot runs in **single-tenant** mode for backward compatibility.
When the tenants table has entries, all active tenants are started concurrently.
"""

import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats

from bot.adapters.base import OutgoingMessage, PlatformAdapter
from bot.adapters.telegram.ai_handlers import router as ai_router
from bot.adapters.telegram.budget_handlers import router as budget_router
from bot.adapters.telegram.group_handlers import router as group_router
from bot.adapters.telegram.handlers import router as handlers_router
from bot.adapters.telegram.mention_gate import MentionGateMiddleware
from bot.adapters.telegram.middleware import RoleMiddleware
from bot.adapters.telegram.notification_handlers import (
    deliver_notification,
)
from bot.adapters.telegram.notification_handlers import (
    router as notification_router,
)
from bot.adapters.telegram.project_handlers import router as project_router
from bot.adapters.telegram.report_handlers import router as report_router
from bot.adapters.telegram.role_handlers import router as role_router
from bot.adapters.telegram.stage_handlers import router as stage_router
from bot.config import settings
from bot.core.notification_service import Notification
from bot.core.scheduler import start_scheduler, stop_scheduler
from bot.db.repositories import (
    get_all_active_tenants,
    get_tenant_by_bot_token,
    create_tenant,
    update_tenant_username,
)
from bot.db.session import async_session_factory

logger = logging.getLogger(__name__)


class TelegramAdapter(PlatformAdapter):
    """Telegram implementation of the platform adapter.

    Supports two modes:
    - **Single-tenant**: Uses TELEGRAM_BOT_TOKEN from .env (backward compatible)
    - **Multi-tenant**: Loads all active tenants from the DB and runs one bot per tenant

    In multi-tenant mode, all bots share the same Dispatcher and handlers.
    Each bot's updates carry a `tenant_id` kwarg so handlers can scope data.
    """

    def __init__(self) -> None:
        self.dp = Dispatcher()
        self._bots: dict[int, Bot] = {}  # tenant_id -> Bot instance
        self._tenant_ids: dict[int, int] = {}  # bot_id -> tenant_id
        self._register_routers()

    def _register_routers(self) -> None:
        """Attach all handler routers and middleware to the dispatcher."""
        self.dp.include_router(group_router)
        self.dp.include_router(handlers_router)
        self.dp.include_router(project_router)
        self.dp.include_router(stage_router)
        self.dp.include_router(notification_router)
        self.dp.include_router(role_router)
        self.dp.include_router(budget_router)
        self.dp.include_router(ai_router)
        self.dp.include_router(report_router)

    @property
    def bot(self) -> Bot:
        """Primary bot (first registered, or single-tenant bot).

        Used by code that needs a single Bot reference (e.g. scheduler
        notifications). For multi-tenant notification dispatch, use
        get_bot_for_tenant() instead.
        """
        if self._bots:
            return next(iter(self._bots.values()))
        raise RuntimeError("No bots registered")

    def get_bot_for_tenant(self, tenant_id: int) -> Bot | None:
        """Get the Bot instance for a specific tenant."""
        return self._bots.get(tenant_id)

    async def send_message(self, message: OutgoingMessage) -> None:
        """Send a text message via Telegram."""
        parse_mode_map = {
            "html": ParseMode.HTML,
            "markdown": ParseMode.MARKDOWN_V2,
            "plain": None,
        }
        parse_mode = parse_mode_map.get(message.format_type)

        await self.bot.send_message(
            chat_id=int(message.chat_id),
            text=message.text,
            parse_mode=parse_mode,
        )

    async def edit_message(self, message: OutgoingMessage) -> None:
        """Edit an existing Telegram message."""
        if message.edit_message_id is None:
            logger.warning("edit_message called without edit_message_id")
            return

        parse_mode_map = {
            "html": ParseMode.HTML,
            "markdown": ParseMode.MARKDOWN_V2,
            "plain": None,
        }
        parse_mode = parse_mode_map.get(message.format_type)

        await self.bot.edit_message_text(
            chat_id=int(message.chat_id),
            message_id=int(message.edit_message_id),
            text=message.text,
            parse_mode=parse_mode,
        )

    async def download_file(self, file_ref: str) -> bytes:
        """Download a file from Telegram by file_id."""
        file = await self.bot.get_file(file_ref)
        if file.file_path is None:
            raise ValueError(f"Cannot download file: {file_ref}")
        result = await self.bot.download_file(file.file_path)
        if result is None:
            raise ValueError(f"Download returned empty for: {file_ref}")
        return result.read()

    async def _ensure_tenant_in_db(self, token: str) -> int:
        """Ensure a tenant record exists for the given bot token. Returns tenant_id.

        Also backfills any existing projects/messages/embeddings that have
        NULL tenant_id (from before multi-tenant was enabled).
        """
        async with async_session_factory() as session:
            tenant = await get_tenant_by_bot_token(session, token)
            if not tenant:
                tenant = await create_tenant(
                    session, name="Default Bot", telegram_bot_token=token
                )
                await session.commit()

            # Backfill orphaned records (tenant_id IS NULL)
            from sqlalchemy import text
            async with async_session_factory() as session:
                for table in ("projects", "messages", "embeddings"):
                    await session.execute(
                        text(f"UPDATE {table} SET tenant_id = :tid WHERE tenant_id IS NULL"),
                        {"tid": tenant.id},
                    )
                await session.commit()

            return tenant.id

    async def _create_bot(self, token: str, tenant_id: int) -> Bot:
        """Create a Bot instance, resolve identity, store mapping."""
        bot = Bot(
            token=token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        me = await bot.me()
        logger.info(
            "Bot identity: @%s (id=%d) for tenant_id=%d",
            me.username, me.id, tenant_id,
        )
        self._bots[tenant_id] = bot
        self._tenant_ids[me.id] = tenant_id

        # Persist the resolved username
        async with async_session_factory() as session:
            await update_tenant_username(session, tenant_id, me.username or "")
            await session.commit()

        return bot

    async def start(self) -> None:
        """Start polling for Telegram updates and launch the scheduler.

        In single-tenant mode (TELEGRAM_BOT_TOKEN set), creates one bot.
        In multi-tenant mode, loads all active tenants from the DB.
        """
        logger.info("Starting Telegram bot (polling mode)...")

        # ── Discover bots to run ──
        bots_to_poll: list[Bot] = []

        # Always register the .env token if present
        if settings.telegram_bot_token:
            tid = await self._ensure_tenant_in_db(settings.telegram_bot_token)
            bot = await self._create_bot(settings.telegram_bot_token, tid)
            bots_to_poll.append(bot)

        # Load additional tenants from DB
        async with async_session_factory() as session:
            tenants = await get_all_active_tenants(session)

        for tenant in tenants:
            if tenant.id in self._bots:
                continue  # Already registered (from .env token)
            try:
                bot = await self._create_bot(tenant.telegram_bot_token, tenant.id)
                bots_to_poll.append(bot)
            except Exception as e:
                logger.error(
                    "Failed to start bot for tenant %d (%s): %s",
                    tenant.id, tenant.name, e,
                )

        if not bots_to_poll:
            raise RuntimeError(
                "No bots to run. Set TELEGRAM_BOT_TOKEN in .env "
                "or add tenants to the database."
            )

        logger.info("Running %d bot(s)", len(bots_to_poll))

        # ── Register middleware (once on the dispatcher) ──
        # MentionGate needs bot identity — use first bot for gate config.
        # In multi-bot mode, the gate checks the actual bot from each update.
        primary = bots_to_poll[0]
        me = await primary.me()
        self.dp.message.outer_middleware(
            MentionGateMiddleware(bot_id=me.id, bot_username=me.username or "")
        )
        self.dp.message.outer_middleware(RoleMiddleware())
        self.dp.callback_query.outer_middleware(RoleMiddleware())

        # ── Set command scopes for each bot ──
        for bot in bots_to_poll:
            await self._set_command_scopes(bot)

        # ── Inject tenant_id into every update via update.kwargs ──
        @self.dp.update.outer_middleware()
        async def inject_tenant_id(handler, event, data):
            bot_obj = data.get("bot")
            if bot_obj:
                data["tenant_id"] = self._tenant_ids.get(bot_obj.id)
            else:
                data["tenant_id"] = None
            return await handler(event, data)

        # ── Start scheduler ──
        async def _send_notification(notification: Notification) -> None:
            await deliver_notification(notification, self.bot)

        start_scheduler(_send_notification)
        logger.info("Background scheduler started")

        # ── Start polling for all bots ──
        await self.dp.start_polling(*bots_to_poll)

    async def _set_command_scopes(self, bot: Bot) -> None:
        """Register different command menus for private and group chats."""
        # Private chat commands
        private_commands = [
            BotCommand(command="newproject", description="Создать новый проект"),
            BotCommand(command="myprojects", description="Мои проекты"),
            BotCommand(command="stages", description="Этапы ремонта"),
            BotCommand(command="budget", description="Бюджет проекта"),
            BotCommand(command="expenses", description="Добавить расход"),
            BotCommand(command="report", description="Отчёт по проекту"),
            BotCommand(command="status", description="Статус проекта"),
            BotCommand(command="team", description="Команда проекта"),
            BotCommand(command="invite", description="Пригласить участника"),
            BotCommand(command="myrole", description="Моя роль"),
            BotCommand(command="chat", description="AI-чат о проекте"),
            BotCommand(command="launch", description="Запустить проект"),
        ]

        # Group chat commands
        group_commands = [
            BotCommand(command="link", description="Привязать группу к проекту"),
            BotCommand(command="stages", description="Этапы ремонта"),
            BotCommand(command="budget", description="Бюджет проекта"),
            BotCommand(command="expenses", description="Добавить расход"),
            BotCommand(command="status", description="Статус проекта"),
            BotCommand(command="report", description="Отчёт по проекту"),
            BotCommand(command="team", description="Команда проекта"),
            BotCommand(command="myrole", description="Моя роль"),
            BotCommand(command="chat", description="AI-чат о проекте"),
        ]

        try:
            await bot.set_my_commands(private_commands)
            await bot.set_my_commands(
                private_commands,
                scope=BotCommandScopeAllPrivateChats(),
            )
            await bot.set_my_commands(
                group_commands,
                scope=BotCommandScopeAllGroupChats(),
            )
            me = await bot.me()
            logger.info("Command scopes registered for @%s", me.username)
        except Exception as e:
            logger.warning("Failed to set command scopes: %s", e)

    async def stop(self) -> None:
        """Shut down all bots and the scheduler gracefully."""
        logger.info("Stopping Telegram bot(s)...")
        stop_scheduler()
        for bot in self._bots.values():
            await bot.session.close()
