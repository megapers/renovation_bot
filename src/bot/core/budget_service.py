"""
Core budget service — platform-agnostic.

Business logic for budget tracking, payment lifecycle, and change
history. Platform adapters call these functions and handle formatting.

This module never imports platform-specific code.
"""

import logging

from bot.db.models import BudgetCategory, PaymentStatus, StageStatus

logger = logging.getLogger(__name__)


# ── Budget categories ────────────────────────────────────────

CATEGORY_LABELS: dict[str, str] = {
    BudgetCategory.ELECTRICAL.value: "⚡ Электрика",
    BudgetCategory.PLUMBING.value: "🚿 Сантехника",
    BudgetCategory.WALLS.value: "🧱 Стены",
    BudgetCategory.FLOORING.value: "🪵 Полы",
    BudgetCategory.TILING.value: "🔲 Плитка",
    BudgetCategory.CEILINGS.value: "🏗 Потолки",
    BudgetCategory.DOORS.value: "🚪 Двери",
    BudgetCategory.FURNITURE.value: "🪑 Мебель",
    BudgetCategory.DEMOLITION.value: "🔨 Демонтаж",
    BudgetCategory.PAINTING.value: "🎨 Покраска/обои",
    BudgetCategory.OTHER.value: "📦 Прочее",
}

# Map stage names to budget categories for auto-linking
STAGE_TO_CATEGORY: dict[str, str] = {
    "демонтаж": BudgetCategory.DEMOLITION.value,
    "электрика": BudgetCategory.ELECTRICAL.value,
    "сантехника": BudgetCategory.PLUMBING.value,
    "штукатурка": BudgetCategory.WALLS.value,
    "стяжка": BudgetCategory.FLOORING.value,
    "плитка": BudgetCategory.TILING.value,
    "шпаклёвка": BudgetCategory.WALLS.value,
    "шпаклевка": BudgetCategory.WALLS.value,
    "покраска": BudgetCategory.PAINTING.value,
    "обои": BudgetCategory.PAINTING.value,
    "пол": BudgetCategory.FLOORING.value,
    "двери": BudgetCategory.DOORS.value,
    "потолк": BudgetCategory.CEILINGS.value,
    "мебель": BudgetCategory.FURNITURE.value,
    "кухн": BudgetCategory.FURNITURE.value,
    "шкаф": BudgetCategory.FURNITURE.value,
    "гардероб": BudgetCategory.FURNITURE.value,
}


def get_category_label(category: str) -> str:
    """Get a human-readable label for a budget category."""
    return CATEGORY_LABELS.get(category, f"📦 {category}")


def guess_category_from_stage(stage_name: str) -> str:
    """
    Guess the budget category from a stage name.

    Falls back to 'other' if no match found.
    """
    name_lower = stage_name.lower()
    for keyword, cat in STAGE_TO_CATEGORY.items():
        if keyword in name_lower:
            return cat
    return BudgetCategory.OTHER.value


# ── Payment lifecycle ────────────────────────────────────────

PAYMENT_STATUS_LABELS: dict[str, str] = {
    PaymentStatus.RECORDED.value: "📝 Записано",
    PaymentStatus.IN_PROGRESS.value: "🔄 В процессе",
    PaymentStatus.VERIFIED.value: "✅ Проверено",
    PaymentStatus.PAID.value: "💸 Оплачено",
    PaymentStatus.CLOSED.value: "🔒 Закрыто",
}

PAYMENT_STATUS_ICONS: dict[str, str] = {
    PaymentStatus.RECORDED.value: "📝",
    PaymentStatus.IN_PROGRESS.value: "🔄",
    PaymentStatus.VERIFIED.value: "✅",
    PaymentStatus.PAID.value: "💸",
    PaymentStatus.CLOSED.value: "🔒",
}

# Valid payment status transitions
# Key: current status → Value: list of allowed next statuses
PAYMENT_TRANSITIONS: dict[str, list[str]] = {
    PaymentStatus.RECORDED.value: [
        PaymentStatus.IN_PROGRESS.value,
    ],
    PaymentStatus.IN_PROGRESS.value: [
        PaymentStatus.VERIFIED.value,
        PaymentStatus.RECORDED.value,  # rollback
    ],
    PaymentStatus.VERIFIED.value: [
        PaymentStatus.PAID.value,
        PaymentStatus.IN_PROGRESS.value,  # rollback
    ],
    PaymentStatus.PAID.value: [
        PaymentStatus.CLOSED.value,
        PaymentStatus.VERIFIED.value,  # rollback
    ],
    PaymentStatus.CLOSED.value: [],  # terminal state
}


def get_allowed_payment_transitions(current_status: str) -> list[str]:
    """Get allowed next payment statuses from the current one."""
    return PAYMENT_TRANSITIONS.get(current_status, [])


def validate_payment_transition(
    current_status: str,
    new_status: str,
) -> tuple[bool, str]:
    """
    Validate a payment status transition.

    Returns (is_valid, error_message).
    """
    allowed = get_allowed_payment_transitions(current_status)
    if new_status not in allowed:
        current_label = PAYMENT_STATUS_LABELS.get(current_status, current_status)
        new_label = PAYMENT_STATUS_LABELS.get(new_status, new_status)
        return False, (
            f"Нельзя перейти из {current_label} в {new_label}.\n"
            f"Допустимые переходы: "
            + ", ".join(PAYMENT_STATUS_LABELS.get(s, s) for s in allowed)
        )
    return True, ""


def check_payment_risk(stage_status: str, payment_status: str) -> str | None:
    """
    Check if there's a payment risk for a stage.

    Warns if payment is happening before verification.
    Returns a warning string or None.
    """
    # Risk: paying for unverified work
    if payment_status == PaymentStatus.PAID.value and stage_status != StageStatus.COMPLETED.value:
        return (
            "⚠️ ВНИМАНИЕ: оплата произведена, но этап ещё не завершён!\n"
            "Рекомендуется завершить и проверить работу перед оплатой."
        )

    # Risk: paying without verification
    if payment_status == PaymentStatus.PAID.value:
        return (
            "💡 Совет: перед оплатой рекомендуется вызвать эксперта "
            "для проверки качества работ."
        )

    # Risk: stage closed but payment not closed
    if stage_status == StageStatus.COMPLETED.value and payment_status == PaymentStatus.RECORDED.value:
        return (
            "ℹ️ Этап завершён, но оплата ещё не оформлена.\n"
            "Не забудьте записать расходы."
        )

    return None


# ── Budget analysis ──────────────────────────────────────────


def analyze_budget(
    total_budget: float | None,
    total_spent: float,
    total_prepayments: float,
) -> dict:
    """
    Analyze budget usage and return status info.

    Returns:
        {
            "has_budget": bool,
            "remaining": float,
            "usage_pct": float,
            "status": "ok" | "warning" | "over",
            "message": str,
        }
    """
    if not total_budget or total_budget <= 0:
        return {
            "has_budget": False,
            "remaining": 0,
            "usage_pct": 0,
            "status": "ok",
            "message": "Общий бюджет не задан",
        }

    remaining = total_budget - total_spent
    usage_pct = (total_spent / total_budget) * 100

    if total_spent > total_budget:
        overspend = total_spent - total_budget
        return {
            "has_budget": True,
            "remaining": remaining,
            "usage_pct": usage_pct,
            "status": "over",
            "message": (
                f"Бюджет превышен на {overspend:,.0f} ₸ ({usage_pct:.0f}%)"
            ),
        }
    elif usage_pct >= 90:
        return {
            "has_budget": True,
            "remaining": remaining,
            "usage_pct": usage_pct,
            "status": "warning",
            "message": (
                f"Бюджет на исходе! Использовано {usage_pct:.0f}%, "
                f"осталось {remaining:,.0f} ₸"
            ),
        }
    else:
        return {
            "has_budget": True,
            "remaining": remaining,
            "usage_pct": usage_pct,
            "status": "ok",
            "message": (
                f"Использовано {usage_pct:.0f}%, осталось {remaining:,.0f} ₸"
            ),
        }


def parse_expense_amount(text: str) -> float | None:
    """
    Parse an expense amount from user input.

    Handles: "500000", "500 000", "500,000", "1500.50", etc.
    Returns None if parsing fails.
    """
    text = text.strip().replace(" ", "").replace(",", ".")
    # Remove currency symbols
    for sym in ("₸", "тг", "руб", "₽", "$", "€"):
        text = text.replace(sym, "")
    text = text.strip()
    try:
        amount = float(text)
        if amount < 0:
            return None
        return amount
    except ValueError:
        return None
