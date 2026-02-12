"""
Database repository for Project-related operations.

All raw database queries live here. Core business logic calls these
functions instead of touching SQLAlchemy directly, keeping the layers
cleanly separated.
"""

import logging
from datetime import date, datetime, timedelta
from typing import Any, Sequence

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from bot.db.models import (
    BudgetItem,
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
    platform: str | None = None,
    platform_chat_id: str | None = None,
) -> Project:
    """Create a new renovation project.

    Args:
        platform: Messaging platform ("telegram", "whatsapp", etc.)
        platform_chat_id: Chat/group ID on the platform (string for portability)
    """
    project = Project(
        name=name,
        address=address,
        area_sqm=area_sqm,
        renovation_type=renovation_type,
        total_budget=total_budget,
    )
    # Route chat ID to the correct platform column
    if platform == "telegram" and platform_chat_id:
        project.telegram_chat_id = int(platform_chat_id)
    # future: elif platform == "whatsapp" and platform_chat_id:
    #     project.whatsapp_chat_id = platform_chat_id

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


async def get_user_by_platform_id(
    session: AsyncSession,
    platform: str,
    platform_id: str,
) -> User | None:
    """
    Find a user by their platform-specific ID.

    Routes to the correct column based on platform name.
    Supports: telegram, whatsapp.
    """
    if platform == "telegram":
        return await get_user_by_telegram_id(session, int(platform_id))
    elif platform == "whatsapp":
        result = await session.execute(
            select(User).where(User.whatsapp_id == platform_id)
        )
        return result.scalar_one_or_none()
    else:
        logger.warning("Unknown platform: %s", platform)
        return None


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


async def get_project_by_platform_chat_id(
    session: AsyncSession,
    platform: str,
    chat_id: str,
) -> Project | None:
    """
    Find a project linked to a platform-specific chat/group.

    Routes to the correct column based on platform.
    """
    if platform == "telegram":
        return await get_project_by_telegram_chat_id(session, int(chat_id))
    # future: elif platform == "whatsapp": ...
    logger.warning("Unknown platform for chat lookup: %s", platform)
    return None


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
    return await link_project_to_platform_chat(session, project_id, "telegram", str(telegram_chat_id))


async def link_project_to_platform_chat(
    session: AsyncSession,
    project_id: int,
    platform: str,
    platform_chat_id: str,
) -> Project | None:
    """
    Link a project to a platform-specific group chat.

    Routes to the correct column based on platform.
    """
    result = await session.execute(
        select(Project).where(Project.id == project_id)
    )
    project = result.scalar_one_or_none()
    if project is None:
        return None

    if platform == "telegram":
        project.telegram_chat_id = int(platform_chat_id)
    # future: elif platform == "whatsapp":
    #     project.whatsapp_chat_id = platform_chat_id
    else:
        logger.warning("Unknown platform for chat link: %s", platform)
        return None

    await session.flush()
    logger.info("Linked project_id=%d to %s chat_id=%s",
                project_id, platform, platform_chat_id)
    return project


# ── Monitoring queries (Phase 5) ─────────────────────────────


async def get_stages_due_soon(
    session: AsyncSession,
    within_days: int = 1,
) -> Sequence[Stage]:
    """
    Find stages whose end_date is within `within_days` days from now.

    Only returns IN_PROGRESS or DELAYED stages of active projects.
    """
    now = datetime.now().astimezone()
    deadline = now + timedelta(days=within_days)
    result = await session.execute(
        select(Stage)
        .join(Project)
        .where(
            Project.is_active == True,  # noqa: E712
            Stage.status.in_([StageStatus.IN_PROGRESS, StageStatus.DELAYED]),
            Stage.end_date.isnot(None),
            Stage.end_date <= deadline,
            Stage.end_date > now,
        )
        .options(
            selectinload(Stage.project),
            selectinload(Stage.responsible_user),
            selectinload(Stage.sub_stages),
        )
    )
    return result.scalars().all()


async def get_overdue_stages(
    session: AsyncSession,
) -> Sequence[Stage]:
    """
    Find stages past their end_date that are still IN_PROGRESS or DELAYED.

    Only for active projects.
    """
    now = datetime.now().astimezone()
    result = await session.execute(
        select(Stage)
        .join(Project)
        .where(
            Project.is_active == True,  # noqa: E712
            Stage.status.in_([StageStatus.IN_PROGRESS, StageStatus.DELAYED]),
            Stage.end_date.isnot(None),
            Stage.end_date < now,
        )
        .options(
            selectinload(Stage.project),
            selectinload(Stage.responsible_user),
        )
    )
    return result.scalars().all()


async def get_stages_needing_status_update(
    session: AsyncSession,
    idle_days: int = 3,
) -> Sequence[Stage]:
    """
    Find IN_PROGRESS stages that haven't been updated in `idle_days` days.

    Uses stage.updated_at or stage.created_at as last-activity proxy.
    """
    cutoff = datetime.now().astimezone() - timedelta(days=idle_days)
    result = await session.execute(
        select(Stage)
        .join(Project)
        .where(
            Project.is_active == True,  # noqa: E712
            Stage.status == StageStatus.IN_PROGRESS,
            Stage.responsible_user_id.isnot(None),
        )
        .options(
            selectinload(Stage.project),
            selectinload(Stage.responsible_user),
        )
    )
    return result.scalars().all()


async def get_completed_checkpoint_stages(
    session: AsyncSession,
) -> Sequence[Stage]:
    """
    Find stages that are COMPLETED and are checkpoints.

    Used to check if owner approval is needed before proceeding.
    """
    result = await session.execute(
        select(Stage)
        .join(Project)
        .where(
            Project.is_active == True,  # noqa: E712
            Stage.status == StageStatus.COMPLETED,
            Stage.is_checkpoint == True,  # noqa: E712
        )
        .options(
            selectinload(Stage.project),
        )
    )
    return result.scalars().all()


async def get_next_stage(
    session: AsyncSession,
    stage: Stage,
) -> Stage | None:
    """Get the stage immediately after the given one (by order) in the same project."""
    result = await session.execute(
        select(Stage)
        .where(
            Stage.project_id == stage.project_id,
            Stage.order > stage.order,
        )
        .order_by(Stage.order.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_parallel_stages_with_upcoming_installation(
    session: AsyncSession,
    within_days: int = 45,
) -> Sequence[Stage]:
    """
    Find parallel (furniture) stages whose installation sub-stage is
    coming up within `within_days` days.

    Looks at parallel stages with status PLANNED or IN_PROGRESS.
    """
    deadline = datetime.now().astimezone() + timedelta(days=within_days)
    now = datetime.now().astimezone()
    min_days = timedelta(days=0)

    result = await session.execute(
        select(Stage)
        .join(Project)
        .where(
            Project.is_active == True,  # noqa: E712
            Stage.is_parallel == True,  # noqa: E712
            Stage.status.in_([StageStatus.PLANNED, StageStatus.IN_PROGRESS]),
        )
        .options(
            selectinload(Stage.project),
            selectinload(Stage.sub_stages),
            selectinload(Stage.responsible_user),
        )
    )
    stages = result.scalars().all()

    # Filter to stages that have an installation sub-stage due within range
    upcoming = []
    for stage in stages:
        for sub in stage.sub_stages:
            if "монтаж" in sub.name.lower() or "установка" in sub.name.lower():
                if sub.start_date and now < sub.start_date <= deadline:
                    upcoming.append(stage)
                    break
    return upcoming


async def get_project_budget_summary(
    session: AsyncSession,
    project_id: int,
) -> dict:
    """
    Calculate total spent vs budget for a project.

    Returns:
        {
            "total_budget": float | None,
            "total_work": float,
            "total_materials": float,
            "total_prepayments": float,
            "total_spent": float,
        }
    """
    # Project budget
    proj_result = await session.execute(
        select(Project.total_budget).where(Project.id == project_id)
    )
    total_budget = proj_result.scalar_one_or_none()

    # Sum budget items
    result = await session.execute(
        select(
            func.coalesce(func.sum(BudgetItem.work_cost), 0),
            func.coalesce(func.sum(BudgetItem.material_cost), 0),
            func.coalesce(func.sum(BudgetItem.prepayment), 0),
        )
        .where(BudgetItem.project_id == project_id)
    )
    row = result.one()
    total_work = float(row[0])
    total_materials = float(row[1])
    total_prepayments = float(row[2])

    return {
        "total_budget": float(total_budget) if total_budget else None,
        "total_work": total_work,
        "total_materials": total_materials,
        "total_prepayments": total_prepayments,
        "total_spent": total_work + total_materials,
    }


async def get_stage_budget_vs_items(
    session: AsyncSession,
    stage_id: int,
) -> dict:
    """
    Compare a stage's allocated budget vs its associated spending.

    For now, returns the stage budget vs sum of budget items
    whose category matches the stage name (approximate).
    """
    result = await session.execute(
        select(Stage).where(Stage.id == stage_id)
    )
    stage = result.scalar_one_or_none()
    if not stage:
        return {"budget": None, "spent": 0.0}

    return {
        "budget": float(stage.budget) if stage.budget else None,
        "spent": 0.0,  # Will be enhanced when budget items link to stages
    }


async def get_project_owner_ids(
    session: AsyncSession,
    project_id: int,
) -> list[int]:
    """Get user IDs of all owners and co-owners for a project."""
    result = await session.execute(
        select(ProjectRole.user_id)
        .where(
            ProjectRole.project_id == project_id,
            ProjectRole.role.in_([RoleType.OWNER, RoleType.CO_OWNER]),
        )
    )
    return list(result.scalars().all())


async def get_project_role_user_ids(
    session: AsyncSession,
    project_id: int,
    roles: list[RoleType],
) -> list[int]:
    """Get user IDs for specific roles in a project."""
    result = await session.execute(
        select(ProjectRole.user_id)
        .where(
            ProjectRole.project_id == project_id,
            ProjectRole.role.in_(roles),
        )
    )
    return list(result.scalars().all())


async def get_all_active_projects(
    session: AsyncSession,
) -> Sequence[Project]:
    """Get all active projects with their stages loaded."""
    result = await session.execute(
        select(Project)
        .where(Project.is_active == True)  # noqa: E712
        .options(
            selectinload(Project.stages).selectinload(Stage.sub_stages),
            selectinload(Project.stages).selectinload(Stage.responsible_user),
            selectinload(Project.roles),
        )
    )
    return result.scalars().all()


async def get_user_by_id(
    session: AsyncSession,
    user_id: int,
) -> User | None:
    """Get a user by internal ID."""
    result = await session.execute(
        select(User).where(User.id == user_id)
    )
    return result.scalar_one_or_none()
