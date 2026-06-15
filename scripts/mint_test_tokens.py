#!/usr/bin/env python3
"""Mint short-lived access tokens for the existing admin + provider users.

For internal QA only — does NOT change passwords or create data.
Run: podman exec -e PYTHONPATH=/app rcm-ai-platform-api-1 python scripts/mint_test_tokens.py
"""
import asyncio
from sqlalchemy import select
from src.infrastructure.database.session import async_session
from src.infrastructure.database.models import User
from src.infrastructure.auth.jwt_handler import create_access_token
from src.infrastructure.auth.schemas import TokenData


async def main():
    async with async_session() as s:
        for label, email in (("ADMIN", "kirkmar078@gmail.com"),
                             ("PROVIDER", "kirkmar078+provider@gmail.com")):
            u = (await s.execute(select(User).where(User.email == email))).scalar_one_or_none()
            if not u:
                print(f"{label}=MISSING")
                continue
            td = TokenData(
                user_id=u.id, email=u.email, user_type=u.user_type,
                practice_id=u.practice_id, internal_role=u.internal_role,
                provider_role=u.provider_role,
            )
            print(f"{label}={create_access_token(td)}")


if __name__ == "__main__":
    asyncio.run(main())
