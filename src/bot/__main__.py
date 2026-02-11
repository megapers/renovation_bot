"""
Main entry point for the Renovation Chatbot.

Run with:  python -m bot
"""

import asyncio
import logging

from bot.config import settings


def setup_logging() -> None:
    """Configure structured logging."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


async def main() -> None:
    """Initialize and start the bot."""
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("Starting Renovation Chatbot...")
    logger.info("Database: %s@%s:%s/%s",
                settings.postgres_user, settings.postgres_host,
                settings.postgres_port, settings.postgres_db)

    # Import adapter here to avoid loading aiogram before logging is configured
    from bot.adapters.telegram.bot import TelegramAdapter

    adapter = TelegramAdapter()

    try:
        await adapter.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        await adapter.stop()


if __name__ == "__main__":
    asyncio.run(main())
