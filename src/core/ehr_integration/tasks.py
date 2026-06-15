"""Celery tasks for EHR integration — SFTP polling, FHIR sync, auto-close denials."""
from __future__ import annotations
import asyncio
import structlog
from celery import shared_task

logger = structlog.get_logger()


@shared_task(bind=True, max_retries=3, default_retry_delay=120)
def sftp_file_watcher(self):
    """Poll all active SFTP EHR connections for new patient/charge files."""
    try:
        asyncio.run(_poll_all_sftp_connections())  # py3.12: get_event_loop() invalid in worker thread
    except Exception as exc:
        logger.error("sftp_watcher_failed", error=str(exc))
        raise self.retry(exc=exc)


async def _poll_all_sftp_connections():
    from sqlalchemy import select
    from src.infrastructure.database.session import async_session as async_session_factory
    from src.infrastructure.database.models import EHRConnection

    async with async_session_factory() as db:
        result = await db.execute(
            select(EHRConnection).where(
                EHRConnection.ehr_type == "sftp_csv",
                EHRConnection.is_active == True,
            )
        )
        connections = result.scalars().all()

    for conn in connections:
        try:
            await _poll_sftp_connection(conn)
        except Exception as exc:
            logger.error(
                "sftp_connection_poll_failed", conn_id=str(conn.id), error=str(exc)
            )


async def _poll_sftp_connection(conn):
    """Poll a single SFTP connection for new CSV files and import them."""
    try:
        import paramiko
    except ImportError:
        logger.warning("paramiko_not_installed_skipping_sftp")
        return

    from src.infrastructure.database.session import async_session as async_session_factory
    from src.core.ehr_integration.service import (
        import_patients_from_csv,
        import_encounters_from_csv,
    )

    sftp_host = conn.sftp_host
    sftp_port = conn.sftp_port or 22
    sftp_user = conn.sftp_username
    sftp_path = conn.sftp_path or "/incoming"

    if not sftp_host or not sftp_user:
        return

    try:
        transport = paramiko.Transport((sftp_host, sftp_port))
        transport.connect(username=sftp_user, password=conn.sftp_password_enc)
        sftp = paramiko.SFTPClient.from_transport(transport)

        files = sftp.listdir(sftp_path)
        processed_path = f"{sftp_path}/processed"
        try:
            sftp.mkdir(processed_path)
        except Exception:
            pass  # already exists

        for filename in files:
            if not filename.endswith(".csv"):
                continue
            remote_path = f"{sftp_path}/{filename}"
            content = sftp.open(remote_path).read()

            async with async_session_factory() as db:
                if "patient" in filename.lower():
                    result = await import_patients_from_csv(
                        db, conn.practice_id, content, conn.id
                    )
                elif "encounter" in filename.lower() or "charge" in filename.lower():
                    result = await import_encounters_from_csv(
                        db, conn.practice_id, content, conn.id
                    )
                else:
                    # Default: attempt patient import
                    result = await import_patients_from_csv(
                        db, conn.practice_id, content, conn.id
                    )
                await db.commit()

            # Move to processed directory
            sftp.rename(remote_path, f"{processed_path}/{filename}")
            logger.info("sftp_file_processed", file=filename, result=result)

        sftp.close()
        transport.close()

    except Exception as exc:
        logger.error("sftp_poll_error", host=sftp_host, error=str(exc))


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def sync_fhir_all_practices(self):
    """Sync patients from all active FHIR R4 EHR connections."""
    try:
        asyncio.get_event_loop().run_until_complete(_sync_all_fhir())
    except Exception as exc:
        raise self.retry(exc=exc)


async def _sync_all_fhir():
    from sqlalchemy import select
    from src.infrastructure.database.session import async_session as async_session_factory
    from src.infrastructure.database.models import EHRConnection
    from src.core.ehr_integration.service import sync_fhir_patients

    async with async_session_factory() as db:
        result = await db.execute(
            select(EHRConnection).where(
                EHRConnection.ehr_type == "fhir_r4",
                EHRConnection.is_active == True,
            )
        )
        connections = result.scalars().all()
        count = len(connections)
        for conn in connections:
            await sync_fhir_patients(db, conn.id, conn.practice_id)
            await db.commit()
        logger.info("fhir_sync_complete", count=count)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def auto_close_resolved_denials(self):
    """When ERA payment posts on a denied claim, auto-close the open denial."""
    try:
        asyncio.get_event_loop().run_until_complete(_auto_close_denials())
    except Exception as exc:
        raise self.retry(exc=exc)


async def _auto_close_denials():
    """
    Find denials where the underlying claim has been paid (status='paid')
    but the denial record is still open. Close them automatically.
    """
    from sqlalchemy import select
    from src.infrastructure.database.session import async_session as async_session_factory
    from src.infrastructure.database.models import Denial, Claim, Appeal

    async with async_session_factory() as db:
        result = await db.execute(
            select(Denial)
            .join(Claim, Denial.claim_id == Claim.id)
            .where(
                Denial.status.in_(["open", "pending", "appealed"]),
                Claim.status == "paid",
            )
            .limit(200)
        )
        denials = result.scalars().all()
        closed = 0

        for denial in denials:
            denial.status = "resolved"
            denial.resolution = "auto_closed_payment_received"
            closed += 1

            # Close open appeals on this denial too
            appeal_result = await db.execute(
                select(Appeal).where(
                    Appeal.denial_id == denial.id,
                    Appeal.status == "pending",
                )
            )
            for appeal in appeal_result.scalars().all():
                appeal.status = "approved"
                appeal.outcome = "payment_received"

        await db.commit()
        logger.info("auto_closed_denials", count=closed)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def generate_patient_statements(self):
    """
    Daily task: Generate patient statements for all claims with
    outstanding patient balance (PR-coded adjustments).
    """
    try:
        asyncio.get_event_loop().run_until_complete(_generate_statements())
    except Exception as exc:
        raise self.retry(exc=exc)


async def _generate_statements():
    from datetime import date, timedelta
    from decimal import Decimal
    import random
    import string
    from sqlalchemy import select, func as sqlfunc
    from src.infrastructure.database.session import async_session as async_session_factory
    from src.infrastructure.database.models import (
        Adjustment,
        PaymentLine,
        Claim,
        PatientStatement,
    )

    async with async_session_factory() as db:
        # Find patient balances from PR-coded adjustments not yet on a statement
        result = await db.execute(
            select(
                Adjustment.practice_id,
                PaymentLine.claim_id,
                Claim.patient_id,
                sqlfunc.sum(Adjustment.amount).label("patient_balance"),
            )
            .join(PaymentLine, Adjustment.payment_line_id == PaymentLine.id)
            .join(Claim, PaymentLine.claim_id == Claim.id)
            .where(
                Adjustment.carc_code.like("PR%"),
                Adjustment.amount > 0,
            )
            .group_by(
                Adjustment.practice_id,
                PaymentLine.claim_id,
                Claim.patient_id,
            )
            .having(sqlfunc.sum(Adjustment.amount) > Decimal("0.01"))
            .limit(500)
        )
        rows = result.all()

        created = 0
        for row in rows:
            # Skip if an open statement already exists for this patient
            existing = await db.execute(
                select(PatientStatement).where(
                    PatientStatement.practice_id == row.practice_id,
                    PatientStatement.patient_id == row.patient_id,
                    PatientStatement.status == "open",
                )
            )
            if existing.scalar_one_or_none():
                continue

            stmt_num = "STM-" + "".join(
                random.choices(string.ascii_uppercase + string.digits, k=8)
            )
            stmt = PatientStatement(
                practice_id=row.practice_id,
                patient_id=row.patient_id,
                statement_number=stmt_num,
                statement_date=date.today(),
                due_date=date.today() + timedelta(days=30),
                balance_due=row.patient_balance,
                status="open",
            )
            db.add(stmt)
            created += 1

        await db.commit()
        logger.info("patient_statements_generated", count=created)
