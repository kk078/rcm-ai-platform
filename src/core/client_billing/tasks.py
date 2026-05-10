"""Background tasks for client billing — overdue invoice detection."""

from celery import shared_task


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def mark_overdue_invoices(self):
    """Daily task: mark invoices past their due date as overdue.

    Scans all sent/viewed invoices whose due_date has passed
    and updates their status to 'overdue'.
    """
    import structlog

    logger = structlog.get_logger("client_billing.tasks")

    try:
        import asyncio
        asyncio.get_event_loop().run_until_complete(_mark_overdue_invoices())
    except Exception as exc:
        logger.error("overdue_invoice_check_failed", error=str(exc))
        raise self.retry(exc=exc)


@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def generate_monthly_invoices(self, billing_period_start: str, billing_period_end: str):
    """Generate invoices for all active practices for a billing period.

    Args:
        billing_period_start: Start date in YYYY-MM-DD format.
        billing_period_end: End date in YYYY-MM-DD format.
    """
    import structlog

    logger = structlog.get_logger("client_billing.tasks")

    try:
        import asyncio
        asyncio.get_event_loop().run_until_complete(
            _generate_monthly_invoices(billing_period_start, billing_period_end)
        )
    except Exception as exc:
        logger.error("monthly_invoice_generation_failed", error=str(exc))
        raise self.retry(exc=exc)


async def _mark_overdue_invoices():
    """Async implementation of overdue invoice marking."""
    from datetime import date
    from src.infrastructure.database.session import async_session_factory
    from src.infrastructure.database.models import ClientInvoice
    from sqlalchemy import select, update
    import structlog

    logger = structlog.get_logger("client_billing.tasks")
    today = date.today()

    async with async_session_factory() as db:
        # Update sent/viewed invoices past their due date to 'overdue'
        result = await db.execute(
            update(ClientInvoice)
            .where(
                ClientInvoice.status.in_(["sent", "viewed"]),
                ClientInvoice.due_date < today,
            )
            .values(status="overdue")
        )
        count = result.rowcount
        await db.commit()
        logger.info("overdue_invoices_marked", count=count)


async def _generate_monthly_invoices(billing_period_start: str, billing_period_end: str):
    """Async implementation of monthly invoice generation."""
    from datetime import date
    from uuid import uuid4
    from src.infrastructure.database.session import async_session_factory
    from src.core.client_billing.service import billing_service
    import structlog

    logger = structlog.get_logger("client_billing.tasks")
    start = date.fromisoformat(billing_period_start)
    end = date.fromisoformat(billing_period_end)

    # Use a system user ID for automated tasks
    system_user_id = uuid4()

    async with async_session_factory() as db:
        try:
            invoices = await billing_service.generate_batch_invoices(
                db=db, user_id=system_user_id,
                billing_period_start=start, billing_period_end=end,
            )
            await db.commit()
            logger.info("monthly_invoices_generated", count=len(invoices))
        except Exception as exc:
            logger.error("monthly_invoice_generation_error", error=str(exc))
            raise