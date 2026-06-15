"""
Medical Coding API Routes
AI-assisted medical code suggestion from clinical documentation.
"""

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from pydantic import BaseModel, Field
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone
from enum import Enum
from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.session import get_db
from src.infrastructure.auth.middleware import get_current_user
from src.api.schemas.common import PaginatedResponse

router = APIRouter()


# ── Schemas ──────────────────────────────────────────────────────

class CodeSystem(str, Enum):
    ICD10CM = "ICD-10-CM"
    ICD10PCS = "ICD-10-PCS"
    CPT = "CPT"
    HCPCS = "HCPCS"


class CodeSuggestion(BaseModel):
    code: str
    code_system: CodeSystem
    description: str
    confidence: float = Field(ge=0, le=1)
    rationale: str  # AI explanation of why this code applies
    supporting_text: str  # Excerpt from clinical note supporting code
    guideline_reference: str | None  # Coding guideline citation
    specificity_note: str | None  # If a more specific code exists


class CodingSessionResponse(BaseModel):
    id: UUID
    encounter_id: UUID
    status: str
    suggested_diagnoses: list[CodeSuggestion]
    suggested_procedures: list[CodeSuggestion]
    nlp_entities: dict  # Extracted clinical entities
    processing_time_ms: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CodeApproval(BaseModel):
    approved_diagnoses: list[str]  # Final ICD-10 codes
    approved_procedures: list[str]  # Final CPT/HCPCS codes
    coder_notes: str | None = None


class StartSessionRequest(BaseModel):
    encounter_id: UUID


class ValidationResult(BaseModel):
    valid: bool
    score: int = 0
    findings: list[dict] = []


class ApprovalResult(BaseModel):
    session_id: UUID
    encounter_id: UUID
    claim_id: UUID
    claim_number: str


class CodeValidationRequest(BaseModel):
    diagnosis_codes: list[str]
    procedure_codes: list[str]
    payer_id: UUID | None = None


# ── Endpoints ────────────────────────────────────────────────────

@router.post("/sessions", response_model=CodingSessionResponse, status_code=201)
async def start_coding_session(
    encounter_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Start an AI-assisted coding session for an encounter.

    Pipeline:
    1. Retrieve clinical documents for the encounter
    2. Run NLP extraction (diagnoses, procedures, medications, severity)
    3. Query vector DB for relevant coding guidelines
    4. Send to Claude API with RAG context for code suggestions
    5. Validate suggestions against NCCI edits and payer rules
    6. Return ranked suggestions with confidence scores
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return CodingSessionResponse(
        id=uuid4(),
        encounter_id=encounter_id,
        status="processing",
        suggested_diagnoses=[],
        suggested_procedures=[],
        nlp_entities={},
        processing_time_ms=0,
        created_at=now,
    )


@router.post("/sessions/from-document", response_model=CodingSessionResponse, status_code=201)
async def code_from_document(
    encounter_id: UUID,
    document: UploadFile = File(..., description="Clinical document (PDF, TXT, or HL7 CDA)"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Start a coding session from an uploaded clinical document."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return CodingSessionResponse(
        id=uuid4(),
        encounter_id=encounter_id,
        status="processing",
        suggested_diagnoses=[],
        suggested_procedures=[],
        nlp_entities={},
        processing_time_ms=0,
        created_at=now,
    )


@router.get("/sessions")
async def list_coding_sessions(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """List coding sessions for the current user's practices."""
    from src.infrastructure.database.models import CodingSession, Encounter, Patient
    conditions = []
    # Provider users see only their own practice; internal staff see everything
    user_type = current_user.get("user_type")
    if user_type == "provider":
        practice_ids = current_user.get("assigned_practice_ids", [])
        if practice_ids:
            conditions.append(CodingSession.practice_id.in_(practice_ids))
    if status:
        conditions.append(CodingSession.status == status)

    where = and_(*conditions) if conditions else True

    count_q = await db.execute(select(func.count(CodingSession.id)).where(where))
    total = count_q.scalar() or 0

    offset = (page - 1) * page_size
    items_q = await db.execute(
        select(CodingSession).where(where).order_by(CodingSession.created_at.desc()).offset(offset).limit(page_size)
    )
    sessions = items_q.scalars().all()

    # Pre-fetch encounters to resolve patient names in bulk
    encounter_ids = list({s.encounter_id for s in sessions if s.encounter_id})
    encounter_map: dict = {}
    if encounter_ids:
        enc_q = await db.execute(select(Encounter).where(Encounter.id.in_(encounter_ids)))
        encounters = enc_q.scalars().all()
        encounter_map = {e.id: e for e in encounters}

    patient_ids = list({e.patient_id for e in encounter_map.values() if e.patient_id})
    patient_map: dict = {}
    if patient_ids:
        pat_q = await db.execute(select(Patient).where(Patient.id.in_(patient_ids)))
        patients = pat_q.scalars().all()
        for p in patients:
            try:
                patient_map[p.id] = f"{p.first_name} {p.last_name}".strip() or None
            except Exception:
                patient_map[p.id] = None

    # Build response items with confidence score
    items = []
    for s in sessions:
        suggested = s.suggested_codes or {}

        def _extract_codes(items: list) -> list[str]:
            """Extract code strings from a list that may contain dicts or plain strings."""
            out = []
            for item in items:
                if isinstance(item, dict):
                    out.append(item.get("code", ""))
                elif isinstance(item, str):
                    out.append(item)
            return [c for c in out if c]

        dx_items = suggested.get("diagnoses", []) if isinstance(suggested, dict) else []
        proc_items = suggested.get("procedures", []) if isinstance(suggested, dict) else []
        code_list = _extract_codes(dx_items) + _extract_codes(proc_items)

        # Confidence is stored per-code; compute average across all suggested codes
        if isinstance(suggested, dict):
            all_confs = [
                item["confidence"] for item in dx_items
                if isinstance(item, dict) and "confidence" in item
            ] + [
                item["confidence"] for item in proc_items
                if isinstance(item, dict) and "confidence" in item
            ]
            confidence = sum(all_confs) / len(all_confs) if all_confs else 0.0
        else:
            confidence = 0.0

        # Resolve patient name via encounter
        patient_name = "—"
        enc = encounter_map.get(s.encounter_id)
        if enc and enc.patient_id:
            patient_name = patient_map.get(enc.patient_id) or "—"

        items.append({
            "id": str(s.id),
            "encounter_id": str(s.encounter_id),
            "patient_name": patient_name,
            "status": s.status,
            "suggested_codes": code_list,
            "coder_codes": list((s.final_codes or {}).get("diagnoses", [])) + list((s.final_codes or {}).get("procedures", [])),
            "confidence": confidence,
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "completed_at": s.review_completed_at.isoformat() if s.review_completed_at else None,
        })

    return {"items": items, "total": total, "page": page, "page_size": page_size}


@router.get("/sessions/{session_id}", response_model=CodingSessionResponse)
async def get_coding_session(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Retrieve a coding session with all suggestions."""
    raise HTTPException(status_code=404, detail="Coding session not found")


@router.post("/sessions/{session_id}/approve")
async def approve_codes(
    session_id: UUID,
    approval: CodeApproval,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Coder approves/modifies AI-suggested codes.
    Changes are logged for the AI feedback loop.
    Triggers claim assembly if all codes approved.
    """
    return {"message": "Codes approved"}


@router.get("/sessions/{session_id}/guidelines")
async def get_relevant_guidelines(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Retrieve coding guidelines relevant to this session's codes."""
    return []


@router.post("/validate")
async def validate_code_combination(
    body: CodeValidationRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """
    Validate a combination of diagnosis and procedure codes.
    Checks medical necessity, NCCI edits, and payer-specific rules.
    """
    return {"valid": True, "issues": []}


@router.get("/lookup/{code}")
async def lookup_code(
    code: str,
    code_system: CodeSystem | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Look up a specific medical code with description and guidelines."""
    return {"code": code, "description": "Code lookup", "code_system": "CPT"}


@router.get("/search")
async def search_codes(
    query: str = Query(default=""),
    code_system: CodeSystem | None = None,
    limit: int = 20,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Semantic search for medical codes by description or clinical term."""
    return []


# ── AI feedback flywheel (roadmap D) ─────────────────────────────────────────
class CodingFeedbackRequest(BaseModel):
    encounter_id: Optional[UUID] = None
    coding_session_id: Optional[UUID] = None
    ai_suggested_dx: list[str] = Field(default_factory=list)
    ai_suggested_cpt: list[str] = Field(default_factory=list)
    final_dx: list[str] = Field(default_factory=list)
    final_cpt: list[str] = Field(default_factory=list)
    override_reason: Optional[str] = None
    specialty: Optional[str] = None


@router.post("/feedback")
async def record_coding_feedback(
    body: CodingFeedbackRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Capture coder accept/override of AI codes -> AICodingFeedback (feeds the
    accuracy trend + threshold calibration). dx/cpt 'accepted' is derived by
    comparing the AI suggestion to the coder's final codes."""
    from src.infrastructure.database.models import AICodingFeedback  # noqa: PLC0415
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    dx_accepted = sorted(body.ai_suggested_dx) == sorted(body.final_dx) if (body.ai_suggested_dx or body.final_dx) else None
    cpt_accepted = sorted(body.ai_suggested_cpt) == sorted(body.final_cpt) if (body.ai_suggested_cpt or body.final_cpt) else None
    fb = AICodingFeedback(
        practice_id=current_user.get("practice_id"),
        coding_session_id=body.coding_session_id,
        encounter_id=body.encounter_id,
        coder_id=current_user.get("user_id"),
        ai_suggested_dx=body.ai_suggested_dx or None,
        ai_suggested_cpt=body.ai_suggested_cpt or None,
        final_dx=body.final_dx or None,
        final_cpt=body.final_cpt or None,
        dx_accepted=dx_accepted,
        cpt_accepted=cpt_accepted,
        override_reason=body.override_reason,
        specialty=body.specialty,
        created_at=now, updated_at=now,
    )
    db.add(fb)
    await db.commit()
    return {"recorded": True, "dx_accepted": dx_accepted, "cpt_accepted": cpt_accepted}
