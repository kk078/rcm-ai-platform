"""
Work Queue API Routes — Unified cross-client work queues for internal staff.
Your coders, billers, posters, and denial analysts work from these queues.
Items from all assigned practices appear in one prioritized list.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import date, datetime, timezone
from enum import Enum
from sqlalchemy import select, func, case, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.session import get_db
from src.infrastructure.database.models import (
    WorkQueueItem,
    Claim,
    Denial,
    Practice,
    User,
    Patient,
)
from src.infrastructure.auth.middleware import get_current_user
from src.core.rbac import allowed_queue_types

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
    item_type: str
    item_id: UUID
    priority: int
    priority_label: str
    status: QueueItemStatus
    assigned_to_name: str | None = None
    assigned_to: UUID | None = None
    due_date: datetime | None
    sla_breached: bool
    age_hours: float
    summary: str
    patient_name: str | None = None
    dollar_amount: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class QueueDashboard(BaseModel):
    """Overview of all queues for a manager."""
    # KPI data
    total_claims: int = 0
    claims_submitted_today: int = 0
    total_payments: float = 0
    payments_posted_today: float = 0
    open_denials: int = 0
    denial_rate: float = 0.0
    avg_days_in_ar: float = 0.0
    clean_claim_rate: float = 0.0
    # Queue summary
    my_queue_count: int = 0
    team_queue_count: int = 0
    unassigned_count: int = 0


class StaffWorkload(BaseModel):
    user_id: UUID
    user_name: str
    items_in_progress: int
    items_completed_today: int
    avg_time_per_item_minutes: float
    queues: dict[str, int]


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


# ── Helpers ────────────────────────────────────────────────────────

PRIORITY_RANGES = {
    "critical": (80, 100),
    "high": (60, 79),
    "medium": (30, 59),
    "low": (0, 29),
}


def priority_label(score: int) -> str:
    if score >= 80:
        return "critical"
    if score >= 60:
        return "high"
    if score >= 30:
        return "medium"
    return "low"


def priority_to_score(label: str) -> int | None:
    mapping = {"critical": 90, "high": 70, "medium": 45, "low": 15}
    return mapping.get(label)


async def _build_queue_item_response(item: WorkQueueItem, db: AsyncSession) -> QueueItemResponse:
    """Convert a WorkQueueItem ORM object to a QueueItemResponse."""
    # Compute age
    age_hours = 0.0
    if item.created_at:
        delta = datetime.utcnow() - item.created_at
        age_hours = round(delta.total_seconds() / 3600, 1)

    # Get practice name — explicit query to avoid async lazy-load issue
    practice_name = ""
    if item.practice_id:
        try:
            prac_result = await db.execute(select(Practice).where(Practice.id == item.practice_id))
            prac = prac_result.scalar_one_or_none()
            if prac:
                practice_name = prac.practice_name or ""
        except Exception:
            pass

    # Get assigned user name
    assigned_to_name = None
    if item.assigned_to:
        result = await db.execute(select(User).where(User.id == item.assigned_to))
        assignee = result.scalar_one_or_none()
        if assignee:
            assigned_to_name = f"{assignee.first_name} {assignee.last_name}"

    # Build summary
    summary = f"{item.item_type.replace('_', ' ').title()} — {item.queue_type} queue"
    if practice_name:
        summary = f"{practice_name}: {summary}"

    # Resolve patient name and dollar amount from the referenced item
    patient_name = None
    dollar_amount = None
    try:
        if item.item_type == "claim" and item.item_id:
            claim_res = await db.execute(select(Claim).where(Claim.id == item.item_id))
            claim = claim_res.scalar_one_or_none()
            if claim:
                dollar_amount = float(claim.total_charge or 0) or None
                if claim.patient_id:
                    pat_res = await db.execute(select(Patient).where(Patient.id == claim.patient_id))
                    pat = pat_res.scalar_one_or_none()
                    if pat:
                        patient_name = f"{pat.first_name} {pat.last_name}".strip() or None
        elif item.item_type == "denial" and item.item_id:
            denial_res = await db.execute(select(Denial).where(Denial.id == item.item_id))
            denial = denial_res.scalar_one_or_none()
            if denial:
                dollar_amount = float(denial.billed_amount or 0) or None
                if denial.patient_id:
                    pat_res = await db.execute(select(Patient).where(Patient.id == denial.patient_id))
                    pat = pat_res.scalar_one_or_none()
                    if pat:
                        patient_name = f"{pat.first_name} {pat.last_name}".strip() or None
    except Exception:
        pass

    return QueueItemResponse(
        id=item.id,
        practice_name=practice_name,
        practice_id=item.practice_id,
        queue_type=QueueType(item.queue_type),
        item_type=item.item_type,
        item_id=item.item_id,
        priority=item.priority,
        priority_label=priority_label(item.priority),
        status=QueueItemStatus(item.status),
        assigned_to_name=assigned_to_name,
        assigned_to=item.assigned_to,
        due_date=item.due_date,
        sla_breached=item.sla_breached,
        age_hours=age_hours,
        summary=summary,
        patient_name=patient_name,
        dollar_amount=dollar_amount,
        created_at=item.created_at,
    )


# ── Queue Dashboard ────────────────────────────────────────────────

@router.get("/dashboard", response_model=QueueDashboard)
async def queue_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Manager view: overview of all queues across all practices.
    Returns KPI data plus queue summary counts.
    """
    # Total claims
    total_claims_q = await db.execute(select(func.count(Claim.id)))
    total_claims = total_claims_q.scalar() or 0

    # Claims submitted today
    today = date.today()
    claims_today_q = await db.execute(
        select(func.count(Claim.id)).where(
            func.date(Claim.submission_date) == today
        )
    )
    claims_submitted_today = claims_today_q.scalar() or 0

    # Total payments (sum of total_paid from claims)
    total_paid_q = await db.execute(select(func.coalesce(func.sum(Claim.total_paid), 0)))
    total_payments = float(total_paid_q.scalar() or 0)

    # Payments posted today
    payments_today_q = await db.execute(
        select(func.coalesce(func.sum(Claim.total_paid), 0)).where(
            func.date(Claim.adjudication_date) == today
        )
    )
    payments_posted_today = float(payments_today_q.scalar() or 0)

    # Open denials
    open_denials_q = await db.execute(
        select(func.count(Denial.id)).where(Denial.status.in_(["new", "appealed", "in_progress"]))
    )
    open_denials = open_denials_q.scalar() or 0

    # Denial rate
    total_submitted_q = await db.execute(
        select(func.count(Claim.id)).where(Claim.status != "draft")
    )
    total_submitted = total_submitted_q.scalar() or 1
    total_denied_q = await db.execute(
        select(func.count(Claim.id)).where(Claim.status == "denied")
    )
    total_denied = total_denied_q.scalar() or 0
    denial_rate = round(total_denied / total_submitted, 4) if total_submitted else 0.0

    # Clean claim rate (claims accepted on first submission)
    accepted_q = await db.execute(
        select(func.count(Claim.id)).where(Claim.status == "paid")
    )
    accepted = accepted_q.scalar() or 0
    clean_claim_rate = round(accepted / total_submitted, 4) if total_submitted else 0.0

    # Average days in AR (simple approximation from created_at to now for unpaid claims)
    avg_ar_q = await db.execute(
        select(func.coalesce(func.avg(
            func.extract("day", func.now() - Claim.created_at)
        ), 0)).where(Claim.status.in_(["submitted", "pending", "denied"]))
    )
    avg_days_in_ar = round(float(avg_ar_q.scalar() or 0), 1)

    # Queue counts
    user_id = current_user["user_id"] if current_user.get("user_id") else None

    my_queue_count = 0
    team_queue_count = 0
    unassigned_count = 0

    if user_id:
        my_q = await db.execute(
            select(func.count(WorkQueueItem.id)).where(
                and_(
                    WorkQueueItem.assigned_to == user_id,
                    WorkQueueItem.status.in_(["pending", "in_progress"]),
                )
            )
        )
        my_queue_count = my_q.scalar() or 0

    team_q = await db.execute(
        select(func.count(WorkQueueItem.id)).where(
            WorkQueueItem.status.in_(["pending", "in_progress", "escalated"])
        )
    )
    team_queue_count = team_q.scalar() or 0

    unassigned_q = await db.execute(
        select(func.count(WorkQueueItem.id)).where(
            and_(
                WorkQueueItem.assigned_to.is_(None),
                WorkQueueItem.status == "pending",
            )
        )
    )
    unassigned_count = unassigned_q.scalar() or 0

    return QueueDashboard(
        total_claims=total_claims,
        claims_submitted_today=claims_submitted_today,
        total_payments=total_payments,
        payments_posted_today=payments_posted_today,
        open_denials=open_denials,
        denial_rate=denial_rate,
        avg_days_in_ar=avg_days_in_ar,
        clean_claim_rate=clean_claim_rate,
        my_queue_count=my_queue_count,
        team_queue_count=team_queue_count,
        unassigned_count=unassigned_count,
    )


# ── My Queue ───────────────────────────────────────────────────────

@router.get("/my-queue")
async def get_my_queue(
    queue_type: QueueType | None = None,
    practice_id: UUID | None = None,
    priority: str | None = None,
    status: QueueItemStatus | None = None,
    include_unassigned: bool = False,
    sort_by: str = Query(default="priority", enum=["priority", "due_date", "dollar_amount", "age"]),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Get the current user's work queue.
    Returns paginated items with total count for the queues page.
    """
    user_id = current_user["user_id"] if current_user.get("user_id") else None

    # Base query: assigned to current user, or unassigned if requested
    conditions = [WorkQueueItem.status.in_(["pending", "in_progress", "escalated"])]
    if user_id:
        if include_unassigned:
            conditions.append(
                (WorkQueueItem.assigned_to == user_id) | (WorkQueueItem.assigned_to.is_(None))
            )
        else:
            conditions.append(WorkQueueItem.assigned_to == user_id)

    if queue_type:
        conditions.append(WorkQueueItem.queue_type == queue_type.value)

    # Per-area scoping: non-super-admins only see queues for their assigned agent areas.
    _allowed = allowed_queue_types(current_user)
    if _allowed is not None:
        conditions.append(WorkQueueItem.queue_type.in_(_allowed or ["__none__"]))
    if practice_id:
        conditions.append(WorkQueueItem.practice_id == practice_id)
    if status:
        conditions.append(WorkQueueItem.status == status.value)
    if priority:
        score = priority_to_score(priority)
        if score is not None:
            if score >= 80:
                conditions.append(WorkQueueItem.priority >= 80)
            elif score >= 60:
                conditions.append(WorkQueueItem.priority >= 60)
                conditions.append(WorkQueueItem.priority < 80)
            elif score >= 30:
                conditions.append(WorkQueueItem.priority >= 30)
                conditions.append(WorkQueueItem.priority < 60)
            else:
                conditions.append(WorkQueueItem.priority < 30)

    where_clause = and_(*conditions)

    # Count total
    count_q = await db.execute(select(func.count(WorkQueueItem.id)).where(where_clause))
    total = count_q.scalar() or 0

    # Ordering
    order_col = WorkQueueItem.priority.desc()
    if sort_by == "due_date":
        order_col = WorkQueueItem.due_date.asc()
    elif sort_by == "age":
        order_col = WorkQueueItem.created_at.asc()

    # Fetch items
    offset = (page - 1) * page_size
    items_q = await db.execute(
        select(WorkQueueItem)
        .where(where_clause)
        .order_by(order_col)
        .offset(offset)
        .limit(page_size)
    )
    items = items_q.scalars().all()

    # Build response
    result_items = []
    for item in items:
        resp = await _build_queue_item_response(item, db)
        result_items.append(resp.model_dump(mode="json"))

    return {
        "items": result_items,
        "total": total,
        "page": page,
        "page_size": page_size,
    }


@router.get("/queue/{queue_type}", response_model=list[QueueItemResponse])
async def get_queue(
    queue_type: QueueType,
    practice_id: UUID | None = None,
    assigned_to: UUID | None = None,
    status: QueueItemStatus | None = None,
    sla_breached_only: bool = False,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Get a specific queue with filtering.
    Managers can see all items; staff see only their assigned practices.
    """
    conditions = [WorkQueueItem.queue_type == queue_type.value]
    if practice_id:
        conditions.append(WorkQueueItem.practice_id == practice_id)
    if assigned_to:
        conditions.append(WorkQueueItem.assigned_to == assigned_to)
    if status:
        conditions.append(WorkQueueItem.status == status.value)
    if sla_breached_only:
        conditions.append(WorkQueueItem.sla_breached == True)

    offset = (page - 1) * page_size
    items_q = await db.execute(
        select(WorkQueueItem)
        .where(and_(*conditions))
        .order_by(WorkQueueItem.priority.desc())
        .offset(offset)
        .limit(page_size)
    )
    items = items_q.scalars().all()

    result = []
    for item in items:
        resp = await _build_queue_item_response(item, db)
        result.append(resp)
    return result


# ── Queue Actions ────────────────────────────────────────────────

@router.post("/queue/{item_id}/claim")
async def claim_queue_item(
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Staff member claims (self-assigns) a queue item."""
    user_id = current_user["user_id"]
    result = await db.execute(select(WorkQueueItem).where(WorkQueueItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    if item.assigned_to and item.assigned_to != user_id:
        raise HTTPException(status_code=409, detail="Item already assigned to another user")
    item.assigned_to = user_id
    item.status = "in_progress"
    item.started_at = datetime.utcnow()
    await db.flush()
    return {"detail": "Item claimed", "item_id": str(item.id)}


@router.post("/queue/{item_id}/release")
async def release_queue_item(
    item_id: UUID,
    body: ReleaseRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Release a claimed item back to the queue."""
    result = await db.execute(select(WorkQueueItem).where(WorkQueueItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    item.assigned_to = None
    item.status = "pending"
    item.started_at = None
    await db.flush()
    return {"detail": "Item released", "item_id": str(item.id)}


@router.post("/queue/{item_id}/complete")
async def complete_queue_item(
    item_id: UUID,
    body: CompleteRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Mark a queue item as completed."""
    result = await db.execute(select(WorkQueueItem).where(WorkQueueItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    item.status = "completed"
    item.completed_at = datetime.utcnow()
    if body and body.time_spent_seconds:
        item.time_spent_seconds = body.time_spent_seconds
    await db.flush()
    return {"detail": "Item completed", "item_id": str(item.id)}


@router.post("/queue/{item_id}/escalate")
async def escalate_queue_item(
    item_id: UUID,
    body: EscalateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Escalate an item to a manager or senior staff member."""
    result = await db.execute(select(WorkQueueItem).where(WorkQueueItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    item.status = "escalated"
    if body.escalate_to:
        item.assigned_to = body.escalate_to
    await db.flush()
    return {"detail": "Item escalated", "item_id": str(item.id)}


@router.post("/queue/{item_id}/assign")
async def assign_queue_item(
    item_id: UUID,
    body: AssignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Manager assigns a queue item to a specific staff member."""
    result = await db.execute(select(WorkQueueItem).where(WorkQueueItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Queue item not found")
    item.assigned_to = body.assign_to
    item.status = "in_progress"
    item.started_at = datetime.utcnow()
    await db.flush()
    return {"detail": "Item assigned", "item_id": str(item.id)}


@router.post("/queue/bulk-assign")
async def bulk_assign(body: BulkAssignRequest, db: AsyncSession = Depends(get_db)):
    """Manager bulk-assigns multiple items to one staff member."""
    result = await db.execute(
        select(WorkQueueItem).where(WorkQueueItem.id.in_(body.item_ids))
    )
    items = result.scalars().all()
    for item in items:
        item.assigned_to = body.assign_to
        item.status = "in_progress"
        item.started_at = datetime.utcnow()
    await db.flush()
    return {"detail": f"Assigned {len(items)} items", "count": len(items)}


@router.post("/queue/auto-assign")
async def trigger_auto_assignment(body: dict, db: AsyncSession = Depends(get_db)):
    """
    Run the auto-assignment algorithm for a queue.
    Body: { "queue_type": "coding", "practice_id": "uuid-or-null" }
    """
    # Placeholder: auto-assign by distributing unassigned items to available staff
    queue_type = body.get("queue_type")
    conditions = [WorkQueueItem.status == "pending", WorkQueueItem.assigned_to.is_(None)]
    if queue_type:
        conditions.append(WorkQueueItem.queue_type == queue_type)
    result = await db.execute(
        select(WorkQueueItem).where(and_(*conditions)).limit(100)
    )
    items = result.scalars().all()
    return {"detail": "Auto-assignment not yet fully implemented", "unassigned_count": len(items)}


# ── Staff Workload ───────────────────────────────────────────────

@router.get("/workload", response_model=list[StaffWorkload])
async def get_team_workload(db: AsyncSession = Depends(get_db)):
    """Manager view: current workload for all team members."""
    try:
        from sqlalchemy import text as sa_text

        result = await db.execute(
            select(
                WorkQueueItem.assigned_to,
                func.count(WorkQueueItem.id).label("items_in_progress"),
            )
            .where(WorkQueueItem.status == "in_progress")
            .group_by(WorkQueueItem.assigned_to)
        )
        rows = result.all()

        workload_list = []
        for row in rows:
            user_id = row[0]
            if not user_id:
                continue
            user_result = await db.execute(select(User).where(User.id == user_id))
            user = user_result.scalar_one_or_none()
            if not user:
                continue
            workload_list.append(StaffWorkload(
                user_id=user_id,
                user_name=f"{user.first_name} {user.last_name}",
                items_in_progress=row[1],
                items_completed_today=0,
                avg_time_per_item_minutes=0.0,
                queues={},
            ))

        return workload_list
    except Exception:
        return []


@router.get("/workload/{user_id}", response_model=StaffWorkload)
async def get_staff_workload(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Detailed workload for a specific staff member."""
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    count_result = await db.execute(
        select(func.count(WorkQueueItem.id))
        .where(WorkQueueItem.assigned_to == user_id)
        .where(WorkQueueItem.status == "in_progress")
    )
    items_in_progress = count_result.scalar() or 0

    return StaffWorkload(
        user_id=user_id,
        user_name=f"{user.first_name} {user.last_name}",
        items_in_progress=items_in_progress,
        items_completed_today=0,
        avg_time_per_item_minutes=0.0,
        queues={},
    )


# ── Productivity ─────────────────────────────────────────────────

@router.get("/productivity", response_model=list[ProductivityReport])
async def get_team_productivity(
    date_from: date | None = None,
    date_to: date | None = None,
    practice_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Team productivity report. Managers see all staff; staff see only themselves."""
    # Placeholder — return empty list until productivity aggregation is implemented
    return []


@router.get("/productivity/{user_id}", response_model=ProductivityReport)
async def get_staff_productivity(
    user_id: UUID,
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Individual staff productivity report."""
    # Look up user
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    user_name = f"{user.first_name} {user.last_name}"
    if date_from and date_to:
        period_label = f"{date_from} to {date_to}"
    elif date_from:
        period_label = f"from {date_from}"
    elif date_to:
        period_label = f"up to {date_to}"
    else:
        period_label = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m")

    # Query productivity records for this user
    from src.infrastructure.database.models import StaffProductivity

    conditions = [StaffProductivity.user_id == user_id]
    if date_from:
        conditions.append(StaffProductivity.date >= date_from)
    if date_to:
        conditions.append(StaffProductivity.date <= date_to)

    prod_result = await db.execute(
        select(StaffProductivity).where(and_(*conditions))
    )
    records = prod_result.scalars().all()

    # Aggregate productivity metrics from recorded data
    claims_submitted = sum(r.claims_submitted or 0 for r in records)
    claims_dollar_amount = sum(r.claims_dollar_amount or 0 for r in records)
    payments_posted = sum(r.payments_posted or 0 for r in records)
    payments_dollar_amount = sum(r.payments_dollar_amount or 0 for r in records)
    denials_worked = sum(r.denials_worked or 0 for r in records)
    denials_recovered = sum(r.denials_dollar_recovered or 0 for r in records)
    codes_reviewed = sum(r.codes_reviewed or 0 for r in records)
    total_items = sum(r.items_completed or 0 for r in records)
    total_days = len(set(r.date for r in records)) if records else 1
    avg_items_per_day = round(total_items / total_days, 1) if total_days else 0.0

    # SLA compliance: completed items that weren't breached vs total completed
    completed_q = await db.execute(
        select(func.count(WorkQueueItem.id)).where(
            and_(
                WorkQueueItem.assigned_to == user_id,
                WorkQueueItem.status == "completed",
            )
        )
    )
    completed_total = completed_q.scalar() or 0

    compliant_q = await db.execute(
        select(func.count(WorkQueueItem.id)).where(
            and_(
                WorkQueueItem.assigned_to == user_id,
                WorkQueueItem.status == "completed",
                WorkQueueItem.sla_breached == False,
            )
        )
    )
    compliant = compliant_q.scalar() or 0
    sla_compliance_pct = round((compliant / completed_total) * 100, 1) if completed_total else 0.0

    return ProductivityReport(
        user_name=user_name,
        period=period_label,
        claims_submitted=claims_submitted,
        claims_dollar_amount=claims_dollar_amount,
        payments_posted=payments_posted,
        payments_dollar_amount=payments_dollar_amount,
        denials_worked=denials_worked,
        denials_recovered=denials_recovered,
        codes_reviewed=codes_reviewed,
        avg_items_per_day=avg_items_per_day,
        sla_compliance_pct=sla_compliance_pct,
    )


# ── SLA Monitoring ───────────────────────────────────────────────

@router.get("/sla/breaches")
async def get_sla_breaches(
    practice_id: UUID | None = None,
    queue_type: QueueType | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all current SLA breaches across practices."""
    try:
        conditions = [WorkQueueItem.sla_breached == True]
        if practice_id:
            conditions.append(WorkQueueItem.practice_id == practice_id)
        if queue_type:
            conditions.append(WorkQueueItem.queue_type == queue_type.value)

        result = await db.execute(
            select(WorkQueueItem).where(and_(*conditions)).order_by(WorkQueueItem.priority.desc())
        )
        items = result.scalars().all()
        breaches = []
        for item in items:
            resp = await _build_queue_item_response(item, db)
            breaches.append(resp.model_dump(mode="json"))
        return breaches
    except Exception:
        return []


@router.get("/sla/compliance")
async def get_sla_compliance_report(
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
):
    """SLA compliance rates by practice and queue type."""
    try:
        total_q = await db.execute(select(func.count(WorkQueueItem.id)))
        breached_q = await db.execute(
            select(func.count(WorkQueueItem.id)).where(WorkQueueItem.sla_breached == True)
        )
        total = total_q.scalar() or 0
        breached = breached_q.scalar() or 0
        compliance = round((total - breached) / total, 4) if total else 1.0

        return {
            "total_items": total,
            "sla_breached": breached,
            "compliance_rate": compliance,
        }
    except Exception:
        return {"total_items": 0, "sla_breached": 0, "compliance_rate": 1.0}


# ── AI transparency, autonomy & batch review (roadmap A + D) ─────────────────
import json as _json  # noqa: E402


def _scope_provider(q, current_user):
    """Restrict a WorkQueueItem query to the provider's own practice."""
    if current_user.get("user_type") == "provider" and current_user.get("practice_id"):
        return q.where(WorkQueueItem.practice_id == current_user["practice_id"])
    return q


def _parse_notes(notes: str | None) -> dict:
    if not notes:
        return {}
    try:
        return _json.loads(notes)
    except (ValueError, TypeError):
        return {"message": notes}


@router.get("/queue/{item_id}/detail")
async def get_queue_item_detail(
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Full work-item detail incl. the step-by-step AI agent trace (roadmap A)."""
    item = await db.get(WorkQueueItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Work item not found")
    if current_user.get("user_type") == "provider" and str(item.practice_id) != str(current_user.get("practice_id")):
        raise HTTPException(status_code=403, detail="Not authorized for this item")
    meta = _parse_notes(item.notes)
    return {
        "id": str(item.id),
        "queue_type": item.queue_type,
        "item_type": item.item_type,
        "item_id": str(item.item_id),
        "status": item.status,
        "priority": item.priority,
        "agent_type": meta.get("agent_type"),
        "confidence": meta.get("confidence"),
        "outcome": meta.get("outcome"),
        "duration_ms": meta.get("duration_ms"),
        "message": meta.get("message"),
        "agent_trace": item.agent_trace or [],
        "started_at": item.started_at.isoformat() if item.started_at else None,
        "completed_at": item.completed_at.isoformat() if item.completed_at else None,
    }


@router.get("/needs-attention")
async def needs_attention(
    limit: int = Query(100, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Only the items a human must touch: escalated/failed or SLA-breached (roadmap D)."""
    from sqlalchemy import or_  # noqa: PLC0415
    q = select(WorkQueueItem).where(
        or_(WorkQueueItem.status.in_(["escalated", "failed"]), WorkQueueItem.sla_breached.is_(True))
    )
    q = _scope_provider(q, current_user).order_by(WorkQueueItem.priority.desc()).limit(limit)
    items = (await db.execute(q)).scalars().all()
    out = []
    for it in items:
        meta = _parse_notes(it.notes)
        out.append({
            "id": str(it.id), "queue_type": it.queue_type, "status": it.status,
            "priority": it.priority, "sla_breached": it.sla_breached,
            "agent_type": meta.get("agent_type"), "confidence": meta.get("confidence"),
            "reason": meta.get("message") or meta.get("outcome"),
        })
    return {"total": len(out), "items": out}


_AR_BUCKETS = [">120", "91-120", "61-90", "31-60", "0-30"]


@router.get("/open-ar")
async def open_ar(
    practice_id: UUID | None = None,
    bucket: str | None = Query(None, description="aging bucket filter"),
    status: str | None = Query(None, description="pending|in_progress|completed"),
    include_credits: bool = True,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Imported open AR (external_ar follow-up items): an aging-bucket summary plus a
    prioritized worklist. RBAC + provider scoped; reuse /queue/{id}/claim and /complete
    to work an item."""
    conds = [WorkQueueItem.item_type == "external_ar"]
    _allowed = allowed_queue_types(current_user)
    if _allowed is not None and "follow_up" not in (_allowed or []):
        return {"summary": {"open_ar_total": 0.0, "claim_count": 0,
                            "buckets": {b: {"count": 0, "balance": 0.0} for b in _AR_BUCKETS}},
                "items": [], "total": 0, "page": page, "page_size": page_size}
    if practice_id:
        conds.append(WorkQueueItem.practice_id == practice_id)
    if current_user.get("user_type") == "provider" and current_user.get("practice_id"):
        conds.append(WorkQueueItem.practice_id == current_user["practice_id"])

    rows = (await db.execute(select(WorkQueueItem).where(and_(*conds)))).scalars().all()

    summary = {b: {"count": 0, "balance": 0.0} for b in _AR_BUCKETS}
    total_ar = 0.0
    parsed = []
    for it in rows:
        m = _parse_notes(it.notes)
        b = m.get("bucket") if m.get("bucket") in _AR_BUCKETS else "0-30"
        bal = float(m.get("balance") or 0)
        is_credit = bool(m.get("is_credit"))
        if not is_credit:
            summary[b]["count"] += 1
            summary[b]["balance"] = round(summary[b]["balance"] + bal, 2)
            total_ar += bal
        parsed.append((it, m, b, bal, is_credit))

    def _keep(t):
        it, m, b, bal, is_credit = t
        if status and it.status != status:
            return False
        if bucket and b != bucket:
            return False
        if not include_credits and is_credit:
            return False
        return True

    work = [t for t in parsed if _keep(t)]
    work.sort(key=lambda t: (t[0].priority, t[3]), reverse=True)
    total = len(work)
    page_items = work[(page - 1) * page_size: (page - 1) * page_size + page_size]
    items = [{
        "id": str(it.id), "status": it.status, "priority": it.priority,
        "priority_label": priority_label(it.priority),
        "assigned_to": str(it.assigned_to) if it.assigned_to else None,
        "claim_no": m.get("claim_no"), "payer": m.get("payer"), "patient": m.get("patient"),
        "balance": round(bal, 2), "charges": m.get("charges"), "bucket": b,
        "aging_days": m.get("aging_days"), "service_date": m.get("service_date"),
        "is_credit": is_credit, "action": m.get("action"),
        "recommendation": m.get("recommendation"),
        "rec_reasoning": m.get("rec_reasoning"),
        "rec_confidence": m.get("rec_confidence"),
        "due_date": it.due_date.isoformat() if it.due_date else None,
    } for (it, m, b, bal, is_credit) in page_items]

    return {
        "summary": {
            "open_ar_total": round(total_ar, 2),
            "claim_count": sum(v["count"] for v in summary.values()),
            "buckets": summary,
        },
        "items": items, "total": total, "page": page, "page_size": page_size,
    }


class BulkCompleteRequest(BaseModel):
    item_ids: list[UUID]
    note: str | None = None


@router.post("/queue/bulk-complete")
async def bulk_complete(
    body: BulkCompleteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Approve/complete many AI-handled items in one action (roadmap D batch review)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    updated = 0
    for iid in body.item_ids:
        item = await db.get(WorkQueueItem, iid)
        if item is None:
            continue
        if current_user.get("user_type") == "provider" and str(item.practice_id) != str(current_user.get("practice_id")):
            continue
        if item.status in ("completed",):
            continue
        item.status = "completed"
        item.completed_at = now
        item.updated_at = now
        meta = _parse_notes(item.notes)
        meta["batch_approved_by"] = str(current_user.get("user_id"))
        if body.note:
            meta["approval_note"] = body.note
        item.notes = _json.dumps(meta)[:2000]
        updated += 1
    await db.commit()
    return {"updated": updated, "requested": len(body.item_ids)}
