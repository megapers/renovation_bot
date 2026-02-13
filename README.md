# Renovation Chatbot

A chatbot assistant for managing home renovation projects — tracking stages, deadlines, budgets, and communication between homeowners, contractors, and tradespeople.

Built with Python, currently running on Telegram with a platform-agnostic architecture designed for future WhatsApp support.

## Tech Stack

- **Python 3.12+** with async throughout
- **aiogram 3.x** — Telegram bot framework
- **FastAPI** — webhooks & REST API
- **PostgreSQL 17** + TimescaleDB + pgvector
- **SQLAlchemy 2.0** (async) + Alembic migrations
- **Multi-provider AI** — Azure OpenAI, OpenAI, or any OpenAI-compatible API (Kimi K2.5, DeepSeek, Groq, etc.)

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Python 3.12+
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- An AI provider account (Azure OpenAI, OpenAI, or compatible)

### 1. Clone & configure

```bash
git clone <repo-url>
cd Chatbot
cp .env.example .env
# Edit .env — see "AI Provider Configuration" below
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

# Basic install
pip install -e ".[dev]"

# With Azure Entra ID support
pip install -e ".[azure,dev]"
```

### 4. Run migrations

```bash
alembic upgrade head
```

### 5. Start the bot

```bash
python -m bot
```

---

## AI Provider Configuration

The bot supports three AI providers via the `AI_PROVIDER` setting in `.env`:

### Azure OpenAI (`AI_PROVIDER=azure`)

Two authentication modes:

**API Key auth:**
```env
AI_PROVIDER=azure
AZURE_OPENAI_API_KEY=your-key-here
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_VERSION=2024-10-21
AZURE_OPENAI_CHAT_DEPLOYMENT=gpt-4o
AZURE_OPENAI_EMBEDDING_DEPLOYMENT=text-embedding-3-small
```

**Microsoft Entra ID auth** (leave `AZURE_OPENAI_API_KEY` empty):
```env
AI_PROVIDER=azure
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
```
Requires `pip install -e ".[azure]"` and an active Azure login (`az login`).

### Standard OpenAI (`AI_PROVIDER=openai`)
```env
AI_PROVIDER=openai
AI_API_KEY=sk-...
AI_CHAT_MODEL=gpt-4o
AI_EMBEDDING_MODEL=text-embedding-3-small
```

### OpenAI-compatible (`AI_PROVIDER=openai_compatible`)
```env
AI_PROVIDER=openai_compatible
AI_API_KEY=your-key
AI_BASE_URL=https://api.deepseek.com
AI_CHAT_MODEL=deepseek-chat
AI_EMBEDDING_MODEL=text-embedding-3-small
```

---

## Testing Guide

### Step 1 — Verify infrastructure

```bash
# Database is running
docker compose ps          # timescaledb should be "Up"

# Migrations applied
alembic current            # should show the latest revision as (head)

# AI provider configured
python -c "from bot.config import settings; print(f'Provider: {settings.ai_provider}'); print(f'Chat: {settings.effective_chat_model}'); print(f'Embed: {settings.effective_embedding_model}')"
```

### Step 2 — Start the bot

```bash
python -m bot
```

Expected output:
```
INFO     Starting Telegram bot (polling mode)...
INFO     Command scopes registered
INFO     Background scheduler started
INFO     Run polling for bot @YourBotName ...
```

The bot registers separate command menus for private and group chats on startup.

### Step 3 — Private chat test scenarios

Open a private chat with your bot in Telegram and run through these scenarios in order:

#### 3.1 — Registration
| Action | Expected |
|---|---|
| Send `/start` | Welcome message with command list; user created in DB |
| Send `/start` again | Same welcome; user marked as returning |

#### 3.2 — Check empty state
| Action | Expected |
|---|---|
| `/myprojects` | "У вас нет проектов" + prompt to create |
| `/stages` | "У вас нет активных проектов" |
| `/budget` | "У вас нет активных проектов" |
| `/report` | "У вас нет активных проектов" |

#### 3.3 — Create a project
| Action | Expected |
|---|---|
| `/newproject` | Wizard starts: "Шаг 1 из 7 — Введите название объекта" |
| Type project name | Prompts for address (with Skip button) |
| Enter address or skip | Prompts for area |
| Enter area or skip | Shows renovation type picker (4 buttons) |
| Pick type | Prompts for budget |
| Enter budget or skip | Asks who coordinates (3 buttons) |
| Pick coordinator | If foreman/designer → asks for contact; if self → asks about co-owner |
| Answer co-owner | Custom furniture picker (Kitchen, Wardrobes, etc.) |
| Select items + "Готово" | Shows project summary with Confirm/Edit/Cancel buttons |
| Press "Подтвердить" | Project created. In private chat, shows "Добавить бота в группу" button with deep link |

#### 3.4 — Single project commands (auto-resolved)
With exactly one project, all commands auto-resolve without a picker:

| Command | Expected |
|---|---|
| `/myprojects` | Shows project with 🟢 status, budget, and group link status |
| `/stages` | Shows all 13 stages (+ custom furniture stages if selected) |
| `/budget` | Shows budget summary by category |
| `/report` | Generates project report |
| `/status` | Shows current project status |
| `/team` | Lists team members |
| `/myrole` | Shows your role (Owner) |
| `/ask What is the current status?` | AI answers about the project |

#### 3.5 — Multi-project picker
Create a second project with `/newproject`, then test:

| Command | Expected |
|---|---|
| `/stages` | Shows project picker (inline buttons) instead of auto-resolving |
| Pick a project | Shows stages for that project |
| `/budget` | Shows project picker |
| `/report` | Shows project picker |

#### 3.6 — Stage management
| Action | Expected |
|---|---|
| `/stages` (with project) | Lists stages with status icons |
| `/launch` | Starts the project (first stage becomes "In progress") |
| `/nextstage` | Advances to next stage |
| `/deadline` | Shows deadline info |
| `/mystage` | Shows stages assigned to you |

#### 3.7 — Budget & expenses
| Action | Expected |
|---|---|
| `/budget` | Shows budget overview |
| `/expenses` | Prompts to enter an expense with categories |

#### 3.8 — Team management
| Action | Expected |
|---|---|
| `/invite` | Starts invite flow (enter Telegram @username, pick role) |
| `/team` | Lists project members with roles |

#### 3.9 — AI features
| Action | Expected |
|---|---|
| `/ask How much budget is left?` | AI responds with project context |
| `/backfill` | Generates embeddings for existing messages |
| Send a voice message | Bot acknowledges (Phase 8: transcribes via Whisper) |
| Send a photo | Bot acknowledges (Phase 8: processes via Vision) |
| Type free text (not a command) | Stored as message; quick commands like "бюджет" or "отчёт" trigger matching handlers |

### Step 4 — Group chat test scenarios

#### 4.1 — Add bot to group via deep link
| Action | Expected |
|---|---|
| After creating a project, click "Добавить бота в группу" | Telegram prompts to select a group |
| Pick a group | Bot sends "Группа автоматически привязана к проекту {name}" |

#### 4.2 — Add bot to group manually
| Action | Expected |
|---|---|
| Add bot to a group (not via deep link) | Bot sends welcome: "Бот подключён к группе" + instructions to use /link |
| `/link` | If one unlinked project → auto-links; if multiple → shows picker |

#### 4.3 — Group commands (auto-resolve to linked project)
In a group linked to a project, all commands auto-resolve:

| Command | Expected |
|---|---|
| `/stages` | Shows stages for the linked project (no picker) |
| `/budget` | Shows budget for the linked project |
| `/team` | Lists team members |
| `/status` | Shows current status |
| `/report` | Shows project report |
| `/myrole` | Shows your role in this project |
| `/ask` | AI answers in project context |

#### 4.4 — Unlinked group
| Action | Expected |
|---|---|
| Use commands in a group with no linked project | "Эта группа не привязана к проекту. Используйте /link" |

### Step 5 — Command menu verification

| Chat type | Expected menu |
|---|---|
| Private chat | 12 commands: newproject, myprojects, stages, budget, expenses, report, status, team, invite, myrole, ask, launch |
| Group chat | 9 commands: link, stages, budget, expenses, status, report, team, myrole, ask |

Click the `/` button or the menu icon in Telegram to verify the correct commands appear.

### Step 6 — Quick text commands

In private chat (with a project), send these as plain text (without `/`):

| Text | Expected |
|---|---|
| `бюджет` | Budget report |
| `этапы` | Stage list |
| `расходы` | Expense info |
| `отчёт` | Project report |
| `статус` | Status report |
| `следующий этап` | Next stage info |
| `моя роль` | Your role |
| `мой этап` | Your assigned stages |

### Step 7 — Notification & scheduler checks

The background scheduler runs periodically. Verify in logs:

```
INFO     Background scheduler started
```

Notifications trigger for:
- Stage deadline 1 day before expiry
- Overdue stage alerts
- Furniture order reminders (30–45 days before installation)
- Overspending warnings
- Weekly client reports

### Step 8 — Database verification

```sql
-- Connect to the database
docker compose exec timescaledb psql -U megapers -d renovbot

-- Check tables
\dt

-- Verify user was created
SELECT id, telegram_id, full_name, is_bot_started FROM users;

-- Verify project
SELECT id, name, renovation_type, total_budget, telegram_chat_id, is_active FROM projects;

-- Verify stages were generated
SELECT s.id, s.name, s.status, s.sort_order FROM stages s JOIN projects p ON s.project_id = p.id ORDER BY s.sort_order;

-- Check project-user roles
SELECT pm.user_id, pm.role, u.full_name FROM project_members pm JOIN users u ON pm.user_id = u.id;

-- Check embeddings (pgvector)
SELECT id, LEFT(content, 50) as content_preview, vector_dims(embedding) as dims FROM message_embeddings LIMIT 5;
```

### Troubleshooting

| Issue | Solution |
|---|---|
| `Command scopes registered` not in logs | Bot token may lack permission; check BotFather settings |
| "Вы не зарегистрированы" | Send `/start` to the bot in private chat first |
| Picker keeps appearing | You have multiple projects — select one, or test with only one project |
| AI commands fail | Check `AI_PROVIDER` config: `python -c "from bot.config import settings; print(settings.ai_provider)"` |
| Azure Entra ID auth error | Run `az login` and ensure `azure-identity` is installed |
| Database connection refused | Ensure `docker compose up -d` is running and `.env` has correct credentials |
| Embeddings not generated | Check `AI_EMBEDDING_DIMENSIONS` in `.env` (default: 1536) |
| Bot not responding in group | Ensure the bot has been granted admin/message access in the group |
| `/link` says "all projects linked" | All your projects already have groups; create a new project first |
| Deep link doesn't auto-link | The group may already be linked to another project |

---

## Project Structure

```
src/bot/
├── __init__.py              # Package root
├── __main__.py              # Entry point (python -m bot)
├── config.py                # Settings from .env via pydantic-settings
├── adapters/                # Platform-specific code
│   ├── base.py              # Abstract PlatformAdapter interface
│   └── telegram/            # Telegram implementation
│       ├── bot.py           # TelegramAdapter (polling, command scopes)
│       ├── handlers.py      # /start, /myprojects
│       ├── project_handlers.py   # /newproject wizard
│       ├── project_resolver.py   # Unified project resolution
│       ├── stage_handlers.py     # /stages, /launch
│       ├── budget_handlers.py    # /budget, /expenses
│       ├── report_handlers.py    # /report, /status, quick commands
│       ├── role_handlers.py      # /team, /invite, /myrole
│       ├── ai_handlers.py        # /ask, /backfill, voice/photo/text
│       ├── group_handlers.py     # /link, deep links, bot added/removed
│       ├── notification_handlers.py  # Checkpoint approvals, status changes
│       ├── fsm_states.py        # FSM state groups
│       ├── keyboards.py         # Inline keyboard builders
│       ├── formatters.py        # Message formatting helpers
│       ├── filters.py           # Custom aiogram filters
│       └── middleware.py        # RoleMiddleware
├── core/                    # Business logic (platform-independent)
│   ├── project_service.py   # Project creation & management
│   ├── stage_service.py     # Stage lifecycle
│   ├── stage_templates.py   # Default stage definitions
│   ├── budget_service.py    # Budget tracking
│   ├── report_service.py    # Report generation
│   ├── role_service.py      # Role management
│   ├── notification_service.py  # Notification definitions
│   ├── scheduler.py         # Background task scheduler
│   └── states.py            # Core state definitions
├── db/                      # Database layer
│   ├── models.py            # SQLAlchemy ORM models
│   ├── repositories.py      # Data access queries
│   ├── session.py           # Async engine & session factory
│   └── migrations/          # Alembic migration scripts
└── services/                # External services
    ├── ai_client.py         # Multi-provider AI client factory
    ├── embedding_service.py # Vector embedding generation
    ├── media_service.py     # Voice/image processing
    ├── nlp_parser.py        # Natural language stage parsing
    └── rag_service.py       # RAG pipeline for AI context
```

## Architecture

The codebase follows a layered design:

1. **Adapters** — translate platform messages (Telegram, WhatsApp) to/from a common format
2. **Core** — conversation flows, state machines, business rules — never imports platform libraries
3. **Data** — SQLAlchemy models, database queries, embeddings

### Project Resolution

All command handlers use a unified project resolution system (`project_resolver.py`):

- **Group chat** → auto-resolves to the project linked to that group
- **Private chat, 1 project** → auto-resolves to that project
- **Private chat, N projects** → shows an inline picker, dispatches via FSM intent
- **No projects** → prompts user to create one with `/newproject`

This ensures consistent behavior across all commands and chat types.

## License

TBD
