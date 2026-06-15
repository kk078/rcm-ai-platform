#!/usr/bin/env python3
"""
DISPOSABLE end-to-end RCM lifecycle simulation (authorized one-off).

Creates ZZZSIM-tagged throwaway rows under the 'Aethera Health' practice, drives
one synthetic patient encounter through the REAL AI-agent pipeline stage by
stage, records a step-by-step trace, and DELETES everything in a finally block.

Run detached:
  podman exec -d -e PYTHONPATH=/app rcm-ai-platform-api-1 \
    sh -c 'python scripts/simulate_rcm.py > /tmp/rcm_sim.out 2>&1; touch /tmp/rcm_sim.done'
"""
import asyncio, json, traceback
from datetime import datetime, timezone, date

from sqlalchemy import select
from src.infrastructure.database.session import async_session
from src.infrastructure.database.models import Practice, Patient, ChargeEntry, WorkQueueItem
from src.core.ai_dispatch.dispatcher import dispatch_item
from src.core.ai_dispatch.tasks import _process_item, _build_item_data

TAG = "ZZZSIM"
NOTE = ("Established patient, 54M, seen for follow-up of type 2 diabetes mellitus "
        "without complications and essential hypertension. BP 138/86. A1c reviewed "
        "at 7.2%. Metformin and lisinopril refilled. Counseled on diet/exercise. "
        "25 minutes, low complexity MDM.")

trace = []
def step(title, **data):
    trace.append({"step": len(trace) + 1, "title": title, **data})
    print(f"\n========== STEP {len(trace)}: {title} ==========")
    print(json.dumps(data, indent=2, default=str)[:2600])


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def main():
    created = {"wqi": None, "charge": None, "patient": None}
    try:
        # ── Setup: disposable rows under Aethera Health ──────────────────────
        async with async_session() as db:
            practice = (await db.execute(
                select(Practice).where(Practice.practice_name == "Aethera Health")
            )).scalar_one()
            now = _now()

            patient = Patient(
                practice_id=practice.id, mrn=f"{TAG}-0001",
                first_name="SIMTEST", last_name="PATIENT",
                date_of_birth=date(1971, 3, 2), is_active=True,
                created_at=now, updated_at=now,
            )
            db.add(patient); await db.flush()

            charge = ChargeEntry(
                practice_id=practice.id, patient_id=patient.id,
                service_date=date(2026, 6, 10), needs_coding=True,
                status="pending_coding", provider_notified=False,
                clinical_notes=NOTE, created_at=now, updated_at=now,
            )
            db.add(charge); await db.flush()

            wqi = WorkQueueItem(
                practice_id=practice.id, queue_type="coding",
                item_type="charge_entry", item_id=charge.id,
                priority=5, status="pending", sla_breached=False,
                created_at=now, updated_at=now,
            )
            db.add(wqi); await db.commit()
            created.update(wqi=str(wqi.id), charge=str(charge.id), patient=str(patient.id))
            wqi_id, charge_id, practice_id = str(wqi.id), str(charge.id), str(practice.id)

        step("Setup — disposable encounter created",
             practice="Aethera Health", patient_mrn=f"{TAG}-0001",
             charge_entry=charge_id, work_queue_item=wqi_id,
             clinical_note=NOTE)

        # ── STAGE 1: Coding via the REAL work-item pipeline (DB write-back) ───
        # _process_item: marks in_progress -> enriches -> calls agent -> writes
        # status (completed/escalated) + notes back onto the WorkQueueItem.
        result1 = await _process_item(None, wqi_id)
        async with async_session() as db:
            wqi_after = (await db.execute(
                select(WorkQueueItem).where(WorkQueueItem.id == wqi_id)
            )).scalar_one()
            wqi_notes = wqi_after.notes
            wqi_status = wqi_after.status
        step("Coding agent — autonomous work-item pipeline",
             work_item_status_transition=f"pending -> {wqi_status}",
             dispatch_summary=result1,
             persisted_notes=json.loads(wqi_notes) if wqi_notes else None)

        # Full coding result (codes) for display via the same dispatcher.
        async with async_session() as db:
            charge_obj = (await db.execute(
                select(ChargeEntry).where(ChargeEntry.id == charge_id)
            )).scalar_one()
            coding_payload = await _fetch_like(charge_obj, practice_id)
        coding = await dispatch_item("coding", coding_payload)
        step("Coding agent — assigned codes",
             success=coding.success, confidence=coding.confidence,
             escalate=coding.escalate, result=coding.result,
             duration_ms=coding.duration_ms)

        # ── STAGE 2: Eligibility verification ────────────────────────────────
        elig = await dispatch_item("eligibility", {
            "patient_dob": "1971-03-02", "member_id": "1EG4TE5MK72",
            "payer_name": "Medicare Part B", "service_date": "2026-06-10",
            "cpt_codes": [{"code": "99213"}],
            "diagnosis_codes": ["E11.9", "I10"],
        })
        step("Eligibility agent — coverage verification",
             success=elig.success, confidence=elig.confidence,
             escalate=elig.escalate, result=elig.result, notes=elig.notes[:600])

        # ── STAGE 3: Billing / claim scrub ───────────────────────────────────
        bill = await dispatch_item("billing", {
            "payer_name": "Medicare Part B", "total_charge": 128.00,
            "claim_lines": [{"cpt_code": "99213", "modifiers": [],
                             "icd_pointers": [1, 2], "charge_amount": 128.00}],
            "diagnoses": [{"icd10_code": "E11.9", "sequence_number": 1, "is_principal": True},
                          {"icd10_code": "I10", "sequence_number": 2, "is_principal": False}],
            "member_id": "1EG4TE5MK72",
        })
        step("Billing agent — claim scrub before submission",
             success=bill.success, confidence=bill.confidence,
             escalate=bill.escalate, result=bill.result, notes=bill.notes[:600])

        # ── STAGE 4: Denial management (synthetic CARC-16 denial) ────────────
        den = await dispatch_item("denial", {
            "reason_code": "16", "remark_codes": ["M76"],
            "denial_amount": 128.00, "category": "missing_information",
            "payer_name": "Medicare Part B",
            "claim_lines": [{"cpt_code": "99213", "charge_amount": 128.00}],
            "diagnoses": [{"icd10_code": "E11.9"}, {"icd10_code": "I10"}],
        })
        step("AR/Denial agent — denial triage & appeal recommendation",
             success=den.success, confidence=den.confidence,
             escalate=den.escalate, result=den.result, notes=den.notes[:800])

        print("\n=== SIM RESULT JSON ===")
        print(json.dumps(trace, default=str))

    except Exception:
        print("SIM ERROR:\n" + traceback.format_exc())
    finally:
        # ── Cleanup: delete every disposable row (FK-safe order) ─────────────
        async with async_session() as db:
            from sqlalchemy import delete as _del
            if created["wqi"]:
                await db.execute(_del(WorkQueueItem).where(WorkQueueItem.id == created["wqi"]))
            if created["charge"]:
                await db.execute(_del(ChargeEntry).where(ChargeEntry.id == created["charge"]))
            if created["patient"]:
                await db.execute(_del(Patient).where(Patient.id == created["patient"]))
            await db.commit()
        # Verify nothing tagged remains.
        async with async_session() as db:
            left = (await db.execute(
                select(Patient).where(Patient.mrn == f"{TAG}-0001")
            )).scalars().all()
        print(f"\n=== CLEANUP: removed wqi/charge/patient; residual ZZZSIM patients = {len(left)} ===")
        print("=== SIM COMPLETE ===")


async def _fetch_like(charge, practice_id):
    """Mirror _fetch_charge_entry_data for display (no DB lock needed)."""
    return {
        "queue_type": "coding", "item_type": "charge_entry",
        "practice_id": practice_id,
        "charge_entry_id": str(charge.id),
        "service_date": str(charge.service_date),
        "clinical_notes": charge.clinical_notes or "",
        "diagnosis_codes": charge.diagnosis_codes or [],
        "procedure_codes": charge.procedure_codes or {},
    }


if __name__ == "__main__":
    asyncio.run(main())
