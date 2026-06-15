#!/usr/bin/env python3
"""
Seed missing LOB mock data using raw SQL (bypasses ORM encryption).
Seeds: CodingSession, PatientStatement, ClientInvoice.
Run inside api container:
  docker compose -f docker-compose.prod.yml exec -e PYTHONPATH=/app api python scripts/seed_extra_lobs.py
"""
import asyncio, uuid, random, json
from datetime import date, datetime, timedelta
import asyncpg
import os

# Build DB URL from env
DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    # Try to load from settings
    import sys; sys.path.insert(0, "/app")
    from src.config import get_settings
    settings = get_settings()
    DATABASE_URL = settings.database_url

# Convert SQLAlchemy URL to asyncpg URL
PG_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://").replace("postgresql://", "postgresql://")

CPT_DESCS = {
    "99213": "Office visit, established patient, moderate complexity",
    "99214": "Office visit, established patient, moderate-high complexity",
    "99215": "Office visit, established patient, high complexity",
    "93000": "Electrocardiogram, routine ECG",
    "71046": "Chest X-ray, 2 views",
    "80053": "Comprehensive metabolic panel",
    "36415": "Venipuncture for blood draw",
    "99232": "Subsequent hospital care",
    "99203": "New patient office visit, low complexity",
    "99204": "New patient office visit, moderate complexity",
    "99205": "New patient office visit, high complexity",
    "99395": "Preventive visit, 18-39 years",
    "99396": "Preventive visit, 40-64 years",
    "96372": "Therapeutic injection",
    "93306": "Echocardiography",
}
CPT_CODES = list(CPT_DESCS.keys())
ICD10_CODES = ["Z00.00","I10","E11.9","M54.5","J06.9","F41.1","K21.0","N39.0","R05.9","G43.909",
               "E78.5","Z23","R10.9","M79.3","J20.9","F32.1","K92.1","N18.3","R51.9","G89.29"]
CODING_STATUSES = ["draft", "in_review", "complete", "complete", "complete", "needs_clarification"]


def utcnow():
    return datetime.utcnow()

def rdate(lo=1, hi=90):
    return date.today() - timedelta(days=random.randint(lo, hi))


async def main():
    print("=== Aethera AI Extra LOB Seeder (raw SQL) ===\n")
    print(f"Connecting to database...")

    conn = await asyncpg.connect(PG_URL)
    print("Connected.\n")

    try:
        # ── Get practice ID — find where the seed data actually lives ─
        # Strategy: pick the practice with the most patients/encounters.
        # Internal admin users have no meaningful practice_id; the real
        # data lives under "Riverside Family Medicine" seeded by seed_mock_data.py.
        practice_row = await conn.fetchrow(
            """SELECT p.id, p.practice_name
               FROM practices p
               LEFT JOIN patients pa ON pa.practice_id = p.id
               GROUP BY p.id, p.practice_name
               ORDER BY COUNT(pa.id) DESC
               LIMIT 1"""
        )
        if not practice_row:
            print("ERROR: No practice found. Run seed_mock_data.py first.")
            return
        practice_id = practice_row["id"]
        practice_name = practice_row["practice_name"]
        print(f"Practice: {practice_name} (id={practice_id})\n")

        # admin_row used later for admin_id
        admin_row = await conn.fetchrow(
            "SELECT id FROM users WHERE email = 'kirkmar078@gmail.com'"
        )

        # ── Get patient IDs (raw, skip decryption) ────────────────────
        patient_rows = await conn.fetch(
            "SELECT id FROM patients WHERE practice_id = $1 LIMIT 50", practice_id
        )
        patient_ids = [str(r["id"]) for r in patient_rows]
        print(f"Found {len(patient_ids)} patients")

        # ── Get encounter IDs ──────────────────────────────────────────
        encounter_rows = await conn.fetch(
            "SELECT id FROM encounters WHERE practice_id = $1 LIMIT 50", practice_id
        )
        encounter_ids = [str(r["id"]) for r in encounter_rows]
        print(f"Found {len(encounter_ids)} encounters")

        # ── Get admin user ID ──────────────────────────────────────────
        if admin_row and admin_row.get("id"):
            admin_id = str(admin_row["id"])
        else:
            ar2 = await conn.fetchrow("SELECT id FROM users WHERE email = 'kirkmar078@gmail.com'")
            admin_id = str(ar2["id"]) if ar2 else None
        print(f"Admin ID: {admin_id}\n")

        # ── 1. Coding Sessions ─────────────────────────────────────────
        existing_coding = await conn.fetchval(
            "SELECT COUNT(*) FROM coding_sessions WHERE practice_id = $1", practice_id
        )
        if existing_coding > 0:
            print(f"[1/3] Coding Sessions: {existing_coding} already exist — skipping.")
        elif not encounter_ids:
            print("[1/3] Coding Sessions: No encounters found — skipping.")
        else:
            print("[1/3] Seeding Coding Sessions...")
            count = 0
            for enc_id in encounter_ids[:25]:
                status = random.choice(CODING_STATUSES)
                cpt_picks = random.sample(CPT_CODES[:10], random.randint(1, 3))
                icd_picks = random.sample(ICD10_CODES[:8], random.randint(1, 3))

                suggested_codes = json.dumps({
                    "cpt": [
                        {
                            "code": c,
                            "description": CPT_DESCS.get(c, "Medical service"),
                            "confidence": round(random.uniform(0.72, 0.99), 2),
                            "modifiers": random.choice([[], ["25"], ["59"]]),
                            "units": random.randint(1, 2),
                        }
                        for c in cpt_picks
                    ],
                    "icd10": [
                        {
                            "code": icd,
                            "description": "Diagnosis code",
                            "confidence": round(random.uniform(0.80, 0.98), 2),
                            "is_primary": j == 0,
                        }
                        for j, icd in enumerate(icd_picks)
                    ],
                })
                final_codes = suggested_codes if status == "complete" else None
                review_started = utcnow() - timedelta(hours=random.randint(1, 72)) if status != "draft" else None
                review_completed = utcnow() - timedelta(minutes=random.randint(5, 120)) if status == "complete" else None
                review_time = random.randint(120, 1800) if status == "complete" else None

                await conn.execute("""
                    INSERT INTO coding_sessions
                        (id, practice_id, encounter_id, coder_id, ai_model_version,
                         processing_time_ms, token_count, suggested_codes, final_codes, status,
                         review_started_at, review_completed_at, review_time_seconds, created_at, updated_at)
                    VALUES
                        ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9::jsonb, $10, $11, $12, $13, $14, $14)
                    ON CONFLICT DO NOTHING
                """,
                    uuid.uuid4(), practice_id, uuid.UUID(enc_id),
                    uuid.UUID(admin_id) if admin_id else None,
                    "gpt-4-turbo",
                    random.randint(800, 3500),
                    random.randint(400, 2000),
                    suggested_codes,
                    final_codes,
                    status,
                    review_started,
                    review_completed,
                    review_time,
                    utcnow(),
                )
                count += 1
            print(f"  {count} coding sessions seeded ✓")

        # ── 2. Patient Statements ─────────────────────────────────────
        existing_stmts = await conn.fetchval(
            "SELECT COUNT(*) FROM patient_statements WHERE practice_id = $1", practice_id
        )
        if existing_stmts > 0:
            print(f"[2/3] Patient Statements: {existing_stmts} already exist — skipping.")
        elif not patient_ids:
            print("[2/3] Patient Statements: No patients found — skipping.")
        else:
            print("[2/3] Seeding Patient Statements...")
            count = 0
            for i, pat_id in enumerate(patient_ids[:30]):
                total_charges = round(random.uniform(150, 2500), 2)
                ins_paid = round(total_charges * random.uniform(0.60, 0.85), 2)
                adjustments = round(total_charges * random.uniform(0.05, 0.15), 2)
                patient_paid_raw = total_charges - ins_paid - adjustments
                patient_paid = round(random.uniform(0, patient_paid_raw * 0.7), 2)
                balance = round(max(patient_paid_raw - patient_paid, 0), 2)

                stmt_status = random.choice(["open","open","open","partial","paid","collections"])
                if stmt_status == "paid":
                    balance = 0.0
                    patient_paid = round(patient_paid_raw, 2)

                stmt_date = rdate(1, 90)
                due_date = stmt_date + timedelta(days=30)

                await conn.execute("""
                    INSERT INTO patient_statements
                        (id, practice_id, patient_id, statement_number, statement_date, due_date,
                         total_charges, total_insurance_paid, total_adjustments,
                         total_patient_paid, balance_due, status, created_at, updated_at)
                    VALUES
                        ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $13)
                    ON CONFLICT (statement_number) DO NOTHING
                """,
                    uuid.uuid4(), practice_id, uuid.UUID(pat_id),
                    f"STMT{80000 + i}",
                    stmt_date, due_date,
                    total_charges, ins_paid, adjustments,
                    patient_paid, balance,
                    stmt_status,
                    utcnow(),
                )
                count += 1
            print(f"  {count} patient statements seeded ✓")

        # ── 3. Client Invoices (Billing) ───────────────────────────────
        existing_invoices = await conn.fetchval(
            "SELECT COUNT(*) FROM client_invoices WHERE practice_id = $1", practice_id
        )
        if existing_invoices > 0:
            print(f"[3/3] Client Invoices: {existing_invoices} already exist — skipping.")
        else:
            print("[3/3] Seeding Client Invoices...")
            count = 0
            for month_offset in range(6):
                # Build period for each of last 6 months
                today = date.today()
                first_of_current = today.replace(day=1)
                period_end_dt = first_of_current - timedelta(days=1) - timedelta(days=30 * month_offset)
                period_end = period_end_dt
                period_start = period_end.replace(day=1)

                collections = round(random.uniform(18000, 95000), 2)
                calculated_fee = round(collections * 0.04, 2)
                total_due = round(calculated_fee + random.uniform(-200, 200), 2)
                inv_status = "paid" if month_offset > 1 else random.choice(["sent","overdue","draft"])

                line_items = json.dumps({
                    "items": [{
                        "description": "RCM Services Fee (4% of collections)",
                        "quantity": 1,
                        "unit_price": calculated_fee,
                        "total": calculated_fee,
                    }]
                })

                paid_at = utcnow() - timedelta(days=random.randint(5, 25)) if inv_status == "paid" else None
                paid_amount = total_due if inv_status == "paid" else None
                payment_method = "ach" if inv_status == "paid" else None

                await conn.execute("""
                    INSERT INTO client_invoices
                        (id, practice_id, invoice_number, billing_period_start, billing_period_end,
                         total_collections, total_claims_submitted, fee_model_used,
                         calculated_fee, minimum_fee_applied, adjustments, total_due,
                         line_items, status, due_date, paid_at, paid_amount, payment_method,
                         created_at, updated_at)
                    VALUES
                        ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13::jsonb, $14, $15, $16, $17, $18, $19, $19)
                    ON CONFLICT (invoice_number) DO NOTHING
                """,
                    uuid.uuid4(), practice_id,
                    f"RFM-2026-{str(6 - month_offset).zfill(3)}",
                    period_start, period_end,
                    collections, random.randint(80, 350),
                    "percentage",
                    calculated_fee, False, 0.0, total_due,
                    line_items,
                    inv_status,
                    period_end + timedelta(days=30),
                    paid_at, paid_amount, payment_method,
                    utcnow(),
                )
                count += 1
            print(f"  {count} client invoices seeded ✓")

    finally:
        await conn.close()

    print("\n=== Extra LOB Seeding Complete! ===")
    print("  CodingSessions, PatientStatements, ClientInvoices done.")


asyncio.run(main())
