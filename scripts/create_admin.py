#!/usr/bin/env python3
"""
Create the default admin user for Aethera AI.
Run inside the api container:
  docker compose -f docker-compose.prod.yml exec -e PYTHONPATH=/app api python scripts/create_admin.py
"""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from src.infrastructure.database.session import async_session
from src.infrastructure.database.models import User
from src.infrastructure.auth.service import AuthService


ADMIN_EMAIL    = "kirkmar078@gmail.com"
ADMIN_PASSWORD = "Mykia@0902"
ADMIN_FIRST    = "Kiran"
ADMIN_LAST     = "Marr"


async def create_admin() -> None:
    auth_service = AuthService()

    async with async_session() as session:
        result = await session.execute(select(User).where(User.email == ADMIN_EMAIL))
        existing = result.scalar_one_or_none()

        if existing:
            # Update password and force change flag on existing account
            existing.password_hash = auth_service.hash_password(ADMIN_PASSWORD)
            existing.must_change_password = True
            existing.is_active = True
            await session.commit()
            print(f"✓ Admin credentials updated: {ADMIN_EMAIL}")
            print("  User will be prompted to change password on next login.")
            return

        now = datetime.now(timezone.utc).replace(tzinfo=None)
        admin = User(
            email=ADMIN_EMAIL,
            password_hash=auth_service.hash_password(ADMIN_PASSWORD),
            first_name=ADMIN_FIRST,
            last_name=ADMIN_LAST,
            user_type="internal",
            internal_role="company_admin",
            is_active=True,
            mfa_enabled=False,
            must_change_password=True,   # Force change on first login
            password_changed_at=now,
            created_at=now,
            updated_at=now,
        )

        session.add(admin)
        await session.commit()

        print(f"✓ Admin user created: {ADMIN_EMAIL}")
        print("  User will be prompted to set a new password on first login.")


if __name__ == "__main__":
    asyncio.run(create_admin())
