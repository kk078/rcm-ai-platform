#!/usr/bin/env python3
"""Verify roadmap A/B/E/C live via _process_item. Disposable (ZZENH), self-cleans."""
import asyncio, json, traceback
from datetime import datetime, timezone, date
from collections import defaultdict
from sqlalchemy import select, delete as sqld
from src.infrastructure.database.session import async_session
from src.infrastructure.database.models import (
    Practice, Provider, Patient, Payer, Coverage, Encounter,
    Claim, ClaimLine, ClaimDiagnosis, ChargeEntry, WorkQueueItem, ClaimForm)
from src.core.ai_dispatch.tasks import _process_item
TAG="ZZENH"
def now(): return datetime.now(timezone.utc).replace(tzinfo=None)

async def main():
    ids={}
    try:
        async with async_session() as db:
            n=now()
            prac=(await db.execute(select(Practice).where(Practice.practice_name=="Aethera Health"))).scalar_one()
            prov=(await db.execute(select(Provider).limit(1))).scalar_one()
            pat=Patient(practice_id=prac.id, mrn=f"{TAG}-1", first_name="ENH", last_name="TEST",
                date_of_birth=date(1970,1,1), gender="M", is_active=True, created_at=n, updated_at=n); db.add(pat); await db.flush()
            pay=Payer(payer_name="Medicare", payer_id_number="ZZENHMB", payer_type="Medicare", timely_filing_days=365,
                appeal_filing_days=120, electronic_payer=True, era_enrolled=True, eft_enrolled=True, is_active=True, created_at=n, updated_at=n); db.add(pay); await db.flush()
            cov=Coverage(practice_id=prac.id, patient_id=pat.id, payer_id=pay.id, member_id="1EG4TE5MK72", coverage_type="primary",
                plan_name="Medicare Part B", plan_type="MB", effective_date=date(2026,1,1), is_active=True, created_at=n, updated_at=n); db.add(cov); await db.flush()
            enc=Encounter(practice_id=prac.id, patient_id=pat.id, provider_id=prov.id, encounter_type="office_visit",
                encounter_date=date(2026,6,10), place_of_service="11", status="complete", created_at=n, updated_at=n); db.add(enc); await db.flush()
            # CHARGE ENTRY for coding agent (trace + guardrails)
            chg=ChargeEntry(practice_id=prac.id, patient_id=pat.id, service_date=date(2026,6,10), needs_coding=True,
                status="pending_coding", provider_notified=False,
                clinical_notes="Established 56M, type 2 diabetes without complications and essential hypertension; A1c 7.1, BP 140/88; meds refilled; low complexity MDM, 20 min.",
                created_at=n, updated_at=n); db.add(chg); await db.flush()
            clm=Claim(practice_id=prac.id, claim_number=f"{TAG}-CLM", encounter_id=enc.id, patient_id=pat.id, payer_id=pay.id,
                coverage_id=cov.id, rendering_provider=prov.id, billing_provider=prov.id, claim_type="837P", frequency_code="1",
                total_charge=128.0, total_paid=0.0, total_adjusted=0.0, patient_responsibility=0.0, status="ready", created_at=n, updated_at=n); db.add(clm); await db.flush()
            db.add(ClaimLine(practice_id=prac.id, claim_id=clm.id, line_number=1, cpt_code="99213", icd_pointer_1="1", icd_pointer_2="2",
                units=1.0, charge_amount=128.0, paid_amount=0.0, service_date_from=date(2026,6,10), place_of_service="11", status="ready"))
            for i,(c,p) in enumerate([("E11.9",True),("I10",False)],1):
                db.add(ClaimDiagnosis(practice_id=prac.id, claim_id=clm.id, sequence_number=i, icd10_code=c, is_principal=p))
            wq_code=WorkQueueItem(practice_id=prac.id, queue_type="coding", item_type="charge_entry", item_id=chg.id, priority=5, status="pending", sla_breached=False, created_at=n, updated_at=n)
            wq_bill=WorkQueueItem(practice_id=prac.id, queue_type="billing", item_type="claim", item_id=clm.id, priority=5, status="pending", sla_breached=False, created_at=n, updated_at=n)
            db.add(wq_code); db.add(wq_bill); await db.commit()
            ids=dict(pat=pat.id, pay=pay.id, cov=cov.id, enc=enc.id, chg=chg.id, clm=clm.id, wqc=wq_code.id, wqb=wq_bill.id)

        # A+E: coding through pipeline
        await _process_item(None, str(ids["wqc"]))
        # B: billing through pipeline (auto-builds claim form)
        await _process_item(None, str(ids["wqb"]))

        async with async_session() as db:
            wqc=(await db.execute(select(WorkQueueItem).where(WorkQueueItem.id==ids["wqc"]))).scalar_one()
            wqb=(await db.execute(select(WorkQueueItem).where(WorkQueueItem.id==ids["wqb"]))).scalar_one()
            cf=(await db.execute(select(ClaimForm).where(ClaimForm.claim_id==ids["clm"], ClaimForm.form_type=="cms1500"))).scalar_one_or_none()
            print("=== A. CODING agent_trace (persisted steps) ===")
            print("status:", wqc.status)
            for s in (wqc.agent_trace or []): print(f"  [{s.get('status')}] {s.get('label')}: {s.get('detail')}")
            print("\n=== A. BILLING agent_trace ===")
            print("status:", wqb.status)
            for s in (wqb.agent_trace or []): print(f"  [{s.get('status')}] {s.get('label')}: {s.get('detail')}")
            print("\n=== B. Auto-built ClaimForm (feedback loop) ===")
            if cf: print(f"  form={cf.form_type} status={cf.status} edits={len(cf.edits or [])} enrichment_keys={list((cf.enrichment or {}).keys())}")
            else: print("  (none)")
            # C: mini agent-health aggregation
            rows=(await db.execute(select(WorkQueueItem).where(WorkQueueItem.status.in_(["completed","escalated","failed"])))).scalars().all()
            agg=defaultdict(lambda:{"n":0,"completed":0,"escalated":0})
            for it in rows:
                try: m=json.loads(it.notes) if it.notes else {}
                except Exception: m={}
                a=agg[m.get("agent_type","?")]; a["n"]+=1
                if it.status=="completed": a["completed"]+=1
                elif it.status=="escalated": a["escalated"]+=1
            print("\n=== C. agent-health snapshot (from work items) ===")
            for k,v in agg.items(): print(f"  {k}: processed={v['n']} completed={v['completed']} escalated={v['escalated']}")
        print("\n=== VERIFY COMPLETE ===")
    except Exception:
        print("ERR:\n"+traceback.format_exc())
    finally:
        async with async_session() as db:
            await db.execute(sqld(ClaimForm).where(ClaimForm.claim_id==ids.get("clm")))
            await db.execute(sqld(ClaimLine).where(ClaimLine.claim_id==ids.get("clm")))
            await db.execute(sqld(ClaimDiagnosis).where(ClaimDiagnosis.claim_id==ids.get("clm")))
            for m,k in ((WorkQueueItem,"wqc"),(WorkQueueItem,"wqb"),(Claim,"clm"),(ChargeEntry,"chg"),(Encounter,"enc"),(Coverage,"cov"),(Patient,"pat"),(Payer,"pay")):
                if ids.get(k): await db.execute(sqld(m).where(m.id==ids[k]))
            await db.commit()
        print("CLEANUP done")
asyncio.run(main())
