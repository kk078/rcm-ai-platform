"""Knowledge base routes — manage reference material the AI assistant + agents cite.

Add references by URL (fetched server-side) or pasted text; list, search, refresh, archive.
Store NON-PHI guidance only (CMS / USA.gov / payer policy pages, coding rules).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.session import get_db
from src.infrastructure.auth.middleware import get_current_user
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
    fetched_at: Any = None
    created_at: Any = None

    class Config:
        from_attributes = True


def _practice(current_user: dict, global_scope: bool) -> uuid.UUID | None:
    return None if global_scope else current_user.get("practice_id")


@router.post("/", response_model=ReferenceResponse)
async def add_reference(
    body: AddReferenceRequest,
    current_user: dict = Depends(get_current_user),
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
    current_user: dict = Depends(get_current_user),
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
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    ok = await kb.delete_reference(db, ref_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Reference not found.")
    await db.commit()
    return {"status": "archived", "id": str(ref_id)}
