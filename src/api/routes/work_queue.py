"""
Work Queue API Routes — Unified cross-client work queues for internal staff.
Your coders, billers, posters, and denial analysts work from these queues.
Items from all assigned practices appear in one prioritized list.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import date, datetime
from enum import Enum

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────

class QueueType(str, Enum):
    INTAKE = "intake"
    CODING = "coding"
    BILLING = "billing"
    POSTING = "posting"
    DENIAL = "denial"
    FOLLOW_UP = "follow_up"


class QueueItemStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ESCALATED = "escalated"
    ON_HOLD = "on_hold"


class QueueItemResponse(BaseModel):
    id: UUID
    practice_name: str
    practice_id: UUID
    queue_type: QueueType
    item_type: str  # charge_entry, coding_session, claim, payment_batch, denial
    item_id: UUID
    priority: int  # 0-100
    status: QueueItemStatus
    assigned_to_name: str | None
    due_date: datetime | None
    sla_breached: bool
    age_hours: float  # How long this item has been in queue
    summary: str  # Human-readable summary of the work item
    patient_name: str | None = None
    dollar_amount: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class QueueDashboard(BaseModel):
    """Overview of all queues for a manager."""
    intake_pending: int
    intake_sla_breached: int
    coding_pending: int
    coding_sla_breached: int
    billing_pending: int
    billing_sla_breached: int
    posting_pending: int
    posting_sla_breached: int
    denial_pending: int
    denial_sla_breached: int
    follow_up_pending: int
    follow_up_overdue: int
    total_dollar_at_risk: float  # Sum of denial amounts + aging claims


class StaffWorkload(BaseModel):
    user_id: UUID
    user_name: str
    items_in_progress: int
    items_completed_today: int
    avg_time_per_item_minutes: float
    queues: dict[str, int]  # {queue_type: count}


class ReleaseRequest(BaseModel):
    reason: str | None = None


class EscalateRequest(BaseModel):
    reason: str
    escalate_to: UUID | None = None


class CompleteRequest(BaseModel):
    time_spent_seconds: int | None = None


class AssignRequest(BaseModel):
    assign_to: UUID


class BulkAssignRequest(BaseModel):
    item_ids: list[UUID]
    assign_to: UUID


class ProductivityReport(BaseModel):
    user_name: str
    period: str
    claims_submitted: int
    claims_dollar_amount: float
    payments_posted: int
    payments_dollar_amount: float
    denials_worked: int
    denials_recovered: float
    codes_reviewed: int
    avg_items_per_day: float
    sla_compliance_pct: float


# ── Queue Access ─────────────────────────────────────────────────

@router.get("/dashboard", response_model=QueueDashboard)
async def queue_dashboard():
    """
    Manager view: overview of all queues across all practices.
    Shows pending counts, SLA breaches, and dollar amounts at risk.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/my-queue", response_model=list[QueueItemResponse])
async def get_my_queue(
    queue_type: QueueType | None = None,
    practice_id: UUID | None = None,
    include_unassigned: bool = False,
    sort_by: str = Query(default="priority", enum=["priority", "due_date", "dollar_amount", "age"]),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    """
    Get the current user's work queue.
    Pulls items from ALL assigned practices, sorted by priority.
    Optionally filter by queue type or specific practice.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/queue/{queue_type}", response_model=list[QueueItemResponse])
async def get_queue(
    queue_type: QueueType,
    practice_id: UUID | None = None,
    assigned_to: UUID | None = None,
    status: QueueItemStatus | None = None,
    sla_breached_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    """
    Get a specific queue with filtering.
    Managers can see all items; staff see only their assigned practices.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


# ── Queue Actions ────────────────────────────────────────────────

@router.post("/queue/{item_id}/claim")
async def claim_queue_item(item_id: UUID):
    """
    Staff member claims (self-assigns) a queue item.
    Sets status to in_progress and records start time.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/queue/{item_id}/release")
async def release_queue_item(item_id: UUID, body: ReleaseRequest | None = None):
    """Release a claimed item back to the queue (e.g., need more info)."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/queue/{item_id}/complete")
async def complete_queue_item(item_id: UUID, body: CompleteRequest | None = None):
    """Mark a queue item as completed. Records time spent."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/queue/{item_id}/escalate")
async def escalate_queue_item(item_id: UUID, body: EscalateRequest):
    """Escalate an item to a manager or senior staff member."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/queue/{item_id}/assign")
async def assign_queue_item(item_id: UUID, body: AssignRequest):
    """Manager assigns a queue item to a specific staff member."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/queue/bulk-assign")
async def bulk_assign(body: BulkAssignRequest):
    """Manager bulk-assigns multiple items to one staff member."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/queue/auto-assign")
async def trigger_auto_assignment(body: dict):
    """
    Run the auto-assignment algorithm for a queue.
    Body: { "queue_type": "coding", "practice_id": "uuid-or-null" }
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


# ── Staff Workload ───────────────────────────────────────────────

@router.get("/workload", response_model=list[StaffWorkload])
async def get_team_workload():
    """Manager view: current workload for all team members."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/workload/{user_id}", response_model=StaffWorkload)
async def get_staff_workload(user_id: UUID):
    """Detailed workload for a specific staff member."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


# ── Productivity ─────────────────────────────────────────────────

@router.get("/productivity", response_model=list[ProductivityReport])
async def get_team_productivity(
    date_from: date | None = None,
    date_to: date | None = None,
    practice_id: UUID | None = None,
):
    """Team productivity report. Managers see all staff; staff see only themselves."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/productivity/{user_id}", response_model=ProductivityReport)
async def get_staff_productivity(
    user_id: UUID,
    date_from: date | None = None,
    date_to: date | None = None,
):
    """Individual staff productivity report."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


# ── SLA Monitoring ───────────────────────────────────────────────

@router.get("/sla/breaches")
async def get_sla_breaches(
    practice_id: UUID | None = None,
    queue_type: QueueType | None = None,
):
    """
    List all current SLA breaches across practices.
    Critical for managers to identify and resolve bottlenecks.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/sla/compliance")
async def get_sla_compliance_report(
    date_from: date | None = None,
    date_to: date | None = None,
):
    """
    SLA compliance rates by practice and queue type.
    Used for client reporting and internal performance management.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")
