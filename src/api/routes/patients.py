"""Patient management routes with PHI access controls."""
from fastapi import APIRouter
from pydantic import BaseModel
from uuid import UUID

router = APIRouter()


class EligibilityRequest(BaseModel):
    payer_id: UUID


@router.get("/")
async def list_patients():
    """List patients (PHI access logged)."""
    ...


@router.get("/{patient_id}")
async def get_patient(patient_id: str):
    """Get patient details including coverage."""
    ...


@router.get("/{patient_id}/claims")
async def get_patient_claims(patient_id: str):
    """Get all claims for a patient."""
    ...


@router.post("/{patient_id}/verify-eligibility")
async def verify_eligibility(patient_id: str, body: EligibilityRequest):
    """Real-time eligibility verification (270/271)."""
    ...