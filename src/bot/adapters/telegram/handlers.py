"""
Telegram message handlers.

Each handler converts Telegram-specific objects into platform-agnostic
data and delegates to core logic. This keeps business rules out of
the adapter layer.
"""

import logging

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from bot.db.models import User
from bot.db.repositories import get_user_by_telegram_id, get_user_projects
from bot.db.session import async_session_factory

from sqlalchemy import select

logger = logging.getLogger(__name__)
router = Router(name="telegram_handlers")


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    """
    Handle /start command — register user and confirm bot activation.

    This is required before the bot can send private messages to a user.
    The handler:
    1. Checks if the user already exists in the database
    2. Creates a new User record if not
    3. Marks is_bot_started = True
    4. Sends a welcome message
    """
    tg_user = message.from_user
    if tg_user is None:
        return

    async with async_session_factory() as session:
        # Look up existing user by telegram_id
        result = await session.execute(
            select(User).where(User.telegram_id == tg_user.id)
        )
        user = result.scalar_one_or_none()

        if user is None:
            # First time — create user record
            user = User(
                telegram_id=tg_user.id,
                full_name=tg_user.full_name or "Unknown",
                is_bot_started=True,
            )
            session.add(user)
            logger.info("New user registered: %s (tg_id=%d)", tg_user.full_name, tg_user.id)
        else:
            # Returning user — ensure bot is marked as started
            user.is_bot_started = True
            logger.info("Returning user: %s (tg_id=%d)", tg_user.full_name, tg_user.id)

        await session.commit()

    await message.answer(
        "👋 <b>Добро пожаловать!</b>\n\n"
        "Я — бот-помощник для управления ремонтом.\n"
        "Я помогу отслеживать этапы, сроки и бюджет вашего проекта.\n\n"
        "<b>Команды:</b>\n"
        "/newproject — создать новый проект\n"
        "/myprojects — мои проекты\n"
        "/stages — управление этапами\n"
        "/budget — бюджет проекта\n"
        "/report — отчёт по проекту\n"
        "/team — команда проекта\n"
        "/invite — пригласить участника\n"
        "/myrole — моя роль в проекте\n"
        "/ask — задать вопрос AI\n\n"
        "<b>В группе:</b>\n"
        "/link — привязать группу к проекту"
    )


@router.message(Command("myprojects"))
async def cmd_myprojects(message: Message) -> None:
    """
    /myprojects — list all projects the user is a member of.

    Shows project name, type, budget, and linked group status.
    """
    tg_user = message.from_user
    if tg_user is None:
        return

    async with async_session_factory() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if user is None:
            await message.answer(
                "❌ Вы не зарегистрированы. Отправьте /start сначала."
            )
            return

        projects = await get_user_projects(session, user.id)

    if not projects:
        await message.answer(
            "У вас нет проектов.\n"
            "Создайте первый проект командой /newproject"
        )
        return

    lines = ["📋 <b>Мои проекты:</b>\n"]
    for i, p in enumerate(projects, 1):
        status = "🟢" if p.is_active else "⏸"
        budget_str = f" | 💰 {p.total_budget:,.0f} ₸" if p.total_budget else ""
        group_str = " | 👥 Группа" if p.telegram_chat_id else ""
        lines.append(f"{status} {i}. <b>{p.name}</b>{budget_str}{group_str}")

    lines.append(f"\nВсего проектов: {len(projects)}")

    await message.answer("\n".join(lines))
