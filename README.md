# Renovation Chatbot

A chatbot assistant for managing home renovation projects — tracking stages, deadlines, budgets, and communication between homeowners, contractors, and tradespeople.

Built with Python, currently running on Telegram with a platform-agnostic architecture designed for future WhatsApp support.

## Tech Stack

- **Python 3.12+** with async throughout
- **aiogram 3.x** — Telegram bot framework
- **FastAPI** — webhooks & REST API
- **PostgreSQL 17** + TimescaleDB + pgvector
- **SQLAlchemy 2.0** (async) + Alembic migrations
- **Azure OpenAI** — chat completions & embeddings

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.12+

### 1. Clone & configure

```bash
git clone <repo-url>
cd Chatbot
cp .env.example .env
# Edit .env — fill in your TELEGRAM_BOT_TOKEN and Azure OpenAI keys
```

### 2. Start the database

```bash
docker compose up -d
```

### 3. Install dependencies

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

pip install -e ".[dev]"
```

### 4. Run migrations

```bash
alembic upgrade head
```

### 5. Start the bot

```bash
python -m bot
```

## Project Structure

```
src/bot/
├── __init__.py          # Package root
├── __main__.py          # Entry point (python -m bot)
├── config.py            # Settings from .env via pydantic-settings
├── adapters/            # Platform-specific code
│   ├── base.py          # Abstract PlatformAdapter interface
│   └── telegram/        # Telegram implementation
│       ├── bot.py       # TelegramAdapter (aiogram setup)
│       └── handlers.py  # Message & command handlers
├── core/                # Business logic (platform-independent)
├── db/                  # Database layer
│   ├── models.py        # SQLAlchemy ORM models
│   ├── session.py       # Async engine & session factory
│   └── migrations/      # Alembic migration scripts
└── services/            # External services (AI/LLM, embeddings)
```

## Architecture

The codebase follows a layered design:

1. **Adapters** — translate platform messages (Telegram, WhatsApp) to/from a common format
2. **Core** — conversation flows, state machines, business rules — never imports platform libraries
3. **Data** — SQLAlchemy models, database queries, embeddings

## License

TBD
