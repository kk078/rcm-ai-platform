#!/usr/bin/env python3
"""Seed ONE persistent ZZCFRM claim (GERMAN note) and print CLAIM_ID. No cleanup."""
import asyncio
from datetime import datetime, timezone, date
from src.infrastructure.database.session import async_session
from src.infrastructure.database.models import (Practice, Provider, Patient, Payer, Coverage, Encounter, Claim, ClaimLine, ClaimDiagnosis)
TAG="ZZCFRM"
def now(): return datetime.now(timezone.utc).replace(tzinfo=None)
async def main():
    async with async_session() as db:
        n=now()
        prac=Practice(practice_name="Gulf Coast Internist LLC", legal_name="Gulf Coast Internist LLC", tin="59-1234567",
            specialty_primary="Internal Medicine", status="active", address_line_1="4957 38th Ave N", address_line_2="Suite C",
            city="Saint Petersburg", state="FL", zip_code="33710", phone="727-525-0900", timezone="America/New_York",
            intake_method="portal", created_at=n, updated_at=n); db.add(prac); await db.flush()
        prov=Provider(npi="1083684153", first_name="KAVITA", last_name="RAO", is_individual=True, is_active=True, created_at=n, updated_at=n); db.add(prov); await db.flush()
        pat=Patient(practice_id=prac.id, mrn=f"{TAG}-21844", first_name="CYNTHIA", last_name="GERMAN", date_of_birth=date(1959,9,15),
            gender="F", address_line_1="5816 44TH AVE N", city="Saint Petersburg", state="FL", zip_code="33709", phone="727-641-6120",
            is_active=True, created_at=n, updated_at=n); db.add(pat); await db.flush()
        pay=Payer(payer_name="Medicare", payer_id_number="SMFL0", payer_type="Medicare", timely_filing_days=365, appeal_filing_days=120,
            electronic_payer=True, era_enrolled=True, eft_enrolled=True, is_active=True, created_at=n, updated_at=n); db.add(pay); await db.flush()
        cov=Coverage(practice_id=prac.id, patient_id=pat.id, payer_id=pay.id, member_id="1EG4TE5MK72", coverage_type="primary",
            plan_name="Medicare Part B", plan_type="MB", effective_date=date(2021,1,1), is_active=True, created_at=n, updated_at=n); db.add(cov); await db.flush()
        enc=Encounter(practice_id=prac.id, patient_id=pat.id, provider_id=prov.id, encounter_type="office_visit",
            encounter_date=date(2021,3,24), place_of_service="11", status="complete", created_at=n, updated_at=n); db.add(enc); await db.flush()
        clm=Claim(practice_id=prac.id, claim_number=f"{TAG}-CLM1", encounter_id=enc.id, patient_id=pat.id, payer_id=pay.id,
            coverage_id=cov.id, rendering_provider=prov.id, billing_provider=prov.id, claim_type="837P", frequency_code="1",
            total_charge=175.0, total_paid=0.0, total_adjusted=0.0, patient_responsibility=0.0, status="ready", created_at=n, updated_at=n); db.add(clm); await db.flush()
        db.add(ClaimLine(practice_id=prac.id, claim_id=clm.id, line_number=1, cpt_code="99214", icd_pointer_1="1", icd_pointer_2="2",
            units=1.0, charge_amount=175.0, paid_amount=0.0, service_date_from=date(2021,3,24), place_of_service="11", status="ready"))
        for i,(c,prin) in enumerate([("G97.1",True),("F33.1",False),("E78.2",False),("I10",False)],1):
            db.add(ClaimDiagnosis(practice_id=prac.id, claim_id=clm.id, sequence_number=i, icd10_code=c, is_principal=prin))
        await db.commit()
        print(f"CLAIM_ID={clm.id}")
asyncio.run(main())
