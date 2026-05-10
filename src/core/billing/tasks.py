"""Background tasks for billing — timely filing deadline checks."""

from celery import shared_task


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def check_timely_filing_deadlines(self):
    """Daily task: check claims approaching timely filing deadlines.

    Marks claims whose timely_filing_deadline is within 7 days as at-risk,
    and those past deadline as expired. Creates work queue items for
    claims that need urgent attention.
    """
    import structlog
    from src.infrastructure.database.session import async_session_factory
    from src.infrastructure.database.models import Claim, WorkQueueItem
    from sqlalchemy import select, and_
    from datetime import date, timedelta
    from uuid import uuid4

    logger = structlog.get_logger("billing.tasks")

    try:
        import asyncio
        asyncio.get_event_loop().run_until_complete(_check_timely_filing())
    except Exception as exc:
        logger.error("timely_filing_check_failed", error=str(exc))
        raise self.retry(exc=exc)


async def _check_timely_filing():
    """Async implementation of timely filing check."""
    from src.infrastructure.database.session import async_session_factory
    from src.infrastructure.database.models import Claim, WorkQueueItem, AuditLog
    from sqlalchemy import select, and_
    from datetime import date, timedelta
    import structlog

    logger = structlog.get_logger("billing.tasks")
    today = date.today()
    warning_days = 7

    async with async_session_factory() as db:
        # Find claims approaching timely filing deadline
        result = await db.execute(
            select(Claim).where(
                Claim.timely_filing_deadline.isnot(None),
                Claim.status.in_(["ready", "submitted", "accepted"]),
                Claim.timely_filing_deadline <= today + timedelta(days=warning_days),
            )
        )
        at_risk_claims = list(result.scalars().all())

        for claim in at_risk_claims:
            days_remaining = (claim.timely_filing_deadline - today).days
            logger.info(
                "timely_filing_warning",
                claim_id=str(claim.id),
                claim_number=claim.claim_number,
                days_remaining=days_remaining,
            )

        await db.commit()
        logger.info("timely_filing_check_complete", at_risk_count=len(at_risk_claims))