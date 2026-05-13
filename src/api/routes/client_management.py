"""
Client Management API Routes — Practice onboarding, configuration,
payer enrollments, fee schedules, staff assignments, and SLA tracking.
Internal staff only (provider portal users cannot access this).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import date, datetime
from enum import Enum

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
async def create_practice(practice: PracticeCreate):
    """
    Create a new practice client. Starts the onboarding process.
    Only company admins and billing managers can create practices.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/practices", response_model=list[PracticeResponse])
async def list_practices(
    status: PracticeStatus | None = None,
    search: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    """List all practices. Admins see all; managers see assigned only."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/practices/{practice_id}", response_model=PracticeResponse)
async def get_practice(practice_id: UUID):
    """Get practice details including onboarding status and KPIs."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.patch("/practices/{practice_id}")
async def update_practice(practice_id: UUID, updates: PracticeCreate):
    """Update practice configuration."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/practices/{practice_id}/activate")
async def activate_practice(practice_id: UUID):
    """
    Activate a practice after onboarding is complete.
    Validates all onboarding steps are done.
    Sets go_live_date.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/practices/{practice_id}/suspend")
async def suspend_practice(practice_id: UUID, body: SuspendRequest):
    """Suspend a practice (e.g., non-payment). Stops claim processing."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/practices/{practice_id}/terminate")
async def terminate_practice(practice_id: UUID, body: TerminateRequest):
    """Terminate a practice relationship. Triggers offboarding workflow."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


# ── Onboarding ───────────────────────────────────────────────────

@router.get("/practices/{practice_id}/onboarding", response_model=OnboardingChecklist)
async def get_onboarding_status(practice_id: UUID):
    """Get the onboarding checklist status for a practice."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


# ── Locations ────────────────────────────────────────────────────

@router.post("/practices/{practice_id}/locations", status_code=201)
async def add_location(practice_id: UUID, location: LocationCreate):
    """Add a practice location/facility."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/practices/{practice_id}/locations")
async def list_locations(practice_id: UUID):
    raise HTTPException(status_code=501, detail="Not yet implemented")


# ── Providers ────────────────────────────────────────────────────

@router.post("/practices/{practice_id}/providers", status_code=201)
async def add_provider(practice_id: UUID, provider: ProviderAdd):
    """
    Add a provider to the practice.
    If NPI already exists in system, links to existing provider record.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/practices/{practice_id}/providers")
async def list_practice_providers(practice_id: UUID):
    raise HTTPException(status_code=501, detail="Not yet implemented")


# ── Payer Enrollments ────────────────────────────────────────────

@router.post("/practices/{practice_id}/payer-enrollments", status_code=201)
async def add_payer_enrollment(practice_id: UUID, enrollment: PayerEnrollmentCreate):
    """
    Configure a payer enrollment for a practice.
    Includes ERA/EFT enrollment status, clearinghouse config, and fee schedule link.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/practices/{practice_id}/payer-enrollments")
async def list_payer_enrollments(practice_id: UUID):
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.patch("/practices/{practice_id}/payer-enrollments/{enrollment_id}")
async def update_payer_enrollment(practice_id: UUID, enrollment_id: UUID, updates: PayerEnrollmentCreate):
    raise HTTPException(status_code=501, detail="Not yet implemented")


# ── Fee Schedules ────────────────────────────────────────────────

@router.post("/practices/{practice_id}/fee-schedules/import")
async def import_fee_schedule(
    practice_id: UUID,
    payer_id: UUID,
    file: UploadFile = File(..., description="CSV or Excel fee schedule file"),
):
    """
    Import a contracted fee schedule for a payer.
    Parses CPT code, allowed amount, modifier-specific rates.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/practices/{practice_id}/fee-schedules")
async def list_fee_schedules(practice_id: UUID):
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/practices/{practice_id}/fee-schedules/{schedule_id}/rates")
async def get_fee_schedule_rates(
    practice_id: UUID,
    schedule_id: UUID,
    cpt_code: str | None = None,
):
    raise HTTPException(status_code=501, detail="Not yet implemented")


# ── Service Agreement ────────────────────────────────────────────

@router.post("/practices/{practice_id}/service-agreement", status_code=201)
async def create_service_agreement(practice_id: UUID, agreement: ServiceAgreementCreate):
    """Set the billing fee structure and SLA targets for this practice."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/practices/{practice_id}/service-agreement")
async def get_service_agreement(practice_id: UUID):
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/practices/{practice_id}/sla-compliance")
async def get_sla_compliance(
    practice_id: UUID,
    period_start: date | None = None,
    period_end: date | None = None,
):
    """
    Check SLA compliance for a practice over a period.
    Returns actual vs target for each SLA metric.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


# ── Staff Assignments ────────────────────────────────────────────

@router.post("/practices/{practice_id}/staff-assignments", status_code=201)
async def assign_staff(practice_id: UUID, assignment: StaffAssignmentCreate):
    """Assign an internal staff member to work on this practice."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/practices/{practice_id}/staff-assignments")
async def list_staff_assignments(practice_id: UUID):
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.delete("/practices/{practice_id}/staff-assignments/{assignment_id}")
async def remove_staff_assignment(practice_id: UUID, assignment_id: UUID):
    raise HTTPException(status_code=501, detail="Not yet implemented")


# ── Portal User Management ───────────────────────────────────────

@router.post("/practices/{practice_id}/portal-users", status_code=201)
async def create_portal_user(practice_id: UUID, portal_user: PortalUserCreate):
    """
    Create a provider portal user for this practice.
    Sends welcome email with password setup link.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/practices/{practice_id}/portal-users")
async def list_portal_users(practice_id: UUID):
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.patch("/practices/{practice_id}/portal-users/{user_id}")
async def update_portal_user(practice_id: UUID, user_id: UUID, updates: PortalUserCreate):
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/practices/{practice_id}/portal-users/{user_id}/deactivate")
async def deactivate_portal_user(practice_id: UUID, user_id: UUID):
    raise HTTPException(status_code=501, detail="Not yet implemented")


# ── Data Migration ───────────────────────────────────────────────

@router.post("/practices/{practice_id}/migrate/patients")
async def import_patients(
    practice_id: UUID,
    file: UploadFile = File(..., description="CSV with patient demographics"),
):
    """Bulk import patient demographics during onboarding."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/practices/{practice_id}/migrate/open-ar")
async def import_open_ar(
    practice_id: UUID,
    file: UploadFile = File(..., description="CSV with open claims from previous biller"),
):
    """Import existing open AR during transition from previous biller."""
    raise HTTPException(status_code=501, detail="Not yet implemented")
