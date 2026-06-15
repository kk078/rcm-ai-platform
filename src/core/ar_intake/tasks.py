"""Celery task: throttled AI triage of imported open-AR items (beat, every 10 min)."""
from __future__ import annotations

import asyncio

import structlog
from celery import shared_task

logger = structlog.get_logger()


def _run(coro):
    return asyncio.run(coro)


async def _triage(limit: int) -> dict:
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession  # noqa: PLC0415
    from sqlalchemy.pool import NullPool  # noqa: PLC0415
    from src.config import get_settings  # noqa: PLC0415
    from src.core.ar_intake import triage as t  # noqa: PLC0415

    engine = create_async_engine(get_settings().database_url, poolclass=NullPool)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with Session() as db:
            res = await t.triage_pending(db, limit=limit)
            await db.commit()
            return res
    finally:
        await engine.dispose()


@shared_task(name="src.core.ar_intake.tasks.triage_open_ar", bind=True,
             max_retries=1, default_retry_delay=60)
def triage_open_ar(self, limit: int = 100) -> dict:
    res = _run(_triage(int(limit)))
    logger.info("ar_triage_task_done", **res)
    return res
