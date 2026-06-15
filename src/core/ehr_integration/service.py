"""EHR/EMR/PMS integration service — FHIR R4, SFTP, CSV, Webhooks, CDS Hooks."""
from __future__ import annotations
import uuid
import csv
import io
import json
from datetime import date, datetime
from typing import Any
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = structlog.get_logger()


# ── CSV / Excel Import ────────────────────────────────────────────────────────

async def import_patients_from_csv(
    db: AsyncSession,
    practice_id: uuid.UUID,
    csv_content: bytes,
    imported_by_id: uuid.UUID,
) -> dict:
    """Parse CSV and upsert patient records. Returns summary dict."""
    from src.infrastructure.database.models import Patient

    reader = csv.DictReader(io.StringIO(csv_content.decode("utf-8-sig")))
    created = updated = skipped = errored = 0
    errors = []

    for row_num, row in enumerate(reader, start=2):
        try:
            # Normalize field names (handle various header formats)
            first = (
                row.get("first_name") or row.get("First Name") or row.get("FirstName") or ""
            )
            last = (
                row.get("last_name") or row.get("Last Name") or row.get("LastName") or ""
            )
            dob_str = (
                row.get("dob") or row.get("date_of_birth") or row.get("DOB") or ""
            )
            mrn = (
                row.get("mrn") or row.get("MRN") or row.get("medical_record_number") or None
            )
            email = row.get("email") or row.get("Email") or None
            phone = row.get("phone") or row.get("Phone") or None
            gender = (row.get("gender") or row.get("Gender") or "").lower()[:1]

            if not first or not last:
                skipped += 1
                continue

            dob = None
            if dob_str:
                for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%d/%m/%Y"):
                    try:
                        dob = datetime.strptime(dob_str.strip(), fmt).date()
                        break
                    except ValueError:
                        continue

            # Check for existing patient by MRN or name+DOB
            existing = None
            if mrn:
                result = await db.execute(
                    select(Patient).where(
                        Patient.practice_id == practice_id, Patient.mrn == mrn
                    )
                )
                existing = result.scalar_one_or_none()

            if not existing and dob:
                result = await db.execute(
                    select(Patient).where(
                        Patient.practice_id == practice_id,
                        Patient.first_name == first,
                        Patient.last_name == last,
                        Patient.date_of_birth == dob,
                    )
                )
                existing = result.scalar_one_or_none()

            if existing:
                # Update fields if changed
                changed = False
                if email and not existing.email:
                    existing.email = email
                    changed = True
                if phone and not getattr(existing, "phone", None):
                    existing.phone = phone
                    changed = True
                if changed:
                    updated += 1
                else:
                    skipped += 1
            else:
                patient = Patient(
                    practice_id=practice_id,
                    first_name=first,
                    last_name=last,
                    date_of_birth=dob,
                    mrn=mrn,
                    email=email,
                    gender=gender or None,
                )
                db.add(patient)
                created += 1

        except Exception as exc:
            errored += 1
            errors.append({"row": row_num, "error": str(exc)})
            logger.warning("csv_patient_import_row_error", row=row_num, error=str(exc))

    await db.flush()
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errored": errored,
        "errors": errors[:20],
    }


async def import_encounters_from_csv(
    db: AsyncSession,
    practice_id: uuid.UUID,
    csv_content: bytes,
    imported_by_id: uuid.UUID,
) -> dict:
    """Parse encounter/charge CSV and create ChargeBatch + ChargeEntry records."""
    from src.infrastructure.database.models import ChargeBatch, ChargeEntry, Patient

    reader = csv.DictReader(io.StringIO(csv_content.decode("utf-8-sig")))
    created = skipped = errored = 0
    errors = []

    # Group rows by patient MRN + date of service
    batches: dict[str, list[dict]] = {}
    for row in reader:
        patient_mrn = row.get("mrn") or row.get("MRN") or ""
        dos_str = (
            row.get("date_of_service") or row.get("DOS") or row.get("Date of Service") or ""
        )
        key = f"{patient_mrn}_{dos_str}"
        if key not in batches:
            batches[key] = []
        batches[key].append(row)

    for key, rows in batches.items():
        try:
            first_row = rows[0]
            mrn = first_row.get("mrn") or first_row.get("MRN") or ""
            dos_str = first_row.get("date_of_service") or first_row.get("DOS") or ""

            # Look up patient
            result = await db.execute(
                select(Patient).where(
                    Patient.practice_id == practice_id, Patient.mrn == mrn
                )
            )
            patient = result.scalar_one_or_none()
            if not patient:
                skipped += 1
                continue

            dos = None
            for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
                try:
                    dos = datetime.strptime(dos_str.strip(), fmt).date()
                    break
                except ValueError:
                    continue

            batch = ChargeBatch(
                practice_id=practice_id,
                patient_id=patient.id,
                batch_date=dos or date.today(),
                status="pending",
                source="csv_import",
            )
            db.add(batch)
            await db.flush()

            for row in rows:
                cpt = (
                    row.get("cpt") or row.get("CPT") or row.get("procedure_code") or ""
                )
                dx = (
                    row.get("dx") or row.get("icd10") or row.get("diagnosis") or ""
                )
                units_str = row.get("units") or row.get("Units") or "1"
                fee_str = (
                    row.get("fee") or row.get("charge") or row.get("billed_amount") or "0"
                )

                entry = ChargeEntry(
                    charge_batch_id=batch.id,
                    procedure_code=cpt.strip(),
                    diagnosis_codes=[d.strip() for d in dx.split(",") if d.strip()],
                    units=int(units_str) if units_str.isdigit() else 1,
                    fee=float(fee_str.replace("$", "").replace(",", "") or 0),
                )
                db.add(entry)
            created += 1

        except Exception as exc:
            errored += 1
            errors.append({"batch": key, "error": str(exc)})
            logger.warning("csv_encounter_import_batch_error", batch=key, error=str(exc))

    await db.flush()
    return {
        "batches_created": created,
        "skipped": skipped,
        "errored": errored,
        "errors": errors[:20],
    }


# ── FHIR R4 ──────────────────────────────────────────────────────────────────

async def sync_fhir_patients(
    db: AsyncSession,
    ehr_connection_id: uuid.UUID,
    practice_id: uuid.UUID,
) -> dict:
    """Pull Patient and Coverage resources from FHIR R4 endpoint."""
    from src.infrastructure.database.models import EHRConnection, EHRSyncLog
    import httpx

    result = await db.execute(
        select(EHRConnection).where(EHRConnection.id == ehr_connection_id)
    )
    conn = result.scalar_one_or_none()
    if not conn or not conn.is_active:
        return {"error": "EHR connection not found or inactive"}

    sync_log = EHRSyncLog(
        ehr_connection_id=ehr_connection_id,
        practice_id=practice_id,
        sync_type="patients",
        trigger="manual",
        status="running",
    )
    db.add(sync_log)
    await db.flush()

    try:
        token = await _get_fhir_token(conn)
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/fhir+json"}

        async with httpx.AsyncClient(timeout=30) as client:
            url = f"{conn.base_url.rstrip('/')}/Patient?_count=100"
            fetched = created = updated = 0

            while url:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                bundle = response.json()

                for entry in bundle.get("entry", []):
                    resource = entry.get("resource", {})
                    if resource.get("resourceType") != "Patient":
                        continue
                    fetched += 1

                    try:
                        c, u = await _upsert_fhir_patient(
                            db, practice_id, resource, ehr_connection_id
                        )
                        created += c
                        updated += u
                    except Exception as exc:
                        sync_log.records_errored = (sync_log.records_errored or 0) + 1
                        logger.warning("fhir_patient_upsert_error", error=str(exc))

                # Follow next link for pagination
                url = None
                for link in bundle.get("link", []):
                    if link.get("relation") == "next":
                        url = link.get("url")

        sync_log.status = "success"
        sync_log.records_fetched = fetched
        sync_log.records_created = created
        sync_log.records_updated = updated
        sync_log.completed_at = datetime.utcnow()
        conn.last_sync_at = datetime.utcnow()
        conn.last_sync_status = "success"
        conn.last_sync_count = fetched
        await db.flush()
        return {"fetched": fetched, "created": created, "updated": updated}

    except Exception as exc:
        sync_log.status = "failed"
        sync_log.error_details = {"error": str(exc)}
        sync_log.completed_at = datetime.utcnow()
        conn.last_sync_status = "failed"
        await db.flush()
        logger.error("fhir_sync_failed", error=str(exc))
        return {"error": str(exc)}


async def _get_fhir_token(conn) -> str:
    """Obtain OAuth2 access token for FHIR endpoint."""
    import httpx
    from datetime import timezone

    # Check if current token is still valid (with 60s buffer)
    if conn.access_token_enc and conn.token_expires_at:
        now = datetime.now(timezone.utc)
        if conn.token_expires_at.replace(tzinfo=timezone.utc) > now:
            return conn.access_token_enc

    # Request new token via client_credentials grant
    async with httpx.AsyncClient(timeout=15) as client:
        token_url = f"{conn.base_url.rstrip('/')}/oauth/token"
        resp = await client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": conn.client_id,
                "client_secret": conn.client_secret_enc,
                "scope": "system/Patient.read system/Coverage.read",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["access_token"]


async def _upsert_fhir_patient(
    db: AsyncSession,
    practice_id: uuid.UUID,
    resource: dict,
    ehr_connection_id: uuid.UUID,
) -> tuple[int, int]:
    """Create or update a patient from a FHIR Patient resource."""
    from src.infrastructure.database.models import Patient

    names = resource.get("name", [])
    official = next(
        (n for n in names if n.get("use") == "official"), names[0] if names else {}
    )
    family = official.get("family", "")
    given = official.get("given", [""])
    first = given[0] if given else ""

    dob_str = resource.get("birthDate", "")
    dob = None
    if dob_str:
        try:
            dob = date.fromisoformat(dob_str)
        except ValueError:
            pass

    gender_map = {"male": "m", "female": "f", "other": "o", "unknown": None}
    gender = gender_map.get(resource.get("gender", "").lower())

    # Check by name+DOB
    result = await db.execute(
        select(Patient).where(
            Patient.practice_id == practice_id,
            Patient.first_name == first,
            Patient.last_name == family,
        )
    )
    existing = result.scalar_one_or_none()

    if existing:
        if dob and not existing.date_of_birth:
            existing.date_of_birth = dob
        if gender and not existing.gender:
            existing.gender = gender
        return 0, 1

    patient = Patient(
        practice_id=practice_id,
        first_name=first,
        last_name=family,
        date_of_birth=dob,
        gender=gender,
    )
    db.add(patient)
    await db.flush()
    return 1, 0


# ── Webhook Processor ─────────────────────────────────────────────────────────

async def process_webhook_patient(
    db: AsyncSession,
    practice_id: uuid.UUID,
    payload: dict,
) -> dict:
    """Process inbound patient webhook — create or update patient record."""
    from src.infrastructure.database.models import Patient

    first = (
        payload.get("first_name")
        or payload.get("firstName")
        or payload.get("given_name")
        or ""
    )
    last = (
        payload.get("last_name")
        or payload.get("lastName")
        or payload.get("family_name")
        or ""
    )
    dob_str = (
        payload.get("date_of_birth")
        or payload.get("dob")
        or payload.get("birthDate")
        or ""
    )
    mrn = (
        payload.get("mrn")
        or payload.get("patient_id")
        or payload.get("external_id")
        or None
    )
    email = payload.get("email") or None
    phone = payload.get("phone") or payload.get("mobile") or None
    gender = (payload.get("gender") or "").lower()[:1]

    if not first or not last:
        return {"status": "skipped", "reason": "missing name"}

    dob = None
    if dob_str:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                dob = datetime.strptime(dob_str.strip(), fmt).date()
                break
            except ValueError:
                continue

    # Upsert by MRN if provided
    existing = None
    if mrn:
        result = await db.execute(
            select(Patient).where(Patient.practice_id == practice_id, Patient.mrn == mrn)
        )
        existing = result.scalar_one_or_none()

    if existing:
        if email and not existing.email:
            existing.email = email
        return {"status": "updated", "patient_id": str(existing.id)}

    patient = Patient(
        practice_id=practice_id,
        first_name=first,
        last_name=last,
        date_of_birth=dob,
        mrn=mrn,
        email=email,
        gender=gender or None,
    )
    db.add(patient)
    await db.flush()
    return {"status": "created", "patient_id": str(patient.id)}


async def process_webhook_encounter(
    db: AsyncSession,
    practice_id: uuid.UUID,
    payload: dict,
) -> dict:
    """Process inbound encounter webhook — create ChargeBatch for billing."""
    from src.infrastructure.database.models import ChargeBatch, ChargeEntry, Patient

    mrn = payload.get("mrn") or payload.get("patient_id") or ""
    dos_str = payload.get("date_of_service") or payload.get("encounter_date") or ""
    procedures = payload.get("procedures") or payload.get("charges") or []
    diagnoses = payload.get("diagnoses") or payload.get("diagnosis_codes") or []

    # Find patient
    result = await db.execute(
        select(Patient).where(Patient.practice_id == practice_id, Patient.mrn == mrn)
    )
    patient = result.scalar_one_or_none()
    if not patient:
        return {"status": "error", "reason": f"Patient MRN {mrn} not found"}

    dos = date.today()
    if dos_str:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                dos = datetime.strptime(dos_str.strip(), fmt).date()
                break
            except ValueError:
                continue

    batch = ChargeBatch(
        practice_id=practice_id,
        patient_id=patient.id,
        batch_date=dos,
        status="pending",
        source="webhook",
    )
    db.add(batch)
    await db.flush()

    for proc in procedures:
        cpt = (
            proc.get("code")
            or proc.get("cpt")
            or proc.get("procedure_code")
            or ""
        )
        entry = ChargeEntry(
            charge_batch_id=batch.id,
            procedure_code=cpt,
            diagnosis_codes=[str(d) for d in (proc.get("diagnosis_codes") or diagnoses)],
            units=int(proc.get("units") or 1),
            fee=float(proc.get("fee") or proc.get("charge") or 0),
        )
        db.add(entry)

    await db.flush()
    return {"status": "created", "charge_batch_id": str(batch.id)}


# ── CDS Hooks ─────────────────────────────────────────────────────────────────

async def handle_cds_hook_order_sign(
    db: AsyncSession,
    hook_request: dict,
) -> dict:
    """
    CDS Hooks service — fires on 'order-sign' or 'encounter-discharge' event.
    Returns coding suggestions as CDS Cards for display inside the EHR.
    """
    from src.core.nlp.ai_service import get_coding_suggestion

    context = hook_request.get("context", {})
    prefetch = hook_request.get("prefetch", {})

    # Extract clinical note from context
    note_text = context.get("note_text") or context.get("clinicalNote") or ""

    if not note_text:
        return {"cards": []}

    try:
        suggestion = await get_coding_suggestion(note_text, context={})
        suggested_cpt = suggestion.get("cpt_codes", [])
        suggested_dx = suggestion.get("icd10_codes", [])
        rationale = suggestion.get("rationale", "")

        cards = []
        if suggested_cpt or suggested_dx:
            summary_parts = []
            if suggested_dx:
                summary_parts.append(f"ICD-10: {', '.join(suggested_dx[:5])}")
            if suggested_cpt:
                summary_parts.append(f"CPT: {', '.join(suggested_cpt[:5])}")

            cards.append({
                "summary": "Aethera AI Coding Suggestion",
                "detail": (
                    f"**Suggested codes:**\n{chr(10).join(summary_parts)}\n\n"
                    f"**Rationale:** {rationale}"
                ),
                "indicator": "info",
                "source": {
                    "label": "Aethera Healthcare AI",
                    "url": "https://rcm.aetherahealthcare.com",
                },
                "suggestions": [
                    {
                        "label": "Apply suggested codes",
                        "actions": [
                            {
                                "type": "update",
                                "description": f"Apply ICD-10: {', '.join(suggested_dx)}",
                            },
                        ],
                    }
                ],
            })

        return {"cards": cards}

    except Exception as exc:
        logger.error("cds_hook_failed", error=str(exc))
        return {"cards": []}
