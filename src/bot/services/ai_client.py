"""
Azure OpenAI client service — centralized AI access.

Provides async methods for:
  - Chat completions (GPT-4o)
  - Text embeddings (text-embedding-3-small)
  - Voice transcription (Whisper)
  - Image understanding (GPT-4 Vision)

All Azure OpenAI interactions go through this module.
Platform-specific code never calls the openai SDK directly.
"""

import logging
from typing import Any

from openai import AsyncAzureOpenAI

from bot.config import settings

logger = logging.getLogger(__name__)

# Module-level client (lazy-initialized)
_client: AsyncAzureOpenAI | None = None


def _get_client() -> AsyncAzureOpenAI:
    """Get or create the async Azure OpenAI client."""
    global _client
    if _client is None:
        if not settings.azure_openai_api_key or not settings.azure_openai_endpoint:
            raise RuntimeError(
                "Azure OpenAI is not configured. "
                "Set AZURE_OPENAI_API_KEY and AZURE_OPENAI_ENDPOINT in .env"
            )
        _client = AsyncAzureOpenAI(
            api_key=settings.azure_openai_api_key,
            azure_endpoint=settings.azure_openai_endpoint,
            api_version=settings.azure_openai_api_version,
        )
        logger.info("Azure OpenAI client initialized (endpoint=%s)", settings.azure_openai_endpoint)
    return _client


def is_ai_configured() -> bool:
    """Check if Azure OpenAI credentials are configured."""
    return bool(settings.azure_openai_api_key and settings.azure_openai_endpoint)


# ── Chat Completions ─────────────────────────────────────────


async def chat_completion(
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    response_format: dict | None = None,
) -> str:
    """
    Send a chat completion request to Azure OpenAI.

    Args:
        messages: list of {"role": "system"|"user"|"assistant", "content": ...}
        temperature: creativity (0.0 = deterministic, 1.0 = creative)
        max_tokens: max tokens in response
        response_format: optional {"type": "json_object"} for JSON mode

    Returns:
        The assistant's response text.
    """
    client = _get_client()
    deployment = settings.azure_openai_chat_deployment
    if not deployment:
        raise RuntimeError("AZURE_OPENAI_CHAT_DEPLOYMENT is not set")

    kwargs: dict[str, Any] = {
        "model": deployment,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        kwargs["response_format"] = response_format

    response = await client.chat.completions.create(**kwargs)
    content = response.choices[0].message.content or ""

    logger.debug(
        "Chat completion: %d messages → %d tokens used",
        len(messages),
        response.usage.total_tokens if response.usage else 0,
    )
    return content


async def chat_completion_with_vision(
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.3,
    max_tokens: int = 1000,
) -> str:
    """
    Send a chat completion with image(s) to GPT-4 Vision.

    Messages should include content blocks with type "image_url".
    Example message:
    {
        "role": "user",
        "content": [
            {"type": "text", "text": "Describe this image"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,..."}}
        ]
    }
    """
    return await chat_completion(
        messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )


# ── Embeddings ───────────────────────────────────────────────


async def generate_embedding(text: str) -> list[float]:
    """
    Generate a vector embedding for a single text.

    Uses text-embedding-3-small (1536 dimensions).

    Returns:
        List of floats (1536-dim vector).
    """
    client = _get_client()
    deployment = settings.azure_openai_embedding_deployment
    if not deployment:
        raise RuntimeError("AZURE_OPENAI_EMBEDDING_DEPLOYMENT is not set")

    # Truncate very long texts (embedding model has token limits)
    max_chars = 8000  # ~2000 tokens — safe for text-embedding-3-small
    if len(text) > max_chars:
        text = text[:max_chars]

    response = await client.embeddings.create(
        model=deployment,
        input=text,
    )
    vector = response.data[0].embedding

    logger.debug(
        "Embedding generated: %d chars → %d dims, %d tokens",
        len(text),
        len(vector),
        response.usage.total_tokens if response.usage else 0,
    )
    return vector


async def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """
    Generate embeddings for multiple texts in a single API call.

    More efficient than calling generate_embedding() in a loop.

    Returns:
        List of embedding vectors (same order as input texts).
    """
    client = _get_client()
    deployment = settings.azure_openai_embedding_deployment
    if not deployment:
        raise RuntimeError("AZURE_OPENAI_EMBEDDING_DEPLOYMENT is not set")

    max_chars = 8000
    truncated = [t[:max_chars] if len(t) > max_chars else t for t in texts]

    response = await client.embeddings.create(
        model=deployment,
        input=truncated,
    )

    # Sort by index to ensure order matches input
    sorted_data = sorted(response.data, key=lambda x: x.index)
    vectors = [item.embedding for item in sorted_data]

    logger.debug(
        "Batch embeddings: %d texts → %d vectors, %d tokens",
        len(texts),
        len(vectors),
        response.usage.total_tokens if response.usage else 0,
    )
    return vectors


# ── Voice Transcription (Whisper) ─────────────────────────────


async def transcribe_audio(
    audio_bytes: bytes,
    filename: str = "voice.ogg",
    language: str = "ru",
) -> str:
    """
    Transcribe audio using Azure OpenAI Whisper.

    Args:
        audio_bytes: raw audio file bytes
        filename: filename with extension (helps Whisper detect format)
        language: ISO 639-1 language code

    Returns:
        Transcribed text.
    """
    client = _get_client()
    # Whisper uses the same deployment or a dedicated whisper deployment
    # For Azure OpenAI, whisper is typically deployed as a separate model
    deployment = getattr(settings, "azure_openai_whisper_deployment", "") or "whisper"

    response = await client.audio.transcriptions.create(
        model=deployment,
        file=(filename, audio_bytes),
        language=language,
    )

    text = response.text.strip()
    logger.debug("Whisper transcription: %s → %d chars", filename, len(text))
    return text


# ── Image Understanding ──────────────────────────────────────


async def describe_image(
    image_bytes: bytes,
    caption: str | None = None,
    mime_type: str = "image/jpeg",
) -> str:
    """
    Generate a text description of an image using GPT-4 Vision.

    Args:
        image_bytes: raw image bytes
        caption: optional caption/context provided by the user
        mime_type: image MIME type

    Returns:
        AI-generated description of the image.
    """
    import base64

    b64 = base64.b64encode(image_bytes).decode("utf-8")
    image_url = f"data:{mime_type};base64,{b64}"

    prompt = (
        "Ты помощник по ремонту квартир. "
        "Опиши что изображено на этой фотографии в контексте ремонта. "
        "Включи: что изображено, текущее состояние работ, "
        "заметные материалы или проблемы. Ответ на русском, кратко."
    )
    if caption:
        prompt += f"\n\nПодпись пользователя: {caption}"

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": image_url, "detail": "low"},
                },
            ],
        },
    ]

    text = await chat_completion_with_vision(messages, max_tokens=500)
    logger.debug("Image description: %d bytes → %d chars", len(image_bytes), len(text))
    return text
