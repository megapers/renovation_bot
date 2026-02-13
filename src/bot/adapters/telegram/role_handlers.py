"""
Telegram handlers for role & team management.

Commands:
  /invite  — invite a user to a project with a specific role
  /team    — show the project team and their roles
  /myrole  — show the current user's role in the project

The /invite flow:
  1. Select project (if multiple)
  2. Choose a role to assign
  3. Enter @username or forward a message from the user
  4. Confirm → user is added with that role
"""

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.adapters.telegram.filters import RequirePermission, RequireRegistration
from bot.adapters.telegram.keyboards import (
    invite_confirm_keyboard,
    role_select_keyboard,
)
from bot.adapters.telegram.formatters import format_team_list
from bot.adapters.telegram.project_resolver import resolve_project
from bot.core.role_service import (
    ASSIGNABLE_ROLES,
    Permission,
    ROLE_LABELS,
    format_role_list,
)
from bot.adapters.telegram.fsm_states import RoleManagement
from bot.db.models import RoleType, User
from bot.db.repositories import (
    assign_role,
    get_or_create_user_by_telegram_id,
    get_project_team,
    get_project_with_stages,
    get_user_by_telegram_id,
    get_user_roles_in_project,
    has_role_in_project,
    remove_role,
)
from bot.db.session import async_session_factory

logger = logging.getLogger(__name__)
router = Router(name="role_management")


# ═══════════════════════════════════════════════════════════════
# /team — Show project team
# ═══════════════════════════════════════════════════════════════


@router.message(Command("team"))
async def cmd_team(message: Message, state: FSMContext) -> None:
    """Show the team for the current project."""
    await state.clear()
    resolved = await resolve_project(
        message, state,
        intent="team",
        picker_state=RoleManagement.selecting_project,
    )
    if resolved:
        await _show_team(message, resolved.id)


async def _show_team(target: Message, project_id: int) -> None:
    """Load and display the project team."""
    async with async_session_factory() as session:
        project = await get_project_with_stages(session, project_id)
        if project is None:
            await target.answer("❌ Проект не найден.")
            return

        team = await get_project_team(session, project_id)

    members = [
        (user.full_name, roles, user.is_bot_started)
        for user, roles in team
    ]

    text = f"🏠 <b>{project.name}</b>\n\n"
    text += format_team_list(members)
    text += "\n\nИспользуйте /invite для добавления участников."

    await target.answer(text)


# ═══════════════════════════════════════════════════════════════
# /myrole — Show current user's role
# ═══════════════════════════════════════════════════════════════


@router.message(Command("myrole"))
async def cmd_myrole(message: Message, state: FSMContext) -> None:
    """Show the user's roles in the current project."""
    await state.clear()
    resolved = await resolve_project(
        message, state,
        intent="myrole",
        picker_state=RoleManagement.selecting_project,
    )
    if resolved:
        async with async_session_factory() as session:
            user = await get_user_by_telegram_id(session, message.from_user.id)  # type: ignore[union-attr]
        if user:
            await _show_myrole(message, user, resolved.id)


async def _show_myrole(target: Message, user: User, project_id: int) -> None:
    """Show the user's roles in a project."""
    async with async_session_factory() as session:
        roles = await get_user_roles_in_project(session, user.id, project_id)
        project = await get_project_with_stages(session, project_id)

    if not roles:
        await target.answer("Вы не являетесь участником этого проекта.")
        return

    project_name = project.name if project else "—"
    await target.answer(
        f"🏠 <b>{project_name}</b>\n\n"
        f"👤 {user.full_name}\n"
        f"Роль: <b>{format_role_list(roles)}</b>"
    )


# ═══════════════════════════════════════════════════════════════
# /invite — Add team member
# ═══════════════════════════════════════════════════════════════


@router.message(Command("invite"), RequireRegistration())
async def cmd_invite(message: Message, state: FSMContext) -> None:
    """Start the invitation flow."""
    await state.clear()
    resolved = await resolve_project(
        message, state,
        intent="invite",
        picker_state=RoleManagement.selecting_project,
    )
    if resolved:
        # Check permission
        async with async_session_factory() as session:
            roles = await get_user_roles_in_project(
                session, resolved.user_id, resolved.id
            )
        from bot.core.role_service import has_permission
        if not has_permission(roles, Permission.INVITE_MEMBER):
            await message.answer(
                "🚫 <b>Доступ запрещён</b>\n\n"
                "Только владелец или прораб может приглашать участников."
            )
            return

        await state.update_data(project_id=resolved.id)
        await _ask_for_role(message, state)


# ── Project selection (shared across /team, /myrole, /invite) ──


@router.callback_query(RoleManagement.selecting_project, F.data.startswith("prjsel:"))
async def select_project_for_role(callback: CallbackQuery, state: FSMContext) -> None:
    """User selected a project."""
    await callback.answer()
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    data = await state.get_data()
    intent = data.get("intent", "invite")

    tg_user = callback.from_user

    if intent == "team":
        await _show_team(callback.message, project_id)  # type: ignore[arg-type]
        await state.clear()
        return

    if intent == "myrole":
        async with async_session_factory() as session:
            user = await get_user_by_telegram_id(session, tg_user.id)
        if user:
            await _show_myrole(callback.message, user, project_id)  # type: ignore[arg-type]
        await state.clear()
        return

    # intent == "invite"
    async with async_session_factory() as session:
        user = await get_user_by_telegram_id(session, tg_user.id)
        if user is None:
            await callback.message.answer("❌ Ошибка.")  # type: ignore[union-attr]
            await state.clear()
            return
        roles = await get_user_roles_in_project(session, user.id, project_id)

    from bot.core.role_service import has_permission
    if not has_permission(roles, Permission.INVITE_MEMBER):
        await callback.message.answer(  # type: ignore[union-attr]
            "🚫 <b>Доступ запрещён</b>\n\n"
            "Только владелец или прораб может приглашать участников."
        )
        await state.clear()
        return

    await state.update_data(project_id=project_id)
    await _ask_for_role(callback.message, state)  # type: ignore[arg-type]


# ── Role selection ────────────────────────────────────────────


async def _ask_for_role(target: Message, state: FSMContext) -> None:
    """Show the role selection keyboard."""
    await state.set_state(RoleManagement.choosing_role)
    await target.answer(
        "👤 <b>Приглашение участника</b>\n\n"
        "Выберите <b>роль</b> для нового участника:",
        reply_markup=role_select_keyboard(),
    )


@router.callback_query(RoleManagement.choosing_role, F.data.startswith("role:"))
async def choose_role(callback: CallbackQuery, state: FSMContext) -> None:
    """User selected a role to assign."""
    await callback.answer()
    role_str = callback.data.split(":")[1]  # type: ignore[union-attr]

    if role_str == "cancel":
        await state.clear()
        await callback.message.answer("❌ Приглашение отменено.")  # type: ignore[union-attr]
        return

    try:
        role = RoleType(role_str)
    except ValueError:
        await callback.message.answer("❌ Неизвестная роль.")  # type: ignore[union-attr]
        return

    await state.update_data(invite_role=role_str)
    await state.set_state(RoleManagement.entering_contact)

    role_label = ROLE_LABELS.get(role, role.value)
    await callback.message.answer(  # type: ignore[union-attr]
        f"Роль: <b>{role_label}</b>\n\n"
        "Теперь укажите пользователя одним из способов:\n"
        "• Введите <b>@username</b> Telegram\n"
        "• <b>Перешлите сообщение</b> от этого пользователя\n"
        "• Введите <b>имя и телефон</b> (будет создан без привязки к Telegram)"
    )


# ── Contact entry ─────────────────────────────────────────────

# Regex for @username
_USERNAME_RE = re.compile(r"^@([a-zA-Z][a-zA-Z0-9_]{4,31})$")


@router.message(RoleManagement.entering_contact)
async def process_contact(message: Message, state: FSMContext) -> None:
    """
    Receive contact info for the invitee.

    Supports:
    1. Forwarded message — extract telegram_id from forward_from
    2. @username text — we store it but can't resolve to telegram_id yet
    3. Free text — stored as contact name (no Telegram link)
    """
    data = await state.get_data()
    project_id = data["project_id"]
    role_str = data["invite_role"]
    role = RoleType(role_str)

    # Case 1: Forwarded message
    if message.forward_from:
        fwd_user = message.forward_from
        async with async_session_factory() as session:
            user, created = await get_or_create_user_by_telegram_id(
                session, fwd_user.id, fwd_user.full_name or "Unknown"
            )
            await session.commit()

        await state.update_data(
            target_user_id=user.id,
            target_name=user.full_name,
            target_tg_id=fwd_user.id,
        )
        await _confirm_invite(message, state, user.full_name, role)
        return

    if not message.text or not message.text.strip():
        await message.answer(
            "Введите @username, перешлите сообщение или введите имя:"
        )
        return

    text = message.text.strip()

    # Case 2: @username
    match = _USERNAME_RE.match(text)
    if match:
        username = match.group(1)
        # We can't resolve @username to telegram_id via Bot API easily,
        # so store as a contact name and invite will complete when
        # the user sends /start to the bot
        await state.update_data(
            target_user_id=None,
            target_name=f"@{username}",
            target_tg_id=None,
        )
        await _confirm_invite(message, state, f"@{username}", role)
        return

    # Case 3: Free text (name/phone)
    await state.update_data(
        target_user_id=None,
        target_name=text,
        target_tg_id=None,
    )
    await _confirm_invite(message, state, text, role)


async def _confirm_invite(
    target: Message,
    state: FSMContext,
    name: str,
    role: RoleType,
) -> None:
    """Show confirmation screen for the invitation."""
    await state.set_state(RoleManagement.confirming_invite)
    role_label = ROLE_LABELS.get(role, role.value)
    await target.answer(
        f"📩 <b>Подтверждение приглашения</b>\n\n"
        f"Участник: <b>{name}</b>\n"
        f"Роль: <b>{role_label}</b>\n\n"
        "Подтвердить?",
        reply_markup=invite_confirm_keyboard(),
    )


@router.callback_query(RoleManagement.confirming_invite, F.data == "inv:yes")
async def confirm_invite(callback: CallbackQuery, state: FSMContext) -> None:
    """Execute the invitation."""
    await callback.answer("Добавляю...")
    data = await state.get_data()

    project_id = data["project_id"]
    role = RoleType(data["invite_role"])
    target_user_id = data.get("target_user_id")
    target_name = data.get("target_name", "Unknown")
    target_tg_id = data.get("target_tg_id")

    async with async_session_factory() as session:
        if target_user_id:
            # Already have a user record — assign role directly
            user_id = target_user_id
        elif target_tg_id:
            # Have a Telegram ID but need to get/create user
            user, _ = await get_or_create_user_by_telegram_id(
                session, target_tg_id, target_name
            )
            user_id = user.id
        else:
            # No Telegram ID — create a placeholder user with just a name
            user = User(
                full_name=target_name,
                is_bot_started=False,
            )
            session.add(user)
            await session.flush()
            user_id = user.id
            logger.info("Created placeholder user '%s' (id=%d)", target_name, user_id)

        # Check if they already have this role
        already = await has_role_in_project(session, user_id, project_id, role)
        if already:
            await callback.message.answer(  # type: ignore[union-attr]
                f"ℹ️ <b>{target_name}</b> уже имеет роль "
                f"<b>{ROLE_LABELS.get(role, role.value)}</b> в этом проекте."
            )
            await state.clear()
            return

        await assign_role(
            session,
            project_id=project_id,
            user_id=user_id,
            role=role,
        )
        await session.commit()

    role_label = ROLE_LABELS.get(role, role.value)

    # Notify about /start requirement
    start_note = ""
    if not target_tg_id:
        start_note = (
            "\n\n⚠️ Участник без Telegram-аккаунта. "
            "Уведомления не будут отправляться, пока он не отправит /start боту."
        )
    else:
        start_note = (
            "\n\n💡 Чтобы получать уведомления, участник должен "
            "отправить /start боту в личном чате."
        )

    await callback.message.answer(  # type: ignore[union-attr]
        f"✅ <b>{target_name}</b> добавлен(а) как <b>{role_label}</b>!{start_note}"
    )
    await state.clear()
    logger.info(
        "Invited '%s' as %s to project_id=%d",
        target_name, role.value, project_id,
    )


@router.callback_query(RoleManagement.confirming_invite, F.data == "inv:cancel")
async def cancel_invite(callback: CallbackQuery, state: FSMContext) -> None:
    """Cancel the invitation."""
    await callback.answer()
    await state.clear()
    await callback.message.answer("❌ Приглашение отменено.")  # type: ignore[union-attr]


# ═══════════════════════════════════════════════════════════════
# Team member removal (owner only)
# ═══════════════════════════════════════════════════════════════


@router.callback_query(F.data.startswith("tmrm:"))
async def remove_team_member(callback: CallbackQuery, state: FSMContext) -> None:
    """Remove a team member from the project (owner only)."""
    await callback.answer()
    parts = callback.data.split(":")  # type: ignore[union-attr]
    if len(parts) != 3:
        return

    project_id = int(parts[1])
    target_user_id = int(parts[2])

    tg_user = callback.from_user
    if tg_user is None:
        return

    async with async_session_factory() as session:
        # Verify caller is owner
        caller = await get_user_by_telegram_id(session, tg_user.id)
        if caller is None:
            return
        caller_roles = await get_user_roles_in_project(session, caller.id, project_id)
        if RoleType.OWNER not in caller_roles:
            await callback.message.answer(  # type: ignore[union-attr]
                "🚫 Только владелец может удалять участников."
            )
            return

        # Can't remove the owner
        target_roles = await get_user_roles_in_project(session, target_user_id, project_id)
        if RoleType.OWNER in target_roles:
            await callback.message.answer(  # type: ignore[union-attr]
                "❌ Нельзя удалить владельца проекта."
            )
            return

        # Remove all roles
        for role in target_roles:
            await remove_role(session, target_user_id, project_id, role)
        await session.commit()

    await callback.message.answer(  # type: ignore[union-attr]
        "✅ Участник удалён из проекта."
    )
