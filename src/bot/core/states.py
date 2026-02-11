"""
FSM (Finite State Machine) states for multi-step conversations.

These represent the steps in the project creation wizard and other
multi-turn flows. States are platform-agnostic — the adapter layer
maps them to platform-specific state storage (e.g. aiogram FSMContext).
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
