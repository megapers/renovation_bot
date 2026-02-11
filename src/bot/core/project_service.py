"""
Core service for project creation.

Contains platform-agnostic business logic for creating a renovation project,
assigning the owner role, generating default stages, and adding parallel
stages for custom furniture/fittings.

This service is called by platform adapters (Telegram, WhatsApp) but
never imports platform-specific code.
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.stage_templates import STANDARD_STAGES, build_parallel_stages
from bot.db.models import Project, RenovationType, RoleType, Stage
from bot.db.repositories import (
    assign_role,
    create_project,
    create_stages_for_project,
    get_project_with_stages,
)

logger = logging.getLogger(__name__)


async def create_renovation_project(
    session: AsyncSession,
    *,
    owner_user_id: int,
    name: str,
    address: str | None = None,
    area_sqm: float | None = None,
    renovation_type: RenovationType,
    total_budget: float | None = None,
    telegram_chat_id: int | None = None,
    custom_items: list[str] | None = None,
) -> Project:
    """
    Full project creation flow:
    1. Create the project record
    2. Assign the creator as OWNER
    3. Generate standard renovation stages
    4. Add parallel stages for custom items (if any)

    Returns the created Project with stages loaded.
    """
    # 1. Create project
    project = await create_project(
        session,
        name=name,
        address=address,
        area_sqm=area_sqm,
        renovation_type=renovation_type,
        total_budget=total_budget,
        telegram_chat_id=telegram_chat_id,
    )

    # 2. Assign owner role
    await assign_role(
        session,
        project_id=project.id,
        user_id=owner_user_id,
        role=RoleType.OWNER,
    )

    # 3. Generate standard stages
    all_stages = list(STANDARD_STAGES)

    # 4. Add parallel stages for custom items
    if custom_items:
        parallel = build_parallel_stages(custom_items)
        all_stages.extend(parallel)

    await create_stages_for_project(
        session,
        project_id=project.id,
        stage_definitions=all_stages,
    )

    logger.info(
        "Project '%s' fully created: id=%d, owner_user_id=%d, %d stages",
        name, project.id, owner_user_id, len(all_stages),
    )

    # Reload with stages
    result = await get_project_with_stages(session, project.id)
    return result  # type: ignore[return-value]


def format_project_summary(project: Project) -> str:
    """
    Format a project summary for display to the user.

    Platform adapters may wrap this in platform-specific formatting
    (HTML for Telegram, plain text for WhatsApp).
    """
    type_labels = {
        RenovationType.COSMETIC: "Косметический",
        RenovationType.STANDARD: "Стандартный",
        RenovationType.MAJOR: "Капитальный",
        RenovationType.DESIGNER: "Дизайнерский",
    }

    lines = [
        f"🏠 <b>{project.name}</b>",
        "",
    ]

    if project.address:
        lines.append(f"📍 Адрес: {project.address}")
    if project.area_sqm:
        lines.append(f"📐 Площадь: {project.area_sqm} м²")

    lines.append(f"🔧 Тип ремонта: {type_labels.get(project.renovation_type, project.renovation_type.value)}")

    if project.total_budget:
        lines.append(f"💰 Бюджет: {project.total_budget:,.0f} ₸")

    if project.stages:
        lines.append("")
        lines.append(f"📋 <b>Этапы ({len(project.stages)}):</b>")

        # Separate main and parallel stages
        main_stages = [s for s in project.stages if not s.is_parallel]
        parallel_stages = [s for s in project.stages if s.is_parallel]

        for stage in main_stages:
            checkpoint = " ✅" if stage.is_checkpoint else ""
            lines.append(f"  {stage.order}. {stage.name}{checkpoint}")

        if parallel_stages:
            lines.append("")
            lines.append("  <b>Параллельные (мебель на заказ):</b>")
            for stage in parallel_stages:
                lines.append(f"  • {stage.name}")

    return "\n".join(lines)
