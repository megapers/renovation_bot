"""
Media processing service — voice transcription and image understanding.

Handles downloading, transcribing, and describing media files.
Platform adapters pass raw bytes; this service is platform-agnostic.

Processing flow:
  Voice: bytes → Whisper STT → transcribed_text
  Image: bytes + caption → GPT-4 Vision → description text
"""

import logging

from bot.services.ai_client import describe_image, is_ai_configured, transcribe_audio

logger = logging.getLogger(__name__)


async def process_voice(
    audio_bytes: bytes,
    filename: str = "voice.ogg",
    language: str = "ru",
) -> str | None:
    """
    Transcribe a voice message to text.

    Args:
        audio_bytes: raw audio file content
        filename: original filename (helps Whisper detect format)
        language: ISO 639-1 language code (default: Russian)

    Returns:
        Transcribed text, or None if AI is not configured or transcription fails.
    """
    if not is_ai_configured():
        logger.warning("AI not configured — cannot transcribe voice")
        return None

    if not audio_bytes:
        logger.warning("Empty audio bytes — skipping transcription")
        return None

    try:
        text = await transcribe_audio(audio_bytes, filename=filename, language=language)
        logger.info("Voice transcription: %s → %d chars", filename, len(text))
        return text
    except Exception as e:
        logger.error("Voice transcription failed: %s", e)
        return None


async def process_image(
    image_bytes: bytes,
    caption: str | None = None,
    mime_type: str = "image/jpeg",
) -> str | None:
    """
    Generate a text description of an image.

    Args:
        image_bytes: raw image content
        caption: optional user-provided caption
        mime_type: image MIME type (jpeg, png, etc.)

    Returns:
        AI-generated text description, or None if not available.
    """
    if not is_ai_configured():
        logger.warning("AI not configured — cannot describe image")
        return None

    if not image_bytes:
        logger.warning("Empty image bytes — skipping description")
        return None

    try:
        description = await describe_image(
            image_bytes, caption=caption, mime_type=mime_type
        )
        logger.info("Image description: %d bytes → %d chars", len(image_bytes), len(description))
        return description
    except Exception as e:
        logger.error("Image description failed: %s", e)
        return None


def build_message_text(
    *,
    message_type: str,
    raw_text: str | None = None,
    transcribed_text: str | None = None,
) -> str | None:
    """
    Get the canonical text representation of a message for storage/embedding.

    Priority:
      1. transcribed_text (from STT or Vision) — always preferred
      2. raw_text (original text or caption)
      3. None — no text available

    Returns:
        The best available text, or None.
    """
    if transcribed_text and transcribed_text.strip():
        return transcribed_text.strip()
    if raw_text and raw_text.strip():
        return raw_text.strip()
    return None
