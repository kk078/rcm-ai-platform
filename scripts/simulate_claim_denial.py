#!/usr/bin/env python3
"""
DEEPER disposable simulation: a real Claim + Denial through the billing and
AR/denial agents via the actual work-item pipeline. All rows ZZZSIM-tagged and
deleted in a finally block. Authorized one-off.

Run detached:
  podman exec -d -e PYTHONPATH=/app rcm-ai-platform-api-1 \
    sh -c 'python scripts/simulate_claim_denial.py > /tmp/cd_sim.out 2>&1; touch /tmp/cd_sim.done'
"""
import asyncio, json, traceback
from datetime import datetime, timezone, date

from sqlalchemy import select, delete as sqldelete
from src.infrastructure.database.session import async_session
from src.infrastructure.database.models import (
    Practice, Provider, Patient, Payer, Coverage, Encounter,
    Claim, ClaimLine, ClaimDiagnosis, Denial, WorkQueueItem,
)
from src.core.ai_dispatch.tasks import _process_item, _build_item_data
from src.core.ai_dispatch.dispatcher import dispatch_item

TAG = "ZZZSIM"
trace = []
def step(title, **data):
    trace.append({"step": len(trace) + 1, "title": title, **data})
    print(f"\n========== STEP {len(trace)}: {title} ==========")
    print(json.dumps(data, indent=2, default=str)[:2800])

def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def main():
    ids = {k: None for k in (
        "wqi_bill", "wqi_den", "denial", "line", "dx1", "dx2",
        "claim", "encounter", "coverage", "patient", "payer")}
    try:
        async with async_session() as db:
            practice = (await db.execute(
                select(Practice).where(Practice.practice_name == "Aethera Health"))).scalar_one()
            provider = (await db.execute(select(Provider).limit(1))).scalar_one()
            now = _now()

            payer = Payer(payer_name="ZZZSIM Medicare Part B", payer_id_number="SIMMCR01",
                          timely_filing_days=365, appeal_filing_days=120,
                          electronic_payer=True, era_enrolled=True, eft_enrolled=True,
                          is_active=True, created_at=now, updated_at=now)
            db.add(payer); await db.flush()

            patient = Patient(practice_id=practice.id, mrn=f"{TAG}-CLAIM1",
                              first_name="SIMTEST", last_name="CLAIMPT",
                              date_of_birth=date(1971, 3, 2), is_active=True,
                              created_at=now, updated_at=now)
            db.add(patient); await db.flush()

            coverage = Coverage(practice_id=practice.id, patient_id=patient.id, payer_id=payer.id,
                                member_id="1EG4TE5MK72", coverage_type="primary",
                                plan_name="Medicare Part B", plan_type="MB",
                                effective_date=date(2026, 1, 1), is_active=True,
                                created_at=now, updated_at=now)
            db.add(coverage); await db.flush()

            enc = Encounter(practice_id=practice.id, patient_id=patient.id, provider_id=provider.id,
                            encounter_type="office_visit", encounter_date=date(2026, 6, 10),
                            place_of_service="11", status="complete",
                            notes="T2DM + HTN follow-up. A1c 7.2%, BP 138/86. Meds refilled.",
                            created_at=now, updated_at=now)
            db.add(enc); await db.flush()

            claim = Claim(practice_id=practice.id, claim_number=f"{TAG}-CLM-0001",
                          encounter_id=enc.id, patient_id=patient.id, payer_id=payer.id,
                          coverage_id=coverage.id, rendering_provider=provider.id,
                          billing_provider=provider.id, claim_type="837P",
                          frequency_code="1", total_charge=128.00, total_paid=0.0,
                          total_adjusted=0.0, patient_responsibility=0.0,
                          status="ready", created_at=now, updated_at=now)
            db.add(claim); await db.flush()

            line = ClaimLine(practice_id=practice.id, claim_id=claim.id, line_number=1,
                             cpt_code="99214", icd_pointer_1="1", icd_pointer_2="2",
                             units=1.0, charge_amount=128.00, paid_amount=0.0,
                             service_date_from=date(2026, 6, 10), status="ready")
            db.add(line)
            dx1 = ClaimDiagnosis(practice_id=practice.id, claim_id=claim.id, sequence_number=1,
                                 icd10_code="E11.9", is_principal=True)
            dx2 = ClaimDiagnosis(practice_id=practice.id, claim_id=claim.id, sequence_number=2,
                                 icd10_code="I10", is_principal=False)
            db.add(dx1); db.add(dx2); await db.flush()

            denial = Denial(practice_id=practice.id, claim_id=claim.id, payer_id=payer.id,
                            denial_date=date(2026, 6, 14), reason_code="16",
                            remark_codes=["M76"], denial_amount=128.00,
                            category="missing_information",
                            root_cause="Diagnosis code missing/invalid on submitted claim",
                            appeal_deadline=date(2026, 10, 12), status="open",
                            created_at=now, updated_at=now)
            db.add(denial); await db.flush()

            wqi_bill = WorkQueueItem(practice_id=practice.id, queue_type="billing",
                                     item_type="claim", item_id=claim.id, priority=5,
                                     status="pending", sla_breached=False,
                                     created_at=now, updated_at=now)
            wqi_den = WorkQueueItem(practice_id=practice.id, queue_type="denial",
                                    item_type="denial", item_id=denial.id, priority=4,
                                    status="pending", sla_breached=False,
                                    created_at=now, updated_at=now)
            db.add(wqi_bill); db.add(wqi_den); await db.commit()

            ids.update(wqi_bill=str(wqi_bill.id), wqi_den=str(wqi_den.id), denial=str(denial.id),
                       line=str(line.id), dx1=str(dx1.id), dx2=str(dx2.id), claim=str(claim.id),
                       encounter=str(enc.id), coverage=str(coverage.id),
                       patient=str(patient.id), payer=str(payer.id))

        step("Setup — disposable claim graph created",
             practice="Aethera Health", claim_number=f"{TAG}-CLM-0001",
             cpt="99214", dx=["E11.9", "I10"], charge=128.00,
             denial_CARC="16 (+RARC M76)", billing_wqi=ids["wqi_bill"], denial_wqi=ids["wqi_den"])

        # ── BILLING: real pipeline ───────────────────────────────────────────
        bill_summary = await _process_item(None, ids["wqi_bill"])
        async with async_session() as db:
            w = (await db.execute(select(WorkQueueItem).where(WorkQueueItem.id == ids["wqi_bill"]))).scalar_one()
            bill_status, bill_notes = w.status, w.notes
            enriched_bill = await _build_item_data(db, w)
        bill_full = await dispatch_item("billing", enriched_bill)
        step("Billing agent — claim scrub (enriched from real Claim)",
             work_item_status=f"pending -> {bill_status}",
             pipeline_summary=bill_summary,
             enriched_payload_keys=sorted(enriched_bill.keys()),
             agent_success=bill_full.success, confidence=bill_full.confidence,
             escalate=bill_full.escalate, result=bill_full.result, notes=bill_full.notes[:700])

        # ── DENIAL: real pipeline ────────────────────────────────────────────
        den_summary = await _process_item(None, ids["wqi_den"])
        async with async_session() as db:
            w = (await db.execute(select(WorkQueueItem).where(WorkQueueItem.id == ids["wqi_den"]))).scalar_one()
            den_status, den_notes = w.status, w.notes
            enriched_den = await _build_item_data(db, w)
        den_full = await dispatch_item("denial", enriched_den)
        step("AR/Denial agent — triage & appeal (enriched from real Denial)",
             work_item_status=f"pending -> {den_status}",
             pipeline_summary=den_summary,
             enriched_payload=enriched_den,
             agent_success=den_full.success, confidence=den_full.confidence,
             escalate=den_full.escalate, result=den_full.result, notes=den_full.notes[:900])

        print("\n=== SIM RESULT JSON ===")
        print(json.dumps(trace, default=str))

    except Exception:
        print("SIM ERROR:\n" + traceback.format_exc())
    finally:
        async with async_session() as db:
            for model, key in ((WorkQueueItem, "wqi_bill"), (WorkQueueItem, "wqi_den"),
                               (Denial, "denial"), (ClaimLine, "line"),
                               (ClaimDiagnosis, "dx1"), (ClaimDiagnosis, "dx2"),
                               (Claim, "claim"), (Encounter, "encounter"),
                               (Coverage, "coverage"), (Patient, "patient"), (Payer, "payer")):
                if ids[key]:
                    await db.execute(sqldelete(model).where(model.id == ids[key]))
            await db.commit()
        async with async_session() as db:
            left_c = (await db.execute(select(Claim).where(Claim.claim_number == f"{TAG}-CLM-0001"))).scalars().all()
            left_p = (await db.execute(select(Payer).where(Payer.payer_id_number == "SIMMCR01"))).scalars().all()
        print(f"\n=== CLEANUP: residual claims={len(left_c)} payers={len(left_p)} ===")
        print("=== SIM COMPLETE ===")


if __name__ == "__main__":
    asyncio.run(main())
