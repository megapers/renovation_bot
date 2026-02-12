"""
Database repository for Project-related operations.

All raw database queries live here. Core business logic calls these
functions instead of touching SQLAlchemy directly, keeping the layers
cleanly separated.
"""

import logging
from datetime import datetime
from typing import Any, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import (
    Project,
    ProjectRole,
    RenovationType,
    RoleType,
    Stage,
    StageStatus,
    SubStage,
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


# ── Stage management (Phase 3) ──────────────────────────────


async def get_stages_for_project(
    session: AsyncSession,
    project_id: int,
) -> Sequence[Stage]:
    """Get all stages for a project with sub-stages, ordered by order."""
    result = await session.execute(
        select(Stage)
        .where(Stage.project_id == project_id)
        .options(selectinload(Stage.sub_stages))
        .order_by(Stage.order)
    )
    return result.scalars().all()


async def get_stage_with_substages(
    session: AsyncSession,
    stage_id: int,
) -> Stage | None:
    """Load a stage with its sub-stages eagerly loaded."""
    result = await session.execute(
        select(Stage)
        .where(Stage.id == stage_id)
        .options(selectinload(Stage.sub_stages))
    )
    return result.scalar_one_or_none()


async def update_stage(
    session: AsyncSession,
    stage_id: int,
    **fields: Any,
) -> Stage | None:
    """
    Update a stage's fields.

    Accepted keyword args match Stage column names:
      start_date, end_date, budget, responsible_contact,
      responsible_user_id, status, payment_status, etc.
    """
    result = await session.execute(
        select(Stage).where(Stage.id == stage_id)
    )
    stage = result.scalar_one_or_none()
    if stage is None:
        return None

    for key, value in fields.items():
        setattr(stage, key, value)
    await session.flush()
    logger.info("Updated stage id=%d: %s", stage_id, list(fields.keys()))
    return stage


async def create_sub_stages_bulk(
    session: AsyncSession,
    *,
    stage_id: int,
    names: list[str],
    start_order: int = 1,
) -> list[SubStage]:
    """Create multiple sub-stages for a stage."""
    sub_stages: list[SubStage] = []
    for idx, name in enumerate(names, start=start_order):
        sub = SubStage(
            stage_id=stage_id,
            name=name,
            order=idx,
        )
        session.add(sub)
        sub_stages.append(sub)
    await session.flush()
    logger.info("Created %d sub-stages for stage_id=%d", len(sub_stages), stage_id)
    return sub_stages


async def get_previous_stage(
    session: AsyncSession,
    stage: Stage,
) -> Stage | None:
    """Get the stage immediately before the given one (by order) in the same project."""
    result = await session.execute(
        select(Stage)
        .where(
            Stage.project_id == stage.project_id,
            Stage.order < stage.order,
        )
        .order_by(Stage.order.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def launch_project(
    session: AsyncSession,
    project_id: int,
) -> Stage | None:
    """
    Launch a project: set the first stage to IN_PROGRESS.

    Returns the first stage (now in progress) or None if no stages exist.
    """
    result = await session.execute(
        select(Stage)
        .where(Stage.project_id == project_id)
        .order_by(Stage.order)
        .limit(1)
    )
    first_stage = result.scalar_one_or_none()
    if first_stage:
        first_stage.status = StageStatus.IN_PROGRESS
        await session.flush()
        logger.info("Launched project_id=%d, first stage '%s' → IN_PROGRESS",
                     project_id, first_stage.name)
    return first_stage
