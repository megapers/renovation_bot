"""
Core role & permissions service.

Defines what each role is allowed to do, provides permission-checking
helpers, and maps roles to human-readable labels (Russian).

This module is platform-agnostic — imported by adapters, never by
platform-specific code.
"""

import enum
import logging
from typing import Sequence

from bot.db.models import RoleType

logger = logging.getLogger(__name__)


# ── Permission definitions ───────────────────────────────────


class Permission(str, enum.Enum):
    """Granular actions that can be allowed or denied per role."""

    # Project management
    CREATE_PROJECT = "create_project"
    EDIT_PROJECT = "edit_project"
    LAUNCH_PROJECT = "launch_project"
    CLOSE_PROJECT = "close_project"
    INVITE_MEMBER = "invite_member"

    # Stage management
    VIEW_STAGES = "view_stages"
    EDIT_STAGE = "edit_stage"           # dates, responsible, budget
    UPDATE_STATUS = "update_status"     # mark stage in_progress / completed
    ADD_SUB_STAGES = "add_sub_stages"
    APPROVE_CHECKPOINT = "approve_checkpoint"

    # Budget
    VIEW_BUDGET = "view_budget"
    EDIT_BUDGET = "edit_budget"
    CONFIRM_BUDGET = "confirm_budget"   # owner-only

    # Reports
    VIEW_REPORTS = "view_reports"
    REQUEST_REPORT = "request_report"

    # Workers
    VIEW_MY_STAGE = "view_my_stage"     # tradesperson's assigned stage
    SEND_STATUS = "send_status"         # status update / photo
    PROPOSE_WORK = "propose_work"       # propose additional work

    # Expert
    REQUEST_EXPERT = "request_expert"
    CONDUCT_INSPECTION = "conduct_inspection"


# Role → set of allowed permissions
ROLE_PERMISSIONS: dict[RoleType, set[Permission]] = {
    RoleType.OWNER: {
        Permission.CREATE_PROJECT,
        Permission.EDIT_PROJECT,
        Permission.LAUNCH_PROJECT,
        Permission.CLOSE_PROJECT,
        Permission.INVITE_MEMBER,
        Permission.VIEW_STAGES,
        Permission.EDIT_STAGE,
        Permission.UPDATE_STATUS,
        Permission.ADD_SUB_STAGES,
        Permission.APPROVE_CHECKPOINT,
        Permission.VIEW_BUDGET,
        Permission.EDIT_BUDGET,
        Permission.CONFIRM_BUDGET,
        Permission.VIEW_REPORTS,
        Permission.REQUEST_REPORT,
        Permission.VIEW_MY_STAGE,
        Permission.REQUEST_EXPERT,
    },
    RoleType.CO_OWNER: {
        Permission.VIEW_STAGES,
        Permission.VIEW_BUDGET,
        Permission.VIEW_REPORTS,
        Permission.REQUEST_REPORT,
        Permission.VIEW_MY_STAGE,
        Permission.REQUEST_EXPERT,
    },
    RoleType.FOREMAN: {
        Permission.INVITE_MEMBER,
        Permission.VIEW_STAGES,
        Permission.EDIT_STAGE,
        Permission.UPDATE_STATUS,
        Permission.ADD_SUB_STAGES,
        Permission.VIEW_BUDGET,
        Permission.EDIT_BUDGET,
        Permission.VIEW_REPORTS,
        Permission.VIEW_MY_STAGE,
        Permission.SEND_STATUS,
        Permission.PROPOSE_WORK,
    },
    RoleType.TRADESPERSON: {
        Permission.VIEW_STAGES,
        Permission.VIEW_MY_STAGE,
        Permission.SEND_STATUS,
        Permission.PROPOSE_WORK,
    },
    RoleType.DESIGNER: {
        Permission.VIEW_STAGES,
        Permission.EDIT_STAGE,
        Permission.ADD_SUB_STAGES,
        Permission.VIEW_BUDGET,
        Permission.VIEW_REPORTS,
        Permission.VIEW_MY_STAGE,
        Permission.SEND_STATUS,
    },
    RoleType.SUPPLIER: {
        Permission.VIEW_MY_STAGE,
        Permission.SEND_STATUS,
    },
    RoleType.EXPERT: {
        Permission.VIEW_STAGES,
        Permission.VIEW_BUDGET,
        Permission.CONDUCT_INSPECTION,
    },
    RoleType.VIEWER: {
        Permission.VIEW_STAGES,
        Permission.VIEW_BUDGET,
        Permission.VIEW_REPORTS,
    },
}


# ── Role labels (Russian) ───────────────────────────────────

ROLE_LABELS: dict[RoleType, str] = {
    RoleType.OWNER: "👑 Владелец",
    RoleType.CO_OWNER: "👥 Совладелец",
    RoleType.FOREMAN: "👷 Прораб",
    RoleType.TRADESPERSON: "🔧 Мастер",
    RoleType.DESIGNER: "🎨 Дизайнер",
    RoleType.SUPPLIER: "📦 Поставщик",
    RoleType.EXPERT: "🔍 Эксперт",
    RoleType.VIEWER: "👁 Наблюдатель",
}

# Roles that can be assigned via /invite (excludes OWNER — only one per project)
ASSIGNABLE_ROLES: list[RoleType] = [
    RoleType.CO_OWNER,
    RoleType.FOREMAN,
    RoleType.TRADESPERSON,
    RoleType.DESIGNER,
    RoleType.SUPPLIER,
    RoleType.EXPERT,
    RoleType.VIEWER,
]


# ── Permission-checking helpers ──────────────────────────────


def has_permission(
    roles: Sequence[RoleType],
    permission: Permission,
) -> bool:
    """
    Check if ANY of the user's roles grants the given permission.

    A user can have multiple roles in a project (e.g. Owner + Designer).
    """
    return any(
        permission in ROLE_PERMISSIONS.get(role, set())
        for role in roles
    )


def get_permissions(roles: Sequence[RoleType]) -> set[Permission]:
    """Get the union of all permissions from the given roles."""
    result: set[Permission] = set()
    for role in roles:
        result.update(ROLE_PERMISSIONS.get(role, set()))
    return result


def format_role_list(roles: Sequence[RoleType]) -> str:
    """Format a list of roles as a comma-separated string with labels."""
    return ", ".join(ROLE_LABELS.get(r, r.value) for r in roles)


def format_team_list(
    members: list[tuple[str, list[RoleType], bool]],
) -> str:
    """
    Format the project team for display.

    Args:
        members: list of (full_name, [roles], is_bot_started)
    """
    lines: list[str] = ["👥 <b>Команда проекта:</b>", ""]
    for name, roles, started in members:
        role_text = format_role_list(roles)
        status = "" if started else " ⚠️ (не запустил бота)"
        lines.append(f"• <b>{name}</b> — {role_text}{status}")
    return "\n".join(lines)
