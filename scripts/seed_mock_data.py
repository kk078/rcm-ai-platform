#!/usr/bin/env python3
"""
Aethera AI -- Comprehensive Mock Data Seeder (field-accurate v2)
Run inside api container:
  docker compose -f docker-compose.prod.yml exec -e PYTHONPATH=/app api python scripts/seed_mock_data.py
"""
import asyncio, uuid, random
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select
from src.infrastructure.database.session import async_session
from src.infrastructure.database.models import (
    Practice, Provider, User, Patient, Coverage, Payer,
    Encounter, Claim, ClaimLine, ClaimDiagnosis,
    PaymentBatch, PaymentLine,
    Denial, WorkQueueItem,
    PriorAuthorization, EligibilityCheck,
)

def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)

def rdate(lo=0, hi=120):
    return date.today() - timedelta(days=random.randint(lo, hi))

def rf(lo=50.0, hi=5000.0):
    return round(random.uniform(lo, hi), 2)

ICD10 = ["Z00.00","I10","E11.9","M54.5","J06.9","F41.1","K21.0","N39.0","R05.9","G43.909",
         "E78.5","Z23","R10.9","M79.3","J20.9","F32.1","K92.1","N18.3","R51.9","G89.29"]
CPT   = ["99213","99214","99215","93000","71046","80053","36415","99232","43239","27447",
         "99203","99204","99205","99395","99396","96372","93306","70553","27130","90837"]
FN = ["James","Maria","Robert","Patricia","Michael","Jennifer","William","Linda","David","Barbara",
      "Richard","Susan","Joseph","Jessica","Thomas","Sarah","Charles","Karen","Christopher","Lisa",
      "Kevin","Nancy","Brian","Betty","George","Helen","Edward","Dorothy","Ronald","Frances"]
LN = ["Smith","Johnson","Williams","Brown","Jones","Garcia","Miller","Davis","Rodriguez","Martinez",
      "Hernandez","Lopez","Gonzalez","Wilson","Anderson","Taylor","Thomas","Moore","Jackson","White",
      "Harris","Martin","Thompson","Robinson","Clark","Lewis","Lee","Walker","Hall","Allen"]
PAYERS = [
    ("United Healthcare","87726","commercial"),
    ("Aetna","60054","commercial"),
    ("BlueCross BlueShield","00050","commercial"),
    ("Cigna","62308","commercial"),
    ("Medicare","00001","medicare"),
    ("Medicaid","00002","medicaid"),
    ("Humana","61101","commercial"),
    ("Anthem","00031","commercial"),
]
CLAIM_STATUSES = ["draft","ready","submitted","accepted","rejected","paid","partial_paid","denied","appealed","closed"]
CARC_CODES = [
    ("CO-4","Inconsistent with modifier","coding"),
    ("CO-11","Diagnosis inconsistent with procedure","coding"),
    ("CO-97","Global period denial","bundling"),
    ("CO-50","Non-covered service","coverage"),
    ("CO-16","Missing required info","administrative"),
    ("CO-167","Age inconsistent with diagnosis","clinical"),
    ("PR-1","Deductible","patient_responsibility"),
    ("CO-197","Precertification required","authorization"),
]

async def main():
    async with async_session() as db:
        print("=== Aethera AI Mock Data Seeder v2 ===\n")

        # Admin user
        r = await db.execute(select(User).where(User.email=="kirkmar078@gmail.com"))
        admin = r.scalar_one_or_none()
        if not admin:
            print("ERROR: Admin user not found."); return
        print(f"Admin: {admin.first_name} {admin.last_name} (id={admin.id})")

        # ── 1. Payers ──────────────────────────────────────────────────
        print("\n[1/10] Payers...")
        payer_objs = []
        for name, pid, pt in PAYERS:
            r = await db.execute(select(Payer).where(Payer.payer_id_number==pid))
            p = r.scalar_one_or_none()
            if not p:
                p = Payer(payer_name=name, payer_id_number=pid, payer_type=pt,
                          timely_filing_days=180, appeal_filing_days=60,
                          electronic_payer=True, era_enrolled=(pt=="medicare"), is_active=True)
                db.add(p)
            payer_objs.append(p)
        await db.flush()
        print(f"  {len(payer_objs)} payers")

        # ── 2. Practice ────────────────────────────────────────────────
        print("\n[2/10] Practice...")
        r = await db.execute(select(Practice).where(Practice.practice_name=="Riverside Family Medicine"))
        practice = r.scalar_one_or_none()
        if not practice:
            practice = Practice(
                practice_name="Riverside Family Medicine",
                legal_name="Riverside Family Medicine LLC",
                tin="12-3456789", group_npi="1234567890",
                specialty_primary="Family Medicine",
                address_line_1="500 Medical Plaza Dr", city="Austin",
                state="TX", zip_code="78701", phone="512-555-0100",
                email="billing@riverside-med.com", contact_name="Jane Doe",
                status="active", intake_method="portal", timezone="America/Chicago",
                created_by=admin.id,
            )
            db.add(practice); await db.flush()
        print(f"  {practice.practice_name} id={practice.id}")

        # ── 3. Providers ───────────────────────────────────────────────
        print("\n[3/10] Providers...")
        prov_data = [
            ("1111111111","Sarah","Johnson","MD","Family Medicine"),
            ("2222222222","Michael","Chen","DO","Internal Medicine"),
            ("3333333333","Emily","Roberts","NP","Family Medicine"),
            ("4444444444","David","Kim","MD","Cardiology"),
        ]
        prov_objs = []
        for npi, fn, ln, cred, spec in prov_data:
            r = await db.execute(select(Provider).where(Provider.npi==npi))
            p = r.scalar_one_or_none()
            if not p:
                p = Provider(npi=npi, first_name=fn, last_name=ln, credential=cred,
                             specialty=spec, is_active=True, is_individual=True)
                db.add(p)
            prov_objs.append(p)
        await db.flush()
        print(f"  {len(prov_objs)} providers")

        # ── 4. Patients + Coverage ─────────────────────────────────────
        print("\n[4/10] Patients + Coverage...")
        pat_objs, cov_map = [], {}   # cov_map: patient_id -> coverage
        for i in range(50):
            mrn = f"RFM{20000+i}"
            r = await db.execute(select(Patient).where(Patient.mrn==mrn))
            pat = r.scalar_one_or_none()
            if not pat:
                dob = date(random.randint(1940,2005), random.randint(1,12), random.randint(1,28))
                pat = Patient(
                    practice_id=practice.id, mrn=mrn,
                    first_name=random.choice(FN), last_name=random.choice(LN),
                    date_of_birth=dob, gender=random.choice(["m","f"]),
                    phone=f"512-555-{2000+i:04d}",
                    email=f"patient{i}@example.com", is_active=True,
                )
                db.add(pat); await db.flush()
                payer = random.choice(payer_objs)
                cov = Coverage(
                    practice_id=practice.id, patient_id=pat.id, payer_id=payer.id,
                    member_id=f"MBR{100000+i}", group_number=f"GRP{5000+i}",
                    plan_name=f"{payer.payer_name} PPO",
                    plan_type=random.choice(["PPO","HMO","POS","EPO"]),
                    coverage_type="primary", subscriber_relation="self",
                    effective_date=date(2024,1,1), termination_date=date(2026,12,31),
                    copay_amount=float(random.choice([20,30,40,50])),
                    deductible_amount=float(random.choice([500,1000,1500,2000,3000])),
                    deductible_met=float(random.randint(0,1500)),
                    coinsurance_pct=float(random.choice([10,20,30])),
                    is_active=True,
                )
                db.add(cov); await db.flush()
                cov_map[pat.id] = cov
            pat_objs.append(pat)
        await db.flush()
        print(f"  {len(pat_objs)} patients, {len(cov_map)} coverages")

        # ── 5. Encounters + Claims + Lines + Diagnoses ─────────────────
        print("\n[5/10] Encounters, Claims, Claim Lines...")
        claim_objs = []
        for i in range(100):
            pat = random.choice(pat_objs)
            prov = random.choice(prov_objs)
            cov = cov_map.get(pat.id)
            if not cov:
                continue
            svc = rdate(0, 150)
            enc = Encounter(
                practice_id=practice.id, patient_id=pat.id,
                provider_id=prov.id, encounter_type="office",
                encounter_date=svc, place_of_service="11",
                status=random.choice(["open","billed","closed"]),
                notes=f"Visit for {random.choice(['checkup','follow-up','acute visit','annual wellness'])}",
            )
            db.add(enc); await db.flush()

            # Claim
            status = random.choice(CLAIM_STATUSES)
            num_lines = random.randint(1, 4)
            total_charge = 0.0
            line_data = []
            for ln_i in range(num_lines):
                charge = rf(80, 600)
                total_charge += charge
                line_data.append((CPT[random.randint(0, len(CPT)-1)], charge))

            total_paid   = round(total_charge * 0.72, 2) if status in ("paid",) else \
                           round(total_charge * 0.35, 2) if status == "partial_paid" else 0.0
            total_adj    = round(total_charge * 0.08, 2) if status in ("paid","partial_paid") else 0.0
            pat_resp     = round(total_charge * 0.20, 2) if status in ("paid","partial_paid") else 0.0

            claim = Claim(
                practice_id=practice.id,
                claim_number=f"CLM{30000+i}",
                encounter_id=enc.id, patient_id=pat.id,
                payer_id=cov.payer_id, coverage_id=cov.id,
                rendering_provider=prov.id, billing_provider=prov.id,
                claim_type="837P",
                total_charge=round(total_charge, 2),
                total_paid=total_paid, total_adjusted=total_adj,
                patient_responsibility=pat_resp,
                status=status,
                submission_date=datetime.now()-timedelta(days=random.randint(1,90)) if status != "draft" else None,
                timely_filing_deadline=svc + timedelta(days=180),
                created_by=admin.id,
            )
            db.add(claim); await db.flush()

            # Diagnoses
            dx_codes = random.sample(ICD10, random.randint(1,3))
            for seq, code in enumerate(dx_codes, 1):
                db.add(ClaimDiagnosis(
                    practice_id=practice.id, claim_id=claim.id,
                    sequence_number=seq, icd10_code=code,
                    is_principal=(seq==1),
                ))

            # Lines
            for ln_i, (cpt, charge) in enumerate(line_data, 1):
                paid = round(charge * 0.72, 2) if status == "paid" else \
                       round(charge * 0.35, 2) if status == "partial_paid" else 0.0
                db.add(ClaimLine(
                    practice_id=practice.id, claim_id=claim.id,
                    line_number=ln_i, cpt_code=cpt,
                    icd_pointer_1=dx_codes[0] if dx_codes else None,
                    modifier_1=random.choice([None,None,"25","59","GT"]),
                    units=1.0, charge_amount=charge,
                    paid_amount=paid,
                    allowed_amount=round(charge*0.80,2) if status in ("paid","partial_paid") else None,
                    service_date_from=svc, place_of_service="11",
                    status="active",
                ))
            claim_objs.append(claim)
        await db.flush()
        print(f"  {len(claim_objs)} claims, {sum(1 for c in claim_objs if c.status=='paid')} paid, "
              f"{sum(1 for c in claim_objs if c.status=='denied')} denied")

        # ── 6. Payment Batches + Lines ─────────────────────────────────
        print("\n[6/10] ERA Payment Batches...")
        paid_claims = [c for c in claim_objs if c.status in ("paid","partial_paid")]
        batch_count = 0
        for i, claim in enumerate(paid_claims[:35]):
            batch = PaymentBatch(
                practice_id=practice.id, payer_id=claim.payer_id,
                check_number=f"CHK{50000+i}", eft_trace=f"EFT{60000+i}",
                payment_method=random.choice(["eft","check","virtual_card"]),
                total_paid=float(claim.total_paid),
                total_claims=1,
                production_date=date.today() - timedelta(days=random.randint(1,30)),
                deposit_date=date.today() - timedelta(days=random.randint(0,5)),
                status=random.choice(["posted","received","partial"]),
                auto_posted=random.random()>0.5,
            )
            db.add(batch); await db.flush()
            db.add(PaymentLine(
                practice_id=practice.id, batch_id=batch.id,
                claim_id=claim.id, patient_id=claim.patient_id,
                claim_number_reported=claim.claim_number,
                service_date=date.today() - timedelta(days=30),
                billed_amount=float(claim.total_charge),
                allowed_amount=float(claim.total_charge)*0.80,
                paid_amount=float(claim.total_paid),
                patient_responsibility=float(claim.patient_responsibility),
                match_status="matched",
                match_confidence=0.98,
                is_underpaid=float(claim.total_paid) < float(claim.total_charge)*0.70,
            ))
            batch_count += 1
        await db.flush()
        print(f"  {batch_count} payment batches posted")

        # ── 7. Denials ─────────────────────────────────────────────────
        print("\n[7/10] Denials...")
        denied = [c for c in claim_objs if c.status in ("denied","rejected","appealed")]
        denial_count = 0
        for i, claim in enumerate(denied[:25]):
            code, reason, cat = random.choice(CARC_CODES)
            db.add(Denial(
                practice_id=practice.id, claim_id=claim.id,
                payer_id=claim.payer_id,
                denial_date=date.today() - timedelta(days=random.randint(0,45)),
                reason_code=code,
                remark_codes=["N130","MA04"] if random.random()>0.5 else None,
                denial_amount=float(claim.total_charge),
                category=cat, subcategory=code,
                root_cause=reason,
                priority_score=round(random.uniform(0.3,1.0), 4),
                recovery_probability=round(random.uniform(0.4,0.95), 4),
                status=random.choice(["new","working","appealed","closed"]),
                assigned_to=admin.id,
                appeal_deadline=date.today() + timedelta(days=random.randint(5,55)),
                timely_filing_deadline=date.today() + timedelta(days=random.randint(30,120)),
            ))
            denial_count += 1
        await db.flush()
        print(f"  {denial_count} denials")

        # ── 8. Prior Authorizations ────────────────────────────────────
        print("\n[8/10] Prior Authorizations...")
        for i in range(20):
            pat = random.choice(pat_objs)
            cov = cov_map.get(pat.id)
            valid_from = date.today() - timedelta(days=random.randint(0,60))
            db.add(PriorAuthorization(
                practice_id=practice.id, patient_id=pat.id,
                coverage_id=cov.id if cov else None,
                payer_id=random.choice(payer_objs).id,
                procedure_codes=random.sample(CPT[:8], random.randint(1,2)),
                diagnosis_codes=random.sample(ICD10[:6], 1),
                auth_number=f"AUTH{70000+i}" if random.random()>0.3 else None,
                status=random.choice(["pending","approved","denied","expired","submitted"]),
                requested_date=valid_from - timedelta(days=5),
                approved_date=valid_from if random.random()>0.4 else None,
                valid_from=valid_from, valid_to=valid_from+timedelta(days=90),
                approved_visits=random.choice([6,12,24,None]),
                approved_units=random.choice([None,10,20]),
                notes="Medical necessity documented in clinical notes.",
            ))
        await db.flush()
        print("  20 prior authorizations")

        # ── 9. Eligibility Checks ──────────────────────────────────────
        print("\n[9/10] Eligibility Checks...")
        for i in range(30):
            pat = random.choice(pat_objs)
            cov = cov_map.get(pat.id)
            db.add(EligibilityCheck(
                practice_id=practice.id, patient_id=pat.id,
                coverage_id=cov.id if cov else None,
                payer_id=random.choice(payer_objs).id,
                status=random.choice(["active","inactive","pending","error"]),
                is_active=random.random()>0.2,
                plan_name=f"Plan {random.randint(100,999)}",
                group_number=f"GRP{random.randint(1000,9999)}",
                network_status=random.choice(["in-network","out-of-network","unknown"]),
                deductible_total=float(random.choice([1000,1500,2000,3000])),
                deductible_met=float(random.randint(0,1500)),
                oop_total=6000.0,
                oop_met=float(random.randint(0,3000)),
                copay=float(random.choice([20,30,40,50])),
                coinsurance_pct=random.choice([10,20,30]),
                check_date=utcnow() - timedelta(days=random.randint(0,14)),
                service_date=date.today(),
            ))
        await db.flush()
        print("  30 eligibility checks")

        # ── 10. Work Queue Items ───────────────────────────────────────
        print("\n[10/10] Work Queue Items...")
        queue_types = ["intake","coding","billing","posting","denial","follow_up"]
        item_types  = ["claim","denial","charge_entry","coding_session","payment_batch"]
        for i in range(30):
            claim = random.choice(claim_objs)
            qt = random.choice(queue_types)
            db.add(WorkQueueItem(
                practice_id=practice.id,
                queue_type=qt,
                item_type="claim",
                item_id=claim.id,
                priority=random.randint(10, 90),
                assigned_to=admin.id,
                status=random.choice(["pending","in_progress","completed","escalated"]),
                due_date=utcnow() + timedelta(days=random.randint(1,14)),
                sla_breached=random.random()<0.15,
            ))
        await db.flush()
        await db.commit()
        print("  30 work queue items")

        print("\n" + "="*50)
        print("SEEDING COMPLETE!")
        print(f"  Practice:    Riverside Family Medicine")
        print(f"  Providers:   {len(prov_objs)}")
        print(f"  Patients:    {len(pat_objs)}")
        print(f"  Claims:      {len(claim_objs)}")
        print(f"  Payers:      {len(payer_objs)}")
        print(f"  Payments:    {batch_count}")
        print(f"  Denials:     {denial_count}")
        print("="*50)

asyncio.run(main())
