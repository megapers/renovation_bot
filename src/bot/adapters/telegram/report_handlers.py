"""
Telegram handlers for reports & quick commands (Phase 7).

Commands:
  /report    — generate on-demand project report
  /status    — quick project status
  /nextstage — show next upcoming stage
  /deadline  — deadline-focused report
  /mystage   — stages assigned to current user

Quick text commands (without /):
  бюджет, этапы, расходы, отчёт, следующий этап,
  мой этап, статус, дедлайн, эксперт
"""

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from bot.adapters.telegram.formatters import (
    format_deadline_report,
    format_my_stages,
    format_next_stage_info,
    format_status_report,
    format_weekly_report,
)
from bot.adapters.telegram.fsm_states import ReportSelection
from bot.adapters.telegram.project_resolver import resolve_project
from bot.core.report_service import (
    build_deadline_report,
    build_next_stage_info,
    build_status_report,
    build_weekly_report,
    parse_quick_command,
)
from bot.core.stage_service import STATUS_LABELS, format_date
from bot.db import repositories as repo
from bot.db.session import async_session_factory

logger = logging.getLogger(__name__)
router = Router(name="reports")


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════


async def _resolve_for_report(
    message: Message,
    state: FSMContext,
    intent: str,
) -> int | None:
    """Resolve project for report commands using the shared resolver."""
    resolved = await resolve_project(
        message, state,
        intent=intent,
        picker_state=ReportSelection.selecting_project,
    )
    if resolved:
        await state.update_data(user_id=resolved.user_id)
        return resolved.id
    return None


# ═══════════════════════════════════════════════════════════════
# REPORT COMMAND — /report
# ═══════════════════════════════════════════════════════════════


@router.message(Command("report"))
async def cmd_report(message: Message, state: FSMContext) -> None:
    """/report — generate a full weekly-style report."""
    await state.clear()
    project_id = await _resolve_for_report(message, state, "report")
    if project_id is not None:
        await _send_report(message, project_id)


async def _send_report(target: Message, project_id: int) -> None:
    """Build and send a full weekly report."""
    async with async_session_factory() as session:
        data = await repo.get_project_full_report_data(session, project_id)

    project = data["project"]
    if project is None:
        await target.answer("❌ Проект не найден.")
        return

    report = await build_weekly_report(
        project_id=project.id,
        project_name=project.name,
        total_budget=float(project.total_budget) if project.total_budget else None,
        stages=data["stages"],
        budget_summary=data["budget_summary"],
        category_summaries=data["category_summaries"],
    )

    text = format_weekly_report(report)
    await target.answer(text)


# ═══════════════════════════════════════════════════════════════
# STATUS COMMAND — /status
# ═══════════════════════════════════════════════════════════════


@router.message(Command("status"))
async def cmd_status(message: Message, state: FSMContext) -> None:
    """/status — quick project status overview."""
    await state.clear()
    project_id = await _resolve_for_report(message, state, "status")
    if project_id is not None:
        await _send_status(message, project_id)


async def _send_status(target: Message, project_id: int) -> None:
    """Build and send a status report."""
    async with async_session_factory() as session:
        project = await repo.get_project_with_stages(session, project_id)
        stages = list(await repo.get_stages_for_project(session, project_id))

    if project is None:
        await target.answer("❌ Проект не найден.")
        return

    report = await build_status_report(project.name, stages)
    text = format_status_report(report)
    await target.answer(text)


# ═══════════════════════════════════════════════════════════════
# NEXT STAGE — /nextstage
# ═══════════════════════════════════════════════════════════════


@router.message(Command("nextstage"))
async def cmd_next_stage(message: Message, state: FSMContext) -> None:
    """/nextstage — show current and next stage."""
    await state.clear()
    project_id = await _resolve_for_report(message, state, "next_stage")
    if project_id is not None:
        await _send_next_stage(message, project_id)


async def _send_next_stage(target: Message, project_id: int) -> None:
    """Build and send next stage info."""
    async with async_session_factory() as session:
        project = await repo.get_project_with_stages(session, project_id)
        current = await repo.get_current_in_progress_stage(session, project_id)
        next_stage = None
        if current:
            next_stage = await repo.get_next_stage(session, current)

    if project is None:
        await target.answer("❌ Проект не найден.")
        return

    info = await build_next_stage_info(project.name, current, next_stage)
    text = format_next_stage_info(info)
    await target.answer(text)


# ═══════════════════════════════════════════════════════════════
# DEADLINE — /deadline
# ═══════════════════════════════════════════════════════════════


@router.message(Command("deadline"))
async def cmd_deadline(message: Message, state: FSMContext) -> None:
    """/deadline — deadline-focused report."""
    await state.clear()
    project_id = await _resolve_for_report(message, state, "deadline")
    if project_id is not None:
        await _send_deadline(message, project_id)


async def _send_deadline(target: Message, project_id: int) -> None:
    """Build and send a deadline report."""
    async with async_session_factory() as session:
        project = await repo.get_project_with_stages(session, project_id)
        stages = list(await repo.get_stages_for_project(session, project_id))

    if project is None:
        await target.answer("❌ Проект не найден.")
        return

    report = await build_deadline_report(project.name, stages)
    text = format_deadline_report(report)
    await target.answer(text)


# ═══════════════════════════════════════════════════════════════
# MY STAGE — /mystage
# ═══════════════════════════════════════════════════════════════


@router.message(Command("mystage"))
async def cmd_my_stage(message: Message, state: FSMContext) -> None:
    """/mystage — show stages assigned to current user."""
    await state.clear()

    # In group chat, resolve to linked project
    # In private chat, show all projects
    tg_user = message.from_user
    if tg_user is None:
        return

    async with async_session_factory() as session:
        user = await repo.get_user_by_telegram_id(session, tg_user.id)
        if user is None:
            await message.answer("❌ Вы не зарегистрированы. Отправьте /start сначала.")
            return

        # Group chat: only show stages for the linked project
        if message.chat.type in ("group", "supergroup"):
            project = await repo.get_project_by_telegram_chat_id(
                session, message.chat.id
            )
            if project:
                await _send_my_stages(message, project.id, user.id)
            else:
                await message.answer(
                    "❌ Эта группа не привязана к проекту.\n"
                    "Используйте /link чтобы привязать группу к проекту."
                )
            return

        # Private chat: show stages across all projects
        projects = await repo.get_user_projects(session, user.id)

    if not projects:
        await message.answer("У вас нет активных проектов.")
        return

    for project in projects:
        await _send_my_stages(message, project.id, user.id)


async def _send_my_stages(
    target: Message,
    project_id: int,
    user_id: int,
) -> None:
    """Build and send user's assigned stages."""
    from datetime import datetime, timezone

    async with async_session_factory() as session:
        project = await repo.get_project_with_stages(session, project_id)
        stages = await repo.get_stages_for_user(session, user_id, project_id)

    if project is None:
        return

    now = datetime.now(tz=timezone.utc)
    stages_info = []
    for s in stages:
        is_overdue = (
            s.status.value in ("in_progress", "delayed")
            and s.end_date
            and s.end_date < now
        )
        stages_info.append({
            "name": s.name,
            "status": STATUS_LABELS.get(s.status.value, s.status.value),
            "start_date": format_date(s.start_date),
            "end_date": format_date(s.end_date),
            "is_overdue": is_overdue,
        })

    text = format_my_stages(stages_info, project.name)
    await target.answer(text)


# ═══════════════════════════════════════════════════════════════
# PROJECT SELECTION CALLBACK (for multi-project users)
# ═══════════════════════════════════════════════════════════════


@router.callback_query(
    ReportSelection.selecting_project,
    F.data.startswith("prjsel:"),
)
async def report_select_project(
    callback: CallbackQuery,
    state: FSMContext,
) -> None:
    """
    Handle project selection for report commands.

    Only fires when in ReportSelection.selecting_project state.
    """
    await callback.answer()
    project_id = int(callback.data.split(":")[1])  # type: ignore[union-attr]
    data = await state.get_data()
    intent = data.get("intent")
    await state.clear()

    dispatch = {
        "report": _send_report,
        "status": _send_status,
        "next_stage": _send_next_stage,
        "deadline": _send_deadline,
    }

    handler = dispatch.get(intent)
    if handler:
        await handler(callback.message, project_id)  # type: ignore[arg-type]
        return

    # AI intents that share ReportSelection picker state
    if intent == "ask":
        await callback.message.answer(  # type: ignore[union-attr]
            "✅ Проект выбран. Теперь отправьте /ask &lt;ваш вопрос&gt;"
        )
    elif intent == "backfill":
        from bot.adapters.telegram.ai_handlers import cmd_backfill
        # Re-trigger backfill with the selected project context
        await callback.message.answer(  # type: ignore[union-attr]
            "✅ Проект выбран. Отправьте /backfill снова."
        )


# ═══════════════════════════════════════════════════════════════
# QUICK TEXT COMMANDS (without /)
# ═══════════════════════════════════════════════════════════════


@router.message(F.text)
async def handle_quick_command(message: Message, state: FSMContext) -> None:
    """
    Handle quick text commands (sent without /).

    Recognized commands: бюджет, этапы, расходы, отчёт, следующий этап,
    мой этап, статус, дедлайн, эксперт

    This handler has lowest priority — placed LAST in router registration
    so it only catches unhandled text messages.
    """
    if not message.text:
        return

    command = parse_quick_command(message.text)
    if command is None:
        return  # Not a recognized quick command — ignore

    logger.debug("Quick command recognized: %s (text: %s)", command, message.text)

    # Dispatch to the appropriate handler
    if command == "budget":
        # Redirect to /budget handler
        from bot.adapters.telegram.budget_handlers import cmd_budget
        await cmd_budget(message, state)

    elif command == "stages":
        from bot.adapters.telegram.stage_handlers import cmd_stages
        await cmd_stages(message, state)

    elif command == "expenses":
        from bot.adapters.telegram.budget_handlers import cmd_expenses
        await cmd_expenses(message, state)

    elif command == "report":
        await cmd_report(message, state)

    elif command == "next_stage":
        await cmd_next_stage(message, state)

    elif command == "my_stage":
        await cmd_my_stage(message, state)

    elif command == "status":
        await cmd_status(message, state)

    elif command == "deadline":
        await cmd_deadline(message, state)

    elif command == "expert":
        await message.answer(
            "🔍 <b>Вызов эксперта</b>\n\n"
            "Функция вызова эксперта будет доступна в следующем обновлении.\n"
            "Для связи с экспертом обратитесь к координатору проекта."
        )
