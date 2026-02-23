"""
Multi-provider AI client service — centralized LLM access.

Supports three provider types (controlled by AI_PROVIDER env var):
  - "azure"             — Azure OpenAI (Entra ID or API key)
  - "openai"            — Standard OpenAI API
  - "openai_compatible" — Any OpenAI-compatible API (Kimi K2.5, DeepSeek, Groq, etc.)

Provides async methods for:
  - Chat completions
  - Text embeddings
  - Voice transcription (Whisper)
  - Image understanding (Vision)

All AI interactions go through this module.
Platform-specific code never calls the openai SDK directly.
"""

import logging
from typing import Any

from openai import AsyncAzureOpenAI, AsyncOpenAI

from bot.config import settings

logger = logging.getLogger(__name__)

# Module-level clients (lazy-initialized)
_client: AsyncOpenAI | AsyncAzureOpenAI | None = None
_embedding_client: AsyncOpenAI | None = None  # Separate client for embeddings (optional)
_whisper_client: AsyncOpenAI | None = None  # Separate client for STT (optional)


def _get_client() -> AsyncOpenAI | AsyncAzureOpenAI:
    """
    Get or create the async OpenAI-compatible client.

    Provider selection (AI_PROVIDER):
      "azure"             → AsyncAzureOpenAI (Entra ID if no API key, else key auth)
      "openai"            → AsyncOpenAI (standard OpenAI)
      "openai_compatible" → AsyncOpenAI with custom base_url (Kimi, DeepSeek, etc.)
    """
    global _client
    if _client is not None:
        return _client

    provider = settings.ai_provider

    if provider == "azure":
        if not settings.azure_openai_endpoint:
            raise RuntimeError(
                "Azure OpenAI is not configured. "
                "Set AZURE_OPENAI_ENDPOINT in .env"
            )

        if settings.azure_openai_api_key:
            # Azure — API key authentication
            _client = AsyncAzureOpenAI(
                api_key=settings.azure_openai_api_key,
                azure_endpoint=settings.azure_openai_endpoint,
                api_version=settings.azure_openai_api_version,
            )
            logger.info(
                "AI client: Azure OpenAI with API key (endpoint=%s)",
                settings.azure_openai_endpoint,
            )
        else:
            # Azure — Microsoft Entra ID (DefaultAzureCredential)
            try:
                from azure.identity import DefaultAzureCredential, get_bearer_token_provider
            except ImportError:
                raise RuntimeError(
                    "azure-identity is required for Entra ID auth. "
                    "Install it: pip install azure-identity"
                )

            credential = DefaultAzureCredential()
            token_provider = get_bearer_token_provider(
                credential,
                "https://cognitiveservices.azure.com/.default",
            )
            _client = AsyncAzureOpenAI(
                azure_ad_token_provider=token_provider,
                azure_endpoint=settings.azure_openai_endpoint,
                api_version=settings.azure_openai_api_version,
            )
            logger.info(
                "AI client: Azure OpenAI with Entra ID (endpoint=%s)",
                settings.azure_openai_endpoint,
            )

    elif provider == "openai":
        if not settings.ai_api_key:
            raise RuntimeError(
                "OpenAI API key is not set. Set AI_API_KEY in .env"
            )
        _client = AsyncOpenAI(api_key=settings.ai_api_key)
        logger.info("AI client: OpenAI (standard)")

    elif provider == "openai_compatible":
        if not settings.ai_api_key:
            raise RuntimeError(
                "API key is not set. Set AI_API_KEY in .env"
            )
        if not settings.ai_base_url:
            raise RuntimeError(
                "Base URL is not set. Set AI_BASE_URL in .env "
                "(e.g. https://api.moonshot.cn/v1)"
            )
        _client = AsyncOpenAI(
            api_key=settings.ai_api_key,
            base_url=settings.ai_base_url,
        )
        logger.info(
            "AI client: OpenAI-compatible (base_url=%s)",
            settings.ai_base_url,
        )

    else:
        raise RuntimeError(f"Unknown AI_PROVIDER: {provider!r}")

    return _client


def reset_client() -> None:
    """Reset the cached client (useful when switching providers at runtime/tests)."""
    global _client, _embedding_client, _whisper_client
    _client = None
    _embedding_client = None
    _whisper_client = None


def _get_embedding_client() -> AsyncOpenAI | AsyncAzureOpenAI:
    """
    Get the client for embedding generation.

    If AI_EMBEDDING_BASE_URL is set, creates a separate client
    (e.g., Ollama on localhost for BGE-M3 while chat uses Groq).
    Otherwise, reuses the main AI client.
    """
    global _embedding_client
    if _embedding_client is not None:
        return _embedding_client

    if settings.ai_embedding_base_url:
        _embedding_client = AsyncOpenAI(
            api_key=settings.ai_embedding_api_key or "not-needed",
            base_url=settings.ai_embedding_base_url,
        )
        logger.info("Embedding client: separate endpoint (%s)", settings.ai_embedding_base_url)
        return _embedding_client

    return _get_client()


def _get_whisper_client() -> AsyncOpenAI | AsyncAzureOpenAI:
    """
    Get the client for Whisper STT.

    If AI_WHISPER_BASE_URL is set, creates a separate client for STT
    (e.g., faster-whisper-server on a different port, or Groq free API).
    Otherwise, reuses the main AI client.
    """
    global _whisper_client
    if _whisper_client is not None:
        return _whisper_client

    if settings.ai_whisper_base_url:
        _whisper_client = AsyncOpenAI(
            api_key=settings.ai_whisper_api_key or "not-needed",
            base_url=settings.ai_whisper_base_url,
        )
        logger.info("Whisper client: separate endpoint (%s)", settings.ai_whisper_base_url)
        return _whisper_client

    return _get_client()


def is_ai_configured() -> bool:
    """Check if AI provider credentials are configured."""
    provider = settings.ai_provider
    if provider == "azure":
        # Entra ID needs only the endpoint; API key auth needs both
        return bool(settings.azure_openai_endpoint)
    if provider == "openai":
        return bool(settings.ai_api_key)
    if provider == "openai_compatible":
        return bool(settings.ai_api_key and settings.ai_base_url)
    return False


# ── Chat Completions ─────────────────────────────────────────


async def chat_completion(
    messages: list[dict[str, Any]],
    *,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    response_format: dict | None = None,
) -> str:
    """
    Send a chat completion request.

    Args:
        messages: list of {"role": "system"|"user"|"assistant", "content": ...}
        temperature: creativity (0.0 = deterministic, 1.0 = creative)
        max_tokens: max tokens in response
        response_format: optional {"type": "json_object"} for JSON mode

    Returns:
        The assistant's response text.
    """
    client = _get_client()
    model = settings.effective_chat_model
    if not model:
        raise RuntimeError(
            "Chat model is not set. "
            "Set AZURE_OPENAI_CHAT_DEPLOYMENT (azure) or AI_CHAT_MODEL (openai/compatible)"
        )

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
    }

    # Token limit parameter: some models use max_completion_tokens, others max_tokens
    # Try max_completion_tokens first (newer models), fall back to max_tokens
    kwargs["max_completion_tokens"] = max_tokens

    # Only send temperature if non-default (some models like GPT-5.x only support default=1)
    if temperature != 1.0:
        kwargs["temperature"] = temperature
    if response_format:
        kwargs["response_format"] = response_format

    try:
        response = await client.chat.completions.create(**kwargs)
    except Exception as e:
        err_msg = str(e).lower()
        retry_kwargs = dict(kwargs)
        changed = False

        # Retry with max_tokens if max_completion_tokens is not supported
        if "max_completion_tokens" in err_msg and "max_completion_tokens" in retry_kwargs:
            retry_kwargs.pop("max_completion_tokens")
            retry_kwargs["max_tokens"] = max_tokens
            changed = True

        # Retry without temperature if model doesn't support it
        if "temperature" in err_msg and "temperature" in retry_kwargs:
            retry_kwargs.pop("temperature")
            changed = True

        if changed:
            response = await client.chat.completions.create(**retry_kwargs)
        else:
            raise

    content = response.choices[0].message.content or ""

    logger.debug(
        "Chat completion [%s]: %d messages → %d tokens used",
        model,
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
    Send a chat completion with image(s) (Vision).

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

    Output dimensions controlled by AI_EMBEDDING_DIMENSIONS.
    Models that support Matryoshka truncation (text-embedding-3-*)
    truncate server-side via the dimensions parameter.

    Returns:
        List of floats (dimension count matches settings).
    """
    client = _get_embedding_client()
    model = settings.effective_embedding_model
    if not model:
        raise RuntimeError(
            "Embedding model is not set. "
            "Set AZURE_OPENAI_EMBEDDING_DEPLOYMENT (azure) or AI_EMBEDDING_MODEL (openai/compat)"
        )

    # Truncate very long texts (embedding models have token limits)
    max_chars = 8000  # ~2000 tokens
    if len(text) > max_chars:
        text = text[:max_chars]

    embed_kwargs: dict[str, Any] = {
        "model": model,
        "input": text,
    }
    # Only send dimensions if configured (not all providers support it)
    if settings.ai_embedding_dimensions:
        embed_kwargs["dimensions"] = settings.ai_embedding_dimensions

    try:
        response = await client.embeddings.create(**embed_kwargs)
    except Exception as e:
        # Retry without dimensions if provider doesn't support truncation
        if "dimensions" in str(e).lower() and "dimensions" in embed_kwargs:
            embed_kwargs.pop("dimensions")
            response = await client.embeddings.create(**embed_kwargs)
        else:
            raise

    vector = response.data[0].embedding

    logger.debug(
        "Embedding [%s]: %d chars → %d dims, %d tokens",
        model,
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
    client = _get_embedding_client()
    model = settings.effective_embedding_model
    if not model:
        raise RuntimeError(
            "Embedding model is not set. "
            "Set AZURE_OPENAI_EMBEDDING_DEPLOYMENT (azure) or AI_EMBEDDING_MODEL (openai/compat)"
        )

    max_chars = 8000
    truncated = [t[:max_chars] if len(t) > max_chars else t for t in texts]

    embed_kwargs: dict[str, Any] = {
        "model": model,
        "input": truncated,
    }
    if settings.ai_embedding_dimensions:
        embed_kwargs["dimensions"] = settings.ai_embedding_dimensions

    try:
        response = await client.embeddings.create(**embed_kwargs)
    except Exception as e:
        if "dimensions" in str(e).lower() and "dimensions" in embed_kwargs:
            embed_kwargs.pop("dimensions")
            response = await client.embeddings.create(**embed_kwargs)
        else:
            raise

    # Sort by index to ensure order matches input
    sorted_data = sorted(response.data, key=lambda x: x.index)
    vectors = [item.embedding for item in sorted_data]

    logger.debug(
        "Batch embeddings [%s]: %d texts → %d vectors, %d tokens",
        model,
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
    Transcribe audio using Whisper (or compatible STT model).

    Args:
        audio_bytes: raw audio file bytes
        filename: filename with extension (helps detect format)
        language: ISO 639-1 language code

    Returns:
        Transcribed text.
    """
    client = _get_whisper_client()
    model = settings.effective_whisper_model

    response = await client.audio.transcriptions.create(
        model=model,
        file=(filename, audio_bytes),
        language=language,
    )

    text = response.text.strip()
    logger.debug("Whisper [%s]: %s → %d chars", model, filename, len(text))
    return text


# ── Image Understanding ──────────────────────────────────────


async def describe_image(
    image_bytes: bytes,
    caption: str | None = None,
    mime_type: str = "image/jpeg",
) -> str:
    """
    Generate a text description of an image using Vision model.

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

    from bot.services.skills_loader import get_skill_prompt

    prompt = get_skill_prompt("image-describer") or (
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
