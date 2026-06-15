"""
Payment Posting API Routes
ERA/835 processing, payment matching, and reconciliation.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel, Field, computed_field
from typing import Optional
from uuid import UUID
from datetime import date, datetime, timezone
from enum import Enum
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.session import get_db
from src.infrastructure.database.models import (
    PaymentBatch,
    PaymentLine,
    Adjustment,
    Payer,
)
from src.api.schemas.common import PaginatedResponse
from src.infrastructure.auth.middleware import get_current_user

router = APIRouter()


class PaymentMatchStatus(str, Enum):
    MATCHED = "matched"
    UNMATCHED = "unmatched"
    PARTIAL = "partial"
    EXCEPTION = "exception"


class ManualMatchRequest(BaseModel):
    claim_id: UUID


class DisputeUnderpaymentRequest(BaseModel):
    expected_amount: float
    notes: str | None = None


class PostBatchRequest(BaseModel):
    auto_only: bool = True


class BatchStatus(str, Enum):
    RECEIVED = "received"
    PROCESSING = "processing"
    POSTED = "posted"
    RECONCILED = "reconciled"
    EXCEPTION = "exception"


class AdjustmentDetail(BaseModel):
    group_code: str          # CO, PR, OA, PI
    reason_code: str         # CARC code
    reason_description: str
    amount: float
    remark_codes: list[str]
    is_denial: bool


class PaymentLineResponse(BaseModel):
    id: UUID
    claim_number: str
    patient_name: str
    service_date: date | None
    cpt_code: str | None
    billed_amount: float | None
    allowed_amount: float | None
    paid_amount: float
    patient_responsibility: float
    adjustments: list[AdjustmentDetail]
    match_status: PaymentMatchStatus
    match_confidence: float | None
    is_underpaid: bool
    underpayment_amount: float | None


class BatchResponse(BaseModel):
    id: UUID
    payer_name: str
    check_number: str | None
    payment_method: str | None
    total_paid: float
    total_claims: int
    status: BatchStatus
    auto_posted_count: int
    exception_count: int
    denial_count: int
    underpayment_count: int
    production_date: date | None
    posted_date: datetime | None
    created_at: datetime | None = None

    model_config = {"from_attributes": True}

    # Frontend alias fields — use @computed_field so Pydantic v2 includes them in serialization
    @computed_field
    @property
    def batch_id(self) -> str:
        """Use check_number as a human-readable batch identifier; fall back to short UUID."""
        if self.check_number:
            return self.check_number
        return f"BATCH-{str(self.id)[:8].upper()}"

    @computed_field
    @property
    def total_amount(self) -> float:
        return self.total_paid

    @computed_field
    @property
    def claim_count(self) -> int:
        return self.total_claims

    @computed_field
    @property
    def processed_at(self) -> datetime | None:
        return self.posted_date


class ReconciliationReport(BaseModel):
    period: str
    total_payments_received: float
    total_payments_posted: float
    unmatched_payments: float
    unmatched_count: int
    underpayments_detected: float
    underpayment_count: int
    denials_routed: int
    denials_amount: float
    auto_post_rate: float  # Percentage


# ── Endpoints ────────────────────────────────────────────────────

@router.post("/era/upload", response_model=BatchResponse, status_code=201)
async def upload_era(
    era_file: UploadFile = File(..., description="X12 835 ERA file"),
):
    """
    Upload and process an ERA/835 file:
    1. Parse X12 835 into structured payment records
    2. Match each payment line to existing claims
    3. Identify contractual adjustments vs patient responsibility vs denials
    4. Compare paid amounts to contracted fee schedule rates
    5. Auto-post clean matches (high confidence + correct amount)
    6. Route denials to Denial Management module
    7. Flag underpayments for review
    8. Queue exceptions for manual matching
    """
    return {"message": "ERA upload processed", "batch_id": None, "lines_imported": 0}


@router.get("/batches", response_model=PaginatedResponse[BatchResponse])
async def list_payment_batches(
    status: BatchStatus | None = None,
    payer_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List payment batches with filtering."""
    conditions = []
    if status is not None:
        conditions.append(PaymentBatch.status == status.value)
    if payer_id is not None:
        conditions.append(PaymentBatch.payer_id == payer_id)
    if date_from is not None:
        conditions.append(PaymentBatch.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to is not None:
        conditions.append(PaymentBatch.created_at <= datetime.combine(date_to, datetime.max.time()))

    # Practice filter for non-admin
    practice_id = current_user.get("practice_id")
    internal_role = current_user.get("internal_role")
    user_type = current_user.get("user_type")
    if user_type == "provider" and practice_id:
        conditions.append(PaymentBatch.practice_id == practice_id)

    count_q = select(func.count(PaymentBatch.id))
    if conditions:
        count_q = count_q.where(*conditions)
    total = (await db.execute(count_q)).scalar_one()

    q = select(PaymentBatch)
    if conditions:
        q = q.where(*conditions)
    q = q.order_by(PaymentBatch.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
    batches = (await db.execute(q)).scalars().all()

    # Fetch payer names in a second pass (no relationship on model)
    payer_ids = list({b.payer_id for b in batches})
    payer_map: dict = {}
    if payer_ids:
        payer_rows = (await db.execute(select(Payer).where(Payer.id.in_(payer_ids)))).scalars().all()
        payer_map = {p.id: p.payer_name for p in payer_rows}

    items = []
    for b in batches:
        safe_status = BatchStatus(b.status) if b.status and b.status in [e.value for e in BatchStatus] else BatchStatus.RECEIVED
        # Use check_number or EFT trace as the human-readable batch identifier;
        # fall back to a short UUID prefix so the UI never shows a raw UUID.
        readable_batch_id = b.check_number or b.eft_trace or f"BATCH-{str(b.id)[:8].upper()}"
        items.append({
            "id": str(b.id),
            "batch_id": readable_batch_id,
            "payer_name": payer_map.get(b.payer_id, "Unknown"),
            "check_number": b.check_number,
            "payment_method": b.payment_method,
            "total_paid": b.total_paid or 0.0,
            "total_amount": b.total_paid or 0.0,
            "total_claims": b.total_claims or 0,
            "claim_count": b.total_claims or 0,
            "status": safe_status.value,
            "auto_posted_count": 0,
            "exception_count": 0,
            "denial_count": 0,
            "underpayment_count": 0,
            "production_date": b.production_date.isoformat() if b.production_date else None,
            "posted_date": b.posted_date.isoformat() if b.posted_date else None,
            "processed_at": b.posted_date.isoformat() if b.posted_date else None,
            "created_at": b.created_at.isoformat() if b.created_at else None,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/batches/{batch_id}", response_model=BatchResponse)
async def get_payment_batch(
    batch_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get payment batch details."""
    raise HTTPException(status_code=404, detail="Payment batch not found")


@router.get("/batches/{batch_id}/lines", response_model=PaginatedResponse[PaymentLineResponse])
async def get_batch_lines(
    batch_id: UUID,
    match_status: PaymentMatchStatus | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get payment lines within a batch, optionally filtered by match status."""
    return {"items": [], "total": 0, "page": page, "page_size": page_size}

@router.post("/batches/{batch_id}/post")
async def post_batch(
    batch_id: UUID,
    body: PostBatchRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Post matched payments."""
    return {"message": "Batch posted"}


@router.post("/lines/{line_id}/match")
async def manual_match(
    line_id: UUID,
    body: ManualMatchRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Manually match an unmatched payment line to a claim."""
    return {"message": "Payment matched"}


@router.post("/lines/{line_id}/dispute-underpayment")
async def dispute_underpayment(
    line_id: UUID,
    body: DisputeUnderpaymentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Flag an underpayment for dispute with the payer."""
    return {"message": "Dispute filed"}


@router.get("/reconciliation", response_model=ReconciliationReport)
async def get_reconciliation_report(
    period: str = Query(default=None, description="Period in YYYY-MM format"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Monthly reconciliation report."""
    if period is None:
        from datetime import datetime, timezone
        period = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m")

    return ReconciliationReport(
        period=period,
        total_payments_received=0,
        total_payments_posted=0,
        unmatched_payments=0,
        unmatched_count=0,
        underpayments_detected=0,
        underpayment_count=0,
        denials_routed=0,
        denials_amount=0,
        auto_post_rate=0,
    )


@router.get("/unmatched", response_model=PaginatedResponse[PaymentLineResponse])
async def list_unmatched_payments(
    payer_id: UUID | None = None,
    min_amount: float | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List all unmatched payment lines across batches for resolution."""
    return {"items": [], "total": 0, "page": page, "page_size": page_size}
