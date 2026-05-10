"""Background tasks for payments — daily reconciliation and ERA processing."""

from celery import shared_task


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def process_era_file(self, batch_id: str):
    """Process an uploaded ERA/835 file.

    Args:
        batch_id: UUID of the PaymentBatch to process.
    """
    import structlog

    logger = structlog.get_logger("payments.tasks")

    try:
        import asyncio
        asyncio.get_event_loop().run_until_complete(_process_era(batch_id))
    except Exception as exc:
        logger.error("era_processing_failed", batch_id=batch_id, error=str(exc))
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def daily_reconciliation(self):
    """Daily task: generate reconciliation reports for all active practices.

    Identifies unmatched payments, underpayments, and posting discrepancies.
    """
    import structlog

    logger = structlog.get_logger("payments.tasks")

    try:
        import asyncio
        asyncio.get_event_loop().run_until_complete(_daily_reconciliation())
    except Exception as exc:
        logger.error("daily_reconciliation_failed", error=str(exc))
        raise self.retry(exc=exc)


async def _process_era(batch_id: str):
    """Async implementation of ERA file processing."""
    from uuid import UUID
    from src.infrastructure.database.session import async_session_factory
    from src.core.payments.service import payment_service
    import structlog

    logger = structlog.get_logger("payments.tasks")

    async with async_session_factory() as db:
        try:
            result = await payment_service.post_batch(
                db=db, batch_id=UUID(batch_id),
                user_id=None,  # System task
            )
            await db.commit()
            logger.info("era_processing_complete", batch_id=batch_id)
        except Exception as exc:
            logger.error("era_processing_error", batch_id=batch_id, error=str(exc))
            raise


async def _daily_reconciliation():
    """Async implementation of daily reconciliation."""
    from src.infrastructure.database.session import async_session_factory
    from src.core.payments.service import payment_service
    from src.infrastructure.database.models import Practice
    from sqlalchemy import select
    from datetime import date
    import structlog

    logger = structlog.get_logger("payments.tasks")

    async with async_session_factory() as db:
        # Get all active practices
        result = await db.execute(
            select(Practice.id).where(Practice.status == "active")
        )
        practice_ids = [row[0] for row in result.all()]

        total_reconciled = 0
        for practice_id in practice_ids:
            try:
                report = await payment_service.get_reconciliation_report(
                    db=db, practice_id=practice_id,
                )
                total_reconciled += 1
            except Exception as exc:
                logger.warning("reconciliation_skipped", practice_id=str(practice_id), error=str(exc))

        logger.info("daily_reconciliation_complete", practices_reconciled=total_reconciled)