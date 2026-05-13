"""
Payment Posting API Routes
ERA/835 processing, payment matching, and reconciliation.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import date, datetime
from enum import Enum

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

    model_config = {"from_attributes": True}


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
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/batches", response_model=list[BatchResponse])
async def list_payment_batches(
    status: BatchStatus | None = None,
    payer_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    """List payment batches with filtering."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/batches/{batch_id}", response_model=BatchResponse)
async def get_payment_batch(batch_id: UUID):
    """Get payment batch details."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/batches/{batch_id}/lines", response_model=list[PaymentLineResponse])
async def get_batch_lines(
    batch_id: UUID,
    match_status: PaymentMatchStatus | None = None,
):
    """Get payment lines within a batch, optionally filtered by match status."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/batches/{batch_id}/post")
async def post_batch(batch_id: UUID, body: PostBatchRequest | None = None):
    """
    Post matched payments. If auto_only=True, only posts high-confidence matches.
    Otherwise, posts all matched payments including manual matches.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/lines/{line_id}/match")
async def manual_match(line_id: UUID, body: ManualMatchRequest):
    """Manually match an unmatched payment line to a claim."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/lines/{line_id}/dispute-underpayment")
async def dispute_underpayment(line_id: UUID, body: DisputeUnderpaymentRequest):
    """Flag an underpayment for dispute with the payer."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/reconciliation", response_model=ReconciliationReport)
async def get_reconciliation_report(
    period: str = Query(description="Period in YYYY-MM format"),
):
    """
    Monthly reconciliation report:
    - Total received vs posted
    - Unmatched payments
    - Underpayment detection
    - Auto-post success rate
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/unmatched")
async def list_unmatched_payments(
    payer_id: UUID | None = None,
    min_amount: float | None = None,
    page: int = Query(default=1, ge=1),
):
    """List all unmatched payment lines across batches for resolution."""
    raise HTTPException(status_code=501, detail="Not yet implemented")
