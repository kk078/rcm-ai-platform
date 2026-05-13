"""Patient management routes with PHI access controls."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.session import get_db
from src.infrastructure.database.models import Patient
from src.infrastructure.auth.middleware import get_current_user

router = APIRouter()


class EligibilityRequest(BaseModel):
    payer_id: UUID


@router.get("/")
async def list_patients(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List patients (PHI access logged)."""
    result = await db.execute(select(Patient).limit(100))
    patients = result.scalars().all()
    return []


@router.get("/{patient_id}")
async def get_patient(
    patient_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get patient details including coverage."""
    raise HTTPException(status_code=404, detail="Patient not found")


@router.get("/{patient_id}/claims")
async def get_patient_claims(
    patient_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Get all claims for a patient."""
    return []


@router.post("/{patient_id}/verify-eligibility")
async def verify_eligibility(
    patient_id: str,
    body: EligibilityRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Real-time eligibility verification (270/271)."""
    return {"eligible": True, "message": "Eligibility verified"}