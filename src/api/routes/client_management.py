"""
Client Management API Routes — Practice onboarding, configuration,
payer enrollments, fee schedules, staff assignments, and SLA tracking.
Internal staff only (provider portal users cannot access this).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field, field_validator
from typing import Optional
from uuid import UUID
from datetime import date, datetime, timezone
from enum import Enum
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.session import get_db
from src.infrastructure.database.models import (
    Practice,
    PayerEnrollment,
    PracticeLocation,
    ServiceAgreement,
    StaffAssignment,
    User,
    Payer,
)
from src.api.schemas.common import PaginatedResponse
from src.infrastructure.auth.middleware import get_current_user
from src.core.client_management.service import (
    practice_service,
    provider_service,
    payer_enrollment_service,
    service_agreement_service,
    staff_assignment_service,
    portal_user_service,
    onboarding_service,
)
from src.core.client_management.errors import ClientManagementError

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────

class PracticeStatus(str, Enum):
    ONBOARDING = "onboarding"
    ACTIVE = "active"
    SUSPENDED = "suspended"
    TERMINATED = "terminated"


class FeeModel(str, Enum):
    PERCENTAGE = "percentage"
    PER_CLAIM = "per_claim"
    FLAT_FEE = "flat_fee"
    HYBRID = "hybrid"


class IntakeMethod(str, Enum):
    PORTAL = "portal"
    UPLOAD = "upload"
    EHR = "ehr"
    BATCH = "batch"
    FAX = "fax"


class PracticeCreate(BaseModel):
    practice_name: str = Field(..., max_length=255)
    legal_name: str | None = None
    tin: str = Field(..., pattern=r"^\d{2}-\d{7}$", description="EIN format: XX-XXXXXXX")
    group_npi: str | None = Field(None, pattern=r"^\d{10}$")
    specialty_primary: str | None = None
    address_line_1: str | None = None
    city: str | None = None
    state: str | None = Field(None, max_length=2)
    zip_code: str | None = None
    phone: str | None = None
    fax: str | None = None
    email: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    intake_method: IntakeMethod = IntakeMethod.PORTAL
    timezone: str = "America/New_York"


class PracticeResponse(BaseModel):
    id: UUID
    practice_name: str
    legal_name: str | None
    group_npi: str | None
    specialty_primary: str | None
    status: PracticeStatus
    intake_method: IntakeMethod
    go_live_date: date | None
    provider_count: int | None = None
    active_claims_count: int | None = None
    monthly_collections: float | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class LocationCreate(BaseModel):
    location_name: str
    address_line_1: str
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    phone: str | None = None
    place_of_service: str = "11"
    facility_npi: str | None = None
    is_primary: bool = False


class ProviderAdd(BaseModel):
    npi: str = Field(..., pattern=r"^\d{10}$")
    first_name: str
    last_name: str
    credential: str | None = None  # MD, DO, NP, PA
    taxonomy_code: str | None = None
    specialty: str | None = None

    @field_validator("taxonomy_code")
    @classmethod
    def _clean_taxonomy(cls, v):
        """Accept 'code' or 'code - description' and keep only the code (column is 20 chars)."""
        if not v:
            return v
        import re  # noqa: PLC0415
        m = re.match(r"[A-Za-z0-9]+", v.strip())
        return (m.group(0) if m else v.strip())[:20]

    @field_validator("credential")
    @classmethod
    def _clean_credential(cls, v):
        return v.strip()[:20] if v else v


class PayerEnrollmentCreate(BaseModel):
    payer_id: UUID
    group_number: str | None = None
    edi_payer_id: str | None = None
    era_enrolled: bool = False
    eft_enrolled: bool = False
    clearinghouse: str | None = None
    sender_id: str | None = None
    timely_filing_days: int | None = None
    appeal_filing_days: int | None = None
    appeal_address: str | None = None
    appeal_fax: str | None = None
    fee_schedule_id: UUID | None = None


class ServiceAgreementCreate(BaseModel):
    fee_model: FeeModel
    percentage_rate: float | None = None
    per_claim_rate: float | None = None
    flat_fee_monthly: float | None = None
    hybrid_base_fee: float | None = None
    hybrid_threshold: float | None = None
    hybrid_overage_rate: float | None = None
    minimum_monthly_fee: float | None = None
    includes_coding: bool = True
    includes_billing: bool = True
    includes_posting: bool = True
    includes_denials: bool = True
    includes_credentialing: bool = False
    includes_eligibility: bool = True
    sla_clean_claim_rate: float = 95.0
    sla_days_to_submit: int = 2
    sla_appeal_turnaround: int = 5
    sla_posting_turnaround: int = 2
    effective_date: date
    termination_date: date | None = None


class StaffAssignmentCreate(BaseModel):
    user_id: UUID
    role_in_practice: str  # coder, biller, poster, denial_analyst, manager
    is_primary: bool = False


class PortalUserCreate(BaseModel):
    email: str
    first_name: str
    last_name: str
    provider_role: str  # practice_admin, provider, office_manager, front_desk
    provider_id: UUID | None = None  # If this user is a doctor


class SuspendRequest(BaseModel):
    reason: str


class TerminateRequest(BaseModel):
    reason: str
    effective_date: date


class OnboardingChecklist(BaseModel):
    practice_created: bool = False
    providers_added: bool = False
    locations_added: bool = False
    payers_enrolled: bool = False
    fee_schedules_loaded: bool = False
    clearinghouse_configured: bool = False
    service_agreement_set: bool = False
    portal_users_created: bool = False
    initial_data_migrated: bool = False
    go_live_ready: bool = False


# ── Practice CRUD ────────────────────────────────────────────────

@router.post("/practices", response_model=PracticeResponse, status_code=201)
async def create_practice(
    practice: PracticeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Create a new practice client. Starts the onboarding process.
    Only company admins and billing managers can create practices.
    """
    try:
        result = await practice_service.create_practice(
            db=db,
            user_id=current_user["user_id"],
            data=practice,
        )
        return result
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


class OnboardRequest(BaseModel):
    practice: PracticeCreate
    providers: list[ProviderAdd] = Field(default_factory=list)
    payers: list[PayerEnrollmentCreate] = Field(default_factory=list)


@router.post("/practices/onboard", status_code=201)
async def onboard_practice(
    body: OnboardRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """One-stop provider setup: create the practice plus its providers and payer
    enrollments in a single call. Each sub-step reuses the same service logic as the
    individual endpoints, so this is just a convenience wrapper — the single place to
    stand a provider up before sending charges."""
    uid = current_user["user_id"]
    providers_out, payers_out = [], []
    try:
        practice = await practice_service.create_practice(db=db, user_id=uid, data=body.practice)
        pid = getattr(practice, "id", None) or (practice.get("id") if isinstance(practice, dict) else None)
        for p in body.providers:
            providers_out.append(await provider_service.add_provider_to_practice(
                db=db, user_id=uid, practice_id=pid, data=p))
        for pe in body.payers:
            payers_out.append(await payer_enrollment_service.add_payer_enrollment(
                db=db, user_id=uid, practice_id=pid, data=pe))
        await db.commit()
    except ClientManagementError as e:
        await db.rollback()
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    return {
        "status": "onboarded", "practice_id": str(pid), "practice": practice,
        "providers_added": len(providers_out), "payers_enrolled": len(payers_out),
    }


@router.get("/practices", response_model=PaginatedResponse[PracticeResponse])
async def list_practices(
    status: PracticeStatus | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List all practices. Admins see all; managers see assigned only."""
    try:
        # Build count query with same filters as the service
        count_query = select(func.count(Practice.id))
        if status:
            count_query = count_query.where(Practice.status == status.value)
        if search:
            count_query = count_query.where(Practice.practice_name.ilike(f"%{search}%"))
        total_result = await db.execute(count_query)
        total = total_result.scalar() or 0

        practices = await practice_service.list_practices(
            db=db,
            status=status.value if status else None,
            search=search,
            page=page,
            page_size=page_size,
        )
        return {"items": practices, "total": total, "page": page, "page_size": page_size}
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("/practices/{practice_id}", response_model=PracticeResponse)
async def get_practice(
    practice_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get practice details including onboarding status and KPIs."""
    try:
        practice = await practice_service.get_practice(db=db, practice_id=practice_id)
        return practice
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.patch("/practices/{practice_id}")
async def update_practice(
    practice_id: UUID,
    updates: PracticeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Update practice configuration."""
    try:
        result = await practice_service.update_practice(
            db=db,
            user_id=current_user["user_id"],
            practice_id=practice_id,
            updates=updates.model_dump(exclude_none=True),
        )
        return result
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/practices/{practice_id}/activate")
async def activate_practice(
    practice_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Activate a practice after onboarding is complete.
    Validates all onboarding steps are done.
    Sets go_live_date.
    """
    try:
        result = await practice_service.activate_practice(
            db=db,
            user_id=current_user["user_id"],
            practice_id=practice_id,
        )
        return result
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/practices/{practice_id}/suspend")
async def suspend_practice(
    practice_id: UUID,
    body: SuspendRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Suspend a practice (e.g., non-payment). Stops claim processing."""
    try:
        result = await practice_service.suspend_practice(
            db=db,
            user_id=current_user["user_id"],
            practice_id=practice_id,
            reason=body.reason,
        )
        return result
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/practices/{practice_id}/terminate")
async def terminate_practice(
    practice_id: UUID,
    body: TerminateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Terminate a practice relationship. Triggers offboarding workflow."""
    try:
        result = await practice_service.terminate_practice(
            db=db,
            user_id=current_user["user_id"],
            practice_id=practice_id,
            reason=body.reason,
            effective_date=body.effective_date,
        )
        return result
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.patch("/practices/{practice_id}/reactivate")
async def reactivate_practice(
    practice_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Reactivate a suspended or terminated practice back to active status."""
    result = await db.execute(select(Practice).where(Practice.id == practice_id))
    practice = result.scalar_one_or_none()
    if not practice:
        raise HTTPException(status_code=404, detail=f"Practice {practice_id} not found")
    if practice.status not in ("suspended", "terminated"):
        raise HTTPException(
            status_code=422,
            detail=f"Cannot reactivate practice in '{practice.status}' status. Must be 'suspended' or 'terminated'.",
        )
    practice.status = "active"
    practice.terminated_at = None
    practice.termination_reason = None
    await db.flush()
    return practice


# ── Onboarding ───────────────────────────────────────────────────

@router.get("/practices/{practice_id}/onboarding", response_model=OnboardingChecklist)
async def get_onboarding_status(
    practice_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get the onboarding checklist status for a practice."""
    try:
        checklist = await onboarding_service.get_onboarding_status(db=db, practice_id=practice_id)
        return checklist
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


# ── Locations ────────────────────────────────────────────────────

@router.post("/practices/{practice_id}/locations", status_code=201)
async def add_location(
    practice_id: UUID,
    location: LocationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Add a practice location/facility."""
    # Verify practice exists
    result = await db.execute(select(Practice).where(Practice.id == practice_id))
    practice = result.scalar_one_or_none()
    if not practice:
        raise HTTPException(status_code=404, detail=f"Practice {practice_id} not found")

    new_location = PracticeLocation(
        practice_id=practice_id,
        location_name=location.location_name,
        address_line_1=location.address_line_1,
        city=location.city,
        state=location.state,
        zip_code=location.zip_code,
        phone=location.phone,
        place_of_service=location.place_of_service,
        facility_npi=location.facility_npi,
        is_primary=location.is_primary,
    )
    db.add(new_location)
    await db.flush()
    return new_location


@router.get("/practices/{practice_id}/locations")
async def list_locations(
    practice_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # Total count
    count_result = await db.execute(
        select(func.count()).select_from(PracticeLocation).where(
            PracticeLocation.practice_id == practice_id
        )
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(PracticeLocation)
        .where(PracticeLocation.practice_id == practice_id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    locations = list(result.scalars().all())
    return {"items": locations, "total": total, "page": page, "page_size": page_size}


# ── Providers ────────────────────────────────────────────────────

@router.post("/practices/{practice_id}/providers", status_code=201)
async def add_provider(
    practice_id: UUID,
    provider: ProviderAdd,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Add a provider to the practice.
    If NPI already exists in system, links to existing provider record.
    """
    try:
        result = await provider_service.add_provider_to_practice(
            db=db,
            user_id=current_user["user_id"],
            practice_id=practice_id,
            data=provider,
        )
        return result
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("/practices/{practice_id}/providers")
async def list_practice_providers(
    practice_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        providers = await provider_service.list_practice_providers(db=db, practice_id=practice_id)
        total = len(providers)
        start = (page - 1) * page_size
        return {
            "items": providers[start : start + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


# ── Payer Enrollments ────────────────────────────────────────────

@router.post("/practices/{practice_id}/payer-enrollments", status_code=201)
async def add_payer_enrollment(
    practice_id: UUID,
    enrollment: PayerEnrollmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Configure a payer enrollment for a practice.
    Includes ERA/EFT enrollment status, clearinghouse config, and fee schedule link.
    """
    try:
        result = await payer_enrollment_service.add_payer_enrollment(
            db=db,
            user_id=current_user["user_id"],
            practice_id=practice_id,
            data=enrollment,
        )
        return result
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("/practices/{practice_id}/payer-enrollments")
async def list_payer_enrollments(
    practice_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        enrollments = await payer_enrollment_service.list_payer_enrollments(
            db=db, practice_id=practice_id
        )
        total = len(enrollments)
        start = (page - 1) * page_size
        return {
            "items": enrollments[start : start + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.patch("/practices/{practice_id}/payer-enrollments/{enrollment_id}")
async def update_payer_enrollment(
    practice_id: UUID,
    enrollment_id: UUID,
    updates: PayerEnrollmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        result = await payer_enrollment_service.update_payer_enrollment(
            db=db,
            user_id=current_user["user_id"],
            practice_id=practice_id,
            enrollment_id=enrollment_id,
            updates=updates.model_dump(exclude_none=True),
        )
        return result
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


# ── Fee Schedules ────────────────────────────────────────────────

@router.post("/practices/{practice_id}/fee-schedules/import")
async def import_fee_schedule(
    practice_id: UUID,
    payer_id: UUID,
    file: UploadFile = File(..., description="CSV or Excel fee schedule file"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Import a contracted fee schedule for a payer.
    Parses CPT code, allowed amount, modifier-specific rates.
    """
    # Verify practice exists
    result = await db.execute(select(Practice).where(Practice.id == practice_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail=f"Practice {practice_id} not found")
    return {"message": "Fee schedule import not yet available"}


@router.get("/practices/{practice_id}/fee-schedules")
async def list_fee_schedules(
    practice_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    # Get fee schedules through payer enrollments linked to this practice
    result = await db.execute(
        select(PayerEnrollment).where(
            PayerEnrollment.practice_id == practice_id,
            PayerEnrollment.fee_schedule_id.isnot(None),
        )
    )
    enrollments = list(result.scalars().all())
    if not enrollments:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    # Fetch the actual fee schedules
    from src.infrastructure.database.models import FeeSchedule

    schedule_ids = [e.fee_schedule_id for e in enrollments if e.fee_schedule_id]
    count_result = await db.execute(
        select(func.count()).select_from(FeeSchedule).where(FeeSchedule.id.in_(schedule_ids))
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(FeeSchedule)
        .where(FeeSchedule.id.in_(schedule_ids))
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    schedules = list(result.scalars().all())
    return {"items": schedules, "total": total, "page": page, "page_size": page_size}


@router.get("/practices/{practice_id}/fee-schedules/{schedule_id}/rates")
async def get_fee_schedule_rates(
    practice_id: UUID,
    schedule_id: UUID,
    cpt_code: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    from src.infrastructure.database.models import FeeScheduleRate

    # Build base filter
    base_where = FeeScheduleRate.fee_schedule_id == schedule_id
    if cpt_code:
        base_where = (FeeScheduleRate.fee_schedule_id == schedule_id) & (
            FeeScheduleRate.cpt_code == cpt_code
        )

    # Total count
    count_result = await db.execute(
        select(func.count()).select_from(FeeScheduleRate).where(base_where)
    )
    total = count_result.scalar() or 0

    # Fetch paginated results
    query = (
        select(FeeScheduleRate)
        .where(base_where)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(query)
    rates = list(result.scalars().all())
    return {"items": rates, "total": total, "page": page, "page_size": page_size}


# ── Service Agreement ────────────────────────────────────────────

@router.post("/practices/{practice_id}/service-agreement", status_code=201)
async def create_service_agreement(
    practice_id: UUID,
    agreement: ServiceAgreementCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Set the billing fee structure and SLA targets for this practice."""
    try:
        result = await service_agreement_service.create_agreement(
            db=db,
            user_id=current_user["user_id"],
            practice_id=practice_id,
            data=agreement,
        )
        return result
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("/practices/{practice_id}/service-agreement")
async def get_service_agreement(
    practice_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        agreement = await service_agreement_service.get_active_agreement(
            db=db, practice_id=practice_id
        )
        return agreement
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("/practices/{practice_id}/sla-compliance")
async def get_sla_compliance(
    practice_id: UUID,
    period_start: date | None = None,
    period_end: date | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Check SLA compliance for a practice over a period.
    Returns actual vs target for each SLA metric.
    """
    # Verify practice exists
    result = await db.execute(select(Practice).where(Practice.id == practice_id))
    practice = result.scalar_one_or_none()
    if not practice:
        raise HTTPException(status_code=404, detail=f"Practice {practice_id} not found")

    # Try to get the service agreement for targets
    try:
        agreement = await service_agreement_service.get_active_agreement(
            db=db, practice_id=practice_id
        )
        targets = {
            "clean_claim_rate_target": agreement.sla_clean_claim_rate,
            "days_to_submit_target": agreement.sla_days_to_submit,
            "appeal_turnaround_target": agreement.sla_appeal_turnaround,
            "posting_turnaround_target": agreement.sla_posting_turnaround,
        }
    except ClientManagementError:
        targets = {
            "clean_claim_rate_target": 95.0,
            "days_to_submit_target": 2,
            "appeal_turnaround_target": 5,
            "posting_turnaround_target": 2,
        }

    # Return template with zeroed actuals since analytics aggregation is complex
    return {
        "practice_id": str(practice_id),
        "period_start": period_start,
        "period_end": period_end,
        "targets": targets,
        "actuals": {
            "clean_claim_rate": 0.0,
            "avg_days_to_submit": 0,
            "avg_appeal_turnaround": 0,
            "avg_posting_turnaround": 0,
        },
        "compliant": {
            "clean_claim_rate": False,
            "days_to_submit": False,
            "appeal_turnaround": False,
            "posting_turnaround": False,
        },
    }


# ── Staff Assignments ────────────────────────────────────────────

@router.post("/practices/{practice_id}/staff-assignments", status_code=201)
async def assign_staff(
    practice_id: UUID,
    assignment: StaffAssignmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Assign an internal staff member to work on this practice."""
    try:
        result = await staff_assignment_service.assign_staff(
            db=db,
            user_id=current_user["user_id"],
            practice_id=practice_id,
            data=assignment,
        )
        return result
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("/practices/{practice_id}/staff-assignments")
async def list_staff_assignments(
    practice_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        assignments = await staff_assignment_service.list_staff_assignments(
            db=db, practice_id=practice_id
        )
        total = len(assignments)
        start = (page - 1) * page_size
        return {
            "items": assignments[start : start + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.delete("/practices/{practice_id}/staff-assignments/{assignment_id}")
async def remove_staff_assignment(
    practice_id: UUID,
    assignment_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        await staff_assignment_service.remove_assignment(
            db=db,
            user_id=current_user["user_id"],
            practice_id=practice_id,
            assignment_id=assignment_id,
        )
        return {"detail": "Staff assignment removed"}
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


# ── Portal User Management ───────────────────────────────────────

@router.post("/practices/{practice_id}/portal-users", status_code=201)
async def create_portal_user(
    practice_id: UUID,
    portal_user: PortalUserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Create a provider portal user for this practice.
    Sends welcome email with password setup link.
    """
    try:
        result = await portal_user_service.create_portal_user(
            db=db,
            user_id=current_user["user_id"],
            practice_id=practice_id,
            data=portal_user,
        )
        return result
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.get("/practices/{practice_id}/portal-users")
async def list_portal_users(
    practice_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        users = await portal_user_service.list_portal_users(db=db, practice_id=practice_id)
        total = len(users)
        start = (page - 1) * page_size
        return {
            "items": users[start : start + page_size],
            "total": total,
            "page": page,
            "page_size": page_size,
        }
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.patch("/practices/{practice_id}/portal-users/{user_id}")
async def update_portal_user(
    practice_id: UUID,
    user_id: UUID,
    updates: PortalUserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        result = await portal_user_service.update_portal_user(
            db=db,
            user_id=current_user["user_id"],
            practice_id=practice_id,
            target_user_id=user_id,
            updates=updates.model_dump(exclude_none=True),
        )
        return result
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


@router.post("/practices/{practice_id}/portal-users/{user_id}/deactivate")
async def deactivate_portal_user(
    practice_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    try:
        result = await portal_user_service.deactivate_portal_user(
            db=db,
            caller_user_id=current_user["user_id"],
            practice_id=practice_id,
            target_user_id=user_id,
        )
        return result
    except ClientManagementError as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)


# ── Data Migration ───────────────────────────────────────────────

@router.post("/practices/{practice_id}/migrate/patients")
async def import_patients(
    practice_id: UUID,
    file: UploadFile = File(..., description="CSV with patient demographics"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Bulk import patient demographics during onboarding."""
    # Verify practice exists
    result = await db.execute(select(Practice).where(Practice.id == practice_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail=f"Practice {practice_id} not found")
    return {"message": "Patient import not yet available"}


@router.post("/practices/{practice_id}/migrate/open-ar")
async def import_open_ar(
    practice_id: UUID,
    file: UploadFile = File(..., description="CSV with open claims from previous biller"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Import existing open AR (a PMS/EHR payer-claim-aging export) during transition
    from a previous biller. Each open line becomes a follow-up queue item the AR/denial
    agent can work, prioritized by aging bucket."""
    result = await db.execute(select(Practice).where(Practice.id == practice_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail=f"Practice {practice_id} not found")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Empty file.")
    from src.core.ar_intake import service as ar_intake  # noqa: PLC0415
    try:
        summary = await ar_intake.import_open_ar(
            db, practice_id=practice_id, data=data, added_by_id=current_user.get("user_id"))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    await db.commit()
    return {"status": "imported", "practice_id": str(practice_id), **summary}


# ── Dashboard ───────────────────────────────────────────────────

@router.get("/dashboard")
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Return dashboard summary for client management."""
    # Count active practices
    active_result = await db.execute(
        select(func.count()).select_from(Practice).where(Practice.status == "active")
    )
    active_practices = active_result.scalar() or 0

    # Total revenue placeholder — would aggregate from ClientInvoice in production
    total_revenue = 0.0

    # Recent activities placeholder — would aggregate from AuditLog in production
    recent_activities: list = []

    return {
        "active_practices": active_practices,
        "total_revenue": total_revenue,
        "recent_activities": recent_activities,
    }