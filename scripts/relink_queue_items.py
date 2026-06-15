"""Re-link work queue item_ids to real claims in the database."""
import asyncio, sys, random
sys.path.insert(0, '/app')
from src.infrastructure.database.session import async_session
from src.infrastructure.database.models import WorkQueueItem, Claim
from sqlalchemy import select

async def main():
    async with async_session() as db:
        # Get all claims
        claims_q = await db.execute(select(Claim))
        claims = claims_q.scalars().all()
        if not claims:
            print("No claims found!")
            return
        print(f"Found {len(claims)} claims")

        # Get all work queue items
        wq_q = await db.execute(select(WorkQueueItem))
        items = wq_q.scalars().all()
        print(f"Found {len(items)} queue items")

        updated = 0
        for item in items:
            # Assign a random claim's id and practice_id
            claim = random.choice(claims)
            item.item_id = claim.id
            item.item_type = "claim"
            if claim.practice_id:
                item.practice_id = claim.practice_id
            updated += 1

        await db.commit()
        print(f"Re-linked {updated} queue items to real claims.")

asyncio.run(main())
