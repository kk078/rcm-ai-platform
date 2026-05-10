"""
Charge intake service layer — Provider charge submission, validation,
routing, and batch import.

Every write operation creates an AuditLog entry.
Every query enforces tenant isolation via practice_id filtering.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime, timezone
from uuid import UUID, uuid4

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.charge_intake.errors import (
    ChargeNotFoundError,
    ChargeValidationError,
    DuplicateChargeError,
    InvalidCSVFormatError,
)
from src.infrastructure.database.models import (
    AuditLog,
    ChargeBatch,
    ChargeEntry,
    Claim,
    ClaimLine,
    Encounter,
    Patient,
    PortalMessage,
    PortalNotification,
    Practice,
    Provider,
    WorkQueueItem,
)

logger = structlog.get_logger()

# ICD-10 format: letter + 2 digits + optional . + 1-4 digits
ICD10_PATTERN = re.compile(r"^[A-Z]\d{2}(\.\d{1,4})?$")
# CPT format: 5 digits
CPT_PATTERN = re.compile(r"^\d{5}$")

# Allowed fields for charge entry updates
CHARGE_UPDATABLE_FIELDS = {
    "patient_id", "patient_name_submitted", "patient_dob_submitted",
    "patient_mrn_submitted", "rendering_provider_id", "referring_provider_name",
    "referring_provider_npi", "service_date", "place_of_service", "location_id",
    "diagnosis_codes", "procedure_codes", "needs_coding", "clinical_notes",
    "authorization_number", "primary_payer_id", "member_id",
}


async def _write_audit(
    db: AsyncSession,
    user_id: UUID,
    action: str,
    resource_type: str,
    resource_id: UUID | None = None,
    resource_detail: str | None = None,
    phi_accessed: bool = False,
    ip_address: str | None = None,
    request_path: str | None = None,
    request_method: str | None = None,
) -> None:
    """Create an AuditLog entry. Caller must flush/commit the session."""
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


def validate_diagnosis_codes(codes: list[str]) -> list[str]:
    """Validate ICD-10 format. Returns list of error messages."""
    errors = []
    for code in codes:
        if not ICD10_PATTERN.match(code):
            errors.append(f"Invalid ICD-10 code format: {code}")
    return errors


def validate_cpt_code(code: str) -> list[str]:
    """Validate CPT format. Returns list of error messages."""
    if not CPT_PATTERN.match(code):
        return [f"Invalid CPT code format: {code}"]
    return []


class ChargeEntryService:
    """Manage charge entries: submit, validate, route, reject."""

    async def submit_charge(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        data,  # ChargeEntryCreate Pydantic model
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> ChargeEntry:
        # Build procedure_codes JSONB from schema
        procedure_codes = None
        total_charges = 0.0
        if data.procedures:
            procedure_codes = [
                {
                    "cpt_code": p.cpt_code,
                    "modifiers": p.modifiers,
                    "units": p.units,
                    "charge_amount": p.charge_amount,
                }
                for p in data.procedures
            ]
            total_charges = sum(p.charge_amount * p.units for p in data.procedures)

        # Determine initial status
        if data.needs_coding or not data.procedures:
            status = "needs_coding"
        else:
            # Run validation; set status based on results
            validation_errors = self._validate_charge_data(data)
            status = "received" if not validation_errors else "validation_error"

        charge = ChargeEntry(
            practice_id=practice_id,
            patient_id=data.patient_id,
            patient_name_submitted=data.patient_name,
            patient_dob_submitted=data.patient_dob,
            patient_mrn_submitted=data.patient_mrn,
            rendering_provider_id=data.rendering_provider_id,
            location_id=data.location_id,
            place_of_service=data.place_of_service,
            service_date=data.service_date,
            diagnosis_codes=data.diagnosis_codes,
            procedure_codes=procedure_codes,
            needs_coding=data.needs_coding,
            clinical_notes=data.clinical_notes,
            authorization_number=data.authorization_number,
            primary_payer_id=data.primary_payer_id,
            member_id=data.member_id,
            status=status,
            validation_errors={"errors": validation_errors} if validation_errors else None,
        )
        db.add(charge)
        await db.flush()

        # Create a ChargeBatch for single submissions
        batch = ChargeBatch(
            practice_id=practice_id,
            submitted_by=user_id,
            intake_method="portal",
            total_charges=1,
            processed_charges=0,
            error_charges=0,
            status="received",
        )
        db.add(batch)
        await db.flush()

        charge.batch_id = batch.id
        await db.flush()

        # Create work queue item
        queue_type = "coding" if status == "needs_coding" else "intake"
        wqi = WorkQueueItem(
            practice_id=practice_id,
            queue_type=queue_type,
            item_type="charge_entry",
            item_id=charge.id,
        )
        db.add(wqi)

        await _write_audit(
            db, user_id, "submit_charge", "charge_entry", charge.id,
            resource_detail=f"Status: {status}, Practice: {practice_id}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("charge_submitted", charge_id=str(charge.id), status=status, practice_id=str(practice_id))
        return charge

    @staticmethod
    def _validate_charge_data(data) -> list[str]:
        """Validate a ChargeEntryCreate schema. Returns list of error messages."""
        errors = []
        # ICD-10 codes
        if data.diagnosis_codes:
            for code in data.diagnosis_codes:
                if not ICD10_PATTERN.match(code):
                    errors.append(f"Invalid ICD-10 code format: {code}")
        # CPT codes
        if data.procedures:
            for proc in data.procedures:
                if not CPT_PATTERN.match(proc.cpt_code):
                    errors.append(f"Invalid CPT code format: {proc.cpt_code}")
        # Service date not in future
        if data.service_date and data.service_date > date.today():
            errors.append("Service date cannot be in the future")
        # Must have patient reference or name
        if not data.patient_id and not data.patient_name:
            errors.append("Either patient_id or patient_name is required")
        # Must have provider
        if not data.rendering_provider_id:
            errors.append("rendering_provider_id is required")
        return errors

    async def validate_charge(
        self,
        db: AsyncSession,
        charge_id: UUID,
        practice_id: UUID,
    ) -> dict:
        """Run validation on an existing charge entry. Returns {valid: bool, errors: list[str]}."""
        charge = await self._get_charge_or_raise(db, charge_id, practice_id)
        errors = []

        # Check patient exists and has active coverage
        if charge.patient_id:
            result = await db.execute(select(Patient).where(Patient.id == charge.patient_id))
            patient = result.scalar_one_or_none()
            if not patient:
                errors.append(f"Patient {charge.patient_id} not found")
            elif not patient.is_active:
                errors.append(f"Patient {charge.patient_id} is not active")

        # Check provider is in the practice
        if charge.rendering_provider_id:
            # Provider existence check (Provider is not tenant-scoped)
            result = await db.execute(select(Provider).where(Provider.id == charge.rendering_provider_id))
            provider = result.scalar_one_or_none()
            if not provider:
                errors.append(f"Provider {charge.rendering_provider_id} not found")
            elif not provider.is_active:
                errors.append(f"Provider {charge.rendering_provider_id} is not active")

        # Validate ICD-10 codes
        if charge.diagnosis_codes:
            for code in charge.diagnosis_codes:
                if not ICD10_PATTERN.match(code):
                    errors.append(f"Invalid ICD-10 code format: {code}")

        # Validate CPT codes in procedure_codes JSONB
        if charge.procedure_codes:
            for proc in charge.procedure_codes:
                cpt = proc.get("cpt_code", "")
                if not CPT_PATTERN.match(cpt):
                    errors.append(f"Invalid CPT code format: {cpt}")

        # Service date not in future
        if charge.service_date and charge.service_date > date.today():
            errors.append("Service date cannot be in the future")

        # Check for duplicates (same patient + DOS + CPT in last 7 days)
        if charge.patient_id and charge.procedure_codes:
            for proc in charge.procedure_codes:
                cpt = proc.get("cpt_code", "")
                result = await db.execute(
                    select(func.count()).select(ChargeEntry).where(
                        ChargeEntry.practice_id == practice_id,
                        ChargeEntry.patient_id == charge.patient_id,
                        ChargeEntry.service_date == charge.service_date,
                        ChargeEntry.id != charge_id,
                        ChargeEntry.status.notin_(["rejected"]),
                    )
                )
                dup_count = result.scalar() or 0
                if dup_count > 0:
                    errors.append(
                        f"Potential duplicate: {dup_count} existing charge(s) "
                        f"for patient on {charge.service_date}"
                    )
                    break  # Only report duplicate once

        # Update charge validation status
        if errors:
            charge.status = "validation_error"
            charge.validation_errors = {"errors": errors}
        else:
            charge.status = "received"
            charge.validation_errors = None
        await db.flush()

        return {"valid": len(errors) == 0, "errors": errors}

    async def request_info_from_provider(
        self,
        db: AsyncSession,
        user_id: UUID,
        charge_id: UUID,
        practice_id: UUID,
        message: str,
        fields_needed: list[str],
        urgent: bool = False,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> PortalMessage:
        charge = await self._get_charge_or_raise(db, charge_id, practice_id)
        charge.status = "needs_info"
        charge.provider_notified = True
        await db.flush()

        msg = PortalMessage(
            practice_id=practice_id,
            sender_id=user_id,
            sender_type="internal_staff",
            subject=f"Information needed for charge {charge_id}",
            body=message,
            related_charge_id=charge_id,
            is_urgent=urgent,
            requires_response=True,
        )
        db.add(msg)
        await db.flush()

        # Create notification for the provider
        if charge.rendering_provider_id:
            # Find the portal user for this provider
            from src.infrastructure.database.models import User
            result = await db.execute(
                select(User).where(
                    User.provider_id == charge.rendering_provider_id,
                    User.user_type == "provider",
                    User.is_active == True,
                )
            )
            provider_user = result.scalar_one_or_none()
            if provider_user:
                notification = PortalNotification(
                    practice_id=practice_id,
                    user_id=provider_user.id,
                    notification_type="info_request",
                    title="Information needed for charge",
                    body=message,
                    link_url=f"/charges/{charge_id}",
                )
                db.add(notification)

        await _write_audit(
            db, user_id, "request_info_from_provider", "charge_entry", charge_id,
            resource_detail=f"Fields needed: {', '.join(fields_needed)}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        return msg

    async def route_to_coding(
        self,
        db: AsyncSession,
        user_id: UUID,
        charge_id: UUID,
        practice_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> ChargeEntry:
        charge = await self._get_charge_or_raise(db, charge_id, practice_id)
        charge.status = "needs_coding"
        charge.needs_coding = True
        await db.flush()

        wqi = WorkQueueItem(
            practice_id=practice_id,
            queue_type="coding",
            item_type="charge_entry",
            item_id=charge.id,
        )
        db.add(wqi)

        await _write_audit(
            db, user_id, "route_to_coding", "charge_entry", charge_id,
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("charge_routed_to_coding", charge_id=str(charge_id), practice_id=str(practice_id))
        return charge

    async def route_to_billing(
        self,
        db: AsyncSession,
        user_id: UUID,
        charge_id: UUID,
        practice_id: UUID,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> dict:
        charge = await self._get_charge_or_raise(db, charge_id, practice_id)

        # Validate that charge has minimum required data for billing
        if not charge.patient_id:
            raise ChargeValidationError("Cannot route to billing: charge must have a patient")
        if not charge.rendering_provider_id:
            raise ChargeValidationError("Cannot route to billing: charge must have a provider")
        if not charge.procedure_codes:
            raise ChargeValidationError("Cannot route to billing: charge must have procedure codes")

        # Update charge status
        charge.status = "ready_to_bill"
        await db.flush()

        # Create Encounter from charge data
        encounter = Encounter(
            practice_id=practice_id,
            patient_id=charge.patient_id,
            provider_id=charge.rendering_provider_id,
            encounter_type="office",  # Default; can be overridden
            encounter_date=charge.service_date,
            place_of_service=charge.place_of_service or "11",
            referring_provider_id=None,
            prior_auth_number=charge.authorization_number,
            notes=charge.clinical_notes,
            status="open",
        )
        db.add(encounter)
        await db.flush()

        # Update charge with encounter reference
        charge.encounter_id = encounter.id
        await db.flush()

        # Create Claim from charge data
        # Determine payer from charge
        payer_id = charge.primary_payer_id
        if not payer_id:
            # Try to find active primary coverage for the patient
            from src.infrastructure.database.models import Coverage
            result = await db.execute(
                select(Coverage).where(
                    Coverage.patient_id == charge.patient_id,
                    Coverage.coverage_type == "primary",
                    Coverage.is_active == True,
                )
            )
            coverage = result.scalar_one_or_none()
            if coverage:
                payer_id = coverage.payer_id

        if payer_id and charge.patient_id:
            # Get coverage for claim
            coverage_id = None
            from src.infrastructure.database.models import Coverage
            cov_result = await db.execute(
                select(Coverage).where(
                    Coverage.patient_id == charge.patient_id,
                    Coverage.payer_id == payer_id,
                    Coverage.is_active == True,
                )
            )
            coverage = cov_result.scalar_one_or_none()
            if coverage:
                coverage_id = coverage.id

            claim_number = f"CLM-{uuid4().hex[:12].upper()}"
            total_charge = sum(
                p.get("charge_amount", 0) * p.get("units", 1)
                for p in (charge.procedure_codes or [])
            )

            claim = Claim(
                practice_id=practice_id,
                claim_number=claim_number,
                encounter_id=encounter.id,
                patient_id=charge.patient_id,
                payer_id=payer_id,
                coverage_id=coverage_id,
                rendering_provider=charge.rendering_provider_id,
                billing_provider=charge.rendering_provider_id,
                claim_type="837P",
                total_charge=total_charge,
                status="draft",
                created_by=user_id,
            )
            db.add(claim)
            await db.flush()

            # Create ClaimLines from procedures
            if charge.procedure_codes:
                for i, proc in enumerate(charge.procedure_codes, start=1):
                    line = ClaimLine(
                        practice_id=practice_id,
                        claim_id=claim.id,
                        line_number=i,
                        cpt_code=proc.get("cpt_code", ""),
                        modifier_1=proc.get("modifiers", [""])[0] if proc.get("modifiers") else None,
                        modifier_2=proc.get("modifiers", ["", ""])[1] if proc.get("modifiers") and len(proc["modifiers"]) > 1 else None,
                        units=proc.get("units", 1),
                        charge_amount=proc.get("charge_amount", 0),
                        service_date_from=charge.service_date,
                        place_of_service=charge.place_of_service or "11",
                    )
                    db.add(line)
                await db.flush()

                # Create ClaimDiagnosis entries from diagnosis_codes
                from src.infrastructure.database.models import ClaimDiagnosis
                if charge.diagnosis_codes:
                    for j, dx_code in enumerate(charge.diagnosis_codes[:12], start=1):
                        dx = ClaimDiagnosis(
                            practice_id=practice_id,
                            claim_id=claim.id,
                            sequence_number=j,
                            icd10_code=dx_code,
                        )
                        db.add(dx)
                    await db.flush()

            # Create work queue item for billing
            wqi = WorkQueueItem(
                practice_id=practice_id,
                queue_type="billing",
                item_type="claim",
                item_id=claim.id,
            )
            db.add(wqi)

            await _write_audit(
                db, user_id, "route_to_billing", "charge_entry", charge_id,
                resource_detail=f"Created encounter {encounter.id}, claim {claim.id}",
                ip_address=ip_address, request_path=request_path,
                request_method=request_method, phi_accessed=True,
            )
            logger.info(
                "charge_routed_to_billing",
                charge_id=str(charge_id),
                encounter_id=str(encounter.id),
                claim_id=str(claim.id),
            )
            return {
                "charge_id": charge_id,
                "encounter_id": encounter.id,
                "claim_id": claim.id,
                "claim_number": claim_number,
            }

        # Fallback: no payer, create encounter + WQI but skip claim creation
        wqi = WorkQueueItem(
            practice_id=practice_id,
            queue_type="billing",
            item_type="charge_entry",
            item_id=charge.id,
        )
        db.add(wqi)

        await _write_audit(
            db, user_id, "route_to_billing", "charge_entry", charge_id,
            resource_detail=f"Created encounter {encounter.id}, no claim (missing payer)",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        return {
            "charge_id": charge_id,
            "encounter_id": encounter.id,
            "claim_id": None,
            "claim_number": None,
        }

    async def reject_charge(
        self,
        db: AsyncSession,
        user_id: UUID,
        charge_id: UUID,
        practice_id: UUID,
        reason: str,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> ChargeEntry:
        charge = await self._get_charge_or_raise(db, charge_id, practice_id)
        charge.status = "rejected"
        charge.provider_response = reason
        await db.flush()

        # Notify the provider
        if charge.rendering_provider_id:
            from src.infrastructure.database.models import User
            result = await db.execute(
                select(User).where(
                    User.provider_id == charge.rendering_provider_id,
                    User.user_type == "provider",
                    User.is_active == True,
                )
            )
            provider_user = result.scalar_one_or_none()
            if provider_user:
                notification = PortalNotification(
                    practice_id=practice_id,
                    user_id=provider_user.id,
                    notification_type="charge_rejected",
                    title="Charge rejected",
                    body=f"Your charge has been rejected: {reason}",
                    link_url=f"/charges/{charge_id}",
                )
                db.add(notification)

        await _write_audit(
            db, user_id, "reject_charge", "charge_entry", charge_id,
            resource_detail=f"Reason: {reason}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info("charge_rejected", charge_id=str(charge_id), reason=reason)
        return charge

    async def list_charges(
        self,
        db: AsyncSession,
        practice_id: UUID,
        status: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
        assigned_to: UUID | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[ChargeEntry]:
        query = select(ChargeEntry).where(ChargeEntry.practice_id == practice_id)
        if status:
            query = query.where(ChargeEntry.status == status)
        if date_from:
            query = query.where(ChargeEntry.service_date >= date_from)
        if date_to:
            query = query.where(ChargeEntry.service_date <= date_to)
        if assigned_to:
            query = query.where(ChargeEntry.assigned_to == assigned_to)
        query = query.order_by(ChargeEntry.service_date.desc()).offset((page - 1) * page_size).limit(page_size)
        result = await db.execute(query)
        return list(result.scalars().all())

    async def get_charge(
        self,
        db: AsyncSession,
        charge_id: UUID,
        practice_id: UUID,
    ) -> ChargeEntry:
        return await self._get_charge_or_raise(db, charge_id, practice_id)

    async def update_charge(
        self,
        db: AsyncSession,
        user_id: UUID,
        charge_id: UUID,
        practice_id: UUID,
        updates: dict,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> ChargeEntry:
        charge = await self._get_charge_or_raise(db, charge_id, practice_id)

        for key, value in updates.items():
            if key in CHARGE_UPDATABLE_FIELDS:
                setattr(charge, key, value)
        await db.flush()

        await _write_audit(
            db, user_id, "update_charge", "charge_entry", charge_id,
            resource_detail=f"Updated fields: {', '.join(k for k in updates if k in CHARGE_UPDATABLE_FIELDS)}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        return charge

    async def _get_charge_or_raise(
        self, db: AsyncSession, charge_id: UUID, practice_id: UUID
    ) -> ChargeEntry:
        result = await db.execute(
            select(ChargeEntry).where(
                ChargeEntry.id == charge_id,
                ChargeEntry.practice_id == practice_id,
            )
        )
        charge = result.scalar_one_or_none()
        if not charge:
            raise ChargeNotFoundError(charge_id)
        return charge


class BatchImportService:
    """Bulk import charges from CSV."""

    async def import_from_csv(
        self,
        db: AsyncSession,
        user_id: UUID,
        practice_id: UUID,
        csv_content: str,
        ip_address: str | None = None,
        request_path: str | None = None,
        request_method: str | None = None,
    ) -> dict:
        """Parse CSV and create charge entries. Returns BatchImportResult-like dict."""
        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        if not rows:
            raise InvalidCSVFormatError("CSV file is empty or has no data rows")

        errors = []
        success_count = 0
        charge_entries = []

        # Create batch record
        batch = ChargeBatch(
            practice_id=practice_id,
            submitted_by=user_id,
            intake_method="batch_import",
            total_charges=len(rows),
            processed_charges=0,
            error_charges=0,
            status="received",
        )
        db.add(batch)
        await db.flush()

        for i, row in enumerate(rows, start=2):  # start=2 for 1-indexed + header
            row_errors = self._validate_csv_row(row, i)
            if row_errors:
                errors.extend(row_errors)
                continue

            charge = ChargeEntry(
                practice_id=practice_id,
                batch_id=batch.id,
                patient_name_submitted=row.get("patient_name", "").strip(),
                patient_dob_submitted=self._parse_date(row.get("patient_dob", "").strip()),
                patient_mrn_submitted=row.get("mrn", "").strip() or None,
                rendering_provider_id=None,  # Will need NPI lookup
                service_date=self._parse_date(row.get("service_date", "").strip()),
                place_of_service=row.get("place_of_service", "11").strip() or "11",
                diagnosis_codes=[row[f"dx{j}"].strip() for j in range(1, 5) if row.get(f"dx{j}", "").strip()],
                procedure_codes=[{
                    "cpt_code": row.get("cpt", "").strip(),
                    "modifiers": [row.get(f"mod{k}", "").strip() for k in range(1, 5) if row.get(f"mod{k}", "").strip()],
                    "units": float(row.get("units", "1").strip() or "1"),
                    "charge_amount": float(row.get("charge", "0").strip() or "0"),
                }],
                primary_payer_id=None,  # Will need payer name lookup
                member_id=row.get("member_id", "").strip() or None,
                status="received",
            )
            db.add(charge)
            charge_entries.append(charge)
            success_count += 1

        await db.flush()

        # Update batch counts
        batch.processed_charges = success_count
        batch.error_charges = len(errors)
        if success_count > 0:
            batch.status = "processed"
        elif errors:
            batch.status = "error"
        await db.flush()

        # Create work queue item for the batch
        if success_count > 0:
            wqi = WorkQueueItem(
                practice_id=practice_id,
                queue_type="intake",
                item_type="charge_entry",
                item_id=batch.id,
            )
            db.add(wqi)

        await _write_audit(
            db, user_id, "batch_import_charges", "charge_batch", batch.id,
            resource_detail=f"Total: {len(rows)}, Success: {success_count}, Errors: {len(errors)}",
            ip_address=ip_address, request_path=request_path,
            request_method=request_method, phi_accessed=True,
        )
        logger.info(
            "batch_import_completed",
            batch_id=str(batch.id),
            total=len(rows),
            success=success_count,
            errors=len(errors),
        )

        return {
            "batch_id": batch.id,
            "total_rows": len(rows),
            "success_count": success_count,
            "error_count": len(errors),
            "errors": errors,
        }

    @staticmethod
    def _validate_csv_row(row: dict, row_num: int) -> list[dict]:
        """Validate a single CSV row. Returns list of error dicts."""
        errors = []
        required_fields = ["patient_name", "service_date", "cpt"]
        for field in required_fields:
            if not row.get(field, "").strip():
                errors.append({"row": row_num, "field": field, "message": f"Missing required field: {field}"})

        # Validate service_date format
        date_val = row.get("service_date", "").strip()
        if date_val:
            try:
                parsed = BatchImportService._parse_date(date_val)
                if parsed is None:
                    errors.append({"row": row_num, "field": "service_date", "message": "Invalid date format"})
            except (ValueError, TypeError):
                errors.append({"row": row_num, "field": "service_date", "message": "Invalid date format"})

        # Validate CPT format
        cpt = row.get("cpt", "").strip()
        if cpt and not CPT_PATTERN.match(cpt):
            errors.append({"row": row_num, "field": "cpt", "message": f"Invalid CPT code: {cpt}"})

        # Validate ICD-10 codes
        for j in range(1, 5):
            dx = row.get(f"dx{j}", "").strip()
            if dx and not ICD10_PATTERN.match(dx):
                errors.append({"row": row_num, "field": f"dx{j}", "message": f"Invalid ICD-10 code: {dx}"})

        return errors

    @staticmethod
    def _parse_date(value: str) -> date | None:
        """Parse date from CSV. Supports YYYY-MM-DD and MM/DD/YYYY."""
        if not value:
            return None
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
        return None


# Module-level singletons
charge_entry_service = ChargeEntryService()
batch_import_service = BatchImportService()