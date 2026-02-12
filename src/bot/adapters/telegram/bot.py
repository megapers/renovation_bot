"""
Telegram adapter — implements PlatformAdapter using aiogram 3.x.

This is the ONLY module that imports aiogram. All platform-specific
Telegram logic lives here, never in core/.
"""

import logging

from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from bot.adapters.base import OutgoingMessage, PlatformAdapter
from bot.adapters.telegram.budget_handlers import router as budget_router
from bot.adapters.telegram.handlers import router as handlers_router
from bot.adapters.telegram.group_handlers import router as group_router
from bot.adapters.telegram.middleware import RoleMiddleware
from bot.adapters.telegram.notification_handlers import (
    deliver_notification,
    router as notification_router,
)
from bot.adapters.telegram.project_handlers import router as project_router
from bot.adapters.telegram.report_handlers import router as report_router
from bot.adapters.telegram.role_handlers import router as role_router
from bot.adapters.telegram.stage_handlers import router as stage_router
from bot.config import settings
from bot.core.notification_service import Notification
from bot.core.scheduler import start_scheduler, stop_scheduler

logger = logging.getLogger(__name__)


class TelegramAdapter(PlatformAdapter):
    """Telegram implementation of the platform adapter."""

    def __init__(self) -> None:
        self.bot = Bot(
            token=settings.telegram_bot_token,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        )
        self.dp = Dispatcher()
        self._register_routers()

    def _register_routers(self) -> None:
        """Attach all handler routers and middleware to the dispatcher."""
        # Register middleware (runs before every handler)
        self.dp.message.middleware(RoleMiddleware())
        self.dp.callback_query.middleware(RoleMiddleware())

        # Register routers in order of priority
        self.dp.include_router(group_router)           # group chat events (bot added/removed)
        self.dp.include_router(handlers_router)        # /start and general commands
        self.dp.include_router(project_router)         # /newproject wizard
        self.dp.include_router(stage_router)           # /stages, /launch
        self.dp.include_router(notification_router)    # checkpoint approval, status changes
        self.dp.include_router(role_router)            # /team, /invite, /myrole
        self.dp.include_router(budget_router)          # /budget, /expenses
        self.dp.include_router(report_router)          # /report, /status, quick commands (LAST — has catch-all)

    async def send_message(self, message: OutgoingMessage) -> None:
        """Send a text message via Telegram."""
        # Map generic format_type to Telegram parse_mode
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

    async def start(self) -> None:
        """Start polling for Telegram updates and launch the scheduler."""
        logger.info("Starting Telegram bot (polling mode)...")

        # Start the background scheduler for deadline checks, reminders, etc.
        async def _send_notification(notification: Notification) -> None:
            await deliver_notification(notification, self.bot)

        start_scheduler(_send_notification)
        logger.info("Background scheduler started")

        await self.dp.start_polling(self.bot)

    async def stop(self) -> None:
        """Shut down the Telegram bot and scheduler gracefully."""
        logger.info("Stopping Telegram bot...")
        stop_scheduler()
        await self.bot.session.close()
