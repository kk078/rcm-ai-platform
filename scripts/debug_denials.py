"""
Debug script: Run the denials query directly and show any exception.
Usage: docker compose -f docker-compose.prod.yml exec -T api python scripts/debug_denials.py
"""
import asyncio
import traceback
import uuid
from datetime import date

async def main():
    import sys
    sys.path.insert(0, "/app")

    from sqlalchemy import select, func, and_
    from sqlalchemy.orm import selectinload
    from src.infrastructure.database.session import async_session
    from src.infrastructure.database.models import Denial, Claim, Appeal

    PRACTICE_ID = uuid.UUID("9430a396-1a3f-42a4-bdac-d066c3c16c21")

    async with async_session() as db:
        try:
            print("Step 1: count query...")
            conditions = [Denial.practice_id == PRACTICE_ID]
            total_result = await db.execute(
                select(func.count(Denial.id)).where(and_(*conditions))
            )
            total = total_result.scalar() or 0
            print(f"  total denials: {total}")

            print("Step 2: main denials query...")
            result = await db.execute(
                select(Denial)
                .where(and_(*conditions))
                .order_by(Denial.denial_date.desc())
                .limit(5)
            )
            denials = result.scalars().all()
            print(f"  fetched {len(denials)} denials")

            print("Step 3: iterate denials...")
            today = date.today()
            for i, d in enumerate(denials):
                print(f"  denial {i}: id={d.id}, claim_id={d.claim_id}, status={d.status}")

                print(f"    Step 3a: claim query for claim_id={d.claim_id}...")
                try:
                    claim_q = await db.execute(
                        select(Claim).options(selectinload(Claim.patient)).where(Claim.id == d.claim_id)
                    )
                    claim = claim_q.scalar_one_or_none()
                    if claim:
                        print(f"    claim={claim.claim_number}, patient={claim.patient}")
                        if claim.patient:
                            fn = getattr(claim.patient, 'first_name', '') or ''
                            ln = getattr(claim.patient, 'last_name', '') or ''
                            print(f"    patient name: '{fn} {ln}'")
                    else:
                        print(f"    claim not found")
                except Exception as e:
                    print(f"    CLAIM ERROR: {e}")
                    traceback.print_exc()

                print(f"    Step 3b: appeal query...")
                try:
                    appeal_q = await db.execute(
                        select(Appeal).where(Appeal.denial_id == d.id).order_by(Appeal.created_at.desc())
                    )
                    latest = appeal_q.scalars().first()
                    print(f"    latest appeal: {latest}")
                except Exception as e:
                    print(f"    APPEAL ERROR: {e}")
                    traceback.print_exc()

                print(f"    Step 3c: building response dict...")
                try:
                    days_remaining = None
                    if d.appeal_deadline:
                        dl = d.appeal_deadline.date() if hasattr(d.appeal_deadline, "date") else d.appeal_deadline
                        days_remaining = max(0, (dl - today).days)

                    item = {
                        "id": str(d.id),
                        "claim_number": "",
                        "denial_code": d.reason_code,
                        "denial_reason": d.category or d.reason_code or "",
                        "amount_denied": float(d.denial_amount or 0),
                        "appeal_status": "not_started",
                        "days_remaining": days_remaining,
                    }
                    print(f"    dict OK: {item}")
                except Exception as e:
                    print(f"    DICT ERROR: {e}")
                    traceback.print_exc()

            print("\n=== All steps completed successfully ===")

        except Exception as e:
            print(f"\n=== FATAL ERROR ===")
            print(f"Exception: {type(e).__name__}: {e}")
            traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
