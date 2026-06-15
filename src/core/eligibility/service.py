"""Eligibility verification service — real-time 270/271 and manual entry."""
from __future__ import annotations
import uuid
from datetime import datetime, date
from decimal import Decimal
from typing import Any
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from src.infrastructure.database.models import EligibilityCheck, Patient, Coverage, Payer
from src.core.eligibility.plan_types import normalize_plan_type

logger = structlog.get_logger()


async def run_eligibility_check(
    db: AsyncSession,
    practice_id: uuid.UUID,
    patient_id: uuid.UUID,
    coverage_id: uuid.UUID | None = None,
    charge_batch_id: uuid.UUID | None = None,
    service_date: date | None = None,
    checked_by_id: uuid.UUID | None = None,
) -> EligibilityCheck:
    """
    Run eligibility check for a patient/coverage combination.
    Currently performs a rule-based mock check using coverage data on file.
    When a clearinghouse API key is configured in settings, routes to the 270/271 transaction.
    """
    from src.config import settings

    # Load coverage
    coverage = None
    if coverage_id:
        result = await db.execute(select(Coverage).where(Coverage.id == coverage_id))
        coverage = result.scalar_one_or_none()

    # Check if clearinghouse API is configured
    if getattr(settings, "clearinghouse_api_key", None):
        return await _run_clearinghouse_check(
            db, practice_id, patient_id, coverage, charge_batch_id, service_date, checked_by_id
        )
    else:
        return await _run_coverage_based_check(
            db, practice_id, patient_id, coverage, charge_batch_id, service_date, checked_by_id
        )


async def _run_coverage_based_check(
    db: AsyncSession,
    practice_id: uuid.UUID,
    patient_id: uuid.UUID,
    coverage: Coverage | None,
    charge_batch_id: uuid.UUID | None,
    service_date: date | None,
    checked_by_id: uuid.UUID | None,
) -> EligibilityCheck:
    """Rule-based eligibility using coverage dates and status on file."""
    check_date = datetime.utcnow()
    svc_date = service_date or date.today()

    if coverage is None:
        check = EligibilityCheck(
            practice_id=practice_id,
            patient_id=patient_id,
            charge_batch_id=charge_batch_id,
            status="inactive",
            is_active=False,
            check_date=check_date,
            service_date=svc_date,
            error_message="No coverage on file for this patient.",
            checked_by_id=checked_by_id,
        )
        db.add(check)
        await db.flush()
        return check

    # Evaluate coverage dates
    is_active = True
    error_msgs = []

    if coverage.effective_date and svc_date < coverage.effective_date:
        is_active = False
        error_msgs.append(
            f"Service date {svc_date} is before coverage effective date {coverage.effective_date}."
        )
    if coverage.termination_date and svc_date > coverage.termination_date:
        is_active = False
        error_msgs.append(f"Coverage terminated on {coverage.termination_date}.")

    status = "active" if is_active else "inactive"

    check = EligibilityCheck(
        practice_id=practice_id,
        patient_id=patient_id,
        coverage_id=coverage.id if coverage else None,
        charge_batch_id=charge_batch_id,
        payer_id=coverage.payer_id if coverage else None,
        status=status,
        is_active=is_active,
        check_date=check_date,
        service_date=svc_date,
        plan_name=getattr(coverage, "plan_name", None),
        plan_type=normalize_plan_type(getattr(coverage, "plan_type", None)),
        group_number=getattr(coverage, "group_number", None),
        network_status="unknown",
        error_message="; ".join(error_msgs) if error_msgs else None,
        checked_by_id=checked_by_id,
        raw_response={
            "source": "coverage_on_file",
            "member_id": getattr(coverage, "member_id", None),
            "effective_date": str(coverage.effective_date) if coverage.effective_date else None,
            "termination_date": str(coverage.termination_date) if coverage.termination_date else None,
        },
    )
    db.add(check)
    await db.flush()
    logger.info("eligibility_check_complete", patient_id=str(patient_id), status=status)
    return check


async def _run_clearinghouse_check(
    db: AsyncSession,
    practice_id: uuid.UUID,
    patient_id: uuid.UUID,
    coverage: Coverage | None,
    charge_batch_id: uuid.UUID | None,
    service_date: date | None,
    checked_by_id: uuid.UUID | None,
) -> EligibilityCheck:
    """Real-time 270/271 via the configured CAQH CORE clearinghouse (CMS HETS for Medicare).
    Falls back to coverage-on-file when the clearinghouse is unconfigured or errors."""
    from src.config import settings
    from src.core.eligibility.clearinghouse import is_configured, check_eligibility_271
    from src.core.eligibility.plan_types import normalize_plan_type
    from src.infrastructure.database.models import Practice

    if coverage is None or not is_configured(settings):
        return await _run_coverage_based_check(
            db, practice_id, patient_id, coverage, charge_batch_id, service_date, checked_by_id
        )

    patient = (await db.execute(select(Patient).where(Patient.id == patient_id))).scalar_one_or_none()
    payer = (await db.execute(select(Payer).where(Payer.id == coverage.payer_id))).scalar_one_or_none()
    practice = (await db.execute(select(Practice).where(Practice.id == practice_id))).scalar_one_or_none()

    parsed = await check_eligibility_271(
        settings,
        payer_name=getattr(payer, "payer_name", "") or "",
        payer_id=getattr(payer, "payer_id", "") or getattr(payer, "edi_payer_id", "") or "",
        provider_last_or_org=getattr(practice, "name", "") or "",
        provider_npi=getattr(practice, "group_npi", "") or "",
        subscriber_first=getattr(patient, "first_name", "") or "",
        subscriber_last=getattr(patient, "last_name", "") or "",
        member_id=getattr(coverage, "member_id", "") or "",
        subscriber_dob=getattr(patient, "date_of_birth", None),
        service_date=service_date,
    )
    if not parsed or parsed.get("error") or parsed.get("status") in (None, "unknown", "error"):
        logger.warning("clearinghouse_eligibility_fallback", error=(parsed or {}).get("error"))
        return await _run_coverage_based_check(
            db, practice_id, patient_id, coverage, charge_batch_id, service_date, checked_by_id
        )

    check = EligibilityCheck(
        practice_id=practice_id,
        patient_id=patient_id,
        coverage_id=coverage.id,
        charge_batch_id=charge_batch_id,
        payer_id=coverage.payer_id,
        status=parsed["status"],
        is_active=parsed["is_active"],
        check_date=datetime.utcnow(),
        service_date=service_date or date.today(),
        plan_name=parsed.get("plan_name") or getattr(coverage, "plan_name", None),
        plan_type=parsed.get("plan_type") or normalize_plan_type(getattr(coverage, "plan_type", None)),
        group_number=getattr(coverage, "group_number", None),
        network_status=parsed.get("network_status") or "unknown",
        deductible_total=parsed.get("deductible_total"),
        oop_total=parsed.get("oop_total"),
        copay=parsed.get("copay"),
        coinsurance_pct=parsed.get("coinsurance_pct"),
        checked_by_id=checked_by_id,
        raw_response={"source": "clearinghouse_271", "payload_id": parsed.get("payload_id"), "x271": parsed.get("_271")},
    )
    db.add(check)
    await db.flush()
    logger.info("eligibility_271_complete", patient_id=str(patient_id), status=parsed["status"], plan_type=parsed.get("plan_type"))
    return check

async def get_latest_eligibility(
    db: AsyncSession,
    practice_id: uuid.UUID,
    patient_id: uuid.UUID,
    coverage_id: uuid.UUID | None = None,
) -> EligibilityCheck | None:
    """Get most recent eligibility check for a patient."""
    q = select(EligibilityCheck).where(
        EligibilityCheck.practice_id == practice_id,
        EligibilityCheck.patient_id == patient_id,
    )
    if coverage_id:
        q = q.where(EligibilityCheck.coverage_id == coverage_id)
    q = q.order_by(EligibilityCheck.check_date.desc()).limit(1)
    result = await db.execute(q)
    return result.scalar_one_or_none()
