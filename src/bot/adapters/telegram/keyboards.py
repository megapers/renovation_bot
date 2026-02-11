"""
Telegram inline keyboard builders for the project creation flow.

These helpers produce aiogram InlineKeyboardMarkup objects.
They are Telegram-specific and belong in the adapter layer.
"""

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def renovation_type_keyboard() -> InlineKeyboardMarkup:
    """Renovation type selection: Cosmetic | Standard | Major | Designer."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Косметический", callback_data="rtype:cosmetic"),
            InlineKeyboardButton(text="Стандартный", callback_data="rtype:standard"),
        ],
        [
            InlineKeyboardButton(text="Капитальный", callback_data="rtype:major"),
            InlineKeyboardButton(text="Дизайнерский", callback_data="rtype:designer"),
        ],
    ])


def coordinator_keyboard() -> InlineKeyboardMarkup:
    """Who manages the renovation: Self | Foreman | Designer."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Сам(а)", callback_data="coord:self"),
        ],
        [
            InlineKeyboardButton(text="Прораб", callback_data="coord:foreman"),
            InlineKeyboardButton(text="Дизайнер", callback_data="coord:designer"),
        ],
    ])


def yes_no_keyboard(prefix: str = "yn") -> InlineKeyboardMarkup:
    """Simple Yes / No keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data=f"{prefix}:yes"),
            InlineKeyboardButton(text="❌ Нет", callback_data=f"{prefix}:no"),
        ],
    ])


def custom_items_keyboard(selected: set[str] | None = None) -> InlineKeyboardMarkup:
    """
    Multi-select keyboard for custom furniture/fittings.

    Selected items get a ✅ prefix. User taps to toggle, then presses Done.
    """
    if selected is None:
        selected = set()

    items = [
        ("kitchen", "Кухня"),
        ("wardrobes", "Шкафы"),
        ("walkin", "Гардеробная"),
        ("doors", "Двери на заказ"),
    ]

    rows = []
    for key, label in items:
        prefix = "✅ " if key in selected else ""
        rows.append([
            InlineKeyboardButton(text=f"{prefix}{label}", callback_data=f"custom:{key}")
        ])

    # Done / Skip buttons
    rows.append([
        InlineKeyboardButton(text="✅ Готово", callback_data="custom:done"),
        InlineKeyboardButton(text="⏭ Пропустить", callback_data="custom:skip"),
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_keyboard() -> InlineKeyboardMarkup:
    """Final confirmation: Confirm / Edit / Cancel."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm:yes"),
        ],
        [
            InlineKeyboardButton(text="✏️ Изменить", callback_data="confirm:edit"),
            InlineKeyboardButton(text="❌ Отмена", callback_data="confirm:cancel"),
        ],
    ])


def skip_keyboard(prefix: str = "skip") -> InlineKeyboardMarkup:
    """Optional step — user can skip."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"{prefix}:skip"),
        ],
    ])
