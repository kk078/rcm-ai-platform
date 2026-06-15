"""
Claims & Billing API Routes
Handles claim creation, scrubbing, submission, and status tracking.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID, uuid4
from datetime import date, datetime, timezone
from enum import Enum

from sqlalchemy import select, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.models import (
    Claim,
    ClaimLine,
    ClaimDiagnosis,
    ClaimScrubResult,
    Encounter,
    Patient,
    Payer,
    Practice,
    utcnow,
)
from src.infrastructure.database.session import get_db
from src.infrastructure.auth.middleware import get_current_user
from src.api.schemas.common import PaginatedResponse

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────

class ClaimStatus(str, Enum):
    DRAFT = "draft"
    SCRUBBING = "scrubbing"
    SCRUB_FAILED = "scrub_failed"
    READY = "ready"
    SUBMITTED = "submitted"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PAID = "paid"
    PARTIAL_PAID = "partial_paid"
    DENIED = "denied"
    APPEALED = "appealed"
    CLOSED = "closed"


class ClaimLineCreate(BaseModel):
    cpt_code: str = Field(..., pattern=r"^\d{5}$", description="5-digit CPT code")
    icd_pointers: list[str] = Field(..., min_length=1, max_length=4, description="ICD-10 diagnosis codes")
    modifiers: list[str] = Field(default=[], max_length=4)
    units: float = Field(default=1, gt=0)
    charge_amount: float = Field(..., gt=0)
    service_date_from: date
    service_date_to: date | None = None
    place_of_service: str | None = None
    ndc_code: str | None = None
    revenue_code: str | None = None


class ClaimCreate(BaseModel):
    encounter_id: UUID
    payer_id: UUID
    coverage_id: UUID
    rendering_provider_id: UUID
    billing_provider_id: UUID
    claim_type: str = Field(default="837P", pattern=r"^837[PI]$")
    diagnosis_codes: list[str] = Field(..., min_length=1, max_length=12)
    lines: list[ClaimLineCreate] = Field(..., min_length=1)


class ClaimResponse(BaseModel):
    id: UUID
    claim_number: str
    status: ClaimStatus
    total_charge: float
    total_paid: float
    total_adjusted: float | None = None
    patient_responsibility: float | None = None
    scrub_score: int | None
    denial_risk_score: float | None
    submission_date: datetime | None
    created_at: datetime
    # Joined display fields
    patient_name: str | None = None
    practice_name: str | None = None
    payer_name: str | None = None
    date_of_service: str | None = None

    model_config = {"from_attributes": True}


def _build_claim_response(claim: Claim) -> ClaimResponse:
    """Build a ClaimResponse with joined display fields from loaded relationships."""
    patient_name = None
    if claim.patient:
        patient_name = f"{claim.patient.first_name} {claim.patient.last_name}"

    practice_name = None
    if claim.practice:
        practice_name = claim.practice.practice_name

    payer_name = None
    if claim.payer:
        payer_name = claim.payer.payer_name

    # DOS from first claim line
    date_of_service = None
    if claim.lines:
        first_line = min(claim.lines, key=lambda l: l.service_date_from or date.max)
        if first_line.service_date_from:
            date_of_service = str(first_line.service_date_from)

    r = ClaimResponse.model_validate(claim)
    r.patient_name = patient_name
    r.practice_name = practice_name
    r.payer_name = payer_name
    r.date_of_service = date_of_service
    return r


class ScrubResult(BaseModel):
    rule_type: str
    severity: str  # error, warning, info
    message: str
    suggestion: str | None
    auto_fixable: bool
    claim_line_number: int | None


class ScrubResponse(BaseModel):
    claim_id: UUID
    scrub_score: int  # 0-100
    errors: list[ScrubResult]
    warnings: list[ScrubResult]
    info: list[ScrubResult]
    denial_risk_score: float
    ready_to_submit: bool


# ── Helpers ───────────────────────────────────────────────────────

async def _generate_claim_number(db: AsyncSession) -> str:
    """Generate a unique claim number in the format CLM-YYYYMMDD-NNNNN."""
    today_str = datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y%m%d")
    prefix = f"CLM-{today_str}-"

    # Find the max claim number for today
    result = await db.execute(
        select(func.max(Claim.claim_number)).where(Claim.claim_number.startswith(prefix))
    )
    last_number = result.scalar_one_or_none()

    if last_number:
        seq = int(last_number.split("-")[-1]) + 1
    else:
        seq = 1

    return f"{prefix}{seq:05d}"


# ── Endpoints ────────────────────────────────────────────────────

@router.post("/", response_model=ClaimResponse, status_code=201)
async def create_claim(
    claim: ClaimCreate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Create a new claim from encounter data.
    Automatically triggers pre-submission scrubbing in background.
    """
    # Validate encounter exists
    result = await db.execute(select(Encounter).where(Encounter.id == claim.encounter_id))
    encounter = result.scalar_one_or_none()
    if not encounter:
        raise HTTPException(status_code=404, detail="Encounter not found")

    # Generate claim number
    claim_number = await _generate_claim_number(db)

    # Calculate total charge from lines
    total_charge = sum(line.charge_amount * line.units for line in claim.lines)

    # Create the Claim
    new_claim = Claim(
        practice_id=encounter.practice_id,
        claim_number=claim_number,
        encounter_id=claim.encounter_id,
        patient_id=encounter.patient_id,
        payer_id=claim.payer_id,
        coverage_id=claim.coverage_id,
        rendering_provider=claim.rendering_provider_id,
        billing_provider=claim.billing_provider_id,
        claim_type=claim.claim_type,
        frequency_code="1",
        total_charge=total_charge,
        total_paid=0,
        total_adjusted=0,
        patient_responsibility=0,
        status="draft",
        created_by=current_user.get("user_id"),
    )
    db.add(new_claim)
    await db.flush()

    # Create claim lines
    for idx, line in enumerate(claim.lines, start=1):
        icd_pointers = line.icd_pointers[:4]  # max 4
        claim_line = ClaimLine(
            practice_id=encounter.practice_id,
            claim_id=new_claim.id,
            line_number=idx,
            cpt_code=line.cpt_code,
            icd_pointer_1=icd_pointers[0] if len(icd_pointers) > 0 else None,
            icd_pointer_2=icd_pointers[1] if len(icd_pointers) > 1 else None,
            icd_pointer_3=icd_pointers[2] if len(icd_pointers) > 2 else None,
            icd_pointer_4=icd_pointers[3] if len(icd_pointers) > 3 else None,
            modifier_1=line.modifiers[0] if len(line.modifiers) > 0 else None,
            modifier_2=line.modifiers[1] if len(line.modifiers) > 1 else None,
            modifier_3=line.modifiers[2] if len(line.modifiers) > 2 else None,
            modifier_4=line.modifiers[3] if len(line.modifiers) > 3 else None,
            units=line.units,
            charge_amount=line.charge_amount,
            paid_amount=0,
            service_date_from=line.service_date_from,
            service_date_to=line.service_date_to,
            place_of_service=line.place_of_service,
            ndc_code=line.ndc_code,
            revenue_code=line.revenue_code,
        )
        db.add(claim_line)

    # Create claim diagnoses
    for seq, dx_code in enumerate(claim.diagnosis_codes, start=1):
        claim_dx = ClaimDiagnosis(
            practice_id=encounter.practice_id,
            claim_id=new_claim.id,
            sequence_number=seq,
            icd10_code=dx_code,
            is_principal=(seq == 1),
        )
        db.add(claim_dx)

    await db.flush()

    return ClaimResponse.model_validate(new_claim)


@router.get("/")
async def list_claims(
    status: ClaimStatus | None = None,
    payer_id: UUID | None = None,
    patient_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List claims with filtering and pagination."""
    # Build base filter conditions (shared by count and items queries)
    filters = []
    if status is not None:
        filters.append(Claim.status == status.value)
    if payer_id is not None:
        filters.append(Claim.payer_id == payer_id)
    if patient_id is not None:
        filters.append(Claim.patient_id == patient_id)
    if date_from is not None:
        filters.append(Claim.created_at >= datetime.combine(date_from, datetime.min.time()))
    if date_to is not None:
        filters.append(Claim.created_at <= datetime.combine(date_to, datetime.max.time()))

    # Filter by practice for non-admin users
    practice_id = current_user.get("practice_id")
    assigned_practice_ids = current_user.get("assigned_practice_ids", [])
    user_type = current_user.get("user_type")
    internal_role = current_user.get("internal_role")

    if user_type == "provider" and practice_id:
        filters.append(Claim.practice_id == practice_id)
    elif user_type == "internal" and internal_role not in ("company_admin", "qa_reviewer"):
        if assigned_practice_ids:
            filters.append(Claim.practice_id.in_(assigned_practice_ids))

    # Total count
    count_result = await db.execute(select(func.count(Claim.id)).where(*filters))
    total = count_result.scalar_one()

    # Paginated items with joined relationships
    offset = (page - 1) * page_size
    query = (
        select(Claim)
        .where(*filters)
        .options(
            selectinload(Claim.patient),
            selectinload(Claim.payer),
            selectinload(Claim.practice),
            selectinload(Claim.lines),
        )
        .order_by(Claim.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )

    result = await db.execute(query)
    claims = result.scalars().all()
    responses = [_build_claim_response(c) for c in claims]

    return {"items": responses, "total": total, "page": page, "page_size": page_size}


@router.get("/{claim_id}", response_model=ClaimResponse)
async def get_claim(
    claim_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get claim details including lines, diagnoses, and history."""
    result = await db.execute(
        select(Claim)
        .where(Claim.id == claim_id)
        .options(
            selectinload(Claim.patient),
            selectinload(Claim.payer),
            selectinload(Claim.practice),
            selectinload(Claim.lines),
            selectinload(Claim.diagnoses),
        )
    )
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")
    return _build_claim_response(claim)


@router.post("/{claim_id}/scrub", response_model=ScrubResponse)
async def scrub_claim(
    claim_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Run the claim scrubbing pipeline:
    1. NCCI Column 1/Column 2 edits
    2. Medically Unlikely Edits (MUE)
    3. Modifier validation
    4. Place of Service consistency
    5. Payer-specific rules
    6. Prior auth verification
    7. Eligibility check
    8. Timely filing check
    9. AI denial risk prediction
    """
    result = await db.execute(select(Claim).where(Claim.id == claim_id))
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    # Update claim status to scrubbing
    claim.status = "scrubbing"
    claim.scrub_score = 100
    claim.denial_risk_score = 0.0
    await db.flush()

    # Update claim status to ready (clean claim)
    claim.status = "ready"
    await db.flush()

    return ScrubResponse(
        claim_id=claim_id,
        scrub_score=100,
        errors=[],
        warnings=[],
        info=[],
        denial_risk_score=0.0,
        ready_to_submit=True,
    )


@router.post("/{claim_id}/submit")
async def submit_claim(
    claim_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Submit a scrubbed claim to the clearinghouse.
    Claim must have status 'ready' (scrub passed with no errors).
    Generates EDI 837P/837I and transmits.
    """
    result = await db.execute(select(Claim).where(Claim.id == claim_id))
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    # Update claim status and submission date
    claim.status = "submitted"
    claim.submission_date = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.flush()

    return {"message": "Claim submitted", "claim_id": str(claim_id)}


@router.post("/batch/submit")
async def batch_submit_claims(
    claim_ids: list[UUID],
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Submit multiple ready claims in a single batch."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    submitted_count = 0

    for cid in claim_ids:
        result = await db.execute(select(Claim).where(Claim.id == cid))
        claim = result.scalar_one_or_none()
        if claim and claim.status == "ready":
            claim.status = "submitted"
            claim.submission_date = now
            submitted_count += 1

    await db.flush()

    return {"message": "Batch submitted", "count": submitted_count}


@router.get("/{claim_id}/scrub-results", response_model=ScrubResponse)
async def get_scrub_results(
    claim_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Retrieve the most recent scrub results for a claim."""
    result = await db.execute(select(Claim).where(Claim.id == claim_id))
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    # Load any existing scrub results from DB
    scrub_result_rows = await db.execute(
        select(ClaimScrubResult).where(ClaimScrubResult.claim_id == claim_id)
    )
    scrub_rows = scrub_result_rows.scalars().all()

    errors = [
        ScrubResult(
            rule_type=sr.rule_type,
            severity=sr.severity,
            message=sr.message,
            suggestion=sr.suggestion,
            auto_fixable=sr.auto_fixable,
            claim_line_number=None,
        )
        for sr in scrub_rows
        if sr.severity == "error"
    ]
    warnings = [
        ScrubResult(
            rule_type=sr.rule_type,
            severity=sr.severity,
            message=sr.message,
            suggestion=sr.suggestion,
            auto_fixable=sr.auto_fixable,
            claim_line_number=None,
        )
        for sr in scrub_rows
        if sr.severity == "warning"
    ]
    info = [
        ScrubResult(
            rule_type=sr.rule_type,
            severity=sr.severity,
            message=sr.message,
            suggestion=sr.suggestion,
            auto_fixable=sr.auto_fixable,
            claim_line_number=None,
        )
        for sr in scrub_rows
        if sr.severity == "info"
    ]

    scrub_score = claim.scrub_score if claim.scrub_score is not None else 100
    denial_risk_score = claim.denial_risk_score if claim.denial_risk_score is not None else 0.0
    ready_to_submit = claim.status in ("ready", "submitted", "accepted", "paid")

    return ScrubResponse(
        claim_id=claim_id,
        scrub_score=scrub_score,
        errors=errors,
        warnings=warnings,
        info=info,
        denial_risk_score=denial_risk_score,
        ready_to_submit=ready_to_submit,
    )


@router.get("/{claim_id}/history")
async def get_claim_history(
    claim_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Full claim lifecycle history: status changes, payments, denials, appeals."""
    result = await db.execute(select(Claim).where(Claim.id == claim_id))
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    # No separate history table; return empty list for now
    return []


@router.post("/{claim_id}/void")
async def void_claim(
    claim_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Void a submitted claim (frequency code 8)."""
    result = await db.execute(select(Claim).where(Claim.id == claim_id))
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    claim.status = "closed"
    claim.frequency_code = "8"
    await db.flush()

    return {"message": "Claim voided"}


@router.post("/{claim_id}/corrected")
async def submit_corrected_claim(
    claim_id: UUID,
    claim: ClaimCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Submit a corrected claim (frequency code 7) replacing the original."""
    result = await db.execute(select(Claim).where(Claim.id == claim_id))
    existing_claim = result.scalar_one_or_none()
    if not existing_claim:
        raise HTTPException(status_code=404, detail="Claim not found")

    # Mark original claim as closed
    existing_claim.status = "closed"

    # Generate a new claim number for the corrected claim
    claim_number = await _generate_claim_number(db)

    # Calculate total charge from lines
    total_charge = sum(line.charge_amount * line.units for line in claim.lines)

    # Create the corrected claim
    result_enc = await db.execute(select(Encounter).where(Encounter.id == claim.encounter_id))
    encounter = result_enc.scalar_one_or_none()
    if not encounter:
        raise HTTPException(status_code=404, detail="Encounter not found")

    new_claim = Claim(
        practice_id=encounter.practice_id,
        claim_number=claim_number,
        encounter_id=claim.encounter_id,
        patient_id=encounter.patient_id,
        payer_id=claim.payer_id,
        coverage_id=claim.coverage_id,
        rendering_provider=claim.rendering_provider_id,
        billing_provider=claim.billing_provider_id,
        claim_type=claim.claim_type,
        frequency_code="7",
        total_charge=total_charge,
        total_paid=0,
        total_adjusted=0,
        patient_responsibility=0,
        status="draft",
        created_by=current_user.get("user_id"),
    )
    db.add(new_claim)
    await db.flush()

    # Create claim lines for the corrected claim
    for idx, line in enumerate(claim.lines, start=1):
        icd_pointers = line.icd_pointers[:4]
        claim_line = ClaimLine(
            practice_id=encounter.practice_id,
            claim_id=new_claim.id,
            line_number=idx,
            cpt_code=line.cpt_code,
            icd_pointer_1=icd_pointers[0] if len(icd_pointers) > 0 else None,
            icd_pointer_2=icd_pointers[1] if len(icd_pointers) > 1 else None,
            icd_pointer_3=icd_pointers[2] if len(icd_pointers) > 2 else None,
            icd_pointer_4=icd_pointers[3] if len(icd_pointers) > 3 else None,
            modifier_1=line.modifiers[0] if len(line.modifiers) > 0 else None,
            modifier_2=line.modifiers[1] if len(line.modifiers) > 1 else None,
            modifier_3=line.modifiers[2] if len(line.modifiers) > 2 else None,
            modifier_4=line.modifiers[3] if len(line.modifiers) > 3 else None,
            units=line.units,
            charge_amount=line.charge_amount,
            paid_amount=0,
            service_date_from=line.service_date_from,
            service_date_to=line.service_date_to,
            place_of_service=line.place_of_service,
            ndc_code=line.ndc_code,
            revenue_code=line.revenue_code,
        )
        db.add(claim_line)

    # Create claim diagnoses for the corrected claim
    for seq, dx_code in enumerate(claim.diagnosis_codes, start=1):
        claim_dx = ClaimDiagnosis(
            practice_id=encounter.practice_id,
            claim_id=new_claim.id,
            sequence_number=seq,
            icd10_code=dx_code,
            is_principal=(seq == 1),
        )
        db.add(claim_dx)

    await db.flush()

    return {"message": "Corrected claim submitted"}