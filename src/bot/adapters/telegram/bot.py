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
from bot.adapters.telegram.handlers import router as handlers_router
from bot.adapters.telegram.group_handlers import router as group_router
from bot.adapters.telegram.middleware import RoleMiddleware
from bot.adapters.telegram.project_handlers import router as project_router
from bot.adapters.telegram.role_handlers import router as role_router
from bot.adapters.telegram.stage_handlers import router as stage_router
from bot.config import settings

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
        self.dp.include_router(group_router)      # group chat events (bot added/removed)
        self.dp.include_router(handlers_router)    # /start and general commands
        self.dp.include_router(project_router)     # /newproject wizard
        self.dp.include_router(stage_router)       # /stages, /launch
        self.dp.include_router(role_router)        # /team, /invite, /myrole

    async def send_message(self, message: OutgoingMessage) -> None:
        """Send a text message via Telegram."""
        await self.bot.send_message(
            chat_id=int(message.chat_id),
            text=message.text,
            parse_mode=message.parse_mode,
        )

    async def start(self) -> None:
        """Start polling for Telegram updates (good for development)."""
        logger.info("Starting Telegram bot (polling mode)...")
        await self.dp.start_polling(self.bot)

    async def stop(self) -> None:
        """Shut down the Telegram bot gracefully."""
        logger.info("Stopping Telegram bot...")
        await self.bot.session.close()
