"""
Standard renovation stages and parallel (custom furniture) stages.

These templates define the default stages auto-generated when a project
is created. The user can edit them before confirming.
"""

# ── Standard sequential stages ───────────────────────────────
# Order matches the typical renovation workflow.
# is_checkpoint = True means client approval is required before proceeding.

STANDARD_STAGES: list[dict] = [
    {"name": "Демонтаж",                    "order": 1,  "is_checkpoint": False},
    {"name": "Электрика",                   "order": 2,  "is_checkpoint": True},
    {"name": "Сантехника",                  "order": 3,  "is_checkpoint": True},
    {"name": "Штукатурка",                  "order": 4,  "is_checkpoint": False},
    {"name": "Стяжка пола",                 "order": 5,  "is_checkpoint": False},
    {"name": "Плитка",                      "order": 6,  "is_checkpoint": True},
    {"name": "Шпаклёвка",                   "order": 7,  "is_checkpoint": True},
    {"name": "Покраска / обои",             "order": 8,  "is_checkpoint": False},
    {"name": "Напольное покрытие",          "order": 9,  "is_checkpoint": False},
    {"name": "Установка дверей",            "order": 10, "is_checkpoint": False},
    {"name": "Чистовая электрика",          "order": 11, "is_checkpoint": False},
    {"name": "Чистовая сантехника",         "order": 12, "is_checkpoint": False},
    {"name": "Финальная приёмка",           "order": 13, "is_checkpoint": True},
]


# ── Parallel stages for custom items ─────────────────────────
# Each custom item (kitchen, wardrobes, etc.) follows the same sub-flow:
# Measurement → Contract & prepayment → Production → Delivery → Installation

CUSTOM_ITEM_LABELS: dict[str, str] = {
    "kitchen":     "Кухня",
    "wardrobes":   "Шкафы",
    "walkin":      "Гардеробная",
    "doors":       "Двери на заказ",
}

CUSTOM_ITEM_SUBSTAGES: list[str] = [
    "Замер",
    "Договор и предоплата",
    "Производство",
    "Доставка",
    "Монтаж",
]


def build_parallel_stages(
    selected_items: list[str],
    start_order: int = 100,
) -> list[dict]:
    """
    Build parallel stage definitions for selected custom items.

    Args:
        selected_items: keys from CUSTOM_ITEM_LABELS (e.g. ["kitchen", "wardrobes"])
        start_order: order offset for parallel stages (high number so they sort after main stages)

    Returns:
        List of stage definitions ready for create_stages_for_project()
    """
    stages = []
    for idx, item_key in enumerate(selected_items):
        label = CUSTOM_ITEM_LABELS.get(item_key, item_key)
        for sub_idx, substage_name in enumerate(CUSTOM_ITEM_SUBSTAGES):
            stages.append({
                "name": f"{label} → {substage_name}",
                "order": start_order + (idx * 10) + sub_idx,
                "is_checkpoint": False,
                "is_parallel": True,
            })
    return stages
