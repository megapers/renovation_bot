"""
Telegram handlers for the project creation wizard.

This module implements a multi-step conversation using aiogram's FSM
(Finite State Machine). Each handler collects one piece of data,
stores it in FSM state, and advances to the next step.

Flow:
  /newproject → name → address → area → type → budget → coordinator
  → co-owner → custom items → review stages → confirm
"""

import logging

from aiogram import Bot, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.adapters.telegram.formatters import format_project_summary
from bot.adapters.telegram.fsm_states import ProjectCreation
from bot.adapters.telegram.keyboards import (
    confirm_keyboard,
    coordinator_keyboard,
    custom_items_keyboard,
    renovation_type_keyboard,
    skip_keyboard,
    yes_no_keyboard,
)
from bot.core.project_service import create_renovation_project
from bot.db.models import RenovationType
from bot.db.repositories import get_project_by_telegram_chat_id, get_user_by_telegram_id
from bot.db.session import async_session_factory

logger = logging.getLogger(__name__)
router = Router(name="project_creation")


# ── Step 0: Entry point ──────────────────────────────────────


@router.message(Command("newproject"))
async def cmd_new_project(message: Message, state: FSMContext) -> None:
    """Start the project creation wizard."""
    await state.clear()
    await state.set_state(ProjectCreation.waiting_for_name)
    await message.answer(
        "🏗 <b>Создание нового проекта ремонта</b>\n\n"
        "Шаг 1 из 7\n"
        "Введите <b>название объекта</b> (например: «Квартира на Абая» или «Дом на Навои»):"
    )


# ── Step 1: Property name ────────────────────────────────────


@router.message(ProjectCreation.waiting_for_name)
async def process_name(message: Message, state: FSMContext) -> None:
    """Receive property name and ask for address."""
    if not message.text or not message.text.strip():
        await message.answer("Пожалуйста, введите название объекта:")
        return

    await state.update_data(name=message.text.strip())
    await state.set_state(ProjectCreation.waiting_for_address)
    await message.answer(
        "📍 Шаг 2 из 7\n"
        "Введите <b>адрес</b> объекта:",
        reply_markup=skip_keyboard("addr"),
    )


# ── Step 2: Address ──────────────────────────────────────────


@router.message(ProjectCreation.waiting_for_address)
async def process_address(message: Message, state: FSMContext) -> None:
    """Receive address and ask for area."""
    if not message.text or not message.text.strip():
        await message.answer("Пожалуйста, введите адрес или нажмите «Пропустить»:")
        return

    await state.update_data(address=message.text.strip())
    await _ask_for_area(message, state)


@router.callback_query(ProjectCreation.waiting_for_address, F.data == "addr:skip")
async def skip_address(callback: CallbackQuery, state: FSMContext) -> None:
    """Skip address step."""
    await callback.answer()
    await state.update_data(address=None)
    await _ask_for_area(callback.message, state)  # type: ignore[arg-type]


async def _ask_for_area(message: Message, state: FSMContext) -> None:
    """Transition helper: ask for area."""
    await state.set_state(ProjectCreation.waiting_for_area)
    await message.answer(
        "📐 Шаг 3 из 7\n"
        "Введите <b>площадь</b> объекта в м² (число):",
        reply_markup=skip_keyboard("area"),
    )


# ── Step 3: Area ─────────────────────────────────────────────


@router.message(ProjectCreation.waiting_for_area)
async def process_area(message: Message, state: FSMContext) -> None:
    """Receive area and ask for renovation type."""
    if not message.text or not message.text.strip():
        await message.answer("Введите площадь в м² или нажмите «Пропустить»:")
        return

    try:
        area = float(message.text.strip().replace(",", "."))
        if area <= 0 or area > 99999:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введите корректное число (например: 65 или 120.5):")
        return

    await state.update_data(area_sqm=area)
    await _ask_for_type(message, state)


@router.callback_query(ProjectCreation.waiting_for_area, F.data == "area:skip")
async def skip_area(callback: CallbackQuery, state: FSMContext) -> None:
    """Skip area step."""
    await callback.answer()
    await state.update_data(area_sqm=None)
    await _ask_for_type(callback.message, state)  # type: ignore[arg-type]


async def _ask_for_type(message: Message, state: FSMContext) -> None:
    """Transition helper: ask for renovation type."""
    await state.set_state(ProjectCreation.waiting_for_type)
    await message.answer(
        "🔧 Шаг 4 из 7\n"
        "Выберите <b>тип ремонта</b>:",
        reply_markup=renovation_type_keyboard(),
    )


# ── Step 4: Renovation type ──────────────────────────────────


@router.callback_query(ProjectCreation.waiting_for_type, F.data.startswith("rtype:"))
async def process_type(callback: CallbackQuery, state: FSMContext) -> None:
    """Receive renovation type via inline button."""
    await callback.answer()
    rtype = callback.data.split(":")[1]  # type: ignore[union-attr]
    await state.update_data(renovation_type=rtype)
    await state.set_state(ProjectCreation.waiting_for_budget)
    await callback.message.answer(  # type: ignore[union-attr]
        "💰 Шаг 5 из 7\n"
        "Введите <b>общий бюджет</b> (число в тенге):",
        reply_markup=skip_keyboard("budget"),
    )


# ── Step 5: Budget ───────────────────────────────────────────


@router.message(ProjectCreation.waiting_for_budget)
async def process_budget(message: Message, state: FSMContext) -> None:
    """Receive total budget."""
    if not message.text or not message.text.strip():
        await message.answer("Введите бюджет или нажмите «Пропустить»:")
        return

    text = message.text.strip().replace(" ", "").replace(",", ".")
    try:
        budget = float(text)
        if budget <= 0:
            raise ValueError
    except ValueError:
        await message.answer("Пожалуйста, введите корректную сумму (например: 5000000):")
        return

    await state.update_data(total_budget=budget)
    await _ask_for_coordinator(message, state)


@router.callback_query(ProjectCreation.waiting_for_budget, F.data == "budget:skip")
async def skip_budget(callback: CallbackQuery, state: FSMContext) -> None:
    """Skip budget step."""
    await callback.answer()
    await state.update_data(total_budget=None)
    await _ask_for_coordinator(callback.message, state)  # type: ignore[arg-type]


async def _ask_for_coordinator(message: Message, state: FSMContext) -> None:
    """Transition helper: ask who coordinates the renovation."""
    await state.set_state(ProjectCreation.waiting_for_coordinator)
    await message.answer(
        "👷 Шаг 6 из 7\n"
        "Кто <b>координирует</b> ремонт?",
        reply_markup=coordinator_keyboard(),
    )


# ── Step 6: Coordinator ──────────────────────────────────────


@router.callback_query(ProjectCreation.waiting_for_coordinator, F.data.startswith("coord:"))
async def process_coordinator(callback: CallbackQuery, state: FSMContext) -> None:
    """Receive coordinator choice."""
    await callback.answer()
    coord = callback.data.split(":")[1]  # type: ignore[union-attr]
    await state.update_data(coordinator=coord)

    if coord in ("foreman", "designer"):
        # Need contact info for the coordinator
        role_label = "прораба" if coord == "foreman" else "дизайнера"
        await state.set_state(ProjectCreation.waiting_for_coordinator_contact)
        await callback.message.answer(  # type: ignore[union-attr]
            f"📞 Введите контакт {role_label} "
            "(имя и телефон или @username в Telegram):",
        )
    else:
        # Self-managed — skip to co-owner
        await state.update_data(coordinator_contact=None)
        await _ask_for_co_owner(callback.message, state)  # type: ignore[arg-type]


@router.message(ProjectCreation.waiting_for_coordinator_contact)
async def process_coordinator_contact(message: Message, state: FSMContext) -> None:
    """Receive coordinator contact info."""
    if not message.text or not message.text.strip():
        await message.answer("Пожалуйста, введите контактные данные координатора:")
        return

    await state.update_data(coordinator_contact=message.text.strip())
    await _ask_for_co_owner(message, state)


# ── Step 7: Co-owner ─────────────────────────────────────────


async def _ask_for_co_owner(message: Message, state: FSMContext) -> None:
    """Transition helper: ask about co-owner."""
    await state.set_state(ProjectCreation.waiting_for_co_owner)
    await message.answer(
        "👥 Шаг 7 из 7\n"
        "Есть ли <b>второй владелец</b> (например, супруг/супруга)?",
        reply_markup=yes_no_keyboard("coown"),
    )


@router.callback_query(ProjectCreation.waiting_for_co_owner, F.data == "coown:yes")
async def co_owner_yes(callback: CallbackQuery, state: FSMContext) -> None:
    """User wants to add a co-owner."""
    await callback.answer()
    await state.set_state(ProjectCreation.waiting_for_co_owner_contact)
    await callback.message.answer(  # type: ignore[union-attr]
        "👤 Введите контакт второго владельца "
        "(имя и @username в Telegram):"
    )


@router.callback_query(ProjectCreation.waiting_for_co_owner, F.data == "coown:no")
async def co_owner_no(callback: CallbackQuery, state: FSMContext) -> None:
    """No co-owner — move to custom items."""
    await callback.answer()
    await state.update_data(co_owner_contact=None)
    await _ask_for_custom_items(callback.message, state)  # type: ignore[arg-type]


@router.message(ProjectCreation.waiting_for_co_owner_contact)
async def process_co_owner_contact(message: Message, state: FSMContext) -> None:
    """Receive co-owner contact info."""
    if not message.text or not message.text.strip():
        await message.answer("Пожалуйста, введите контактные данные второго владельца:")
        return

    await state.update_data(co_owner_contact=message.text.strip())
    await _ask_for_custom_items(message, state)


# ── Step 8: Custom furniture/fittings ─────────────────────────


async def _ask_for_custom_items(message: Message, state: FSMContext) -> None:
    """Transition helper: ask about custom furniture."""
    await state.update_data(custom_items=[])
    await state.set_state(ProjectCreation.waiting_for_custom_items)
    await message.answer(
        "🪑 Заказываете ли вы <b>мебель на заказ</b>?\n"
        "Выберите нужные пункты (можно несколько), затем нажмите «Готово»:",
        reply_markup=custom_items_keyboard(),
    )


@router.callback_query(ProjectCreation.waiting_for_custom_items, F.data.startswith("custom:"))
async def process_custom_items(callback: CallbackQuery, state: FSMContext) -> None:
    """Toggle custom item selection or finish."""
    await callback.answer()
    action = callback.data.split(":")[1]  # type: ignore[union-attr]

    if action in ("done", "skip"):
        # Move to confirmation
        if action == "skip":
            await state.update_data(custom_items=[])
        await _show_confirmation(callback.message, state)  # type: ignore[arg-type]
        return

    # Toggle the item
    data = await state.get_data()
    current: list[str] = data.get("custom_items", [])
    if action in current:
        current.remove(action)
    else:
        current.append(action)
    await state.update_data(custom_items=current)

    # Update keyboard to show selection
    await callback.message.edit_reply_markup(  # type: ignore[union-attr]
        reply_markup=custom_items_keyboard(set(current)),
    )


# ── Step 9: Review & Confirm ─────────────────────────────────


async def _show_confirmation(message: Message, state: FSMContext) -> None:
    """Show project summary and ask for confirmation."""
    data = await state.get_data()
    await state.set_state(ProjectCreation.confirming)

    # Build a text summary from collected data
    type_labels = {
        "cosmetic": "Косметический",
        "standard": "Стандартный",
        "major": "Капитальный",
        "designer": "Дизайнерский",
    }

    coord_labels = {
        "self": "Самостоятельно",
        "foreman": "Прораб",
        "designer": "Дизайнер",
    }

    lines = [
        "📋 <b>Проверьте данные проекта:</b>",
        "",
        f"🏠 Название: <b>{data['name']}</b>",
    ]

    if data.get("address"):
        lines.append(f"📍 Адрес: {data['address']}")
    if data.get("area_sqm"):
        lines.append(f"📐 Площадь: {data['area_sqm']} м²")

    lines.append(f"🔧 Тип: {type_labels.get(data['renovation_type'], data['renovation_type'])}")

    if data.get("total_budget"):
        lines.append(f"💰 Бюджет: {data['total_budget']:,.0f} ₸")

    lines.append(f"👷 Координатор: {coord_labels.get(data.get('coordinator', 'self'), 'Самостоятельно')}")

    if data.get("coordinator_contact"):
        lines.append(f"   Контакт: {data['coordinator_contact']}")

    if data.get("co_owner_contact"):
        lines.append(f"👥 Второй владелец: {data['co_owner_contact']}")

    custom = data.get("custom_items", [])
    if custom:
        from bot.core.stage_templates import CUSTOM_ITEM_LABELS
        labels = [CUSTOM_ITEM_LABELS.get(k, k) for k in custom]
        lines.append(f"🪑 Мебель на заказ: {', '.join(labels)}")

    lines.append("")
    lines.append("Будет создано <b>13 основных этапов</b> ремонта.")
    if custom:
        lines.append(f"+ <b>{len(custom) * 5} параллельных этапов</b> для мебели на заказ.")

    await message.answer(
        "\n".join(lines),
        reply_markup=confirm_keyboard(),
    )


@router.callback_query(ProjectCreation.confirming, F.data == "confirm:yes")
async def confirm_project(callback: CallbackQuery, state: FSMContext, bot: Bot, **kwargs) -> None:
    """Create the project in the database."""
    await callback.answer("Создаю проект...")
    data = await state.get_data()

    tg_user = callback.from_user

    async with async_session_factory() as session:
        # Find the user
        user = await get_user_by_telegram_id(session, tg_user.id)
        if user is None:
            await callback.message.answer(  # type: ignore[union-attr]
                "❌ Ошибка: пользователь не найден. Отправьте /start сначала."
            )
            await state.clear()
            return

        # Create the project
        # Only bind to a group chat, never to a private chat.
        # The user links to a group later via deep link or /link.
        chat_type = callback.message.chat.type if callback.message else None  # type: ignore[union-attr]
        chat_id = callback.message.chat.id if callback.message else None  # type: ignore[union-attr]
        platform_chat_id: str | None = None

        if chat_type in ("group", "supergroup") and chat_id:
            existing = await get_project_by_telegram_chat_id(session, chat_id)
            if not existing:
                platform_chat_id = str(chat_id)

        project = await create_renovation_project(
            session,
            owner_user_id=user.id,
            name=data["name"],
            address=data.get("address"),
            area_sqm=data.get("area_sqm"),
            renovation_type=RenovationType(data["renovation_type"]),
            total_budget=data.get("total_budget"),
            tenant_id=kwargs.get("tenant_id"),
            platform="telegram",
            platform_chat_id=platform_chat_id,
            custom_items=data.get("custom_items") or None,
        )

        await session.commit()

    # Show the final summary
    summary = format_project_summary(project)

    # Build deep link for adding bot to a group with this project
    bot_info = await bot.get_me()
    bot_username = bot_info.username if bot_info else None

    reply_text = f"✅ <b>Проект создан!</b>\n\n{summary}"

    if bot_username and callback.message.chat.type == "private":  # type: ignore[union-attr]
        # Show "Add to group" button only in private chat
        reply_text += (
            "\n\n👥 Чтобы привязать проект к рабочей группе, "
            "нажмите кнопку ниже или добавьте бота в группу и "
            "отправьте /link"
        )
        deep_link_url = (
            f"https://t.me/{bot_username}?startgroup=proj_{project.id}"
        )
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(
                text="👥 Добавить бота в группу",
                url=deep_link_url,
            )],
        ])
        await callback.message.answer(  # type: ignore[union-attr]
            reply_text, reply_markup=keyboard,
        )
    else:
        await callback.message.answer(reply_text)  # type: ignore[union-attr]

    await state.clear()
    logger.info("Project created via Telegram: %s (id=%d) by user tg_id=%d", project.name, project.id, tg_user.id)


@router.callback_query(ProjectCreation.confirming, F.data == "confirm:cancel")
async def cancel_project(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel project creation."""
    await callback.answer()
    await state.clear()
    await callback.message.answer(  # type: ignore[union-attr]
        "❌ Создание проекта отменено.\n"
        "Чтобы начать заново, отправьте /newproject"
    )


@router.callback_query(ProjectCreation.confirming, F.data == "confirm:edit")
async def edit_project(callback: CallbackQuery, state: FSMContext) -> None:
    """Restart the wizard to edit the project."""
    await callback.answer()
    await state.set_state(ProjectCreation.waiting_for_name)
    data = await state.get_data()
    await callback.message.answer(  # type: ignore[union-attr]
        "✏️ Начнём сначала.\n\n"
        f"Текущее название: <b>{data.get('name', '—')}</b>\n"
        "Введите новое название или отправьте прежнее:"
    )
