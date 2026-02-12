"""
Core service for project creation.

Contains platform-agnostic business logic for creating a renovation project,
assigning the owner role, generating default stages, and adding parallel
stages for custom furniture/fittings.

This service is called by platform adapters (Telegram, WhatsApp) but
never imports platform-specific code. Formatting / presentation logic
lives in platform adapters (e.g. adapters/telegram/formatters.py).
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from bot.core.stage_templates import STANDARD_STAGES, build_parallel_stages
from bot.db.models import Project, RenovationType, RoleType
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
    platform: str | None = None,
    platform_chat_id: str | None = None,
    custom_items: list[str] | None = None,
) -> Project:
    """
    Full project creation flow:
    1. Create the project record
    2. Assign the creator as OWNER
    3. Generate standard renovation stages
    4. Add parallel stages for custom items (if any)

    Args:
        platform: Messaging platform identifier ("telegram", "whatsapp")
        platform_chat_id: Chat/group ID on the platform (as string)

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
        platform=platform,
        platform_chat_id=platform_chat_id,
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
