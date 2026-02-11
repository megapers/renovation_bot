"""
Database repository for Project-related operations.

All raw database queries live here. Core business logic calls these
functions instead of touching SQLAlchemy directly, keeping the layers
cleanly separated.
"""

import logging
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import (
    Project,
    ProjectRole,
    RenovationType,
    RoleType,
    Stage,
    User,
)

logger = logging.getLogger(__name__)


async def create_project(
    session: AsyncSession,
    *,
    name: str,
    address: str | None = None,
    area_sqm: float | None = None,
    renovation_type: RenovationType,
    total_budget: float | None = None,
    telegram_chat_id: int | None = None,
) -> Project:
    """Create a new renovation project."""
    project = Project(
        name=name,
        address=address,
        area_sqm=area_sqm,
        renovation_type=renovation_type,
        total_budget=total_budget,
        telegram_chat_id=telegram_chat_id,
    )
    session.add(project)
    await session.flush()  # get project.id without committing
    logger.info("Created project: %s (id=%d)", name, project.id)
    return project


async def assign_role(
    session: AsyncSession,
    *,
    project_id: int,
    user_id: int,
    role: RoleType,
) -> ProjectRole:
    """Assign a role to a user within a project."""
    project_role = ProjectRole(
        project_id=project_id,
        user_id=user_id,
        role=role,
    )
    session.add(project_role)
    await session.flush()
    logger.info("Assigned role %s to user_id=%d in project_id=%d", role.value, user_id, project_id)
    return project_role


async def create_stages_for_project(
    session: AsyncSession,
    *,
    project_id: int,
    stage_definitions: list[dict],
) -> list[Stage]:
    """
    Bulk-create stages for a project from a list of definitions.

    Each definition: {"name": str, "order": int, "is_checkpoint": bool}
    """
    stages = []
    for defn in stage_definitions:
        stage = Stage(
            project_id=project_id,
            name=defn["name"],
            order=defn["order"],
            is_checkpoint=defn.get("is_checkpoint", False),
            is_parallel=defn.get("is_parallel", False),
        )
        session.add(stage)
        stages.append(stage)
    await session.flush()
    logger.info("Created %d stages for project_id=%d", len(stages), project_id)
    return stages


async def get_project_with_stages(
    session: AsyncSession,
    project_id: int,
) -> Project | None:
    """Load a project with its stages eagerly loaded."""
    result = await session.execute(
        select(Project)
        .where(Project.id == project_id)
        .options(selectinload(Project.stages))
    )
    return result.scalar_one_or_none()


async def get_user_projects(
    session: AsyncSession,
    user_id: int,
) -> Sequence[Project]:
    """Get all active projects where the user has a role."""
    result = await session.execute(
        select(Project)
        .join(ProjectRole)
        .where(
            ProjectRole.user_id == user_id,
            Project.is_active == True,  # noqa: E712
        )
    )
    return result.scalars().all()


async def get_user_by_telegram_id(
    session: AsyncSession,
    telegram_id: int,
) -> User | None:
    """Find a user by their Telegram ID."""
    result = await session.execute(
        select(User).where(User.telegram_id == telegram_id)
    )
    return result.scalar_one_or_none()
