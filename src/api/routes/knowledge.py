"""Knowledge base routes — manage reference material the AI assistant + agents cite.

Add references by URL (fetched server-side) or pasted text; list, search, refresh, archive.
Store NON-PHI guidance only (CMS / USA.gov / payer policy pages, coding rules).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, File, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.session import get_db
from src.infrastructure.auth.middleware import get_current_user
from src.core.rbac import require_super_admin
from src.core.knowledge import service as kb

logger = structlog.get_logger()
router = APIRouter(prefix="/knowledge", tags=["Knowledge Base"])


class AddReferenceRequest(BaseModel):
    url: str | None = None
    title: str | None = None
    content: str | None = None
    tags: list[str] | None = None
    global_scope: bool = False  # if true, store unscoped (visible to all practices)


class ReferenceResponse(BaseModel):
    id: uuid.UUID
    title: str
    url: str | None = None
    source_type: str
    char_count: int
    status: str
    tags: list[str] | None = None
    summary: str | None = None
    fetched_at: Any = None
    created_at: Any = None

    class Config:
        from_attributes = True


def _practice(current_user: dict, global_scope: bool) -> uuid.UUID | None:
    return None if global_scope else current_user.get("practice_id")


@router.post("/", response_model=ReferenceResponse)
async def add_reference(
    body: AddReferenceRequest,
    current_user: dict = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Add a reference by URL (fetched server-side) or by pasted text."""
    practice_id = _practice(current_user, body.global_scope)
    added_by = current_user.get("user_id")
    try:
        if body.url and not body.content:
            ref = await kb.ingest_url(db, practice_id=practice_id, url=body.url,
                                      added_by_id=added_by, tags=body.tags, title=body.title)
        elif body.content:
            ref = await kb.ingest_text(db, practice_id=practice_id, title=body.title or "Pasted reference",
                                       content=body.content, url=body.url, added_by_id=added_by, tags=body.tags)
        else:
            raise HTTPException(status_code=422, detail="Provide a 'url' or 'content'.")
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.warning("knowledge_ingest_failed", url=body.url, error=str(e))
        raise HTTPException(status_code=502, detail=f"Could not fetch/ingest the reference: {e}")
    await db.commit()
    return ref


@router.post("/upload")
async def upload_reference(
    file: UploadFile = File(...),
    global_scope: bool = False,
    current_user: dict = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """Upload a document. Patient PHI documents (eligibility/benefits, progress notes, fee
    schedules, EHR exports, EOB/ERA) are routed to the patient-document intake pipeline
    (operational tables). Everything else is stored as reference material in the knowledge base."""
    from src.core.document_intake import service as di  # noqa: PLC0415
    data = await file.read()
    if not data:
        raise HTTPException(status_code=422, detail="Empty file.")
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 15 MB).")
    fname = file.filename or "upload"
    try:
        text = kb.extract_text_from_file(fname, data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.warning("knowledge_upload_extract_failed", filename=fname, error=str(e))
        raise HTTPException(status_code=502, detail=f"Could not read the file: {e}")

    parsed = await di.classify_and_extract(text)
    PATIENT_TYPES = {"eligibility_benefits", "progress_note", "fee_schedule", "ehr_export", "eob_era"}
    try:
        if parsed.get("doc_type") in PATIENT_TYPES:
            res = await di.ingest_patient_document(
                db, practice_id=current_user.get("practice_id"), filename=fname,
                added_by_id=current_user.get("user_id"), text=text, parsed=parsed)
            await db.commit()
            tags = [parsed.get("doc_type")] + (["duplicate"] if res.get("duplicate") else [])
            summ = res.get("message") or res.get("summary") or ""
            if res.get("eligibility_check_id"):
                summ = (summ + " Created an eligibility/benefits record linked to the patient.").strip()
            return {"kind": "patient_document", "title": fname, "char_count": len(text),
                    "tags": tags, "summary": summ, **res}
        ref = await kb.ingest_text(db, practice_id=_practice(current_user, global_scope),
                                   title=fname, content=text, added_by_id=current_user.get("user_id"))
        await db.commit()
        return {"kind": "reference", "title": ref.title, "char_count": ref.char_count,
                "tags": ref.tags, "summary": ref.summary}
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.warning("knowledge_upload_failed", filename=fname, error=str(e))
        raise HTTPException(status_code=502, detail=f"Could not ingest the file: {e}")

@router.get("/", response_model=list[ReferenceResponse])
async def list_references(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await kb.list_references(db, practice_id=current_user.get("practice_id"))


@router.get("/search", response_model=list[ReferenceResponse])
async def search_references(
    q: str = Query(..., min_length=2),
    limit: int = Query(default=5, ge=1, le=20),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await kb.search_references(db, practice_id=current_user.get("practice_id"), query=q, limit=limit)


@router.get("/{ref_id}", response_model=ReferenceResponse)
async def get_reference(
    ref_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ref = await kb.get_reference(db, ref_id)
    if not ref:
        raise HTTPException(status_code=404, detail="Reference not found.")
    return ref


@router.post("/{ref_id}/refresh", response_model=ReferenceResponse)
async def refresh_reference(
    ref_id: uuid.UUID,
    current_user: dict = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    ref = await kb.get_reference(db, ref_id)
    if not ref:
        raise HTTPException(status_code=404, detail="Reference not found.")
    if not ref.url:
        raise HTTPException(status_code=422, detail="Reference has no URL to refresh.")
    try:
        updated = await kb.ingest_url(db, practice_id=ref.practice_id, url=ref.url,
                                      added_by_id=current_user.get("user_id"), tags=ref.tags, title=ref.title)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Refresh failed: {e}")
    await db.commit()
    return updated


@router.delete("/{ref_id}")
async def delete_reference(
    ref_id: uuid.UUID,
    current_user: dict = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    ok = await kb.delete_reference(db, ref_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Reference not found.")
    await db.commit()
    return {"status": "archived", "id": str(ref_id)}
