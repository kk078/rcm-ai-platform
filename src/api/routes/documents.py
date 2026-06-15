"""Document management routes — upload, list, download."""
from __future__ import annotations
import uuid
from typing import Any
from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from src.infrastructure.database.session import get_db
from src.infrastructure.auth.middleware import get_current_user
from src.infrastructure.database.models import DocumentAttachment, User
from src.core.documents.service import store_document, get_document_url

router = APIRouter(prefix="/documents", tags=["Documents"])

ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpeg",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
}


class DocumentResponse(BaseModel):
    id: uuid.UUID
    entity_type: str
    entity_id: uuid.UUID
    file_name: str
    file_size: int | None
    mime_type: str | None
    document_type: str | None
    description: str | None
    is_phi: bool
    created_at: Any
    download_url: str | None = None

    class Config:
        from_attributes = True


@router.get("", response_model=list[DocumentResponse], summary="List recent documents")
async def list_documents(
    entity_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List recent documents for the practice, optionally filtered by entity type."""
    stmt = select(DocumentAttachment).where(
        DocumentAttachment.practice_id == current_user.get("practice_id")
    )
    if entity_type:
        stmt = stmt.where(DocumentAttachment.entity_type == entity_type)
    stmt = stmt.order_by(desc(DocumentAttachment.created_at)).limit(limit)
    result = await db.execute(stmt)
    docs = result.scalars().all()
    responses = []
    for doc in docs:
        r = DocumentResponse.model_validate(doc)
        try:
            r.download_url = await get_document_url(doc.storage_key)
        except Exception:
            r.download_url = None
        responses.append(r)
    return responses


@router.post("/upload", response_model=DocumentResponse, status_code=201)
async def upload_document(
    entity_type: str = Form(...),
    entity_id: uuid.UUID = Form(...),
    document_type: str = Form(default="other"),
    description: str | None = Form(default=None),
    is_phi: bool = Form(default=True),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a document and attach it to an entity (claim, denial, appeal, etc.)."""
    if file.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail=f"File type {file.content_type} not allowed")

    content = await file.read()
    if len(content) > 25 * 1024 * 1024:  # 25MB limit
        raise HTTPException(status_code=413, detail="File too large (max 25MB)")

    doc = await store_document(
        db=db,
        practice_id=current_user.get("practice_id"),
        entity_type=entity_type,
        entity_id=entity_id,
        file_name=file.filename,
        file_content=content,
        mime_type=file.content_type,
        document_type=document_type,
        description=description,
        uploaded_by_id=current_user.get("user_id"),
        is_phi=is_phi,
    )
    await db.commit()

    response = DocumentResponse.model_validate(doc)
    response.download_url = await get_document_url(doc.storage_key)
    return response


@router.get("/entity/{entity_type}/{entity_id}", response_model=list[DocumentResponse])
async def list_entity_documents(
    entity_type: str,
    entity_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all documents attached to an entity."""
    result = await db.execute(
        select(DocumentAttachment).where(
            DocumentAttachment.practice_id == current_user.get("practice_id"),
            DocumentAttachment.entity_type == entity_type,
            DocumentAttachment.entity_id == entity_id,
        ).order_by(desc(DocumentAttachment.created_at))
    )
    docs = result.scalars().all()
    responses = []
    for doc in docs:
        r = DocumentResponse.model_validate(doc)
        try:
            r.download_url = await get_document_url(doc.storage_key)
        except Exception:
            r.download_url = None
        responses.append(r)
    return responses


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(
    document_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single document by ID (practice-scoped)."""
    result = await db.execute(
        select(DocumentAttachment).where(
            DocumentAttachment.id == document_id,
            DocumentAttachment.practice_id == current_user.get("practice_id"),
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    r = DocumentResponse.model_validate(doc)
    try:
        r.download_url = await get_document_url(doc.storage_key)
    except Exception:
        r.download_url = None
    return r


@router.delete("/{document_id}", status_code=204)
async def delete_document(
    document_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a document (practice-scoped)."""
    result = await db.execute(
        select(DocumentAttachment).where(
            DocumentAttachment.id == document_id,
            DocumentAttachment.practice_id == current_user.get("practice_id"),
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.delete(doc)
    await db.commit()
