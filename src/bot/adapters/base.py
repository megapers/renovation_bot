"""
Abstract base class for messaging platform adapters.

Every platform (Telegram, WhatsApp, etc.) must implement this interface.
Core bot logic imports ONLY this interface — never platform-specific libraries.

This ensures that conversation flows, business rules, and state machines
remain completely platform-independent.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class IncomingMessage:
    """Platform-agnostic representation of an incoming message."""

    platform: str           # "telegram", "whatsapp"
    chat_id: str            # unique chat identifier (group or private)
    user_id: str            # unique user identifier on the platform
    user_name: str          # display name
    text: str               # message text content
    is_group: bool = False  # True if the message comes from a group chat


@dataclass
class OutgoingMessage:
    """Platform-agnostic representation of an outgoing message."""

    chat_id: str
    text: str
    parse_mode: str | None = None  # adapter translates to platform-specific format


class PlatformAdapter(ABC):
    """
    Interface that every messaging platform adapter must implement.

    The core bot logic calls these methods; the adapter translates
    them into platform-specific API calls.
    """

    @abstractmethod
    async def send_message(self, message: OutgoingMessage) -> None:
        """Send a text message to a chat."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Start listening for incoming messages (polling, webhook, etc.)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully shut down the adapter."""
        ...
