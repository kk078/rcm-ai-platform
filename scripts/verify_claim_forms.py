#!/usr/bin/env python3
"""Verify CMS-1500 + UB-04 assembly + NPPES enrichment on a GERMAN-note claim. Disposable."""
import asyncio, json, traceback
from datetime import datetime, timezone, date
from sqlalchemy import select, delete as sqld
from src.infrastructure.database.session import async_session
from src.infrastructure.database.models import (
    Practice, Provider, Patient, Payer, Coverage, Encounter, Claim, ClaimLine, ClaimDiagnosis)
from src.core.claim_forms.assembler import assemble_claim_form

TAG="ZZCFRM"
def now(): return datetime.now(timezone.utc).replace(tzinfo=None)

async def main():
    ids={k:None for k in ("dx","line","claim","enc","cov","pat","prov","pay","prac")}
    try:
        async with async_session() as db:
            n=now()
            prac=Practice(practice_name="Gulf Coast Internist LLC", legal_name="Gulf Coast Internist LLC",
                tin="59-1234567", specialty_primary="Internal Medicine", status="active",
                address_line_1="4957 38th Ave N", address_line_2="Suite C", city="Saint Petersburg",
                state="FL", zip_code="33710", phone="727-525-0900",
                timezone="America/New_York", intake_method="portal", created_at=n, updated_at=n)  # no group_npi -> NPPES org lookup
            db.add(prac); await db.flush()
            prov=Provider(npi="1083684153", first_name="KAVITA", last_name="RAO", is_individual=True,
                is_active=True, created_at=n, updated_at=n)  # taxonomy/credential NULL -> NPPES fills
            db.add(prov); await db.flush()
            pat=Patient(practice_id=prac.id, mrn=f"{TAG}-21844", first_name="CYNTHIA", last_name="GERMAN",
                date_of_birth=date(1959,9,15), gender="F", address_line_1="5816 44TH AVE N",
                city="Saint Petersburg", state="FL", zip_code="33709", phone="727-641-6120",
                is_active=True, created_at=n, updated_at=n)
            db.add(pat); await db.flush()
            pay=Payer(payer_name="Medicare", payer_id_number="SMFL0", payer_type="Medicare",
                timely_filing_days=365, appeal_filing_days=120, electronic_payer=True, era_enrolled=True,
                eft_enrolled=True, is_active=True, created_at=n, updated_at=n)
            db.add(pay); await db.flush()
            cov=Coverage(practice_id=prac.id, patient_id=pat.id, payer_id=pay.id, member_id="",
                coverage_type="primary", plan_name="Medicare Part B", plan_type="MB",
                effective_date=date(2021,1,1), is_active=True, created_at=n, updated_at=n)  # blank member_id -> scrub flags 1a
            db.add(cov); await db.flush()
            enc=Encounter(practice_id=prac.id, patient_id=pat.id, provider_id=prov.id,
                encounter_type="office_visit", encounter_date=date(2021,3,24), place_of_service="11",
                status="complete", created_at=n, updated_at=n)
            db.add(enc); await db.flush()
            clm=Claim(practice_id=prac.id, claim_number=f"{TAG}-CLM1", encounter_id=enc.id, patient_id=pat.id,
                payer_id=pay.id, coverage_id=cov.id, rendering_provider=prov.id, billing_provider=prov.id,
                claim_type="837P", frequency_code="1", total_charge=175.0, total_paid=0.0, total_adjusted=0.0,
                patient_responsibility=0.0, status="ready", created_at=n, updated_at=n)
            db.add(clm); await db.flush()
            line=ClaimLine(practice_id=prac.id, claim_id=clm.id, line_number=1, cpt_code="99214",
                icd_pointer_1="1", icd_pointer_2="2", units=1.0, charge_amount=175.0, paid_amount=0.0,
                service_date_from=date(2021,3,24), place_of_service="11", status="ready")
            db.add(line)
            codes=[("G97.1",True),("F33.1",False),("E78.2",False),("I10",False)]
            dxs=[]
            for i,(c,prin) in enumerate(codes,1):
                d=ClaimDiagnosis(practice_id=prac.id, claim_id=clm.id, sequence_number=i, icd10_code=c, is_principal=prin)
                db.add(d); dxs.append(d)
            await db.flush()
            ids.update(dx=[str(d.id) for d in dxs], line=str(line.id), claim=str(clm.id), enc=str(enc.id),
                cov=str(cov.id), pat=str(pat.id), prov=str(prov.id), pay=str(pay.id), prac=str(prac.id))
            await db.commit()
            cid=ids["claim"]

        for ft in ("cms1500","ub04"):
            async with async_session() as db:
                res=await assemble_claim_form(db, cid, ft)
            print(f"\n================= {ft.upper()} =================")
            print("ENRICHMENT:", json.dumps(res["enrichment"]))
            print(f"EDITS ({len(res['edits'])}):")
            for e in res["edits"]:
                print(f"   [{e['severity']}] {e['code']} {e['field']}: {e['message']}")
            print("DIAGNOSES:", json.dumps(res["form"]["diagnoses"]))
            print("SERVICE LINES:", json.dumps(res["form"]["service_lines"]))
            for sec in res["form"]["sections"]:
                print(f"  -- {sec['title']} --")
                for fld in sec["fields"]:
                    if str(fld["value"]).strip():
                        print(f"     {fld['label']}: {fld['value']}")
        print("\n=== VERIFY COMPLETE ===")
    except Exception:
        print("ERR:\n"+traceback.format_exc())
    finally:
        async with async_session() as db:
            if ids["line"]: await db.execute(sqld(ClaimLine).where(ClaimLine.id==ids["line"]))
            for d in (ids["dx"] or []): await db.execute(sqld(ClaimDiagnosis).where(ClaimDiagnosis.id==d))
            for m,k in ((Claim,"claim"),(Encounter,"enc"),(Coverage,"cov"),(Patient,"pat"),(Payer,"pay"),(Provider,"prov"),(Practice,"prac")):
                if ids[k]: await db.execute(sqld(m).where(m.id==ids[k]))
            await db.commit()
        print("CLEANUP done")

if __name__=="__main__":
    asyncio.run(main())
