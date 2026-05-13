"""Analytics and reporting routes."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.database.session import get_db
from src.infrastructure.database.models import Claim, Denial, Practice
from src.infrastructure.auth.middleware import get_current_user

router = APIRouter()


@router.get("/dashboard")
async def get_dashboard(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Main dashboard KPIs: claims, payments, denials, revenue."""
    total_claims = await db.execute(select(func.count(Claim.id)))
    open_denials = await db.execute(
        select(func.count(Denial.id)).where(Denial.status.in_(["new", "appealed", "in_progress"]))
    )
    total_payments = await db.execute(select(func.coalesce(func.sum(Claim.total_paid), 0)))
    denied_claims = await db.execute(
        select(func.count(Claim.id)).where(Claim.status == "denied")
    )
    total_submitted = await db.execute(
        select(func.count(Claim.id)).where(Claim.status != "draft")
    )

    claims_count = total_claims.scalar() or 0
    denials_count = open_denials.scalar() or 0
    payments = float(total_payments.scalar() or 0)
    denied = denied_claims.scalar() or 0
    submitted = total_submitted.scalar() or 1

    return {
        "total_claims": claims_count,
        "total_collections": payments,
        "denial_rate": round(denied / submitted, 4) if submitted else 0.0,
        "avg_days_in_ar": 0.0,
        "clean_claim_rate": 0.0,
    }


@router.get("/revenue-cycle")
async def revenue_cycle_report(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Full revenue cycle metrics: days in AR, clean claim rate, denial rate."""
    return {
        "days_in_ar": 0.0,
        "clean_claim_rate": 0.0,
        "denial_rate": 0.0,
        "first_pass_resolution_rate": 0.0,
        "avg_reimbursement_per_claim": 0.0,
    }


@router.get("/coding-accuracy")
async def coding_accuracy_report(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """AI coding accuracy vs coder corrections."""
    return {
        "total_sessions": 0,
        "ai_suggested_accepted": 0,
        "coder_corrections": 0,
        "accuracy_rate": 0.0,
        "by_coder": [],
    }


@router.get("/payer-performance")
async def payer_performance(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """Payer comparison: payment speed, denial rates, underpayments."""
    return []


@router.get("/aging-report")
async def aging_report(
    db: AsyncSession = Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    """AR aging report: 0-30, 31-60, 61-90, 91-120, 120+ days."""
    return {
        "buckets": [
            {"range": "0-30", "amount": 0, "count": 0},
            {"range": "31-60", "amount": 0, "count": 0},
            {"range": "61-90", "amount": 0, "count": 0},
            {"range": "91-120", "amount": 0, "count": 0},
            {"range": "120+", "amount": 0, "count": 0},
        ]
    }