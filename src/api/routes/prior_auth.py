"""Prior authorization tracking routes."""
from __future__ import annotations
import uuid
from datetime import date, timedelta
from typing import Any
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from sqlalchemy.orm import selectinload
from src.infrastructure.database.session import get_db
from src.infrastructure.auth.middleware import get_current_user
from src.infrastructure.database.models import PriorAuthorization, Patient, Payer

router = APIRouter(prefix="/prior-auth", tags=["Prior Authorization"])


class PriorAuthCreate(BaseModel):
    patient_id: uuid.UUID
    coverage_id: uuid.UUID | None = None
    encounter_id: uuid.UUID | None = None
    payer_id: uuid.UUID | None = None
    procedure_codes: list[str] | None = None
    diagnosis_codes: list[str] | None = None
    auth_number: str | None = None
    status: str = "pending"
    requested_date: date | None = None
    approved_date: date | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    approved_units: int | None = None
    approved_visits: int | None = None
    notes: str | None = None


class PriorAuthUpdate(BaseModel):
    auth_number: str | None = None
    status: str | None = None
    approved_date: date | None = None
    valid_from: date | None = None
    valid_to: date | None = None
    approved_units: int | None = None
    approved_visits: int | None = None
    notes: str | None = None
    denial_reason: str | None = None
    appeal_deadline: date | None = None


class PriorAuthResponse(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    coverage_id: uuid.UUID | None
    encounter_id: uuid.UUID | None
    payer_id: uuid.UUID | None
    auth_number: str | None
    procedure_codes: list[str] | None
    diagnosis_codes: list[str] | None
    status: str
    requested_date: date | None
    approved_date: date | None
    valid_from: date | None
    valid_to: date | None
    approved_units: int | None
    approved_visits: int | None
    notes: str | None
    denial_reason: str | None
    appeal_deadline: date | None
    created_at: Any
    # Joined display fields (populated by _build_response)
    patient_name: str | None = None
    payer_name: str | None = None
    days_remaining: int | None = None

    class Config:
        from_attributes = True


def _build_pa_response(pa: PriorAuthorization, patient: Patient | None, payer: Payer | None) -> PriorAuthResponse:
    """Build PriorAuthResponse with joined display fields."""
    patient_name = None
    if patient:
        patient_name = f"{patient.first_name} {patient.last_name}"

    payer_name = None
    if payer:
        payer_name = payer.payer_name

    days_remaining = None
    if pa.valid_to:
        days_remaining = (pa.valid_to - date.today()).days

    r = PriorAuthResponse.model_validate(pa)
    r.patient_name = patient_name
    r.payer_name = payer_name
    r.days_remaining = days_remaining
    return r


async def _enrich_pa_list(db: AsyncSession, pa_list: list[PriorAuthorization]) -> list[PriorAuthResponse]:
    """Load patient/payer in batch and build enriched responses."""
    patient_ids = list({pa.patient_id for pa in pa_list if pa.patient_id})
    payer_ids = list({pa.payer_id for pa in pa_list if pa.payer_id})

    patient_map: dict = {}
    payer_map: dict = {}

    if patient_ids:
        pts = (await db.execute(select(Patient).where(Patient.id.in_(patient_ids)))).scalars().all()
        patient_map = {p.id: p for p in pts}

    if payer_ids:
        pyrs = (await db.execute(select(Payer).where(Payer.id.in_(payer_ids)))).scalars().all()
        payer_map = {p.id: p for p in pyrs}

    return [_build_pa_response(pa, patient_map.get(pa.patient_id), payer_map.get(pa.payer_id)) for pa in pa_list]


def _practice_filters(current_user: dict) -> list:
    """Build practice-level access filters for internal/provider users."""
    practice_id = current_user.get("practice_id")
    user_type = current_user.get("user_type")
    internal_role = current_user.get("internal_role")
    assigned = current_user.get("assigned_practice_ids", [])

    if user_type == "provider" and practice_id:
        return [PriorAuthorization.practice_id == practice_id]
    elif user_type == "internal" and internal_role not in ("company_admin", "qa_reviewer", None):
        if assigned:
            return [PriorAuthorization.practice_id.in_(assigned)]
    return []  # admin sees all


@router.post("/", response_model=PriorAuthResponse, status_code=201)
async def create_prior_auth(
    data: PriorAuthCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new prior authorization record."""
    practice_id = current_user.get("practice_id")
    user_id = current_user.get("user_id")
    pa = PriorAuthorization(
        practice_id=practice_id,
        requested_by_id=user_id,
        **data.model_dump(),
    )
    db.add(pa)
    await db.flush()
    enriched = await _enrich_pa_list(db, [pa])
    return enriched[0]


@router.get("/expiring/soon", response_model=list[PriorAuthResponse])
async def get_expiring_prior_auths(
    days: int = Query(default=7, ge=1, le=30),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get approved PAs expiring within N days."""
    cutoff = date.today() + timedelta(days=days)
    filters = [
        PriorAuthorization.status == "approved",
        PriorAuthorization.valid_to <= cutoff,
        PriorAuthorization.valid_to >= date.today(),
    ]
    filters.extend(_practice_filters(current_user))
    result = await db.execute(
        select(PriorAuthorization).where(*filters).order_by(PriorAuthorization.valid_to)
    )
    pa_list = result.scalars().all()
    return await _enrich_pa_list(db, pa_list)


@router.get("/", response_model=list[PriorAuthResponse])
async def list_prior_auths(
    status: str | None = None,
    patient_id: uuid.UUID | None = None,
    expiring_within_days: int | None = Query(default=None, ge=1, le=90),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List prior authorizations with optional filters."""
    filters = []
    filters.extend(_practice_filters(current_user))
    if status:
        filters.append(PriorAuthorization.status == status)
    if patient_id:
        filters.append(PriorAuthorization.patient_id == patient_id)
    if expiring_within_days:
        from datetime import timedelta
        cutoff = date.today() + timedelta(days=expiring_within_days)
        filters.append(PriorAuthorization.valid_to <= cutoff)
        filters.append(PriorAuthorization.valid_to >= date.today())
        filters.append(PriorAuthorization.status == "approved")

    q = select(PriorAuthorization)
    if filters:
        q = q.where(*filters)
    q = q.order_by(desc(PriorAuthorization.created_at)).offset(skip).limit(limit)

    result = await db.execute(q)
    pa_list = result.scalars().all()
    return await _enrich_pa_list(db, pa_list)


@router.get("/{pa_id}", response_model=PriorAuthResponse)
async def get_prior_auth(
    pa_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    filters = [PriorAuthorization.id == pa_id]
    filters.extend(_practice_filters(current_user))
    result = await db.execute(select(PriorAuthorization).where(*filters))
    pa = result.scalar_one_or_none()
    if not pa:
        raise HTTPException(status_code=404, detail="Prior authorization not found")
    enriched = await _enrich_pa_list(db, [pa])
    return enriched[0]


@router.patch("/{pa_id}", response_model=PriorAuthResponse)
async def update_prior_auth(
    pa_id: uuid.UUID,
    data: PriorAuthUpdate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    filters = [PriorAuthorization.id == pa_id]
    filters.extend(_practice_filters(current_user))
    result = await db.execute(select(PriorAuthorization).where(*filters))
    pa = result.scalar_one_or_none()
    if not pa:
        raise HTTPException(status_code=404, detail="Prior authorization not found")
    for field, value in data.model_dump(exclude_none=True).items():
        setattr(pa, field, value)
    await db.flush()
    enriched = await _enrich_pa_list(db, [pa])
    return enriched[0]
