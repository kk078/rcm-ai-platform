"""Patient billing service — statement generation and payment recording."""
from __future__ import annotations
import uuid
from datetime import date, timedelta
from decimal import Decimal
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = structlog.get_logger()


async def get_patient_balance(
    db: AsyncSession,
    practice_id: uuid.UUID,
    patient_id: uuid.UUID,
) -> Decimal:
    """Sum all open patient statement balances for a patient."""
    from src.infrastructure.database.models import PatientStatement
    from sqlalchemy import func as sqlfunc

    result = await db.execute(
        select(sqlfunc.sum(PatientStatement.balance_due)).where(
            PatientStatement.practice_id == practice_id,
            PatientStatement.patient_id == patient_id,
            PatientStatement.status.in_(["open", "partial"]),
        )
    )
    return result.scalar() or Decimal("0.00")


async def record_patient_payment(
    db: AsyncSession,
    statement_id: uuid.UUID,
    amount: Decimal,
    payment_reference: str,
    posted_by_id: uuid.UUID | None = None,
) -> dict:
    """Apply a patient payment to an open statement."""
    from src.infrastructure.database.models import PatientStatement
    from datetime import datetime

    result = await db.execute(
        select(PatientStatement).where(PatientStatement.id == statement_id)
    )
    stmt = result.scalar_one_or_none()
    if not stmt:
        return {"error": "Statement not found"}

    stmt.total_patient_paid = (stmt.total_patient_paid or Decimal("0")) + amount
    new_balance = stmt.balance_due - amount

    if new_balance <= Decimal("0.01"):
        stmt.status = "paid"
        stmt.balance_due = Decimal("0.00")
        stmt.paid_at = datetime.utcnow()
    else:
        stmt.status = "partial"
        stmt.balance_due = new_balance

    stmt.payment_reference = payment_reference
    await db.flush()
    logger.info(
        "patient_payment_recorded",
        statement_id=str(statement_id),
        amount=float(amount),
        new_status=stmt.status,
    )
    return {
        "statement_id": str(statement_id),
        "new_balance": float(stmt.balance_due),
        "status": stmt.status,
    }


async def void_statement(
    db: AsyncSession,
    statement_id: uuid.UUID,
    reason: str,
    voided_by_id: uuid.UUID,
) -> dict:
    """Void an open patient statement."""
    from src.infrastructure.database.models import PatientStatement

    result = await db.execute(
        select(PatientStatement).where(PatientStatement.id == statement_id)
    )
    stmt = result.scalar_one_or_none()
    if not stmt:
        return {"error": "Statement not found"}

    if stmt.status == "paid":
        return {"error": "Cannot void a paid statement"}

    stmt.status = "voided"
    stmt.notes = (stmt.notes or "") + f"\nVoided: {reason}"
    await db.flush()
    logger.info("patient_statement_voided", statement_id=str(statement_id), reason=reason)
    return {"statement_id": str(statement_id), "status": "voided"}


async def list_patient_statements(
    db: AsyncSession,
    practice_id: uuid.UUID,
    patient_id: uuid.UUID,
    status: str | None = None,
) -> list:
    """List all statements for a patient, optionally filtered by status."""
    from src.infrastructure.database.models import PatientStatement

    q = select(PatientStatement).where(
        PatientStatement.practice_id == practice_id,
        PatientStatement.patient_id == patient_id,
    )
    if status:
        q = q.where(PatientStatement.status == status)
    q = q.order_by(PatientStatement.statement_date.desc())

    result = await db.execute(q)
    return result.scalars().all()
