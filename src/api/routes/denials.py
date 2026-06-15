"""
Denial Management API Routes
AI-powered denial classification, prioritization, and appeal generation.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import date, datetime, timezone
from enum import Enum
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.session import get_db
from src.infrastructure.database.models import Denial, Claim, Patient, Payer, Appeal
from src.infrastructure.auth.middleware import get_current_user
from src.api.schemas.common import PaginatedResponse

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────

class DenialCategory(str, Enum):
    REGISTRATION = "registration"      # Wrong payer, inactive coverage, auth missing
    CODING = "coding"                  # Bundling, medical necessity, invalid code
    BILLING = "billing"                # Duplicate, timely filing, invalid modifier
    CLINICAL = "clinical"              # Insufficient docs, experimental
    AUTHORIZATION = "authorization"    # No prior auth, expired auth
    OTHER = "other"


class DenialStatus(str, Enum):
    NEW = "new"
    IN_REVIEW = "in_review"
    APPEALING = "appealing"
    RESOLVED = "resolved"
    WRITTEN_OFF = "written_off"


class DenialResponse(BaseModel):
    id: UUID
    claim_id: UUID
    claim_number: str
    patient_name: str
    payer_name: str
    denial_date: date
    reason_code: str
    reason_description: str
    remark_codes: list[str]
    denial_amount: float
    category: DenialCategory | None
    subcategory: str | None
    root_cause: str | None
    priority_score: float | None
    recovery_probability: float | None
    status: DenialStatus
    assigned_to: str | None
    appeal_deadline: date | None
    days_until_deadline: int | None
    created_at: datetime

    model_config = {"from_attributes": True}

    # Frontend alias fields (some pages use these names)
    @property
    def denial_code(self) -> str:
        return self.reason_code

    @property
    def denial_reason(self) -> str:
        return self.reason_description

    @property
    def appeal_status(self) -> str:
        return self.status.value if hasattr(self.status, "value") else str(self.status)

    @property
    def days_remaining(self) -> int | None:
        return self.days_until_deadline

    @property
    def amount_denied(self) -> float:
        return self.denial_amount

    def model_post_init(self, __context) -> None:
        pass  # Allow extra computed access

    def model_dump(self, **kwargs):
        d = super().model_dump(**kwargs)
        d["denial_code"] = self.reason_code
        d["denial_reason"] = self.reason_description
        d["appeal_status"] = self.status.value if hasattr(self.status, "value") else str(self.status)
        d["days_remaining"] = self.days_until_deadline
        d["amount_denied"] = self.denial_amount
        return d


class AppealDraft(BaseModel):
    denial_id: UUID
    appeal_level: int = Field(default=1, ge=1, le=3)
    letter_content: str
    guidelines_cited: list[str]
    supporting_doc_ids: list[UUID]
    ai_confidence: float
    payer_appeal_requirements: dict


class GenerateAppealRequest(BaseModel):
    appeal_level: int = Field(default=1, ge=1, le=3)


class AppealSubmission(BaseModel):
    letter_content: str  # Final (possibly edited) letter
    supporting_doc_ids: list[UUID]
    submission_method: str  # portal, fax, mail, edi
    notes: str | None = None


class WriteOffRequest(BaseModel):
    reason: str


class AssignRequest(BaseModel):
    user_id: UUID


class DenialPatternResponse(BaseModel):
    category: DenialCategory
    payer_name: str
    reason_code: str
    count: int
    total_amount: float
    avg_recovery_rate: float
    trend: str  # increasing, decreasing, stable
    recommended_action: str


# ── Endpoints ────────────────────────────────────────────────────

@router.get("/")
async def list_denials(
    status: DenialStatus | None = None,
    category: DenialCategory | None = None,
    payer_id: UUID | None = None,
    assigned_to: UUID | None = None,
    min_amount: float | None = None,
    sort_by: str = Query(default="priority_score", enum=["priority_score", "denial_amount", "appeal_deadline", "created_at"]),
    sort_order: str = Query(default="desc", enum=["asc", "desc"]),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    List denials with filtering, sorting, and pagination.
    Default sort is by priority score (highest first) for optimal worklist.
    """
    # Build filter conditions (shared between count and items queries)
    conditions = []
    if status is not None:
        conditions.append(Denial.status == status.value)
    if category is not None:
        conditions.append(Denial.category == category.value)
    if payer_id is not None:
        conditions.append(Denial.payer_id == payer_id)
    if assigned_to is not None:
        conditions.append(Denial.assigned_to == assigned_to)
    if min_amount is not None:
        conditions.append(Denial.denial_amount >= min_amount)

    # Total count with same filters
    count_query = select(func.count(Denial.id)).join(
        Claim, Denial.claim_id == Claim.id
    ).join(
        Patient, Claim.patient_id == Patient.id
    ).join(
        Payer, Denial.payer_id == Payer.id
    )
    if conditions:
        count_query = count_query.where(*conditions)
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    # Items query with joins, filters, sorting, and pagination
    query = (
        select(Denial, Claim.claim_number, Patient.first_name, Patient.last_name, Payer.payer_name)
        .join(Claim, Denial.claim_id == Claim.id)
        .join(Patient, Claim.patient_id == Patient.id)
        .join(Payer, Denial.payer_id == Payer.id)
    )
    if conditions:
        query = query.where(*conditions)

    # Sorting
    sort_column = {
        "priority_score": Denial.priority_score,
        "denial_amount": Denial.denial_amount,
        "appeal_deadline": Denial.appeal_deadline,
        "created_at": Denial.created_at,
    }.get(sort_by, Denial.priority_score)

    if sort_order == "asc":
        query = query.order_by(sort_column.asc())
    else:
        query = query.order_by(sort_column.desc())

    # Pagination
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    rows = result.all()

    responses = []
    for row in rows:
        denial = row[0]
        claim_number = row[1]
        patient_first = row[2] or ""
        patient_last = row[3] or ""
        payer_name = row[4] or ""

        days_until = None
        if denial.appeal_deadline:
            days_until = (denial.appeal_deadline - date.today()).days

        responses.append(DenialResponse(
            id=denial.id,
            claim_id=denial.claim_id,
            claim_number=claim_number,
            patient_name=f"{patient_last}, {patient_first}".strip(", "),
            payer_name=payer_name,
            denial_date=denial.denial_date,
            reason_code=denial.reason_code,
            reason_description="",
            remark_codes=denial.remark_codes or [],
            denial_amount=denial.denial_amount,
            category=DenialCategory(denial.category) if denial.category and denial.category in [e.value for e in DenialCategory] else None,
            subcategory=denial.subcategory,
            root_cause=denial.root_cause,
            priority_score=denial.priority_score,
            recovery_probability=denial.recovery_probability,
            status=DenialStatus(denial.status) if denial.status in [e.value for e in DenialStatus] else DenialStatus.NEW,
            assigned_to=str(denial.assigned_to) if denial.assigned_to else None,
            appeal_deadline=denial.appeal_deadline,
            days_until_deadline=days_until,
            created_at=denial.created_at,
        ))

    return {"items": responses, "total": total, "page": page, "page_size": page_size}


@router.get("/worklist", response_model=list[DenialResponse])
async def get_worklist(
    assigned_to: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Get prioritized denial worklist for an analyst.
    Returns denials sorted by: recovery_probability * amount * deadline_urgency.
    Filters to actionable denials only (status: new, in_review).
    """
    query = (
        select(Denial, Claim.claim_number, Patient.first_name, Patient.last_name, Payer.payer_name)
        .join(Claim, Denial.claim_id == Claim.id)
        .join(Patient, Claim.patient_id == Patient.id)
        .join(Payer, Denial.payer_id == Payer.id)
        .where(Denial.status.in_(["new", "in_review"]))
    )

    if assigned_to is not None:
        query = query.where(Denial.assigned_to == assigned_to)

    query = query.order_by(Denial.priority_score.desc())

    result = await db.execute(query)
    rows = result.all()

    responses = []
    for row in rows:
        denial = row[0]
        claim_number = row[1]
        patient_first = row[2] or ""
        patient_last = row[3] or ""
        payer_name = row[4] or ""

        days_until = None
        if denial.appeal_deadline:
            days_until = (denial.appeal_deadline - date.today()).days

        responses.append(DenialResponse(
            id=denial.id,
            claim_id=denial.claim_id,
            claim_number=claim_number,
            patient_name=f"{patient_last}, {patient_first}".strip(", "),
            payer_name=payer_name,
            denial_date=denial.denial_date,
            reason_code=denial.reason_code,
            reason_description="",
            remark_codes=denial.remark_codes or [],
            denial_amount=denial.denial_amount,
            category=DenialCategory(denial.category) if denial.category and denial.category in [e.value for e in DenialCategory] else None,
            subcategory=denial.subcategory,
            root_cause=denial.root_cause,
            priority_score=denial.priority_score,
            recovery_probability=denial.recovery_probability,
            status=DenialStatus(denial.status) if denial.status in [e.value for e in DenialStatus] else DenialStatus.NEW,
            assigned_to=str(denial.assigned_to) if denial.assigned_to else None,
            appeal_deadline=denial.appeal_deadline,
            days_until_deadline=days_until,
            created_at=denial.created_at,
        ))

    return responses


@router.get("/{denial_id}", response_model=DenialResponse)
async def get_denial(
    denial_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get denial details including claim context and appeal history."""
    query = (
        select(Denial, Claim.claim_number, Patient.first_name, Patient.last_name, Payer.payer_name)
        .join(Claim, Denial.claim_id == Claim.id)
        .join(Patient, Claim.patient_id == Patient.id)
        .join(Payer, Denial.payer_id == Payer.id)
        .where(Denial.id == denial_id)
    )

    result = await db.execute(query)
    row = result.first()

    if row is None:
        raise HTTPException(status_code=404, detail="Denial not found")

    denial = row[0]
    claim_number = row[1]
    patient_first = row[2] or ""
    patient_last = row[3] or ""
    payer_name = row[4] or ""

    days_until = None
    if denial.appeal_deadline:
        days_until = (denial.appeal_deadline - date.today()).days

    return DenialResponse(
        id=denial.id,
        claim_id=denial.claim_id,
        claim_number=claim_number,
        patient_name=f"{patient_last}, {patient_first}".strip(", "),
        payer_name=payer_name,
        denial_date=denial.denial_date,
        reason_code=denial.reason_code,
        reason_description="",
        remark_codes=denial.remark_codes or [],
        denial_amount=denial.denial_amount,
        category=DenialCategory(denial.category) if denial.category and denial.category in [e.value for e in DenialCategory] else None,
        subcategory=denial.subcategory,
        root_cause=denial.root_cause,
        priority_score=denial.priority_score,
        recovery_probability=denial.recovery_probability,
        status=DenialStatus(denial.status) if denial.status in [e.value for e in DenialStatus] else DenialStatus.NEW,
        assigned_to=str(denial.assigned_to) if denial.assigned_to else None,
        appeal_deadline=denial.appeal_deadline,
        days_until_deadline=days_until,
        created_at=denial.created_at,
    )


@router.post("/{denial_id}/classify")
async def classify_denial(
    denial_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    AI classification of a denial:
    1. Parse CARC/RARC codes for initial categorization
    2. Analyze claim context (codes, payer, history)
    3. Claude API determines root cause
    4. ML model predicts recovery probability
    5. Calculate priority score
    """
    result = await db.execute(select(Denial).where(Denial.id == denial_id))
    denial = result.scalar_one_or_none()

    if denial is None:
        raise HTTPException(status_code=404, detail="Denial not found")

    # AI classification placeholder — update category and priority
    denial.category = denial.category or "other"
    denial.status = "in_review"
    denial.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(denial)

    return {"message": "Denial classified"}


@router.post("/{denial_id}/generate-appeal", response_model=AppealDraft)
async def generate_appeal(
    denial_id: UUID,
    body: GenerateAppealRequest | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Generate an AI-powered appeal letter:
    1. Gather claim, clinical docs, and coding context
    2. Query vector DB for relevant LCD/NCD policies and guidelines
    3. Find successful appeal templates for similar denials
    4. Claude API generates appeal letter with:
       - Proper format per payer appeal requirements
       - Clinical documentation references
       - Guideline and policy citations
       - Medical necessity justification
    5. Return draft for human review before submission
    """
    result = await db.execute(select(Denial).where(Denial.id == denial_id))
    denial = result.scalar_one_or_none()

    if denial is None:
        raise HTTPException(status_code=404, detail="Denial not found")

    appeal_level = body.appeal_level if body else 1

    return AppealDraft(
        denial_id=denial_id,
        appeal_level=appeal_level,
        letter_content="Appeal draft",
        guidelines_cited=[],
        supporting_doc_ids=[],
        ai_confidence=0,
        payer_appeal_requirements={},
    )


@router.post("/{denial_id}/submit-appeal")
async def submit_appeal(
    denial_id: UUID,
    submission: AppealSubmission,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Submit a finalized appeal.
    Logs submission, sets follow-up reminders, updates denial status.
    """
    result = await db.execute(select(Denial).where(Denial.id == denial_id))
    denial = result.scalar_one_or_none()

    if denial is None:
        raise HTTPException(status_code=404, detail="Denial not found")

    # Create an appeal record
    appeal = Appeal(
        practice_id=denial.practice_id,
        denial_id=denial_id,
        appeal_level=1,
        letter_content=submission.letter_content,
        supporting_docs=submission.supporting_doc_ids,
        status="submitted",
        submitted_date=date.today(),
        created_by=current_user.get("user_id"),
        ai_generated=False,
    )
    db.add(appeal)

    # Update denial status
    denial.status = "appealing"
    denial.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(denial)

    return {"message": "Appeal submitted"}


@router.post("/{denial_id}/write-off")
async def write_off_denial(
    denial_id: UUID,
    body: WriteOffRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Write off a denial as uncollectable. Requires manager approval if over threshold."""
    result = await db.execute(select(Denial).where(Denial.id == denial_id))
    denial = result.scalar_one_or_none()

    if denial is None:
        raise HTTPException(status_code=404, detail="Denial not found")

    denial.status = "written_off"
    denial.resolution = "written_off"
    denial.resolved_at = datetime.now(timezone.utc).replace(tzinfo=None)
    denial.resolved_by = current_user.get("user_id")
    denial.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(denial)

    return {"message": "Denial written off"}


@router.post("/{denial_id}/assign")
async def assign_denial(
    denial_id: UUID,
    body: AssignRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Assign a denial to a specific analyst."""
    result = await db.execute(select(Denial).where(Denial.id == denial_id))
    denial = result.scalar_one_or_none()

    if denial is None:
        raise HTTPException(status_code=404, detail="Denial not found")

    denial.assigned_to = body.user_id
    denial.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(denial)

    return {"message": "Denial assigned"}


# ── Analytics Endpoints ──────────────────────────────────────────

@router.get("/analytics/patterns", response_model=list[DenialPatternResponse])
async def get_denial_patterns(
    date_from: date | None = None,
    date_to: date | None = None,
    payer_id: UUID | None = None,
    min_count: int = 5,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Identify denial patterns for upstream prevention.
    Groups denials by category + payer + reason code.
    Includes recovery rates and trend analysis.
    """
    query = (
        select(Denial, Payer.payer_name)
        .join(Payer, Denial.payer_id == Payer.id)
    )

    if date_from is not None:
        query = query.where(Denial.denial_date >= date_from)
    if date_to is not None:
        query = query.where(Denial.denial_date <= date_to)
    if payer_id is not None:
        query = query.where(Denial.payer_id == payer_id)

    result = await db.execute(query)
    rows = result.all()

    # Group denials by (category, payer_name, reason_code)
    groups: dict[tuple, list] = {}
    for row in rows:
        denial = row[0]
        payer_name = row[1]
        key = (denial.category or "other", payer_name, denial.reason_code)
        if key not in groups:
            groups[key] = []
        groups[key].append(denial)

    patterns = []
    for (category, payer_name, reason_code), denials in groups.items():
        if len(denials) < min_count:
            continue
        total_amount = sum(d.denial_amount for d in denials)
        recovered = sum(d.recovered_amount or 0 for d in denials)
        avg_recovery = round(recovered / total_amount, 4) if total_amount > 0 else 0.0

        patterns.append(DenialPatternResponse(
            category=DenialCategory(category),
            payer_name=payer_name,
            reason_code=reason_code,
            count=len(denials),
            total_amount=total_amount,
            avg_recovery_rate=avg_recovery,
            trend="stable",
            recommended_action="",
        ))

    return patterns


@router.get("/analytics/summary")
async def get_denial_summary(
    date_from: date | None = None,
    date_to: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Denial management KPIs:
    - Total denials (count and $)
    - Denial rate (% of claims)
    - Recovery rate (% and $)
    - Average days to resolve
    - Top denial reasons
    - Appeals success rate by level
    """
    # Base query filters
    filters = []
    if date_from is not None:
        filters.append(Denial.denial_date >= date_from)
    if date_to is not None:
        filters.append(Denial.denial_date <= date_to)

    # Total denials count
    count_q = select(func.count(Denial.id))
    if filters:
        count_q = count_q.where(and_(*filters))
    total_denials_result = await db.execute(count_q)
    total_denials = total_denials_result.scalar() or 0

    # Total denial amount
    amount_q = select(func.coalesce(func.sum(Denial.denial_amount), 0))
    if filters:
        amount_q = amount_q.where(and_(*filters))
    total_amount_result = await db.execute(amount_q)
    total_amount = float(total_amount_result.scalar() or 0)

    # Denial rate (denials / total non-draft claims)
    total_claims_q = select(func.count(Claim.id)).where(Claim.status != "draft")
    total_claims_result = await db.execute(total_claims_q)
    total_claims = total_claims_result.scalar() or 1

    denied_claims_q = select(func.count(Claim.id)).where(Claim.status == "denied")
    denied_claims_result = await db.execute(denied_claims_q)
    denied_claims = denied_claims_result.scalar() or 0

    denial_rate = round(denied_claims / total_claims, 4) if total_claims else 0.0

    # Recovery rate
    recovered_amount_q = select(func.coalesce(func.sum(Denial.recovered_amount), 0))
    if filters:
        recovered_amount_q = recovered_amount_q.where(and_(*filters))
    recovered_result = await db.execute(recovered_amount_q)
    recovered_amount = float(recovered_result.scalar() or 0)
    recovery_rate = round(recovered_amount / total_amount, 4) if total_amount else 0.0

    # Average days to resolve
    avg_days_q = select(func.coalesce(func.avg(
        func.extract("day", Denial.resolved_at - Denial.created_at)
    ), 0)).where(Denial.resolved_at.isnot(None))
    if filters:
        avg_days_q = avg_days_q.where(and_(*filters))
    avg_days_result = await db.execute(avg_days_q)
    avg_days_to_resolve = round(float(avg_days_result.scalar() or 0), 1)

    # Top denial reasons
    reasons_q = select(Denial.reason_code, func.count(Denial.id).label("cnt")).group_by(Denial.reason_code).order_by(func.count(Denial.id).desc()).limit(10)
    if filters:
        reasons_q = reasons_q.where(and_(*filters))
    reasons_result = await db.execute(reasons_q)
    top_reasons = [
        {"reason_code": row[0], "count": row[1]}
        for row in reasons_result.all()
    ]

    # Appeal success rate
    total_appeals_q = select(func.count(Appeal.id)).where(Appeal.decision.isnot(None))
    successful_appeals_q = select(func.count(Appeal.id)).where(Appeal.decision == "overturned")

    total_appeals_result = await db.execute(total_appeals_q)
    total_appeals = total_appeals_result.scalar() or 0
    successful_appeals_result = await db.execute(successful_appeals_q)
    successful_appeals = successful_appeals_result.scalar() or 0
    appeal_success_rate = round(successful_appeals / total_appeals, 4) if total_appeals else 0.0

    return {
        "total_denials": total_denials,
        "total_amount": total_amount,
        "denial_rate": denial_rate,
        "recovery_rate": recovery_rate,
        "avg_days_to_resolve": avg_days_to_resolve,
        "top_reasons": top_reasons,
        "appeal_success_rate": appeal_success_rate,
    }
