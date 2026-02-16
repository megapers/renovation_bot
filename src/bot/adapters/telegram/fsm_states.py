"""
Telegram-specific FSM state definitions using aiogram's StatesGroup.

These implement the platform-agnostic state identifiers defined in
bot.core.states using aiogram's FSM primitives. Only Telegram
handlers import from this module — core logic never does.

A WhatsApp adapter would implement its own state management
(e.g. session-based or redis-backed) without aiogram.
"""

from aiogram.fsm.state import State, StatesGroup


class ProjectCreation(StatesGroup):
    """
    States for the guided project creation flow.

    Flow: name → address → area → type → budget → coordinator → co-owner → stages → confirm
    """

    waiting_for_name = State()          # Step 1: Property name
    waiting_for_address = State()       # Step 2: Address
    waiting_for_area = State()          # Step 3: Area in sqm (optional)
    waiting_for_type = State()          # Step 4: Renovation type (inline keyboard)
    waiting_for_budget = State()        # Step 5: Total budget
    waiting_for_coordinator = State()   # Step 6: Who manages? (Self / Foreman / Designer)
    waiting_for_coordinator_contact = State()  # Step 6b: Coordinator contact info
    waiting_for_co_owner = State()      # Step 7: Add co-owner? (Yes/No)
    waiting_for_co_owner_contact = State()    # Step 7b: Co-owner contact info
    waiting_for_custom_items = State()  # Step 8: Custom furniture? (multi-select)
    reviewing_stages = State()          # Step 9: Review/edit auto-generated stages
    confirming = State()                # Step 10: Final confirmation


class StageSetup(StatesGroup):
    """
    States for stage configuration: deadlines, assignments, budgets,
    sub-stages, and project launch.

    Accessed via /stages and /launch commands.

    FSM data keys used:
      project_id  — current project being configured
      stage_id    — stage currently being edited
      date_mode   — "duration" | "exact" (how dates are entered)
    """

    selecting_project = State()        # Pick project (if user has multiple)
    viewing_stages = State()           # Browsing the stage list
    viewing_stage_detail = State()     # Viewing one stage's details

    # Date entry
    setting_start_date = State()       # Entering start date (DD.MM.YYYY)
    setting_end_date = State()         # Entering end date (DD.MM.YYYY)
    setting_duration = State()         # Entering duration in days

    # Person & budget
    assigning_person = State()         # Entering responsible person name/contact
    setting_stage_budget = State()     # Entering budget amount for stage

    # Sub-stages
    adding_sub_stages = State()        # Entering sub-stage names (one per line)

    # Launch
    confirming_launch = State()        # Final project launch confirmation


class RoleManagement(StatesGroup):
    """
    States for inviting and managing team members.

    Accessed via /invite command.

    FSM data keys used:
      project_id    — target project
      invite_role   — RoleType being assigned
      target_user_id — user being invited (if resolved)
    """

    selecting_project = State()        # Pick project (if user has multiple)
    choosing_role = State()            # Select which role to assign
    entering_contact = State()         # Enter @username or forward a message
    confirming_invite = State()        # Confirm the invitation


class BudgetManagement(StatesGroup):
    """
    States for budget and expense tracking.

    Accessed via /budget and /expenses commands.

    FSM data keys used:
      project_id  — current project
      category    — selected budget category
      stage_id    — optional stage link
      item_id     — budget item being viewed/edited
    """

    selecting_project = State()        # Pick project (if user has multiple)
    viewing_budget = State()           # Browsing budget overview
    selecting_category = State()       # Choosing expense category
    entering_description = State()     # Expense description
    entering_work_cost = State()       # Work cost amount
    entering_material_cost = State()   # Material cost amount
    entering_prepayment = State()      # Prepayment amount
    viewing_item = State()             # Viewing a single budget item
    viewing_history = State()          # Viewing change history


class ReportSelection(StatesGroup):
    """
    States for report command project selection.

    Used by /report, /status, /nextstage, /deadline when the user
    has multiple projects and needs to pick one.

    FSM data keys used:
      intent  — which report command triggered selection
    """

    selecting_project = State()        # Pick project (if user has multiple)


class ChatMode(StatesGroup):
    """
    States for the interactive AI chat mode.

    Owner/Co-Owner can enter a multi-turn conversation with the AI
    about their project. Every text message is forwarded to the LLM
    until the user sends /end to exit.

    FSM data keys used:
      project_id           — current project being discussed
      chat_history          — list of {"role", "content"} dicts
    """

    chatting = State()                 # Active conversation with LLM
