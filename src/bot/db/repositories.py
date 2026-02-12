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


# ── Role & team management (Phase 4) ────────────────────────


async def get_user_roles_in_project(
    session: AsyncSession,
    user_id: int,
    project_id: int,
) -> list[RoleType]:
    """Get all roles a user has in a specific project."""
    result = await session.execute(
        select(ProjectRole.role)
        .where(
            ProjectRole.user_id == user_id,
            ProjectRole.project_id == project_id,
        )
    )
    return list(result.scalars().all())


async def get_project_by_telegram_chat_id(
    session: AsyncSession,
    chat_id: int,
) -> Project | None:
    """Find a project linked to a Telegram group chat."""
    result = await session.execute(
        select(Project).where(Project.telegram_chat_id == chat_id)
    )
    return result.scalar_one_or_none()


async def get_project_team(
    session: AsyncSession,
    project_id: int,
) -> list[tuple[User, list[RoleType]]]:
    """
    Get all team members for a project, grouped by user.

    Returns list of (User, [RoleType, ...]) tuples.
    """
    result = await session.execute(
        select(ProjectRole)
        .where(ProjectRole.project_id == project_id)
        .options(selectinload(ProjectRole.user))
        .order_by(ProjectRole.role)
    )
    roles = result.scalars().all()

    # Group roles by user
    user_roles: dict[int, tuple[User, list[RoleType]]] = {}
    for pr in roles:
        if pr.user_id not in user_roles:
            user_roles[pr.user_id] = (pr.user, [])
        user_roles[pr.user_id][1].append(pr.role)

    return list(user_roles.values())


async def get_or_create_user_by_telegram_id(
    session: AsyncSession,
    telegram_id: int,
    full_name: str = "Unknown",
) -> tuple[User, bool]:
    """
    Find or create a user by Telegram ID.

    Returns (user, created) where created is True if user was newly created.
    """
    user = await get_user_by_telegram_id(session, telegram_id)
    if user:
        return user, False

    user = User(
        telegram_id=telegram_id,
        full_name=full_name,
        is_bot_started=False,
    )
    session.add(user)
    await session.flush()
    logger.info("Created placeholder user: %s (tg_id=%d)", full_name, telegram_id)
    return user, True


async def has_role_in_project(
    session: AsyncSession,
    user_id: int,
    project_id: int,
    role: RoleType | None = None,
) -> bool:
    """
    Check if a user has any role (or a specific role) in a project.

    If role is None, checks for any role.
    """
    query = select(ProjectRole.id).where(
        ProjectRole.user_id == user_id,
        ProjectRole.project_id == project_id,
    )
    if role is not None:
        query = query.where(ProjectRole.role == role)
    result = await session.execute(query.limit(1))
    return result.scalar_one_or_none() is not None


async def remove_role(
    session: AsyncSession,
    user_id: int,
    project_id: int,
    role: RoleType,
) -> bool:
    """
    Remove a specific role from a user in a project.

    Returns True if a role was actually removed.
    """
    result = await session.execute(
        select(ProjectRole).where(
            ProjectRole.user_id == user_id,
            ProjectRole.project_id == project_id,
            ProjectRole.role == role,
        )
    )
    pr = result.scalar_one_or_none()
    if pr is None:
        return False
    await session.delete(pr)
    await session.flush()
    logger.info("Removed role %s from user_id=%d in project_id=%d",
                role.value, user_id, project_id)
    return True


async def link_project_to_chat(
    session: AsyncSession,
    project_id: int,
    telegram_chat_id: int,
) -> Project | None:
    """Link a project to a Telegram group chat."""
    result = await session.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        return None
    project.telegram_chat_id = telegram_chat_id
    await session.flush()
    logger.info("Linked project_id=%d to telegram_chat_id=%d",
                project_id, telegram_chat_id)
    return project
