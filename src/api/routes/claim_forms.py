"""Claim form (CMS-1500 / UB-04) assembly, review, edit, and approval.

Workflow: a coded Claim -> /build (assemble + NPPES/CMS enrich + map + scrub) ->
review screen (GET) -> edit (PUT) -> approve (POST). All endpoints require auth;
provider users are scoped to their own practice.
"""
from datetime import datetime, timezone
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.auth.middleware import get_current_user
from src.infrastructure.database.session import get_db
from src.core.claim_forms.assembler import assemble_claim_form
from src.core.claim_forms.forms import validate_form
from src.core.claim_forms import nppes

logger = structlog.get_logger()
router = APIRouter()

VALID_FORMS = ("cms1500", "ub04")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class SaveFormRequest(BaseModel):
    form_type: str
    fields: dict


class NpiLookupRequest(BaseModel):
    npi: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    organization_name: Optional[str] = None
    state: Optional[str] = None


async def _load_claim_scoped(db: AsyncSession, claim_id: str, user: dict):
    from src.infrastructure.database.models import Claim  # noqa: PLC0415
    claim = (await db.execute(select(Claim).where(Claim.id == claim_id))).scalar_one_or_none()
    if claim is None:
        raise HTTPException(status_code=404, detail="Claim not found")
    if user.get("user_type") == "provider":
        upid = user.get("practice_id")
        if not upid or str(claim.practice_id) != str(upid):
            raise HTTPException(status_code=403, detail="Not authorized for this claim's practice")
    return claim


async def _serialize(cf) -> dict:
    return {
        "id": str(cf.id), "claim_id": str(cf.claim_id), "form_type": cf.form_type,
        "status": cf.status, "fields": cf.fields, "edits": cf.edits or [],
        "enrichment": cf.enrichment or {},
        "updated_at": cf.updated_at.isoformat() if cf.updated_at else None,
    }


@router.post("/{claim_id}/build")
async def build_claim_form(
    claim_id: str,
    form_type: str = Query("cms1500"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Assemble + auto-enrich (NPPES/CMS) + map a claim to the requested form, persist, return."""
    if form_type not in VALID_FORMS:
        raise HTTPException(status_code=400, detail=f"form_type must be one of {VALID_FORMS}")
    await _load_claim_scoped(db, claim_id, current_user)

    try:
        assembled = await assemble_claim_form(db, claim_id, form_type)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    from src.infrastructure.database.models import Claim, ClaimForm  # noqa: PLC0415
    claim = (await db.execute(select(Claim).where(Claim.id == claim_id))).scalar_one()

    existing = (await db.execute(
        select(ClaimForm).where(ClaimForm.claim_id == claim_id, ClaimForm.form_type == form_type)
    )).scalar_one_or_none()

    now = _now()
    if existing is None:
        cf = ClaimForm(claim_id=claim.id, practice_id=claim.practice_id, form_type=form_type,
                       fields=assembled["form"], edits=assembled["edits"],
                       enrichment=assembled["enrichment"], status="draft",
                       created_at=now, updated_at=now)
        db.add(cf)
    else:
        existing.fields = assembled["form"]
        existing.edits = assembled["edits"]
        existing.enrichment = assembled["enrichment"]
        existing.status = "draft"
        existing.updated_at = now
        cf = existing
    await db.commit()
    await db.refresh(cf)
    logger.info("claim_form.built", claim_id=claim_id, form_type=form_type,
                edits=len(assembled["edits"]))
    return await _serialize(cf)


@router.get("/{claim_id}")
async def get_claim_form(
    claim_id: str,
    form_type: str = Query("cms1500"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    await _load_claim_scoped(db, claim_id, current_user)
    from src.infrastructure.database.models import ClaimForm  # noqa: PLC0415
    cf = (await db.execute(
        select(ClaimForm).where(ClaimForm.claim_id == claim_id, ClaimForm.form_type == form_type)
    )).scalar_one_or_none()
    if cf is None:
        raise HTTPException(status_code=404, detail="Form not built yet")
    return await _serialize(cf)


@router.put("/{claim_id}")
async def save_claim_form(
    claim_id: str,
    body: SaveFormRequest,
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Save user-edited boxes and re-run validation."""
    if body.form_type not in VALID_FORMS:
        raise HTTPException(status_code=400, detail=f"form_type must be one of {VALID_FORMS}")
    await _load_claim_scoped(db, claim_id, current_user)
    from src.infrastructure.database.models import ClaimForm  # noqa: PLC0415
    cf = (await db.execute(
        select(ClaimForm).where(ClaimForm.claim_id == claim_id, ClaimForm.form_type == body.form_type)
    )).scalar_one_or_none()
    if cf is None:
        raise HTTPException(status_code=404, detail="Form not built yet")
    cf.fields = body.fields
    cf.edits = validate_form(body.form_type, body.fields)
    cf.status = "draft"
    cf.updated_at = _now()
    await db.commit()
    await db.refresh(cf)
    return await _serialize(cf)


@router.post("/{claim_id}/approve")
async def approve_claim_form(
    claim_id: str,
    form_type: str = Query("cms1500"),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    await _load_claim_scoped(db, claim_id, current_user)
    from src.infrastructure.database.models import ClaimForm  # noqa: PLC0415
    cf = (await db.execute(
        select(ClaimForm).where(ClaimForm.claim_id == claim_id, ClaimForm.form_type == form_type)
    )).scalar_one_or_none()
    if cf is None:
        raise HTTPException(status_code=404, detail="Form not built yet")
    errors = [e for e in (cf.edits or []) if e.get("severity") == "error"]
    if errors:
        raise HTTPException(status_code=400,
                            detail=f"Cannot approve: {len(errors)} blocking error(s) remain.")
    cf.status = "approved"
    cf.updated_at = _now()
    await db.commit()
    await db.refresh(cf)
    return await _serialize(cf)


@router.post("/lookup-npi")
async def lookup_npi(
    body: NpiLookupRequest,
    current_user: dict = Depends(get_current_user),
):
    """NPPES passthrough used by the review screen's 'enrich' action."""
    if body.npi:
        res = await nppes.lookup_npi(body.npi)
    elif body.organization_name:
        res = await nppes.lookup_organization(body.organization_name, body.state)
    elif body.first_name and body.last_name:
        res = await nppes.lookup_individual(body.first_name, body.last_name, body.state)
    else:
        raise HTTPException(status_code=400, detail="Provide npi, organization_name, or first+last name")
    if not res:
        raise HTTPException(status_code=404, detail="No NPPES match found")
    return res
