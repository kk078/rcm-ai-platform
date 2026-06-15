"""Eligibility verification routes."""
from __future__ import annotations
import uuid
from datetime import date
from typing import Any
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from src.infrastructure.database.session import get_db
from src.infrastructure.auth.middleware import get_current_user
from src.infrastructure.database.models import EligibilityCheck, User, Patient, Payer
from src.core.eligibility.service import run_eligibility_check, get_latest_eligibility

router = APIRouter(prefix="/eligibility", tags=["Eligibility"])


class EligibilityCheckRequest(BaseModel):
    patient_id: uuid.UUID
    coverage_id: uuid.UUID | None = None
    charge_batch_id: uuid.UUID | None = None
    service_date: date | None = None


class EligibilityResponse(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    coverage_id: uuid.UUID | None
    status: str
    is_active: bool
    plan_name: str | None
    group_number: str | None
    network_status: str | None
    deductible_total: float | None
    deductible_met: float | None
    oop_total: float | None
    oop_met: float | None
    copay: float | None
    coinsurance_pct: int | None
    error_message: str | None
    check_date: Any
    service_date: date | None
    patient_name: str | None = None
    payer_name: str | None = None

    class Config:
        from_attributes = True


def _build_response(check: EligibilityCheck, first_name: str | None = None, last_name: str | None = None, payer_name: str | None = None) -> EligibilityResponse:
    """Serialize an EligibilityCheck ORM object plus optional joined name fields."""
    data = EligibilityResponse.model_validate(check)
    if first_name and last_name:
        data.patient_name = f"{first_name} {last_name}"
    elif first_name:
        data.patient_name = first_name
    data.payer_name = payer_name
    return data


@router.post("/check", response_model=EligibilityResponse)
async def check_eligibility(
    request: EligibilityCheckRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run eligibility check for a patient/coverage combination."""
    check = await run_eligibility_check(
        db=db,
        practice_id=current_user.get("practice_id"),
        patient_id=request.patient_id,
        coverage_id=request.coverage_id,
        charge_batch_id=request.charge_batch_id,
        service_date=request.service_date,
        checked_by_id=current_user.get("user_id"),
    )
    await db.commit()
    return EligibilityResponse.model_validate(check)


@router.get("/patient/{patient_id}", response_model=list[EligibilityResponse])
async def get_patient_eligibility_history(
    patient_id: uuid.UUID,
    limit: int = Query(default=10, ge=1, le=50),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get eligibility check history for a patient."""
    result = await db.execute(
        select(
            EligibilityCheck,
            Patient.first_name,
            Patient.last_name,
            Payer.payer_name,
        )
        .join(Patient, EligibilityCheck.patient_id == Patient.id)
        .outerjoin(Payer, EligibilityCheck.payer_id == Payer.id)
        .where(
            EligibilityCheck.practice_id == current_user.get("practice_id"),
            EligibilityCheck.patient_id == patient_id,
        )
        .order_by(desc(EligibilityCheck.check_date))
        .limit(limit)
    )
    rows = result.all()
    return [_build_response(check, first_name, last_name, payer_name) for check, first_name, last_name, payer_name in rows]


@router.get("/latest/{patient_id}", response_model=EligibilityResponse | None)
async def get_latest_eligibility_check(
    patient_id: uuid.UUID,
    coverage_id: uuid.UUID | None = None,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the most recent eligibility check for a patient."""
    check = await get_latest_eligibility(db, current_user.get("practice_id"), patient_id, coverage_id)
    if not check:
        return None
    return EligibilityResponse.model_validate(check)


@router.get("/", response_model=list[EligibilityResponse])
async def list_eligibility_checks(
    status: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List eligibility checks for the practice."""
    filters = [EligibilityCheck.practice_id == current_user.get("practice_id")]
    if status:
        filters.append(EligibilityCheck.status == status)
    result = await db.execute(
        select(
            EligibilityCheck,
            Patient.first_name,
            Patient.last_name,
            Payer.payer_name,
        )
        .join(Patient, EligibilityCheck.patient_id == Patient.id)
        .outerjoin(Payer, EligibilityCheck.payer_id == Payer.id)
        .where(*filters)
        .order_by(desc(EligibilityCheck.check_date))
        .offset(skip).limit(limit)
    )
    rows = result.all()
    return [_build_response(check, first_name, last_name, payer_name) for check, first_name, last_name, payer_name in rows]
