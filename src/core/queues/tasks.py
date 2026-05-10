"""Background tasks for queues — SLA breach monitoring and auto-assignment."""

from celery import shared_task


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def check_sla_breaches(self):
    """Every 30 minutes: check all queues for SLA breaches and mark overdue items.

    Uses QueueService.check_and_mark_sla_breaches() for each active practice.
    """
    import structlog

    logger = structlog.get_logger("queues.tasks")

    try:
        import asyncio
        asyncio.get_event_loop().run_until_complete(_check_sla_breaches())
    except Exception as exc:
        logger.error("sla_breach_check_failed", error=str(exc))
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def auto_assign_pending_items(self):
    """Every 10 minutes: auto-assign pending queue items across all practices.

    Distributes unassigned items to available staff via round-robin.
    """
    import structlog

    logger = structlog.get_logger("queues.tasks")

    try:
        import asyncio
        asyncio.get_event_loop().run_until_complete(_auto_assign_items())
    except Exception as exc:
        logger.error("auto_assign_failed", error=str(exc))
        raise self.retry(exc=exc)


async def _check_sla_breaches():
    """Async implementation of SLA breach check."""
    from src.infrastructure.database.session import async_session_factory
    from src.core.queues.service import queue_service
    from src.infrastructure.database.models import Practice
    from sqlalchemy import select
    import structlog

    logger = structlog.get_logger("queues.tasks")

    async with async_session_factory() as db:
        result = await db.execute(
            select(Practice.id).where(Practice.status == "active")
        )
        practice_ids = [row[0] for row in result.all()]

        total_breached = 0
        for practice_id in practice_ids:
            try:
                newly_breached = await queue_service.check_and_mark_sla_breaches(
                    db=db, practice_id=practice_id,
                )
                total_breached += newly_breached
            except Exception as exc:
                logger.warning("sla_check_skipped", practice_id=str(practice_id), error=str(exc))

        await db.commit()
        logger.info("sla_breach_check_complete", practices_checked=len(practice_ids), newly_breached=total_breached)


async def _auto_assign_items():
    """Async implementation of auto-assignment."""
    from src.infrastructure.database.session import async_session_factory
    from src.core.queues.service import queue_service
    from src.infrastructure.database.models import Practice
    from sqlalchemy import select
    import structlog

    logger = structlog.get_logger("queues.tasks")
    queue_types = ["intake", "coding", "billing", "posting", "denial", "follow_up"]

    async with async_session_factory() as db:
        result = await db.execute(
            select(Practice.id).where(Practice.status == "active")
        )
        practice_ids = [row[0] for row in result.all()]

        total_assigned = 0
        for practice_id in practice_ids:
            for qt in queue_types:
                try:
                    result = await queue_service.auto_assign(
                        db=db, user_id=None,  # System task
                        practice_id=practice_id, queue_type=qt,
                    )
                    total_assigned += result.get("assigned_count", 0)
                except Exception as exc:
                    logger.warning("auto_assign_skipped", practice_id=str(practice_id), queue_type=qt, error=str(exc))

        await db.commit()
        logger.info("auto_assign_complete", total_assigned=total_assigned)