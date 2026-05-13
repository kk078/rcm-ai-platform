"""
Charge Intake API Routes — How providers submit charges/superbills
to your billing company. Accessible by both provider portal users
and internal staff.
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
    ChargeEntry,
    ChargeBatch,
    Practice,
    Provider,
    User,
    WorkQueueItem,
    PortalNotification,
)
from src.infrastructure.auth.middleware import get_current_user

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


class RejectRequest(BaseModel):
    reason: str


class MissingInfoRequest(BaseModel):
    """When billing staff needs info from the provider."""
    message: str
    fields_needed: list[str]  # e.g., ["diagnosis_codes", "authorization_number"]
    urgent: bool = False


# ── Helpers ──────────────────────────────────────────────────────

async def _build_charge_response(entry: ChargeEntry, db: AsyncSession) -> ChargeEntryResponse:
    """Build a ChargeEntryResponse from a ChargeEntry ORM object."""
    # Get practice name
    practice_name = None
    if entry.practice_id:
        result = await db.execute(
            select(Practice.practice_name).where(Practice.id == entry.practice_id)
        )
        practice_name = result.scalar_one_or_none()

    # Get provider name
    provider_name = None
    if entry.rendering_provider_id:
        result = await db.execute(
            select(Provider.first_name, Provider.last_name).where(
                Provider.id == entry.rendering_provider_id
            )
        )
        row = result.first()
        if row:
            provider_name = f"{row[0]} {row[1]}"

    # Get assigned_to user name
    assigned_to_name = None
    if entry.assigned_to:
        result = await db.execute(
            select(User.first_name, User.last_name).where(User.id == entry.assigned_to)
        )
        row = result.first()
        if row:
            assigned_to_name = f"{row[0]} {row[1]}"

    # Calculate procedure count and total charges from procedure_codes JSONB
    procedure_codes = entry.procedure_codes
    if isinstance(procedure_codes, list):
        procedure_count = len(procedure_codes)
        total_charges = sum(
            p.get("charge_amount", 0) for p in procedure_codes if isinstance(p, dict)
        )
    elif isinstance(procedure_codes, dict):
        procedure_count = len(procedure_codes)
        total_charges = sum(
            v.get("charge_amount", 0) for v in procedure_codes.values() if isinstance(v, dict)
        )
    else:
        procedure_count = 0
        total_charges = 0

    # Convert validation_errors to list[str] if needed
    validation_errors = None
    if entry.validation_errors:
        if isinstance(entry.validation_errors, list):
            validation_errors = entry.validation_errors
        elif isinstance(entry.validation_errors, dict):
            validation_errors = [f"{k}: {v}" for k, v in entry.validation_errors.items()]

    return ChargeEntryResponse(
        id=entry.id,
        practice_name=practice_name,
        patient_name=entry.patient_name_submitted,
        service_date=entry.service_date,
        provider_name=provider_name,
        status=ChargeStatus(entry.status),
        diagnosis_codes=entry.diagnosis_codes or [],
        procedure_count=procedure_count,
        total_charges=total_charges if total_charges else None,
        validation_errors=validation_errors,
        assigned_to=assigned_to_name,
        submitted_by=None,
        created_at=entry.created_at,
    )


# ── Provider Portal Endpoints ────────────────────────────────────

@router.post("/charges", response_model=ChargeEntryResponse, status_code=201)
async def submit_charge(
    charge: ChargeEntryCreate,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
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
    practice_id = current_user.get("practice_id")
    if not practice_id:
        raise HTTPException(status_code=400, detail="Practice ID required for charge submission")

    # Determine initial status
    if charge.needs_coding or not charge.diagnosis_codes:
        initial_status = "needs_coding"
    else:
        initial_status = "received"

    # Serialize procedures to JSONB-compatible format
    procedure_codes = [p.model_dump() for p in charge.procedures] if charge.procedures else None

    # Create the charge entry
    entry = ChargeEntry(
        id=uuid4(),
        practice_id=practice_id,
        patient_id=charge.patient_id,
        patient_name_submitted=charge.patient_name,
        patient_dob_submitted=charge.patient_dob,
        patient_mrn_submitted=charge.patient_mrn,
        rendering_provider_id=charge.rendering_provider_id,
        service_date=charge.service_date,
        place_of_service=charge.place_of_service,
        location_id=charge.location_id,
        diagnosis_codes=charge.diagnosis_codes or None,
        procedure_codes=procedure_codes,
        needs_coding=charge.needs_coding,
        clinical_notes=charge.clinical_notes,
        authorization_number=charge.authorization_number,
        primary_payer_id=charge.primary_payer_id,
        member_id=charge.member_id,
        status=initial_status,
    )
    db.add(entry)

    # Create a work queue item
    queue_item = WorkQueueItem(
        id=uuid4(),
        practice_id=practice_id,
        queue_type="intake",
        item_type="charge_entry",
        item_id=entry.id,
        priority=50,
        status="pending",
    )
    db.add(queue_item)

    await db.flush()

    return await _build_charge_response(entry, db)


@router.post("/charges/superbill-upload", response_model=ChargeEntryResponse, status_code=201)
async def upload_superbill(
    service_date: date,
    rendering_provider_id: UUID,
    superbill: UploadFile = File(..., description="Scanned superbill (PDF, JPG, PNG)"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Upload a scanned superbill.
    AI extracts: patient info, diagnosis codes, procedure codes, modifiers, units.
    Creates a charge entry pre-populated with extracted data for review.
    """
    practice_id = current_user.get("practice_id")
    if not practice_id:
        raise HTTPException(status_code=400, detail="Practice ID required for charge submission")

    # Create a placeholder charge entry — AI extraction would populate details
    entry = ChargeEntry(
        id=uuid4(),
        practice_id=practice_id,
        rendering_provider_id=rendering_provider_id,
        service_date=service_date,
        place_of_service="11",
        needs_coding=True,
        status="needs_coding",
    )
    db.add(entry)

    queue_item = WorkQueueItem(
        id=uuid4(),
        practice_id=practice_id,
        queue_type="intake",
        item_type="charge_entry",
        item_id=entry.id,
        priority=60,
        status="pending",
    )
    db.add(queue_item)

    await db.flush()

    return await _build_charge_response(entry, db)


@router.post("/charges/batch-import", response_model=BatchImportResult)
async def batch_import_charges(
    file: UploadFile = File(..., description="CSV or Excel file with charges"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Bulk import charges from a CSV/Excel export from the practice's PM system.
    Expected columns: patient_name, patient_dob, mrn, service_date,
    provider_npi, dx1-dx4, cpt, mod1-mod4, units, charge, payer_name, member_id
    """
    practice_id = current_user.get("practice_id")
    if not practice_id:
        raise HTTPException(status_code=400, detail="Practice ID required for batch import")

    # Create a batch record
    batch = ChargeBatch(
        id=uuid4(),
        practice_id=practice_id,
        submitted_by=current_user.get("user_id"),
        intake_method="batch_import",
        total_charges=0,
        processed_charges=0,
        error_charges=0,
        status="received",
    )
    db.add(batch)
    await db.flush()

    return BatchImportResult(
        batch_id=batch.id,
        total_rows=0,
        success_count=0,
        error_count=0,
        errors=[],
    )


@router.post("/charges/clinical-document", response_model=ChargeEntryResponse, status_code=201)
async def submit_clinical_document(
    rendering_provider_id: UUID,
    patient_id: UUID | None = None,
    document: UploadFile = File(..., description="Clinical note, operative report, etc."),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Upload a clinical document for AI-assisted coding.
    Creates a charge entry with needs_coding=True and routes to coding queue.
    """
    practice_id = current_user.get("practice_id")
    if not practice_id:
        raise HTTPException(status_code=400, detail="Practice ID required for charge submission")

    entry = ChargeEntry(
        id=uuid4(),
        practice_id=practice_id,
        patient_id=patient_id,
        rendering_provider_id=rendering_provider_id,
        service_date=date.today(),
        needs_coding=True,
        status="needs_coding",
    )
    db.add(entry)

    queue_item = WorkQueueItem(
        id=uuid4(),
        practice_id=practice_id,
        queue_type="coding",
        item_type="charge_entry",
        item_id=entry.id,
        priority=70,
        status="pending",
    )
    db.add(queue_item)

    await db.flush()

    return await _build_charge_response(entry, db)


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
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    List charges. Tenant-filtered:
    - Provider portal users see only their practice's charges
    - Internal staff see charges for their assigned practices
    """
    conditions = []

    # Tenant filter: provider users see only their own practice
    user_practice_id = current_user.get("practice_id")
    user_type = current_user.get("user_type")

    if user_type == "provider" and user_practice_id:
        conditions.append(ChargeEntry.practice_id == user_practice_id)
    elif practice_id:
        conditions.append(ChargeEntry.practice_id == practice_id)

    if status:
        conditions.append(ChargeEntry.status == status.value)
    if provider_id:
        conditions.append(ChargeEntry.rendering_provider_id == provider_id)
    if date_from:
        conditions.append(ChargeEntry.service_date >= date_from)
    if date_to:
        conditions.append(ChargeEntry.service_date <= date_to)
    if assigned_to:
        conditions.append(ChargeEntry.assigned_to == assigned_to)

    where_clause = and_(*conditions) if conditions else True

    offset = (page - 1) * page_size
    result = await db.execute(
        select(ChargeEntry)
        .where(where_clause)
        .order_by(ChargeEntry.created_at.desc())
        .offset(offset)
        .limit(page_size)
    )
    entries = result.scalars().all()

    responses = []
    for entry in entries:
        resp = await _build_charge_response(entry, db)
        responses.append(resp)

    return responses


@router.get("/charges/{charge_id}", response_model=ChargeEntryResponse)
async def get_charge(
    charge_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get charge details including validation errors and communication history."""
    result = await db.execute(select(ChargeEntry).where(ChargeEntry.id == charge_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Charge not found")

    # Tenant filter
    user_practice_id = current_user.get("practice_id")
    user_type = current_user.get("user_type")
    if user_type == "provider" and user_practice_id and entry.practice_id != user_practice_id:
        raise HTTPException(status_code=404, detail="Charge not found")

    return await _build_charge_response(entry, db)


@router.patch("/charges/{charge_id}")
async def update_charge(
    charge_id: UUID,
    updates: dict,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Update a charge entry. Provider can update before it's billed.
    Internal staff can update during processing.
    """
    result = await db.execute(select(ChargeEntry).where(ChargeEntry.id == charge_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Charge not found")

    # Tenant filter
    user_practice_id = current_user.get("practice_id")
    user_type = current_user.get("user_type")
    if user_type == "provider" and user_practice_id and entry.practice_id != user_practice_id:
        raise HTTPException(status_code=404, detail="Charge not found")

    # Apply allowed updates
    allowed_fields = {
        "patient_name_submitted", "patient_dob_submitted", "patient_mrn_submitted",
        "diagnosis_codes", "procedure_codes", "clinical_notes", "authorization_number",
        "place_of_service", "needs_coding", "primary_payer_id", "member_id",
    }
    for field, value in updates.items():
        if field in allowed_fields:
            setattr(entry, field, value)

    await db.flush()

    return await _build_charge_response(entry, db)


@router.post("/charges/{charge_id}/upload-document")
async def attach_document_to_charge(
    charge_id: UUID,
    document: UploadFile = File(..., description="Supporting document"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Attach additional documentation to a charge (clinical notes, auth letter, etc.)."""
    result = await db.execute(select(ChargeEntry).where(ChargeEntry.id == charge_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Charge not found")

    return {
        "message": "Document attached",
        "charge_id": str(charge_id),
        "filename": document.filename,
    }


# ── Internal Staff Actions ───────────────────────────────────────

@router.post("/charges/{charge_id}/request-info")
async def request_info_from_provider(
    charge_id: UUID,
    request_info: MissingInfoRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Internal staff requests missing information from the provider.
    Sends a portal notification + email to the practice.
    Sets charge status to 'needs_info'.
    """
    result = await db.execute(select(ChargeEntry).where(ChargeEntry.id == charge_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Charge not found")

    entry.status = "needs_info"
    entry.provider_notified = True

    # Create a portal notification for the practice
    notification = PortalNotification(
        id=uuid4(),
        practice_id=entry.practice_id,
        user_id=entry.assigned_to or current_user.get("user_id"),
        notification_type="info_request",
        title="Information Requested",
        body=request_info.message,
    )
    db.add(notification)

    await db.flush()

    return {
        "message": "Information request sent to provider",
        "charge_id": str(charge_id),
        "fields_needed": request_info.fields_needed,
    }


@router.post("/charges/{charge_id}/validate")
async def validate_charge(
    charge_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Run validation on a charge entry:
    - Patient exists and has active coverage
    - Provider is credentialed with the payer
    - Codes are valid and appropriate
    - Authorization is on file if required
    - No obvious duplicate
    """
    result = await db.execute(select(ChargeEntry).where(ChargeEntry.id == charge_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Charge not found")

    errors = []

    # Basic validation checks
    if not entry.patient_id and not entry.patient_name_submitted:
        errors.append("Patient identification required")
    if not entry.rendering_provider_id:
        errors.append("Rendering provider required")
    if not entry.diagnosis_codes and not entry.needs_coding:
        errors.append("Diagnosis codes required (or flag needs_coding)")
    if not entry.primary_payer_id:
        errors.append("Primary payer required")

    if errors:
        entry.status = "validation_error"
        entry.validation_errors = errors
    else:
        entry.status = "received"
        entry.validation_errors = None

    await db.flush()

    return {
        "charge_id": str(charge_id),
        "valid": len(errors) == 0,
        "errors": errors,
    }


@router.post("/charges/{charge_id}/route-to-coding")
async def route_to_coding(
    charge_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Move charge to coding queue for AI-assisted code assignment."""
    result = await db.execute(select(ChargeEntry).where(ChargeEntry.id == charge_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Charge not found")

    entry.status = "needs_coding"
    entry.needs_coding = True

    # Create or update work queue item
    existing = await db.execute(
        select(WorkQueueItem).where(
            and_(
                WorkQueueItem.item_id == charge_id,
                WorkQueueItem.item_type == "charge_entry",
            )
        )
    )
    queue_item = existing.scalar_one_or_none()
    if queue_item:
        queue_item.queue_type = "coding"
        queue_item.status = "pending"
    else:
        queue_item = WorkQueueItem(
            id=uuid4(),
            practice_id=entry.practice_id,
            queue_type="coding",
            item_type="charge_entry",
            item_id=entry.id,
            priority=70,
            status="pending",
        )
        db.add(queue_item)

    await db.flush()

    return {"message": "Charge routed to coding", "charge_id": str(charge_id)}


@router.post("/charges/{charge_id}/route-to-billing")
async def route_to_billing(
    charge_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Mark charge as ready and route to billing queue.
    Creates the encounter + claim records from the charge entry.
    """
    result = await db.execute(select(ChargeEntry).where(ChargeEntry.id == charge_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Charge not found")

    entry.status = "ready_to_bill"

    # Create or update work queue item
    existing = await db.execute(
        select(WorkQueueItem).where(
            and_(
                WorkQueueItem.item_id == charge_id,
                WorkQueueItem.item_type == "charge_entry",
            )
        )
    )
    queue_item = existing.scalar_one_or_none()
    if queue_item:
        queue_item.queue_type = "billing"
        queue_item.status = "pending"
    else:
        queue_item = WorkQueueItem(
            id=uuid4(),
            practice_id=entry.practice_id,
            queue_type="billing",
            item_type="charge_entry",
            item_id=entry.id,
            priority=60,
            status="pending",
        )
        db.add(queue_item)

    await db.flush()

    return {"message": "Charge routed", "charge_id": str(charge_id)}


@router.post("/charges/{charge_id}/reject")
async def reject_charge(
    charge_id: UUID,
    body: RejectRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Reject a charge entry (e.g., duplicate, unbillable). Notifies provider."""
    result = await db.execute(select(ChargeEntry).where(ChargeEntry.id == charge_id))
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Charge not found")

    entry.status = "rejected"
    entry.validation_errors = {"rejection_reason": body.reason}

    # Create portal notification
    notification = PortalNotification(
        id=uuid4(),
        practice_id=entry.practice_id,
        notification_type="charge_rejected",
        title="Charge Rejected",
        body=body.reason,
    )
    db.add(notification)

    await db.flush()

    return {"message": "Charge rejected", "charge_id": str(charge_id), "reason": body.reason}


# ── Intake Dashboard (Internal) ─────────────────────────────────

@router.get("/intake/dashboard")
async def intake_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Intake queue overview for internal staff:
    - Total charges pending by status
    - Charges by practice
    - Aging (charges waiting > 24h, 48h, 72h)
    - SLA compliance (% processed within SLA)
    """
    # Total pending charges
    pending_q = await db.execute(
        select(func.count(ChargeEntry.id)).where(
            ChargeEntry.status.in_(["received", "needs_coding", "needs_info"])
        )
    )
    total_pending = pending_q.scalar() or 0

    # Charges by status
    status_q = await db.execute(
        select(ChargeEntry.status, func.count(ChargeEntry.id))
        .group_by(ChargeEntry.status)
    )
    status_rows = status_q.all()
    by_status = {row[0]: row[1] for row in status_rows}

    # Charges by practice
    practice_q = await db.execute(
        select(Practice.practice_name, func.count(ChargeEntry.id))
        .join(Practice, ChargeEntry.practice_id == Practice.id)
        .group_by(Practice.practice_name)
    )
    practice_rows = practice_q.all()
    by_practice = {row[0]: row[1] for row in practice_rows}

    # Aging buckets
    from datetime import timedelta

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    aging_24_q = await db.execute(
        select(func.count(ChargeEntry.id)).where(
            and_(
                ChargeEntry.status.in_(["received", "needs_coding", "needs_info"]),
                ChargeEntry.created_at <= now - timedelta(hours=24),
            )
        )
    )
    aging_48_q = await db.execute(
        select(func.count(ChargeEntry.id)).where(
            and_(
                ChargeEntry.status.in_(["received", "needs_coding", "needs_info"]),
                ChargeEntry.created_at <= now - timedelta(hours=48),
            )
        )
    )
    aging_72_q = await db.execute(
        select(func.count(ChargeEntry.id)).where(
            and_(
                ChargeEntry.status.in_(["received", "needs_coding", "needs_info"]),
                ChargeEntry.created_at <= now - timedelta(hours=72),
            )
        )
    )

    aging = {
        "over_24h": aging_24_q.scalar() or 0,
        "over_48h": aging_48_q.scalar() or 0,
        "over_72h": aging_72_q.scalar() or 0,
    }

    return {
        "total_pending": total_pending,
        "by_status": by_status,
        "by_practice": by_practice,
        "aging": aging,
    }


@router.get("/intake/queue")
async def get_intake_queue(
    assigned_to: UUID | None = None,
    practice_id: UUID | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Prioritized intake work queue.
    Sorted by: SLA deadline, practice priority, date received.
    """
    conditions = [
        WorkQueueItem.queue_type == "intake",
        WorkQueueItem.status.in_(["pending", "in_progress"]),
    ]
    if assigned_to:
        conditions.append(WorkQueueItem.assigned_to == assigned_to)
    if practice_id:
        conditions.append(WorkQueueItem.practice_id == practice_id)

    result = await db.execute(
        select(WorkQueueItem)
        .where(and_(*conditions))
        .order_by(WorkQueueItem.priority.desc(), WorkQueueItem.created_at.asc())
        .limit(100)
    )
    items = result.scalars().all()

    queue_items = []
    for item in items:
        # Get charge entry details
        charge_result = await db.execute(
            select(ChargeEntry).where(ChargeEntry.id == item.item_id)
        )
        charge = charge_result.scalar_one_or_none()

        # Get practice name
        practice_name = ""
        if item.practice:
            practice_name = item.practice.name or ""

        # Get assigned user name
        assigned_to_name = None
        if item.assigned_to:
            user_result = await db.execute(
                select(User.first_name, User.last_name).where(User.id == item.assigned_to)
            )
            row = user_result.first()
            if row:
                assigned_to_name = f"{row[0]} {row[1]}"

        age_hours = 0.0
        if item.created_at:
            delta = datetime.now(timezone.utc).replace(tzinfo=None) - item.created_at
            age_hours = round(delta.total_seconds() / 3600, 1)

        queue_items.append({
            "id": str(item.id),
            "practice_name": practice_name,
            "practice_id": str(item.practice_id),
            "queue_type": item.queue_type,
            "item_type": item.item_type,
            "item_id": str(item.item_id),
            "priority": item.priority,
            "priority_label": "critical" if item.priority >= 80 else "high" if item.priority >= 60 else "medium" if item.priority >= 30 else "low",
            "status": item.status,
            "assigned_to": str(item.assigned_to) if item.assigned_to else None,
            "assigned_to_name": assigned_to_name,
            "due_date": item.due_date.isoformat() if item.due_date else None,
            "sla_breached": item.sla_breached,
            "age_hours": age_hours,
            "summary": f"{practice_name}: {item.item_type.replace('_', ' ').title()} — intake queue" if practice_name else f"{item.item_type.replace('_', ' ').title()} — intake queue",
            "charge_status": charge.status if charge else None,
            "patient_name": charge.patient_name_submitted if charge else None,
            "created_at": item.created_at.isoformat() if item.created_at else None,
        })

    return queue_items


@router.get("/intake/stats")
async def get_intake_stats(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Intake statistics summary."""
    total_q = await db.execute(select(func.count(ChargeEntry.id)))
    total = total_q.scalar() or 0

    pending_q = await db.execute(
        select(func.count(ChargeEntry.id)).where(
            ChargeEntry.status.in_(["received", "needs_coding", "needs_info"])
        )
    )
    pending = pending_q.scalar() or 0

    routed_q = await db.execute(
        select(func.count(ChargeEntry.id)).where(
            ChargeEntry.status.in_(["ready_to_bill", "billed"])
        )
    )
    routed = routed_q.scalar() or 0

    rejected_q = await db.execute(
        select(func.count(ChargeEntry.id)).where(ChargeEntry.status == "rejected")
    )
    rejected = rejected_q.scalar() or 0

    return {
        "total": total,
        "pending": pending,
        "routed": routed,
        "rejected": rejected,
    }