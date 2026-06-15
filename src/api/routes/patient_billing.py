"""Patient billing — statements and payment collection routes."""
from __future__ import annotations
import uuid
from datetime import date
from decimal import Decimal
from typing import Any
from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from src.infrastructure.database.session import get_db
from src.infrastructure.auth.middleware import get_current_user
from src.infrastructure.database.models import PatientStatement, User
from src.core.patient_billing.service import get_patient_balance, record_patient_payment

router = APIRouter(prefix="/patient-billing", tags=["Patient Billing"])


class StatementResponse(BaseModel):
    id: uuid.UUID
    patient_id: uuid.UUID
    patient_name: str | None = None
    statement_number: str
    statement_date: date
    due_date: date | None
    total_charges: float
    total_insurance_paid: float
    total_adjustments: float
    total_patient_paid: float
    balance_due: float
    status: str
    delivery_method: str | None
    sent_at: Any
    paid_at: Any
    notes: str | None

    class Config:
        from_attributes = True


class PaymentRequest(BaseModel):
    statement_id: uuid.UUID
    amount: float
    payment_reference: str


class PatientBalanceResponse(BaseModel):
    patient_id: uuid.UUID
    total_balance: float
    open_statements: int


@router.get("/statements", response_model=list[StatementResponse])
async def list_statements(
    patient_id: uuid.UUID | None = None,
    status: str | None = None,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List patient statements for the practice."""
    # Internal company-admin / billing-manager users can see all practices
    user_type = current_user.get("user_type")
    internal_role = current_user.get("internal_role")
    practice_id = current_user.get("practice_id")
    is_global_internal = (
        user_type == "internal"
        and internal_role in ("company_admin", "billing_manager", "qa_reviewer")
    )

    filters = []
    if not is_global_internal and practice_id:
        filters.append(PatientStatement.practice_id == practice_id)

    if patient_id:
        filters.append(PatientStatement.patient_id == patient_id)
    if status:
        filters.append(PatientStatement.status == status)

    q = select(PatientStatement)
    if filters:
        q = q.where(*filters)

    result = await db.execute(
        q.order_by(desc(PatientStatement.statement_date)).offset(skip).limit(limit)
    )
    rows = result.scalars().all()
    out = []
    for s in rows:
        base = StatementResponse.model_validate(s)
        if s.patient:
            try:
                base.patient_name = f"{s.patient.first_name} {s.patient.last_name}".strip() or None
            except Exception:
                pass
        out.append(base)
    return out


@router.get("/statements/{statement_id}", response_model=StatementResponse)
async def get_statement(
    statement_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_type = current_user.get("user_type")
    internal_role = current_user.get("internal_role")
    practice_id = current_user.get("practice_id")
    is_global_internal = (
        user_type == "internal"
        and internal_role in ("company_admin", "billing_manager", "qa_reviewer")
    )
    conditions = [PatientStatement.id == statement_id]
    if not is_global_internal and practice_id:
        conditions.append(PatientStatement.practice_id == practice_id)

    result = await db.execute(select(PatientStatement).where(*conditions))
    stmt = result.scalar_one_or_none()
    if not stmt:
        raise HTTPException(status_code=404, detail="Statement not found")
    return StatementResponse.model_validate(stmt)


@router.get("/balance/{patient_id}", response_model=PatientBalanceResponse)
async def get_patient_outstanding_balance(
    patient_id: uuid.UUID,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get total outstanding patient balance."""
    from sqlalchemy import func as sqlfunc
    balance = await get_patient_balance(db, current_user.get("practice_id"), patient_id)
    count_result = await db.execute(
        select(sqlfunc.count(PatientStatement.id)).where(
            PatientStatement.practice_id == current_user.get("practice_id"),
            PatientStatement.patient_id == patient_id,
            PatientStatement.status.in_(["open", "partial"]),
        )
    )
    open_count = count_result.scalar() or 0
    return PatientBalanceResponse(
        patient_id=patient_id,
        total_balance=float(balance),
        open_statements=open_count,
    )


@router.post("/payments", response_model=dict)
async def post_patient_payment(
    data: PaymentRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Record a patient payment against a statement."""
    result = await record_patient_payment(
        db=db,
        statement_id=data.statement_id,
        amount=Decimal(str(data.amount)),
        payment_reference=data.payment_reference,
        posted_by_id=current_user.get("user_id"),
    )
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/ar-summary", response_model=dict)
async def get_patient_ar_summary(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """AR aging summary for patient balances: current, 30, 60, 90+ days."""
    from datetime import datetime, timedelta
    from sqlalchemy import func as sqlfunc, case
    user_type = current_user.get("user_type")
    internal_role = current_user.get("internal_role")
    practice_id = current_user.get("practice_id")
    is_global_internal = (
        user_type == "internal"
        and internal_role in ("company_admin", "billing_manager", "qa_reviewer")
    )
    today = date.today()
    base_filters = [PatientStatement.status.in_(["open", "partial"])]
    if not is_global_internal and practice_id:
        base_filters.append(PatientStatement.practice_id == practice_id)
    result = await db.execute(
        select(
            sqlfunc.sum(case(
                (PatientStatement.statement_date >= today - timedelta(days=30), PatientStatement.balance_due),
                else_=Decimal("0"),
            )).label("current_0_30"),
            sqlfunc.sum(case(
                (
                    (PatientStatement.statement_date < today - timedelta(days=30)) &
                    (PatientStatement.statement_date >= today - timedelta(days=60)),
                    PatientStatement.balance_due
                ),
                else_=Decimal("0"),
            )).label("days_31_60"),
            sqlfunc.sum(case(
                (
                    (PatientStatement.statement_date < today - timedelta(days=60)) &
                    (PatientStatement.statement_date >= today - timedelta(days=90)),
                    PatientStatement.balance_due
                ),
                else_=Decimal("0"),
            )).label("days_61_90"),
            sqlfunc.sum(case(
                (PatientStatement.statement_date < today - timedelta(days=90), PatientStatement.balance_due),
                else_=Decimal("0"),
            )).label("days_90_plus"),
            sqlfunc.sum(PatientStatement.balance_due).label("total"),
            sqlfunc.count(PatientStatement.id).label("open_count"),
        ).where(*base_filters)
    )
    row = result.one()
    total = float(row.total or 0)
    c0_30 = float(row.current_0_30 or 0)
    d31_60 = float(row.days_31_60 or 0)
    d61_90 = float(row.days_61_90 or 0)
    d90_plus = float(row.days_90_plus or 0)
    return {
        # Frontend-expected field names
        "total_ar": total,
        "current_0_30": c0_30,
        "ar_31_60": d31_60,
        "ar_61_90": d61_90,
        "ar_90_plus": d90_plus,
        # Legacy names kept for compatibility
        "days_31_60": d31_60,
        "days_61_90": d61_90,
        "days_90_plus": d90_plus,
        "total": total,
        "open_statement_count": row.open_count or 0,
    }
