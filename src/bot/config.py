"""
Application configuration.

Uses pydantic-settings to load values from environment variables / .env file.
All secrets (DB password, bot token, API keys) come from .env — never hardcoded.
"""

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignore unknown env vars
    )

    # ── Database ──────────────────────────────────────────────
    postgres_db: str = "postgres"
    postgres_user: str = "postgres"
    postgres_password: str = "password"
    postgres_host: str = "localhost"
    postgres_port: int = 5432

    @property
    def database_url(self) -> str:
        """Async SQLAlchemy connection string for asyncpg."""
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # ── Telegram ──────────────────────────────────────────────
    telegram_bot_token: str = ""

    # ── AI / LLM Provider ────────────────────────────────────
    # Provider type:
    #   "azure"             — Azure OpenAI (AsyncAzureOpenAI)
    #   "openai"            — Standard OpenAI API (AsyncOpenAI)
    #   "openai_compatible" — Any OpenAI-compatible API: Kimi K2.5, DeepSeek, Groq, etc.
    ai_provider: Literal["azure", "openai", "openai_compatible"] = "azure"

    # ── Provider-agnostic model settings ─────────────────────
    # Used by "openai" and "openai_compatible" providers.
    # For "azure" provider, the azure_openai_*_deployment fields below are used instead.
    ai_api_key: str = ""                    # API key for OpenAI / compatible providers
    ai_base_url: str = ""                   # Base URL (required for openai_compatible)
    ai_chat_model: str = ""                 # e.g. "gpt-4o", "kimi-k2.5", "deepseek-chat"
    ai_embedding_model: str = ""            # e.g. "text-embedding-3-small"
    ai_embedding_dimensions: int = 1536     # truncate embeddings to fit Vector(1536)
    ai_whisper_model: str = "whisper-1"     # STT model name

    # ── Azure OpenAI (only when ai_provider=azure) ───────────
    # Auth: if api_key is empty, Microsoft Entra ID (DefaultAzureCredential) is used
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_chat_deployment: str = ""       # e.g. "gpt-4o", "gpt-5.2-chat-global"
    azure_openai_embedding_deployment: str = ""  # e.g. "text-embedding-3-large"
    azure_openai_whisper_deployment: str = ""     # e.g. "whisper"

    # ── Resolved model accessors ─────────────────────────────
    @property
    def effective_chat_model(self) -> str:
        """Chat model/deployment name for the active provider."""
        if self.ai_provider == "azure":
            return self.azure_openai_chat_deployment
        return self.ai_chat_model

    @property
    def effective_embedding_model(self) -> str:
        """Embedding model/deployment name for the active provider."""
        if self.ai_provider == "azure":
            return self.azure_openai_embedding_deployment
        return self.ai_embedding_model

    @property
    def effective_whisper_model(self) -> str:
        """Whisper model/deployment name for the active provider."""
        if self.ai_provider == "azure":
            return self.azure_openai_whisper_deployment or "whisper"
        return self.ai_whisper_model

    # ── App ───────────────────────────────────────────────────
    log_level: str = "INFO"
    debug: bool = False


# Singleton — import this wherever config is needed
settings = Settings()
