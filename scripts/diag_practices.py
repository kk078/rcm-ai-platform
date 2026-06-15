#!/usr/bin/env python3
"""Diagnose which practice has patient/encounter data."""
import asyncio
import asyncpg
import os
import sys

sys.path.insert(0, "/app")
from src.config import get_settings

settings = get_settings()
PG_URL = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")


async def main():
    conn = await asyncpg.connect(PG_URL)
    try:
        print("=== All Practices ===")
        rows = await conn.fetch("SELECT id, practice_name FROM practices")
        for r in rows:
            print(f"  {r['id']} — {r['practice_name']}")

        print("\n=== Patient counts per practice ===")
        rows = await conn.fetch(
            "SELECT practice_id, COUNT(*) as cnt FROM patients GROUP BY practice_id"
        )
        for r in rows:
            print(f"  practice_id={r['practice_id']} → {r['cnt']} patients")

        print("\n=== Encounter counts per practice ===")
        rows = await conn.fetch(
            "SELECT practice_id, COUNT(*) as cnt FROM encounters GROUP BY practice_id"
        )
        for r in rows:
            print(f"  practice_id={r['practice_id']} → {r['cnt']} encounters")

        print("\n=== Claim counts per practice ===")
        rows = await conn.fetch(
            "SELECT practice_id, COUNT(*) as cnt FROM claims GROUP BY practice_id"
        )
        for r in rows:
            print(f"  practice_id={r['practice_id']} → {r['cnt']} claims")

    finally:
        await conn.close()


asyncio.run(main())
