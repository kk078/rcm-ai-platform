"""Analytics and reporting routes."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, cast, extract, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.auth.middleware import get_current_user
from src.infrastructure.database.models import (
    AICodingFeedback,
    Claim,
    ClaimScrubResult,
    CodingSession,
    Denial,
    Payer,
    User,
    WorkQueueItem,
)
from src.infrastructure.database.session import get_db

router = APIRouter()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _days_diff(later, earlier):
    """Return a SQLAlchemy expression: (later - earlier) in fractional days."""
    return cast(
        extract("epoch", later - earlier) / 86400.0,
        type_=type(None),  # float in PostgreSQL
    )


# ---------------------------------------------------------------------------
# /dashboard
# ---------------------------------------------------------------------------


@router.get("/dashboard")
async def get_dashboard(
    practice_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Main dashboard KPIs: claims, payments, denials, revenue, days-in-AR, clean-claim rate."""

    base_claim = select(Claim)
    if practice_id:
        base_claim = base_claim.where(Claim.practice_id == practice_id)

    # ── Total claims & payments ──────────────────────────────────────────────
    total_claims_q = await db.execute(
        select(func.count(Claim.id)).where(
            *([Claim.practice_id == practice_id] if practice_id else [])
        )
    )
    total_payments_q = await db.execute(
        select(func.coalesce(func.sum(Claim.total_paid), 0.0)).where(
            *([Claim.practice_id == practice_id] if practice_id else [])
        )
    )

    # ── Open denials ─────────────────────────────────────────────────────────
    denial_filter = [Denial.status.in_(["new", "appealed", "in_progress"])]
    if practice_id:
        denial_filter.append(Denial.practice_id == practice_id)
    open_denials_q = await db.execute(
        select(func.count(Denial.id)).where(*denial_filter)
    )

    # ── Denial rate ──────────────────────────────────────────────────────────
    submitted_filter = [Claim.status != "draft"]
    denied_filter = [Claim.status == "denied"]
    if practice_id:
        submitted_filter.append(Claim.practice_id == practice_id)
        denied_filter.append(Claim.practice_id == practice_id)

    total_submitted_q = await db.execute(
        select(func.count(Claim.id)).where(*submitted_filter)
    )
    denied_claims_q = await db.execute(
        select(func.count(Claim.id)).where(*denied_filter)
    )

    # ── Average days in AR ───────────────────────────────────────────────────
    # Only for adjudicated claims where both dates are present.
    ar_filter = [
        Claim.submission_date.isnot(None),
        Claim.adjudication_date.isnot(None),
    ]
    if practice_id:
        ar_filter.append(Claim.practice_id == practice_id)

    avg_ar_q = await db.execute(
        select(
            func.avg(
                extract("epoch", Claim.adjudication_date - Claim.submission_date)
                / 86400.0
            )
        ).where(*ar_filter)
    )

    # ── Clean claim rate ─────────────────────────────────────────────────────
    # = claims with NO unresolved error-severity scrub results / total submitted
    #
    # Subquery: claim_ids that HAVE at least one unresolved error scrub result.
    dirty_subq = (
        select(ClaimScrubResult.claim_id)
        .where(
            ClaimScrubResult.severity == "error",
            ClaimScrubResult.resolved.is_(False),
        )
        .distinct()
        .scalar_subquery()
    )

    clean_submitted_filter = [Claim.status != "draft", Claim.id.not_in(dirty_subq)]
    total_submitted_filter2 = [Claim.status != "draft"]
    if practice_id:
        clean_submitted_filter.append(Claim.practice_id == practice_id)
        total_submitted_filter2.append(Claim.practice_id == practice_id)

    clean_claims_q = await db.execute(
        select(func.count(Claim.id)).where(*clean_submitted_filter)
    )
    total_sub2_q = await db.execute(
        select(func.count(Claim.id)).where(*total_submitted_filter2)
    )

    # ── Assemble ─────────────────────────────────────────────────────────────
    claims_count = total_claims_q.scalar() or 0
    payments = float(total_payments_q.scalar() or 0)
    open_denials = open_denials_q.scalar() or 0
    submitted = total_submitted_q.scalar() or 0
    denied = denied_claims_q.scalar() or 0
    avg_ar = avg_ar_q.scalar()
    clean = clean_claims_q.scalar() or 0
    total_sub2 = total_sub2_q.scalar() or 0

    return {
        "total_claims": claims_count,
        "total_collections": round(payments, 2),
        "open_denials": open_denials,
        "denial_rate": round(denied / submitted, 4) if submitted else 0.0,
        "avg_days_in_ar": round(float(avg_ar), 2) if avg_ar is not None else 0.0,
        "clean_claim_rate": round(clean / total_sub2, 4) if total_sub2 else 0.0,
    }


# ---------------------------------------------------------------------------
# /revenue-cycle
# ---------------------------------------------------------------------------


@router.get("/revenue-cycle")
async def revenue_cycle_report(
    practice_id: str | None = Query(None),
    days: int = Query(90, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Full revenue cycle metrics: days in AR, clean claim rate, denial rate,
    first-pass resolution rate, and avg reimbursement per claim."""

    pf = [Claim.practice_id == practice_id] if practice_id else []

    # ── Average days in AR ───────────────────────────────────────────────────
    avg_ar_q = await db.execute(
        select(
            func.avg(
                extract("epoch", Claim.adjudication_date - Claim.submission_date)
                / 86400.0
            )
        ).where(
            Claim.submission_date.isnot(None),
            Claim.adjudication_date.isnot(None),
            *pf,
        )
    )

    # ── Clean claim rate ─────────────────────────────────────────────────────
    dirty_subq = (
        select(ClaimScrubResult.claim_id)
        .where(
            ClaimScrubResult.severity == "error",
            ClaimScrubResult.resolved.is_(False),
        )
        .distinct()
        .scalar_subquery()
    )

    total_sub_q = await db.execute(
        select(func.count(Claim.id)).where(Claim.status != "draft", *pf)
    )
    clean_sub_q = await db.execute(
        select(func.count(Claim.id)).where(
            Claim.status != "draft",
            Claim.id.not_in(dirty_subq),
            *pf,
        )
    )

    # ── Denial rate ──────────────────────────────────────────────────────────
    denied_q = await db.execute(
        select(func.count(Claim.id)).where(Claim.status == "denied", *pf)
    )

    # ── First-pass resolution rate ───────────────────────────────────────────
    # Claims that reached "paid" status and never had a Denial record.
    ever_denied_subq = (
        select(Denial.claim_id).distinct().scalar_subquery()
    )
    paid_no_denial_q = await db.execute(
        select(func.count(Claim.id)).where(
            Claim.status == "paid",
            Claim.id.not_in(ever_denied_subq),
            *pf,
        )
    )
    total_paid_q = await db.execute(
        select(func.count(Claim.id)).where(Claim.status == "paid", *pf)
    )

    # ── Average reimbursement per paid claim ─────────────────────────────────
    avg_reimb_q = await db.execute(
        select(func.avg(Claim.total_paid)).where(
            Claim.status == "paid",
            Claim.total_paid.isnot(None),
            *pf,
        )
    )

    total_sub = total_sub_q.scalar() or 0
    clean = clean_sub_q.scalar() or 0
    denied = denied_q.scalar() or 0
    paid_no_denial = paid_no_denial_q.scalar() or 0
    total_paid = total_paid_q.scalar() or 0
    avg_ar = avg_ar_q.scalar()
    avg_reimb = avg_reimb_q.scalar()

    return {
        "days_in_ar": round(float(avg_ar), 2) if avg_ar is not None else 0.0,
        "clean_claim_rate": round(clean / total_sub, 4) if total_sub else 0.0,
        "denial_rate": round(denied / total_sub, 4) if total_sub else 0.0,
        "first_pass_resolution_rate": (
            round(paid_no_denial / total_paid, 4) if total_paid else 0.0
        ),
        "avg_reimbursement_per_claim": (
            round(float(avg_reimb), 2) if avg_reimb is not None else 0.0
        ),
    }


# ---------------------------------------------------------------------------
# /coding-accuracy
# ---------------------------------------------------------------------------


@router.get("/coding-accuracy")
async def coding_accuracy_report(
    practice_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """AI coding accuracy vs coder corrections, broken down by coder."""

    session_filter = []
    if practice_id:
        session_filter.append(CodingSession.practice_id == practice_id)

    # ── Total sessions ───────────────────────────────────────────────────────
    total_sessions_q = await db.execute(
        select(func.count(CodingSession.id)).where(*session_filter)
    )

    # ── Feedback-level acceptance rates ──────────────────────────────────────
    # Join AICodingFeedback → CodingSession for practice filtering.
    feedback_base = select(AICodingFeedback).join(
        CodingSession,
        AICodingFeedback.coding_session_id == CodingSession.id,
    )
    if session_filter:
        feedback_base = feedback_base.where(*session_filter)

    # Count records where dx_accepted=True and cpt_accepted=True.
    dx_accepted_q = await db.execute(
        select(
            func.count(AICodingFeedback.id).filter(
                AICodingFeedback.dx_accepted.is_(True)
            ),
            func.count(AICodingFeedback.id).filter(
                AICodingFeedback.dx_accepted.isnot(None)
            ),
        ).join(
            CodingSession,
            AICodingFeedback.coding_session_id == CodingSession.id,
        ).where(*session_filter)
    )
    dx_row = dx_accepted_q.one()
    dx_accepted, dx_total = dx_row[0] or 0, dx_row[1] or 0

    cpt_accepted_q = await db.execute(
        select(
            func.count(AICodingFeedback.id).filter(
                AICodingFeedback.cpt_accepted.is_(True)
            ),
            func.count(AICodingFeedback.id).filter(
                AICodingFeedback.cpt_accepted.isnot(None)
            ),
        ).join(
            CodingSession,
            AICodingFeedback.coding_session_id == CodingSession.id,
        ).where(*session_filter)
    )
    cpt_row = cpt_accepted_q.one()
    cpt_accepted, cpt_total = cpt_row[0] or 0, cpt_row[1] or 0

    # ── Per-coder breakdown ──────────────────────────────────────────────────
    by_coder_q = await db.execute(
        select(
            AICodingFeedback.coder_id,
            func.concat(User.first_name, " ", User.last_name).label("full_name"),
            func.count(AICodingFeedback.id).label("sessions"),
            func.count(AICodingFeedback.id).filter(
                AICodingFeedback.dx_accepted.is_(True)
            ).label("dx_accepted"),
            func.count(AICodingFeedback.id).filter(
                AICodingFeedback.dx_accepted.isnot(None)
            ).label("dx_total"),
            func.count(AICodingFeedback.id).filter(
                AICodingFeedback.cpt_accepted.is_(True)
            ).label("cpt_accepted"),
            func.count(AICodingFeedback.id).filter(
                AICodingFeedback.cpt_accepted.isnot(None)
            ).label("cpt_total"),
        )
        .join(
            CodingSession,
            AICodingFeedback.coding_session_id == CodingSession.id,
        )
        .outerjoin(User, User.id == AICodingFeedback.coder_id)
        .where(*session_filter)
        .group_by(AICodingFeedback.coder_id, User.first_name, User.last_name)
        .order_by(func.count(AICodingFeedback.id).desc())
    )

    by_coder = [
        {
            "coder_id": str(row.coder_id),
            "coder_name": row.full_name or "Unknown",
            "sessions": row.sessions,
            "dx_acceptance_rate": (
                round(row.dx_accepted / row.dx_total, 4) if row.dx_total else 0.0
            ),
            "cpt_acceptance_rate": (
                round(row.cpt_accepted / row.cpt_total, 4) if row.cpt_total else 0.0
            ),
        }
        for row in by_coder_q
    ]

    total_sessions = total_sessions_q.scalar() or 0
    overall_accepted = dx_accepted + cpt_accepted
    overall_total = dx_total + cpt_total

    return {
        "total_sessions": total_sessions,
        "dx_acceptance_rate": round(dx_accepted / dx_total, 4) if dx_total else 0.0,
        "cpt_acceptance_rate": (
            round(cpt_accepted / cpt_total, 4) if cpt_total else 0.0
        ),
        "overall_ai_acceptance_rate": (
            round(overall_accepted / overall_total, 4) if overall_total else 0.0
        ),
        "coder_corrections": overall_total - overall_accepted,
        "by_coder": by_coder,
    }


# ---------------------------------------------------------------------------
# /payer-performance
# ---------------------------------------------------------------------------


@router.get("/payer-performance")
async def payer_performance(
    practice_id: str | None = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> list[dict[str, Any]]:
    """Payer comparison: payment speed, denial rates, avg reimbursement."""

    pf = [Claim.practice_id == practice_id] if practice_id else []

    # ── Per-payer aggregates from Claims ─────────────────────────────────────
    payer_stats_q = await db.execute(
        select(
            Claim.payer_id,
            Payer.payer_name,
            func.count(Claim.id).label("total_claims"),
            func.count(Claim.id).filter(Claim.status == "paid").label("paid_claims"),
            func.count(Claim.id).filter(Claim.status == "denied").label(
                "denied_claims"
            ),
            func.coalesce(func.sum(Claim.total_paid), 0.0).label("total_paid"),
            func.avg(Claim.total_paid).filter(
                Claim.status == "paid",
            ).label("avg_paid"),
            func.avg(
                extract(
                    "epoch",
                    Claim.adjudication_date - Claim.submission_date,
                )
                / 86400.0
            )
            .filter(
                Claim.submission_date.isnot(None),
                Claim.adjudication_date.isnot(None),
            )
            .label("avg_days_to_pay"),
        )
        .join(Payer, Claim.payer_id == Payer.id, isouter=True)
        .where(Claim.payer_id.isnot(None), *pf)
        .group_by(Claim.payer_id, Payer.payer_name)
        .order_by(func.count(Claim.id).desc())
        .limit(limit)
    )

    results = []
    for row in payer_stats_q:
        total = row.total_claims or 0
        denied = row.denied_claims or 0
        results.append(
            {
                "payer_id": str(row.payer_id),
                "payer_name": row.payer_name or "Unknown",
                "total_claims": total,
                "paid_claims": row.paid_claims or 0,
                "denied_claims": denied,
                "denial_rate": round(denied / total, 4) if total else 0.0,
                "total_paid": round(float(row.total_paid or 0), 2),
                "avg_paid_per_claim": (
                    round(float(row.avg_paid), 2)
                    if row.avg_paid is not None
                    else 0.0
                ),
                "avg_days_to_payment": (
                    round(float(row.avg_days_to_pay), 2)
                    if row.avg_days_to_pay is not None
                    else None
                ),
            }
        )

    return results


# ---------------------------------------------------------------------------
# /aging-report
# ---------------------------------------------------------------------------


@router.get("/aging-report")
async def aging_report(
    practice_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """AR aging report bucketed into 0-30, 31-60, 61-90, 91-120, 120+ days.

    Uses open claims (status not in paid/closed/draft) and calculates age
    from submission_date to today.
    """

    open_statuses = ["submitted", "accepted", "rejected", "denied", "appealed", "partial_paid"]
    pf = [Claim.practice_id == practice_id] if practice_id else []

    age_expr = (
        extract("epoch", func.now() - Claim.submission_date) / 86400.0
    )

    bucket_expr = case(
        (age_expr <= 30, "0-30"),
        (age_expr <= 60, "31-60"),
        (age_expr <= 90, "61-90"),
        (age_expr <= 120, "91-120"),
        else_="120+",
    )

    aging_q = await db.execute(
        select(
            bucket_expr.label("bucket"),
            func.count(Claim.id).label("count"),
            func.coalesce(func.sum(Claim.total_charge), 0.0).label("total_charge"),
            func.coalesce(
                func.sum(Claim.total_charge - Claim.total_paid), 0.0
            ).label("outstanding"),
        )
        .where(
            Claim.status.in_(open_statuses),
            Claim.submission_date.isnot(None),
            *pf,
        )
        .group_by(bucket_expr)
    )

    # Build ordered result using canonical bucket ordering.
    bucket_order = ["0-30", "31-60", "61-90", "91-120", "120+"]
    bucket_map: dict[str, dict] = {
        b: {"range": b, "count": 0, "total_charge": 0.0, "outstanding": 0.0}
        for b in bucket_order
    }

    for row in aging_q:
        b = row.bucket
        if b in bucket_map:
            bucket_map[b]["count"] = row.count
            bucket_map[b]["total_charge"] = round(float(row.total_charge or 0), 2)
            bucket_map[b]["outstanding"] = round(float(row.outstanding or 0), 2)

    total_outstanding = sum(v["outstanding"] for v in bucket_map.values())

    return {
        "buckets": list(bucket_map.values()),
        "total_outstanding": round(total_outstanding, 2),
    }


# ---------------------------------------------------------------------------
# /ai-insights  (new)
# ---------------------------------------------------------------------------


@router.get("/ai-insights")
async def ai_insights(
    practice_id: str | None = Query(None),
    queue_type: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """AI dispatch performance: throughput, escalation rates, confidence,
    SLA breaches, and per-queue-type breakdown."""

    wqi_filter = []
    if practice_id:
        wqi_filter.append(WorkQueueItem.practice_id == practice_id)
    if queue_type:
        wqi_filter.append(WorkQueueItem.queue_type == queue_type)

    # ── Overall counts by status ─────────────────────────────────────────────
    status_counts_q = await db.execute(
        select(
            WorkQueueItem.status,
            func.count(WorkQueueItem.id).label("cnt"),
        )
        .where(*wqi_filter)
        .group_by(WorkQueueItem.status)
    )
    status_map: dict[str, int] = {row.status: row.cnt for row in status_counts_q}

    total_processed = sum(status_map.get(s, 0) for s in ("completed", "escalated", "failed"))
    escalated = status_map.get("escalated", 0)
    failed = status_map.get("failed", 0)
    completed = status_map.get("completed", 0)
    pending = status_map.get("pending", 0)
    in_progress = status_map.get("in_progress", 0)

    # ── SLA breaches ─────────────────────────────────────────────────────────
    sla_q = await db.execute(
        select(func.count(WorkQueueItem.id)).where(
            WorkQueueItem.sla_breached.is_(True),
            *wqi_filter,
        )
    )
    sla_breached = sla_q.scalar() or 0

    # ── Average time spent (seconds) ────────────────────────────────────────
    avg_time_q = await db.execute(
        select(
            func.avg(WorkQueueItem.time_spent_seconds).filter(
                WorkQueueItem.time_spent_seconds.isnot(None)
            )
        ).where(*wqi_filter)
    )
    avg_time = avg_time_q.scalar()

    # ── Average AI confidence from JSON notes ────────────────────────────────
    # notes is a JSON string: {"confidence": 0.87, ...}
    # PostgreSQL: cast(notes::json->>'confidence' as double precision)
    # JSON-extract average is computed via the raw-SQL path below; building it
    # through the ORM with cast(..., type_=None) produced a NullType DDL error.
    avg_conf_val = None

    # If ORM JSON path failed, run raw SQL.
    if avg_conf_val is None and total_processed > 0:
        raw_conf_filter = "notes IS NOT NULL"
        params: dict[str, Any] = {}
        if practice_id:
            raw_conf_filter += " AND practice_id = :pid"
            params["pid"] = practice_id
        if queue_type:
            raw_conf_filter += " AND queue_type = :qt"
            params["qt"] = queue_type
        try:
            raw_q = await db.execute(
                text(
                    f"""
                    SELECT AVG(
                        (notes::json->>'confidence')::double precision
                    )
                    FROM work_queue_items
                    WHERE {raw_conf_filter}
                      AND status IN ('completed', 'escalated')
                    """
                ),
                params,
            )
            avg_conf_val = raw_q.scalar()
        except Exception:  # noqa: BLE001
            avg_conf_val = None

    # ── Per-queue-type breakdown ─────────────────────────────────────────────
    by_queue_q = await db.execute(
        select(
            WorkQueueItem.queue_type,
            func.count(WorkQueueItem.id).label("total"),
            func.count(WorkQueueItem.id).filter(
                WorkQueueItem.status == "completed"
            ).label("completed"),
            func.count(WorkQueueItem.id).filter(
                WorkQueueItem.status == "escalated"
            ).label("escalated"),
            func.count(WorkQueueItem.id).filter(
                WorkQueueItem.status == "failed"
            ).label("failed"),
            func.count(WorkQueueItem.id).filter(
                WorkQueueItem.sla_breached.is_(True)
            ).label("sla_breached"),
            func.avg(WorkQueueItem.time_spent_seconds).filter(
                WorkQueueItem.time_spent_seconds.isnot(None)
            ).label("avg_time_s"),
        )
        .where(*wqi_filter)
        .group_by(WorkQueueItem.queue_type)
        .order_by(func.count(WorkQueueItem.id).desc())
    )

    by_queue = [
        {
            "queue_type": row.queue_type,
            "total": row.total,
            "completed": row.completed,
            "escalated": row.escalated,
            "failed": row.failed,
            "sla_breached": row.sla_breached,
            "escalation_rate": (
                round(row.escalated / (row.completed + row.escalated + row.failed), 4)
                if (row.completed + row.escalated + row.failed) > 0
                else 0.0
            ),
            "avg_time_seconds": (
                round(float(row.avg_time_s), 1)
                if row.avg_time_s is not None
                else None
            ),
        }
        for row in by_queue_q
    ]

    return {
        # ── Volume ───────────────────────────────────────────────────────────
        "total_processed": total_processed,
        "pending": pending,
        "in_progress": in_progress,
        "completed": completed,
        "escalated": escalated,
        "failed": failed,
        # ── Quality / performance ─────────────────────────────────────────────
        "escalation_rate": (
            round(escalated / total_processed, 4) if total_processed else 0.0
        ),
        "failure_rate": (
            round(failed / total_processed, 4) if total_processed else 0.0
        ),
        "sla_breached": sla_breached,
        "sla_breach_rate": (
            round(
                sla_breached / (total_processed + pending + in_progress), 4
            )
            if (total_processed + pending + in_progress)
            else 0.0
        ),
        # ── Timing ──────────────────────────────────────────────────────────
        "avg_processing_time_seconds": (
            round(float(avg_time), 1) if avg_time is not None else None
        ),
        # ── Confidence ───────────────────────────────────────────────────────
        "avg_ai_confidence": (
            round(float(avg_conf_val), 4) if avg_conf_val is not None else None
        ),
        # ── Queue-type breakdown ─────────────────────────────────────────────
        "by_queue_type": by_queue,
    }
