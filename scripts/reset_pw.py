#!/usr/bin/env python3
"""Reset admin password via asyncpg + raw bcrypt."""
import asyncio, sys, os
sys.path.insert(0, '/app')

import asyncpg
import bcrypt

DATABASE_URL = os.environ.get("DATABASE_URL", "")
if not DATABASE_URL:
    from src.config import get_settings
    settings = get_settings()
    DATABASE_URL = settings.database_url

PG_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

async def main():
    conn = await asyncpg.connect(PG_URL)
    try:
        password = 'AetheraisGr8!'
        salt = bcrypt.gensalt(rounds=12)
        new_hash = bcrypt.hashpw(password.encode('utf-8'), salt).decode('utf-8')
        print(f'Generated hash: {new_hash[:30]}...')
        result = await conn.execute(
            "UPDATE users SET password_hash=$1, must_change_password=false WHERE email='kirkmar078@gmail.com'",
            new_hash
        )
        print(f'Update result: {result}')
        row = await conn.fetchrow(
            "SELECT email, must_change_password FROM users WHERE email='kirkmar078@gmail.com'"
        )
        print(f'Verified row: email={row["email"]}, must_change_password={row["must_change_password"]}')
        print('SUCCESS: Password reset to AetheraisGr8!')
    finally:
        await conn.close()

asyncio.run(main())
