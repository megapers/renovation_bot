"""
FSM (Finite State Machine) state definitions — platform-agnostic.

These are pure Python enums that define the conversation states for
multi-step flows. They contain NO platform-specific imports.

Each platform adapter maps these identifiers to its own FSM
implementation:
  - Telegram: aiogram StatesGroup (see adapters/telegram/fsm_states.py)
  - WhatsApp: session-based or Redis-backed state machine (future)
"""

import enum


class ProjectCreationState(str, enum.Enum):
    """States for the guided project creation flow."""

    WAITING_FOR_NAME = "project_creation:waiting_for_name"
    WAITING_FOR_ADDRESS = "project_creation:waiting_for_address"
    WAITING_FOR_AREA = "project_creation:waiting_for_area"
    WAITING_FOR_TYPE = "project_creation:waiting_for_type"
    WAITING_FOR_BUDGET = "project_creation:waiting_for_budget"
    WAITING_FOR_COORDINATOR = "project_creation:waiting_for_coordinator"
    WAITING_FOR_COORDINATOR_CONTACT = "project_creation:waiting_for_coordinator_contact"
    WAITING_FOR_CO_OWNER = "project_creation:waiting_for_co_owner"
    WAITING_FOR_CO_OWNER_CONTACT = "project_creation:waiting_for_co_owner_contact"
    WAITING_FOR_CUSTOM_ITEMS = "project_creation:waiting_for_custom_items"
    REVIEWING_STAGES = "project_creation:reviewing_stages"
    CONFIRMING = "project_creation:confirming"


class StageSetupState(str, enum.Enum):
    """States for stage configuration."""

    SELECTING_PROJECT = "stage_setup:selecting_project"
    VIEWING_STAGES = "stage_setup:viewing_stages"
    VIEWING_STAGE_DETAIL = "stage_setup:viewing_stage_detail"
    SETTING_START_DATE = "stage_setup:setting_start_date"
    SETTING_END_DATE = "stage_setup:setting_end_date"
    SETTING_DURATION = "stage_setup:setting_duration"
    ASSIGNING_PERSON = "stage_setup:assigning_person"
    SETTING_STAGE_BUDGET = "stage_setup:setting_stage_budget"
    ADDING_SUB_STAGES = "stage_setup:adding_sub_stages"
    CONFIRMING_LAUNCH = "stage_setup:confirming_launch"


class RoleManagementState(str, enum.Enum):
    """States for inviting and managing team members."""

    SELECTING_PROJECT = "role_management:selecting_project"
    CHOOSING_ROLE = "role_management:choosing_role"
    ENTERING_CONTACT = "role_management:entering_contact"
    CONFIRMING_INVITE = "role_management:confirming_invite"


class BudgetManagementState(str, enum.Enum):
    """States for budget and expense tracking."""

    SELECTING_PROJECT = "budget:selecting_project"
    VIEWING_BUDGET = "budget:viewing_budget"
    SELECTING_CATEGORY = "budget:selecting_category"
    ENTERING_DESCRIPTION = "budget:entering_description"
    ENTERING_WORK_COST = "budget:entering_work_cost"
    ENTERING_MATERIAL_COST = "budget:entering_material_cost"
    ENTERING_PREPAYMENT = "budget:entering_prepayment"
    VIEWING_ITEM = "budget:viewing_item"
    VIEWING_HISTORY = "budget:viewing_history"
