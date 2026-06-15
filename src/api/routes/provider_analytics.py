"""Provider performance analytics routes."""
from __future__ import annotations
import uuid
from datetime import date, timedelta
from typing import Any
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func as sqlfunc, and_
from src.infrastructure.database.session import get_db
from src.infrastructure.auth.middleware import get_current_user
from src.infrastructure.database.models import (
    Claim, Denial, AICodingFeedback, User,
    PaymentLine, Adjustment, Encounter
)

router = APIRouter(prefix="/provider-analytics", tags=["Provider Analytics"])


@router.get("/summary")
async def get_provider_analytics_summary(
    provider_id: uuid.UUID | None = None,
    period_days: int = Query(default=30, ge=7, le=365),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Provider performance summary: charges, collections, denial rate,
    AI coding accuracy for a given period.
    """
    start_date = date.today() - timedelta(days=period_days)

    # Claims submitted in period
    claim_filters = [
        Claim.practice_id == current_user.get("practice_id"),
        Claim.created_at >= start_date,
    ]
    if provider_id:
        claim_filters.append(Claim.rendering_provider == provider_id)

    claim_result = await db.execute(
        select(
            sqlfunc.count(Claim.id).label("total_claims"),
            sqlfunc.sum(Claim.total_charge).label("total_billed"),
            sqlfunc.count(Claim.id).filter(Claim.status == "paid").label("paid_claims"),
            sqlfunc.count(Claim.id).filter(Claim.status == "denied").label("denied_claims"),
        ).where(*claim_filters)
    )
    claim_row = claim_result.one()

    # Denial rate
    total = claim_row.total_claims or 0
    denied = claim_row.denied_claims or 0
    denial_rate = round((denied / total * 100), 1) if total > 0 else 0.0

    # Payments collected
    payment_result = await db.execute(
        select(sqlfunc.sum(PaymentLine.paid_amount)).join(
            Claim, PaymentLine.claim_id == Claim.id
        ).where(
            Claim.practice_id == current_user.get("practice_id"),
            PaymentLine.created_at >= start_date,
        )
    )
    total_collected = float(payment_result.scalar() or 0)
    total_billed = float(claim_row.total_billed or 0)
    collection_rate = round((total_collected / total_billed * 100), 1) if total_billed > 0 else 0.0

    # AI coding accuracy (from feedback)
    ai_result = await db.execute(
        select(
            sqlfunc.count(AICodingFeedback.id).label("total_sessions"),
            sqlfunc.count(AICodingFeedback.id).filter(
                AICodingFeedback.cpt_accepted == True
            ).label("cpt_accepted"),
            sqlfunc.count(AICodingFeedback.id).filter(
                AICodingFeedback.dx_accepted == True
            ).label("dx_accepted"),
        ).where(
            AICodingFeedback.practice_id == current_user.get("practice_id"),
            AICodingFeedback.created_at >= start_date,
        )
    )
    ai_row = ai_result.one()
    total_ai = ai_row.total_sessions or 0
    cpt_accuracy = round((ai_row.cpt_accepted / total_ai * 100), 1) if total_ai > 0 else None
    dx_accuracy = round((ai_row.dx_accepted / total_ai * 100), 1) if total_ai > 0 else None

    # Return flat structure with 0-1 decimals — matches AnalyticsSummary interface in frontend
    return {
        "total_claims": total,
        "denial_rate": round(denied / total, 4) if total > 0 else 0.0,
        "collection_rate": round(total_collected / total_billed, 4) if total_billed > 0 else 0.0,
        "total_collected": total_collected,
        "ai_cpt_acceptance_rate": round(ai_row.cpt_accepted / total_ai, 4) if total_ai > 0 else None,
        "ai_dx_acceptance_rate": round(ai_row.dx_accepted / total_ai, 4) if total_ai > 0 else None,
        # Extra context fields (ignored by frontend but useful for debugging)
        "period_days": period_days,
        "period_start": str(start_date),
    }


@router.get("/denial-breakdown")
async def get_denial_breakdown(
    period_days: int = Query(default=90, ge=7, le=365),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Top denial reasons for the practice in the period."""
    start_date = date.today() - timedelta(days=period_days)
    result = await db.execute(
        select(
            Denial.reason_code.label("denial_code"),
            Denial.category.label("denial_reason"),
            sqlfunc.count(Denial.id).label("count"),
            sqlfunc.sum(Denial.denial_amount).label("denied_amount"),
        ).where(
            Denial.practice_id == current_user.get("practice_id"),
            Denial.created_at >= start_date,
        ).group_by(Denial.reason_code, Denial.category)
        .order_by(sqlfunc.count(Denial.id).desc())
        .limit(15)
    )
    return [
        {
            "denial_code": row.denial_code or "—",
            "denial_reason": row.denial_reason or row.denial_code or "Unknown",
            "count": row.count,
            "denied_amount": float(row.denied_amount or 0),
        }
        for row in result.all()
    ]


@router.get("/ai-feedback-summary")
async def get_ai_feedback_summary(
    period_days: int = Query(default=30, ge=7, le=180),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Summary of AI coding suggestions accepted vs. overridden."""
    start_date = date.today() - timedelta(days=period_days)
    result = await db.execute(
        select(
            AICodingFeedback.specialty,
            sqlfunc.count(AICodingFeedback.id).label("total"),
            sqlfunc.count(AICodingFeedback.id).filter(
                AICodingFeedback.cpt_accepted == True
            ).label("cpt_accepted"),
            sqlfunc.count(AICodingFeedback.id).filter(
                AICodingFeedback.dx_accepted == True
            ).label("dx_accepted"),
        ).where(
            AICodingFeedback.practice_id == current_user.get("practice_id"),
            AICodingFeedback.created_at >= start_date,
        ).group_by(AICodingFeedback.specialty)
    )
    rows = result.all()
    return [
        {
            "specialty": row.specialty or "Unknown",
            "total_sessions": row.total,
            "cpt_acceptance_rate": round(row.cpt_accepted / row.total * 100, 1) if row.total else 0,
            "dx_acceptance_rate": round(row.dx_accepted / row.total * 100, 1) if row.total else 0,
        }
        for row in rows
    ]
