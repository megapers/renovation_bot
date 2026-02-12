"""
Abstract base class for messaging platform adapters.

Every platform (Telegram, WhatsApp, etc.) must implement this interface.
Core bot logic imports ONLY this interface — never platform-specific libraries.

This ensures that conversation flows, business rules, and state machines
remain completely platform-independent.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum


class MessageType(str, Enum):
    """Type of incoming user message (mirrors db enum)."""
    TEXT = "text"
    VOICE = "voice"
    IMAGE = "image"


@dataclass
class IncomingMessage:
    """Platform-agnostic representation of an incoming message."""

    platform: str           # "telegram", "whatsapp"
    chat_id: str            # unique chat identifier (group or private)
    user_id: str            # unique user identifier on the platform
    user_name: str          # display name
    text: str               # message text (original for text, caption for image, empty for voice)
    message_type: MessageType = MessageType.TEXT
    message_id: str | None = None   # platform-specific message ID
    file_id: str | None = None      # platform file reference (e.g. Telegram file_id)
    file_url: str | None = None     # direct URL to the file (if available)
    is_group: bool = False           # True if the message comes from a group chat


@dataclass
class ButtonOption:
    """A single button/option for interactive messages."""

    label: str              # display text
    callback_data: str      # data payload when pressed


@dataclass
class OutgoingMessage:
    """Platform-agnostic representation of an outgoing message."""

    chat_id: str
    text: str
    format_type: str = "plain"          # "plain", "html", "markdown" — adapter maps to platform format
    buttons: list[list[ButtonOption]] | None = None   # rows of buttons (inline keyboard / interactive list)
    edit_message_id: str | None = None  # if set, edit existing message instead of sending new


class PlatformAdapter(ABC):
    """
    Interface that every messaging platform adapter must implement.

    The core bot logic calls these methods; the adapter translates
    them into platform-specific API calls.
    """

    @abstractmethod
    async def send_message(self, message: OutgoingMessage) -> None:
        """Send a text message to a chat, with optional buttons."""
        ...

    @abstractmethod
    async def edit_message(self, message: OutgoingMessage) -> None:
        """Edit an existing message (if platform supports it)."""
        ...

    @abstractmethod
    async def download_file(self, file_ref: str) -> bytes:
        """Download a media file from the platform by reference."""
        ...

    @abstractmethod
    async def start(self) -> None:
        """Start listening for incoming messages (polling, webhook, etc.)."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully shut down the adapter."""
        ...
