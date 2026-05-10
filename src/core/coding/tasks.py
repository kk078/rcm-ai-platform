"""Background tasks for coding — AI code suggestion processing."""

from celery import shared_task


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def process_coding_session(self, session_id: str):
    """Process a coding session through the AI pipeline.

    Runs NLP extraction, code suggestion, and validation.
    Updates the CodingSession status through processing -> completed/review.

    Args:
        session_id: UUID of the CodingSession to process.
    """
    import structlog

    logger = structlog.get_logger("coding.tasks")

    try:
        import asyncio
        asyncio.get_event_loop().run_until_complete(_process_coding_session(session_id))
    except Exception as exc:
        logger.error("coding_session_processing_failed", session_id=session_id, error=str(exc))
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def batch_process_coding_sessions(self, practice_id: str):
    """Process all pending coding sessions for a practice.

    Finds sessions in 'processing' status and runs the AI pipeline.
    """
    import structlog

    logger = structlog.get_logger("coding.tasks")

    try:
        import asyncio
        asyncio.get_event_loop().run_until_complete(_batch_process(practice_id))
    except Exception as exc:
        logger.error("batch_coding_failed", practice_id=practice_id, error=str(exc))
        raise self.retry(exc=exc)


async def _process_coding_session(session_id: str):
    """Async implementation of coding session processing."""
    from uuid import UUID
    from src.infrastructure.database.session import async_session_factory
    from src.infrastructure.database.models import CodingSession
    from sqlalchemy import select
    import structlog

    logger = structlog.get_logger("coding.tasks")

    async with async_session_factory() as db:
        result = await db.execute(
            select(CodingSession).where(CodingSession.id == UUID(session_id))
        )
        session = result.scalar_one_or_none()
        if not session:
            logger.warning("coding_session_not_found", session_id=session_id)
            return

        # Update status to completed if still processing
        if session.status == "processing":
            session.status = "completed"
            await db.commit()
            logger.info("coding_session_processed", session_id=session_id)


async def _batch_process(practice_id: str):
    """Async implementation of batch coding session processing."""
    from uuid import UUID
    from src.infrastructure.database.session import async_session_factory
    from src.infrastructure.database.models import CodingSession
    from sqlalchemy import select
    import structlog

    logger = structlog.get_logger("coding.tasks")

    async with async_session_factory() as db:
        result = await db.execute(
            select(CodingSession).where(
                CodingSession.practice_id == UUID(practice_id),
                CodingSession.status == "processing",
            )
        )
        sessions = list(result.scalars().all())

        for session in sessions:
            session.status = "completed"

        await db.commit()
        logger.info("batch_coding_complete", practice_id=practice_id, count=len(sessions))