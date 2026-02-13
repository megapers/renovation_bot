"""
Mention-gating middleware for Telegram group chats.

Inspired by OpenClaw's mention-gating pattern: in group chats, the bot
only responds to messages that are specifically directed at it.  This
avoids the "noisy bot" problem where the bot intercepts every message.

The gate opens (message passes through) when ANY of these is true:
  • The message is in a private chat (always passes)
  • The message is an explicit command (/stages, /budget, etc.)
  • The bot is @mentioned by username
  • The message is a reply to one of the bot's own messages
  • The message text matches a custom pattern (e.g. "бот," prefix)
  • mention_gate_enabled is False (gate disabled entirely)

When the gate is CLOSED, the handler chain is silently skipped —
no error message, no reaction.  The message is simply ignored.

Configuration (in .env):
  MENTION_GATE_ENABLED=true
  MENTION_GATE_PATTERNS=бот,помощник

Usage — register as outer middleware on the dispatcher:
  dp.message.outer_middleware(MentionGateMiddleware(bot_id=bot.id))
"""

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from aiogram import BaseMiddleware
from aiogram.types import Message, TelegramObject

from bot.config import settings

logger = logging.getLogger(__name__)


class MentionGateMiddleware(BaseMiddleware):
    """
    Outer middleware that silently drops group messages not directed at the bot.

    Must be registered as an *outer* middleware so it runs BEFORE
    all other middleware (including RoleMiddleware) and filters.
    This avoids unnecessary DB queries for messages the bot will ignore.

    Args:
        bot_id:       The bot's Telegram user ID (from bot.me().id)
        bot_username: The bot's @username (without @), for text matching
    """

    def __init__(self, bot_id: int, bot_username: str = "") -> None:
        super().__init__()
        self.bot_id = bot_id
        self.bot_username = bot_username.lower().lstrip("@")

        # Pre-compile custom patterns from config
        self._custom_patterns: list[re.Pattern[str]] = []
        if settings.mention_gate_patterns:
            for pat in settings.mention_gate_patterns.split(","):
                pat = pat.strip()
                if pat:
                    try:
                        self._custom_patterns.append(
                            re.compile(rf"^\s*{re.escape(pat)}\b", re.IGNORECASE)
                        )
                    except re.error as e:
                        logger.warning("Invalid mention_gate_pattern '%s': %s", pat, e)

        logger.info(
            "MentionGate initialized: bot_id=%d, username=%s, patterns=%d, enabled=%s",
            bot_id,
            self.bot_username or "(unknown)",
            len(self._custom_patterns),
            settings.mention_gate_enabled,
        )

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Only filter Message events (not CallbackQuery, etc.)
        if not isinstance(event, Message):
            return await handler(event, data)

        # ── Always pass in private chats ──
        if event.chat.type == "private":
            return await handler(event, data)

        # ── Gate disabled → pass everything ──
        if not settings.mention_gate_enabled:
            return await handler(event, data)

        # ── Always pass explicit commands (/start, /stages, etc.) ──
        if event.text and event.text.startswith("/"):
            return await handler(event, data)

        # ── Check if directed at the bot ──
        if self._is_directed_at_bot(event):
            return await handler(event, data)

        # Gate closed — silently ignore
        logger.debug(
            "MentionGate: ignoring message in chat %d from user %d",
            event.chat.id,
            event.from_user.id if event.from_user else 0,
        )
        return None  # short-circuit: don't call handler chain

    def _is_directed_at_bot(self, message: Message) -> bool:
        """Check if the message is directed at the bot."""

        # 1. Reply to bot's message
        if message.reply_to_message and message.reply_to_message.from_user:
            if message.reply_to_message.from_user.id == self.bot_id:
                return True

        # 2. @mention in entities
        if message.entities:
            for entity in message.entities:
                if entity.type == "mention" and message.text:
                    mention_text = message.text[entity.offset:entity.offset + entity.length]
                    if mention_text.lower().lstrip("@") == self.bot_username:
                        return True
                if entity.type == "text_mention" and entity.user:
                    if entity.user.id == self.bot_id:
                        return True

        # 3. @mention in caption entities (for images with captions)
        if message.caption_entities:
            for entity in message.caption_entities:
                if entity.type == "mention" and message.caption:
                    mention_text = message.caption[entity.offset:entity.offset + entity.length]
                    if mention_text.lower().lstrip("@") == self.bot_username:
                        return True
                if entity.type == "text_mention" and entity.user:
                    if entity.user.id == self.bot_id:
                        return True

        # 4. Custom patterns (e.g. "бот, покажи бюджет")
        text = message.text or message.caption or ""
        for pattern in self._custom_patterns:
            if pattern.search(text):
                return True

        return False
