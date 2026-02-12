"""
Telegram inline keyboard builders for the project creation flow
and stage management.

These helpers produce aiogram InlineKeyboardMarkup objects.
They are Telegram-specific and belong in the adapter layer.
"""

from typing import Sequence

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


# ── Stage management keyboards (Phase 3) ──────────────────────


_STATUS_ICONS: dict[str, str] = {
    "planned": "📋",
    "in_progress": "🔨",
    "completed": "✅",
    "delayed": "⚠️",
}


def _stage_indicators(stage: object) -> str:
    """Build tiny indicator string showing which fields are set."""
    parts: list[str] = []
    if getattr(stage, "start_date", None):
        parts.append("📅")
    if getattr(stage, "responsible_contact", None):
        parts.append("👤")
    if getattr(stage, "budget", None):
        parts.append("💰")
    return " " + "".join(parts) if parts else ""


def project_select_keyboard(
    projects: Sequence,
) -> InlineKeyboardMarkup:
    """Show a list of projects for the user to select."""
    rows = [
        [InlineKeyboardButton(
            text=f"🏠 {p.name}",
            callback_data=f"prjsel:{p.id}",
        )]
        for p in projects
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def stages_list_keyboard(
    stages: Sequence,
    show_launch: bool = True,
) -> InlineKeyboardMarkup:
    """
    Stage list as inline buttons with status icons and indicators.

    Each button shows: icon + order + name + indicators (📅👤💰).
    """
    rows: list[list[InlineKeyboardButton]] = []

    main_stages = [s for s in stages if not s.is_parallel]
    parallel_stages = [s for s in stages if s.is_parallel]

    for stage in main_stages:
        icon = _STATUS_ICONS.get(stage.status.value, "📋")
        info = _stage_indicators(stage)
        rows.append([
            InlineKeyboardButton(
                text=f"{icon} {stage.order}. {stage.name}{info}",
                callback_data=f"stg:{stage.id}",
            )
        ])

    if parallel_stages:
        for stage in parallel_stages:
            icon = _STATUS_ICONS.get(stage.status.value, "📋")
            info = _stage_indicators(stage)
            rows.append([
                InlineKeyboardButton(
                    text=f"{icon} • {stage.name}{info}",
                    callback_data=f"stg:{stage.id}",
                )
            ])

    if show_launch:
        rows.append([
            InlineKeyboardButton(
                text="🚀 Запустить проект",
                callback_data="launch",
            ),
        ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def stage_actions_keyboard(stage_id: int) -> InlineKeyboardMarkup:
    """Action buttons for a single stage."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📅 Сроки", callback_data=f"stgdt:{stage_id}"),
            InlineKeyboardButton(text="👤 Ответственный", callback_data=f"stgprs:{stage_id}"),
        ],
        [
            InlineKeyboardButton(text="💰 Бюджет", callback_data=f"stgbdg:{stage_id}"),
            InlineKeyboardButton(text="📝 Подзадачи", callback_data=f"stgsub:{stage_id}"),
        ],
        [
            InlineKeyboardButton(text="🔄 Статус", callback_data=f"stgchst:{stage_id}"),
        ],
        [
            InlineKeyboardButton(text="↩️ К списку этапов", callback_data="stgback"),
        ],
    ])


def date_method_keyboard(stage_id: int) -> InlineKeyboardMarkup:
    """Choose how to enter dates: duration or exact dates."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="⏱ Длительность (дни)",
                callback_data=f"stgdur:{stage_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="📅 Точные даты",
                callback_data=f"stgex:{stage_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="↩️ Назад",
                callback_data=f"stg:{stage_id}",
            ),
        ],
    ])


def substages_keyboard(
    stage_id: int,
    sub_stages: Sequence,
) -> InlineKeyboardMarkup:
    """Show existing sub-stages and an 'Add' button."""
    rows: list[list[InlineKeyboardButton]] = []

    for sub in sub_stages:
        icon = _STATUS_ICONS.get(sub.status.value, "📋")
        rows.append([
            InlineKeyboardButton(
                text=f"{icon} {sub.order}. {sub.name}",
                callback_data=f"substg:{sub.id}",  # for future detail view
            )
        ])

    rows.append([
        InlineKeyboardButton(
            text="➕ Добавить подзадачи",
            callback_data=f"stgsuba:{stage_id}",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            text="↩️ Назад",
            callback_data=f"stg:{stage_id}",
        ),
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def launch_keyboard(is_ready: bool = True) -> InlineKeyboardMarkup:
    """Launch confirmation buttons."""
    rows: list[list[InlineKeyboardButton]] = []

    if is_ready:
        rows.append([
            InlineKeyboardButton(
                text="🚀 Запустить",
                callback_data="launch_yes",
            ),
        ])

    rows.append([
        InlineKeyboardButton(
            text="↩️ К этапам",
            callback_data="stgback",
        ),
    ])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def back_to_stage_keyboard(stage_id: int) -> InlineKeyboardMarkup:
    """Simple back button to return to stage detail."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="↩️ Назад к этапу",
                callback_data=f"stg:{stage_id}",
            ),
        ],
    ])


# ── Role management keyboards (Phase 4) ───────────────────────


def role_select_keyboard() -> InlineKeyboardMarkup:
    """Select a role to assign to a new team member."""
    from bot.core.role_service import ASSIGNABLE_ROLES, ROLE_LABELS

    rows: list[list[InlineKeyboardButton]] = []
    for role in ASSIGNABLE_ROLES:
        rows.append([
            InlineKeyboardButton(
                text=ROLE_LABELS.get(role, role.value),
                callback_data=f"role:{role.value}",
            )
        ])
    rows.append([
        InlineKeyboardButton(text="❌ Отмена", callback_data="role:cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def invite_confirm_keyboard() -> InlineKeyboardMarkup:
    """Confirm or cancel an invitation."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Пригласить",
                callback_data="inv:yes",
            ),
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data="inv:cancel",
            ),
        ],
    ])


def team_member_keyboard(
    user_id: int,
    project_id: int,
) -> InlineKeyboardMarkup:
    """Actions for a team member (for the owner)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🗑 Удалить из проекта",
                callback_data=f"tmrm:{project_id}:{user_id}",
            ),
        ],
    ])


# ── Notification / checkpoint keyboards (Phase 5) ────────────


def checkpoint_keyboard(stage_id: int) -> InlineKeyboardMarkup:
    """Checkpoint approval / rejection buttons."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="✅ Одобрить",
                callback_data=f"chkpt:approve:{stage_id}",
            ),
            InlineKeyboardButton(
                text="❌ Отклонить",
                callback_data=f"chkpt:reject:{stage_id}",
            ),
        ],
    ])


def stage_status_keyboard(stage_id: int) -> InlineKeyboardMarkup:
    """
    Change stage status — used in stage detail view.

    Shows available status transitions.
    """
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🔨 В работу",
                callback_data=f"stgsts:in_progress:{stage_id}",
            ),
            InlineKeyboardButton(
                text="✅ Завершить",
                callback_data=f"stgcomplete:{stage_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="⚠️ Задержка",
                callback_data=f"stgsts:delayed:{stage_id}",
            ),
            InlineKeyboardButton(
                text="📋 Запланирован",
                callback_data=f"stgsts:planned:{stage_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="↩️ Назад",
                callback_data=f"stg:{stage_id}",
            ),
        ],
    ])


# ── Budget keyboards (Phase 6) ───────────────────────────────


def budget_category_keyboard() -> InlineKeyboardMarkup:
    """Select a budget category for a new expense."""
    from bot.core.budget_service import CATEGORY_LABELS
    from bot.db.models import BudgetCategory

    rows: list[list[InlineKeyboardButton]] = []
    # Two columns layout
    cats = list(BudgetCategory)
    for i in range(0, len(cats), 2):
        row = []
        for cat in cats[i:i + 2]:
            label = CATEGORY_LABELS.get(cat.value, cat.value)
            row.append(InlineKeyboardButton(
                text=label,
                callback_data=f"bcat:{cat.value}",
            ))
        rows.append(row)

    rows.append([
        InlineKeyboardButton(text="❌ Отмена", callback_data="bcat:cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def budget_overview_keyboard(project_id: int) -> InlineKeyboardMarkup:
    """Actions available from the budget overview screen."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="➕ Добавить расход",
                callback_data=f"badd:{project_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="📊 По категориям",
                callback_data=f"bcats:{project_id}",
            ),
            InlineKeyboardButton(
                text="🔍 Не подтверждённые",
                callback_data=f"bunconf:{project_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="📜 История изменений",
                callback_data=f"bhist:{project_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                text="💳 Оплата этапов",
                callback_data=f"bpay:{project_id}",
            ),
        ],
    ])


def budget_item_keyboard(item_id: int, is_confirmed: bool) -> InlineKeyboardMarkup:
    """Actions for a single budget item."""
    rows: list[list[InlineKeyboardButton]] = []

    if not is_confirmed:
        rows.append([
            InlineKeyboardButton(
                text="✅ Подтвердить",
                callback_data=f"bconf:{item_id}",
            ),
        ])

    rows.append([
        InlineKeyboardButton(
            text="🗑 Удалить",
            callback_data=f"bdel:{item_id}",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            text="↩️ К бюджету",
            callback_data="bback",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def budget_items_list_keyboard(
    items: Sequence,
    project_id: int,
) -> InlineKeyboardMarkup:
    """List budget items as buttons."""
    from bot.core.budget_service import get_category_label

    rows: list[list[InlineKeyboardButton]] = []
    for item in items:
        confirmed = "✅" if item.is_confirmed else "❓"
        total = float(item.work_cost) + float(item.material_cost)
        label = f"{confirmed} {get_category_label(item.category)}: {total:,.0f} ₸"
        if len(label) > 50:
            label = label[:47] + "..."
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"bitem:{item.id}",
            ),
        ])

    rows.append([
        InlineKeyboardButton(
            text="↩️ К бюджету",
            callback_data="bback",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_status_keyboard(stage_id: int, current_status: str) -> InlineKeyboardMarkup:
    """Show available payment status transitions for a stage."""
    from bot.core.budget_service import (
        PAYMENT_STATUS_LABELS,
        get_allowed_payment_transitions,
    )

    transitions = get_allowed_payment_transitions(current_status)
    rows: list[list[InlineKeyboardButton]] = []

    for status in transitions:
        label = PAYMENT_STATUS_LABELS.get(status, status)
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"bpysts:{status}:{stage_id}",
            ),
        ])

    rows.append([
        InlineKeyboardButton(
            text="↩️ Назад",
            callback_data="bback",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def payment_stages_keyboard(stages: Sequence) -> InlineKeyboardMarkup:
    """Show stages with their payment status for selection."""
    from bot.core.budget_service import PAYMENT_STATUS_ICONS

    rows: list[list[InlineKeyboardButton]] = []
    for stage in stages:
        icon = PAYMENT_STATUS_ICONS.get(stage.payment_status.value, "📝")
        rows.append([
            InlineKeyboardButton(
                text=f"{icon} {stage.order}. {stage.name}",
                callback_data=f"bpay_stg:{stage.id}",
            ),
        ])

    rows.append([
        InlineKeyboardButton(
            text="↩️ К бюджету",
            callback_data="bback",
        ),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def expense_type_keyboard() -> InlineKeyboardMarkup:
    """Choose what type of expense to enter."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="🔨 Работа",
                callback_data="betype:work",
            ),
            InlineKeyboardButton(
                text="🧱 Материалы",
                callback_data="betype:material",
            ),
        ],
        [
            InlineKeyboardButton(
                text="💵 Предоплата",
                callback_data="betype:prepayment",
            ),
        ],
        [
            InlineKeyboardButton(
                text="🔨+🧱 Работа + Материалы",
                callback_data="betype:both",
            ),
        ],
        [
            InlineKeyboardButton(
                text="❌ Отмена",
                callback_data="betype:cancel",
            ),
        ],
    ])


def skip_amount_keyboard() -> InlineKeyboardMarkup:
    """Skip entering an optional amount (0)."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text="⏭ Пропустить (0 ₸)",
                callback_data="bskip:0",
            ),
        ],
    ])
