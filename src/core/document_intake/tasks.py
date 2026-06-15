"""Background ingestion of uploaded documents.

Heavy work (OCR of scanned PDFs, LLM classification, storage) runs in a Celery
worker instead of on the HTTP request path, so large scanned documents never hit
the gateway (Cloudflare 524) timeout. Routed to the default 'celery' queue, which
the worker already consumes.
"""
from __future__ import annotations

import asyncio
import base64
import uuid as _uuid

import structlog
from celery import shared_task

logger = structlog.get_logger()

PATIENT_TYPES = {"eligibility_benefits", "progress_note", "fee_schedule", "ehr_export", "eob_era"}


def _run(coro):
    """Run an async coroutine synchronously inside a Celery worker (py3.12-safe)."""
    return asyncio.run(coro)


async def _ingest(data: bytes, filename: str, practice_id, added_by_id, global_scope: bool) -> dict:
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession  # noqa: PLC0415
    from sqlalchemy.pool import NullPool  # noqa: PLC0415
    from src.config import get_settings  # noqa: PLC0415
    from src.core.knowledge import service as kb  # noqa: PLC0415
    from src.core.document_intake import service as di  # noqa: PLC0415

    pid = _uuid.UUID(practice_id) if practice_id else None
    aid = _uuid.UUID(added_by_id) if added_by_id else None

    text = kb.extract_text_from_file(filename, data)  # OCRs scanned / glyph-garbage PDFs
    if not text:
        raise ValueError("No text could be extracted from the document.")
    parsed = await di.classify_and_extract(text)

    # Task-local engine (NullPool) created INSIDE this asyncio.run() loop. Sharing the
    # module-level engine's pooled asyncpg connections across Celery's per-task event
    # loops raises "Future attached to a different loop"; a fresh NullPool engine that
    # we dispose at the end keeps every connection within this one loop.
    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as db:
            if parsed.get("doc_type") in PATIENT_TYPES:
                res = await di.ingest_patient_document(
                    db, practice_id=pid, filename=filename,
                    added_by_id=aid, text=text, parsed=parsed)
                res["kind"] = "patient_document"
            else:
                ref = await kb.ingest_text(
                    db, practice_id=(None if global_scope else pid),
                    title=filename, content=text, added_by_id=aid)
                res = {"kind": "reference", "title": ref.title,
                       "char_count": ref.char_count, "tags": ref.tags, "summary": ref.summary}
            await db.commit()
    finally:
        await engine.dispose()
    logger.info("document_ingested_async", filename=filename, kind=res.get("kind"),
                duplicate=res.get("duplicate"))
    return res


@shared_task(name="src.core.document_intake.tasks.ingest_document",
             bind=True, max_retries=1, default_retry_delay=30)
def ingest_document(self, *, file_b64: str, filename: str, practice_id=None,
                    added_by_id=None, global_scope: bool = False) -> dict:
    data = base64.b64decode(file_b64)
    return _run(_ingest(data, filename, practice_id, added_by_id, bool(global_scope)))
