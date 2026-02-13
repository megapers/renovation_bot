"""
WhatsApp adapter — implements PlatformAdapter using WhatsApp Cloud API.

Inspired by OpenClaw's multi-channel architecture, this adapter mirrors
our Telegram adapter's interface while handling WhatsApp-specific
concerns: webhook verification, phone-number-based routing, and
the Cloud API message format.

This module is the ONLY place that imports WhatsApp-specific helpers.
All platform-specific logic lives here — core/ never imports this.

Deployment options:
  1. WhatsApp Business Cloud API (Meta-hosted — production recommended)
  2. Self-hosted Baileys-like bridge (advanced — future option)

This adapter implements option 1 (Cloud API) which is the officially
supported, stable, REST-based approach — best fit for our Python async stack.
"""

import hashlib
import hmac
import json
import logging
from typing import Any

import httpx

from bot.adapters.base import OutgoingMessage, PlatformAdapter
from bot.config import settings

logger = logging.getLogger(__name__)


# ── WhatsApp Cloud API helpers ────────────────────────────────


class WhatsAppCloudClient:
    """
    Async client for WhatsApp Business Cloud API.

    Wraps the Graph API v21.0 endpoints for sending messages,
    reacting, and downloading media.

    Reference: https://developers.facebook.com/docs/whatsapp/cloud-api
    """

    BASE_URL = "https://graph.facebook.com/v21.0"

    def __init__(
        self,
        phone_number_id: str,
        access_token: str,
    ) -> None:
        self.phone_number_id = phone_number_id
        self.access_token = access_token
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    async def send_text(
        self,
        to: str,
        text: str,
        *,
        preview_url: bool = False,
    ) -> dict[str, Any]:
        """
        Send a text message.

        Args:
            to: recipient phone number in E.164 format (e.g. "+77001234567")
            text: message body (max 4096 chars, supports basic formatting)
            preview_url: whether to show link previews

        Returns:
            WhatsApp API response with message ID.
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {
                "preview_url": preview_url,
                "body": text,
            },
        }
        return await self._post(f"/{self.phone_number_id}/messages", payload)

    async def send_reaction(
        self,
        to: str,
        message_id: str,
        emoji: str,
    ) -> dict[str, Any]:
        """
        React to a message with an emoji.

        This is the WhatsApp equivalent of Telegram's "ack reaction"
        pattern used by OpenClaw.
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "reaction",
            "reaction": {
                "message_id": message_id,
                "emoji": emoji,
            },
        }
        return await self._post(f"/{self.phone_number_id}/messages", payload)

    async def send_interactive_buttons(
        self,
        to: str,
        body_text: str,
        buttons: list[dict[str, str]],
        *,
        header: str | None = None,
        footer: str | None = None,
    ) -> dict[str, Any]:
        """
        Send an interactive button message (max 3 buttons).

        This is the WhatsApp equivalent of Telegram's inline keyboard.
        For more than 3 options, use send_interactive_list() instead.

        Args:
            to: recipient phone number
            body_text: message body
            buttons: list of {"id": "callback_data", "title": "Button Label"}
                     (max 3, title max 20 chars)
        """
        action_buttons = [
            {
                "type": "reply",
                "reply": {"id": btn["id"], "title": btn["title"][:20]},
            }
            for btn in buttons[:3]
        ]
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "button",
                "body": {"text": body_text},
                "action": {"buttons": action_buttons},
            },
        }
        if header:
            payload["interactive"]["header"] = {"type": "text", "text": header}
        if footer:
            payload["interactive"]["footer"] = {"text": footer}

        return await self._post(f"/{self.phone_number_id}/messages", payload)

    async def send_interactive_list(
        self,
        to: str,
        body_text: str,
        button_text: str,
        sections: list[dict[str, Any]],
        *,
        header: str | None = None,
        footer: str | None = None,
    ) -> dict[str, Any]:
        """
        Send an interactive list message (up to 10 items per section).

        Use this for project selection when there are more than 3 options.

        Args:
            to: recipient phone number
            body_text: message body
            button_text: CTA button text (max 20 chars)
            sections: list of {"title": "...", "rows": [{"id": "...", "title": "..."}]}
        """
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": {
                "type": "list",
                "body": {"text": body_text},
                "action": {
                    "button": button_text[:20],
                    "sections": sections,
                },
            },
        }
        if header:
            payload["interactive"]["header"] = {"type": "text", "text": header}
        if footer:
            payload["interactive"]["footer"] = {"text": footer}

        return await self._post(f"/{self.phone_number_id}/messages", payload)

    async def download_media(self, media_id: str) -> bytes:
        """
        Download media from WhatsApp (two-step: get URL, then download).

        Used for voice messages and images that need transcription/description.
        """
        # Step 1: get download URL
        resp = await self._client.get(f"/{media_id}")
        resp.raise_for_status()
        media_url = resp.json().get("url")
        if not media_url:
            raise ValueError(f"No download URL for media {media_id}")

        # Step 2: download the actual file
        dl_resp = await self._client.get(media_url)
        dl_resp.raise_for_status()
        return dl_resp.content

    async def mark_as_read(self, message_id: str) -> None:
        """
        Mark a message as read (blue ticks).

        OpenClaw calls this per their sendReadReceipts config.
        """
        payload = {
            "messaging_product": "whatsapp",
            "status": "read",
            "message_id": message_id,
        }
        try:
            await self._post(f"/{self.phone_number_id}/messages", payload)
        except Exception as e:
            logger.debug("Failed to mark as read: %s", e)

    async def _post(
        self, path: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Send a POST request to the WhatsApp Cloud API."""
        resp = await self._client.post(path, json=payload)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            logger.error("WhatsApp API error: %s", data["error"])
            raise RuntimeError(f"WhatsApp API error: {data['error']}")
        return data

    async def close(self) -> None:
        """Shut down the HTTP client."""
        await self._client.aclose()


# ── Webhook parsing ──────────────────────────────────────────


class WebhookParser:
    """
    Parse and validate incoming WhatsApp webhook payloads.

    Handles:
      - Hub challenge verification (GET)
      - Signature validation (X-Hub-Signature-256)
      - Message extraction from webhook payload
      - Group vs DM detection

    Follows the same security model as OpenClaw's WhatsApp channel:
    verify signatures, normalize inbound into a shared envelope.
    """

    def __init__(self, app_secret: str, verify_token: str) -> None:
        self.app_secret = app_secret
        self.verify_token = verify_token

    def verify_hub_challenge(
        self,
        mode: str | None,
        token: str | None,
        challenge: str | None,
    ) -> str | None:
        """
        Verify the webhook subscription (GET request from Meta).

        Returns the challenge string if valid, None otherwise.
        """
        if mode == "subscribe" and token == self.verify_token:
            return challenge
        logger.warning("Webhook verification failed: mode=%s", mode)
        return None

    def verify_signature(self, body: bytes, signature: str) -> bool:
        """
        Validate X-Hub-Signature-256 header.

        This prevents forged webhook calls — same approach as OpenClaw.
        """
        expected = hmac.new(
            self.app_secret.encode(),
            body,
            hashlib.sha256,
        ).hexdigest()
        received = signature.removeprefix("sha256=")
        return hmac.compare_digest(expected, received)

    def extract_messages(
        self, payload: dict[str, Any]
    ) -> list[dict[str, Any]]:
        """
        Extract normalized message entries from a webhook payload.

        Returns a list of dicts, each containing:
          - from_number: sender's phone number
          - message_id: WhatsApp message ID
          - timestamp: Unix timestamp
          - type: "text" | "image" | "audio" | "video" | "interactive" | ...
          - text: message text (for text messages)
          - media_id: media ID (for image/audio/video)
          - caption: image caption (for image messages)
          - interactive_id: button reply ID (for interactive replies)
          - is_group: bool
          - group_id: group JID (if group message)
          - context_message_id: replied-to message ID (if reply)
          - contact_name: sender's profile name
        """
        results: list[dict[str, Any]] = []

        entry_list = payload.get("entry", [])
        for entry in entry_list:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages", [])
                contacts = value.get("contacts", [])

                # Build contact name map
                name_map: dict[str, str] = {}
                for contact in contacts:
                    wa_id = contact.get("wa_id", "")
                    profile = contact.get("profile", {})
                    name_map[wa_id] = profile.get("name", wa_id)

                for msg in messages:
                    from_number = msg.get("from", "")
                    msg_type = msg.get("type", "unknown")
                    context = msg.get("context", {})

                    normalized: dict[str, Any] = {
                        "from_number": from_number,
                        "message_id": msg.get("id", ""),
                        "timestamp": msg.get("timestamp", ""),
                        "type": msg_type,
                        "text": None,
                        "media_id": None,
                        "caption": None,
                        "interactive_id": None,
                        "is_group": bool(msg.get("group_id")),
                        "group_id": msg.get("group_id"),
                        "context_message_id": context.get("id"),
                        "contact_name": name_map.get(from_number, from_number),
                    }

                    if msg_type == "text":
                        normalized["text"] = msg.get("text", {}).get("body", "")

                    elif msg_type == "image":
                        img = msg.get("image", {})
                        normalized["media_id"] = img.get("id")
                        normalized["caption"] = img.get("caption")

                    elif msg_type == "audio":
                        audio = msg.get("audio", {})
                        normalized["media_id"] = audio.get("id")

                    elif msg_type == "interactive":
                        interactive = msg.get("interactive", {})
                        ir_type = interactive.get("type", "")
                        if ir_type == "button_reply":
                            normalized["interactive_id"] = (
                                interactive.get("button_reply", {}).get("id")
                            )
                        elif ir_type == "list_reply":
                            normalized["interactive_id"] = (
                                interactive.get("list_reply", {}).get("id")
                            )

                    results.append(normalized)

        return results


# ── WhatsApp Adapter ─────────────────────────────────────────


class WhatsAppAdapter(PlatformAdapter):
    """
    WhatsApp implementation of the platform adapter.

    Uses WhatsApp Business Cloud API (Meta Graph API) for sending
    and receiving messages. Incoming messages arrive via FastAPI
    webhook; outgoing messages are sent via the Cloud API client.

    Architecture mirrors our TelegramAdapter:
      - WhatsAppCloudClient handles API calls (like aiogram.Bot)
      - WebhookParser handles webhook payload parsing
      - FastAPI routes handle webhook HTTP endpoints

    Group chat support:
      - WhatsApp groups use a group JID as chat_id
      - The adapter normalizes group messages the same way as DMs
      - Mention gating applies (see mention_gate.py)
    """

    def __init__(self) -> None:
        if not settings.whatsapp_phone_number_id:
            raise RuntimeError(
                "WHATSAPP_PHONE_NUMBER_ID is required. "
                "Get it from Meta Business Suite → WhatsApp → API Setup."
            )

        self.client = WhatsAppCloudClient(
            phone_number_id=settings.whatsapp_phone_number_id,
            access_token=settings.whatsapp_access_token,
        )
        self.parser = WebhookParser(
            app_secret=settings.whatsapp_app_secret,
            verify_token=settings.whatsapp_verify_token,
        )
        self._ack_emoji = settings.whatsapp_ack_emoji

    async def send_message(self, message: OutgoingMessage) -> None:
        """Send a text message via WhatsApp Cloud API."""
        # WhatsApp uses its own formatting (*bold*, _italic_, ~strike~, ```mono```)
        # Convert from HTML if needed
        text = self._convert_format(message.text, message.format_type)

        if message.buttons:
            # Flatten buttons and send as interactive
            flat_buttons = [
                {"id": btn.callback_data, "title": btn.label}
                for row in message.buttons
                for btn in row
            ]
            if len(flat_buttons) <= 3:
                await self.client.send_interactive_buttons(
                    to=message.chat_id,
                    body_text=text,
                    buttons=flat_buttons,
                )
            else:
                # Use list for >3 options
                rows = [
                    {"id": btn["id"], "title": btn["title"]}
                    for btn in flat_buttons
                ]
                await self.client.send_interactive_list(
                    to=message.chat_id,
                    body_text=text,
                    button_text="Выбрать",
                    sections=[{"title": "Варианты", "rows": rows}],
                )
        else:
            await self.client.send_text(to=message.chat_id, text=text)

    async def edit_message(self, message: OutgoingMessage) -> None:
        """
        WhatsApp doesn't support editing messages — send a new one.

        This is a known platform limitation. OpenClaw handles this
        the same way: send a replacement message.
        """
        logger.debug("WhatsApp: edit_message → sending new message (edits not supported)")
        await self.send_message(message)

    async def download_file(self, file_ref: str) -> bytes:
        """Download media by WhatsApp media ID."""
        return await self.client.download_media(file_ref)

    async def start(self) -> None:
        """
        Start the WhatsApp adapter.

        Unlike Telegram (polling), WhatsApp uses webhooks.
        The FastAPI app must register the webhook routes.
        Call register_webhook_routes() to add them to your FastAPI app.
        """
        logger.info(
            "WhatsApp adapter initialized (phone_number_id=%s)",
            settings.whatsapp_phone_number_id,
        )
        logger.info(
            "Register webhook routes via adapter.register_webhook_routes(app)"
        )

    async def stop(self) -> None:
        """Shut down the WhatsApp adapter."""
        logger.info("Stopping WhatsApp adapter...")
        await self.client.close()

    def register_webhook_routes(self, app: Any) -> None:
        """
        Register WhatsApp webhook endpoints on a FastAPI app.

        Adds:
          GET  /webhook/whatsapp  — hub verification
          POST /webhook/whatsapp  — incoming messages

        Call this during app startup:
            whatsapp_adapter.register_webhook_routes(fastapi_app)
        """
        from fastapi import FastAPI, Request, Response

        assert isinstance(app, FastAPI), "Expected a FastAPI app instance"

        @app.get("/webhook/whatsapp")
        async def verify_webhook(request: Request) -> Response:
            """Handle Meta's webhook verification challenge."""
            mode = request.query_params.get("hub.mode")
            token = request.query_params.get("hub.verify_token")
            challenge = request.query_params.get("hub.challenge")

            result = self.parser.verify_hub_challenge(mode, token, challenge)
            if result:
                return Response(content=result, media_type="text/plain")
            return Response(status_code=403)

        @app.post("/webhook/whatsapp")
        async def receive_webhook(request: Request) -> Response:
            """Handle incoming WhatsApp messages."""
            body = await request.body()

            # Verify signature
            signature = request.headers.get("X-Hub-Signature-256", "")
            if self.parser.app_secret and not self.parser.verify_signature(
                body, signature
            ):
                logger.warning("Invalid webhook signature")
                return Response(status_code=403)

            payload = json.loads(body)
            messages = self.parser.extract_messages(payload)

            for msg in messages:
                await self._handle_incoming(msg)

            # Always return 200 to acknowledge receipt
            return Response(status_code=200)

    async def _handle_incoming(self, msg: dict[str, Any]) -> None:
        """
        Process a single incoming WhatsApp message.

        Converts to IncomingMessage and routes to the appropriate handler.
        This is where the adapter meets the core logic.
        """
        from bot.adapters.base import IncomingMessage, MessageType

        msg_type = msg["type"]
        message_type = MessageType.TEXT

        if msg_type == "audio":
            message_type = MessageType.VOICE
        elif msg_type == "image":
            message_type = MessageType.IMAGE

        incoming = IncomingMessage(
            platform="whatsapp",
            chat_id=msg.get("group_id") or msg["from_number"],
            user_id=msg["from_number"],
            user_name=msg["contact_name"],
            text=msg.get("text") or msg.get("caption") or "",
            message_type=message_type,
            message_id=msg["message_id"],
            file_id=msg.get("media_id"),
            is_group=msg["is_group"],
        )

        logger.info(
            "WhatsApp message: from=%s type=%s group=%s text=%s",
            incoming.user_id,
            incoming.message_type,
            incoming.is_group,
            (incoming.text or "")[:50],
        )

        # Send ack reaction (like OpenClaw's ackReaction pattern)
        if self._ack_emoji:
            try:
                await self.client.send_reaction(
                    to=msg["from_number"],
                    message_id=msg["message_id"],
                    emoji=self._ack_emoji,
                )
            except Exception as e:
                logger.debug("Ack reaction failed: %s", e)

        # Mark as read
        await self.client.mark_as_read(msg["message_id"])

        # TODO: Route to core handlers (Phase 2 integration)
        # For now, log and acknowledge
        logger.debug("Incoming processed: %s", incoming)

    @staticmethod
    def _convert_format(text: str, format_type: str) -> str:
        """
        Convert HTML formatting to WhatsApp format.

        WhatsApp uses:
          *bold*  _italic_  ~strikethrough~  ```monospace```

        Telegram uses HTML:
          <b>bold</b>  <i>italic</i>  <s>strike</s>  <code>mono</code>
        """
        import re

        if format_type != "html":
            return text

        conversions = [
            (r"<b>(.*?)</b>", r"*\1*"),
            (r"<strong>(.*?)</strong>", r"*\1*"),
            (r"<i>(.*?)</i>", r"_\1_"),
            (r"<em>(.*?)</em>", r"_\1_"),
            (r"<s>(.*?)</s>", r"~\1~"),
            (r"<code>(.*?)</code>", r"```\1```"),
            (r"<pre>(.*?)</pre>", r"```\1```"),
            (r"<a href=['\"]([^'\"]+)['\"]>([^<]+)</a>", r"\2 (\1)"),
        ]

        result = text
        for pattern, replacement in conversions:
            result = re.sub(pattern, replacement, result, flags=re.DOTALL)

        # Strip any remaining HTML tags
        result = re.sub(r"<[^>]+>", "", result)
        return result
