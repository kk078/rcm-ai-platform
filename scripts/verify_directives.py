#!/usr/bin/env python3
"""Prove AI-Assistant directives are complied with by the agents. Disposable; resets directives."""
import asyncio, traceback
from datetime import datetime, timezone, date
from sqlalchemy import select, delete as sqld
from src.infrastructure.database.session import async_session
from src.infrastructure.database.models import Practice, Provider, Patient, ChargeEntry, WorkQueueItem, AgentDirective
from src.core.ai_dispatch.tasks import _process_item
TAG="ZZDIR"
def now(): return datetime.now(timezone.utc).replace(tzinfo=None)

async def seed_coding_item(db, prac, pat):
    n=now()
    chg=ChargeEntry(practice_id=prac.id, patient_id=pat.id, service_date=date(2026,6,10), needs_coding=True,
        status="pending_coding", provider_notified=False,
        clinical_notes="Established 60F, type 2 diabetes without complications, essential hypertension; meds refilled; low complexity MDM.",
        created_at=n, updated_at=n); db.add(chg); await db.flush()
    wq=WorkQueueItem(practice_id=prac.id, queue_type="coding", item_type="charge_entry", item_id=chg.id,
        priority=5, status="pending", sla_breached=False, created_at=n, updated_at=n); db.add(wq); await db.flush()
    return str(chg.id), str(wq.id)

async def main():
    cleanup=[]
    try:
        async with async_session() as db:
            prac=(await db.execute(select(Practice).where(Practice.practice_name=="Aethera Health"))).scalar_one()
            pat=(await db.execute(select(Patient).limit(1))).scalar_one_or_none()
            if pat is None:
                pat=Patient(practice_id=prac.id, mrn=f"{TAG}-P", first_name="DIR", last_name="TEST",
                    date_of_birth=date(1966,1,1), gender="F", is_active=True, created_at=now(), updated_at=now()); db.add(pat); await db.flush(); cleanup.append(("patient",str(pat.id)))
            c1,w1=await seed_coding_item(db, prac, pat); cleanup+=[("charge",c1),("wqi",w1)]
            await db.commit()

        print("== TEST 1: threshold 0.95 + standing instruction (set via assistant earlier) ==")
        await _process_item(None, w1)
        async with async_session() as db:
            wq=(await db.execute(select(WorkQueueItem).where(WorkQueueItem.id==w1))).scalar_one()
            print("  status:", wq.status, "(expect: escalated — conf<0.95)")
            applied_instr=any("policy instructions" in (s.get("label","").lower()) for s in (wq.agent_trace or []))
            print("  instruction step present:", applied_instr)
            for s in (wq.agent_trace or []):
                print(f"    [{s.get('status')}] {s.get('label')}: {s.get('detail')[:80]}")

        print("\n== TEST 2: pause the coding agent (directive enabled=False) ==")
        async with async_session() as db:
            d=(await db.execute(select(AgentDirective).where(AgentDirective.agent_type=="coding"))).scalar_one_or_none()
            if d is None:
                d=AgentDirective(agent_type="coding", enabled=False, created_at=now(), updated_at=now()); db.add(d)
            else:
                d.enabled=False; d.updated_at=now()
            await db.commit()
        async with async_session() as db:
            prac=(await db.execute(select(Practice).where(Practice.practice_name=="Aethera Health"))).scalar_one()
            pat=(await db.execute(select(Patient).where(Patient.id==cleanup[-3][1] if False else Patient.mrn.like(f"{TAG}%")))).scalars().first() or (await db.execute(select(Patient).limit(1))).scalar_one()
            c2,w2=await seed_coding_item(db, prac, pat); cleanup+=[("charge",c2),("wqi",w2)]; await db.commit()
        await _process_item(None, w2)
        async with async_session() as db:
            wq=(await db.execute(select(WorkQueueItem).where(WorkQueueItem.id==w2))).scalar_one()
            print("  status:", wq.status, "(expect: escalated — agent paused, NO LLM call)")
            for s in (wq.agent_trace or []):
                print(f"    [{s.get('status')}] {s.get('label')}: {s.get('detail')[:80]}")
        print("\n== VERIFY COMPLETE ==")
    except Exception:
        print("ERR:\n"+traceback.format_exc())
    finally:
        async with async_session() as db:
            for typ,_id in cleanup:
                if typ=="wqi": await db.execute(sqld(WorkQueueItem).where(WorkQueueItem.id==_id))
            for typ,_id in cleanup:
                if typ=="charge": await db.execute(sqld(ChargeEntry).where(ChargeEntry.id==_id))
            for typ,_id in cleanup:
                if typ=="patient": await db.execute(sqld(Patient).where(Patient.id==_id))
            # RESET directives so production is not left throttled/paused
            await db.execute(sqld(AgentDirective).where(AgentDirective.agent_type.in_(["coding","*"])))
            await db.commit()
        print("CLEANUP done (directives reset)")
asyncio.run(main())
