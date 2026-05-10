#!/usr/bin/env python3
"""Create the default admin user for MedClaim AI."""

import asyncio
from datetime import datetime, timezone

from sqlalchemy import select
from src.infrastructure.database.session import async_session
from src.infrastructure.database.models import User
from src.infrastructure.auth.service import AuthService


ADMIN_EMAIL = "admin@aetheraonline.com"
ADMIN_PASSWORD = "MedClaimAdmin2026!"


async def create_admin() -> None:
    auth_service = AuthService()

    async with async_session() as session:
        # Check if admin already exists
        result = await session.execute(select(User).where(User.email == ADMIN_EMAIL))
        existing = result.scalar_one_or_none()

        if existing:
            print(f"Admin user already exists: {ADMIN_EMAIL}")
            return

        # Create admin user
        now = datetime.now(timezone.utc).replace(tzinfo=None)  # naive UTC for PG TIMESTAMP columns
        admin = User(
            email=ADMIN_EMAIL,
            password_hash=auth_service.hash_password(ADMIN_PASSWORD),
            first_name="Admin",
            last_name="User",
            user_type="internal",
            internal_role="company_admin",
            is_active=True,
            mfa_enabled=False,
            password_changed_at=now,
            created_at=now,
            updated_at=now,
        )

        session.add(admin)
        await session.commit()

        print(f"Admin user created: {ADMIN_EMAIL}")
        print("IMPORTANT: Change the password after first login!")


if __name__ == "__main__":
    asyncio.run(create_admin())