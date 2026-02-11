# Renovation Chatbot — Project Instructions

## Project Overview

A messaging chatbot that acts as a digital assistant for home renovation projects. It tracks stages, deadlines, budgets, and communications between homeowners, contractors, designers, and tradespeople. The bot creates a renovation "passport," forms work stages, assigns deadlines, monitors progress, and accompanies the project through to final acceptance.

**Core mission:** Control deadlines, stages, and budget of a renovation project.

**Platform strategy:** The architecture must support multiple messaging platforms (Telegram, WhatsApp). The MVP and initial prototype use **Telegram** because of its superior bot API, inline keyboards, group chat management, and free bot hosting. WhatsApp support will be added later via the same core logic with a platform-specific adapter.

---

## Tech Stack

- **Database:** PostgreSQL 17 with TimescaleDB (via `timescale/timescaledb-ha:pg17`)
- **Vector extension:** pgvector (HNSW index) — for AI-powered text understanding and semantic search. Sufficient for MVP scale (thousands to tens of thousands of vectors). pgvectorscale/DiskANN available in the image if scaling past 100k+ vectors later.
- **Language:** Python 3.12+
- **Bot framework:** aiogram 3.x (async Telegram bot framework)
- **Web framework:** FastAPI (webhooks, future REST API)
- **AI/LLM:** Azure OpenAI (`openai` Python SDK) — chat completions + embeddings (`text-embedding-3-small`)
- **ORM:** SQLAlchemy 2.0 (async) + asyncpg driver
- **Migrations:** Alembic
- **Validation:** Pydantic v2 (also powers FastAPI)
- **Container orchestration:** Docker Compose
- **Bot platform (MVP):** Telegram — chosen for richer bot API, inline keyboards, group chat support, and simpler development
- **Future platforms:** WhatsApp (via WhatsApp Business API / Cloud API)

### Architecture Note — Multi-Platform Design

All bot logic must be **platform-agnostic**. The codebase should follow a layered architecture:

1. **Platform adapters** (Telegram, WhatsApp) — handle incoming messages, send replies, manage platform-specific features (inline keyboards, buttons, media)
2. **Core bot logic** — conversation flows, state machines, business rules (platform-independent)
3. **Data layer** — database access, queries, embeddings

Platform-specific code (Telegram API calls, WhatsApp webhook parsing) must be isolated in adapter modules, never mixed into core logic.

### Message Handling Strategy

Users may send different types of messages: **text**, **images (photos)**, and **voice messages**. The bot must handle all of them, but the core principle is:

> **Every incoming message — regardless of type — must be converted to a text representation and stored in the database.** This text is the basis for the RAG system, semantic search, budgeting, reporting, and planning.

Message processing pipeline per type:

| Message Type | Processing | Stored Text |
|---|---|---|
| **Text** | Used as-is | Original message text |
| **Voice** | Transcribed via Azure OpenAI Whisper (or similar STT) | Transcription result |
| **Image/Photo** | Caption extracted; optional OCR or GPT-4 Vision description | Caption + AI-generated description |

Implementation approach:
1. **Phase 1–3 (MVP):** Only text messages are processed. Voice and image messages are acknowledged but not parsed.
2. **Phase 8+:** Voice transcription (STT) and image understanding are added. All historical messages already have the `message_type` field, so they can be backfilled.
3. **Storage:** Every message is stored in a `messages` table with its type, raw content reference (file IDs, URLs), transcribed text, and link to the project. The transcribed text is embedded via pgvector for semantic search.
4. **Platform adapters** are responsible for downloading media files and passing them to core services for transcription/description. Core logic never calls platform-specific download APIs.

---

## Requirements Summary (translated from Russian originals in `/Requirements/`)

### Document 1 — Final Bot Flow (`1 Final_Remont_Bot_Flow.docx`)

#### Project Kickoff (Steps 1–6)

1. **Property name** — user provides the property/object name
2. **Address** — user provides the renovation address
3. **Renovation type** — Cosmetic | Standard | Major | Designer
4. **Total budget** — user sets the overall budget
5. **Coordinator** — Who manages the renovation: Self | Foreman | Designer
   - If Foreman or Designer is selected, the bot requests their contact info
6. **Second client** (optional) — e.g. spouse

#### Stage Formation (auto-generated, editable)

Standard renovation stages:

1. Demolition
2. Electrical
3. Plumbing
4. Plastering
5. Floor screed
6. Tiling
7. Putty/spackling
8. Painting or wallpaper
9. Flooring
10. Door installation
11. Finish electrical
12. Finish plumbing
13. Final acceptance

#### Parallel Stages (custom furniture & fittings)

Bot asks if custom items are being ordered: Kitchen, Wardrobes, Walk-in closet, Custom doors.

If yes, parallel sub-stages are created: Measurement → Contract & prepayment → Production → Delivery → Installation.

#### Deadline Assignment

For each stage, the coordinator sets:
- Responsible person
- Start date
- End date
- Stage budget

Options: specify duration in days, or exact start/end dates.

#### Project Launch Summary

Bot summarizes: Property, Renovation type, Total budget, Coordinator, First stage → project is considered launched.

#### Bot Behavior During Renovation

- Monitors stage deadlines
- Reminds responsible parties about deadlines
- Requests work status updates
- Records expenses and payments
- Stores budget change history
- Warns about overspending
- Sends weekly reports to the client

#### Sub-stages Within Each Stage

Each stage contains sub-stages. Example for "Demolition":
- Remove bathroom tiles
- Remove plumbing fixtures
- Tear down partition wall

Each sub-stage has: Status, Deadline, Responsible person.

#### Checkpoints & Reminders

Bot automatically:
- Reminds about stage completion 1 day before deadline
- Warns about overdue items
- Reminds to order furniture 30–45 days before installation
- Suggests calling an expert before paying for a stage

#### Final Acceptance

- Verifies all work is complete
- Records defects/remarks
- Summarizes the budget
- Closes the renovation project

---

### Document 2 — MVP Technical Description (`2 Chatbot_Remont_MVP.docx`)

#### AI-Powered Text Processing

The bot uses a text-based AI to parse natural language. Example: a foreman writes "demolition will take 2 weeks, 3 days to remove tiles in bathroom and kitchen, 3 days to lift the floor, 4 days to strip wallpaper, 2 days to remove doors, and 1 day to haul debris." The bot extracts the total duration, creates a DEMOLITION stage (e.g. Jan 1–15, 2026) with sub-stages and their dates.

#### Project Block

- Property name, Address, Area
- Renovation type (cosmetic, standard, major, designer)
- Participants: Client, Electrician, Plumber, Tiler, Other tradespeople

#### Stage Statuses

- Planned
- In progress
- Completed
- Delayed

#### Checkpoints (require client approval before next stage)

| Checkpoint | Example |
|---|---|
| Electrical check before plastering | Verify socket count and positions match the plan |
| Plumbing check before tiling | Verify shower, faucet, and toilet outlet positions match the plan |
| Tile check before full payment | Most common point to call an expert for quality verification |
| Putty/spackling check before painting | Important quality checkpoint |
| Final acceptance | Overall completion check |

An expert can be called at any checkpoint (or any time on request).

#### Budget Categories

Electrical, Plumbing, Walls, Flooring, Tiling, Ceilings, Doors, Furniture, Other.

Each category tracks: Work costs, Materials, Prepayments, Remaining balance.

#### Change History

For every change: Original amount → New amount → Difference → Date → Who confirmed.

#### Payment Logic

Stage lifecycle: Recorded → In progress → Verified → Paid → Closed.

If a stage is not closed, the bot warns the client about payment risk.

#### Reminders

- Reminds tradespeople about deadlines
- Warns about delays
- Notifies client about checkpoints
- Tracks budget overspending

#### Reports

Weekly or on-demand: Completed stages, Current work, Deadline deviations, Budget status.

#### Quick Commands

`budget`, `stages`, `expenses`, `next stage`, `expert`

#### Expert Feature (add-on)

- Call an expert for a specific stage
- Video consultation
- Get recommendations before paying for a stage

---

### Document 3 — Roles & Permissions (`3 Chatbot_Roles_Scheme.docx`)

#### Roles

**Clients:**
| Role | Description |
|---|---|
| Owner (Primary Client) | Creates project, assigns participants, approves everything |
| Co-owner (e.g. spouse) | Views budget/stages/reports, cannot confirm final amounts by default |
| Viewer | Observation only |

**Workers:**
| Role | Description |
|---|---|
| Foreman / Coordinator | Updates stage statuses, proposes deadlines and expenses, cannot confirm budget |
| Tradesperson (electrician, plumber, tiler, etc.) | Receives reminders, sends status/photos, proposes additional work, cannot confirm amounts |
| Designer | Records material choices, comments on stages, cannot confirm budget |
| Supplier (optional) | Confirms delivery, sends invoices, cannot confirm budget |

**Service Experts:**
| Role | Description |
|---|---|
| Video Expert | Conducts video consultations |
| Technical Supervision | Quality inspection |

#### Communication Channels

- **Group chat per property:** All participants + bot
- **Private chats:** Client ↔ Bot, Tradesperson ↔ Bot, Expert ↔ Bot

Important: For the bot to send private messages, each participant must first send a START command to the bot.

#### Confirmation Rules

- Only the Owner can confirm all amounts
- Co-owner has view-only access by default
- Budget changes are versioned: old amount → new amount → confirmation required

#### Notifications

| Recipient | Notifications |
|---|---|
| Client | Reports on request, overspending alerts, checkpoint reminders |
| Tradesperson | Deadline reminders, stage status requests, inspection reminders |

#### Quick Commands by Role

| Client | Tradesperson |
|---|---|
| `budget` | `my stage` |
| `stages` | `status` |
| `expenses` | `deadline` |
| `report` | `send photo` |
| `next stage` | |

#### MVP Roles

Roles: Owner, Co-owner, Tradesperson, Expert

Features: Stages & deadlines, Budget with confirmations, Tradesperson reminders, Client reports on demand, Change history.

---

### Document 4 — Typical Chat Scenarios (`4 Remont_Bot_Tipovye_Scenarii_Chatov.docx`)

#### Scenario 1: Renovation via Foreman

Chat members: Client, Co-client (optional), Foreman, Bot

- Bot reminds foreman about deadlines and stages
- Foreman updates work statuses
- Client receives reports and risk warnings
- Client confirms budgets and payments

#### Scenario 2: Renovation via Designer

Chat members: Client, Co-client (optional), Designer, Bot

- Designer manages tradespeople and material decisions
- Bot reminds designer about deadlines and checkpoints
- Client receives reports and confirms budgets

#### Scenario 3: Direct Renovation (no foreman)

Chat members: Client, Tradespeople (electrician, plumber, tiler, etc.), Bot

- Bot reminds tradespeople about stage deadlines
- Tradespeople send statuses and work photos
- Client confirms stages and payments

#### Scenario 4: Minimal Format

Chat members: Client, Bot

- Bot tracks stages and budget
- Client manually records expenses and deadlines
- Bot reminds about checkpoints

#### Scenario 5: Extended Format with Expert

Chat members: Client, Coordinator (foreman or designer), Bot

- Expert joins on request for specific stages
- Before paying for a stage, client can call an expert (paid add-on)
- Expert conducts video consultation
- Bot records inspection results

#### Common Logic Across All Scenarios

- Bot creates the renovation property record
- Records stages, deadlines, and budget
- Reminds about checkpoints
- Sends reports to the client
- Stores full change history

---

## Development Plan

### Phase 1 — Foundation & Infrastructure

- [x] Set up PostgreSQL + TimescaleDB via Docker Compose
- [x] Design database schema: projects, stages, sub-stages, budgets, users, roles, change history, messages
- [x] Enable pgvector extension (HNSW indexes for vector search)
- [x] Set up Telegram bot skeleton with webhook/polling
- [x] Define platform adapter interface for future multi-platform support (with message type support: text, voice, image)
- [x] Implement user registration & START command handling

### Phase 2 — Project Creation Flow

- [ ] Implement guided project creation (property name, address, type, budget, coordinator)
- [ ] Add second client (co-owner) flow
- [ ] Auto-generate standard renovation stages
- [ ] Allow stage list editing (add/remove/reorder)
- [ ] Implement parallel stages for custom furniture/fittings

### Phase 3 — Deadline & Assignment Management

- [ ] Implement deadline assignment per stage (duration or exact dates)
- [ ] Assign responsible person per stage
- [ ] Set budget per stage
- [ ] Sub-stage creation within stages
- [ ] Project launch summary and confirmation

### Phase 4 — Roles & Permissions

- [ ] Implement role system: Owner, Co-owner, Foreman, Tradesperson, Designer, Expert
- [ ] Role-based command access
- [ ] Group chat + private chat logic
- [ ] START command requirement for private messaging

### Phase 5 — Active Monitoring & Notifications

- [ ] Deadline tracking and reminders (1 day before, overdue alerts)
- [ ] Stage status update prompts to responsible parties
- [ ] Checkpoint logic (approval gates between stages)
- [ ] Furniture order reminders (30–45 days before installation)
- [ ] Overspending alerts

### Phase 6 — Budget & Payment Tracking

- [ ] Budget tracking by category (electrical, plumbing, walls, etc.)
- [ ] Work vs. materials vs. prepayments breakdown
- [ ] Stage payment lifecycle: Recorded → In progress → Verified → Paid → Closed
- [ ] Budget change history with confirmation workflow
- [ ] Payment risk warnings for unverified stages

### Phase 7 — Reporting & Quick Commands

- [ ] Weekly automated report to client
- [ ] On-demand reports via quick commands
- [ ] Implement all quick commands: `budget`, `stages`, `expenses`, `report`, `next stage`, `my stage`, `status`, `deadline`, `send photo`, `expert`

### Phase 8 — AI Text Processing & Media Understanding

- [ ] Integrate LLM for natural language parsing of stage descriptions
- [ ] Auto-extract durations, sub-stages, and dates from foreman/designer messages
- [ ] Embed project documents and chat history using pgvector (HNSW) for semantic search
- [ ] RAG pipeline for context-aware bot responses
- [ ] Voice message transcription via Azure OpenAI Whisper (STT)
- [ ] Image understanding: caption extraction, optional OCR / GPT-4 Vision description
- [ ] Backfill embeddings for historical voice/image messages

### Phase 9 — Expert Integration

- [ ] Expert request flow per stage
- [ ] Video consultation scheduling
- [ ] Expert report recording and attachment to stage
- [ ] Paid add-on billing logic

### Phase 10 — Final Acceptance & Project Closure

- [ ] Final acceptance checklist: verify all stages complete
- [ ] Defect/remark recording
- [ ] Final budget summary
- [ ] Project closure and archival

---

## Coding Conventions

- Use environment variables from `.env` for all secrets (DB credentials, API keys)
- Never commit `.env` — use `.env.example` as template
- All database migrations should be versioned and reversible
- Bot messages should support Russian language
- Use ISO 8601 for all date handling internally
- Log all budget changes with immutable audit trail
- **Platform isolation:** Never import Telegram-specific (or WhatsApp-specific) libraries in core bot logic. All platform interactions go through adapter interfaces.
- Keep message formatting in templates/helpers that can be overridden per platform (Telegram Markdown vs WhatsApp plain text)

### Python Conventions

- Use `async`/`await` throughout — aiogram, FastAPI, SQLAlchemy, and asyncpg are all async-native
- Type-hint all function signatures; use Pydantic models for data boundaries
- Use `pydantic-settings` for configuration (loads from `.env` automatically)
- Structure the project as a Python package with clear module boundaries:
  - `adapters/` — platform-specific code (Telegram, WhatsApp)
  - `core/` — business logic, conversation flows, state machines
  - `db/` — models, repositories, migrations
  - `services/` — AI/LLM integration, embedding generation
- Prefer dependency injection over global state
- Use `logging` module with structured log output
- Pin all dependencies in `requirements.txt` or use `pyproject.toml` with locked versions
