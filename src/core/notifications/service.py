"""Multi-channel notification service — portal, email, SMS (Twilio)."""
from __future__ import annotations
import uuid
from typing import Any
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.infrastructure.database.models import NotificationLog, User

logger = structlog.get_logger()


async def send_notification(
    db: AsyncSession,
    event_type: str,
    channels: list[str],
    recipient_user_id: uuid.UUID | None = None,
    recipient_email: str | None = None,
    recipient_phone: str | None = None,
    subject: str = "",
    body: str = "",
    entity_type: str | None = None,
    entity_id: uuid.UUID | None = None,
    practice_id: uuid.UUID | None = None,
) -> list[NotificationLog]:
    """Send notification via one or more channels. Returns log records."""
    logs = []
    for channel in channels:
        log = NotificationLog(
            practice_id=practice_id,
            user_id=recipient_user_id,
            event_type=event_type,
            channel=channel,
            subject=subject,
            body=body,
            entity_type=entity_type,
            entity_id=entity_id,
        )
        try:
            if channel == "portal":
                # Portal notifications already handled by PortalNotification model
                log.status = "sent"
                log.recipient = str(recipient_user_id) if recipient_user_id else None

            elif channel == "email":
                email = recipient_email
                if not email and recipient_user_id:
                    result = await db.execute(select(User).where(User.id == recipient_user_id))
                    user = result.scalar_one_or_none()
                    email = user.email if user else None
                if email:
                    await _send_email(email, subject, body)
                    log.recipient = email
                    log.status = "sent"
                else:
                    log.status = "failed"
                    log.error_message = "No email address available"

            elif channel == "sms":
                phone = recipient_phone
                if not phone and recipient_user_id:
                    result = await db.execute(select(User).where(User.id == recipient_user_id))
                    user = result.scalar_one_or_none()
                    phone = getattr(user, "phone", None)
                if phone:
                    ext_id = await _send_sms(phone, body)
                    log.recipient = phone
                    log.status = "sent"
                    log.external_id = ext_id
                else:
                    log.status = "failed"
                    log.error_message = "No phone number available"

        except Exception as exc:
            log.status = "failed"
            log.error_message = str(exc)
            logger.error(
                "notification_send_failed",
                channel=channel,
                event_type=event_type,
                error=str(exc),
            )

        db.add(log)
        logs.append(log)

    await db.flush()
    return logs


async def _send_email(to_email: str, subject: str, body: str) -> None:
    """Send email via SMTP. Falls back to logging if not configured."""
    try:
        from src.config import settings
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        smtp_host = getattr(settings, "smtp_host", None)
        smtp_port = getattr(settings, "smtp_port", 587)
        smtp_user = getattr(settings, "smtp_user", None)
        smtp_pass = getattr(settings, "smtp_password", None)
        from_email = getattr(settings, "smtp_from_email", "noreply@aetherahealthcare.com")

        if not smtp_host:
            logger.info("email_not_configured_logging_only", to=to_email, subject=subject)
            return

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email
        msg.attach(MIMEText(body, "plain"))
        msg.attach(MIMEText(f"<pre>{body}</pre>", "html"))

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            if smtp_user and smtp_pass:
                server.login(smtp_user, smtp_pass)
            server.sendmail(from_email, to_email, msg.as_string())
        logger.info("email_sent", to=to_email, subject=subject)
    except Exception as exc:
        logger.error("email_send_failed", to=to_email, error=str(exc))
        raise


async def _send_sms(to_phone: str, body: str) -> str | None:
    """Send SMS via Twilio. Falls back to logging if not configured."""
    try:
        from src.config import settings
        account_sid = getattr(settings, "twilio_account_sid", None)
        auth_token = getattr(settings, "twilio_auth_token", None)
        from_number = getattr(settings, "twilio_from_number", None)

        if not all([account_sid, auth_token, from_number]):
            logger.info("sms_not_configured_logging_only", to=to_phone, body=body[:50])
            return None

        from twilio.rest import Client
        client = Client(account_sid, auth_token)
        message = client.messages.create(body=body[:1600], from_=from_number, to=to_phone)
        logger.info("sms_sent", to=to_phone, sid=message.sid)
        return message.sid
    except Exception as exc:
        logger.error("sms_send_failed", to=to_phone, error=str(exc))
        raise
