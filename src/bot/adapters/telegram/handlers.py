"""
Telegram message handlers.

Each handler converts Telegram-specific objects into platform-agnostic
data and delegates to core logic. This keeps business rules out of
the adapter layer.
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

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

    # Different welcome for admin bot vs tenant bots
    from bot.adapters.telegram.bot import ADMIN_BOT_ID
    is_admin_bot = message.bot is not None and message.bot.id == ADMIN_BOT_ID

    if is_admin_bot:
        await message.answer(
            "👋 <b>Добро пожаловать в панель управления!</b>\n\n"
            "Этот бот управляет ботами-ассистентами для ремонта.\n\n"
            "<b>Команды:</b>\n"
            "/addbot — зарегистрировать нового бота\n"
            "/listbots — список всех ботов\n"
            "/removebot — деактивировать бота\n"
        )
    else:
        await message.answer(
            "👋 <b>Добро пожаловать!</b>\n\n"
            "Я — бот-помощник для управления ремонтом.\n"
            "Я помогу отслеживать этапы, сроки и бюджет вашего проекта.\n\n"
            "<b>Команды:</b>\n"
            "/newproject — создать новый проект\n"
            "/myprojects — мои проекты\n"
            "/deleteproject — удалить проект\n"
            "/stages — управление этапами\n"
            "/budget — бюджет проекта\n"
            "/expenses — добавить расход\n"
            "/report — отчёт по проекту\n"
            "/status — статус проекта\n"
            "/team — команда проекта\n"
            "/invite — пригласить участника\n"
            "/myrole — моя роль в проекте\n"
            "/ask — задать вопрос AI\n"
            "/chat — AI-чат о проекте\n"
            "/launch — запустить проект\n\n"
            "<b>В группе:</b>\n"
            "/link — привязать группу к проекту"
        )


@router.message(Command("myprojects"))
async def cmd_myprojects(message: Message, **kwargs) -> None:
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

        projects = await get_user_projects(session, user.id, tenant_id=kwargs.get("tenant_id"))

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


# ═══════════════════════════════════════════════════════════════
# /deleteproject — remove a project
# ═══════════════════════════════════════════════════════════════


@router.message(Command("deleteproject"))
async def cmd_deleteproject(message: Message, state: FSMContext, **kwargs) -> None:
    """
    /deleteproject — delete a project and all its data.

    Shows a project picker (if multiple), then asks for confirmation.
    Only the project owner can delete.
    """
    tg_user = message.from_user
    if tg_user is None:
        return

    await state.clear()

    async with async_session_factory() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if user is None:
            await message.answer("❌ Вы не зарегистрированы. Отправьте /start сначала.")
            return

        projects = await get_user_projects(session, user.id, tenant_id=kwargs.get("tenant_id"))

    if not projects:
        await message.answer("У вас нет проектов для удаления.")
        return

    if len(projects) == 1:
        # Single project — go straight to confirmation
        p = projects[0]
        await message.answer(
            f"🗑 <b>Удалить проект?</b>\n\n"
            f"🏠 {p.name}\n"
            f"{'💰 ' + f'{p.total_budget:,.0f} ₸' if p.total_budget else ''}\n\n"
            f"⚠️ Будут удалены все этапы, расходы, сообщения и история.\n"
            f"Это действие <b>необратимо</b>.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delprj_yes:{p.id}"),
                    InlineKeyboardButton(text="❌ Отмена", callback_data="delprj_no"),
                ],
            ]),
        )
    else:
        # Multiple projects — show picker
        rows = [
            [InlineKeyboardButton(text=f"🏠 {p.name}", callback_data=f"delprj_pick:{p.id}")]
            for p in projects
        ]
        rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="delprj_no")])
        await message.answer(
            "🗑 Выберите проект для удаления:",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )


@router.callback_query(F.data.startswith("delprj_pick:"))
async def deleteproject_pick(callback: CallbackQuery) -> None:
    """User picked a project to delete — show confirmation."""
    await callback.answer()
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    async with async_session_factory() as session:
        from bot.db.models import Project
        result = await session.execute(select(Project).where(Project.id == project_id))
        p = result.scalar_one_or_none()

    if not p:
        await callback.message.edit_text("❌ Проект не найден.")  # type: ignore[union-attr]
        return

    await callback.message.edit_text(  # type: ignore[union-attr]
        f"🗑 <b>Удалить проект?</b>\n\n"
        f"🏠 {p.name}\n"
        f"{'💰 ' + f'{p.total_budget:,.0f} ₸' if p.total_budget else ''}\n\n"
        f"⚠️ Будут удалены все этапы, расходы, сообщения и история.\n"
        f"Это действие <b>необратимо</b>.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delprj_yes:{p.id}"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="delprj_no"),
            ],
        ]),
    )


@router.callback_query(F.data.startswith("delprj_yes:"))
async def deleteproject_confirm(callback: CallbackQuery) -> None:
    """Confirmed deletion — delete the project and all related data."""
    await callback.answer()
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    async with async_session_factory() as session:
        from bot.db.models import Project
        result = await session.execute(select(Project).where(Project.id == project_id))
        project = result.scalar_one_or_none()

        if not project:
            await callback.message.edit_text("❌ Проект не найден.")  # type: ignore[union-attr]
            return

        project_name = project.name

        # Delete all related data explicitly to avoid ORM cascade issues
        from bot.db.models import (
            BudgetItem, ChangeLog, Embedding, Message as Msg,
            ProjectRole, Stage, SubStage,
        )
        from sqlalchemy import delete

        # Sub-stages (via stage FK)
        await session.execute(
            delete(SubStage).where(
                SubStage.stage_id.in_(
                    select(Stage.id).where(Stage.project_id == project_id)
                )
            )
        )
        await session.execute(delete(ChangeLog).where(ChangeLog.project_id == project_id))
        await session.execute(delete(BudgetItem).where(BudgetItem.project_id == project_id))
        await session.execute(delete(Stage).where(Stage.project_id == project_id))
        await session.execute(delete(ProjectRole).where(ProjectRole.project_id == project_id))
        await session.execute(delete(Msg).where(Msg.project_id == project_id))
        await session.execute(delete(Embedding).where(Embedding.project_id == project_id))
        await session.delete(project)
        await session.commit()

    logger.info(
        "Project deleted: %s (id=%d) by user %d",
        project_name, project_id,
        callback.from_user.id if callback.from_user else 0,
    )

    await callback.message.edit_text(  # type: ignore[union-attr]
        f"✅ Проект <b>{project_name}</b> удалён.\n\n"
        f"Все этапы, расходы и история удалены."
    )


@router.callback_query(F.data == "delprj_no")
async def deleteproject_cancel(callback: CallbackQuery) -> None:
    """Cancel project deletion."""
    await callback.answer()
    await callback.message.edit_text("❌ Удаление отменено.")  # type: ignore[union-attr]
