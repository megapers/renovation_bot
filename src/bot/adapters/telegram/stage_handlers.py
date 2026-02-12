"""
Telegram handlers for stage management — deadlines, assignments,
budgets, sub-stages, and project launch.

Commands:
  /stages  — list stages for the current project
  /launch  — launch the project (start renovation)

All inline-keyboard interactions for stage configuration are handled
here via callback query handlers.
"""

import logging
from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.adapters.telegram.keyboards import (
    back_to_stage_keyboard,
    date_method_keyboard,
    launch_keyboard,
    project_select_keyboard,
    stage_actions_keyboard,
    stages_list_keyboard,
    substages_keyboard,
)
from bot.core.stage_service import (
    format_date,
    format_launch_summary,
    format_stage_detail,
    format_stages_overview,
    parse_date,
    validate_launch_readiness,
)
from bot.core.states import StageSetup
from bot.db.repositories import (
    create_sub_stages_bulk,
    get_previous_stage,
    get_stage_with_substages,
    get_stages_for_project,
    get_user_by_telegram_id,
    get_user_projects,
    launch_project,
    update_stage,
)
from bot.db.session import async_session_factory

logger = logging.getLogger(__name__)
router = Router(name="stage_setup")


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════


async def _ensure_user(message: Message | CallbackQuery) -> int | None:
    """
    Get the internal user ID from a Telegram message/callback.

    Returns None and sends error if user not found.
    """
    tg_user = message.from_user if isinstance(message, Message) else message.from_user
    if tg_user is None:
        return None

    async with async_session_factory() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if user is None:
            target = message if isinstance(message, Message) else message.message
            await target.answer(  # type: ignore[union-attr]
                "❌ Вы не зарегистрированы. Отправьте /start сначала."
            )
            return None
        return user.id


async def _show_stages_list(
    target: Message,
    state: FSMContext,
    project_id: int,
) -> None:
    """Load and display the stages list for a project."""
    async with async_session_factory() as session:
        stages = await get_stages_for_project(session, project_id)

    if not stages:
        await target.answer("В проекте нет этапов.")
        return

    text = format_stages_overview(list(stages))
    await target.answer(
        text + "\n\nНажмите на этап для настройки:",
        reply_markup=stages_list_keyboard(stages),
    )
    await state.set_state(StageSetup.viewing_stages)
    await state.update_data(project_id=project_id)


async def _show_stage_detail(
    target: Message,
    state: FSMContext,
    stage_id: int,
    edit: bool = False,
) -> None:
    """Load and display a single stage's details."""
    async with async_session_factory() as session:
        stage = await get_stage_with_substages(session, stage_id)

    if stage is None:
        await target.answer("❌ Этап не найден.")
        return

    text = format_stage_detail(stage)

    if edit:
        await target.edit_text(text, reply_markup=stage_actions_keyboard(stage_id))
    else:
        await target.answer(text, reply_markup=stage_actions_keyboard(stage_id))

    await state.set_state(StageSetup.viewing_stage_detail)
    await state.update_data(stage_id=stage_id, project_id=stage.project_id)


# ═══════════════════════════════════════════════════════════════
# ENTRY POINTS
# ═══════════════════════════════════════════════════════════════


@router.message(Command("stages"))
async def cmd_stages(message: Message, state: FSMContext) -> None:
    """
    /stages — show project stages.

    If the user has one project, show its stages.
    If multiple, show a project selection keyboard.
    """
    await state.clear()

    tg_user = message.from_user
    if tg_user is None:
        return

    async with async_session_factory() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if user is None:
            await message.answer("❌ Вы не зарегистрированы. Отправьте /start сначала.")
            return

        projects = await get_user_projects(session, user.id)

    if not projects:
        await message.answer(
            "У вас нет активных проектов.\n"
            "Создайте проект командой /newproject"
        )
        return

    if len(projects) == 1:
        await _show_stages_list(message, state, projects[0].id)
    else:
        await state.set_state(StageSetup.selecting_project)
        await message.answer(
            "Выберите проект:",
            reply_markup=project_select_keyboard(projects),
        )


@router.message(Command("launch"))
async def cmd_launch(message: Message, state: FSMContext) -> None:
    """
    /launch — show project launch summary and confirmation.

    Same project selection logic as /stages.
    """
    await state.clear()

    tg_user = message.from_user
    if tg_user is None:
        return

    async with async_session_factory() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if user is None:
            await message.answer("❌ Вы не зарегистрированы. Отправьте /start сначала.")
            return

        projects = await get_user_projects(session, user.id)

    if not projects:
        await message.answer(
            "У вас нет активных проектов.\n"
            "Создайте проект командой /newproject"
        )
        return

    # For launch, pick the first project (or show selection if multiple)
    if len(projects) == 1:
        await _show_launch_screen(message, state, projects[0].id)
    else:
        await state.set_state(StageSetup.selecting_project)
        await state.update_data(intent="launch")
        await message.answer(
            "Выберите проект для запуска:",
            reply_markup=project_select_keyboard(projects),
        )


async def _show_launch_screen(
    target: Message,
    state: FSMContext,
    project_id: int,
) -> None:
    """Display the launch summary and confirmation buttons."""
    from bot.db.repositories import get_project_with_stages

    async with async_session_factory() as session:
        project = await get_project_with_stages(session, project_id)

    if project is None:
        await target.answer("❌ Проект не найден.")
        return

    text = format_launch_summary(project)
    is_ready, _ = validate_launch_readiness(project)

    await target.answer(text, reply_markup=launch_keyboard(is_ready=is_ready))
    await state.set_state(StageSetup.confirming_launch)
    await state.update_data(project_id=project_id)


# ═══════════════════════════════════════════════════════════════
# PROJECT SELECTION
# ═══════════════════════════════════════════════════════════════


@router.callback_query(StageSetup.selecting_project, F.data.startswith("prjsel:"))
async def select_project(callback: CallbackQuery, state: FSMContext) -> None:
    """User selected a project from the list."""
    await callback.answer()
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    data = await state.get_data()

    if data.get("intent") == "launch":
        await _show_launch_screen(
            callback.message, state, project_id  # type: ignore[arg-type]
        )
    else:
        await _show_stages_list(
            callback.message, state, project_id  # type: ignore[arg-type]
        )


# ═══════════════════════════════════════════════════════════════
# STAGE LIST & DETAIL NAVIGATION
# ═══════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith("stg:"))
async def view_stage_detail(callback: CallbackQuery, state: FSMContext) -> None:
    """Show details for a single stage."""
    await callback.answer()
    stage_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    await _show_stage_detail(
        callback.message, state, stage_id, edit=True  # type: ignore[arg-type]
    )


@router.callback_query(F.data == "stgback")
async def back_to_stages(callback: CallbackQuery, state: FSMContext) -> None:
    """Return to the stages list."""
    await callback.answer()
    data = await state.get_data()
    project_id = data.get("project_id")
    if project_id is None:
        await callback.message.answer("❌ Проект не найден. Отправьте /stages")  # type: ignore[union-attr]
        await state.clear()
        return

    await _show_stages_list(
        callback.message, state, project_id  # type: ignore[arg-type]
    )


# ═══════════════════════════════════════════════════════════════
# DATE ASSIGNMENT
# ═══════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith("stgdt:"))
async def show_date_method(callback: CallbackQuery, state: FSMContext) -> None:
    """Show date entry method selection: duration or exact dates."""
    await callback.answer()
    stage_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    await callback.message.edit_text(  # type: ignore[union-attr]
        "📅 <b>Как указать сроки?</b>\n\n"
        "Выберите способ:",
        reply_markup=date_method_keyboard(stage_id),
    )


@router.callback_query(F.data.startswith("stgdur:"))
async def start_duration_mode(callback: CallbackQuery, state: FSMContext) -> None:
    """Duration mode: ask for start date first."""
    await callback.answer()
    stage_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    # Check if previous stage has an end date we can suggest
    hint = ""
    async with async_session_factory() as session:
        stage = await get_stage_with_substages(session, stage_id)
        if stage:
            prev = await get_previous_stage(session, stage)
            if prev and prev.end_date:
                suggested = prev.end_date + timedelta(days=1)
                hint = (
                    f"\n\n💡 Предыдущий этап «{prev.name}» заканчивается "
                    f"{format_date(prev.end_date)}.\n"
                    f"Можете ввести {format_date(suggested)}"
                )

    await state.set_state(StageSetup.setting_start_date)
    await state.update_data(stage_id=stage_id, date_mode="duration")
    await callback.message.answer(  # type: ignore[union-attr]
        f"📅 Введите <b>дату начала</b> этапа (ДД.ММ.ГГГГ):{hint}"
    )


@router.callback_query(F.data.startswith("stgex:"))
async def start_exact_dates_mode(callback: CallbackQuery, state: FSMContext) -> None:
    """Exact dates mode: ask for start date."""
    await callback.answer()
    stage_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    # Same hint logic
    hint = ""
    async with async_session_factory() as session:
        stage = await get_stage_with_substages(session, stage_id)
        if stage:
            prev = await get_previous_stage(session, stage)
            if prev and prev.end_date:
                suggested = prev.end_date + timedelta(days=1)
                hint = (
                    f"\n\n💡 Предыдущий этап «{prev.name}» заканчивается "
                    f"{format_date(prev.end_date)}.\n"
                    f"Можете ввести {format_date(suggested)}"
                )

    await state.set_state(StageSetup.setting_start_date)
    await state.update_data(stage_id=stage_id, date_mode="exact")
    await callback.message.answer(  # type: ignore[union-attr]
        f"📅 Введите <b>дату начала</b> этапа (ДД.ММ.ГГГГ):{hint}"
    )


@router.message(StageSetup.setting_start_date)
async def process_start_date(message: Message, state: FSMContext) -> None:
    """Receive start date text input."""
    if not message.text or not message.text.strip():
        await message.answer("Пожалуйста, введите дату в формате ДД.ММ.ГГГГ:")
        return

    dt = parse_date(message.text)
    if dt is None:
        await message.answer(
            "❌ Неверный формат даты.\n"
            "Введите дату в формате <b>ДД.ММ.ГГГГ</b> (например: 15.03.2026):"
        )
        return

    data = await state.get_data()
    stage_id = data["stage_id"]
    date_mode = data.get("date_mode", "exact")

    # Save start date
    async with async_session_factory() as session:
        await update_stage(session, stage_id, start_date=dt)
        await session.commit()

    if date_mode == "duration":
        await state.set_state(StageSetup.setting_duration)
        await message.answer(
            f"✅ Дата начала: <b>{format_date(dt)}</b>\n\n"
            "⏱ Введите <b>длительность</b> этапа в днях:"
        )
    else:
        await state.set_state(StageSetup.setting_end_date)
        await message.answer(
            f"✅ Дата начала: <b>{format_date(dt)}</b>\n\n"
            "📅 Введите <b>дату окончания</b> этапа (ДД.ММ.ГГГГ):"
        )


@router.message(StageSetup.setting_duration)
async def process_duration(message: Message, state: FSMContext) -> None:
    """Receive duration in days, calculate end date."""
    if not message.text or not message.text.strip():
        await message.answer("Введите количество дней:")
        return

    try:
        days = int(message.text.strip())
        if days <= 0 or days > 365:
            raise ValueError
    except ValueError:
        await message.answer("Введите корректное число дней (1–365):")
        return

    data = await state.get_data()
    stage_id = data["stage_id"]

    async with async_session_factory() as session:
        stage = await get_stage_with_substages(session, stage_id)
        if stage is None or stage.start_date is None:
            await message.answer("❌ Ошибка: этап или дата начала не найдены.")
            await state.clear()
            return

        end_date = stage.start_date + timedelta(days=days)
        await update_stage(session, stage_id, end_date=end_date)
        await session.commit()

        # Reload for display
        stage = await get_stage_with_substages(session, stage_id)

    await message.answer(
        f"✅ Сроки установлены:\n"
        f"📅 {format_date(stage.start_date)} — {format_date(stage.end_date)} "  # type: ignore[union-attr]
        f"({days} дн.)"
    )
    await _show_stage_detail(message, state, stage_id)


@router.message(StageSetup.setting_end_date)
async def process_end_date(message: Message, state: FSMContext) -> None:
    """Receive end date text input."""
    if not message.text or not message.text.strip():
        await message.answer("Введите дату в формате ДД.ММ.ГГГГ:")
        return

    dt = parse_date(message.text)
    if dt is None:
        await message.answer(
            "❌ Неверный формат даты.\n"
            "Введите дату в формате <b>ДД.ММ.ГГГГ</b>:"
        )
        return

    data = await state.get_data()
    stage_id = data["stage_id"]

    async with async_session_factory() as session:
        stage = await get_stage_with_substages(session, stage_id)
        if stage is None:
            await message.answer("❌ Этап не найден.")
            await state.clear()
            return

        if stage.start_date and dt <= stage.start_date:
            await message.answer(
                f"❌ Дата окончания должна быть позже даты начала "
                f"({format_date(stage.start_date)}).\n"
                "Введите корректную дату:"
            )
            return

        await update_stage(session, stage_id, end_date=dt)
        await session.commit()

    await message.answer(
        f"✅ Сроки установлены:\n"
        f"📅 {format_date(stage.start_date)} — {format_date(dt)}"  # type: ignore[union-attr]
    )
    await _show_stage_detail(message, state, stage_id)


# ═══════════════════════════════════════════════════════════════
# RESPONSIBLE PERSON ASSIGNMENT
# ═══════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith("stgprs:"))
async def start_assign_person(callback: CallbackQuery, state: FSMContext) -> None:
    """Ask for the responsible person's name/contact."""
    await callback.answer()
    stage_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    # Show current value if any
    current = ""
    async with async_session_factory() as session:
        stage = await get_stage_with_substages(session, stage_id)
        if stage and stage.responsible_contact:
            current = f"\nТекущий: <b>{stage.responsible_contact}</b>\n"

    await state.set_state(StageSetup.assigning_person)
    await state.update_data(stage_id=stage_id)
    await callback.message.answer(  # type: ignore[union-attr]
        f"👤 <b>Назначение ответственного</b>\n{current}\n"
        "Введите имя и контакт ответственного\n"
        "(например: <i>Иван +77771234567</i> или <i>@ivan_master</i>):"
    )


@router.message(StageSetup.assigning_person)
async def process_assign_person(message: Message, state: FSMContext) -> None:
    """Receive responsible person contact."""
    if not message.text or not message.text.strip():
        await message.answer("Введите имя/контакт ответственного:")
        return

    data = await state.get_data()
    stage_id = data["stage_id"]
    contact = message.text.strip()

    async with async_session_factory() as session:
        await update_stage(session, stage_id, responsible_contact=contact)
        await session.commit()

    await message.answer(f"✅ Ответственный: <b>{contact}</b>")
    await _show_stage_detail(message, state, stage_id)


# ═══════════════════════════════════════════════════════════════
# STAGE BUDGET
# ═══════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith("stgbdg:"))
async def start_set_budget(callback: CallbackQuery, state: FSMContext) -> None:
    """Ask for the stage budget amount."""
    await callback.answer()
    stage_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    current = ""
    async with async_session_factory() as session:
        stage = await get_stage_with_substages(session, stage_id)
        if stage and stage.budget:
            current = f"\nТекущий бюджет: <b>{stage.budget:,.0f} ₸</b>\n"

    await state.set_state(StageSetup.setting_stage_budget)
    await state.update_data(stage_id=stage_id)
    await callback.message.answer(  # type: ignore[union-attr]
        f"💰 <b>Бюджет этапа</b>\n{current}\n"
        "Введите сумму бюджета для этого этапа (в тенге):"
    )


@router.message(StageSetup.setting_stage_budget)
async def process_stage_budget(message: Message, state: FSMContext) -> None:
    """Receive stage budget amount."""
    if not message.text or not message.text.strip():
        await message.answer("Введите сумму бюджета:")
        return

    text = message.text.strip().replace(" ", "").replace(",", ".")
    try:
        amount = float(text)
        if amount <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Введите корректную сумму (например: 500000):")
        return

    data = await state.get_data()
    stage_id = data["stage_id"]

    async with async_session_factory() as session:
        await update_stage(session, stage_id, budget=amount)
        await session.commit()

    await message.answer(f"✅ Бюджет этапа: <b>{amount:,.0f} ₸</b>")
    await _show_stage_detail(message, state, stage_id)


# ═══════════════════════════════════════════════════════════════
# SUB-STAGES
# ═══════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith("stgsub:"))
async def show_substages(callback: CallbackQuery, state: FSMContext) -> None:
    """Show sub-stages for a stage."""
    await callback.answer()
    stage_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    async with async_session_factory() as session:
        stage = await get_stage_with_substages(session, stage_id)

    if stage is None:
        await callback.message.answer("❌ Этап не найден.")  # type: ignore[union-attr]
        return

    if stage.sub_stages:
        text = f"📝 <b>Подзадачи — {stage.name}:</b>\n\n"
        for sub in stage.sub_stages:
            text += f"  {sub.order}. {sub.name}\n"
    else:
        text = f"📝 <b>Подзадачи — {stage.name}:</b>\n\nПодзадач пока нет."

    await callback.message.edit_text(  # type: ignore[union-attr]
        text,
        reply_markup=substages_keyboard(stage_id, stage.sub_stages),
    )


@router.callback_query(F.data.startswith("stgsuba:"))
async def start_add_substages(callback: CallbackQuery, state: FSMContext) -> None:
    """Ask for sub-stage names."""
    await callback.answer()
    stage_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    await state.set_state(StageSetup.adding_sub_stages)
    await state.update_data(stage_id=stage_id)
    await callback.message.answer(  # type: ignore[union-attr]
        "📝 <b>Добавление подзадач</b>\n\n"
        "Введите названия подзадач, <b>каждую на новой строке</b>.\n\n"
        "Пример:\n"
        "<i>Снять плитку в ванной\n"
        "Демонтировать сантехнику\n"
        "Снести перегородку</i>"
    )


@router.message(StageSetup.adding_sub_stages)
async def process_add_substages(message: Message, state: FSMContext) -> None:
    """Receive sub-stage names (one per line)."""
    if not message.text or not message.text.strip():
        await message.answer("Введите названия подзадач (каждую на новой строке):")
        return

    names = [
        line.strip()
        for line in message.text.strip().split("\n")
        if line.strip()
    ]

    if not names:
        await message.answer("Не удалось распознать подзадачи. Введите каждую на новой строке:")
        return

    data = await state.get_data()
    stage_id = data["stage_id"]

    async with async_session_factory() as session:
        # Determine starting order (after existing sub-stages)
        stage = await get_stage_with_substages(session, stage_id)
        start_order = len(stage.sub_stages) + 1 if stage and stage.sub_stages else 1

        subs = await create_sub_stages_bulk(
            session,
            stage_id=stage_id,
            names=names,
            start_order=start_order,
        )
        await session.commit()

    names_text = "\n".join(f"  {i}. {n}" for i, n in enumerate(names, start=start_order))
    await message.answer(
        f"✅ Добавлено подзадач: <b>{len(subs)}</b>\n\n{names_text}"
    )
    await _show_stage_detail(message, state, stage_id)


# ═══════════════════════════════════════════════════════════════
# PROJECT LAUNCH
# ═══════════════════════════════════════════════════════════════


@router.callback_query(F.data == "launch")
async def launch_from_stages(callback: CallbackQuery, state: FSMContext) -> None:
    """Launch button pressed from the stages list."""
    await callback.answer()
    data = await state.get_data()
    project_id = data.get("project_id")
    if project_id is None:
        await callback.message.answer(  # type: ignore[union-attr]
            "❌ Проект не найден. Отправьте /launch"
        )
        return

    await _show_launch_screen(
        callback.message, state, project_id  # type: ignore[arg-type]
    )


@router.callback_query(F.data == "launch_yes")
async def confirm_launch(callback: CallbackQuery, state: FSMContext) -> None:
    """Confirm project launch."""
    await callback.answer("Запускаем проект...")
    data = await state.get_data()
    project_id = data.get("project_id")

    if project_id is None:
        await callback.message.answer("❌ Проект не найден.")  # type: ignore[union-attr]
        await state.clear()
        return

    async with async_session_factory() as session:
        first_stage = await launch_project(session, project_id)
        await session.commit()

    if first_stage:
        await callback.message.answer(  # type: ignore[union-attr]
            "🚀 <b>Проект запущен!</b>\n\n"
            f"Первый этап «{first_stage.name}» переведён в статус <b>🔨 В работе</b>.\n\n"
            "Используйте /stages для управления этапами."
        )
    else:
        await callback.message.answer(  # type: ignore[union-attr]
            "🚀 <b>Проект запущен!</b>\n\n"
            "Используйте /stages для управления этапами."
        )

    await state.clear()
    logger.info("Project id=%d launched", project_id)
