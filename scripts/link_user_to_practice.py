#!/usr/bin/env python3
"""
Links kirkmar078@gmail.com to the Riverside Family Medicine practice
so the provider portal shows live data scoped to that practice.
"""
import asyncio
import os
import sys

sys.path.insert(0, '/app')

import asyncpg

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    from src.config import get_settings
    settings = get_settings()
    DATABASE_URL = settings.database_url

PG_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

USER_EMAIL = "kirkmar078@gmail.com"
PRACTICE_NAME = "Riverside Family Medicine"


async def main():
    conn = await asyncpg.connect(PG_URL)
    try:
        # Find the practice
        practice = await conn.fetchrow(
            "SELECT id, practice_name FROM practices WHERE practice_name = $1",
            PRACTICE_NAME,
        )
        if not practice:
            # Fall back to any practice
            practice = await conn.fetchrow(
                "SELECT id, practice_name FROM practices ORDER BY created_at LIMIT 1"
            )
        if not practice:
            print("ERROR: No practices found in database. Run seed_mock_data.py first.")
            return

        practice_id = practice["id"]
        practice_name = practice["practice_name"]
        print(f"Found practice: {practice_name}  id={practice_id}")

        # Link user to practice
        result = await conn.execute(
            "UPDATE users SET practice_id = $1 WHERE email = $2",
            practice_id,
            USER_EMAIL,
        )
        print(f"Update result: {result}")

        # Verify
        row = await conn.fetchrow(
            "SELECT email, practice_id FROM users WHERE email = $1",
            USER_EMAIL,
        )
        if row and str(row["practice_id"]) == str(practice_id):
            print(f"SUCCESS: {USER_EMAIL} is now linked to '{practice_name}' ({practice_id})")
            print("")
            print("ACTION REQUIRED: Log out of the provider portal and log back in")
            print("to get a new JWT that includes the practice_id.")
        else:
            print(f"ERROR: Update may have failed. Row: {row}")

    finally:
        await conn.close()


asyncio.run(main())
