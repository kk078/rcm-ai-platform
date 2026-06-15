"""EHR/EMR/PMS integration routes — webhooks, CSV import, FHIR sync, CDS Hooks, connections."""
from __future__ import annotations
import uuid
import hmac
import hashlib
from typing import Any
from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File, Header, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from src.infrastructure.database.session import get_db
from src.infrastructure.auth.middleware import get_current_user
from src.infrastructure.database.models import EHRConnection, EHRSyncLog, User
from src.core.ehr_integration.service import (
    import_patients_from_csv,
    import_encounters_from_csv,
    process_webhook_patient,
    process_webhook_encounter,
    sync_fhir_patients,
    handle_cds_hook_order_sign,
)

router = APIRouter(prefix="/ehr", tags=["EHR Integration"])


class EHRConnectionCreate(BaseModel):
    ehr_type: str  # fhir_r4, sftp_csv, webhook, athena, kareo
    ehr_name: str | None = None
    base_url: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    sftp_host: str | None = None
    sftp_port: int = 22
    sftp_username: str | None = None
    sftp_password: str | None = None
    sftp_path: str | None = None
    webhook_secret: str | None = None
    fhir_patient_scope: bool = True
    fhir_coverage_scope: bool = True
    fhir_encounter_scope: bool = False
    config: dict | None = None


class EHRConnectionResponse(BaseModel):
    id: uuid.UUID
    ehr_type: str
    ehr_name: str | None
    base_url: str | None
    is_active: bool
    last_sync_at: Any
    last_sync_status: str | None
    last_sync_count: int | None
    fhir_patient_scope: bool
    fhir_coverage_scope: bool
    fhir_encounter_scope: bool

    class Config:
        from_attributes = True


class SyncLogResponse(BaseModel):
    id: uuid.UUID
    sync_type: str
    trigger: str
    records_fetched: int
    records_created: int
    records_updated: int
    records_errored: int
    status: str
    started_at: Any
    completed_at: Any

    class Config:
        from_attributes = True


# ── EHR Connection Management ──────────────────────────────────────────────────

@router.post("/connections", response_model=EHRConnectionResponse, status_code=201)
async def create_ehr_connection(
    data: EHRConnectionCreate,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Configure a new EHR/PMS integration for the practice."""
    existing = await db.execute(
        select(EHRConnection).where(EHRConnection.practice_id == current_user.get("practice_id"))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Practice already has an EHR connection. Update instead.")

    conn = EHRConnection(
        practice_id=current_user.get("practice_id"),
        ehr_type=data.ehr_type,
        ehr_name=data.ehr_name,
        base_url=data.base_url,
        client_id=data.client_id,
        client_secret_enc=data.client_secret,  # TODO: encrypt in production
        sftp_host=data.sftp_host,
        sftp_port=data.sftp_port,
        sftp_username=data.sftp_username,
        sftp_password_enc=data.sftp_password,  # TODO: encrypt
        sftp_path=data.sftp_path,
        webhook_secret=data.webhook_secret,
        fhir_patient_scope=data.fhir_patient_scope,
        fhir_coverage_scope=data.fhir_coverage_scope,
        fhir_encounter_scope=data.fhir_encounter_scope,
        config=data.config,
    )
    db.add(conn)
    await db.flush()
    return EHRConnectionResponse.model_validate(conn)


@router.get("/connections", response_model=EHRConnectionResponse | None)
async def get_ehr_connection(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get EHR connection for the current practice."""
    result = await db.execute(
        select(EHRConnection).where(EHRConnection.practice_id == current_user.get("practice_id"))
    )
    conn = result.scalar_one_or_none()
    if not conn:
        return None
    return EHRConnectionResponse.model_validate(conn)


@router.post("/connections/sync", response_model=dict)
async def trigger_fhir_sync(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Manually trigger FHIR patient sync."""
    result = await db.execute(
        select(EHRConnection).where(EHRConnection.practice_id == current_user.get("practice_id"))
    )
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="No EHR connection configured")
    if conn.ehr_type != "fhir_r4":
        raise HTTPException(status_code=400, detail="Manual sync only available for FHIR R4 connections")
    sync_result = await sync_fhir_patients(db, conn.id, current_user.get("practice_id"))
    return sync_result


@router.get("/connections/sync-log", response_model=list[SyncLogResponse])
async def get_sync_log(
    limit: int = Query(default=20, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get sync history for the practice's EHR connection."""
    result = await db.execute(
        select(EHRSyncLog).where(EHRSyncLog.practice_id == current_user.get("practice_id"))
        .order_by(desc(EHRSyncLog.started_at)).limit(limit)
    )
    return [SyncLogResponse.model_validate(log) for log in result.scalars().all()]


# ── CSV / Excel Import ─────────────────────────────────────────────────────────

@router.post("/import/patients", response_model=dict)
async def import_patients(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Import patients from a CSV file. Accepts CSV exports from any PMS."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=415, detail="Only CSV files are supported")
    content = await file.read()
    result = await import_patients_from_csv(db, current_user.get("practice_id"), content, current_user.get("user_id"))
    return result


@router.post("/import/encounters", response_model=dict)
async def import_encounters(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Import encounters/charges from a CSV file."""
    if not file.filename.endswith(".csv"):
        raise HTTPException(status_code=415, detail="Only CSV files are supported")
    content = await file.read()
    result = await import_encounters_from_csv(db, current_user.get("practice_id"), content, current_user.get("user_id"))
    return result


# ── Inbound Webhooks (no auth — validated by HMAC secret) ────────────────────

@router.post("/webhooks/patient", include_in_schema=False)
async def webhook_patient(
    request: Request,
    x_practice_id: str = Header(..., alias="X-Practice-Id"),
    x_webhook_signature: str | None = Header(default=None, alias="X-Webhook-Signature"),
    db: AsyncSession = Depends(get_db),
):
    """
    Inbound patient webhook — called by Zapier, external PMS, or any system.
    Header X-Practice-Id must be the practice UUID.
    Optional HMAC-SHA256 signature in X-Webhook-Signature for verification.
    """
    body = await request.body()

    # Verify HMAC signature if present
    if x_webhook_signature:
        try:
            practice_id = uuid.UUID(x_practice_id)
            conn_result = await db.execute(
                select(EHRConnection).where(EHRConnection.practice_id == practice_id)
            )
            conn = conn_result.scalar_one_or_none()
            if conn and conn.webhook_secret:
                expected = hmac.new(
                    conn.webhook_secret.encode(), body, hashlib.sha256
                ).hexdigest()
                if not hmac.compare_digest(f"sha256={expected}", x_webhook_signature):
                    raise HTTPException(status_code=401, detail="Invalid webhook signature")
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid practice ID format")

    try:
        practice_id = uuid.UUID(x_practice_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid X-Practice-Id header")

    import json
    payload = json.loads(body)
    result = await process_webhook_patient(db, practice_id, payload)
    return result


@router.post("/webhooks/encounter", include_in_schema=False)
async def webhook_encounter(
    request: Request,
    x_practice_id: str = Header(..., alias="X-Practice-Id"),
    db: AsyncSession = Depends(get_db),
):
    """Inbound encounter/charge webhook."""
    body = await request.body()
    try:
        practice_id = uuid.UUID(x_practice_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid X-Practice-Id header")
    import json
    payload = json.loads(body)
    result = await process_webhook_encounter(db, practice_id, payload)
    return result


# ── CDS Hooks (EHR → Aethera AI coding) ──────────────────────────────────────

@router.post("/cds-hooks/order-sign", include_in_schema=False)
async def cds_hook_order_sign(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    CDS Hooks endpoint — 'order-sign' hook.
    Called by EHRs (Epic, Cerner, Athena) to get AI coding suggestions
    during encounter documentation. Returns CDS Cards.
    """
    hook_request = await request.json()
    cards_response = await handle_cds_hook_order_sign(db, hook_request)
    return cards_response


@router.get("/cds-hooks/discovery", include_in_schema=False)
async def cds_hooks_discovery():
    """CDS Hooks discovery endpoint — advertises available hooks to EHRs."""
    return {
        "services": [
            {
                "hook": "order-sign",
                "title": "Aethera AI Coding Suggestion",
                "description": "AI-powered ICD-10 and CPT code suggestions from clinical documentation",
                "id": "aethera-coding-suggestion",
                "prefetch": {
                    "patient": "Patient/{{context.patientId}}",
                },
            }
        ]
    }
