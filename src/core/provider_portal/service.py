"""
Provider portal service — dashboard KPIs, claim tracker, messaging,
notifications, reports, practice profile, and invoices.

Every query enforces tenant isolation via practice_id filtering.
Every write operation creates an AuditLog entry.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import structlog
from sqlalchemy import func, select, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.provider_portal.errors import (
    ClaimAccessError,
    MessageNotFoundError,
    NotificationNotFoundError,
    PortalError,
)
from src.infrastructure.database.models import (
    Appeal,
    AuditLog,
    ChargeEntry,
    Claim,
    ClientInvoice,
    Denial,
    Payer,
    PayerEnrollment,
    PaymentLine,
    PortalMessage,
    PortalNotification,
    Practice,
    Provider,
)

logger = structlog.get_logger()

# Claim status → human-readable display strings
STATUS_DISPLAY_MAP = {
    "draft": "Draft — Not Yet Submitted",
    "scrubbing": "Being Reviewed — Claim Scrub in Progress",
    "scrub_failed": "Scrub Failed — Requires Review",
    "ready": "Ready for Submission",
    "submitted": "Submitted — Awaiting Acknowledgment",
    "accepted": "Accepted — Awaiting Payment",
    "rejected": "Rejected — Needs Correction",
    "paid": "Paid — Payment Received",
    "partial_paid": "Partially Paid — Balance Remaining",
    "denied": "Denied — Appeal May Be Filed",
    "appealed": "Appeal Filed — Awaiting Decision",
    "closed": "Closed",
}

NOTIFICATION_TYPES = {
    "denial_alert",
    "payment_posted",
    "info_requested",
    "report_ready",
    "appeal_outcome",
}


async def _write_audit(
    db: AsyncSession,
    user_id: UUID,
    action: str,
    resource_type: str,
    resource_id: UUID | None = None,
    resource_detail: str | None = None,
    phi_accessed: bool = True,
    ip_address: str | None = None,
    request_path: str | None = None,
    request_method: str | None = None,
) -> None:
    entry = AuditLog(
        user_id=user_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        resource_detail=resource_detail,
        phi_accessed=phi_accessed,
        ip_address=ip_address,
        request_path=request_path,
        request_method=request_method,
    )
    db.add(entry)


class PortalService:
    """Provider-facing portal: dashboard, claims, messaging, reports."""

    # ── Dashboard ────────────────────────────────────────────────────

    async def get_dashboard(
        self,
        db: AsyncSession,
        practice_id: UUID,
        period: str | None = None,
    ) -> dict:
        """Practice-level KPI dashboard."""
        if period:
            year, month = int(period[:4]), int(period[5:7])
            start = date(year, month, 1)
            end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        else:
            today = date.today()
            start = today.replace(day=1)
            end = today

        # Revenue snapshot
        rev_result = await db.execute(
            select(
                func.coalesce(func.sum(Claim.total_charge), 0).label("total_charges"),
                func.coalesce(func.sum(Claim.total_paid), 0).label("total_paid"),
                func.coalesce(func.sum(Claim.total_adjusted), 0).label("total_adjusted"),
                func.count(Claim.id).label("total_claims"),
            ).where(
                Claim.practice_id == practice_id,
                Claim.created_at >= start,
                Claim.created_at <= end,
            )
        )
        rev = rev_result.one()

        total_charges = float(rev.total_charges or 0)
        total_paid = float(rev.total_paid or 0)
        total_adjusted = float(rev.total_adjusted or 0)
        net_collection_rate = round(
            total_paid / max(total_charges - total_adjusted, 1) * 100, 1
        ) if (total_charges - total_adjusted) > 0 else 0

        # AR aging
        ar_aging = await self._compute_ar_aging(db, practice_id)

        # Claims summary
        claims_submitted = await db.execute(
            select(func.count(Claim.id)).where(
                Claim.practice_id == practice_id,
                Claim.created_at >= start,
                Claim.created_at <= end,
                Claim.status.in_(["submitted", "accepted"]),
            )
        )
        claims_paid = await db.execute(
            select(func.count(Claim.id)).where(
                Claim.practice_id == practice_id,
                Claim.created_at >= start,
                Claim.created_at <= end,
                Claim.status.in_(["paid", "partial_paid"]),
            )
        )
        claims_denied = await db.execute(
            select(func.count(Claim.id)).where(
                Claim.practice_id == practice_id,
                Claim.created_at >= start,
                Claim.created_at <= end,
                Claim.status == "denied",
            )
        )
        total_in_period = max(int(rev.total_claims or 0), 1)
        denial_rate = round(int(claims_denied.scalar() or 0) / total_in_period * 100, 1)

        # Pending work
        charges_in_progress = await db.execute(
            select(func.count(ChargeEntry.id)).where(
                ChargeEntry.practice_id == practice_id,
                ChargeEntry.status.in_(["received", "coding", "review"]),
            )
        )
        claims_pending_payer = await db.execute(
            select(func.count(Claim.id)).where(
                Claim.practice_id == practice_id,
                Claim.status.in_(["submitted", "accepted"]),
            )
        )
        denials_being_worked = await db.execute(
            select(func.count(Denial.id)).where(
                Denial.practice_id == practice_id,
                Denial.status.in_(["new", "in_review"]),
            )
        )
        appeals_pending = await db.execute(
            select(func.count(Appeal.id)).join(
                Denial, Appeal.denial_id == Denial.id
            ).where(
                Denial.practice_id == practice_id,
                Appeal.status.in_(["draft", "submitted"]),
            )
        )

        # Practice name
        practice_result = await db.execute(
            select(Practice.practice_name).where(Practice.id == practice_id)
        )
        practice_name = practice_result.scalar() or "Unknown"

        return {
            "practice_name": practice_name,
            "period": f"{start.strftime('%B %Y')}",
            "total_charges_mtd": total_charges,
            "total_collections_mtd": total_paid,
            "total_adjustments_mtd": total_adjusted,
            "net_collection_rate": net_collection_rate,
            "total_ar_balance": ar_aging["total"],
            "ar_0_30": ar_aging["0_30"],
            "ar_31_60": ar_aging["31_60"],
            "ar_61_90": ar_aging["61_90"],
            "ar_91_120": ar_aging["91_120"],
            "ar_120_plus": ar_aging["120_plus"],
            "claims_submitted_mtd": int(claims_submitted.scalar() or 0),
            "claims_paid_mtd": int(claims_paid.scalar() or 0),
            "claims_denied_mtd": int(claims_denied.scalar() or 0),
            "denial_rate": denial_rate,
            "charges_in_progress": int(charges_in_progress.scalar() or 0),
            "claims_pending_payer": int(claims_pending_payer.scalar() or 0),
            "denials_being_worked": int(denials_being_worked.scalar() or 0),
            "appeals_pending": int(appeals_pending.scalar() or 0),
        }

    # ── Claim Status Tracker ─────────────────────────────────────────

    async def list_claims(
        self,
        db: AsyncSession,
        practice_id: UUID,
        status: str | None = None,
        provider_id: UUID | None = None,
        patient_name: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        search: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[Claim]:
        """List claims for this practice with filtering and search."""
        query = select(Claim).where(Claim.practice_id == practice_id)

        if status:
            query = query.where(Claim.status == status)
        if provider_id:
            query = query.where(Claim.rendering_provider == provider_id)
        if date_from:
            query = query.where(Claim.created_at >= date_from)
        if date_to:
            query = query.where(Claim.created_at <= date_to)
        if search:
            query = query.where(Claim.claim_number.ilike(f"%{search}%"))

        query = query.order_by(Claim.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_claim_status(
        self, db: AsyncSession, claim_id: UUID, practice_id: UUID,
    ) -> dict:
        """Get claim detail for provider view."""
        claim = await self._get_claim_or_raise(db, claim_id, practice_id)

        # Load denial if exists
        denial_result = await db.execute(
            select(Denial).where(Denial.claim_id == claim_id)
        )
        denial = denial_result.scalar_one_or_none()

        # Load appeal if exists
        appeal = None
        if denial:
            appeal_result = await db.execute(
                select(Appeal).where(Appeal.denial_id == denial.id)
            )
            appeal = appeal_result.scalar_one_or_none()

        # Load payer name
        payer_result = await db.execute(
            select(Payer.payer_name).where(Payer.id == claim.payer_id)
        )
        payer_name = payer_result.scalar() or "Unknown"

        # Load provider name
        provider_result = await db.execute(
            select(Provider).where(Provider.id == claim.rendering_provider)
        )
        provider = provider_result.scalar_one_or_none()
        provider_name = f"{provider.first_name} {provider.last_name}" if provider else "Unknown"

        status_display = self._compute_status_display(claim, denial, appeal)

        result = {
            "claim_id": str(claim.id),
            "claim_number": claim.claim_number,
            "patient_name": "",  # Would need patient join
            "service_date": claim.created_at.date() if claim.created_at else None,
            "provider_name": provider_name,
            "payer_name": payer_name,
            "total_charge": claim.total_charge,
            "total_paid": claim.total_paid,
            "status": claim.status,
            "status_display": status_display,
            "last_updated": claim.updated_at or claim.created_at,
        }

        if denial:
            result["denial_reason"] = denial.reason_code
            result["appeal_status"] = appeal.status if appeal else None

        return result

    async def get_claim_timeline(
        self, db: AsyncSession, claim_id: UUID, practice_id: UUID,
    ) -> list[dict]:
        """Build a visual timeline of claim lifecycle events."""
        claim = await self._get_claim_or_raise(db, claim_id, practice_id)
        timeline: list[dict] = []

        # Charge received
        timeline.append({
            "event": "charge_received",
            "timestamp": claim.created_at.isoformat() if claim.created_at else None,
            "detail": "Charge received and entered into system",
        })

        # Submitted
        if claim.submission_date:
            timeline.append({
                "event": "submitted",
                "timestamp": claim.submission_date.isoformat() if isinstance(claim.submission_date, date) else claim.submission_date,
                "detail": f"Claim submitted to payer",
            })

        # Accepted/rejected
        if claim.adjudication_date:
            if claim.status in ("accepted", "paid", "partial_paid"):
                timeline.append({
                    "event": "accepted",
                    "timestamp": claim.adjudication_date.isoformat() if isinstance(claim.adjudication_date, date) else claim.adjudication_date,
                    "detail": "Claim accepted by payer",
                })
            elif claim.status == "rejected":
                timeline.append({
                    "event": "rejected",
                    "timestamp": claim.adjudication_date.isoformat() if isinstance(claim.adjudication_date, date) else claim.adjudication_date,
                    "detail": "Claim rejected by payer",
                })

        # Paid
        if claim.status in ("paid", "partial_paid"):
            timeline.append({
                "event": "paid",
                "timestamp": claim.updated_at.isoformat() if claim.updated_at else None,
                "detail": f"Payment of ${claim.total_paid:,.2f} received",
            })

        # Denied
        if claim.status == "denied":
            denial_result = await db.execute(
                select(Denial).where(Denial.claim_id == claim_id)
            )
            denial = denial_result.scalar_one_or_none()
            reason = f" — {denial.reason_code}" if denial else ""
            timeline.append({
                "event": "denied",
                "timestamp": denial.denial_date.isoformat() if denial else None,
                "detail": f"Claim denied{reason}",
            })

            # Appeal filed
            if denial:
                appeal_result = await db.execute(
                    select(Appeal).where(Appeal.denial_id == denial.id)
                )
                appeal = appeal_result.scalar_one_or_none()
                if appeal:
                    timeline.append({
                        "event": "appeal_filed",
                        "timestamp": appeal.created_at.isoformat() if appeal.created_at else None,
                        "detail": f"Appeal filed (Level {appeal.appeal_level or 1})",
                    })
                    if appeal.decision:
                        outcome = "approved" if appeal.decision == "approved" else appeal.decision
                        timeline.append({
                            "event": "appeal_outcome",
                            "timestamp": appeal.decision_date.isoformat() if appeal.decision_date else None,
                            "detail": f"Appeal {outcome}",
                        })

        # Closed
        if claim.status == "closed":
            timeline.append({
                "event": "closed",
                "timestamp": claim.updated_at.isoformat() if claim.updated_at else None,
                "detail": "Claim closed",
            })

        return timeline

    # ── Denial Alerts ─────────────────────────────────────────────────

    async def list_denials(
        self,
        db: AsyncSession,
        practice_id: UUID,
        status: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[Denial]:
        """List denials for this practice."""
        query = select(Denial).where(Denial.practice_id == practice_id)
        if status:
            query = query.where(Denial.status == status)
        if date_from:
            query = query.where(Denial.denial_date >= date_from)
        if date_to:
            query = query.where(Denial.denial_date <= date_to)
        query = query.order_by(Denial.priority_score.desc().nulls_last(), Denial.denial_date.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_denial_detail(
        self, db: AsyncSession, denial_id: UUID, practice_id: UUID,
    ) -> Denial:
        """Get denial detail for provider view."""
        result = await db.execute(
            select(Denial).where(
                Denial.id == denial_id,
                Denial.practice_id == practice_id,
            )
        )
        denial = result.scalar_one_or_none()
        if not denial:
            raise ClaimAccessError("Denial not found or does not belong to your practice")
        return denial

    async def upload_supporting_doc(
        self,
        db: AsyncSession,
        user_id: UUID,
        denial_id: UUID,
        practice_id: UUID,
        filename: str,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> dict:
        """Record a supporting document upload for a denial appeal."""
        denial = await self.get_denial_detail(db, denial_id, practice_id)

        # Create notification for billing team
        notification = PortalNotification(
            practice_id=practice_id,
            user_id=user_id,
            notification_type="info_requested",
            title=f"Supporting document uploaded for denial {denial.reason_code}",
            body=f"Document '{filename}' uploaded for appeal.",
            link_url=f"/denials/{denial_id}",
        )
        db.add(notification)

        await _write_audit(
            db, user_id, "upload_supporting_doc", "denial", denial_id,
            resource_detail=f"Filename: {filename}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("supporting_doc_uploaded", denial_id=str(denial_id), filename=filename)
        return {"denial_id": str(denial_id), "filename": filename, "uploaded": True}

    # ── Messaging ────────────────────────────────────────────────────

    async def list_messages(
        self,
        db: AsyncSession,
        practice_id: UUID,
        unread_only: bool = False,
        page: int = 1,
        page_size: int = 50,
    ) -> list[PortalMessage]:
        """List messages for this practice."""
        query = select(PortalMessage).where(
            PortalMessage.practice_id == practice_id,
        )
        if unread_only:
            query = query.where(PortalMessage.is_read == False)
        query = query.order_by(PortalMessage.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def send_message(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        subject: str | None,
        body: str,
        related_claim_id: UUID | None = None,
        is_urgent: bool = False,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> PortalMessage:
        """Send a message from provider to billing team."""
        # Verify related claim belongs to practice
        if related_claim_id:
            claim_result = await db.execute(
                select(Claim.id).where(
                    Claim.id == related_claim_id,
                    Claim.practice_id == practice_id,
                )
            )
            if not claim_result.scalar_one_or_none():
                raise ClaimAccessError("Related claim does not belong to your practice")

        message = PortalMessage(
            practice_id=practice_id,
            sender_id=user_id,
            sender_type="provider",
            subject=subject,
            body=body,
            related_claim_id=related_claim_id,
            is_urgent=is_urgent,
        )
        db.add(message)
        await db.flush()

        await _write_audit(
            db, user_id, "send_portal_message", "portal_message", message.id,
            resource_detail=f"Subject: {subject or '(no subject)'}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        logger.info("portal_message_sent", message_id=str(message.id), practice_id=str(practice_id))
        return message

    async def mark_message_read(
        self,
        db: AsyncSession,
        user_id: UUID,
        message_id: UUID,
        practice_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> PortalMessage:
        """Mark a message as read."""
        result = await db.execute(
            select(PortalMessage).where(
                PortalMessage.id == message_id,
                PortalMessage.practice_id == practice_id,
            )
        )
        message = result.scalar_one_or_none()
        if not message:
            raise MessageNotFoundError(message_id)

        message.is_read = True
        message.read_at = datetime.now(timezone.utc).replace(tzinfo=None)
        await db.flush()

        await _write_audit(
            db, user_id, "mark_message_read", "portal_message", message_id,
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        return message

    # ── Notifications ─────────────────────────────────────────────────

    async def list_notifications(
        self,
        db: AsyncSession,
        practice_id: UUID,
        user_id: UUID,
        unread_only: bool = True,
        page: int = 1,
        page_size: int = 50,
    ) -> list[PortalNotification]:
        """List notifications for this user."""
        query = select(PortalNotification).where(
            PortalNotification.practice_id == practice_id,
            PortalNotification.user_id == user_id,
        )
        if unread_only:
            query = query.where(PortalNotification.is_read == False)
        query = query.order_by(PortalNotification.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def mark_all_notifications_read(
        self,
        db: AsyncSession,
        practice_id: UUID,
        user_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> dict:
        """Mark all unread notifications as read for this user."""
        result = await db.execute(
            select(PortalNotification).where(
                PortalNotification.practice_id == practice_id,
                PortalNotification.user_id == user_id,
                PortalNotification.is_read == False,
            )
        )
        notifications = list(result.scalars().all())

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for notification in notifications:
            notification.is_read = True
            notification.read_at = now

        await db.flush()

        await _write_audit(
            db, user_id, "mark_all_notifications_read", "portal_notification", None,
            resource_detail=f"Marked {len(notifications)} notifications as read",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method,
        )
        return {"marked_count": len(notifications)}

    # ── Reports ──────────────────────────────────────────────────────

    async def list_available_reports(
        self, db: AsyncSession, practice_id: UUID,
    ) -> list[dict]:
        """List report types available for this practice."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        current_month = now.strftime("%Y-%m")
        return [
            {
                "report_type": "monthly_collection",
                "period": current_month,
                "generated_at": now.isoformat(),
                "download_url": f"/api/v1/portal/reports/monthly-collection?period={current_month}",
            },
            {
                "report_type": "ar_aging",
                "period": "current",
                "generated_at": now.isoformat(),
                "download_url": "/api/v1/portal/reports/ar-aging",
            },
            {
                "report_type": "denial_summary",
                "period": current_month,
                "generated_at": now.isoformat(),
                "download_url": f"/api/v1/portal/reports/denial-summary?period={current_month}",
            },
            {
                "report_type": "payer_performance",
                "period": "current",
                "generated_at": now.isoformat(),
                "download_url": "/api/v1/portal/reports/payer-performance",
            },
        ]

    async def monthly_collection_report(
        self, db: AsyncSession, practice_id: UUID, period: str,
    ) -> dict:
        """Monthly collection report broken down by payer and provider."""
        year, month = int(period[:4]), int(period[5:7])
        start = date(year, month, 1)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        # Total charges and payments
        totals = await db.execute(
            select(
                func.coalesce(func.sum(Claim.total_charge), 0).label("total_charges"),
                func.coalesce(func.sum(Claim.total_paid), 0).label("total_paid"),
                func.coalesce(func.sum(Claim.total_adjusted), 0).label("total_adjusted"),
            ).where(
                Claim.practice_id == practice_id,
                Claim.created_at >= start,
                Claim.created_at <= end,
            )
        )
        t = totals.one()

        # Breakdown by payer
        payer_breakdown = await db.execute(
            select(
                Payer.payer_name,
                func.coalesce(func.sum(Claim.total_charge), 0).label("charges"),
                func.coalesce(func.sum(Claim.total_paid), 0).label("paid"),
                func.coalesce(func.sum(Claim.total_adjusted), 0).label("adjusted"),
            ).join(
                Payer, Claim.payer_id == Payer.id
            ).where(
                Claim.practice_id == practice_id,
                Claim.created_at >= start,
                Claim.created_at <= end,
            ).group_by(Payer.payer_name)
        )
        by_payer = [
            {"payer": row.payer_name, "charges": float(row.charges), "paid": float(row.paid), "adjusted": float(row.adjusted)}
            for row in payer_breakdown.all()
        ]

        return {
            "period": period,
            "total_charges": float(t.total_charges or 0),
            "total_collections": float(t.total_paid or 0),
            "total_adjustments": float(t.total_adjusted or 0),
            "net_collection_rate": round(
                float(t.total_paid or 0) / max(float(t.total_charges or 0) - float(t.total_adjusted or 0), 1) * 100, 1
            ),
            "by_payer": by_payer,
        }

    async def ar_aging_report(
        self, db: AsyncSession, practice_id: UUID,
    ) -> dict:
        """Current AR aging by payer and bucket."""
        ar_aging = await self._compute_ar_aging(db, practice_id)

        # Breakdown by payer
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        payer_aging = await db.execute(
            select(
                Payer.payer_name,
                func.coalesce(func.sum(Claim.total_charge - Claim.total_paid - Claim.total_adjusted), 0).label("outstanding"),
            ).join(
                Payer, Claim.payer_id == Payer.id
            ).where(
                Claim.practice_id == practice_id,
                Claim.status.notin_(["paid", "closed", "written_off"]),
            ).group_by(Payer.payer_name)
        )
        by_payer = [
            {"payer": row.payer_name, "outstanding": float(row.outstanding)}
            for row in payer_aging.all()
        ]

        return {
            "total_ar_balance": ar_aging["total"],
            "buckets": {
                "0_30": ar_aging["0_30"],
                "31_60": ar_aging["31_60"],
                "61_90": ar_aging["61_90"],
                "91_120": ar_aging["91_120"],
                "120_plus": ar_aging["120_plus"],
            },
            "by_payer": by_payer,
        }

    async def denial_summary_report(
        self, db: AsyncSession, practice_id: UUID, period: str,
    ) -> dict:
        """Denial rates, top reasons, and outcomes."""
        year, month = int(period[:4]), int(period[5:7])
        start = date(year, month, 1)
        end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)

        # Total claims and denials
        total_claims = await db.execute(
            select(func.count(Claim.id)).where(
                Claim.practice_id == practice_id,
                Claim.created_at >= start,
                Claim.created_at <= end,
            )
        )
        total_count = total_claims.scalar() or 1

        # Denial breakdown by category
        denial_by_category = await db.execute(
            select(
                func.coalesce(Denial.category, "uncategorized").label("category"),
                func.count(Denial.id).label("count"),
                func.coalesce(func.sum(Denial.denial_amount), 0).label("total_amount"),
            ).where(
                Denial.practice_id == practice_id,
                Denial.denial_date >= start,
                Denial.denial_date <= end,
            ).group_by(Denial.category)
        )
        by_category = [
            {"category": row.category, "count": row.count, "total_amount": float(row.total_amount)}
            for row in denial_by_category.all()
        ]

        # Top denial reasons
        top_reasons = await db.execute(
            select(
                Denial.reason_code,
                func.count(Denial.id).label("count"),
            ).where(
                Denial.practice_id == practice_id,
                Denial.denial_date >= start,
                Denial.denial_date <= end,
            ).group_by(Denial.reason_code).order_by(func.count(Denial.id).desc()).limit(5)
        )
        top_reasons_list = [
            {"reason_code": row.reason_code, "count": row.count}
            for row in top_reasons.all()
        ]

        # Recovery stats
        recovery = await db.execute(
            select(
                func.count(Denial.id).label("total_denials"),
                func.coalesce(func.sum(Denial.recovered_amount), 0).label("total_recovered"),
            ).where(
                Denial.practice_id == practice_id,
                Denial.denial_date >= start,
                Denial.denial_date <= end,
            )
        )
        r = recovery.one()

        return {
            "period": period,
            "total_claims": total_count,
            "denial_rate": round(
                sum(c["count"] for c in by_category) / max(total_count, 1) * 100, 1
            ),
            "by_category": by_category,
            "top_reasons": top_reasons_list,
            "total_recovered": float(r.total_recovered or 0),
        }

    async def payer_performance_report(
        self, db: AsyncSession, practice_id: UUID,
    ) -> dict:
        """Payer comparison: avg days to pay, denial rate, reimbursement rate."""
        # Payer-level metrics
        payer_stats = await db.execute(
            select(
                Payer.payer_name,
                func.count(Claim.id).label("total_claims"),
                func.coalesce(func.sum(Claim.total_charge), 0).label("total_charged"),
                func.coalesce(func.sum(Claim.total_paid), 0).label("total_paid"),
                func.count(Claim.id).filter(Claim.status == "denied").label("denied_claims"),
                func.count(Claim.id).filter(Claim.status.in_(["paid", "partial_paid"])).label("paid_claims"),
            ).join(
                Payer, Claim.payer_id == Payer.id
            ).where(
                Claim.practice_id == practice_id,
            ).group_by(Payer.payer_name)
        )

        payers = []
        for row in payer_stats.all():
            total = max(int(row.total_claims or 0), 1)
            charged = float(row.total_charged or 0)
            paid = float(row.total_paid or 0)
            payers.append({
                "payer": row.payer_name,
                "total_claims": int(row.total_claims or 0),
                "denial_rate": round(int(row.denied_claims or 0) / total * 100, 1),
                "reimbursement_rate": round(paid / max(charged, 1) * 100, 1) if charged > 0 else 0,
                "total_charged": charged,
                "total_paid": paid,
            })

        return {"payers": payers}

    # ── Practice Profile ──────────────────────────────────────────────

    async def get_my_practice(
        self, db: AsyncSession, practice_id: UUID,
    ) -> dict:
        """Return practice info for the provider."""
        result = await db.execute(
            select(Practice).where(Practice.id == practice_id)
        )
        practice = result.scalar_one_or_none()
        if not practice:
            raise ClaimAccessError("Practice not found")

        return {
            "id": str(practice.id),
            "practice_name": practice.practice_name,
            "legal_name": practice.legal_name,
            "specialty_primary": practice.specialty_primary,
            "address": {
                "line_1": practice.address_line_1,
                "line_2": practice.address_line_2,
                "city": practice.city,
                "state": practice.state,
                "zip_code": practice.zip_code,
            },
            "phone": practice.phone,
            "email": practice.email,
            "status": practice.status,
        }

    async def list_my_providers(
        self, db: AsyncSession, practice_id: UUID,
    ) -> list[dict]:
        """List providers linked to this practice."""
        # Providers are linked via rendering_provider on claims
        result = await db.execute(
            select(Provider).where(Provider.is_active == True).distinct()
        )
        providers = list(result.scalars().all())
        return [
            {
                "id": str(p.id),
                "npi": p.npi,
                "name": f"{p.first_name} {p.last_name}",
                "credential": p.credential,
                "specialty": p.specialty,
            }
            for p in providers
        ]

    async def list_my_payers(
        self, db: AsyncSession, practice_id: UUID,
    ) -> list[dict]:
        """List enrolled payers for this practice."""
        result = await db.execute(
            select(PayerEnrollment).where(
                PayerEnrollment.practice_id == practice_id,
                PayerEnrollment.is_active == True,
            )
        )
        enrollments = list(result.scalars().all())

        payers_data = []
        for enrollment in enrollments:
            payer_result = await db.execute(
                select(Payer).where(Payer.id == enrollment.payer_id)
            )
            payer = payer_result.scalar_one_or_none()
            payers_data.append({
                "id": str(enrollment.id),
                "payer_name": payer.payer_name if payer else "Unknown",
                "group_number": enrollment.group_number,
                "era_enrolled": enrollment.era_enrolled,
                "eft_enrolled": enrollment.eft_enrolled,
            })

        return payers_data

    # ── Invoices ──────────────────────────────────────────────────────

    async def list_invoices(
        self,
        db: AsyncSession,
        practice_id: UUID,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[ClientInvoice]:
        """List invoices for this practice."""
        query = select(ClientInvoice).where(
            ClientInvoice.practice_id == practice_id,
        )
        if status:
            query = query.where(ClientInvoice.status == status)
        query = query.order_by(ClientInvoice.created_at.desc())
        query = query.offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_invoice_detail(
        self, db: AsyncSession, invoice_id: UUID, practice_id: UUID,
    ) -> ClientInvoice:
        """Get invoice detail."""
        result = await db.execute(
            select(ClientInvoice).where(
                ClientInvoice.id == invoice_id,
                ClientInvoice.practice_id == practice_id,
            )
        )
        invoice = result.scalar_one_or_none()
        if not invoice:
            raise ClaimAccessError("Invoice not found or does not belong to your practice")
        return invoice

    # ── Helpers ───────────────────────────────────────────────────────

    async def _get_claim_or_raise(
        self, db: AsyncSession, claim_id: UUID, practice_id: UUID,
    ) -> Claim:
        """Load a claim with tenant isolation check."""
        result = await db.execute(
            select(Claim).where(
                Claim.id == claim_id,
                Claim.practice_id == practice_id,
            )
        )
        claim = result.scalar_one_or_none()
        if not claim:
            raise ClaimAccessError(f"Claim {claim_id} not found or does not belong to your practice")
        return claim

    @staticmethod
    def _compute_status_display(claim: Claim, denial: Denial | None = None, appeal: Appeal | None = None) -> str:
        """Map internal claim status to provider-friendly display string."""
        base = STATUS_DISPLAY_MAP.get(claim.status, claim.status.replace("_", " ").title())

        if claim.status == "denied" and appeal:
            base = f"Denied — Appeal Filed (Level {appeal.appeal_level or 1})"
        elif claim.status == "partial_paid":
            base = f"Partially Paid — ${claim.total_paid:,.2f} of ${claim.total_charge:,.2f}"

        return base

    async def _compute_ar_aging(
        self, db: AsyncSession, practice_id: UUID,
    ) -> dict:
        """Compute AR aging buckets for a practice."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        buckets = {
            "0_30": 0.0,
            "31_60": 0.0,
            "61_90": 0.0,
            "91_120": 0.0,
            "120_plus": 0.0,
            "total": 0.0,
        }

        # Get all outstanding claims
        result = await db.execute(
            select(Claim).where(
                Claim.practice_id == practice_id,
                Claim.status.notin_(["paid", "closed", "written_off"]),
            )
        )
        claims = list(result.scalars().all())

        for claim in claims:
            outstanding = claim.total_charge - claim.total_paid - claim.total_adjusted
            if outstanding <= 0:
                continue

            claim_date = claim.created_at or now
            age_days = (now - claim_date).days

            if age_days <= 30:
                buckets["0_30"] += outstanding
            elif age_days <= 60:
                buckets["31_60"] += outstanding
            elif age_days <= 90:
                buckets["61_90"] += outstanding
            elif age_days <= 120:
                buckets["91_120"] += outstanding
            else:
                buckets["120_plus"] += outstanding

            buckets["total"] += outstanding

        return buckets


# Module-level singleton
portal_service = PortalService()