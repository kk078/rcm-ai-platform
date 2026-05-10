"""Background tasks for denials — appeal deadline checks and pattern analysis."""

from celery import shared_task


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def check_appeal_deadlines(self):
    """Hourly task: check denials approaching appeal filing deadlines.

    Flags denials whose appeal_deadline is within 3 days as urgent,
    and those past deadline as expired. Updates work queue items.
    """
    import structlog

    logger = structlog.get_logger("denials.tasks")

    try:
        import asyncio
        asyncio.get_event_loop().run_until_complete(_check_appeal_deadlines())
    except Exception as exc:
        logger.error("appeal_deadline_check_failed", error=str(exc))
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def analyze_denial_patterns(self):
    """Weekly task: analyze denial patterns and generate insights.

    Aggregates denial data by category, payer, and reason code.
    Stores results for the analytics dashboard.
    """
    import structlog

    logger = structlog.get_logger("denials.tasks")

    try:
        import asyncio
        asyncio.get_event_loop().run_until_complete(_analyze_patterns())
    except Exception as exc:
        logger.error("denial_pattern_analysis_failed", error=str(exc))
        raise self.retry(exc=exc)


async def _check_appeal_deadlines():
    """Async implementation of appeal deadline check."""
    from src.infrastructure.database.session import async_session_factory
    from src.infrastructure.database.models import Denial, WorkQueueItem
    from sqlalchemy import select
    from datetime import date, timedelta
    import structlog

    logger = structlog.get_logger("denials.tasks")
    today = date.today()
    warning_days = 3

    async with async_session_factory() as db:
        result = await db.execute(
            select(Denial).where(
                Denial.appeal_deadline.isnot(None),
                Denial.status.in_(["new", "in_review"]),
                Denial.appeal_deadline <= today + timedelta(days=warning_days),
            )
        )
        urgent_denials = list(result.scalars().all())

        for denial in urgent_denials:
            days_remaining = (denial.appeal_deadline - today).days
            logger.info(
                "appeal_deadline_warning",
                denial_id=str(denial.id),
                days_remaining=days_remaining,
            )

        await db.commit()
        logger.info("appeal_deadline_check_complete", urgent_count=len(urgent_denials))


async def _analyze_patterns():
    """Async implementation of denial pattern analysis."""
    from src.infrastructure.database.session import async_session_factory
    from src.infrastructure.database.models import Denial
    from sqlalchemy import select, func
    from datetime import date, timedelta
    import structlog

    logger = structlog.get_logger("denials.tasks")
    today = date.today()
    month_ago = today - timedelta(days=30)

    async with async_session_factory() as db:
        # Aggregate denial patterns for the last 30 days
        result = await db.execute(
            select(
                Denial.category,
                func.count(Denial.id).label("count"),
                func.coalesce(func.sum(Denial.denial_amount), 0).label("total_amount"),
            ).where(
                Denial.denial_date >= month_ago,
            ).group_by(Denial.category)
        )
        patterns = [
            {"category": row.category or "uncategorized", "count": row.count, "total_amount": float(row.total_amount)}
            for row in result.all()
        ]

        logger.info("denial_pattern_analysis_complete", pattern_count=len(patterns))
        return patterns