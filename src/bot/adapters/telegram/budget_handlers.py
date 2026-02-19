"""
Telegram handlers for budget & payment tracking (Phase 6).

Commands:
  /budget   — view project budget overview
  /expenses — add a new expense

All inline-keyboard interactions for budget management are handled
here via callback query handlers.
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.adapters.telegram.filters import RequirePermission
from bot.core.role_service import Permission
from bot.adapters.telegram.formatters import (
    format_budget_item_detail,
    format_budget_overview,
    format_change_history,
    format_payment_stage_detail,
)
from bot.adapters.telegram.fsm_states import BudgetManagement
from bot.adapters.telegram.keyboards import (
    budget_category_keyboard,
    budget_item_keyboard,
    budget_items_list_keyboard,
    budget_overview_keyboard,
    expense_type_keyboard,
    payment_stages_keyboard,
    payment_status_keyboard,
    skip_amount_keyboard,
)
from bot.adapters.telegram.project_resolver import resolve_project
from bot.core.budget_service import (
    get_category_label,
    parse_expense_amount,
    validate_payment_transition,
)
from bot.db.repositories import (
    confirm_budget_item,
    create_budget_item,
    create_change_log,
    delete_budget_item,
    get_budget_item_by_id,
    get_budget_items_by_category,
    get_budget_summary_by_category,
    get_change_logs_for_project,
    get_project_budget_summary,
    get_stages_for_project,
    get_stage_with_substages,
    get_unconfirmed_budget_items,
    get_user_by_telegram_id,
    update_stage_payment_status,
)
from bot.db.session import async_session_factory

logger = logging.getLogger(__name__)
router = Router(name="budget")


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════


async def _get_user_id(event: Message | CallbackQuery) -> int | None:
    """
    Get the internal user ID from a Telegram message/callback.

    Returns None and sends error if user not found.
    """
    tg_user = event.from_user
    if tg_user is None:
        return None

    async with async_session_factory() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if user is None:
            target = event if isinstance(event, Message) else event.message
            if target:
                await target.answer(
                    "❌ Вы не зарегистрированы. Отправьте /start сначала."
                )
            return None
        return user.id


async def _show_budget_overview(
    target: Message,
    state: FSMContext,
    project_id: int,
    edit: bool = False,
) -> None:
    """Load and display the budget overview for a project."""
    async with async_session_factory() as session:
        summary = await get_project_budget_summary(session, project_id)
        cat_summaries = await get_budget_summary_by_category(session, project_id)

        # Get project name
        from bot.db.repositories import get_project_with_stages

        project = await get_project_with_stages(session, project_id)

    project_name = project.name if project else "—"
    total_budget = summary["total_budget"]

    text = format_budget_overview(project_name, total_budget, summary, cat_summaries)
    keyboard = budget_overview_keyboard(project_id)

    if edit:
        await target.edit_text(text, reply_markup=keyboard)
    else:
        await target.answer(text, reply_markup=keyboard)

    await state.set_state(BudgetManagement.viewing_budget)
    await state.update_data(project_id=project_id)


# ═══════════════════════════════════════════════════════════════
# ENTRY POINTS — /budget and /expenses
# ═══════════════════════════════════════════════════════════════


@router.message(Command("budget"), RequirePermission(Permission.VIEW_BUDGET))
async def cmd_budget(message: Message, state: FSMContext) -> None:
    """
    /budget — show project budget overview.

    Group chat: auto-resolves to linked project.
    Private chat: picker if multiple projects.
    """
    await state.clear()
    resolved = await resolve_project(
        message, state,
        intent="budget",
        picker_state=BudgetManagement.selecting_project,
    )
    if resolved:
        await _show_budget_overview(message, state, resolved.id)


@router.message(Command("expenses"), RequirePermission(Permission.EDIT_BUDGET))
async def cmd_expenses(message: Message, state: FSMContext) -> None:
    """
    /expenses — start adding a new expense.

    Group chat: auto-resolves to linked project.
    Private chat: picker if multiple projects.
    """
    await state.clear()
    resolved = await resolve_project(
        message, state,
        intent="expense",
        picker_state=BudgetManagement.selecting_project,
    )
    if resolved:
        await _start_expense_wizard(message, state, resolved.id)


# ═══════════════════════════════════════════════════════════════
# PROJECT SELECTION (shared prefix with stage handlers — use
# budget-specific state to distinguish)
# ═══════════════════════════════════════════════════════════════


@router.callback_query(
    BudgetManagement.selecting_project,
    F.data.startswith("prjsel:"),
)
async def budget_select_project(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """User selected a project from the budget selection list."""
    await callback.answer()
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    data = await state.get_data()
    intent = data.get("intent", "budget")

    if intent == "expense":
        await _start_expense_wizard(
            callback.message, state, project_id  # type: ignore[arg-type]
        )
    else:
        await _show_budget_overview(
            callback.message, state, project_id, edit=True  # type: ignore[arg-type]
        )


# ═══════════════════════════════════════════════════════════════
# BUDGET OVERVIEW NAVIGATION
# ═══════════════════════════════════════════════════════════════


@router.callback_query(F.data == "bback")
async def back_to_budget(callback: CallbackQuery, state: FSMContext) -> None:
    """Return to the budget overview."""
    await callback.answer()
    data = await state.get_data()
    project_id = data.get("project_id")
    if project_id is None:
        await callback.message.answer(  # type: ignore[union-attr]
            "❌ Проект не найден. Отправьте /budget"
        )
        await state.clear()
        return

    await _show_budget_overview(
        callback.message, state, project_id, edit=True  # type: ignore[arg-type]
    )


# ═══════════════════════════════════════════════════════════════
# ADD EXPENSE WIZARD
# ═══════════════════════════════════════════════════════════════


async def _start_expense_wizard(
    target: Message,
    state: FSMContext,
    project_id: int,
) -> None:
    """Start the expense creation flow — select expense type first."""
    await state.set_state(BudgetManagement.selecting_category)
    await state.update_data(
        project_id=project_id,
        expense_type=None,
        work_cost=0.0,
        material_cost=0.0,
        prepayment=0.0,
    )
    await target.answer(
        "💰 <b>Новый расход</b>\n\n"
        "Выберите тип расхода:",
        reply_markup=expense_type_keyboard(),
    )


@router.callback_query(F.data.startswith("badd:"))
async def start_add_expense(callback: CallbackQuery, state: FSMContext) -> None:
    """Start adding an expense from the budget overview."""
    await callback.answer()
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    await _start_expense_wizard(
        callback.message, state, project_id  # type: ignore[arg-type]
    )


@router.callback_query(F.data.startswith("betype:"))
async def select_expense_type(callback: CallbackQuery, state: FSMContext) -> None:
    """User selected the expense type (work/material/prepayment/both)."""
    await callback.answer()
    etype = callback.data.split(":")[1]  # type: ignore[union-attr]

    if etype == "cancel":
        data = await state.get_data()
        project_id = data.get("project_id")
        if project_id:
            await _show_budget_overview(
                callback.message, state, project_id, edit=True  # type: ignore[arg-type]
            )
        else:
            await state.clear()
            await callback.message.answer("❌ Отменено.")  # type: ignore[union-attr]
        return

    await state.update_data(expense_type=etype)

    # Now select category
    await callback.message.edit_text(  # type: ignore[union-attr]
        "📂 <b>Выберите категорию расхода:</b>",
        reply_markup=budget_category_keyboard(),
    )


@router.callback_query(F.data.startswith("bcat:"))
async def select_category(callback: CallbackQuery, state: FSMContext) -> None:
    """User selected a budget category."""
    await callback.answer()
    category = callback.data.split(":")[1]  # type: ignore[union-attr]

    if category == "cancel":
        data = await state.get_data()
        project_id = data.get("project_id")
        if project_id:
            await _show_budget_overview(
                callback.message, state, project_id, edit=True  # type: ignore[arg-type]
            )
        else:
            await state.clear()
            await callback.message.answer("❌ Отменено.")  # type: ignore[union-attr]
        return

    await state.update_data(category=category)
    await state.set_state(BudgetManagement.entering_description)

    label = get_category_label(category)
    await callback.message.answer(  # type: ignore[union-attr]
        f"📝 Категория: <b>{label}</b>\n\n"
        "Введите описание расхода\n"
        "(например: <i>Монтаж розеток в гостиной</i>):"
    )


@router.message(BudgetManagement.entering_description)
async def process_description(message: Message, state: FSMContext) -> None:
    """Receive expense description."""
    if not message.text or not message.text.strip():
        await message.answer("Введите описание расхода:")
        return

    description = message.text.strip()
    await state.update_data(description=description)

    data = await state.get_data()
    etype = data.get("expense_type", "both")

    # Route based on expense type
    if etype in ("work", "both"):
        await state.set_state(BudgetManagement.entering_work_cost)
        await message.answer(
            "🔨 Введите <b>стоимость работы</b> (в тенге):",
            reply_markup=skip_amount_keyboard(),
        )
    elif etype == "material":
        await state.set_state(BudgetManagement.entering_material_cost)
        await message.answer(
            "🧱 Введите <b>стоимость материалов</b> (в тенге):",
            reply_markup=skip_amount_keyboard(),
        )
    elif etype == "prepayment":
        await state.set_state(BudgetManagement.entering_prepayment)
        await message.answer(
            "💵 Введите <b>сумму предоплаты</b> (в тенге):"
        )


@router.callback_query(F.data == "bskip:0")
async def skip_amount(callback: CallbackQuery, state: FSMContext) -> None:
    """Skip entering an optional amount (set to 0)."""
    await callback.answer()
    current_state = await state.get_state()
    data = await state.get_data()
    etype = data.get("expense_type", "both")

    if current_state == BudgetManagement.entering_work_cost.state:
        await state.update_data(work_cost=0.0)
        if etype == "both":
            await state.set_state(BudgetManagement.entering_material_cost)
            await callback.message.answer(  # type: ignore[union-attr]
                "🧱 Введите <b>стоимость материалов</b> (в тенге):",
                reply_markup=skip_amount_keyboard(),
            )
        else:
            await _save_expense(callback.message, state)  # type: ignore[arg-type]

    elif current_state == BudgetManagement.entering_material_cost.state:
        await state.update_data(material_cost=0.0)
        await _save_expense(callback.message, state)  # type: ignore[arg-type]


@router.message(BudgetManagement.entering_work_cost)
async def process_work_cost(message: Message, state: FSMContext) -> None:
    """Receive work cost amount."""
    if not message.text:
        await message.answer("Введите сумму:")
        return

    amount = parse_expense_amount(message.text)
    if amount is None:
        await message.answer(
            "❌ Не удалось распознать сумму.\n"
            "Введите число (например: 150000 или 150 000):"
        )
        return

    await state.update_data(work_cost=amount)
    data = await state.get_data()
    etype = data.get("expense_type", "both")

    if etype == "both":
        await state.set_state(BudgetManagement.entering_material_cost)
        await message.answer(
            f"✅ Работа: {amount:,.0f} ₸\n\n"
            "🧱 Введите <b>стоимость материалов</b> (в тенге):",
            reply_markup=skip_amount_keyboard(),
        )
    else:
        await _save_expense(message, state)


@router.message(BudgetManagement.entering_material_cost)
async def process_material_cost(message: Message, state: FSMContext) -> None:
    """Receive material cost amount."""
    if not message.text:
        await message.answer("Введите сумму:")
        return

    amount = parse_expense_amount(message.text)
    if amount is None:
        await message.answer(
            "❌ Не удалось распознать сумму.\n"
            "Введите число (например: 80000 или 80 000):"
        )
        return

    await state.update_data(material_cost=amount)
    await _save_expense(message, state)


@router.message(BudgetManagement.entering_prepayment)
async def process_prepayment(message: Message, state: FSMContext) -> None:
    """Receive prepayment amount."""
    if not message.text:
        await message.answer("Введите сумму предоплаты:")
        return

    amount = parse_expense_amount(message.text)
    if amount is None:
        await message.answer(
            "❌ Не удалось распознать сумму.\n"
            "Введите число (например: 50000):"
        )
        return

    await state.update_data(prepayment=amount)
    await _save_expense(message, state)


async def _save_expense(target: Message, state: FSMContext) -> None:
    """Save the expense to the database and return to budget overview."""
    data = await state.get_data()
    project_id = data["project_id"]
    category = data["category"]
    description = data.get("description")
    work_cost = data.get("work_cost", 0.0)
    material_cost = data.get("material_cost", 0.0)
    prepayment = data.get("prepayment", 0.0)

    async with async_session_factory() as session:
        item = await create_budget_item(
            session,
            project_id=project_id,
            category=category,
            description=description,
            work_cost=work_cost,
            material_cost=material_cost,
            prepayment=prepayment,
        )

        # Create change log entry
        total = work_cost + material_cost
        await create_change_log(
            session,
            project_id=project_id,
            entity_type="budget_item",
            entity_id=item.id,
            field_name="amount",
            old_value=None,
            new_value=str(total),
            user_id=None,  # TODO: pass user_id through state
        )
        await session.commit()

    label = get_category_label(category)
    parts = []
    if work_cost > 0:
        parts.append(f"🔨 Работа: {work_cost:,.0f} ₸")
    if material_cost > 0:
        parts.append(f"🧱 Материалы: {material_cost:,.0f} ₸")
    if prepayment > 0:
        parts.append(f"💵 Предоплата: {prepayment:,.0f} ₸")

    await target.answer(
        f"✅ <b>Расход добавлен!</b>\n\n"
        f"📂 {label}\n"
        + (f"📝 {description}\n" if description else "")
        + "\n".join(parts)
    )

    # Return to budget overview
    await _show_budget_overview(target, state, project_id)


# ═══════════════════════════════════════════════════════════════
# BUDGET ITEMS — VIEW / CONFIRM / DELETE
# ═══════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith("bcats:"))
async def show_by_category(callback: CallbackQuery, state: FSMContext) -> None:
    """Show budget items grouped by category."""
    await callback.answer()
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    async with async_session_factory() as session:
        items = await get_budget_items_by_category(
            session, project_id, ""
        )
        # Actually show all items — the list keyboard groups visually
        from bot.db.repositories import get_budget_items_for_project

        items = await get_budget_items_for_project(session, project_id)

    if not items:
        await callback.message.edit_text(  # type: ignore[union-attr]
            "📊 Расходов пока нет.\n\n"
            "Добавьте первый расход через кнопку ➕ или команду /expenses",
            reply_markup=budget_overview_keyboard(project_id),
        )
        return

    await callback.message.edit_text(  # type: ignore[union-attr]
        "📊 <b>Все расходы:</b>\n\n"
        "Нажмите для подробностей:",
        reply_markup=budget_items_list_keyboard(items, project_id),
    )
    await state.update_data(project_id=project_id)


@router.callback_query(F.data.startswith("bunconf:"))
async def show_unconfirmed(callback: CallbackQuery, state: FSMContext) -> None:
    """Show only unconfirmed budget items."""
    await callback.answer()
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    async with async_session_factory() as session:
        items = await get_unconfirmed_budget_items(session, project_id)

    if not items:
        await callback.message.edit_text(  # type: ignore[union-attr]
            "✅ Все расходы подтверждены!",
            reply_markup=budget_overview_keyboard(project_id),
        )
        return

    await callback.message.edit_text(  # type: ignore[union-attr]
        f"🔍 <b>Не подтверждённые расходы ({len(items)}):</b>\n\n"
        "Нажмите для подробностей:",
        reply_markup=budget_items_list_keyboard(items, project_id),
    )
    await state.update_data(project_id=project_id)


@router.callback_query(F.data.startswith("bitem:"))
async def view_budget_item(callback: CallbackQuery, state: FSMContext) -> None:
    """View a single budget item's details."""
    await callback.answer()
    item_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    async with async_session_factory() as session:
        item = await get_budget_item_by_id(session, item_id)

    if item is None:
        await callback.message.edit_text("❌ Расход не найден.")  # type: ignore[union-attr]
        return

    text = format_budget_item_detail(item)
    await callback.message.edit_text(  # type: ignore[union-attr]
        text,
        reply_markup=budget_item_keyboard(item.id, item.is_confirmed),
    )
    await state.set_state(BudgetManagement.viewing_item)
    await state.update_data(item_id=item.id, project_id=item.project_id)


@router.callback_query(F.data.startswith("bconf:"))
async def confirm_item(callback: CallbackQuery, state: FSMContext) -> None:
    """Confirm a budget item (owner only)."""
    await callback.answer("Подтверждаем...")
    item_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    user_id = await _get_user_id(callback)
    if user_id is None:
        return

    async with async_session_factory() as session:
        item = await confirm_budget_item(session, item_id, user_id)
        if item:
            # Log the confirmation
            await create_change_log(
                session,
                project_id=item.project_id,
                entity_type="budget_item",
                entity_id=item.id,
                field_name="is_confirmed",
                old_value="false",
                new_value="true",
                changed_by_user_id=user_id,
                confirmed_by_user_id=user_id,
            )
            await session.commit()

            text = format_budget_item_detail(item)
            await callback.message.edit_text(  # type: ignore[union-attr]
                text,
                reply_markup=budget_item_keyboard(item.id, item.is_confirmed),
            )
        else:
            await callback.message.answer("❌ Расход не найден.")  # type: ignore[union-attr]


@router.callback_query(F.data.startswith("bdel:"))
async def delete_item(callback: CallbackQuery, state: FSMContext) -> None:
    """Delete a budget item."""
    await callback.answer("Удаляем...")
    item_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    user_id = await _get_user_id(callback)
    if user_id is None:
        return

    async with async_session_factory() as session:
        item = await get_budget_item_by_id(session, item_id)
        if item is None:
            await callback.message.answer("❌ Расход не найден.")  # type: ignore[union-attr]
            return

        project_id = item.project_id
        total = float(item.work_cost) + float(item.material_cost)

        # Log deletion
        await create_change_log(
            session,
            project_id=project_id,
            entity_type="budget_item",
            entity_id=item_id,
            field_name="deleted",
            old_value=str(total),
            new_value=None,
            changed_by_user_id=user_id,
        )

        success = await delete_budget_item(session, item_id)
        await session.commit()

    if success:
        await callback.message.edit_text(  # type: ignore[union-attr]
            "🗑 Расход удалён."
        )
        # Return to budget overview
        data = await state.get_data()
        pid = data.get("project_id", project_id)
        await _show_budget_overview(
            callback.message, state, pid  # type: ignore[arg-type]
        )
    else:
        await callback.message.answer("❌ Не удалось удалить расход.")  # type: ignore[union-attr]


# ═══════════════════════════════════════════════════════════════
# CHANGE HISTORY
# ═══════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith("bhist:"))
async def show_change_history(callback: CallbackQuery, state: FSMContext) -> None:
    """Show budget change history for a project."""
    await callback.answer()
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    async with async_session_factory() as session:
        logs = await get_change_logs_for_project(session, project_id, limit=20)

    text = format_change_history(list(logs))
    await callback.message.edit_text(  # type: ignore[union-attr]
        text,
        reply_markup=budget_overview_keyboard(project_id),
    )
    await state.update_data(project_id=project_id)
    await state.set_state(BudgetManagement.viewing_history)


# ═══════════════════════════════════════════════════════════════
# PAYMENT STATUS MANAGEMENT
# ═══════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith("bpay:"))
async def show_payment_stages(callback: CallbackQuery, state: FSMContext) -> None:
    """Show all stages with their payment status."""
    await callback.answer()
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    async with async_session_factory() as session:
        stages = await get_stages_for_project(session, project_id)

    if not stages:
        await callback.message.edit_text(  # type: ignore[union-attr]
            "Нет этапов для управления оплатой.",
            reply_markup=budget_overview_keyboard(project_id),
        )
        return

    await callback.message.edit_text(  # type: ignore[union-attr]
        "💳 <b>Оплата этапов</b>\n\n"
        "Выберите этап для управления оплатой:",
        reply_markup=payment_stages_keyboard(stages),
    )
    await state.update_data(project_id=project_id)


@router.callback_query(F.data.startswith("bpay_stg:"))
async def view_stage_payment(callback: CallbackQuery, state: FSMContext) -> None:
    """View payment details for a specific stage."""
    await callback.answer()
    stage_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]

    async with async_session_factory() as session:
        stage = await get_stage_with_substages(session, stage_id)

    if stage is None:
        await callback.message.edit_text("❌ Этап не найден.")  # type: ignore[union-attr]
        return

    text = format_payment_stage_detail(stage)
    await callback.message.edit_text(  # type: ignore[union-attr]
        text,
        reply_markup=payment_status_keyboard(
            stage_id, stage.payment_status.value
        ),
    )
    await state.update_data(stage_id=stage_id)


@router.callback_query(F.data.startswith("bpysts:"))
async def change_payment_status(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """Change the payment status of a stage."""
    await callback.answer()
    parts = callback.data.split(":")  # type: ignore[union-attr]
    new_status = parts[1]
    stage_id = int(parts[2])

    user_id = await _get_user_id(callback)
    if user_id is None:
        return

    async with async_session_factory() as session:
        stage = await get_stage_with_substages(session, stage_id)
        if stage is None:
            await callback.message.answer("❌ Этап не найден.")  # type: ignore[union-attr]
            return

        current_status = stage.payment_status.value

        # Validate the transition
        is_valid, error_msg = validate_payment_transition(
            current_status, new_status
        )
        if not is_valid:
            await callback.message.answer(  # type: ignore[union-attr]
                f"❌ {error_msg}"
            )
            return

        # Update the payment status (also creates a change log entry)
        await update_stage_payment_status(
            session, stage_id, new_status, user_id
        )
        await session.commit()

        # Reload stage
        stage = await get_stage_with_substages(session, stage_id)

    if stage:
        text = format_payment_stage_detail(stage)
        await callback.message.edit_text(  # type: ignore[union-attr]
            text + "\n\n✅ Статус оплаты обновлён!",
            reply_markup=payment_status_keyboard(
                stage_id, stage.payment_status.value
            ),
        )
    logger.info(
        "Payment status changed: stage_id=%d %s→%s by user_id=%d",
        stage_id,
        current_status,
        new_status,
        user_id,
    )
