"""
Charge Intake API Routes — How providers submit charges/superbills
to your billing company. Accessible by both provider portal users
and internal staff.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID
from datetime import date, datetime
from enum import Enum

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────

class ChargeStatus(str, Enum):
    RECEIVED = "received"
    VALIDATION_ERROR = "validation_error"
    NEEDS_INFO = "needs_info"
    NEEDS_CODING = "needs_coding"
    READY_TO_BILL = "ready_to_bill"
    BILLED = "billed"
    REJECTED = "rejected"


class ProcedureEntry(BaseModel):
    cpt_code: str = Field(..., pattern=r"^\d{5}$")
    modifiers: list[str] = Field(default=[], max_length=4)
    units: float = Field(default=1, gt=0)
    charge_amount: float = Field(..., gt=0)


class ChargeEntryCreate(BaseModel):
    """Schema for provider portal charge entry."""
    # Patient
    patient_id: UUID | None = None
    patient_name: str | None = None  # If patient not yet in system
    patient_dob: date | None = None
    patient_mrn: str | None = None

    # Service
    service_date: date
    rendering_provider_id: UUID
    location_id: UUID | None = None
    place_of_service: str = "11"

    # Codes
    diagnosis_codes: list[str] = Field(default=[], description="ICD-10 codes")
    procedures: list[ProcedureEntry] = Field(default=[])
    needs_coding: bool = False  # Provider can flag if they want AI coding

    # Clinical
    clinical_notes: str | None = None
    authorization_number: str | None = None

    # Insurance
    primary_payer_id: UUID | None = None
    member_id: str | None = None


class ChargeEntryResponse(BaseModel):
    id: UUID
    practice_name: str | None = None
    patient_name: str | None
    service_date: date
    provider_name: str | None = None
    status: ChargeStatus
    diagnosis_codes: list[str]
    procedure_count: int
    total_charges: float | None = None
    validation_errors: list[str] | None = None
    assigned_to: str | None = None
    submitted_by: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class BatchImportResult(BaseModel):
    batch_id: UUID
    total_rows: int
    success_count: int
    error_count: int
    errors: list[dict]  # [{row: int, field: str, message: str}]


class MissingInfoRequest(BaseModel):
    """When billing staff needs info from the provider."""
    message: str
    fields_needed: list[str]  # e.g., ["diagnosis_codes", "authorization_number"]
    urgent: bool = False


# ── Provider Portal Endpoints ────────────────────────────────────

@router.post("/charges", response_model=ChargeEntryResponse, status_code=201)
async def submit_charge(charge: ChargeEntryCreate):
    """
    Submit a charge/encounter from the provider portal.
    Available to: provider portal users (practice_admin, provider, office_manager, front_desk)

    Workflow:
    1. Validate required fields (patient, provider, DOS, at least DX or notes)
    2. Match patient to existing record or flag for creation
    3. Auto-validate codes if provided
    4. If needs_coding=True or no codes provided, route to coding queue
    5. If codes valid, route to billing queue
    6. Create work queue item for internal staff
    7. Notify assigned billing staff
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/charges/superbill-upload", response_model=ChargeEntryResponse, status_code=201)
async def upload_superbill(
    service_date: date,
    rendering_provider_id: UUID,
    superbill: UploadFile = File(..., description="Scanned superbill (PDF, JPG, PNG)"),
):
    """
    Upload a scanned superbill.
    AI extracts: patient info, diagnosis codes, procedure codes, modifiers, units.
    Creates a charge entry pre-populated with extracted data for review.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/charges/batch-import", response_model=BatchImportResult)
async def batch_import_charges(
    file: UploadFile = File(..., description="CSV or Excel file with charges"),
):
    """
    Bulk import charges from a CSV/Excel export from the practice's PM system.
    Expected columns: patient_name, patient_dob, mrn, service_date,
    provider_npi, dx1-dx4, cpt, mod1-mod4, units, charge, payer_name, member_id
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/charges/clinical-document", response_model=ChargeEntryResponse, status_code=201)
async def submit_clinical_document(
    rendering_provider_id: UUID,
    patient_id: UUID | None = None,
    document: UploadFile = File(..., description="Clinical note, operative report, etc."),
):
    """
    Upload a clinical document for AI-assisted coding.
    Creates a charge entry with needs_coding=True and routes to coding queue.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


# ── Charge Management (Both Portals) ────────────────────────────

@router.get("/charges", response_model=list[ChargeEntryResponse])
async def list_charges(
    status: ChargeStatus | None = None,
    practice_id: UUID | None = None,  # Internal staff can filter by practice
    provider_id: UUID | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    assigned_to: UUID | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    """
    List charges. Tenant-filtered:
    - Provider portal users see only their practice's charges
    - Internal staff see charges for their assigned practices
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/charges/{charge_id}", response_model=ChargeEntryResponse)
async def get_charge(charge_id: UUID):
    """Get charge details including validation errors and communication history."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.patch("/charges/{charge_id}")
async def update_charge(charge_id: UUID, updates: dict):
    """
    Update a charge entry. Provider can update before it's billed.
    Internal staff can update during processing.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/charges/{charge_id}/upload-document")
async def attach_document_to_charge(
    charge_id: UUID,
    document: UploadFile = File(..., description="Supporting document"),
):
    """Attach additional documentation to a charge (clinical notes, auth letter, etc.)."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


# ── Internal Staff Actions ───────────────────────────────────────

@router.post("/charges/{charge_id}/request-info")
async def request_info_from_provider(charge_id: UUID, request_info: MissingInfoRequest):
    """
    Internal staff requests missing information from the provider.
    Sends a portal notification + email to the practice.
    Sets charge status to 'needs_info'.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/charges/{charge_id}/validate")
async def validate_charge(charge_id: UUID):
    """
    Run validation on a charge entry:
    - Patient exists and has active coverage
    - Provider is credentialed with the payer
    - Codes are valid and appropriate
    - Authorization is on file if required
    - No obvious duplicate
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/charges/{charge_id}/route-to-coding")
async def route_to_coding(charge_id: UUID):
    """Move charge to coding queue for AI-assisted code assignment."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/charges/{charge_id}/route-to-billing")
async def route_to_billing(charge_id: UUID):
    """
    Mark charge as ready and route to billing queue.
    Creates the encounter + claim records from the charge entry.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.post("/charges/{charge_id}/reject")
async def reject_charge(charge_id: UUID, reason: str):
    """Reject a charge entry (e.g., duplicate, unbillable). Notifies provider."""
    raise HTTPException(status_code=501, detail="Not yet implemented")


# ── Intake Dashboard (Internal) ─────────────────────────────────

@router.get("/intake/dashboard")
async def intake_dashboard():
    """
    Intake queue overview for internal staff:
    - Total charges pending by status
    - Charges by practice
    - Aging (charges waiting > 24h, 48h, 72h)
    - SLA compliance (% processed within SLA)
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")


@router.get("/intake/queue")
async def get_intake_queue(
    assigned_to: UUID | None = None,
    practice_id: UUID | None = None,
):
    """
    Prioritized intake work queue.
    Sorted by: SLA deadline, practice priority, date received.
    """
    raise HTTPException(status_code=501, detail="Not yet implemented")
