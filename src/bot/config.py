"""
Application configuration.

Uses pydantic-settings to load values from environment variables / .env file.
All secrets (DB password, bot token, API keys) come from .env — never hardcoded.
"""

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

    # ── Azure OpenAI ──────────────────────────────────────────
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_chat_deployment: str = ""       # e.g. "gpt-4o"
    azure_openai_embedding_deployment: str = ""  # e.g. "text-embedding-3-small"

    # ── App ───────────────────────────────────────────────────
    log_level: str = "INFO"
    debug: bool = False


# Singleton — import this wherever config is needed
settings = Settings()
