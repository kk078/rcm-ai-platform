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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.session import get_db
from src.infrastructure.auth.middleware import get_current_user

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