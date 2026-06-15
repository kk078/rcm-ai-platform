"""Document management service — file storage with Cloudflare R2 / local fallback."""
from __future__ import annotations
import uuid
import os
from pathlib import Path
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = structlog.get_logger()

UPLOAD_DIR = Path("/app/uploads/documents")


async def store_document(
    db: AsyncSession,
    practice_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
    file_name: str,
    file_content: bytes,
    mime_type: str,
    document_type: str = "other",
    description: str | None = None,
    uploaded_by_id: uuid.UUID | None = None,
    is_phi: bool = True,
) -> "DocumentAttachment":
    """Store a document and create a DocumentAttachment record."""
    from src.infrastructure.database.models import DocumentAttachment

    storage_key = (
        f"{practice_id}/{entity_type}/{entity_id}/{uuid.uuid4()}_{file_name}"
    )

    # Try R2/S3 first; fall back to local filesystem
    storage_url = None
    try:
        storage_url = await _upload_to_r2(storage_key, file_content, mime_type)
        logger.info("document_stored_r2", key=storage_key, size=len(file_content))
    except Exception as exc:
        logger.warning("r2_upload_failed_using_local", key=storage_key, error=str(exc))
        _save_local(storage_key, file_content)

    doc = DocumentAttachment(
        practice_id=practice_id,
        entity_type=entity_type,
        entity_id=entity_id,
        file_name=file_name,
        file_size=len(file_content),
        mime_type=mime_type,
        storage_key=storage_key,
        storage_url=storage_url,
        document_type=document_type,
        description=description,
        uploaded_by_id=uploaded_by_id,
        is_phi=is_phi,
    )
    db.add(doc)
    await db.flush()
    return doc


async def get_document_url(storage_key: str) -> str:
    """Get a short-lived signed URL for a document."""
    try:
        return await _get_r2_signed_url(storage_key)
    except Exception:
        return f"/api/v1/documents/download/{storage_key}"


async def list_entity_documents(
    db: AsyncSession,
    practice_id: uuid.UUID,
    entity_type: str,
    entity_id: uuid.UUID,
) -> list:
    """List all documents attached to a given entity."""
    from src.infrastructure.database.models import DocumentAttachment

    result = await db.execute(
        select(DocumentAttachment).where(
            DocumentAttachment.practice_id == practice_id,
            DocumentAttachment.entity_type == entity_type,
            DocumentAttachment.entity_id == entity_id,
        ).order_by(DocumentAttachment.created_at.desc())
    )
    return result.scalars().all()


async def delete_document(
    db: AsyncSession,
    document_id: uuid.UUID,
    practice_id: uuid.UUID,
) -> dict:
    """Delete a document attachment record (does not remove from storage)."""
    from src.infrastructure.database.models import DocumentAttachment

    result = await db.execute(
        select(DocumentAttachment).where(
            DocumentAttachment.id == document_id,
            DocumentAttachment.practice_id == practice_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        return {"error": "Document not found"}

    storage_key = doc.storage_key
    await db.delete(doc)
    await db.flush()
    logger.info("document_deleted", document_id=str(document_id), key=storage_key)
    return {"deleted": True, "storage_key": storage_key}


async def _upload_to_r2(key: str, content: bytes, mime_type: str) -> str:
    """Upload to Cloudflare R2 using boto3-compatible S3 SDK."""
    from src.config import settings
    import boto3
    from botocore.config import Config

    r2_account_id = getattr(settings, "r2_account_id", None)
    r2_access_key = getattr(settings, "r2_access_key_id", None)
    r2_secret = getattr(settings, "r2_secret_access_key", None)
    r2_bucket = getattr(settings, "r2_bucket_name", "aethera-documents")

    if not all([r2_account_id, r2_access_key, r2_secret]):
        raise ValueError("R2 not configured — missing account_id, access_key, or secret")

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=r2_access_key,
        aws_secret_access_key=r2_secret,
        config=Config(signature_version="s3v4"),
    )
    s3.put_object(Bucket=r2_bucket, Key=key, Body=content, ContentType=mime_type)
    return f"https://{r2_bucket}.{r2_account_id}.r2.cloudflarestorage.com/{key}"


async def _get_r2_signed_url(key: str, expires: int = 3600) -> str:
    """Generate a presigned GET URL for a stored document."""
    from src.config import settings
    import boto3
    from botocore.config import Config

    r2_account_id = getattr(settings, "r2_account_id", None)
    r2_access_key = getattr(settings, "r2_access_key_id", None)
    r2_secret = getattr(settings, "r2_secret_access_key", None)
    r2_bucket = getattr(settings, "r2_bucket_name", "aethera-documents")

    if not all([r2_account_id, r2_access_key, r2_secret]):
        raise ValueError("R2 not configured")

    s3 = boto3.client(
        "s3",
        endpoint_url=f"https://{r2_account_id}.r2.cloudflarestorage.com",
        aws_access_key_id=r2_access_key,
        aws_secret_access_key=r2_secret,
        config=Config(signature_version="s3v4"),
    )
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": r2_bucket, "Key": key},
        ExpiresIn=expires,
    )


def _save_local(key: str, content: bytes) -> None:
    """Local filesystem fallback for development/testing."""
    path = UPLOAD_DIR / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    logger.info("document_saved_local", key=key, size=len(content))
