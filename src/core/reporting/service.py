"""
Analytics and reporting service — KPI dashboards, revenue cycle metrics,
coding accuracy, payer performance, and AR aging reports.

Aggregates data from Claims, Denials, Payments, CodingSessions, and
ServiceAgreements to produce cross-practice analytics.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import structlog
from sqlalchemy import func, select, case, and_
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.reporting.errors import ReportGenerationError
from src.infrastructure.database.models import (
    Claim,
    CodingSession,
    Denial,
    PaymentLine,
    Payer,
    Practice,
    ServiceAgreement,
)

logger = structlog.get_logger()


class AnalyticsService:
    """Cross-practice analytics and reporting."""

    # ── Dashboard KPIs ────────────────────────────────────────────────

    async def get_dashboard(
        self,
        db: AsyncSession,
        practice_id: UUID | None = None,
        period: str | None = None,
    ) -> dict:
        """Main dashboard: claims, payments, denials, revenue KPIs."""
        if period:
            year, month = int(period[:4]), int(period[5:7])
            start = date(year, month, 1)
            end = (start + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        else:
            today = date.today()
            start = today.replace(day=1)
            end = today

        # Build base filter
        base_filter = []
        if practice_id:
            base_filter.append(Claim.practice_id == practice_id)
        base_filter.append(Claim.created_at >= start)
        base_filter.append(Claim.created_at <= end)

        # Claims KPIs
        claims_result = await db.execute(
            select(
                func.count(Claim.id).label("total_claims"),
                func.coalesce(func.sum(Claim.total_charge), 0).label("total_charged"),
                func.coalesce(func.sum(Claim.total_paid), 0).label("total_paid"),
                func.coalesce(func.sum(Claim.total_adjusted), 0).label("total_adjusted"),
            ).where(*base_filter)
        )
        c = claims_result.one()

        total_claims = int(c.total_claims or 0)
        total_charged = float(c.total_charged or 0)
        total_paid = float(c.total_paid or 0)
        total_adjusted = float(c.total_adjusted or 0)

        # Claims by status
        status_result = await db.execute(
            select(Claim.status, func.count(Claim.id)).where(*base_filter).group_by(Claim.status)
        )
        claims_by_status = {row[0]: row[1] for row in status_result.all()}

        # Clean claim rate (scrub_score >= 95)
        clean_result = await db.execute(
            select(func.count(Claim.id)).where(
                *base_filter,
                Claim.scrub_score >= 95,
            )
        )
        clean_claims = clean_result.scalar() or 0
        clean_claim_rate = round(clean_claims / max(total_claims, 1) * 100, 1)

        # Denial rate
        denied_result = await db.execute(
            select(func.count(Claim.id)).where(
                *base_filter,
                Claim.status == "denied",
            )
        )
        denied_claims = denied_result.scalar() or 0
        denial_rate = round(denied_claims / max(total_claims, 1) * 100, 1)

        # Payment KPIs
        payment_result = await db.execute(
            select(
                func.coalesce(func.sum(PaymentLine.paid_amount), 0).label("total_payments"),
                func.count(PaymentLine.id).label("payment_count"),
            ).where(
                PaymentLine.created_at >= start,
                PaymentLine.created_at <= end,
            )
        )
        p = payment_result.one()
        total_payments = float(p.total_payments or 0)

        # Active practices
        practice_filter = [Practice.status == "active"]
        if practice_id:
            practice_filter.append(Practice.id == practice_id)
        practice_count_result = await db.execute(
            select(func.count(Practice.id)).where(*practice_filter)
        )
        active_practices = practice_count_result.scalar() or 1

        # Collection rate
        net_collection_rate = round(
            total_paid / max(total_charged - total_adjusted, 1) * 100, 1
        ) if (total_charged - total_adjusted) > 0 else 0

        return {
            "period": f"{start.strftime('%B %Y')}" if period else "Current Month",
            "total_claims": total_claims,
            "total_charged": total_charged,
            "total_paid": total_paid,
            "total_adjusted": total_adjusted,
            "total_payments": total_payments,
            "net_collection_rate": net_collection_rate,
            "clean_claim_rate": clean_claim_rate,
            "denial_rate": denial_rate,
            "claims_by_status": claims_by_status,
            "active_practices": active_practices,
        }

    # ── Revenue Cycle Report ──────────────────────────────────────────

    async def revenue_cycle_report(
        self,
        db: AsyncSession,
        practice_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict:
        """Full revenue cycle metrics: days in AR, clean claim rate, denial rate."""
        base_filter = []
        if practice_id:
            base_filter.append(Claim.practice_id == practice_id)
        if date_from:
            base_filter.append(Claim.created_at >= date_from)
        if date_to:
            base_filter.append(Claim.created_at <= date_to)

        # Days in AR (average age of unpaid claims)
        today = date.today()
        ar_claims_result = await db.execute(
            select(
                func.count(Claim.id).label("count"),
                func.coalesce(func.sum(Claim.total_charge - Claim.total_paid - Claim.total_adjusted), 0).label("total_ar"),
            ).where(
                *base_filter,
                Claim.status.notin_(["paid", "closed", "written_off"]),
            )
        )
        ar = ar_claims_result.one()
        ar_count = int(ar.count or 0)
        total_ar_balance = float(ar.total_ar or 0)

        # Average days outstanding (simplified: use created_at)
        avg_days_result = await db.execute(
            select(func.avg(
                func.extract("epoch", func.now() - Claim.created_at) / 86400
            )).where(
                *base_filter,
                Claim.status.notin_(["paid", "closed", "written_off"]),
            )
        )
        avg_days_in_ar = round(float(avg_days_result.scalar() or 0), 1)

        # Clean claim rate
        total_claims_result = await db.execute(
            select(func.count(Claim.id)).where(*base_filter)
        )
        total_claims = total_claims_result.scalar() or 1

        clean_result = await db.execute(
            select(func.count(Claim.id)).where(
                *base_filter,
                Claim.scrub_score >= 95,
            )
        )
        clean_claims = clean_result.scalar() or 0
        clean_claim_rate = round(clean_claims / max(total_claims, 1) * 100, 1)

        # Denial rate
        denied_result = await db.execute(
            select(func.count(Claim.id)).where(
                *base_filter,
                Claim.status == "denied",
            )
        )
        denied_claims = denied_result.scalar() or 0
        denial_rate = round(denied_claims / max(total_claims, 1) * 100, 1)

        # First-pass resolution rate (claims paid on first submission)
        first_pass_result = await db.execute(
            select(func.count(Claim.id)).where(
                *base_filter,
                Claim.status.in_(["paid", "partial_paid"]),
                Claim.adjudication_date.isnot(None),
            )
        )
        first_pass_paid = first_pass_result.scalar() or 0
        first_pass_rate = round(first_pass_paid / max(total_claims, 1) * 100, 1)

        return {
            "total_claims": int(total_claims),
            "total_ar_balance": total_ar_balance,
            "ar_claim_count": ar_count,
            "avg_days_in_ar": avg_days_in_ar,
            "clean_claim_rate": clean_claim_rate,
            "denial_rate": denial_rate,
            "first_pass_resolution_rate": first_pass_rate,
            "net_collection_rate": None,  # Computed separately if needed
        }

    # ── Coding Accuracy Report ────────────────────────────────────────

    async def coding_accuracy_report(
        self,
        db: AsyncSession,
        practice_id: UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> dict:
        """AI coding accuracy vs coder corrections."""
        base_filter = []
        if practice_id:
            base_filter.append(CodingSession.practice_id == practice_id)
        if date_from:
            base_filter.append(CodingSession.created_at >= date_from)
        if date_to:
            base_filter.append(CodingSession.created_at <= date_to)

        # Total coding sessions
        total_result = await db.execute(
            select(func.count(CodingSession.id)).where(*base_filter)
        )
        total_sessions = total_result.scalar() or 0

        # Sessions where coder made changes (coder_changes is not null)
        changed_result = await db.execute(
            select(func.count(CodingSession.id)).where(
                *base_filter,
                CodingSession.coder_changes.isnot(None),
            )
        )
        sessions_with_changes = changed_result.scalar() or 0

        # AI accuracy = sessions with no changes / total sessions
        ai_accuracy = round(
            (total_sessions - sessions_with_changes) / max(total_sessions, 1) * 100, 1
        ) if total_sessions > 0 else 0

        # Average review time
        avg_review_result = await db.execute(
            select(func.avg(CodingSession.review_time_seconds)).where(
                *base_filter,
                CodingSession.review_time_seconds.isnot(None),
            )
        )
        avg_review_seconds = avg_review_result.scalar() or 0
        avg_review_minutes = round(float(avg_review_seconds) / 60, 1)

        # Sessions by status
        status_result = await db.execute(
            select(CodingSession.status, func.count(CodingSession.id)).where(*base_filter).group_by(CodingSession.status)
        )
        sessions_by_status = {row[0]: row[1] for row in status_result.all()}

        # Average processing time
        avg_processing_result = await db.execute(
            select(func.avg(CodingSession.processing_time_ms)).where(
                *base_filter,
                CodingSession.processing_time_ms.isnot(None),
            )
        )
        avg_processing_ms = avg_processing_result.scalar() or 0

        return {
            "total_sessions": int(total_sessions),
            "sessions_with_coder_changes": int(sessions_with_changes),
            "ai_accuracy_rate": ai_accuracy,
            "avg_review_time_minutes": avg_review_minutes,
            "avg_processing_time_ms": round(float(avg_processing_ms), 0),
            "sessions_by_status": sessions_by_status,
        }

    # ── Payer Performance ─────────────────────────────────────────────

    async def payer_performance(
        self,
        db: AsyncSession,
        practice_id: UUID | None = None,
    ) -> dict:
        """Payer comparison: payment speed, denial rates, reimbursement rates."""
        base_filter = []
        if practice_id:
            base_filter.append(Claim.practice_id == practice_id)

        # Payer-level metrics
        payer_stats = await db.execute(
            select(
                Payer.payer_name,
                func.count(Claim.id).label("total_claims"),
                func.coalesce(func.sum(Claim.total_charge), 0).label("total_charged"),
                func.coalesce(func.sum(Claim.total_paid), 0).label("total_paid"),
                func.count(Claim.id).filter(Claim.status == "denied").label("denied"),
                func.count(Claim.id).filter(Claim.status.in_(["paid", "partial_paid"])).label("paid"),
            ).join(
                Payer, Claim.payer_id == Payer.id
            ).where(*base_filter).group_by(Payer.payer_name)
        )

        payers = []
        for row in payer_stats.all():
            total = max(int(row.total_claims or 0), 1)
            charged = float(row.total_charged or 0)
            paid = float(row.total_paid or 0)
            denied_count = int(row.denied or 0)
            paid_count = int(row.paid or 0)
            payers.append({
                "payer_name": row.payer_name,
                "total_claims": int(row.total_claims or 0),
                "denial_rate": round(denied_count / total * 100, 1),
                "reimbursement_rate": round(paid / max(charged, 1) * 100, 1) if charged > 0 else 0,
                "total_charged": charged,
                "total_paid": paid,
                "paid_claims": paid_count,
                "denied_claims": denied_count,
            })

        return {"payers": payers}

    # ── AR Aging Report ───────────────────────────────────────────────

    async def aging_report(
        self,
        db: AsyncSession,
        practice_id: UUID | None = None,
    ) -> dict:
        """AR aging report: 0-30, 31-60, 61-90, 91-120, 120+ days."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)

        base_filter = [
            Claim.status.notin_(["paid", "closed", "written_off"]),
        ]
        if practice_id:
            base_filter.append(Claim.practice_id == practice_id)

        # Get all outstanding claims
        result = await db.execute(
            select(Claim).where(*base_filter)
        )
        claims = list(result.scalars().all())

        buckets = {
            "0_30": 0.0,
            "31_60": 0.0,
            "61_90": 0.0,
            "91_120": 0.0,
            "120_plus": 0.0,
            "total": 0.0,
        }

        # Payer breakdown
        payer_breakdown: dict[str, dict] = {}

        for claim in claims:
            outstanding = claim.total_charge - claim.total_paid - claim.total_adjusted
            if outstanding <= 0:
                continue

            claim_date = claim.created_at or now
            age_days = (now - claim_date).days

            if age_days <= 30:
                bucket = "0_30"
            elif age_days <= 60:
                bucket = "31_60"
            elif age_days <= 90:
                bucket = "61_90"
            elif age_days <= 120:
                bucket = "91_120"
            else:
                bucket = "120_plus"

            buckets[bucket] += outstanding
            buckets["total"] += outstanding

            # Payer breakdown
            payer_result = await db.execute(
                select(Payer.payer_name).where(Payer.id == claim.payer_id)
            )
            payer_name = payer_result.scalar() or "Unknown"
            if payer_name not in payer_breakdown:
                payer_breakdown[payer_name] = {"total": 0.0, "0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "91_120": 0.0, "120_plus": 0.0}
            payer_breakdown[payer_name][bucket] += outstanding
            payer_breakdown[payer_name]["total"] += outstanding

        return {
            "aging_buckets": buckets,
            "payer_breakdown": payer_breakdown,
            "total_claims_outstanding": len(claims),
        }


# Module-level singleton
analytics_service = AnalyticsService()