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
from sqlalchemy import select, func, case, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.session import get_db
from src.infrastructure.database.models import (
    WorkQueueItem,
    Claim,
    Denial,
    Practice,
    User,
)
from src.infrastructure.auth.middleware import get_current_user

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

    # Get practice name
    practice_name = ""
    if item.practice:
        practice_name = item.practice.name or ""

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
    # Aggregate workload from work_queue_items
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
    raise HTTPException(status_code=501, detail="Not yet implemented")


# ── SLA Monitoring ───────────────────────────────────────────────

@router.get("/sla/breaches")
async def get_sla_breaches(
    practice_id: UUID | None = None,
    queue_type: QueueType | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all current SLA breaches across practices."""
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


@router.get("/sla/compliance")
async def get_sla_compliance_report(
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
):
    """SLA compliance rates by practice and queue type."""
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