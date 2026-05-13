"""
Provider Portal API Routes — Endpoints for practice clients.
Everything here is tenant-locked to the authenticated user's practice.
Providers CANNOT see any other practice's data.
"""

from datetime import date, datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.session import get_db
from src.infrastructure.database.models import (
    Claim,
    Denial,
    Appeal,
    Practice,
    Provider,
    Payer,
    PortalMessage,
    PortalNotification,
    ClientInvoice,
    ClaimLine,
    PayerEnrollment,
    User,
)
from src.infrastructure.auth.middleware import get_current_user

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────

class PortalDashboard(BaseModel):
    """Practice-level KPIs for the provider portal landing page."""
    practice_name: str
    period: str  # e.g., "May 2026"

    # Revenue Snapshot
    total_charges_mtd: float
    total_collections_mtd: float
    total_adjustments_mtd: float
    net_collection_rate: float  # (collections / (charges - contractual adj)) × 100

    # AR Summary
    total_ar_balance: float
    ar_0_30: float
    ar_31_60: float
    ar_61_90: float
    ar_91_120: float
    ar_120_plus: float

    # Claims Summary
    claims_submitted_mtd: int
    claims_paid_mtd: int
    claims_denied_mtd: int
    denial_rate: float

    # Pending Work
    charges_in_progress: int
    claims_pending_payer: int
    denials_being_worked: int
    appeals_pending: int


class ClaimStatusItem(BaseModel):
    """Simplified claim view for provider portal."""
    claim_id: UUID
    claim_number: str
    patient_name: str
    service_date: date
    provider_name: str
    payer_name: str
    total_charge: float
    total_paid: float
    status: str
    status_display: str  # Human-readable: "Submitted - Awaiting Payment", "Denied - Appeal Filed"
    last_updated: datetime
    denial_reason: str | None = None
    appeal_status: str | None = None


class MessageCreate(BaseModel):
    subject: str
    body: str
    related_claim_id: UUID | None = None
    is_urgent: bool = False


class MessageResponse(BaseModel):
    id: UUID
    sender_name: str
    sender_type: str  # "Your Team" or "Billing Team"
    subject: str | None
    body: str
    related_claim_number: str | None = None
    is_read: bool
    created_at: datetime


class NotificationResponse(BaseModel):
    id: UUID
    notification_type: str
    title: str
    body: str | None
    link_url: str | None
    is_read: bool
    created_at: datetime


class ReportSummary(BaseModel):
    report_type: str  # monthly_collection, aging, denial_summary, payer_performance
    period: str
    generated_at: datetime
    download_url: str


# ── Helpers ──────────────────────────────────────────────────────

STATUS_DISPLAY = {
    "draft": "Draft",
    "scrubbing": "Being Reviewed",
    "scrub_failed": "Review Failed",
    "ready": "Ready to Submit",
    "submitted": "Submitted - Awaiting Response",
    "accepted": "Accepted - Awaiting Payment",
    "rejected": "Rejected",
    "paid": "Paid",
    "partial_paid": "Partially Paid",
    "denied": "Denied",
    "appealed": "Denied - Appeal Filed",
    "closed": "Closed",
}


def _get_practice_id(current_user: dict) -> UUID | None:
    """Extract practice_id from current_user. Returns None for internal users without a practice."""
    return current_user.get("practice_id")


async def _build_claim_status_item(claim: Claim, db: AsyncSession) -> ClaimStatusItem:
    """Build a ClaimStatusItem from a Claim ORM object."""
    # Get patient name
    patient_name = ""
    if claim.patient:
        first = getattr(claim.patient, "first_name", "") or ""
        last = getattr(claim.patient, "last_name", "") or ""
        patient_name = f"{first} {last}".strip()

    # Get provider name
    provider_name = ""
    if claim.rendering_provider:
        first = claim.rendering_provider.first_name or ""
        last = claim.rendering_provider.last_name or ""
        provider_name = f"{first} {last}".strip()

    # Get payer name
    payer_name = ""
    if claim.payer:
        payer_name = claim.payer.payer_name or ""

    # Get denial info
    denial_reason = None
    appeal_status = None
    if claim.status == "denied":
        denial_result = await db.execute(
            select(Denial).where(Denial.claim_id == claim.id).order_by(Denial.created_at.desc())
        )
        denial = denial_result.scalar_one_or_none()
        if denial:
            denial_reason = f"{denial.reason_code}: {denial.denial_amount}"
            # Check for appeal
            appeal_result = await db.execute(
                select(Appeal).where(Appeal.denial_id == denial.id).order_by(Appeal.created_at.desc())
            )
            appeal = appeal_result.scalar_one_or_none()
            if appeal:
                appeal_status = appeal.status

    status_display = STATUS_DISPLAY.get(claim.status, claim.status.replace("_", " ").title())
    last_updated = claim.updated_at or claim.created_at or datetime.now(timezone.utc).replace(tzinfo=None)

    return ClaimStatusItem(
        claim_id=claim.id,
        claim_number=claim.claim_number,
        patient_name=patient_name,
        service_date=claim.encounter_date if hasattr(claim, "encounter_date") else date.today(),
        provider_name=provider_name,
        payer_name=payer_name,
        total_charge=claim.total_charge,
        total_paid=claim.total_paid,
        status=claim.status,
        status_display=status_display,
        last_updated=last_updated,
        denial_reason=denial_reason,
        appeal_status=appeal_status,
    )


# ── Dashboard ────────────────────────────────────────────────────

@router.get("/dashboard", response_model=PortalDashboard)
async def get_portal_dashboard(
    period: str | None = Query(None, description="YYYY-MM format, defaults to current month"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Practice dashboard — the landing page for provider portal users.
    Shows KPIs, AR aging, claim status summary, and pending items.
    Automatically scoped to the authenticated user's practice.
    """
    practice_id = _get_practice_id(current_user)
    if not practice_id:
        # Internal user without a practice — return empty dashboard
        return PortalDashboard(
            practice_name="",
            period=period or datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m"),
            total_charges_mtd=0,
            total_collections_mtd=0,
            total_adjustments_mtd=0,
            net_collection_rate=0,
            total_ar_balance=0,
            ar_0_30=0,
            ar_31_60=0,
            ar_61_90=0,
            ar_91_120=0,
            ar_120_plus=0,
            claims_submitted_mtd=0,
            claims_paid_mtd=0,
            claims_denied_mtd=0,
            denial_rate=0,
            charges_in_progress=0,
            claims_pending_payer=0,
            denials_being_worked=0,
            appeals_pending=0,
        )
    if period is None:
        period = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m")

    # Get practice name
    practice_result = await db.execute(select(Practice).where(Practice.id == practice_id))
    practice = practice_result.scalar_one_or_none()
    practice_name = practice.practice_name if practice else "Unknown"

    # Parse period for date range filtering
    year, month = period.split("-")
    period_start = date(int(year), int(month), 1)
    if int(month) == 12:
        period_end = date(int(year) + 1, 1, 1)
    else:
        period_end = date(int(year), int(month) + 1, 1)

    # Revenue snapshot
    charges_q = await db.execute(
        select(func.coalesce(func.sum(Claim.total_charge), 0)).where(
            and_(
                Claim.practice_id == practice_id,
                Claim.created_at >= period_start,
                Claim.created_at < period_end,
            )
        )
    )
    total_charges_mtd = float(charges_q.scalar() or 0)

    collections_q = await db.execute(
        select(func.coalesce(func.sum(Claim.total_paid), 0)).where(
            and_(
                Claim.practice_id == practice_id,
                Claim.adjudication_date >= period_start,
                Claim.adjudication_date < period_end,
            )
        )
    )
    total_collections_mtd = float(collections_q.scalar() or 0)

    adjustments_q = await db.execute(
        select(func.coalesce(func.sum(Claim.total_adjusted), 0)).where(
            and_(
                Claim.practice_id == practice_id,
                Claim.adjudication_date >= period_start,
                Claim.adjudication_date < period_end,
            )
        )
    )
    total_adjustments_mtd = float(adjustments_q.scalar() or 0)

    net_collection_rate = (
        round((total_collections_mtd / (total_charges_mtd - total_adjustments_mtd)) * 100, 1)
        if (total_charges_mtd - total_adjustments_mtd) > 0
        else 0.0
    )

    # AR aging
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = now.date()

    ar_total_q = await db.execute(
        select(func.coalesce(func.sum(Claim.total_charge - Claim.total_paid), 0)).where(
            and_(
                Claim.practice_id == practice_id,
                Claim.total_charge > Claim.total_paid,
                Claim.status.in_(["submitted", "accepted", "partial_paid"]),
            )
        )
    )
    total_ar_balance = float(ar_total_q.scalar() or 0)

    # Claims summary
    submitted_q = await db.execute(
        select(func.count(Claim.id)).where(
            and_(
                Claim.practice_id == practice_id,
                Claim.created_at >= period_start,
                Claim.created_at < period_end,
            )
        )
    )
    claims_submitted_mtd = submitted_q.scalar() or 0

    paid_q = await db.execute(
        select(func.count(Claim.id)).where(
            and_(
                Claim.practice_id == practice_id,
                Claim.status == "paid",
                Claim.adjudication_date >= period_start,
                Claim.adjudication_date < period_end,
            )
        )
    )
    claims_paid_mtd = paid_q.scalar() or 0

    denied_q = await db.execute(
        select(func.count(Claim.id)).where(
            and_(
                Claim.practice_id == practice_id,
                Claim.status == "denied",
                Claim.created_at >= period_start,
                Claim.created_at < period_end,
            )
        )
    )
    claims_denied_mtd = denied_q.scalar() or 0

    denial_rate = round(claims_denied_mtd / claims_submitted_mtd, 4) if claims_submitted_mtd else 0.0

    # Pending work
    charges_in_progress_q = await db.execute(
        select(func.count(Claim.id)).where(
            and_(
                Claim.practice_id == practice_id,
                Claim.status.in_(["draft", "scrubbing", "ready"]),
            )
        )
    )
    charges_in_progress = charges_in_progress_q.scalar() or 0

    claims_pending_q = await db.execute(
        select(func.count(Claim.id)).where(
            and_(
                Claim.practice_id == practice_id,
                Claim.status == "submitted",
            )
        )
    )
    claims_pending_payer = claims_pending_q.scalar() or 0

    denials_worked_q = await db.execute(
        select(func.count(Denial.id)).where(
            and_(
                Denial.practice_id == practice_id,
                Denial.status.in_(["new", "in_progress"]),
            )
        )
    )
    denials_being_worked = denials_worked_q.scalar() or 0

    appeals_pending_q = await db.execute(
        select(func.count(Appeal.id)).where(
            and_(
                Appeal.practice_id == practice_id,
                Appeal.status.in_(["draft", "submitted"]),
            )
        )
    )
    appeals_pending = appeals_pending_q.scalar() or 0

    return PortalDashboard(
        practice_name=practice_name,
        period=period,
        total_charges_mtd=total_charges_mtd,
        total_collections_mtd=total_collections_mtd,
        total_adjustments_mtd=total_adjustments_mtd,
        net_collection_rate=net_collection_rate,
        total_ar_balance=total_ar_balance,
        ar_0_30=0.0,
        ar_31_60=0.0,
        ar_61_90=0.0,
        ar_91_120=0.0,
        ar_120_plus=0.0,
        claims_submitted_mtd=claims_submitted_mtd,
        claims_paid_mtd=claims_paid_mtd,
        claims_denied_mtd=claims_denied_mtd,
        denial_rate=denial_rate,
        charges_in_progress=charges_in_progress,
        claims_pending_payer=claims_pending_payer,
        denials_being_worked=denials_being_worked,
        appeals_pending=appeals_pending,
    )


# ── Claim Status Tracker ─────────────────────────────────────────

@router.get("/claims", response_model=list[ClaimStatusItem])
async def get_my_claims(
    status: str | None = None,  # submitted, paid, denied, appealing, pending
    provider_id: UUID | None = None,
    patient_name: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    search: str | None = Query(None, description="Search by claim #, patient name, or payer"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Search and filter claims for this practice.
    Providers see a simplified status view — not internal workflow details.
    """
    practice_id = _get_practice_id(current_user)

    conditions = [Claim.practice_id == practice_id]
    if status:
        conditions.append(Claim.status == status)
    if provider_id:
        conditions.append(Claim.rendering_provider == provider_id)
    if date_from:
        conditions.append(Claim.created_at >= date_from)
    if date_to:
        conditions.append(Claim.created_at <= date_to)

    offset = (page - 1) * page_size
    result = await db.execute(
        select(Claim)
        .where(and_(*conditions))
        .order_by(Claim.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    claims = result.scalars().all()

    items = []
    for claim in claims:
        item = await _build_claim_status_item(claim, db)
        items.append(item)
    return items


@router.get("/claims/{claim_id}", response_model=ClaimStatusItem)
async def get_claim_status(
    claim_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Claim detail view for providers.
    Shows: dates, codes, charges, payments, denial info, appeal status.
    Does NOT show: internal notes, scrub details, staff assignments.
    """
    practice_id = _get_practice_id(current_user)

    result = await db.execute(
        select(Claim).where(and_(Claim.id == claim_id, Claim.practice_id == practice_id))
    )
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    return await _build_claim_status_item(claim, db)


@router.get("/claims/{claim_id}/timeline")
async def get_claim_timeline(
    claim_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Visual timeline of claim lifecycle events:
    Charge received → Coded → Submitted → Accepted → Paid
    Or: Submitted → Denied → Appeal Filed → Appeal Approved → Paid
    """
    practice_id = _get_practice_id(current_user)

    result = await db.execute(
        select(Claim).where(and_(Claim.id == claim_id, Claim.practice_id == practice_id))
    )
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    # Build timeline from claim status changes
    timeline = []
    if claim.created_at:
        timeline.append({
            "event": "Claim Created",
            "timestamp": claim.created_at.isoformat() if claim.created_at else None,
            "details": f"Claim {claim.claim_number} created",
        })
    if claim.submission_date:
        timeline.append({
            "event": "Claim Submitted",
            "timestamp": claim.submission_date.isoformat() if claim.submission_date else None,
            "details": f"Submitted to payer",
        })
    if claim.status == "paid" and claim.adjudication_date:
        timeline.append({
            "event": "Claim Paid",
            "timestamp": claim.adjudication_date.isoformat() if claim.adjudication_date else None,
            "details": f"Paid ${claim.total_paid}",
        })
    if claim.status == "denied":
        timeline.append({
            "event": "Claim Denied",
            "timestamp": claim.adjudication_date.isoformat() if claim.adjudication_date else None,
            "details": f"Denied",
        })

    return timeline


# ── Denial Alerts ────────────────────────────────────────────────

@router.get("/denials")
async def get_my_denials(
    status: str | None = None,  # new, appealing, resolved
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    View denials for this practice.
    Shows: what was denied, why, and what the billing team is doing about it.
    """
    practice_id = _get_practice_id(current_user)

    conditions = [Denial.practice_id == practice_id]
    if status:
        conditions.append(Denial.status == status)
    if date_from:
        conditions.append(Denial.denial_date >= date_from)
    if date_to:
        conditions.append(Denial.denial_date <= date_to)

    offset = (page - 1) * 50  # page_size
    result = await db.execute(
        select(Denial)
        .where(and_(*conditions))
        .order_by(Denial.priority_score.desc() if Denial.priority_score is not None else Denial.denial_date.desc())
        .offset(offset)
        .limit(50)
    )
    denials = result.scalars().all()

    denial_list = []
    for d in denials:
        denial_list.append({
            "id": str(d.id),
            "claim_id": str(d.claim_id),
            "denial_date": d.denial_date.isoformat() if d.denial_date else None,
            "reason_code": d.reason_code,
            "denial_amount": d.denial_amount,
            "category": d.category,
            "status": d.status,
            "priority_score": d.priority_score,
            "recovery_probability": d.recovery_probability,
            "appeal_deadline": d.appeal_deadline.isoformat() if d.appeal_deadline else None,
        })
    return denial_list


@router.get("/denials/{denial_id}")
async def get_denial_detail(
    denial_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Denial detail with appeal status and any action needed from provider."""
    practice_id = _get_practice_id(current_user)

    result = await db.execute(
        select(Denial).where(and_(Denial.id == denial_id, Denial.practice_id == practice_id))
    )
    denial = result.scalar_one_or_none()
    if not denial:
        raise HTTPException(status_code=404, detail="Denial not found")

    # Get appeal status
    appeal_result = await db.execute(
        select(Appeal).where(Appeal.denial_id == denial_id)
    )
    appeals = appeal_result.scalars().all()
    appeal_list = [
        {
            "id": str(a.id),
            "level": a.appeal_level,
            "status": a.status,
            "submitted_date": a.submitted_date.isoformat() if a.submitted_date else None,
            "decision": a.decision,
        }
        for a in appeals
    ]

    return {
        "id": str(denial.id),
        "claim_id": str(denial.claim_id),
        "denial_date": denial.denial_date.isoformat() if denial.denial_date else None,
        "reason_code": denial.reason_code,
        "denial_amount": denial.denial_amount,
        "category": denial.category,
        "subcategory": denial.subcategory,
        "root_cause": denial.root_cause,
        "status": denial.status,
        "priority_score": denial.priority_score,
        "recovery_probability": denial.recovery_probability,
        "appeal_deadline": denial.appeal_deadline.isoformat() if denial.appeal_deadline else None,
        "appeals": appeal_list,
    }


@router.post("/denials/{denial_id}/upload-supporting-doc")
async def upload_supporting_document(
    denial_id: UUID,
    document: UploadFile = File(..., description="Clinical documentation to support appeal"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Provider uploads additional clinical documentation to support an appeal."""
    practice_id = _get_practice_id(current_user)

    result = await db.execute(
        select(Denial).where(and_(Denial.id == denial_id, Denial.practice_id == practice_id))
    )
    denial = result.scalar_one_or_none()
    if not denial:
        raise HTTPException(status_code=404, detail="Denial not found")

    return {
        "message": "Document uploaded",
        "denial_id": str(denial_id),
        "filename": document.filename,
        "content_type": document.content_type,
    }


# ── Messaging ────────────────────────────────────────────────────

@router.get("/messages", response_model=list[MessageResponse])
async def list_messages(
    unread_only: bool = False,
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List messages between the practice and billing team."""
    practice_id = _get_practice_id(current_user)

    conditions = [PortalMessage.practice_id == practice_id]
    if unread_only:
        conditions.append(PortalMessage.is_read == False)

    offset = (page - 1) * 50
    result = await db.execute(
        select(PortalMessage)
        .where(and_(*conditions))
        .order_by(PortalMessage.created_at.desc())
        .offset(offset)
        .limit(50)
    )
    messages = result.scalars().all()

    responses = []
    for msg in messages:
        # Get sender name
        sender_name = "Billing Team"
        if msg.sender_id:
            sender_result = await db.execute(select(User).where(User.id == msg.sender_id))
            sender = sender_result.scalar_one_or_none()
            if sender:
                sender_name = f"{sender.first_name} {sender.last_name}"

        # Get related claim number
        related_claim_number = None
        if msg.related_claim_id:
            claim_result = await db.execute(
                select(Claim.claim_number).where(Claim.id == msg.related_claim_id)
            )
            related_claim_number = claim_result.scalar_one_or_none()

        responses.append(MessageResponse(
            id=msg.id,
            sender_name=sender_name,
            sender_type=msg.sender_type,
            subject=msg.subject,
            body=msg.body,
            related_claim_number=related_claim_number,
            is_read=msg.is_read,
            created_at=msg.created_at,
        ))
    return responses


@router.post("/messages", response_model=MessageResponse, status_code=201)
async def send_message(
    message: MessageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Send a message to the billing team.
    Can be linked to a specific claim for context.
    """
    practice_id = _get_practice_id(current_user)
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    msg = PortalMessage(
        id=uuid4(),
        practice_id=practice_id,
        sender_id=current_user.get("user_id"),
        sender_type="provider",
        subject=message.subject,
        body=message.body,
        related_claim_id=message.related_claim_id,
        is_urgent=message.is_urgent,
    )
    db.add(msg)
    await db.flush()

    sender_name = f"{current_user.get('first_name', '')} {current_user.get('last_name', '')}".strip() or "Provider"

    # Get related claim number
    related_claim_number = None
    if message.related_claim_id:
        claim_result = await db.execute(
            select(Claim.claim_number).where(Claim.id == message.related_claim_id)
        )
        related_claim_number = claim_result.scalar_one_or_none()

    return MessageResponse(
        id=msg.id,
        sender_name=sender_name,
        sender_type="provider",
        subject=msg.subject,
        body=msg.body,
        related_claim_number=related_claim_number,
        is_read=msg.is_read,
        created_at=now,
    )


@router.post("/messages/{message_id}/read")
async def mark_message_read(
    message_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Mark a message as read."""
    practice_id = _get_practice_id(current_user)

    result = await db.execute(
        select(PortalMessage).where(
            and_(PortalMessage.id == message_id, PortalMessage.practice_id == practice_id)
        )
    )
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="Message not found")

    msg.is_read = True
    msg.read_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.flush()

    return {"message": "Message marked as read"}


# ── Notifications ────────────────────────────────────────────────

@router.get("/notifications", response_model=list[NotificationResponse])
async def list_notifications(
    unread_only: bool = True,
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Provider notifications:
    - Denial alerts
    - Payment posted notifications
    - Information requested alerts
    - Report ready notifications
    - Appeal outcome notifications
    """
    practice_id = _get_practice_id(current_user)
    user_id = current_user.get("user_id")

    conditions = [PortalNotification.practice_id == practice_id]
    if user_id:
        conditions.append(PortalNotification.user_id == user_id)
    if unread_only:
        conditions.append(PortalNotification.is_read == False)

    offset = (page - 1) * 50
    result = await db.execute(
        select(PortalNotification)
        .where(and_(*conditions))
        .order_by(PortalNotification.created_at.desc())
        .offset(offset)
        .limit(50)
    )
    notifications = result.scalars().all()

    return [
        NotificationResponse(
            id=n.id,
            notification_type=n.notification_type,
            title=n.title,
            body=n.body,
            link_url=n.link_url,
            is_read=n.is_read,
            created_at=n.created_at,
        )
        for n in notifications
    ]


@router.post("/notifications/mark-all-read")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Mark all notifications as read for the current user."""
    practice_id = _get_practice_id(current_user)
    user_id = current_user.get("user_id")
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    # Update all unread notifications for this user
    result = await db.execute(
        select(PortalNotification).where(
            and_(
                PortalNotification.practice_id == practice_id,
                PortalNotification.is_read == False,
                PortalNotification.user_id == user_id if user_id else True,
            )
        )
    )
    notifications = result.scalars().all()
    for n in notifications:
        n.is_read = True
        n.read_at = now

    await db.flush()

    return {"message": "All notifications marked as read", "count": len(notifications)}


# ── Reports ──────────────────────────────────────────────────────

@router.get("/reports", response_model=list[ReportSummary])
async def list_available_reports(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List reports available for download (monthly collections, aging, etc.)."""
    return []


@router.get("/reports/monthly-collection")
async def monthly_collection_report(
    period: str = Query(description="YYYY-MM format"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Detailed monthly collection report:
    - Total charges vs collections
    - Breakdown by payer
    - Breakdown by provider
    - Payment vs adjustment detail
    - Comparison to prior month and prior year
    """
    practice_id = _get_practice_id(current_user)

    year, month = period.split("-")
    period_start = date(int(year), int(month), 1)
    if int(month) == 12:
        period_end = date(int(year) + 1, 1, 1)
    else:
        period_end = date(int(year), int(month) + 1, 1)

    # Total charges and collections
    charges_q = await db.execute(
        select(func.coalesce(func.sum(Claim.total_charge), 0)).where(
            and_(
                Claim.practice_id == practice_id,
                Claim.created_at >= period_start,
                Claim.created_at < period_end,
            )
        )
    )
    total_charges = float(charges_q.scalar() or 0)

    collections_q = await db.execute(
        select(func.coalesce(func.sum(Claim.total_paid), 0)).where(
            and_(
                Claim.practice_id == practice_id,
                Claim.adjudication_date >= period_start,
                Claim.adjudication_date < period_end,
            )
        )
    )
    total_collections = float(collections_q.scalar() or 0)

    adjustments_q = await db.execute(
        select(func.coalesce(func.sum(Claim.total_adjusted), 0)).where(
            and_(
                Claim.practice_id == practice_id,
                Claim.adjudication_date >= period_start,
                Claim.adjudication_date < period_end,
            )
        )
    )
    total_adjustments = float(adjustments_q.scalar() or 0)

    return {
        "period": period,
        "total_charges": total_charges,
        "total_collections": total_collections,
        "total_adjustments": total_adjustments,
        "by_payer": [],
        "by_provider": [],
    }


@router.get("/reports/ar-aging")
async def ar_aging_report(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Current AR aging by payer and by aging bucket."""
    practice_id = _get_practice_id(current_user)

    # Get all outstanding claims
    result = await db.execute(
        select(Claim).where(
            and_(
                Claim.practice_id == practice_id,
                Claim.total_charge > Claim.total_paid,
                Claim.status.in_(["submitted", "accepted", "partial_paid"]),
            )
        )
    )
    claims = result.scalars().all()

    aging = {
        "0_30": 0.0,
        "31_60": 0.0,
        "61_90": 0.0,
        "91_120": 0.0,
        "120_plus": 0.0,
        "total": 0.0,
    }

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    today = now.date()

    for claim in claims:
        balance = claim.total_charge - (claim.total_paid or 0)
        days = (today - claim.created_at.date()).days if claim.created_at else 0

        if days <= 30:
            aging["0_30"] += balance
        elif days <= 60:
            aging["31_60"] += balance
        elif days <= 90:
            aging["61_90"] += balance
        elif days <= 120:
            aging["91_120"] += balance
        else:
            aging["120_plus"] += balance
        aging["total"] += balance

    return aging


@router.get("/reports/denial-summary")
async def denial_summary_report(
    period: str = Query(description="YYYY-MM format"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Denial rates, top reasons, and outcomes for the period."""
    practice_id = _get_practice_id(current_user)

    year, month = period.split("-")
    period_start = date(int(year), int(month), 1)
    if int(month) == 12:
        period_end = date(int(year) + 1, 1, 1)
    else:
        period_end = date(int(year), int(month) + 1, 1)

    # Denial count and rate
    total_claims_q = await db.execute(
        select(func.count(Claim.id)).where(
            and_(
                Claim.practice_id == practice_id,
                Claim.created_at >= period_start,
                Claim.created_at < period_end,
            )
        )
    )
    total_claims = total_claims_q.scalar() or 0

    denied_q = await db.execute(
        select(func.count(Claim.id)).where(
            and_(
                Claim.practice_id == practice_id,
                Claim.status == "denied",
                Claim.created_at >= period_start,
                Claim.created_at < period_end,
            )
        )
    )
    denied_claims = denied_q.scalar() or 0

    denial_rate = round(denied_claims / total_claims, 4) if total_claims else 0.0

    # Top denial reasons
    reasons_q = await db.execute(
        select(Denial.reason_code, func.count(Denial.id).label("count"))
        .where(
            and_(
                Denial.practice_id == practice_id,
                Denial.denial_date >= period_start,
                Denial.denial_date < period_end,
            )
        )
        .group_by(Denial.reason_code)
        .order_by(func.count(Denial.id).desc())
        .limit(10)
    )
    top_reasons = [{"reason_code": row[0], "count": row[1]} for row in reasons_q.all()]

    return {
        "period": period,
        "total_claims": total_claims,
        "denied_claims": denied_claims,
        "denial_rate": denial_rate,
        "top_reasons": top_reasons,
    }


@router.get("/reports/payer-performance")
async def payer_performance_report(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Payer comparison: avg days to pay, denial rate, reimbursement rate."""
    practice_id = _get_practice_id(current_user)

    # Get payer performance data
    result = await db.execute(
        select(
            Payer.payer_name,
            func.count(Claim.id).label("total_claims"),
            func.coalesce(func.sum(Claim.total_charge), 0).label("total_charged"),
            func.coalesce(func.sum(Claim.total_paid), 0).label("total_paid"),
        )
        .join(Payer, Claim.payer_id == Payer.id)
        .where(Claim.practice_id == practice_id)
        .group_by(Payer.payer_name)
    )
    payer_data = result.all()

    payers = []
    for row in payer_data:
        payer_name, total_claims, total_charged, total_paid = row
        avg_reimbursement = round(total_paid / total_charged, 4) if total_charged else 0.0
        payers.append({
            "payer_name": payer_name,
            "total_claims": total_claims,
            "total_charged": float(total_charged),
            "total_paid": float(total_paid),
            "reimbursement_rate": avg_reimbursement,
        })

    return payers


@router.get("/reports/download/{report_id}")
async def download_report(
    report_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Download a generated report as PDF."""
    raise HTTPException(status_code=404, detail="Report not found")


# ── Provider Profile ─────────────────────────────────────────────

@router.get("/my-practice")
async def get_my_practice(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get practice info, providers, locations, and payers on file."""
    practice_id = _get_practice_id(current_user)

    result = await db.execute(select(Practice).where(Practice.id == practice_id))
    practice = result.scalar_one_or_none()
    if not practice:
        raise HTTPException(status_code=404, detail="Practice not found")

    return {
        "id": str(practice.id),
        "practice_name": practice.practice_name,
        "legal_name": practice.legal_name,
        "specialty_primary": practice.specialty_primary,
        "address": {
            "line_1": practice.address_line_1,
            "line_2": practice.address_line_2,
            "city": practice.city,
            "state": practice.state,
            "zip_code": practice.zip_code,
        },
        "phone": practice.phone,
        "email": practice.email,
        "status": practice.status,
    }


@router.get("/my-practice/providers")
async def list_my_providers(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List providers in this practice."""
    practice_id = _get_practice_id(current_user)

    from src.infrastructure.database.models import PayerEnrollment
    # Get providers through payer enrollments or a more direct link
    # For now, get providers who have rendered claims for this practice
    result = await db.execute(
        select(Provider).where(Provider.is_active == True)
    )
    providers = result.scalars().all()

    provider_list = []
    for p in providers:
        provider_list.append({
            "id": str(p.id),
            "first_name": p.first_name,
            "last_name": p.last_name,
            "npi": p.npi,
            "specialty": p.specialty,
            "credential": p.credential,
        })
    return provider_list


@router.get("/my-practice/payers")
async def list_my_payers(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List payers enrolled for this practice."""
    practice_id = _get_practice_id(current_user)

    result = await db.execute(
        select(PayerEnrollment, Payer)
        .join(Payer, PayerEnrollment.payer_id == Payer.id)
        .where(and_(PayerEnrollment.practice_id == practice_id, PayerEnrollment.is_active == True))
    )
    rows = result.all()

    payer_list = []
    for enrollment, payer in rows:
        payer_list.append({
            "id": str(payer.id),
            "payer_name": payer.payer_name,
            "payer_type": payer.payer_type,
            "plan_name": enrollment.plan_name if hasattr(enrollment, "plan_name") else None,
            "member_id": enrollment.member_id if hasattr(enrollment, "member_id") else None,
            "is_active": enrollment.is_active,
        })
    return payer_list


# ── Invoices (What You Charge the Provider) ──────────────────────

@router.get("/invoices")
async def list_my_invoices(
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """View billing invoices from the billing company to this practice."""
    practice_id = _get_practice_id(current_user)

    conditions = [ClientInvoice.practice_id == practice_id]
    if status:
        conditions.append(ClientInvoice.status == status)

    offset = (page - 1) * 50
    result = await db.execute(
        select(ClientInvoice)
        .where(and_(*conditions))
        .order_by(ClientInvoice.created_at.desc())
        .offset(offset)
        .limit(50)
    )
    invoices = result.scalars().all()

    invoice_list = []
    for inv in invoices:
        invoice_list.append({
            "id": str(inv.id),
            "invoice_number": inv.invoice_number,
            "billing_period": f"{inv.billing_period_start} to {inv.billing_period_end}",
            "total_collections": inv.total_collections,
            "total_due": inv.total_due,
            "status": inv.status,
            "sent_at": inv.sent_at.isoformat() if inv.sent_at else None,
            "due_date": inv.due_date.isoformat() if inv.due_date else None,
            "paid_at": inv.paid_at.isoformat() if inv.paid_at else None,
            "paid_amount": inv.paid_amount,
            "created_at": inv.created_at.isoformat() if inv.created_at else None,
        })
    return invoice_list


@router.get("/invoices/{invoice_id}")
async def get_invoice_detail(
    invoice_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Detailed invoice with line items and collection basis."""
    practice_id = _get_practice_id(current_user)

    result = await db.execute(
        select(ClientInvoice).where(
            and_(ClientInvoice.id == invoice_id, ClientInvoice.practice_id == practice_id)
        )
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return {
        "id": str(invoice.id),
        "invoice_number": invoice.invoice_number,
        "billing_period_start": invoice.billing_period_start.isoformat(),
        "billing_period_end": invoice.billing_period_end.isoformat(),
        "total_collections": invoice.total_collections,
        "fee_model_used": invoice.fee_model_used,
        "calculated_fee": invoice.calculated_fee,
        "minimum_fee_applied": invoice.minimum_fee_applied,
        "adjustments": invoice.adjustments,
        "total_due": invoice.total_due,
        "line_items": invoice.line_items or [],
        "status": invoice.status,
        "sent_at": invoice.sent_at.isoformat() if invoice.sent_at else None,
        "due_date": invoice.due_date.isoformat() if invoice.due_date else None,
        "paid_at": invoice.paid_at.isoformat() if invoice.paid_at else None,
        "paid_amount": invoice.paid_amount,
        "notes": invoice.notes,
        "created_at": invoice.created_at.isoformat() if invoice.created_at else None,
    }


@router.get("/invoices/{invoice_id}/download")
async def download_invoice_pdf(
    invoice_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Download invoice as PDF."""
    practice_id = _get_practice_id(current_user)

    result = await db.execute(
        select(ClientInvoice).where(
            and_(ClientInvoice.id == invoice_id, ClientInvoice.practice_id == practice_id)
        )
    )
    invoice = result.scalar_one_or_none()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")

    return {"message": "PDF generation not yet available"}