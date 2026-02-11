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
        """Attach all handler routers to the dispatcher."""
        self.dp.include_router(handlers_router)

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
