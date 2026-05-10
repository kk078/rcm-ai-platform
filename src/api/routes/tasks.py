"""
Task Management API Routes — Monitor background jobs and trigger manual runs.
Internal staff only (company_admin role).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from uuid import UUID

from src.infrastructure.auth.middleware import get_current_user, require_role

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────

class TaskStatus(BaseModel):
    task_id: str
    task_name: str
    status: str  # PENDING, STARTED, SUCCESS, FAILURE, RETRY
    result: str | None = None
    date_done: str | None = None


class TaskTriggerResult(BaseModel):
    task_id: str
    task_name: str
    message: str


class BeatScheduleItem(BaseModel):
    name: str
    task: str
    schedule_seconds: float


# ── Task Status ──────────────────────────────────────────────────

@router.get("/status/{task_id}",
             dependencies=[Depends(require_role("company_admin"))])
async def get_task_status(
    task_id: str,
    current_user: dict = Depends(get_current_user),
):
    """Get the status of a background task by its ID."""
    from src.infrastructure.queue.celery_app import celery_app

    result = celery_app.AsyncResult(task_id)
    return {
        "task_id": task_id,
        "status": result.status,
        "result": str(result.result) if result.result else None,
        "date_done": str(result.date_done) if result.date_done else None,
        "task_name": result.name or "unknown",
    }


# ── Beat Schedule ─────────────────────────────────────────────────

@router.get("/schedule",
             dependencies=[Depends(require_role("company_admin"))])
async def get_beat_schedule(
    current_user: dict = Depends(get_current_user),
):
    """List all configured periodic tasks (Celery Beat schedule)."""
    from src.infrastructure.queue.celery_app import celery_app

    schedule = celery_app.conf.beat_schedule
    items = []
    for name, config in schedule.items():
        items.append({
            "name": name,
            "task": config["task"],
            "schedule_seconds": config["schedule"],
        })
    return items


# ── Manual Task Triggers ──────────────────────────────────────────

@router.post("/trigger/appeal-deadlines",
              dependencies=[Depends(require_role("company_admin"))])
async def trigger_appeal_deadlines(
    current_user: dict = Depends(get_current_user),
):
    """Manually trigger appeal deadline check."""
    from src.core.denials.tasks import check_appeal_deadlines
    result = check_appeal_deadlines.delay()
    return {"task_id": result.id, "task_name": "check_appeal_deadlines", "message": "Appeal deadline check triggered"}


@router.post("/trigger/timely-filing",
              dependencies=[Depends(require_role("company_admin"))])
async def trigger_timely_filing(
    current_user: dict = Depends(get_current_user),
):
    """Manually trigger timely filing deadline check."""
    from src.core.billing.tasks import check_timely_filing_deadlines
    result = check_timely_filing_deadlines.delay()
    return {"task_id": result.id, "task_name": "check_timely_filing_deadlines", "message": "Timely filing check triggered"}


@router.post("/trigger/sla-breaches",
              dependencies=[Depends(require_role("company_admin"))])
async def trigger_sla_breaches(
    current_user: dict = Depends(get_current_user),
):
    """Manually trigger SLA breach check."""
    from src.core.queues.tasks import check_sla_breaches
    result = check_sla_breaches.delay()
    return {"task_id": result.id, "task_name": "check_sla_breaches", "message": "SLA breach check triggered"}


@router.post("/trigger/auto-assign",
              dependencies=[Depends(require_role("company_admin"))])
async def trigger_auto_assign(
    current_user: dict = Depends(get_current_user),
):
    """Manually trigger auto-assignment of pending queue items."""
    from src.core.queues.tasks import auto_assign_pending_items
    result = auto_assign_pending_items.delay()
    return {"task_id": result.id, "task_name": "auto_assign_pending_items", "message": "Auto-assignment triggered"}


@router.post("/trigger/overdue-invoices",
              dependencies=[Depends(require_role("company_admin"))])
async def trigger_overdue_invoices(
    current_user: dict = Depends(get_current_user),
):
    """Manually trigger overdue invoice detection."""
    from src.core.client_billing.tasks import mark_overdue_invoices
    result = mark_overdue_invoices.delay()
    return {"task_id": result.id, "task_name": "mark_overdue_invoices", "message": "Overdue invoice check triggered"}


@router.post("/trigger/denial-patterns",
              dependencies=[Depends(require_role("company_admin"))])
async def trigger_denial_patterns(
    current_user: dict = Depends(get_current_user),
):
    """Manually trigger denial pattern analysis."""
    from src.core.denials.tasks import analyze_denial_patterns
    result = analyze_denial_patterns.delay()
    return {"task_id": result.id, "task_name": "analyze_denial_patterns", "message": "Denial pattern analysis triggered"}