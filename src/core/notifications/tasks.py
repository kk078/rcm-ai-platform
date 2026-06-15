"""Celery tasks for notification delivery."""
from __future__ import annotations
import asyncio
import structlog
from celery import shared_task

logger = structlog.get_logger()


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_sla_breach_notifications(self):
    """Check for SLA breaches and send multi-channel alerts."""
    try:
        asyncio.get_event_loop().run_until_complete(_check_and_notify_sla_breaches())
    except Exception as exc:
        logger.error("sla_breach_notification_failed", error=str(exc))
        raise self.retry(exc=exc)


async def _check_and_notify_sla_breaches():
    from datetime import datetime, timedelta
    from sqlalchemy import select
    from src.infrastructure.database.session import async_session as async_session_factory
    from src.infrastructure.database.models import WorkQueueItem, NotificationRule
    from src.core.notifications.service import send_notification

    async with async_session_factory() as db:
        now = datetime.utcnow()

        # Find items breaching SLA (due_date passed, still open)
        result = await db.execute(
            select(WorkQueueItem).where(
                WorkQueueItem.status == "open",
                WorkQueueItem.due_date < now,
            ).limit(100)
        )
        breached = result.scalars().all()

        for item in breached:
            await send_notification(
                db=db,
                event_type="sla_breach",
                channels=["portal", "email"],
                subject=f"SLA Breach: {item.item_type} queue item overdue",
                body=(
                    f"Work queue item (type: {item.item_type}, priority: {item.priority}) "
                    f"has breached SLA. Due: {item.due_date}. Immediate action required."
                ),
                entity_type="work_queue_item",
                entity_id=item.id,
                practice_id=item.practice_id,
            )
        await db.commit()
        logger.info("sla_breach_notifications_sent", count=len(breached))


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_denial_deadline_alerts(self):
    """Alert analysts of approaching denial/appeal deadlines."""
    try:
        asyncio.get_event_loop().run_until_complete(_check_denial_deadlines())
    except Exception as exc:
        raise self.retry(exc=exc)


async def _check_denial_deadlines():
    from datetime import datetime, timedelta, date
    from sqlalchemy import select
    from src.infrastructure.database.session import async_session as async_session_factory
    from src.infrastructure.database.models import Appeal
    from src.core.notifications.service import send_notification

    async with async_session_factory() as db:
        today = date.today()
        warning_date = today + timedelta(days=3)

        result = await db.execute(
            select(Appeal).where(
                Appeal.status == "pending",
                Appeal.deadline <= warning_date,
                Appeal.deadline >= today,
            ).limit(50)
        )
        appeals = result.scalars().all()

        for appeal in appeals:
            days_left = (appeal.deadline - today).days
            await send_notification(
                db=db,
                event_type="appeal_deadline",
                channels=["portal", "sms"],
                subject=f"Appeal Deadline in {days_left} day(s)",
                body=(
                    f"Appeal deadline approaching in {days_left} day(s) on {appeal.deadline}. "
                    f"Immediate action required."
                ),
                entity_type="appeal",
                entity_id=appeal.id,
            )
        await db.commit()
        logger.info("denial_deadline_alerts_sent", count=len(appeals))
