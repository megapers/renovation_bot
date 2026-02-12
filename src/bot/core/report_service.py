"""
Core report service — platform-agnostic.

Builds structured report data from project/stage/budget information.
Platform adapters consume the report dict and format it into
platform-specific markup (HTML for Telegram, plain text for WhatsApp).

This module never imports platform-specific code.
"""

import logging
from datetime import datetime, timezone

from bot.core.budget_service import (
    CATEGORY_LABELS,
    PAYMENT_STATUS_LABELS,
    analyze_budget,
    get_category_label,
)
from bot.core.stage_service import STATUS_LABELS, format_date

logger = logging.getLogger(__name__)


# ── Report types ─────────────────────────────────────────────


async def build_weekly_report(
    project_id: int,
    project_name: str,
    total_budget: float | None,
    stages: list,
    budget_summary: dict,
    category_summaries: list[dict],
) -> dict:
    """
    Build data for a weekly project report.

    Returns a dict with all structured data a formatter needs:
    {
        "project_name": str,
        "generated_at": datetime,
        "stages_summary": {
            "total": int,
            "completed": int,
            "in_progress": int,
            "delayed": int,
            "planned": int,
        },
        "completed_stages": list[dict],  -- finished this period
        "current_stages": list[dict],    -- in progress now
        "overdue_stages": list[dict],    -- past deadline
        "upcoming_stages": list[dict],   -- starting soon
        "budget_info": dict,
        "budget_analysis": dict,
        "category_breakdown": list[dict],
    }
    """
    now = datetime.now(tz=timezone.utc)

    # Classify stages
    completed = []
    in_progress = []
    delayed = []
    planned = []
    overdue = []
    upcoming = []

    for s in stages:
        status = s.status.value
        if status == "completed":
            completed.append(s)
        elif status == "in_progress":
            in_progress.append(s)
            # Check if overdue
            if s.end_date and s.end_date < now:
                days_over = (now - s.end_date).days
                overdue.append({"stage": s, "days_overdue": days_over})
        elif status == "delayed":
            delayed.append(s)
            if s.end_date and s.end_date < now:
                days_over = (now - s.end_date).days
                overdue.append({"stage": s, "days_overdue": days_over})
        else:
            planned.append(s)
            # Upcoming = starting within 7 days
            if s.start_date:
                days_until = (s.start_date - now).days
                if 0 <= days_until <= 7:
                    upcoming.append({"stage": s, "days_until": days_until})

    # Budget analysis
    total_spent = budget_summary.get("total_spent", 0)
    total_prepayments = budget_summary.get("total_prepayments", 0)
    analysis = analyze_budget(total_budget, total_spent, total_prepayments)

    return {
        "project_name": project_name,
        "generated_at": now,
        "stages_summary": {
            "total": len(stages),
            "completed": len(completed),
            "in_progress": len(in_progress),
            "delayed": len(delayed),
            "planned": len(planned),
        },
        "completed_stages": [
            {
                "name": s.name,
                "end_date": format_date(s.end_date),
            }
            for s in completed
        ],
        "current_stages": [
            {
                "name": s.name,
                "status": STATUS_LABELS.get(s.status.value, s.status.value),
                "end_date": format_date(s.end_date),
                "responsible": s.responsible_contact or "—",
                "payment_status": PAYMENT_STATUS_LABELS.get(
                    s.payment_status.value, s.payment_status.value
                ),
            }
            for s in in_progress
        ],
        "overdue_stages": [
            {
                "name": item["stage"].name,
                "days_overdue": item["days_overdue"],
                "responsible": item["stage"].responsible_contact or "—",
            }
            for item in overdue
        ],
        "upcoming_stages": [
            {
                "name": item["stage"].name,
                "days_until": item["days_until"],
                "start_date": format_date(item["stage"].start_date),
            }
            for item in upcoming
        ],
        "budget_info": budget_summary,
        "budget_analysis": analysis,
        "category_breakdown": [
            {
                "label": get_category_label(c["category"]),
                "total": c["total"],
                "confirmed": c["confirmed"],
            }
            for c in category_summaries
        ],
    }


async def build_status_report(
    project_name: str,
    stages: list,
) -> dict:
    """
    Build a quick status report — current state of all stages.

    Returns:
    {
        "project_name": str,
        "generated_at": datetime,
        "stages": list[dict],
        "progress_pct": float,
    }
    """
    now = datetime.now(tz=timezone.utc)

    total = len(stages)
    completed_count = sum(1 for s in stages if s.status.value == "completed")
    progress_pct = (completed_count / total * 100) if total > 0 else 0

    stage_list = []
    for s in stages:
        info = {
            "name": s.name,
            "order": s.order,
            "status": STATUS_LABELS.get(s.status.value, s.status.value),
            "status_value": s.status.value,
            "is_parallel": s.is_parallel,
            "start_date": format_date(s.start_date),
            "end_date": format_date(s.end_date),
            "responsible": s.responsible_contact or "—",
        }

        # Overdue check
        if (
            s.status.value in ("in_progress", "delayed")
            and s.end_date
            and s.end_date < now
        ):
            info["is_overdue"] = True
            info["days_overdue"] = (now - s.end_date).days
        else:
            info["is_overdue"] = False

        stage_list.append(info)

    return {
        "project_name": project_name,
        "generated_at": now,
        "stages": stage_list,
        "progress_pct": progress_pct,
        "total": total,
        "completed": completed_count,
    }


async def build_next_stage_info(
    project_name: str,
    current_stage,
    next_stage,
) -> dict:
    """
    Build info about the next stage.

    Returns:
    {
        "project_name": str,
        "current_stage": dict | None,
        "next_stage": dict | None,
    }
    """
    current = None
    if current_stage:
        current = {
            "name": current_stage.name,
            "status": STATUS_LABELS.get(
                current_stage.status.value, current_stage.status.value
            ),
            "end_date": format_date(current_stage.end_date),
            "responsible": current_stage.responsible_contact or "—",
        }

    nxt = None
    if next_stage:
        nxt = {
            "name": next_stage.name,
            "start_date": format_date(next_stage.start_date),
            "end_date": format_date(next_stage.end_date),
            "responsible": next_stage.responsible_contact or "—",
            "budget": float(next_stage.budget) if next_stage.budget else None,
        }

    return {
        "project_name": project_name,
        "current_stage": current,
        "next_stage": nxt,
    }


async def build_deadline_report(
    project_name: str,
    stages: list,
) -> dict:
    """
    Build a deadline-focused report.

    Returns:
    {
        "project_name": str,
        "overdue": list[dict],
        "due_soon": list[dict],   -- within 3 days
        "on_track": list[dict],   -- in progress, not overdue
    }
    """
    now = datetime.now(tz=timezone.utc)

    overdue = []
    due_soon = []
    on_track = []

    for s in stages:
        if s.status.value in ("completed",):
            continue
        if s.status.value not in ("in_progress", "delayed", "planned"):
            continue

        if s.end_date and s.end_date < now and s.status.value in ("in_progress", "delayed"):
            days_over = (now - s.end_date).days
            overdue.append({
                "name": s.name,
                "end_date": format_date(s.end_date),
                "days_overdue": days_over,
                "responsible": s.responsible_contact or "—",
            })
        elif s.end_date:
            days_left = (s.end_date - now).days
            entry = {
                "name": s.name,
                "end_date": format_date(s.end_date),
                "days_left": days_left,
                "responsible": s.responsible_contact or "—",
            }
            if 0 <= days_left <= 3:
                due_soon.append(entry)
            elif s.status.value in ("in_progress",):
                on_track.append(entry)

    return {
        "project_name": project_name,
        "overdue": overdue,
        "due_soon": due_soon,
        "on_track": on_track,
    }


# ── Quick command parsers ────────────────────────────────────

# All quick commands that can be sent as plain text (without /)
QUICK_COMMANDS: dict[str, str] = {
    "бюджет": "budget",
    "budget": "budget",
    "этапы": "stages",
    "stages": "stages",
    "расходы": "expenses",
    "expenses": "expenses",
    "отчёт": "report",
    "отчет": "report",
    "report": "report",
    "следующий этап": "next_stage",
    "next stage": "next_stage",
    "мой этап": "my_stage",
    "my stage": "my_stage",
    "статус": "status",
    "status": "status",
    "дедлайн": "deadline",
    "deadline": "deadline",
    "эксперт": "expert",
    "expert": "expert",
}


def parse_quick_command(text: str) -> str | None:
    """
    Check if text matches a known quick command.

    Returns the command key (e.g. 'budget', 'stages') or None.
    """
    normalized = text.strip().lower()
    return QUICK_COMMANDS.get(normalized)
